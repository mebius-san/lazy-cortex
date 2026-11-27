"""Runtime job-marker sidecar for review documents, plus the `mark-job` verb that writes it.

The two markers that gate the review loop — which coordinator job is in flight on a document,
which expert job is — live here rather than in the document's frontmatter. Two things follow.
An operator hand-editing a document cannot break the loop by mangling a marker, because the
markers are not in the document at all; and neither setting nor clearing one costs a commit,
because the sidecar is gitignored runtime state.

Store shape — `<repo>/.runtime/lazy-review.jobs.json`, keyed by the document's repo-relative
POSIX path:

    {
      "specs/proposal.md": {
        "coordinator_job": "<job id>" | null,
        "active_job":      "<job id>" | null,
        "pending_wake":    "job-done" | null,
        "last_seen_sha":   "<commit sha>" | null,
        "verdict":         "sufficient" | "new-plan" | null
      }
    }

An absent key and an all-null entry mean the same thing; `update` prunes an entry once every
field is null, so an untouched document leaves no row. Writes are atomic (temp file + rename)
— the daemon's main loop is serial by contract, so nothing beyond atomicity is needed.
`update` refuses to rewrite a sidecar it could not read, so the rows it never saw are not lost;
a sidecar that reads but is no store is moved aside under a `.corrupt-<UTC time>` name before the fresh store
is written.

`read` and `read_store` fall back to the empty store on a sidecar they cannot read, or that reads but is no store,
and never raise. `read_checked` and `find_doc_for_job_checked` are the readers for a decision: each raises `OSError`
on a sidecar that exists but cannot be read, and `MarkerStoreCorruptError`, an `OSError`, on one that reads but is
no store. No reader moves a sidecar aside; `set_aside_corrupt` is the one function other than a writer that does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from keys import JobMarker, Paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import MarkerStoreCorruptError  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The closed field schema of one document's entry. A field outside it is refused, so a typo
# never becomes state.
_FIELDS = (
    JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB, JobMarker.PENDING_WAKE,
    JobMarker.LAST_SEEN_SHA, JobMarker.VERDICT,
)

# Maps the `mark-job` CLI's kind token to the entry field it writes.
_FIELD_BY_KIND = {
    JobMarker.KIND_COORDINATOR: JobMarker.COORDINATOR_JOB,
    JobMarker.KIND_WRITER: JobMarker.ACTIVE_JOB,
}

# Suffix of the same-directory temp file the atomic write renames over the store.
_TMP_SUFFIX = ".tmp"

# What follows the sidecar's own name in the name of the file a corrupt sidecar is moved aside to, and the format
# of the time that ends that name.
_CORRUPT_INFIX = ".corrupt-"
_CORRUPT_TIME_FORMAT = "%Y-%m-%dT%H-%M-%S.%fZ"

# The exit code of the `mark-job` verb when the sidecar cannot be read, moved aside or written.
_EXIT_STORE_FAILED = 1


def sidecar_path(repo: Path) -> Path:
  """
  Return the absolute path of the repository's job-marker sidecar.

  Args:
    repo: Repository root the sidecar belongs to.

  Returns:
    Absolute path of `<repo>/.runtime/lazy-review.jobs.json`, whether or not it exists.
  """
  return repo / Paths.RUNTIME_DIR / Paths.JOBS_SIDECAR


def doc_key(repo: Path, doc: Path) -> str:
  """
  Return the store key for one document.

  Guarantees:
    - Two distinct documents never resolve to the same store key.

  Args:
    repo: Repository root the key is relative to.
    doc: The reviewed document's path, absolute or already repo-relative.

  Returns:
    The document's repo-relative POSIX path, or its absolute POSIX path when it lies
    outside `repo` (a caller mistake that must not collapse two documents onto one key).
  """

  # Contract:
  # Two distinct documents never resolve to the same store key, whether or not they
  # lie inside `repo`.

  try:
    return doc.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return doc.resolve().as_posix()


def empty_entry() -> dict[str, str | None]:
  """
  Return the entry every document has before anything is marked on it.

  Returns:
    Dict carrying every field of the closed schema, each `None`.
  """
  return dict.fromkeys(_FIELDS)


def read_store(repo: Path) -> dict[str, dict]:
  """
  Read the whole sidecar.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    The parsed store, or `{}` when the file is absent, unreadable (bytes that are not UTF-8 text included), or not
    a JSON object. This reader falls back to the empty store, never raises and moves nothing; a writer does not: it
    refuses a store it could not read and moves a corrupt one aside; the checked readers, `read_checked` and
    `find_doc_for_job_checked`, raise on a store they could not read or that is no store.
  """
  path = sidecar_path(repo)
  try:
    data = json.loads(path.read_text(encoding = "utf-8"))
  # `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
  except (OSError, ValueError):
    return {}
  return data if isinstance(data, dict) else {}


def _write_store(repo: Path, store: Mapping[str, dict]) -> None:
  """
  Replace the sidecar with `store` atomically.

  Args:
    repo: Repository root holding the sidecar.
    store: The whole store to serialise.
  """
  path = sidecar_path(repo)
  path.parent.mkdir(parents = True, exist_ok = True)

  # write beside the target and rename over it, so a reader never observes a half-written store
  tmp = path.with_suffix(path.suffix + _TMP_SUFFIX)
  tmp.write_text(json.dumps(store, indent = 2, sort_keys = True) + "\n", encoding = "utf-8")
  os.replace(tmp, path)


def read(repo: Path, doc: Path) -> dict[str, str | None]:
  """
  Read one document's marker entry.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.

  Returns:
    The entry with every field of the closed schema present, unrecorded ones as `None`.
  """
  return _normalise_entry(read_store(repo).get(doc_key(repo, doc)))


def read_checked(repo: Path, doc: Path) -> dict[str, str | None]:
  """
  Read one document's marker entry for a caller that decides an action from it.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.

  Returns:
    The entry with every field of the closed schema present, unrecorded ones as `None`. An absent sidecar gives the
    all-`None` entry.

  Raises:
    OSError: If the sidecar exists but cannot be read.
    MarkerStoreCorruptError: If the sidecar reads but is no store (not UTF-8 text, not valid JSON, not a JSON
      object); the file is left where it is.
  """
  # a sidecar that cannot be read, or that is no store, raises here instead of reading as "nothing recorded"
  return _normalise_entry(_read_checked_store(repo).get(doc_key(repo, doc)))


def _read_checked_store(repo: Path) -> dict[str, dict]:
  """
  Read the whole sidecar for a caller that decides an action from it.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    The parsed store, or `{}` when the sidecar is absent.

  Raises:
    OSError: If the sidecar exists but cannot be read.
    MarkerStoreCorruptError: If the sidecar reads but is no store; the file is left where it is.
  """
  path = sidecar_path(repo)

  # an absent sidecar is an empty store; one that is there but cannot be read raises to the caller as it is
  try:
    raw = path.read_bytes()
  except FileNotFoundError:
    return {}
  store = _parse_store(raw)

  # guard: a sidecar that reads but is no store cannot say what is in flight — the decision is refused, and the
  # file is left where it is for a writer to set aside
  if store is None:
    raise MarkerStoreCorruptError(f"{path} is not a JSON object store")
  return store


def _parse_store(raw: bytes) -> dict[str, dict] | None:
  """
  Parse the bytes of a sidecar as a store.

  Args:
    raw: The sidecar's bytes.

  Returns:
    The parsed store, or `None` when the bytes are not UTF-8 text, not JSON, or not a JSON object.
  """
  # `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
  try:
    data = json.loads(raw.decode("utf-8"))
  except ValueError:
    return None
  return data if isinstance(data, dict) else None


# waiver: `object` is the honest type here — the row is whatever JSON the store holds under the document's key
def _normalise_entry(stored: object) -> dict[str, str | None]:
  """
  Bring one stored row to the closed entry schema.

  Args:
    stored: The row as the store holds it, or `None` when the document has no row; a value that is not a mapping
      counts as no row.

  Returns:
    The entry with every field of the closed schema present, unrecorded and blank ones as `None`.
  """
  entry = empty_entry()

  # guard: nothing recorded for this document — the all-`None` entry is the answer
  if not isinstance(stored, dict):
    return entry
  for field in _FIELDS:
    value = stored.get(field)
    entry[field] = value if isinstance(value, str) and value.strip() else None
  return entry


def _read_store_for_write(repo: Path, *, is_setting_aside: bool = True) -> dict[str, dict]:
  """
  Read the whole sidecar for a caller that is about to replace it or decides an action from it.

  Unlike `read_store`, a sidecar that exists but cannot be read is refused rather than taken for an empty store,
  and one that reads but is no store is moved aside before the empty store is returned, unless the caller is
  only reading and asks for it to be left where it is.

  Args:
    repo: Repository root holding the sidecar.
    is_setting_aside: Whether a file that is no store is moved aside; when False it is left where it is.

  Returns:
    The parsed store, or `{}` when the file is absent, or is no store and was moved aside (or, with
    `is_setting_aside` False, left where it is). When the move finds the file already gone, the store is read once
    more and what stands there now is returned.

  Raises:
    OSError: If the file exists but cannot be read, or cannot be moved aside for a reason other than its being gone.
  """
  path = sidecar_path(repo)

  # an absent sidecar is an empty store; one that is there but cannot be read holds rows nobody saw, and that
  # failure goes to the caller as it is
  try:
    raw = path.read_bytes()
  except FileNotFoundError:
    return {}

  # a store that parsed as a JSON object is returned as it is
  if (data := _parse_store(raw)) is not None:
    return data

  # what was read is no store: its bytes are kept under another name before anything is written in its place
  if not is_setting_aside or _set_aside(path):
    return {}

  # the file was already gone at the move: the store is read once more and what stands there now is used
  return _read_store_for_write(repo, is_setting_aside = False)


def _set_aside(path: Path) -> bool:
  """
  Move a sidecar that is no store to a time-stamped sibling and report the move.

  Args:
    path: The sidecar file to move aside.

  Returns:
    True when this call moved the file aside and reported it; False when the file was already gone.

  Raises:
    OSError: If the move fails for a reason other than the file's absence.
  """
  # the sibling name carries the time down to the microsecond, so two files set aside never share a name
  aside = path.with_name(f"{path.name}{_CORRUPT_INFIX}{datetime.now(UTC).strftime(_CORRUPT_TIME_FORMAT)}")

  # a file that is already gone leaves nothing to move and nothing to report
  try:
    os.replace(path, aside)
  except FileNotFoundError:
    return False

  # the operator is told where the bytes went
  sys.stderr.write(
      f"job_markers: {path} is not a JSON object store; moved aside to {aside}, the store starts empty\n"
  )
  return True


def find_doc_for_job_checked(repo: Path, job_id: str) -> str | None:
  """
  Find the document whose `active_job` marker names one job, for a caller that decides an action from it.

  Args:
    repo: Repository root holding the sidecar.
    job_id: The expert job id to look up, as recorded by `mark-job <file> writer <id>`.

  Returns:
    The document's store key (repo-relative POSIX path), or `None` when no entry's `active_job` carries the id. An
    absent sidecar names no document.

  Raises:
    OSError: If the sidecar exists but cannot be read.
    MarkerStoreCorruptError: If the sidecar reads but is no store; the file is left where it is.
  """
  # guard: a blank id can never identify a job
  if not job_id.strip():
    return None

  # a sidecar that cannot be read, or that is no store, raises here instead of reading as "no document"; nothing
  # is moved aside
  return _find_job_key(_read_checked_store(repo), job_id)


def set_aside_corrupt(repo: Path) -> bool:
  """
  Move a sidecar that reads but is no store aside, without writing a new store.

  Guarantees:
    - A sidecar that reads but is no store (not UTF-8 text, not valid JSON, or not a JSON object) is moved aside,
      bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`, the move is reported as one line on
      stderr naming both paths, and the call returns True.
    - An absent sidecar and a sidecar that is a valid store are left alone, and the call returns False.
    - A sidecar that cannot be read, or a move that fails for a reason other than the file being gone, raises
      `OSError`, and the sidecar keeps its bytes under its own name.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    True when this call moved a corrupt sidecar aside; False when the sidecar is absent, is a valid store, or was
    already gone at the move.

  Raises:
    OSError: If the sidecar exists but cannot be read, or cannot be moved aside for a reason other than its being
      gone.
  """

  # Contract:
  # A sidecar that reads but is no store (it is not UTF-8 text, not valid JSON, or not a JSON object) is moved aside,
  # bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`; the move is reported as one line on
  # stderr naming both paths, and the call returns True. An absent sidecar and a sidecar that is a valid store are
  # NEVER moved: the call returns False. A sidecar that cannot be read, or a move that fails for a reason other than
  # the file being gone, raises `OSError`, and the sidecar keeps its bytes under its own name.

  path = sidecar_path(repo)

  # an absent sidecar holds nothing to set aside; one that cannot be read raises, since its content is unknown
  try:
    raw = path.read_bytes()
  except FileNotFoundError:
    return False

  # guard: a sidecar that is a store stays where it is
  if _parse_store(raw) is not None:
    return False

  # the bytes are kept under another name and the move is reported, so the next reader starts from an empty store
  return _set_aside(path)


def _find_job_key(store: Mapping[str, dict], job_id: str) -> str | None:
  """
  Find the store key of the entry whose `active_job` marker names one job.

  Args:
    store: The whole parsed store.
    job_id: The expert job id to look up.

  Returns:
    The key of the first entry whose `active_job` carries the id, or `None` when none does.
  """
  # scan the whole store — the sidecar is one small JSON object, keyed by document
  for key, entry in store.items():
    # guard: only a dict entry carries the closed marker schema
    if not isinstance(entry, dict):
      continue
    if entry.get(JobMarker.ACTIVE_JOB) == job_id:
      return key
  return None


def update(repo: Path, doc: Path, changes: Mapping[str, str | None]) -> dict[str, str | None]:
  """
  Apply `changes` to one document's entry and persist the store.

  Guarantees:
    - Once every field of the resulting entry is null, the document's row is removed from
      the store rather than kept as an all-null entry.
    - Never writes over a store it could not read: when the sidecar file exists but reading it fails with an
      `OSError`, the error is raised and the file is left as it is, so the rows of other documents survive.
      An absent sidecar is an empty store. `clear` behaves the same.
    - A sidecar that reads but is no store (not UTF-8 text, not valid JSON, or not a JSON object) is first moved
      aside, bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`; the move is reported as one
      line on stderr naming both paths; only then does the store start empty, so the write that follows holds only
      the caller's row. A move that finds the sidecar already gone is not an error: the store is read again once,
      what stands under the name then is used (an absent sidecar reads as empty), and this call makes no report.
      Any other failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes
      under its own name. Readers never move anything and leave such a file where it is: `read` and `read_store`
      read it as an empty store, and `read_checked` and `find_doc_for_job_checked` refuse it by raising
      `MarkerStoreCorruptError`, an `OSError`. `clear` behaves the same.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.
    changes: Field-to-value mapping; a `None` value clears that field.

  Returns:
    The document's resulting entry.

  Raises:
    ValueError: If `changes` names a field outside the closed schema.
    OSError: If the sidecar exists but cannot be read, cannot be moved aside as no store for a reason other than
      its being gone, or the new store cannot be written.
  """

  # Contract:
  # Once every field of the resulting entry is null, the document's row is removed from
  # the store rather than kept as an all-null entry.

  # Contract:
  # `update` NEVER writes over a store it could not read. When the sidecar file exists but reading it
  # fails with an `OSError`, `update` raises that `OSError` and writes nothing: the file is left as it
  # is, so the rows of the other documents survive. A sidecar that is plainly absent is an empty store.
  # `clear` goes through `update` and behaves the same.

  # Contract:
  # A sidecar that reads but is no store (it is not UTF-8 text, not valid JSON, or not a JSON object) is first moved
  # aside, bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`. The move is reported as one
  # line on stderr naming both paths, and only then does the store start empty, so the write that follows holds only
  # the caller's row. A move that finds the sidecar already gone is not an error: the store is read again once, what
  # stands under the name then is used (an absent sidecar reads as empty), and this call makes no report. Any other
  # failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes under its own
  # name. Readers NEVER move anything and leave such a file where it is: `read` and `read_store` read it as an
  # empty store, and `read_checked` and `find_doc_for_job_checked` refuse it by raising `MarkerStoreCorruptError`,
  # an `OSError`. `clear` goes through `update` and behaves the same.

  # Domain(review.jobs):
  # # Job markers live outside the document
  # The review loop's job-in-flight state is tracked outside the document being reviewed, in
  # a runtime store keyed by the document's own path. Because the markers never enter the
  # document, an operator hand-editing the document cannot corrupt the loop's understanding of
  # what job is running by mangling a marker, and setting or clearing a marker never requires a
  # commit of its own — the document's git history stays a record of content, not of the
  # loop's internal bookkeeping.

  unknown = [field for field in changes if field not in _FIELDS]

  # guard: a field outside the schema is a typo, and a typo must not become state
  if unknown:
    raise ValueError(f"mark-job: field(s) {unknown} are not in the marker schema {list(_FIELDS)}")

  # the store is read once, and a store that cannot be read stops the update before anything is written
  store = _read_store_for_write(repo)
  key = doc_key(repo, doc)

  # overlay the changes on the current entry, normalising a blank id to the absent marker
  entry = _normalise_entry(store.get(key))
  for field, value in changes.items():
    entry[field] = value.strip() if isinstance(value, str) and value.strip() else None

  # an all-`None` entry is indistinguishable from an absent one, so drop the row instead
  if any(entry.values()):
    store[key] = entry
  else:
    store.pop(key, None)
  _write_store(repo, store)
  return entry


def clear(repo: Path, doc: Path) -> None:
  """
  Drop one document's entry entirely.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.

  Raises:
    OSError: If the sidecar exists but cannot be read, cannot be moved aside as no store for a reason other than
      its being gone, or the new store cannot be written.
  """
  # clearing every field of the schema at once is what prunes the row from the store
  update(repo, doc, dict.fromkeys(_FIELDS))


def clear_verdict(repo: Path, doc: Path) -> None:
  """
  Drop the verdict recorded for one document, and nothing else.

  Guarantees:
    - Every other field of the document's entry is kept as it is.
    - A document with no verdict recorded leaves the sidecar untouched, so no sidecar file appears for it.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.

  Raises:
    OSError: If a recorded verdict is to be cleared and the sidecar cannot be rewritten as `update` describes.
  """

  # Contract:
  # Every other field of the document's entry is kept as it is.

  # Contract:
  # A document with no verdict recorded leaves the sidecar untouched, so no sidecar file appears for it.

  # guard: nothing recorded, nothing to clear, and the sidecar stays as it is
  if read(repo, doc)[JobMarker.VERDICT] is None:
    return
  update(repo, doc, { JobMarker.VERDICT: None })


def main(argv: list[str]) -> int:
  """
  Write one job marker from the command line, printing the resulting entry as JSON.

  Invoked as `mark-job <file> coordinator|writer <id>` to set a marker, or with `--clear`
  in place of the id to drop it. Clearing a marker that was never set is a no-op success.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the working directory); the marker is kept for the checkout that directory
      sits in.

  Returns:
    Exit code: 0 on success; 1 when the sidecar cannot be read, moved aside or written, with one line naming the
    sidecar and the error on stderr and nothing on stdout; 2 when neither a job id nor `--clear` was given.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-review mark-job")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("kind", choices = list(_FIELD_BY_KIND))
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("job_id", nargs = "?", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--clear", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = None)
  args = parser.parse_args(argv)

  # guard: exactly one of the two forms must be used — an id, or the explicit clear
  if bool(args.job_id) == bool(args.clear):
    # waiver: one-off CLI usage message, not a domain token compared anywhere
    sys.stderr.write("mark-job: pass either a job id or --clear, not both and not neither\n")
    return 2

  # a relative `file` resolves against the root of the checkout `--repo`, `$LAZY_REPO_ROOT` or the cwd sits in; an
  # absolute one is taken as is
  # (pathlib drops the left operand of `/` when the right one is absolute). The document need
  # not exist on disk: the marker is runtime state about a path, and a clear on a document that
  # was just finalized away is exactly the case that must still work.
  repo = _review_locator.query_repo_root(args.repo)
  try:
    entry = update(repo, repo / args.file, { _FIELD_BY_KIND[args.kind]: None if args.clear else args.job_id })
  # a sidecar that cannot be read, moved aside or written is reported in one line, and nothing is printed
  except OSError as error:
    sys.stderr.write(f"mark-job: {sidecar_path(repo)}: {type(error).__name__}: {error}\n")
    return _EXIT_STORE_FAILED
  print(json.dumps(entry))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
