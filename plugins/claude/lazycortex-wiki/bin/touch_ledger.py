from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Encoding the ledger file is read and written with.
_ENCODING = "utf-8"

# Separator between two recorded paths.
_NEWLINE = "\n"

# Append mode — a record never rewrites what earlier records wrote.
_APPEND = "a"


# ----------------------------------------------------------------------------------------
class TouchLedger:
  """
  Append-only record of the repository files a series of runs touched.

  Lets a caller that issues several mutating calls learn afterwards, in one read, every path they wrote.

  Guarantees:
    - Every path read back is repo-relative; an absolute path is never returned.
    - Reading yields paths in first-recorded order, each path once, at its first position.
  """

  # Contract:
  # Every path read back is relative to the repository root, so it can be compared with and
  # joined to other repo-relative paths; an absolute path is never returned.

  # Contract:
  # Paths are returned in the order they were first recorded, and a path recorded more than once
  # appears only at its first position.

  def __init__(self, *, path: Path) -> None:
    """
    Bind the ledger to its file.

    Args:
      path: Ledger file; created on the first record.
    """
    # the ledger file, kept outside the repository so it never dirties the tree
    self._path = Path(path)

  def record(self, repo: Path, paths: list[Path | str]) -> None:
    """
    Append paths to the ledger.

    Notes:
      - Earlier records are never rewritten; an empty batch leaves the file untouched.

    Args:
      repo: Repository root the paths are made relative to.
      paths: Touched paths, absolute inside the repository or already repo-relative.

    Raises:
      ValueError: If an absolute path lies outside the repository.
    """
    # every path is stored relative to the repository root, one per line
    root = Path(repo).resolve()
    lines = [ self.to_repo_rel(root, path) for path in paths ]

    # guard: nothing to record — the file is left as it is
    if not lines:
      return

    # append the batch, creating the file and its directory on the first record
    self._path.parent.mkdir(parents = True, exist_ok = True)
    with self._path.open(_APPEND, encoding = _ENCODING) as handle:
      handle.write("".join(f"{line}{_NEWLINE}" for line in lines))

  def read(self) -> list[str]:
    """
    Return the recorded paths.

    Returns:
      Repo-relative paths in first-recorded order without duplicates; empty when nothing was recorded.
    """
    # guard: no ledger file yet — nothing was recorded
    if not self._path.is_file():
      return []

    # first occurrence wins; blank lines are not paths
    return list(dict.fromkeys(
      line.strip() for line in self._path.read_text(encoding = _ENCODING).split(_NEWLINE) if line.strip()
    ))

  @staticmethod
  def to_repo_rel(root: Path, path: Path | str) -> str:
    """
    Express a path relative to the repository root.

    Args:
      root: Repository root.
      path: Absolute path inside the repository, or a path already relative to it.

    Returns:
      The repo-relative path with forward slashes.

    Raises:
      ValueError: If an absolute path lies outside the repository.
    """
    candidate = Path(path)
    root = Path(root).resolve()

    # a relative path is already repo-relative and is taken as written
    if not candidate.is_absolute():
      return candidate.as_posix()

    # an absolute path inside the repository is stored relative to its root
    return candidate.resolve().relative_to(root).as_posix()
