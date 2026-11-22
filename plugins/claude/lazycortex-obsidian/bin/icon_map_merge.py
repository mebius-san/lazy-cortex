#!/usr/bin/env python3

"""
Icon-map merge for the lazycortex-obsidian plugin.

Backs the `icon-map-merge` verb, which `lazy-obsidian.iconize-install` calls when an authored icon-map on the current
schema differs from the shipped template: the template's additions are merged in, authored content is kept, and a
disagreement between the two is a conflict the caller resolves per key path.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The top-level array merged by entry id, and the entry key that identifies a matcher.
_MATCHERS_KEY = "matchers"
_ID_KEY = "id"

# The two answers a conflict takes.
KEEP_AUTHORED = "keep-authored"
TAKE_SHIPPED = "take-shipped"
_CHOICES = ( KEEP_AUTHORED, TAKE_SHIPPED )

# The separator of a `--resolve` value and of a key path's segments.
_RESOLVE_SEP = "="
_PATH_SEP = "."

# The answer's wire-shape keys and states.
_STATE_KEY = "state"
_ADDED_KEY = "added"
_CONFLICTS_KEY = "conflicts"
_KEPT_KEY = "kept_authored"
_TOOK_KEY = "took_shipped"
_PATH_KEY = "path"
_AUTHORED_KEY = "authored"
_SHIPPED_KEY = "shipped"
_STATE_UNCHANGED = "unchanged"
_STATE_MERGED = "merged"
_STATE_CONFLICTS = "conflicts"

# The file encoding, and the JSON layout the merged file is written in.
_ENCODING = "utf-8"
_INDENT = 2

# Exit codes of an unresolved conflict and of a refused input.
_EXIT_CONFLICTS = 1
_EXIT_REFUSED = 2


# ----------------------------------------------------------------------------------------
@dataclass
class MergeRecord:
  """
  Outcome of one icon-map merge.

  Attributes:
    resolutions: The answer chosen per conflicting key path.
    added: Key paths the shipped template added, in merge order.
    conflicts: Every conflict with no answer, as path, authored value and shipped value.
    kept_authored: Count of conflicts answered with the authored value.
    took_shipped: Count of conflicts answered with the shipped value.
  """

  # The answer the caller chose for each conflicting key path
  resolutions: dict[str, str]
  # Key paths the template added, in merge order
  added: list[str] = field(default_factory = list)
  # Conflicts still without an answer
  conflicts: list[dict] = field(default_factory = list)
  # Conflicts answered with the authored value
  kept_authored: int = 0
  # Conflicts answered with the shipped value
  took_shipped: int = 0


def _join(path: str, key: str) -> str:
  """
  Extend a key path by one key.

  Args:
    path: The parent key path, empty at the top level.
    key: The key to append.

  Returns:
    The child key path.
  """
  return f"{path}{_PATH_SEP}{key}" if path else key


def _matcher_path(matcher_id: str) -> str:
  """
  Name one matcher entry as a key path.

  Args:
    matcher_id: The matcher's id.

  Returns:
    The key path of the matcher entry.
  """
  return f"{_MATCHERS_KEY}[{matcher_id}]"


def _resolve_conflict(authored: object, shipped: object, path: str, report: MergeRecord) -> object:
  """
  Pick the value a conflicting key keeps, or record the conflict when it has no answer.

  Args:
    authored: The authored value.
    shipped: The shipped value.
    path: The key path both values sit under.
    report: The merge report collecting answers and open conflicts.

  Returns:
    The chosen value; the authored one while the conflict stays open.
  """
  choice = report.resolutions.get(path)

  # an answered conflict takes the side the caller chose
  if choice == TAKE_SHIPPED:
    report.took_shipped += 1
    return copy.deepcopy(shipped)
  if choice == KEEP_AUTHORED:
    report.kept_authored += 1
    return copy.deepcopy(authored)

  # an unanswered conflict is reported and keeps the authored value meanwhile
  report.conflicts.append({ _PATH_KEY: path, _AUTHORED_KEY: authored, _SHIPPED_KEY: shipped })
  return copy.deepcopy(authored)


def _merge_value(authored: object, shipped: object, path: str, report: MergeRecord) -> object:
  """
  Merge one value both sides carry under the same key path.

  Args:
    authored: The authored value.
    shipped: The shipped value.
    path: The key path both values sit under.
    report: The merge report.

  Returns:
    The merged value.
  """
  # two objects merge key by key, and the matcher list merges entry by entry
  if isinstance(authored, dict) and isinstance(shipped, dict):
    return merge_objects(authored, shipped, path, report)
  if path == _MATCHERS_KEY and isinstance(authored, list) and isinstance(shipped, list):
    return _merge_matchers(authored, shipped, report)

  # equal values need no answer; anything else is a conflict
  if authored == shipped:
    return copy.deepcopy(authored)
  return _resolve_conflict(authored, shipped, path, report)


def _merge_matchers(authored: list, shipped: list, report: MergeRecord) -> list:
  """
  Merge the matcher lists by each entry's id.

  Args:
    authored: The authored matcher list.
    shipped: The shipped matcher list.
    report: The merge report.

  Returns:
    The authored entries in authored order, each merged with its shipped namesake, then the shipped-only entries.
  """
  shipped_by_id = { entry[_ID_KEY]: entry for entry in shipped if isinstance(entry, dict) and _ID_KEY in entry }
  authored_ids = { entry[_ID_KEY] for entry in authored if isinstance(entry, dict) and _ID_KEY in entry }

  # an authored entry keeps its place and merges with the shipped entry of the same id
  merged: list = []
  for entry in authored:
    if isinstance(entry, dict) and entry.get(_ID_KEY) in shipped_by_id:
      merged.append(merge_objects(entry, shipped_by_id[entry[_ID_KEY]], _matcher_path(entry[_ID_KEY]), report))
    else:
      merged.append(copy.deepcopy(entry))

  # a shipped entry no authored entry carries is appended, in shipped order
  for entry in shipped:
    if isinstance(entry, dict) and _ID_KEY in entry:
      if entry[_ID_KEY] not in authored_ids:
        merged.append(copy.deepcopy(entry))
        report.added.append(_matcher_path(entry[_ID_KEY]))
    elif entry not in authored:
      merged.append(copy.deepcopy(entry))
  return merged


def merge_objects(authored: dict, shipped: dict, path: str, report: MergeRecord) -> dict:
  """
  Merge a shipped object into an authored one, key by key.

  Args:
    authored: The authored object.
    shipped: The shipped object.
    path: The key path of both objects, empty at the top level.
    report: The merge report.

  Returns:
    A new object: the authored keys in authored order, merged with their shipped namesakes, then the shipped-only
    keys in shipped order.
  """

  # Domain(obsidian.icon-map-merge):
  # # Merging a shipped icon map into an authored one
  # The shipped template evolves while the operator's own icon map holds personal choices that must survive an update,
  # so the merge never overwrites authored content. A key only the template carries is added; a key only the authored
  # map carries is kept. Objects found on both sides merge key by key at every depth. Matchers are identified by their
  # id, never by position: an authored matcher keeps its place and merges with the shipped matcher of the same id, and
  # shipped matchers the authored map lacks are appended after it. Where both sides carry the same key with different
  # values, that is a conflict, and any other list counts as one value, conflicting whole. Equal values never
  # conflict. The operator answers each conflict per key path, keeping the authored value or taking the shipped one.
  # An unanswered conflict leaves the authored value in place, and nothing is written until every conflict is answered.

  # every authored key keeps its place; a key both sides carry merges
  merged = {
      key: _merge_value(value, shipped[key], _join(path, key), report) if key in shipped else copy.deepcopy(value)
      for key, value in authored.items()
  }

  # a key only the template carries is added
  for key, value in shipped.items():
    if key not in authored:
      merged[key] = copy.deepcopy(value)
      report.added.append(_join(path, key))
  return merged


def read_icon_map(path: Path) -> dict:
  """
  Read one icon-map file.

  Args:
    path: The file to read.

  Returns:
    The parsed object.

  Raises:
    ValueError: If the file cannot be read, is not valid JSON, or is not a JSON object.
  """
  try:
    data = json.loads(path.read_text(encoding = _ENCODING))
  except (OSError, ValueError) as error:
    raise ValueError(f"{path}: {error}") from error

  # guard: an icon-map is an object at its top level
  if not isinstance(data, dict):
    raise ValueError(f"{path}: not a JSON object")
  return data


def parse_resolutions(values: list[str]) -> dict[str, str]:
  """
  Parse the `--resolve <key-path>=<choice>` arguments.

  Args:
    values: The raw argument values.

  Returns:
    The answer per key path.

  Raises:
    ValueError: If a value has no `=`, names an empty key path, or names an unknown choice.
  """
  resolutions: dict[str, str] = {}
  for value in values:
    path, sep, choice = value.rpartition(_RESOLVE_SEP)

    # guard: a resolution names a key path and one of the two answers
    if not sep or not path or choice not in _CHOICES:
      raise ValueError(f"--resolve {value!r}: expected <key-path>={KEEP_AUTHORED}|{TAKE_SHIPPED}")
    resolutions[path] = choice
  return resolutions


def run_merge(authored_path: Path, shipped_path: Path, out: Path, resolutions: dict[str, str]) -> dict:
  """
  Merge the shipped template into an authored icon-map and write the result when the merge is complete.

  Guarantees:
    - Nothing is written while any conflict is open, nor when the merge changes nothing.
    - Authored content is never overwritten, except where its conflict was answered take-shipped.

  Notes:
    - Writes the merged icon-map to `out`, creating missing parent directories, only in the `merged` state.

  Args:
    authored_path: The authored icon-map.
    shipped_path: The shipped template.
    out: The file the merged icon-map is written to.
    resolutions: The answer per conflicting key path.

  Returns:
    The answer: the `state` (`unchanged`, `merged` or `conflicts`), the added key paths, the open conflicts and the
    count of each kind of answer.

  Raises:
    ValueError: If either input cannot be read as a JSON object.
    OSError: If the output directory cannot be created or the output file cannot be written.
  """

  # Contract:
  # Nothing is written while any conflict is open, and nothing is written when the merge changes nothing;
  # the output file is written only for a complete merge that differs from the authored icon-map.

  # Contract:
  # Authored content is never overwritten: every authored value survives into the written file,
  # except where its conflict was answered take-shipped.

  authored = read_icon_map(authored_path)
  report = MergeRecord(resolutions = resolutions)
  merged = merge_objects(authored, read_icon_map(shipped_path), "", report)

  # an open conflict, or a result equal to the authored file, writes nothing
  if report.conflicts:
    state = _STATE_CONFLICTS
  elif merged == authored:
    state = _STATE_UNCHANGED
  else:
    state = _STATE_MERGED
    out.parent.mkdir(parents = True, exist_ok = True)
    out.write_text(json.dumps(merged, indent = _INDENT, ensure_ascii = False) + "\n", encoding = _ENCODING)

  # the answer carries everything the caller reports or asks about
  return { _STATE_KEY: state, _ADDED_KEY: report.added, _CONFLICTS_KEY: report.conflicts,
           _KEPT_KEY: report.kept_authored, _TOOK_KEY: report.took_shipped }


def main(argv: list[str]) -> int:
  """
  Run the `icon-map-merge` verb and print its answer as JSON.

  Args:
    argv: Arguments after the subcommand: the authored icon-map, `--shipped`, `--out` and any `--resolve`.

  Returns:
    0 for `unchanged` or `merged`, 1 for `conflicts`, 2 when an input or a `--resolve` value is refused or the
    merged file cannot be written.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-obsidian icon-map-merge")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("authored", type = Path)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--shipped", type = Path, required = True)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--out", type = Path, required = True)
  # waiver: argparse CLI signature -- repeatable option flag
  parser.add_argument("--resolve", action = "append", default = [])
  args = parser.parse_args(argv)

  # a refused input or answer is reported on stderr and writes nothing
  try:
    answer = run_merge(args.authored, args.shipped, args.out, parse_resolutions(args.resolve))
  except (ValueError, OSError) as error:
    sys.stderr.write(f"icon-map-merge: {error}\n")
    return _EXIT_REFUSED
  print(json.dumps(answer, ensure_ascii = False))
  return _EXIT_CONFLICTS if answer[_STATE_KEY] == _STATE_CONFLICTS else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
