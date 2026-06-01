"""
Error ledger for the lazycortex-core autonomous runtime.

The append-only event journal (`.runtime/errors.jsonl`) is the source of truth;
each incident's state (open / needs_operator / closed) is folded on read by its
`incident` key. A retention snapshot (`.runtime/errors.state.json`) carries
cumulative counters plus the latest event of still-open incidents that have aged
past the window, so the journal can be pruned without losing live incidents.

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
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


JOURNAL_REL = ".runtime/errors.jsonl"
SNAPSHOT_REL = ".runtime/errors.state.json"
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DETAIL_MAX = 500
_LINE_MAX = 4096
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_HUMAN_HALT_CAUSES = {
  "git_pull_diverged", "git_push_failed", "git_remote_unavailable",
  "config_violation", "suspected_loop",
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

_PH_OPENED = "opened"
_SECONDS_PER_DAY = 86400
_UNKNOWN_KIND = "unknown"
_TMP_SUFFIX = ".tmp"
_SNAP_COUNTERS = "counters"
_JOB_PREFIX = "job:"
_JOBS_BASE_REL = ".experts/.jobs"
_RES_GONE = "gone"


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

  The CLI mints one before `record()` so the published response (`{"recorded": true, "id": "<ulid>"}`)
  can carry the same id that lands in the journal. `record()` mints its own id only when the caller
  did not pre-fill `id`.

  Returns:
    A new 26-character ULID, time-sortable.
  """
  return _ulid()


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def record(repo: Path, event: dict) -> None:  # type: ignore[type-arg]
  """
  Append one event to the journal. Best-effort — never raises into the caller.

  Fills `id` (ULID) and `ts` (UTC) when absent, truncates `detail`, and writes a
  single atomic O_APPEND line. A failed write degrades to a stderr note.

  Args:
    repo: Repository root containing the `.runtime/` directory.
    event: Event dict; at minimum `incident`, `phase`, `kind`, `cause`.
  """
  try:
    ev = dict(event)
    ev.setdefault(_F_ID, _ulid())
    ev.setdefault(_F_TS, time.strftime(_TS_FMT, time.gmtime()))
    detail = ev.get(_F_DETAIL)
    if isinstance(detail, str) and len(detail) > _DETAIL_MAX:
      ev[_F_DETAIL] = detail[:_DETAIL_MAX]
    line = json.dumps(ev, ensure_ascii = False, separators = (",", ":"))
    # guard: oversized event would break single-write atomicity — shed refs/detail to fit
    if len(line.encode(_UTF8)) > _LINE_MAX:
      ev.pop(_F_REFS, None)
      ev[_F_DETAIL] = (ev.get(_F_DETAIL) or "")[:200]
      line = json.dumps(ev, ensure_ascii = False, separators = (",", ":"))
    path = Path(repo) / JOURNAL_REL
    path.parent.mkdir(parents = True, exist_ok = True)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, _MODE_RW_R_R)
    try:
      os.write(fd, (line + "\n").encode(_UTF8))
    finally:
      os.close(fd)
  except Exception as e:  # best-effort: recording an error must never crash the caller
    print(f"error_ledger.record failed: {e}", file = sys.stderr)


def resolve(repo: Path, incident: str, *, resolution: str, **extra: object) -> None:
  """
  Append a `resolved` event that folds `incident` to closed.

  Args:
    repo: Repository root containing the `.runtime/` directory.
    incident: Incident key to close.
    resolution: Short string describing the resolution outcome.
    **extra: Additional fields merged into the event.
  """
  ev: dict[str, object] = {_F_INCIDENT: incident, _F_PHASE: _PH_RESOLVED, "resolution": resolution}
  ev.update(extra)
  record(repo, ev)


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _read_journal(repo: Path) -> list[dict]:  # type: ignore[type-arg]
  """
  Return parsed journal events, silently skipping torn/corrupt lines.

  Args:
    repo: Repository root containing the `.runtime/` directory.

  Returns:
    A list of event dicts from the journal, in file order.
  """
  path = Path(repo) / JOURNAL_REL
  # guard: missing journal is normal on a fresh repo — return empty
  if not path.is_file():
    return []
  out = []
  for raw in path.read_text(encoding = _UTF8, errors = _UTF8_ERRORS_REPLACE).splitlines():
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    raw = raw.strip()  # noqa: PLW2901
    # guard: blank lines between records are not events — skip silently
    if not raw:
      continue
    try:
      out.append(json.loads(raw))
    except (ValueError, json.JSONDecodeError):
      # guard: corrupt line (e.g. crash mid-write) — skip, never break the read
      print(_MSG_CORRUPT_LINE, file = sys.stderr)
  return out


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
def _all_events(repo: Path) -> list[dict]:  # type: ignore[type-arg]
  """
  Snapshot-carried open events plus the live journal.

  Args:
    repo: Repository root.

  Returns:
    Combined list of event dicts, snapshot events first.
  """
  return list(_read_snapshot(repo).get(_SNAP_OPEN, [])) + _read_journal(repo)


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _fold_state(events: list[dict]) -> str:  # type: ignore[type-arg]
  """
  Fold one incident's events to a state: closed / needs_operator / open.

  The journal is append-only, so the last event in causal order is authoritative;
  second-resolution timestamps cannot order same-second events, so file order — not
  a timestamp sort — decides the current state.

  Args:
    events: All events belonging to one incident, in append order.

  Returns:
    One of `closed`, `needs_operator`, or `open`.
  """
  last = events[-1]
  if last.get(_F_PHASE) == _PH_RESOLVED:
    return _ST_CLOSED
  if last.get(_F_PHASE) == _PH_TRIAGED and last.get(_F_CAUSE) == _CAUSE_PERMANENT_FAIL:
    return _ST_NEEDS_OPERATOR
  # guard: daemon halts with human-action causes escalate without triage
  if last.get(_F_KIND) == _KIND_DAEMON_HALT and last.get(_F_CAUSE) in _HUMAN_HALT_CAUSES:
    return _ST_NEEDS_OPERATOR
  return _ST_OPEN


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def incidents(repo: Path, *, state: str = _ST_ALL, since: str | None = None) -> list[dict]:  # type: ignore[type-arg]
  """
  Fold the journal (+ snapshot) into one row per incident, newest first.

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
  # waiver: dict[str, list[dict]] — inner list carries mixed-type event dicts; Any is banned; bare dict is the lesser evil
  by_incident: dict[str, list[dict]] = {}  # type: ignore[type-arg]
  for ev in _all_events(repo):
    inc = ev.get(_F_INCIDENT)
    if inc:
      by_incident.setdefault(inc, []).append(ev)
  out = []
  for inc, evs in by_incident.items():
    st = _fold_state(evs)
    # guard: state filter — skip if caller restricted to a specific state
    if state not in (_ST_ALL, st):
      continue
    last = evs[-1]
    # guard: --since cursor — ULIDs sort lexicographically by time, drop anything not newer
    last_id = last.get(_F_ID, "")
    # guard: skip incidents at or before the since-cursor
    if since is not None and isinstance(last_id, str) and last_id <= since:
      continue
    out.append({
      _F_ID: last_id,
      _F_INCIDENT: inc, _F_STATE: st,
      _F_KIND: last.get(_F_KIND), _F_CAUSE: last.get(_F_CAUSE),
      _F_SEVERITY: last.get(_F_SEVERITY, _SEV_ERROR),
      _F_EXPERT: last.get(_F_EXPERT), _F_JOB_ID: last.get(_F_JOB_ID),
      _F_ROUTINE: last.get(_F_ROUTINE), _F_DETAIL: last.get(_F_DETAIL, ""),
      _F_TS: last.get(_F_TS), "events": len(evs),
    })
  out.sort(key = lambda i: i.get(_F_TS) or "", reverse = True)
  return out


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def summary(repo: Path) -> dict:  # type: ignore[type-arg]
  """
  Return aggregate counts: `{by_state: {...}, total_incidents: N}`.

  Args:
    repo: Repository root.

  Returns:
    A dict with `by_state` (counts per state) and `total_incidents`.
  """
  incs = incidents(repo, state = _ST_ALL)
  by_state: dict[str, int] = {}
  for i in incs:
    by_state[i[_F_STATE]] = by_state.get(i[_F_STATE], 0) + 1
  return {"by_state": by_state, "total_incidents": len(incs)}


# waiver: bare dict param — event dicts carry mixed-type values; Any is banned; bare dict is the lesser evil
def _event_unix(ev: dict) -> float:  # type: ignore[type-arg]
  """
  Parse an event's UTC timestamp to epoch seconds.

  Args:
    ev: Event dict.

  Returns:
    Epoch seconds, or `0.0` when the timestamp is missing or unparseable (treated as ancient).
  """
  try:
    return float(calendar.timegm(time.strptime(ev.get(_F_TS, ""), _TS_FMT)))
  except (ValueError, TypeError):
    return 0.0


# waiver: dict[str, object] annotation is caller-hostile — event dicts carry mixed-type values; Any is the correct type but banned; bare dict is the lesser evil
def _latest_per_incident(events: list[dict]) -> dict[str, dict]:  # type: ignore[type-arg]
  """
  Map each incident to its newest event by append order (last occurrence wins).

  Args:
    events: Events in append order.

  Returns:
    A mapping of incident key to its latest event.
  """
  # waiver: dict[str, dict] inner value is a mixed-type event dict; Any is banned; bare dict is the lesser evil
  latest: dict[str, dict] = {}  # type: ignore[type-arg]
  for ev in events:
    inc = ev.get(_F_INCIDENT)
    if inc:
      latest[inc] = ev
  return latest


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


# waiver: list[dict] inner value is a mixed-type event dict; Any is banned; bare dict is the lesser evil
def _rewrite_journal(repo: Path, events: list[dict]) -> None:  # type: ignore[type-arg]
  """
  Atomically replace the journal with the given events via a temp file and rename.

  Args:
    repo: Repository root.
    events: Events to write as the new journal body, in order.
  """
  path = Path(repo) / JOURNAL_REL
  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_name(path.name + _TMP_SUFFIX)
  body = "".join(json.dumps(e, ensure_ascii = False, separators = (",", ":")) + "\n" for e in events)
  tmp.write_text(body, encoding = _UTF8)
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
  for inc in incidents(repo, state = _ST_OPEN) + incidents(repo, state = _ST_NEEDS_OPERATOR):
    key = inc.get(_F_INCIDENT, "")
    # guard: only job incidents map to a job directory
    if not key.startswith(_JOB_PREFIX):
      continue
    jdir = Path(repo) / _JOBS_BASE_REL / key[len(_JOB_PREFIX):]
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
  Drop journal events older than the window, folding them into the snapshot.

  Young events stay in the journal verbatim. A still-open or needs-operator incident
  whose every event aged out is carried forward as its latest event in the snapshot,
  so it never vanishes. Dropped `opened` events bump cumulative per-kind counters.

  Args:
    repo: Repository root.
    retention_days: Age window in days.

  Returns:
    A dict with `pruned`, `kept`, and `carried` counts.
  """
  _gc_gone_job_incidents(repo)
  cutoff = time.time() - retention_days * _SECONDS_PER_DAY
  events = _read_journal(repo)
  snap = _read_snapshot(repo)
  counters = dict(snap.get(_SNAP_COUNTERS, {}))
  states = {i[_F_INCIDENT]: i[_F_STATE] for i in incidents(repo, state = _ST_ALL)}
  kept = [e for e in events if _event_unix(e) >= cutoff]
  kept_incidents = {e.get(_F_INCIDENT) for e in kept}
  dropped = [e for e in events if _event_unix(e) < cutoff]
  for e in dropped:
    # guard: only `opened` events advance the all-time error counter
    if e.get(_F_PHASE) == _PH_OPENED:
      k = e.get(_F_KIND, _UNKNOWN_KIND)
      counters[k] = counters.get(k, 0) + 1
  latest = _latest_per_incident(events + list(snap.get(_SNAP_OPEN, [])))
  carry = [
    latest[inc] for inc, st in states.items()
    if st in (_ST_OPEN, _ST_NEEDS_OPERATOR) and inc not in kept_incidents and inc in latest
  ]
  _write_snapshot(repo, {_SNAP_COUNTERS: counters, _SNAP_OPEN: carry})
  _rewrite_journal(repo, kept)
  return {"pruned": len(dropped), "kept": len(kept), "carried": len(carry)}
