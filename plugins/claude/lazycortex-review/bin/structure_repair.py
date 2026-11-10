from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import edit_markup as _edit_markup  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import ParseError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import Tag  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# A line that continues a frontmatter value: indented, or a column-0 list item
_YAML_CONTINUATION_RE = re.compile(r"^(?:[ \t]+\S|-(?:[ \t]|$))")

# A heading line of any level, which ends a paragraph
_HEADING_RE = re.compile(r"^#{1,6} ")

# An H1 heading line, the boundary of a protected section
_H1_RE = re.compile(r"^# ")

# The owner name review's own protected section carries; a section with any other owner is foreign
_OWN_OWNER = _body.protected_section_owner(Tag.HISTORY)

# The heading of the review history section, the fallback boundary of an unclosed fence
_HISTORY_HEADING = "# History"

# An inline code span, whose content never carries an edit mark
_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")

# The opening marks per edit-marker style that a fold leaves behind when they have no partner
_SPAN_OPENERS: dict[str, tuple[str, ...]] = {
    "simple": ( "~~", "%%", "==" ),
    "criticmarkup": ( "{++", "{--", "{~~", "{>>", "{==" ),
    "html": ( "<ins>", "<del>", "<mark>", "<!--" ),
    "diff": (),
}

# The first Private Use Area code point; each mark occurrence is tagged with its own code point from here on
_SENTINEL_BASE = 0xE000
# limit: a paragraph with more mark occurrences than the Basic Multilingual Plane's Private Use Area holds is left
# to the doctor, extend to the supplementary planes if one ever enters review
_SENTINEL_COUNT = 0x1900

# The frontmatter delimiter line, without its line ending.
_FRONTMATTER_FENCE = "---"
# The byte order mark (U+FEFF) a document may open with, kept ahead of an inserted opening delimiter.
_BOM = "﻿"

# The longest excerpt a defect carries
_EXCERPT_LIMIT = 120

# The CLI's exit codes
_EXIT_OK = 0
_EXIT_MISSING = 1
_EXIT_USAGE = 2
_EXIT_UNCLASSIFIED = 3

# The CLI's program name and argument spellings
_PROG = "lazy-review repair-structure"
_ARG_FILE = "file"
_ARG_CHECK = "--check"
_ARG_REPO = "--repo"
_STORE_TRUE = "store_true"


# ----------------------------------------------------------------------------------------
class RepairState(StrEnum):
  """
  The closed set of status words a repair pass reports.

  Attributes:
    CLEAN: Nothing was broken.
    REPAIRED: Every break was repaired.
    UNCLASSIFIED: A break needs a guess, so nothing was repaired.
  """

  # Nothing was broken.
  CLEAN = "clean"
  # Every break was repaired.
  REPAIRED = "repaired"
  # A break needs a guess, so nothing was repaired.
  UNCLASSIFIED = "unclassified"


# ----------------------------------------------------------------------------------------
class DefectKind(StrEnum):
  """
  The closed set of structural breaks the detector reports.

  Attributes:
    FENCE_UNCLOSED: A fenced code block that runs to the end of the document.
    FRONTMATTER_UNCLOSED: An opening frontmatter delimiter with no closing one.
    FRONTMATTER_UNOPENED: Frontmatter keys and a closing delimiter with no opening one.
    FRONTMATTER_MISSING: No frontmatter block at all.
    EDIT_SPAN_UNCLOSED: An inline edit-annotation mark with no partner in its paragraph.
  """

  # A fenced code block that runs to the end of the document.
  FENCE_UNCLOSED = "fence_unclosed"
  # An opening frontmatter delimiter with no closing one.
  FRONTMATTER_UNCLOSED = "frontmatter_unclosed"
  # Frontmatter keys and a closing delimiter with no opening one.
  FRONTMATTER_UNOPENED = "frontmatter_unopened"
  # No frontmatter block at all.
  FRONTMATTER_MISSING = "frontmatter_missing"
  # An inline edit-annotation mark with no partner in its paragraph.
  EDIT_SPAN_UNCLOSED = "edit_span_unclosed"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class Defect:
  """
  One structural break found in a document.

  Attributes:
    kind: What broke.
    line: The 1-based line the break is reported at.
    excerpt: The text of that line.
    repairable: Whether the break is repaired without a guess.
  """

  # What broke.
  kind: DefectKind
  # The 1-based line the break is reported at.
  line: int
  # The text of that line.
  excerpt: str
  # Whether the break is repaired without a guess.
  repairable: bool


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class RepairResult:
  """
  The outcome of one repair pass.

  Attributes:
    status: `clean`, `repaired`, or `unclassified`.
    text: The repaired document, or the input unchanged.
    repaired: The breaks the pass repaired.
    unclassified: The breaks the pass could not repair without a guess.
  """

  # `clean`, `repaired`, or `unclassified`.
  status: RepairState
  # The repaired document, or the input unchanged.
  text: str
  # The breaks the pass repaired.
  repaired: list[Defect]
  # The breaks the pass could not repair without a guess.
  unclassified: list[Defect]


def _is_yaml_like(line: str) -> bool:
  """
  Report whether a line reads as part of a frontmatter block.

  Args:
    line: One document line without its line ending.

  Returns:
    True for a top-level key line, an indented continuation, or a list item; False otherwise.
  """
  # a key line, an indented continuation, or a list item reads as frontmatter
  return _fm.is_top_level_key_line(line) or bool(_YAML_CONTINUATION_RE.match(line))


def _format_excerpt(line: str) -> str:
  """
  Shorten a document line to a readable excerpt.

  Args:
    line: One document line, with or without its line ending.

  Returns:
    The line without its ending, cut to the longest length a defect excerpt carries.
  """
  # one line without its ending, cut to a readable length
  return line.rstrip("\r\n")[:_EXCERPT_LIMIT]


def _detect_frontmatter(lines: list[str]) -> tuple[list[Defect], int]:
  """
  Find the structural break in a document's frontmatter block, if any.

  Args:
    lines: The document lines, each with its line ending.

  Returns:
    The frontmatter defects, and the 0-based index of the first body line after the frontmatter block (0 when the
    document has no usable block).
  """
  text = "".join(lines)

  # a well-formed block, or an opening delimiter left without its partner
  try:
    span = _fm.find_fences(text)
  except ParseError:
    # the block runs from the opener over its key lines and stops at the first blank or non-frontmatter line
    end = 1
    while end < len(lines) and lines[end].strip() and _is_yaml_like(lines[end].rstrip("\r\n")):
      end += 1
    excerpt = _format_excerpt(lines[end]) if end < len(lines) else ""

    # the missing closer belongs on that stopping line; with no key line after the opener there is no block to close
    return [ Defect(DefectKind.FRONTMATTER_UNCLOSED, end + 1, excerpt, end > 1) ], 0

  # a whole block: the body starts on the line after its closing delimiter
  if span is not None:
    return [], text.count("\n", 0, span[2])

  # leading key lines closed by a delimiter are a block that lost its opening line
  first = lines[0].removeprefix(_BOM).rstrip("\r\n") if lines else ""
  end = 0
  if _fm.is_top_level_key_line(first):
    end = 1
    while end < len(lines) and _is_yaml_like(lines[end].rstrip("\r\n")):
      end += 1

  # a run of key lines closed by a delimiter is the one shape repaired without a guess
  if end and end < len(lines) and lines[end].rstrip("\r\n").rstrip(" \t") == _FRONTMATTER_FENCE:
    return [ Defect(DefectKind.FRONTMATTER_UNOPENED, 1, _format_excerpt(first), True) ], end + 1

  # anything else at the top is a document with no frontmatter to restore
  return [ Defect(DefectKind.FRONTMATTER_MISSING, 1, _format_excerpt(first), False) ], 0


def _detect_fence(lines: list[str], start: int) -> list[Defect]:
  """
  Find a fenced code block that is never closed.

  Args:
    lines: The document lines, each with its line ending.
    start: The 0-based index of the first line to inspect.

  Returns:
    A single repairable unclosed-fence defect reported at the opening line, or an empty list when every fence is
    closed.
  """
  chunks = _parser.split_fenced("".join(lines[start:]))

  # every fence is closed, so there is nothing to report
  if not chunks or not chunks[-1].fenced or chunks[-1].closed:
    return []

  # the opener sits after every line of the earlier chunks, counted from `start`, as a 1-based line number
  opener = chunks[-1].text.splitlines()[0]
  line = start + sum(chunk.text.count("\n") for chunk in chunks[:-1]) + 1
  return [ Defect(DefectKind.FENCE_UNCLOSED, line, _format_excerpt(opener), True) ]


def _split_paragraphs(lines: list[str], start: int) -> list[tuple[int, list[str]]]:
  """
  Split the document body into paragraphs outside fenced code blocks.

  Args:
    lines: The document lines, each with its line ending.
    start: The 0-based index of the first body line.

  Returns:
    Pairs of the 0-based first line index and the lines of each paragraph; a blank line and a heading line each
    form a unit of their own, and fenced lines appear in no unit.
  """
  units: list[tuple[int, list[str]]] = []
  offset = start

  # a paragraph ends at a blank line and at a heading line; fenced lines are never read
  for chunk in _parser.split_fenced("".join(lines[start:])):
    rows = chunk.text.splitlines()
    if not chunk.fenced:
      para: list[str] = []
      first = offset
      for idx, row in enumerate(rows):
        # a blank or heading line closes the open paragraph and forms a unit of its own
        if not row.strip() or _HEADING_RE.match(row):
          if para:
            units.append(( first, para ))
          units.append(( offset + idx, [ row ] ))
          para = []
          continue

        # the first row of a new paragraph records where that paragraph starts
        if not para:
          first = offset + idx
        para.append(row)

      # a paragraph still open at the chunk's end is closed there
      if para:
        units.append(( first, para ))

    # the line offset advances over every chunk, fenced ones included, so later indices stay absolute
    offset += len(rows)

  # the units in document order
  return units


def _foreign_lines(lines: list[str], units: list[tuple[int, list[str]]]) -> set[int]:
  """
  Find the lines that belong to a section another plugin owns.

  Args:
    lines: The document lines, each with its line ending.
    units: The body's paragraph units, each the 0-based first line index paired with the lines of that unit.

  Returns:
    The 0-based indices of every line, heading included, of each protected H1 section whose owner is not review.
  """
  heads = [ first for first, rows in units if _H1_RE.match(rows[0]) ]
  foreign: set[int] = set()

  # a section runs from its H1 to the next one; the owner is read from the text below its heading
  for pos, head in enumerate(heads):
    end = heads[pos + 1] if pos + 1 < len(heads) else len(lines)
    owner = _body.protected_section_owner("".join(lines[head + 1:end]))
    if owner is not None and owner != _OWN_OWNER:
      foreign.update(range(head, end))
  return foreign


def _left_marks(para: list[str], style: str) -> list[str]:
  """
  List the opening marks a paragraph still holds once its paired spans are folded.

  Args:
    para: The paragraph lines, without line endings.
    style: The edit-marker style whose marks are looked for.

  Returns:
    The opening marks of the style found in the folded paragraph, with inline code ignored.
  """
  # inline code never carries a mark, and a mark the fold leaves behind has no partner
  plain = "\n".join(_INLINE_CODE_RE.sub("", row) for row in para)
  folded = _edit_markup.strip_markers(plain, style = style)
  return [ token for token in _SPAN_OPENERS[style] if token in folded ]


def _plain_paragraph(para: list[str]) -> tuple[str, list[tuple[int, int] | None]]:
  """
  Read a paragraph with inline code removed, keeping where each remaining character came from.

  Args:
    para: The paragraph lines, without line endings.

  Returns:
    The paragraph lines joined by newlines with inline code removed, and for each of its characters the row and
    column it came from (`None` for a joining newline).
  """
  chars: list[str] = []
  where: list[tuple[int, int] | None] = []

  # every character outside an inline code span is kept, with its row and column
  for row_idx, row in enumerate(para):
    if row_idx:
      chars.append("\n")
      where.append(None)
    cursor = 0
    for match in [ *_INLINE_CODE_RE.finditer(row), None ]:
      stop = match.start() if match else len(row)
      chars.extend(row[cursor:stop])
      where.extend(( row_idx, col ) for col in range(cursor, stop))
      cursor = match.end() if match else len(row)
  return "".join(chars), where


def _lone_mark_cells(para: list[str], style: str) -> set[tuple[int, int]]:
  """
  Locate the characters of the opening marks a paragraph's fold leaves without a partner.

  Args:
    para: The paragraph lines, without line endings.
    style: The edit-marker style whose marks are looked for.

  Returns:
    The row and column of every character of each unpartnered opening mark, with inline code ignored; empty when no
    occurrence can be pinned.
  """
  plain, where = _plain_paragraph(para)

  # every opening-mark occurrence, left to right, never two over the same characters
  spots: list[tuple[int, str]] = []
  taken: set[int] = set()
  for token in _SPAN_OPENERS[style]:
    pos = plain.find(token)
    while pos != -1:
      if not taken.intersection(range(pos, pos + len(token))):
        spots.append(( pos, token ))
        taken.update(range(pos, pos + len(token)))
      pos = plain.find(token, pos + len(token))
  spots.sort()

  # the private-use characters that can tag an occurrence
  sentinels = range(_SENTINEL_BASE, _SENTINEL_BASE + _SENTINEL_COUNT)

  # guard: a sentinel must be a character the paragraph does not already hold, one per occurrence
  if len(spots) > _SENTINEL_COUNT or any(ord(char) in sentinels for char in plain):
    return set()

  # each occurrence is tagged with its own sentinel; the fold drops a paired mark and keeps a lone one beside its tag
  pieces: list[str] = []
  cursor = 0
  for idx, ( pos, _token ) in enumerate(spots):
    pieces.extend(( plain[cursor:pos], chr(_SENTINEL_BASE + idx) ))
    cursor = pos
  pieces.append(plain[cursor:])
  folded = _edit_markup.strip_markers("".join(pieces), style = style)

  # the characters of every occurrence the fold left standing beside its own sentinel
  cells: set[tuple[int, int]] = set()
  for idx, ( pos, token ) in enumerate(spots):
    if chr(_SENTINEL_BASE + idx) + token in folded:
      cells.update(cell for cell in where[pos:pos + len(token)] if cell is not None)
  return cells


def _drop_lone_marks(para: list[str], style: str) -> list[str] | None:
  """
  Remove the unpartnered opening marks of a paragraph and nothing else.

  Args:
    para: The paragraph lines, without line endings.
    style: The edit-marker style whose marks are looked for.

  Returns:
    The paragraph lines with only the characters of each unpartnered opening mark removed, or `None` when the marks
    cannot be pinned, or when removing them would leave a mark behind or change where the paragraph starts or ends.
  """
  cells = _lone_mark_cells(para, style)

  # guard: a mark that cannot be pinned is not removed at all
  if not cells:
    return None

  # every row with the characters of its lone marks taken out
  rows = [ "".join(char for col, char in enumerate(row) if ( row_idx, col ) not in cells)
           for row_idx, row in enumerate(para) ]

  # the result must read as the same single paragraph, with no mark left over
  units = _split_paragraphs([ row + "\n" for row in rows ], 0)
  if units != [ ( 0, rows ) ] or _left_marks(rows, style):
    return None
  return rows


def _detect_spans(lines: list[str], start: int, style: str) -> list[Defect]:
  """
  Find inline edit-annotation marks that have no partner in their paragraph.

  Args:
    lines: The document lines, each with its line ending.
    start: The 0-based index of the first body line.
    style: The edit-marker style whose marks are looked for.

  Returns:
    One defect per paragraph holding an unpartnered mark, reported at the line carrying it; it is repairable unless
    the paragraph sits in a section another plugin owns or its marks cannot be pinned and removed on their own.
  """
  defects: list[Defect] = []

  # guard: a style with no inline marks has no span to leave open
  if not _SPAN_OPENERS[style]:
    return defects

  # the body's paragraphs, and the lines that sit in a section another plugin owns
  units = _split_paragraphs(lines, start)
  foreign = _foreign_lines(lines, units)

  # a mark left behind once the paragraph's paired spans are folded has no partner
  for first, para in units:
    left = _left_marks(para, style)

    # guard: a paragraph whose every mark has its partner reports nothing
    if not left:
      continue

    # the break is reported at the paragraph's first line still carrying an unpartnered mark
    plain = [ _INLINE_CODE_RE.sub("", row) for row in para ]
    idx = next((pos for pos, row in enumerate(plain) if any(token in row for token in left)), 0)
    repairable = first not in foreign and _drop_lone_marks(para, style) is not None
    defects.append(Defect(DefectKind.EDIT_SPAN_UNCLOSED, first + idx + 1, _format_excerpt(para[idx]), repairable))
  return defects


def _remove_lone_marks(text: str, style: str) -> str:
  """
  Remove every unpartnered opening mark outside sections another plugin owns.

  Args:
    text: The full document text.
    style: The edit-marker style whose marks are looked for.

  Returns:
    The document with the characters of each removable unpartnered mark gone; every other byte, line endings and
    sections another plugin owns included, is kept.
  """
  lines = text.splitlines(keepends = True)
  _defects, start = _detect_frontmatter(lines)
  units = _split_paragraphs(lines, start)
  foreign = _foreign_lines(lines, units)

  # each paragraph outside a foreign section loses only its lone marks, every line keeping its own ending
  for first, para in units:
    rows = None if first in foreign or not _left_marks(para, style) else _drop_lone_marks(para, style)
    for offset, ( old, new ) in enumerate(zip(para, rows or para, strict = True)):
      lines[first + offset] = new + lines[first + offset][len(old):]
  return "".join(lines)


def detect(text: str, *, style: str) -> list[Defect]:
  """
  Report the structural breaks of a review markdown document.

  Reports each structural break with its position and whether it can be repaired without a guess.

  Args:
    text: The full document text.
    style: The edit-marker style the document uses.

  Returns:
    The defects found, frontmatter first, then fences, then edit-annotation marks; empty for a sound document.

  Raises:
    ValueError: If `style` is not a known edit-marker style.
  """
  # guard: an unknown style has no marks to look for
  if style not in _SPAN_OPENERS:
    raise ValueError(f"unknown edit_marker_style: {style!r}; supported: {', '.join(_SPAN_OPENERS)}")

  # frontmatter first: its end is where the body's fences and paragraphs start
  lines = text.splitlines(keepends = True)
  defects, body_start = _detect_frontmatter(lines)
  return [ *defects, *_detect_fence(lines, body_start), *_detect_spans(lines, body_start, style) ]


def _insert_line(text: str, line: int, content: str, *, newline: str) -> str:
  """
  Insert one line of content into a document.

  Args:
    text: The full document text.
    line: The 1-based line number the new line takes; a number past the last line appends at the end.
    content: The inserted line, without its line ending.
    newline: The line ending written after the inserted line.

  Returns:
    The document with the new line in place.
  """
  lines = text.splitlines(keepends = True)

  # past the last line the content is appended, on a line of its own
  if line > len(lines):
    return text + ("" if not text or text.endswith("\n") else newline) + content + newline

  # inside the text the content goes in at the start of the target line
  offset = sum(len(row) for row in lines[:line - 1])
  return text[:offset] + content + newline + text[offset:]


def _is_section_tag(line: str) -> bool:
  """
  Report whether a line is a section owner tag, either an expert tag or a protected-section tag.

  Args:
    line: The first line with content under an H1 heading.

  Returns:
    True when the line carries either kind of tag, False otherwise.
  """
  return line.strip().startswith(Tag.EXPERT_PREFIX) or _body.protected_section_owner(line) is not None


def _close_fence(text: str, newline: str) -> str:
  """
  Close the unclosed fenced code block of a document.

  Args:
    text: The full document text, which holds an unclosed fence.
    newline: The line ending written after the closing fence line.

  Returns:
    The document with a closing fence line inserted before the nearest later H1 heading that opens a review section,
    else before a `# History` heading, else at the end of the text. A `#` comment line inside the code never closes
    the fence.
  """
  lines = text.splitlines(keepends = True)
  rows = [ line.rstrip("\r\n") for line in lines ]
  after = range(_detect_fence(lines, 0)[0].line, len(rows))

  # the nearest H1 whose first line with content is an expert or a protected owner tag opens a review section
  sections = ( idx for idx in after if _H1_RE.match(rows[idx])
               and _is_section_tag(next((row for row in rows[idx + 1:] if row.strip()), "")) )
  history = ( idx for idx in after if rows[idx].rstrip() == _HISTORY_HEADING )
  boundary = next(sections, None)
  if boundary is None:
    boundary = next(history, None)

  # the closing line goes before that boundary, else at the end of the text
  if boundary is None:
    return _parser.close_open_fence(text, newline)
  offset = sum(len(row) for row in lines[:boundary])
  return _parser.close_open_fence(text[:offset], newline) + text[offset:]


def repair(text: str, *, style: str) -> RepairResult:
  """
  Repair the structural breaks of a review markdown document without guessing.

  Scope:
    Restores only structure the text itself determines, so no author prose is lost. A break that cannot be settled
    without a guess is left alone, and the document stays untouched.

  Guarantees:
    - An `unclassified` result carries the input unchanged and lists only the defects that are not repairable.
    - A `repaired` result holds no defect when detected again.

  Args:
    text: The full document text.
    style: The edit-marker style the document uses.

  Returns:
    The status, the resulting text, the defects repaired, and the defects left unclassified. A document with any
    break that needs a guess is reported `unclassified` and left untouched.

  Raises:
    ValueError: If `style` is not a known edit-marker style.
    RuntimeError: If the repaired text still has a structural defect.
  """

  # Contract:
  # An `unclassified` result carries the input unchanged and lists only the defects that are not repairable;
  # nothing is repaired in that case.

  # Contract:
  # A `repaired` result holds no structural defect when detected again, so a second call reports `clean`.

  # Domain(review.markup):
  # # Guess-free structural repair
  # A review document is repaired only where the intended structure follows from the text itself.
  # Repair adds lines and removes nothing but the characters of an edit-annotation mark that has no partner,
  # so no author prose can be lost.
  # An unclosed code fence is closed before the nearest later review section: a top-level heading whose first line
  # with content is an expert's or another plugin's ownership tag.
  # Failing that, it is closed before the review history section's heading; failing that, at the end of the text.
  # An ordinary heading-looking line inside the code, such as a `# comment` in a shell or Python block, never closes
  # the fence. Only a section the review document is built from marks where the runaway code must have ended;
  # closing at the first heading-looking line cut code at its own comments and turned the rest into prose.
  # Such a fence is therefore always repaired.
  # Frontmatter that lost its opening delimiter is restored only when the text opens with a run of key lines
  # closed by `---`.
  # Frontmatter whose opening delimiter has no closer is closed at the first blank or non-frontmatter line,
  # and only when at least one key line follows the opener.
  # An edit-annotation opening mark with no partner in its paragraph is repaired by removing that mark and only
  # its characters. A lone mark is literal text, never the start of a span, so the paragraph around it stays
  # byte for byte.
  # The span is not closed instead, because closing it at a guessed spot would pull foreign text into the edit.
  # A mark inside a section that another plugin protects is never touched, and such a document stays unrepaired.
  # A document with no frontmatter at all is never repaired, because there is nothing to restore it from.
  # One break that needs a guess leaves the whole document untouched, so a partial repair never hides the rest.

  found = detect(text, style = style)

  # nothing broken comes back as it stands, with nothing written
  if not found:
    return RepairResult(RepairState.CLEAN, text, [], [])

  # one break that needs a guess leaves the whole document to the doctor, untouched
  if unclassified := [ defect for defect in found if not defect.repairable ]:
    return RepairResult(RepairState.UNCLASSIFIED, text, [], unclassified)

  # frontmatter first, then the fence, each by inserting one line in the document's own ending
  newline = _parser.line_ending(text)
  repaired = text
  for defect in found:
    if defect.kind == DefectKind.FRONTMATTER_UNCLOSED:
      repaired = _insert_line(repaired, defect.line, _FRONTMATTER_FENCE, newline = newline)
    elif defect.kind == DefectKind.FRONTMATTER_UNOPENED:
      bom = _BOM if repaired.startswith(_BOM) else ""
      repaired = bom + _FRONTMATTER_FENCE + newline + repaired[len(bom):]
  if any(defect.kind == DefectKind.FENCE_UNCLOSED for defect in found):
    repaired = _close_fence(repaired, newline)

  # a lone edit mark is removed last, character by character, so the lines around it keep every byte
  if any(defect.kind == DefectKind.EDIT_SPAN_UNCLOSED for defect in found):
    repaired = _remove_lone_marks(repaired, style)

  # guard: a repair that leaves a break behind is a bug, never a result
  if leftover := detect(repaired, style = style):
    raise RuntimeError(f"repair left structural defects behind: {leftover!r}")
  return RepairResult(RepairState.REPAIRED, repaired, found, [])


def _read_style(file_path: Path) -> str:
  """
  Resolve the edit-marker style that applies to a document.

  Args:
    file_path: The document file.

  Returns:
    The style the document pins, or the repository's configured style when the document's frontmatter cannot be
    parsed.
  """
  # the pin needs parseable frontmatter; a broken block falls back to the settings value
  try:
    return _finalize.read_document_edit_marker_style(file_path)
  except ParseError:
    return _finalize.read_settings_edit_marker_style(file_path)


def main(argv: list[str]) -> int:
  """
  Run the `repair-structure` verb on one review document.

  Scope:
    Prints one JSON line with the keys `status`, `changed`, `repaired` (kind and line per defect), and
    `unclassified` (kind, line, and excerpt per defect). The file is written only when the status is `repaired`
    and `--check` is absent; nothing is ever committed.

  Guarantees:
    - The file is written only for a `repaired` status without `--check`, and never for a `clean` or `unclassified`
      document.
    - Nothing is ever committed.

  Args:
    argv: Command-line arguments: the file, then optional `--check` and `--repo <root>`.

  Returns:
    Exit code: 0 for a clean or repaired document, 1 for a missing file, 2 for an unknown edit-marker style, 3 for
    a document with defects that need a guess.

  Raises:
    RuntimeError: If the repaired text still has a structural defect.
    UnicodeDecodeError: If the file bytes are not valid text.
  """

  # Contract:
  # The document file is written only when the status is `repaired` and `--check` is absent;
  # it is never written for a `clean` or `unclassified` document.

  # Contract:
  # The verb never commits; committing the written file is the caller's.

  # the verb's arguments: the document, an optional report-only switch, and the repo root
  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(_ARG_FILE)
  parser.add_argument(_ARG_CHECK, action = _STORE_TRUE)
  parser.add_argument(_ARG_REPO, default = ".")
  args = parser.parse_args(argv)

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has a structure to repair
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return _EXIT_MISSING

  # the repair works on the bytes as stored, so every inserted line takes the document's own ending
  text = _atomic_io.read_text(file_path)
  try:
    result = repair(text, style = _read_style(file_path))
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return _EXIT_USAGE

  # write only a real repair, and never under --check
  changed = result.status == RepairState.REPAIRED and not args.check
  if changed:
    _atomic_io.write_text_atomic(file_path, result.text)

  # the report names what was repaired and what was left for a human, one JSON object on stdout
  print(json.dumps({
      "status": result.status,
      "changed": changed,
      "repaired": [ { "kind": str(defect.kind), "line": defect.line } for defect in result.repaired ],
      "unclassified": [
          { "kind": str(defect.kind), "line": defect.line, "excerpt": defect.excerpt }
          for defect in result.unclassified
      ],
  }))

  # a defect left unclassified is a non-zero exit, so a caller cannot take the document for sound
  return _EXIT_UNCLASSIFIED if result.status == RepairState.UNCLASSIFIED else _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
