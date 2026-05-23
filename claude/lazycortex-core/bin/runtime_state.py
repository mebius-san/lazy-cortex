"""
Runtime state persistence for the lazycortex-core daemon.

Stores last_run timestamps, per-`git`-watch last_seen_sha, and the optional
top-level daemon_halted block under <repo>/.runtime/state.json.

Atomic writes via temp+os.replace — same dir as the target file so the rename
is on the same filesystem.
"""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path

STATE_REL = ".runtime/state.json"


def _state_path(repo_root: Path) -> Path:
  """
  Return the canonical path to the state file for the given repository root.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    Path to `<repo_root>/.runtime/state.json`.
  """
  return Path(repo_root) / STATE_REL


def _empty_state() -> dict:
  """
  Return a default state dict used when no persisted state is available.

  Returns:
    A dict with empty `last_run` and `git_watch` mappings and no `daemon_halted` block.
  """
  return { "last_run": {}, "git_watch": {} }


def load(repo_root: Path) -> dict:
  """
  Return the persisted daemon state for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The stored state dict, or a fresh default state when no state file exists or the file is
    not valid JSON.
  """
  path = _state_path(repo_root)
  # guard: no persisted state yet — return fresh default
  if not path.exists():
    return _empty_state()
  try:
    return json.loads(path.read_text())
  except json.JSONDecodeError:
    # corrupt or partial state file — fall back to fresh default
    return _empty_state()


def save(repo_root: Path, state: dict) -> None:
  """
  Persist the given state dict to disk for the given repository.

  Notes:
    - Creates the `.runtime/` directory if it does not exist.
    - The write is crash-safe: an interrupted call leaves the previous state intact.

  Args:
    repo_root: Absolute path to the root of the repository.
    state: State dict to persist.

  Raises:
    OSError: If the state file or its parent directory cannot be written.
  """
  path = _state_path(repo_root)
  path.parent.mkdir(parents = True, exist_ok = True)
  # write to a sibling temp file first so an interrupted call leaves the previous state intact
  fd, tmp_name = tempfile.mkstemp(prefix = ".state.", suffix = ".tmp", dir = str(path.parent))
  # noinspection PyBroadException
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(state, f, indent = 2)
    os.replace(tmp_name, path)
  except Exception:
    # best-effort cleanup of the temp file before re-raising the original failure
    try: os.unlink(tmp_name)
    except OSError: pass
    raise


def get_halted(repo_root: Path) -> dict | None:
  """
  Return the stored `daemon_halted` block for the given repository, or None if the daemon is not halted.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The `daemon_halted` dict from the persisted state, or None if no halt block is present.
  """
  return load(repo_root).get("daemon_halted")


def set_halted(repo_root: Path, block: dict) -> None:
  """
  Store a `daemon_halted` block in the persisted state for the given repository.

  Args:
    repo_root: Absolute path to the root of the repository.
    block: Halt-reason dict to store under the `daemon_halted` key.

  Raises:
    OSError: If the updated state cannot be written to disk.
  """
  state = load(repo_root)
  state["daemon_halted"] = block
  save(repo_root, state)


def clear_halted(repo_root: Path) -> None:
  """
  Remove the `daemon_halted` block from the persisted state for the given repository.

  If no halt block is present, the call completes without error and leaves the state unchanged.

  Args:
    repo_root: Absolute path to the root of the repository.

  Raises:
    OSError: If the updated state cannot be written to disk.
  """
  state = load(repo_root)
  state.pop("daemon_halted", None)
  save(repo_root, state)
