"""Implementation of `lazycortex-core expert-pump-once` subcommand."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from lazy_settings import load_section
from reference_resolver import resolve, ReferenceError

JOBS_BASE = ".experts/.jobs"
EXPERTS_FILE = ".experts/experts.settings.json"
RETRY_DELAYS = [1, 2, 4, 8, 16]

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
                _process_one(repo, name, identity, jdir)
                processed += 1
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
    last_err = None
    for delay in [0, *RETRY_DELAYS]:
        if delay: time.sleep(delay)
        try:
            proc = subprocess.run(
                ["claude", "-p", "--permission-mode", "bypassPermissions",
                 "--agent", str(agent_path), prompt],
                env=env, cwd=repo, capture_output=True, text=True, timeout=900,
            )
            if proc.returncode == 0 and (jdir / "response.json").exists():
                (jdir / "DONE").touch()
                return
            last_err = f"exit={proc.returncode} stderr={proc.stderr[-500:]}"
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout: {e}"
    _write_error(jdir, "transient", last_err or "unknown failure")

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
