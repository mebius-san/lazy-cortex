"""
Error ledger for the lazycortex-core autonomous runtime.

The append-only event journal (`.runtime/errors.jsonl`) is the source of truth;
each incident's state (open / needs_operator / closed) is folded on read by its
`incident` key. A retention snapshot (`.runtime/errors.state.json`) carries
all-time per-kind counters of dropped incident openings, plus the entries earlier
retention passes carried forward for open incidents, which stay until those
incidents expire.

This module is the only reader/writer of the journal. Other plugins reach it
through the `lazycortex-core error-record` / `error-list` CLI, never by import.
"""
from __future__ import annotations

import calendar
import json
import os
import secrets
import sys
import time
from itertools import chain
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterator


# Repo-relative path of the append-only event journal
JOURNAL_REL = ".runtime/errors.jsonl"
# Repo-relative path of the retention snapshot carrying counters and open incidents earlier passes carried forward
SNAPSHOT_REL = ".runtime/errors.state.json"
# UTC timestamp format stamped on every event
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
# Character budget an event's detail is cut to before it is written
_DETAIL_MAX = 500
# Byte ceiling of one journal line, kept so each append stays a single atomic write
_LINE_MAX = 4096
# Crockford base32 alphabet the event ids are encoded in
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# Daemon-halt causes the runtime never retries itself, so the incident waits for an operator
_HUMAN_HALT_CAUSES = {
  "git_pull_diverged", "git_push_failed", "git_remote_unavailable", "git_rebase_not_started",
  "config_violation", "suspected_loop", "routine_config_invalid",
}

# ULID algorithm constants (per https://github.com/ulid/spec)
# waiver: these are fixed algorithm parameters from the ULID spec — Enum adds no clarity
_ULID_LEN = 26
_ULID_RAND_BITS = 80
_ULID_TS_MS_BITS = 48
_ULID_BASE_BITS = 5
_ULID_TS_MS_SCALE = 1000

# Journal field-name constants — used in multiple write paths
_F_ID = "id"
_F_TS = "ts"
_F_DETAIL = "detail"
_F_REFS = "refs"
_F_PHASE = "phase"
_F_KIND = "kind"
_F_CAUSE = "cause"
_F_SEVERITY = "severity"
_F_INCIDENT = "incident"
_F_EXPERT = "expert"
_F_JOB_ID = "job_id"
_F_ROUTINE = "routine"
_F_STATE = "state"
_UTF8 = "utf-8"
_UTF8_ERRORS_REPLACE = "replace"
# waiver: 0o644 file-permission literal — octal intent is clear at call site; no Enum gain
_MODE_RW_R_R = 0o644

# Incident state constants
_ST_OPEN = "open"
_ST_NEEDS_OPERATOR = "needs_operator"
_ST_CLOSED = "closed"
_ST_ALL = "all"

# Phase constants
_PH_RESOLVED = "resolved"
_PH_TRIAGED = "triaged"

# Kind constants
_KIND_DAEMON_HALT = "daemon_halt"

# Cause constants
_CAUSE_PERMANENT_FAIL = "permanent_fail"

# Default severity
_SEV_ERROR = "error"

# Snapshot field
_SNAP_OPEN = "open"

# Logging message constant
_MSG_CORRUPT_LINE = "error_ledger: skipping corrupt journal line"

# Phase of the event that opens an incident and advances the all-time counter
_PH_OPENED = "opened"
# Seconds in a day, converting the retention window to a cutoff
_SECONDS_PER_DAY = 86400
# Counter key for a pruned event that carries no kind
_UNKNOWN_KIND = "unknown"
# Suffix of the temporary file a rewrite goes through before it replaces the original
_TMP_SUFFIX = ".tmp"
# Snapshot field holding the all-time per-kind counters
_SNAP_COUNTERS = "counters"
# Incident-key prefix naming an expert job
_JOB_PREFIX = "job:"
# Repo-relative root of the expert job tree a job incident's key resolves into
_JOBS_BASE_REL = ".experts/.jobs"
# Resolution recorded for a job incident whose job directory no longer exists
_RES_GONE = "gone"

# Crash-loop dedupe: an event identical to the journal's last line within this window is spam, not signal.
# The journal itself is the persistent memory, so the guard survives process restarts.
_DEDUP_WINDOW_SEC = 3600
_TAIL_READ_BYTES = 4096
_DEDUP_KEYS = (_F_INCIDENT, _F_PHASE, _F_KIND, _F_CAUSE, _F_DETAIL)
# limit: the first 10 and last 40 events per incident are the forensics headroom; raise either count if that pinches
# Number of an incident's earliest events retention always keeps
_CAP_HEAD = 10
# Number of an incident's latest events retention always keeps
_CAP_TAIL = 40


def _ulid() -> str:
  """
  Return a 26-char Crockford-base32 ULID: 48-bit ms timestamp + 80-bit random, time-sortable.

  Returns:
    A 26-character uppercase string encoding the current millisecond timestamp
    and 80 bits of cryptographic randomness in Crockford base32 form.
  """
  ts_ms = int(time.time() * _ULID_TS_MS_SCALE) & ((1 << _ULID_TS_MS_BITS) - 1)
  value = (ts_ms << _ULID_RAND_BITS) | secrets.randbits(_ULID_RAND_BITS)
  out = []
  for _ in range(_ULID_LEN):
    out.append(_CROCKFORD[value & ((1 << _ULID_BASE_BITS) - 1)])
    value >>= _ULID_BASE_BITS
  return "".join(reversed(out))


def new_id() -> str:
  """
  Return a fresh ULID for use as an event id outside this module.

  The result has the same form as the ids the journal assigns to its events.

  Returns:
    A new 26-character ULID, time-sortable.
  """
  return _ulid()


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def record(repo: Path, event: dict) -> None:  # type: ignore[type-arg]
  """
  Append one event to the journal. Best-effort — never raises into the caller.

  Guarantees:
    - Never raises into the caller; an internal failure is reported to stderr and the call
      returns normally.
    - Each event lands in the journal as one complete line; concurrent writers never produce a
      torn line.
    - A repeat of the immediately preceding event (same incident, phase, kind, cause, and detail)
      within a short window is dropped rather than appended.

  Notes:
    - A missing `id` or `ts` is filled in before the event is written, and an overlong `detail` is
      truncated to fit the line-length budget.

  Args:
    repo: Repository root containing the `.runtime/` directory.
    event: Event dict; at minimum `incident`, `phase`, `kind`, `cause`.
  """

  # Contract:
  # This call never raises into the caller; on any internal failure it is reported to
  # stderr and the call returns normally.

  try:
    # work on a copy so the caller's dict is never mutated, and stamp the identity fields it left out
    stamped = dict(event)
    stamped.setdefault(_F_ID, _ulid())
    stamped.setdefault(_F_TS, time.strftime(_TS_FMT, time.gmtime()))

    # an overlong detail is cut to its budget before the line is encoded
    detail = stamped.get(_F_DETAIL)
    if isinstance(detail, str) and len(detail) > _DETAIL_MAX:
      stamped[_F_DETAIL] = detail[:_DETAIL_MAX]
    line = json.dumps(stamped, ensure_ascii = False, separators = (",", ":"))

    # guard: oversized event would break single-write atomicity — shed refs/detail to fit
    if len(line.encode(_UTF8)) > _LINE_MAX:
      stamped.pop(_F_REFS, None)
      stamped[_F_DETAIL] = (stamped.get(_F_DETAIL) or "")[:200]
      line = json.dumps(stamped, ensure_ascii = False, separators = (",", ":"))
    path = Path(repo) / JOURNAL_REL

    # the last journal line is the baseline the dedupe window compares against
    prev = _last_event(path)

    # Domain(runtime.incidents):
    # # Crash-loop dedupe window
    # The journal is an incident's persistent memory, so a process that crashes and restarts must
    # still see its own recent history instead of starting blind. A new event that repeats the same
    # incident, phase, kind, cause, and detail as the journal's immediately preceding entry, within a
    # bounded window, adds no new fold signal and is dropped rather than recorded — otherwise a tight
    # crash loop floods the journal with copies of the same failure instead of leaving one entry the
    # operator can act on.

    # Contract:
    # A repeat of the immediately preceding event (same incident, phase, kind, cause, and
    # detail) within a short window is dropped rather than appended.

    # a repeat of the last journal line within the dedupe window adds no fold signal and is dropped
    if (prev is not None
        and all(prev.get(field) == stamped.get(field) for field in _DEDUP_KEYS)
        and time.time() - _event_unix(prev) < _DEDUP_WINDOW_SEC):
      return

    # Contract:
    # Each event lands in the journal as one complete line; concurrent writers on the
    # same journal never interleave into a torn line.

    # append the encoded line to the journal, creating the directory and file on first use
    path.parent.mkdir(parents = True, exist_ok = True)
    journal_fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, _MODE_RW_R_R)
    try:
      os.write(journal_fd, (line + "\n").encode(_UTF8))
    finally:
      os.close(journal_fd)
  except Exception as error:  # best-effort: recording an error must never crash the caller
    print(f"error_ledger.record failed: {error}", file = sys.stderr)


def resolve(repo: Path, incident: str, *, resolution: str, **extra: object) -> None:
  """
  Append a `resolved` event that folds `incident` to closed.

  Args:
    repo: Repository root containing the `.runtime/` directory.
    incident: Incident key to close.
    resolution: Short string describing the resolution outcome.
    **extra: Additional fields merged into the event.
  """
  event: dict[str, object] = {_F_INCIDENT: incident, _F_PHASE: _PH_RESOLVED, "resolution": resolution}
  event.update(extra)
  record(repo, event)


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _last_event(path: Path) -> dict | None:  # type: ignore[type-arg]
  """
  Return the journal's last parseable event, or `None` if there is none.

  Notes:
    - Cost is bounded and independent of journal size.

  Args:
    path: Journal file path.

  Returns:
    The last complete event dict, or `None` when the file is missing, empty,
    or its last line is torn/corrupt.
  """
  try:
    with open(path, "rb") as journal:
      journal.seek(0, os.SEEK_END)
      journal.seek(max(0, journal.tell() - _TAIL_READ_BYTES))
      tail = journal.read().decode(_UTF8, errors = _UTF8_ERRORS_REPLACE)
  except OSError:
    return None
  for raw in reversed(tail.splitlines()):
    line = raw.strip()

    # guard: trailing blank lines are not events — keep scanning upward
    if not line:
      continue
    try:
      return json.loads(line)
    except (ValueError, json.JSONDecodeError):
      # guard: torn last line (crash mid-write) — no dedupe basis, let the write proceed
      return None
  return None


# waiver: Iterator[dict] — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _iter_journal(repo: Path) -> Iterator[dict]:  # type: ignore[type-arg]
  """
  Yield parsed journal events, skipping torn or corrupt lines.

  Notes:
    - Memory usage stays bounded no matter how large the journal has grown.

  Args:
    repo: Repository root containing the `.runtime/` directory.

  Yields:
    Event dicts from the journal, in file order.
  """
  path = Path(repo) / JOURNAL_REL

  # guard: missing journal is normal on a fresh repo — yield nothing
  if not path.is_file():
    return
  with open(path, encoding = _UTF8, errors = _UTF8_ERRORS_REPLACE) as journal:
    for raw in journal:
      line = raw.strip()

      # guard: blank lines between records are not events — skip silently
      if not line:
        continue
      try:
        yield json.loads(line)
      except (ValueError, json.JSONDecodeError):
        # guard: corrupt line (e.g. crash mid-write) — skip, never break the read
        print(_MSG_CORRUPT_LINE, file = sys.stderr)


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _read_snapshot(repo: Path) -> dict:  # type: ignore[type-arg]
  """
  Return the retention snapshot, or an empty one when absent/unreadable.

  Args:
    repo: Repository root containing the `.runtime/` directory.

  Returns:
    A dict with at least `counters` and `open` keys.
  """
  path = Path(repo) / SNAPSHOT_REL
  try:
    return json.loads(path.read_text(encoding = _UTF8))
  except (OSError, ValueError, json.JSONDecodeError):
    return {"counters": {}, _SNAP_OPEN: []}


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _fold_state(events: list[dict]) -> str:  # type: ignore[type-arg]
  """
  Fold one incident's events to a state: closed / needs_operator / open.

  The incident's current state is determined by its most recent event in append order.

  Args:
    events: All events belonging to one incident, in append order.

  Returns:
    One of `closed`, `needs_operator`, or `open`.
  """

  # Decision: file order, not a timestamp sort, picks the last event — timestamps have second
  # resolution and cannot order events written within the same second

  # the newest event in append order carries the incident's current state
  last = events[-1]
  if last.get(_F_PHASE) == _PH_RESOLVED:
    return _ST_CLOSED
  if last.get(_F_PHASE) == _PH_TRIAGED and last.get(_F_CAUSE) == _CAUSE_PERMANENT_FAIL:
    return _ST_NEEDS_OPERATOR

  # Domain(runtime.incidents):
  # # Incident state folding
  # An incident's current state is read from only its most recent event, never a full history scan,
  # because the journal is append-only and so the last entry in file order is always the authoritative
  # one. A `resolved` entry closes the incident outright. Anything else opens it, except two escalation
  # paths that both skip ahead to needing an operator without a resolved entry: a triage conclusion
  # naming a permanent failure, and a daemon halt whose cause belongs to a fixed set of causes that
  # the runtime does not retry itself and that wait for an operator action. The set includes an
  # unreachable remote, although the doctor lifts that halt on its own once a probe of the remote
  # answers again after an hour; until it is lifted, such an incident reads as needing an operator.

  # daemon halts with human-action causes escalate without triage
  if last.get(_F_KIND) == _KIND_DAEMON_HALT and last.get(_F_CAUSE) in _HUMAN_HALT_CAUSES:
    return _ST_NEEDS_OPERATOR
  return _ST_OPEN


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def read_incidents(repo: Path, *,
                   state: str = _ST_ALL,
                   since: str | None = None) -> list[dict]:  # type: ignore[type-arg]
  """
  Fold the journal (+ snapshot) into one row per incident, newest first.

  Notes:
    - Memory scales with the incident count, not the total number of events in the journal.

  Args:
    repo: Repository root.
    state: Filter — `open`, `needs_operator`, `closed`, or `all`.
    since: Cursor — exclude incidents whose last event id (ULID) is less than or equal to it.
      ULIDs are lexicographically time-sortable, so a string compare is the correct ordering.
      `None` returns everything; the typical caller stores the latest returned `id` and replays
      with that cursor on the next pull.

  Returns:
    A list of incident dicts (`id`, `incident`, `state`, `kind`, `cause`, `severity`,
    `expert`, `job_id`, `routine`, `detail`, `ts`, `events`).
  """
  # folding only needs each incident's last event plus a count — never the full event lists
  # waiver: dict[str, dict] inner value is a mixed-type event dict; Any is banned; bare dict is the lesser evil
  last_by_incident: dict[str, dict] = {}  # type: ignore[type-arg]
  counts: dict[str, int] = {}
  kinds: dict[str, str] = {}
  for event in chain(_read_snapshot(repo).get(_SNAP_OPEN, []), _iter_journal(repo)):
    inc = event.get(_F_INCIDENT)
    if inc:
      last_by_incident[inc] = event
      counts[inc] = counts.get(inc, 0) + 1

      # a closing event names no class of its own, so the incident keeps the class its events last carried
      if event.get(_F_KIND):
        kinds[inc] = event.get(_F_KIND)
  out = []
  for inc, last in last_by_incident.items():
    fold = _fold_state([ last ])

    # keep only incidents in the state the caller asked for
    if state not in (_ST_ALL, fold):
      continue

    # ULIDs sort lexicographically by time, so the last event's id doubles as the cursor value
    last_id = last.get(_F_ID, "")

    # keep only incidents newer than the since-cursor
    if since is not None and isinstance(last_id, str) and last_id <= since:
      continue
    out.append({
      _F_ID: last_id,
      _F_INCIDENT: inc, _F_STATE: fold,
      _F_KIND: last.get(_F_KIND) or kinds.get(inc), _F_CAUSE: last.get(_F_CAUSE),
      _F_SEVERITY: last.get(_F_SEVERITY, _SEV_ERROR),
      _F_EXPERT: last.get(_F_EXPERT), _F_JOB_ID: last.get(_F_JOB_ID),
      _F_ROUTINE: last.get(_F_ROUTINE), _F_DETAIL: last.get(_F_DETAIL, ""),
      _F_TS: last.get(_F_TS), "events": counts[inc],
    })
  out.sort(key = lambda row: row.get(_F_TS) or "", reverse = True)
  return out


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def build_summary(repo: Path) -> dict:  # type: ignore[type-arg]
  """
  Return aggregate counts: `{by_state: {...}, total_incidents: N}`.

  Args:
    repo: Repository root.

  Returns:
    A dict with `by_state` (counts per state) and `total_incidents`.
  """
  incs = read_incidents(repo, state = _ST_ALL)
  by_state: dict[str, int] = {}
  for row in incs:
    by_state[row[_F_STATE]] = by_state.get(row[_F_STATE], 0) + 1
  return {"by_state": by_state, "total_incidents": len(incs)}


# waiver: bare dict param — event dicts carry mixed-type values; Any is banned; bare dict is the lesser evil
def _event_unix(event: dict) -> float:  # type: ignore[type-arg]
  """
  Parse an event's UTC timestamp to epoch seconds.

  Args:
    event: Event dict.

  Returns:
    Epoch seconds, or `0.0` when the timestamp is missing or unparseable (treated as ancient).
  """
  try:
    return float(calendar.timegm(time.strptime(event.get(_F_TS, ""), _TS_FMT)))
  except (ValueError, TypeError):
    return 0.0


# waiver: dict[str, object] annotation is caller-hostile — snapshot carries mixed-type values; Any is banned; bare dict is the lesser evil
def _write_snapshot(repo: Path, snap: dict) -> None:  # type: ignore[type-arg]
  """
  Atomically write the retention snapshot via a temp file and rename.

  Args:
    repo: Repository root.
    snap: Snapshot dict to persist.
  """
  path = Path(repo) / SNAPSHOT_REL
  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_name(path.name + _TMP_SUFFIX)
  tmp.write_text(json.dumps(snap, ensure_ascii = False, indent = 2), encoding = _UTF8)
  os.replace(tmp, path)


def _gc_gone_job_incidents(repo: Path) -> int:
  """
  Close open job incidents whose job directory no longer exists.

  A job incident whose `.experts/.jobs/<expert>/<job_id>` directory was consumed or
  cancelled cannot resolve on its own; this best-effort sweep closes it as `resolved:gone`
  so the open set never accumulates forever.

  Args:
    repo: Repository root.

  Returns:
    The number of incidents closed as `resolved:gone`.
  """
  closed = 0
  for inc in read_incidents(repo, state = _ST_OPEN) + read_incidents(repo, state = _ST_NEEDS_OPERATOR):
    key = inc.get(_F_INCIDENT, "")

    # guard: only job incidents map to a job directory
    if not key.startswith(_JOB_PREFIX):
      continue
    jdir = Path(repo) / _JOBS_BASE_REL / key[len(_JOB_PREFIX):]

    # Domain(runtime.incidents):
    # # Job incidents die with their job
    # An incident opened for a running job has no path back to `resolved` once the job it names has
    # already been consumed or cancelled — nothing will ever triage or close it through the normal
    # channel again. Such an incident is closed here as gone rather than left open or escalated,
    # because an open incident that can never be acted on is worse than silence: it would sit in the
    # operator's queue forever pointing at work that no longer exists.

    # guard: job dir still present — the incident is genuinely live
    if jdir.exists():
      continue
    # waiver: one-off actor label for the prune CLI path
    resolve(repo, key, resolution = _RES_GONE, kind = inc.get(_F_KIND), actor = "prune")
    closed += 1
  return closed


# waiver: dict[str, object] annotation is caller-hostile — result carries mixed-type values; Any is banned; bare dict is the lesser evil
def prune(repo: Path, retention_days: int) -> dict:  # type: ignore[type-arg]
  """
  Drop expired closed incidents and over-cap events, counting dropped openings in the snapshot.

  Guarantees:
    - An open or needs-operator incident is never pruned by age: age alone never drops any of its
      events. An incident is dropped as a whole only when it is closed and its last event is older
      than `retention_days`; a closed incident whose last event is inside the window keeps all of
      its events as far as age is concerned.
    - Every incident that survives pruning keeps its first 10 and its last 40 events, in their
      original order; the events in between are dropped. The all-time per-kind counters still count
      every dropped `opened` event, so the snapshot counter plus the kept `opened` events equals all
      `opened` events ever recorded.

  Notes:
    - Dropped `opened` events bump cumulative per-kind counters retained in the snapshot.
    - Snapshot entries that earlier passes carried forward for open incidents stay until those incidents
      expire; no new entries are carried.
    - Memory scales with the incident count, not the total number of events in the journal.

  Args:
    repo: Repository root.
    retention_days: Age window in days.

  Returns:
    A dict with `pruned`, `kept`, and `carried` counts.
  """
  _gc_gone_job_incidents(repo)
  cutoff = time.time() - retention_days * _SECONDS_PER_DAY
  snap = _read_snapshot(repo)
  counters = dict(snap.get(_SNAP_COUNTERS, {}))

  # Contract:
  # An open or needs-operator incident is never pruned by age: age alone never drops any of its
  # events, however old they are. An incident is dropped as a whole only when it is closed and its
  # last event is older than `retention_days`. A closed incident whose last event is inside the
  # window keeps all of its events as far as age is concerned.

  # Contract:
  # Every incident that survives pruning keeps its first 10 and its last 40 events, in their
  # original order; the events in between are dropped. The all-time per-kind counters still count
  # every dropped `opened` event, so the snapshot counter plus the kept `opened` events equals all
  # `opened` events ever recorded.

  # Domain(runtime.incidents):
  # # Retention drops whole closed incidents and caps the rest
  # An incident is retired as a whole, every one of its events at once, and only when two conditions
  # hold together: it is closed, and its last event is older than the retention window. An open or
  # needs-operator incident is never pruned by age, however old its events are, and a closed incident
  # whose last event is still inside the window keeps all of its events. Events are never aged out one
  # by one inside a live incident. Because age is counted from the last event, an incident that was
  # closed and then reopened by a new event counts as open, so a recently reopened incident is never
  # written off as old. Retention snapshot entries that an earlier pass carried forward stay until
  # their incident expires.
  # Every incident also keeps only its first 10 and its last 40 events; the events in between are
  # dropped, so one noisy incident can never grow the journal without bound. The first events show
  # how the incident began and the last ones show where it stands now. The periodic prune applies
  # this cap, not the write.
  # Only a dropped `opened` event advances the all-time per-kind counters, so an incident's later
  # phases are never counted as new occurrences of the same kind. The all-time count therefore still
  # covers dropped events, and the gap between it and the kept history shows how many were lost.

  # pass 1 — per-incident latest event + journal event count; snapshot first so journal events win
  # waiver: dict[str, dict] inner value is a mixed-type event dict; Any is banned; bare dict is the lesser evil
  latest: dict[str, dict] = {}  # type: ignore[type-arg]
  totals: dict[str, int] = {}
  for event in snap.get(_SNAP_OPEN, []):
    inc = event.get(_F_INCIDENT)
    if inc:
      latest[inc] = event
  for event in _iter_journal(repo):
    inc = event.get(_F_INCIDENT)
    if inc:
      latest[inc] = event
      totals[inc] = totals.get(inc, 0) + 1

  # an incident leaves the ledger whole only when it is closed and its last event aged past the window
  expired = {
    inc for inc, event in latest.items()
    if _fold_state([ event ]) == _ST_CLOSED and _event_unix(event) < cutoff
  }

  # pass 2 — stream kept events straight to the tmp journal
  path = Path(repo) / JOURNAL_REL
  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_name(path.name + _TMP_SUFFIX)
  pruned = 0
  kept = 0
  seen: dict[str, int] = {}
  with open(tmp, "w", encoding = _UTF8) as out:
    for event in _iter_journal(repo):
      inc = event.get(_F_INCIDENT)
      if inc:
        seen[inc] = seen.get(inc, 0) + 1

        # an expired closed incident loses every event; a live one keeps only its first _CAP_HEAD and
        # last _CAP_TAIL events; an incident appended after pass 1 has no total yet and is kept whole
        drop = inc in expired or _CAP_HEAD < seen[inc] <= totals.get(inc, 0) - _CAP_TAIL
      else:
        # an event outside any incident has nothing to keep it alive, so age alone retires it
        drop = _event_unix(event) < cutoff
      if drop:
        pruned += 1

        # only `opened` events advance the all-time error counter
        if event.get(_F_PHASE) == _PH_OPENED:
          kind = event.get(_F_KIND, _UNKNOWN_KIND)
          counters[kind] = counters.get(kind, 0) + 1
        continue
      out.write(json.dumps(event, ensure_ascii = False, separators = (",", ":")) + "\n")
      kept += 1

  # snapshot entries an earlier pass carried forward stay until their incident expires
  carry = [ event for event in snap.get(_SNAP_OPEN, []) if event.get(_F_INCIDENT) not in expired ]
  _write_snapshot(repo, {_SNAP_COUNTERS: counters, _SNAP_OPEN: carry})
  os.replace(tmp, path)
  return {"pruned": pruned, "kept": kept, "carried": len(carry)}
