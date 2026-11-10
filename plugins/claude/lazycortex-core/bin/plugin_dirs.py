"""
Plugin directory registry and routine-command resolution.

Holds the dev-plugin source directories the runtime daemon prefers over installed plugins, and turns a
routine's `[plugin, *args]` command into a runnable interpreter invocation: a registered dev directory
first, then the install root the machine's plugin registry records.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_setup import installed_plugin_root, read_install_paths  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from shebang_exec import argv_for  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import EnvVar, PluginFile  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Set by `set_plugin_dirs`. When non-empty, `resolve_routine_command` consults these paths first (each is
# a plugin source dir containing `.claude-plugin/` and `bin/`) and falls back to the install registry
# (`~/.claude/plugins/installed_plugins.json`) if no match. Mirrors Claude Code's `--plugin-dir` for
# the daemon's separate-process world: a dev-vault operator points the daemon at the source plugins
# they're working on, instead of routing through an installed copy.
# waiver: module-level mutable registry — `set_plugin_dirs` is its one writer, called once at daemon start
_PLUGIN_DIRS: list[Path] = []


# A plugin-cache root is `<cache>/<registry>/<plugin>/<version>`, so its own directory name is a
# version string; a dev-plugin source root is named after the plugin. That shape difference is the
# one test every consumer can run without knowing where the cache lives.
_VERSION_DIR_RE = re.compile(r"\d+(\.\d+)*")


def is_cache_root(path: Path) -> bool:
  """
  Tell whether a plugin root is a versioned plugin-cache install rather than a dev source tree.

  Args:
    path: Plugin root directory.

  Returns:
    True when the directory is named like a version (`9.1.1`), which only a cache install is.
  """
  return _VERSION_DIR_RE.fullmatch(path.name) is not None


def read_installed_plugin_roots(home: Path) -> list[Path]:
  """
  List the installed source root of every plugin the machine's plugin registry records.

  Reads `~/.claude/plugins/installed_plugins.json`, where the highest recorded version of each
  plugin names its root; the plugin cache is never walked, since it keeps every version ever
  installed.

  Args:
    home: Home directory holding the registry.

  Returns:
    One root per plugin name that exists on disk, sorted by plugin name; empty when nothing is installed.
  """
  return [ root for _name, root in sorted(read_install_paths(home).items()) if root.is_dir() ]


def set_plugin_dirs(dirs: list[Path]) -> None:
  """
  Register plugin source directories the daemon should prefer over the installed plugins.

  Also exports those directories to the environment so downstream subprocess routines (such as
  `lazycortex-core expert-pump-once` or `lazycortex-review tick`) and their own resolvers reach the
  same dev sources. An installed plugin is never exported: every consumer resolves it through the
  install registry itself when it needs one. Pins `EnvVar.MAX_SUBAGENT_SPAWN_DEPTH` for the same
  subprocesses.

  Guarantees:
    - `LAZYCORTEX_PLUGIN_DIRS` lists exactly the registered dev-plugin directories and never a cached
      plugin root, so a plugin updated after daemon start is never shadowed by its older cached copy.

  Args:
    dirs: Plugin source directories to register, in caller-preferred order. Each entry should be the
      root of a plugin source tree containing `.claude-plugin/` and `bin/`.
  """
  # waiver: a genuine module-level rebind, not a false positive — this is the one writer of that cache
  global _PLUGIN_DIRS  # noqa: PLW0603  # pylint: disable=global-statement
  _PLUGIN_DIRS = [ Path(d).resolve() for d in dirs ]

  # Contract:
  # `LAZYCORTEX_PLUGIN_DIRS` lists exactly the registered dev-plugin directories and never a cached
  # plugin root. The daemon outlives plugin updates, so a cached root frozen here at startup would
  # keep serving an old version; resolvers take the dev entries first and read the install registry
  # themselves, at call time, for everything else.

  # `resolve_routine_command` in this module reads `_PLUGIN_DIRS` directly, while this env handle
  # exists for every process the daemon spawns
  os.environ["LAZYCORTEX_PLUGIN_DIRS"] = os.pathsep.join(str(p) for p in _PLUGIN_DIRS)

  # every routine the daemon spawns inherits the subagent spawn-depth pin, not only the expert pump
  os.environ[EnvVar.MAX_SUBAGENT_SPAWN_DEPTH] = EnvVar.SUBAGENT_SPAWN_DEPTH_PIN


def _resolve_in_plugin_dir(plugin_dir: Path, plugin_name: str) -> Path | None:
  """
  Resolve the bin entrypoint for a single plugin source directory.

  Reads the directory's `plugin.json` "name" field and returns its entrypoint when it matches the
  requested plugin. The entrypoint is always `bin/<plugin-name>`, resolved by name alone — never by
  the executable bit, which a git client that does not preserve file modes may silently drop.

  Args:
    plugin_dir: Plugin source root containing `.claude-plugin/` and `bin/`.
    plugin_name: Expected plugin identifier as declared in `plugin.json`.

  Returns:
    Path to the resolved bin entrypoint, or `None` when the directory does not match or the
    entrypoint file is absent.
  """
  manifest = plugin_dir / PluginFile.MANIFEST_DIR / PluginFile.MANIFEST
  try:
    data = json.loads(manifest.read_text(encoding = "utf-8"))
  except (FileNotFoundError, json.JSONDecodeError):
    return None

  # guard: directory's manifest names a different plugin
  if data.get(PluginFile.NAME) != plugin_name:
    return None

  # the plugin's bin directory
  # waiver: filesystem path idiom, not a domain constant
  bin_dir = plugin_dir / "bin"

  # guard: no bin directory present
  if not bin_dir.is_dir():
    return None

  # the entry point is the file named after the plugin, full stop — no exec-bit
  # probing, no "unique executable" guess: a git client that cannot store modes
  # would silently unregister every plugin otherwise
  primary = bin_dir / plugin_name
  return primary if primary.is_file() else None


def resolve_routine_command(cmd: list[str]) -> list[str]:
  """
  Resolve a `[plugin, *args]` command vector to a runnable `[bin_path, *args]` invocation.

  Consults dev-plugin source directories registered via `set_plugin_dirs` first, then falls back to
  the install root Claude Code's plugin registry (`~/.claude/plugins/installed_plugins.json`)
  records for the plugin; the plugin cache is never walked.

  Guarantees:
    - A registered dev-plugin directory for the named plugin always takes precedence over the
      installed copy of the same plugin.
    - When resolution falls back to the registry, the highest recorded version's `installPath` is
      selected, compared numerically component by component rather than as strings.

  Args:
    cmd: Routine command vector whose first element is the plugin name and the rest are arguments
      passed through unchanged.

  Returns:
    A new list where the first element is the interpreter that runs the plugin's bin entrypoint, the
    second element is the resolved absolute path to that entrypoint, and the remaining elements are
    the original arguments.

  Raises:
    FileNotFoundError: When the plugin is not present in any registered source directory or in the
      install registry, or when the resolved root has no bin entrypoint.
    ShebangError: When the resolved entrypoint's shebang line cannot be parsed into an interpreter.
  """

  # Contract:
  # A registered dev-plugin directory for `cmd[0]` always takes precedence over the installed copy
  # of the same plugin. When resolution falls back to the install registry, the `installPath` of
  # the highest recorded version is the one resolved, compared numerically component by component;
  # the plugin cache is never walked.

  plugin = cmd[0]

  # dev-plugin paths take precedence over the installed copy
  for plugin_dir in _PLUGIN_DIRS:
    bin_path = _resolve_in_plugin_dir(plugin_dir, plugin)
    if bin_path is not None:
      return argv_for(bin_path, *cmd[1:])

  # otherwise the install root the plugin registry records
  root = installed_plugin_root(plugin)

  # guard: plugin missing from both dev-plugin paths and the install registry
  if root is None:
    raise FileNotFoundError(
      f"plugin not recorded in ~/.claude/plugins/installed_plugins.json and no matching --plugin-dir for: {plugin}"
    )

  # the installed root's entry point, named after the plugin
  # waiver: filesystem path idiom, not a domain constant
  bin_path = root / "bin" / plugin

  # guard: installed root has no bin entrypoint
  if not bin_path.is_file():
    raise FileNotFoundError(f"no bin for plugin: {bin_path}")
  return argv_for(bin_path, *cmd[1:])
