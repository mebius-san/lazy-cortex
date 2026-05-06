"""Runtime state persistence for the lazycortex-core daemon.

Stores last_run timestamps, per-`git`-watch last_seen_sha, and the optional
top-level daemon_halted block under <repo>/.logs/lazy-core/runtime/state.json.

Atomic writes via temp+os.replace — same dir as the target file so the rename
is on the same filesystem.
"""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path

STATE_REL = ".logs/lazy-core/runtime/state.json"


def _state_path(repo_root: Path) -> Path:
    return Path(repo_root) / STATE_REL


def _empty_state() -> dict:
    return {"last_run": {}, "git_watch": {}}


def load(repo_root: Path) -> dict:
    """Read state.json. Returns _empty_state() when absent or unparseable."""
    path = _state_path(repo_root)
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return _empty_state()


def save(repo_root: Path, state: dict) -> None:
    """Atomic write: temp file in same dir + os.replace."""
    path = _state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise


def get_halted(repo_root: Path) -> dict | None:
    return load(repo_root).get("daemon_halted")


def set_halted(repo_root: Path, block: dict) -> None:
    state = load(repo_root)
    state["daemon_halted"] = block
    save(repo_root, state)


def clear_halted(repo_root: Path) -> None:
    state = load(repo_root)
    state.pop("daemon_halted", None)
    save(repo_root, state)
