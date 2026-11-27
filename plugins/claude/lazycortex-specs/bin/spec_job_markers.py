"""
Runtime job-marker sidecar for asset status folder-notes, plus the `mark-job` verb writing it.

The two markers that gate an asset's automation — which coordinator job is in flight on the note,
which launch-checkbox expert job is — live here rather than in the folder-note's frontmatter. Two
things follow. An operator hand-editing a folder-note cannot break the coordinator's one-job mutex
or lose a live job's record by mangling a key, because the markers are not in the note at all; and
neither setting nor clearing one costs a commit, because the sidecar is gitignored runtime state.

Store shape — `<repo>/.runtime/lazy-specs.jobs.json`, keyed by the note's repo-relative POSIX path:

    {
      "specs/my-product/bugs/thing/thing.md": {
        "coordinator_job": {"trigger": ..., "expert": ..., "job_id": ...} | null,
        "active_job":      {"checkbox": ..., "expert": ..., "job_id": ...} | null,
        "pending_wake":    "job-done" | "declined" | null,
        "last_job":        {"checkbox": ..., "expert": ..., "job_id": ..., "outcome": ..., "marker": ...,
                             "unlanded": true, "retired_by_cancel": true} | null,
        "coherence_jobs":  [{"doc": ..., "expert": ..., "job_id": ..., "dropped": ...}, ...] | null
      }
    }

The three job fields (`coordinator_job`, `active_job` and `last_job`, the launch job last retired on the note) carry
native JSON objects validated against the closed sub-schema their key declares, and every member of the
`coherence_jobs` list is validated the same way, so a malformed value refuses at write time rather than crashing a
later tick. A `coherence_jobs` member's `dropped` is optional, and so are `last_job`'s two flags, each the literal
true when present: `unlanded` marks a job let go before its result landed, `retired_by_cancel` a job whose result the
asset's cancellation kept from landing. An absent key and an all-null entry mean the same thing; `update` prunes an
entry once every field is null, so an untouched note leaves no row. Writes are atomic (temp file + rename) — the
daemon's main loop is serial by contract, so nothing beyond atomicity is needed.

A job let go is kept as the note's `last_job`: helpers read the terminal marker its bundle carries, build the record
from it and tell a record of a cancelled job from the rest.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable, Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import CoordinatorTrigger, JobMarker, PluginErrorCause  # noqa: E402
# waiver: same deferred sibling import as above
# pylint: disable-next=import-error,wrong-import-position
import error_report  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import spec_locator  # noqa: E402


# The core CLI verb that cancels an expert job, and the variable naming the repository the core CLI acts on.
_CANCEL_JOB = "cancel-job"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The seconds one `cancel-job` call may run before the cancel counts as unconfirmed.
CANCEL_TIMEOUT_S = 60

# The core job store under the repository root, a bundle's response file and the response's outcome key.
_JOBS_BASE = ".experts/.jobs"
_RESPONSE_FILE = "response.json"
_RESPONSE_OUTCOME = "outcome"

# The terminal marker files a finished job bundle carries, in the order they are looked for.
_TERMINAL_MARKERS = ( "DONE", "DEAD", "CANCELLED" )

# The marker file core's `consume-job` leaves in a bundle its consumer retired, and the lowercased `done` marker.
_CONSUMED_MARKER = "CONSUMED"
_DONE = "done"

# The outcome and marker a job carries when the call that retires it is the one that cancelled it.
_CANCELLED = "cancelled"

# How the core CLI's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# The gitignored per-repo runtime directory and this plugin's own sidecar filename inside it.
# `lazy-core.install` creates the directory and puts it in `.gitignore`; a sibling plugin's
# sidecar lives beside this one under its own name.
_RUNTIME_DIR = ".runtime"
_JOBS_SIDECAR = "lazy-specs.jobs.json"

# The sibling sidecar recording each stage lag already raised on a note, so a repeat warns instead of waking.
_STAGE_LAG_SIDECAR = "lazy-specs.stage-lag.json"

# The closed field schema of one note's entry. A field outside it is refused, so a typo never becomes state.
_FIELDS = (
    JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB, JobMarker.PENDING_WAKE, JobMarker.COHERENCE_JOBS,
    JobMarker.LAST_JOB,
)

# The dict-valued fields, whose values are validated against a closed sub-schema below.
_DICT_FIELDS = (JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB, JobMarker.LAST_JOB)

# The list-valued field, each member of which is validated against the field's closed sub-schema below.
_LIST_FIELDS = (JobMarker.COHERENCE_JOBS,)

# Maps the `mark-job` CLI's kind token to the entry field it writes.
_FIELD_BY_KIND = {
    JobMarker.KIND_COORDINATOR: JobMarker.COORDINATOR_JOB,
    JobMarker.KIND_ACTIVE: JobMarker.ACTIVE_JOB,
}

# Suffix of the same-directory temp file the atomic write renames over the store.
_TMP_SUFFIX = ".tmp"

# What follows a sidecar's own name in the name of the file a corrupt sidecar is moved aside to, the format of the
# time that ends that name, and the leading part of the incident key the move is reported under.
_CORRUPT_INFIX = ".corrupt-"
_CORRUPT_TIME_FORMAT = "%Y-%m-%dT%H-%M-%S.%fZ"
_CORRUPT_INCIDENT_PREFIX = "spec-sidecar-corrupt:"


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


# Sub-schema per dict-valued field — `(required keys, {field: closed-value-set})`; `lazy-spec.audit`'s own
# deep-shape checks read this store. The key set is closed in every entry, widened only by the optional keys
# `_OPTIONAL_COUNTS`, `_OPTIONAL_TEXTS` and `_OPTIONAL_FLAGS` name; only the coordinator's `trigger` closes its
# VALUE set too — a launch checkbox's label is playbook vocabulary, declared by the asset type's playbook, so it
# is validated for shape alone rather than against a list this worker would have to grow every time a playbook
# names a new one.
_SUB_SCHEMAS: dict[str, tuple[frozenset[str], dict[str, frozenset[str]]]] = {
    JobMarker.ACTIVE_JOB: (
        frozenset({ JobMarker.CHECKBOX, JobMarker.EXPERT, JobMarker.JOB_ID }),
        {},
    ),
    JobMarker.COORDINATOR_JOB: (
        frozenset({ JobMarker.TRIGGER, JobMarker.EXPERT, JobMarker.JOB_ID }),
        { JobMarker.TRIGGER: _enum_values(CoordinatorTrigger) },
    ),
    JobMarker.COHERENCE_JOBS: (
        frozenset({ JobMarker.DOC, JobMarker.EXPERT, JobMarker.JOB_ID }),
        {},
    ),
    JobMarker.LAST_JOB: (
        frozenset({ JobMarker.CHECKBOX, JobMarker.EXPERT, JobMarker.JOB_ID, JobMarker.OUTCOME, JobMarker.MARKER }),
        {},
    ),
}

# The optional keys a field's object may carry beside its required ones, each a positive count when present
_OPTIONAL_COUNTS: dict[str, frozenset[str]] = {
    JobMarker.COHERENCE_JOBS: frozenset({ JobMarker.DROPPED }),
}

# The optional keys a field's object may carry beside its required ones, each a non-empty string when present
_OPTIONAL_TEXTS: dict[str, frozenset[str]] = {
    JobMarker.COHERENCE_JOBS: frozenset({ JobMarker.HISTORY }),
}

# waiver: the sidecar's own `last_job` sub-key, private to this store; not a frontmatter key in `spec_keys`
# The optional `last_job` key a cancel writes on the record of a job it let go before its result landed.
_UNLANDED = "unlanded"

# waiver: the sidecar's own `last_job` sub-key, private to this store; not a frontmatter key in `spec_keys`
# The optional `last_job` key stamped on the record of a job whose result the asset's cancellation kept from landing.
_RETIRED_BY_CANCEL = "retired_by_cancel"

# The optional keys a field's object may carry beside its required ones, each the literal `True` when present
_OPTIONAL_FLAGS: dict[str, frozenset[str]] = {
    JobMarker.LAST_JOB: frozenset({ _UNLANDED, _RETIRED_BY_CANCEL }),
}


def sidecar_path(repo: Path) -> Path:
  """
  Return the absolute path of the repository's job-marker sidecar.

  Args:
    repo: Repository root the sidecar belongs to.

  Returns:
    Absolute path of `<repo>/.runtime/lazy-specs.jobs.json`, whether or not it exists.
  """

  # Domain(spec.lifecycle):
  # # Job markers live beside the note, never inside it
  # Which background job is running against an asset, and whether a coordinator job already
  # holds it, is tracked apart from the note's own content rather than as one more field an
  # operator could edit by hand. This keeps a hand edit to the note from ever corrupting a live
  # job's record or defeating the one-job-per-asset rule, and it keeps every mark and every clear
  # free of its own commit, since the record is disposable runtime state, never part of the
  # asset's lasting history.

  return repo / _RUNTIME_DIR / _JOBS_SIDECAR


def note_key(repo: Path, note: Path) -> str:
  """
  Return the store key for one status folder-note.

  Guarantees:
    - Two distinct notes always resolve to distinct keys, even when a note lies outside
      `repo` and falls back to its absolute path.

  Args:
    repo: Repository root the key is relative to.
    note: The asset status folder-note's path, absolute or already repo-relative.

  Returns:
    The note's repo-relative POSIX path, or its absolute POSIX path when it lies outside `repo`
    (a caller mistake that must not collapse two notes onto one key).
  """

  # Contract:
  # Two distinct notes never resolve to the same store key, even when a note lies
  # outside `repo` and falls back to its absolute path.

  try:
    return note.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return note.resolve().as_posix()


def empty_entry() -> dict[str, dict | list | str | None]:
  """
  Return the entry every note has before anything is marked on it.

  Returns:
    Dict carrying every field of the closed schema, each `None`.
  """
  return dict.fromkeys(_FIELDS)


def check_sub_schema(field: str, value: dict) -> str | None:
  """
  Validate one job-metadata object against the sub-schema of the field it is written to.

  Every marker's key set stays closed. A field's VALUE set is closed only where the vocabulary
  belongs to this worker — the coordinator's own `trigger`. A launch checkbox's label does not:
  which labels exist is decided by the asset type's playbook, which declares its launch rows,
  so the label is validated for shape alone. A member of the `coherence_jobs` list is checked the
  same way, as one object of that field. A member or record may also carry the optional keys its sub-schema
  declares, each held to that key's own value rule; any other extra key is refused.

  Args:
    field: The entry field being written (`coordinator_job` / `active_job` / `last_job` / `coherence_jobs`).
    value: The candidate job-metadata object — for `coherence_jobs`, one member of the list.

  Returns:
    An error string naming the violation, or None when `field` declares no sub-schema or `value`
    satisfies the one it declares.
  """

  # Domain(spec.lifecycle):
  # # A wake reason is closed vocabulary; a launch label is not
  # The reason a coordinator job is running is always one of a fixed, known set, so it is checked
  # against that set outright. A launch job's own label is never checked the same way, because
  # which launches exist is a decision the asset type's playbook makes, not one this record
  # is entitled to constrain; the label is
  # validated only for being a real, non-empty identifier, whatever vocabulary the playbook draws
  # it from.

  sub_schema = _SUB_SCHEMAS.get(field)

  # guard: this field carries no closed sub-schema — nothing further to check
  if sub_schema is None:
    return None
  required_keys, closed_fields = sub_schema
  optional_flags = _OPTIONAL_FLAGS.get(field, frozenset())
  optional_texts = _OPTIONAL_TEXTS.get(field, frozenset())
  optional_keys = _OPTIONAL_COUNTS.get(field, frozenset()) | optional_flags | optional_texts
  if not required_keys <= value.keys() <= required_keys | optional_keys:
    optional = f" plus optionally {sorted(optional_keys)}" if optional_keys else ""
    return f"expected exactly the keys {sorted(required_keys)}{optional}, got {sorted(value.keys())}"
  for name in sorted(optional_texts & value.keys()):
    # an optional text is a non-empty string or absent; anything else is a violation
    if not isinstance(value[name], str) or not value[name].strip():
      return f"{name} must be a non-empty string, got {value[name]!r}"
  for name in sorted((optional_keys - optional_flags - optional_texts) & value.keys()):
    count = value[name]

    # an optional count is a positive integer or absent; a bool is no count and a violation
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
      return f"{name} must be a positive integer, got {count!r}"
  for name in sorted(optional_flags & value.keys()):
    # an optional flag is the literal `True` or absent; any other value is a violation
    if value[name] is not True:
      return f"{name} must be true, got {value[name]!r}"
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
    The parsed store, or `{}` when the file is absent or was no JSON object store and was moved aside.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, or cannot be moved aside as no store
      for a reason other than its being gone.
  """
  return _read_json(repo, sidecar_path(repo))


def _write_store(repo: Path, store: Mapping[str, dict]) -> None:
  """
  Replace the sidecar with `store` atomically.

  Args:
    repo: Repository root holding the sidecar.
    store: The whole store to serialise.
  """
  _write_json(sidecar_path(repo), store)


def _read_json(repo: Path, path: Path, *, set_aside: bool = True) -> dict[str, dict]:
  """
  Read a sidecar store from disk, setting aside a file that is no store.

  Args:
    repo: Repository root the sidecar belongs to.
    path: The sidecar file.
    set_aside: Whether a file that is no store is moved aside; when False it is left where it is.

  Returns:
    The stored mapping, or an empty one when the file is absent or is not UTF-8 text, not valid JSON, or not a
    JSON object. When the move finds the file already gone, the store is read again once and what stands under
    the name then is returned, an absent file reading as empty.

  Raises:
    OSError: If the file cannot be read for a reason other than its absence, or cannot be moved aside for a reason
      other than its being gone.
  """
  # limit: concurrent writers of a sidecar are not supported — the daemon loop that owns the sidecars is serial, so
  # nothing guards a read-modify-write against another process; the upgrade is a lock held around every
  # read-modify-write of a sidecar

  # an absent sidecar is an empty store; any other failure to read it propagates, so no caller ever writes over a
  # store it could not read. `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
  try:
    data = json.loads(path.read_text(encoding = "utf-8"))
  except FileNotFoundError:
    return {}
  except ValueError:
    data = None

  # a store that parsed as a JSON object is returned as it is
  if isinstance(data, dict):
    return data

  # what was read is no store: the file is kept under another name before anything can be written in its place,
  # for a caller that only reads as well. Only a dry-run prune and the second read below leave it where it is
  if not set_aside or _set_aside(repo, path):
    return {}

  # the file was already gone at the move: the store is read once more and what stands there now is used
  return _read_json(repo, path, set_aside = False)


def _set_aside(repo: Path, path: Path) -> bool:
  """
  Move a sidecar that is no store to a time-stamped sibling and report the move.

  The sibling is named `<sidecar name>.corrupt-<UTC time>`. The move is printed as one line on stderr and
  reported to the error ledger as a warning. A file that is already gone is left alone and nothing is reported.

  Args:
    repo: Repository root the sidecar belongs to.
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

  # the operator is told where the bytes went, on stderr and in the error ledger
  detail = f"{path.name} is not a JSON object store; moved aside to {aside.name}, the store starts empty"
  print(f"spec_job_markers: {detail}", file = sys.stderr)
  error_report.report_warning(
      repo, cause = PluginErrorCause.RUNTIME_SIDECAR_CORRUPT, incident = f"{_CORRUPT_INCIDENT_PREFIX}{path.name}",
      detail = detail,
  )
  return True


def _write_json(path: Path, store: Mapping[str, dict]) -> None:
  """
  Write a sidecar store to disk.

  Args:
    path: The sidecar file; its directory is created when missing.
    store: The mapping to write.
  """
  path.parent.mkdir(parents = True, exist_ok = True)

  # write beside the target and rename over it, so a reader never observes a half-written store
  tmp = path.with_suffix(path.suffix + _TMP_SUFFIX)
  tmp.write_text(json.dumps(store, indent = 2, sort_keys = True) + "\n", encoding = "utf-8")
  os.replace(tmp, path)


def stage_lag_path(repo: Path) -> Path:
  """
  Locate the stage-lag sidecar.

  Args:
    repo: The repository root.

  Returns:
    The path of the gitignored `.runtime/lazy-specs.stage-lag.json` sidecar.
  """
  return repo / _RUNTIME_DIR / _STAGE_LAG_SIDECAR


def read_stage_lag(repo: Path, note: Path) -> dict[str, str]:
  """
  Read the stage-lag record of one asset note.

  Args:
    repo: The repository root.
    note: The asset's status folder-note.

  Returns:
    A mapping of `<basename>:<review_result>` to `woken` or `warned`, plus, per woken lag, a
    `<basename>:<review_result>/lines-before` entry holding a count as text that marks where the lag's episode
    began; empty when nothing is recorded.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, or cannot be moved aside as no store
      for a reason other than its being gone.
  """
  stored = _read_json(repo, stage_lag_path(repo)).get(note_key(repo, note))

  # guard: nothing (or garbage) recorded for this note reads as no lag ever raised
  if not isinstance(stored, dict):
    return {}
  return { key: value for key, value in stored.items() if isinstance(key, str) and isinstance(value, str) }


def write_stage_lag(repo: Path, note: Path, fingerprints: Mapping[str, str]) -> None:
  """
  Replace the stage-lag record of one asset note.

  An empty record removes the note's row; clearing a row that was never written writes nothing.

  Guarantees:
    - A concurrent reader never observes a partially written record.
    - Nothing is ever written over a stage-lag sidecar that could not be read: when reading an existing sidecar
      fails with an `OSError` other than the file's absence, the error propagates and the file is left
      byte-identical.
    - A stage-lag sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved
      aside, bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`; the move is reported on
      stderr and to the error ledger as a warning; only then does the store start empty, so the write that
      follows holds only the new record. A move that finds the sidecar already gone is not an error: the store is
      read again once, what stands under the name then is used (an absent sidecar reads as empty), and this call
      makes no report. Any other failure of the move propagates as `OSError`, nothing is written, and the sidecar
      keeps its bytes under its own name.

  Args:
    repo: The repository root.
    note: The asset's status folder-note.
    fingerprints: The new record, mapping `<basename>:<review_result>` to `woken` or `warned`, plus, per woken lag, a
      `<basename>:<review_result>/lines-before` entry holding a count as text that marks where the lag's episode
      began.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, cannot be moved aside as no store
      for a reason other than its being gone, or the new store cannot be written.
  """

  # Contract:
  # A concurrent reader never observes a partially written record;
  # it sees either the previous content or the new one.

  # Contract:
  # Nothing is ever written over a stage-lag sidecar that could not be read. When reading an existing sidecar fails
  # with an `OSError` other than the file's absence, the error propagates and the file is left byte-identical.

  # Contract:
  # A stage-lag sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved aside,
  # bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`. The move is reported on stderr and to
  # the error ledger as a warning, and only then does the store start empty, so the write that follows holds only
  # the new record. A move that finds the sidecar already gone is not an error: the store is read again once, what
  # stands under the name then is used (an absent sidecar reads as empty), and this call makes no report. Any other
  # failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes under its own
  # name.

  # the whole stored mapping and this note's key in it
  store = _read_json(repo, stage_lag_path(repo))
  key = note_key(repo, note)

  # guard: clearing a record that was never written leaves no file behind
  if not fingerprints and key not in store:
    return

  # an empty record is indistinguishable from an absent one, so drop the row instead
  if fingerprints:
    store[key] = dict(fingerprints)
  else:
    store.pop(key, None)
  _write_json(stage_lag_path(repo), store)


def prune_stage_lag(repo: Path, drop: Callable[[str], bool], *, dry_run: bool = False) -> list[str]:
  """
  Remove every stage-lag row whose note key the predicate selects.

  Guarantees:
    - Nothing is ever written over a stage-lag sidecar that could not be read: when reading an existing sidecar
      fails with an `OSError` other than the file's absence, the error propagates and the file is left
      byte-identical.
    - A stage-lag sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved
      aside, bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`; the move is reported on
      stderr and to the error ledger as a warning; only then does the store start empty, so the write that
      follows holds only the surviving rows. A move that finds the sidecar already gone is not an error: the store
      is read again once, what stands under the name then is used (an absent sidecar reads as empty), and this call
      makes no report. Any other failure of the move propagates as `OSError`, nothing is written, and the sidecar
      keeps its bytes under its own name.
    - With `dry_run` set, nothing is written: a corrupt sidecar is left under its own name and reads as empty.

  Args:
    repo: The repository root.
    drop: Called with each stored note key; True removes that row.
    dry_run: When True, report the selected keys and write nothing.

  Returns:
    The selected note keys, sorted; empty when the store is absent, was set aside as no store, or holds no match.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, cannot be moved aside as no store
      for a reason other than its being gone, or the rewritten store cannot be written.
  """

  # Contract:
  # Nothing is ever written over a stage-lag sidecar that could not be read. When reading an existing sidecar fails
  # with an `OSError` other than the file's absence, the error propagates and the file is left byte-identical.

  # Contract:
  # A stage-lag sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved aside,
  # bytes intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`. The move is reported on stderr and to
  # the error ledger as a warning, and only then does the store start empty, so the write that follows holds only
  # the surviving rows. A move that finds the sidecar already gone is not an error: the store is read again once,
  # what stands under the name then is used (an absent sidecar reads as empty), and this call makes no report. Any
  # other failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes under
  # its own name.

  # Contract:
  # A dry run writes nothing: a corrupt sidecar is left under its own name and reads as empty.

  store = _read_json(repo, stage_lag_path(repo), set_aside = not dry_run)
  dropped = sorted(key for key in store if drop(key))

  # guard: a dry run or a store with nothing to drop leaves the file exactly as it is
  if dry_run or not dropped:
    return dropped

  # the surviving rows replace the store through the same atomic write every other writer uses
  _write_json(stage_lag_path(repo), { key: value for key, value in store.items() if key not in dropped })
  return dropped


def _normalize_entry(stored: object) -> dict[str, dict | list | str | None]:
  """
  Normalize one raw store row into the closed-schema entry shape.

  Args:
    stored: The raw value found under a note's key in the store — any JSON value.

  Returns:
    The entry with every field of the closed schema present; a non-dict row, a non-dict value
    in a dict field, a list field holding no valid member, and a blank wake token all read as
    `None`.
  """
  entry = empty_entry()

  # guard: nothing (or garbage) recorded for this note — the all-`None` entry is the answer
  if not isinstance(stored, dict):
    return entry
  for field in _FIELDS:
    value = stored.get(field)
    if field in _DICT_FIELDS:
      entry[field] = value if isinstance(value, dict) and value else None
    elif field in _LIST_FIELDS:
      members = value if isinstance(value, list) else []
      entry[field] = [ member for member in members
                       if isinstance(member, dict) and check_sub_schema(field, member) is None ] or None
    else:
      entry[field] = value if isinstance(value, str) and value.strip() else None
  return entry


def read(repo: Path, note: Path) -> dict[str, dict | list | str | None]:
  """
  Read one note's marker entry.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.

  Returns:
    The entry with every field of the closed schema present, unrecorded ones as `None`.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, or cannot be moved aside as no store
      for a reason other than its being gone.
  """
  return _normalize_entry(_read_store(repo).get(note_key(repo, note)))


def coherence_jobs(repo: Path, note: Path) -> list[dict]:
  """
  Read the coherence checks tracked for one note's documents.

  Args:
    repo: Repository root holding the sidecar.
    note: The folder-note's path.

  Returns:
    The recorded members in recorded order, each `{"doc", "expert", "job_id"}` as strings plus `"dropped"` as an
    integer and `"history"` as a string when those were recorded; empty when none is recorded.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, or cannot be moved aside as no store
      for a reason other than its being gone.
  """
  jobs = read(repo, note)[JobMarker.COHERENCE_JOBS]
  return [ { str(key): value if key == JobMarker.DROPPED else str(value) for key, value in job.items() }
           for job in jobs if isinstance(job, dict) ] if isinstance(jobs, list) else []


def entries(repo: Path) -> dict[str, dict[str, dict | list | str | None]]:
  """
  Read every recorded row of the sidecar at once.

  Args:
    repo: Repository root holding the sidecar.

  Returns:
    Mapping of each recorded note's repo-relative POSIX key to its entry, each normalized
    exactly as `read` normalizes one; `{}` when the sidecar is absent or was set aside as no store.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, or cannot be moved aside as no store
      for a reason other than its being gone.
  """
  return { key: _normalize_entry(stored) for key, stored in _read_store(repo).items() }


def _check_members(field: str, value: object) -> list[dict]:
  """
  Validate the value of a list-valued field member by member.

  Args:
    field: The list-valued entry field being written.
    value: The candidate value.

  Returns:
    The members, each satisfying the field's closed sub-schema.

  Raises:
    ValueError: If the value is not a list, or a member is not an object or violates the sub-schema.
  """
  # guard: a list-valued field never takes anything but a list
  if not isinstance(value, list):
    raise ValueError(f"mark-job: {field} takes a JSON list, got {value!r}")
  for member in value:
    # guard: every member is an object of the field's closed shape, or the whole write is refused
    if not isinstance(member, dict):
      raise ValueError(f"mark-job: {field} takes JSON objects, got {member!r}")
    error = check_sub_schema(field, member)

    # guard: a member that violates the closed shape is refused just as cleanly
    if error is not None:
      raise ValueError(f"mark-job: {field} {error}")
  return value


def update(repo: Path, note: Path,
           changes: Mapping[str, dict | list | str | None]) -> dict[str, dict | list | str | None]:
  """
  Apply `changes` to one note's entry and persist the store.

  Guarantees:
    - When `changes` fails validation, the store is left exactly as it was before the
      call; no field of `changes` is ever partially persisted. A refused call does not even move a corrupt sidecar
      aside or report it.
    - Nothing is ever written over a sidecar that could not be read: when reading an existing sidecar fails with
      an `OSError` other than the file's absence, the error propagates and the file is left byte-identical.
    - A sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved aside, bytes
      intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`; the move is reported on stderr and to
      the error ledger as a warning; only then does the store start empty, so the write that follows holds only
      the new content. A move that finds the sidecar already gone is not an error: the store is read again once,
      what stands under the name then is used (an absent sidecar reads as empty), and this call makes no report.
      Any other failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes
      under its own name.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.
    changes: Field-to-value mapping; a `None` value clears that field.

  Returns:
    The note's resulting entry.

  Raises:
    ValueError: If `changes` names a field outside the closed schema, gives a dict-valued field
      a non-dict value, a list-valued field a non-list one, or a scalar field a value that is neither a string
      nor `None`, or gives a dict-valued or list-valued field an object violating that field's closed sub-schema.
    OSError: If the sidecar cannot be read for a reason other than its absence, cannot be moved aside as no store
      for a reason other than its being gone, or the new store cannot be written.
  """

  # Contract:
  # When `changes` fails validation for any reason, the sidecar store is left
  # byte-identical to its state before the call — no partial write is ever persisted.
  # A refused call does not even move a corrupt sidecar aside or report it.

  # Contract:
  # Nothing is ever written over a sidecar that could not be read. When reading an existing sidecar fails with an
  # `OSError` other than the file's absence, the error propagates and the file is left byte-identical.

  # Contract:
  # A sidecar that reads but is not UTF-8 text, not valid JSON, or not a JSON object is first moved aside, bytes
  # intact, to a sibling file named `<sidecar name>.corrupt-<UTC time>`. The move is reported on stderr and to the
  # error ledger as a warning, and only then does the store start empty, so the write that follows holds only the
  # new content. A move that finds the sidecar already gone is not an error: the store is read again once, what
  # stands under the name then is used (an absent sidecar reads as empty), and this call makes no report. Any other
  # failure of the move propagates as `OSError`, nothing is written, and the sidecar keeps its bytes under its own
  # name.

  unknown = [field for field in changes if field not in _FIELDS]

  # guard: a field outside the schema is a typo, and a typo must not become state
  if unknown:
    raise ValueError(f"mark-job: field(s) {unknown} are not in the marker schema {list(_FIELDS)}")

  # every change is validated before the sidecar is first read, so a refused call never touches it: each dict
  # value is checked against its sub-schema and a blank scalar is normalised to the absent marker
  accepted: dict[str, dict | list | str | None] = {}
  for field, value in changes.items():
    if field in _DICT_FIELDS and value is not None:
      # guard: a dict-valued field never takes a scalar — refuse before it becomes state
      if not isinstance(value, dict):
        raise ValueError(f"mark-job: {field} takes a JSON object, got {value!r}")
      error = check_sub_schema(field, value)

      # guard: an object that violates the field's closed sub-schema is refused just as cleanly
      if error is not None:
        raise ValueError(f"mark-job: {field} {error}")
      accepted[field] = value
    elif field in _LIST_FIELDS and value is not None:
      accepted[field] = _check_members(field, value) or None
    else:
      # guard: a scalar field takes a token or nothing — any other value would silently clear what is recorded
      if value is not None and not isinstance(value, str):
        raise ValueError(f"mark-job: {field} takes a string, got {value!r}")
      accepted[field] = value.strip() or None if value is not None else None

  # the accepted changes overlay the note's current entry
  entry = { **read(repo, note), **accepted }

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

  Guarantees:
    - The absence of an entry for the note is never itself an error; clearing a note that carries no recorded entry
      succeeds as a no-op.

  Args:
    repo: Repository root holding the sidecar.
    note: The asset status folder-note's path.

  Raises:
    OSError: If the sidecar cannot be read for a reason other than its absence, cannot be moved aside as no store
      for a reason other than its being gone, or the new store cannot be written.
  """

  # Contract:
  # The absence of an entry for the note is never itself an error;
  # clearing a note that carries no recorded entry succeeds as a no-op.

  # clearing every field of the schema at once is what prunes the row from the store
  update(repo, note, dict.fromkeys(_FIELDS))


def cancel_job(repo: Path, cli: Path, job_info: Mapping[str, object]) -> bool:
  """
  Cancel one expert job through the core `cancel-job` verb.

  Guarantees:
    - The result is True only when the core `cancel-job` verb exits cleanly within the cancel timeout; any other
      outcome returns False.
    - A verb that runs out of time or cannot be launched returns False and never raises.

  Args:
    repo: Repository root the job runs in.
    cli: The resolved `lazycortex-core` CLI.
    job_info: The tracked job marker, carrying `expert` and `job_id`.

  Returns:
    True when the verb exits zero in time (the job is cancelled or was already over); False when the job may still
    run.
  """

  # Contract:
  # The result is True only when the core `cancel-job` verb exits cleanly within the cancel timeout; any other
  # outcome returns False, so a caller may treat True as proof the job no longer runs.

  # Contract:
  # A verb that runs out of time or cannot be launched returns False and NEVER raises, so a stuck or missing core
  # cannot hang or break the caller.

  # the core CLI resolves the job against this repo's runtime, named through the environment
  env = { **os.environ, _ENV_REPO_ROOT: str(repo) }

  # the cancel request names the job by its expert and id
  request = json.dumps({
      JobMarker.EXPERT: job_info.get(JobMarker.EXPERT), JobMarker.JOB_ID: job_info.get(JobMarker.JOB_ID),
  })

  # only a clean exit in time counts as cancelled
  try:
    done = subprocess.run(
        [ sys.executable, str(cli), _CANCEL_JOB ],
        input = request,
        capture_output = True, text = True, cwd = str(repo), env = env, check = False, encoding = "utf-8",
        errors = _DECODE_ERRORS, timeout = CANCEL_TIMEOUT_S,
    )
  except (OSError, subprocess.TimeoutExpired):
    return False
  return done.returncode == 0


def find_terminal_marker(repo: Path, job_info: Mapping[str, object]) -> str | None:
  """
  Name the terminal marker a tracked job's bundle carries.

  Args:
    repo: Repository root holding the job store.
    job_info: The tracked job marker, carrying `expert` and `job_id`.

  Returns:
    The marker file name found (`DONE`, `DEAD` or `CANCELLED`), None while the job has not ended.
  """
  # the bundle sits under the expert it ran for, named by its id
  job_dir = repo / _JOBS_BASE / str(job_info.get(JobMarker.EXPERT)) / str(job_info.get(JobMarker.JOB_ID))
  return next((marker for marker in _TERMINAL_MARKERS if (job_dir / marker).is_file()), None)


def build_retired_record(repo: Path, job_info: Mapping[str, object], finished: str | None) -> dict:
  """
  Build the `last_job` record of a tracked job being let go.

  Guarantees:
    - A job that had not ended before the call let it go (`finished` None) is recorded with outcome and marker
      `cancelled`.
    - A job that had already ended is recorded with the lowercased marker, and with the outcome its `response.json`
      reports, the marker standing in when the bundle holds no response naming one.
    - The record always carries `unlanded: true`, whichever way the job ended.

  Args:
    repo: Repository root holding the job store.
    job_info: The tracked job marker, carrying `checkbox`, `expert` and `job_id`.
    finished: The terminal marker the bundle carried before the call let the job go, None when it had none.

  Returns:
    The `{checkbox, expert, job_id, outcome, marker, unlanded}` record, `unlanded` always true.
  """

  # Contract:
  # A job that had not ended before the call let it go is recorded with outcome and marker `cancelled`; one that had
  # ended is recorded with the lowercased marker and the outcome its response reports, the marker standing in. The
  # record always carries `unlanded: true`, whichever way the job ended.

  # a job the caller cancelled itself has no response of its own to report
  marker = finished.lower() if finished else _CANCELLED
  outcome = _read_response_outcome(repo, job_info) if finished else None
  return {
      JobMarker.CHECKBOX: job_info.get(JobMarker.CHECKBOX), JobMarker.EXPERT: job_info.get(JobMarker.EXPERT),
      JobMarker.JOB_ID: job_info.get(JobMarker.JOB_ID), JobMarker.OUTCOME: outcome or marker,
      JobMarker.MARKER: marker, _UNLANDED: True,
  }


def mark_unlanded(record: Mapping[str, object]) -> dict:
  """
  Mark a `last_job` record as let go before its result landed.

  Args:
    record: The stored `last_job` record.

  Returns:
    A copy of the record carrying `unlanded: true`.
  """
  # the record keeps every field and gains the flag
  return { **record, _UNLANDED: True }


def is_unlanded_record(record: object) -> bool:
  """
  Tell whether a `last_job` record names a job let go before its result landed.

  Args:
    record: The stored `last_job` value.

  Returns:
    True when the record is an object whose `unlanded` is the literal `True`.
  """
  # only an object carrying the literal flag counts
  return isinstance(record, dict) and record.get(_UNLANDED) is True


def mark_retired_by_cancel(record: Mapping[str, object]) -> dict:
  """
  Stamp a `last_job` record as retired by the asset's cancellation.

  Args:
    record: The `last_job` record.

  Returns:
    A copy of the record carrying `retired_by_cancel: true`.
  """
  # the record keeps every field and gains the stamp
  return { **record, _RETIRED_BY_CANCEL: True }


def is_retired_by_cancel(record: object) -> bool:
  """
  Tell whether a `last_job` record carries the stamp of the asset's cancellation.

  Args:
    record: The stored `last_job` value.

  Returns:
    True when the record is an object whose `retired_by_cancel` is the literal `True`.
  """
  # only an object carrying the literal stamp counts
  return isinstance(record, dict) and record.get(_RETIRED_BY_CANCEL) is True


def drop_retired_by_cancel(record: Mapping[str, object]) -> dict:
  """
  Remove the cancellation's stamp from a `last_job` record.

  Args:
    record: The `last_job` record.

  Returns:
    A copy of the record without `retired_by_cancel`, every other field kept.
  """
  # every field but the stamp is kept
  return { key: value for key, value in record.items() if key != _RETIRED_BY_CANCEL }


def is_result_landed(repo: Path, record: object) -> bool:
  """
  Tell whether a `last_job` record names a finished job whose result has landed.

  Args:
    repo: Repository root holding the job store.
    record: The stored `last_job` value.

  Returns:
    True when the record is an object with marker `done` and no `unlanded` flag, and its job bundle is marked
    consumed; False for any other value, a job that is still unfinished or flagged `unlanded` included.
  """
  # guard: only a finished job not already marked unlanded can have landed
  if not isinstance(record, dict) or record.get(JobMarker.MARKER) != _DONE or is_unlanded_record(record):
    return False

  # the landing retires the bundle, so a consumed bundle is a landed result
  job_dir = repo / _JOBS_BASE / str(record.get(JobMarker.EXPERT)) / str(record.get(JobMarker.JOB_ID))
  return (job_dir / _CONSUMED_MARKER).is_file()


def is_cancelled_record(record: object) -> bool:
  """
  Tell whether a `last_job` record names a job that was cancelled before it ended.

  Args:
    record: The stored `last_job` value.

  Returns:
    True when the record's outcome and marker both read `cancelled`.
  """
  # only a record naming the cancellation in both fields counts
  return isinstance(record, dict) and record.get(JobMarker.OUTCOME) == _CANCELLED \
      and record.get(JobMarker.MARKER) == _CANCELLED


def _read_response_outcome(repo: Path, job_info: Mapping[str, object]) -> str | None:
  """
  Read the outcome a finished job's response reports.

  Args:
    repo: Repository root holding the job store.
    job_info: The tracked job marker, carrying `expert` and `job_id`.

  Returns:
    The response's non-empty `outcome` string, None when the bundle holds no readable response naming one.
  """
  # a missing or unreadable response names no outcome
  job_dir = repo / _JOBS_BASE / str(job_info.get(JobMarker.EXPERT)) / str(job_info.get(JobMarker.JOB_ID))
  try:
    response = json.loads((job_dir / _RESPONSE_FILE).read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    # `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
    return None

  # only a JSON object naming a non-empty outcome reports one
  outcome = response.get(_RESPONSE_OUTCOME) if isinstance(response, dict) else None
  return outcome.strip() if isinstance(outcome, str) and outcome.strip() else None


def main(argv: list[str]) -> int:
  """
  Write one job marker from the command line, printing the resulting entry as JSON.

  Invoked as `mark-job <note> coordinator|active <json-object>` to set a marker, or with
  `--clear` in place of the value to drop it. Clearing a marker that was never set is a no-op
  success. `--wake` raises or clears the pending wake instead of touching a job field.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the working directory); the marker is kept for the checkout that directory
      sits in.

  Returns:
    Exit code: 0 on success, 2 when neither a value nor `--clear` was given, or both were; 1 when
    the value is not a JSON object or violates the marker's closed sub-schema, or when the sidecar
    cannot be read, moved aside or written (one line naming the sidecar and the error goes to stderr).
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
  parser.add_argument("--repo", default = None)
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

      # guard: a JSON `null` is no object either — only `--clear` clears a marker
      if value is None:
        sys.stderr.write(f"mark-job: expected a JSON object, got {args.value!r}\n")
        return 1

  # `note` resolves against the checkout `--repo`, else `$LAZY_REPO_ROOT`, else the cwd sits in, unless it is
  # already absolute
  # (pathlib drops the left operand of `/` when the right one is absolute). The note need not
  # exist on disk: the marker is runtime state about a path, and a clear on a note that was just
  # deleted is exactly the case that must still work.
  repo = spec_locator.query_repo_root(args.repo)
  try:
    entry = update(repo, repo / args.note, { field: value })
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return 1
  # a sidecar that cannot be read, set aside or written refuses the call the same way, named with its error
  except OSError as error:
    sys.stderr.write(f"mark-job: {_JOBS_SIDECAR}: {type(error).__name__}: {error}\n")
    return 1
  print(json.dumps(entry))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
