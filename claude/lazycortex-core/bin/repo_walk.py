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

  Excludes any path git would ignore — `.git/info/exclude`, every `.gitignore`,
  and the repo's `.lazyignore` wired as `core.excludesFile`. `--no-index` makes
  the check apply to tracked paths too, so a tracked directory listed in
  `.lazyignore` is still excluded from the walk.
  """

  _NUL = "\x00"
  # waiver: filesystem sentinel names — not interchangeable values; Enum adds no clarity
  _GIT_DIR = ".git"
  _LAZYIGNORE = ".lazyignore"

  def __init__(self, repo: Path) -> None:
    self._repo = Path(repo)
    self._excludes = self._repo / self._LAZYIGNORE

  def _ignored(self, rels: list[str]) -> set[str]:
    # guard: nothing to check
    if not rels:
      return set()
    cmd = [ "git" ]
    # guard: a .lazyignore exists — add it as the global excludes source
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

  def iter_files(self) -> Iterator[Path]:
    """
    Yield every non-ignored file path under the repository root.

    Walks the repository tree using `os.walk`, pruning `.git` and any directory
    that git's ignore engine (including `.lazyignore`) marks as excluded.
    Individual files within non-ignored directories are also filtered through
    the same ignore check before being yielded.

    Yields:
      Absolute `Path` objects for each file that survives the ignore filters.
    """
    repo = self._repo
    for base, dirs, files in os.walk(str(repo)):
      # guard: never descend into git internals
      dirs[ : ] = [ d for d in dirs if d != self._GIT_DIR ]
      dir_rels = [ (Path(base) / d).relative_to(repo).as_posix() for d in dirs ]
      ignored_dirs = self._ignored(dir_rels)
      # prune ignored subdirs in place so os.walk does not descend into them
      dirs[ : ] = [
        d for d in dirs
        if (Path(base) / d).relative_to(repo).as_posix() not in ignored_dirs
      ]
      file_rels = [ (Path(base) / f).relative_to(repo).as_posix() for f in files ]
      ignored_files = self._ignored(file_rels)
      for f in files:
        full = Path(base) / f
        # guard: file excluded by the git ignore stack / .lazyignore
        if full.relative_to(repo).as_posix() in ignored_files:
          continue
        yield full
