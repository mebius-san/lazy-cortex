"""
Logic behind the `lazycortex-specs review-rows <note>` verb.

The verb keeps the `Review <doc>` launch rows in a spec folder note's `# Gates` section in line with the documents
the note owes one, and lays the section out into its row groups, the rows of one verb sharing one gate callout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    GATE_ROW_ORDER, LEVEL_ROLES, ConflictCallout, GateCheckbox, GateRowGroup, LevelDoc, Section, SpecHaltKey,
    SpecKey, Stage, StageKey,
)


_ENCODING = "utf-8"
_MD_SUFFIX = ".md"
_LF = "\n"
_QUOTE = ">"
_CALLOUT_OPEN = "> [!"
_GATE_OPEN = f"{_QUOTE} {GateCheckbox.GATE_CALLOUT_MARK} "
CONFLICT_OPEN = f"{_QUOTE} {ConflictCallout.MARK} {ConflictCallout.TITLE_PREFIX}"
# A checkbox line of a gate callout: its tick mark and the row's label
_CHECKBOX_RE = re.compile(r"^>\s*-\s*\[([ xX])\]\s*(.*?)\s*$")
_TICK_GROUP = 1
_LABEL_GROUP = 2
_UNTICKED_MARK = " "
_TICKED_BOX = "> - [x]"
_UNTICKED_BOX = "> - [ ]"
_WRITE_PREFIX = "Write "
_REVISE_PREFIX = "Revise "
_H1_PREFIX = "# "
_ADDED = "added"
_REMOVED = "removed"
_KEPT = "kept"
_CHANGED = "changed"
# The env var the daemon exports for every subprocess it spawns
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class GateRow:
  """
  One launch row of a folder note's `# Gates` section.

  Attributes:
    label: The row's label, as its checkbox line writes it.
    ticked: Whether the row's checkbox is ticked.
    hint: The explanatory text lines of the callout holding the row, interior blank lines kept as empty strings.
    line: Index of the row's checkbox line within the section lines it was read from.
  """

  # The row's label, read off its checkbox line
  label: str

  # Whether the row's checkbox carries a tick
  ticked: bool

  # The text lines of the callout below its checkboxes, blank interior lines kept as empty strings
  hint: tuple[str, ...]

  # Index of the row's checkbox line within the section lines it was read from; the callout's own line for a callout
  # that carries no checkbox
  line: int


# ----------------------------------------------------------------------------------------
def _find_all_scope_files(note: Path, role: str) -> list[str]:
  """
  List the documents beside a note that fall in its review scope.

  Level notes cover only the level documents of their own folder, in ladder order; any other note covers every
  other markdown file beside it, alphabetically.

  Args:
    note: Path of the folder note.
    role: The note's `spec_role` value.

  Returns:
    File names, relative to the note's folder, in scope order.
  """

  # Domain(spec.notes):
  # # Review scope of a folder note
  # What a folder note may offer to review depends on what the note describes. A level note, meaning the folder note
  # of a product or of the catalog root, covers only the five level documents of its own folder: vision, use-cases,
  # design, ui-design and tech, taken in that ladder order. It never covers the documents of a product nested inside
  # it, because those belong to the nested product's own note. An asset status note covers every other markdown
  # file that sits beside it, taken in alphabetical order.

  # a level note owns exactly the ladder's documents of its own folder, in writing order
  if role in LEVEL_ROLES:
    return [ name for name, _doc_type, _gate in LevelDoc.CHAIN if (note.parent / name).is_file() ]

  # an asset note owns every other markdown file beside it, alphabetically
  return sorted(
      entry for entry in os.listdir(note.parent)
      if entry.endswith(_MD_SUFFIX) and entry != note.name and (note.parent / entry).is_file()
  )


def _is_owed(repo: Path, doc: Path, product: str | None) -> bool:
  """
  Decide whether a document is owed a review checkbox row.

  A document is owed one when its declared document type takes part in review and is not append-only, and the
  document is neither already under review nor at `spec_stage: cancelled`, since a cancelled document's work is
  abandoned. An append-only report enters review only when its writing job finishes, never by an operator's tick.

  Args:
    repo: Repository root.
    doc: Path of the document to test.
    product: Key of the owning product whose own document types extend the shipped registry, or `None`.

  Returns:
    `True` when the document is owed a row, `False` for an untyped document, an undeclared or non-reviewed type,
    an append-only type, a document at `spec_stage: cancelled`, or a document already carrying
    `review_active: true`.
  """

  # Domain(spec.notes):
  # # Open-review checkbox on a folder note
  # A document of a spec asset or level carries a permanent "open review" checkbox in its folder note for as long
  # as four things hold: its document type is one that goes through the review loop, that type is not append-only,
  # the document is not under review right now, and the document is not cancelled. A report that is only ever
  # appended to never gets the checkbox, even though its type goes through review: such a report enters review
  # only when the job writing it finishes, never through an operator's tick. A cancelled document never gets the
  # checkbox either, because its work is abandoned. Every other lifecycle stage qualifies: empty, draft, approved,
  # rejected and deferred documents all do, and so does a document that carries no stage at all. Whether an
  # operator has edited the document does not matter. The checkbox is the operator's own way to open a review, and
  # nothing opens one on its own. A document already in review needs no checkbox to enter it, so the checkbox
  # disappears for the duration of the review and returns when it ends.

  # guard: an untyped document has no declaration to route it through review
  if not (doc_type := spec_doc_types.doc_type_of(doc)):
    return False

  # guard: an undeclared type, or one kept out of the review loop, is owed nothing
  if not (declaration := spec_doc_types.resolve(repo, doc_type, product)) or \
      not declaration.get(spec_doc_types.DocTypeFlag.REVIEW):
    return False

  # guard: an append-only report enters review only when its writing job finishes, never by a tick
  if declaration.get(spec_doc_types.DocTypeFlag.APPEND_ONLY):
    return False

  # the document's own frontmatter carries its stage and its review flag
  fm_values, _fm_end = spec_frontmatter.parse(doc.read_text(encoding = _ENCODING))

  # guard: a cancelled document's work is abandoned, so no review is offered on it
  if fm_values.get(StageKey.STAGE, "").strip() == Stage.CANCELLED:
    return False

  # a document already in the loop needs no row to enter it
  return not flip_gate.is_true(fm_values, SpecKey.REVIEW_ACTIVE)


def read_review_candidates(repo: Path, note: Path) -> list[str]:
  """
  List the documents a spec folder note owes a `Review <doc>` launch row.

  Guarantees:
    - The documents come back in scope order: the level ladder order (vision, use-cases, design, ui-design, tech) on
      a level note, alphabetical order on an asset note.
    - A halted note yields an empty list; an untyped document, an undeclared or non-reviewed type, an append-only
      type, a cancelled document and a document already under review are never listed.

  Args:
    repo: Repository root.
    note: Path of the folder note, located inside the repository.

  Returns:
    File names, relative to the note's folder, in scope order. Empty when the note carries `spec_halted: true`.

  Raises:
    ValueError: If the note lies outside the repository.
  """

  # Contract:
  # The documents come back in scope order: on a level note in the level ladder order (vision, use-cases, design,
  # ui-design, tech), on an asset note in alphabetical order. Callers append new rows in exactly this order, so
  # it never changes with how the scope is listed.

  # Contract:
  # A halted note yields an empty list. An untyped document, an undeclared or non-reviewed type, an append-only
  # type, a cancelled document and a document already under review are never listed.

  # Domain(spec.notes):
  # # Halted note owes no review checkbox
  # A halted note owes no open-review checkbox row, whether it is an asset note or a level note (a product's
  # or the catalog root's folder note), and whatever documents sit beside it or their types and stages. A halt
  # takes the note's un-ticked checkbox rows down until the halt is lifted.

  note_fm, _fm_end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))

  # guard: a halted note hangs no checkbox row at all
  if flip_gate.is_true(note_fm, SpecHaltKey.HALTED):
    return []

  # the owning product, whose own document types extend the shipped registry
  product, _record = resolve_product.effective_record_by_path(
      repo, note.resolve().relative_to(repo.resolve()).as_posix(),
  )

  # keep the scope's order, dropping every document that is not owed a row
  return [
      name for name in _find_all_scope_files(note, flip_gate.note_role(note_fm))
      if _is_owed(repo, note.parent / name, product)
  ]


def _find_all_callout_spans(section_lines: list[str], opener: str) -> list[tuple[int, int]]:
  """
  Locate the callout blocks of a section whose first line opens with a given prefix.

  A block runs from its opening line over the consecutive `>` lines, ending before the next non-quoted line or the
  next callout (`> [!`).

  Args:
    section_lines: Lines of the `# Gates` section.
    opener: The prefix a block's first line starts with.

  Returns:
    The `(start, end)` half-open line index ranges of the blocks, in section order.
  """
  spans: list[tuple[int, int]] = []
  pos = 0
  while pos < len(section_lines):
    # guard: a line that opens no such callout belongs to no block
    if not section_lines[pos].startswith(opener):
      pos += 1
      continue

    # the block runs over the consecutive quoted lines, stopping where another callout opens
    end = pos + 1
    while end < len(section_lines) and section_lines[end].startswith(_QUOTE) and \
        not section_lines[end].startswith(_CALLOUT_OPEN):
      end += 1
    spans.append(( pos, end ))
    pos = end

  # every block in the order the section carries them
  return spans


def _find_all_gate_spans(section_lines: list[str]) -> list[tuple[int, int]]:
  """
  Locate the gate callouts of a section.

  Callout boundaries follow the same rules as `parse_gate_rows`.

  Args:
    section_lines: Lines of the `# Gates` section.

  Returns:
    The `(start, end)` half-open line index ranges of the gate callouts, in section order.
  """
  return _find_all_callout_spans(section_lines, _GATE_OPEN)


def find_all_conflict_spans(section_lines: list[str]) -> list[tuple[int, int]]:
  """
  Locate the conflict callouts of a section.

  A conflict callout opens with `> [!warning] Conflict with ` and runs over the consecutive `>` lines, ending before
  the next non-quoted line or the next callout; any other `[!warning]` callout is not one.

  Args:
    section_lines: Lines of the `# Gates` section.

  Returns:
    The `(start, end)` half-open line index ranges of the conflict callouts, in section order.
  """
  return _find_all_callout_spans(section_lines, CONFLICT_OPEN)


def _parse_callout_rows(section_lines: list[str], start: int, end: int) -> list[GateRow]:
  """
  Read the launch rows of one gate callout.

  Args:
    section_lines: Lines of the `# Gates` section.
    start: Index of the callout's `> [!gate] ` line.
    end: Index one past the callout's last line.

  Returns:
    One row per checkbox line, in callout order, each carrying the callout's text lines as its hint; a callout
    without a checkbox line yields one unticked row labelled by the text after its gate mark.
  """
  head = section_lines[start][len(_GATE_OPEN):].strip()
  boxes: list[tuple[int, re.Match[str]]] = []
  texts: list[str] = []

  # every quoted line below the head is either a checkbox or a line of the callout's text
  for idx in range(start + 1, end):
    if (match := _CHECKBOX_RE.match(section_lines[idx])) is not None:
      boxes.append(( idx, match ))
    else:
      texts.append(section_lines[idx][len(_QUOTE):].strip())

  # the text runs from its first to its last written line, blank lines inside kept
  filled = [ idx for idx, text in enumerate(texts) if text ]
  hint = tuple(texts[filled[0]:filled[-1] + 1]) if filled else ()

  # a callout without a checkbox offers one unticked row under its head text
  if not boxes:
    return [ GateRow(label = head, ticked = False, hint = hint, line = start) ]

  # one row per checkbox, labelled by its own line, falling back to the head text for a bare box
  return [
      GateRow(label = match.group(_LABEL_GROUP) or head, ticked = match.group(_TICK_GROUP) != _UNTICKED_MARK,
              hint = hint, line = idx)
      for idx, match in boxes
  ]


def parse_gate_rows(section_lines: list[str]) -> list[GateRow]:
  """
  Split a `# Gates` section into its launch rows.

  A gate callout runs from its `> [!gate] ` line over the consecutive `>` lines, ending before the next non-quoted
  line or the next callout (`> [!`), so a halt `[!failure]` callout placed flush after one is never absorbed into
  it. Both shapes a callout comes in are read: a one-row block whose title repeats its label, and a callout titled
  by a verb holding the checkboxes of every row of that verb. A row's label comes from its checkbox line, never from
  the callout's title.

  Args:
    section_lines: Lines of the `# Gates` section.

  Returns:
    One `GateRow` per checkbox line, in section order; a gate callout without any checkbox line contributes one
    unticked row labelled by the text after its gate mark.
  """
  return [ row for start, end in _find_all_gate_spans(section_lines)
           for row in _parse_callout_rows(section_lines, start, end) ]


def find_all_hanging_write_docs(body: str) -> set[str]:
  """
  Name the documents whose `Write` row hangs unticked in a folder note's `# Gates` section.

  Args:
    body: The folder note's body text, frontmatter stripped.

  Returns:
    The basenames of those documents; empty when the body has no `# Gates` section.
  """
  lines = body.split(_LF)

  # guard: a note without the section hangs no row
  if (head := next(( idx for idx, line in enumerate(lines) if line.strip() == Section.GATES ), None)) is None:
    return set()

  # the section runs from its heading to the next H1; its own sub-headings stay inside it
  end = next(( idx for idx in range(head + 1, len(lines)) if lines[idx].startswith(_H1_PREFIX) ), len(lines))

  # every unticked `Write <stem>` row names the document `<stem>.md` it would create
  return {
      row.label[len(_WRITE_PREFIX):] + _MD_SUFFIX
      for row in parse_gate_rows(lines[head:end])
      if not row.ticked and row.label.startswith(_WRITE_PREFIX)
  }


def verb_of(label: str) -> str:
  """
  Name the verb a launch row's label opens with.

  Args:
    label: The row's label.

  Returns:
    The label's first word, or the empty string for a blank label.
  """
  # the first word is the verb that decides which callout the row joins
  words = label.split(maxsplit = 1)
  return words[0] if words else ""


def _callout_footer(verb: str, rows: list[GateRow], lang: str) -> list[str]:
  """
  Compose the text lines closing the gate callout of one verb.

  Args:
    verb: The verb the callout's rows share.
    rows: The callout's rows.
    lang: Authoring language of the note.

  Returns:
    The verb's fixed one-line helper in the note's language (English for an unknown language) when the verb has
    one; otherwise the distinct hints the rows carried, in first-seen order, separated by blank lines; empty when
    there is neither.
  """
  # a verb with a fixed helper always carries that one line
  if helper := note_explainers.gate_helper_text(verb, lang):
    return [ helper ]

  # any other verb keeps what its rows said, each distinct text once
  hints = [ hint for hint in dict.fromkeys(row.hint for row in rows) if hint ]
  return [ line for pos, hint in enumerate(hints) for line in ([ "" ] if pos else []) + list(hint) ]


def render_gate_callout(verb: str, rows: list[GateRow], lang: str) -> list[str]:
  """
  Render the gate callout holding the rows of one verb.

  The callout is its title line `> [!gate] <title>`, one checkbox line per row in the order given, and, when there
  is a footer, a bare `>` followed by the footer lines. The title is the verb exactly as the rows write it, whatever
  the note's language.

  Args:
    verb: The verb the rows share.
    rows: The rows the callout holds, in the order they are listed.
    lang: Authoring language of the note.

  Returns:
    The callout's lines, title line first.
  """
  # one checkbox line per row, its tick carried as the row holds it
  boxes =[ f"{_TICKED_BOX if row.ticked else _UNTICKED_BOX} {row.label}" for row in rows ]

  # the footer sits behind its own bare quoted line, so Obsidian's task renderer keeps it visible
  footer = _callout_footer(verb, rows, lang)
  tail = [ _QUOTE, *(f"{_QUOTE} {text}" if text else _QUOTE for text in footer) ] if footer else []

  # the title is the verb as the rows write it, in every note language; only the footer follows the language
  return [ f"{_GATE_OPEN}{verb}", *boxes, *tail ]


def _parse_review_file(row: GateRow) -> str | None:
  """
  Name the document a launch row offers to review.

  Args:
    row: The row to inspect.

  Returns:
    The document name a `Review <doc>` row names, or `None` for any other row.
  """
  # guard: a row whose label lacks the review prefix names no document
  if not row.label.startswith(GateCheckbox.REVIEW_PREFIX):
    return None

  # a review row names its document after the prefix
  return row.label[len(GateCheckbox.REVIEW_PREFIX):]


def _is_blank_or_absent(lines: list[str], idx: int) -> bool:
  """
  Tell whether a line position is blank or past the end.

  Args:
    lines: The lines to look into.
    idx: Index of the line to test.

  Returns:
    `True` when the line at `idx` is blank or `idx` is past the end of `lines`.
  """
  # past the end counts as blank, so a section closing the body needs no separator
  return idx >= len(lines) or not lines[idx].strip()


def read_review_stages(repo: Path, note: Path) -> dict[str, str]:
  """
  Read the stage of every document in a folder note's review scope.

  Args:
    repo: Repository root.
    note: Path of the folder note, located inside the repository.

  Returns:
    Document name to its `spec_stage`, for every scope document that carries one; a document without a stage is
    absent from the result.

  Raises:
    ValueError: If the note lies outside the repository.
  """
  note.resolve().relative_to(repo.resolve())
  note_fm, _fm_end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))

  # every scope document with a stage, keyed by its name
  stages: dict[str, str] = {}
  for name in _find_all_scope_files(note, flip_gate.note_role(note_fm)):
    doc_fm, _end = spec_frontmatter.parse((note.parent / name).read_text(encoding = _ENCODING))
    if stage := doc_fm.get(StageKey.STAGE, "").strip():
      stages[name] = stage
  return stages


def _row_document(label: str) -> str | None:
  """
  Name the document a gate row is about.

  Args:
    label: The row's label.

  Returns:
    The document a `Review`, `Write` or `Revise` row names, or `None` for a tool launch or publication row.
  """
  # a review row names its document outright
  if label.startswith(GateCheckbox.REVIEW_PREFIX):
    return label[len(GateCheckbox.REVIEW_PREFIX):]

  # a write or revise row names the document it creates or reopens by its stem
  for prefix in (_WRITE_PREFIX, _REVISE_PREFIX):
    if label.startswith(prefix):
      return label[len(prefix):] + _MD_SUFFIX
  return None


def order_key(row: GateRow) -> int:
  """
  Place a gate row on the ladder.

  Args:
    row: The row to place.

  Returns:
    The row's index in the ladder order, by the document it is about or by its label; a row the ladder does not
    list sorts after every listed one.
  """
  # the document first, the bare label second, so a review of the design and the design's own write row share a rung
  for key in (_row_document(row.label), row.label):
    if key in GATE_ROW_ORDER:
      return GATE_ROW_ORDER.index(key)
  return len(GATE_ROW_ORDER)


def group_of(row: GateRow, stages: dict[str, str]) -> str:
  """
  Sort a gate row into its layout group.

  Args:
    row: The row to sort.
    stages: Document name to `spec_stage`, as `read_review_stages` reads them.

  Returns:
    `GateRowGroup.REREVIEW` for a review row of an approved document, `GateRowGroup.NEXT` for every other row.
  """
  # only a review of an already approved document re-opens settled work; everything else moves the asset forward
  file = _parse_review_file(row)
  if file is not None and stages.get(file) == Stage.APPROVED:
    return GateRowGroup.REREVIEW
  return GateRowGroup.NEXT


def layout_section(section_lines: list[str], stages: dict[str, str], lang: str) -> list[str]:
  """
  Lay a `# Gates` section out into its row groups and conflict callouts.

  Text that is neither a launch row nor a conflict callout keeps its order and comes first. Then come the
  next-step rows and the re-review rows, each group under its own sub-heading and, inside a group, the rows of one
  verb in one gate callout in ladder order. Last come the conflict callouts under their own sub-heading, carried
  byte for byte. A group without members gets no sub-heading, and a ticked row stays ticked.

  Guarantees:
    - Laying out an already laid-out section changes nothing.
    - Every row the section carries comes out once with its label and its tick; no row is added or dropped.

  Args:
    section_lines: Lines of the `# Gates` section, heading first.
    stages: Document name to `spec_stage`, as `read_review_stages` reads them.
    lang: Authoring language of the note.

  Returns:
    The section's lines, laid out.
  """

  # Contract:
  # Laying out an already laid-out section changes nothing: the layout is a fixed point of itself, so a caller may
  # run it on every wake without churning the note.

  # Contract:
  # Every row the section carries, in either callout shape, comes out exactly once with its label and its tick; the
  # layout never adds or drops a row, so a migration may run it without changing what the note offers.

  # Domain(spec.notes):
  # # Conflict callouts close the gates section
  # In the gates section of a folder-note, conflict callouts form the last group, after the next-step rows and the
  # re-review rows. They are carried as written, without being reshaped or reordered, and sit under their own group
  # heading. When the note holds no conflict callout, the group heading is absent as well.

  # Domain(spec.notes):
  # # Launch rows of one verb share one callout
  # Inside each group of the gates section, the launch rows that open with the same verb — write, review, start,
  # rebuild, publish, revise, or any other first word — sit together in one callout titled by that verb exactly as
  # the rows write it, whatever language the note is written in. The callout lists one checkbox per
  # row in ladder order, and the callouts themselves follow the ladder position of their first row. The explanation
  # is written once, at the bottom of the callout, never per row: write, review, start, rebuild and publish rows carry
  # a fixed explanation of what a tick does, in the note's language, and any other verb keeps the distinct
  # explanations its rows brought along. A ticked row is the operator's gesture and stays in its verb's callout as a
  # ticked checkbox. An older note that kept every row in a block of its own is read the same way and folded into
  # this shape.

  headings = note_explainers.gate_heading_texts()

  # the spans of every gate and conflict callout, in section order
  conflict_spans = find_all_conflict_spans(section_lines)
  block_spans = sorted([ *_find_all_gate_spans(section_lines), *conflict_spans ])

  # every line outside the callouts, as runs of written lines; a blank line or an old sub-heading ends a run and is
  # dropped, and so does the start of a callout
  runs: list[list[str]] = []
  run: list[str] = []
  pos = 0
  for start, end in [ *block_spans, ( len(section_lines), len(section_lines) ) ]:
    for line in section_lines[pos:start]:
      if line in headings or not line.strip():
        if run:
          runs.append(run)
          run = []
        continue
      run.append(line)
    if run:
      runs.append(run)
      run = []
    pos = end

  # the written lines first, one blank line between runs
  laid: list[str] = []
  for chunk in runs:
    if laid:
      laid.append("")
    laid.extend(chunk)

  # then the two groups, each under its sub-heading, one callout per verb in the order of its first row
  rows = parse_gate_rows(section_lines)
  for group in (GateRowGroup.NEXT, GateRowGroup.REREVIEW):
    members = sorted(( row for row in rows if group_of(row, stages) == group ), key = order_key)

    # guard: a group without rows gets no sub-heading
    if not members:
      continue

    # the group's rows gathered per verb, each verb keeping the place of its first row
    by_verb: dict[str, list[GateRow]] = {}
    for row in members:
      by_verb.setdefault(verb_of(row.label), []).append(row)

    # the sub-heading, then one callout per verb
    laid.extend([ "", note_explainers.gate_heading_text(group, lang) ])
    for verb, verb_rows in by_verb.items():
      laid.extend([ "", *render_gate_callout(verb, verb_rows, lang) ])

  # last the conflict callouts, under their own sub-heading, each carried as the section holds it
  if conflict_spans:
    laid.extend([ "", note_explainers.gate_heading_text(GateRowGroup.CONFLICTS, lang) ])
    for start, end in conflict_spans:
      laid.extend([ "", *section_lines[start:end] ])

  # the section closes the way it opened: on a blank line when one followed its last written line
  if section_lines and not section_lines[-1].strip():
    laid.append("")
  return laid


def _find_gates_span(lines: list[str]) -> tuple[int, int] | None:
  """
  Locate the `# Gates` section of a note body.

  Args:
    lines: The body's lines.

  Returns:
    The `(head, end)` half-open range from the section's heading to the next H1 or the end of the body, or `None`
    when the body has no such section.
  """
  # guard: without the heading there is no section
  if (head := next(( idx for idx, line in enumerate(lines) if line.strip() == Section.GATES ), None)) is None:
    return None

  # the section runs to the next H1; its own sub-headings stay inside it
  return head, next(( idx for idx in range(head + 1, len(lines)) if lines[idx].startswith(_H1_PREFIX) ), len(lines))


def layout_body(body: str, stages: dict[str, str], lang: str) -> str:
  """
  Lay out the `# Gates` section of a folder-note body, leaving every other line as it is.

  Guarantees:
    - Every line outside the `# Gates` section is carried over byte for byte.
    - Laying out an already laid-out body changes nothing.

  Args:
    body: Folder-note body text, after the frontmatter.
    stages: Document name to `spec_stage`, as `read_review_stages` reads them.
    lang: Authoring language of the note.

  Returns:
    The body with its `# Gates` section laid out by `layout_section`.

  Raises:
    ValueError: If the body has no `# Gates` H1 section.
  """

  # Contract:
  # Every line outside the `# Gates` section MUST be carried over byte for byte, and laying out an already laid-out
  # body MUST change nothing: the gate-rows migration relies on both to touch no other part of a note and to be safe
  # to run twice.

  lines = body.split(_LF)

  # guard: without the section there is nothing to lay out
  if (span := _find_gates_span(lines)) is None:
    raise ValueError(f"the note body has no {Section.GATES} section")

  # only the section's lines are laid out; the head and the rest are re-joined untouched
  head, end = span
  return _LF.join([ *lines[:head], *layout_section(lines[head:end], stages, lang), *lines[end:] ])


def _drop_rows(section: list[str], doomed: set[int], tail: list[str]) -> None:
  """
  Remove launch rows from a `# Gates` section in place.

  A removed row takes only its checkbox line; a gate callout left without any checkbox goes whole, and with it the
  blank line before it when nothing but a blank line or the end of the body follows it.

  Args:
    section: Lines of the `# Gates` section, edited in place.
    doomed: Indices of the rows' checkbox lines (or callout lines, for a callout carrying no checkbox) to remove.
    tail: The body's lines after the section, consulted for what follows a callout closing the section.
  """
  # every callout from the back, so earlier indices stay valid while later lines go
  for start, end in reversed(_find_all_gate_spans(section)):
    rows = _parse_callout_rows(section, start, end)
    gone = [ row.line for row in rows if row.line in doomed ]

    # guard: a callout losing none of its rows stays as it is
    if not gone:
      continue

    # a callout keeping some of its rows loses just the removed checkbox lines
    if len(gone) < len(rows):
      for idx in reversed(gone):
        del section[idx]
      continue

    # a callout losing every row goes whole, folding the blank line that separated it when nothing follows it
    del section[start:end]
    if start > 0 and not section[start - 1].strip() and _is_blank_or_absent(section + tail, start):
      del section[start - 1]


def _hang_review_rows(section: list[str], added: list[str], lang: str, tail: list[str]) -> None:
  """
  Hang new `Review <doc>` rows into a `# Gates` section in place.

  The rows join the first gate callout already holding a review row, after its last checkbox line; with no such
  callout they open a new review callout after the last gate callout (or after the section's last non-blank line
  when none is left), preceded by one blank line.

  Args:
    section: Lines of the `# Gates` section, edited in place.
    added: Names of the documents to hang a row for, in order.
    lang: Authoring language of the note.
    tail: The body's lines after the section, consulted for what follows the new callout.
  """
  rows = [ GateRow(label = f"{GateCheckbox.REVIEW_PREFIX}{file}", ticked = False, hint = (), line = -1)
           for file in added ]

  # an existing review callout takes the rows below its last checkbox
  for start, end in _find_all_gate_spans(section):
    existing = _parse_callout_rows(section, start, end)
    if any(_parse_review_file(row) is not None for row in existing) and existing[-1].line != start:
      at = existing[-1].line + 1
      section[at:at] = [ f"{_UNTICKED_BOX} {row.label}" for row in rows ]
      return

  # otherwise a new review callout goes after the last gate callout, or after the section's last written line
  spans = _find_all_gate_spans(section)
  insert_at = spans[-1][1] if spans else max(idx for idx, line in enumerate(section) if line.strip()) + 1

  # the new callout opens on a blank line, and one more closes it when a written line follows it
  chunk = [ "", *render_gate_callout(GateCheckbox.REVIEW_VERB, rows, lang) ]
  if not _is_blank_or_absent(section + tail, insert_at):
    chunk.append("")
  section[insert_at:insert_at] = chunk


def reconcile(body: str, wanted: list[str], lang: str, *,
              stages: dict[str, str] | None = None) -> tuple[str, dict[str, list[str]]]:
  """
  Bring the `Review <doc>` rows of a folder note in line with the documents owed one.

  Only the `Review <doc>` rows of the `# Gates` section change. Every unticked review row whose document is not
  wanted is removed, and a gate callout left without a row goes whole; a ticked review row is never removed. Each
  wanted document without a row gets one, joining the existing review callout or opening a new one. With `stages`
  given, the whole section is then laid out into its row groups by `layout_section`.

  Guarantees:
    - Without `stages`, every line other than a removed review checkbox line, a callout emptied by the removal and
      the lines hanging new rows is carried over byte for byte; with `stages`, every line outside the `# Gates`
      section is.
    - Repeating the call with the same `wanted` and `stages` changes nothing; an up-to-date note comes back
      identical.

  Args:
    body: Folder-note body text, after the frontmatter.
    wanted: Names of the documents owed a row, as produced by `read_review_candidates`.
    lang: Authoring language of the note.
    stages: Document name to `spec_stage`, as `read_review_stages` reads them, or `None` to leave the layout alone.

  Returns:
    The rewritten body and a summary with the keys `added`, `removed` and `kept`. `added` lists the new rows'
    documents in `wanted` order with duplicates dropped; `removed` and `kept` list documents in the order the note
    carries their rows, `kept` covering every review row that stays.

  Raises:
    ValueError: If the body has no `# Gates` H1 section.
  """

  # Contract:
  # Without `stages`, every line other than a removed `Review <doc>` checkbox line, a gate callout the removal left
  # empty and the lines that hang new rows is carried over byte for byte, including other rows, the halt callout,
  # the protected tag, the explainer and the other sections; with `stages`, every line outside the `# Gates` section
  # is.

  # Contract:
  # Repeating the call with the same `wanted` and `stages` changes nothing: an up-to-date note comes back identical,
  # so the caller can leave its bytes and modification time alone.

  lines = body.split(_LF)

  # guard: without the section there is nowhere to hang a row
  if (span := _find_gates_span(lines)) is None:
    raise ValueError(f"the note body has no {Section.GATES} section")

  # the section runs from its heading to the next H1, or to the end of the body
  head, end = span
  section, tail = lines[head:end], lines[end:]

  # sort the existing review rows into the ones that stay and the un-ticked ones nobody wants any more
  kept: list[str] = []
  removed: list[str] = []
  doomed: set[int] = set()
  for row in parse_gate_rows(section):
    file = _parse_review_file(row)

    # guard: a launch row that is not a review row is never touched
    if file is None:
      continue

    # a ticked row, or one still owed, stays where it is; any other un-ticked row is doomed
    if row.ticked or file in wanted:
      kept.append(file)
    else:
      removed.append(file)
      doomed.add(row.line)

  # drop the doomed rows, and every callout they leave empty
  _drop_rows(section, doomed, tail)

  # every wanted document without a row yet, each named once, in the order it is wanted
  added = [ file for file in dict.fromkeys(wanted) if file not in kept ]
  if added:
    _hang_review_rows(section, added, lang, tail)

  # with the stages known, the whole section is laid out into its groups
  if stages is not None:
    section = layout_section(section, stages, lang)

  # re-join the untouched head, the rewritten section and the untouched rest
  return _LF.join([ *lines[:head], *section, *tail ]), { _ADDED: added, _REMOVED: removed, _KEPT: kept }


def main(argv: list[str]) -> int:
  """
  Bring the `Review <doc>` launch rows of a spec folder note in line with the documents it owes one.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Notes:
    - Rewrites the note on disk only when its body changed; an up-to-date note keeps its bytes and modification time.
    - Prints a JSON summary on stdout with the keys `added`, `removed` and `kept` (lists of document names) and
      `changed` (whether the note was rewritten).

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the path names no file, the note lies outside the repository root, the file
    has no `spec_role` in its frontmatter, or its body has no `# Gates` section.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs review-rows")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note", type = Path)
  note: Path = parser.parse_args(argv).note.resolve()

  # guard: a path that names no file has no frontmatter to read
  if not note.is_file():
    sys.stderr.write(f"no such note: {note}\n")
    return 2

  # the root comes from the daemon-exported env var, else from the process cwd
  repo = scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))

  # guard: a note outside the resolved root is a caller error -- its owning product cannot be resolved
  if not note.is_relative_to(repo):
    sys.stderr.write(f"note lies outside the repository root {repo}: {note}\n")
    return 2

  # the note's whole text, its frontmatter parsed off the front
  text = note.read_text(encoding = _ENCODING)
  note_fm, fm_end = spec_frontmatter.parse(text)

  # guard: a file without a coordination role is no folder note and owes no rows
  if not note_fm.get(SpecKey.ROLE, "").strip():
    sys.stderr.write(f"not a spec folder note (no {SpecKey.ROLE}): {note}\n")
    return 2

  # the rows the note owes, reconciled against the rows it already carries; only the reconciler's missing
  # `# Gates` refusal marks a non-note -- every other failure propagates as itself
  # waiver: `wanted` and `lang` stay out of the `try` so a candidate failure is never reported as a missing `# Gates`
  wanted = read_review_candidates(repo, note)
  stages = read_review_stages(repo, note)
  lang = note_explainers.lang_for_note(note)
  try:
    body, summary = reconcile(text[fm_end:], wanted, lang, stages = stages)
  except ValueError as error:
    sys.stderr.write(f"not a spec folder note ({error}): {note}\n")
    return 2

  # write only a body that moved, so an up-to-date note keeps its bytes and its mtime
  changed = body != text[fm_end:]
  if changed:
    spec_paths.write_text_atomic(note, text[:fm_end] + body)
  print(json.dumps({ **summary, _CHANGED: changed }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
