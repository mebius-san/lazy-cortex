"""Public helpers for dispatching/collecting jobs in the expert runtime."""
from __future__ import annotations
import json, shutil, uuid
from pathlib import Path
from typing import Iterable

JOBS_BASE = ".experts/.jobs"

def _job_dir(repo: Path, expert: str, job_id: str) -> Path:
    return Path(repo) / JOBS_BASE / expert / job_id

def dispatch_job(
    repo: Path,
    expert: str,
    payload: dict,
    *,
    job_id: str | None = None,
    dedup_key: str | None = None,
) -> dict:
    """Dispatch a job for `expert` with `payload`. Returns:
      - {job_id, queue_path}                    — normal create
      - {job_id, status: "already-queued"}      — dedup hit (only when
        dedup_key is set AND an active job for the same (expert, key)
        pair already exists)

    "Active" job = READY exists, no response.json, no DEAD. The DEAD
    flag is owned by expert_pump._detect_dead_jobs; this function does
    NOT do PID-liveness checks of its own — it just reads the flag.

    When dedup_key is set, it is embedded into the payload as
    `_dedup_key` so future dispatches can find existing jobs by
    walking <repo>/.experts/.jobs/<expert>/*/request.json.
    """
    if dedup_key is not None:
        edir = Path(repo) / JOBS_BASE / expert
        if edir.exists():
            for jdir in edir.iterdir():
                if not jdir.is_dir():
                    continue
                if not (jdir / "READY").exists():
                    continue
                if (jdir / "response.json").exists():
                    continue
                if (jdir / "DEAD").exists():
                    continue
                req_file = jdir / "request.json"
                if not req_file.exists():
                    continue
                try:
                    existing = json.loads(req_file.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if existing.get("_dedup_key") == dedup_key:
                    return {"job_id": jdir.name, "status": "already-queued"}

    job_id = job_id or uuid.uuid4().hex[:12]
    d = _job_dir(repo, expert, job_id)
    d.mkdir(parents=True, exist_ok=True)
    out_payload = dict(payload)
    if dedup_key is not None:
        out_payload["_dedup_key"] = dedup_key
    (d / "request.json").write_text(json.dumps(out_payload, indent=2))
    (d / "READY").touch()
    return {"job_id": job_id, "queue_path": str(d)}

def collect_job(repo: Path, expert: str, job_id: str) -> dict:
    d = _job_dir(repo, expert, job_id)
    if not d.exists():
        return {"status": "missing"}
    if not (d / "DONE").exists():
        return {"status": "pending"}
    resp = json.loads((d / "response.json").read_text()) if (d / "response.json").exists() else {}
    status = "failed" if resp.get("outcome") == "error" else "done"
    return {"status": status, "response": resp}

def list_jobs(repo: Path, *, expert: str | None = None, status: str | None = None) -> list[dict]:
    """List jobs. Status enum: queued | active | dead | done | failed.

    Filesystem mapping:
      - DEAD exists                                  → dead
      - DONE + response.json (outcome == error)      → failed
      - DONE present                                  → done
      - READY + PID (no DEAD, no response.json)       → active
      - READY only (no PID)                           → queued
      - none of the above                             → skipped (not listed)
    """
    base = Path(repo) / JOBS_BASE
    out = []
    if not base.exists(): return out
    experts = [expert] if expert else [d.name for d in base.iterdir() if d.is_dir()]
    for e in experts:
        edir = base / e
        if not edir.exists(): continue
        for jdir in edir.iterdir():
            if not jdir.is_dir(): continue
            entry_status = _job_status(jdir)
            if entry_status is None:
                continue
            entry = {"expert": e, "job_id": jdir.name, "path": str(jdir),
                     "status": entry_status}
            if status and entry["status"] != status:
                continue
            out.append(entry)
    return out


def _job_status(jdir: Path) -> str | None:
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
    d = _job_dir(repo, expert, job_id)
    if d.exists():
        shutil.rmtree(d)

def register_routine(repo: Path, name: str, cfg: dict | None = None, *,
                     command: list[str] | None = None,
                     interval_sec: int | None = None,
                     timeout_sec: int | None = None) -> None:
    """Register a routine in lazy-core.runtime.routines.

    Two call shapes:
      - Typed:  register_routine(repo, name, {"type": "inbox", "inbox_dir": ..., ...})
      - Legacy: register_routine(repo, name, command=[...], interval_sec=N, timeout_sec=...)
                (equivalent to type="subprocess")

    Either way the cfg is validated via routine_types.validate_routine_entry
    before being written.
    """
    from routine_types import validate_routine_entry
    if cfg is None:
        if command is None or interval_sec is None:
            raise TypeError(
                "register_routine: pass `cfg` (typed shape), "
                "or pass `command` + `interval_sec` (legacy subprocess shape)"
            )
        cfg = {"command": list(command), "interval_sec": interval_sec}
        if timeout_sec is not None:
            cfg["timeout_sec"] = timeout_sec
    validate_routine_entry(name, cfg)
    from lazy_settings import load_section, save_section
    settings = Path(repo) / ".claude/lazy.settings.json"
    routines = load_section(settings, "routines")
    routines[name] = cfg
    save_section(settings, "routines", routines)

PROTECTED_ROUTINES = {"lazy-expert.pump"}

def unregister_routine(repo: Path, name: str) -> None:
    if name in PROTECTED_ROUTINES:
        raise ValueError(
            f"cannot unregister built-in routine: {name}. "
            f"It is required by the expert runtime; uninstall the plugin instead."
        )
    from lazy_settings import load_section, save_section
    settings = Path(repo) / ".claude/lazy.settings.json"
    routines = load_section(settings, "routines")
    routines.pop(name, None)
    save_section(settings, "routines", routines)

DEFAULT_EXPERT_PUMP = {
    "name": "lazy-expert.pump",
    "command": ["lazycortex-core", "expert-pump-once"],
    "interval_sec": 30,
    # Pump's internal claude-spawn timeout is 900s and it may retry up to 6
    # times with backoff sum 31s — worst case ~5430s. Set the per-routine
    # timeout above that floor so the daemon doesn't kill pump mid-retry.
    "timeout_sec": 5500,
}

def bootstrap_default_routines(repo: Path) -> None:
    """Register the built-in expert-pump routine if not already present.
    Idempotent — does not overwrite user-modified config for an existing routine."""
    from lazy_settings import load_section
    settings = Path(repo) / ".claude/lazy.settings.json"
    routines = load_section(settings, "routines")
    name = DEFAULT_EXPERT_PUMP["name"]
    if name in routines:
        return  # already registered; respect any user customization
    register_routine(
        repo, name,
        command=DEFAULT_EXPERT_PUMP["command"],
        interval_sec=DEFAULT_EXPERT_PUMP["interval_sec"],
    )
