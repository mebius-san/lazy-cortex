#!/usr/bin/env python3

"""
install_fs — directory and move primitives for install skills.

Creates consumer directories and moves consumer files from a subprocess, so an install that runs as a background
subagent never issues a shell write or a file-tool write to a protected path that the session would have to approve.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Exit status of a verb that could not ensure a directory, write a keep-file, or land a move.
EXIT_FAILED = 3

# File name of the empty marker that keeps an otherwise empty directory tracked.
GITKEEP_NAME = ".gitkeep"


# ----------------------------------------------------------------------------------------
class FsState:
  """
  Outcome words the verbs report per directory, keep-file and move.

  Attributes:
    CREATED: The directory was absent and now exists.
    ALREADY_EXISTS: The directory was already there.
    NOT_A_DIRECTORY: Something other than a directory holds the path and was left alone.
    MOVED: The file now lives at its new path.
    KEPT_BOTH: The target was taken, so neither file was touched.
    ABSENT: There was no source file to move.
    FAILED: The filesystem refused the operation.
    INSTALLED: The keep-file was written.
    UNCHANGED: The keep-file was already there.
  """

  # The directory was absent and now exists.
  CREATED = "created"
  # The directory was already there.
  ALREADY_EXISTS = "already-exists"
  # Something other than a directory holds the path and was left alone.
  NOT_A_DIRECTORY = "not-a-directory"
  # The file now lives at its new path.
  MOVED = "moved"
  # The target was taken, so neither file was touched.
  KEPT_BOTH = "kept-both"
  # There was no source file to move.
  ABSENT = "absent"
  # The filesystem refused the operation.
  FAILED = "failed"
  # The keep-file was written.
  INSTALLED = "installed"
  # The keep-file was already there.
  UNCHANGED = "unchanged"


# ----------------------------------------------------------------------------------------
class ReceiptKey:
  """
  Field names of the JSON receipts the verbs print.

  Attributes:
    PATH: The directory one result is about.
    STATE: The outcome word of one result or of the move.
    GITKEEP: The keep-file outcome of one directory.
    SRC: The file the move started from.
    DST: The path the move targeted.
    PRUNED: Whether the emptied source directory was removed.
    RESULTS: The per-directory results.
    FAILED: The directories the caller must act on.
  """

  # The directory one result is about.
  PATH = "path"
  # The outcome word of one result or of the move.
  STATE = "state"
  # The keep-file outcome of one directory.
  GITKEEP = "gitkeep"
  # The file the move started from.
  SRC = "src"
  # The path the move targeted.
  DST = "dst"
  # Whether the emptied source directory was removed.
  PRUNED = "pruned"
  # The per-directory results.
  RESULTS = "results"
  # The directories the caller must act on.
  FAILED = "failed"


# Directory outcomes that leave the caller something to act on.
_FAILED_STATES = frozenset({ FsState.NOT_A_DIRECTORY, FsState.FAILED })


def _ensure_gitkeep(directory: str) -> str:
  """
  Place an empty keep-file in a directory unless one is already there.

  Args:
    directory: Existing directory that must stay tracked while empty.

  Returns:
    `installed` when the keep-file was written, `unchanged` when it was present, `failed` on a write error.
  """
  # an existing keep-file is left as it is, whatever it holds
  marker = os.path.join(directory, GITKEEP_NAME)
  if os.path.exists(marker):
    return FsState.UNCHANGED

  # an empty file is the whole keep-file
  try:
    with open(marker, "x", encoding = "utf-8"):
      pass
  except OSError:
    return FsState.FAILED
  return FsState.INSTALLED


def _create_dir(path: str) -> str:
  """
  Create a directory together with its missing parents.

  Args:
    path: Directory to create.

  Returns:
    `created` when the directory exists afterwards, `failed` when the filesystem refused to create it.
  """
  # a refused creation is a verdict, not an exception for the caller
  try:
    os.makedirs(path, exist_ok = True)
  except OSError:
    return FsState.FAILED
  return FsState.CREATED


def ensure_dirs(paths: list[str], *, gitkeep: bool = False) -> list[dict[str, str]]:
  """
  Make sure every named directory exists, creating missing parents.

  Guarantees:
    - A path occupied by something other than a directory is reported as `not-a-directory` and left untouched.

  Args:
    paths: Directories to ensure, in the order they are reported.
    gitkeep: When True, every directory that exists afterwards also carries an empty keep-file.

  Returns:
    One result per path: `{"path", "state"}`. When `gitkeep` is set, a result whose `state` is `created` or
    `already-exists` also carries `"gitkeep"`; `not-a-directory` and `failed` results never do.
  """

  # Contract:
  # A path that exists as anything other than a directory MUST NEVER be removed, replaced, or written into; it is
  # reported as `not-a-directory` so the caller sees the obstruction instead of a silent overwrite.

  # each path gets its own verdict, so one obstruction never hides the rest
  results = []
  for path in paths:
    # guard: something that is not a directory already holds the path
    if os.path.lexists(path) and not os.path.isdir(path):
      results.append({ ReceiptKey.PATH: path, ReceiptKey.STATE: FsState.NOT_A_DIRECTORY })
      continue

    # a present directory is only reported, an absent one is created
    if os.path.isdir(path):
      state = FsState.ALREADY_EXISTS
    else:
      state = _create_dir(path)

    # the entry names the path and its verdict
    entry = { ReceiptKey.PATH: path, ReceiptKey.STATE: state }

    # the keep-file follows only a directory that now exists
    if gitkeep and state != FsState.FAILED:
      entry[ReceiptKey.GITKEEP] = _ensure_gitkeep(path)
    results.append(entry)

  # results keep the caller's order
  return results


def move_file(src: str, dst: str, *, prune_src_dir: bool = False) -> dict[str, str | bool]:
  """
  Move one file to a new path unless the new path is already taken.

  Guarantees:
    - An existing target is never overwritten; both files are left as they are.
    - The source directory is never removed while it holds anything; it is pruned only when the move left it empty
      and the caller asked for it.

  Args:
    src: File to move.
    dst: Path the file moves to; missing parents are created.
    prune_src_dir: When True, the source's directory is removed after a move that left it empty.

  Returns:
    `{"src", "dst", "state", "pruned"}`, where `state` is `moved`, `kept-both`, `absent` or `failed`.
  """

  # Contract:
  # An existing target MUST NEVER be overwritten — it may be the operator's file, and a same-named source confers no
  # claim on it. Both files are left in place and the outcome is `kept-both`.

  # Contract:
  # The source directory MUST NEVER be removed while it holds anything; pruning is reported only for a directory the
  # move left empty, and only when the caller asked for it.

  # the outcome starts as "nothing moved" and is refined below
  outcome: dict[str, str | bool] = {
    ReceiptKey.SRC: src, ReceiptKey.DST: dst, ReceiptKey.STATE: FsState.ABSENT, ReceiptKey.PRUNED: False,
  }

  # guard: nothing to move
  if not os.path.isfile(src):
    return outcome

  # guard: the target is taken and stays the operator's
  if os.path.lexists(dst):
    outcome[ReceiptKey.STATE] = FsState.KEPT_BOTH
    return outcome

  # the move creates the target's parents first
  try:
    os.makedirs(os.path.dirname(dst) or ".", exist_ok = True)
    shutil.move(src, dst)
  except OSError:
    outcome[ReceiptKey.STATE] = FsState.FAILED
    return outcome
  outcome[ReceiptKey.STATE] = FsState.MOVED

  # an emptied source directory goes only when the caller asked for it
  src_dir = os.path.dirname(src)
  if prune_src_dir and src_dir and not os.listdir(src_dir):
    try:
      os.rmdir(src_dir)
      outcome[ReceiptKey.PRUNED] = True
    except OSError:
      # waiver: a directory that refuses removal simply stays; the move already landed and `pruned` stays false
      pass
  return outcome


def cmd_ensure_dirs(argv: list[str]) -> int:
  """
  Run the `ensure-dirs` verb and print its JSON receipt.

  Args:
    argv: Arguments after the verb.

  Returns:
    Exit status: 0 when every directory exists afterwards and every requested keep-file is in place, 3 when a
    directory could not be ensured or a requested keep-file could not be written.

  Raises:
    SystemExit: If the arguments do not parse.
  """

  # Contract:
  # The exit status MUST be 3 whenever the receipt's `failed` list is non-empty, and `failed` MUST name every path
  # whose directory is not there afterwards or whose requested keep-file could not be written; install skills read
  # either signal as "this directory was not ensured".

  # the CLI surface: the directories plus the keep-file switch
  parser = argparse.ArgumentParser(prog = "ensure-dirs", description = "Ensure consumer directories exist.")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("paths", nargs = "+", metavar = "PATH", help = "directory to ensure (repeatable)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--gitkeep", action = "store_true", help = "place an empty .gitkeep in every directory")
  args = parser.parse_args(argv)

  # the receipt hoists the paths the caller must act on
  results = ensure_dirs(args.paths, gitkeep = args.gitkeep)
  failed = [ entry[ReceiptKey.PATH] for entry in results
             if entry[ReceiptKey.STATE] in _FAILED_STATES or entry.get(ReceiptKey.GITKEEP) == FsState.FAILED ]
  print(json.dumps({ ReceiptKey.RESULTS: results, ReceiptKey.FAILED: failed }, indent = 2))

  # any path the caller must act on turns the exit status to failure
  if failed:
    return EXIT_FAILED
  return 0


def cmd_move_file(argv: list[str]) -> int:
  """
  Run the `move-file` verb and print its JSON receipt.

  Args:
    argv: Arguments after the verb.

  Returns:
    Exit status: 0 when the move finished or was skipped without error, 3 when the move itself failed.

  Raises:
    SystemExit: If the arguments do not parse.
  """
  # the CLI surface: the source/target pair plus the prune switch
  parser = argparse.ArgumentParser(prog = "move-file", description = "Move a consumer file without overwriting.")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--src", required = True, help = "file to move")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dst", required = True, help = "path the file moves to")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--prune-src-dir", action = "store_true", help = "remove the source directory once empty")
  args = parser.parse_args(argv)

  # the receipt is the whole outcome
  outcome = move_file(args.src, args.dst, prune_src_dir = args.prune_src_dir)
  print(json.dumps(outcome, indent = 2))

  # a move that did not land turns the exit status to failure
  if outcome[ReceiptKey.STATE] == FsState.FAILED:
    return EXIT_FAILED
  return 0
