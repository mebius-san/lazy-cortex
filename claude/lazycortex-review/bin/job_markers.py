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
        "pending_wake":    "job-done" | null
      }
    }

An absent key and an all-null entry mean the same thing; `update` prunes an entry once every
field is null, so an untouched document leaves no row. Writes are atomic (temp file + rename)
— the daemon's main loop is serial by contract, so nothing beyond atomicity is needed.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobMarker, Paths  # noqa: E402


# The closed field schema of one document's entry. A field outside it is refused the way
# `set-key` refuses a frontmatter key outside its own schema — a typo must not become state.
_FIELDS = (JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB, JobMarker.PENDING_WAKE)

# Maps the `mark-job` CLI's kind token to the entry field it writes.
_FIELD_BY_KIND = {
    JobMarker.KIND_COORDINATOR: JobMarker.COORDINATOR_JOB,
    JobMarker.KIND_WRITER: JobMarker.ACTIVE_JOB,
}

# Suffix of the same-directory temp file the atomic write renames over the store.
_TMP_SUFFIX = ".tmp"


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

  Args:
    repo: Repository root the key is relative to.
    doc: The reviewed document's path, absolute or already repo-relative.

  Returns:
    The document's repo-relative POSIX path, or its absolute POSIX path when it lies
    outside `repo` (a caller mistake that must not collapse two documents onto one key).
  """
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


def _read_store(repo: Path) -> dict[str, dict]:
  """
  Read the whole sidecar.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    The parsed store, or `{}` when the file is absent, unreadable, or not a JSON object —
    a corrupt sidecar is runtime scratch and re-derives itself, so it never fails a tick.
  """
  path = sidecar_path(repo)
  try:
    data = json.loads(path.read_text())
  except (OSError, json.JSONDecodeError):
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
  tmp.write_text(json.dumps(store, indent = 2, sort_keys = True) + "\n")
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
  entry = empty_entry()
  stored = _read_store(repo).get(doc_key(repo, doc))
  # guard: nothing recorded for this document — the all-`None` entry is the answer
  if not isinstance(stored, dict):
    return entry
  for field in _FIELDS:
    value = stored.get(field)
    entry[field] = value if isinstance(value, str) and value.strip() else None
  return entry


def doc_for_job(repo: Path, job_id: str) -> str | None:
  """
  Find the document whose `active_job` marker names one job.

  Args:
    repo: Repository root holding the sidecar.
    job_id: The expert job id to look up, as recorded by `mark-job <file> writer <id>`.

  Returns:
    The document's store key (repo-relative POSIX path), or `None` when no entry's
    `active_job` carries the id.
  """
  # guard: a blank id can never identify a job
  if not job_id.strip():
    return None

  # scan the whole store — the sidecar is one small JSON object, keyed by document
  for key, entry in _read_store(repo).items():
    # guard: only a dict entry carries the closed marker schema
    if not isinstance(entry, dict):
      continue
    if entry.get(JobMarker.ACTIVE_JOB) == job_id:
      return key
  return None


def update(repo: Path, doc: Path, changes: Mapping[str, str | None]) -> dict[str, str | None]:
  """
  Apply `changes` to one document's entry and persist the store.

  Args:
    repo: Repository root holding the sidecar.
    doc: The reviewed document's path.
    changes: Field-to-value mapping; a `None` value clears that field.

  Returns:
    The document's resulting entry.

  Raises:
    ValueError: If `changes` names a field outside the closed schema.
  """
  unknown = [field for field in changes if field not in _FIELDS]
  # guard: a field outside the schema is a typo, and a typo must not become state
  if unknown:
    raise ValueError(f"mark-job: field(s) {unknown} are not in the marker schema {list(_FIELDS)}")

  # overlay the changes on the current entry, normalising a blank id to the absent marker
  entry = read(repo, doc)
  for field, value in changes.items():
    entry[field] = value.strip() if isinstance(value, str) and value.strip() else None

  # an all-`None` entry is indistinguishable from an absent one, so drop the row instead
  store = _read_store(repo)
  key = doc_key(repo, doc)
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
  """
  # clearing every field of the schema at once is what prunes the row from the store
  update(repo, doc, dict.fromkeys(_FIELDS))


def main(argv: list[str]) -> int:
  """
  Write one job marker from the command line, printing the resulting entry as JSON.

  Invoked as `mark-job <file> coordinator|writer <id>` to set a marker, or with `--clear`
  in place of the id to drop it. Clearing a marker that was never set is a no-op success.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when neither a job id nor `--clear` was given.
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
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # guard: exactly one of the two forms must be used — an id, or the explicit clear
  if bool(args.job_id) == bool(args.clear):
    # waiver: one-off CLI usage message, not a domain token compared anywhere
    sys.stderr.write("mark-job: pass either a job id or --clear, not both and not neither\n")
    return 2

  # `file` resolves against `--repo` unless it is already absolute, mirroring every other verb
  # (pathlib drops the left operand of `/` when the right one is absolute). The document need
  # not exist on disk: the marker is runtime state about a path, and a clear on a document that
  # was just finalized away is exactly the case that must still work.
  repo = Path(args.repo).resolve()
  entry = update(repo, repo / args.file, { _FIELD_BY_KIND[args.kind]: None if args.clear else args.job_id })
  print(json.dumps(entry))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
