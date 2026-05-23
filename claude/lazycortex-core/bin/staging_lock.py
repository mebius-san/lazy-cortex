"""
Staging-window mutex for concurrent Claude Code sessions sharing one checkout.

The lock file lives under `<repo>/.git/lazy-git.lock` and is written atomically as JSON.
Public surface: resolve_session_id, load_config, inspect, acquire, release_if_index_empty,
break_lock. Defaults are module-level constants; consumer overrides go through
`.claude/lazy.settings.json[lazy-core.git]`.
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

@dataclass(frozen = True)
class StagingConfig:
  """
  Tunable configuration for the staging-window mutex.

  Attributes:
    enabled: Whether the mutex is active; when false, every acquire call returns immediately.
    wait_seconds: Maximum time an acquire call will poll before returning a refused result.
    max_hold_seconds: Age threshold beyond which a held lock becomes eligible for the
      stale-and-idle break rule.
    max_idle_seconds: Index-idle threshold combined with `max_hold_seconds` to qualify a lock
      for the stale-and-idle break rule.
  """
  enabled: bool = DEFAULT_ENABLED
  wait_seconds: float = DEFAULT_WAIT_SECONDS
  max_hold_seconds: float = DEFAULT_MAX_HOLD_SECONDS
  max_idle_seconds: float = DEFAULT_MAX_IDLE_SECONDS


@dataclass(frozen = True)
class LockState:
  """
  Snapshot of an existing staging lock on disk.

  Attributes:
    session_id: Identifier of the Claude Code session that holds the lock.
    pid: Process id of the holder, used by the dead-pid break rule.
    host: Hostname of the holder, used by the different-host break rule.
    branch: Branch the holder is staging onto, surfaced in refusal messages.
    started_at: Wall-clock epoch seconds (UTC) when the lock was first acquired.
    last_index_mtime: Mtime of `.git/index` at acquire time, used by the stale-and-idle rule.
  """
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


@dataclass(frozen = True)
class AcquireResult:
  """
  Outcome of an acquire attempt.

  Attributes:
    status: Categorical outcome of the attempt.
    held_by_us: True when the lock is held by the caller after the attempt completes.
    peer: Lock state of the previous holder when one was observed during the attempt.
    break_reason: Reason a peer lock was broken, present only on `broke_then_acquired`.
    waited_seconds: Total wall-clock time spent polling before the attempt returned.
    message: Human-readable diagnostic, populated on refusals and disabled-mutex paths.
  """
  status: AcquireStatus
  held_by_us: bool
  peer: Optional[LockState] = None
  break_reason: Optional[str] = None
  waited_seconds: float = 0.0
  message: str = ""


ReleaseReason = Literal["released", "index_not_empty", "not_our_lock", "no_lock"]


@dataclass(frozen = True)
class ReleaseResult:
  """
  Outcome of a conditional release attempt.

  Attributes:
    released: True when the lock was deleted by this call.
    reason: Categorical explanation of the outcome.
  """
  released: bool
  reason: ReleaseReason


def _lock_path(repo_root: Path) -> Path:
  """
  Return the canonical path to the staging lock file for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    Path to `<repo_root>/.git/lazy-git.lock`.
  """
  return repo_root / ".git" / LOCK_FILENAME


# --- Session ID ---------------------------------------------------------------

def resolve_session_id() -> str:
  """
  Resolve a stable identifier for the current Claude Code session.

  The identifier is opaque and is only ever compared for equality between sessions sharing
  the same lock file. Resolution prefers the `CLAUDE_SESSION_ID` environment variable, then
  falls back to a process-tree probe, then to the parent process id.

  Returns:
    A non-empty string identifying the current session.
  """
  env = os.environ.get("CLAUDE_SESSION_ID", "")
  # guard: explicit session id provided by the harness
  if env:
    return env
  ancestor = _find_claude_ancestor_pid()
  # guard: a Claude Code ancestor process was located
  if ancestor is not None:
    return f"pid:{ancestor}"
  return f"pid:{os.getppid()}"


def _find_claude_ancestor_pid() -> Optional[int]:
  """
  Locate the closest ancestor process whose argv[0] is a Claude Code binary.

  The walk is best-effort and operates on macOS and Linux only; the search is bounded so
  the function never loops forever on a malformed process tree.

  Returns:
    The process id of the matching ancestor, or None when no match was found.
  """
  pid = os.getppid()
  # bounded walk; never recurse forever even on cyclic / malformed process tables
  for _ in range(20):
    # guard: reached the init / kernel process boundary
    if pid <= 1:
      return None
    try:
      argv0 = subprocess.check_output(
        [ "ps", "-p", str(pid), "-o", "command=" ],
        text = True, stderr = subprocess.DEVNULL,
      ).strip().split()
      # guard: ancestor argv[0] resolves to a Claude Code binary
      if argv0 and Path(argv0[0]).name in ("claude", "claude-code"):
        return pid
      parent = subprocess.check_output(
        [ "ps", "-p", str(pid), "-o", "ppid=" ],
        text = True, stderr = subprocess.DEVNULL,
      ).strip()
      pid = int(parent)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
      return None
  return None


# --- Lock file IO -------------------------------------------------------------

def _read_lock(repo_root: Path) -> Optional[LockState]:
  """
  Return the lock state currently persisted for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The parsed lock state, or None when no lock file exists or the file is unreadable.
  """
  path = _lock_path(repo_root)
  try:
    raw = json.loads(path.read_text())
  except (FileNotFoundError, json.JSONDecodeError, ValueError):
    return None
  try:
    return LockState(
      session_id = str(raw["session_id"]),
      pid = int(raw["pid"]),
      host = str(raw["host"]),
      branch = str(raw["branch"]),
      started_at = float(raw["started_at"]),
      last_index_mtime = float(raw["last_index_mtime"]),
    )
  except (KeyError, TypeError, ValueError):
    return None


def _write_lock(repo_root: Path, state: LockState) -> None:
  """
  Persist a lock state for the given repository.

  The write is crash-safe: an interrupted call leaves any previously existing lock file
  intact. The `.git/` directory is created when missing.

  Args:
    repo_root: Absolute path to the root of the repository.
    state: Lock state to persist.

  Raises:
    OSError: If the lock file or its parent directory cannot be written.
  """
  path = _lock_path(repo_root)
  path.parent.mkdir(parents = True, exist_ok = True)
  payload = {
    "session_id": state.session_id,
    "pid": state.pid,
    "host": state.host,
    "branch": state.branch,
    "started_at": state.started_at,
    "last_index_mtime": state.last_index_mtime,
  }
  fd, tmp = tempfile.mkstemp(dir = str(path.parent), prefix = ".lazy-git-", suffix = ".tmp")
  # noinspection PyBroadException
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(payload, f, indent = 2, sort_keys = True)
      f.write("\n")
    os.replace(tmp, path)
  except Exception:
    # best-effort cleanup of the temp file before re-raising the original failure
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise


def _delete_lock(repo_root: Path) -> None:
  """
  Remove the staging lock file for the given repository.

  The call is idempotent: a missing file is not an error.

  Args:
    repo_root: Absolute path to the root of the repository.
  """
  try:
    _lock_path(repo_root).unlink()
  except FileNotFoundError:
    pass


# --- Git state helpers --------------------------------------------------------

def _index_is_empty(repo_root: Path) -> bool:
  """
  Report whether the git index for the given repository currently has no staged changes.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    True when the index is empty (no staged entries), False otherwise.
  """
  # `--no-optional-locks` skips the stat-cache refresh that would otherwise write to
  # `.git/index.lock`. Read-only inspection of the index doesn't need the lock.
  rc = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(repo_root),
      "diff", "--cached", "--quiet" ],
    capture_output = True,
  ).returncode
  return rc == 0


def _current_branch(repo_root: Path) -> str:
  """
  Return the symbolic name of the current branch for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The branch name, or the literal `HEAD` when the repository is in a detached state or
    the probe fails.
  """
  try:
    return subprocess.check_output(
      [ "git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD" ],
      text = True, stderr = subprocess.DEVNULL,
    ).strip()
  except subprocess.CalledProcessError:
    return "HEAD"


def _index_mtime(repo_root: Path) -> float:
  """
  Return the modification time of the git index file as epoch seconds.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The epoch-seconds mtime of `.git/index`, or `0.0` when the file does not exist.
  """
  try:
    return (repo_root / ".git" / "index").stat().st_mtime
  except FileNotFoundError:
    return 0.0


# --- Inspect ------------------------------------------------------------------

def inspect(repo_root: Path) -> Optional[LockState]:
  """
  Return the current lock state for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The parsed lock state when a lock file exists and is readable, otherwise None.
  """
  return _read_lock(repo_root)


# --- Break-the-lock rules -----------------------------------------------------

BreakReason = Literal["dead_pid", "different_host", "stale_and_idle", "held"]


def _pid_alive(pid: int) -> bool:
  """
  Report whether the given process id refers to a running process.

  A `PermissionError` from the probe is treated as alive — the process exists but the
  current user lacks permission to signal it.

  Args:
    pid: Process id to probe.

  Returns:
    True when the process is reachable, False otherwise.
  """
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    # process exists but the current user is not permitted to signal it
    return True
  except OSError:
    return False
  return True


def _is_breakable(
  repo_root: Path,
  state: LockState,
  cfg: StagingConfig,
  now: float,
) -> tuple[bool, BreakReason]:
  """
  Decide whether a held lock qualifies for auto-break under the configured rules.

  Rules are applied in fixed order: dead pid, different host, stale-and-idle. The first
  matching rule wins; when none match the lock is considered actively held.

  Args:
    repo_root: Absolute path to the root of the repository.
    state: The lock state currently observed on disk.
    cfg: Configuration that supplies the stale-and-idle thresholds.
    now: Current wall-clock epoch seconds, supplied by the caller for testability.

  Returns:
    A pair of `(breakable, reason)` where `breakable` is True iff one of the rules matched
    and `reason` identifies the matching rule (or `held` when none matched).
  """
  # Rule 1: dead PID
  # guard: holder process no longer exists on this host
  if not _pid_alive(state.pid):
    return True, "dead_pid"
  # Rule 2: different host
  # guard: holder recorded a different host than the current one
  if state.host != socket.gethostname():
    return True, "different_host"
  # Rule 3: stale-and-idle
  age = now - state.started_at
  # guard: holder has exceeded the configured max-hold age
  if age > cfg.max_hold_seconds:
    current_index_mtime = _index_mtime(repo_root)
    # The index has not moved past last_index_mtime AND mtime itself is stale.
    index_idle = (
      current_index_mtime <= state.last_index_mtime
      and (now - max(current_index_mtime, state.last_index_mtime)) > cfg.max_idle_seconds
    )
    # guard: index has been idle long enough to declare the holder abandoned
    if index_idle:
      return True, "stale_and_idle"
  return False, "held"


def break_lock(repo_root: Path, reason: str) -> bool:
  """
  Force-delete the staging lock file for the given repository.

  The call is idempotent: invoking it when no lock exists is a no-op that returns False.

  Args:
    repo_root: Absolute path to the root of the repository.
    reason: Human-readable reason for the manual break, surfaced by callers in diagnostics.

  Returns:
    True when a lock file existed and was removed, False when no lock file was present.
  """
  path = _lock_path(repo_root)
  existed = path.exists()
  _delete_lock(repo_root)
  return existed


# --- Acquire ------------------------------------------------------------------

def _new_lock_state(repo_root: Path, session_id: str) -> LockState:
  """
  Build a fresh lock state describing the current process for the given session.

  Args:
    repo_root: Absolute path to the root of the repository.
    session_id: Identifier of the Claude Code session that will own the lock.

  Returns:
    A `LockState` populated with the current process id, hostname, branch, and index mtime.
  """
  return LockState(
    session_id = session_id,
    pid = os.getpid(),
    host = socket.gethostname(),
    branch = _current_branch(repo_root),
    started_at = time.time(),
    last_index_mtime = _index_mtime(repo_root),
  )


def acquire(
  repo_root: Path,
  session_id: str,
  cfg: StagingConfig,
) -> AcquireResult:
  """
  Attempt to acquire the staging lock for the given repository and session.

  When the lock is held by a live peer the call polls with jittered backoff until either
  the lock can be taken, the peer becomes breakable, or the configured wait deadline
  expires. Re-entry from the same session is a no-op that returns immediately.

  Args:
    repo_root: Absolute path to the root of the repository.
    session_id: Identifier of the Claude Code session requesting the lock.
    cfg: Configuration that supplies the wait deadline and break thresholds.

  Returns:
    An `AcquireResult` describing the outcome of the attempt.
  """
  # guard: mutex is disabled in this repository — fast-path success
  if not cfg.enabled:
    return AcquireResult(status = "acquired", held_by_us = True,
                         message = "staging lock disabled (lazy-core.git.enabled=false)")

  deadline = time.time() + cfg.wait_seconds
  waited = 0.0
  first_pass = True

  while True:
    existing = _read_lock(repo_root)

    # No lock — take it.
    # guard: no current holder, claim the lock immediately
    if existing is None:
      _write_lock(repo_root, _new_lock_state(repo_root, session_id))
      status: AcquireStatus = "acquired" if first_pass else "waited_then_acquired"
      return AcquireResult(status = status, held_by_us = True, waited_seconds = waited)

    # Lock is ours — re-entry.
    # guard: lock is already held by the requesting session
    if existing.session_id == session_id:
      return AcquireResult(status = "reentered", held_by_us = True, waited_seconds = waited)

    # Held by peer — check if breakable.
    breakable, reason = _is_breakable(repo_root, existing, cfg, now = time.time())
    # guard: peer lock qualifies for auto-break under the configured rules
    if breakable:
      _delete_lock(repo_root)
      _write_lock(repo_root, _new_lock_state(repo_root, session_id))
      return AcquireResult(
        status = "broke_then_acquired", held_by_us = True,
        break_reason = reason, peer = existing, waited_seconds = waited,
      )

    # Held by live peer; check deadline.
    now = time.time()
    # guard: wait deadline reached without acquiring the lock
    if now >= deadline:
      return AcquireResult(
        status = "refused", held_by_us = False, peer = existing, waited_seconds = waited,
        message = _refusal_message(existing, cfg, now),
      )

    # Sleep with jitter, then retry.
    sleep_ms = random.randint(POLL_MIN_MS, POLL_MAX_MS)
    sleep_s = min(sleep_ms / 1000.0, max(0.0, deadline - now))
    time.sleep(sleep_s)
    waited += sleep_s
    first_pass = False


def _refusal_message(peer: LockState, cfg: StagingConfig, now: float) -> str:
  """
  Compose a human-readable diagnostic for a refused acquire attempt.

  Args:
    peer: Lock state of the holder that caused the refusal.
    cfg: Configuration whose `max_hold_seconds` informs the auto-break hint.
    now: Current wall-clock epoch seconds.

  Returns:
    A single-line message naming the peer branch, pid, age, and the time remaining until
    the stale-and-idle rule would auto-break the lock.
  """
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
  """
  Release the staging lock for the given session only when the index is now empty.

  The release is conditional on two facts: the lock must currently be held by the supplied
  session, and the git index for the repository must contain no staged entries. When
  either precondition fails the lock is left untouched.

  Args:
    repo_root: Absolute path to the root of the repository.
    session_id: Identifier of the Claude Code session requesting the release.

  Returns:
    A `ReleaseResult` describing whether the lock was deleted and why.
  """
  state = _read_lock(repo_root)
  # guard: no lock file currently exists for this repository
  if state is None:
    return ReleaseResult(released = False, reason = "no_lock")
  # guard: lock is held by a different session and must not be released
  if state.session_id != session_id:
    return ReleaseResult(released = False, reason = "not_our_lock")
  # guard: index still has staged entries — staging window is not closed
  if not _index_is_empty(repo_root):
    return ReleaseResult(released = False, reason = "index_not_empty")
  _delete_lock(repo_root)
  return ReleaseResult(released = True, reason = "released")


# --- Config -------------------------------------------------------------------

_SETTINGS_REL = ".claude/lazy.settings.json"
_SECTION = "git"


def load_config(repo_root: Path) -> StagingConfig:
  """
  Load staging-mutex configuration from the repository's lazy settings.

  Reads the `git` section of `<repo>/.claude/lazy.settings.json` when present; missing
  keys fall back to module-level defaults. A malformed settings file produces a fully
  default configuration rather than an error.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    A `StagingConfig` reflecting the merged configuration.
  """
  settings_path = repo_root / _SETTINGS_REL
  section: dict = {}
  # guard: settings file exists for this repository
  if settings_path.exists():
    # Inline the lazy_settings import so the helper has zero hard dependency on
    # lazy_settings being importable. Hooks are short-lived and import latency matters;
    # defer to first use.
    # noinspection PyBroadException
    try:
      sys.path.insert(0, str(Path(__file__).parent))
      import lazy_settings  # type: ignore
      section = lazy_settings.load_section(settings_path, _SECTION)
    except Exception:
      # noinspection PyBroadException
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
    enabled = bool(section.get("enabled", DEFAULT_ENABLED)),
    wait_seconds = float(section.get("wait_seconds", DEFAULT_WAIT_SECONDS)),
    max_hold_seconds = float(section.get("max_hold_seconds", DEFAULT_MAX_HOLD_SECONDS)),
    max_idle_seconds = float(section.get("max_idle_seconds", DEFAULT_MAX_IDLE_SECONDS)),
  )
