#!/usr/bin/env python3

"""
file_sync — deterministic triage for install-managed file mirrors.

Compares a shipped source (file or flat directory) against its consumer-side target,
copies what is mechanically safe (absent targets; diverged targets under
--copy-diverged), and emits a machine-readable receipt so the calling skill only
exercises judgment on genuinely diverged files.
"""
from __future__ import annotations

import argparse
import filecmp
import fnmatch
import json
import os
import shutil
import stat
import sys

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


STATE_INSTALLED = "installed"
STATE_UNCHANGED = "unchanged"
STATE_DIVERGED = "diverged"
STATE_REFRESHED = "refreshed"
STATE_KEPT_ORPHAN = "kept-orphan"

KEY_FILE = "file"
KEY_SRC = "src"
KEY_DST = "dst"
KEY_STATE = "state"


def _ensure_exec(path: str) -> None:
  """
  Set the executable bits (user/group/other) on a file, preserving its other mode bits.

  Args:
    path: Filesystem path of the file to mark executable.
  """
  mode = os.stat(path).st_mode
  os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sync_one(src: str, dst: str, *, copy_diverged: bool = False, chmod_x: bool = False) -> str:
  """
  Triage a single source/target pair and copy when mechanically safe.

  Args:
    src: Path of the shipped source file.
    dst: Path of the consumer-side target file.
    copy_diverged: When True, a diverged target is overwritten with the source
      (state `refreshed`) instead of being reported for merge judgment.
    chmod_x: When True, ensure the target carries executable bits after sync.

  Returns:
    One of `installed`, `unchanged`, `refreshed`, `diverged`.
  """
  os.makedirs(os.path.dirname(dst) or ".", exist_ok = True)
  if not os.path.exists(dst):
    shutil.copyfile(src, dst)
    state = STATE_INSTALLED
  elif filecmp.cmp(src, dst, shallow = False):
    state = STATE_UNCHANGED
  elif copy_diverged:
    shutil.copyfile(src, dst)
    state = STATE_REFRESHED
  else:
    state = STATE_DIVERGED
  # guard: a diverged target awaiting merge judgment must not be mutated, not even its mode bits
  if chmod_x and state != STATE_DIVERGED:
    _ensure_exec(dst)
  return state


def sync_dir(
  src_dir: str,
  dst_dir: str,
  *,
  excludes: frozenset[str] = frozenset(),
  owned_globs: tuple[str, ...] = (),
  copy_diverged: bool = False,
  chmod_x: bool = False,
) -> list[dict[str, str]]:
  """
  Triage every file of a flat source directory against the target directory.

  Args:
    src_dir: Directory holding the shipped source files (flat — subdirectories are ignored).
    dst_dir: Consumer-side target directory (created when missing).
    excludes: Basenames to skip entirely (e.g. plugin-internal manifests).
    owned_globs: fnmatch patterns naming the caller's owned namespaces; target files
      matching one of them with no same-name source are reported as `kept-orphan`.
    copy_diverged: Forwarded to the per-file triage.
    chmod_x: Forwarded to the per-file triage.

  Returns:
    One result dict per file: `{"file", "src", "dst", "state"}`.
  """
  results = []
  names = sorted(
    entry for entry in os.listdir(src_dir)
    if entry not in excludes and os.path.isfile(os.path.join(src_dir, entry))
  )
  for name in names:
    src = os.path.join(src_dir, name)
    dst = os.path.join(dst_dir, name)
    state = sync_one(src, dst, copy_diverged = copy_diverged, chmod_x = chmod_x)
    results.append({ KEY_FILE: name, KEY_SRC: src, KEY_DST: dst, KEY_STATE: state })
  synced = { entry[KEY_FILE] for entry in results }
  # guard: orphan detection is reporting-only and needs both patterns and an existing target dir
  if not owned_globs or not os.path.isdir(dst_dir):
    return results
  for name in sorted(os.listdir(dst_dir)):
    # guard: only owned, not-just-synced plain files count as orphans
    if name in synced or name in excludes or not os.path.isfile(os.path.join(dst_dir, name)):
      continue
    if any(fnmatch.fnmatch(name, pattern) for pattern in owned_globs):
      orphan = os.path.join(dst_dir, name)
      results.append({ KEY_FILE: name, KEY_SRC: "", KEY_DST: orphan, KEY_STATE: STATE_KEPT_ORPHAN })
  return results


def main(argv: list[str]) -> int:
  """
  Run the file-sync CLI and print its JSON triage receipt to stdout.

  Args:
    argv: Command-line arguments (without the program name).

  Returns:
    Process exit code — 0 on success, 2 on a missing source path.
  """
  # waiver: argparse CLI signature and help strings, not domain keys (whole block below)
  parser = argparse.ArgumentParser(description = "Deterministic file-sync triage for install-managed mirrors.")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--src", required = True, help = "shipped source: a file, or a flat directory")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dst", required = True,
                      help = "consumer target: a file path (file mode) or directory (dir mode)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--exclude", action = "append", default = [], metavar = "NAME",
                      help = "basename to skip (repeatable; dir mode)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--owned-glob", action = "append", default = [], metavar = "PATTERN",
                      help = "fnmatch pattern of an owned namespace for orphan reporting (repeatable; dir mode)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--copy-diverged", action = "store_true",
                      help = "overwrite diverged targets with the source (state 'refreshed')")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--chmod-x", action = "store_true", help = "ensure executable bits on synced targets")
  args = parser.parse_args(argv)
  # guard: a missing source is a caller error, not a triage state
  if not os.path.exists(args.src):
    print(json.dumps({ "error": f"source not found: {args.src}" }))
    return 2
  if os.path.isdir(args.src):
    results = sync_dir(
      args.src, args.dst,
      excludes = frozenset(args.exclude),
      owned_globs = tuple(args.owned_glob),
      copy_diverged = args.copy_diverged,
      chmod_x = args.chmod_x,
    )
  else:
    state = sync_one(args.src, args.dst, copy_diverged = args.copy_diverged, chmod_x = args.chmod_x)
    results = [ { KEY_FILE: os.path.basename(args.dst), KEY_SRC: args.src, KEY_DST: args.dst, KEY_STATE: state } ]
  counts: dict[str, int] = {}
  for entry in results:
    counts[entry[KEY_STATE]] = counts.get(entry[KEY_STATE], 0) + 1
  receipt = {
    "results": results,
    "counts": counts,
    "diverged": [ entry[KEY_DST] for entry in results if entry[KEY_STATE] == STATE_DIVERGED ],
  }
  print(json.dumps(receipt, indent = 2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
