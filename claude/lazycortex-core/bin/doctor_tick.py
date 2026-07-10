"""
Trigger for the autonomous lazy-runtime.doctor expert.

Pure-Python tick (no reasoning) that runs hourly. Decides whether the
daemon needs medical attention and, if so, dispatches a single
`lazy-runtime.doctor` expert job to the queue. The agent itself
performs every diagnosis + fix-or-give-up decision.

Trigger conditions (OR-joined):
1. `state.daemon_halted.reason == "uncommitted_changes"` and
   `halted_since` is at least 1 hour old — operator clearly is not
   coming to fix it manually, doctor takes over.
2. At least one `.experts/.jobs/<expert>/<job>/DEAD` marker exists
   without a sibling `diagnosis.json` — there's a dead job waiting
   for retry-or-permanent-fail judgment.

When triggered, the tick gathers context (halt block, dead-job
inventory with their `dead.json` + `error.json` + tails of
`transcript.jsonl`, recent commit log) and dispatches a single doctor
job via `expert_runtime.dispatch_job`. Deduplication via
`dedup_key="doctor"` ensures we never queue a second concurrent
doctor — one runs at a time, period.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import subprocess
import time
from pathlib import Path

from constants import HaltKey, HaltReason, IncidentKey, JobArtifact, JobFile, JobMarker, SettingsFile, SettingsKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


JOBS_BASE = ".experts/.jobs"
DEAD_HALT_AGE_SEC = 3600  # halt must be ≥1h old before doctor takes over


def _dead_jobs_needing_doctor(repo: Path) -> list[dict]:
  """
  Return entries for every DEAD job directory that has not yet been triaged.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    A list of dicts with keys `expert`, `job_id`, and `jdir_rel` (the job dir path relative to
    the repository root). Empty list when no dead jobs await triage.
  """
  base = repo / JOBS_BASE
  # guard: jobs base directory does not exist — no dead jobs to inventory
  if not base.is_dir():
    return []
  out: list[dict] = []
  # walk expert directories then per-expert job directories looking for un-triaged DEAD markers
  for edir in sorted(base.iterdir()):
    # guard: skip non-directory entries under the jobs base
    if not edir.is_dir():
      continue
    for jdir in sorted(edir.iterdir()):
      # guard: skip non-directory entries under an expert
      if not jdir.is_dir():
        continue
      # guard: skip jobs that are not marked DEAD
      if not (jdir / JobMarker.DEAD).exists():
        continue
      # guard: skip jobs that have already been triaged
      if (jdir / JobArtifact.DIAGNOSIS_JSON).exists():
        continue
      out.append({
        IncidentKey.EXPERT: edir.name,
        IncidentKey.JOB_ID: jdir.name,
        "jdir_rel": str(jdir.relative_to(repo)),
      })
  return out


def _stuck_halt(repo: Path) -> dict | None:
  """
  Return the persisted halt block when the daemon has been stuck on a dirty tree long enough for the doctor.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    The halt block dict when the daemon has been halted with reason `uncommitted_changes` for at least
    `DEAD_HALT_AGE_SEC` seconds, otherwise `None`. Other halt reasons (git-related) require human
    investigation and stay out of doctor scope.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from runtime_state import get_halted
  halt = get_halted(repo)
  # guard: no halt block — daemon is not stuck
  if halt is None:
    return None
  # guard: halt is not a dirty-tree halt — out of doctor scope
  if halt.get(HaltKey.REASON) != HaltReason.UNCOMMITTED_CHANGES:
    return None
  age = time.time() - float(halt.get(HaltKey.HALTED_SINCE, 0))
  # guard: halt is younger than the threshold — give the operator more time to react
  if age < DEAD_HALT_AGE_SEC:
    return None
  return halt


def _read_tail(path: Path, lines: int = 50) -> str:
  """
  Return the last lines of a text file as a single string.

  Args:
    path: Path to the text file to read.
    lines: Maximum number of trailing lines to return.

  Returns:
    The concatenation of the last `lines` lines of the file separated by newlines, or an empty string when
    the file is missing or cannot be decoded.
  """
  try:
    text = path.read_text()
  except (OSError, UnicodeDecodeError):
    return ""
  parts = text.splitlines()
  return "\n".join(parts[-lines:])


def _build_context(repo: Path, halt: dict | None, dead_jobs: list[dict]) -> dict:
  """
  Build the context snapshot the doctor agent will read from its job source directory.

  Args:
    repo: Absolute path to the repository root.
    halt: The halt block returned by `_stuck_halt`, or `None` when the daemon is not halted.
    dead_jobs: The list of dead-job entries returned by `_dead_jobs_needing_doctor`.

  Returns:
    A dict with the halt block, per-dead-job context (request, config, dead and error payloads,
    attempt count, transcript tail), recent git log, and current git status. Missing or unreadable
    sub-payloads are reported as `None`/`0`/empty strings.
  """
  context: dict = {
    "halt": halt,
    "dead_jobs": [],
    "git_log_recent": "",
    "git_status": "",
  }
  # snapshot each dead job's metadata and transcript tail for the doctor
  for entry in dead_jobs:
    # waiver: one-off dead-job context-schema field name, not a reusable domain key
    jdir = repo / entry["jdir_rel"]
    e = dict(entry)
    for key, fname in (
      ( "request_json", JobFile.REQUEST ),
      ( "config_json", JobFile.CONFIG ),
      ( "dead_json", JobArtifact.DEAD_JSON ),
      ( "error_json", JobArtifact.ERROR_JSON ),
    ):
      try:
        e[key] = json.loads((jdir / fname).read_text())
      except (OSError, json.JSONDecodeError):
        e[key] = None
    try:
      # waiver: one-off doctor-context-schema field name, not a reusable domain key
      e["attempts"] = int((jdir / JobArtifact.ATTEMPTS).read_text().strip())
    except (OSError, ValueError):
      # waiver: one-off doctor-context-schema field name, not a reusable domain key
      e["attempts"] = 0
    # waiver: one-off doctor-context-schema field name and inline tail-length literal, not domain constants
    e["transcript_tail"] = _read_tail(jdir / JobArtifact.TRANSCRIPT, 30)
    # waiver: one-off doctor-context-schema field name, not a reusable domain key
    context["dead_jobs"].append(e)
  # capture a small slice of recent commit history for situational awareness
  try:
    # waiver: one-off doctor-context-schema field name, not a reusable domain key
    context["git_log_recent"] = subprocess.run(
      [ "git", "log", "--oneline", "-20" ],
      cwd = str(repo), capture_output = True, text = True, check = True,
    ).stdout
  except subprocess.CalledProcessError:
    pass
  # capture current working-tree status so the doctor can see what the operator left behind
  try:
    # waiver: one-off doctor-context-schema field name, not a reusable domain key
    context["git_status"] = subprocess.run(
      [ "git", "--no-optional-locks", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True, check = True,
    ).stdout
  except subprocess.CalledProcessError:
    pass
  return context


def _all_known_protocols(repo: Path) -> list[str]:
  """
  Return every protocol identifier declared by any routine in the repository's settings.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    The deduplicated list of protocol identifiers reachable from any registered routine, in first-seen
    order so prompts are byte-stable across runs.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from lazy_settings import load_section
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from routine_types import _routine_protocols
  routines = load_section(repo / SettingsFile.REL, SettingsKey.ROUTINES)
  seen: list[str] = []
  for name, cfg in routines.items():
    # guard: skip the version sentinel and any non-dict entries
    if name == SettingsKey.VERSION or not isinstance(cfg, dict):
      continue
    for p in _routine_protocols(cfg):
      # guard: deduplicate while preserving first-seen order
      if p not in seen:
        seen.append(p)
  return seen


def doctor_tick(repo: Path) -> dict:
  """
  Run one hourly doctor trigger pass against the given repository.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    A stats dict the calling routine logs. When no trigger condition is met, the dict reports
    `triggered=False` with no dispatch. When a trigger fires, the dict additionally carries the
    halt and dead-job counts, the ids of finished doctor bundles retired before the fresh
    dispatch, and the dispatch result returned by `expert_runtime.dispatch_job`.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from expert_runtime import dispatch_job, retire_completed_jobs
  repo = Path(repo)
  halt = _stuck_halt(repo)
  dead_jobs = _dead_jobs_needing_doctor(repo)
  # guard: no trigger condition met — leave the queue untouched
  if not halt and not dead_jobs:
    return { "triggered": False, "halt": None, "dead_jobs": 0 }
  # Recycle finished doctor bundles before re-dispatch: the doctor is fire-and-
  # forget (nobody consumes its response), so a DONE bundle — success or error —
  # holds the dedup slot and silently disables the doctor until the cleanup TTL.
  # The errored bundle's failure is already folded into the error ledger by the
  # pump; recycling here lets the next triggered tick retry instead of blocking
  # for days. In-flight bundles (READY without DONE) still deduplicate.
  # waiver: one-off expert name / dedup key for the doctor dispatch, not reusable domain constants
  retired = retire_completed_jobs(repo, "lazy-runtime.doctor", "doctor", dispatched_from = repo)
  context = _build_context(repo, halt, dead_jobs)
  source = { "context.json": json.dumps(context, indent = 2) }
  payload = {
    "halt_present": halt is not None,
    "dead_job_count": len(dead_jobs),
  }
  result = dispatch_job(
    # waiver: one-off routine name and dedup key for the doctor dispatch, not reusable domain constants
    repo, "lazy-runtime.doctor", payload,
    protocols = _all_known_protocols(repo),
    source = source,
    # waiver: one-off dedup key for the doctor dispatch, not a reusable domain constant
    dedup_key = "doctor",
  )
  return {
    "triggered": True,
    "halt": halt is not None,
    "dead_jobs": len(dead_jobs),
    "retired": retired,
    "dispatch": result,
  }
