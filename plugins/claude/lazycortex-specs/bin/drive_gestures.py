from __future__ import annotations

import argparse
import json
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
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_commit  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import review_rows  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import Section  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The gesture names, each one a sub-command of the verb.
_MENU = "menu"
_TICK = "tick"
_ANSWER = "answer"
_COMMAND = "command"

# The verb's argument and flag names.
_ARG_GESTURE = "gesture"
_ARG_NOTE = "note"
_ARG_LABEL = "label"
_FLAG_QUESTION = "--question"
_FLAG_OPTION = "--option"
_FLAG_TEXT = "--text"

# The outcome words of a writing gesture.
_COMMITTED = "committed"
_NOOP = "noop"
_REFUSED = "refused"

# The verb's exit codes: done or nothing to do, and a refusal.
_EXIT_OK = 0
_EXIT_REFUSED = 1

# The encoding a note is read in.
_ENCODING = "utf-8"

# The frontmatter fence line and the H1 heading prefix that bound a note's sections.
_FENCE = "---"
_H1_PREFIX = "# "

# A quoted line, the opening of any callout, and the opening of a question callout.
_QUOTE = ">"
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!")
_QUESTION_HEAD_RE = re.compile(r"^>\s*\[!question\]\s*(.*)$")

# An option line of a checkbox-carrying callout, capturing its box mark and its text.
_OPTION_RE = re.compile(r"^>\s*-\s*\[([ xX])\]\s*(.*)$")

# An unticked checkbox's box and the box a tick puts in its place.
_UNTICKED = "[ ]"
_TICKED = "[x]"

# A tag token inside a callout's head line, which is no part of its title.
_TAG_RE = re.compile(r"(?:^|\s)#\S+")

# The closing lines that sign a question as one of the two coordinators' own.
_ATTRIBUTIONS = frozenset({ "> — spec.coordinator", "> — spec.catalog-coordinator" })

# The commit subjects of the three writing gestures.
_SUBJECT_TICK = "lazy-spec.drive: tick {label} on {slug}"
_SUBJECT_ANSWER = "lazy-spec.drive: answer {summary} on {slug}"
_SUBJECT_COMMAND = 'lazy-spec.drive: command "{text}" on {slug}'

# The refusal reasons.
_NO_NOTE = "no-such-note"
_NO_GATES = "no-gates-section"
_NO_CHECKBOX = "no-such-checkbox"
_NO_QUESTION = "no-such-question"
_NO_OPTION = "no-such-option"
_NO_COMMANDS = "no-commands-section"


# ----------------------------------------------------------------------------------------
class GestureRefusedError(Exception):
  """
  Refusal of a drive gesture before anything was written.

  Attributes:
    reason: The refusal word the verb reports, such as `no-such-note` or `no-such-option`.
  """
  def __init__(self, reason: str) -> None:
    """
    Create a refusal carrying the given reason word.

    Args:
      reason: The refusal word, one of `no-such-note`, `no-gates-section`, `no-such-checkbox`, `no-such-question`,
        `no-such-option` or `no-commands-section`.
    """
    # the exception's own message is the reason itself
    super().__init__(reason)

    # the reason, kept for the verb's JSON line
    self.reason: str = reason


def _body_start(lines: list[str]) -> int:
  """
  Return the index of the first body line after a leading frontmatter block.

  Args:
    lines: The note's lines.

  Returns:
    The index after the closing `---` line, `0` when the note has no frontmatter, or the line count when the block
    is never closed.
  """
  # guard: a note without frontmatter has its body from the first line
  if not lines or lines[0].rstrip() != _FENCE:
    return 0

  # the body starts after the closing fence; an unclosed block leaves no body
  for idx in range(1, len(lines)):
    if lines[idx].rstrip() == _FENCE:
      return idx + 1
  return len(lines)


def _find_section_span(lines: list[str], heading: str) -> tuple[int, int] | None:
  """
  Locate the H1 section opened by a heading, outside frontmatter and code fences.

  Args:
    lines: The note's lines.
    heading: The exact H1 heading line to find.

  Returns:
    The half-open line range of the section, excluding the heading line and ending at the next H1 outside a code
    fence, or `None` when the note has no such section.
  """
  start = _body_start(lines)
  fenced = spec_frontmatter.fenced_lines(lines)

  # the heading line itself, outside the frontmatter and every code fence
  head = next(( idx for idx in range(start, len(lines)) if not fenced[idx] and lines[idx].rstrip() == heading ),
              None)

  # guard: the note carries no such section
  if head is None:
    return None

  # the next H1 outside a fence closes the section; absent one, it runs to the end
  end = next(( idx for idx in range(head + 1, len(lines)) if not fenced[idx] and lines[idx].startswith(_H1_PREFIX) ),
             len(lines))
  return head + 1, end


def _find_all_question_spans(lines: list[str]) -> list[tuple[int, int]]:
  """
  Locate the question callouts in the note body that a coordinator signed.

  Args:
    lines: The note's lines.

  Returns:
    The half-open line range of each `[!question]` callout whose last substantive quoted line is a coordinator
    signature, in note order. A callout runs over consecutive quoted lines until another callout opens.
  """
  start = _body_start(lines)
  fenced = spec_frontmatter.fenced_lines(lines)
  spans: list[tuple[int, int]] = []
  pos = start
  while pos < len(lines):
    # a line that opens no question callout belongs to no question: scan on
    if fenced[pos] or not _QUESTION_HEAD_RE.match(lines[pos]):
      pos += 1
      continue

    # the callout runs over the consecutive quoted lines, stopping where another callout opens
    end = pos + 1
    while end < len(lines) and lines[end].startswith(_QUOTE) and not _CALLOUT_HEAD_RE.match(lines[end]):
      end += 1
    spans.append(( pos, end ))
    pos = end

  # only the questions a coordinator signed, the ones whose answer wakes it
  return [ span for span in spans if _is_attributed(lines[span[0]:span[1]]) ]


def _is_attributed(block: list[str]) -> bool:
  """
  Tell whether a callout block is signed by a coordinator.

  Args:
    block: The callout's lines.

  Returns:
    `True` when the block's last substantive quoted line, bare `>` lines skipped, is a coordinator signature.
  """
  # the last substantive quoted line, past any blank continuation, is the signature
  for line in reversed(block):
    stripped = line.strip()

    # a bare continuation line carries nothing to compare
    if stripped == _QUOTE:
      continue
    return stripped in _ATTRIBUTIONS
  return False


def _parse_summary(block: list[str]) -> str:
  """
  Extract the one-line summary of a question callout.

  Args:
    block: The question callout's lines, head line first.

  Returns:
    The head line's title with its tags dropped, or else the first body line that is neither blank nor an option,
    without its `>`; an empty string when there is none.
  """
  # the head line's own title, its tags dropped
  head = _QUESTION_HEAD_RE.match(block[0])
  title = _TAG_RE.sub("", head.group(1)).strip() if head is not None else ""

  # a titled head line is the summary itself
  if title:
    return title

  # otherwise the first body line that is neither blank nor an option
  for line in block[1:]:
    text = line[len(_QUOTE):].strip()

    # a blank line or an option is no summary: scan on
    if not text or _OPTION_RE.match(line):
      continue
    return text
  return ""


def _parse_options(block: list[str], offset: int) -> list[tuple[int, str, bool]]:
  """
  List the option lines of a callout block.

  Args:
    block: The callout's lines.
    offset: The note line index of the block's first line.

  Returns:
    One entry per `> - [ ]` or `> - [x]` line: its absolute line index, its text and whether it is ticked.
  """
  # every option line of the block, as its line index, its text and its tick
  found: list[tuple[int, str, bool]] = []
  for idx, line in enumerate(block):
    match = _OPTION_RE.match(line)
    if match is not None:
      found.append(( offset + idx, match.group(2).strip(), match.group(1) != " " ))
  return found


def _read(note: Path) -> list[str]:
  """
  Read a note's lines.

  Args:
    note: The note's path.

  Returns:
    The note's lines, split on LF.

  Raises:
    GestureRefusedError: With `no-such-note` when the note does not exist.
  """
  # guard: a gesture needs a note to act on
  if not note.is_file():
    raise GestureRefusedError(_NO_NOTE)
  return spec_frontmatter.split_lines(note.read_text(encoding = _ENCODING))


def build_menu(note: Path) -> dict[str, object]:
  """
  List what an operator can do on a coordination folder-note, without changing it.

  Args:
    note: The folder-note's path.

  Returns:
    A mapping with `checkboxes` (a label and tick for every launch row under `# Gates`), `questions` (the
    coordinator-signed questions, each with a 1-based index, its summary and its 1-based options carrying text and
    tick), and `commands_pending` (whether `# Coordinator commands` holds text that wakes the dispatcher).

  Raises:
    GestureRefusedError: With `no-such-note` when the note does not exist.
  """
  lines = _read(note)
  gates = _find_section_span(lines, Section.GATES)

  # the launch rows of `# Gates`, each with its tick
  rows = review_rows.parse_gate_rows(lines[gates[0]:gates[1]]) if gates is not None else []
  checkboxes = [ { "label": row.label, "ticked": row.ticked } for row in rows ]

  # the coordinator's questions, numbered from one, each option numbered from one
  questions = []
  for number, ( start, end ) in enumerate(_find_all_question_spans(lines), start = 1):
    block = lines[start:end]
    questions.append({
        "index": number, "summary": _parse_summary(block),
        "options": [ { "index": pos, "text": text, "ticked": ticked }
                     for pos, ( _idx, text, ticked ) in enumerate(_parse_options(block, start), start = 1) ],
    })

  # a pending command is the same non-empty section that wakes the dispatcher
  body = "\n".join(lines[_body_start(lines):])
  return { "checkboxes": checkboxes, "questions": questions,
           "commands_pending": bool(coordinator_dispatch.read_section_body(body, Section.COORD_COMMANDS)) }


def _tick_line(line: str) -> str:
  """
  Turn the first unticked checkbox on a line into a ticked one.

  Args:
    line: The line carrying the checkbox.

  Returns:
    The line with its first `[ ]` replaced by `[x]`.
  """
  # the first unticked box on the line becomes a ticked one, nothing else moves
  return line.replace(_UNTICKED, _TICKED, 1)


def tick(lines: list[str], label: str) -> list[str] | None:
  """
  Tick the checkbox of a named launch row.

  Both shapes a gate callout comes in are read: a one-row block, and a callout holding the checkboxes of every row
  of one verb.

  Args:
    lines: The note's lines.
    label: The label of the launch row under `# Gates`, as its checkbox line writes it.

  Returns:
    The edited lines, with only the row's own checkbox line ticked, or `None` when the row is already ticked.

  Raises:
    GestureRefusedError: With `no-gates-section` when the note has no `# Gates` section, or `no-such-checkbox` when
      no row carries the label or the row's callout carries no checkbox.
  """
  gates = _find_section_span(lines, Section.GATES)

  # guard: no `# Gates` section, no row to tick
  if gates is None:
    raise GestureRefusedError(_NO_GATES)

  # the lines of the `# Gates` section alone
  section = lines[gates[0]:gates[1]]

  # the first row under the asked label decides, whichever callout shape holds it
  for row in review_rows.parse_gate_rows(section):

    # a row under another label is not the one asked for: scan on
    if row.label != label:
      continue

    # guard: an already ticked row needs nothing
    if row.ticked:
      return None

    # guard: a row whose callout carries no checkbox has nothing to tick
    match = _OPTION_RE.match(section[row.line])
    if match is None or match.group(1) != " ":
      break

    # the row's own checkbox line takes the tick
    ticked = list(lines)
    ticked[gates[0] + row.line] = _tick_line(section[row.line])
    return ticked
  raise GestureRefusedError(_NO_CHECKBOX)


def answer(lines: list[str], question: int, option: int) -> tuple[list[str] | None, str]:
  """
  Tick one option of a coordinator-signed question.

  Args:
    lines: The note's lines.
    question: The 1-based question number, as the menu lists it.
    option: The 1-based option number within that question, as the menu lists it.

  Returns:
    The edited lines, or `None` when the option is already ticked, and the question's summary.

  Raises:
    GestureRefusedError: With `no-such-question` when the question number names no signed question, or
      `no-such-option` when the option number names no option of it.
  """
  spans = _find_all_question_spans(lines)

  # guard: the question number names no coordinator question
  if not 1 <= question <= len(spans):
    raise GestureRefusedError(_NO_QUESTION)

  # the chosen question's lines and the options it carries
  start, end = spans[question - 1]
  block = lines[start:end]
  options = _parse_options(block, start)

  # guard: the option number names no option of that question
  if not 1 <= option <= len(options):
    raise GestureRefusedError(_NO_OPTION)

  # the chosen option's line and its current tick state
  idx, _text, ticked = options[option - 1]

  # an already ticked option needs nothing; otherwise only its line takes the tick
  if ticked:
    return None, _parse_summary(block)
  answered = list(lines)
  answered[idx] = _tick_line(lines[idx])
  return answered, _parse_summary(block)


def add_command(lines: list[str], text: str) -> list[str]:
  """
  Append a command line to the `# Coordinator commands` section.

  Args:
    lines: The note's lines.
    text: The command text to write as a new line.

  Returns:
    The edited lines, with the text placed after the section's last written line, past its owner tag and explainer
    and before its trailing blank lines.

  Raises:
    GestureRefusedError: With `no-commands-section` when the note has no `# Coordinator commands` section.
  """
  span = _find_section_span(lines, Section.COORD_COMMANDS)

  # guard: no `# Coordinator commands` section to write into
  if span is None:
    raise GestureRefusedError(_NO_COMMANDS)

  # the section's bounds
  start, end = span

  # the section's owner tag and its explainer are structure, the new line goes past them
  floor = start
  if floor < end and lines[floor].strip() == note_ops.PROTECTED_MARKERS.get(Section.COORD_COMMANDS):
    floor += 1
  if floor < end and note_explainers.is_explainer_line(lines[floor], Section.COORD_COMMANDS):
    floor += 1

  # the line lands right after the section's last written line, before its trailing blank lines
  last = max(( idx + 1 for idx in range(floor, end) if lines[idx].strip() ), default = floor)
  return [ *lines[:last], text, *lines[last:] ]


def _commit_edit(note: Path, edited: list[str] | None, subject: str) -> dict[str, object]:
  """
  Write an edited note back and commit it alone.

  Notes:
    - Writes the note keeping its line ending and commits only that file under the ambient git identity.

  Args:
    note: The folder-note's path.
    edited: The note's edited lines, or `None` when the gesture changed nothing.
    subject: The commit subject.

  Returns:
    A mapping with `status` (`committed` or `noop`), `sha` and `reason`. Nothing is written or committed when
    `edited` is `None`.

  Raises:
    subprocess.CalledProcessError: If the git commit fails.
  """
  # guard: a gesture that changed nothing commits nothing
  if edited is None:
    return { "status": _NOOP, "sha": None, "reason": None }

  # the note written back with its own line ending, then committed alone under the ambient identity
  spec_paths.write_text_atomic(note, "\n".join(edited) + "\n")
  done = note_commit.commit_paths(flip_gate.repo_root(note.parent), [ str(note) ], subject = subject)
  return { "status": _COMMITTED if done.status == note_commit.COMMITTED else _NOOP, "sha": done.sha, "reason": None }


def _build_parser() -> argparse.ArgumentParser:
  """
  Build the argument parser of the `drive-gesture` verb.

  Returns:
    The parser with the sub-commands `menu`, `tick`, `answer` and `command`.
  """
  # the verb's own parser, one sub-command per gesture
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs drive-gesture")
  sub = parser.add_subparsers(dest = _ARG_GESTURE, required = True)

  # `menu <note>`
  sub.add_parser(_MENU).add_argument(_ARG_NOTE, type = Path)

  # `tick <note> <label>`
  p_tick = sub.add_parser(_TICK)
  p_tick.add_argument(_ARG_NOTE, type = Path)
  p_tick.add_argument(_ARG_LABEL)

  # `answer <note> --question N --option M`
  p_answer = sub.add_parser(_ANSWER)
  p_answer.add_argument(_ARG_NOTE, type = Path)
  p_answer.add_argument(_FLAG_QUESTION, type = int, required = True)
  p_answer.add_argument(_FLAG_OPTION, type = int, required = True)

  # `command <note> --text TEXT`
  p_command = sub.add_parser(_COMMAND)
  p_command.add_argument(_ARG_NOTE, type = Path)
  p_command.add_argument(_FLAG_TEXT, required = True)
  return parser


def _run(args: argparse.Namespace) -> dict[str, object]:
  """
  Perform the gesture the parsed arguments name.

  Notes:
    - A writing gesture commits with the subject `lazy-spec.drive: tick <label> on <slug>`,
      `lazy-spec.drive: answer <summary> on <slug>` or `lazy-spec.drive: command "<text>" on <slug>`, where the slug
      is the note's folder name.

  Args:
    args: The parsed arguments of the verb.

  Returns:
    The gesture's result mapping.

  Raises:
    GestureRefusedError: If the gesture is refused.
  """
  note = args.note.resolve()

  # the read-only menu
  if args.gesture == _MENU:
    return build_menu(note)

  # the note's lines and the asset slug every writing gesture's subject names
  lines = _read(note)
  slug = note.parent.name

  # the three writing gestures, each a one-line edit and its own commit
  if args.gesture == _TICK:
    return _commit_edit(note, tick(lines, args.label), _SUBJECT_TICK.format(label = args.label, slug = slug))
  if args.gesture == _ANSWER:
    edited, summary = answer(lines, args.question, args.option)
    return _commit_edit(note, edited, _SUBJECT_ANSWER.format(summary = summary, slug = slug))
  return _commit_edit(note, add_command(lines, args.text), _SUBJECT_COMMAND.format(text = args.text, slug = slug))


def main(argv: list[str]) -> int:
  """
  Run the `drive-gesture` verb and print its result as one JSON line.

  Notes:
    - Bad arguments make the argument parser exit with code `2`.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    The exit code: `0` for a menu, a commit or a noop, and `1` for a refusal, which prints
    `{"status": "refused", "sha": null, "reason": ...}`.
  """
  args = _build_parser().parse_args(argv)

  # a refusal is reported on the JSON line, never raised to the caller
  try:
    result = _run(args)
  except GestureRefusedError as refused:
    print(json.dumps({ "status": _REFUSED, "sha": None, "reason": refused.reason }, ensure_ascii = False))
    return _EXIT_REFUSED

  # one JSON line carries the whole result
  print(json.dumps(result, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
