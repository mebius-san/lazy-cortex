"""
Heal a `.git/index` displaced by a cloud-sync conflict resolution, when healing is provably safe.

A sync client racing git's rename-replace of `.git/index` resolves the conflict by keeping an
older version under the real name and renaming the newer local write to
`index (<owner>'s conflicted copy <date>)`. The observable damage is a resurrected pre-commit
index: `git status` shows phantom staged content nobody staged. This module restores the newest
conflicted copy — the version git actually wrote last, parked operator staging included — back
onto `.git/index`, and removes the conflicted-copy litter afterwards.

The heal is file-level and conservative: it runs only when no `index.lock` is present (no git
operation in flight), only when the newest copy is strictly newer than the live index, and only
when that copy carries the index signature. Anything else leaves the repository untouched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Dropbox names every displaced version `<name> (<owner>'s conflicted copy <date>...)`; the
# glob keys on the invariant middle so an owner rename or a numbered suffix still matches.
_CONFLICTED_COPY_GLOB = "index (*conflicted copy*"

# First four bytes of every git index file, any version (git's on-disk signature).
_INDEX_SIGNATURE = b"DIRC"

# The shared index and git's own write lock, by their fixed names inside the git dir.
_INDEX_NAME = "index"
_INDEX_LOCK_NAME = "index.lock"

# Staging name for the atomic restore — written fully, then renamed over the live index.
_STAGING_NAME = "index-guard.tmp"


def _git_common_dir(repo_root: Path) -> Path | None:
  """
  Resolve the repository's common git directory, where the shared index lives.

  Args:
    repo_root: Absolute path to the repository root.

  Returns:
    The absolute common git dir, or None when `repo_root` is not a git repository.
  """
  probe = subprocess.run(
    [ "git", "rev-parse", "--git-common-dir" ],
    cwd = repo_root, check = False, capture_output = True, text = True,
  )
  # guard: not a repository — nothing to heal
  if probe.returncode != 0:
    return None
  return (repo_root / probe.stdout.strip()).resolve()


def guard_index(repo_root: Path) -> dict:
  """
  Restore the newest conflicted copy of `.git/index` when it is newer than the live file, and
  remove the conflicted-copy litter.

  Guarantees:
    - The live index is replaced only by a strictly newer conflicted copy that carries the git
      index signature, and never while `index.lock` exists.
    - The worktree, HEAD, and refs are never touched.
    - Conflicted copies are removed only after the newest one was restored or proved stale.

  Args:
    repo_root: Absolute path to the repository root.

  Returns:
    A report dict: `restored` (bool), `removed` (count of copies deleted), and `skipped`
    (None, or the reason the heal did not run: `no-git`, `index-lock`).
  """
  git_dir = _git_common_dir(repo_root)
  # guard: not a repository — nothing to heal
  if git_dir is None:
    return { "restored": False, "removed": 0, "skipped": "no-git" }

  # oldest-to-newest, so the last element is the one candidate worth restoring
  copies = sorted(git_dir.glob(_CONFLICTED_COPY_GLOB), key = lambda p: p.stat().st_mtime)
  # guard: no conflicted copies — the common case, exit without touching anything
  if not copies:
    return { "restored": False, "removed": 0, "skipped": None }

  # guard: a git operation is mid-flight — retry on the next invocation
  if (git_dir / _INDEX_LOCK_NAME).exists():
    return { "restored": False, "removed": 0, "skipped": "index-lock" }

  # restore only a strictly newer, signature-valid copy — the version git wrote last that the
  # sync client displaced; an older copy is litter from an already-resolved incident
  index = git_dir / _INDEX_NAME
  newest = copies[-1]
  restored = False
  if (
    index.exists()
    and newest.stat().st_mtime > index.stat().st_mtime
    and newest.read_bytes()[:4] == _INDEX_SIGNATURE
  ):
    # copy-then-rename: the live index is never observable half-written
    staging = git_dir / _STAGING_NAME
    shutil.copy2(newest, staging)
    os.replace(staging, index)
    restored = True

  # every copy is settled now — restored, or proved stale by the newest-wins comparison
  removed = 0
  for copy in copies:
    copy.unlink(missing_ok = True)
    removed += 1
  return { "restored": restored, "removed": removed, "skipped": None }


def main(argv: list[str] | None = None) -> int:
  """
  CLI entry point: heal the current repository's index and print a one-line JSON report.

  Args:
    argv: Unused; present for dispatcher-signature uniformity.

  Returns:
    Process exit code — always 0; a repository without healable state is a healthy outcome.
  """
  del argv
  report = guard_index(Path.cwd())
  print(json.dumps({ "op": "index-guard", **report }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
