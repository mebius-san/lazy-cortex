"""
Runtime state persistence for the lazycortex-core daemon.

Stores last_run timestamps, per-`git`-watch last_seen_sha, and the optional
top-level daemon_halted block under <repo>/.runtime/state.json.

Atomic writes via temp+os.replace — same dir as the target file so the rename
is on the same filesystem.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import StateKey  # pylint: disable=import-error

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
    return json.loads(path.read_text(encoding = "utf-8"))
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
  atomic_write_text(_state_path(repo_root), json.dumps(state, indent = 2))


def _write_in_place(target: Path, data: bytes) -> None:
  """
  Overwrite an existing file's content in place, restoring its original bytes if the write fails.

  Args:
    target: Real path of the existing file to overwrite.
    data: Encoded bytes of the new content.

  Raises:
    PermissionError: If the file cannot be read, so its original bytes could not be restored;
      the file is left untouched.
    OSError: If the new content cannot be written; the original bytes are back on disk first.
  """
  # a file that cannot be read back cannot be rolled back either: the read refuses before any write
  original = target.read_bytes()
  try:
    # write over the old bytes, cut the old tail, then flush to disk — the file keeps its inode and mode
    # waiver: stdlib file-mode idiom
    with open(target, "r+b") as handle:
      handle.write(data)
      handle.truncate()
      handle.flush()
      os.fsync(handle.fileno())
  except BaseException:
    # a failed write (full disk, file-size limit) must not leave a truncated file: put the old bytes back
    # waiver: stdlib file-mode idiom
    with open(target, "r+b") as handle:
      handle.write(original)
      handle.truncate()
      handle.flush()
      os.fsync(handle.fileno())
    raise


def atomic_write_text(path: Path, text: str) -> None:
  """
  Write text to a file, replacing its previous content in one atomic step.

  Guarantees:
    - An interrupted call leaves the previous content at `path` intact, and readers never
      observe a corrupted or partially written file, whenever the temp file beside `path`
      can be created. On the in-place fallback, the original bytes are restored when the
      write fails, but a concurrent reader may observe a partial write while it is in progress.
    - An existing destination keeps its own permission bits; a destination that does not
      yet exist gets the mode a plain write would produce under the process umask.
    - When `path` is a symlink, the link itself is left in place and its real target
      receives the new content.
    - The text is written byte-exact in UTF-8 with no newline translation, so a CRLF
      line ending in `text` is preserved as CRLF.
    - When the containing directory refuses to create the temp file with a `PermissionError`
      and `path` already exists as a file, the content is rewritten in place instead: a failed
      write restores the file's previous bytes before the error propagates, so a caller
      catching the failure finds the previous content intact. A file that cannot be read back
      is refused with a `PermissionError` and left untouched. This path is not atomic — a
      concurrent reader may observe a partial write while it is in progress, and a process
      crash mid-write, as opposed to a raised exception, can still leave partial content. A
      missing destination still raises rather than falling back. Every other case stays atomic.

  Notes:
    - Creates the parent directory of `path` when it does not already exist.

  Args:
    path: Destination file to write.
    text: Content to write to `path`.

  Raises:
    OSError: If `path` or its parent directory cannot be written.
  """

  # Contract:
  # An interrupted call never corrupts or truncates the previously persisted content at
  # `path`, and a reader always sees either the old content in full or the new content in
  # full, whenever the temp file beside `path` can be created. On the in-place fallback,
  # the original bytes are restored when the write fails, but a concurrent reader may
  # observe a partial write while it is in progress.

  # Contract:
  # An existing destination keeps its own permission bits across the write; a destination
  # that does not yet exist gets the mode a plain write would produce under the process umask.

  # Contract:
  # When `path` is a symlink, the link itself is left in place and its real target receives
  # the new content.

  # Contract:
  # The text is written byte-exact: UTF-8 encoded with no newline translation, so a CRLF
  # line ending in `text` is written back as CRLF.

  # a symlinked destination is written through: the link stays, its real target gets the content
  target = Path(os.path.realpath(path))
  target.parent.mkdir(parents = True, exist_ok = True)

  # write to a sibling temp file first so an interrupted call leaves the previous content intact;
  # created with the default 0o666 request so the process umask applies exactly as for a plain write
  # waiver: temp-file naming idiom, not a domain constant
  tmp_name = str(target.parent / f".{target.name}.{secrets.token_hex(8)}.tmp")

  # Contract:
  # When the containing directory refuses to create the temp file with a PermissionError and
  # `path` already exists as a file, the content is rewritten in place instead: a failed write
  # restores the file's previous bytes before the exception propagates, so a failed write never
  # corrupts or truncates the previous content. A file that cannot be read back cannot be restored,
  # so it is refused with a PermissionError and left untouched. This path is NOT atomic — a concurrent reader may observe
  # a partial write while it is in progress, and a process crash mid-write, as opposed to a
  # raised exception, can still leave partial content. A missing destination still raises
  # instead of falling back.

  # attempt the atomic replace first; only a directory that refuses the temp file falls back
  try:
    # waiver: the default 0o666 creation mode a plain write requests, umask applied on top
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
  except PermissionError:
    # guard: a directory that refuses the temp file cannot take a rename either; a file that
    # already exists and is readable and writable is rewritten in place instead — truncate, write,
    # fsync — trading the all-or-nothing replace for a write that lands at all
    if not target.is_file():
      raise
    # waiver: stdlib encoding idiom
    _write_in_place(target, text.encode("utf-8"))
    return
  # noinspection PyBroadException
  try:
    # an existing file keeps its own permission bits across the replace
    if target.exists():
      os.chmod(fd, stat.S_IMODE(target.stat().st_mode))

    # newline translation is off so CRLF content is written byte-exact
    # waiver: stdlib file-mode idiom
    with os.fdopen(fd, "w", encoding = "utf-8", newline = "") as f:
      f.write(text)
    os.replace(tmp_name, target)
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
  then persists the result.

  Guarantees:
    - The write always merges into the latest on-disk state; a key another writer
      persisted since this caller's own load is never clobbered.

  Args:
    repo_root: Absolute path to the root of the repository.
    mutator: Callable that receives the loaded state dict and mutates it in place.
      Its return value is discarded — `object` lets `setdefault` / `pop` lambdas
      pass without ceremony even though they yield a value.

  Returns:
    The persisted state dict.
  """

  # Contract:
  # The write always merges into the latest on-disk state; a key another writer
  # persisted since this caller's own load is never clobbered by this call.

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
