"""
Public helpers for dispatching and collecting jobs in the expert runtime.

Owns the on-disk layout of `<repo>/.experts/.jobs/<expert>/<job_id>/` — the
per-job bundle the pump consumes. Every state-mutating operation in this
module is the atomic primitive a caller in another plugin reaches for via
the `lazycortex-core` CLI (`dispatch-job`, `collect-job`, `lookup-expert`,
`consume-job`) — never via direct Python import.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from typing import TypedDict

import json
import time
import uuid
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from job_response import classify_response, read_response

from constants import (
  HookName, IncidentActor, IncidentKey, IncidentKind, IncidentPhase, JobCollectKey, JobConfigKey,
  JobFile,
  JobIODir, JobMarker, JobRequestKey, JobResponseKey, JobStatus,
  RoutineKey, SettingsFile, SettingsKey, WorkspaceMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NotRequired


JOBS_BASE = ".experts/.jobs"
# Grace between SIGTERM and SIGKILL when cancel_job tears down a claimed job's processes.
_CANCEL_KILL_GRACE_SEC = 5.0
# Wall-clock cap for the pgrep child-enumeration subprocess in _stop_claimant.
_PGREP_TIMEOUT_SEC = 10
# Poll interval while waiting out the SIGTERM grace window in _kill_group.
_KILL_POLL_SEC = 0.1


class _RoutineDefaults(TypedDict):
  """
  Shape of a built-in routine's default config block.

  Mirrors the keyword surface of `register_routine`; `ignore_halt` and
  `hooks_enabled` are optional because only some built-in routines declare them.
  """
  name: str
  command: list[str]
  interval_sec: int
  timeout_sec: int
  priority: int
  ignore_halt: NotRequired[bool]
  hooks_enabled: NotRequired[list[str]]

# tier aliases the model-router recognizes; an agent_models value outside this
# set (including the "default" sentinel and unknown strings) means "no pin"
_MODEL_TIERS = frozenset({ "haiku", "sonnet", "opus" })


def _job_dir(repo: Path, expert: str, job_id: str) -> Path:
  """
  Return the canonical job-bundle directory for a single dispatched job.

  Args:
    repo: Absolute path to the repository root that owns the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    job_id: Caller-computed or auto-generated identifier of the job.

  Returns:
    Path to `<repo>/.experts/.jobs/<expert>/<job_id>/`.
  """
  return Path(repo) / JOBS_BASE / expert / job_id


def _with_routine_protocols(protocols: list[str] | None) -> list[str]:
  """
  Union the dispatching routine's protocols with the caller-supplied list.

  A `command:`-shape routine hands its declared protocols to the subprocess only through the
  `LAZYCORTEX_ROUTINE_PROTOCOLS` environment variable, so a dispatcher that never reads that
  variable would otherwise queue jobs without them. Folding the variable in here makes delivery a
  property of the runtime rather than a convention each plugin's dispatcher has to honour, and a
  caller's own protocols are added to the routine's rather than replacing them.

  Args:
    protocols: Protocol references the caller passed to `dispatch_job`.

  Returns:
    Routine-declared references first, then caller-supplied ones, deduplicated with order preserved.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import os as _os
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from routine_types import ROUTINE_PROTOCOLS_ENV, parse_routine_protocols_env

  # env first so the routine's own protocols lead the list a plugin dispatcher extends
  merged: list[str] = []
  for ref in [ *parse_routine_protocols_env(_os.environ.get(ROUTINE_PROTOCOLS_ENV)), *(protocols or []) ]:
    if ref not in merged:
      merged.append(ref)
  return merged


def dispatch_job(
  repo: Path,
  expert: str,
  payload: dict,
  *,
  protocols: list[str] | None = None,
  source: list[str] | None = None,
  context: list[str] | None = None,
  source_inline: dict[str, str] | None = None,
  context_inline: dict[str, str] | None = None,
  result: list[str] | None = None,
  job_id: str | None = None,
  dedup_key: str | None = None,
  dedup_fingerprint: str | None = None,
  can_commit_in_repo: bool | None = None,
) -> dict:
  """
  Create one job bundle atomically and queue it for the pump.

  Writes `request.json` and `config.json` — the latter recording the `source`/`context`
  path manifests for the pump to copy later — plus any inline `source/`, `context/`, and
  `result/` content, in pump-safe order, and touches the `READY` marker last so the pump
  never observes a partial bundle.

  When `dedup_key` is set and an active job for the same `(expert, key)`
  pair already exists, no new bundle is written and `already-queued` is
  returned. An "active" job is one with `READY` present and neither
  `DEAD` nor `CONSUMED` markers — a job that has `response.json` (DONE)
  but no `CONSUMED` is still active for dedup purposes.

  Guarantees:
    - The `source/` and `context/` buckets an expert reads carry the work tree as it stands when
      the pump claims the job, never as it stood at dispatch; only `source_inline` and
      `context_inline` are written at dispatch, for content that exists in no file.

  Notes:
    - Records a best-effort `unpinned_model` incident on the error ledger when the model
      resolution chain yields no pin, without blocking or altering the rest of the dispatch.
    - The protocols written to `config.json` are the dispatching routine's own, read from
      the `LAZYCORTEX_ROUTINE_PROTOCOLS` environment variable, followed by whatever the
      caller passed; a caller adds to the routine's list and cannot replace it.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    payload: JSON-serializable request body written as `request.json`.
    protocols: References the agent reads at spawn time on top of the dispatching
      routine's own; empty for a caller that adds nothing of its own.
    source: Repo-relative paths recorded into `config.json` as `source_paths`; the pump
      copies them under `<job_dir>/source/` when it claims the job, a directory entry
      under `<parent-directory-name>-<directory-name>` and a file entry under its basename.
    context: Repo-relative paths recorded into `config.json` as `context_paths`; the pump
      copies them under `<job_dir>/context/` when it claims the job, a directory entry
      under `<parent-directory-name>-<directory-name>` and a file entry under its basename.
    source_inline: Mapping of filename to text written under `<job_dir>/source/` at
      dispatch, for content that exists in no file.
    context_inline: Mapping of filename to text written under `<job_dir>/context/` at
      dispatch, for content that exists in no file.
    result: Filenames created as empty placeholders under
      `<job_dir>/result/` for the agent to fill.
    job_id: Caller-computed deterministic identifier; a 12-hex slice of
      a fresh UUID is used when omitted.
    dedup_key: When set, embedded in the payload as `_dedup_key` and
      short-circuits to `already-queued` on a pre-existing match.
    dedup_fingerprint: Identity token of the artifact the dedup key names; embedded in the
      payload as `_dedup_fingerprint` and handed back later by `completed_dedup_jobs`, so a
      caller that destroys its input on success can confirm the artifact is still the one
      the job ran on.
    can_commit_in_repo: Override for whether the spawned agent may commit in the target
      repository; the per-expert `can_commit_in_repo` default from `lazy.settings.json` is
      used when omitted.

  Returns:
    `{job_id, queue_path}` on a fresh dispatch, or
    `{job_id, status: "already-queued"}` on a dedup hit.
  """

  # Contract:
  # The `source/` and `context/` buckets an expert reads MUST carry the work tree as it stands
  # when the pump claims the job, never as it stood at dispatch — the declared paths are recorded
  # here as manifests and copied only at claim. The `source_inline` and `context_inline` buckets
  # are the sole exception: they carry content that exists in no file and are written now.

  # dedup short-circuit: scan existing job bundles for a live `_dedup_key` match
  if dedup_key is not None:
    edir = Path(repo) / JOBS_BASE / expert
    if edir.exists():
      for jdir in edir.iterdir():
        # guard: skip non-directory entries that may appear under the expert dir
        if not jdir.is_dir():
          continue
        # guard: pre-READY bundles are not yet active
        if not (jdir / JobMarker.READY).exists():
          continue
        # guard: DEAD bundles are not eligible for dedup
        if (jdir / JobMarker.DEAD).exists():
          continue
        # guard: CONSUMED bundles have been retired by the consumer
        if (jdir / JobMarker.CONSUMED).exists():
          continue
        # guard: CANCELLED bundles released their dedup key on cancellation
        if (jdir / JobMarker.CANCELLED).exists():
          continue
        req_file = jdir / JobFile.REQUEST
        # guard: bundle missing request.json is malformed and cannot match
        if not req_file.exists():
          continue
        try:
          existing = json.loads(req_file.read_text())
        except (OSError, json.JSONDecodeError):
          continue
        if existing.get(JobRequestKey.DEDUP_KEY) == dedup_key:
          return { JobCollectKey.JOB_ID: jdir.name, JobCollectKey.STATUS: JobStatus.ALREADY_QUEUED }

  # resolve expert settings before any filesystem mutation so a misconfigured
  # expert surfaces at dispatch time rather than after partial setup
  expert_entry = _resolve_expert_entry(repo, expert)

  # the bundle slot: a caller-supplied id keeps dispatches addressable, otherwise mint one
  job_id = job_id or uuid.uuid4().hex[:12]
  d = _job_dir(repo, expert, job_id)
  # park any prior DEAD bundle at the same slot before reusing it — without
  # this the new job would coexist with the stale DEAD marker and the pump
  # would skip it as a zombie
  if d.exists() and (d / JobMarker.DEAD).exists():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    d.rename(d.with_name(f"{job_id}.dead-{stamp}"))
  d.mkdir(parents = True, exist_ok = True)

  # auxiliary work files: `source` / `context` are manifests the pump copies when it claims
  # the job, so the expert starts from the tree as it stands then rather than as it stood at
  # dispatch; the `_inline` buckets carry content that exists in no file and is written now
  if source_inline:
    (d / JobIODir.SOURCE).mkdir(exist_ok = True)
    for fname, text in source_inline.items():
      (d / JobIODir.SOURCE / fname).write_text(text)
  if context_inline:
    (d / JobIODir.CONTEXT).mkdir(exist_ok = True)
    for fname, text in context_inline.items():
      (d / JobIODir.CONTEXT / fname).write_text(text)
  if result:
    (d / JobIODir.RESULT).mkdir(exist_ok = True)
    for fname in result:
      (d / JobIODir.RESULT / fname).touch()

  # agent: solely the expert entry — every dispatchable agent, built-ins like
  # the doctor included, is registered in settings by the installer
  agent_ref = expert_entry.get(JobConfigKey.AGENT)

  # model: an explicit per-expert override wins verbatim; otherwise the agent's
  # tier from agent_models (same settings file). None is allowed to proceed but
  # is recorded loudly.
  model = expert_entry.get(JobConfigKey.MODEL) or resolve_agent_model(repo, agent_ref)
  if model is None:
    _record_unpinned_model(repo, expert, agent_ref, d)

  # config.json derived purely from settings.experts[<expert>] plus the
  # protocols of the dispatching routine and the caller together; pump reads
  # this at spawn time
  cfg_blob = {
    JobConfigKey.AGENT:             agent_ref,
    JobConfigKey.PROTOCOLS:         _with_routine_protocols(protocols),
    # the pump copies these when it claims the job — recorded here rather than acted on now
    JobConfigKey.SOURCE_PATHS:      list(source or []),
    JobConfigKey.CONTEXT_PATHS:     list(context or []),
    JobConfigKey.ASPECTS:           list(expert_entry.get(JobConfigKey.ASPECTS) or []),
    JobConfigKey.ARGUMENTS:         dict(expert_entry.get(JobConfigKey.ARGUMENTS) or {}),
    JobConfigKey.GIT_AUTHOR:        expert_entry.get(JobConfigKey.GIT_AUTHOR, {}),
    JobConfigKey.MODEL:             model,
    # Per-expert MCP allow-list: path(s) to explicit --mcp-config files. Owner
    # reads its own settings (dev.plugin-boundaries § 3); the spawn always runs
    # --strict-mcp-config so ambient operator MCP servers are never inherited —
    # a headless daemon spawn must not hang on interactive-auth server init.
    JobConfigKey.MCP_CONFIG:        expert_entry.get(JobConfigKey.MCP_CONFIG),
    # Per-expert hermetic settings scope (mirrors mcp_config sealing): which
    # setting sources the spawn loads. None → pump applies the project,local
    # default, so operator user-scope plugins/hooks never load headless.
    JobConfigKey.SETTING_SOURCES:   expert_entry.get(JobConfigKey.SETTING_SOURCES),
    # Per-expert workspace mode (`main`/`branch`): owner reads its own settings per
    # `dev.plugin-boundaries.md` § 3, same as every other operational key above. `main`
    # (the default) is today's behavior — the pump enforces nothing further.
    JobConfigKey.WORKSPACE:         expert_entry.get(JobConfigKey.WORKSPACE, WorkspaceMode.MAIN),
    # `can_commit_in_repo` override (Bug 87): md-scan dispatches in-place
    # (the consumer edits the file where it lies — see routine_types
    # dispatch_md_scan) and pass True so the apply expert may write +
    # commit in place; the pump (review writer) passes None and inherits
    # the per-expert default (foreign-execution, no-commit clause injected).
    JobConfigKey.CAN_COMMIT_IN_REPO: (
        can_commit_in_repo if can_commit_in_repo is not None
        else bool(expert_entry.get(JobConfigKey.CAN_COMMIT_IN_REPO, False))
    ),
  }
  (d / JobFile.CONFIG).write_text(json.dumps(cfg_blob, indent = 2))

  # request.json is the caller payload plus the dedup key, so a later dispatch can match against it
  out_payload = dict(payload)
  if dedup_key is not None:
    out_payload[JobRequestKey.DEDUP_KEY] = dedup_key

  # the identity of the artifact behind the key at dispatch time, so a consumer that
  # destroys its input on success can tell the same file from a new one at the same path
  if dedup_fingerprint is not None:
    out_payload[JobRequestKey.DEDUP_FINGERPRINT] = dedup_fingerprint

  # the payload is complete only once both reserved keys have had their say
  (d / JobFile.REQUEST).write_text(json.dumps(out_payload, indent = 2))

  # READY touched LAST — atomic activation marker; pump treats READY presence
  # as "every other file in this bundle is valid and you can spawn now"
  (d / JobMarker.READY).touch()

  # the caller gets the handle it needs to poll or consume this job later
  return { "job_id": job_id, "queue_path": str(d) }


def _resolve_expert_entry(repo: Path, expert_name: str) -> dict:
  """
  Return the expert settings block from `<repo>/.claude/lazy.settings.json`.

  An empty dict is returned when the expert is not registered — the
  resulting `config.json` then carries `agent: null` and the pump rejects
  the job with `config.json: missing agent`. Reporting the misconfiguration
  through the pump's per-job error response surfaces it where operators
  already expect to see job failures, rather than at dispatch time.

  Args:
    repo: Absolute path to the repository whose settings file is consulted.
    expert_name: Expert name as registered in `lazy.settings.json[experts]`.

  Returns:
    The settings dict for the named expert, or an empty dict when the
    expert is absent or stored as a non-dict value.
  """
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_section
  experts = load_section(Path(repo) / SettingsFile.REL, SettingsKey.EXPERTS)
  entry = experts.get(expert_name)
  return entry if isinstance(entry, dict) else {}


def resolve_agent_model(repo: Path, agent_ref: str | None) -> str | None:
  """
  Resolve the agent's model tier from the repository's project-scope settings only.

  Reads `agent_models` from `<repo>/.claude/lazy.settings.json` — the same file the
  expert block is read from, so the agent tier and expert entry always resolve from
  one scope — and is deliberately not merged with any global or user-scope settings.
  A tier outside the recognized set — including the `default` sentinel and any
  unknown string — resolves to None so the expert subprocess inherits the CLI
  default rather than a bogus pin.

  Args:
    repo: Absolute path to the repository whose settings file is consulted.
    agent_ref: The expert's `agent` dispatch string, or None when unset.

  Returns:
    The recognized tier (`haiku` / `sonnet` / `opus`) configured for the agent,
    or None when the agent is unconfigured, sentinel-routed, or `agent_ref` is
    None.
  """
  # guard: no agent ref — nothing to look up
  if not agent_ref:
    return None
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_section
  groups = load_section(Path(repo) / SettingsFile.REL, SettingsKey.AGENT_MODELS)
  tier: str | None = None
  # flatten grouped agent_models; on cross-group collision the last entry wins
  for entries in groups.values():
    # guard: non-dict group value is metadata (`_version`, etc.)
    if not isinstance(entries, dict):
      continue
    if agent_ref in entries:
      tier = entries[agent_ref]
  # guard: sentinel / unknown tier — treat as no explicit pin
  if tier not in _MODEL_TIERS:
    return None
  return tier


def _record_unpinned_model(repo: Path, expert: str, agent_ref: str | None, jdir: Path) -> None:
  """
  Record a best-effort `unpinned_model` incident when a dispatch resolves to no model pin.

  Folds repeated occurrences for the same expert into one open incident on the shared error
  ledger, surfacing the configuration gap without failing or blocking the dispatch itself.

  Args:
    repo: Absolute path to the repository whose error ledger receives the incident.
    expert: Expert name the incident is folded under.
    agent_ref: The expert's resolved agent dispatch string, or None when unset.
    jdir: Path to the job bundle the incident references.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import error_ledger
  error_ledger.record(Path(repo), {
    IncidentKey.INCIDENT: f"unpinned:{expert}",
    IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.UNPINNED_MODEL,
    # waiver: closed-set cause literal shared with the routine-error classifier, not a reusable domain key
    IncidentKey.CAUSE: "config_violation",
    IncidentKey.ACTOR: IncidentActor.DISPATCHER,
    # waiver: severity literal from the error-ledger CLI vocabulary (error|warn), not a domain constant
    IncidentKey.SEVERITY: "warn",
    IncidentKey.EXPERT: expert,
    IncidentKey.DETAIL: (
      f"dispatch without model pin: expert '{expert}' (agent {agent_ref!r}) inherits the CLI default model"
    ),
    IncidentKey.REFS: { "jdir": str(jdir) },
  })


def lookup_expert(target_repo: Path, name: str) -> dict | None:
  """
  Return the expert settings block for a same-plugin lookup.

  Convenience wrapper for same-plugin callers. Sibling plugins must use
  the `lookup-expert` CLI subcommand instead — direct cross-plugin Python
  imports are forbidden.

  Args:
    target_repo: Absolute path to the repository whose settings file is consulted.
    name: Expert name as registered in `lazy.settings.json[experts]`.

  Returns:
    The settings dict for the named expert, or None when the expert is
    absent or stored as a non-dict value.
  """
  entry = _resolve_expert_entry(Path(target_repo), name)
  return entry or None


def collect_job(repo: Path, expert: str, job_id: str) -> dict:
  """
  Return the current outcome of a dispatched job.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    job_id: Identifier of the dispatched job.

  Returns:
    `{status: "missing"}` when the bundle directory does not exist,
    `{status: "pending"}` when the pump has not produced `DONE`,
    `{status: "done", response}` when the response explicitly reports a
    finished outcome, `{status: "deferred", response}` when it reports the
    reserved deferred outcome, or `{status: "failed", response}` otherwise —
    including a response that violates the envelope by omitting `outcome`.
  """
  d = _job_dir(repo, expert, job_id)
  # guard: caller may poll before the bundle has been queued
  if not d.exists():
    return { JobCollectKey.STATUS: JobStatus.MISSING }
  # guard: pump has not finished processing yet
  if not (d / JobMarker.DONE).exists():
    return { JobCollectKey.STATUS: JobStatus.PENDING }
  resp = read_response(d)
  return { JobCollectKey.STATUS: classify_response(resp), JobCollectKey.RESPONSE: resp }


def list_jobs(
  repo: Path,
  *,
  expert: str | None = None,
  status: str | None = None,
) -> list[dict]:
  """
  Enumerate jobs in a repository's queue.

  Status enum: `queued` (READY only, no PID), `active` (READY + PID),
  `done` (DONE with a response reporting a finished outcome), `deferred`
  (DONE with the reserved deferred outcome — postponed work, input untouched),
  `failed` (DONE with any other response, error or envelope-violating),
  `dead` (DEAD marker present), `cancelled` (CANCELLED marker present).
  A deferred bundle answers neither the `done` nor the `failed` filter; ask
  for `deferred` explicitly to list postponed work.
  Bundles in none of these shapes are skipped.

  Args:
    repo: Absolute path to the repository whose queue is enumerated.
    expert: Restrict the listing to a single expert when provided.
    status: Restrict the listing to a single status value when provided.

  Returns:
    A list of job descriptors, each carrying `expert`, `job_id`, `path`, and `status`.
  """
  base = Path(repo) / JOBS_BASE
  out: list[dict] = []
  # guard: empty repo has no queue at all
  if not base.exists():
    return out
  experts = [ expert ] if expert else [ d.name for d in base.iterdir() if d.is_dir() ]
  for e in experts:
    edir = base / e
    # guard: expert filter may name a queue that has never seen a dispatch
    if not edir.exists():
      continue
    for jdir in edir.iterdir():
      # guard: skip stray files under the expert directory
      if not jdir.is_dir():
        continue
      entry_status = _job_status(jdir)
      # guard: bundle in an unrecognised shape is dropped from the listing
      if entry_status is None:
        continue
      entry = { JobCollectKey.EXPERT: e, JobCollectKey.JOB_ID: jdir.name, JobCollectKey.PATH: str(jdir),
                JobCollectKey.STATUS: entry_status }
      # guard: caller-supplied status filter eliminates non-matching bundles
      if status and entry[JobCollectKey.STATUS] != status:
        continue
      out.append(entry)
  return out


def _job_status(jdir: Path) -> str | None:
  """
  Classify a job-bundle directory into its current status value.

  Args:
    jdir: Path to the bundle directory to classify.

  Returns:
    `"cancelled"`, `"dead"`, `"failed"`, `"deferred"`, `"done"`, `"active"`,
    or `"queued"` when the bundle matches one of the recognised marker
    shapes, or None when the bundle is in an unrecognised shape.
  """
  # cancellation is a terminal operator decision — it outranks every other marker
  if (jdir / JobMarker.CANCELLED).exists():
    return JobStatus.CANCELLED
  if (jdir / JobMarker.DEAD).exists():
    return JobStatus.DEAD
  if (jdir / JobMarker.DONE).exists():
    return classify_response(read_response(jdir))
  if (jdir / JobMarker.READY).exists():
    if (jdir / JobMarker.PID).exists():
      return JobStatus.ACTIVE
    return JobStatus.QUEUED
  return None


def cancel_job(repo: Path, expert: str, job_id: str) -> None:
  """
  Cancel a job: stop its executor immediately and mark the bundle `CANCELLED`.

  The bundle directory (request, response, source, context, result,
  transcript) stays on disk for operator post-mortem; the standard
  cleanup window for failed jobs removes it later. The `READY` marker is
  removed and `CANCELLED` is placed, so the pump never picks the job up
  and the dedup key it may hold is released for a fresh dispatch.

  When the bundle carries a live `PID` marker (the pump worker that
  claimed the job), the worker's child process groups — the spawned
  executor runs in its own session — are terminated first, then the
  worker's own group, each with a SIGTERM → grace → SIGKILL escalation.

  Idempotent — calling on a non-existent or already-cancelled bundle is
  a no-op.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    job_id: Identifier of the job to cancel.
  """
  d = _job_dir(repo, expert, job_id)
  # guard: bundle never existed or was already removed
  if not d.exists():
    return
  # CANCELLED lands before the kill so a worker outcome-path racing the signal
  # finds the terminal marker already in place
  (d / JobMarker.CANCELLED).touch()
  pid_file = d / JobMarker.PID
  if pid_file.exists():
    try:
      pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
      pid = None
    if pid is not None:
      _stop_claimant(pid)
  (d / JobMarker.READY).unlink(missing_ok = True)


def _stop_claimant(pid: int) -> None:
  """
  Terminate a job's claimant worker and its spawned executor.

  The PID marker names the pump worker; the executor it spawned runs in
  its own session (separate process group), so killing the worker's
  group alone would orphan a still-running executor. Child pids are
  enumerated first (via `pgrep -P`), each child's group is torn down,
  then the worker's own group — every kill escalating SIGTERM → grace →
  SIGKILL.

  Args:
    pid: OS process id recorded in the bundle's PID marker.
  """
  # waiver: deferred / late-bound local imports per the plugin import style (avoids import cycles / optional deps)
  import os
  import subprocess
  # guard: claimant already gone — nothing left to signal (children were reparented; the
  # spawned executor exits on its own once its stdout consumer disappeared)
  try:
    os.kill(pid, 0)
  except (ProcessLookupError, PermissionError):
    return
  child_pids: list[int] = []
  try:
    out = subprocess.run(
      [ "pgrep", "-P", str(pid) ], capture_output = True, text = True,
      timeout = _PGREP_TIMEOUT_SEC, check = False,
    ).stdout
    child_pids = [ int(line) for line in out.split() if line.strip().isdigit() ]
  except (OSError, subprocess.TimeoutExpired):
    # ponytail: no pgrep on this host — fall through to killing the worker group only
    pass
  for target in [ *child_pids, pid ]:
    _kill_group(target)


def _kill_group(pid: int) -> None:
  """
  Terminate one process group with a SIGTERM → grace → SIGKILL escalation.

  Args:
    pid: Any process id inside the group to tear down.
  """
  # waiver: deferred / late-bound local imports per the plugin import style (avoids import cycles / optional deps)
  import os
  import signal
  # PermissionError ranks with ProcessLookupError throughout: a group we may not signal
  # (or a zombie-only group, which macOS reports as EPERM) is one we are done with
  try:
    pgid = os.getpgid(pid)
  except (ProcessLookupError, PermissionError):
    return
  try:
    os.killpg(pgid, signal.SIGTERM)
  except (ProcessLookupError, PermissionError):
    return
  deadline = time.time() + _CANCEL_KILL_GRACE_SEC
  while time.time() < deadline:
    # probe the GROUP, not the pid — an unreaped zombie keeps os.kill(pid, 0) succeeding
    # forever, which would burn the whole grace window on an already-dead executor
    try:
      os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
      return
    time.sleep(_KILL_POLL_SEC)
  # the grace window expired with the group still alive — SIGTERM was ignored, escalate to SIGKILL
  try:
    os.killpg(pgid, signal.SIGKILL)
  except (ProcessLookupError, PermissionError):
    pass


def consume_job(
  repo: Path, expert: str, job_id: str,
) -> None:
  """
  Mark a job's response as applied or explicitly discarded by its consumer.

  After this call, the job is invisible to two lookup paths: the
  pre-dispatch duplicate-detection check in `dispatch_job` no longer
  blocks fresh dispatches that share the same dedup key, and
  consumer-side lookups that scan job bundles by dedup key treat the
  job as if it were absent so a fresh dispatch happens on the next tick
  instead of re-reading the stale response.

  The bundle directory itself stays on disk until the standard cleanup
  TTL in the pump removes it; its forensic contents remain available
  for operator post-mortem during that window.

  Lifecycle separation: `DONE` is the producer-side signal (the pump
  wrote `response.json`) while `CONSUMED` is the consumer-side signal
  (whoever read the response is finished with it). They can land at
  different times; between DONE and CONSUMED the response is reachable
  to the consumer's lookup, and after CONSUMED it is no longer relevant
  for dedup or re-read.

  Idempotent — a second call on the same job is a no-op.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    job_id: Identifier of the job to retire.
  """
  d = _job_dir(repo, expert, job_id)
  # guard: caller may consume a job that no longer exists on disk
  if not d.exists():
    return
  (d / JobMarker.CONSUMED).touch()


def retire_completed_jobs(
  repo: Path, expert: str, dedup_key: str,
) -> list[str]:
  """
  Retire every completed job bundle that shares the given dedup key.

  Marks each matching finished job as consumed so a later dispatch for the
  same key is no longer refused as already-queued. A fire-and-forget
  dispatcher whose jobs no other party consumes calls this before it
  re-dispatches, so a finished prior attempt stops blocking the retry.
  In-flight bundles, bundles already retired, and bundles marked dead are
  left untouched.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    dedup_key: Dedup key whose finished bundles are retired.

  Returns:
    The ids of the retired jobs, in directory-iteration order.
  """
  retired: list[str] = []
  edir = Path(repo) / JOBS_BASE / expert
  # guard: no bundles for this expert yet — nothing to retire
  if not edir.exists():
    return retired
  for jdir in edir.iterdir():
    # guard: skip non-directory entries that may appear under the expert dir
    if not jdir.is_dir():
      continue
    # guard: only finished bundles are eligible — never retire an in-flight job
    if not (jdir / JobMarker.DONE).exists():
      continue
    # guard: bundle already retired by a prior consumer pass
    if (jdir / JobMarker.CONSUMED).exists():
      continue
    # guard: dead bundles are the dead-job collector's responsibility
    if (jdir / JobMarker.DEAD).exists():
      continue
    req_file = jdir / JobFile.REQUEST
    # guard: bundle missing request.json is malformed and cannot match
    if not req_file.exists():
      continue
    try:
      existing = json.loads(req_file.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    if existing.get(JobRequestKey.DEDUP_KEY) == dedup_key:
      consume_job(repo, expert, jdir.name)
      retired.append(jdir.name)
  return retired


def completed_dedup_jobs(repo: Path, expert: str) -> list[dict]:
  """
  List finished, unconsumed bundles for an expert that carry a dedup key.

  Returns one entry per bundle whose `DONE` marker is present, that has not
  been consumed, and that is not marked dead, carrying its `job_id`, its
  `dedup_key`, its `dedup_fingerprint` (the token recorded at dispatch, or
  `None` for a bundle dispatched before the field existed), its `status`
  (`done` only when the response explicitly reports a finished outcome,
  `deferred` when it reports the reserved deferred outcome, `failed` for
  every other response), the error `category` of a failed bundle, and the
  `age_sec` elapsed since the bundle finished. In-flight bundles, dead
  bundles, already-consumed bundles, and bundles without a dedup key are
  omitted.

  A dispatcher that keeps the source artifact outside the bundle (the inbox
  routine) reconciles finished work against its input store with this: drain
  the input whose job succeeded, leave the input whose job failed parked
  behind its still-unconsumed bundle so the dedup key keeps it from being
  re-dispatched. Success is never inferred from silence — a response that
  omits its outcome counts as failed, so an input is destroyed only against
  an explicit success. The category and the age let such a dispatcher
  separate a permanent dead-letter from a spawn-level fault worth retrying.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.

  Returns:
    A list of `{job_id, dedup_key, dedup_fingerprint, status, category, age_sec}` dicts in
    directory-iteration order.
  """
  out: list[dict] = []
  edir = Path(repo) / JOBS_BASE / expert
  # guard: no bundles for this expert yet
  if not edir.exists():
    return out
  for jdir in edir.iterdir():
    # guard: skip non-directory entries that may appear under the expert dir
    if not jdir.is_dir():
      continue
    # guard: only finished bundles are reconcilable
    if not (jdir / JobMarker.DONE).exists():
      continue
    # guard: already retired by a prior reconcile pass
    if (jdir / JobMarker.CONSUMED).exists():
      continue
    # guard: dead bundles are the dead-job collector's responsibility
    if (jdir / JobMarker.DEAD).exists():
      continue
    req_file = jdir / JobFile.REQUEST
    # guard: bundle missing request.json is malformed and carries no key
    if not req_file.exists():
      continue
    try:
      req = json.loads(req_file.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    dedup_key = req.get(JobRequestKey.DEDUP_KEY)
    # guard: only keyed bundles are reconcilable against an external input store
    if dedup_key is None:
      continue
    resp = read_response(jdir)
    error = resp.get(JobResponseKey.ERROR)
    category = error.get(JobResponseKey.CATEGORY) if isinstance(error, dict) else None
    # the DONE marker is stamped when the pump wrote the response — the bundle's finish time
    out.append({
      JobCollectKey.JOB_ID:    jdir.name,
      JobCollectKey.DEDUP_KEY: dedup_key,
      # absent on bundles dispatched before fingerprints existed — consumers read that as "unknown"
      JobCollectKey.DEDUP_FINGERPRINT: req.get(JobRequestKey.DEDUP_FINGERPRINT),
      JobCollectKey.STATUS:    classify_response(resp),
      JobCollectKey.CATEGORY:  category,
      JobCollectKey.AGE_SEC:   max(0.0, time.time() - (jdir / JobMarker.DONE).stat().st_mtime),
    })
  return out


def register_routine(repo: Path, name: str, cfg: dict | None = None, *,
                     command: list[str] | None = None,
                     interval_sec: int | None = None,
                     timeout_sec: int | None = None,
                     priority: int | None = None,
                     ignore_halt: bool | None = None,
                     hooks_enabled: list[str] | None = None) -> None:
  """
  Persist a routine entry under the `routines` section.

  Two call shapes are supported. The typed shape passes a fully-formed
  `cfg` dict (with `type`, type-specific keys, and an optional shared
  block) and is the form used by every modern caller. The legacy shape
  passes `command` + `interval_sec` keyword arguments and is treated as
  equivalent to `type = "subprocess"`.

  Either way the cfg is validated via `validate_routine_entry` before
  being written. The routine entry is persisted to the tracked
  `lazy.settings.json` so local-overlay routine entries are not leaked
  into the shared file on save.

  Args:
    repo: Absolute path to the repository whose settings file is updated.
    name: Routine name to register.
    cfg: Fully-formed routine config dict for the typed call shape.
    command: Subprocess command argv for the legacy call shape.
    interval_sec: Tick interval in seconds for the legacy call shape.
    timeout_sec: Optional per-tick timeout passed through to the cfg.
    priority: Ascending per-tick execution order; lower runs earlier;
      defaults to 100 when unset.
    ignore_halt: When true the routine runs even when the daemon is
      halted or the working tree is dirty — intended for recovery
      routines such as `lazy-runtime.doctor`.
    hooks_enabled: Short names of the lazycortex hooks allowed to run inside
      anything this routine spawns; absent leaves every hook silent.

  Raises:
    TypeError: When neither a typed `cfg` nor the legacy
      `command` + `interval_sec` pair is supplied.
  """
  # waiver: deferred import — avoid module-load cycle with routine_types
  from routine_types import validate_routine_entry
  if cfg is None:
    # guard: legacy shape requires both command and interval_sec
    if command is None or interval_sec is None:
      raise TypeError(
        "register_routine: pass `cfg` (typed shape), "
        "or pass `command` + `interval_sec` (legacy subprocess shape)"
      )
    cfg = { RoutineKey.COMMAND: list(command), RoutineKey.INTERVAL_SEC: interval_sec }
    if timeout_sec is not None:
      cfg[RoutineKey.TIMEOUT_SEC] = timeout_sec
  if priority is not None:
    cfg[RoutineKey.PRIORITY] = priority
  if ignore_halt is not None:
    cfg[RoutineKey.IGNORE_HALT] = ignore_halt
  if hooks_enabled is not None:
    cfg[RoutineKey.HOOKS_ENABLED] = list(hooks_enabled)
  validate_routine_entry(name, cfg)
  # load_tracked_section keeps local-overlay routine entries out of the
  # tracked file on save_section
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_tracked_section, save_section
  settings = Path(repo) / SettingsFile.REL
  routines = load_tracked_section(settings, SettingsKey.ROUTINES)
  routines[name] = cfg
  save_section(settings, SettingsKey.ROUTINES, routines)


PROTECTED_ROUTINES = { "lazy-expert.pump", "lazy-runtime.doctor" }


def unregister_routine(repo: Path, name: str) -> None:
  """
  Remove a routine entry from the `routines` section.

  Built-in routines required by the expert runtime cannot be removed
  through this entry point — uninstall the plugin instead.

  Args:
    repo: Absolute path to the repository whose settings file is updated.
    name: Routine name to remove.

  Raises:
    ValueError: When `name` matches a protected built-in routine.
  """
  # guard: protected routines may only be removed by uninstalling the plugin
  if name in PROTECTED_ROUTINES:
    raise ValueError(
      f"cannot unregister built-in routine: {name}. "
      f"It is required by the expert runtime; uninstall the plugin instead."
    )
  # load_tracked_section: same reasoning as register_routine — only the
  # tracked layer participates in the load → modify → save round-trip
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_tracked_section, save_section
  settings = Path(repo) / SettingsFile.REL
  routines = load_tracked_section(settings, SettingsKey.ROUTINES)
  routines.pop(name, None)
  save_section(settings, SettingsKey.ROUTINES, routines)


DEFAULT_EXPERT_PUMP: _RoutineDefaults = {
  "name":         "lazy-expert.pump",
  "command":      [ "lazycortex-core", "expert-pump-once" ],
  "interval_sec": 5,
  # pump processes at most one Claude spawn per invocation; the daemon kills
  # the pump (and the Claude child) after this many seconds. Subsequent jobs
  # land on subsequent pump ticks. The 30-min ceiling accommodates long-running
  # specialists (historian / interpreter on rich documents); raise further
  # only when consistently hitting timeout in normal operation.
  "timeout_sec":  1800,
  # slow Claude spawns — runs last in each tick
  "priority":     100,

  # Decision: the secret scan runs in expert spawns, the rest of the hooks do not — the
  # hermetic default exists because `check-public` and `git-guard` cost tens of seconds per
  # tool call, but a secret an autonomous expert commits has nobody watching for it.

  "hooks_enabled": [ HookName.SECRETS_GUARD ],
}

# Hourly trigger for the autonomous doctor: scans for DEAD job dirs OR a
# halt-block ≥ 1h old, and dispatches a `runtime.doctor` expert job
# when something needs attention. The Python tick is intentionally dumb —
# all reasoning (revert vs commit vs permanent-fail) belongs to the agent.
DEFAULT_DOCTOR_TICK: _RoutineDefaults = {
  "name":         "lazy-runtime.doctor",
  "command":      [ "lazycortex-core", "doctor-tick" ],
  "interval_sec": 3600,
  "timeout_sec":  60,
  # fast, runs before pump
  "priority":     30,
  # MUST run during halt — exists to fix stuck state
  "ignore_halt":  True,
}

# Weekly LLM-tier sanitizer (state-sanitizers-design's second tier): dispatches one
# `core.autocheckup` expert job that runs the domain doctors and applies only its
# mechanically-derivable whitelist. Typed (`schedule` + `expert`) shape, which the legacy
# `_RoutineDefaults` TypedDict cannot express; `repo` resolves against the job's own cwd —
# the pump spawns every job inside the repository it serves.
DEFAULT_AUTOCHECKUP_NAME = "lazy-core.autocheckup"

# The routine key and the expert it dispatches are two different registries, so they carry two
# different canonical shapes (`lazy-core.hygiene` § Naming): the routine belongs to this plugin and
# wears its namespace, the expert key names a domain and a role and never does.
DEFAULT_AUTOCHECKUP_EXPERT = "core.autocheckup"
DEFAULT_AUTOCHECKUP_CFG: dict = {
  "type":    "schedule",
  "cron":    "0 6 * * 1",
  "expert":  DEFAULT_AUTOCHECKUP_EXPERT,
  "request": { "repo": "." },
}


def _backfill_defaults(repo: Path, entry: _RoutineDefaults, existing: dict) -> None:
  """
  Add default keys a registered built-in routine predates, leaving every set value intact.

  A repository installed before a default gained a key keeps the old shape forever
  otherwise: the routine exists, so registration skips it, and nothing else ever revisits
  the entry.

  Args:
    repo: Absolute path to the repository whose settings file is updated.
    entry: The built-in routine's default config block.
    existing: The routine config as it stands in the tracked settings layer.

  Raises:
    RoutineConfigError: When the merged entry fails schema validation — a pre-existing
      malformed built-in entry surfaces here instead of at the routine's next tick.
  """
  # Contract: a key the entry already carries is never rewritten, whatever its value —
  # `hooks_enabled: []` is an operator's answer, not a gap to fill.

  # only keys absent from the registered entry are candidates
  # waiver: TypedDict iteration yields its own string-literal keys; `name` is the registry key,
  # not part of the config body
  missing = { k: v for k, v in entry.items() if k != "name" and k not in existing }
  # guard: the registered entry already carries every default key
  if not missing:
    return

  # the merged entry is re-validated on write, so a default that no longer fits the schema
  # surfaces here rather than at the routine's next tick
  # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
  register_routine(repo, str(entry["name"]), { **existing, **missing })


def bootstrap_default_routines(repo: Path) -> None:
  """
  Register the built-in expert-pump, doctor-tick, and autocheckup routines when absent.

  Idempotent — never overwrites a value an existing routine already carries. A key the
  defaults gained after the routine was first registered is filled in, since a repository
  installed before that key existed would otherwise never receive it; a key the operator
  has set, to any value including an empty one, is left alone. Intended to be called from
  the plugin install skill so the built-in routines exist and stay current after every
  fresh install or update.

  Args:
    repo: Absolute path to the repository whose settings file is updated.
  """
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_section, load_tracked_section
  settings = Path(repo) / SettingsFile.REL
  # two views, two questions: the merged one answers "is this routine configured at all",
  # the tracked one is the only safe basis for a write-back — merging the overlay in and
  # saving would copy the operator's private values into the shared file
  merged = load_section(settings, SettingsKey.ROUTINES)
  tracked = load_tracked_section(settings, SettingsKey.ROUTINES)
  for entry in (DEFAULT_EXPERT_PUMP, DEFAULT_DOCTOR_TICK):
    # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
    name = entry["name"]
    # guard: configured only in the local overlay — writing the tracked layer would leave the
    # repository carrying the routine twice, so the operator's own copy is left to them
    if name in merged and name not in tracked:
      continue
    # guard: already tracked — fill only what the defaults gained since, never a set value
    if name in tracked:
      _backfill_defaults(repo, entry, tracked[name])
      continue
    register_routine(
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      repo, entry["name"],
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      command = entry["command"],
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      interval_sec = entry["interval_sec"],
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      timeout_sec = entry["timeout_sec"],
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      priority = entry.get("priority"),
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      hooks_enabled = entry.get("hooks_enabled"),
      # waiver: TypedDict access requires string-literal keys; constants break mypy literal-required
      ignore_halt = entry.get("ignore_halt"),
    )

  # the weekly autocheckup rides the same absent-only / backfill discipline as the loop above,
  # in the typed (`schedule` + `expert`) shape the legacy loop cannot carry
  # guard: configured only in the local overlay — writing the tracked layer would leave the
  # repository carrying the routine twice, so the operator's own copy is left to them
  if DEFAULT_AUTOCHECKUP_NAME in merged and DEFAULT_AUTOCHECKUP_NAME not in tracked:
    return

  # guard: already tracked — fill only the default keys the entry predates, never a set value
  if DEFAULT_AUTOCHECKUP_NAME in tracked:
    missing = {
        key: value for key, value in DEFAULT_AUTOCHECKUP_CFG.items()
        if key not in tracked[DEFAULT_AUTOCHECKUP_NAME]
    }
    if missing:
      register_routine(repo, DEFAULT_AUTOCHECKUP_NAME, { **tracked[DEFAULT_AUTOCHECKUP_NAME], **missing })
    return

  # fresh registration — the defaults land whole
  register_routine(repo, DEFAULT_AUTOCHECKUP_NAME, dict(DEFAULT_AUTOCHECKUP_CFG))
