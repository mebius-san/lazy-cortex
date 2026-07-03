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
import shutil
import subprocess
import sys
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
from constants import (
  HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase, IncidentState,
  JobArtifact, JobConfigKey, JobErrorCategory, JobFile, JobMarker, JobOutcome, JobRequestKey, JobResponseKey,
  RuntimeFile, SettingsFile, SettingsKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


JOBS_BASE = ".experts/.jobs"


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
  JobMarker.READY, JobMarker.PID, JobFile.REQUEST, JobMarker.DEAD, JobArtifact.DEAD_JSON,
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

  try:
    original_pid = int((jdir / JobMarker.PID).read_text().strip())
  except (OSError, ValueError):
    original_pid = -1

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


def _detect_dead_jobs(repo: Path) -> int:
  """
  Scan all job directories and mark stuck jobs as dead.

  A job is considered stuck when it has been claimed (READY + PID present), has no
  response.json or DONE marker, is not already marked DEAD, and its recorded PID is
  no longer alive. Each newly-stuck job receives a DEAD marker and a dead.json payload.

  Args:
    repo: Repository root containing the expert job tree.

  Returns:
    The number of jobs newly marked dead in this scan.
  """
  base = Path(repo) / JOBS_BASE
  # guard: nothing to scan when the jobs root has not been created yet
  if not base.exists():
    return 0

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
      # guard: job already produced a response — nothing to mark
      if (jdir / JobFile.RESPONSE).exists():
        continue
      # guard: job already DONE — terminal state reached
      if (jdir / JobMarker.DONE).exists():
        continue
      # guard: job already DEAD — skip to keep idempotent
      if (jdir / JobMarker.DEAD).exists():
        continue
      # guard: no PID file — job is queued, not claimed
      if not (jdir / JobMarker.PID).exists():
        continue

      try:
        pid_text = (jdir / JobMarker.PID).read_text().strip()
        pid = int(pid_text)
        alive = _pid_alive(pid)
      except (OSError, ValueError):
        alive = False

      # guard: claimant process is still running — leave the job alone
      if alive:
        continue

      blob = _build_dead_json(jdir, edir.name, jdir.name, time.time())
      (jdir / JobArtifact.DEAD_JSON).write_text(json.dumps(blob, indent = 2))
      (jdir / JobMarker.DEAD).touch()
      # waiver: small internal subkey, not a reusable domain key
      cause = blob.get("likely_cause", "unknown")
      error_ledger.record(repo, {
        IncidentKey.INCIDENT: f"job:{edir.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
        IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: cause, IncidentKey.ACTOR: IncidentActor.PUMP,
        IncidentKey.EXPERT: edir.name, IncidentKey.JOB_ID: jdir.name, IncidentKey.DETAIL: f"job DEAD: {cause}",
        IncidentKey.REFS: { "jdir": str(jdir), "dead_json": str(jdir / JobArtifact.DEAD_JSON) },
      })
      marked += 1

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


def pump(repo: Path) -> dict:
  """
  Run one pump tick over the expert-job queue.

  The tick performs three actions in sequence: garbage-collect expired job
  directories, mark jobs whose claimant process has died, then process at most one
  READY job (lexicographically first across all expert directories). The single-spawn
  ceiling matters because the daemon's per-routine timeout is the only bound on a
  Claude subprocess.

  Args:
    repo: Repository root containing the expert job tree.

  Returns:
    A summary dict with counts of experts seen, jobs processed, jobs cleaned, jobs newly
    marked dead, and — when a halt fired — the offending expert and job_id.
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
  detected_dead = _detect_dead_jobs(repo)

  jobs_root = repo / JOBS_BASE
  # guard: no jobs tree on disk yet — return early summary
  if not jobs_root.exists():
    return { "experts": 0, "processed": 0, "cleaned": 0, "detected_dead": detected_dead }

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
      )
      # guard: only collect actually-ready jobs into the FIFO queue
      if not ready:
        continue
      ready_candidates.append((ready_marker.stat().st_mtime, name, jdir))
  # guard: no ready jobs at all → return early
  if ready_candidates:
    ready_candidates.sort(key = lambda t: t[0])
    _mtime, name, jdir = ready_candidates[0]
    try:
      _process_one(repo, name, jdir)
      processed = 1
    except _ExpertLeftDirtyTree as e:
      processed = 1
      return {
        "experts": expert_count, "processed": processed,
        "cleaned": cleaned, "detected_dead": detected_dead, "halted": True,
        "halt_expert": e.expert, "halt_job_id": e.job_id,
      }
  return { "experts": expert_count, "processed": processed, "cleaned": cleaned, "detected_dead": detected_dead }


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
  ])
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


def build_expert_argv(repo: Path, env: dict[str, str], *, contract_path: Path,
                      model: str | None, mcp_config: str | list[str] | None,
                      agent_ref: str, prompt: str) -> list[str]:
  """
  Assemble the `claude -p` command line for an expert spawn.

  The spawn always runs `--strict-mcp-config`, so ambient operator MCP servers
  (`~/.claude.json`, project `.mcp.json`) are never inherited — a headless
  daemon spawn has no TTY and would otherwise block on an interactive-auth
  server's initialization until the job times out. MCP servers come only from
  the per-expert `mcp_config` allow-list, if any. The pump and the launchability
  preflight share this builder so the probed command line matches the real one.

  Args:
    repo: Repository root the spawn runs inside.
    env: Environment mapping the spawn inherits; read for `LAZYCORTEX_PLUGIN_DIRS`.
    contract_path: Path to the expert-runtime contract appended as a system prompt.
    model: Model tier pin, or None to inherit the CLI default.
    mcp_config: Per-expert MCP-config path(s), or None for a hermetic spawn.
    agent_ref: Scoped agent reference the spawn resolves.
    prompt: The user prompt passed to `claude -p`.

  Returns:
    The full argv list ready for `subprocess.run`.
  """
  # `--permission-mode dontAsk` (not `bypassPermissions`): auto-deny any tool
  # call outside the sandbox — bypassPermissions skips even deny rules and lets a
  # misguided agent burn minutes on `find /Users/...`; dontAsk fails immediately.
  argv = [ "claude", "-p", "--permission-mode", "dontAsk",
           "--output-format", "stream-json", "--verbose",
           "--append-system-prompt-file", str(contract_path),
           "--strict-mcp-config" ]
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

  Exactly one attempt is made — transient failures such as a non-zero exit, a missing
  response.json, or a SIGTERM from the daemon-level timeout leave the job in a
  READY+ERROR state for the next pump tick to retry. A successful run that leaves the
  working tree dirty raises `_ExpertLeftDirtyTree` so the pump halts the queue.

  Args:
    repo: Repository root the spawn runs inside.
    expert_name: Name of the expert that owns this job.
    jdir: Path to the job directory being processed.

  Raises:
    _ExpertLeftDirtyTree: When the expert exited cleanly but left uncommitted changes.
  """
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

  agent_ref = cfg.get(JobConfigKey.AGENT)
  protocols_refs = cfg.get(JobConfigKey.PROTOCOLS) or []
  aspects_refs   = cfg.get(JobConfigKey.ASPECTS) or []
  arguments      = cfg.get(JobConfigKey.ARGUMENTS) or {}
  model          = cfg.get(JobConfigKey.MODEL)
  mcp_config     = cfg.get(JobConfigKey.MCP_CONFIG)
  # guard: agent reference must be present in config
  if not agent_ref:
    # waiver: one-off human-facing message
    _write_error(jdir, JobErrorCategory.LOGICAL, "config.json: missing agent")
    return

  # Empty protocols + empty aspects is a valid config. Specific-domain
  # agents (test-designer, lazy-review.historian, doc_doctor, …) are
  # self-contained — the .md frontmatter + body IS the full instruction.
  # The composition path (generic agent + aspects + protocol) is one
  # valid spawn shape, not the only one. No guard needed; pump spawns
  # whatever the agent file alone can do.

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

  git_author = cfg.get(JobConfigKey.GIT_AUTHOR) or {}
  env = os.environ.copy()
  # waiver: environment-variable name, not a domain key
  env["GIT_AUTHOR_NAME"]  = git_author.get("name",  "")
  # waiver: environment-variable name, not a domain key
  env["GIT_AUTHOR_EMAIL"] = git_author.get("email", "")

  # Three parallel single-noun labels — protocols, aspects, arguments.
  # `- protocol:` replaces the legacy `- protocol contract:` for parallelism.
  # Arguments are key-sorted for byte-stable prompts (cache hits, snapshot tests).
  prompt = _compose_user_prompt(jdir, protocols = protocol_paths, aspects = aspect_paths, arguments = arguments)
  # waiver: filesystem path idiom, not a domain constant
  contract_path = (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()
  # Mark this job as ours: write PID before invoking the expert.
  # The dead-job detector reads this to distinguish queued (no PID)
  # from active (PID file present, alive) from stuck (PID dead).
  (jdir / JobMarker.PID).write_text(f"{os.getpid()}\n")
  # Bump attempts counter — persists across pump kills + recovery cycles.
  # Recovery routine reads this to decide retry vs. permanent-fail.
  # waiver: filesystem path idiom, not a domain constant
  attempts_file = jdir / "attempts"
  try:
    n = int(attempts_file.read_text().strip())
  except (OSError, ValueError):
    n = 0
  attempts_file.write_text(f"{n + 1}\n")
  # The spawn command line — permission mode, hermetic `--strict-mcp-config` +
  # any per-expert `--mcp-config`, plugin dirs, `--settings` sandbox, model, and
  # `--agent` — is assembled by `build_expert_argv`, shared with the
  # `lazy-runtime.preflight` launchability probe so the probe matches the real spawn.
  # (`agent_path` is still resolved above and used for the read-only check below.)
  claude_argv = build_expert_argv(
    repo, env,
    contract_path = contract_path, model = model, mcp_config = mcp_config,
    agent_ref = agent_ref, prompt = prompt,
  )
  proc = subprocess.run(
    claude_argv,
    env = env, cwd = repo, capture_output = True, text = True, check = False,
  )
  # Persist the transcript — best-effort, never block DONE on a write failure.
  try:
    (jdir / JobArtifact.TRANSCRIPT).write_text(proc.stdout or "")
  except Exception as e:  # pragma: no cover — defensive
    sys.stderr.write(f"transcript write failed: {e}\n")
  if proc.returncode == 0:
    response_path = jdir / JobFile.RESPONSE
    # Bug 99 fallback: agent exited cleanly but didn't write response.json
    # — recover the JSON object from the final assistant text frame of
    # the stream-json transcript. LLMs sometimes describe their result in
    # text instead of writing the file. Without this fallback the success-
    # gate fails, the pump records a transient error, and the dispatcher
    # re-dispatches until a roll of the dice lands a write-this-time run.
    if not response_path.exists():
      recovered = _extract_response_from_stdout(proc.stdout or "")
      if recovered is not None:
        response_path.write_text(json.dumps(recovered, indent = 2))
    if response_path.exists():
      # Token capture is best-effort — never block DONE.
      try:
        usage = _extract_usage(proc.stdout)
        if usage is not None:
          _append_tokens_log(repo, expert_name, usage)
      except Exception as e:  # pragma: no cover — defensive
        sys.stderr.write(f"token capture failed: {e}\n")
      if not _agent_is_read_only(agent_path):
        # guard: abort the tick when the expert left the working tree dirty
        if _check_post_claude(repo, expert_name, jdir):
          raise _ExpertLeftDirtyTree(expert_name, jdir.name, [])
      (jdir / JobMarker.DONE).touch()
      return
  _write_error(jdir, JobErrorCategory.TRANSIENT, f"exit={proc.returncode} stderr={proc.stderr[-500:]}")


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
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
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
  model = "unknown"
  final_usage: dict | None = None

  # Try line-by-line first (stream-json), then whole-buffer (single json).
  candidates: list[str] = []
  for line in stdout.splitlines():
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    line = line.strip()  # noqa: PLW2901
    if line:
      candidates.append(line)
  # guard: nothing non-empty in stdout to parse
  if not candidates:
    return None

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


def _write_error(jdir: Path, category: str, message: str) -> None:
  """
  Write an error outcome to the job and close it.

  Args:
    jdir: Path to the job directory whose response.json is being written.
    category: Error category label persisted in the response payload.
    message: Human-readable error message persisted alongside the category.
  """
  (jdir / JobFile.RESPONSE).write_text(json.dumps({
    JobResponseKey.OUTCOME: JobOutcome.ERROR,
    JobResponseKey.ERROR: { JobResponseKey.CATEGORY: category, JobResponseKey.MESSAGE: message },
  }, indent = 2))
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

  Jobs marked DONE are retained for `done_after` seconds when the response succeeded,
  or `fail_after` seconds when the response carried an error outcome. Jobs marked DEAD
  are retained for `dead_after` seconds as a forensic window. Jobs in neither state
  are left untouched.

  Args:
    jdir: Path to the job directory being considered for cleanup.
    done_after: Retention window in seconds for successfully completed jobs.
    fail_after: Retention window in seconds for jobs that completed with an error.
    dead_after: Retention window in seconds for jobs that were marked dead.

  Returns:
    1 if the job directory was removed, 0 otherwise.
  """
  if (jdir / JobMarker.DONE).exists():
    age = time.time() - (jdir / JobMarker.DONE).stat().st_mtime
    resp_path = jdir / JobFile.RESPONSE
    is_error = False
    if resp_path.exists():
      try:
        is_error = json.loads(resp_path.read_text()).get(JobResponseKey.OUTCOME) == JobOutcome.ERROR
      except json.JSONDecodeError:
        pass
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

  if (jdir / JobMarker.DEAD).exists():
    age = time.time() - (jdir / JobMarker.DEAD).stat().st_mtime
    if age >= dead_after:
      shutil.rmtree(jdir)
      return 1
    return 0

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
