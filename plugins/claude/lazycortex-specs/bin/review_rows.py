"""
Logic behind the `lazycortex-specs review-rows <note>` verb.

The verb keeps the `Review <doc>` checkbox blocks in a spec folder note's `# Gates` section in line with the
documents the note owes one.
"""
from __future__ import annotations

import argparse
import json
import os
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
    LEVEL_ROLES, GateCheckbox, LevelDoc, Section, SpecHaltKey, SpecKey, Stage, StageKey,
)


_ENCODING = "utf-8"
_MD_SUFFIX = ".md"
_LF = "\n"
_QUOTE = ">"
_CALLOUT_OPEN = "> [!"
_GATE_OPEN = f"{_QUOTE} {GateCheckbox.GATE_CALLOUT_MARK} "
_TICKED_BOX = "> - [x]"
_UNTICKED_BOX = "> - [ ]"
_H1_PREFIX = "# "
_ADDED = "added"
_REMOVED = "removed"
_KEPT = "kept"
_CHANGED = "changed"
# The env var the daemon exports for every subprocess it spawns
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class GateBlock:
  """
  One `[!gate]` callout block of a folder note's `# Gates` section.

  Attributes:
    label: Text after the gate mark on the block's first line.
    ticked: Whether the block's checkbox is ticked (`- [x]`).
    lines: The block's own lines, callout line first.
  """

  # The text after the gate callout mark on the block's first line
  label: str

  # Whether the block's checkbox carries a tick
  ticked: bool

  # The block's own lines, the callout line first
  lines: list[str]


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
  Decide whether a document is owed a review checkbox block.

  A document is owed one when its declared document type takes part in review and is not append-only, and the
  document is neither already under review nor at `spec_stage: cancelled`, since a cancelled document's work is
  abandoned. An append-only report enters review only when its writing job finishes, never by an operator's tick.

  Args:
    repo: Repository root.
    doc: Path of the document to test.
    product: Key of the owning product whose own document types extend the shipped registry, or `None`.

  Returns:
    `True` when the document is owed a block, `False` for an untyped document, an undeclared or non-reviewed type,
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

  # a document already in the loop needs no block to enter it
  return not flip_gate.is_true(fm_values, SpecKey.REVIEW_ACTIVE)


def read_review_candidates(repo: Path, note: Path) -> list[str]:
  """
  List the documents a spec folder note owes a `Review <doc>` checkbox block.

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
  # ui-design, tech), on an asset note in alphabetical order. Callers append new blocks in exactly this order, so
  # it never changes with how the scope is listed.

  # Contract:
  # A halted note yields an empty list. An untyped document, an undeclared or non-reviewed type, an append-only
  # type, a cancelled document and a document already under review are never listed.

  # Domain(spec.notes):
  # # Halted note owes no review checkbox
  # A halted note owes no open-review checkbox block, whether it is an asset note or a level note (a product's
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

  # keep the scope's order, dropping every document that is not owed a block
  return [
      # waiver: the specs `bin/` modules are one flat sibling set sharing this single private role reader, which
      # has no public counterpart in `flip_gate` or `spec_keys`
      # pylint: disable-next=protected-access
      name for name in _find_all_scope_files(note, flip_gate._note_role(note_fm))
      if _is_owed(repo, note.parent / name, product)
  ]


def _find_all_gate_spans(section_lines: list[str]) -> list[tuple[int, int]]:
  """
  Locate the gate blocks of a section.

  Block boundaries follow the same rules as `parse_gate_blocks`.

  Args:
    section_lines: Lines of the `# Gates` section.

  Returns:
    The `(start, end)` half-open line index ranges of the gate blocks, in section order.
  """
  spans: list[tuple[int, int]] = []
  pos = 0
  while pos < len(section_lines):
    # guard: a line that opens no gate callout belongs to no block
    if not section_lines[pos].startswith(_GATE_OPEN):
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


def parse_gate_blocks(section_lines: list[str]) -> list[GateBlock]:
  """
  Split a `# Gates` section into its gate blocks.

  A block runs from its `> [!gate] ` callout line over the consecutive `>` lines, ending before the next non-quoted
  line or the next callout (`> [!`). A halt `[!failure]` callout placed flush after a block is therefore never
  absorbed into it.

  Args:
    section_lines: Lines of the `# Gates` section.

  Returns:
    One `GateBlock` per gate callout, in section order.
  """
  # one entry per gate callout, its tick read off any checkbox line of the block
  return [
      GateBlock(
          label = section_lines[start][len(_GATE_OPEN):].strip(),
          ticked = any(line.lower().startswith(_TICKED_BOX) for line in section_lines[start:end]),
          lines = section_lines[start:end],
      )
      for start, end in _find_all_gate_spans(section_lines)
  ]


def render_review_block(file: str, lang: str) -> list[str]:
  """
  Render the gate block that offers a review of one document.

  The block is the four lines `> [!gate] Review <file>`, `> - [ ] Review <file>`, `>` and `> <helper>`, where the
  helper is the review explainer in the given language, falling back to English for an unknown language.

  Args:
    file: Name of the document the block offers to review.
    lang: Authoring language of the note.

  Returns:
    The four block lines, callout line first.
  """
  # an unknown language falls back to the English helper
  helper = note_explainers.REVIEW_HELPER.get(lang) or note_explainers.REVIEW_HELPER[note_explainers.LANG_EN]
  label = f"{GateCheckbox.REVIEW_PREFIX}{file}"
  return [ f"{_GATE_OPEN}{label}", f"{_UNTICKED_BOX} {label}", _QUOTE, f"{_QUOTE} {helper.format(file = file)}" ]


def _parse_review_file(block: GateBlock) -> str | None:
  """
  Name the document a gate block offers to review.

  Args:
    block: The gate block to inspect.

  Returns:
    The document name a `Review <doc>` block names, or `None` for any other gate block.
  """
  # guard: a gate block whose label lacks the review prefix names no document
  if not block.label.startswith(GateCheckbox.REVIEW_PREFIX):
    return None

  # a review block names its document after the prefix
  return block.label[len(GateCheckbox.REVIEW_PREFIX):]


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


def reconcile(body: str, wanted: list[str], lang: str) -> tuple[str, dict[str, list[str]]]:
  """
  Bring the `Review <doc>` gate blocks of a folder note in line with the documents owed one.

  Only the `Review <doc>` blocks of the `# Gates` section change. Every unticked review block whose document is not
  wanted is removed so that no doubled blank line is left behind: the blank line before the block goes with it only
  when nothing but a blank line or the end of the body follows the block, and stays when text or a callout, such as
  a halt callout, follows it flush. A ticked review block is never removed. One block is appended per wanted
  document that has none yet, after the last remaining gate block (or after the section's last non-blank line when
  none remains), each preceded by one blank line.

  Guarantees:
    - Every line outside a `Review <doc>` gate block, including other gate blocks, the halt callout, the protected
      tag, the explainer and other sections, is carried over byte for byte.
    - Repeating the call with the same `wanted` changes nothing; an up-to-date note comes back identical.

  Args:
    body: Folder-note body text, after the frontmatter.
    wanted: Names of the documents owed a block, as produced by `read_review_candidates`.
    lang: Authoring language of the note.

  Returns:
    The rewritten body and a summary with the keys `added`, `removed` and `kept`. `added` lists the new blocks'
    documents in `wanted` order with duplicates dropped; `removed` and `kept` list documents in the order the note
    carries their blocks, `kept` covering every review block that stays.

  Raises:
    ValueError: If the body has no `# Gates` H1 section.
  """

  # Contract:
  # Every line that is not part of a `Review <doc>` gate block, including other gate blocks, the halt callout, the
  # protected tag, the explainer and the other sections, is carried over byte for byte.

  # Contract:
  # Repeating the call with the same `wanted` changes nothing: an up-to-date note comes back identical, so the
  # caller can leave its bytes and modification time alone.

  lines = body.split(_LF)

  # guard: without the section there is nowhere to hang a block
  if (head := next(( idx for idx, line in enumerate(lines) if line.strip() == Section.GATES ), None)) is None:
    raise ValueError(f"the note body has no {Section.GATES} section")

  # the section runs from its heading to the next H1, or to the end of the body
  end = next(( idx for idx in range(head + 1, len(lines)) if lines[idx].startswith(_H1_PREFIX) ), len(lines))
  section, tail = lines[head:end], lines[end:]

  # sort the existing review blocks into the ones that stay and the un-ticked ones nobody wants any more
  kept: list[str] = []
  removed: list[str] = []
  doomed: list[tuple[int, int]] = []
  for span, block in zip(_find_all_gate_spans(section), parse_gate_blocks(section), strict = True):
    file = _parse_review_file(block)

    # guard: a launch block that is not a review block is never touched
    if file is None:
      continue

    # a ticked block, or one still owed, stays where it is; any other un-ticked block is doomed
    if block.ticked or file in wanted:
      kept.append(file)
    else:
      removed.append(file)
      doomed.append(span)

  # drop each doomed block from the back, folding the blank line that separated it when nothing follows it
  for start, stop in reversed(doomed):
    del section[start:stop]
    if start > 0 and not section[start - 1].strip() and _is_blank_or_absent(section + tail, start):
      del section[start - 1]

  # every wanted document without a block yet, each named once, in the order it is wanted
  added = [ file for file in dict.fromkeys(wanted) if file not in kept ]
  if added:
    # new blocks go after the last block left, or after the section's last written line when none is left
    spans = _find_all_gate_spans(section)
    insert_at = spans[-1][1] if spans else max(idx for idx, line in enumerate(section) if line.strip()) + 1

    # each new block opens on a blank line, and one more closes the run when a written line follows it
    chunk = [ row for file in added for row in [ "", *render_review_block(file, lang) ] ]
    if not _is_blank_or_absent(section + tail, insert_at):
      chunk.append("")
    section[insert_at:insert_at] = chunk

  # re-join the untouched head, the rewritten section and the untouched rest
  return _LF.join([ *lines[:head], *section, *tail ]), { _ADDED: added, _REMOVED: removed, _KEPT: kept }


def main(argv: list[str]) -> int:
  """
  Bring the `Review <doc>` gate blocks of a spec folder note in line with the documents it owes one.

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

  # the rows the note owes, reconciled against the blocks it already carries; only the reconciler's missing
  # `# Gates` refusal marks a non-note -- every other failure propagates as itself
  # waiver: `wanted` and `lang` stay out of the `try` so a candidate failure is never reported as a missing `# Gates`
  wanted = read_review_candidates(repo, note)
  lang = note_explainers.lang_for_note(note)
  try:
    body, summary = reconcile(text[fm_end:], wanted, lang)
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
