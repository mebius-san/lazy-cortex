"""Public helpers for dispatching/collecting jobs in the expert runtime."""
from __future__ import annotations
import json, shutil, uuid
from pathlib import Path
from typing import Iterable

JOBS_BASE = ".experts/.jobs"

def _job_dir(repo: Path, expert: str, job_id: str) -> Path:
    return Path(repo) / JOBS_BASE / expert / job_id

def dispatch_job(repo: Path, expert: str, payload: dict, *, job_id: str | None = None) -> dict:
    job_id = job_id or uuid.uuid4().hex[:12]
    d = _job_dir(repo, expert, job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "request.json").write_text(json.dumps(payload, indent=2))
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
    base = Path(repo) / JOBS_BASE
    out = []
    if not base.exists(): return out
    experts = [expert] if expert else [d.name for d in base.iterdir() if d.is_dir()]
    for e in experts:
        edir = base / e
        if not edir.exists(): continue
        for jdir in edir.iterdir():
            if not jdir.is_dir(): continue
            done = (jdir / "DONE").exists()
            entry = {"expert": e, "job_id": jdir.name, "path": str(jdir),
                     "status": "done" if done else "pending"}
            if status and entry["status"] != status:
                continue
            out.append(entry)
    return out

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
    section = load_section(settings, "lazy-core.runtime")
    section.setdefault("routines", {})[name] = cfg
    save_section(settings, "lazy-core.runtime", section)

PROTECTED_ROUTINES = {"lazy-expert.pump"}

def unregister_routine(repo: Path, name: str) -> None:
    if name in PROTECTED_ROUTINES:
        raise ValueError(
            f"cannot unregister built-in routine: {name}. "
            f"It is required by the expert runtime; uninstall the plugin instead."
        )
    from lazy_settings import load_section, save_section
    settings = Path(repo) / ".claude/lazy.settings.json"
    section = load_section(settings, "lazy-core.runtime")
    section.get("routines", {}).pop(name, None)
    save_section(settings, "lazy-core.runtime", section)

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
    section = load_section(settings, "lazy-core.runtime")
    routines = section.get("routines", {})
    name = DEFAULT_EXPERT_PUMP["name"]
    if name in routines:
        return  # already registered; respect any user customization
    register_routine(
        repo, name,
        command=DEFAULT_EXPERT_PUMP["command"],
        interval_sec=DEFAULT_EXPERT_PUMP["interval_sec"],
    )
