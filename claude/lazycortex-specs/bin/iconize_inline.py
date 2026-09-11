"""Inline icon repaint for spec bot commits.

One helper: hand it the repo-relative notes a commit is about to carry and it asks the
obsidian plugin's `sync-paths` op to refresh their icon frontmatter, returning the paths
that actually changed so the caller folds them into the same commit. No separate icons
commit is born, and no coordinator reads a repaint as an operator edit.

Best-effort by contract: a consumer without the obsidian plugin, an unset
`$LAZYCORTEX_PLUGIN_DIRS` and no cached sibling, or a failing worker yields an empty list and never raises.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _cached_sibling_root(name: str) -> Path | None:
  """
  Locate a sibling plugin's newest cached install next to this plugin's own cached install.

  A cached install lives at `<cache>/<registry>/<plugin>/<version>/`, so when this file runs from
  one, the cache root is four levels above `bin/` and every sibling's versions sit under it. A dev
  source tree has no version level above `bin/`, so the walk finds nothing there — the dev layout
  is served by the daemon's env export and each caller's own dev fallback.

  Args:
    name: Sibling plugin name, which is also its cache directory and CLI name.

  Returns:
    The sibling's highest cached version directory, or None outside a cached install or when no
    version of the sibling is cached.
  """
  own = Path(__file__).resolve()
  # guard: not a cached install — a dev checkout has no version directory above bin/
  if not own.parents[1].name.replace(".", "").isdigit():
    return None
  # the cache root sits four levels above bin/: cache/<registry>/<plugin>/<version>/bin
  try:
    cache = own.parents[4]
  except IndexError:
    return None
  versions = [
    version
    for registry in cache.iterdir() if (registry / name).is_dir()
    for version in (registry / name).iterdir()
    if version.is_dir() and version.name.replace(".", "").isdigit()
  ]
  return max(versions, key = lambda v: _version_sort_key(v.name)) if versions else None


def repaint_paths(repo: Path, paths: list[str]) -> list[str]:
  """
  Repaint icon frontmatter for `paths` via the obsidian plugin's `sync-paths` op.

  Resolves the `lazycortex-obsidian` CLI through `$LAZYCORTEX_PLUGIN_DIRS` (the blessed
  cross-plugin contract) and asks it to refresh the named repo-relative notes.

  Notes:
    - Best-effort by design: any failure — plugin absent, environment unset, worker
      exiting non-zero, unparseable output — yields an empty list and never raises.

  Args:
    repo: Absolute path to the repository root.
    paths: Repo-relative POSIX paths of the notes about to be committed.

  Returns:
    Repo-relative paths whose frontmatter the repaint actually changed; empty when the
    repaint was unavailable, failed, or changed nothing.
  """
  # guard: nothing to repaint — skip the subprocess entirely
  if not paths:
    return []

  # walk the plugin-dir registry for the obsidian CLI; absence means no repaint here
  cli = None
  for entry in os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep):
    # guard: empty segments appear when the variable is unset or ends with a separator
    if not entry:
      continue
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    candidate = Path(entry) / "bin" / "lazycortex-obsidian"
    if candidate.is_file():
      cli = candidate
      break
  # plugin-cache fallback — a session (hook, skill) has no daemon export to walk
  if cli is None:
    # waiver: sibling plugin's on-disk CLI layout per dev.plugin-boundaries § 1c, not a domain key
    root = _cached_sibling_root("lazycortex-obsidian")
    cached = None if root is None else root / "bin" / "lazycortex-obsidian"
    if cached is not None and cached.is_file():
      cli = cached
  # guard: no obsidian plugin on this host — repaint silently unavailable
  if cli is None:
    return []

  # run the repaint and read back which notes actually changed
  try:
    proc = subprocess.run(
        # waiver: the obsidian CLI's subcommand vocabulary, owned by lazycortex-obsidian
        [sys.executable, str(cli), "sync-paths", *paths],
        cwd = repo, capture_output = True, text = True, check = False,
    )
    # guard: a failing worker must never block the caller's commit
    if proc.returncode != 0:
      return []
    # waiver: the obsidian CLI's JSON result vocabulary, owned by lazycortex-obsidian
    touched = json.loads(proc.stdout.strip().splitlines()[-1]).get("touched", [])
  except (OSError, ValueError, IndexError):
    return []
  return [p for p in touched if isinstance(p, str)]
