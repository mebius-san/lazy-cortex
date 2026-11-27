from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import Trailer  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The `git cat-file --batch` answer for an object it cannot find, and the field count of a found object's header
# (`<sha> <type> <size>`), whose last field is the object's size.
_MISSING = b"missing"
_FOUND_HEADER_FIELDS = 3

# How undecodable bytes of git's output are read: replaced, never fatal.
_DECODE_ERRORS = "replace"

# The log format of one commit: a record separator, then sha, author address and message, each closed by a unit
# separator, so the name-status fields git prints after the message follow the last one.
_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"
_LOG_FORMAT = "%x1e%H%x1f%ae%x1f%B%x1f"
_HEADER_FIELDS = 3

# The separator `-z` puts between name-status fields, and the field count of a rename: code, old path, new path.
_NUL = "\x00"
_RENAME_FIELDS = 3

# How a path name that is not UTF-8 text is read and written back to git: kept byte for byte.
_PATH_ERRORS = "surrogateescape"

# The name-status codes of a commit that moved the file: a rename, or a copy git reports as one.
_RENAME_CODES = ( "R", "C" )


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class RevisionRecord:
  """
  One commit of a document's history, with the document's text before and after it.

  Attributes:
    sha: Full SHA of the commit.
    author_email: Author address of the commit.
    body: Full commit message.
    parent_text: The document's text in the commit's parent revision, `None` when the parent has no such file.
    text: The document's text in the commit's own revision, `None` when the commit deleted the file.
  """

  sha: str
  author_email: str
  body: str
  parent_text: str | None
  text: str | None


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _CommitRecord:
  """
  One commit of a document's history as the rename-following log reports it.

  Attributes:
    sha: Full SHA of the commit.
    author_email: Author address of the commit.
    body: Full commit message.
    path: Repository-relative path the document has in the commit.
    parent_path: Repository-relative path the document had in the commit's parent.
  """

  sha: str
  author_email: str
  body: str
  path: str
  parent_path: str


# ----------------------------------------------------------------------------------------
def _read_blobs(repo: Path, specs: Iterable[str]) -> dict[str, str | None]:
  """
  Read several `<rev>:<path>` objects in one git call.

  Notes:
    - Runs git as a subprocess in `repo` and reads the repository without changing it.

  Args:
    repo: Repository root.
    specs: Object names in `<rev>:<path>` form.

  Returns:
    Each requested name mapped to its text, or to `None` when git has no such object.

  Raises:
    RuntimeError: If git cannot be run or exits non-zero.
  """
  # one batch process answers every name, in request order
  names = list(dict.fromkeys(specs))
  try:
    proc = subprocess.run(
        [ "git", "cat-file", "--batch" ],
        cwd = repo, input = "".join(f"{name}\n" for name in names).encode("utf-8", errors = _PATH_ERRORS),
        capture_output = True, check = False,
    )
  except OSError as error:
    raise RuntimeError(f"git cannot be run: {error}") from error

  # guard: a failed batch leaves every answer unknown
  if proc.returncode != 0:
    raise RuntimeError(f"git cat-file failed: {proc.stderr.decode(errors = _DECODE_ERRORS).strip()}")

  # each answer is a header line, then for a found object its bytes and a newline
  pos = 0
  blobs: dict[str, str | None] = {}
  for name in names:
    eol = proc.stdout.index(b"\n", pos)
    header = proc.stdout[pos:eol].split()
    pos = eol + 1

    # guard: an object git cannot find carries no bytes after its header
    if header[-1] == _MISSING or len(header) != _FOUND_HEADER_FIELDS:
      blobs[name] = None
      continue

    # the found object's bytes, then the newline git closes every answer with
    size = int(header[-1])
    blobs[name] = proc.stdout[pos:pos + size].decode("utf-8", errors = _DECODE_ERRORS)
    pos += size + 1
  return blobs


def _read_log(repo: Path, rel: str) -> list[_CommitRecord]:
  """
  Read the document's commits newest first, following renames.

  Each commit carries the path the document had after it and the path it had before it; a commit that is not a
  rename keeps one path for both.

  Notes:
    - Runs `git log` as a subprocess in `repo` and reads the repository without changing it.

  Args:
    repo: Repository root.
    rel: The document's current path relative to `repo`.

  Returns:
    The document's commits, newest first.

  Raises:
    RuntimeError: If git cannot be run or exits non-zero.
  """
  # one log across renames: each commit's header, then its NUL-separated name-status naming the path before and
  # after, path names read byte-safe
  try:
    proc = subprocess.run(
        [ "git", "--literal-pathspecs", "log", "--follow", "-M", "-z", f"--format={_LOG_FORMAT}", "--name-status",
          "--", rel ],
        cwd = repo, capture_output = True, check = False,
    )
  except OSError as error:
    raise RuntimeError(f"git cannot be run: {error}") from error

  # guard: a failed log leaves the history unknown
  if proc.returncode != 0:
    raise RuntimeError(f"git log failed: {proc.stderr.decode(errors = _DECODE_ERRORS).strip()}")

  # newest first, the path the file has after each commit is the path it had before the newer one
  commits: list[_CommitRecord] = []
  path = rel
  for chunk in proc.stdout.decode("utf-8", errors = _PATH_ERRORS).split(_RECORD_SEP)[1:]:
    sha, email, body, status = chunk.split(_FIELD_SEP, _HEADER_FIELDS)
    fields = [ token.strip("\n") for token in status.split(_NUL) if token.strip("\n") ]
    before = fields[1] if len(fields) > _RENAME_FIELDS - 1 and fields[0][:1] in _RENAME_CODES else path
    commits.append(_CommitRecord(sha = sha, author_email = email, body = body, path = path, parent_path = before))
    path = before
  return commits


def read_revisions(repo: Path, rel: str) -> list[RevisionRecord]:
  """
  Return the document's commits newest first, each with the document's text before and after it.

  Guarantees:
    - The history follows renames: each revision's text is read under the name the document had in it, so a pure
      rename carries equal text on both sides.

  Notes:
    - Runs git as a subprocess in `repo` and reads the repository without changing it.

  Args:
    repo: Repository root.
    rel: The document's current path relative to `repo`.

  Returns:
    The document's commits, newest first.

  Raises:
    RuntimeError: If git cannot be run or exits non-zero.
  """

  # Contract:
  # The history follows renames: each revision's text is read under the name the document had in that revision,
  # so a pure rename carries equal text on both sides and NEVER reads as a rewrite of the whole document.

  # every commit's own and parent revision are read in one batch, at the path the file had in each
  commits = _read_log(repo, rel)
  blobs = _read_blobs(
      repo, [ spec for rec in commits for spec in ( f"{rec.sha}:{rec.path}", f"{rec.sha}^:{rec.parent_path}" ) ],
  )

  # each commit pairs with its two texts
  return [
      RevisionRecord(
          sha = rec.sha, author_email = rec.author_email, body = rec.body,
          parent_text = blobs[f"{rec.sha}^:{rec.parent_path}"], text = blobs[f"{rec.sha}:{rec.path}"],
      )
      for rec in commits
  ]


def is_watch_skip(record: RevisionRecord) -> bool:
  """
  Report whether a commit is bookkeeping no watch reacts to.

  Args:
    record: The commit.

  Returns:
    True when the commit carries the `Lazy-Watch: skip` trailer, compared case-insensitively.
  """
  return Trailer.WATCH_SKIP in [ val.lower() for val in _git_ops.parse_trailer_values(record.body, Trailer.WATCH) ]
