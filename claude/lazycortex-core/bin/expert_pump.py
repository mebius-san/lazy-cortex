"""
Implementation of `lazycortex-core expert-pump-once` subcommand.

Drives one pump tick of the expert-job queue: cleans up expired job
directories, marks stuck jobs as dead, and dispatches at most one READY
job to a `claude -p` subprocess. The routine-level timeout the daemon
applies to `lazy-expert.pump` is the only ceiling on a single Claude
spawn — pump never runs more than one spawn per invocation.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import error_ledger
import runtime_state
from lazy_settings import load_section
# waiver: ReferenceError is reference_resolver's domain exception, not the builtin
from reference_resolver import resolve, ReferenceError  # pylint: disable=redefined-builtin
# Hoisted from inside `_check_post_claude` (Bug 113): the deferred import inside the
# function was firing every job, and when a sibling editor flushed an update to
# `constants.py` (e.g. adding a new key like `DaemonKey`) the cached `constants` module
# in the long-running pump subprocess pointed at V1 while the on-disk file was V2 —
# `runtime_daemon`'s top-level `from constants import …` then exploded with
# `ImportError: cannot import name X from constants`. Binding the import at module load
# means the lookup happens ONCE per process lifetime, not per job.
from runtime_daemon import _check_working_tree
from job_response import classify_response, outcome_tokens, read_response
from worktree_tasks import WorktreeStartError, WorktreeTaskManager
import rate_limit_flag
from constants import (
  DaemonKey, EnvVar, GitConfigKey, HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  IncidentState, JobArtifact, JobConfigKey, JobErrorCategory, JobFile, JobIODir, JobLogOutcome, JobMarker,
  JobOutcome, JobRequestKey, JobResponseKey, JobStatus, RateLimitGuardKey, RateLimitRecordKey, RuntimeFile,
  SettingsFile, SettingsKey, WorkspaceMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import IO


JOBS_BASE = ".experts/.jobs"

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
# Rejection text handed back to the expert on its corrective re-spawn and recorded as the
# incident detail when the retry budget is spent.
_ENVELOPE_VIOLATION_MESSAGE = (
  "response.json carries no `outcome` field. The response envelope (`outcome`, `error`, "
  "`result`) belongs to the expert-runtime contract; a protocol may add fields and define "
  "the values `outcome` takes, but never replace it with a status field of its own."
)


def _pid_alive(pid: int) -> bool:
  """
  Return whether the given process is currently alive.

  Args:
    pid: Numeric OS process identifier to probe.

  Returns:
    True if a process with that PID exists (or the caller lacks permission to signal it),
    False if the PID is invalid or the process is gone.
  """
  # guard: non-positive PID is never a real process
  if pid <= 0:
    return False
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  except OSError:
    return False
  return True


_DEAD_JSON_INTERNAL_FILES = {
  JobMarker.READY, JobMarker.PID, JobFile.REQUEST, JobMarker.DEAD, JobMarker.DEAD_CANDIDATE,
  JobArtifact.DEAD_JSON,
}
# Job-liveness classification thresholds (seconds): a job that died faster than
# _STARTUP_CRASH_SEC with no output likely crashed at startup; one alive longer
# than _HUNG_JOB_SEC with no output was likely hung or killed.
_STARTUP_CRASH_SEC = 5
_HUNG_JOB_SEC = 3600


def _build_dead_json(jdir: Path, expert: str, job_id: str, marked_at: float) -> dict:
  """
  Compose the forensic payload describing a job that was marked dead.

  Args:
    jdir: Path to the job directory whose state is being captured.
    expert: Name of the expert that owned the job.
    job_id: Identifier of the job within the expert's queue.
    marked_at: Wall-clock timestamp at which the job was marked dead.

  Returns:
    A dict carrying queue and claim timestamps, the original PID, an optional dedup key,
    the list of partial output files, and a heuristic likely-cause label.
  """
  queued_at = (jdir / JobMarker.READY).stat().st_mtime
  claimed_at = (jdir / JobMarker.PID).stat().st_mtime

  # the claimant PID as recorded at claim time; -1 when the marker is gone or garbled
  try:
    original_pid = int((jdir / JobMarker.PID).read_text().strip())
  except (OSError, ValueError):
    original_pid = -1

  # carry the dedup key forward so a re-dispatch can be matched against this death
  dedup_key = None
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text())
    dedup_key = request.get(JobRequestKey.DEDUP_KEY)
  except (OSError, json.JSONDecodeError, KeyError):
    pass

  # collect names of files the expert produced before dying — excludes runtime bookkeeping files
  partial_output = sorted(
    p.name for p in jdir.iterdir()
    if p.name not in _DEAD_JSON_INTERNAL_FILES
  )

  # time the claimant survived after claiming, floored at zero against clock skew
  duration_alive_sec = max(0.0, marked_at - claimed_at)

  # classify by duration + output presence — informative label, not a contract
  if duration_alive_sec < _STARTUP_CRASH_SEC and not partial_output:
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
    "duration_queued_sec": max(0.0, claimed_at - queued_at),
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


def _detect_dead_jobs(repo: Path, *, grace_sec: float = 0.0) -> int:
  """
  Reconcile claimed jobs across the queue whose claimant process is no longer alive.

  Treats a claimed job that already has a response as finished rather than dead, and
  applies a grace window before declaring a truly unresponsive job dead so a slow
  response has time to land.

  Notes:
    - Records a `job_dead` incident in the error ledger for each job newly marked dead.

  Args:
    repo: Repository root containing the expert job tree.
    grace_sec: Minimum flagged time before a stuck job is declared dead; zero applies
      the dead verdict on first sighting.

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
    for jdir in edir.iterdir():
      # guard: skip non-directory entries
      if not jdir.is_dir():
        continue
      # guard: job never reached READY — still being assembled
      if not (jdir / JobMarker.READY).exists():
        continue
      # guard: job already DONE — terminal state reached
      if (jdir / JobMarker.DONE).exists():
        continue
      # guard: job already DEAD — skip to keep idempotent
      if (jdir / JobMarker.DEAD).exists():
        continue
      # guard: job CANCELLED — the operator killed its executor deliberately; not a death
      if (jdir / JobMarker.CANCELLED).exists():
        continue
      # guard: no PID file — job is queued, not claimed
      if not (jdir / JobMarker.PID).exists():
        continue

      # an unreadable or garbled PID marker reads the same as a claimant that is gone
      try:
        pid_text = (jdir / JobMarker.PID).read_text().strip()
        pid = int(pid_text)
        alive = _pid_alive(pid)
      except (OSError, ValueError):
        alive = False

      # the candidate marker records when this job was first seen unclaimed
      candidate = jdir / JobMarker.DEAD_CANDIDATE
      # guard: claimant process is still running — leave the job alone
      if alive:
        # A live claimant means the job was re-claimed after the earlier sighting;
        # a stale marker must not shortcut the grace window on a later scan.
        candidate.unlink(missing_ok = True)
        continue
      # guard: claimant died after the expert finished — finalize instead of marking dead
      if (jdir / JobFile.RESPONSE).exists():
        _finalize_orphaned_job(jdir)
        _append_jobs_log(repo, edir.name, jdir.name, _classify_finished(jdir))
        continue
      # guard: first sighting — open the grace window instead of marking dead
      if grace_sec > 0 and not candidate.exists():
        candidate.touch()
        continue
      # guard: grace window still open — give a surviving subprocess time to respond
      if grace_sec > 0 and time.time() - candidate.stat().st_mtime < grace_sec:
        continue

      # the dead record is composed before the last-moment response check below
      blob = _build_dead_json(jdir, edir.name, jdir.name, time.time())
      # guard: response landed during this scan — finalize instead of marking dead
      if (jdir / JobFile.RESPONSE).exists():
        _finalize_orphaned_job(jdir)
        _append_jobs_log(repo, edir.name, jdir.name, _classify_finished(jdir))
        continue
      candidate.unlink(missing_ok = True)
      (jdir / JobArtifact.DEAD_JSON).write_text(json.dumps(blob, indent = 2))
      (jdir / JobMarker.DEAD).touch()
      _append_jobs_log(repo, edir.name, jdir.name, JobLogOutcome.DEAD)
      # waiver: small internal subkey, not a reusable domain key
      cause = blob.get("likely_cause", "unknown")
      error_ledger.record(repo, {
        IncidentKey.INCIDENT: f"job:{edir.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
        IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: cause, IncidentKey.ACTOR: IncidentActor.PUMP,
        IncidentKey.EXPERT: edir.name, IncidentKey.JOB_ID: jdir.name, IncidentKey.DETAIL: f"job DEAD: {cause}",
        IncidentKey.REFS: { "jdir": str(jdir), "dead_json": str(jdir / JobArtifact.DEAD_JSON) },
      })
      marked += 1

  # the tick summary carries this count so a checkout burying jobs every tick is visible in
  # the daemon log without reading the job tree
  return marked


class _ExpertLeftDirtyTree(Exception):
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
    super().__init__(f"expert {expert!r} left dirty tree at job {job_id!r}")
    self.expert = expert
    self.job_id = job_id
    self.dirty_paths = dirty_paths


_READ_ONLY_TOOLS = frozenset({
  "Read", "Grep", "Glob",
  "WebFetch", "WebSearch",
  "BashOutput",
  "ListMcpResourcesTool", "ReadMcpResourceTool",
})


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
  and lists only members of the known read-only tool set. When the field is absent
  or includes any write-capable tool, the agent is treated as write-capable so the
  post-Claude dirty-tree check applies to its runs.

  Args:
    agent_path: Path to the agent definition file.

  Returns:
    True only when every declared tool is in the known read-only set; False otherwise.
  """
  try:
    text = agent_path.read_text()
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
    # guard: not the tools field — keep scanning
    # waiver: external Claude Code stream-json field name, not an internal key
    if not line.startswith("tools:"):
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    value = line[len("tools:"):].strip()
    # guard: tools field present but empty — treat as write-capable
    if not value:
      return False
    tools = { t.strip() for t in value.split(",") if t.strip() }
    return bool(tools) and tools.issubset(_READ_ONLY_TOOLS)
  return False


def _check_post_claude(repo: Path, expert_name: str, jdir: Path) -> bool:
  """
  Verify that the working tree is clean after a successful expert run.

  When the working tree is dirty the job's response.json is overwritten with an
  error outcome, the job is marked DONE, and a daemon-wide halt block is written
  to runtime state with full attribution so subsequent ticks stop processing.

  Args:
    repo: Repository root in which the expert ran.
    expert_name: Name of the expert whose run is being checked.
    jdir: Path to the job directory whose state is being finalised.

  Returns:
    True when the working tree was dirty (caller is expected to raise the halt exception),
    False when the tree was clean.
  """
  dirty = _check_working_tree(repo)
  # guard: working tree is clean — nothing to do
  if dirty is None:
    return False
  (jdir / JobFile.RESPONSE).write_text(json.dumps({
    JobResponseKey.OUTCOME: JobOutcome.ERROR,
    JobResponseKey.ERROR: {
      JobResponseKey.CATEGORY: JobErrorCategory.UNCOMMITTED_CHANGES,
      JobResponseKey.MESSAGE: "expert left uncommitted changes after exit",
      HaltKey.DIRTY_PATHS: dirty,
    },
  }, indent = 2))
  (jdir / JobMarker.DONE).touch()
  runtime_state.set_halted(repo, {
    HaltKey.HALTED_SINCE: time.time(),
    HaltKey.TRIGGERED_BY: "lazy-expert.pump",
    HaltKey.REASON: HaltReason.UNCOMMITTED_CHANGES,
    HaltKey.DIRTY_PATHS: dirty,
    IncidentKey.EXPERT: expert_name,
    IncidentKey.JOB_ID: jdir.name,
  })
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


def _worktree_head(wt: Path) -> str | None:
  """
  Return the commit the worktree's HEAD points at.

  Args:
    wt: Path to the worktree directory.

  Returns:
    The full commit hash, or None when it cannot be resolved.
  """
  head = subprocess.run(
    # waiver: git CLI vocabulary, not a domain constant
    [ "git", "rev-parse", "HEAD" ], cwd = str(wt), capture_output = True, text = True, check = False,
  )
  # guard: an unresolvable HEAD carries no comparable tip
  if head.returncode != 0:
    return None
  return head.stdout.strip()


def _isolated_job_failure(wt: Path, pre_spawn_tip: str | None) -> str | None:
  """
  Check an isolated job's worktree after a clean spawn: dirty tree or an unmoved branch fails it.

  A job failure, never a daemon halt — the primary checkout was untouched throughout, so the
  daemon-wide dirty-tree halt's rationale does not apply here. The unmoved-branch check compares
  against the tip captured before the spawn, so a continuation round that produced nothing is
  caught even though the branch already carried earlier rounds' commits.

  Args:
    wt: Path to the job's worktree directory.
    pre_spawn_tip: The branch tip captured before the spawn, or None when it was unresolvable.

  Returns:
    None when the worktree is clean and the branch moved, else a one-line failure text.
  """
  status = subprocess.run(
    # waiver: git CLI vocabulary, not a domain constant
    [ "git", "status", "--porcelain" ], cwd = str(wt), capture_output = True, text = True, check = False,
  )
  # guard: the expert left uncommitted changes in its worktree — the commit obligation was broken
  if status.stdout.strip():
    return f"isolated job left the worktree dirty: {status.stdout.strip()[:300]}"
  # guard: a clean tree with the tip exactly where the spawn found it means nothing durable landed
  if pre_spawn_tip is not None and _worktree_head(wt) == pre_spawn_tip:
    # waiver: one-off human-facing message
    return "isolated job finished with no new commits and a clean tree"
  return None


def _isolation_prompt(branch: str, branch_created: bool) -> str:
  """
  Compose the commit-obligation paragraph for a spawn running in an isolated worktree.

  Args:
    branch: The job's branch, named so the agent knows where its work lands.
    branch_created: Whether this dispatch created the branch (fresh) or reuses it (resume).

  Returns:
    The paragraph to append to the user prompt.
  """
  if branch_created:
    return (
      f"You are working in an isolated git worktree on branch `{branch}`. Commit ALL your work "
      "to this branch before writing response.json — the worktree is removed after the job, and "
      "only committed work survives. An uncommitted or empty result fails the job."
    )
  return (
    f"You are working in an isolated git worktree on branch `{branch}`, which already carries "
    "commits from an earlier round of this job — this is a continuation. Build on them, never "
    "reset or rewrite them. Commit ALL new work before writing response.json — the worktree is "
    "removed after the job, and only committed work survives."
  )


def pump(repo: Path) -> dict:
  """
  Run one pump tick over the expert-job queue.

  Each tick garbage-collects expired job directories and marks jobs whose claimant process
  has died, then handles at most one READY job: it processes the oldest READY job across
  all expert directories, or defers without spawning anything when a job is waiting and the
  host's rate-limit guard has flagged the account. The single-spawn ceiling matters because
  the daemon's per-routine timeout is the only bound on a Claude subprocess.

  Args:
    repo: Repository root containing the expert job tree.

  Returns:
    A summary dict with counts of experts seen, jobs processed, jobs cleaned, and jobs newly
    marked dead. On a deferred tick, adds `deferred` (True) and `resets_at` (the epoch-seconds
    timestamp when the rate limit reopens) instead of processing a job. When a halt fires
    instead, adds the offending expert and job_id.
  """
  repo = Path(repo)
  settings_path = repo / SettingsFile.REL
  daemon = load_section(settings_path, SettingsKey.DAEMON)
  # waiver: small internal subkey, not a reusable domain key
  cleanup_done_after  = _parse_duration(daemon.get("cleanup_completed_after", "7d"))
  # waiver: small internal subkey, not a reusable domain key
  cleanup_fail_after  = _parse_duration(daemon.get("cleanup_failed_after",   "30d"))
  # waiver: small internal subkey, not a reusable domain key
  cleanup_dead_after  = _parse_duration(daemon.get("cleanup_dead_after",     "7d"))
  detected_dead = _detect_dead_jobs(repo, grace_sec = _DEAD_GRACE_SEC)

  # the queue root only appears once something has been dispatched
  jobs_root = repo / JOBS_BASE
  # guard: no jobs tree on disk yet — return early summary
  if not jobs_root.exists():
    return { "experts": 0, "processed": 0, "cleaned": 0, "detected_dead": detected_dead }

  # per-tick counters the daemon folds into its metrics
  processed = cleaned = expert_count = 0
  # Bug 118: previous loop processed the first READY job in alphabetical order of
  # expert directories (`designer` < `historian` < `interpreter` < `planner` <
  # `planner-2` < `spec.request-router` < `spec.request-apply`). Sibling fixtures
  # continuously enqueueing main-writer / validator jobs starved terminal-barrier
  # writers indefinitely (RUN 6 observed `spec.request-router` waiting 21 minutes).
  # Fix: collect ALL READY jobs across every expert dir in one pass, then pick the
  # oldest by READY-marker mtime. Plain FIFO fairness across the whole queue.
  ready_candidates: list[tuple[float, str, Path]] = []
  for edir in sorted(jobs_root.iterdir()):
    # guard: skip stray files mixed in beside expert directories
    if not edir.is_dir():
      continue
    expert_count += 1
    name = edir.name
    for jdir in sorted(edir.iterdir()):
      # guard: skip non-directory entries
      if not jdir.is_dir():
        continue
      cleaned += _maybe_cleanup(jdir, cleanup_done_after, cleanup_fail_after, cleanup_dead_after)
      ready_marker = jdir / JobMarker.READY
      ready = (
        ready_marker.exists()
        and not (jdir / JobMarker.DONE).exists()
        and not (jdir / JobMarker.DEAD).exists()
        and not (jdir / JobMarker.CANCELLED).exists()
      )
      # guard: only collect actually-ready jobs into the FIFO queue
      if not ready:
        continue
      ready_candidates.append((ready_marker.stat().st_mtime, name, jdir))
  # process the oldest ready job, if any surfaced above
  if ready_candidates:

    # Decision: the rate-limit check lives here, in the pump, not inside `_process_one` — down
    # there the PID marker is already written and `attempts` already incremented, so a deferred
    # job would be marked DEAD two scans later and would fatten `jobs.jsonl` with an error line
    # every polling interval. Standing before the spawn also covers a second checkout on this
    # host, the window between a halt clearing and the next spawn, and a halt an operator lifted
    # early via `/lazy-runtime.recover`.

    # resolve the guard's effective triggers for this repository
    guard = rate_limit_flag.config(daemon)
    # one listing answers both questions — a record expiring between two reads would otherwise
    # report a deferral with no reopening time attached
    raised = rate_limit_flag.live() if guard[RateLimitGuardKey.ENABLED] else []
    # guard: the subscription window is closed — postpone rather than burn the call
    if raised:
      # waiver: pump-summary subkeys, mirroring the sibling `halted` summary below
      return {
        "experts": expert_count, "processed": 0, "cleaned": cleaned,
        "detected_dead": detected_dead, "deferred": True,
        RateLimitRecordKey.RESETS_AT: max(float(e[RateLimitRecordKey.RESETS_AT]) for e in raised),
      }

    # plain FIFO across the whole queue — oldest READY marker wins
    ready_candidates.sort(key = lambda t: t[0])
    _mtime, name, jdir = ready_candidates[0]
    started = time.monotonic()
    try:
      _process_one(repo, name, jdir)
      processed = 1
      _log_job_attempt(repo, name, jdir, started)
    except _ExpertLeftDirtyTree as e:
      processed = 1
      _log_job_attempt(repo, name, jdir, started)
      return {
        "experts": expert_count, "processed": processed,
        "cleaned": cleaned, "detected_dead": detected_dead, "halted": True,
        "halt_expert": e.expert, "halt_job_id": e.job_id,
      }

    # The pre-spawn check found the flag clear, so a flag up now went up during this run — by this
    # run's own frames or a concurrent writer on the host; either way the window is closed. Halt
    # the daemon until it reopens. The current job was never interrupted for it.
    if guard[RateLimitGuardKey.ENABLED] and _halt_on_rate_limit(repo, name, jdir):
      # waiver: pump-summary subkeys, mirroring the sibling dirty-tree halt summary above
      return {
        "experts": expert_count, "processed": processed, "cleaned": cleaned,
        "detected_dead": detected_dead, "halted": True, "halt_reason": HaltReason.RATE_LIMIT,
        "halt_expert": name, "halt_job_id": jdir.name,
      }
  return { "experts": expert_count, "processed": processed, "cleaned": cleaned, "detected_dead": detected_dead }


def _halt_on_rate_limit(repo: Path, expert_name: str, jdir: Path) -> bool:
  """
  Raise the rate-limit daemon halt when the host-local flag is up after a job's run.

  A halt already standing — for example an unresolved dirty-tree halt — is never overwritten:
  it carries its own reason the operator still has to see. The halt opens the daemon-halt
  incident so `/error-list` reflects the stop, mirroring the automatic clear on the other side.

  Args:
    repo: Repository root whose daemon is halted.
    expert_name: Name of the expert whose run raised the flag, recorded on the incident.
    jdir: Path to the job directory of that run.

  Returns:
    True when the halt was raised by this call; False when the flag is down or a halt stood.
  """
  raised = rate_limit_flag.live()
  # guard: the flag is not up — nothing this run has to act on
  if not raised:
    return False
  # guard: a standing halt keeps its own reason; the flag alone still defers every next tick
  if runtime_state.get_halted(repo) is not None:
    return False
  resets = max(float(e[RateLimitRecordKey.RESETS_AT]) for e in raised)
  runtime_state.set_halted(repo, {
    HaltKey.HALTED_SINCE: time.time(),
    HaltKey.TRIGGERED_BY: "lazy-expert.pump",
    HaltKey.REASON: HaltReason.RATE_LIMIT,
    HaltKey.RESETS_AT: resets,
    IncidentKey.EXPERT: expert_name,
    IncidentKey.JOB_ID: jdir.name,
  })
  # human-facing detail line — the machine-readable epoch stays on the halt block
  reopens = datetime.fromtimestamp(resets, tz = UTC).strftime("%Y-%m-%d %H:%M UTC")
  # the loud line: the routine's stderr reaches the daemon journal's stderr_tail and the
  # operator's terminal — a multi-hour stop must never be discoverable only via state.json
  sys.stderr.write(
      f"DAEMON HALTED (rate limit): expert {expert_name} job {jdir.name} — "
      f"no routine runs until {reopens}; /lazy-runtime.recover lifts it early\n")
  error_ledger.record(repo, {
    IncidentKey.INCIDENT: f"halt:{repo.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.DAEMON_HALT,
    IncidentKey.CAUSE: HaltReason.RATE_LIMIT, IncidentKey.ACTOR: "lazy-expert.pump",
    IncidentKey.EXPERT: expert_name, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.DETAIL: f"rate-limit window closed until {reopens}",
  })
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
  frames = rate_limit_flag.frames(stdout or "")
  # guard: the run carried no rate-limit signal to act on
  if not frames:
    return 0
  cfg = rate_limit_flag.config(load_section(repo / SettingsFile.REL, SettingsKey.DAEMON))
  # guard: the guard is switched off in this repository — frames are counted, never acted on
  if not cfg[RateLimitGuardKey.ENABLED]:
    return len(frames)
  for info in frames:
    trigger = rate_limit_flag.triggered(info, cfg)
    # guard: this frame reports a healthy window
    if trigger is None:
      continue
    try:
      rate_limit_flag.record(info, trigger, writer = f"expert-pump:{expert_name}")
    except OSError as e:
      sys.stderr.write(f"rate-limit guard: cannot write flag: {e}\n")
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
    record = json.loads(record_path.read_text())
  except (OSError, json.JSONDecodeError):
    return None
  # waiver: per-attempt rejection record field, written by _reject_response
  attempt = record.get("attempt", 0)
  return (
    f"CORRECTION — attempt {attempt} of this job was rejected and its response discarded. "
    f"Reason: {record.get(JobResponseKey.MESSAGE, '')} "
    "Redo the work and write a response that satisfies the contract."
  )


def _materialize_io(jdir: Path, cfg: dict, work_root: Path) -> str | None:
  """
  Copy a claimed job's declared source and context paths into its bundle directory.

  A directory entry is copied whole under `<parent>-<name>`, so two asset folders that share a
  slug across categories stay apart; a file entry lands directly in the bucket under its
  basename. A bucket whose manifest is empty is not created. An entry resolving outside the
  work tree is rejected rather than copied.

  Guarantees:
    - Every entry a bucket receives comes from inside the work tree; an entry whose resolved path
      lies outside it is refused rather than copied.
    - A directory entry lands under `<parent-directory-name>-<directory-name>`, never under its bare
      name, so folders sharing a slug across categories stay apart.
    - A file entry lands under its plain basename.

  Args:
    jdir: Job bundle directory the buckets are created under.
    cfg: Parsed `config.json` carrying the two manifests.
    work_root: Tree the entries are read from — the job's linked worktree when it has one,
      otherwise the repository checkout.

  Returns:
    None when every declared entry was copied, or a one-line message naming the first entry
    that could not be resolved.
  """

  # Contract:
  # Every entry a bucket receives MUST come from inside the work tree; an entry whose resolved
  # path lies outside it is refused rather than copied. A directory entry lands under
  # `<parent-directory-name>-<directory-name>` and NEVER under its bare name, so folders sharing
  # a slug across categories stay apart; a file entry lands under its plain basename.

  # both buckets share one loop — the only difference is which manifest key feeds which dir
  for key, bucket in ( ( JobConfigKey.SOURCE_PATHS, JobIODir.SOURCE ),
                       ( JobConfigKey.CONTEXT_PATHS, JobIODir.CONTEXT ) ):
    for rel in cfg.get(key) or []:
      src = (work_root / rel).resolve()
      # guard: a `../`-bearing entry would stage files from outside the checkout into a bundle the
      # expert reads and may commit — the manifest arrives as JSON on stdin, so it is untrusted
      if not src.is_relative_to(work_root.resolve()):
        return f"{bucket}/: declared path {rel!r} escapes the work tree"
      # guard: the entry vanished between dispatch and claim — deterministic, retry cannot help
      if not src.exists():
        return f"{bucket}/: declared path {rel!r} does not exist at claim time"
      dst_dir = jdir / bucket
      dst_dir.mkdir(exist_ok = True)
      # a directory arrives whole under `<parent>-<name>`: two asset folders declared from
      # different categories share their own name and would otherwise merge into one; a file goes
      # flat, which is the layout every protocol's per-kind subdir declaration already describes
      if src.is_dir():
        shutil.copytree(src, dst_dir / f"{src.parent.name}-{src.name}", dirs_exist_ok = True)
      else:
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
  for p in protocols:
    prompt_lines.append(f"- protocol:           {p}")
  for a in aspects:
    prompt_lines.append(f"- aspect:             {a}")
  for k in sorted(arguments):
    v = json.dumps(arguments[k], ensure_ascii = False, sort_keys = True)
    prompt_lines.append(f"- argument:           {k} = {v}")
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
    "response.json MUST carry an `outcome` field: a value from your protocol's outcome enum, "
    "the reserved `error` with an `error` object, or the reserved `deferred` when you "
    "deliberately did none of the work and left every input untouched. A protocol names the values, never the "
    "field — if yours prescribes some other status field, write `outcome` anyway and report "
    "the contradiction in your summary. A response without `outcome` is rejected, and work "
    "reported as done through any other field is read as a failure.",
  ])
  # a rejected previous attempt left its reason behind — the re-spawn is told what was
  # wrong with it, since repeating the same prompt would only reproduce the same answer
  rejection = _read_rejection(jdir)
  if rejection is not None:
    prompt_lines.extend([ "", rejection ])
  cfg = json.loads((jdir / JobFile.CONFIG).read_text())
  if not cfg.get(JobConfigKey.CAN_COMMIT_IN_REPO, False):
    clause = (
      # waiver: filesystem path idiom, not a domain constant
      Path(__file__).parent.parent / "templates" / "expert-prompts" / "no-commit-clause.md"
    )
    if clause.exists():
      prompt_lines.extend([ "", clause.read_text().strip() ])
  return "\n".join(prompt_lines)


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
  # guard: sandbox settings file absent (daemon not installed here) — spawn unsandboxed
  if not settings_file.is_file():
    return []
  return [ "--settings", str(settings_file) ]


def _normalize_mcp_config(mcp_config: str | list[str] | None, repo: Path) -> list[str]:
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
  for p in paths:
    # guard: skip non-string / empty entries defensively
    if not isinstance(p, str) or not p:
      continue
    pp = Path(p)
    out.append(str(pp if pp.is_absolute() else (Path(repo) / pp)))
  return out


# Valid `--setting-sources` scopes (claude rejects anything else with
# "Invalid setting source: … Valid options are: user, project, local").
_VALID_SETTING_SOURCES = ( "user", "project", "local" )
# Hermetic default when an expert declares no `setting_sources`: drop `user`
# scope so interactive operator plugins/hooks (e.g. a Warp PostToolUse hook that
# blocks a headless spawn on every tool call) never load, while keeping the
# project's own skills / agents / plugins. Mirrors always-on `--strict-mcp-config`.
_DEFAULT_SETTING_SOURCES = ( "project", "local" )


def _normalize_setting_sources(setting_sources: str | list[str] | None) -> list[str]:
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
  for s in raw:
    # guard: skip non-string / empty entries defensively
    if not isinstance(s, str) or not s.strip():
      continue
    scope = s.strip().lower()
    # guard: keep only recognized, de-duplicated scopes
    if scope in _VALID_SETTING_SOURCES and scope not in out:
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
  # `--permission-mode dontAsk` (not `bypassPermissions`): auto-deny any tool
  # call outside the sandbox — bypassPermissions skips even deny rules and lets a
  # misguided agent burn minutes on `find /Users/...`; dontAsk fails immediately.
  argv = [ "claude", "-p", "--permission-mode", "dontAsk",
           "--output-format", "stream-json", "--verbose",
           "--append-system-prompt-file", str(contract_path),
           "--strict-mcp-config",
           "--setting-sources", ",".join(_normalize_setting_sources(setting_sources)) ]
  for cfg_path in _normalize_mcp_config(mcp_config, repo):
    argv.extend([ "--mcp-config", cfg_path ])
  # Propagate plugin-dir flags so the spawn sees the same plugin tree as the
  # daemon; without them `claude -p` falls back to its cache and chases sibling
  # skills via slow `find` on Dropbox checkouts. Set by runtime_daemon.
  # waiver: environment-variable name, not a domain key
  for pd in (env.get("LAZYCORTEX_PLUGIN_DIRS") or "").split(os.pathsep):
    if pd:
      argv.extend([ "--plugin-dir", pd ])
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
  transient failure — a non-zero exit or a missing response.json — still gets exactly one
  attempt per pump tick before the same READY+ERROR outcome. A successful run that leaves
  the working tree dirty raises `_ExpertLeftDirtyTree` so the pump halts the queue.

  Args:
    repo: Repository root the spawn runs inside.
    expert_name: Name of the expert that owns this job.
    jdir: Path to the job directory being processed.

  Raises:
    _ExpertLeftDirtyTree: When the expert exited cleanly but left uncommitted changes.
  """
  # Idle-watchdog config is read per-job (cheap single-file read) so _process_one keeps
  # its 3-arg signature — pump()'s call site and the halt-test monkeypatch stay valid.
  daemon = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON)
  idle_timeout_sec = int(daemon.get(DaemonKey.STREAM_IDLE_TIMEOUT_SEC, _STREAM_IDLE_TIMEOUT_DEFAULT))
  # waiver: small internal subkey, not a reusable domain key
  max_stall_retries = max(0, int(daemon.get("stream_max_retries", _STREAM_MAX_RETRIES_DEFAULT)))
  # Per-job config.json carries everything the pump needs: agent ref,
  # protocols list (declared by the routine that created this job),
  # git_author for any commits the expert makes. Routine wrote it at
  # dispatch time; pump never consults lazy.settings.json[experts].
  config_path = jdir / JobFile.CONFIG
  # guard: per-job config missing — write logical error and bail
  if not config_path.exists():
    _write_error(jdir, JobErrorCategory.LOGICAL, f"config.json missing in {jdir}")
    return
  try:
    cfg = json.loads(config_path.read_text())
  except (OSError, json.JSONDecodeError) as e:
    _write_error(jdir, JobErrorCategory.LOGICAL, f"unreadable config.json: {e}")
    return

  # the job config names the agent plus the reference sets composed onto it
  agent_ref = cfg.get(JobConfigKey.AGENT)
  protocols_refs = cfg.get(JobConfigKey.PROTOCOLS) or []
  aspects_refs   = cfg.get(JobConfigKey.ASPECTS) or []
  arguments      = cfg.get(JobConfigKey.ARGUMENTS) or {}
  model          = cfg.get(JobConfigKey.MODEL)
  mcp_config     = cfg.get(JobConfigKey.MCP_CONFIG)
  setting_sources = cfg.get(JobConfigKey.SETTING_SOURCES)
  # guard: agent reference must be present in config
  if not agent_ref:
    # waiver: one-off human-facing message
    _write_error(jdir, JobErrorCategory.LOGICAL, "config.json: missing agent")
    return

  # Empty protocols + empty aspects is a valid config. Specific-domain
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
      resolve(p, category = "protocols", repo = repo) for p in protocols_refs
    ]
    aspect_paths = [
      # waiver: cross-module reference-category token, not an internal key
      resolve(a, category = "aspects", repo = repo) for a in aspects_refs
    ]
  except ReferenceError as e:
    _write_error(jdir, JobErrorCategory.LOGICAL, str(e))
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
    job_branch = json.loads((jdir / JobFile.REQUEST).read_text()).get(JobRequestKey.BRANCH)
  except (OSError, json.JSONDecodeError):
    job_branch = None

  # a workspace:main (or absent) expert never branches — a payload naming one anyway (the
  # same expert also dispatched for review rewrites) is ignored, not refused
  if workspace != WorkspaceMode.BRANCH and job_branch:
    sys.stderr.write(
      f"workspace: {expert_name!r} is workspace:{workspace!r} — ignoring payload branch "
      f"{job_branch!r}, job runs on the current checkout\n"
    )
  # the reverse mismatch: a workspace:branch expert dispatched with no payload branch (an
  # ordinary review-rewrite sharing the expert) runs on the current checkout too — logged for
  # the same observability the reverse case above gets, since it is the same capability-not-
  # mandate shape from the other side (M14)
  elif workspace == WorkspaceMode.BRANCH and not job_branch:
    sys.stderr.write(
      f"workspace: {expert_name!r} is workspace:branch but this job carries no payload "
      f"branch — job runs on the current checkout\n"
    )

  # `branch` present AND this expert opted in — activate the capability for this dispatch;
  # any other combination leaves worktree_dir None and the job runs on the current checkout
  branch_created = False
  mgr: WorktreeTaskManager | None = None
  pre_spawn_tip: str | None = None
  if workspace == WorkspaceMode.BRANCH and job_branch:
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
    )
    try:
      worktree_dir, branch_created = mgr.create(jdir.name, job_branch)
    except WorktreeStartError as e:
      _write_error(jdir, JobErrorCategory.LOGICAL, f"workspace: branch worktree failed: {e}")
      return

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

  # From here on the job's worktree (if any) exists — every exit, including one raised by code
  # below rather than returned, must remove it so a crashed spawn never leaves a stray worktree
  # for the whole polling interval (the hourly sweep is the backstop, not the plan). The `try`
  # opens right here, before the git-author dict access below, so a malformed `git_author` in a
  # job's config.json (a string where a dict is expected) can't strand the worktree either.
  # Removal is unconditional (operator decision 2026-08-14): the branch survives as the only
  # durable product; an agent's uncommitted dirt disappears with the directory.
  try:
    # the expert commits under its own identity, passed down through the environment
    git_author = cfg.get(JobConfigKey.GIT_AUTHOR) or {}
    env = os.environ.copy()
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
    # subagents may nest. `runtime_daemon.set_plugin_dirs` pins the same value onto the
    # daemon's own subprocess environment, for routines that spawn outside this function.

    # pin it on this spawn's own env
    env[EnvVar.MAX_SUBAGENT_SPAWN_DEPTH] = EnvVar.SUBAGENT_SPAWN_DEPTH_PIN

    # the buckets are filled now, not at dispatch — a job that waited in the queue starts from
    # the tree as it stands at claim, which is what makes the serial queue safe against a
    # stale snapshot
    materialize_error = _materialize_io(jdir, cfg, worktree_dir or repo)
    # guard: a declared path vanished or reaches outside the work tree — a logical fault the
    # owning coordinator sorts out on its next wake
    if materialize_error is not None:
      _write_error(jdir, JobErrorCategory.LOGICAL, materialize_error)
      return

    # Three parallel single-noun labels — protocols, aspects, arguments.
    # `- protocol:` replaces the legacy `- protocol contract:` for parallelism.
    # Arguments are key-sorted for byte-stable prompts (cache hits, snapshot tests).
    prompt = _compose_user_prompt(jdir, protocols = protocol_paths, aspects = aspect_paths, arguments = arguments)
    # an isolated job carries its commit obligation in the prompt — the protocol files under the
    # job dir are reached by absolute paths, so the worktree cwd changes nothing else
    if worktree_dir is not None and job_branch:
      prompt += "\n\n" + _isolation_prompt(job_branch, branch_created)
    # waiver: filesystem path idiom, not a domain constant
    contract_path = (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()

    # Mark this job as ours: write PID before invoking the expert.
    # The dead-job detector reads this to distinguish queued (no PID)
    # from active (PID file present, alive) from stuck (PID dead).
    (jdir / JobMarker.PID).write_text(f"{os.getpid()}\n")

    # Bump attempts counter — persists across pump kills + recovery cycles.
    # Recovery routine reads this to decide retry vs. permanent-fail.
    attempts_file = jdir / JobArtifact.ATTEMPTS
    try:
      n = int(attempts_file.read_text().strip())
    except (OSError, ValueError):
      n = 0
    attempts_file.write_text(f"{n + 1}\n")

    # The spawn command line — permission mode, hermetic `--strict-mcp-config` +
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

    # Idle-watchdog + bounded re-spawn. A `claude -p` stream can freeze (no first token,
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

    # frames seen across every attempt of this job, for the degradation warning below
    seen_frames = 0
    for stall_attempt in range(max_stall_retries + 1):
      returncode, stdout, stderr, stalled = _spawn_with_idle_watchdog(
        # an isolated job's agent works inside its worktree; every other job on the checkout
        claude_argv, env = env, cwd = worktree_dir or repo, idle_timeout_sec = idle_timeout_sec,
      )
      seen_frames += _record_rate_limit(repo, expert_name, stdout)
      # guard: stream produced output / exited on its own — hand off to the outcome path
      if not stalled:
        break
      _append_stream_stall_log(repo, expert_name, jdir, stall_attempt + 1, idle_timeout_sec)
      sys.stderr.write(
        f"stream-idle-stall: {expert_name}/{jdir.name} "
        f"attempt {stall_attempt + 1}/{max_stall_retries + 1}\n"
      )
    # guard: every re-spawn stalled — record a transient error; the next tick re-dispatches
    if stalled:
      _write_error(
        jdir, JobErrorCategory.TRANSIENT,
        f"stream-idle-stall after {max_stall_retries + 1} spawn(s); no stdout for >{idle_timeout_sec}s",
      )
      return

    # Silence must not read as "all clear": the provider emits a rate-limit frame in every run,
    # so a completed run carrying none means the signal the guard depends on has degraded.
    if seen_frames == 0:
      sys.stderr.write(
        f"rate-limit guard: no rate_limit_event frame in {expert_name}/{jdir.name} "
        f"(exit={returncode}) — guard blind for this run\n"
      )

    # Persist the transcript — best-effort, never block DONE on a write failure.
    try:
      (jdir / JobArtifact.TRANSCRIPT).write_text(stdout or "")
    except Exception as e:  # pragma: no cover — defensive
      sys.stderr.write(f"transcript write failed: {e}\n")

    # a clean exit still needs a usable response.json before this job can reach DONE
    if returncode == 0:
      response_path = jdir / JobFile.RESPONSE
      # Bug 99 fallback: agent exited cleanly but didn't write a usable response.json
      # — recover the JSON object from the final assistant text frame of
      # the stream-json transcript. LLMs sometimes describe their result in
      # text instead of writing the file. Without this fallback the success-
      # gate fails, the pump records a transient error, and the dispatcher
      # re-dispatches until a roll of the dice lands a write-this-time run.
      # The same salvage covers a written-but-envelope-violating response: the
      # narrated payload is often well-formed even when the written file is not.
      if not outcome_tokens(read_response(jdir)):
        recovered = _extract_response_from_stdout(stdout or "")
        if recovered is not None:
          response_path.write_text(json.dumps(recovered, indent = 2))
      # guard: no outcome survived the salvage — the envelope is violated, and a
      # missing discriminator must never be read as completed work
      if not outcome_tokens(read_response(jdir)):
        _reject_response(jdir, _ENVELOPE_VIOLATION_MESSAGE)
        return

      # the envelope guard above already proved a parsed response with an outcome is on disk
      # Token capture is best-effort — never block DONE.
      try:
        usage = _extract_usage(stdout)
        if usage is not None:
          _append_tokens_log(repo, expert_name, usage)
      except Exception as e:  # pragma: no cover — defensive
        sys.stderr.write(f"token capture failed: {e}\n")

      # Post-spawn verification splits by isolation: an isolated job is judged inside its own
      # worktree (dirty tree OR an unmoved branch = job failure, never a daemon halt — the
      # primary checkout was untouched throughout); a non-isolated job keeps the daemon-wide
      # dirty-tree halt, whose rationale is exactly that it shares the operator's tree. A
      # read-only agent never writes or commits, so it is exempt on both arms — an isolated
      # read-only job would otherwise always fail the unmoved-branch check.
      if not _agent_is_read_only(agent_path):
        if worktree_dir is not None:
          failure = _isolated_job_failure(worktree_dir, pre_spawn_tip)
          # guard: the isolated job broke its commit obligation — fail it, keep the queue moving
          if failure is not None:
            _write_error(jdir, JobErrorCategory.LOGICAL, failure)
            return
        # guard: abort the tick when the expert left the shared working tree dirty
        elif _check_post_claude(repo, expert_name, jdir):
          raise _ExpertLeftDirtyTree(expert_name, jdir.name, [])
      # the correction landed — drop the rejection record so it cannot resurface
      # in the prompt of a later attempt on this same bundle
      (jdir / JobArtifact.ERROR_JSON).unlink(missing_ok = True)
      (jdir / JobMarker.DONE).touch()
      return
    _write_error(jdir, JobErrorCategory.TRANSIENT, f"exit={returncode} stderr={stderr[-500:]}")
  finally:
    # the worktree is removed on EVERY exit — success, failure, and exception alike; the branch
    # is the durable product, uncommitted dirt goes with the directory (operator decision)
    if mgr is not None and worktree_dir is not None:
      mgr.remove(worktree_dir)


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
    # guard: best-effort close — the child owns the write end and may already be gone
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
  # guard: SIGTERM ignored within the grace window — force-kill the whole group
  try:
    os.killpg(pgid, signal.SIGKILL)
  except ProcessLookupError:
    pass


def _spawn_with_idle_watchdog(
  argv: list[str], *, env: dict, cwd: Path, idle_timeout_sec: float,
) -> tuple[int, str, str, bool]:
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
    text = True, start_new_session = True,
  )
  line_q: queue.Queue = queue.Queue()
  # Both pipes are drained on daemon threads so a full OS buffer can never deadlock the
  # read loop; the idle timer is measured on stdout only (the model's event stream).
  readers = [
    threading.Thread(target = _pipe_reader, args = (proc.stdout, "out", line_q), daemon = True),
    threading.Thread(target = _pipe_reader, args = (proc.stderr, "err", line_q), daemon = True),
  ]
  for t in readers:
    t.start()

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
      now = time.monotonic()
      idle = now - last_out
      # guard: stdout silent past the idle window while still open — treat as a freeze
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
      # guard: EOF sentinel for one pipe
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
    # Any unexpected exit must not leave the spawn's group alive.
    _kill_process_group(proc)
    raise
  returncode = proc.wait()
  return returncode, "".join(out_parts), "".join(err_parts), stalled


def _extract_response_from_stdout(stdout: str) -> dict | None:
  """
  Recover a response.json payload from the agent's stream-json transcript.

  Used as a fallback when the agent process exits cleanly (`rc == 0`) but
  did not write `response.json` to disk. LLMs occasionally narrate their
  outcome in their final assistant message instead of invoking the Write
  tool against the response file. Without this recovery, the pump records
  a transient error, the dispatcher re-dispatches the same job, and the
  cycle repeats until a random roll of the dice lands a write-this-time
  run (Bug 99).

  Walk the stream-json frames, collect every text block emitted by an
  assistant frame, and search the LAST emitted text first for the first
  balanced JSON object that carries an `outcome` field — that is the
  documented response.json shape. Returns the parsed dict or None when
  no recoverable object is found (transient-error path is the right
  outcome in that case).

  Args:
    stdout: Raw stdout produced by a `claude -p --output-format stream-json`
      invocation.

  Returns:
    The parsed response payload as a dict, or None when no JSON object
    with an `outcome` field can be recovered from any assistant text.
  """
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
  # Search last-emitted text first; LLMs typically describe outcome in final reply.
  for text in reversed(texts):
    idx = 0
    while idx < len(text):
      # guard: skip non-object-opening characters
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

  The function walks each stream-json frame for the final `result` frame and the most
  recent `model` value seen on an assistant frame. When the buffer is a single JSON
  object instead of a stream, the whole-buffer shape is parsed as a fallback.

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

  # Try line-by-line first (stream-json), then whole-buffer (single json).
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

  # Fallback: stdout was a single JSON object (whole buffer parses).
  if final_usage is None and not parsed_any:
    try:
      frame = json.loads(stdout)
      # waiver: external Claude Code stream-json field name, not an internal key
      if isinstance(frame, dict) and isinstance(frame.get("usage"), dict):
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
  # waiver: filesystem path idiom, not a domain constant
  log_path = log_dir / "tokens.jsonl"
  record = {
    "ts": time.time(),
    "routine": "expert-pump",
    "expert": expert_name,
    **usage,
  }
  # waiver: stdlib idiom, not a domain constant
  with log_path.open("a") as f:
    f.write(json.dumps(record) + "\n")


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
  # waiver: filesystem path idiom, not a domain constant
  log_path = log_dir / "stream-stalls.jsonl"
  record = {
    "ts": time.time(),
    "routine": "expert-pump",
    "expert": expert_name,
    "job_id": jdir.name,
    "attempt": attempt,
    "idle_sec": idle_sec,
  }
  # waiver: stdlib idiom, not a domain constant
  with log_path.open("a") as f:
    f.write(json.dumps(record) + "\n")


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


def _append_jobs_log(
    repo: Path, expert_name: str, job_id: str, outcome: str, *, duration_sec: float | None = None,
) -> None:
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
    with (log_dir / "jobs.jsonl").open("a") as f:
      f.write(json.dumps(record) + "\n")
  except Exception as e:  # pragma: no cover — defensive
    sys.stderr.write(f"job log append failed: {e}\n")


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
    if (jdir / JobMarker.DONE).exists():
      outcome = _classify_finished(jdir)
    else:
      outcome = JobLogOutcome.ERROR
    _append_jobs_log(
      repo, expert_name, jdir.name, outcome,
      duration_sec = time.monotonic() - started_monotonic,
    )
  except Exception as e:  # pragma: no cover — defensive
    sys.stderr.write(f"job log append failed: {e}\n")


def _reject_response(jdir: Path, message: str) -> None:
  """
  Reject a finished attempt whose response violated the envelope.

  The first rejection of a bundle keeps the job queued: the unusable response is
  removed, the claim released, and the reason recorded beside the bundle so the
  next spawn is told what was wrong with the last one. A repeat rejection means
  the fault reproduces regardless of the run, so the job is failed for good and
  the incident is opened for an operator.

  Args:
    jdir: Path to the job directory whose attempt is being rejected.
    message: Human-readable reason handed back to the expert and recorded with
      the incident.
  """
  # the counter was bumped before this attempt started, so it counts attempts so far
  try:
    attempts = int((jdir / JobArtifact.ATTEMPTS).read_text().strip())
  except (OSError, ValueError):
    attempts = 0
  # guard: the retry budget is spent — a reproducing violation is the expert's contract,
  # not a bad roll, and another spawn would only burn a model call to fail identically
  if attempts > _ENVELOPE_RETRY_LIMIT:
    _write_error(jdir, JobErrorCategory.LOGICAL, message)
    return
  # waiver: per-attempt rejection record read back by the prompt composer, not a shared key
  (jdir / JobArtifact.ERROR_JSON).write_text(json.dumps({
    JobResponseKey.CATEGORY: JobErrorCategory.LOGICAL,
    JobResponseKey.MESSAGE: message,
    "attempt": attempts,
  }, indent = 2))
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
  # read the persisted counter; a missing or garbled file restarts the budget from zero,
  # which errs toward retrying — the cap exists to stop storms, not to lose work
  counter = jdir / JobArtifact.TRANSIENT_ERRORS
  try:
    count = int(counter.read_text().strip())
  except (OSError, ValueError):
    count = 0
  count += 1
  counter.write_text(f"{count}\n")

  # the repo root is fixed by the queue layout: <repo>/.experts/.jobs/<expert>/<job>
  # waiver: inline numeric literal — the shipped default budget (5), overridable in settings
  daemon = load_section(jdir.parents[3] / SettingsFile.REL, SettingsKey.DAEMON)
  return count < int(daemon.get(DaemonKey.TRANSIENT_MAX_RETRIES, 5))


def _write_error(jdir: Path, category: str, message: str) -> None:
  """
  Write an error outcome to the job, closing it unless a transient retry is still due.

  A transient failure with budget left releases the job's claim and leaves the bundle in the
  documented READY+ERROR state — `DONE` untouched — so the next pump tick retries it as an
  unclaimed job, until the bundle's transient budget (`daemon.transient_max_retries`) runs out
  and the job closes like any other error. Every path records the ledger incident.

  Guarantees:
    - A transiently-errored bundle with retry budget left has its claim's `PID` marker unlinked,
      so it is queued again, indistinguishable from a never-claimed READY job, and dead-claimant
      reconciliation cannot finalize it to `DONE` while a retry is due.

  Args:
    jdir: Path to the job directory whose response.json is being written.
    category: Error category label persisted in the response payload.
    message: Human-readable error message persisted alongside the category.
  """
  (jdir / JobFile.RESPONSE).write_text(json.dumps({
    JobResponseKey.OUTCOME: JobOutcome.ERROR,
    JobResponseKey.ERROR: { JobResponseKey.CATEGORY: category, JobResponseKey.MESSAGE: message },
  }, indent = 2))

  # a transient failure with budget left stays claimable — READY+ERROR, no DONE;
  # everything else (logical, uncommitted, exhausted budget) closes the job
  if category == JobErrorCategory.TRANSIENT and _spend_transient_budget(jdir):

    # Contract:
    # A transiently-errored bundle with retry budget left has its claim's PID marker unlinked,
    # so it is queued again, indistinguishable from a never-claimed READY job; dead-claimant
    # reconciliation cannot finalize it to DONE while a retry is due.

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


def _maybe_cleanup(jdir: Path, done_after: float, fail_after: float, dead_after: float) -> int:
  """
  Garbage-collect a single job directory when its retention window has elapsed.

  Jobs marked DONE are retained for `done_after` seconds only when the response proves
  the work finished; every other finished bundle — an error outcome, a deferral, a
  violated envelope — is retained for `fail_after` seconds so it survives to be inspected. Jobs marked DEAD
  are retained for `dead_after` seconds as a forensic window. Cancelled jobs share the
  `fail_after` window (`cleanup_failed_after`, default 30d) — a cancellation is an
  operator intervention whose forensics deserve the long window; no separate knob.
  Jobs in none of these states are left untouched.

  Args:
    jdir: Path to the job directory being considered for cleanup.
    done_after: Retention window in seconds for jobs whose response proves the work finished.
    fail_after: Retention window in seconds for every other finished job — an error outcome,
      a deferral, or a violated envelope.
    dead_after: Retention window in seconds for jobs that were marked dead.

  Returns:
    1 if the job directory was removed, 0 otherwise.
  """
  # cancellation outranks every other marker (same precedence as status classification)
  if (jdir / JobMarker.CANCELLED).exists():
    age = time.time() - (jdir / JobMarker.CANCELLED).stat().st_mtime
    if age >= fail_after:
      shutil.rmtree(jdir)
      return 1
    return 0

  # a finished job is retained for its own window, longer when it ended in an error
  if (jdir / JobMarker.DONE).exists():
    age = time.time() - (jdir / JobMarker.DONE).stat().st_mtime
    # anything short of a proven success is retained on the longer failure window,
    # so an envelope-violating or deferred bundle survives long enough to be inspected
    is_error = classify_response(read_response(jdir)) != JobStatus.DONE
    threshold = fail_after if is_error else done_after
    if age >= threshold:
      # a clean job that still has an open incident was retried after a failure → resolved:retried_ok
      key = f"job:{jdir.parent.name}/{jdir.name}"
      open_states = ( IncidentState.OPEN, IncidentState.NEEDS_OPERATOR )
      if not is_error and any(
        i.get(IncidentKey.INCIDENT) == key and i.get(IncidentKey.STATE) in open_states
        # waiver: inline numeric/default literal, not a domain constant
        for i in error_ledger.incidents(jdir.parents[3], state = IncidentState.ALL)):
        # waiver: inline numeric/default literal, not a domain constant
        error_ledger.resolve(jdir.parents[3], key, resolution = "retried_ok",
                             kind = IncidentKind.JOB_DEAD, actor = IncidentActor.PUMP)
      shutil.rmtree(jdir)
      return 1
    return 0

  # a dead job is retained on its own window so the operator can still inspect it
  if (jdir / JobMarker.DEAD).exists():
    age = time.time() - (jdir / JobMarker.DEAD).stat().st_mtime
    if age >= dead_after:
      shutil.rmtree(jdir)
      return 1
    return 0

  # a job carrying neither marker is still live, so nothing is reaped
  return 0


def _parse_duration(s: str) -> float:
  """
  Parse a human-readable duration string into seconds.

  Args:
    s: Duration string of the form `<number><unit>` where unit is one of `s`, `m`, `h`, `d`.

  Returns:
    The duration expressed in seconds as a float.

  Raises:
    KeyError: When the trailing unit character is not recognized.
    ValueError: When the leading portion does not parse as a number.
  """
  units = { "s": 1, "m": 60, "h": 3600, "d": 86400 }
  return float(s[:-1]) * units[s[-1]]
