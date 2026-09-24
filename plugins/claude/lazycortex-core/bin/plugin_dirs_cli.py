"""
Plugin-directory derivation for sessions that run without the daemon's environment.

This module backs the `plugin-dirs` subcommand and the expert preflight's probe spawn. Both
need the `LAZYCORTEX_PLUGIN_DIRS` value the runtime daemon exports to its subprocesses, but
neither runs under the daemon, so the value is rebuilt in the daemon's shape: every dev-vault
plugin source under `<repo>/plugins/claude/*/` that carries a manifest comes first, then the
newest cached version of every plugin directory under `~/.claude/plugins/cache/<registry>/`.
The rebuild is a best-effort approximation, not the daemon's own builder: it keeps a cached copy
of a plugin a dev source already covers, treats every subdirectory of a cached plugin as a
version, and picks the newest per registry, so a plugin cached under two registries is listed
twice. The repository root follows the dispatcher convention — `LAZY_REPO_ROOT`, then the
process working directory, overridable per call with `--cwd`.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: dev-vault plugin-tree dirname, fixed by the repo layout, not a domain key
_DEV_PLUGINS_REL = "plugins/claude"
# waiver: plugin-manifest layout idiom, mirrors reference_resolver / runtime_daemon
_MANIFEST_REL = ".claude-plugin/plugin.json"
# waiver: the Claude Code plugin-cache location, fixed by the host, not a domain key
_PLUGIN_CACHE_REL = ".claude/plugins/cache"


def _compute_version_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  # each dotted component contributes its digits; a digit-free one sorts lowest
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(char for char in part if char.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def derive_plugin_dirs(repo: Path, *, cache_root: Path | None = None) -> tuple[str, bool]:
  """
  Rebuild the `LAZYCORTEX_PLUGIN_DIRS` value for a process the daemon did not spawn.

  The value keeps the daemon's ordering — in-repo plugin sources first, cached installs after —
  but is a best-effort approximation of the daemon's export: a cached copy of a plugin that an
  in-repo source already covers stays listed, every subdirectory of a cached plugin counts as a
  version, and the newest version is chosen per registry rather than per plugin name.

  Args:
    repo: Repository root whose in-repo plugin sources are scanned.
    cache_root: Plugin-cache root to scan; `~/.claude/plugins/cache` when omitted.

  Returns:
    A tuple of the `os.pathsep`-joined plugin-dir string (possibly empty) and a flag that is
    True when at least one plugin dir was derived; False tells the caller the value is
    best-effort only.
  """
  dirs: list[str] = []

  # Domain(plugin.boundaries):
  # # How a session rebuilds the plugin-directory list the daemon would export
  # The list a process needs to reach sibling plugins keeps the daemon's ordering whether the daemon
  # exports it or a session rebuilds it: every plugin source in the checkout's own plugin tree that
  # carries a manifest comes first, so a resolver that takes the first match prefers live sources
  # over an installed copy of the same plugin, and then the newest cached version of every
  # installed plugin follows, chosen by numeric version order rather than name order so a
  # two-digit component outranks a one-digit one. A directory already listed is never repeated.

  # in a dev vault every in-repo source dir carrying a manifest is a plugin dir, and it leads
  # so a checkout's live sources win over an installed copy of the same plugin
  dev_claude = Path(repo) / _DEV_PLUGINS_REL
  if dev_claude.is_dir():
    for entry in sorted(dev_claude.iterdir()):
      if (entry / _MANIFEST_REL).is_file():
        dirs.append(str(entry.resolve()))

  # then the newest cached version of every installed plugin, so a consumer install with no
  # dev dirs still sees all of its siblings
  # limit: shadowed copies stay, any subdir is a version, one per registry; reuse the daemon's builder to match it
  cache = Path.home() / _PLUGIN_CACHE_REL if cache_root is None else cache_root
  if cache.is_dir():
    for registry in sorted(cache.iterdir()):
      # guard: a non-directory entry under the cache root
      if not registry.is_dir():
        continue
      for plugin in sorted(registry.iterdir()):
        # guard: a non-directory entry under a registry
        if not plugin.is_dir():
          continue

        # guard: plugin dir exists but has no cached versions
        if not (versions := [ version for version in plugin.iterdir() if version.is_dir() ]):
          continue

        # the newest version by numeric order joins the list once
        resolved = str(max(versions, key = lambda version: _compute_version_key(version.name)).resolve())
        if resolved not in dirs:
          dirs.append(resolved)

  # the joined value, and whether anything was found at all
  return os.pathsep.join(dirs), bool(dirs)


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
