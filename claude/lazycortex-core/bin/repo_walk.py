"""
Tree walk that honours git's ignore engine plus a repo `.lazyignore` excludes file.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterator


class RepoWalk:
  """
  Repo file enumeration with git-ignore-aware exclusion.

  Excludes any path git would ignore — `.git/info/exclude`, every `.gitignore`, and the repo's
  `.lazyignore` wired as `core.excludesFile`. A tracked path listed in `.lazyignore` is still
  excluded from the walk. Outside a git repository, enumeration falls back to walking the full
  directory tree, excluding only `.git`.
  """

  _NUL = "\x00"
  # waiver: filesystem sentinel names — not interchangeable values; Enum adds no clarity
  _GIT_DIR = ".git"
  _LAZYIGNORE = ".lazyignore"

  def __init__(self, repo: Path) -> None:
    """
    Bind the walker to one repository root.

    Args:
      repo: Absolute path to the repository root to enumerate.
    """
    self._repo = Path(repo)
    self._excludes = self._repo / self._LAZYIGNORE

  def _ignored(self, rels: list[str]) -> set[str]:
    """
    Return the subset of candidate paths that git's ignore stack excludes.

    Args:
      rels: Repo-relative candidate paths to check.

    Returns:
      The subset of `rels` that git ignores. Empty when `rels` is empty or when the check
      cannot run (not a git repository, or a git failure).
    """
    # guard: nothing to check
    if not rels:
      return set()
    cmd = [ "git" ]
    # wire the repo `.lazyignore` in as git's global excludes source when the file is present
    if self._excludes.is_file():
      cmd += [ "-c", f"core.excludesFile={self._excludes}" ]
    cmd += [ "check-ignore", "--no-index", "--stdin", "-z" ]
    blob = self._NUL.join(rels) + self._NUL
    proc = subprocess.run(
      cmd, cwd = str(self._repo),
      input = blob, capture_output = True, text = True, check = False,
    )
    # git check-ignore: rc 0 = some ignored, 1 = none ignored, >1 = real error
    # guard: not a git repo / git failure — exclude nothing rather than crash the tick
    if proc.returncode not in ( 0, 1 ):
      return set()
    return { p for p in proc.stdout.split(self._NUL) if p }

  def _git_list(self) -> list[str] | None:
    """
    Enumerate candidate repo-relative paths in one `git ls-files` call.

    Lists tracked plus untracked-non-ignored paths, honouring the standard
    ignore stack and the repo `.lazyignore` wired as `core.excludesFile`.

    Returns:
      Ordered, de-duplicated repo-relative POSIX paths, or `None` when git
      is unavailable or the directory is not a repository.
    """
    cmd = [ "git" ]
    # wire the repo `.lazyignore` in as git's global excludes source when the file is present
    if self._excludes.is_file():
      cmd += [ "-c", f"core.excludesFile={self._excludes}" ]
    cmd += [ "ls-files", "-co", "--exclude-standard", "-z" ]
    proc = subprocess.run(
      cmd, cwd = str(self._repo),
      capture_output = True, text = True, check = False,
    )
    # guard: not a git repo / git failure — signal the caller to fall back
    if proc.returncode != 0:
      return None
    # dedupe while keeping order: `ls-files -c` repeats a path once per merge stage
    return list(dict.fromkeys( p for p in proc.stdout.split(self._NUL) if p ))

  def iter_files(self) -> Iterator[Path]:
    """
    Yield every non-ignored file path under the repository root.

    A tracked path listed in `.lazyignore` is still excluded. Outside a git repository, the
    walk falls back to the full directory tree, excluding only `.git`.

    Yields:
      Absolute `Path` objects for each file that survives the ignore filters.
    """
    repo = self._repo
    rels = self._git_list()
    # guard: git enumeration unavailable — walk everything except git internals
    if rels is None:
      for base, dirs, files in os.walk(str(repo)):
        dirs[ : ] = [ d for d in dirs if d != self._GIT_DIR ]
        for f in files:
          yield Path(base) / f
      return
    # one batch check: `ls-files -c` lists tracked paths even when the ignore stack
    # excludes them (a tracked dir in `.lazyignore`) — `--no-index` filters those out
    ignored = self._ignored(rels)
    for rel in rels:
      # guard: tracked path excluded by the git ignore stack / .lazyignore
      if rel in ignored:
        continue
      full = repo / rel
      # guard: index entry with no worktree file (staged delete, submodule)
      if not full.is_file():
        continue
      yield full
