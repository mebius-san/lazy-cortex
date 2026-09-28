"""
Plugin-directory derivation for sessions that run without the daemon's environment.

This module backs the `plugin-dirs` subcommand and the expert preflight's probe spawn. Both
need the `LAZYCORTEX_PLUGIN_DIRS` value the runtime daemon exports to its subprocesses, but
neither runs under the daemon, so the value is rebuilt in the daemon's shape: every dev-vault
plugin source under `<repo>/plugins/claude/*/` that carries a manifest, and nothing else — a cached
install is never listed, because every consumer resolves the newest cached version itself at call
time. The repository root follows the dispatcher convention — `LAZY_REPO_ROOT`, then the
process working directory, overridable per call with `--cwd`.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from runtime_daemon import cached_plugin_roots  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: dev-vault plugin-tree dirname, fixed by the repo layout, not a domain key
_DEV_PLUGINS_REL = "plugins/claude"
# waiver: plugin-manifest layout idiom, mirrors reference_resolver / runtime_daemon
_MANIFEST_REL = ".claude-plugin/plugin.json"
# waiver: the Claude Code plugin-cache location, fixed by the host, not a domain key
_PLUGIN_CACHE_REL = ".claude/plugins/cache"


def derive_plugin_dirs(repo: Path, *, cache_root: Path | None = None) -> tuple[str, bool]:
  """
  Rebuild the `LAZYCORTEX_PLUGIN_DIRS` value for a process the daemon did not spawn.

  The value lists the in-repo plugin sources only, exactly like the daemon's export; cached installs
  never join it.

  Args:
    repo: Repository root whose in-repo plugin sources are scanned.
    cache_root: Plugin-cache root probed for the found flag; `~/.claude/plugins/cache` when omitted.

  Returns:
    A tuple of the `os.pathsep`-joined plugin-dir string (possibly empty) and a flag that is
    True when an in-repo plugin source or any cached plugin was found; False tells the caller the
    value is best-effort only.
  """
  dirs: list[str] = []

  # Domain(plugin.boundaries):
  # # How a session rebuilds the plugin-directory list the daemon would export
  # The list a process inherits names only the live plugin sources in the checkout's own plugin
  # tree — every one that carries a manifest — and never an installed copy. Installed plugins are
  # updated while long-running processes keep going, so a list that froze an installed version in
  # place would keep serving it after the update; whoever needs an installed plugin looks up its
  # newest version itself at the moment it needs it.

  # in a dev vault every in-repo source dir carrying a manifest is a plugin dir
  dev_claude = Path(repo) / _DEV_PLUGINS_REL
  if dev_claude.is_dir():
    for entry in sorted(dev_claude.iterdir()):
      if (entry / _MANIFEST_REL).is_file():
        dirs.append(str(entry.resolve()))

  # the joined value, and whether any plugin is reachable at all — a cached install still counts
  cache = Path.home() / _PLUGIN_CACHE_REL if cache_root is None else cache_root
  return os.pathsep.join(dirs), bool(dirs) or bool(cached_plugin_roots(cache))


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
