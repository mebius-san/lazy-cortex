"""
Folder-note `# Summary` rendering — skeleton + deterministic stats projection.

The précis half is operator/LLM-written; this module owns only the deterministic
stats half (between the `spec:stats` markers) and the empty skeleton emitted at
scaffold time.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    Gate, GATE_ORDER, AssetState, AssetTypeKey, LangId, ReleaseKey, SpecHaltKey, SpecKey, SpecStateKey, SpecValue,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_lockit import Lockit  # noqa: E402


SUMMARY_TAG = "#protected/spec/summary"
_PRECIS_START = "<!-- spec:precis:start -->"
_PRECIS_END = "<!-- spec:precis:end -->"
_STATS_START = "<!-- spec:stats:start -->"
_STATS_END = "<!-- spec:stats:end -->"

_BUCKET_RELEASED = "released"
_BUCKET_CANCELLED = "cancelled"
_BUCKET_IN_PROGRESS = "in_progress"
_BUCKET_READY = "ready"
_BUCKET_NOT_STARTED = "not_started"
_BUCKET_PRODUCT = "product"
_BUCKET_SHELF = "shelf"
_BUCKET_RELEASE_RELEASED = "release_released"
_BUCKET_RELEASE_OPEN = "release_open"
_BUCKET_RELEASE_CANCELLED = "release_cancelled"

# The container stats block's wording: a markdown list of `<count> <label>` total items, each total
# followed by its non-zero breakdown items one level deeper
_STATS_LINE_SEPARATOR = "\n"
_STATS_ITEM = "- {count} {label}"
_STATS_SUB_ITEM = "  - {count} {label}"
# The lockit key of a stats label is the prefix, the label, then its plural form
_STATS_LABEL_KEY = "stats.{label}.{form}"
_STATS_ASSET = "asset"
_STATS_PRODUCT = "product"
_STATS_RELEASE = "release"
_STATS_REQUEST = "request"
_STATS_RELEASED = "released"
_STATS_READY = "ready"
_STATS_IN_PROGRESS = "in-progress"
_STATS_NOT_STARTED = "not-started"
_STATS_CANCELLED = "cancelled"
_STATS_OPEN = "open"
# The plural forms a stats label carries in the lockit
_FORM_ONE = "one"
_FORM_FEW = "few"
_FORM_MANY = "many"
# The lockit key of each stats label in each of its plural forms, by (label, form) — the only route from a label
# to its text, so a label missing here fails loudly instead of reading a key no locale carries
_STATS_LABEL_KEYS = {
    (label, form): _STATS_LABEL_KEY.format(label = label, form = form)
    for label in ( _STATS_ASSET, _STATS_PRODUCT, _STATS_RELEASE, _STATS_REQUEST, _STATS_RELEASED, _STATS_READY,
                   _STATS_IN_PROGRESS, _STATS_NOT_STARTED, _STATS_CANCELLED, _STATS_OPEN )
    for form in ( _FORM_ONE, _FORM_FEW, _FORM_MANY )
}
# The asset states that read as work under way, and as work finished and waiting to ship
_STATES_IN_PROGRESS = frozenset({
    AssetState.DRAFT, AssetState.IN_REVIEW, AssetState.WAITS_OPERATOR, AssetState.IMPLEMENTATION,
    AssetState.TESTING,
})
_STATES_READY = frozenset({ AssetState.AWAITING_RELEASE, AssetState.IN_RELEASE })
# Request statuses the requests-inbox stats block counts, in the order their items appear.
_REQUEST_STATUSES = ("draft", "accepted", "rejected")
# The lockit key of each request status's localised label in the requests-inbox stats block, by status — the only
# route from a status to its text, so a status missing here fails loudly instead of reading a key no locale carries.
_REQUEST_STATUS_KEYS = { status: f"stats.request-status.{status}" for status in _REQUEST_STATUSES }
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


def _read_gate(frontmatter: str, key: str) -> bool:
  """
  Read a boolean gate value from a frontmatter string.

  Args:
    frontmatter: Frontmatter text.
    key: Gate key.

  Returns:
    True when the key is present and set to `true`.
  """
  match = re.search(rf"^{re.escape(key)}:\s*(\w+)\s*$", frontmatter, re.MULTILINE)
  # waiver: magic literal 'true' -- the YAML boolean spelling is a fixed protocol token, not a domain constant
  return match is not None and match.group(1).lower() == "true"


def _read_scalar(frontmatter: str, key: str) -> str:
  """
  Read a bare scalar value from a frontmatter string.

  Args:
    frontmatter: Frontmatter text.
    key: Frontmatter key.

  Returns:
    The value with surrounding quotes stripped, or the empty string when the key is absent.
  """
  match = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", frontmatter, re.MULTILINE)
  return match.group(1).strip("\"'") if match is not None else ""


def _plural_form(count: int, lang: str) -> str:
  """
  Choose the plural form a count takes in a language.

  Args:
    count: The number the label follows.
    lang: The note's authoring language.

  Returns:
    `one`, `few` or `many`.
  """

  # Domain(spec.notes):
  # # A counter's word agrees with its number
  # A counter shows a number followed by a word, and the word takes the form the language's grammar asks for
  # after that number. English has two forms: one thing, and every other count. Russian has three: the singular
  # form after a number ending in one, unless it ends in eleven; the paucal form after a number ending in two,
  # three or four, unless it ends in twelve, thirteen or fourteen; and the plural form after every other number,
  # zero included.

  # Russian distinguishes three forms by the last one and two digits
  if lang == LangId.RU:
    # waiver: magic literals 10 / 100 and the digit bounds -- the Russian plural rule's own fixed numbers
    tens, units = count % 100, count % 10
    # waiver: magic literal 11 -- the teen the Russian singular form excludes, a fixed number of the rule
    if units == 1 and tens != 11:
      return _FORM_ONE
    # waiver: magic literals -- the paucal digits two to four and the teens twelve to fourteen of the same rule
    if 2 <= units <= 4 and not 12 <= tens <= 14:
      return _FORM_FEW
    return _FORM_MANY

  # every other language follows English: one thing, and every other count
  return _FORM_ONE if count == 1 else _FORM_MANY


def _format_label(label: str, count: int, lang: str) -> str:
  """
  Give a stats label in the form its count takes.

  Args:
    label: The label's name in the lockit.
    count: The number the label follows.
    lang: The note's authoring language; a language with no text falls back to English.

  Returns:
    The label's text.
  """
  return Lockit.text(_STATS_LABEL_KEYS[(label, _plural_form(count, lang))], lang)


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


def _is_release(fm: str) -> bool:
  """
  Judge whether a status note's frontmatter declares the release asset type.

  Args:
    fm: The note's frontmatter block.

  Returns:
    True when the block carries `spec_asset_type: release` on a whole line.
  """
  # anchored on the whole line and the whole value, like the role match
  pattern = rf"^{re.escape(AssetTypeKey.TYPE)}:\s*{re.escape(ReleaseKey.ASSET_TYPE)}\s*$"
  return re.search(pattern, fm, re.MULTILINE) is not None


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

  Below cancellation and release, the state an asset reports for itself decides its bucket; a paused asset, or one
  reporting no known state, is read from its ladder gates instead.

  Args:
    note_text: Full status folder-note text.

  Returns:
    One of `released` / `ready` / `cancelled` / `in_progress` / `not_started`, `product` for a nested
    product's own level note, or `shelf` for a folder-note that is neither and for a release's
    status note, which is counted apart from the assets.
  """

  # Domain(spec.lifecycle):
  # # Container summary buckets rank cancellation and release above raw progress
  # A container's summary stats read a child's ROLE first — a nested product runs its own
  # ladder and is counted apart from the assets, and a folder-note claiming neither the status
  # nor the product role is a shelf the stats do not count at all. An asset is then sorted
  # into exactly one bucket by checking cancellation first, then release, then the state the
  # asset reports for itself, and only when that says nothing, whether any ladder step at all
  # has opened; an asset is called not started only when none of those hold. Cancellation always
  # wins the reading because a cancelled asset stopped counting toward progress the moment it
  # was cancelled, whatever it had reached before; release is checked next because it is the
  # more informative fact about where an asset stands than merely being under way. A release is
  # the product's own unit of shipping, not one of the assets it ships, so for the asset reading its note is read
  # like a shelf: it is not one of the assets and is counted apart from them.

  fm = _frontmatter(note_text)

  # a nested product is not an asset of the folder holding it — it runs its own ladder,
  # and its gate booleans (if any) describe that ladder, never progress on an asset
  if _has_role(fm, SpecValue.ROLE_PRODUCT):
    return _BUCKET_PRODUCT

  # a folder-note claiming neither role is a shelf — a group folder holding assets, or
  # any other operator-zone folder. It has no ladder of its own, so it is nothing to count
  if not _has_role(fm, SpecValue.ROLE_STATUS):
    return _BUCKET_SHELF

  # a release note is the product's unit of shipping, never one of the assets it counts
  if _is_release(fm):
    return _BUCKET_SHELF

  # cancelled overlay wins over all other states
  if _read_gate(fm, Gate.SPEC_CANCELLED):
    return _BUCKET_CANCELLED

  # released is the next highest-priority bucket
  if _read_gate(fm, Gate.RELEASED):
    return _BUCKET_RELEASED

  # Domain(spec.lifecycle):
  # # An asset's own state says where its work stands
  # Below cancellation and release, an asset is counted by the state it reports for itself, because that state
  # names the work the gates alone cannot tell apart. A design being written, reviewed or waiting on the
  # operator, and an implementation or test under way, is work in progress. An approved design waiting for a
  # release, or already carried by one, is ready: its own work is finished and only shipping remains. A shipped
  # asset is released. A paused asset, a parked backlog, a note that reports no state, or one whose state is not
  # known, is counted by whether any step of its ladder has opened.

  # the asset's own state decides, unless it is paused
  state = "" if _read_gate(fm, SpecHaltKey.HALTED) else _read_scalar(fm, SpecStateKey.STATE)
  if state in _STATES_IN_PROGRESS:
    return _BUCKET_IN_PROGRESS
  if state in _STATES_READY:
    return _BUCKET_READY
  if state == AssetState.DONE:
    return _BUCKET_RELEASED

  # any true ladder gate means work has started
  if any(_read_gate(fm, g) for g in GATE_ORDER):
    return _BUCKET_IN_PROGRESS
  return _BUCKET_NOT_STARTED


def _release_bucket(fm: str) -> str | None:
  """
  Sort one release's status note into a release bucket.

  Args:
    fm: The note's frontmatter block.

  Returns:
    The cancelled, released or open release bucket, or `None` when the note is no release.
  """

  # Domain(spec.lifecycle):
  # # A release is counted in exactly one of three states
  # A release is a status note of the release asset type, counted in its own total apart from
  # the assets. It falls into exactly one of three states: cancelled, released or open.
  # Cancellation wins over everything, as it does for an asset, because a cancelled release
  # stopped counting toward shipping the moment it was cancelled, whether or not it was ever
  # published. A published release is released, and any other one is still open.

  # any note other than a status note of the release asset type is no release
  if not _has_role(fm, SpecValue.ROLE_STATUS) or not _is_release(fm):
    return None

  # cancellation wins over publication, exactly as it does for an asset
  if _read_gate(fm, Gate.SPEC_CANCELLED):
    return _BUCKET_RELEASE_CANCELLED

  # a published release is closed; any other one is still open
  if _read_gate(fm, Gate.RELEASED):
    return _BUCKET_RELEASE_RELEASED
  return _BUCKET_RELEASE_OPEN


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
  m = re.search(r"^request_status:\s*(\S+)(?:[ \t]+#.*)?\s*$", fm, re.MULTILINE)
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
  # ladder — the moment it holds no subfolders of its own, because any subfolder is taken for an
  # asset, and a container that holds assets is always a category and never an inbox, no matter
  # what loose files sit beside them.
  # Within such a folder, the canonical inbox name settles the reading even while still empty,
  # and any other folder qualifies the moment one file inside it has already opted into intake.

  dir_name = container_dir.name
  has_request_file = False
  for entry in container_dir.iterdir():
    # asset subfolders disqualify requests-inbox mode
    if entry.is_dir():
      return False

    # guard: not a regular file — nothing to read as a request
    if not entry.is_file():
      continue

    # only markdown files are request candidates
    # waiver: magic literal '.md' -- markdown extension is a fixed protocol token
    if not entry.name.endswith(".md"):
      continue

    # the folder-note itself is no request
    if entry.name == f"{dir_name}.md":
      continue
    if _read_request_status(entry.read_text(encoding = "utf-8")) is not None:
      has_request_file = True

  # a 'requests'-named container with no asset subfolders is an inbox even when empty
  # waiver: magic literal 'requests' -- the inbox folder name is a fixed protocol token
  return has_request_file or dir_name == "requests"


def _render_requests_stats(container_dir: Path, lang: str) -> str:
  """
  Compute the stats block for a requests inbox.

  Args:
    container_dir: The requests inbox folder.
    lang: The language the request total's label and each status's label are written in.

  Returns:
    A multi-line markdown list headed by a request total item, with one nested item per non-zero
    request status beneath it. An empty inbox yields the request total item alone, with a zero count.
  """
  dir_name = container_dir.name
  counts: dict[str, int] = dict.fromkeys(_REQUEST_STATUSES, 0)
  for entry in container_dir.iterdir():
    # guard: not a regular file — nothing to read as a request
    if not entry.is_file():
      continue

    # only markdown files are request candidates
    # waiver: magic literal '.md' -- markdown extension is a fixed protocol token
    if not entry.name.endswith(".md"):
      continue

    # the folder-note itself is no request
    if entry.name == f"{dir_name}.md":
      continue
    status = _read_request_status(entry.read_text(encoding = "utf-8"))
    if status in counts:
      counts[status] += 1

  # the request total heads the block, each non-zero status nests under it in the fixed status order
  total = sum(counts.values())
  lines = [ _STATS_ITEM.format(count = total, label = _format_label(_STATS_REQUEST, total, lang)) ]
  lines.extend(
      _STATS_SUB_ITEM.format(count = count, label = Lockit.text(_REQUEST_STATUS_KEYS[status], lang))
      for status, count in counts.items() if count
  )
  return _STATS_LINE_SEPARATOR.join(lines)


def is_shelf_note(note: Path) -> bool:
  """
  Judge whether a folder-note is a shelf — a folder the container tally reads straight through.

  This is the one transparency predicate: a caller refreshing stats regions upward climbs
  through exactly the folders it reports as shelves, and the tally descends through the same
  set with two exceptions: it counts a release and never enters it, and it never enters the
  reserved `releases` folder from above, although that folder's group note reads as a shelf.

  Args:
    note: The folder's own folder-note.

  Returns:
    True when the note is neither an asset status note nor a product's level note; a release's
    status note reads as a shelf too.
  """
  return classify(note.read_text(encoding = "utf-8")) == _BUCKET_SHELF


def _tally_children(container_dir: Path, buckets: dict[str, int], *,
                    visited: set[Path] | None = None) -> None:
  """
  Tally one folder's status-note children into `buckets`, descending through group folders.

  Assets, nested products and releases each land in a bucket of their own. A release is counted
  and never entered, and the reserved `releases` folder is never entered from above it.

  A folder is reached at most once per tally, whatever its bucket: a symlink pointing back up
  the tree neither loops nor double-counts the shelves behind it, and a second symlinked route
  to one asset folder counts that asset once, not once per route.

  Args:
    container_dir: The folder whose subfolders are tallied.
    buckets: Asset, product and release bucket counters, incremented in place.
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
  # The reserved releases folder is closed to a summary reading from above it: a product's
  # summary, or that of any container enclosing it, never looks inside, so releases count
  # toward nothing at product level. A release met by the walk, which only a summary of the
  # releases folder itself or of a group folder inside it can reach, is counted by its own
  # state and never entered.

  # a symlinked folder resolves to a path the walk may already be standing in, so the set of
  # reached folders is what bounds the descent rather than the depth of the tree on disk
  seen = { container_dir.resolve() } if visited is None else visited
  for entry in sorted(container_dir.iterdir()):
    # only subfolders carrying a same-named folder-note count
    if not entry.is_dir():
      continue

    # the reserved releases folder is closed to a walk coming from above it
    if entry.name == ReleaseKey.FOLDER:
      continue
    note = entry / f"{entry.name}.md"

    # guard: the expected same-named folder-note is missing — nothing to read
    if not note.is_file():
      continue
    resolved = entry.resolve()

    # guard: a folder this tally already reached is a second route to it, never a second place
    if resolved in seen:
      continue
    seen.add(resolved)

    # a release is counted by its own state and never entered
    text = note.read_text(encoding = "utf-8")
    if (release := _release_bucket(_frontmatter(text))) is not None:
      buckets[release] += 1
      continue

    # every other note falls into an asset bucket, the product bucket or the shelf reading
    bucket = classify(text)

    # a group folder is transparent — it is never counted, and the tally reads through it
    if bucket == _BUCKET_SHELF:
      _tally_children(entry, buckets, visited = seen)
      continue

    # an asset, or a nested product the walk counts whole and never enters
    buckets[bucket] += 1


def render_container_stats(container_dir: Path, *, lang: str = LangId.EN) -> str:
  """
  Compute the stats block for a group container from the assets below it.

  Detects a requests inbox (flat `*.md` files with `request_status`) and emits
  request-status counts; otherwise falls back to the asset-ladder counts. A nested product
  or a release among the children is counted in an item of its own rather than as an asset,
  and a group folder is transparent — its own children count here, the folder itself never does.
  The reserved `releases` folder is not entered from above it.

  Args:
    container_dir: The group folder (e.g. `bugs/`) or requests inbox.
    lang: The language the total and state labels are written in, request statuses included; a language with no
      text falls back to English.

  Returns:
    A multi-line markdown list. Total items sit at the top level and their breakdown items nest one
    level beneath them; zero-count breakdown items are omitted. A products item comes first when
    nested products exist, then a releases item when releases exist, and the asset item is left
    out when its count is zero beside products or releases. Asset breakdown items run released, ready,
    in progress, not started, cancelled.
  """

  # Domain(spec.notes):
  # # How a container presents its counts
  # Nested products are counted as their own total and listed first, apart from the assets,
  # because each of them runs its own ladder and answers for its own assets. Releases come
  # next, as a total of their own with one nested count for every non-zero release state in the
  # order released, open, cancelled, because a release is the product's unit of shipping and
  # not one of its assets. The asset total follows, with one nested count for every non-zero
  # lifecycle state beneath it, even when only one state is present, so the reader always sees
  # which state the assets are in. An asset total of zero is left out beside products or
  # releases, where it would only repeat that they hold everything, but an empty container
  # still shows a zero asset count so the counts are never blank. A requests inbox lists its
  # request total, with one nested count for every non-zero request status beneath it.

  # delegate to requests mode when the inbox heuristic matches
  if _is_requests_inbox(container_dir):
    return _render_requests_stats(container_dir, lang)

  # every other container is tallied into asset, product and release buckets
  buckets = {
      _BUCKET_RELEASED: 0, _BUCKET_READY: 0, _BUCKET_IN_PROGRESS: 0,
      _BUCKET_NOT_STARTED: 0, _BUCKET_CANCELLED: 0, _BUCKET_PRODUCT: 0,
      _BUCKET_RELEASE_RELEASED: 0, _BUCKET_RELEASE_OPEN: 0, _BUCKET_RELEASE_CANCELLED: 0,
  }
  _tally_children(container_dir, buckets)

  # a nested product is counted beside the assets, never among them — it has its own ladder,
  # so its total heads the block as an item of its own
  products = buckets[_BUCKET_PRODUCT]
  lines = []
  if products:
    lines.append(_STATS_ITEM.format(count = products, label = _format_label(_STATS_PRODUCT, products, lang)))

  # releases are counted beside the assets too, their total followed by each non-zero release state
  release_labels = [
      (_BUCKET_RELEASE_RELEASED, _STATS_RELEASED), (_BUCKET_RELEASE_OPEN, _STATS_OPEN),
      (_BUCKET_RELEASE_CANCELLED, _STATS_CANCELLED),
  ]
  releases = sum(buckets[key] for key, _label in release_labels)
  if releases:
    lines.append(_STATS_ITEM.format(count = releases, label = _format_label(_STATS_RELEASE, releases, lang)))
    lines.extend(
        _STATS_SUB_ITEM.format(count = buckets[key], label = _format_label(label, buckets[key], lang))
        for key, label in release_labels if buckets[key]
    )

  # the asset total is left out when it is zero beside products or releases; an empty container still shows it
  labels = [
      (_BUCKET_RELEASED, _STATS_RELEASED), (_BUCKET_READY, _STATS_READY), (_BUCKET_IN_PROGRESS, _STATS_IN_PROGRESS),
      (_BUCKET_NOT_STARTED, _STATS_NOT_STARTED), (_BUCKET_CANCELLED, _STATS_CANCELLED),
  ]
  total = sum(buckets[key] for key, _label in labels)
  if total or not (products or releases):
    lines.append(_STATS_ITEM.format(count = total, label = _format_label(_STATS_ASSET, total, lang)))

  # each non-zero lifecycle bucket nests under the asset total
  lines.extend(
      _STATS_SUB_ITEM.format(count = buckets[key], label = _format_label(label, buckets[key], lang))
      for key, label in labels if buckets[key]
  )
  return _STATS_LINE_SEPARATOR.join(lines)


def apply_container_stats(note_path: Path,
                          *,
                          products: dict | None = None,
                          catalog_guidelines: dict[str, list[str]] | None = None) -> bool:
  """
  Rewrite the `spec:stats` region of a container note from its sibling children.

  The region is replaced by the multi-line markdown stats list the container's children produce, with its labels
  written in the note's own language.

  Args:
    note_path: The container folder-note (e.g. `bugs/bugs.md`).
    products: An already-loaded products registry the note's language is resolved in; None reads it from the
      settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the settings file.

  Returns:
    True when the file content changed.

  Raises:
    ValueError: If the note carries the stats markers and the settings file is read for the products registry or
      the catalog-wide guidelines and cannot be read, is not valid JSON, not UTF-8 text or not a JSON object.
    RuntimeError: If the note carries the stats markers, its own language and its product's yield nothing, and the
      core plugin's CLI cannot be resolved, its language verb exits non-zero, or the verb exits zero but answers
      nothing.
  """
  # the marker pair decides whether this note is a managed container summary
  text = spec_paths.read_text(note_path)

  # guard: no stats markers, nothing this function owns
  if _STATS_START not in text or _STATS_END not in text:
    return False

  # the freshly rendered stats replace whatever the marker pair held
  lang = note_explainers.lang_for_note(note_path, products = products, catalog_guidelines = catalog_guidelines)
  stats = render_container_stats(note_path.parent, lang = lang)
  new = re.sub(
      re.escape(_STATS_START) + r".*?" + re.escape(_STATS_END), f"{_STATS_START}\n{stats}\n{_STATS_END}",
      text, flags = re.DOTALL,
  )

  # every stats refresh also re-heals the note's section explainer lines
  new = note_explainers.heal_note_text(note_path, new, products = products, catalog_guidelines = catalog_guidelines)

  # nothing changed — the note is left unwritten
  if new == text:
    return False
  spec_paths.write_text_atomic(note_path, new)
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

  # the folder above is the catalog root, whose region counts products rather than
  # assets — an asset flip below it moves nothing the block reports
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
  return _has_role(_frontmatter(note.read_text(encoding = "utf-8")), SpecValue.ROLE_CATALOG)


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
