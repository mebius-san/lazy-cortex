#!/usr/bin/env python3

"""
Community-plugin installer for the lazycortex-obsidian plugin.

Installs or updates one Obsidian community plugin into a vault's config directory, either from the community
registry or from a bundle this plugin ships. Backs the `plugin-install` verb, which carries the mechanical steps
of the `lazy-obsidian.update-plugin` skill.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import vault_manifest  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import plugin_json  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from iconize_sync import IconizeError, find_vault, version_sort_key  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from vault_keys import (  # pylint: disable=import-error
  BundleKey, BundleSourceKind, Encoding, PluginKey, VaultPath,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The override document every plugin's opinionated settings block lives in, under the template root
PLUGIN_SETTINGS = "plugin-settings.json"

# The two bundle files that must land together, and the suffix each is parked under meanwhile
REQUIRED_FILES = (VaultPath.PLUGIN_MANIFEST, VaultPath.PLUGIN_MAIN)
BACKUP_SUFFIX = ".bak"

# Every file a bundle write may touch, each parked and restored as one set
BUNDLE_FILES = (*REQUIRED_FILES, VaultPath.PLUGIN_STYLES)

# Binary outcomes
BINARY_CREATED, BINARY_UNCHANGED, BINARY_VAULT_NEWER = "created", "unchanged", "vault-newer"
BINARY_UPDATED = "updated-{old}-to-{new}"

# The merge outcome that means the override block changes the data file
OVERRIDES_APPLIED = "overrides-applied"

# Registration outcomes
COMMUNITY_CREATED, COMMUNITY_ADDED, COMMUNITY_PRESENT = "created", "added", "present"

# Refusal reasons, worded as the update-plugin skill's failure modes name them
UNSAFE_ID_REASON = "`{pid}` is not a plain plugin id; nothing written."
CATALOG_UNAVAILABLE_REASON = "Could not fetch Obsidian community registry. Check network and retry."
NOT_IN_CATALOG_REASON = (
  "`{pid}` not in the Obsidian community registry. Check the id spelling or pass `--bundled` if it's a "
  "plugin shipped by this LazyCortex plugin."
)
FETCH_FAILED_REASON = "Could not fetch latest release manifest for `{pid}` from `{repo}` ({error}). Retry."
NOT_BUNDLED_REASON = (
  "`{pid}` is not bundled in `templates/obsidian/plugins/`. Remove `--bundled` to resolve from the "
  "community registry instead."
)
COMMUNITY_NOT_ARRAY_REASON = "`{path}` is not a JSON array; cannot register `{pid}` safely."
OVERRIDES_INVALID_REASON = "Cannot merge overrides for `{pid}`: {error}"
WRITE_FAILED_REASON = "Could not install `{pid}` binaries ({error}); the vault plugin was restored from backup."

# Warnings
FROM_CACHE_WARNING = "`{pid}`: upstream unavailable ({error}); installed the cached bundle"
VAULT_NEWER_WARNING = "`{pid}`: vault has {vault}, newer than the source's {source}; binaries left as they are"
SECRET_WARNING = "`{pid}`: data.json holds credential-like values ({paths}) in objects the override block touches"

# CLI statuses and exit code of a refused run
STATUS_INSTALLED, STATUS_REFUSED = "installed", "refused"
EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class PluginInstallRefusedError(Exception):
  """
  Refusal to install a plugin, raised before the vault is changed.

  A refusal carries a one-line reason a caller can report as is. Failures during the bundle write are also
  reported this way, after the previous bundle files have been restored.

  Attributes:
    reason: One-line explanation of the refusal.
  """

  def __init__(self, reason: str) -> None:
    """
    Create a refusal carrying a reportable reason.

    Args:
      reason: One-line explanation of the refusal.
    """
    super().__init__(reason)

    # The one-line reason the caller reports
    self.reason: str = reason


@dataclass
class InstallResult:
  """
  Outcome of one plugin installation, real or dry-run.

  A dry run reports the same outcomes a real run would produce, with no touched paths.

  Attributes:
    binary: Outcome for the bundle files: created, unchanged, vault-newer, or updated with both versions.
    overrides: Outcome of merging the override block into the plugin's settings file.
    community: Outcome of registering the plugin id in the community plugin list.
    warnings: Non-fatal notices for the caller to report.
    touched_paths: Vault-relative paths written by the run.
  """

  # The bundle-file outcome
  binary: str
  # The override-merge outcome
  overrides: str
  # The community-registration outcome
  community: str
  # Non-fatal notices for the caller
  warnings: list[str] = field(default_factory = list)
  # Vault-relative paths the run wrote
  touched_paths: list[str] = field(default_factory = list)


@dataclass
class _Source:
  """
  Resolved origin of the bundle to install.

  Attributes:
    version: Version the source declares, or an empty string when none.
    bundled_dir: Directory of the shipped bundle in bundled mode.
    resolved: Resolved registry bundle envelope in registry mode.
  """

  # The version the source declares
  version: str
  # The shipped bundle directory, bundled mode only
  bundled_dir: Path | None
  # The resolved registry envelope, registry mode only
  resolved: dict | None  # waiver: mixed bytes/str bundle envelope


# ----------------------------------------------------------------------------------------
def _resolve_source(plugin_id: str, *, bundled: bool, dry_run: bool, warnings: list[str]) -> _Source:
  """
  Locate the bundle to install for a plugin id.

  Args:
    plugin_id: Plugin id to resolve.
    bundled: Whether to use the bundle this plugin ships instead of the community registry.
    dry_run: Whether the run must leave the catalog and bundle caches untouched.
    warnings: List that receives a notice when the cached bundle was used because upstream was unavailable.

  Returns:
    The source describing where the bundle and its version come from.

  Raises:
    PluginInstallRefusedError: If the id is not shipped (bundled mode), or neither upstream nor the cache can serve
      the bundle — named as an unreachable registry, an id the registry does not know, or a failed fetch.
  """
  # bundled mode copies what this plugin ships, with no network at all
  if bundled:
    directory = vault_manifest.template_root() / VaultPath.PLUGINS / plugin_id

    # guard: only a plugin this plugin really ships can be installed bundled
    if not directory.is_dir():
      raise PluginInstallRefusedError(NOT_BUNDLED_REASON.format(pid = plugin_id))

    # the shipped manifest names the version the bundle carries
    manifest = vault_manifest.load_json(directory / VaultPath.PLUGIN_MANIFEST)
    version = manifest.get(PluginKey.VERSION) if isinstance(manifest, dict) else None
    return _Source(version = version if isinstance(version, str) else "", bundled_dir = directory, resolved = None)

  # registry mode resolves the bundle exactly as the deploy path does, cached bundle fallback included
  catalog = vault_manifest.fetch_community_catalog(write_cache = not dry_run)
  repo = vault_manifest.resolve_plugin_repo(plugin_id, catalog)
  resolved = vault_manifest.fetch_bundle(plugin_id, repo, write_cache = not dry_run)

  # guard: neither upstream nor the cache could serve the bundle; the refusal names the first missing link
  if resolved[BundleKey.SOURCE] == BundleSourceKind.NONE:
    # an unreadable catalog is a network failure, not a misspelt id
    if not catalog:
      raise PluginInstallRefusedError(CATALOG_UNAVAILABLE_REASON)
    if plugin_id not in catalog:
      raise PluginInstallRefusedError(NOT_IN_CATALOG_REASON.format(pid = plugin_id))
    raise PluginInstallRefusedError(
      FETCH_FAILED_REASON.format(pid = plugin_id, repo = repo, error = resolved[BundleKey.ERROR]))

  # a bundle served from the cache because upstream failed is reported, then used
  if resolved[BundleKey.ERROR]:
    warnings.append(FROM_CACHE_WARNING.format(pid = plugin_id, error = resolved[BundleKey.ERROR]))
  return _Source(version = resolved[BundleKey.VERSION], bundled_dir = None, resolved = resolved)


def _read_vault_version(plugin_dir: Path) -> str:
  """
  Read the version of the plugin currently installed in the vault.

  Args:
    plugin_dir: Per-plugin directory inside the vault.

  Returns:
    The installed version, or an empty string when the plugin is absent or declares none.
  """
  manifest = vault_manifest.load_json(plugin_dir / VaultPath.PLUGIN_MANIFEST)
  version = manifest.get(PluginKey.VERSION) if isinstance(manifest, dict) else None
  return version if isinstance(version, str) else ""


def _decide(vault_version: str, source_version: str) -> str:
  """
  Decide what happens to the bundle files given both versions.

  Versions compare numerically, so a vault ahead of its source is left alone.

  Args:
    vault_version: Installed version, or an empty string when absent.
    source_version: Version the source declares.

  Returns:
    The binary outcome: created, unchanged, vault-newer, or updated with both versions.
  """

  # Domain(obsidian.plugin-bundling):
  # # Plugin update decision
  # A plugin absent from the vault is a fresh install. A plugin already at the source's version string needs no copy.
  # Otherwise the two versions are compared numerically per dotted component, with a component that has no digits
  # counting as 0, so a longer number outranks a shorter one rather than sorting as text.
  # A vault that is ahead of its source is never downgraded: the installed copy is left alone.
  # Versions whose numeric keys are equal but spelled differently are not the same version and still update.

  # an absent plugin is a fresh install
  if not vault_version:
    return BINARY_CREATED

  # the same version needs no copy
  if vault_version == source_version:
    return BINARY_UNCHANGED

  # a vault ahead of its source is left alone; equal keys with different spellings still update
  if version_sort_key(vault_version) > version_sort_key(source_version):
    return BINARY_VAULT_NEWER
  return BINARY_UPDATED.format(old = vault_version, new = source_version)


def _read_community(path: Path, plugin_id: str) -> list | None:  # waiver: Obsidian config JSON
  """
  Read the vault's list of registered community plugin ids.

  Args:
    path: Community plugin list file inside the vault.
    plugin_id: Plugin id being installed, named in the refusal.

  Returns:
    The registered entries, or None when the file does not exist yet.

  Raises:
    PluginInstallRefusedError: If the file exists but does not hold a JSON array.
  """
  # guard: an absent file is created on registration
  if not path.exists():
    return None

  # an unreadable or unparseable file is treated as not holding an array
  try:
    data = json.loads(path.read_text(encoding = Encoding.UTF8))
  except (OSError, ValueError):
    data = None

  # guard: anything but an array cannot take a registration safely
  if not isinstance(data, list):
    raise PluginInstallRefusedError(COMMUNITY_NOT_ARRAY_REASON.format(path = path, pid = plugin_id))
  return data


def _find_all_secret_paths(before: object, override: object, path: str) -> list[str]:
  """
  Find credential-like values in the objects an override block touches.

  Args:
    before: Current settings value at this level.
    override: Override block value at the same level.
    path: Dotted prefix naming this level, empty at the top.

  Returns:
    Dotted paths of the credential-like values; empty when the two values are not both objects.
  """
  # guard: only two objects meeting at the same path can collide
  if not isinstance(before, dict) or not isinstance(override, dict):
    return []

  # the secrets at this level, then those in every nested object the override reaches into
  hits = [ f"{path}{key}" for key, value in before.items() if vault_manifest.is_secret(key, value) ]
  for key, value in override.items():
    hits.extend(_find_all_secret_paths(before.get(key), value, f"{path}{key}."))
  return hits


def _build_credential_warning(settings: Path, plugin_id: str, data_file: Path) -> str | None:
  """
  Build the warning for credential-like values in settings the override block touches.

  Args:
    settings: Override document holding every plugin's block.
    plugin_id: Plugin whose block applies.
    data_file: The plugin's settings file inside the vault.

  Returns:
    The warning text, or None when there is no block, no settings file, or no credential-like value.
  """
  blocks = vault_manifest.load_json(settings)
  override = blocks.get(plugin_id) if isinstance(blocks, dict) else None

  # guard: no block, or no data yet, means nothing can be overwritten
  if not isinstance(override, dict) or not override or not data_file.is_file():
    return None

  # scan the current settings under the block, and word the warning when anything turned up
  hits = _find_all_secret_paths(vault_manifest.load_json(data_file), override, "")
  return SECRET_WARNING.format(pid = plugin_id, paths = ", ".join(hits)) if hits else None


def _write_bundle(source: _Source, plugin_dir: Path, plugin_id: str) -> None:
  """
  Write the source's bundle files into the plugin directory.

  Args:
    source: Resolved bundle origin.
    plugin_dir: Per-plugin directory inside the vault.
    plugin_id: Plugin id, named in the refusal.

  Raises:
    PluginInstallRefusedError: If writing the bundle fails.
  """
  backups = [ plugin_dir / f"{name}{BACKUP_SUFFIX}" for name in BUNDLE_FILES ]

  # the directories the write is about to create, innermost first, so a failed write can remove them
  created_dirs = [ directory for directory in (plugin_dir, plugin_dir.parent) if not directory.exists() ]

  # park the current files so a failed write can be undone
  for name, backup in zip(BUNDLE_FILES, backups, strict = True):
    if (plugin_dir / name).is_file():
      (plugin_dir / name).replace(backup)

  # write the new bundle from whichever source resolved
  try:
    if source.bundled_dir is not None:
      vault_manifest.install_bundled(source.bundled_dir, plugin_dir)
    elif source.resolved is not None:
      vault_manifest.install_resolved(source.resolved, plugin_dir)
  except OSError as error:
    # put the parked files back, and drop whatever half of the new bundle landed
    for name, backup in zip(BUNDLE_FILES, backups, strict = True):
      target = plugin_dir / name
      target.with_name(target.name + VaultPath.TMP_SUFFIX).unlink(missing_ok = True)
      if backup.is_file():
        backup.replace(target)
      else:
        target.unlink(missing_ok = True)

    # a directory the write created is removed again, so a fresh install leaves no empty plugin directory
    for directory in created_dirs:
      if directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
    raise PluginInstallRefusedError(WRITE_FAILED_REASON.format(pid = plugin_id, error = error)) from error

  # the new bundle is complete, so the parked copies go
  for backup in backups:
    backup.unlink(missing_ok = True)


def _format_vault_rel_path(vault: Path, path: Path) -> str:
  """
  Express a vault path relative to the vault's parent directory.

  Args:
    vault: Obsidian config directory.
    path: Path inside the vault.

  Returns:
    The path with forward-slash separators, starting at the config directory's name.
  """
  return "/".join(path.relative_to(vault.parent).parts)


def install(vault: Path, plugin_id: str, *, bundled: bool, dry_run: bool) -> InstallResult:
  """
  Install or update one community plugin into the vault.

  Resolves the plugin from the community registry, or from the bundle this plugin ships, then brings the vault's
  bundle files, override settings, and community registration up to date.

  Guarantees:
    - Every check that can refuse runs before anything in the vault is written.
    - A vault ahead of its source is left alone with a warning.
    - The override block is re-merged into the plugin's settings file on every run.
    - The id is registered in the community plugin list with the existing order preserved.
    - When writing the bundle fails, the previous bundle files are restored, no half-written new file remains, and
      plugin directories the failed write created are removed.
    - A dry run writes nothing, not the vault, the community catalog cache or the bundle cache, and reports the
      same outcomes a real run would.

  Notes:
    - Credential-like values in settings objects the override block touches produce a warning.

  Args:
    vault: Obsidian config directory.
    plugin_id: Id of the plugin to install.
    bundled: Whether to install the bundle this plugin ships instead of resolving the registry.
    dry_run: Whether to report outcomes without writing.

  Returns:
    The outcomes, warnings, and vault-relative paths written.

  Raises:
    PluginInstallRefusedError: If the id is unsafe, cannot be resolved, the overrides or community list are unusable,
      or writing the bundle fails.
  """

  # Contract:
  # Every check that can refuse runs before anything in the vault is written.

  # Contract:
  # The plugin id is registered in the community plugin list with the existing entries and their order preserved.

  # Contract:
  # When writing the bundle fails, the previous bundle files are restored, no half-written new file remains,
  # and plugin directories the failed write created are removed, so a refused run leaves the vault as it was.

  # Contract:
  # A dry run writes nothing, not the vault, the community catalog cache or the bundle cache,
  # and reports the same outcomes a real run would.

  # Contract:
  # A vault whose installed plugin is ahead of its source is left alone and reported with a warning.

  # Contract:
  # The override block is re-merged into the plugin's settings file on every run,
  # whether or not the bundle files changed.

  # guard: an id that is not a plain name would write outside the plugins directory
  if not vault_manifest.is_safe_name(plugin_id):
    raise PluginInstallRefusedError(UNSAFE_ID_REASON.format(pid = plugin_id))

  # resolve every path the run reads or writes
  plugin_dir = vault / VaultPath.PLUGINS / plugin_id
  data_file = plugin_dir / VaultPath.PLUGIN_DATA
  settings = vault_manifest.template_root() / PLUGIN_SETTINGS
  community_path = vault / VaultPath.COMMUNITY_PLUGINS

  # every check that can refuse runs before anything is written: the community list and the override merge first
  warnings: list[str] = []
  community = _read_community(community_path, plugin_id)
  try:
    overrides = plugin_json.merge_overrides(settings, plugin_id, data_file, dry_run = True)
  except (OSError, ValueError) as error:
    raise PluginInstallRefusedError(OVERRIDES_INVALID_REASON.format(pid = plugin_id, error = error)) from error

  # then the source, and what its version means for the vault's copy
  source = _resolve_source(plugin_id, bundled = bundled, dry_run = dry_run, warnings = warnings)
  vault_version = _read_vault_version(plugin_dir)
  binary = _decide(vault_version, source.version)

  # collect the non-fatal notices: a vault ahead of its source, credentials the overrides touch
  if binary == BINARY_VAULT_NEWER:
    warnings.append(VAULT_NEWER_WARNING.format(pid = plugin_id, vault = vault_version, source = source.version))
  if (secret := _build_credential_warning(settings, plugin_id, data_file)) is not None:
    warnings.append(secret)

  # the registration outcome follows from the list as read
  community_state = COMMUNITY_CREATED if community is None \
      else COMMUNITY_PRESENT if plugin_id in community else COMMUNITY_ADDED

  # a dry run reports what a real run would do and writes nothing
  if dry_run:
    return InstallResult(binary = binary, overrides = overrides, community = community_state, warnings = warnings)

  # the bundle lands only when the vault is absent or behind
  touched: list[str] = []
  if binary not in (BINARY_UNCHANGED, BINARY_VAULT_NEWER):
    styles = plugin_dir / VaultPath.PLUGIN_STYLES
    had_styles = styles.is_file()
    _write_bundle(source, plugin_dir, plugin_id)
    touched.extend(_format_vault_rel_path(vault, plugin_dir / name) for name in REQUIRED_FILES)

    # the stylesheet counts when it was written or removed
    if had_styles or styles.is_file():
      touched.append(_format_vault_rel_path(vault, styles))

  # the override block is re-enforced on every run, whatever happened to the binaries
  if overrides == OVERRIDES_APPLIED:
    plugin_json.merge_overrides(settings, plugin_id, data_file, dry_run = False)
    touched.append(_format_vault_rel_path(vault, data_file))

  # register the id once, keeping the order already there
  if community_state != COMMUNITY_PRESENT:
    vault_manifest.dump_json(community_path, [ *(community or []), plugin_id ])
    touched.append(_format_vault_rel_path(vault, community_path))
  return InstallResult(binary = binary, overrides = overrides, community = community_state, warnings = warnings,
                       touched_paths = touched)


def main(argv: list[str]) -> int:
  """
  Run the `plugin-install` command line.

  Installs or updates one community plugin and reports the outcome as one JSON line on standard output.

  Notes:
    - A dry run reports the outcomes without writing.
    - A refused run leaves the vault as it was.

  Args:
    argv: Command-line arguments after the program name: the plugin id, then `--bundled`, `--dry-run`, `--vault`.

  Returns:
    The exit code: 0 when installed, 1 when refused. Invalid arguments exit with 2 through the parser.
  """
  # waiver: argparse CLI signature
  parser = argparse.ArgumentParser(prog = "lazycortex-obsidian plugin-install")
  # waiver: argparse CLI signature
  parser.add_argument("id", help = "Obsidian community plugin id")
  # waiver: argparse CLI signature
  parser.add_argument("--bundled", action = "store_true", help = "install the bundle this plugin ships")
  # waiver: argparse CLI signature
  parser.add_argument("--dry-run", action = "store_true", help = "report the outcome without writing")
  # waiver: argparse CLI signature
  parser.add_argument("--vault", help = "Obsidian config directory (default: <git toplevel>/.obsidian)")
  args = parser.parse_args(argv)
  base: dict[str, object] = { "id": args.id, "binary": None, "overrides": None, "community": None,
                              "warnings": [], "touched_paths": [], "reason": None }

  # every refusal is one JSON line with its reason, and the vault as it was
  try:
    vault = Path(args.vault) if args.vault else find_vault(None) / VaultPath.OBSIDIAN
    result = install(vault, args.id, bundled = args.bundled, dry_run = args.dry_run)
  except (PluginInstallRefusedError, IconizeError) as error:
    reason = error.reason if isinstance(error, PluginInstallRefusedError) else str(error)
    print(json.dumps({ **base, "status": STATUS_REFUSED, "reason": reason }, ensure_ascii = False))
    return EXIT_REFUSED
  print(json.dumps({ **base, "status": STATUS_INSTALLED, "binary": result.binary, "overrides": result.overrides,
                     "community": result.community, "warnings": result.warnings,
                     "touched_paths": result.touched_paths }, ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
