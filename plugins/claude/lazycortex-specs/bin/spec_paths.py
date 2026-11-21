"""Spec layout roots — settings-root vs content-root resolution.

The settings-root holds `.claude/lazy.settings.json`; the content-root holds the
subsystem folders and the `requests/` inbox, and is `settings-root/<vault_root>`
(default `specs`), always a sub-directory of the settings-root. Bin code reads config from the
settings-root but joins spec content under the content-root.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


DEFAULT_VAULT_ROOT = "specs"
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION = "spec"
_VAULT_ROOT_KEY = "vault_root"
_PARENT_SEGMENT = ".."
# One-off operator message -- names the setting, the refused value, why, and the one way out
_VAULT_ROOT_REFUSAL = (
    "spec.vault_root {value!r} in .claude/lazy.settings.json {reason}; the spec catalog must live in a "
    "sub-directory of the repository: move the catalog into one (the default is `specs`) and set "
    "spec.vault_root to that directory"
)
# The refusal of a content-root lookup under settings that cannot be read as a JSON object; the error names the file.
_SETTINGS_REFUSAL = "the spec content root cannot be resolved: {error}"
_REASON_REPO_ROOT = "names the repository root"
_REASON_ABSOLUTE = "is an absolute path"
_REASON_PARENT = "climbs out through `..`"
# waiver: sibling-plugin CLI env contract per dev.plugin-boundaries § 1c
_ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
# waiver: external Claude Code registry path and record keys, not internal keys
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
_REG_PLUGINS = "plugins"
_REG_VERSION = "version"
_REG_INSTALL_PATH = "installPath"
_BIN_DIR = "bin"
# The core plugin, whose CLI every caller of `resolve_core_cli` reaches.
_CORE_CLI_NAME = "lazycortex-core"
# The core verb and flags that print one settings section as the runtime sees it: the tracked file with the local
# overlay merged on.
_CORE_SETTINGS_GET = "settings-get"
_SCOPE_FLAG = "--scope"
_MERGED_SCOPE = "merged"
_CWD_FLAG = "--cwd"
# How long one merged-settings read may take before it counts as failed.
_CORE_TIMEOUT_S: float = 60
# The plugin tree a checkout that authors the plugins carries them under.
_PLUGIN_TREE_REL = Path("plugins") / "claude"
_TMP_SUFFIX = ".tmp"
_ENCODING = "utf-8"
_WRITE_MODE = "w"
# The mode a plain `open()` would give a new file before the umask is applied.
_NEW_FILE_MODE = 0o666
_LF = "\n"
_CRLF = "\r\n"
_CR = "\r"
_CRLF_BYTES = b"\r\n"
_LF_BYTES = b"\n"
_MD = ".md"
_SEP = "/"


class VaultRootError(BaseException):
  """
  Refusal to resolve the spec content-root.

  Raised when `spec.vault_root` is not a sub-directory of the settings-root, and when the settings file cannot be
  read as a JSON object, so no content root can be named. For a bad `spec.vault_root` the message names the setting
  and tells the operator to move the catalog into a sub-directory and point the setting at it; for an unreadable
  settings file the message names the file.
  """

  # Decision: chose a `BaseException` subclass, not `Exception` -- a per-item `except Exception` in a routine
  # tick would otherwise record the refusal and carry on, while every verb resolving the content-root must stop


class SettingsError(ValueError):
  """
  Refusal of a settings file that cannot be read as a JSON object.

  The message names the file.
  """


class SettingsSyntaxError(SettingsError, json.JSONDecodeError):
  """
  Refusal of a settings file that is not valid JSON.

  The message names the file. Callers that catch `json.JSONDecodeError` catch it as well.
  """


def find_settings_root(start: Path) -> Path:
  """
  Walk up from `start` to the nearest dir holding `.claude/lazy.settings.json`.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The first ancestor (inclusive) containing the settings file; `start`
    resolved when none is found.
  """
  cur = start.resolve()
  for cand in [ cur, *cur.parents ]:
    # guard: first dir carrying the settings file is the settings-root
    if (cand / _SETTINGS_REL).is_file():
      return cand
  return cur


def require_settings_root(start: Path) -> Path:
  """
  Find the nearest directory holding `.claude/lazy.settings.json`, refusing when there is none.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The first ancestor (inclusive) containing the settings file.

  Raises:
    FileNotFoundError: When no ancestor of `start` holds the settings file.
  """
  root = find_settings_root(start)

  # guard: the lenient lookup falls back to `start` itself, which may hold no settings file at all
  if not (root / _SETTINGS_REL).is_file():
    raise FileNotFoundError(f"no {_SETTINGS_REL.as_posix()} at or above {start.resolve()}")
  return root


def read_settings(settings_path: Path) -> dict:
  """
  Read an existing settings file as one JSON object.

  Guarantees:
    - Every failure to read the file as one JSON object raises `SettingsError`, a `ValueError` whose message names
      the file: the file cannot be read, is not UTF-8 text, is not valid JSON, or is valid JSON that is not an
      object.
    - A JSON syntax error is raised as `SettingsSyntaxError`, which is also a `json.JSONDecodeError`, so a caller
      catching that class still catches it.
    - No other exception is raised and no default is ever returned in those cases.

  Args:
    settings_path: The `lazy.settings.json` file, which must exist.

  Returns:
    The parsed settings object.

  Raises:
    SettingsSyntaxError: If the file is not valid JSON; also a `json.JSONDecodeError`, and the message names the
      file.
    SettingsError: If the file cannot be read, is not UTF-8 text, or its JSON is not an object; a `ValueError`, and
      the message names the file.
  """

  # Contract:
  # Every failure to read the file as one JSON object raises `SettingsError`, a `ValueError` whose message
  # names the file: the file cannot be read, is not UTF-8 text, is not valid JSON, or is valid JSON that is
  # not an object.
  # A JSON syntax error is raised as `SettingsSyntaxError`, which is also a `json.JSONDecodeError`, so a
  # caller catching that class still catches it.
  # Nothing else is raised and no default is ever returned in those cases.

  # a file that cannot be read, or is not text at all, is named, so the failure says which file is broken
  try:
    text = settings_path.read_text(encoding = "utf-8")
  except UnicodeDecodeError as error:
    raise SettingsError(f"{settings_path}: settings file is not UTF-8 text: {error}") from error
  except OSError as error:
    raise SettingsError(f"{settings_path}: settings file cannot be read: {error}") from error

  # a syntax error stays a JSON decode error for the callers that catch one, and gains the file's name
  try:
    data = json.loads(text)
  except json.JSONDecodeError as error:
    raise SettingsSyntaxError(f"{settings_path}: {error.msg}", error.doc, error.pos) from error

  # guard: valid JSON that is not an object configures nothing and is refused by name
  if not isinstance(data, dict):
    raise SettingsError(f"{settings_path}: settings file is not a JSON object, got {type(data).__name__}")
  return data


def require_valid_settings(settings_root: Path) -> None:
  """
  Require the settings file under a settings root, when there is one, to read as a JSON object.

  A settings root without a `lazy.settings.json` is accepted as one with nothing configured.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Raises:
    SettingsError: If the settings file exists and cannot be read, is not UTF-8 text, is not valid JSON
      (`SettingsSyntaxError`, also a `json.JSONDecodeError`), or is valid JSON that is not an object.
  """

  # an absent settings file is a valid "nothing configured"; one that exists must read as a JSON object
  path = settings_root / _SETTINGS_REL
  if path.is_file():
    read_settings(path)


def _vault_root_value(settings_root: Path) -> str:
  """
  Read `spec.vault_root` from settings, defaulting to `specs`.

  Guarantees:
    - The returned root is always a sub-directory strictly below the settings-root; a value naming the settings-root
      itself, an absolute path, or one with a `..` segment is refused, never replaced by the default.
    - A settings file that exists but cannot be read as a JSON object (unreadable, not UTF-8 text, not valid JSON, or
      not an object) is refused the same way, with the file named, never replaced by the default.
    - Only an absent settings file or an unset, empty, or non-string value falls back to `specs`.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    The configured vault-root sub-directory, relative to the settings-root, or `specs` when the settings file is
    absent or the value is unset, empty, or not a string.

  Raises:
    VaultRootError: When the value names the settings-root itself (`.`), is an absolute path, or
      climbs out through `..`, or when the settings file exists but cannot be read as a JSON object; the message
      names the file.
  """

  # Contract:
  # The returned vault root is always a sub-directory strictly below the settings-root: a value naming
  # the settings-root itself, an absolute path, or one with a `..` segment is refused, never replaced by
  # the default. A settings file that exists but cannot be read as a JSON object (unreadable, not UTF-8 text,
  # not valid JSON, or not an object) is refused the same way, with the file named, never replaced by the
  # default. Only an absent settings file or an unset, empty, or non-string value falls back to `specs`.

  path = settings_root / _SETTINGS_REL

  # guard: no settings file — use the default root
  if not path.is_file():
    return DEFAULT_VAULT_ROOT

  # settings that exist but cannot be read as a JSON object name no root at all: the lookup is refused, never
  # answered with the default root, so nothing acts on a tree the operator may not have configured
  try:
    spec = read_settings(path).get(_SPEC_SECTION)
  except SettingsError as error:
    raise VaultRootError(_SETTINGS_REFUSAL.format(error = error)) from error

  # guard: missing/malformed spec section — default
  if not isinstance(spec, dict):
    return DEFAULT_VAULT_ROOT

  # the configured segment, when the section names one
  value = spec.get(_VAULT_ROOT_KEY)

  # guard: only a non-empty string overrides the default
  if not isinstance(value, str) or not value:
    return DEFAULT_VAULT_ROOT

  # Domain(spec.config):
  # # The spec catalog lives in its own sub-directory
  # The spec catalog always occupies a named sub-directory of the repository, never the repository root
  # itself and never a place outside it. With the catalog at the root, every markdown file of the
  # repository — READMEs, documentation beside code — would fall under the catalog's watch, and the
  # promise that upgrades never touch the project's own code could not be kept. A setting that points at
  # the root, at an absolute location, or out of the repository is refused with an instruction to move
  # the catalog into a sub-directory; it is never silently replaced by the default location.
  # When the project's configuration exists but cannot be read at all — it is unreadable, or is not the
  # structured record it must be — the catalog's location is unknown, and that is refused too, naming the
  # configuration file. The default location is never assumed in its place, because every automatic step
  # would then act on a tree the operator may never have set up as the catalog. Only a project with no
  # configuration at all, or one whose configuration does not name a location, uses the default location.

  # the configured value read as a relative POSIX path
  rel = PurePosixPath(value)

  # guard: an absolute path is not a sub-directory of the settings-root
  if rel.is_absolute():
    raise VaultRootError(_VAULT_ROOT_REFUSAL.format(value = value, reason = _REASON_ABSOLUTE))

  # guard: a `..` segment climbs out of the settings-root
  if _PARENT_SEGMENT in rel.parts:
    raise VaultRootError(_VAULT_ROOT_REFUSAL.format(value = value, reason = _REASON_PARENT))

  # guard: a value with no segment left (`.`, `./`) names the settings-root itself
  if not rel.parts:
    raise VaultRootError(_VAULT_ROOT_REFUSAL.format(value = value, reason = _REASON_REPO_ROOT))
  return rel.as_posix()


def spec_content_root(settings_root: Path) -> Path:
  """
  Resolve the spec content-root under a settings-root.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    `settings_root / <spec.vault_root>` (default `specs`).

  Raises:
    VaultRootError: When `spec.vault_root` names the settings-root itself, an absolute path, or a
      path climbing out through `..`, or when the settings file exists but cannot be read as a JSON object; the
      message names the file.
  """

  # Domain(spec.config):
  # # Settings and content live at two different roots
  # A checkout keeps its configuration and its actual spec content at two different roots on
  # purpose: the settings-root is wherever the project's own configuration already lives, while
  # the content-root is a separate, configurable location underneath it that holds nothing but
  # the spec catalog itself. Keeping them apart lets the spec catalog occupy its own named
  # location in a project that organizes its other content differently, without the project's
  # own configuration having to move to make room for it.

  return settings_root / _vault_root_value(settings_root)


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin version string.

  Args:
    name: Version string as the plugin registry records it.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def installed_plugin_root(name: str, *, home: Path | None = None) -> Path | None:
  """
  Resolve a plugin's installed source root from Claude Code's plugin registry.

  The registry (`~/.claude/plugins/installed_plugins.json`) records one entry per project and
  version that installed the plugin, each naming its `installPath`; the highest recorded version
  wins. The plugin cache is never searched.

  Args:
    name: Plugin name without its `@<marketplace>` suffix.
    home: Keyword-only home directory holding the registry; the current user's when omitted.

  Returns:
    The recorded install root when it exists on disk, else None.
  """

  # the registry as it stands on disk; an unreadable one records nothing
  registry = (home or Path.home()) / _INSTALLED_PLUGINS_REL
  try:
    data = json.loads(registry.read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return None

  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  plugins = data.get(_REG_PLUGINS, data) if isinstance(data, dict) else {}

  # every recorded install of this plugin, under any marketplace suffix
  records = [
    rec
    for key, entries in plugins.items() if key.split("@", 1)[0] == name
    for rec in (entries or []) if isinstance(rec, dict) and rec.get(_REG_INSTALL_PATH)
  ]

  # guard: the plugin was never installed on this machine
  if not records:
    return None

  # the highest recorded version wins, and only while its install root is still on disk
  best = max(records, key = lambda rec: _version_sort_key(str(rec.get(_REG_VERSION, ""))))
  root = Path(str(best[_REG_INSTALL_PATH]))
  return root if root.is_dir() else None


def resolve_plugin_cli(name: str, *, dev_repo: Path | None = None) -> Path | None:
  """
  Locate a sibling plugin's CLI binary by name.

  Lets a plugin's bin script reach another plugin's published CLI without assuming a fixed
  install layout; each caller applies its own error handling to a missing result. Lookup order: the
  plugin-dirs environment (exported by the daemon), the dev-vault sibling beside this plugin's own
  tree, the given repository's own plugin tree, and last the sibling's install root read from Claude
  Code's plugin registry (`installed_plugin_root`).

  Guarantees:
    - When both the plugin-dirs environment and the plugin registry carry a matching CLI, the
      plugin-dirs environment's copy is returned.

  Args:
    name: Name of the CLI binary to look for under each plugin directory's `bin/` folder.
    dev_repo: Repository root whose own plugin tree is searched before the registry, or None to skip it.

  Returns:
    The resolved binary path, or None when none of the lookup stages carries the named CLI.
  """

  # Contract:
  # When both the plugin-dirs environment and the plugin registry carry a matching CLI,
  # the plugin-dirs environment's copy is returned.

  for entry in os.environ.get(_ENV_PLUGIN_DIRS, "").split(os.pathsep):
    # guard: empty path segment (trailing/double pathsep) — skip it
    if not entry:
      continue
    cli = Path(entry) / _BIN_DIR / name
    if cli.is_file():
      return cli

  # dev-vault sibling — this file sits at plugins/claude/lazycortex-specs/bin/, so a neighbour's own
  # bin/ is two levels up and back down; it precedes the registry (§ 2b) so a checkout runs the
  # sources at hand rather than whatever version happens to be installed
  sibling = Path(__file__).resolve().parents[2] / name / _BIN_DIR / name
  if sibling.is_file():
    return sibling

  # the caller's checkout, when it authors the plugins — a dev tree of its own, still before the registry
  if dev_repo is not None:
    in_repo = dev_repo / _PLUGIN_TREE_REL / name / _BIN_DIR / name
    if in_repo.is_file():
      return in_repo

  # registry fallback — the last stage, for a consumer install with no daemon export and no dev tree
  root = installed_plugin_root(name)

  # guard: no registry record for the sibling — nothing further to try
  if root is None:
    return None
  cli = root / _BIN_DIR / name
  return cli if cli.is_file() else None


def require_plugin_cli(name: str, repo: Path) -> Path:
  """
  Find a required sibling plugin's CLI binary or raise.

  Args:
    name: Name of the CLI binary to look for under each plugin directory's `bin/` folder.
    repo: The repository root whose own plugin tree is searched.

  Returns:
    Absolute path to the resolved binary.

  Raises:
    RuntimeError: When no lookup stage finds a binary, naming every stage searched.
  """

  # Domain(plugin.boundaries):
  # # Reaching a neighbouring plugin's binary: sources at hand first, the install registry last
  # Before a neighbouring plugin's published command can be run as a subprocess, its binary has
  # to be found. The search tries four places in a fixed order and takes the first hit. First,
  # the plugin directories a spawning process was handed. Second, the neighbour's own source
  # sitting right beside this plugin in a development checkout. Third, the plugin tree of the
  # repository the caller works in. Last, the install that Claude Code's plugin registry
  # records for the neighbour. The installed plugin cache is never walked: it keeps every
  # version ever installed, so its newest directory need not be the version this machine has
  # enabled; only the registry names that one.
  # The order puts sources ahead of installs on purpose. A checkout that authors the plugins
  # must run the sources at hand, not whichever version happens to be installed, or a stale
  # copy would silently answer in place of the code being developed. The registry stays the
  # final stage so that a consumer install, which has no spawning process's directory list and
  # no development tree, still reaches the neighbour.
  # The neighbour is required. When no place yields a binary, the lookup fails and names every
  # place it searched, rather than carrying on without the neighbour.

  # env-declared plugin dirs, then the dev-vault sibling beside this plugin, then this repo's own
  # plugin tree, and only then the install the plugin registry records (§ 2b: registry last)
  cli = resolve_plugin_cli(name, dev_repo = repo)
  if cli is not None:
    return cli

  # no stage found a binary — name every stage searched, the two dev-tree locations by path
  raise RuntimeError(
      f"{name} CLI not resolvable: ${_ENV_PLUGIN_DIRS} and the plugin registry yield no match, "
      f"{repo / _PLUGIN_TREE_REL / name / _BIN_DIR / name} is absent from this repo and "
      f"{Path(__file__).resolve().parents[2] / name / _BIN_DIR / name} is absent beside "
      f"this plugin"
  )


def resolve_core_cli(repo: Path) -> Path:
  """
  Find the `lazycortex-core` CLI binary or raise.

  Args:
    repo: The repository root whose own plugin tree is searched.

  Returns:
    Absolute path to the resolved `lazycortex-core` binary.

  Raises:
    RuntimeError: When no lookup stage finds a binary, naming every stage searched.
  """
  return require_plugin_cli(_CORE_CLI_NAME, repo)


def read_merged_sections(repo: Path, *sections: str) -> dict[str, dict]:
  """
  Read settings sections as the expert runtime sees them.

  Each section is the tracked settings file with the local overlay file merged on top of it.

  Guarantees:
    - Every requested section is present in the result under its own name, holding the merged view of the tracked
      file and the local overlay; a value that only the overlay carries is never dropped.
    - Any failure to read a section raises `SettingsError` naming the settings file; the result is never empty
      or partial in its place.

  Notes:
    - Runs one core CLI subprocess per requested section and waits on each up to a fixed timeout, so the call can
      block.

  Args:
    repo: The repository root whose settings are read.
    *sections: The names of the top-level settings sections to read.

  Returns:
    Each requested section name mapped to its merged section object.

  Raises:
    SettingsError: When no core CLI is resolvable, or core cannot read a section, does not answer in time, or
      answers with anything but a JSON object; the message names the settings file.
  """

  # Contract:
  # Every requested section is present in the result under its own name and holds the merged view of the
  # tracked settings file and the local overlay file; a value that only the overlay carries is never dropped.

  # Contract:
  # Any failure to read a requested section raises `SettingsError` (a `ValueError`) whose message names
  # the settings file; the function never returns an empty or partial result in its place.

  settings_path = repo / _SETTINGS_REL

  # guard: without the core CLI no merged view exists, and a partial one must not pass for the settings
  try:
    cli = resolve_core_cli(repo)
  except RuntimeError as error:
    raise SettingsError(f"{settings_path}: merged settings cannot be read: {error}") from error

  # one core call per section, each printing that section's merged view as a JSON object
  merged: dict[str, dict] = {}
  for section in sections:
    try:
      proc = subprocess.run(
          [ sys.executable, str(cli), _CORE_SETTINGS_GET, section, _SCOPE_FLAG, _MERGED_SCOPE,
            _CWD_FLAG, str(repo) ],
          capture_output = True, text = True, check = False, encoding = _ENCODING,
          # waiver: stdlib decode-error mode, not a domain constant
          errors = "replace", timeout = _CORE_TIMEOUT_S,
      )
    except (OSError, subprocess.TimeoutExpired) as error:
      raise SettingsError(f"{settings_path}: {_CORE_SETTINGS_GET} {section} could not run: {error}") from error

    # guard: a failed read, a broken layer included, must not pass for an empty section
    if proc.returncode != 0:
      lines = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
      raise SettingsError(f"{settings_path}: {_CORE_SETTINGS_GET} {section} failed: "
                          f"{lines[-1] if lines else f'exit {proc.returncode}'}")

    # guard: an answer that is not JSON is a broken wire, never an empty section
    try:
      value = json.loads(proc.stdout)
    except json.JSONDecodeError as error:
      raise SettingsError(f"{settings_path}: {_CORE_SETTINGS_GET} {section} printed no JSON") from error

    # guard: a whole-section read always prints an object; anything else is a broken wire
    if not isinstance(value, dict):
      raise SettingsError(f"{settings_path}: {_CORE_SETTINGS_GET} {section} printed a non-object")

    # the section's merged view joins the result under its own name
    merged[section] = value
  return merged


def spec_roots(start: Path) -> tuple[Path, Path]:
  """
  Resolve both spec layout roots from a starting directory.

  Args:
    start: Directory to resolve roots from (cwd or a content path).

  Returns:
    `(settings_root, content_root)`.
  """
  settings_root = find_settings_root(start)
  return settings_root, spec_content_root(settings_root)


def build_wikilink_target(path: Path, settings_root: Path) -> str:
  """
  Build the wikilink target that resolves to the given spec document.

  The target is the document's path from the content-root, without `.md`, when no vault-root file
  and no other spec document under the content-root shares that short form; otherwise it is the
  document's full path from the vault root (the settings-root), which Obsidian matches exactly. A
  document sitting directly at the content-root, whose short form has no folder segment, always gets
  the full vault path, even when its name is unique.

  Guarantees:
    - The returned target is either the short content-root form, returned only when no vault-root file
      has that path and no other spec document under the content-root shares it as a tail, or the
      document's full path from the vault root; in both cases `resolve_wikilink` maps it back to
      the same document.

  Args:
    path: The linked document.
    settings_root: Dir holding `.claude/lazy.settings.json` — the vault root.

  Returns:
    The suffix-free target, e.g. `core/vision` or `specs/vision`.

  Raises:
    ValueError: When `path` lies outside the spec content-root.
  """

  # Contract:
  # The returned target is either the short content-root form, returned only when no vault-root file
  # has that path and no other spec document under the content-root shares it as a tail, or the
  # document's full path from the vault root; in both cases `resolve_wikilink` maps it back to
  # the same document.

  # Domain(spec.links):
  # # Catalog links name one document and nothing else
  # A link to a spec document uses its path from the content-root, without extension, as long as
  # that short form names the document alone. Obsidian matches a link by path suffix, so the short
  # form stops being unique in three cases. It has no folder segment, because the document sits
  # at the content-root itself. It also names a file reached from the vault root, which Obsidian
  # resolves first. Or it is the tail of another spec document's path. In each case the link
  # carries the document's full path from the vault root instead, which Obsidian matches exactly.

  root = settings_root.resolve()
  doc = path.resolve()
  short = doc.relative_to(spec_content_root(root).resolve()).with_suffix("").as_posix()

  # the catalog's usual short link when it names this document alone, the full vault path otherwise
  unique = _SEP in short and not (root / f"{short}{_MD}").exists() and not _has_shared_tail(short, doc)
  return short if unique else doc.relative_to(root).with_suffix("").as_posix()


def _has_shared_tail(short: str, doc: Path) -> bool:
  """
  Tell whether another spec document's path ends with the same short form as `doc`'s.

  Args:
    short: The document's suffix-free content-root path.
    doc: The resolved document path.

  Returns:
    True when a second document under the content-root carries `short` as its path tail.
  """
  tail = f"{_SEP}{short}{_MD}"
  name = Path(short).name + _MD

  # limit: only the content-root is walked, not the whole Obsidian vault — a same-tailed note
  # outside the catalog still collides; walk the settings-root if one ever appears
  for dirpath, _dirs, files in os.walk(spec_content_root(find_settings_root(doc.parent))):
    if name in files and (cand := Path(dirpath) / name) != doc and cand.as_posix().endswith(tail):
      return True
  return False


def resolve_wikilink(target: str, settings_root: Path) -> Path:
  """
  Resolve a suffix-free wikilink target to the file it names, in the order Obsidian does.

  Args:
    target: The wikilink target, without `|display` or `#anchor`.
    settings_root: Dir holding `.claude/lazy.settings.json` — the vault root.

  Returns:
    `<settings_root>/<target>.md` when that file exists, else `<content-root>/<target>.md`.
  """
  vault_path = settings_root / f"{target}{_MD}"
  return vault_path if vault_path.is_file() else spec_content_root(settings_root) / f"{target}{_MD}"


def read_text(path: Path) -> str:
  """
  Read a text file with `\\n` line endings.

  Notes:
    - Performs file I/O.

  Args:
    path: The file to read, followed through any symlink to its real target.

  Returns:
    The file's text with every `\\r\\n` turned into `\\n`.

  Raises:
    OSError: If the file cannot be read.
  """
  with open(path, encoding = _ENCODING, newline = "") as handle:
    return handle.read().replace(_CRLF, _LF)


def _disk_ending(target: Path) -> str:
  """
  Read the line ending a file on disk uses now: the one its first line break carries.

  Args:
    target: The resolved file to inspect.

  Returns:
    `\\r\\n` when the file's first line break is CRLF; `\\n` otherwise, including for a file
    that does not exist or carries no line break.
  """
  try:
    raw = target.read_bytes()
  except FileNotFoundError:
    return _LF
  first = raw.find(_LF_BYTES)
  return _CRLF if first > 0 and raw[first - 1:first + 1] == _CRLF_BYTES else _LF


def write_text_atomic(path: Path, text: str, *, newline: str | None = None) -> None:
  """
  Replace a file's content in one step, so a reader never sees it half-written.

  Guarantees:
    - Writes through a symlink to its real target rather than replacing the symlink itself.
    - Writes the line ending the target on disk uses at write time — CRLF when its first line
      break is CRLF — and LF for a new file, unless `newline` names the ending explicitly.
    - An existing target keeps its own permission mode; a new file gets the mode a plain write
      would give it under the current umask.
    - On any failure, the temp file is removed and the exception re-raised, leaving the target
      untouched.

  Notes:
    - Performs file I/O.
    - For a new file, briefly sets and restores the process umask to read it — not thread-safe.
    - A mixed-ending file is written back with its first line break's ending throughout.

  Args:
    path: The file to write, followed through any symlink to its real target.
    text: The full text to write, its lines ended by `\\n`.
    newline: The line ending to write, overriding the one detected on disk; None detects it.

  Raises:
    OSError: If the write, chmod, or rename into place fails for any reason.
  """

  # Contract:
  # A write to a symlink lands in the file the link points to; the symlink itself is never
  # replaced.

  # Contract:
  # The line ending written is the one the target on disk uses at write time — CRLF when its first
  # line break is CRLF, LF for a new file — unless the caller names the ending explicitly.

  # Contract:
  # An existing target keeps its own permission mode; a new file gets the mode a plain write
  # would give it under the current umask.

  # Contract:
  # When the write fails, the exception reaches the caller, the target is left exactly as it was,
  # and no temporary file remains.

  target = path.resolve()

  # the ending comes from the caller or from the file as it is on disk now, never from an earlier read
  if (newline or _disk_ending(target)) == _CRLF:
    text = text.replace(_CRLF, _LF).replace(_LF, _CRLF)

  # a replaced file keeps its own mode; a new one gets what a plain write would have given it
  try:
    mode = stat.S_IMODE(target.stat().st_mode)
  except FileNotFoundError:
    umask = os.umask(0)
    os.umask(umask)
    mode = _NEW_FILE_MODE & ~umask

  # the temp file sits beside the target so the final rename never crosses a filesystem
  fd, tmp_name = tempfile.mkstemp(prefix = f".{target.name}.", suffix = _TMP_SUFFIX, dir = target.parent)
  try:
    with os.fdopen(fd, _WRITE_MODE, encoding = _ENCODING, newline = "") as handle:
      handle.write(text)
      handle.flush()
      os.fsync(handle.fileno())
    os.chmod(tmp_name, mode)
    os.replace(tmp_name, target)
  # waiver: broad catch -- an interrupt mid-write must remove the temp file too; the error is re-raised
  except BaseException:
    Path(tmp_name).unlink(missing_ok = True)
    raise
