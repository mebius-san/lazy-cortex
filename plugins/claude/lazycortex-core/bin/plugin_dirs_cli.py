"""
Plugin-directory derivation for sessions that run without the daemon's environment.

This module backs the `plugin-dirs` subcommand and the expert preflight's probe spawn. Both
need the `LAZYCORTEX_PLUGIN_DIRS` value the runtime daemon exports to its subprocesses, but
neither runs under the daemon, so the value is rebuilt in the daemon's shape: every dev-vault
plugin source under `<repo>/plugins/claude/*/` that carries a manifest, and nothing else — an
installed plugin is never listed, because every consumer resolves it through the install registry
(`~/.claude/plugins/installed_plugins.json`) itself at call time. The repository root follows the
dispatcher convention — `LAZY_REPO_ROOT`, then the process working directory, overridable per call
with `--cwd`.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from runtime_daemon import installed_plugin_roots  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: dev-vault plugin-tree dirname, fixed by the repo layout, not a domain key
_DEV_PLUGINS_REL = "plugins/claude"
# waiver: plugin-manifest layout idiom, mirrors reference_resolver / runtime_daemon
_MANIFEST_REL = ".claude-plugin/plugin.json"


def derive_plugin_dirs(repo: Path, *, home: Path | None = None) -> tuple[str, bool]:
  """
  Rebuild the `LAZYCORTEX_PLUGIN_DIRS` value for a process the daemon did not spawn.

  The value lists the in-repo plugin sources only, exactly like the daemon's export; installed
  plugins never join it.

  Args:
    repo: Repository root whose in-repo plugin sources are scanned.
    home: Home directory whose plugin registry is probed for the found flag; the current user's
      when omitted.

  Returns:
    A tuple of the `os.pathsep`-joined plugin-dir string (possibly empty) and a flag that is
    True when an in-repo plugin source or any installed plugin was found; False tells the caller
    the value is best-effort only.
  """
  dirs: list[str] = []

  # Domain(plugin.boundaries):
  # # How a session rebuilds the plugin-directory list the daemon would export
  # The list a process inherits names only the live plugin sources in the checkout's own plugin
  # tree — every one that carries a manifest — and never an installed copy. Installed plugins are
  # updated while long-running processes keep going, so a list that froze an installed version in
  # place would keep serving it after the update; whoever needs an installed plugin looks it up in
  # the install registry itself at the moment it needs it.

  # in a dev vault every in-repo source dir carrying a manifest is a plugin dir
  dev_claude = Path(repo) / _DEV_PLUGINS_REL
  if dev_claude.is_dir():
    for entry in sorted(dev_claude.iterdir()):
      if (entry / _MANIFEST_REL).is_file():
        dirs.append(str(entry.resolve()))

  # the joined value, and whether any plugin is reachable at all — an installed plugin still counts
  registry_home = Path.home() if home is None else home
  return os.pathsep.join(dirs), bool(dirs) or bool(installed_plugin_roots(registry_home))


def cmd_plugin_dirs(argv: list[str]) -> int:
  """
  Run the `plugin-dirs` subcommand: print the derived `LAZYCORTEX_PLUGIN_DIRS` value.

  Args:
    argv: Argument vector after the subcommand name (`--cwd` only).

  Returns:
    Process exit code: 0 on success (the printed line may be empty when nothing was found).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the repo-root override alone
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core plugin-dirs")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # the derived value alone is printed; the best-effort flag is the preflight's concern
  print(derive_plugin_dirs(resolve_repo_root(args.cwd))[0])
  return 0
