"""Inline icon repaint for spec bot commits.

One helper: hand it the repo-relative notes a commit is about to carry and it asks the
obsidian plugin's `sync-paths` op to refresh their icon frontmatter, returning the paths
that actually changed so the caller folds them into the same commit. No separate icons
commit is born, and no coordinator reads a repaint as an operator edit.

Best-effort by contract: a consumer without the obsidian plugin, an unset
`$LAZYCORTEX_PLUGIN_DIRS`, or a failing worker yields an empty list and never raises.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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
  # guard: no obsidian plugin on this host — repaint silently unavailable
  if cli is None:
    return []

  # run the repaint and read back which notes actually changed
  try:
    proc = subprocess.run(
        # waiver: the obsidian CLI's subcommand vocabulary, owned by lazycortex-obsidian
        [str(cli), "sync-paths", *paths],
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
