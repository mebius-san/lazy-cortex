"""Folder-note `# Summary` rendering — skeleton + deterministic stats projection.

The précis half is operator/LLM-written; this module owns only the deterministic
stats half (between the `spec:stats` markers) and the empty skeleton emitted at
scaffold time.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import re
import sys
from pathlib import Path

from spec_keys import Gate, GATE_ORDER

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


SUMMARY_TAG = "#protected/spec/summary"
_PRECIS_START = "<!-- spec:precis:start -->"
_PRECIS_END = "<!-- spec:precis:end -->"
_STATS_START = "<!-- spec:stats:start -->"
_STATS_END = "<!-- spec:stats:end -->"

_BUCKET_RELEASED = "released"
_BUCKET_CANCELLED = "cancelled"
_BUCKET_IN_PROGRESS = "in_progress"
_BUCKET_NOT_STARTED = "not_started"
# waiver: one-off CLI usage string -- argparse-style usage printed to stderr by main()
_USAGE = "usage: lazycortex-specs render-container-stats <note_path>\n"


def summary_skeleton_asset() -> str:
  """
  Return the empty `# Summary` section for an asset status note (précis only).

  Returns:
    The section text ending with a trailing newline.
  """
  return f"# Summary\n{SUMMARY_TAG}\n\n"


def summary_skeleton_container() -> str:
  """
  Return the empty `# Summary` section for a container note (précis + stats).

  Returns:
    The section text with both sub-marker regions, ending with a newline.
  """
  return (
      f"# Summary\n{SUMMARY_TAG}\n"
      f"{_PRECIS_START}\n\n{_PRECIS_END}\n"
      f"{_STATS_START}\n\n{_STATS_END}\n"
  )


SUMMARY_SKELETON_ASSET = summary_skeleton_asset()
SUMMARY_SKELETON_CONTAINER = summary_skeleton_container()


def _read_gate(fm: str, key: str) -> bool:
  """
  Read a boolean gate value from a frontmatter string.

  Args:
    fm: Frontmatter text.
    key: Gate key.

  Returns:
    True when the key is present and set to `true`.
  """
  m = re.search(rf"^{re.escape(key)}:\s*(\w+)\s*$", fm, re.MULTILINE)
  # waiver: magic literal 'true' -- the YAML boolean spelling is a fixed protocol token, not a domain constant
  return m is not None and m.group(1).lower() == "true"


def _classify(note_text: str) -> str:
  """
  Classify one asset status note into a ladder bucket.

  Args:
    note_text: Full status folder-note text.

  Returns:
    One of `released` / `cancelled` / `in_progress` / `not_started`.
  """
  # waiver: magic literal 3 -- length of the leading '---\n' fence start consumed by find()
  end = note_text.find("\n---", 3)
  fm = note_text[: end if end > 0 else len(note_text) ]
  # guard: cancelled overlay wins over all other states
  if _read_gate(fm, Gate.SPEC_CANCELLED):
    return _BUCKET_CANCELLED
  # guard: released is the next highest-priority bucket
  if _read_gate(fm, Gate.RELEASED):
    return _BUCKET_RELEASED
  # guard: any true ladder gate means work has started
  if any(_read_gate(fm, g) for g in GATE_ORDER):
    return _BUCKET_IN_PROGRESS
  return _BUCKET_NOT_STARTED


_REQUEST_STATUSES = ("draft", "accepted", "rejected")


def _read_request_status(text: str) -> str | None:
  """
  Read the `request_status` value from a frontmatter string.

  Args:
    text: Full file text.

  Returns:
    The status string when present, else `None`.
  """
  # waiver: magic literal 3 -- length of the leading '---\n' fence start consumed by find()
  end = text.find("\n---", 3)
  fm = text[: end if end > 0 else len(text)]
  m = re.search(r"^request_status:\s*(\S+)\s*$", fm, re.MULTILINE)
  return m.group(1) if m is not None else None


def _is_requests_inbox(container_dir: Path) -> bool:
  """
  Detect whether `container_dir` is a requests inbox (flat .md files with request_status).

  An inbox is a directory with no asset subfolders that either is named
  `requests` (the canonical inbox folder) or carries at least one flat `*.md`
  file (other than its own folder-note) with a `request_status` frontmatter key.

  Args:
    container_dir: Directory to inspect.

  Returns:
    True when the requests-inbox heuristic matches.
  """
  dir_name = container_dir.name
  has_request_file = False
  for entry in container_dir.iterdir():
    # guard: asset subfolders disqualify requests-inbox mode
    if entry.is_dir():
      return False
    # guard: skip non-files (symlinks, etc.)
    if not entry.is_file():
      continue
    # guard: only markdown files are request candidates
    # waiver: magic literal '.md' -- markdown extension is a fixed protocol token
    if not entry.name.endswith(".md"):
      continue
    # guard: skip the folder-note itself
    if entry.name == f"{dir_name}.md":
      continue
    if _read_request_status(entry.read_text()) is not None:
      has_request_file = True
  # guard: a 'requests'-named container with no asset subfolders is an inbox even when empty
  # waiver: magic literal 'requests' -- the inbox folder name is a fixed protocol token
  return has_request_file or dir_name == "requests"


def _render_requests_stats(container_dir: Path) -> str:
  """
  Compute the stats line for a requests inbox.

  Args:
    container_dir: The requests inbox folder.

  Returns:
    A `· `-joined line of `<status> <count>` segments; zero-count omitted.
    Returns `0 requests` when all counts are zero.
  """
  dir_name = container_dir.name
  counts: dict[str, int] = dict.fromkeys(_REQUEST_STATUSES, 0)
  for entry in container_dir.iterdir():
    # guard: skip non-files (symlinks, etc.)
    if not entry.is_file():
      continue
    # guard: only markdown files are request candidates
    # waiver: magic literal '.md' -- markdown extension is a fixed protocol token
    if not entry.name.endswith(".md"):
      continue
    # guard: skip the folder-note itself
    if entry.name == f"{dir_name}.md":
      continue
    status = _read_request_status(entry.read_text())
    if status in counts:
      counts[status] += 1
  segs = [f"{status} {count}" for status, count in counts.items() if count]
  return " · ".join(segs) if segs else "0 requests"


def render_container_stats(container_dir: Path) -> str:
  """
  Compute the stats line for a category container from its immediate children.

  Detects a requests inbox (flat `*.md` files with `request_status`) and emits
  request-status counts; otherwise falls back to the asset-ladder counts.

  Args:
    container_dir: The category folder (e.g. `features/`) or requests inbox.

  Returns:
    A `· `-joined stats line; zero-count segments omitted.
  """
  # guard: delegate to requests mode when the inbox heuristic matches
  if _is_requests_inbox(container_dir):
    return _render_requests_stats(container_dir)
  buckets = {
      _BUCKET_RELEASED: 0, _BUCKET_IN_PROGRESS: 0,
      _BUCKET_NOT_STARTED: 0, _BUCKET_CANCELLED: 0,
  }
  total = 0
  for entry in sorted(container_dir.iterdir()):
    # guard: only asset subfolders carrying a same-named status note count
    if not entry.is_dir():
      continue
    note = entry / f"{entry.name}.md"
    # guard: skip entries that lack the expected same-named status note
    if not note.is_file():
      continue
    total += 1
    buckets[_classify(note.read_text())] += 1
  unit = "asset" if total == 1 else "assets"
  segs = [ f"{total} {unit}" ]
  labels = [
      (_BUCKET_RELEASED, "released"), (_BUCKET_IN_PROGRESS, "in progress"),
      (_BUCKET_NOT_STARTED, "not started"), (_BUCKET_CANCELLED, "cancelled"),
  ]
  for key, label in labels:
    # guard: omit zero-count segments to keep the line short
    if buckets[key]:
      segs.append(f"{buckets[key]} {label}")
  return " · ".join(segs)


def apply_container_stats(note_path: Path) -> bool:
  """
  Rewrite the `spec:stats` region of a container note from its sibling children.

  Args:
    note_path: The container folder-note (e.g. `features/features.md`).

  Returns:
    True when the file content changed.
  """
  # guard: a note without the stats markers is not a managed container summary
  text = note_path.read_text()
  if _STATS_START not in text or _STATS_END not in text:
    return False
  line = render_container_stats(note_path.parent)
  new = re.sub(
      re.escape(_STATS_START) + r".*?" + re.escape(_STATS_END),
      f"{_STATS_START}\n{line}\n{_STATS_END}",
      text, flags = re.DOTALL,
  )
  # guard: skip the write when nothing changed
  if new == text:
    return False
  note_path.write_text(new)
  return True


def parent_container_note(asset_dir: Path) -> Path | None:
  """
  Return the category container note for an asset folder, if it exists.

  Args:
    asset_dir: An asset folder `<category>/<slug>/`.

  Returns:
    `<category>/<category>.md` when present, else `None`.
  """
  cat = asset_dir.parent
  note = cat / f"{cat.name}.md"
  return note if note.is_file() else None


def main(argv: list[str]) -> int:
  """
  Run the `render-container-stats <note_path>` subcommand.

  Args:
    argv: Subcommand tail (positional note path).

  Returns:
    `0` on success, `2` on bad arguments.
  """
  # guard: exactly one path argument required
  if len(argv) != 1:
    sys.stderr.write(_USAGE)
    return 2
  apply_container_stats(Path(argv[0]).resolve())
  return 0
