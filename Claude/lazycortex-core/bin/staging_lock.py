"""Staging-window mutex for concurrent Claude Code sessions sharing one checkout.

Lock file: <repo>/.git/lazy-git.lock (atomic write, JSON).
Public API: resolve_session_id, load_config, inspect, acquire,
release_if_index_empty, break_lock.
Defaults are module-level constants; consumer overrides via
.claude/lazy.settings.json[lazy-core.git].
"""
from __future__ import annotations
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

# --- Defaults -----------------------------------------------------------------

DEFAULT_ENABLED = True
DEFAULT_WAIT_SECONDS = 30.0
DEFAULT_MAX_HOLD_SECONDS = 600.0
DEFAULT_MAX_IDLE_SECONDS = 300.0
POLL_MIN_MS = 100
POLL_MAX_MS = 500

LOCK_FILENAME = "lazy-git.lock"  # under <repo>/.git/

# --- Types --------------------------------------------------------------------

@dataclass(frozen=True)
class StagingConfig:
    enabled: bool = DEFAULT_ENABLED
    wait_seconds: float = DEFAULT_WAIT_SECONDS
    max_hold_seconds: float = DEFAULT_MAX_HOLD_SECONDS
    max_idle_seconds: float = DEFAULT_MAX_IDLE_SECONDS


@dataclass(frozen=True)
class LockState:
    """Parsed lock file content + computed attributes."""
    session_id: str
    pid: int
    host: str
    branch: str
    started_at: float          # epoch seconds (UTC)
    last_index_mtime: float    # epoch seconds


AcquireStatus = Literal[
    "acquired",
    "reentered",
    "waited_then_acquired",
    "broke_then_acquired",
    "refused",
]


@dataclass(frozen=True)
class AcquireResult:
    status: AcquireStatus
    held_by_us: bool
    peer: Optional[LockState] = None
    break_reason: Optional[str] = None
    waited_seconds: float = 0.0
    message: str = ""


ReleaseReason = Literal["released", "index_not_empty", "not_our_lock", "no_lock"]


@dataclass(frozen=True)
class ReleaseResult:
    released: bool
    reason: ReleaseReason


def _lock_path(repo_root: Path) -> Path:
    return repo_root / ".git" / LOCK_FILENAME


# --- Session ID ---------------------------------------------------------------

def resolve_session_id() -> str:
    """Resolve a stable per-Claude-Code-session identifier.

    Order: $CLAUDE_SESSION_ID env var → ancestor PID matching `claude` argv
    → fallback `pid:<getppid>`. Result is a string opaque to comparison
    (just checked for equality between sessions sharing the lock file).
    """
    env = os.environ.get("CLAUDE_SESSION_ID", "")
    if env:
        return env
    ancestor = _find_claude_ancestor_pid()
    if ancestor is not None:
        return f"pid:{ancestor}"
    return f"pid:{os.getppid()}"


def _find_claude_ancestor_pid() -> Optional[int]:
    """Walk up the process tree looking for `claude`/`claude-code` in argv[0].

    Best-effort. macOS and Linux only. Returns None if nothing matches.
    """
    pid = os.getppid()
    for _ in range(20):  # bounded walk; never recurse forever
        if pid <= 1:
            return None
        try:
            argv0 = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="],
                text=True, stderr=subprocess.DEVNULL,
            ).strip().split()
            if argv0 and Path(argv0[0]).name in ("claude", "claude-code"):
                return pid
            parent = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "ppid="],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            pid = int(parent)
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
            return None
    return None


# --- Lock file IO -------------------------------------------------------------

def _read_lock(repo_root: Path) -> Optional[LockState]:
    """Return parsed LockState or None if file missing / corrupt."""
    path = _lock_path(repo_root)
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
    try:
        return LockState(
            session_id=str(raw["session_id"]),
            pid=int(raw["pid"]),
            host=str(raw["host"]),
            branch=str(raw["branch"]),
            started_at=float(raw["started_at"]),
            last_index_mtime=float(raw["last_index_mtime"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_lock(repo_root: Path, state: LockState) -> None:
    """Atomically write the lock file. .git/ must already exist."""
    path = _lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": state.session_id,
        "pid": state.pid,
        "host": state.host,
        "branch": state.branch,
        "started_at": state.started_at,
        "last_index_mtime": state.last_index_mtime,
    }
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".lazy-git-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _delete_lock(repo_root: Path) -> None:
    """Remove the lock file. Idempotent."""
    try:
        _lock_path(repo_root).unlink()
    except FileNotFoundError:
        pass


# --- Git state helpers --------------------------------------------------------

def _index_is_empty(repo_root: Path) -> bool:
    """True iff `git diff --cached --quiet` returns 0."""
    rc = subprocess.run(
        # `--no-optional-locks` skips the stat-cache refresh that would
        # otherwise write to `.git/index.lock`. Read-only inspection of
        # the index doesn't need the lock.
        ["git", "--no-optional-locks", "-C", str(repo_root),
         "diff", "--cached", "--quiet"],
        capture_output=True,
    ).returncode
    return rc == 0


def _current_branch(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "HEAD"


def _index_mtime(repo_root: Path) -> float:
    """Mtime of .git/index (epoch seconds). 0.0 if it doesn't exist."""
    try:
        return (repo_root / ".git" / "index").stat().st_mtime
    except FileNotFoundError:
        return 0.0


# --- Inspect ------------------------------------------------------------------

def inspect(repo_root: Path) -> Optional[LockState]:
    """Read the current lock state. Returns None if no lock or unreadable."""
    return _read_lock(repo_root)


# --- Break-the-lock rules -----------------------------------------------------

BreakReason = Literal["dead_pid", "different_host", "stale_and_idle", "held"]


def _pid_alive(pid: int) -> bool:
    """Probe with kill(pid, 0). True if process exists (or we lack permission)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but ours-not-to-signal
    except OSError:
        return False
    return True


def _is_breakable(
    repo_root: Path,
    state: LockState,
    cfg: StagingConfig,
    now: float,
) -> tuple[bool, BreakReason]:
    """Apply break-the-lock rules in order. Returns (breakable, reason)."""
    # Rule 1: dead PID
    if not _pid_alive(state.pid):
        return True, "dead_pid"
    # Rule 2: different host
    if state.host != socket.gethostname():
        return True, "different_host"
    # Rule 3: stale-and-idle
    age = now - state.started_at
    if age > cfg.max_hold_seconds:
        current_index_mtime = _index_mtime(repo_root)
        # The index has not moved past last_index_mtime AND mtime itself is stale.
        index_idle = (
            current_index_mtime <= state.last_index_mtime
            and (now - max(current_index_mtime, state.last_index_mtime)) > cfg.max_idle_seconds
        )
        if index_idle:
            return True, "stale_and_idle"
    return False, "held"


def break_lock(repo_root: Path, reason: str) -> bool:
    """Force-delete the lock file. Idempotent. Returns True if file existed."""
    path = _lock_path(repo_root)
    existed = path.exists()
    _delete_lock(repo_root)
    return existed


# --- Acquire ------------------------------------------------------------------

def _new_lock_state(repo_root: Path, session_id: str) -> LockState:
    return LockState(
        session_id=session_id,
        pid=os.getpid(),
        host=socket.gethostname(),
        branch=_current_branch(repo_root),
        started_at=time.time(),
        last_index_mtime=_index_mtime(repo_root),
    )


def acquire(
    repo_root: Path,
    session_id: str,
    cfg: StagingConfig,
) -> AcquireResult:
    """Try to acquire the staging lock. Polls if held by a live peer."""
    if not cfg.enabled:
        return AcquireResult(status="acquired", held_by_us=True,
                             message="staging lock disabled (lazy-core.git.enabled=false)")

    deadline = time.time() + cfg.wait_seconds
    waited = 0.0
    first_pass = True

    while True:
        existing = _read_lock(repo_root)

        # No lock — take it.
        if existing is None:
            _write_lock(repo_root, _new_lock_state(repo_root, session_id))
            status: AcquireStatus = "acquired" if first_pass else "waited_then_acquired"
            return AcquireResult(status=status, held_by_us=True, waited_seconds=waited)

        # Lock is ours — re-entry.
        if existing.session_id == session_id:
            return AcquireResult(status="reentered", held_by_us=True, waited_seconds=waited)

        # Held by peer — check if breakable.
        breakable, reason = _is_breakable(repo_root, existing, cfg, now=time.time())
        if breakable:
            _delete_lock(repo_root)
            _write_lock(repo_root, _new_lock_state(repo_root, session_id))
            return AcquireResult(
                status="broke_then_acquired", held_by_us=True,
                break_reason=reason, peer=existing, waited_seconds=waited,
            )

        # Held by live peer; check deadline.
        now = time.time()
        if now >= deadline:
            return AcquireResult(
                status="refused", held_by_us=False, peer=existing, waited_seconds=waited,
                message=_refusal_message(existing, cfg, now),
            )

        # Sleep with jitter, then retry.
        sleep_ms = random.randint(POLL_MIN_MS, POLL_MAX_MS)
        sleep_s = min(sleep_ms / 1000.0, max(0.0, deadline - now))
        time.sleep(sleep_s)
        waited += sleep_s
        first_pass = False


def _refusal_message(peer: LockState, cfg: StagingConfig, now: float) -> str:
    age = int(now - peer.started_at)
    age_left = max(0, int(cfg.max_hold_seconds - age))
    return (
        f"Another Claude session is staging on branch {peer.branch} "
        f"(PID {peer.pid}, started {age}s ago). Wait briefly and retry, "
        f"or run `/lazy-core.git-unlock` to break the lock manually. "
        f"(Auto-break in {age_left}s if the index stays idle.)"
    )


# --- Release ------------------------------------------------------------------

def release_if_index_empty(repo_root: Path, session_id: str) -> ReleaseResult:
    """Delete the lock iff (a) lock is ours AND (b) index is now empty."""
    state = _read_lock(repo_root)
    if state is None:
        return ReleaseResult(released=False, reason="no_lock")
    if state.session_id != session_id:
        return ReleaseResult(released=False, reason="not_our_lock")
    if not _index_is_empty(repo_root):
        return ReleaseResult(released=False, reason="index_not_empty")
    _delete_lock(repo_root)
    return ReleaseResult(released=True, reason="released")


# --- Config -------------------------------------------------------------------

_SETTINGS_REL = ".claude/lazy.settings.json"
_SECTION = "git"


def load_config(repo_root: Path) -> StagingConfig:
    """Load StagingConfig from <repo>/.claude/lazy.settings.json or defaults."""
    settings_path = repo_root / _SETTINGS_REL
    section: dict = {}
    if settings_path.exists():
        # Inline the lazy_settings import so the helper has zero hard
        # dependency on lazy_settings being importable. Hooks are short-lived
        # and import latency matters; defer to first use.
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import lazy_settings  # type: ignore
            section = lazy_settings.load_section(settings_path, _SECTION)
        except Exception:
            try:
                section = json.loads(settings_path.read_text()).get(_SECTION, {})
            except Exception:
                section = {}
        finally:
            try:
                sys.path.remove(str(Path(__file__).parent))
            except ValueError:
                pass
    return StagingConfig(
        enabled=bool(section.get("enabled", DEFAULT_ENABLED)),
        wait_seconds=float(section.get("wait_seconds", DEFAULT_WAIT_SECONDS)),
        max_hold_seconds=float(section.get("max_hold_seconds", DEFAULT_MAX_HOLD_SECONDS)),
        max_idle_seconds=float(section.get("max_idle_seconds", DEFAULT_MAX_IDLE_SECONDS)),
    )
