"""Implementation of `lazycortex-core expert-pump-once` subcommand."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from lazy_settings import load_section
from reference_resolver import resolve, ReferenceError

JOBS_BASE = ".experts/.jobs"
EXPERTS_FILE = ".experts/experts.settings.json"
RETRY_DELAYS = [1, 2, 4, 8, 16]


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
    experts_path = repo / EXPERTS_FILE
    if not experts_path.exists():
        return {"experts": 0, "processed": 0, "cleaned": 0}
    experts = json.loads(experts_path.read_text())
    experts.pop("_version", None)

    loop_cfg = load_section(repo / ".claude/lazy.settings.json", "lazy-core.runtime")
    daemon = loop_cfg.get("daemon", {})
    cleanup_done_after  = _parse_duration(daemon.get("cleanup_completed_after", "7d"))
    cleanup_fail_after  = _parse_duration(daemon.get("cleanup_failed_after",   "30d"))

    processed = cleaned = 0
    for name, identity in experts.items():
        edir = repo / JOBS_BASE / name
        if not edir.exists(): continue
        for jdir in sorted(edir.iterdir()):
            if not jdir.is_dir(): continue
            cleaned += _maybe_cleanup(jdir, cleanup_done_after, cleanup_fail_after)
            if (jdir / "READY").exists() and not (jdir / "DONE").exists():
                try:
                    _process_one(repo, name, identity, jdir)
                    processed += 1
                except _ExpertLeftDirtyTree as e:
                    processed += 1
                    # Stop processing further jobs this tick; the daemon-wide
                    # halt is already written by _check_post_claude.
                    return {
                        "experts": len(experts), "processed": processed,
                        "cleaned": cleaned, "halted": True,
                        "halt_expert": e.expert, "halt_job_id": e.job_id,
                    }
    return {"experts": len(experts), "processed": processed, "cleaned": cleaned}

def _process_one(repo: Path, expert_name: str, identity: dict, jdir: Path) -> None:
    try:
        agent_path    = resolve(identity["agent"],    category="agents",    repo=repo)
        protocol_path = resolve(identity["protocol"], category="protocols", repo=repo)
    except ReferenceError as e:
        _write_error(jdir, "logical", str(e))
        return

    env = os.environ.copy()
    env["PROTOCOL_PATH"]    = str(protocol_path)
    env["GIT_AUTHOR_NAME"]  = identity.get("git_author", {}).get("name",  "")
    env["GIT_AUTHOR_EMAIL"] = identity.get("git_author", {}).get("email", "")
    env["JOB_DIR"]          = str(jdir)

    prompt = (
        f"Process this expert job. Concrete paths (already resolved — do not look up env vars):\n"
        f"- protocol contract: {protocol_path}\n"
        f"- request.json:      {jdir}/request.json\n"
        f"- source/ dir:       {jdir}/source/\n"
        f"- context/ dir:      {jdir}/context/  (may be absent)\n"
        f"- result/ dir:       {jdir}/result/   (write outputs here)\n"
        f"- response.json:     {jdir}/response.json  (write your final outcome here)\n"
        f"\nSteps: Read the protocol + request.json, perform the work per the protocol, "
        f"write result files into result/, write response.json with outcome + result array "
        f"per the protocol's response.json schema, then exit. Do not touch DONE — daemon does that."
    )
    contract_path = (Path(__file__).parent.parent / "templates" / "expert-runtime-contract.md").resolve()
    last_err = None
    for delay in [0, *RETRY_DELAYS]:
        if delay: time.sleep(delay)
        try:
            proc = subprocess.run(
                ["claude", "-p", "--permission-mode", "bypassPermissions",
                 "--output-format", "stream-json", "--verbose",
                 "--append-system-prompt-file", str(contract_path),
                 "--agent", str(agent_path), prompt],
                env=env, cwd=repo, capture_output=True, text=True, timeout=900,
            )
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

def _maybe_cleanup(jdir: Path, done_after: float, fail_after: float) -> int:
    if not (jdir / "DONE").exists(): return 0
    age = time.time() - (jdir / "DONE").stat().st_mtime
    resp_path = jdir / "response.json"
    is_error = False
    if resp_path.exists():
        try: is_error = json.loads(resp_path.read_text()).get("outcome") == "error"
        except json.JSONDecodeError: pass
    threshold = fail_after if is_error else done_after
    if age >= threshold:
        shutil.rmtree(jdir)
        return 1
    return 0

def _parse_duration(s: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return float(s[:-1]) * units[s[-1]]
