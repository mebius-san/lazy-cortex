"""
Runtime state persistence for the lazycortex-core daemon.

Stores last_run timestamps, per-`git`-watch last_seen_sha, and the optional
top-level daemon_halted block under <repo>/.runtime/state.json.

Atomic writes via temp+os.replace — same dir as the target file so the rename
is on the same filesystem.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import tempfile
from pathlib import Path

from constants import StateKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


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
  return { StateKey.LAST_RUN: {}, StateKey.GIT_WATCH: {} }


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
  # waiver: temp-file naming idiom, not a domain constant
  fd, tmp_name = tempfile.mkstemp(prefix = ".state.", suffix = ".tmp", dir = str(path.parent))
  # noinspection PyBroadException
  try:
    # waiver: stdlib file-mode idiom
    with os.fdopen(fd, "w") as f:
      json.dump(state, f, indent = 2)
    os.replace(tmp_name, path)
  except Exception:
    # best-effort cleanup of the temp file before re-raising the original failure
    try:
      os.unlink(tmp_name)
    except OSError:
      pass
    raise


def update(repo_root: Path, mutator: Callable[[dict], object]) -> dict:
  """
  Atomically read-modify-write the state file.

  Loads the current on-disk state, applies `mutator` (which mutates the dict in place),
  then persists the result. Re-reading on every call is what prevents one writer from
  clobbering a key another writer set since the caller last loaded — every write merges
  into the latest on-disk content rather than overwriting a held snapshot.

  Args:
    repo_root: Absolute path to the root of the repository.
    mutator: Callable that receives the loaded state dict and mutates it in place.
      Its return value is discarded — `object` lets `setdefault` / `pop` lambdas
      pass without ceremony even though they yield a value.

  Returns:
    The persisted state dict.
  """
  state = load(repo_root)
  mutator(state)
  save(repo_root, state)
  return state


def get_halted(repo_root: Path) -> dict | None:
  """
  Return the stored `daemon_halted` block for the given repository, or None if the daemon is not halted.

  Args:
    repo_root: Absolute path to the root of the repository.

  Returns:
    The `daemon_halted` dict from the persisted state, or None if no halt block is present.
  """
  return load(repo_root).get(StateKey.DAEMON_HALTED)


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
  state[StateKey.DAEMON_HALTED] = block
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
  state.pop(StateKey.DAEMON_HALTED, None)
  save(repo_root, state)
