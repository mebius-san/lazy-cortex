# Managed by /lazy-python.install (Step 2) — edit the template, not this copy.
"""
Consumer-side mypy plugin shim for the `protected-access` check.

Resolves the live lazycortex-python install at mypy start-up and delegates to its
`bin/mypy_protected_access.py`, so the consumer's `plugins = ["cli/mypy/protected_access.py"]`
entry survives plugin version bumps without a frozen path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  # waiver: consumers do not set `extension-pkg-allow-list = ["mypy"]`, so pylint cannot introspect compiled mypy
  from mypy.plugin import Plugin  # pylint: disable=no-name-in-module


_BIN_REL = "bin/mypy_protected_access.py"
_MODULE_NAME = "lazycortex_mypy_protected_access"
_PLUGIN_KEY = "lazycortex-python"
_CONFIG_DIR_NAME = ".claude"
_MANIFEST_REL = "plugins/installed_plugins.json"
_DEV_PLUGINS_REL = "plugins/claude"
_PLUGINS_FIELD = "plugins"
_SCOPE_FIELD = "scope"
_PROJECT_SCOPE = "project"
_USER_SCOPE = "user"
_PROJECT_PATH_FIELD = "projectPath"
_VERSION_FIELD = "version"
_INSTALL_PATH_FIELD = "installPath"
_PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"


def _parse_version(version: str) -> list[int]:
  """
  Turn a dotted version into a sortable list, reading non-numeric pieces as 0.

  Args:
    version: Dotted version string, possibly empty.

  Returns:
    The integer pieces of the version.
  """
  return [int(piece) if piece.isdigit() else 0 for piece in version.split(".")]


def _rank_scope(entry: dict[str, str], repo_root: Path) -> int | None:
  """
  Rank a manifest entry by the scope it was installed for, as seen from one repository.

  Args:
    entry: One install entry of the manifest.
    repo_root: Resolved root of the repository the shim serves.

  Returns:
    1 for a project install made for this repository, 0 for a user install, or None for any other entry.
  """
  scope = entry.get(_SCOPE_FIELD)

  # guard: a user install serves every repository, below this repository's own project install
  if scope == _USER_SCOPE:
    return 0

  # guard: a project install counts only for the project it was made for; paths compare with symlinks resolved
  if scope != _PROJECT_SCOPE or not entry.get(_PROJECT_PATH_FIELD):
    return None

  # the one project install that counts is the one made for this repository
  return 1 if Path(entry[_PROJECT_PATH_FIELD]).resolve() == repo_root else None


def _find_manifest_install(manifest: Path, repo_root: Path) -> Path | None:
  """
  Pick the active install from Claude Code's `installed_plugins.json` for one repository.

  Args:
    manifest: Path of the `installed_plugins.json` to read.
    repo_root: Resolved root of the repository the shim serves.

  Returns:
    The plugin file of the preferred install, or None when the manifest names none for this repository.
  """

  # Domain(plugin.boundaries):
  # # Choosing among installed copies of a plugin
  # The manifest of installed plugins may list one plugin several times, once per scope, project and version. An
  # install made for the current project, its recorded project path naming this repository once symbolic links are
  # resolved on both sides, beats an install made for the user. An install made for any other project is ignored. Within
  # the chosen scope the highest version wins. An entry whose install path is missing, empty or not absolute is
  # skipped, because a relative path would resolve against the working directory instead of an install; so is an
  # entry whose install no longer carries the plugin file.

  # guard: the manifest is optional; absence or corruption means "not found here"
  try:
    # waiver: the shim is copied as one standalone file into consumer repos, with no constants container to import
    data = json.loads(manifest.read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return None

  # every manifest entry of this plugin that serves this repository and whose install carries the plugin file
  candidates: list[tuple[int, list[int], Path]] = []
  for key, entries in (data.get(_PLUGINS_FIELD) or {}).items():
    # guard: other plugins' entries are irrelevant
    if key.split("@", 1)[0] != _PLUGIN_KEY:
      continue
    for entry in entries or []:
      install_path = entry.get(_INSTALL_PATH_FIELD) or ""
      tier = _rank_scope(entry, repo_root)

      # guard: an entry for another project serves no one here; a missing, empty, or relative install path would
      # resolve against the cwd, not an install
      if tier is None or not install_path or not Path(install_path).is_absolute():
        continue

      # an install whose plugin file is gone cannot serve
      bin_path = Path(install_path) / _BIN_REL
      if bin_path.is_file():
        candidates.append((tier, _parse_version(entry.get(_VERSION_FIELD) or ""), bin_path))

  # guard: no usable install in the manifest
  if not candidates:
    return None

  # this repository's project install beats a user install, then the highest version wins
  candidates.sort(key = lambda cand: (cand[0], cand[1]))
  return candidates[-1][2]


def _resolve() -> Path:
  """
  Locate the plugin file: `LAZYCORTEX_PLUGIN_DIRS`, then the dev vault checkout, then the install manifest.

  Returns:
    The path of `bin/mypy_protected_access.py` inside the live install.

  Raises:
    RuntimeError: When no stage finds the plugin; the message names every stage searched.
  """

  # Domain(plugin.boundaries):
  # # Order of locating a sibling plugin install
  # A tool that must reach another plugin's file looks for it in three stages and takes the first hit. First the
  # directories listed in `LAZYCORTEX_PLUGIN_DIRS`, which the runtime exports for development source trees. Then the
  # development vault layout, where the plugin sits as a sibling source tree next to the consumer tooling. Last the
  # manifest of installed plugins, so a development checkout is never shadowed by a stale installed copy. When no stage
  # finds the plugin the tool fails loudly and names every stage it searched; it never carries on without the plugin.

  # 1. daemon context: dev plugin trees exported by the supervisor
  for plugin_dir in os.environ.get(_PLUGIN_DIRS_ENV, "").split(os.pathsep):
    if plugin_dir and (Path(plugin_dir) / _BIN_REL).is_file():
      return Path(plugin_dir) / _BIN_REL

  # 2. dev vault: this shim lives at <repo>/cli/mypy/, the source tree at <repo>/plugins/claude/
  repo_root = Path(__file__).resolve().parents[2]
  dev = repo_root / _DEV_PLUGINS_REL / _PLUGIN_KEY / _BIN_REL
  if dev.is_file():
    return dev

  # 3. consumer install: the plugin manifest names the install made for this repository or for the user
  manifest = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / _CONFIG_DIR_NAME) / _MANIFEST_REL
  found = _find_manifest_install(manifest, repo_root)
  if found is not None:
    return found
  raise RuntimeError(
    f"lazycortex-python plugin not found in ${_PLUGIN_DIRS_ENV}, at the dev-vault path {dev}, or in {manifest}; "
    "install/enable it or re-run /lazy-python.install",
  )


# Decision: resolve at import, not inside plugin() — mypy reports an exception raised while importing the plugin file
# with its message ("Error importing plugin"), but one raised from plugin() as an opaque INTERNAL ERROR.

# the resolved plugin file; a failed resolution aborts the import here
_PLUGIN_FILE = _resolve()


def plugin(version: str) -> type[Plugin]:
  """
  Load the resolved plugin module and return its `Plugin` class to mypy's plugin loader.

  Args:
    version: The mypy version string, passed through to the real entry point.

  Returns:
    The `Plugin` subclass the resolved module provides.

  Raises:
    RuntimeError: When the resolved path cannot be loaded as a module.
  """
  spec = importlib.util.spec_from_file_location(_MODULE_NAME, _PLUGIN_FILE)
  # guard: a path that cannot be loaded as a module is as fatal as a missing one
  if spec is None or spec.loader is None:
    raise RuntimeError("lazycortex-python plugin not loadable; re-run /lazy-python.install")

  # register before exec so dataclasses and pickling inside the plugin can find the module
  module = importlib.util.module_from_spec(spec)
  sys.modules[_MODULE_NAME] = module
  spec.loader.exec_module(module)

  # hand mypy the plugin class of the resolved module
  # waiver: the dynamically loaded module is untyped, so the annotated local gives the entry point's result its type
  result: type[Plugin] = module.plugin(version)
  return result
