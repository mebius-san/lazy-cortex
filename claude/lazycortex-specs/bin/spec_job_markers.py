"""Runtime job-marker sidecar for asset status folder-notes, plus the `mark-job` verb writing it.

The two markers that gate an asset's automation — which coordinator job is in flight on the note,
which launch-checkbox expert job is — live here rather than in the folder-note's frontmatter. Two
things follow. An operator hand-editing a folder-note cannot break the coordinator's one-job mutex
or lose a live job's record by mangling a key, because the markers are not in the note at all; and
neither setting nor clearing one costs a commit, because the sidecar is gitignored runtime state.

Store shape — `<repo>/.runtime/lazy-specs.jobs.json`, keyed by the note's repo-relative POSIX path:

    {
      "specs/my-product/features/thing/thing.md": {
        "coordinator_job": {"trigger": ..., "expert": ..., "job_id": ...} | null,
        "active_job":      {"checkbox": ..., "expert": ..., "job_id": ...} | null,
        "pending_wake":    "job-done" | "declined" | null
      }
    }

Both job fields carry native JSON objects validated against the closed sub-schema their key
declares, so a malformed value refuses at write time rather than crashing a later tick. An absent
key and an all-null entry mean the same thing; `update` prunes an entry once every field is null,
so an untouched note leaves no row. Writes are atomic (temp file + rename) — the daemon's main
loop is serial by contract, so nothing beyond atomicity is needed.
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
from spec_keys import CoordinatorTrigger, JobMarker  # noqa: E402


# The gitignored per-repo runtime directory and this plugin's own sidecar filename inside it.
# `lazy-core.install` creates the directory and puts it in `.gitignore`; a sibling plugin's
# sidecar lives beside this one under its own name.
_RUNTIME_DIR = ".runtime"
_JOBS_SIDECAR = "lazy-specs.jobs.json"

# The closed field schema of one note's entry. A field outside it is refused the way `note-set-key`
# refuses a frontmatter key outside its own schema — a typo must not become state.
_FIELDS = (JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB, JobMarker.PENDING_WAKE)

# The two dict-valued fields, whose values are validated against a closed sub-schema below.
_DICT_FIELDS = (JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB)

# Maps the `mark-job` CLI's kind token to the entry field it writes.
_FIELD_BY_KIND = {
    JobMarker.KIND_COORDINATOR: JobMarker.COORDINATOR_JOB,
    JobMarker.KIND_ACTIVE: JobMarker.ACTIVE_JOB,
}

# Suffix of the same-directory temp file the atomic write renames over the store.
_TMP_SUFFIX = ".tmp"


# waiver: generic over any closed-set marker class in spec_keys, not one specific class
def _enum_values(cls: type[object]) -> frozenset[str]:
  """
  Collect every public string constant declared directly on a closed-set marker class.

  Args:
    cls: A `spec_keys` class whose public attributes are all closed-set string tokens (e.g.
      `CoordinatorTrigger`).

  Returns:
    The frozen set of those string values.
  """
  return frozenset(
      value for name, value in vars(cls).items() if not name.startswith("_") and isinstance(value, str)
  )


# Sub-schema per dict-valued field — `(required keys, {field: closed-value-set})`. Moved here with
# the markers themselves from `note_ops.note_set_key`, which validated the same two shapes while
# they were frontmatter keys; `lazy-spec.doctor`'s own deep-shape checks read this store. The key
# set is closed in both entries; only the coordinator's `trigger` closes its VALUE set too — a
# launch checkbox's label is playbook vocabulary, including labels a playbook parameterises by
# tool, so it is validated for shape alone rather than against a list this worker would have to
# grow every time a playbook names a new one.
_SUB_SCHEMAS: dict[str, tuple[frozenset[str], dict[str, frozenset[str]]]] = {
    JobMarker.ACTIVE_JOB: (
        frozenset({ JobMarker.CHECKBOX, JobMarker.EXPERT, JobMarker.JOB_ID }),
        {},
    ),
    JobMarker.COORDINATOR_JOB: (
        frozenset({ JobMarker.TRIGGER, JobMarker.EXPERT, JobMarker.JOB_ID }),
        { JobMarker.TRIGGER: _enum_values(CoordinatorTrigger) },
    ),
}


def sidecar_path(repo: Path) -> Path:
  """
  Return the absolute path of the repository's job-marker sidecar.

  Args:
    repo: Repository root the sidecar belongs to.

  Returns:
    Absolute path of `<repo>/.runtime/lazy-specs.jobs.json`, whether or not it exists.
  """
  return repo / _RUNTIME_DIR / _JOBS_SIDECAR


def note_key(repo: Path, note: Path) -> str:
  """
  Return the store key for one status folder-note.

  Args:
    repo: Repository root the key is relative to.
    note: The asset status folder-note's path, absolute or already repo-relative.

  Returns:
    The note's repo-relative POSIX path, or its absolute POSIX path when it lies outside `repo`
    (a caller mistake that must not collapse two notes onto one key).
  """
  try:
    return note.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return note.resolve().as_posix()


def empty_entry() -> dict[str, dict | str | None]:
  """
  Return the entry every note has before anything is marked on it.

  Returns:
    Dict carrying every field of the closed schema, each `None`.
  """
  return dict.fromkeys(_FIELDS)


def check_sub_schema(field: str, value: dict) -> str | None:
  """
  Validate a dict-valued field against its sub-schema.

  Every marker's key set stays closed. A field's VALUE set is closed only where the vocabulary
  belongs to this worker — the coordinator's own `trigger`. A launch checkbox's label does not:
  which labels exist, and how a playbook parameterises one by tool, is the playbook's decision,
  so the label is validated for shape alone.

  Args:
    field: The entry field being written (`coordinator_job` / `active_job`).
    value: The candidate job-metadata object.

  Returns:
    An error string naming the violation, or None when `field` declares no sub-schema or `value`
    satisfies the one it declares.
  """
  sub_schema = _SUB_SCHEMAS.get(field)
  # guard: this field carries no closed sub-schema — nothing further to check
  if sub_schema is None:
    return None
  required_keys, closed_fields = sub_schema
  if value.keys() != required_keys:
    return f"expected exactly the keys {sorted(required_keys)}, got {sorted(value.keys())}"
  for name, allowed in closed_fields.items():
    if value[name] not in allowed:
      return f"{name} must be one of {sorted(allowed)}, got {value[name]!r}"
  # a field with no closed set is validated for shape alone — an identifier that is not a
  # non-empty string names nothing, whatever vocabulary the playbook draws it from
  for name in sorted(required_keys - closed_fields.keys()):
    if not isinstance(value[name], str) or not value[name].strip():
      return f"{name} must be a non-empty string, got {value[name]!r}"
  return None


def _read_store(repo: Path) -> dict[str, dict]:
  """
  Read the whole sidecar.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    The parsed store, or `{}` when the file is absent, unreadable, or not a JSON object — a
    corrupt sidecar is runtime scratch and re-derives itself, so it never fails a tick.
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


def _normalize_entry(stored: object) -> dict[str, dict | str | None]:
  """
  Normalize one raw store row into the closed-schema entry shape.

  Args:
    stored: The raw value found under a note's key in the store — any JSON value.

  Returns:
    The entry with every field of the closed schema present; a non-dict row, a non-dict value
    in a dict field, and a blank wake token all read as `None`.
  """
  entry = empty_entry()
  # guard: nothing (or garbage) recorded for this note — the all-`None` entry is the answer
  if not isinstance(stored, dict):
    return entry
  for field in _FIELDS:
    value = stored.get(field)
    if field in _DICT_FIELDS:
      entry[field] = value if isinstance(value, dict) and value else None
    else:
      entry[field] = value if isinstance(value, str) and value.strip() else None
  return entry


def read(repo: Path, note: Path) -> dict[str, dict | str | None]:
  """
  Read one note's marker entry.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.

  Returns:
    The entry with every field of the closed schema present, unrecorded ones as `None`.
  """
  return _normalize_entry(_read_store(repo).get(note_key(repo, note)))


def entries(repo: Path) -> dict[str, dict[str, dict | str | None]]:
  """
  Read every recorded row of the sidecar at once.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    Mapping of each recorded note's repo-relative POSIX key to its entry, each normalized
    exactly as `read` normalizes one; `{}` when the sidecar is absent or corrupt.
  """
  return { key: _normalize_entry(stored) for key, stored in _read_store(repo).items() }


def update(repo: Path, note: Path, changes: Mapping[str, dict | str | None]) -> dict[str, dict | str | None]:
  """
  Apply `changes` to one note's entry and persist the store.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.
    changes: Field-to-value mapping; a `None` value clears that field.

  Returns:
    The note's resulting entry.

  Raises:
    ValueError: If `changes` names a field outside the closed schema, gives a dict-valued field
      a non-dict value, or gives it an object violating that field's closed sub-schema.
  """
  unknown = [field for field in changes if field not in _FIELDS]
  # guard: a field outside the schema is a typo, and a typo must not become state
  if unknown:
    raise ValueError(f"mark-job: field(s) {unknown} are not in the marker schema {list(_FIELDS)}")

  # overlay the changes on the current entry, validating each dict value against its sub-schema
  # and normalising a blank scalar to the absent marker
  entry = read(repo, note)
  for field, value in changes.items():
    if field in _DICT_FIELDS and value is not None:
      # guard: a dict-valued field never takes a scalar — refuse before it becomes state
      if not isinstance(value, dict):
        raise ValueError(f"mark-job: {field} takes a JSON object, got {value!r}")
      error = check_sub_schema(field, value)
      # guard: an object that violates the field's closed sub-schema is refused just as cleanly
      if error is not None:
        raise ValueError(f"mark-job: {field} {error}")
      entry[field] = value
    else:
      entry[field] = value.strip() if isinstance(value, str) and value.strip() else None

  # an all-`None` entry is indistinguishable from an absent one, so drop the row instead
  store = _read_store(repo)
  key = note_key(repo, note)
  if any(entry.values()):
    store[key] = entry
  else:
    store.pop(key, None)
  _write_store(repo, store)
  return entry


def clear(repo: Path, note: Path) -> None:
  """
  Drop one note's entry entirely.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.
  """
  # clearing every field of the schema at once is what prunes the row from the store
  update(repo, note, dict.fromkeys(_FIELDS))


def main(argv: list[str]) -> int:
  """
  Write one job marker from the command line, printing the resulting entry as JSON.

  Invoked as `mark-job <note> coordinator|active <json-object>` to set a marker, or with
  `--clear` in place of the value to drop it. Clearing a marker that was never set is a no-op
  success. `--wake` raises or clears the pending wake instead of touching a job field.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when neither a value nor `--clear` was given, or both were; 1 when
    the value is not a JSON object or violates the marker's closed sub-schema.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs mark-job")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("note")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("kind", choices = [*_FIELD_BY_KIND, JobMarker.KIND_WAKE])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("value", nargs = "?", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--clear", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # guard: exactly one of the two forms must be used — a value, or the explicit clear
  if bool(args.value) == bool(args.clear):
    # waiver: one-off CLI usage message, not a domain token compared anywhere
    sys.stderr.write("mark-job: pass either a value or --clear, not both and not neither\n")
    return 2

  # the wake field carries a bare token; the two job fields carry a JSON object
  field = _FIELD_BY_KIND.get(args.kind, JobMarker.PENDING_WAKE)
  value: dict | str | None = None
  if not args.clear:
    if field == JobMarker.PENDING_WAKE:
      value = args.value
    else:
      try:
        value = json.loads(args.value)
      except json.JSONDecodeError:
        sys.stderr.write(f"mark-job: expected a JSON object, got {args.value!r}\n")
        return 1

  # `note` resolves against `--repo` unless it is already absolute, mirroring every other verb
  # (pathlib drops the left operand of `/` when the right one is absolute). The note need not
  # exist on disk: the marker is runtime state about a path, and a clear on a note that was just
  # deleted is exactly the case that must still work.
  repo = Path(args.repo).resolve()
  try:
    entry = update(repo, repo / args.note, { field: value })
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return 1
  print(json.dumps(entry))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
