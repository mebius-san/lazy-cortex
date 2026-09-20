"""Folder-note `# Summary` rendering — skeleton + deterministic stats projection.

The précis half is operator/LLM-written; this module owns only the deterministic
stats half (between the `spec:stats` markers) and the empty skeleton emitted at
scaffold time.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import note_explainers  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from spec_keys import Gate, GATE_ORDER, SpecKey, SpecValue  # pylint: disable=import-error

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
_BUCKET_PRODUCT = "product"
_BUCKET_SHELF = "shelf"
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
  Return the empty `# Summary` section for a level note (description + stats).

  A group container carries the stats region alone — only a product root and the
  catalog root hold a description of their own.

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


def _frontmatter(note_text: str) -> str:
  """
  Slice a note's frontmatter block off the front of its text.

  Args:
    note_text: Full folder-note text.

  Returns:
    The text before the closing fence, or the whole text when no closing fence is present.
  """
  # waiver: magic literal 3 -- length of the leading '---\n' fence start consumed by find()
  end = note_text.find("\n---", 3)
  return note_text[: end if end > 0 else len(note_text) ]


def _has_role(fm: str, role: str) -> bool:
  """
  Judge whether a frontmatter block declares exactly `role`.

  The match is anchored on a whole frontmatter line and on the whole value, so a longer value
  sharing the role's opening characters never matches and a body mention is out of scope.

  Args:
    fm: The note's frontmatter block.
    role: The `spec_role` value under test.

  Returns:
    True when the block carries that exact role declaration.
  """
  return re.search(rf"^{re.escape(SpecKey.ROLE)}:\s*{re.escape(role)}\s*$", fm, re.MULTILINE) is not None


def classify(note_text: str) -> str:
  """
  Classify one asset status note into a ladder bucket.

  Args:
    note_text: Full status folder-note text.

  Returns:
    One of `released` / `cancelled` / `in_progress` / `not_started`, `product` for a nested
    product's own level note, or `shelf` for a folder-note that is neither.
  """

  # Domain(spec.lifecycle):
  # # Container summary buckets rank cancellation and release above raw progress
  # A container's summary line reads a child's ROLE first — a nested product runs its own
  # ladder and is counted apart from the assets, and a folder-note claiming neither the status
  # nor the product role is a shelf the line does not count at all. An asset is then sorted
  # into exactly one of four buckets by checking cancellation first, then release, then whether
  # any ladder step at all has opened, and only calling an asset not started when none of those
  # hold. Cancellation always wins the reading because a cancelled asset stopped counting toward
  # progress the moment it was cancelled, whatever it had reached before; release is checked
  # next because it is the more informative fact about where an asset stands than merely being
  # under way.

  fm = _frontmatter(note_text)

  # guard: a nested product is not an asset of the folder holding it — it runs its own ladder,
  # and its gate booleans (if any) describe that ladder, never progress on an asset
  if _has_role(fm, SpecValue.ROLE_PRODUCT):
    return _BUCKET_PRODUCT

  # guard: a folder-note claiming neither role is a shelf — a group folder holding assets, or
  # any other operator-zone folder. It has no ladder of its own, so it is nothing to count
  if not _has_role(fm, SpecValue.ROLE_STATUS):
    return _BUCKET_SHELF

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

  # Domain(spec.requests):
  # # A requests container is told apart from an asset category by shape, not by count
  # A folder is read as a requests inbox — counted by intake status rather than by the asset
  # ladder — the moment it holds no asset subfolders of its own, because a container that holds
  # assets is always a category and never an inbox, no matter what loose files sit beside them.
  # Within such a folder, the canonical inbox name settles the reading even while still empty,
  # and any other folder qualifies the moment one file inside it has already opted into intake.

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

  # a 'requests'-named container with no asset subfolders is an inbox even when empty
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


def is_shelf_note(note: Path) -> bool:
  """
  Judge whether a folder-note is a shelf — a folder the container tally reads straight through.

  This is the one transparency predicate: the tally descends through exactly the folders it
  reports as shelves, and a caller refreshing stats regions upward climbs through the same set.

  Args:
    note: The folder's own folder-note.

  Returns:
    True when the note declares neither the asset status role nor a level role.
  """
  return classify(note.read_text()) == _BUCKET_SHELF


def _tally_children(container_dir: Path, buckets: dict[str, int], *,
                    visited: set[Path] | None = None) -> None:
  """
  Tally one folder's status-note children into `buckets`, descending through group folders.

  A folder is reached at most once per tally, whatever its bucket: a symlink pointing back up
  the tree neither loops nor double-counts the shelves behind it, and a second symlinked route
  to one asset folder counts that asset once, not once per route.

  Args:
    container_dir: The folder whose subfolders are tallied.
    buckets: Bucket counters, incremented in place.
    visited: Resolved folder paths already reached by this tally; None starts a fresh walk.
  """

  # Domain(spec.lifecycle):
  # # A group folder is transparent to the container summary that encloses it
  # A folder that holds assets without running a ladder of its own is a place, not a child: the
  # assets it holds belong to the container's own totals, exactly as if they sat straight at the
  # container's root, and the folder itself is never counted as one of them. Reading it any
  # other way would report a product as empty the moment its operator filed its assets into
  # named folders rather than leaving them loose. A nested product ends the reading instead of
  # continuing it, because it runs its own ladder and answers for its own assets.

  # a symlinked folder resolves to a path the walk may already be standing in, so the set of
  # reached folders is what bounds the descent rather than the depth of the tree on disk
  seen = { container_dir.resolve() } if visited is None else visited
  for entry in sorted(container_dir.iterdir()):
    # guard: only subfolders carrying a same-named folder-note count
    if not entry.is_dir():
      continue
    note = entry / f"{entry.name}.md"

    # guard: skip entries that lack the expected same-named folder-note
    if not note.is_file():
      continue
    resolved = entry.resolve()

    # guard: a folder this tally already reached is a second route to it, never a second place
    if resolved in seen:
      continue
    seen.add(resolved)
    bucket = classify(note.read_text())

    # guard: a group folder is transparent — it is never counted, and the tally reads through it
    if bucket == _BUCKET_SHELF:
      _tally_children(entry, buckets, visited = seen)
      continue

    # an asset, or a nested product the walk counts whole and never enters
    buckets[bucket] += 1


def render_container_stats(container_dir: Path) -> str:
  """
  Compute the stats line for a group container from the assets below it.

  Detects a requests inbox (flat `*.md` files with `request_status`) and emits
  request-status counts; otherwise falls back to the asset-ladder counts. A nested product
  among the children is counted in its own trailing segment rather than as an asset, and a
  group folder is transparent — its own children count here, the folder itself never does.

  Args:
    container_dir: The group folder (e.g. `bugs/`) or requests inbox.

  Returns:
    A `· `-joined stats line; zero-count segments omitted.
  """
  # guard: delegate to requests mode when the inbox heuristic matches
  if _is_requests_inbox(container_dir):
    return _render_requests_stats(container_dir)
  buckets = {
      _BUCKET_RELEASED: 0, _BUCKET_IN_PROGRESS: 0,
      _BUCKET_NOT_STARTED: 0, _BUCKET_CANCELLED: 0, _BUCKET_PRODUCT: 0,
  }
  _tally_children(container_dir, buckets)

  # a nested product is counted beside the assets, never among them — it has its own ladder
  total = sum(count for bucket, count in buckets.items() if bucket != _BUCKET_PRODUCT)
  unit = "asset" if total == 1 else "assets"
  segs = [ f"{total} {unit}" ]
  labels = [
      (_BUCKET_RELEASED, "released"), (_BUCKET_IN_PROGRESS, "in progress"),
      (_BUCKET_NOT_STARTED, "not started"), (_BUCKET_CANCELLED, "cancelled"),
  ]
  for key, label in labels:
    # emit only non-zero buckets to keep the line short
    if buckets[key]:
      segs.append(f"{buckets[key]} {label}")

  # the nested-product count closes the line, after the asset total and its own breakdown
  if buckets[_BUCKET_PRODUCT]:
    products = buckets[_BUCKET_PRODUCT]
    segs.append(f"{products} {'product' if products == 1 else 'products'}")
  return " · ".join(segs)


def apply_container_stats(note_path: Path) -> bool:
  """
  Rewrite the `spec:stats` region of a container note from its sibling children.

  Args:
    note_path: The container folder-note (e.g. `bugs/bugs.md`).

  Returns:
    True when the file content changed.
  """
  # the marker pair decides whether this note is a managed container summary
  text = note_path.read_text()

  # guard: no stats markers, nothing this function owns
  if _STATS_START not in text or _STATS_END not in text:
    return False
  line = render_container_stats(note_path.parent)
  new = re.sub(
      re.escape(_STATS_START) + r".*?" + re.escape(_STATS_END),
      f"{_STATS_START}\n{line}\n{_STATS_END}",
      text, flags = re.DOTALL,
  )

  # every stats refresh also re-heals the note's section explainer lines
  new = note_explainers.heal_note_text(note_path, new)

  # guard: skip the write when nothing changed
  if new == text:
    return False
  note_path.write_text(new)
  return True


def parent_container_note(asset_dir: Path) -> Path | None:
  """
  Return the note whose stats region an asset's flip refreshes, if it exists.

  A product root's stats region counts that product's own children, so an asset sitting
  straight at the root refreshes the product note exactly as an asset inside a group folder
  refreshes the group note.

  Guarantees:
    - The catalog root's note is never returned: its children are products, each running its
      own ladder, and no asset flip below it may rewrite its stats region.

  Args:
    asset_dir: An asset folder at any depth under the product root.

  Returns:
    The enclosing folder's own note — a group note or the product note — or `None` at the
    catalog root and when the folder above carries no note of its own.
  """

  # Contract:
  # The catalog root's note is never returned: an asset sitting straight at the catalog root
  # reports no container note, so a gate flip leaves that level note untouched.

  parent = asset_dir.parent
  note = parent / f"{parent.name}.md"

  # guard: no folder-note above this asset — nothing to refresh
  if not note.is_file():
    return None

  # guard: the folder above is the catalog root, whose region counts products rather than
  # assets — an asset flip below it moves nothing the line reports
  if _is_catalog_root(note):
    return None
  return note


def _is_catalog_root(note: Path) -> bool:
  """
  Judge whether a folder-note is the catalog root's own level note.

  Args:
    note: The folder's own folder-note.

  Returns:
    True when the note declares the catalog role; False otherwise, a product root included.
  """
  return _has_role(_frontmatter(note.read_text()), SpecValue.ROLE_CATALOG)


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
