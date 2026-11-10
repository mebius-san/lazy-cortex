from __future__ import annotations

import subprocess
from dataclasses import dataclass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final, Literal

  from pathlib import Path


# Encoding git's text output is decoded with.
_ENCODING = "utf-8"

# The two outcomes a commit attempt reports.
STATUS_COMMITTED: Final = "committed"
STATUS_UNCHANGED: Final = "unchanged"


# ----------------------------------------------------------------------------------------
class _Git:
  """
  Vocabulary of the git invocations a path-scoped wiki commit is made of.
  """

  # The git executable every step runs
  EXE       = "git"
  # Subcommand that lists the named paths' pending changes
  STATUS    = "status"
  # Flag asking `status` for its stable machine-readable output
  PORCELAIN = "--porcelain"
  # Subcommand that stages the named paths
  ADD       = "add"
  # Subcommand that records the staged paths as a commit
  COMMIT    = "commit"
  # Flag carrying the commit message
  MESSAGE   = "-m"
  # Subcommand that resolves a revision to its identifier
  REV_PARSE = "rev-parse"
  # Revision naming the commit just landed
  HEAD      = "HEAD"
  # Separator ending the options so every following argument is read as a path
  PATHS     = "--"


# ----------------------------------------------------------------------------------------
class WikiCommitError(Exception):
  """
  Failure of a path-scoped wiki commit.

  Raised when a git step of the commit cannot run or exits non-zero; the message carries git's own report.
  """


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class CommitResult:
  """
  Outcome of a path-scoped wiki commit.

  Attributes:
    status: Whether a commit landed or the named paths carried nothing to commit.
    sha: Identifier of the new HEAD after a landed commit, or None when nothing was committed.
  """

  # Whether a commit landed or the named paths carried nothing to commit
  status: Literal["committed", "unchanged"]
  # The new HEAD after a landed commit; None when nothing was committed
  sha: str | None


# ----------------------------------------------------------------------------------------
def commit_paths(repo: Path, paths: list[str], message: str) -> CommitResult:
  """
  Commit exactly the named paths of a repository.

  Guarantees:
    - Content staged in the repository's index by anyone else is never included in the commit and stays staged.
    - A call with no paths, or with paths that carry no changes, commits nothing, does not fail, and reports
      `unchanged` with no commit identifier.

  Args:
    repo: Repository root the commit is made in.
    paths: Repo-relative paths to commit.
    message: Commit message.

  Returns:
    The commit outcome, carrying the new HEAD identifier when a commit landed.

  Raises:
    WikiCommitError: If a git step fails or git cannot be run.
  """

  # Contract:
  # Content that anyone else has staged in the repository's index is NEVER included in the commit;
  # it stays staged, unpublished, whatever the named paths are.

  # Contract:
  # A call with no paths, or whose paths carry no changes, commits nothing, does not fail,
  # and reports `unchanged` with no commit identifier.

  # Domain(runtime.git-safety):
  # # A wiki commit never snapshots the shared index
  # The checkout's index is shared with the operator, other sessions and the runtime's own routines, so
  # whatever it holds at commit time is not the wiki's to publish. A wiki commit therefore stages and
  # commits exactly the paths it names and nothing else. Content anyone else has parked in the index
  # stays there, unpublished, and never rides along under a wiki commit message.

  # guard: nothing to commit
  if not paths:
    return CommitResult(status = STATUS_UNCHANGED, sha = None)

  # stage and commit exactly the named paths; any failing git step fails the commit
  try:
    # guard: no changes among the named paths — clean no-op
    if not _git(repo, _Git.STATUS, _Git.PORCELAIN, _Git.PATHS, *paths).strip():
      return CommitResult(status = STATUS_UNCHANGED, sha = None)
    _git(repo, _Git.ADD, _Git.PATHS, *paths)
    _git(repo, _Git.COMMIT, _Git.MESSAGE, message, _Git.PATHS, *paths)
    sha = _git(repo, _Git.REV_PARSE, _Git.HEAD).strip()
  except (subprocess.CalledProcessError, OSError) as error:
    raise WikiCommitError(f"git commit failed: {error}") from error

  # the commit landed; report the new HEAD
  return CommitResult(status = STATUS_COMMITTED, sha = sha)


def _git(repo: Path, *args: str) -> str:
  """
  Run one git command in the repository and return its output.

  Args:
    repo: Repository root the command runs in.
    args: Git subcommand and its arguments.

  Returns:
    Decoded standard output of the command.

  Raises:
    subprocess.CalledProcessError: If git exits non-zero.
    OSError: If git cannot be started.
  """
  return subprocess.check_output(
    [ _Git.EXE, *args ], cwd = str(repo), text = True, encoding = _ENCODING, stderr = subprocess.PIPE,
  )
