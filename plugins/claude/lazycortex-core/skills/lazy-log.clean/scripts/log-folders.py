#!/usr/bin/env python3

"""
Classify the run-log folders against the canonical artifact names and apply the operator's cleanup.

Offers two subcommands over one log root: `classify` reports every folder's bucket and file statistics as
JSON, `apply` merges and deletes the folders the operator chose and reports what it refused.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from types import ModuleType


# The canonical-name resolver this script reuses, beside it on disk.
_RESOLVER = Path(__file__).resolve().parent / "resolve-canonical.py"
_RESOLVER_MODULE = "resolve_canonical"
# The resolver's list of every canonical name.
_RESOLVED_CANONICAL = "canonical"
# The resolver's list of names whose artifacts write a run log.
_LOGGED = "logged"
# Where the run logs live, relative to the working directory.
_DEFAULT_ROOT = ".logs/claude"
# A rename candidate's minimum similarity to a canonical name.
_RENAME_RATIO = 0.8
_RATIO_DIGITS = 3
# Folder names a dispatched task or plan run leaves behind.
_ORPHAN_PATTERNS = tuple(re.compile(pattern) for pattern in (
  r"^task-\d+$", r"^subagent-task-\d+$", r"^subagent-audit-fixup$", r"^plan-execute$", r"^plan-execute-\d+$",
))
_MD = ".md"
# The bucket names of the classification, in the skill's table order.
_UNLOGGED, _CANONICAL, _RENAME, _PATTERN, _OTHER = (
  "unlogged", "canonical", "orphan-rename-candidate", "orphan-pattern", "orphan-other",
)
# Refusal reasons of the apply pass.
_INVALID, _MISSING, _EXISTS = "invalid-name", "missing", "exists-in-target"


def _load_resolver() -> ModuleType:
  """
  Load the canonical-name resolver module that sits beside this script.

  Returns:
    The loaded resolver module.

  Raises:
    FileNotFoundError: If the resolver file cannot be loaded as a module.
  """
  # the resolver's file name carries a hyphen, so it is loaded by path rather than imported
  spec = importlib.util.spec_from_file_location(_RESOLVER_MODULE, _RESOLVER)

  # guard: a resolver missing beside this script cannot be loaded
  if spec is None or spec.loader is None:
    raise FileNotFoundError(_RESOLVER)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def load_canonical() -> tuple[set[str], set[str]]:
  """
  Load the canonical artifact names visible to this session.

  Returns:
    The set of every canonical name and the subset of names whose artifacts write a run log.

  Raises:
    FileNotFoundError: If the canonical-name resolver file cannot be loaded.
  """
  # the canonical names and the logged subset, as the resolver reports them
  result = _load_resolver().find_all_canonical_names()
  return set(result[_RESOLVED_CANONICAL]), set(result[_LOGGED])


def _read_folder_stats(folder: Path) -> dict:
  """
  Summarize the run logs inside one log folder.

  Args:
    folder: Log folder to summarize.

  Returns:
    A mapping with the folder name, its log file count, and the oldest and newest log file names, which are
    `None` for an empty folder.
  """
  # log files are timestamp-named, so a lexical sort is chronological
  logs = sorted(name for name in os.listdir(folder) if name.endswith(_MD) and (folder / name).is_file())
  return {
    "name": folder.name, "file_count": len(logs),
    "oldest": logs[0] if logs else None, "newest": logs[-1] if logs else None,
  }


def _find_best_match(name: str, canonical: set[str]) -> tuple[str, float] | None:
  """
  Find the canonical name a folder name most likely stands for.

  Args:
    name: Folder name to match.
    canonical: Canonical artifact names to compare against.

  Returns:
    The closest canonical name with its similarity ratio, or `None` when no name is similar enough.
  """
  # the highest-ratio canonical name, kept only when it clears the rename threshold
  scored = [ ( difflib.SequenceMatcher(None, name, cand).ratio(), cand ) for cand in sorted(canonical) ]
  best = max(scored, default = None, key = lambda pair: pair[0])
  return ( best[1], best[0] ) if best is not None and best[0] >= _RENAME_RATIO else None


def classify(root: Path, canonical: set[str], logged: set[str]) -> dict:
  """
  Sort the folders of a log root into buckets by how they relate to the canonical names.

  Args:
    root: Log root holding one folder per artifact; it may be absent.
    canonical: Every canonical artifact name.
    logged: Canonical names whose artifacts write a run log.

  Returns:
    A mapping with the folder names per bucket and the file statistics of every folder, in name order.
  """

  # Domain(unfiled):
  # # Run-log folder buckets
  # A run-log folder is judged by its name against the artifacts that exist, and the first rule that fits decides.
  # A folder named for an artifact that writes a run log is in use. A folder named for an artifact that writes
  # no run log is unlogged: the artifact exists, but nothing should be filling its folder. A name that is not an
  # artifact but is at least 80 percent similar to one is a rename candidate, and the closest artifact is offered
  # as its new name. Only then are the leftovers of dispatched task and plan runs recognised by their numbered
  # names. Whatever remains is an unexplained orphan. The similarity test comes before the leftover patterns so
  # that a renamed artifact's history is offered a new home instead of being written off as debris.

  buckets: dict[str, list] = { _UNLOGGED: [], _CANONICAL: [], _RENAME: [], _PATTERN: [], _OTHER: [] }
  folders: list[dict] = []
  names = sorted(name for name in os.listdir(root) if (root / name).is_dir()) if root.is_dir() else []

  # each folder lands in exactly one bucket, checked in the table's order
  for name in names:
    folders.append(_read_folder_stats(root / name))
    if name in logged:
      buckets[_CANONICAL].append(name)
    elif name in canonical:
      buckets[_UNLOGGED].append(name)
    elif (match := _find_best_match(name, canonical)) is not None:
      buckets[_RENAME].append({ "name": name, "match": match[0], "ratio": round(match[1], _RATIO_DIGITS) })
    elif any(pattern.match(name) for pattern in _ORPHAN_PATTERNS):
      buckets[_PATTERN].append(name)
    else:
      buckets[_OTHER].append(name)
  return { "buckets": buckets, "folders": folders }


def _is_valid_name(name: str) -> bool:
  """
  Tell whether a name designates exactly one folder directly inside the log root.

  Args:
    name: Folder name to check.

  Returns:
    `True` when the name is a single path segment that does not step out of the root.
  """
  # a folder name is one path segment inside the root, never a step out of it
  return bool(name) and name not in ( ".", ".." ) and "/" not in name and os.sep not in name


def _merge(root: Path, source: str, target: str, refused: list[dict]) -> bool:
  """
  Move the `.md` log files of one log folder into another and remove the source once it is left empty.

  Notes:
    - Entries of the source that are not `.md` files stay in the source.

  Args:
    root: Log root holding both folders.
    source: Name of the folder to merge away.
    target: Name of the folder receiving the log files; it is created when absent.
    refused: Refusal list extended in place with every name that could not be handled.

  Returns:
    `True` when the source folder was fully merged and removed, `False` when it was refused or kept because a log
    file conflicted or a non-log entry remains in it.
  """
  # either side naming anything but one folder inside the root refuses the merge
  for name in ( source, target ):
    # guard: a name that is not one folder inside the root is refused
    if not _is_valid_name(name):
      refused.append({ "name": name, "reason": _INVALID })
      return False

  # the source folder the files move out of
  src = root / source
  # guard: a source that is not there has nothing to merge
  if not src.is_dir():
    refused.append({ "name": source, "reason": _MISSING })
    return False

  # every log file moves unless the target already holds one of that name; anything else stays in the source
  dst = root / target
  dst.mkdir(parents = True, exist_ok = True)
  for name in sorted(entry for entry in os.listdir(src) if entry.endswith(_MD)):
    if (dst / name).exists():
      refused.append({ "name": f"{source}/{name}", "reason": _EXISTS })
      continue
    shutil.move(str(src / name), str(dst / name))

  # the source goes only once it is empty; a conflict keeps it for the operator
  if os.listdir(src):
    return False
  src.rmdir()
  return True


def apply(root: Path, merges: list[tuple[str, str]], deletes: list[str]) -> dict:
  """
  Carry out the chosen folder merges and deletions inside a log root.

  Guarantees:
    - Never touches anything outside the root.
    - A name that is empty, `.`, `..` or contains a path separator is refused and reported, never acted on.

  Args:
    root: Log root holding the folders.
    merges: Pairs of source and target folder names; each source is merged into its target.
    deletes: Names of folders to delete whole.

  Returns:
    A mapping with the number of merged folders, the number of deleted folders, and the refused names with the
    reason for each.
  """

  # Contract:
  # Nothing outside the log root is ever touched. A folder name that is empty, `.`, `..` or contains a path
  # separator is refused and listed in the result with its reason, never acted on.

  refused: list[dict] = []

  # merges run first, so a folder merged away and also listed for deletion is already gone
  merged = sum(1 for source, target in merges if _merge(root, source, target, refused))

  # each deletion removes one whole folder inside the root
  deleted = 0
  for name in deletes:
    # guard: a name that is not one folder inside the root is refused
    if not _is_valid_name(name):
      refused.append({ "name": name, "reason": _INVALID })
      continue

    # guard: a folder that is not there is reported, not an error
    if not (root / name).is_dir():
      refused.append({ "name": name, "reason": _MISSING })
      continue
    shutil.rmtree(root / name)
    deleted += 1
  return { "merged": merged, "deleted": deleted, "refused": refused }


def _parse_merge(spec: str) -> tuple[str, str]:
  """
  Parse a merge request given as `<source>:<target>`.

  Args:
    spec: Merge request text.

  Returns:
    The source and target folder names; the target is empty when the text has no colon.
  """
  # a merge is spelled `<source>:<target>`; a missing colon leaves an empty target the apply refuses
  source, _sep, target = spec.partition(":")
  return source, target


def main(argv: list[str]) -> int:
  """
  Run the `classify` or `apply` subcommand and print its result as JSON.

  Args:
    argv: Command-line arguments after the script name.

  Returns:
    Process exit code; always `0`.
  """
  # two subcommands over one root: classify reads, apply writes
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "log-folders.py")
  # waiver: argparse CLI signature, not a domain key
  sub = parser.add_subparsers(dest = "cmd", required = True)
  # waiver: argparse CLI signature, not a domain key
  classify_parser = sub.add_parser("classify")
  # waiver: argparse CLI signature, not a domain key
  classify_parser.add_argument("--root", default = _DEFAULT_ROOT)
  # waiver: argparse CLI signature, not a domain key
  apply_parser = sub.add_parser("apply")
  # waiver: argparse CLI signature, not a domain key
  apply_parser.add_argument("--root", default = _DEFAULT_ROOT)
  # waiver: argparse CLI signature, not a domain key
  apply_parser.add_argument("--merge", action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  apply_parser.add_argument("--delete", action = "append", default = [])
  args = parser.parse_args(argv)
  root = Path(args.root)

  # classify buckets every folder against the live canonical names
  # waiver: argparse CLI signature, not a domain key
  if args.cmd == "classify":
    canonical, logged = load_canonical()
    print(json.dumps(classify(root, canonical, logged)))
    return 0

  # apply carries out the operator's merges and deletions
  print(json.dumps(apply(root, [ _parse_merge(spec) for spec in args.merge ], args.delete)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
