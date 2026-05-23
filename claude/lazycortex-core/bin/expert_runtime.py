"""
Public helpers for dispatching and collecting jobs in the expert runtime.

Owns the on-disk layout of `<repo>/.experts/.jobs/<expert>/<job_id>/` (the
per-job bundle the pump consumes) and `<repo>/.experts/.remote-jobs/...`
(cross-repo visibility trackers). Every state-mutating operation in this
module is the atomic primitive a caller in another plugin reaches for via
the `lazycortex-core` CLI (`dispatch-job`, `collect-job`, `lookup-expert`,
`consume-job`) — never via direct Python import.
"""
from __future__ import annotations
import json, shutil, time, uuid
from pathlib import Path
from typing import Iterable

JOBS_BASE = ".experts/.jobs"


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


def dispatch_job(
  repo: Path,
  expert: str,
  payload: dict,
  *,
  protocols: list[str] | None = None,
  source: dict[str, str] | None = None,
  context: dict[str, str] | None = None,
  result: list[str] | None = None,
  job_id: str | None = None,
  dedup_key: str | None = None,
  dispatched_from: Path | None = None,
) -> dict:
  """
  Create one job bundle atomically and queue it for the pump.

  Writes the full job directory (`request.json`, `config.json`, optional
  `source/`, `context/`, `result/`) in pump-safe order and touches the
  `READY` marker last so the pump never observes a partial bundle.

  When `dedup_key` is set and an active job for the same `(expert, key)`
  pair already exists, no new bundle is written and `already-queued` is
  returned. An "active" job is one with `READY` present and neither
  `DEAD` nor `CONSUMED` markers — a job that has `response.json` (DONE)
  but no `CONSUMED` is still active for dedup purposes.

  When the dispatching repo differs from `repo` and the dispatching
  repo's `lazy.settings.json[repos]` registers `repo` by path, a tracker
  is also written under
  `<dispatched_from>/.experts/.remote-jobs/<label>/<expert>/<job_id>.json`
  so the originating repo can observe in-flight remote jobs. Callers
  that do not appear in the registry naturally skip the tracker step.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    payload: JSON-serializable request body written as `request.json`.
    protocols: References the agent reads at spawn time; populated from
      the dispatching routine's protocol field for generic agents and
      left empty for self-contained agents.
    source: Mapping of filename to text written under `<job_dir>/source/`.
    context: Mapping of filename to text written under `<job_dir>/context/`.
    result: Filenames created as empty placeholders under
      `<job_dir>/result/` for the agent to fill.
    job_id: Caller-computed deterministic identifier; a 12-hex slice of
      a fresh UUID is used when omitted.
    dedup_key: When set, embedded in the payload as `_dedup_key` and
      short-circuits to `already-queued` on a pre-existing match.
    dispatched_from: Override of the dispatching repository path; the
      current working directory is used when omitted.

  Returns:
    `{job_id, queue_path}` on a fresh dispatch, or
    `{job_id, status: "already-queued"}` on a dedup hit.
  """
  # dedup short-circuit: scan existing job bundles for a live `_dedup_key` match
  if dedup_key is not None:
    edir = Path(repo) / JOBS_BASE / expert
    if edir.exists():
      for jdir in edir.iterdir():
        # guard: skip non-directory entries that may appear under the expert dir
        if not jdir.is_dir():
          continue
        # guard: pre-READY bundles are not yet active
        if not (jdir / "READY").exists():
          continue
        # guard: DEAD bundles are not eligible for dedup
        if (jdir / "DEAD").exists():
          continue
        # guard: CONSUMED bundles have been retired by the consumer
        if (jdir / "CONSUMED").exists():
          continue
        req_file = jdir / "request.json"
        # guard: bundle missing request.json is malformed and cannot match
        if not req_file.exists():
          continue
        try:
          existing = json.loads(req_file.read_text())
        except (OSError, json.JSONDecodeError):
          continue
        if existing.get("_dedup_key") == dedup_key:
          return { "job_id": jdir.name, "status": "already-queued" }

  # resolve expert settings before any filesystem mutation so a misconfigured
  # expert surfaces at dispatch time rather than after partial setup
  expert_entry = _resolve_expert_entry(repo, expert)

  job_id = job_id or uuid.uuid4().hex[:12]
  d = _job_dir(repo, expert, job_id)
  # park any prior DEAD bundle at the same slot before reusing it — without
  # this the new job would coexist with the stale DEAD marker and the pump
  # would skip it as a zombie
  if d.exists() and (d / "DEAD").exists():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    d.rename(d.with_name(f"{job_id}.dead-{stamp}"))
  d.mkdir(parents = True, exist_ok = True)

  # auxiliary work files: each bucket dir holds caller-supplied filenames
  # as single segments (no nesting under buckets)
  if source:
    (d / "source").mkdir(exist_ok = True)
    for fname, text in source.items():
      (d / "source" / fname).write_text(text)
  if context:
    (d / "context").mkdir(exist_ok = True)
    for fname, text in context.items():
      (d / "context" / fname).write_text(text)
  if result:
    (d / "result").mkdir(exist_ok = True)
    for fname in result:
      (d / "result" / fname).touch()

  # config.json derived purely from settings.experts[<expert>] plus the
  # caller-supplied protocols list; pump reads this at spawn time
  cfg_blob = {
    "agent":             expert_entry.get("agent"),
    "protocols":         list(protocols or []),
    "aspects":           list(expert_entry.get("aspects") or []),
    "arguments":         dict(expert_entry.get("arguments") or {}),
    "git_author":        expert_entry.get("git_author", {}),
    "model":             expert_entry.get("model"),
    "can_commit_in_repo": bool(expert_entry.get("can_commit_in_repo", False)),
  }
  (d / "config.json").write_text(json.dumps(cfg_blob, indent = 2))

  out_payload = dict(payload)
  if dedup_key is not None:
    out_payload["_dedup_key"] = dedup_key
  (d / "request.json").write_text(json.dumps(out_payload, indent = 2))

  # READY touched LAST — atomic activation marker; pump treats READY presence
  # as "every other file in this bundle is valid and you can spawn now"
  (d / "READY").touch()

  # cross-repo tracker: visibility-only entry for the dispatching repo. The
  # local pump never scans `.remote-jobs/`. Gated by the dispatching repo's
  # `lazy.settings.json[repos]` — repos absent from the registry naturally
  # skip without special test plumbing.
  import os as _os
  local = Path(dispatched_from or _os.getcwd()).resolve()
  target = Path(repo).resolve()
  if local != target:
    # waiver: deferred import — avoid module-load cycle with repo_resolver
    from repo_resolver import reverse_lookup
    label = reverse_lookup(local, target)
    if label is not None:
      tracker_dir = local / ".experts" / ".remote-jobs" / label / expert
      tracker_dir.mkdir(parents = True, exist_ok = True)
      tracker_payload = {
        "target_repo":   label,
        "abs_path":      str(d),
        "expert":        expert,
        "dispatched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dedup_key":     dedup_key,
      }
      (tracker_dir / f"{job_id}.json").write_text(
        json.dumps(tracker_payload, indent = 2)
      )

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
  experts = load_section(Path(repo) / ".claude/lazy.settings.json", "experts")
  entry = experts.get(expert_name)
  return entry if isinstance(entry, dict) else {}


def lookup_expert(target_repo: Path, name: str) -> dict | None:
  """
  Return the expert settings block for a same-plugin lookup.

  Same-plugin convenience wrapper over `_resolve_expert_entry`. Sibling
  plugins must use the `lookup-expert` CLI subcommand instead — direct
  cross-plugin Python imports are forbidden.

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
    `{status: "failed", response}` when the response outcome is `error`,
    or `{status: "done", response}` otherwise.
  """
  d = _job_dir(repo, expert, job_id)
  # guard: caller may poll before the bundle has been queued
  if not d.exists():
    return { "status": "missing" }
  # guard: pump has not finished processing yet
  if not (d / "DONE").exists():
    return { "status": "pending" }
  resp = json.loads((d / "response.json").read_text()) if (d / "response.json").exists() else {}
  status = "failed" if resp.get("outcome") == "error" else "done"
  return { "status": status, "response": resp }


def list_jobs(
  repo: Path,
  *,
  expert: str | None = None,
  status: str | None = None,
  include_remote: bool = False,
) -> list[dict]:
  """
  Enumerate jobs in a repository's queue, optionally including remote trackers.

  Status enum: `queued` (READY only, no PID), `active` (READY + PID),
  `done` (DONE without error outcome), `failed` (DONE with error outcome),
  `dead` (DEAD marker present). Bundles in none of these shapes are
  skipped.

  When `include_remote` is true, every tracker under
  `<repo>/.experts/.remote-jobs/<label>/<expert>/*.json` is also followed
  to the foreign job directory; the entry's status reflects the live
  state of the remote bundle and carries an extra `target_repo` field.

  Args:
    repo: Absolute path to the repository whose queue is enumerated.
    expert: Restrict the listing to a single expert when provided.
    status: Restrict the listing to a single status value when provided.
    include_remote: Also enumerate cross-repo tracker entries when true.

  Returns:
    A list of job descriptors. Local entries carry `expert`, `job_id`,
    `path`, and `status`; remote entries additionally carry `target_repo`
    and `dispatched_at`.
  """
  base = Path(repo) / JOBS_BASE
  out = []
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
      entry = { "expert": e, "job_id": jdir.name, "path": str(jdir),
                "status": entry_status }
      # guard: caller-supplied status filter eliminates non-matching bundles
      if status and entry["status"] != status:
        continue
      out.append(entry)
  if include_remote:
    remote_base = Path(repo) / ".experts" / ".remote-jobs"
    if remote_base.exists():
      for target_dir in remote_base.iterdir():
        # guard: skip stray files under the remote-jobs root
        if not target_dir.is_dir():
          continue
        for expert_dir in target_dir.iterdir():
          # guard: skip stray files under each target-label directory
          if not expert_dir.is_dir():
            continue
          # guard: expert filter applies to remote entries too
          if expert and expert_dir.name != expert:
            continue
          for tracker_file in expert_dir.iterdir():
            # guard: only tracker JSON payloads are considered
            if tracker_file.suffix != ".json":
              continue
            try:
              tracker = json.loads(tracker_file.read_text())
            except (OSError, json.JSONDecodeError):
              continue
            abs_job = Path(tracker.get("abs_path", ""))
            live = _job_status(abs_job) if abs_job.exists() else "missing"
            entry = {
              "expert":        expert_dir.name,
              "job_id":        tracker_file.stem,
              "path":          str(abs_job),
              "status":        live or "missing",
              "target_repo":   target_dir.name,
              "dispatched_at": tracker.get("dispatched_at"),
            }
            # guard: caller-supplied status filter applies to remote entries
            if status and entry["status"] != status:
              continue
            out.append(entry)
  return out


def _job_status(jdir: Path) -> str | None:
  """
  Classify a job-bundle directory into its current status value.

  Args:
    jdir: Path to the bundle directory to classify.

  Returns:
    `"dead"`, `"failed"`, `"done"`, `"active"`, or `"queued"` when the
    bundle matches one of the recognised marker shapes, or None when
    the bundle is in an unrecognised shape.
  """
  if (jdir / "DEAD").exists():
    return "dead"
  if (jdir / "DONE").exists():
    resp_path = jdir / "response.json"
    if resp_path.exists():
      try:
        outcome = json.loads(resp_path.read_text()).get("outcome")
        if outcome == "error":
          return "failed"
      except json.JSONDecodeError:
        pass
    return "done"
  if (jdir / "READY").exists():
    if (jdir / "PID").exists():
      return "active"
    return "queued"
  return None


def cancel_job(repo: Path, expert: str, job_id: str) -> None:
  """
  Remove a job bundle from disk.

  Idempotent — calling on a non-existent bundle is a no-op. The entire
  bundle directory (request, response, source, context, result) is
  removed, so forensic contents are not retained.

  Args:
    repo: Absolute path to the repository that hosts the job queue.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    job_id: Identifier of the job to remove.
  """
  d = _job_dir(repo, expert, job_id)
  if d.exists():
    shutil.rmtree(d)


def consume_job(
  repo: Path, expert: str, job_id: str,
  *, dispatched_from: Path | None = None,
) -> None:
  """
  Mark a job's response as applied or explicitly discarded by its consumer.

  After this call, the job is invisible to two lookup paths: the
  pre-dispatch `already-queued` check in `dispatch_job` no longer
  blocks fresh dispatches that share the same `dedup_key`, and
  consumer-side lookups that scan job bundles by `_dedup_key` treat the
  job as if it were absent so a fresh dispatch happens on the next tick
  instead of re-reading the stale response.

  The bundle directory itself stays on disk until the standard cleanup
  TTL in the pump removes it; its forensic contents remain available
  for operator post-mortem during that window.

  When the dispatching repo's `lazy.settings.json[repos]` registers
  `repo` by path, the cross-repo tracker file at
  `<dispatched_from>/.experts/.remote-jobs/<label>/<expert>/<job_id>.json`
  is removed so the originating repo no longer lists the job as
  in-flight. Symmetric with the tracker write in `dispatch_job` — same
  gating, same default of the current working directory for the
  dispatching repo.

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
    dispatched_from: Override of the dispatching repository path; the
      current working directory is used when omitted.
  """
  d = _job_dir(repo, expert, job_id)
  # guard: caller may consume a job that no longer exists on disk
  if not d.exists():
    return
  (d / "CONSUMED").touch()
  import os as _os
  local = Path(dispatched_from or _os.getcwd()).resolve()
  target = Path(repo).resolve()
  if local != target:
    # waiver: deferred import — avoid module-load cycle with repo_resolver
    from repo_resolver import reverse_lookup
    label = reverse_lookup(local, target)
    if label is not None:
      tracker = (
        local / ".experts" / ".remote-jobs"
        / label / expert / f"{job_id}.json"
      )
      if tracker.exists():
        tracker.unlink()


def register_routine(repo: Path, name: str, cfg: dict | None = None, *,
                     command: list[str] | None = None,
                     interval_sec: int | None = None,
                     timeout_sec: int | None = None,
                     priority: int | None = None,
                     ignore_halt: bool | None = None) -> None:
  """
  Persist a routine entry under `lazy-core.runtime.routines`.

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
    cfg = { "command": list(command), "interval_sec": interval_sec }
    if timeout_sec is not None:
      cfg["timeout_sec"] = timeout_sec
  if priority is not None:
    cfg["priority"] = priority
  if ignore_halt is not None:
    cfg["ignore_halt"] = ignore_halt
  validate_routine_entry(name, cfg)
  # load_tracked_section keeps local-overlay routine entries out of the
  # tracked file on save_section
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_tracked_section, save_section
  settings = Path(repo) / ".claude/lazy.settings.json"
  routines = load_tracked_section(settings, "routines")
  routines[name] = cfg
  save_section(settings, "routines", routines)


PROTECTED_ROUTINES = { "lazy-expert.pump", "lazy-runtime.doctor" }


def unregister_routine(repo: Path, name: str) -> None:
  """
  Remove a routine entry from `lazy-core.runtime.routines`.

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
  settings = Path(repo) / ".claude/lazy.settings.json"
  routines = load_tracked_section(settings, "routines")
  routines.pop(name, None)
  save_section(settings, "routines", routines)


DEFAULT_EXPERT_PUMP = {
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
}

# Hourly trigger for the autonomous doctor: scans for DEAD job dirs OR a
# halt-block ≥ 1h old, and dispatches a `lazy-runtime.doctor` expert job
# when something needs attention. The Python tick is intentionally dumb —
# all reasoning (revert vs commit vs permanent-fail) belongs to the agent.
DEFAULT_DOCTOR_TICK = {
  "name":         "lazy-runtime.doctor",
  "command":      [ "lazycortex-core", "doctor-tick" ],
  "interval_sec": 3600,
  "timeout_sec":  60,
  # fast, runs before pump
  "priority":     30,
  # MUST run during halt — exists to fix stuck state
  "ignore_halt":  True,
}


def bootstrap_default_routines(repo: Path) -> None:
  """
  Register the built-in expert-pump and doctor-tick routines when absent.

  Idempotent — does not overwrite user-modified config for an existing
  routine. Intended to be called from the plugin install skill so the
  built-in routines exist after every fresh install or update.

  Args:
    repo: Absolute path to the repository whose settings file is updated.
  """
  # waiver: deferred import — avoid module-load cycle with lazy_settings
  from lazy_settings import load_section
  settings = Path(repo) / ".claude/lazy.settings.json"
  routines = load_section(settings, "routines")
  for entry in (DEFAULT_EXPERT_PUMP, DEFAULT_DOCTOR_TICK):
    # guard: never overwrite a user-modified existing routine
    if entry["name"] in routines:
      continue
    register_routine(
      repo, entry["name"],
      command = entry["command"],
      interval_sec = entry["interval_sec"],
      timeout_sec = entry["timeout_sec"],
      priority = entry.get("priority"),
      ignore_halt = entry.get("ignore_halt"),
    )
