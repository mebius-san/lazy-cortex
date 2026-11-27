"""
Implementation of `lazycortex-core expert-pump-once` subcommand.

Drives one pump tick of the expert-job queue: marks stuck jobs as dead
and dispatches at most one READY job to a `claude -p` subprocess. The routine-level timeout the daemon
applies to `lazy-expert.pump` is the only ceiling on a single Claude
spawn — pump never runs more than one spawn per invocation.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import error_ledger  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import commit_guard  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error
# waiver: ReferenceError is reference_resolver's domain exception, not the builtin
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from reference_resolver import resolve, ReferenceError  # pylint: disable=import-error,redefined-builtin
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from runtime_daemon import UNREADABLE_TREE_LINE, check_working_tree, record_halt  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from plugin_dirs import is_cache_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable-next=import-error
from job_response import classify_response, is_job_bundle, is_success, outcome_tokens, read_response
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from worktree_tasks import WorktreeStartError, WorktreeTaskManager  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from provider_env import ProviderKey, apply_spawn_env, resolve_token  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from routine_types import build_protocols_env  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import rate_limit_flag  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import recover  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import sandbox_scope  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  ClaudeSettingsFile, ClaudeSettingsKey,
  DaemonKey, EnvVar, GitConfigKey, HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  IncidentSeverity, JobArtifact, JobConfigKey, JobErrorCategory, JobFile, JobIODir, JobLogOutcome, JobMarker,
  JobOutcome, JobRequestKey, JobResponseKey, JobStatus, RateLimitGuardKey, RateLimitRecordKey, RuntimeFile,
  SettingsFile, SettingsKey, WorkspaceMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import IO

  from collections.abc import Mapping


JOBS_BASE = ".experts/.jobs"
# The pump's own routine name, recorded as the trigger of every halt the pump raises.
_PUMP_ROUTINE = "lazy-expert.pump"
# The cause of the warning recorded when the pump removed a job's stray result copies instead of halting.
_STRAY_COPY_CAUSE = "stray_result_copy"
# The stable cause of the incident a job gets when a call could neither close nor reconcile it and
# could not raise for it either.
_UNCLOSABLE_CAUSE = "job_unclosable"
# The text an isolated job's work-tree check returns when the tree itself could not be read, so its state is
# unknown; the per-job run tells it from a broken commit obligation by this exact text.
_TREE_CHECK_FAILED = "the worktree could not be read after the run: `git status` exited non-zero"
# The text an isolated job's work-tree check opens with when the run left uncommitted changes; the listing follows.
_DIRTY_TREE_FAILURE = "isolated job left the worktree dirty"
# The text an isolated job's work-tree check returns when a clean run left its branch where the spawn found it.
_NO_NEW_COMMITS_FAILURE = "isolated job finished with no new commits and a clean tree"
# The failure text a job is closed with once it was found to have committed although barred from committing.
_FORBIDDEN_COMMIT_FAILURE = (
  "job barred from committing in the repository committed (see the forbidden_commit halt); it never runs again — "
  "re-dispatch the work as a new job"
)
# The temp file a claim's copy record is written into before it is renamed over the record itself.
_CLAIM_COPIES_TMP = f"{JobArtifact.CLAIM_COPIES}.tmp"

# Idle-watchdog defaults. A `claude -p` stream whose stdout is silent longer than
# _STREAM_IDLE_TIMEOUT_DEFAULT seconds is treated as a transient freeze; the spawn's
# process group is killed and re-spawned up to _STREAM_MAX_RETRIES_DEFAULT times.
# Both are overridable via daemon.stream_idle_timeout_sec / daemon.stream_max_retries.
_STREAM_IDLE_TIMEOUT_DEFAULT = 900
_STREAM_MAX_RETRIES_DEFAULT  = 3
# Watchdog read-loop poll cadence (seconds): how often the idle timer is re-checked while
# stdout is silent. Small enough to react promptly, large enough to idle cheaply.
_WATCHDOG_POLL_SEC = 1.0
# Grace between SIGTERM and SIGKILL when tearing down a stalled spawn's process group.
_KILL_GRACE_SEC = 5.0
# Locations macOS TCC gates behind a consent prompt. A background `claude -p` that loads one of
# them through `permissions.additionalDirectories` blocks at startup on a prompt no one can answer.
_TCC_PROTECTED_ROOTS = ( "~/Downloads", "~/Desktop", "~/Documents", "~/Library/Mobile Documents", "/Volumes" )
# Dead-scan grace window (seconds): a claimed job whose claimant PID is gone but which has
# no response.json yet is first tagged with a DEAD_CANDIDATE marker; DEAD lands only when a
# later scan still finds no response.json after this window. The PID file holds the pump's
# own pid, so a pump killed by the routine timeout looks dead while the spawned Claude
# subprocess may still be seconds away from writing response.json — the window covers that.
_DEAD_GRACE_SEC = 60.0
# How many spawns of one bundle may end in a violated response envelope before the job is
# failed for good. One corrective re-spawn separates a slip of a single run from a fault
# baked into the expert's protocol, which no number of re-spawns would fix.
_ENVELOPE_RETRY_LIMIT = 1
# Sentence added to a continuation's isolation paragraph when its dispatcher allowed a commitless finish, so the
# expert neither forces an empty commit nor reads an unchanged tree as a failure.
_COMMITLESS_CONTINUATION_NOTE = (
  "If this round needs no change to any file, commit nothing and still report success in "
  "response.json — never make an empty commit just to move the branch."
)
# Warnings for a payload branch and a workspace setting that disagree: a main-workspace expert handed a branch, and a
# branch-workspace expert handed none. Either way the job runs on the current checkout.
_PAYLOAD_BRANCH_IGNORED = ("workspace: {expert!r} is workspace:{workspace!r} — ignoring payload branch {branch!r}, "
                           "job runs on the current checkout\n")
_PAYLOAD_BRANCH_MISSING = ("workspace: {expert!r} is workspace:branch but this job carries no payload branch — "
                           "job runs on the current checkout\n")
# Rejection text handed back to the expert on its corrective re-spawn and recorded as the
# incident detail when the retry budget is spent.
_ENVELOPE_VIOLATION_MESSAGE = (
  "response.json carries no `outcome` field. The response envelope (`outcome`, `error`, "
  "`result`) belongs to the expert-runtime contract; a protocol may add fields and define "
  "the values `outcome` takes, but never replace it with a status field of its own."
)
# Stderr warning for a subscription run that did not stall, a failed one included, and carried no rate-limit
# frame; filled with the expert name, the job id and the process exit code.
RATE_LIMIT_BLIND_TEMPLATE = (
  "rate-limit guard: no rate_limit_event frame in {expert}/{job} "
  "(exit={exit}) — guard blind for this run\n"
)

# Runtime bookkeeping files the dead-job record leaves out of the expert's partial output.
_DEAD_JSON_INTERNAL_FILES = {
  JobMarker.READY, JobMarker.PID, JobFile.REQUEST, JobMarker.DEAD, JobMarker.DEAD_CANDIDATE,
  JobArtifact.DEAD_JSON, JobArtifact.CLAIM_COPIES, _CLAIM_COPIES_TMP,
}
# Job-liveness classification thresholds (seconds): a job that died faster than
# _STARTUP_CRASH_SEC with no output likely crashed at startup; one alive longer
# than _HUNG_JOB_SEC with no output was likely hung or killed.
_STARTUP_CRASH_SEC = 5
_HUNG_JOB_SEC = 3600
# Tools that never write to the repository; an agent restricted to them is read-only.
_READ_ONLY_TOOLS = frozenset({
  "Read", "Grep", "Glob",
  "WebFetch", "WebSearch",
  "BashOutput",
  "ListMcpResourcesTool", "ReadMcpResourceTool",
})
# Valid `--setting-sources` scopes (claude rejects anything else with
# "Invalid setting source: … Valid options are: user, project, local").
VALID_SETTING_SOURCES = ( "user", "project", "local" )
# Hermetic default when an expert declares no `setting_sources`: drop `user`
# scope so interactive operator plugins/hooks (e.g. a Warp PostToolUse hook that
# blocks a headless spawn on every tool call) never load, while keeping the
# project's own skills / agents / plugins. Mirrors always-on `--strict-mcp-config`.
_DEFAULT_SETTING_SOURCES = ( "project", "local" )
# The envelope requirement every spawn prompt states; a response missing the field is rejected.
_ENVELOPE_RULE = (
  "response.json MUST carry an `outcome` field: a value from your protocol's outcome enum, "
  "the reserved `error` with an `error` object, or the reserved `deferred` when you "
  "deliberately did none of the work and left every input untouched. A protocol names the values, never the "
  "field — if yours prescribes some other status field, write `outcome` anyway and report "
  "the contradiction in your summary. A response without `outcome` is rejected, and work "
  "reported as done through any other field is read as a failure."
)
# The marker that opens the correction paragraph a re-spawn receives after a rejection.
_CORRECTION_MARKER = "CORRECTION"



# ----------------------------------------------------------------------------------------
class _BranchOriginKind(StrEnum):
  """
  The answers a job's branch-origin record holds.

  Attributes:
    EXISTED: The branch existed before the job's first attempt.
    CREATED: The job's first attempt created the branch.
  """

  # The branch existed before the job's first attempt.
  EXISTED = "existed"
  # The job's first attempt created the branch.
  CREATED = "created"



# ----------------------------------------------------------------------------------------
def _marker_mtime(jdir: Path, marker: str) -> float | None:
  """
  Read the modification time of a job marker, or report its absence.

  Args:
    jdir: Path to the job directory the marker belongs to.
    marker: Filename of the marker being read.

  Returns:
    The marker's modification time, or `None` when the marker is not there.
  """
  path = jdir / marker

  # guard: an unarmed or unclaimed bundle simply has no such marker to time
  if not path.exists():
    return None
  return path.stat().st_mtime


def _is_abandoned_bundle(jdir: Path) -> bool:
  """
  Report whether a job bundle was left behind by a dispatch that never armed it.

  Args:
    jdir: Path to the job directory being judged.

  Returns:
    `True` when the bundle carries none of the markers a dispatched job acquires.
  """

  # Decision: absence of every marker is the signature, rather than absence of READY alone —
  # a dispatch writes the request and the config first and touches READY last, so a bundle with
  # no marker at all is one whose dispatch died in that window. The pump would otherwise skip it
  # forever as "still being assembled", the collector would never reap it (it reaps only the
  # terminal markers), and it would sit in the queue depth as work that never drains.

  # Domain(runtime.jobs):
  # # Dispatch order and the abandoned-bundle signature
  # A job's request and configuration are written before the job is armed for the queue, and
  # the queue marker is the last thing a dispatch touches. A bundle carrying none of the
  # markers a dispatched job goes on to acquire is therefore not one still being assembled —
  # it is one whose dispatch died in the narrow window before arming, and it never becomes
  # ready on its own. Only the complete absence of every such marker counts as that signature;
  # any single one present means some other stage already owns the bundle's fate.

  # any marker at all means the dispatch completed and some other branch owns the bundle
  return not any(
    (jdir / marker).exists()
    for marker in (JobMarker.READY, JobMarker.PID, JobMarker.DONE, JobMarker.DEAD, JobMarker.CANCELLED)
  )


def _mark_dead(repo: Path, expert: str, jdir: Path, blob: dict) -> int:
  """
  Bury a job bundle: write its forensic record, mark it dead, and open an incident.

  Notes:
    - Records a `job_dead` incident in the error ledger keyed on the bundle.

  Args:
    repo: Repository root whose logs and error ledger receive the death.
    expert: Name of the expert that owned the bundle.
    jdir: Path to the job directory being buried.
    blob: Forensic payload composed by `_build_dead_json` before this call.

  Returns:
    One, so a caller can add the result straight to its marked count.
  """
  # the record lands before the marker so nothing can observe a death without its forensics
  (jdir / JobMarker.DEAD_CANDIDATE).unlink(missing_ok = True)
  (jdir / JobArtifact.DEAD_JSON).write_text(json.dumps(blob, indent = 2), encoding = "utf-8")
  (jdir / JobMarker.DEAD).touch()
  _append_jobs_log(repo, expert, jdir.name, JobLogOutcome.DEAD)

  # the incident carries the forensic label forward so triage reads the cause without the file
  # waiver: small internal subkey, not a reusable domain key
  cause = blob.get("likely_cause", "unknown")
  error_ledger.record(repo, {
    IncidentKey.INCIDENT: f"job:{expert}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: cause, IncidentKey.ACTOR: IncidentActor.PUMP,
    IncidentKey.EXPERT: expert, IncidentKey.JOB_ID: jdir.name, IncidentKey.DETAIL: f"job DEAD: {cause}",
    IncidentKey.REFS: { "jdir": str(jdir), "dead_json": str(jdir / JobArtifact.DEAD_JSON) },
  })
  return 1


def _build_dead_json(jdir: Path, expert: str, job_id: str, marked_at: float) -> dict:
  """
  Compose the forensic payload describing a job that was marked dead.

  Notes:
    - The dedup key is `None` whenever the bundle's `request.json` cannot be read, is not UTF-8 text, is not
      valid JSON, or is not a JSON object; such a request never makes the call raise.

  Args:
    jdir: Path to the job directory whose state is being captured.
    expert: Name of the expert that owned the job.
    job_id: Identifier of the job within the expert's queue.
    marked_at: Wall-clock timestamp at which the job was marked dead.

  Returns:
    A dict carrying queue and claim timestamps, the original PID, an optional dedup key,
    the list of partial output files, and a heuristic likely-cause label. The two timestamps
    are `None` for a bundle whose dispatch died before it was ever armed or claimed, and the
    durations derived from them are `None` with them.
  """

  # a bundle abandoned mid-dispatch carries neither marker, so both timestamps stay open
  queued_at = _marker_mtime(jdir, JobMarker.READY)
  claimed_at = _marker_mtime(jdir, JobMarker.PID)

  # the claimant PID as recorded at claim time; -1 when the marker is gone or garbled
  try:
    original_pid = int((jdir / JobMarker.PID).read_text(encoding = "utf-8").strip())
  except (OSError, ValueError):
    original_pid = -1

  # carry the dedup key forward so a re-dispatch can be matched against this death; the key is
  # optional forensic data, so a request that cannot be read as an object yields none and the
  # job is buried all the same
  dedup_key = None
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    # `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
    request = None
  if isinstance(request, dict):
    dedup_key = request.get(JobRequestKey.DEDUP_KEY)

  # collect names of files the expert produced before dying — excludes runtime bookkeeping files
  partial_output = sorted(
    entry.name for entry in jdir.iterdir()
    if entry.name not in _DEAD_JSON_INTERNAL_FILES
  )

  # time the claimant survived after claiming, floored at zero against clock skew
  duration_alive_sec = None if claimed_at is None else max(0.0, marked_at - claimed_at)

  # how long the bundle waited between arming and claim, open when either end is missing
  duration_queued_sec = (
    None if queued_at is None or claimed_at is None else max(0.0, claimed_at - queued_at)
  )

  # Domain(runtime.job-execution):
  # # Startup-crash and hung-job classification
  # A dead job's likely cause is read from how long its claimant survived and whether it left
  # any output behind before dying. A claimant that dies almost immediately with nothing to
  # show for it most likely crashed at startup; one that stayed alive far longer than any
  # real run should, again with nothing produced, was most likely hung or killed outright.
  # Any output at all before death points instead to a crash partway through the work, since
  # the claimant at least reached the point of producing something.

  # classify by duration + output presence — informative label, not a contract
  if duration_alive_sec is None:
    likely_cause = "dispatch_never_armed"
  elif duration_alive_sec < _STARTUP_CRASH_SEC and not partial_output:
    likely_cause = "crashed_at_startup"
  elif duration_alive_sec > _HUNG_JOB_SEC and not partial_output:
    likely_cause = "long_running_killed_or_hung"
  elif partial_output:
    likely_cause = "crashed_mid_processing"
  else:
    likely_cause = "unknown"

  # the forensic payload the runtime doctor triages this death from
  return {
    "marked_at": marked_at,
    # waiver: ISO-timestamp offset/suffix idiom, not a domain constant
    "marked_at_iso": datetime.fromtimestamp(marked_at, tz = UTC).isoformat().replace("+00:00", "Z"),
    "expert": expert,
    "job_id": job_id,
    "dedup_key": dedup_key,
    "original_pid": original_pid,
    "queued_at": queued_at,
    "claimed_at": claimed_at,
    "duration_queued_sec": duration_queued_sec,
    "duration_alive_sec": duration_alive_sec,
    "partial_output": partial_output,
    "likely_cause": likely_cause,
  }


def _finalize_orphaned_job(jdir: Path) -> None:
  """
  Finalize a claimed job whose claimant died after the expert produced its response.

  Applies when the job's response was already written before its claimant process
  disappeared, so downstream status still resolves from the response's outcome exactly
  as it would for a job that finished normally.

  Notes:
    - Touches the job directory's `DONE` marker and clears any `DEAD_CANDIDATE` marker.
    - Writes a diagnostic line to stderr describing the finalized job.

  Args:
    jdir: Path to the job directory holding an existing `response.json`.
  """
  (jdir / JobMarker.DEAD_CANDIDATE).unlink(missing_ok = True)
  (jdir / JobMarker.DONE).touch()
  sys.stderr.write(
    f"dead-scan: finalized orphaned job {jdir.parent.name}/{jdir.name} "
    "(claimant dead, response present)\n"
  )


def _detect_dead_jobs(repo: Path, *, grace_sec: float = 0.0, failures: list[str] | None = None) -> int:
  """
  Reconcile claimed jobs across the queue whose claimant process is no longer alive.

  Treats a claimed job that already has a response as finished rather than dead, and
  applies a grace window before declaring a truly unresponsive job dead so a slow
  response has time to land.

  Notes:
    - A bundle whose reconciliation raises — any exception, not only `OSError` — is named on stderr and appended
      to `failures`, and the scan goes on to the next bundle.
    - An expert queue folder that cannot be listed is named on stderr, appended to `failures`, and stepped over,
      so it never stops the scan of the other experts' queues.
    - A reconciled job barred from committing whose claimant died is judged the same way when it is finalized or
      buried: a found commit closes it as a logical error instead and the `forbidden_commit` halt is raised, an
      unverifiable one raises the halt and leaves the reconciliation as it was.
    - A barred orphan whose spawn is not proven gone is left for a later scan instead of being finalized or buried;
      the spawns of a barred orphan that already answered are stopped first.
    - Records a `job_dead` incident in the error ledger for each job newly marked dead.
    - Tears down (signals) any process still naming a job directory before marking that job dead, and may
      block for up to two kill grace windows per such process.

  Args:
    repo: Repository root containing the expert job tree.
    grace_sec: Minimum flagged time before a stuck job is declared dead; zero applies
      the dead verdict on first sighting.
    failures: List that receives one `<expert>/<job>: <error>` entry for each bundle that could not be
      reconciled and one `<expert>: <error>` entry for each queue folder that could not be listed; `None` when
      the caller does not collect them.

  Returns:
    The number of jobs newly marked dead in this scan.
  """

  base = Path(repo) / JOBS_BASE

  # guard: nothing to scan when the jobs root has not been created yet
  if not base.exists():
    return 0

  # walk every expert queue and reconcile each claimed job against its claimant
  marked = 0
  for edir in base.iterdir():
    # guard: skip stray files mixed in beside expert directories
    if not edir.is_dir():
      continue

    # an expert folder that cannot be listed is named for the caller and stepped over, so it
    # never keeps the scan from the other experts' queues
    try:
      bundles = list(edir.iterdir())
    except OSError as error:
      sys.stderr.write(f"dead-scan: cannot list {edir.name}: {type(error).__name__}: {error}\n")
      if failures is not None:
        failures.append(f"{edir.name}: {type(error).__name__}: {error}")
      continue
    for jdir in bundles:
      # one bundle that cannot be reconciled — its markers cannot be read or written, or its check
      # raises anything else — is named for the caller and stepped over, so it never keeps the
      # scan from the bundles after it nor the tick from the READY job it is about to serve
      try:
        marked += _reconcile_claimed_job(repo, edir.name, jdir, grace_sec)
      # waiver: the broad catch is the per-bundle isolation boundary — a narrower list would let
      # whichever fault it misses stop every tick before any job was served
      except Exception as error:  # pylint: disable=broad-exception-caught
        sys.stderr.write(f"dead-scan: cannot reconcile {edir.name}/{jdir.name}: {type(error).__name__}: {error}\n")
        if failures is not None:
          failures.append(f"{edir.name}/{jdir.name}: {type(error).__name__}: {error}")

  # the tick summary carries this count so a checkout burying jobs every tick is visible in
  # the daemon log without reading the job tree
  return marked


def _reconcile_claimed_job(repo: Path, expert: str, jdir: Path, grace_sec: float) -> int:
  """
  Reconcile one job bundle against its claimant, burying it when the claimant is gone for good.

  Notes:
    - A job barred from committing whose claimant died is judged the same way when it is finalized or buried: a
      found commit closes it as a logical error instead and the `forbidden_commit` halt is raised, an
      unverifiable one raises the halt and leaves the reconciliation as it was.
    - A barred orphan whose spawn is not proven gone is left for a later scan instead of being finalized or buried;
      the spawns of a barred orphan that already answered are stopped first.

  Args:
    repo: Repository root containing the expert job tree.
    expert: Name of the expert whose queue holds the bundle.
    jdir: The bundle directory to judge.
    grace_sec: Minimum flagged time before a stuck job is declared dead.

  Returns:
    1 when the bundle was newly marked dead, otherwise 0.

  Raises:
    OSError: When a marker of the bundle cannot be read or written.
  """
  # guard: only real bundles are queue entries
  if not is_job_bundle(jdir):
    return 0

  # a bundle carrying no marker at all is an abandoned dispatch rather than one still being
  # assembled: nothing will ever arm it, so it is buried once it outlives the same grace a
  # stuck claim gets, which puts it in front of the doctor and inside the collector's reach
  if _is_abandoned_bundle(jdir):
    if time.time() - jdir.stat().st_mtime >= grace_sec:
      return _mark_dead(repo, expert, jdir, _build_dead_json(jdir, expert, jdir.name, time.time()))
    return 0

  # guard: job never reached READY — still being assembled
  if not (jdir / JobMarker.READY).exists():
    return 0

  # guard: job already DONE — terminal state reached
  if (jdir / JobMarker.DONE).exists():
    return 0

  # guard: job already DEAD — skip to keep idempotent
  if (jdir / JobMarker.DEAD).exists():
    return 0

  # guard: job CANCELLED — the operator killed its executor deliberately; not a death
  if (jdir / JobMarker.CANCELLED).exists():
    return 0

  # guard: no PID file — job is queued, not claimed
  if not (jdir / JobMarker.PID).exists():
    return 0

  # an unreadable or garbled PID marker reads the same as a claimant that is gone
  try:
    alive = commit_guard.is_pid_alive(int((jdir / JobMarker.PID).read_text(encoding = "utf-8").strip()))
  except (OSError, ValueError):
    alive = False

  # Domain(runtime.job-execution):
  # # Grace window before a claimed job is declared dead
  # A job whose claimant process is gone is not immediately buried: the first sighting
  # opens a grace window instead of a verdict, since the process that recorded the claim
  # is the pump itself, and a pump killed by its own routine timeout can look dead while
  # the expert subprocess it spawned is still seconds away from writing its result. Only
  # a job still unclaimed once that window elapses is declared dead; a claimant seen alive
  # again before then cancels the window rather than shortening it on a later scan.

  # the candidate marker records when this job was first seen unclaimed
  candidate = jdir / JobMarker.DEAD_CANDIDATE

  # a claimant process still running leaves the job alone
  if alive:
    # a live claimant means the job was re-claimed after the earlier sighting;
    # a stale marker must not shortcut the grace window on a later scan.
    candidate.unlink(missing_ok = True)
    return 0

  # claimant died after the expert finished — finalize instead of marking dead, unless the run committed
  # although barred, which closes the job as failed
  if (jdir / JobFile.RESPONSE).exists():
    # guard: a barred job's spawn not yet proven gone could still commit, so the job waits for a later scan
    if not _settle_orphan(repo, jdir):
      return 0
    if _judge_orphan(repo, expert, jdir):
      _append_jobs_log(repo, expert, jdir.name, _classify_finished(jdir))
      return 0
    _finalize_orphaned_job(jdir)
    _append_jobs_log(repo, expert, jdir.name, _classify_finished(jdir))
    return 0

  # first sighting — open the grace window instead of marking dead
  if grace_sec > 0 and not candidate.exists():
    candidate.touch()
    return 0

  # an open grace window gives a surviving subprocess time to respond
  if grace_sec > 0 and time.time() - candidate.stat().st_mtime < grace_sec:
    return 0

  # the dead record is composed before the last-moment response check below
  blob = _build_dead_json(jdir, expert, jdir.name, time.time())

  # response landed during this scan — finalize instead of marking dead, unless the run committed although barred
  if (jdir / JobFile.RESPONSE).exists():
    # guard: a barred job's spawn not yet proven gone could still commit, so the job waits for a later scan
    if not _settle_orphan(repo, jdir):
      return 0
    if _judge_orphan(repo, expert, jdir):
      _append_jobs_log(repo, expert, jdir.name, _classify_finished(jdir))
      return 0
    _finalize_orphaned_job(jdir)
    _append_jobs_log(repo, expert, jdir.name, _classify_finished(jdir))
    return 0

  # Domain(runtime.job-execution):
  # # A dead job leaves no live session behind
  # An expert spawn runs in its own process session, apart from the pump that started it. A supervised
  # daemon restart or a routine-timeout kill of the pump therefore takes down only the pump's group,
  # while the spawn keeps running on its own, for days if nothing stops it. So a job declared dead after
  # its grace window first has every process still naming its job directory torn down, and only then is
  # it buried, as far as the host's process table can be read. A job barred from committing waits
  # until its spawn is proven gone, since a surviving spawn could still commit; any other job is
  # buried after the teardown attempt even when a spawn could not be found or stopped, as on a host
  # with no process table.

  # a spawn that outlived its pump (a daemon restart, a routine-timeout kill) sits in its
  # own session and would run on for days; it is torn down before the job is buried
  if _kill_orphaned_spawns(jdir):
    sys.stderr.write(f"dead-scan: killed orphaned spawn of {expert}/{jdir.name}\n")

  # guard: a barred job's spawn not yet proven gone could still commit after the burial, so the job waits
  if not _settle_orphan(repo, jdir):
    return 0

  # with no spawn left to commit, a barred job that committed is closed as failed rather than buried
  if _judge_orphan(repo, expert, jdir):
    _append_jobs_log(repo, expert, jdir.name, _classify_finished(jdir))
    return 0
  return _mark_dead(repo, expert, jdir, blob)


def _settle_orphan(repo: Path, jdir: Path) -> bool:
  """
  Stop every spawn still running for a barred job whose claimant is gone, and report whether none is left.

  Notes:
    - Signals the process groups of the job's spawns and may block for up to two kill grace windows per group.
    - Once no spawn is left, records that proof for the job, which ends any overlap with a later claim and lifts the
      job's hold on the daemon's publish.

  Args:
    repo: Repository root whose error ledger and job tree the proof is recorded in.
    jdir: The job's bundle directory.

  Returns:
    True when the job is not barred, or no spawn of it is left running; False when one survived or the process
    table could not be read.
  """
  # guard: only a barred job's late commit matters here
  if commit_guard.read_barred_identity(jdir) is None:
    return True

  # every spawn found is stopped, then the table is read again for proof
  for pid in commit_guard.find_spawn_pids(jdir) or []:
    _kill_pid_group(pid)

  # guard: a spawn survived, or the table cannot be read
  if commit_guard.find_spawn_pids(jdir) != []:
    return False

  # the proof is kept: it ends any overlap with a later claim and lifts the job's hold on the publish
  commit_guard.note_spawns_gone(repo, jdir)
  return True


def _judge_orphan(repo: Path, expert: str, jdir: Path) -> bool:
  """
  Hold a job whose claimant is gone to its bar on committing, as a finished run is held to it.

  Notes:
    - Records the commits the job made since it was last judged and raises the `forbidden_commit` halt over them.
    - When the job committed although barred, now or in an earlier sweep, closes it as a logical failure.
    - When its commits could not be listed and none was found before, raises the same halt and leaves the job as it
      stands.

  Args:
    repo: Repository root the job ran on.
    expert: Name of the expert whose queue holds the job.
    jdir: The job's bundle directory.

  Returns:
    True when the job committed although barred and was closed; False otherwise.
  """
  # what the job committed since it was last judged is recorded; an unverifiable listing only halts
  verdict = commit_guard.judge(repo, jdir)
  if verdict is not None:
    commit_guard.record(repo, expert, jdir, verdict, triggered_by = _PUMP_ROUTINE, on_halt = record_halt)

  # a job that never committed although barred, now or by an earlier sweep's finding, is reconciled as usual
  if not commit_guard.is_tainted(jdir):
    return False

  # a job that committed although barred is failed, never finalized as a success nor buried
  _write_error(jdir, JobErrorCategory.LOGICAL, _FORBIDDEN_COMMIT_FAILURE)
  return True



# ----------------------------------------------------------------------------------------
class _ExpertDirtyTreeError(Exception):
  """
  Signals that a successful expert run left uncommitted changes behind.

  Raised by `_process_one` after the post-Claude working-tree check finds dirty paths.
  Caught at the pump level to abort processing of any further READY jobs on the current
  tick, since the daemon-wide halt block has already been written.

  Attributes:
    expert: Name of the expert whose run was responsible.
    job_id: Identifier of the job that left the dirty state.
    dirty_paths: Repository-relative paths reported as dirty.
  """

  def __init__(self, expert: str, job_id: str, dirty_paths: list[str]):
    """
    Initialize the exception with the offending job's attribution.

    Args:
      expert: Name of the expert whose run left the dirty state.
      job_id: Identifier of the job that produced the failure.
      dirty_paths: Repository-relative paths reported as dirty.
    """
    # the exception's message names the expert and the job
    super().__init__(f"expert {expert!r} left dirty tree at job {job_id!r}")

    # the attribution the pump's halt record reads
    self.expert = expert
    self.job_id = job_id
    self.dirty_paths = dirty_paths



# ----------------------------------------------------------------------------------------
class _ExpertForbiddenCommitError(Exception):
  """
  Failure of a job barred from committing in the repository that moved the shared checkout's branch.

  Caught at the pump level to abort processing of any further READY jobs on the current tick, since the
  daemon-wide halt block has already been written.

  Attributes:
    expert: Name of the expert whose run was responsible.
    job_id: Identifier of the job that committed.
  """

  def __init__(self, expert: str, job_id: str):
    """
    Initialize the exception with the offending job's attribution.

    Args:
      expert: Name of the expert whose run committed.
      job_id: Identifier of the job that committed.
    """
    # the exception's message names the expert and the job
    super().__init__(f"expert {expert!r} committed in the repository at job {job_id!r}")

    # the attribution the pump's halt summary reads
    self.expert = expert
    self.job_id = job_id



# ----------------------------------------------------------------------------------------
class _PumpEnvironmentError(Exception):
  """
  Failure of the checkout itself rather than of the job being processed.

  Marks a fault such as an unusable daemon setting, a settings file that cannot be prepared, an expert binary
  missing from PATH, a work-tree check that fails after a finished run, or a job that cannot be closed. The pump
  raises it instead of closing the job, so the job is left as it stands.

  Attributes:
    unclosable: The jobs and queue folders the call could neither close nor reconcile, one entry each.
  """

  def __init__(self, message: str, *, unclosable: list[str] | None = None):
    """
    Initialize the exception with its message and the jobs the call could not close or reconcile.

    Args:
      message: The one-line account of the fault.
      unclosable: The call's entries, each `<expert>/<job>: <reason>` or `<expert>: <reason>`; none when omitted.
    """
    # the exception's message is the one-line account of the fault
    super().__init__(message)

    # the entries the call could not close, for the caller to report
    self.unclosable: list[str] = list(unclosable or [])



# ----------------------------------------------------------------------------------------

# Decision: kept, not retired, even though `Agent` being a mandatory `tools:` member on every
# canon-conformant agent (`Agent` is itself excluded from `_READ_ONLY_TOOLS` since a dispatched
# subagent can write) makes this function unreachable today — no agent can be classified
# read-only under that rule, so the dirty-tree carve-out below never fires. Retiring it would
# silently treat a future minimal agent (one that genuinely never writes and never dispatches)
# as write-capable instead; keeping it honest costs nothing and pays off the day the
# mandatory-`Agent` rule gains an exception.

def _agent_is_read_only(agent_path: Path) -> bool:
  """
  Return whether the agent declared at the given path can only read.

  An agent is considered read-only when its frontmatter `tools:` field is present
  and lists only members of the known read-only tool set. When the field is absent,
  empty, unparsable, or includes any tool outside that set, the agent is treated as
  write-capable so the post-Claude dirty-tree check applies to its runs.

  Args:
    agent_path: Path to the agent definition file.

  Returns:
    True only when every declared tool is in the known read-only set; False otherwise.
  """

  try:
    text = agent_path.read_text(encoding = "utf-8")
  except OSError:
    return False

  # guard: file does not start with a frontmatter fence
  if not text.startswith("---"):
    return False
  # waiver: inline numeric/default literal, not a domain constant
  end = text.find("\n---", 4)

  # guard: opening fence has no matching closing fence
  if end == -1:
    return False
  frontmatter = text[4:end]
  for raw in frontmatter.splitlines():
    line = raw.strip()

    # not the tools field — keep scanning
    # waiver: external Claude Code stream-json field name, not an internal key
    if not line.startswith("tools:"):
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    value = line[len("tools:"):].strip()

    # guard: tools field present but empty — treat as write-capable
    if not value:
      return False
    tools = { tool.strip() for tool in value.split(",") if tool.strip() }
    return bool(tools) and tools.issubset(_READ_ONLY_TOOLS)
  return False


def _is_job_halt_exempt(jdir: Path) -> bool:
  """
  Report whether one job bundle may still be served while the system is stuck.

  Args:
    jdir: Job-bundle directory whose `config.json` is read.

  Returns:
    True when the bundle's config carries `halt_exempt: true`; False otherwise, a missing or
    unreadable config included.
  """

  # Domain(runtime.daemon-loop):
  # # Halt exemption is stamped by the dispatcher, never inferred from a name
  # Which work may run through trouble is decided once, by whoever queues it: a dispatcher
  # that knows its job is the triage of the stuck condition marks the bundle as it writes it.
  # The pump reads that mark and nothing else — it never reconstructs the answer from the
  # expert's name or from the routine registry, because a resemblance between two registries'
  # naming is a coincidence, not a contract, and a job that loses the race to that coincidence
  # is a job that never runs.

  try:
    cfg = json.loads((jdir / JobFile.CONFIG).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return False
  return bool(cfg.get(JobConfigKey.HALT_EXEMPT, False))


def _is_system_stuck(repo: Path) -> bool:
  """
  Report whether the runtime is in the state that narrows the pump's queue.

  Mirrors the daemon loop's own `system_stuck` reading — a standing halt block, or a working
  tree already dirty or unreadable — so the pump and the loop never disagree about which condition holds.

  Args:
    repo: Repository root being checked.

  Returns:
    True when a halt stands, the working tree carries uncommitted changes, or the tree could not be read inside a
    git checkout.
  """
  return runtime_state.get_halted(repo) is not None or check_working_tree(repo) is not None


def _record_stray_copy_warning(repo: Path, expert_name: str, jdir: Path, detail: str) -> None:
  """
  Record a warning incident about a job's stray result copies, whether they were removed or their removal failed.

  Notes:
    - Writes a `job_error` incident with severity `warn` and cause `stray_result_copy` to the repository's error
      ledger, keyed on the job.

  Args:
    repo: Repository root whose error ledger receives the incident.
    expert_name: Name of the expert whose job left the copies.
    jdir: Path to the job directory the incident is keyed on.
    detail: One-line description of what the removal did.
  """
  error_ledger.record(repo, {
    IncidentKey.INCIDENT: f"job:{expert_name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.JOB_ERROR, IncidentKey.CAUSE: _STRAY_COPY_CAUSE,
    IncidentKey.SEVERITY: IncidentSeverity.WARN, IncidentKey.ACTOR: IncidentActor.PUMP,
    IncidentKey.EXPERT: expert_name, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.DETAIL: detail, IncidentKey.REFS: { "jdir": str(jdir) },
  })


def _record_unclosable(repo: Path, unclosable: list[str]) -> None:
  """
  Record in the error ledger every job or expert queue folder a call could neither close, reconcile nor list.

  Notes:
    - Writes one opened `job_error` incident with cause `job_unclosable` per entry, keyed on the job, or on the
      expert for a queue folder that could not be listed.

  Args:
    repo: Repository root whose error ledger receives the incidents.
    unclosable: The call's entries, each `<expert>/<job>: <reason>` or `<expert>: <reason>`.
  """
  # one incident per entry: the name before the first colon keys it, the rest is the reason
  for entry in unclosable:
    name, _colon, reason = entry.partition(": ")
    expert_name, _slash, job_id = name.partition("/")
    error_ledger.record(repo, {
      IncidentKey.INCIDENT: f"job:{name}", IncidentKey.PHASE: IncidentPhase.OPENED,
      IncidentKey.KIND: IncidentKind.JOB_ERROR, IncidentKey.CAUSE: _UNCLOSABLE_CAUSE,
      IncidentKey.ACTOR: IncidentActor.PUMP,
      IncidentKey.EXPERT: expert_name, IncidentKey.JOB_ID: job_id,
      IncidentKey.DETAIL: reason,
    })


def _update_halt_after_run(repo: Path, expert_name: str, jdir: Path) -> bool:
  """
  Settle the daemon's halt state after a successful expert run on the shared working tree.

  A tree left clean by the run leaves the queue running. Uncommitted dirt that remains once the job's own stray
  result copies are discarded halts the queue, with the job that ran last named as the trigger. A tree that could
  not be read inside a git checkout halts the queue the same way.

  Notes:
    - May delete the job's byte-identical stray result copies under the repository's top-level `result/`. When the
      tree could not be read, no copies are looked for or removed and no stray-copy warning is recorded; the halt
      alone names the condition.
    - May record a `job_error` incident of severity `warn` and cause `stray_result_copy` in the error ledger. A
      removal that failed always records it, with the failure named in the detail, whether the tree is then
      clean or still dirty (the halt is raised as well). A successful removal records it only when the removed
      copies were the only dirt.
    - Touches the job's DONE marker when dirt remains; the job's `response.json` stays as the expert wrote it,
      so the answer is collected once the halt lifts.
    - Writes the daemon-wide halt block with the dirty paths and opens the `halt:<repo>` incident when dirt
      remains; a halt block already standing is never overwritten.
    - A halt-exempt job raises no halt, since its dirt is the triage it was dispatched to perform.

  Args:
    repo: Repository root in which the expert ran.
    expert_name: Name of the expert whose run is being checked.
    jdir: Path to the job directory whose state is being finalised.

  Returns:
    True when a halt stands for the remaining dirt (the caller raises the halt exception), False when the tree
    was clean, the job is halt-exempt, or only stray result copies were dirty and are gone.
  """

  # Domain(runtime.job-execution):
  # # Shared-checkout dirty-tree halt
  # A job run against the shared working tree is judged more strictly than an isolated one:
  # any uncommitted dirt it leaves behind is now sitting on the exact tree every other queued
  # job will run against next, so it stops the whole queue rather than just failing the one
  # job that caused it. This is the reason the shared checkout gets a daemon-wide halt where
  # an isolated worktree only fails its own job — the blast radius of the same mistake is
  # different depending on whose tree it landed in. A tree that cannot be read after the job is
  # never taken for a clean one: it stops the queue exactly like leftover dirt. No copies are
  # looked for or removed then, since the tool that would tell which files are stray cannot be
  # asked, so the job is not blamed for a stray copy and the stop alone names the condition.
  # The same holds for the queue before a job starts — while the tree is not known clean, only
  # jobs marked as triage of the stuck condition are served.
  # One kind of dirt is not held against the queue: a copy of the job's own result files left
  # under the repository's top-level result directory, because the job wrote its result
  # relative to the clone root instead of its own job directory. Such a copy carries no work
  # of its own, and stopping every queued job for hours over a duplicate would be out of
  # proportion to the slip. Before the tree is judged, copies whose content is byte-identical
  # to the result of the job that just finished are removed; the identical content is the
  # proof that the copy is that job's and nobody else's. If that alone leaves the tree clean,
  # the queue is not stopped, and the slip is kept as a warning naming the expert and the
  # job. Any other dirt — another path, differing content, a tracked file — gets no such
  # leniency: the queue stops as above, and the halt describes the dirt that remains after
  # the copies are gone, not the copies.
  # The dirt is attributed to the job that ran last rather than proven to belong to it: the
  # tree is shared, so the job that finished most recently is the best available signal and
  # nothing more. That is exactly why the job's own answer is not touched — a job blamed by
  # proximity must not also lose the work it actually delivered. For the same reason the
  # blame only sticks once: a halt already standing was raised by whoever met the condition
  # first and keeps its own account of it, while the job dispatched to clear that very
  # condition is judged by whether it cleared it, never by the dirt it worked through.

  # a clean working tree leaves nothing to judge
  if (dirty := check_working_tree(repo)) is None:
    return False

  # guard: a halt-exempt job's dirt is the triage it was sent to do, never a contract breach
  if _is_job_halt_exempt(jdir):
    return False

  # the job's byte-identical result copies go first; a removal that fails midway may already have deleted some.
  # A tree that could not be read gives nothing to look for copies in: git cannot be asked, so none is
  # removed, the job is not blamed for one, and the halt alone names the condition
  removed: list[str] = []
  failure: str | None = None
  try:
    if dirty != [ UNREADABLE_TREE_LINE ]:
      removed = recover.delete_stray_result_copies(repo, jdir)
  except (OSError, subprocess.CalledProcessError) as error:
    failure = str(error)

  # once anything was removed or the removal failed, the tree is read afresh
  dirty = check_working_tree(repo) if removed or failure is not None else dirty

  # a failed removal is never dropped: it is kept as the warning whether or not the queue stops over what is left
  if failure is not None:
    _record_stray_copy_warning(repo, expert_name, jdir, f"stray-copy removal failed: {failure}")
  # removed copies that were the only dirt are kept as the warning in place of a halt
  elif removed and dirty is None:
    _record_stray_copy_warning(repo, expert_name, jdir, f"removed stray result copies: {', '.join(removed)}")

  # nothing is left on the tree, so the queue goes on without a halt
  if dirty is None:
    return False

  # the job's own answer is not the dirt's verdict: the response stays exactly as the expert
  # wrote it and the bundle closes with its original outcome, so the collector lands the work
  # once the halt lifts. The halt block below carries the attribution instead.
  (jdir / JobMarker.DONE).touch()

  # guard: a halt already stands — the queue stops either way, but the earlier block's
  # attribution is the one that named the condition first and is never clobbered
  if runtime_state.get_halted(repo) is not None:
    return True

  # nothing stands yet, so this job's run is the first account of the condition
  runtime_state.set_halted(repo, {
    HaltKey.HALTED_SINCE: time.time(),
    HaltKey.TRIGGERED_BY: _PUMP_ROUTINE,
    HaltKey.REASON: HaltReason.UNCOMMITTED_CHANGES,
    HaltKey.DIRTY_PATHS: dirty,
    IncidentKey.EXPERT: expert_name,
    IncidentKey.JOB_ID: jdir.name,
  })

  # the fresh halt is counted and opens the incident the recover skill reads
  record_halt(repo, reason = HaltReason.UNCOMMITTED_CHANGES, triggered_by = _PUMP_ROUTINE,
              detail = "; ".join(dirty), expert = expert_name, job_id = jdir.name)
  return True


def _resolve_base_branch(repo: Path) -> str | None:
  """
  Read the daemon's configured base branch, for `workspace: branch` restoration.

  Args:
    repo: Repository root whose settings file is consulted.

  Returns:
    The `daemon.git.base_branch` value, or None when the daemon's git sync is not configured.
  """
  daemon = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON)
  git_cfg = daemon.get(DaemonKey.GIT) or {}
  return git_cfg.get(GitConfigKey.BASE_BRANCH)


def _worktree_head(worktree: Path) -> str | None:
  """
  Return the commit the worktree's HEAD points at.

  Args:
    worktree: Path to the worktree directory.

  Returns:
    The full commit hash, or None when it cannot be resolved.
  """
  head = subprocess.run(
    # waiver: git CLI vocabulary, not a domain constant
    [ "git", "rev-parse", "HEAD" ], cwd = str(worktree), capture_output = True, text = True, check = False,
    encoding = "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "replace",
  )

  # guard: an unresolvable HEAD carries no comparable tip
  if head.returncode != 0:
    return None
  return head.stdout.strip()


def _record_claim_head(jdir: Path, work_root: Path) -> str | None:
  """
  Write the commit the work tree stands at into the job bundle as its claim head.

  Notes:
    - Writes one file into the bundle directory and nothing else; the work tree is only read.

  Args:
    jdir: Job bundle directory the marker is written into.
    work_root: Tree the job's buckets were copied from — its linked worktree when it has
      one, otherwise the repository checkout.

  Returns:
    The recorded commit hash, or None when the tree has no resolvable `HEAD` — then no marker
    is written, and a consumer reads the absence as "unknown", the conservative side.
  """

  # Domain(runtime.jobs):
  # # A job's claim head
  # A queued job reads nothing until the pump claims it; at that moment its inputs are copied
  # from the tree as it stands, so the commit the tree points at then is the exact boundary of
  # what the job saw. Anything reachable from that commit was in the job's inputs, anything
  # landing later was not. Recording that commit beside the claim lets whoever dispatched the
  # job answer "did it already see this change?" precisely, instead of guessing from clocks —
  # a commit's timestamp says when it was authored elsewhere, not when it reached this tree.

  # guard: no resolvable HEAD — leave no marker rather than a misleading one
  if (head := _worktree_head(work_root)) is None:
    return None

  # the marker beside PID: one hash, read back by whoever dispatched the job
  (jdir / JobArtifact.CLAIM_HEAD).write_text(f"{head}\n", encoding = "utf-8")
  return head


def _ensure_branch_origin(jdir: Path, *, branch_created: bool) -> bool:
  """
  Ensure, once per job, the record of whether an isolated job's branch existed before the job's first attempt.

  Notes:
    - At a job's first attempt it writes one record file into the bundle; later attempts only read it.

  Args:
    jdir: Job bundle directory holding the record.
    branch_created: Whether this attempt's worktree creation created the branch.

  Returns:
    True only when the record says the branch existed before the first attempt. A job with earlier attempts and no
    record, or with an unreadable attempt counter, yields False.

  Raises:
    OSError: When the record exists but cannot be read, or when the first attempt cannot write it into the bundle.
  """

  # Domain(runtime.job-execution):
  # # Whether a job continues earlier work is fixed at its first attempt
  # A job's branch can come into being during the job itself: a first run that fails and is
  # retried finds on its retry the branch its own failed attempt created. Whether the job
  # continues work that was already there is therefore decided once, at the job's first attempt,
  # and kept with the job; every later attempt reads that answer instead of looking at the branch
  # again. A job that already ran before such an answer was kept has none, and is judged as a
  # first run — the strict side of the commit obligation.

  record = jdir / JobArtifact.CLAIM_BRANCH_ORIGIN

  # a later attempt reads the answer its first attempt kept
  if record.exists():
    return record.read_text(encoding = "utf-8").strip() == _BranchOriginKind.EXISTED

  # no counter means no earlier attempt; a counter that cannot be read may hide one, so it counts as one
  try:
    earlier_attempts = int((jdir / JobArtifact.ATTEMPTS).read_text(encoding = "utf-8").strip())
  except FileNotFoundError:
    earlier_attempts = 0
  except (OSError, ValueError):
    earlier_attempts = 1

  # guard: a job that already ran before the answer was kept has none — judged as a first run
  if earlier_attempts > 0:
    return False

  # the first attempt keeps its answer for every later one
  origin = _BranchOriginKind.CREATED if branch_created else _BranchOriginKind.EXISTED
  record.write_text(f"{origin}\n", encoding = "utf-8")
  return origin == _BranchOriginKind.EXISTED


def _isolation_git_env(worktree: Path, base: Mapping[str, str]) -> dict[str, str]:
  """
  Return a copy of an environment under which git in an isolated job's worktree ignores the recorded byproducts.

  The byproducts are the provisioning links and the paths the bootstrap created.

  Args:
    worktree: Path to the job's worktree directory.
    base: Environment the copy starts from; it is never changed.

  Returns:
    The environment for the agent spawn and for the pump's own git calls in that worktree. When a private excludes
    file covering the worktree's provisioning links and bootstrap byproducts was written, it carries one more
    config slot naming that file as `core.excludesFile`, appended after every slot `base` already carries,
    `core.hooksPath` included; otherwise it equals `base`.
  """

  env = dict(base)
  exclude = WorktreeTaskManager.exclude_file(worktree)

  # guard: the worktree recorded no byproducts — git needs no override
  if exclude is None:
    return env

  # the slot joins after whatever the environment already carries
  slot = int(env.get(EnvVar.GIT_CONFIG_COUNT) or 0)
  env[f"{EnvVar.GIT_CONFIG_KEY}{slot}"] = EnvVar.GIT_EXCLUDES_FILE
  env[f"{EnvVar.GIT_CONFIG_VALUE}{slot}"] = str(exclude)
  env[EnvVar.GIT_CONFIG_COUNT] = str(slot + 1)
  return env


def _verify_isolated_job(worktree: Path, pre_spawn_tip: str | None, *, unmoved_ok: bool) -> str | None:
  """
  Check an isolated job's worktree after a clean spawn for a dirty tree, a failed check or an unmoved branch.

  A job failure, never a daemon halt — the primary checkout was untouched throughout, so the
  daemon-wide dirty-tree halt's rationale does not apply here. A `git status` that fails is reported as a
  failed check, distinct from a dirty tree. An untracked path recorded as a byproduct of the worktree's provisioning
  (a link from `daemon.git.worktree_links`) or of its bootstrap is not dirt, whether git already ignores it
  through the recorded excludes file or lists it anyway; any other untracked path and every tracked change is.
  The unmoved-branch check compares against the tip captured before the spawn, so a continuation round that
  produced nothing is caught even though the branch already carried earlier rounds' commits. A dirty tree is a
  failure whatever the caller allows.

  Args:
    worktree: Path to the job's worktree directory.
    pre_spawn_tip: The branch tip captured before the spawn, or None when it was unresolvable.
    unmoved_ok: When true, a clean tree whose branch did not move is not a failure.

  Returns:
    None when the worktree is clean and the branch moved (or did not move while `unmoved_ok` is true), else a
    one-line failure text that names a failed work-tree check, a dirty tree or a branch that did not move.

  Raises:
    OSError: When git cannot be run in the worktree, for example a `FileNotFoundError` for a missing `git`
      executable or worktree directory.
    ValueError: When the process environment's `GIT_CONFIG_COUNT` is not an integer while the worktree has
      recorded byproducts.
  """

  # Domain(runtime.job-execution):
  # # Isolated job's commit obligation
  # A job running in its own worktree carries the whole responsibility for its own durable
  # output: nothing it leaves uncommitted survives past the job, and the worktree is removed
  # once the run ends regardless of outcome. A run that leaves the tree dirty broke that
  # obligation outright; a run that leaves the tree clean but never advanced the branch beyond
  # where it started is equally a failure, since it produced nothing durable either way — a
  # continuation is judged the same way, against the tip the branch already carried before
  # this run, not against where it started overall. One exception is granted by whoever queued
  # the run, never assumed: a continuation whose durable output already sits on the branch, and
  # whose only remaining work may produce nothing to commit (re-running a check that did not run),
  # may finish with the branch unmoved, provided it reports its work as done. A first run on a
  # fresh branch keeps its obligation even when so marked, a run reporting failure or deferred
  # work still fails, and a dirty tree breaks the obligation as before. A run whose agent lists
  # exclusively known read-only tools is not held to the obligation at all, since it cannot commit;
  # an absent, empty or unparsable tools list, or any write-capable tool, keeps the obligation.

  status = subprocess.run(
    # waiver: git CLI vocabulary, not a domain constant
    [ "git", "status", "--porcelain", "-z", "--untracked-files=normal" ],
    cwd = str(worktree), capture_output = True, check = False, env = _isolation_git_env(worktree, os.environ),
  )

  # guard: a status that exits non-zero listed nothing — the tree's state is unknown, never clean
  if status.returncode != 0:
    return _TREE_CHECK_FAILED

  # the listing is captured as bytes and decoded here, so no byte of a name is rewritten on the way
  entries = iter(status.stdout.decode(
    "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "surrogateescape",
  ).split("\0"))
  byproducts = WorktreeTaskManager.read_recorded_paths(worktree)

  # every entry counts as dirt except an untracked path the worktree recorded as a byproduct — a provisioning
  # link or what the bootstrap created — a second line of defence behind the excludes file, for a byproduct git
  # still lists
  kept: list[str] = []
  for entry in entries:
    # guard: the empty piece after the last separator
    if not entry:
      continue
    # a rename or copy entry is followed by its origin path as a separate record — shown together
    # waiver: git porcelain status letters and column width, not domain constants
    if "R" in entry[:2] or "C" in entry[:2]:
      kept.append(f"{entry} <- {next(entries, '')}")
    # waiver: git porcelain prefix and prefix width, not domain constants
    elif entry[:3] != "?? " or entry[3:] not in byproducts:
      kept.append(entry)
  dirty = "\n".join(kept)

  # uncommitted changes left in the worktree break the commit obligation; the listing is quoted with every
  # undecodable path byte replaced, so the message is storable as UTF-8
  if dirty:
    listing = dirty[:300].encode(
      encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "surrogateescape",
    ).decode(
      encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    )
    return f"{_DIRTY_TREE_FAILURE}: {listing}"

  # a clean tree with the tip exactly where the spawn found it means nothing durable landed, unless the
  # dispatcher allowed a commitless finish for this run and the run reported success
  if not unmoved_ok and pre_spawn_tip is not None and _worktree_head(worktree) == pre_spawn_tip:
    return _NO_NEW_COMMITS_FAILURE
  return None


def _format_isolation_prompt(branch: str, *, is_fresh: bool, commitless_ok: bool) -> str:
  """
  Compose the commit-obligation paragraph for a spawn running in an isolated worktree.

  Args:
    branch: The job's branch, named so the agent knows where its work lands.
    is_fresh: Whether this attempt created the branch. When false, the branch already exists at this attempt,
      whatever its origin, and the paragraph tells the expert to build on its commits and never rewrite them.
    commitless_ok: Whether a round needing no file change may finish without a commit. It adds to the
      continuation paragraph only the note that such a round commits nothing and still reports success, never
      making an empty commit to move the branch; it has no effect when `is_fresh` is true.

  Returns:
    The paragraph to append to the user prompt.
  """
  if is_fresh:
    return (
      f"You are working in an isolated git worktree on branch `{branch}`. Commit ALL your work "
      "to this branch before writing response.json — the worktree is removed after the job, and "
      "only committed work survives. An uncommitted or empty result fails the job."
    )

  # a continuation builds on the branch's earlier rounds; a dispatcher-allowed commitless finish is said outright
  continuation = (
    f"You are working in an isolated git worktree on branch `{branch}`, which already carries "
    "commits from an earlier round of this job — this is a continuation. Build on them, never "
    "reset or rewrite them. Commit ALL new work before writing response.json — the worktree is "
    "removed after the job, and only committed work survives."
  )
  return f"{continuation} {_COMMITLESS_CONTINUATION_NOTE}" if commitless_ok else continuation


def pump(repo: Path) -> dict:
  """
  Run one pump tick over the expert-job queue.

  Each tick marks jobs whose claimant process has died, then handles at most one READY job: it
  processes the oldest READY job across all expert directories, or defers without spawning anything
  when a job is waiting and the host's rate-limit guard has flagged the account. The single-spawn
  ceiling matters because the daemon's per-routine timeout is the only bound on a Claude subprocess.

  Guarantees:
    - Spawns at most one Claude expert process per call, regardless of how many jobs are READY.
    - No spawned expert process loads a TCC-gated `permissions.additionalDirectories` entry from the checkout's
      `.claude/settings.local.json`.
    - A claimed job that already has `response.json` is treated as finished, never marked dead, regardless of
      its claimant's liveness or how long it has sat unclaimed.
    - A run is exempt from the post-run dirty-tree check only when its agent's `tools:` field lists exclusively
      known read-only tools; an absent, empty or unparsable field, or any write-capable tool, keeps the check.
    - An isolated job whose run leaves its worktree clean and its branch tip where the spawn found it is closed as
      a logical failure, unless its branch existed before the job's first attempt, its `config.json` carries
      `allow_no_commit: true`, and its `response.json` carries an outcome none of whose tokens is `error` or
      `deferred`; such a job reaches `DONE` with its response intact. A first run on a freshly created branch (its
      retries included), a job that ran before its first attempt's answer was kept, a dirty
      worktree whatever its config says, and a config without the key are all held to the commit obligation.
    - A job's `source/` and `context/` buckets only ever receive entries from inside the work tree; an entry
      resolving outside it is refused and the job fails logically.
    - A directory entry of those buckets lands under `<parent-directory-name>-<directory-name>`, never under its
      bare name; a file entry lands under its basename.
    - For a provider-bound job, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, the variable named by
      `daemon.token_env`, and the daemon's own token digest marker are all absent from the spawn environment.
    - An envelope-violating response within the retry limit leaves the job re-queueable: `response.json` and the
      claim's `PID` marker are removed and `READY` is untouched. Past the limit the job is closed for good.
    - A transiently-errored job with retry budget left is released (its `PID` marker unlinked, no `DONE`), so it
      is queued again and dead-claimant reconciliation cannot finalize it while a retry is due.
    - An exception raised while one job is processed does not escape: the job is closed as a logical failure whose
      message names the exception, and the call returns its normal summary.
    - A fault of the checkout or the host — an unusable daemon setting, a settings file that cannot be prepared,
      an expert binary missing from PATH — is raised as the pump's environment error, and the job is left as it
      stands: queued and unclaimed. A work-tree check that could not be made after a finished run, a `git status`
      that exits non-zero included, is raised the same way, and the job's finished `response.json` is never
      overwritten.
    - A job the call could neither close nor reconcile — a closing record that cannot be written into its own
      bundle, or a bundle the dead scan cannot reconcile — and an expert queue folder that cannot be listed never
      stop the READY job behind them from being served; the call then raises the pump's environment error naming
      every such job or folder. A job that fails to close after it was claimed ends the call instead.
    - When a fault of the checkout or the host is re-raised while the call holds jobs it could neither close nor
      reconcile, those jobs are named on the raised error, in its message and on its `unclosable` attribute.
    - When the subscription window is closed and the call would defer, it raises for those jobs and folders at once
      and spawns nothing.
    - On the three `halted` returns (a dirty-tree halt, a rate-limit halt, a forbidden-commit halt, each raised
      during the run) the halt summary is returned so the daemon can act on the halt; a forbidden-commit check
      that could not be made during the run returns it too, the summary then carrying
      `halt_reason: forbidden_commit`. Each such job or folder is named on stderr and recorded in the error
      ledger as an opened `job_error` incident with cause `job_unclosable`, keyed on the job.

  Notes:
    - When a tick buries a dead job whose spawn outlived its pump, it signals process groups outside this
      process and blocks for up to two kill grace windows per such process.
    - Rewrites the operator's gitignored `.claude/settings.local.json` in the checkout when that file
      carries a TCC-gated `permissions.additionalDirectories` entry.

  Args:
    repo: Repository root containing the expert job tree.

  Returns:
    A summary dict with counts of experts seen, jobs processed, and jobs newly
    marked dead. On a deferred tick, adds `deferred` (True) and `resets_at` (the epoch-seconds
    timestamp when the rate limit reopens) instead of processing a job. When a halt fires
    instead, adds the offending expert and job_id. While a halt stands or the tree is dirty,
    only bundles whose `config.json` carries `halt_exempt` are eligible; the rest are left
    READY for the halt to lift.

  Raises:
    _PumpEnvironmentError: When the daemon stream settings are unusable, the checkout's settings files, including
      `.claude/settings.local.json`, cannot be prepared, the expert binary is missing from PATH, or the work-tree
      check after a finished run could not be made; the job is left as it stands and its finished response is
      left as it is. When such a fault ends the call while jobs could not be closed or reconciled, the error
      names them as well. Also, when a job's closing record could not
      be written into its own bundle, the dead scan could not reconcile a job's bundle, or an expert queue folder
      could not be listed: after the READY job has been served, or at once when the subscription window is closed;
      the message names each such job or folder. A `halted` return raises nothing for them; they are recorded in
      the error ledger instead.
  """

  # Contract:
  # A single call MUST spawn at most one Claude expert process, even when several jobs are
  # READY across the queue; the oldest READY job is picked and processed per call, and a younger
  # one gets the turn only when every older one failed before its claim and could not be closed.

  # Contract:
  # An expert process that a call spawns MUST NOT load a TCC-gated `permissions.additionalDirectories`
  # entry from the checkout's `.claude/settings.local.json`.

  # Contract:
  # A claimed job that already has `response.json` MUST be treated as finished and NEVER marked dead,
  # regardless of its claimant's liveness or how long it has sat unclaimed.

  # Contract:
  # An expert run MUST be exempt from the post-run dirty-tree check only when its agent's `tools:` field
  # lists exclusively known read-only tools; an absent, empty or unparsable field, or any write-capable
  # tool, MUST leave the check applied.

  # Contract:
  # An isolated job whose run leaves its worktree clean and its branch tip where the spawn found it MUST
  # be closed as a logical failure, unless its branch existed before the job's first attempt, its `config.json`
  # carries `allow_no_commit: true`, and its `response.json` carries an outcome none of whose tokens is `error`
  # or `deferred`; such a job reaches `DONE` with its response intact. A first run on a freshly created branch
  # (its retries included), a job that ran before its first attempt's answer was kept, a dirty worktree whatever
  # the config says, and a config without the key MUST all be held to the commit obligation.

  # Contract:
  # A job's `source/` and `context/` buckets MUST only ever receive entries from inside the work tree;
  # an entry resolving outside it is refused, the job fails logically, and nothing is copied for it.

  # Contract:
  # A directory entry of a job's `source/` or `context/` bucket MUST land under
  # `<parent-directory-name>-<directory-name>`, never under its bare name; a file entry lands under
  # its basename.

  # Contract:
  # For a provider-bound job, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, the variable named by
  # `daemon.token_env`, and the daemon's own token digest marker MUST all be absent from the spawn
  # environment.

  # Contract:
  # A response that violates the envelope, within the retry limit, MUST leave the job re-queueable:
  # `response.json` and the claim's `PID` marker are removed and `READY` is untouched, so the next
  # tick re-picks it as though never claimed. Past the retry limit the job MUST be closed for good,
  # like any other logical failure.

  # Contract:
  # A transiently-errored job with transient retry budget left MUST be released: its `PID` marker is
  # unlinked and no `DONE` is written, so it is queued again, indistinguishable from a never-claimed
  # READY job, and dead-claimant reconciliation MUST NOT finalize it while a retry is due.

  # Contract:
  # An exception raised while one job is being processed MUST NOT escape the call. The job is
  # closed as a logical failure whose message names the exception, and the call returns its
  # normal summary, so the next call serves the next READY job instead of dying on the same one.
  # The one exception is a fault of the checkout or the host, which is raised instead.

  # Contract:
  # A fault of the checkout or the host — an unusable daemon setting, a settings file that cannot
  # be prepared, an expert binary missing from PATH — MUST be raised as the pump's environment error,
  # and the job is left as it stands: queued and unclaimed. A work-tree check that could not be made
  # after a finished run, a `git status` that exits non-zero included, is raised the same way, and the
  # job's finished `response.json` is NEVER overwritten: the job keeps its own response.

  # Contract:
  # A job the call could neither close nor reconcile — a closing record that cannot be written into
  # its own bundle, or a bundle the dead scan cannot reconcile — and an expert queue folder that
  # cannot be listed MUST NOT stop the READY job behind them from being served; the call then raises
  # the pump's environment error naming every such job or folder. A job that fails to close after it
  # was claimed ends the call instead, so the single-spawn ceiling holds.

  # Contract:
  # When a fault of the checkout or the host is re-raised while the call holds jobs it could neither
  # close nor reconcile, those jobs MUST be named on the raised error, in its message and on its
  # `unclosable` attribute, so a fault that ends the call never hides them. With no such job the
  # fault is raised as it is.

  # Contract:
  # When the subscription window is closed and the call would defer, it raises for those jobs and
  # folders at once and spawns nothing. The three `halted` returns, a dirty-tree halt, a rate-limit
  # halt and a forbidden-commit halt raised during the run, are the exception: the halt summary is
  # returned so the daemon can act on the halt, a forbidden-commit check that could not be made during
  # the run returns it too, the summary then carrying `halt_reason: forbidden_commit`, and each such
  # job or folder is named on stderr and recorded in the error ledger as an opened `job_error`
  # incident with cause `job_unclosable`, keyed on the job.

  repo = Path(repo)
  daemon = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON)

  # the jobs this call could neither process, close nor reconcile; each is stepped over so it
  # never blocks the jobs queued behind it, and the call raises for them once a job was served
  unclosable: list[str] = []
  detected_dead = _detect_dead_jobs(repo, grace_sec = _DEAD_GRACE_SEC, failures = unclosable)

  # the queue root only appears once something has been dispatched
  jobs_root = repo / JOBS_BASE

  # guard: no jobs tree on disk yet — return early summary
  if not jobs_root.exists():
    return { "experts": 0, "processed": 0, "detected_dead": detected_dead }

  # per-tick counters the daemon folds into its metrics
  processed = expert_count = 0

  # Decision: FIFO by READY-marker mtime across all experts, not per-directory order — alphabetical
  # order let experts that enqueue continuously starve a later-sorted expert's jobs indefinitely

  # collect every READY job across all expert directories, then the oldest is picked
  ready_candidates: list[tuple[float, str, Path]] = []
  for edir in sorted(jobs_root.iterdir()):
    # guard: skip stray files mixed in beside expert directories
    if not edir.is_dir():
      continue
    expert_count += 1

    # an expert folder that cannot be listed queues nothing this call; the dead scan above has
    # already named it, so it is stepped over here without a second report
    try:
      bundles = sorted(edir.iterdir())
    except OSError:
      continue
    for jdir in bundles:
      # a bundle whose markers cannot be read queues nothing this call; the dead scan above has
      # already named it, so it is stepped over here without a second report
      try:
        # guard: only real bundles are queue entries
        if not is_job_bundle(jdir):
          continue
        ready_marker = jdir / JobMarker.READY
        ready = (
          ready_marker.exists()
          and not (jdir / JobMarker.DONE).exists()
          and not (jdir / JobMarker.DEAD).exists()
          and not (jdir / JobMarker.CANCELLED).exists()
        )

        # only actually-ready jobs join the FIFO queue
        if not ready:
          continue
        ready_candidates.append((ready_marker.stat().st_mtime, edir.name, jdir))
      except OSError:
        continue

  # while the system is stuck the queue narrows to the bundles their dispatcher marked
  # halt-exempt — the triage job still reaches its spawn, every other job waits for the halt
  if ready_candidates and _is_system_stuck(repo):
    ready_candidates = [ candidate for candidate in ready_candidates if _is_job_halt_exempt(candidate[2]) ]

  # process the oldest ready job, if any surfaced above
  if ready_candidates:

    # Decision: the rate-limit check lives here, in the pump, not inside `_process_one` — down
    # there the PID marker is already written and `attempts` already incremented, so a deferred
    # job would be marked DEAD two scans later and would fatten `jobs.jsonl` with an error line
    # every polling interval. Standing before the spawn also covers a second checkout on this
    # host, the window between a halt clearing and the next spawn, and a halt an operator lifted
    # early via `/lazy-runtime.recover`.

    # resolve the guard's effective triggers for this repository
    guard = rate_limit_flag.resolve_config(daemon)

    # one listing answers both questions — a record expiring between two reads would otherwise
    # report a deferral with no reopening time attached
    raised = rate_limit_flag.read_live_records() if guard[RateLimitGuardKey.ENABLED] else []

    # guard: the window is closed and the dead scan left a job unreconciled — a deferral can last
    # for hours, so the call fails for that job now instead of deferring over it in silence;
    # nothing is spawned either way
    if raised and unclosable:
      raise _PumpEnvironmentError(
        f"could not close or reconcile job(s): {'; '.join(unclosable)}", unclosable = unclosable,
      )

    # guard: the subscription window is closed — postpone rather than burn the call
    if raised:
      # waiver: pump-summary subkeys, mirroring the sibling `halted` summary below
      return {
        "experts": expert_count, "processed": 0,
        "detected_dead": detected_dead, "deferred": True,
        RateLimitRecordKey.RESETS_AT: max(float(record[RateLimitRecordKey.RESETS_AT]) for record in raised),
      }

    # plain FIFO across the whole queue — oldest READY marker wins
    ready_candidates.sort(key = lambda candidate: candidate[0])

    # the job that got this call's one turn, once there is one
    served: tuple[str, Path] | None = None
    for _mtime, name, jdir in ready_candidates:
      started = time.monotonic()
      try:
        _process_one(repo, name, jdir)
      except (_ExpertDirtyTreeError, _ExpertForbiddenCommitError) as error:
        processed = 1
        _log_job_attempt(repo, name, jdir, started)

        # the halt summary must go back to the daemon, so the call cannot raise for the jobs it
        # could not close — and the halt hides them from later calls — so the ledger takes them
        _record_unclosable(repo, unclosable)
        return {
          "experts": expert_count, "processed": processed,
          "detected_dead": detected_dead, "halted": True,
          "halt_expert": error.expert, "halt_job_id": error.job_id,
        }
      except _PumpEnvironmentError as error:
        # the checkout's own fault would fail every job the same way — the job stays queued, and with
        # no other job lost the fault goes up as it is
        if not unclosable:
          raise

        # the fault ends the call before its closing raise, so it carries the jobs the call could neither
        # close nor reconcile itself: each is named in the message and listed on the error
        raise _PumpEnvironmentError(
          f"{error}; could not close or reconcile job(s): {'; '.join(unclosable)}", unclosable = unclosable,
        ) from error
      # waiver: the broad catch is the isolation boundary itself — whatever one bundle makes the
      # pump raise, the bundle is closed and the queue behind it keeps moving
      except Exception as error:  # pylint: disable=broad-exception-caught
        # the full traceback goes to the routine journal; the job keeps the one-line cause
        traceback.print_exc(file = sys.stderr)
        try:
          _write_error(
            jdir, JobErrorCategory.LOGICAL,
            f"pump could not process this job: {type(error).__name__}: {error}",
          )
        except OSError as close_error:
          # the closing record cannot be written into this bundle — the job cannot be closed;
          # it is named on stderr at once, so no later exit of this call can lose it
          sys.stderr.write(f"pump: cannot close {name}/{jdir.name}: {close_error}\n")
          unclosable.append(f"{name}/{jdir.name}: {close_error}")

          # guard: the job was claimed, so its expert may already have been spawned — handing
          # the turn on would risk a second spawn in one call, so the call stops here
          if (jdir / JobMarker.PID).exists():
            break

          # a job that failed before it was claimed spawned nothing — the next READY job gets
          # this call's turn
          continue

      # this job had the call's one turn, whether it ran or was closed
      processed = 1
      _log_job_attempt(repo, name, jdir, started)
      served = ( name, jdir )
      break

    # a forbidden-commit check that could not be made after the run halted the daemon without ending the job's
    # own classification; the halt summary goes back like the dirty-tree one
    if served is not None and commit_guard.is_recorded(repo, served[1].name):
      _record_unclosable(repo, unclosable)
      # waiver: pump-summary subkeys, mirroring the sibling dirty-tree halt summary above
      return {
        "experts": expert_count, "processed": processed,
        "detected_dead": detected_dead, "halted": True, "halt_reason": HaltReason.FORBIDDEN_COMMIT,
        "halt_expert": served[0], "halt_job_id": served[1].name,
      }

    # the pre-spawn check found the flag clear, so a flag up now went up during this run — by this
    # run's own frames or a concurrent writer on the host; either way the window is closed. Halt
    # the daemon until it reopens. The current job was never interrupted for it.
    if served is not None and guard[RateLimitGuardKey.ENABLED] and _halt_on_rate_limit(repo, *served):
      # same as the dirty-tree halt above: the summary goes back, the ledger takes the lost jobs
      _record_unclosable(repo, unclosable)
      # waiver: pump-summary subkeys, mirroring the sibling dirty-tree halt summary above
      return {
        "experts": expert_count, "processed": processed,
        "detected_dead": detected_dead, "halted": True, "halt_reason": HaltReason.RATE_LIMIT,
        "halt_expert": served[0], "halt_job_id": served[1].name,
      }

  # guard: some job could be neither processed, closed nor reconciled — the call fails for it,
  # loudly, now that the queue behind it has had its turn
  if unclosable:
    raise _PumpEnvironmentError(
      f"could not close or reconcile job(s): {'; '.join(unclosable)}", unclosable = unclosable,
    )
  return { "experts": expert_count, "processed": processed, "detected_dead": detected_dead }


def _halt_on_rate_limit(repo: Path, expert_name: str, jdir: Path) -> bool:
  """
  Raise the rate-limit daemon halt when the host-local flag is up after a job's run.

  A halt already standing — for example an unresolved dirty-tree halt — is never overwritten:
  it carries its own reason the operator still has to see. The halt is counted like every other
  daemon halt and opens the daemon-halt incident, naming the expert and job, so `/error-list`
  reflects the stop, mirroring the automatic clear on the other side.

  Args:
    repo: Repository root whose daemon is halted.
    expert_name: Name of the expert whose run raised the flag, recorded on the incident.
    jdir: Path to the job directory of that run.

  Returns:
    True when the halt was raised by this call; False when the flag is down or a halt stood.
  """
  raised = rate_limit_flag.read_live_records()

  # guard: the flag is not up — nothing this run has to act on
  if not raised:
    return False

  # guard: a standing halt keeps its own reason; the flag alone still defers every next tick
  if runtime_state.get_halted(repo) is not None:
    return False

  # the halt lasts until the latest window among the raised records reopens
  resets = max(float(record[RateLimitRecordKey.RESETS_AT]) for record in raised)
  runtime_state.set_halted(repo, {
    HaltKey.HALTED_SINCE: time.time(),
    HaltKey.TRIGGERED_BY: _PUMP_ROUTINE,
    HaltKey.REASON: HaltReason.RATE_LIMIT,
    HaltKey.RESETS_AT: resets,
    IncidentKey.EXPERT: expert_name,
    IncidentKey.JOB_ID: jdir.name,
  })

  # human-facing detail line — the machine-readable epoch stays on the halt block; a reset no
  # date can hold is shown as the raw number rather than taking the halt down with it
  try:
    reopens = datetime.fromtimestamp(resets, tz = UTC).strftime("%Y-%m-%d %H:%M UTC")
  except (OverflowError, ValueError, OSError):
    reopens = str(resets)

  # the loud line: the routine's stderr reaches the daemon journal's stderr_tail and the
  # operator's terminal — a multi-hour stop must never be discoverable only via state.json
  sys.stderr.write(
      f"DAEMON HALTED (rate limit): expert {expert_name} job {jdir.name} — "
      f"no routine runs until {reopens}; /lazy-runtime.recover lifts it early\n")
  record_halt(repo, reason = HaltReason.RATE_LIMIT, triggered_by = _PUMP_ROUTINE,
              detail = f"rate-limit window closed until {reopens}", expert = expert_name, job_id = jdir.name)
  return True


def _record_rate_limit(repo: Path, expert_name: str, stdout: str) -> int:
  """
  Read one spawn's stdout for rate-limit frames and raise the host-local flag when one trips.

  Every trigger is evaluated against this repository's guard configuration, so an operator who
  disabled a trigger here never writes a record for it. Recording is best-effort — a failure to
  write never propagates into the job's own outcome.

  Args:
    repo: Repository root whose guard configuration governs the triggers.
    expert_name: Name of the expert whose spawn produced the buffer, stored on any record written.
    stdout: Raw stdout produced by the spawn.

  Returns:
    The number of rate-limit frames the buffer carried, regardless of whether any tripped.
  """
  frames = rate_limit_flag.parse_frames(stdout or "")

  # guard: the run carried no rate-limit signal to act on
  if not frames:
    return 0
  cfg = rate_limit_flag.resolve_config(load_section(repo / SettingsFile.REL, SettingsKey.DAEMON))

  # guard: the guard is switched off in this repository — frames are counted, never acted on
  if not cfg[RateLimitGuardKey.ENABLED]:
    return len(frames)
  for info in frames:
    trigger = rate_limit_flag.evaluate_trigger(info, cfg)

    # guard: this frame reports a healthy window
    if trigger is None:
      continue
    try:
      rate_limit_flag.record(info, trigger, writer = f"expert-pump:{expert_name}")
    except OSError as error:
      sys.stderr.write(f"rate-limit guard: cannot write flag: {error}\n")
  return len(frames)


def _read_rejection(jdir: Path) -> str | None:
  """
  Render the correction paragraph for a bundle whose previous attempt was rejected.

  Args:
    jdir: Path to the job directory that may carry a rejection record.

  Returns:
    The paragraph to append to the prompt, or None when no attempt of this
    bundle has been rejected or the record is unreadable.
  """
  record_path = jdir / JobArtifact.ERROR_JSON

  # guard: the common case is a bundle nobody has rejected yet
  if not record_path.exists():
    return None
  try:
    record = json.loads(record_path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return None
  # waiver: per-attempt rejection record field, written by _reject_response
  attempt = record.get("attempt", 0)
  return (
    f"{_CORRECTION_MARKER} — attempt {attempt} of this job was rejected and its response discarded. "
    f"Reason: {record.get(JobResponseKey.MESSAGE, '')} "
    "Redo the work and write a response that satisfies the contract."
  )


def _drop_earlier_copies(jdir: Path) -> str | None:
  """
  Remove from a job's buckets what an earlier claim of the same bundle copied into them.

  Args:
    jdir: Job bundle directory carrying the record of the earlier claim's copies.

  Returns:
    None when the earlier copies are gone or there were none, or a one-line message when the record exists but
    cannot be read or parsed, in which case nothing is removed.
  """
  try:
    record = json.loads((jdir / JobArtifact.CLAIM_COPIES).read_text(encoding = "utf-8"))
  except FileNotFoundError:
    # no record: no earlier claim copied anything
    return None
  except (OSError, ValueError) as error:
    # a record that is there but cannot be read or parsed leaves the earlier copies unknown, which is never
    # read as "no earlier claim"; `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
    return (
      f"{JobArtifact.CLAIM_COPIES} cannot be read, so what the earlier claim copied is unknown: "
      f"{type(error).__name__}: {error}"
    )

  # guard: a record of any other shape names no copies
  if not isinstance(record, dict):
    return None
  for bucket in ( JobIODir.SOURCE, JobIODir.CONTEXT ):
    names = record.get(bucket)

    # guard: this bucket received no copies at the earlier claim
    if not isinstance(names, list):
      continue
    for name in names:
      # guard: a copy sits directly in its bucket under a plain name — anything else in the record would
      # reach outside the bucket, and the record lies in a directory the expert can write to
      if not isinstance(name, str) or not name or name == os.pardir or Path(name).name != name:
        continue
      copy = jdir / bucket / name

      # a symlink is unlinked, never followed; a directory copy goes as a tree
      if copy.is_symlink() or copy.is_file():
        copy.unlink()
      elif copy.is_dir():
        shutil.rmtree(copy)

  # every recorded copy is gone
  return None


def _write_claim_copies(jdir: Path, copied: dict[str, set[str]]) -> None:
  """
  Record what a claim copied into a job's buckets, for the next claim of the same bundle to remove.

  The record is written atomically, so a reader never sees a partial record; a write that fails leaves the
  previous record as it was.

  Args:
    jdir: Job bundle directory the record is written into.
    copied: Bucket name mapped to the names of the entries this claim copied into that bucket.
  """
  record_path = jdir / JobArtifact.CLAIM_COPIES

  # guard: this claim copied nothing, and the earlier claim's copies are already gone — no record to keep
  if not any(copied.values()):
    record_path.unlink(missing_ok = True)
    return

  # the record sits beside the buckets, not inside one, so the expert never reads it as an input; it is
  # written whole into a temp file in the same directory and renamed over the record, so a reader never
  # sees a truncated record and a write that fails leaves the previous record as it was
  record_tmp = jdir / _CLAIM_COPIES_TMP
  try:
    record_tmp.write_text(
      json.dumps({ bucket: sorted(names) for bucket, names in copied.items() }, indent = 2), encoding = "utf-8",
    )
    os.replace(record_tmp, record_path)
  except OSError:
    # the half-written temp file is dropped; the failure itself goes up to the claim
    record_tmp.unlink(missing_ok = True)
    raise


def _materialize_io(jdir: Path, cfg: dict, work_root: Path) -> str | None:
  """
  Copy a claimed job's declared source and context paths into its bundle directory.

  A directory entry is copied whole under `<parent>-<name>`, so two asset folders that share a
  slug across categories stay apart; a file entry lands directly in the bucket under its
  basename. Entries of one claim that land under the same copy name merge. A job can be claimed more than once,
  and the buckets carry the tree as it stands at the latest claim: a re-claim first removes exactly what the
  previous claim of this bundle copied, which the bundle keeps a record of, so a file the tree no longer has does
  not survive in the bucket. A claim record that exists but cannot be read refuses the re-claim: nothing is
  removed or copied. Nothing else is removed, so the files written into the bucket at dispatch stay. A
  bucket whose manifest is empty is not created. An entry resolving outside the work tree is rejected rather
  than copied. A manifest that is not a list, an entry that is not a string, an entry naming a directory that
  contains the job's own bundle, and a directory entry whose copy name is already a file in the bucket that no
  claim created are rejected the same way; such a file is left untouched.

  Args:
    jdir: Job bundle directory the buckets are created under.
    cfg: Parsed `config.json` carrying the two manifests.
    work_root: Tree the entries are read from — the job's linked worktree when it has one,
      otherwise the repository checkout.

  Returns:
    None when every declared entry was copied, or a one-line message naming the first entry that was rejected,
    including a directory entry whose copy name clashes with an existing file, or saying that the earlier claim's
    record cannot be read.
  """
  # a job can be claimed more than once, and the buckets carry the tree as it stands at this claim: what an
  # earlier claim copied goes first, once, so a file the tree no longer has does not survive. Only recorded
  # copies are removed — the buckets also hold the files written at dispatch
  refusal = _drop_earlier_copies(jdir)

  # guard: the earlier claim's record is there but unreadable — which entries are its copies is unknown, so
  # the re-claim is refused before anything is removed or copied, and the damaged record stays in place
  if refusal is not None:
    return refusal
  copied: dict[str, set[str]] = { JobIODir.SOURCE: set(), JobIODir.CONTEXT: set() }

  # the record is written for whatever landed, also when an entry is rejected or a copy raises midway —
  # the next claim has to find every copy this one left
  try:
    return _copy_manifests(jdir, cfg, work_root, copied)
  finally:
    _write_claim_copies(jdir, copied)


def _copy_manifests(jdir: Path, cfg: dict, work_root: Path, copied: dict[str, set[str]]) -> str | None:
  """
  Copy the entries of a job's two manifests into its buckets, merging entries that share a copy name.

  Args:
    jdir: Job bundle directory the buckets are created under.
    cfg: Parsed `config.json` carrying the two manifests.
    work_root: Tree the entries are read from.
    copied: Bucket name mapped to the names copied so far; every entry copied here is added to it.

  Returns:
    None when every declared entry was copied, or a one-line message naming the first entry that was rejected.
  """
  # both buckets share one loop — the only difference is which manifest key feeds which dir
  for key, bucket in ( ( JobConfigKey.SOURCE_PATHS, JobIODir.SOURCE ),
                       ( JobConfigKey.CONTEXT_PATHS, JobIODir.CONTEXT ) ):
    manifest = cfg.get(key) or []

    # guard: the manifest is caller-written JSON — anything but a list names no entries to copy
    if not isinstance(manifest, list):
      return f"{bucket}/: declared manifest {manifest!r} is not a list of paths"
    for rel in manifest:
      # guard: an entry that is not a path string names no file, and joining it onto the work
      # root would raise instead of failing this one job
      if not isinstance(rel, str):
        return f"{bucket}/: declared entry {rel!r} is not a repo-relative path string"
      src = (work_root / rel).resolve()

      # guard: a `../`-bearing entry would stage files from outside the checkout into a bundle the
      # expert reads and may commit — the manifest arrives as JSON on stdin, so it is untrusted
      if not src.is_relative_to(work_root.resolve()):
        return f"{bucket}/: declared path {rel!r} escapes the work tree"

      # guard: the entry vanished between dispatch and claim — deterministic, retry cannot help
      if not src.exists():
        return f"{bucket}/: declared path {rel!r} does not exist at claim time"

      # guard: a directory holding this very bundle would be copied into itself, level after
      # level, until the path length runs out — and the bundle keeps what was copied
      if jdir.resolve().is_relative_to(src):
        return f"{bucket}/: declared path {rel!r} contains the job's own bundle"
      dst_dir = jdir / bucket
      dst_dir.mkdir(exist_ok = True)

      # a directory arrives whole under `<parent>-<name>`: two asset folders declared from
      # different categories share their own name and would otherwise merge into one; a file goes
      # flat, which is the layout every protocol's per-kind subdir declaration already describes
      if src.is_dir():
        copy_dir = dst_dir / f"{src.parent.name}-{src.name}"

        # guard: the copy name is taken by something that is not a directory — a file written at dispatch,
        # or a file entry of this claim; it stays as it is, and the entry cannot be merged into it
        if copy_dir.is_symlink() or (copy_dir.exists() and not copy_dir.is_dir()):
          return f"{bucket}/: declared path {rel!r} cannot be copied, {copy_dir.name!r} is already a file there"

        # the name joins the claim's list before the copy, so a copy that raises midway is still in the record
        # the claim writes once its copies end; the record is not on disk while the copy runs, so a claim
        # killed midway leaves its partial copy unrecorded. Two entries under one copy name merge
        copied[bucket].add(copy_dir.name)
        shutil.copytree(src, copy_dir, dirs_exist_ok = True)
      else:
        copied[bucket].add(src.name)
        shutil.copy2(src, dst_dir / src.name)

  # every declared entry landed — the caller may proceed to the spawn
  return None


def _compose_user_prompt(jdir: Path, *, protocols: list, aspects: list, arguments: dict) -> str:
  """
  Compose the user-facing prompt that drives the expert spawn.

  The prompt lists each resolved protocol, aspect, and argument as an explicit line,
  points at the request/source/context/result directories under the job, and appends a
  no-commit clause when the per-job config forbids commits inside the repository.

  Args:
    jdir: Path to the job directory the prompt addresses.
    protocols: Resolved protocol document paths to include in the prompt.
    aspects: Resolved aspect document paths to include in the prompt.
    arguments: Routine-supplied keyword arguments for the expert, serialized verbatim.

  Returns:
    The composed multi-line prompt text.
  """
  prompt_lines = [
    "Process this expert job. Concrete paths (already resolved — do not look up env vars):"
  ]
  for protocol in protocols:
    prompt_lines.append(f"- protocol:           {protocol}")
  for aspect in aspects:
    prompt_lines.append(f"- aspect:             {aspect}")
  for key in sorted(arguments):
    rendered = json.dumps(arguments[key], ensure_ascii = False, sort_keys = True)
    prompt_lines.append(f"- argument:           {key} = {rendered}")
  prompt_lines.extend([
    f"- request.json:      {jdir}/request.json",
    f"- source/ dir:       {jdir}/source/",
    f"- context/ dir:      {jdir}/context/  (may be absent)",
    f"- result/ dir:       {jdir}/result/   (write outputs here)",
    f"- response.json:     {jdir}/response.json  (write your final outcome here)",
    "",
    "Steps: Read the protocol(s) + aspect(s) + request.json, perform the work per the protocol, "
    "write result files into result/, write response.json with outcome + result array "
    "per the protocol's response.json schema, then exit. Do not touch DONE — daemon does that.",
    "",
    _ENVELOPE_RULE,
  ])

  # a rejected previous attempt left its reason behind — the re-spawn is told what was
  # wrong with it, since repeating the same prompt would only reproduce the same answer
  rejection = _read_rejection(jdir)
  if rejection is not None:
    prompt_lines.extend([ "", rejection ])

  # a job not allowed to commit in the repository carries the no-commit clause in its prompt
  if not json.loads((jdir / JobFile.CONFIG).read_text(encoding = "utf-8")).get(
    JobConfigKey.CAN_COMMIT_IN_REPO, False,
  ):
    clause = (
      # waiver: filesystem path idiom, not a domain constant
      Path(__file__).parent.parent / "templates" / "expert-prompts" / "no-commit-clause.md"
    )
    if clause.exists():
      prompt_lines.extend([ "", clause.read_text(encoding = "utf-8").strip() ])

  # the prompt is one newline-joined text
  return "\n".join(prompt_lines)


def _refresh_sandbox_file(repo: Path) -> None:
  """
  Bring an existing sandbox settings file current with the repository's declared sandbox settings.

  Notes:
    - An absent file is never created here: that is install's step, and a checkout without one
      spawns unconfined on purpose.

  Args:
    repo: Repository root whose sandbox file and tracked settings are read.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
    OSError: If the sandbox file cannot be rewritten.
  """
  # guard: no sandbox file — nothing carries the declaration to a spawn, and the pump does not start one
  if not (repo / RuntimeFile.SANDBOX_SETTINGS).is_file():
    return

  # the declaration reaches the spawn through this file alone; a pass that changes nothing leaves it untouched
  sandbox_scope.sync(repo)


def filter_tcc_protected(entries: list[object]) -> list[str]:
  """
  Select the directory entries a background spawn cannot load without a TCC consent prompt.

  Guarantees:
    - The returned entries keep the order of the input and are spelled exactly as written,
      never expanded or normalised, so a caller can match them back to the input by equality.

  Args:
    entries: Values of a `permissions.additionalDirectories` list, as written.

  Returns:
    The string entries that, with `~` and environment variables expanded, name a TCC-gated
    location or lie under one, in their input order and spelled as written.
  """

  # Contract:
  # The returned entries keep the order of the input and are spelled exactly as written,
  # never expanded or normalised, so a caller can match them back to the input by equality.

  # the roots are compared in expanded form so a tilde entry and its absolute twin match alike
  roots = [ os.path.normpath(os.path.expanduser(root)) for root in _TCC_PROTECTED_ROOTS ]
  flagged: list[str] = []
  for entry in entries:
    # guard: only a non-empty string names a directory
    if not isinstance(entry, str) or not entry:
      continue

    # an entry is gated when it is a gated root itself or sits anywhere below one
    expanded = os.path.normpath(os.path.expandvars(os.path.expanduser(entry)))
    if any(expanded == root or expanded.startswith(root + os.sep) for root in roots):
      flagged.append(entry)
  return flagged


def get_additional_dirs(doc: object) -> list[object]:
  """
  Read the `permissions.additionalDirectories` list out of a parsed Claude settings document.

  Args:
    doc: The parsed settings document.

  Returns:
    The list as written, or an empty list when the document or either key is missing or malformed.
  """
  permissions = doc.get(ClaudeSettingsKey.PERMISSIONS) if isinstance(doc, dict) else None
  dirs = permissions.get(ClaudeSettingsKey.ADDITIONAL_DIRECTORIES) if isinstance(permissions, dict) else None
  return dirs if isinstance(dirs, list) else []


def _sanitize_local_settings(repo: Path) -> list[str]:
  """
  Strip TCC-gated directories from the checkout's local Claude settings before a spawn loads them.

  Notes:
    - Rewrites the operator's gitignored `.claude/settings.local.json` in place when something is stripped.
    - Writes one line to stderr when a file is skipped as unreadable or unparsable, and one line when
      entries are stripped.

  Args:
    repo: Repository root whose `.claude/settings.local.json` is read and, when needed, rewritten.

  Returns:
    The removed entries as written; empty when the file is absent, unreadable, not valid JSON,
    or carries nothing to strip — in those cases the file is left byte-identical.

  Raises:
    OSError: If the rewritten file cannot be written.
  """
  path = repo / ClaudeSettingsFile.LOCAL

  # guard: no local overlay — a spawn loads nothing from it
  if not path.is_file():
    return []

  # guard: a file that cannot be read or parsed is left alone — nothing can be stripped from it safely
  try:
    doc = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    sys.stderr.write(f"local settings not sanitized: {path} cannot be read as JSON ({error})\n")
    return []

  # the gated entries are selected from the list as written so they can be matched back exactly
  dirs = get_additional_dirs(doc)
  removed = filter_tcc_protected(dirs)

  # guard: nothing gated in the list — the file stays byte-identical
  if not removed:
    return []

  # the list is rewritten in place; every other key of the document survives untouched
  doc[ClaudeSettingsKey.PERMISSIONS][ClaudeSettingsKey.ADDITIONAL_DIRECTORIES] = [
    entry for entry in dirs if entry not in removed
  ]
  path.write_text(json.dumps(doc, indent = 2) + "\n", encoding = "utf-8")
  sys.stderr.write(f"local settings: stripped TCC-gated additionalDirectories {removed} from {path}\n")
  return removed


def _spawn_settings_argv(repo: Path) -> list[str]:
  """
  Build the `--settings` argv fragment for an expert spawn.

  Args:
    repo: Repository root the spawn runs inside.

  Returns:
    A two-element `["--settings", <path>]` list when the sandbox settings file exists,
    otherwise an empty list.
  """
  settings_file = repo / RuntimeFile.SANDBOX_SETTINGS

  # guard: sandbox settings file absent (`/lazy-core.install` never ran its sandbox step here) — spawn unsandboxed
  if not settings_file.is_file():
    return []
  return [ "--settings", str(settings_file) ]


def normalize_mcp_config(mcp_config: str | list[str] | None, repo: Path) -> list[str]:
  """
  Resolve a per-expert MCP-config setting into absolute config-file paths.

  Accepts a single path string or a list of them; a relative entry is anchored
  at the repository root (the spawn's working directory). A falsy or empty
  setting yields an empty list — the hermetic default.

  Args:
    mcp_config: The `mcp_config` value from the job's `config.json`, or None.
    repo: Repository root that relative config paths resolve against.

  Returns:
    Absolute MCP-config paths in declaration order, or an empty list.
  """
  # guard: no per-expert MCP config declared — hermetic spawn, zero servers
  if not mcp_config:
    return []
  paths = [ mcp_config ] if isinstance(mcp_config, str) else list(mcp_config)
  out: list[str] = []
  for entry in paths:
    # guard: skip non-string / empty entries defensively
    if not isinstance(entry, str) or not entry:
      continue
    entry_path = Path(entry)
    out.append(str(entry_path if entry_path.is_absolute() else (Path(repo) / entry_path)))
  return out


def normalize_setting_sources(setting_sources: str | list[str] | None) -> list[str]:
  """
  Resolve a per-expert `setting_sources` setting into valid `--setting-sources` scopes.

  Turns an expert's declared setting-source scopes into the value passed on the spawn's
  command line, falling back to the hermetic `project`, `local` default so the flag is
  always emitted and every expert is hermetic out of the box.

  Args:
    setting_sources: The `setting_sources` value from the job's `config.json`
      (a scope string, a list of them, or None).

  Returns:
    The resolved scope names in declaration order, never empty.
  """
  # guard: no per-expert scopes declared — hermetic default (drop user scope)
  if not setting_sources:
    return list(_DEFAULT_SETTING_SOURCES)
  raw = setting_sources.split(",") if isinstance(setting_sources, str) else list(setting_sources)
  out: list[str] = []
  for entry in raw:
    # guard: skip non-string / empty entries defensively
    if not isinstance(entry, str) or not entry.strip():
      continue
    scope = entry.strip().lower()

    # keep only recognized, de-duplicated scopes
    if scope in VALID_SETTING_SOURCES and scope not in out:
      out.append(scope)

  # guard: nothing valid survived filtering — fall back to the hermetic default
  if not out:
    return list(_DEFAULT_SETTING_SOURCES)
  return out


def build_expert_argv(repo: Path, env: dict[str, str], *, contract_path: Path,
                      model: str | None, mcp_config: str | list[str] | None,
                      agent_ref: str, prompt: str,
                      setting_sources: str | list[str] | None = None) -> list[str]:
  """
  Assemble the `claude -p` command line for an expert spawn.

  The spawn always runs `--strict-mcp-config`, so ambient operator MCP servers
  (`~/.claude.json`, project `.mcp.json`) are never inherited — a headless
  daemon spawn has no TTY and would otherwise block on an interactive-auth
  server's initialization until the job times out. MCP servers come only from
  the per-expert `mcp_config` allow-list, if any.

  The spawn also always passes `--setting-sources`, defaulting to `project,local`
  so operator user-scope settings — where interactive plugins and their hooks
  live — never load in a headless spawn; an expert opts back into `user` scope
  explicitly. The pump and the launchability preflight share this builder so the
  probed command line matches the real one.

  Guarantees:
    - The assembled command line always includes `--strict-mcp-config`, so no ambient operator
      MCP server is ever inherited; MCP servers come only from the per-expert `mcp_config`
      allow-list.
    - The assembled command line always includes `--setting-sources`, defaulting to
      `project,local` when the expert declares none, so operator user-scope settings never load
      unless the expert explicitly opts into `user` scope.

  Args:
    repo: Repository root the spawn runs inside.
    env: Environment mapping the spawn inherits; read for `LAZYCORTEX_PLUGIN_DIRS`.
    contract_path: Path to the expert-runtime contract appended as a system prompt.
    model: Model tier pin, or None to inherit the CLI default.
    mcp_config: Per-expert MCP-config path(s), or None for a hermetic spawn.
    agent_ref: Scoped agent reference the spawn resolves.
    prompt: The user prompt passed to `claude -p`.
    setting_sources: Per-expert setting scopes, or None for the hermetic `project,local` default.

  Returns:
    The full argv list ready for `subprocess.run`.
  """

  # Contract:
  # The assembled command line MUST always include `--strict-mcp-config`; no ambient operator
  # MCP server (from `~/.claude.json` or a project `.mcp.json`) is ever inherited. MCP servers
  # reach the spawn only through the per-expert `mcp_config` allow-list.

  # Contract:
  # The assembled command line MUST always include `--setting-sources`, defaulting to
  # `project,local` when the expert declares none. Operator user-scope settings NEVER load in
  # the spawn unless the expert explicitly opts into `user` scope.

  # `--permission-mode dontAsk` (not `bypassPermissions`): auto-deny any tool
  # call outside the sandbox — bypassPermissions skips even deny rules and lets a
  # misguided agent burn minutes on `find /Users/...`; dontAsk fails immediately.
  argv = [ "claude", "-p", "--permission-mode", "dontAsk",
           "--output-format", "stream-json", "--verbose",
           "--append-system-prompt-file", str(contract_path),
           "--strict-mcp-config",
           "--setting-sources", ",".join(normalize_setting_sources(setting_sources)) ]
  for cfg_path in normalize_mcp_config(mcp_config, repo):
    argv.extend([ "--mcp-config", cfg_path ])

  # propagate plugin-dir flags so the spawn sees the same plugin tree as the
  # daemon; without them `claude -p` falls back to its cache and chases sibling
  # skills via slow `find` on Dropbox checkouts. Set by runtime_daemon.
  # waiver: environment-variable name, not a domain key
  for plugin_dir in (env.get("LAZYCORTEX_PLUGIN_DIRS") or "").split(os.pathsep):
    # a cached root is the install Claude Code already loads — passing it again would load
    # the plugin twice; only dev source trees need the flag
    if plugin_dir and not is_cache_root(Path(plugin_dir)):
      argv.extend([ "--plugin-dir", plugin_dir ])
  argv.extend(_spawn_settings_argv(repo))
  if model:
    argv.extend([ "--model", model ])

  # `--agent` resolves by NAME (scoped `<plugin>:<name>`), never by file path — a
  # path or de-scoped name silently falls back to the body-less default assistant.
  argv.extend([ "--agent", agent_ref, prompt ])
  return argv


def _process_one(repo: Path, expert_name: str, jdir: Path) -> None:
  """
  Run one Claude spawn for a single READY job.

  A stream-idle stall retries the spawn in-process, starting a fresh session for each
  attempt, up to the configured stall-retry limit (`daemon.stream_max_retries`, default 3)
  before the job is left in a READY+ERROR state for the next pump tick to retry. Any other
  transient failure — a non-zero exit — still gets exactly one attempt per pump tick before
  the same READY+ERROR outcome. A clean exit that leaves no usable response.json (missing, or
  lacking an `outcome`) first has the response recovered from the final assistant text of the
  transcript when possible; otherwise the rejection reason is recorded and the job is re-queued
  (READY without DONE) for a corrective re-spawn, and once the envelope retry limit is spent the
  job is closed as a logical error, never as a transient one. A successful run that leaves
  the working tree dirty raises `_ExpertDirtyTreeError` so the pump halts the queue.

  A job run on the shared checkout (no isolated worktree) whose config bars committing in the repository is held
  to that bar whatever the run's exit, a non-zero exit or a stall included. A barred job that committed is failed
  as a logical error and the daemon halts naming it. A check that could not be made halts the daemon the same
  way without changing how the job itself is classified. A job once found committing is failed without running
  again. Once a job on the shared checkout is claimed, the barred orphans of its identity whose spawn still runs
  are recorded against it, so their commits are told apart from the job's own.

  When the job carries a resolved provider, the spawn's environment is remapped to that
  provider's endpoint — tier aliases, `ANTHROPIC_BASE_URL`, and `ANTHROPIC_AUTH_TOKEN` are
  overridden, and `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, the variable named by
  `daemon.token_env`, and the daemon's own token digest marker are all stripped from the spawn
  environment so neither the operator's own Anthropic credentials nor the daemon's own token
  source ever reaches it. A token that cannot be found in the environment or in
  `~/.claude/.env` fails the job before the Claude subprocess is spawned.

  Notes:
    - Each run rewrites the checkout's `.claude/settings.local.json` in place, before the expert is spawned,
      when that file carries a TCC-gated `permissions.additionalDirectories` entry.

  Args:
    repo: Repository root the spawn runs inside.
    expert_name: Name of the expert that owns this job.
    jdir: Path to the job directory being processed.

  Raises:
    _ExpertDirtyTreeError: When the expert exited cleanly but left uncommitted changes.
    _ExpertForbiddenCommitError: When a job barred from committing in the repository committed on the shared
      checkout; the job has been closed as a logical error and the daemon-wide halt has been raised.
    _PumpEnvironmentError: When the daemon stream settings are not numbers or the checkout's settings files,
      including `.claude/settings.local.json`, cannot be prepared (both before anything of the job is read), or
      when the expert binary is missing from PATH at spawn time, in which case the claim is undone; in all three
      the job is left queued, unclaimed. Also when git cannot be run to record the claim's head commit, in which
      case the claim is undone (the PID marker is removed, attempts are not incremented) and the job is left
      queued. Also when the work-tree check after a finished run could not be made, in which case
      the job keeps its own finished response, which is left as it is.
    OSError: When the expert process cannot be started although the binary is on PATH; it is the job's own failure.
      Also when an isolated job's bundle cannot hold the branch-origin record written right after its worktree is
      created, or holds a record that cannot be read; in both cases the worktree is removed before the error
      propagates. Also when the job tree cannot be read while the claim records the orphans it overlaps.
  """
  # the idle-watchdog settings are read per job, a cheap single-file read that keeps each spawn on the live config
  daemon = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON)
  try:
    idle_timeout_sec = int(daemon.get(DaemonKey.STREAM_IDLE_TIMEOUT_SEC, _STREAM_IDLE_TIMEOUT_DEFAULT))
    max_stall_retries = max(0, int(daemon.get(DaemonKey.STREAM_MAX_RETRIES, _STREAM_MAX_RETRIES_DEFAULT)))
  except (TypeError, ValueError) as error:
    raise _PumpEnvironmentError(f"daemon stream settings are not numbers: {error}") from error

  # Decision: the daemon checkout's local overlay is rewritten in place, not shadowed by a
  # filtered copy — Claude Code concatenates `additionalDirectories` across every loaded
  # scope, so a copy handed through `--settings` cannot hide an entry the file still carries

  # the sandbox file is re-derived from the declared settings before the command line names it,
  # so a domain declared since the last install reaches this very job; a TCC-gated directory in
  # the local overlay would hang the spawn at startup on a consent prompt no background process
  # can answer, so it is stripped before the spawn loads the file. Both touch the checkout's own
  # settings and nothing of the job, so they run before the job's bundle is read or written: a
  # fault here is the checkout's, and the job is still exactly as it was queued
  try:
    _refresh_sandbox_file(repo)
    _sanitize_local_settings(repo)
  # waiver: every failure of the two settings rewrites is re-labelled, whatever its type, so the
  # pump's per-job boundary does not charge it to the job
  except Exception as error:  # pylint: disable=broad-exception-caught
    raise _PumpEnvironmentError(f"checkout settings could not be prepared: {error}") from error

  # per-job config.json carries everything the pump needs: agent ref,
  # protocols list (declared by the routine that created this job),
  # git_author for any commits the expert makes. Routine wrote it at
  # dispatch time; pump never consults lazy.settings.json[experts].
  config_path = jdir / JobFile.CONFIG

  # guard: per-job config missing — write logical error and bail
  if not config_path.exists():
    _write_error(jdir, JobErrorCategory.LOGICAL, f"config.json missing in {jdir}")
    return
  try:
    cfg = json.loads(config_path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    _write_error(jdir, JobErrorCategory.LOGICAL, f"unreadable config.json: {error}")
    return

  # the job config names the agent plus the reference sets composed onto it
  agent_ref = cfg.get(JobConfigKey.AGENT)
  protocols_refs = cfg.get(JobConfigKey.PROTOCOLS) or []
  aspects_refs   = cfg.get(JobConfigKey.ASPECTS) or []
  arguments      = cfg.get(JobConfigKey.ARGUMENTS) or {}
  model          = cfg.get(JobConfigKey.MODEL)
  provider       = cfg.get(JobConfigKey.PROVIDER)
  mcp_config     = cfg.get(JobConfigKey.MCP_CONFIG)
  setting_sources = cfg.get(JobConfigKey.SETTING_SOURCES)

  # guard: agent reference must be present in config
  if not agent_ref:
    # waiver: one-off human-facing message
    _write_error(jdir, JobErrorCategory.LOGICAL, "config.json: missing agent")
    return

  # guard: a job once found to have committed although barred is failed for good and never runs again
  if commit_guard.is_tainted(jdir):
    _write_error(jdir, JobErrorCategory.LOGICAL, _FORBIDDEN_COMMIT_FAILURE)
    return

  # empty protocols + empty aspects is a valid config. Specific-domain
  # agents (test-designer, lazy-review.doc_doctor, …) are
  # self-contained — the .md frontmatter + body IS the full instruction.
  # The composition path (generic agent + aspects + protocol) is one
  # valid spawn shape, not the only one. No guard needed; pump spawns
  # whatever the agent file alone can do.

  # every reference is resolved to a real file before the subprocess is shaped
  try:
    # waiver: cross-module reference-category token, not an internal key
    agent_path = resolve(agent_ref, category = "agents", repo = repo)
    protocol_paths = [
      # waiver: cross-module reference-category token, not an internal key
      resolve(ref, category = "protocols", repo = repo) for ref in protocols_refs
    ]
    aspect_paths = [
      # waiver: cross-module reference-category token, not an internal key
      resolve(ref, category = "aspects", repo = repo) for ref in aspects_refs
    ]
  except ReferenceError as error:
    _write_error(jdir, JobErrorCategory.LOGICAL, str(error))
    return

  # `workspace: branch` enforcement — runtime-owned, invisible to the expert (it never
  # runs git worktree commands itself; see lazy-core.expert-runtime-contract.md "What you
  # must not touch"). `workspace: branch` is a CAPABILITY, not a mandate: it activates only
  # when the caller's own payload names a `branch` (a launch-checkbox dispatch or its
  # continuation, both of which the coordinator writes explicitly) — a job dispatched to
  # the same expert without one (an ordinary review-rewrite from `review.coordinator`,
  # say) runs on whatever is already checked out, byte-identical to `workspace: main`.
  # The token stays `branch` for compatibility; since the worktree conversion the job runs
  # in a linked worktree on that branch and the primary checkout never leaves base.
  # `worktree_dir` stays None whenever enforcement doesn't apply.
  worktree_dir: Path | None = None
  workspace = cfg.get(JobConfigKey.WORKSPACE, WorkspaceMode.MAIN)

  # best-effort — dispatch_job always writes valid JSON, so an unreadable request.json is
  # not this branch-capability check's problem to diagnose; it just reads as "no branch"
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
    job_branch = request.get(JobRequestKey.BRANCH)
    # the optional named fork point of a fresh job branch; absent means the base
    branch_from = request.get(JobRequestKey.BRANCH_FROM) or None
  except (OSError, json.JSONDecodeError):
    job_branch = None
    branch_from = None

  # a workspace:main (or absent) expert never branches — a payload naming one anyway (the
  # same expert also dispatched for review rewrites) is ignored, not refused
  if workspace != WorkspaceMode.BRANCH and job_branch:
    sys.stderr.write(_PAYLOAD_BRANCH_IGNORED.format(expert = expert_name, workspace = workspace,
                                                    branch = job_branch))
  # the reverse mismatch: a workspace:branch expert dispatched with no payload branch (an
  # ordinary review-rewrite sharing the expert) runs on the current checkout too — logged for
  # the same observability the reverse case above gets, since it is the same capability-not-
  # mandate shape from the other side
  elif workspace == WorkspaceMode.BRANCH and not job_branch:
    sys.stderr.write(_PAYLOAD_BRANCH_MISSING.format(expert = expert_name))

  # `branch` present AND this expert opted in — activate the capability for this dispatch;
  # any other combination leaves worktree_dir None and the job runs on the current checkout
  branch_created = False
  branch_preexisted = False
  mgr: WorktreeTaskManager | None = None
  pre_spawn_tip: str | None = None
  if workspace == WorkspaceMode.BRANCH and job_branch:
    # guard: a start point that is not a string cannot name a branch — refuse rather than hand it to git
    if branch_from is not None and not isinstance(branch_from, str):
      # waiver: one-off human-facing message
      _write_error(jdir, JobErrorCategory.LOGICAL, f"workspace: branch_from {branch_from!r} is not a branch name")
      return

    # the base branch is the fork point for a fresh job branch — without it there is nothing
    # to fork from
    base_branch = _resolve_base_branch(repo)

    # guard: no configured base — refuse rather than fork a job branch off an arbitrary point
    if not base_branch:
      # waiver: one-off human-facing message
      _write_error(jdir, JobErrorCategory.LOGICAL, "workspace: branch requires daemon.git.base_branch configured")
      return

    # the job runs in its own linked worktree; the primary checkout never leaves base
    git_cfg = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.GIT) or {}
    mgr = WorktreeTaskManager(
      repo, base_branch,
      # waiver: filesystem path idiom, not a domain constant
      worktree_root = git_cfg.get(GitConfigKey.WORKTREE_ROOT, ".worktrees"),
      worktree_links = git_cfg.get(GitConfigKey.WORKTREE_LINKS) or (),
    )
    try:
      worktree_dir, branch_created = mgr.create(jdir.name, job_branch, start_point = branch_from)
    except WorktreeStartError as error:
      _write_error(jdir, JobErrorCategory.LOGICAL, f"workspace: branch worktree failed: {error}")
      return

    # whether the job continues earlier work is fixed at its first attempt, before anything can fail it; the
    # worktree already exists, so a bundle that cannot hold the record must not leave it behind
    try:
      branch_preexisted = _ensure_branch_origin(jdir, branch_created = branch_created)
    except OSError:
      mgr.remove(worktree_dir)
      raise

    # rebuild the gitignored execution environment the worktree does not materialise
    bootstrap_error = mgr.bootstrap(worktree_dir, git_cfg.get(GitConfigKey.WORKTREE_BOOTSTRAP_CMD))

    # guard: a broken environment must fail the job before the spawn, not confuse the agent mid-run
    if bootstrap_error is not None:
      mgr.remove(worktree_dir)
      _write_error(jdir, JobErrorCategory.TRANSIENT, f"workspace: branch {bootstrap_error}")
      return

    # the tip before the spawn anchors the did-anything-land check — on a continuation the
    # branch already carries earlier rounds' commits, so "commits over base" would not do
    pre_spawn_tip = _worktree_head(worktree_dir)

  # a commitless finish is open only to a continuation of a branch that existed before the job's first attempt,
  # in a bundle its dispatcher marked — a first run keeps its commit obligation, retried or not
  commitless_ok = branch_preexisted and bool(cfg.get(JobConfigKey.ALLOW_NO_COMMIT, False))

  # Decision: remove the job's worktree unconditionally, not keep a dirty one for inspection — the
  # branch survives as the only durable product; an agent's uncommitted dirt disappears with the
  # directory (operator decision 2026-08-14).

  # from here on the job's worktree (if any) exists — every exit, including one raised by code
  # below rather than returned, must remove it so a crashed spawn never leaves a stray worktree
  # for the whole polling interval (the hourly sweep is the backstop, not the plan). The `try`
  # opens right here, before the git-author dict access below, so a malformed `git_author` in a
  # job's config.json (a string where a dict is expected) can't strand the worktree either.
  try:
    # the expert commits under its own identity, passed down through the environment
    git_author = cfg.get(JobConfigKey.GIT_AUTHOR) or {}
    # an isolated job's agent runs git with the bootstrap's byproducts ignored; every other job inherits as is
    env = os.environ.copy() if worktree_dir is None else _isolation_git_env(worktree_dir, os.environ)
    # waiver: environment-variable name, not a domain key
    env["GIT_AUTHOR_NAME"]  = git_author.get("name",  "")
    # waiver: environment-variable name, not a domain key
    env["GIT_AUTHOR_EMAIL"] = git_author.get("email", "")

    # Decision: inherit the hook allow-list from the dispatching routine, not export it per spawn —
    # the pump is itself a routine, so the daemon already put `hooks_enabled` into this process's
    # environment. Exporting here would let a queued job override the routine that dispatched it,
    # and would split the setting across two config surfaces again.

    # Decision: pin the subagent-spawn depth explicitly, not the `claude` CLI's own default — a
    # future default change must never silently change how deep a headless expert's own
    # subagents may nest. `plugin_dirs.set_plugin_dirs` pins the same value onto the
    # daemon's own subprocess environment, for routines that spawn outside this function.

    # pin it on this spawn's own env
    env[EnvVar.MAX_SUBAGENT_SPAWN_DEPTH] = EnvVar.SUBAGENT_SPAWN_DEPTH_PIN

    # Domain(runtime.job-execution):
    # # A job never repairs its own environment
    # An expert job works with the environment it was given. Every job runs the plugins' tools in a protected mode,
    # however the daemon itself is run, and in that mode a tool that finds the environment missing or out of date
    # fails with the cause and the job stops; it never installs, recreates or reconfigures anything itself. The
    # operator brings the environment up to date and then continues or rebuilds the job.

    # every spawn runs the plugins' tools in protected mode, whatever the daemon's own environment says
    env[EnvVar.PROTECTED] = EnvVar.PROTECTED_ON

    # Domain(runtime.protocols):
    # # Protocol inheritance along a job chain
    # A job's protocols carry over to every job it dispatches from inside its own run, the same
    # way a routine's subprocess passes the routine's protocols on to the jobs it queues.

    # Decision: export the job's own protocols on each spawn, not inherit them from this
    # process's routine environment — the pump is a routine of its own with no protocols, so the
    # dispatching routine's list is absent here and a chained job would otherwise carry none.

    # hand the job's protocol list to the spawn
    env.update(build_protocols_env(protocols_refs))

    # a provider-bound job talks to its own endpoint: remap the base URL, swap the
    # auth token, and pin every tier alias to the provider's model names so nothing
    # inside the harness leaks a Claude alias to a foreign server
    if provider:
      token = resolve_token(provider[ProviderKey.TOKEN_ENV])

      # guard: no token — fail the job before the spawn, with the variable named
      if token is None:
        _write_error(
          jdir, JobErrorCategory.LOGICAL,
          f"provider {provider[ProviderKey.NAME]!r}: token variable "
          f"{provider[ProviderKey.TOKEN_ENV]!r} is set neither in the environment nor in ~/.claude/.env",
        )
        return

      # endpoint, token and tier aliases in; the operator's and the daemon's own credentials out
      apply_spawn_env(env, provider, token, daemon_token_env = daemon.get(DaemonKey.TOKEN_ENV))

    # the buckets are filled now, not at dispatch — a job that waited in the queue starts from
    # the tree as it stands at claim, which is what makes the serial queue safe against a
    # stale snapshot
    materialize_error = _materialize_io(jdir, cfg, worktree_dir or repo)

    # guard: a declared path vanished or reaches outside the work tree — a logical fault the
    # owning coordinator sorts out on its next wake
    if materialize_error is not None:
      _write_error(jdir, JobErrorCategory.LOGICAL, materialize_error)
      return

    # the spawn's user prompt names every resolved protocol, aspect and argument the job carries
    prompt = _compose_user_prompt(jdir, protocols = protocol_paths, aspects = aspect_paths, arguments = arguments)

    # an isolated job carries its commit obligation in the prompt, worded by the branch as this attempt finds it —
    # an existing branch's commits are built on, never rewritten — while the commitless note follows the
    # first-attempt answer; the protocol files under the job dir are reached by absolute paths, so the worktree
    # cwd changes nothing else
    if worktree_dir is not None and job_branch:
      prompt += "\n\n" + _format_isolation_prompt(
        job_branch, is_fresh = branch_created, commitless_ok = commitless_ok,
      )

    # the runtime contract the spawn is pointed at
    # waiver: filesystem path idiom, not a domain constant
    contract_path = (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()

    # mark this job as ours: write PID before invoking the expert.
    # The dead-job detector reads this to distinguish queued (no PID)
    # from active (PID file present, alive) from stuck (PID dead).
    (jdir / JobMarker.PID).write_text(f"{os.getpid()}\n", encoding = "utf-8")

    # the commit the buckets above were copied from — the one fact that lets a consumer tell
    # a change this job already read from one that landed after it started. Reading it runs git:
    # when git itself cannot be run the fault is the host's, so the claim is undone and the job
    # goes back to the queue
    try:
      _record_claim_head(jdir, worktree_dir or repo)
    except OSError as error:
      (jdir / JobMarker.PID).unlink(missing_ok = True)
      raise _PumpEnvironmentError(f"the work tree's HEAD could not be read: {error}") from error

    # a barred orphan of the same identity whose spawn still runs beside this job makes their commits ambiguous;
    # the claim records it, so the orphan's judgement can tell
    if worktree_dir is None:
      commit_guard.note_claim_overlaps(repo, jdir)

    # bump attempts counter — persists across pump kills + recovery cycles.
    # Recovery routine reads this to decide retry vs. permanent-fail.
    attempts_file = jdir / JobArtifact.ATTEMPTS
    try:
      attempts = int(attempts_file.read_text(encoding = "utf-8").strip())
    except (OSError, ValueError):
      attempts = 0
    attempts_file.write_text(f"{attempts + 1}\n", encoding = "utf-8")

    # the spawn command line — permission mode, hermetic `--strict-mcp-config` +
    # any per-expert `--mcp-config`, hermetic `--setting-sources`, plugin dirs,
    # `--settings` sandbox, model, and `--agent` — is assembled by
    # `build_expert_argv`, shared with the `lazy-runtime.preflight` launchability
    # probe so the probe matches the real spawn.
    # (`agent_path` is still resolved above and used for the read-only check below.)
    claude_argv = build_expert_argv(
      repo, env,
      contract_path = contract_path, model = model, mcp_config = mcp_config,
      agent_ref = agent_ref, prompt = prompt,
      setting_sources = setting_sources,
    )

    # idle-watchdog + bounded re-spawn. A `claude -p` stream can freeze (no first token,
    # or mid-response silence) while the API/network hiccups; a single blocking wait would
    # burn the whole routine timeout on a transient. Each spawn runs under an idle-stdout
    # watchdog: silence past idle_timeout_sec kills the spawn's process group and we
    # re-spawn a fresh session (the job dir is untouched — the expert redoes the work
    # idempotently). These in-memory stall retries are SEPARATE from the on-disk `attempts`
    # counter the recovery routine reads for permanent-fail decisions.
    returncode = -1
    stdout = stderr = ""
    stalled = False

    # Decision: rate-limit frames are read after EVERY attempt, not once after the loop — the
    # stdout buffer is overwritten between attempts, so a frame from an early attempt would be
    # lost, and a run the provider rejected exits non-zero, so binding the read to a clean exit
    # (as token capture does) would miss the very case the guard exists for.

    # Domain(runtime.job-execution):
    # # Idle-stream stall retry
    # A run that goes silent on its output stream for longer than the configured idle window
    # is treated as a transient freeze rather than a failure of the work itself, since the
    # underlying model service can hiccup mid-response. A stalled run is torn down and retried
    # from a fresh session up to a bounded number of times before the job is instead left for
    # the next scheduled attempt — each retry redoes the whole run, since a session that froze
    # partway through cannot be resumed from where it stopped.

    # frames seen across every attempt of this job, for the degradation warning below
    seen_frames = 0
    for stall_attempt in range(max_stall_retries + 1):
      try:
        returncode, stdout, stderr, stalled = _spawn_with_idle_watchdog(
          # an isolated job's agent works inside its worktree; every other job on the checkout
          claude_argv, env = env, cwd = worktree_dir or repo, idle_timeout_sec = idle_timeout_sec,
        )
      except OSError as error:
        # with the binary there, the spawn failed over something of this job (an argument list
        # too long, a vanished working directory), so the failure is the job's and closes it
        # waiver: environment-variable name, not a domain key
        if shutil.which(claude_argv[0], path = env.get("PATH")) is not None:
          raise

        # the expert binary itself is missing: the host's fault, which would fail every job the
        # same way. The claim is undone — marker, claim head and the attempt just counted — and
        # the job goes back to the queue instead of being closed
        (jdir / JobMarker.PID).unlink(missing_ok = True)
        (jdir / JobArtifact.CLAIM_HEAD).unlink(missing_ok = True)
        attempts_file.write_text(f"{attempts}\n", encoding = "utf-8")
        raise _PumpEnvironmentError(f"expert binary {claude_argv[0]!r} is not on PATH: {error}") from error
      seen_frames += _record_rate_limit(repo, expert_name, stdout)

      # a stream that produced output / exited on its own hands off to the outcome path
      if not stalled:
        break
      _append_stream_stall_log(repo, expert_name, jdir, stall_attempt + 1, idle_timeout_sec)
      sys.stderr.write(
        f"stream-idle-stall: {expert_name}/{jdir.name} "
        f"attempt {stall_attempt + 1}/{max_stall_retries + 1}\n"
      )

    # a job barred from committing is held to it whatever the run's outcome, since a commit lands before the exit
    # code says anything; an isolated job commits only on its own branch, never on the shared checkout
    verdict = commit_guard.judge(repo, jdir) if worktree_dir is None else None

    # a found commit fails the job, its transcript kept for whoever asks why; a check that could not be made
    # halts the daemon too, but leaves the run to be classified as it would be otherwise
    if verdict is not None:
      if verdict[1] is None:
        _persist_transcript(jdir, stdout)
        _write_error(jdir, JobErrorCategory.LOGICAL,
                     f"job barred from committing in the repository committed: {'; '.join(verdict[0])}")
      commit_guard.record(repo, expert_name, jdir, verdict, triggered_by = _PUMP_ROUTINE, on_halt = record_halt)
      if verdict[1] is None:
        raise _ExpertForbiddenCommitError(expert_name, jdir.name)

    # guard: every re-spawn stalled — record a transient error; the next tick re-dispatches
    if stalled:
      _write_error(
        jdir, JobErrorCategory.TRANSIENT,
        f"stream-idle-stall after {max_stall_retries + 1} spawn(s); no stdout for >{idle_timeout_sec}s",
      )
      return

    # Domain(runtime.job-execution):
    # # Rate-limit guard blind-spot signal
    # A run against the operator's own subscription is expected to carry at least one
    # rate-limit signal frame, however far from any limit it stayed. A run reporting none of
    # them does not mean the account is healthy — it means the signal the guard relies on to
    # notice trouble has stopped arriving, which is itself worth flagging separately from an
    # actually raised limit. The check covers every run that was not abandoned as stalled, a
    # run that failed included, and it holds even where the guard is switched off for the
    # repository. The one other exception is a run of a job barred from committing in the
    # repository that committed anyway: that run is stopped as a violation before the check
    # is reached, so it leaves no blind-spot line. The signal is a warning line on the
    # diagnostic stream only: it changes neither the job's outcome nor any rate-limit record.
    # A run against a foreign provider endpoint is exempt, since such an endpoint never emits
    # these frames in the first place.

    # silence must not read as "all clear": the provider emits a rate-limit frame in every run,
    # so a run that did not stall, a failed one included, carrying none means the signal the guard depends on
    # has degraded. A run stopped for a commit it was barred from never reaches this check.
    # A provider-bound run is exempt — a foreign endpoint sends no such frames, so silence there
    # is expected, not a blind spot.
    if seen_frames == 0 and not provider:
      sys.stderr.write(RATE_LIMIT_BLIND_TEMPLATE.format(expert = expert_name, job = jdir.name, exit = returncode))

    # persist the transcript — best-effort, never block DONE on a write failure.
    _persist_transcript(jdir, stdout)

    # a clean exit still needs a usable response.json before this job can reach DONE
    if returncode == 0:
      # a clean exit without a usable response.json — missing, or written but violating the
      # envelope — is salvaged from the final assistant text frame of the transcript, so a run
      # that narrated its result instead of writing it still reaches DONE
      if not outcome_tokens(read_response(jdir)):
        recovered = _extract_response_from_stdout(stdout or "")
        if recovered is not None:
          ( jdir / JobFile.RESPONSE ).write_text(json.dumps(recovered, indent = 2), encoding = "utf-8")

      # guard: no outcome survived the salvage — the envelope is violated, and a
      # missing discriminator must never be read as completed work
      if not outcome_tokens(read_response(jdir)):
        _reject_response(jdir, _ENVELOPE_VIOLATION_MESSAGE)
        return

      # the envelope guard above already proved a parsed response with an outcome is on disk
      # token capture is best-effort — never block DONE.
      try:
        usage = _extract_usage(stdout)
        if usage is not None:
          _append_tokens_log(repo, expert_name, usage)
      except Exception as error:  # pragma: no cover — defensive
        sys.stderr.write(f"token capture failed: {error}\n")

      # post-spawn verification splits by isolation: an isolated job is judged inside its own
      # worktree (dirty tree OR an unmoved branch = job failure, never a daemon halt — the
      # primary checkout was untouched throughout; an unmoved branch is accepted only when the
      # dispatcher allowed a commitless finish and the run reports success); a non-isolated job keeps the daemon-wide
      # dirty-tree halt, whose rationale is exactly that it shares the operator's tree. A
      # read-only agent never writes or commits, so it is exempt on both arms — an isolated
      # read-only job would otherwise always fail the unmoved-branch check.
      if not _agent_is_read_only(agent_path):
        if worktree_dir is not None:
          # an unmoved branch is excused only where a commitless finish is open and the run reports success
          allow_unmoved = commitless_ok and is_success(read_response(jdir))

          # the run is finished and its response is on disk — a failure of the tree check itself is the
          # checkout's, and must not be charged to the job by overwriting that response
          try:
            failure = _verify_isolated_job(worktree_dir, pre_spawn_tip, unmoved_ok = allow_unmoved)
          # waiver: whatever the tree check raises is re-labelled, so the pump's per-job boundary
          # leaves the finished job's response alone
          except Exception as error:  # pylint: disable=broad-exception-caught
            raise _PumpEnvironmentError(f"work tree check after the run failed: {error}") from error

          # guard: the worktree could not be read, so the check was never made — the same fault of the
          # checkout as a check that raised, and the job keeps its finished response
          if failure == _TREE_CHECK_FAILED:
            raise _PumpEnvironmentError(f"work tree check after the run failed: {failure}")

          # the isolated job broke its commit obligation — fail it, keep the queue moving
          if failure is not None:
            _write_error(jdir, JobErrorCategory.LOGICAL, failure)
            return
        # a shared-tree job settles the halt state; dirt that survives the stray-copy cleanup aborts the tick
        else:
          # the run is finished and its response is on disk — a failure of the tree check itself
          # is the checkout's, and must not be charged to the job by overwriting that response
          try:
            is_halted = _update_halt_after_run(repo, expert_name, jdir)
          # waiver: whatever the tree check raises is re-labelled, so the pump's per-job boundary
          # leaves the finished job's response alone
          except Exception as error:  # pylint: disable=broad-exception-caught
            raise _PumpEnvironmentError(f"work tree check after the run failed: {error}") from error
          if is_halted:
            raise _ExpertDirtyTreeError(expert_name, jdir.name, [])

      # the correction landed — drop the rejection record so it cannot resurface
      # in the prompt of a later attempt on this same bundle
      (jdir / JobArtifact.ERROR_JSON).unlink(missing_ok = True)
      (jdir / JobMarker.DONE).touch()
      return

    # a non-zero exit is a transient failure of this attempt
    _write_error(jdir, JobErrorCategory.TRANSIENT, f"exit={returncode} stderr={stderr[-500:]}")
  finally:
    # the worktree is removed on EVERY exit — success, failure, and exception alike; the branch
    # is the durable product, uncommitted dirt goes with the directory (operator decision)
    if mgr is not None and worktree_dir is not None:
      mgr.remove(worktree_dir)


def _persist_transcript(jdir: Path, stdout: str) -> None:
  """
  Write a run's transcript into its job bundle, reporting a failed write on stderr instead of raising.

  Args:
    jdir: Job bundle directory the transcript is written into.
    stdout: The run's captured stream-json output.
  """
  try:
    (jdir / JobArtifact.TRANSCRIPT).write_text(stdout or "", encoding = "utf-8")
  except Exception as error:  # pragma: no cover — defensive
    sys.stderr.write(f"transcript write failed: {error}\n")


def _pipe_reader(stream: IO[str], tag: str, out_q: queue.Queue) -> None:
  """
  Drain one text pipe line-by-line into a shared queue, then post an EOF sentinel.

  Args:
    stream: Text-mode pipe supplying the lines to forward.
    tag: Label attached to each queued line and to the EOF sentinel, identifying the source pipe.
    out_q: Queue receiving `(tag, line)` pairs; a final `(tag, None)` pair marks pipe closure.
  """
  try:
    # waiver: sentinel-terminated readline loop is the stdlib idiom for line streaming
    for line in iter(stream.readline, ""):
      out_q.put((tag, line))
  finally:
    out_q.put((tag, None))

    # best-effort close — the child owns the write end and may already be gone
    try:
      stream.close()
    except OSError:
      pass


def _kill_process_group(proc: subprocess.Popen) -> None:
  """
  Terminate a spawned expert's process group, escalating SIGTERM to SIGKILL.

  Args:
    proc: Process handle for the spawned expert whose process group is being torn down.
  """
  # guard: process already reaped — nothing to signal
  if proc.poll() is not None:
    return
  try:
    pgid = os.getpgid(proc.pid)
  except ProcessLookupError:
    return
  try:
    os.killpg(pgid, signal.SIGTERM)
  except ProcessLookupError:
    return
  try:
    proc.wait(timeout = _KILL_GRACE_SEC)
    return
  except subprocess.TimeoutExpired:
    pass

  # SIGTERM ignored within the grace window — force-kill the whole group
  try:
    os.killpg(pgid, signal.SIGKILL)
  except ProcessLookupError:
    pass


def _kill_pid_group(pid: int) -> bool:
  """
  Terminate the process group of a process this pump did not spawn, escalating SIGTERM to SIGKILL.

  A group the system refuses to signal, because it holds only an exited process, ends the escalation.

  Notes:
    - Signals a process group outside this process and never the caller's own group.
    - Blocks for up to two grace windows, one after SIGTERM and one after SIGKILL.

  Args:
    pid: Process identifier whose whole group is torn down.

  Returns:
    True when at least one signal reached the group, False when the process was already gone
    or sits in the pump's own group.
  """
  # guard: the process is already gone — there is no group left to signal
  try:
    pgid = os.getpgid(pid)
  except ProcessLookupError:
    return False

  # guard: never signal the pump's own group — the target is always a spawn in its own session
  if pgid == os.getpgid(0):
    return False

  # each signal gets the grace window to take effect before the next one is sent
  signalled = False
  for sig in (signal.SIGTERM, signal.SIGKILL):
    # guard: the group vanished between signals, or holds only an exited process the system refuses to signal —
    # nothing left to escalate to
    try:
      os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
      return signalled
    signalled = True

    # the grace window: poll for the process to disappear before escalating to the next signal
    deadline = time.monotonic() + _KILL_GRACE_SEC
    while time.monotonic() < deadline:
      # the process is gone — the signal did its job
      if not commit_guard.is_pid_alive(pid):
        return True
      # waiver: 0.05s is the liveness poll cadence, same floor the watchdog read loop uses
      time.sleep(0.05)
  return True


def _kill_orphaned_spawns(jdir: Path) -> int:
  """
  Terminate every process whose command line names a job directory — a spawn that outlived its pump.

  Notes:
    - Reads the host process table through `ps` and signals process groups outside this process, never the
      pump itself.
    - Blocks for up to two kill grace windows per signalled process group.

  Args:
    jdir: Absolute job directory the spawn's command line carries.

  Returns:
    The number of processes signalled; zero when none names the directory or `ps` is unavailable.
  """
  # every other process naming the job dir on its command line is one of its spawns; none is found without `ps`
  killed = 0
  for pid in commit_guard.find_spawn_pids(jdir) or []:
    if _kill_pid_group(pid):
      killed += 1
  return killed


def _spawn_with_idle_watchdog(argv: list[str],
                              *,
                              env: dict,
                              cwd: Path,
                              idle_timeout_sec: float) -> tuple[int, str, str, bool]:
  """
  Run a `claude -p` spawn under an idle-stdout watchdog.

  Kills the spawn's process group and reports a stall instead of waiting indefinitely when
  no stdout output arrives within the idle window.

  Args:
    argv: Full command line for the `claude -p` spawn.
    env: Environment variables passed to the spawned process.
    cwd: Working directory the spawn runs inside.
    idle_timeout_sec: Seconds of stdout silence tolerated before the spawn is treated as stalled.

  Returns:
    Tuple of the process exit code, captured stdout, captured stderr, and whether the spawn
    was killed for going idle on stdout past `idle_timeout_sec`.
  """
  # start_new_session gives the spawn its own process group, so a stall can be torn down
  # with os.killpg without signalling the pump itself.
  # waiver: the process must outlive this call's local scope while its pipes are polled
  # from reader threads below — a `with` block would tie its lifetime to this statement
  proc = subprocess.Popen(  # pylint: disable=consider-using-with
    argv, env = env, cwd = str(cwd),
    stdout = subprocess.PIPE, stderr = subprocess.PIPE,
    text = True, start_new_session = True, encoding = "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "replace",
  )
  line_q: queue.Queue = queue.Queue()

  # both pipes are drained on daemon threads so a full OS buffer can never deadlock the
  # read loop; the idle timer is measured on stdout only (the model's event stream).
  readers = [
    threading.Thread(target = _pipe_reader, args = (proc.stdout, "out", line_q), daemon = True),
    threading.Thread(target = _pipe_reader, args = (proc.stderr, "err", line_q), daemon = True),
  ]
  for reader in readers:
    reader.start()

  # watchdog state: stdout alone drives the idle timer, stderr only accumulates
  out_parts: list[str] = []
  err_parts: list[str] = []
  eof = { "out": False, "err": False }
  stalled = False
  last_out = time.monotonic()
  try:
    # waiver: "out"/"err" are the two fixed pipe tags used as out_q/eof dict keys — an
    # Enum would only indirect the same two literals already introduced above
    while not (eof["out"] and eof["err"]):
      idle = time.monotonic() - last_out

      # stdout silent past the idle window while still open is a freeze
      # waiver: see the "out"/"err" waiver above the enclosing while-loop
      if not eof["out"] and idle >= idle_timeout_sec:
        stalled = True
        break
      # waiver: 0.05s is a floor so the poll interval never rounds down to a busy-loop
      poll = max(0.05, min(_WATCHDOG_POLL_SEC, idle_timeout_sec - idle))
      try:
        tag, line = line_q.get(timeout = poll)
      except queue.Empty:
        continue

      # an EOF sentinel marks one pipe as drained
      if line is None:
        eof[tag] = True
        continue
      # waiver: see the "out"/"err" waiver above the enclosing while-loop
      if tag == "out":
        out_parts.append(line)
        last_out = time.monotonic()
      else:
        err_parts.append(line)

    # a stall means the child is wedged — tear down its group before reaping
    if stalled:
      _kill_process_group(proc)
  except BaseException:
    # any unexpected exit must not leave the spawn's group alive.
    _kill_process_group(proc)
    raise
  return proc.wait(), "".join(out_parts), "".join(err_parts), stalled


def _extract_response_from_stdout(stdout: str) -> dict | None:
  """
  Recover a response.json payload from the agent's stream-json transcript.

  Serves as a fallback when the agent process exits cleanly (`rc == 0`) but its `response.json` is
  missing or carries no usable outcome.

  The recovered payload is the JSON object with an `outcome` field found in the agent's assistant
  text, with the most recently emitted text preferred. None means nothing recoverable was found.

  Args:
    stdout: Raw stdout produced by a `claude -p --output-format stream-json`
      invocation.

  Returns:
    The parsed response payload as a dict, or None when no JSON object
    with an `outcome` field can be recovered from any assistant text.
  """

  # Decision: recover the response from the transcript, not treat a missing file as a transient error — an
  # agent sometimes narrates its outcome in its final message instead of writing the response file, and
  # re-dispatching the job would only repeat that roll until a run happens to write it.

  # guard: empty / whitespace-only stdout has no frames to walk
  if not stdout or not stdout.strip():
    return None
  texts: list[str] = []
  for line in stdout.splitlines():
    # waiver: the loop variable is deliberately rebound — each line is normalised in place before use
    line = line.strip()  # noqa: PLW2901

    # guard: blank line between stream frames
    if not line:
      continue
    try:
      frame = json.loads(line)
    except json.JSONDecodeError:
      continue

    # guard: frame must be a JSON object to carry assistant content
    # waiver: external Claude Code stream-json field name, not an internal key
    if not isinstance(frame, dict) or frame.get("type") != "assistant":
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    msg = frame.get("message", {})

    # guard: malformed assistant frame (missing message dict)
    if not isinstance(msg, dict):
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    content = msg.get("content", [])

    # guard: content is expected to be a list of typed blocks
    if not isinstance(content, list):
      continue
    for block in content:
      # waiver: external Claude Code stream-json field name, not an internal key
      if isinstance(block, dict) and block.get("type") == "text":
        # waiver: external Claude Code stream-json field name, not an internal key
        text = block.get("text", "")
        if isinstance(text, str) and text:
          texts.append(text)

  # guard: no assistant text frames in the transcript
  if not texts:
    return None
  decoder = json.JSONDecoder()

  # search last-emitted text first; LLMs typically describe outcome in final reply.
  for text in reversed(texts):
    idx = 0
    while idx < len(text):
      # a decode attempt starts only at an object-opening character
      if text[idx] != "{":
        idx += 1
        continue
      try:
        obj, _end = decoder.raw_decode(text, idx)
      except json.JSONDecodeError:
        idx += 1
        continue
      if isinstance(obj, dict) and JobResponseKey.OUTCOME in obj:
        return obj
      idx += 1
  return None


def _extract_usage(stdout: str) -> dict | None:
  """
  Extract token-usage totals from a `claude -p` stdout buffer.

  Reports the model that answered and the run's final token totals, whether stdout is a stream
  of frames or a single JSON object.

  Args:
    stdout: Raw stdout produced by a `claude -p --output-format stream-json` invocation.

  Returns:
    A dict with keys `model`, `input_tokens`, `output_tokens`, `cache_read`, and `cache_write`,
    or None when no parseable usage frame is present.
  """
  # guard: empty or whitespace-only stdout has no frames to parse
  if not stdout or not stdout.strip():
    return None

  # defaults that survive a buffer carrying frames but no usage
  model = "unknown"
  final_usage: dict | None = None

  # try line-by-line first (stream-json), then whole-buffer (single json).
  candidates: list[str] = []
  for line in stdout.splitlines():
    # waiver: the loop variable is deliberately rebound — each line is normalised in place before use
    line = line.strip()  # noqa: PLW2901
    if line:
      candidates.append(line)

  # guard: nothing non-empty in stdout to parse
  if not candidates:
    return None

  # keep the last model seen and the final result frame's usage
  parsed_any = False
  for raw in candidates:
    try:
      frame = json.loads(raw)
    except json.JSONDecodeError:
      continue
    parsed_any = True

    # guard: frame must be a JSON object to carry usage/model
    if not isinstance(frame, dict):
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    msg = frame.get("message")
    # waiver: external Claude Code stream-json field name, not an internal key
    if isinstance(msg, dict) and msg.get("model"):
      # waiver: external Claude Code stream-json field name, not an internal key
      model = str(msg["model"])
    # waiver: external Claude Code stream-json field name, not an internal key
    if frame.get("type") == "result" and isinstance(frame.get("usage"), dict):
      # waiver: external Claude Code stream-json field name, not an internal key
      final_usage = frame["usage"]

  # fallback: stdout was a single JSON object (whole buffer parses).
  if final_usage is None and not parsed_any:
    try:
      frame = json.loads(stdout)
      # waiver: external Claude Code stream-json field name, not an internal key
      if isinstance(frame, dict) and isinstance(frame.get("usage"), dict):
        # waiver: external Claude Code stream-json field name, not an internal key
        final_usage = frame["usage"]
    except json.JSONDecodeError:
      return None

  # guard: no usage frame found in either parsing strategy
  if final_usage is None:
    return None

  # normalize the provider's usage frame into the flat record the tokens log stores
  return {
    "model": model,
    # waiver: external Anthropic usage field name, not an internal key
    "input_tokens": int(final_usage.get("input_tokens", 0) or 0),
    # waiver: external Anthropic usage field name, not an internal key
    "output_tokens": int(final_usage.get("output_tokens", 0) or 0),
    # waiver: external Anthropic usage field name, not an internal key
    "cache_read": int(final_usage.get("cache_read_input_tokens", 0) or 0),
    # waiver: external Anthropic usage field name, not an internal key
    "cache_write": int(final_usage.get("cache_creation_input_tokens", 0) or 0),
  }


def _append_tokens_log(repo: Path, expert_name: str, usage: dict) -> None:
  """
  Append a single token-usage record to the runtime tokens log.

  The record is written under `.logs/lazy-core/runtime/tokens.jsonl` as a JSON line.
  The routine label is fixed to `expert-pump` because token capture is internal to
  the pump — only routines that actually invoke `claude -p` produce these records.

  Args:
    repo: Repository root whose log directory receives the record.
    expert_name: Name of the expert that produced the usage.
    usage: Usage dict as returned by `_extract_usage`.
  """
  # waiver: filesystem path idiom, not a domain constant
  log_dir = repo / ".logs/lazy-core/runtime"
  log_dir.mkdir(parents = True, exist_ok = True)
  record = {
    "ts": time.time(),
    "routine": "expert-pump",
    "expert": expert_name,
    **usage,
  }
  # waiver: filesystem path and stdlib open-mode idioms, not domain constants
  with (log_dir / "tokens.jsonl").open("a", encoding = "utf-8") as handle:
    handle.write(json.dumps(record) + "\n")


def _append_stream_stall_log(repo: Path, expert_name: str, jdir: Path, attempt: int, idle_sec: float) -> None:
  """
  Append a single stream-idle-stall record to the runtime log.

  Args:
    repo: Repository root whose log directory receives the record.
    expert_name: Name of the expert whose spawn stalled.
    jdir: Path to the job directory being processed when the stall occurred.
    attempt: One-based count of the spawn attempt that stalled.
    idle_sec: Seconds of stdout silence that triggered the stall.
  """
  # waiver: filesystem path idiom, not a domain constant
  log_dir = repo / ".logs/lazy-core/runtime"
  log_dir.mkdir(parents = True, exist_ok = True)
  record = {
    "ts": time.time(),
    "routine": "expert-pump",
    "expert": expert_name,
    "job_id": jdir.name,
    "attempt": attempt,
    "idle_sec": idle_sec,
  }
  # waiver: filesystem path and stdlib open-mode idioms, not domain constants
  with (log_dir / "stream-stalls.jsonl").open("a", encoding = "utf-8") as handle:
    handle.write(json.dumps(record) + "\n")


def _classify_finished(jdir: Path) -> str:
  """
  Classify a DONE-marked job directory into its job-log outcome token.

  Args:
    jdir: Path to the job directory carrying a DONE marker.

  Returns:
    `JobLogOutcome.DONE` when `response.json` reports a finished outcome,
    `JobLogOutcome.DEFERRED` when it reports postponed work, and
    `JobLogOutcome.FAILED` otherwise — including when the response is missing,
    malformed, or omits its outcome.
  """
  # the job log feeds the dashboard counters, so an unproven success is logged as a
  # failure and postponed work gets its own bucket instead of hiding inside done
  status = classify_response(read_response(jdir))
  if status == JobStatus.DEFERRED:
    return JobLogOutcome.DEFERRED
  return JobLogOutcome.DONE if status == JobStatus.DONE else JobLogOutcome.FAILED


def _append_jobs_log(repo: Path,
                     expert_name: str,
                     job_id: str,
                     outcome: str,
                     *,
                     duration_sec: float | None = None) -> None:
  """
  Append a single job-attempt record to the runtime job log.

  The record is written under `.logs/lazy-core/runtime/jobs.jsonl` as a JSON line.
  The metrics module folds these records into the per-expert job counters on scrape.
  Best-effort — a write failure is reported to stderr and never raised to the caller.

  Args:
    repo: Repository root whose log directory receives the record.
    expert_name: Name of the expert that owns the job.
    job_id: Identifier of the job directory the attempt ran in.
    outcome: One of the `JobLogOutcome` tokens.
    duration_sec: Wall-clock duration of the attempt, when the caller measured one.
  """
  record: dict = {
    "ts": time.time(),
    "expert": expert_name,
    "job_id": job_id,
    "outcome": outcome,
  }
  if duration_sec is not None:
    # waiver: external job-log JSON field name and millisecond rounding precision, not internal keys
    record["duration_sec"] = round(duration_sec, 3)
  try:
    # waiver: filesystem path idiom, not a domain constant
    log_dir = repo / ".logs/lazy-core/runtime"
    log_dir.mkdir(parents = True, exist_ok = True)
    # waiver: filesystem path idiom, not a domain constant
    # waiver: stdlib idiom, not a domain constant
    with (log_dir / "jobs.jsonl").open("a", encoding = "utf-8") as handle:
      handle.write(json.dumps(record) + "\n")
  except Exception as error:  # pragma: no cover — defensive
    sys.stderr.write(f"job log append failed: {error}\n")


def _log_job_attempt(repo: Path, expert_name: str, jdir: Path, started_monotonic: float) -> None:
  """
  Record the outcome of one job-processing attempt in the runtime job log.

  Classifies the job directory as it stands after the attempt: a DONE marker maps to
  done/failed via the response outcome; anything else is an attempt-level error that
  leaves the job queued for retry. Best-effort — a logging failure never affects the tick.

  Args:
    repo: Repository root whose log directory receives the record.
    expert_name: Name of the expert that owns the job.
    jdir: Path to the job directory the attempt ran in.
    started_monotonic: `time.monotonic()` timestamp taken just before the attempt.
  """
  try:
    outcome = JobLogOutcome.ERROR
    if (jdir / JobMarker.DONE).exists():
      outcome = _classify_finished(jdir)
    _append_jobs_log(
      repo, expert_name, jdir.name, outcome,
      duration_sec = time.monotonic() - started_monotonic,
    )
  except Exception as error:  # pragma: no cover — defensive
    sys.stderr.write(f"job log append failed: {error}\n")


def _reject_response(jdir: Path, message: str) -> None:
  """
  Reject a finished attempt whose response violated the envelope.

  The first rejection of a bundle keeps the job queued: the unusable response is
  removed and the claim released so the job re-queues as though never claimed, and the
  reason is recorded beside the bundle so the next spawn is told what was wrong with the
  last one. A repeat rejection means the fault reproduces regardless of the run, so the
  job is failed for good through the same error path as any other logical failure and
  the incident is opened for an operator.

  Args:
    jdir: Path to the job directory whose attempt is being rejected.
    message: Human-readable reason handed back to the expert and recorded with
      the incident.
  """

  # Domain(runtime.job-execution):
  # # Envelope-violation retry policy
  # A response that violates the outcome envelope gets exactly one corrective re-spawn before
  # the job is failed for good. One retry is enough to separate an ordinary bad roll on a
  # single run from a fault the expert reproduces regardless of the run, and no amount of
  # further retrying would ever fix the second case — it would only spend more model calls
  # to fail the same way again.

  # the counter was bumped before this attempt started, so it counts attempts so far
  try:
    attempts = int((jdir / JobArtifact.ATTEMPTS).read_text(encoding = "utf-8").strip())
  except (OSError, ValueError):
    attempts = 0

  # guard: the retry budget is spent — a reproducing violation is the expert's contract,
  # not a bad roll, and another spawn would only burn a model call to fail identically
  if attempts > _ENVELOPE_RETRY_LIMIT:
    _write_error(jdir, JobErrorCategory.LOGICAL, message)
    return

  # the rejection is recorded for the corrective prompt of the next attempt
  # waiver: per-attempt rejection record read back by the prompt composer, not a shared key
  (jdir / JobArtifact.ERROR_JSON).write_text(json.dumps({
    JobResponseKey.CATEGORY: JobErrorCategory.LOGICAL,
    JobResponseKey.MESSAGE: message,
    "attempt": attempts,
  }, indent = 2), encoding = "utf-8")

  # drop the unusable payload and release the claim: READY survives without DONE,
  # so the next pump tick re-picks this same bundle
  (jdir / JobFile.RESPONSE).unlink(missing_ok = True)
  (jdir / JobMarker.PID).unlink(missing_ok = True)


def _spend_transient_budget(jdir: Path) -> bool:
  """
  Spend one unit of the job's transient-retry budget and report what remains.

  Every call advances the persisted counter — calling twice spends two units, so the
  caller invokes it exactly once per recorded transient failure.

  Args:
    jdir: Path to the job directory whose counter is read and advanced.

  Returns:
    True while the bundle's transient-error count stays below the configured budget
    (`daemon.transient_max_retries`, default 5), False once the budget is exhausted.
  """

  # Domain(runtime.job-execution):
  # # Transient-failure retry budget
  # A transient failure — one caused by the environment rather than the work itself — is
  # allowed to recur a bounded number of times before a bundle is finally closed as failed.
  # Every recorded transient failure spends one unit of the budget regardless of what caused
  # it, so a bundle that keeps hitting different transient problems exhausts the same budget
  # as one hitting the same problem repeatedly; the count exists to stop a storm of retries,
  # not to distinguish one transient cause from another.

  # read the persisted counter; a missing or garbled file restarts the budget from zero,
  # which errs toward retrying — the cap exists to stop storms, not to lose work
  counter = jdir / JobArtifact.TRANSIENT_ERRORS
  try:
    count = int(counter.read_text(encoding = "utf-8").strip())
  except (OSError, ValueError):
    count = 0
  count += 1
  counter.write_text(f"{count}\n", encoding = "utf-8")

  # the repo root is fixed by the queue layout: <repo>/.experts/.jobs/<expert>/<job>
  daemon = load_section(jdir.parents[3] / SettingsFile.REL, SettingsKey.DAEMON)
  # waiver: inline numeric literal — the shipped default budget (5), overridable in settings
  return count < int(daemon.get(DaemonKey.TRANSIENT_MAX_RETRIES, 5))


def _write_error(jdir: Path, category: str, message: str) -> None:
  """
  Write an error outcome to the job, closing it unless a transient retry is still due.

  A transient failure with budget left releases the job's claim and leaves the bundle in the
  documented READY+ERROR state — `DONE` untouched, so dead-claimant reconciliation cannot
  finalize it while a retry is due — and the next pump tick retries it as an unclaimed job,
  until the bundle's transient budget (`daemon.transient_max_retries`) runs out and the job
  closes like any other error. Every path records the ledger incident.

  Args:
    jdir: Path to the job directory whose response.json is being written.
    category: Error category label persisted in the response payload.
    message: Human-readable error message persisted alongside the category.
  """
  (jdir / JobFile.RESPONSE).write_text(json.dumps({
    JobResponseKey.OUTCOME: JobOutcome.ERROR,
    JobResponseKey.ERROR: { JobResponseKey.CATEGORY: category, JobResponseKey.MESSAGE: message },
  }, indent = 2), encoding = "utf-8")

  # a transient failure with budget left stays claimable — READY+ERROR, no DONE;
  # everything else (logical, uncommitted, exhausted budget) closes the job
  if category == JobErrorCategory.TRANSIENT and _spend_transient_budget(jdir):
    # release the claim: with the dead claimant's PID gone the bundle is queued again, so the
    # dead-scan's "response present" reconciliation cannot finalize it out of its retry
    (jdir / JobMarker.PID).unlink(missing_ok = True)
    sys.stderr.write(
      f"transient error on {jdir.parent.name}/{jdir.name} — left queued for retry\n")
  else:
    (jdir / JobMarker.DONE).touch()

  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric/default literal, not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.JOB_ERROR, IncidentKey.CAUSE: category, IncidentKey.ACTOR: IncidentActor.PUMP,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name, IncidentKey.DETAIL: message[:200],
    IncidentKey.REFS: { "jdir": str(jdir), "response": str(jdir / JobFile.RESPONSE) },
  })
