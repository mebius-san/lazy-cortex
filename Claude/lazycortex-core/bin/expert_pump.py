"""Implementation of `lazycortex-core expert-pump-once` subcommand."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from lazy_settings import load_section
from reference_resolver import resolve, ReferenceError

JOBS_BASE = ".experts/.jobs"
RETRY_DELAYS = [1, 2, 4, 8, 16]


def _pid_alive(pid: int) -> bool:
    """Probe with os.kill(pid, 0). True if process exists (or we lack
    permission to signal it). False on ProcessLookupError or invalid pid.
    Mirrors staging_lock._pid_alive."""
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


_DEAD_JSON_INTERNAL_FILES = {"READY", "PID", "request.json", "DEAD", "dead.json"}


def _build_dead_json(jdir: Path, expert: str, job_id: str, marked_at: float) -> dict:
    """Compose the dead.json payload for a stuck job. Pure function — does not
    write to disk; the caller persists the returned dict.
    """
    import json
    from datetime import datetime, timezone

    queued_at = (jdir / "READY").stat().st_mtime
    claimed_at = (jdir / "PID").stat().st_mtime

    try:
        original_pid = int((jdir / "PID").read_text().strip())
    except (OSError, ValueError):
        original_pid = -1

    dedup_key = None
    try:
        request = json.loads((jdir / "request.json").read_text())
        dedup_key = request.get("_dedup_key")
    except (OSError, json.JSONDecodeError, KeyError):
        pass

    partial_output = sorted(
        p.name for p in jdir.iterdir()
        if p.name not in _DEAD_JSON_INTERNAL_FILES
    )

    duration_alive_sec = max(0.0, marked_at - claimed_at)

    if duration_alive_sec < 5 and not partial_output:
        likely_cause = "crashed_at_startup"
    elif duration_alive_sec > 3600 and not partial_output:
        likely_cause = "long_running_killed_or_hung"
    elif partial_output:
        likely_cause = "crashed_mid_processing"
    else:
        likely_cause = "unknown"

    return {
        "marked_at": marked_at,
        "marked_at_iso": datetime.fromtimestamp(marked_at, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
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
    """Walk all job_dirs under <repo>/.experts/.jobs/, mark stuck jobs
    (READY + PID file + no response.json + no DEAD, with dead PID) by
    touching DEAD and writing dead.json. Returns the count of newly-
    marked dead jobs.
    """
    import json
    base = Path(repo) / JOBS_BASE
    if not base.exists():
        return 0

    marked = 0
    for edir in base.iterdir():
        if not edir.is_dir():
            continue
        for jdir in edir.iterdir():
            if not jdir.is_dir():
                continue
            if not (jdir / "READY").exists():
                continue
            if (jdir / "response.json").exists():
                continue
            if (jdir / "DONE").exists():
                continue
            if (jdir / "DEAD").exists():
                continue
            if not (jdir / "PID").exists():
                continue

            try:
                pid_text = (jdir / "PID").read_text().strip()
                pid = int(pid_text)
                alive = _pid_alive(pid)
            except (OSError, ValueError):
                alive = False

            if alive:
                continue

            blob = _build_dead_json(jdir, edir.name, jdir.name, time.time())
            (jdir / "dead.json").write_text(json.dumps(blob, indent=2))
            (jdir / "DEAD").touch()
            marked += 1

    return marked


class _ExpertLeftDirtyTree(Exception):
    """Raised by _process_one when an expert exited cleanly but left
    uncommitted changes in the working tree. Caught at the pump level to
    stop processing remaining jobs this tick."""
    def __init__(self, expert: str, job_id: str, dirty_paths: list[str]):
        super().__init__(f"expert {expert!r} left dirty tree at job {job_id!r}")
        self.expert = expert
        self.job_id = job_id
        self.dirty_paths = dirty_paths


def _check_post_claude(repo: Path, expert_name: str, jdir: Path) -> bool:
    """After a successful expert run, verify the working tree is clean.

    On dirty:
      - Override response.json with outcome=error, category=uncommitted_changes.
      - Touch DONE (job is closed — failed).
      - Write the daemon-wide halt block to state.json with full attribution
        (expert + job_id).

    Returns True iff dirty (caller should raise _ExpertLeftDirtyTree).
    """
    import runtime_state
    from runtime_daemon import _check_working_tree
    dirty = _check_working_tree(repo)
    if dirty is None:
        return False
    (jdir / "response.json").write_text(json.dumps({
        "outcome": "error",
        "error": {
            "category": "uncommitted_changes",
            "message": "expert left uncommitted changes after exit",
            "dirty_paths": dirty,
        },
    }, indent=2))
    (jdir / "DONE").touch()
    runtime_state.set_halted(repo, {
        "halted_since": time.time(),
        "triggered_by": "lazy-expert.pump",
        "reason": "uncommitted_changes",
        "dirty_paths": dirty,
        "expert": expert_name,
        "job_id": jdir.name,
    })
    return True

def pump(repo: Path) -> dict:
    repo = Path(repo)
    settings_path = repo / ".claude/lazy.settings.json"
    daemon = load_section(settings_path, "daemon")
    cleanup_done_after  = _parse_duration(daemon.get("cleanup_completed_after", "7d"))
    cleanup_fail_after  = _parse_duration(daemon.get("cleanup_failed_after",   "30d"))
    cleanup_dead_after  = _parse_duration(daemon.get("cleanup_dead_after",     "7d"))
    detected_dead = _detect_dead_jobs(repo)

    jobs_root = repo / JOBS_BASE
    if not jobs_root.exists():
        return {"experts": 0, "processed": 0, "cleaned": 0, "detected_dead": detected_dead}

    processed = cleaned = expert_count = 0
    for edir in sorted(jobs_root.iterdir()):
        if not edir.is_dir():
            continue
        expert_count += 1
        name = edir.name
        for jdir in sorted(edir.iterdir()):
            if not jdir.is_dir(): continue
            cleaned += _maybe_cleanup(jdir, cleanup_done_after, cleanup_fail_after, cleanup_dead_after)
            if (jdir / "READY").exists() and not (jdir / "DONE").exists():
                try:
                    _process_one(repo, name, jdir)
                    processed += 1
                except _ExpertLeftDirtyTree as e:
                    processed += 1
                    # Stop processing further jobs this tick; the daemon-wide
                    # halt is already written by _check_post_claude.
                    return {
                        "experts": expert_count, "processed": processed,
                        "cleaned": cleaned, "detected_dead": detected_dead, "halted": True,
                        "halt_expert": e.expert, "halt_job_id": e.job_id,
                    }
    return {"experts": expert_count, "processed": processed, "cleaned": cleaned, "detected_dead": detected_dead}

def _process_one(repo: Path, expert_name: str, jdir: Path) -> None:
    # Per-job config.json carries everything the pump needs: agent ref,
    # protocols list (declared by the routine that created this job),
    # git_author for any commits the expert makes. Routine wrote it at
    # dispatch time; pump never consults lazy.settings.json[experts].
    config_path = jdir / "config.json"
    if not config_path.exists():
        _write_error(jdir, "logical", f"config.json missing in {jdir}")
        return
    try:
        cfg = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        _write_error(jdir, "logical", f"unreadable config.json: {e}")
        return

    agent_ref = cfg.get("agent")
    protocols_refs = cfg.get("protocols") or []
    aspects_refs   = cfg.get("aspects") or []
    arguments      = cfg.get("arguments") or {}
    if not agent_ref:
        _write_error(jdir, "logical", "config.json: missing agent")
        return
    if not protocols_refs and not aspects_refs:
        _write_error(jdir, "logical", "config.json: both protocols and aspects are empty — nothing to instruct the expert with")
        return

    try:
        agent_path = resolve(agent_ref, category="agents", repo=repo)
        protocol_paths = [
            resolve(p, category="protocols", repo=repo) for p in protocols_refs
        ]
        aspect_paths = [
            resolve(a, category="aspects", repo=repo) for a in aspects_refs
        ]
    except ReferenceError as e:
        _write_error(jdir, "logical", str(e))
        return

    git_author = cfg.get("git_author") or {}
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"]  = git_author.get("name",  "")
    env["GIT_AUTHOR_EMAIL"] = git_author.get("email", "")

    # Three parallel single-noun labels — protocols, aspects, arguments.
    # `- protocol:` replaces the legacy `- protocol contract:` for parallelism.
    # Arguments are key-sorted for byte-stable prompts (cache hits, snapshot tests).
    prompt_lines = ["Process this expert job. Concrete paths (already resolved — do not look up env vars):"]
    for p in protocol_paths:
        prompt_lines.append(f"- protocol:           {p}")
    for a in aspect_paths:
        prompt_lines.append(f"- aspect:             {a}")
    for k in sorted(arguments):
        v = json.dumps(arguments[k], ensure_ascii=False, sort_keys=True)
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
    prompt = "\n".join(prompt_lines)
    contract_path = (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()
    last_err = None
    for delay in [0, *RETRY_DELAYS]:
        if delay: time.sleep(delay)
        # Mark this job as ours: write PID before invoking the expert.
        # The dead-job detector reads this to distinguish queued (no PID)
        # from active (PID file present, alive) from stuck (PID dead).
        (jdir / "PID").write_text(f"{os.getpid()}\n")
        try:
            proc = subprocess.run(
                ["claude", "-p", "--permission-mode", "bypassPermissions",
                 "--output-format", "stream-json", "--verbose",
                 "--append-system-prompt-file", str(contract_path),
                 "--agent", str(agent_path), prompt],
                env=env, cwd=repo, capture_output=True, text=True, timeout=900,
            )
            # Persist the transcript on every attempt — the last write wins,
            # matching the final outcome. Job dirs are retained per
            # `cleanup_completed_after` (default 7d) which is the intended
            # debug window. Best-effort; never block DONE on a write failure.
            try:
                (jdir / "transcript.jsonl").write_text(proc.stdout or "")
            except Exception as e:  # pragma: no cover — defensive
                sys.stderr.write(f"transcript write failed: {e}\n")
            if proc.returncode == 0 and (jdir / "response.json").exists():
                # Token capture is best-effort — never block DONE.
                try:
                    usage = _extract_usage(proc.stdout)
                    if usage is not None:
                        _append_tokens_log(repo, expert_name, usage)
                except Exception as e:  # pragma: no cover — defensive
                    sys.stderr.write(f"token capture failed: {e}\n")
                if _check_post_claude(repo, expert_name, jdir):
                    raise _ExpertLeftDirtyTree(expert_name, jdir.name, [])
                (jdir / "DONE").touch()
                return
            last_err = f"exit={proc.returncode} stderr={proc.stderr[-500:]}"
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout: {e}"
    _write_error(jdir, "transient", last_err or "unknown failure")


def _extract_usage(stdout: str) -> dict | None:
    """Walk `claude -p --output-format stream-json` events and accumulate
    the final usage totals + the model id seen on assistant frames.

    Returns a dict with keys {model, input_tokens, output_tokens, cache_read,
    cache_write}, or None if stdout contains no parseable usage frame.

    Falls back to single-object `--output-format json` shape — the same
    `result` frame layout works either way.
    """
    if not stdout or not stdout.strip():
        return None
    model = "unknown"
    final_usage: dict | None = None

    # Try line-by-line first (stream-json), then whole-buffer (single json).
    candidates: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            candidates.append(line)
    if not candidates:
        return None

    parsed_any = False
    for raw in candidates:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        if not isinstance(frame, dict):
            continue
        msg = frame.get("message")
        if isinstance(msg, dict) and msg.get("model"):
            model = str(msg["model"])
        if frame.get("type") == "result" and isinstance(frame.get("usage"), dict):
            final_usage = frame["usage"]

    # Fallback: stdout was a single JSON object (whole buffer parses).
    if final_usage is None and not parsed_any:
        try:
            frame = json.loads(stdout)
            if isinstance(frame, dict) and isinstance(frame.get("usage"), dict):
                final_usage = frame["usage"]
        except json.JSONDecodeError:
            return None
    if final_usage is None:
        return None

    return {
        "model": model,
        "input_tokens": int(final_usage.get("input_tokens", 0) or 0),
        "output_tokens": int(final_usage.get("output_tokens", 0) or 0),
        "cache_read": int(final_usage.get("cache_read_input_tokens", 0) or 0),
        "cache_write": int(final_usage.get("cache_creation_input_tokens", 0) or 0),
    }


def _append_tokens_log(repo: Path, expert_name: str, usage: dict) -> None:
    """Append one token-usage record to .logs/lazy-core/runtime/tokens.jsonl.

    The `routine` label is fixed to `expert-pump` because token capture is
    pump-internal — only routines that actually invoke `claude -p` produce
    these records, and the pump is the only such routine today."""
    log_dir = repo / ".logs/lazy-core/runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tokens.jsonl"
    record = {
        "ts": time.time(),
        "routine": "expert-pump",
        "expert": expert_name,
        **usage,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")

def _write_error(jdir: Path, category: str, message: str) -> None:
    (jdir / "response.json").write_text(json.dumps({
        "outcome": "error",
        "error": {"category": category, "message": message},
    }, indent=2))
    (jdir / "DONE").touch()

def _maybe_cleanup(jdir: Path, done_after: float, fail_after: float, dead_after: float) -> int:
    """Per-tick GC. Returns 1 if jdir was removed, 0 otherwise.

    Branches:
      - DONE present → TTL = done_after (normal) or fail_after (error outcome).
      - DEAD present → TTL = dead_after. Stuck-job forensic window.
      - Neither → leave alone (job is queued or active).
    """
    if (jdir / "DONE").exists():
        age = time.time() - (jdir / "DONE").stat().st_mtime
        resp_path = jdir / "response.json"
        is_error = False
        if resp_path.exists():
            try:
                is_error = json.loads(resp_path.read_text()).get("outcome") == "error"
            except json.JSONDecodeError:
                pass
        threshold = fail_after if is_error else done_after
        if age >= threshold:
            shutil.rmtree(jdir)
            return 1
        return 0

    if (jdir / "DEAD").exists():
        age = time.time() - (jdir / "DEAD").stat().st_mtime
        if age >= dead_after:
            shutil.rmtree(jdir)
            return 1
        return 0

    return 0

def _parse_duration(s: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return float(s[:-1]) * units[s[-1]]
