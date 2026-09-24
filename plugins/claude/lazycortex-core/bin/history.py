"""
Append one bullet to a markdown note's `# History` section, keeping its day-group shape.

The section is the H1 `# History` followed by optional tag / explainer lines and then day groups:
a level-4 heading `#### YYYY-MM-DD`, one blank line before it, and `- <text>` bullets under it,
oldest group first. A new bullet lands in the last group when its date matches, otherwise a new
group opens after the section's last non-blank line. Frontmatter and every other section are
returned byte-identical; the section is created at the end of the note when it is missing.

Reached over the `lazycortex-core history-append` CLI in file mode (rewrite a note in place) or
stdin mode (transform a JSON-carried text, touching no file).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class HistoryShape:
  """
  Fixed markdown tokens of the `# History` section shape.

  Attributes:
    HEADING: The default H1 line that opens the section.
    DAY_PREFIX: The level-4 heading prefix of a day group.
    BULLET: The prefix of every history line.
    H1_PREFIX: The prefix that ends the section — only an H1 is a boundary.
    FRONTMATTER_FENCE: The line that opens and closes a leading YAML block.
  """

  HEADING = "# History"
  DAY_PREFIX = "#### "
  BULLET = "- "
  H1_PREFIX = "# "
  FRONTMATTER_FENCE = "---"


# ----------------------------------------------------------------------------------------
class IoKey:
  """
  Field names of the JSON objects the CLI reads from stdin and prints to stdout.

  Attributes:
    TEXT: The whole note text (stdin input and stdin-mode output).
    LINE: The history line to append.
    DATE: The `YYYY-MM-DD` day the line belongs to.
    HEADING: The H1 that opens the section, when not the default.
    FILE: The note path as given, echoed in file-mode output.
    NEW_DAY: Whether the append opened a new day group.
  """

  TEXT = "text"
  LINE = "line"
  DATE = "date"
  HEADING = "heading"
  FILE = "file"
  NEW_DAY = "new_day"


HISTORY_HEADING = HistoryShape.HEADING
_PROG = "lazycortex-core history-append"
_UTF8 = "utf-8"
_EXIT_USAGE = 2
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_HEADING_RE = re.compile(r"^#### (\d{4}-\d{2}-\d{2})\s*$")


def _bullet(line: str) -> str:
  """
  Normalise a caller-supplied history line into one `- <text>` bullet.

  Args:
    line: The text to append; a leading `- ` is tolerated and not doubled.

  Returns:
    The bullet line, prefix included, with surrounding whitespace removed.

  Raises:
    ValueError: If the line is empty after stripping or spans more than one line.
  """
  text = line.strip()

  # guard: a bullet is exactly one non-empty line — anything else corrupts the group
  if not text or "\n" in text:
    raise ValueError("line must be one non-empty line")
  if text.startswith(HistoryShape.BULLET) or text == HistoryShape.BULLET.strip():
    text = text[len(HistoryShape.BULLET):].strip()

  # guard: a bare `-` carries no text once the prefix is stripped
  if not text:
    raise ValueError("line must be one non-empty line")
  return HistoryShape.BULLET + text


def _body_start(lines: list[str]) -> int:
  """
  Locate the first line after a leading YAML frontmatter block.

  Args:
    lines: The note split into lines.

  Returns:
    The index of the first body line — `0` when the note carries no closed frontmatter block.
  """
  # guard: no opening fence on line one means no frontmatter at all
  if not lines or lines[0] != HistoryShape.FRONTMATTER_FENCE:
    return 0
  for index in range(1, len(lines)):
    if lines[index] == HistoryShape.FRONTMATTER_FENCE:
      return index + 1

  # an unclosed fence is body text, not frontmatter
  return 0


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
  """
  Find the history section as a half-open line range.

  Args:
    lines: The note split into lines.
    heading: The stripped H1 line that opens the section.

  Returns:
    `(start, end)` where `start` indexes the heading line and `end` the next H1 or the line
    count; None when no such heading exists outside the frontmatter.
  """
  start = next(
    (idx for idx in range(_body_start(lines), len(lines)) if lines[idx].strip() == heading), None,
  )

  # guard: no heading — the caller creates the section
  if start is None:
    return None
  end = next(
    (idx for idx in range(start + 1, len(lines)) if lines[idx].startswith(HistoryShape.H1_PREFIX)),
    len(lines),
  )
  return start, end


def append_line(text: str, line: str, date: str, heading: str = HISTORY_HEADING) -> tuple[str, bool]:
  """
  Append one history bullet under the given day, opening the day group when needed.

  Guarantees:
    - Frontmatter and every line outside the history section are returned unchanged.
    - The result ends with exactly one newline.

  Args:
    text: The whole note, frontmatter included.
    line: The history text; a leading `- ` is tolerated.
    date: The `YYYY-MM-DD` day the line belongs to.
    heading: The stripped H1 line that opens the section.

  Returns:
    `(new_text, new_day)` — the rewritten note and whether a day group was created.

  Raises:
    ValueError: If `line` is empty or multi-line, or `date` is not `YYYY-MM-DD`.
  """

  # Contract:
  # Every line outside the history section, frontmatter included, is returned unchanged;
  # the result ends with exactly one newline.

  bullet = _bullet(line)

  # guard: a malformed date would open a group no later append could ever match
  if not _DATE_RE.match(date):
    raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")

  # trailing newlines are re-normalised on output, so they are dropped before splitting
  lines = text.rstrip("\n").split("\n") if text.strip() else []
  bounds = _section_bounds(lines, heading)
  if bounds is None:
    # one blank line separates the new section from whatever precedes it
    if lines:
      lines.append("")
    lines.append(heading)
    bounds = (len(lines) - 1, len(lines))
  start, end = bounds

  # the insertion point is right after the section's last non-blank line, so trailing blanks
  # keep separating the section from what follows
  insert_at = next((idx + 1 for idx in range(end - 1, start, -1) if lines[idx].strip()), start + 1)
  last_day = next(
    (match.group(1) for idx in range(end - 1, start, -1) if (match := _DAY_HEADING_RE.match(lines[idx]))), None,
  )
  if last_day == date:
    lines.insert(insert_at, bullet)
    return "\n".join(lines) + "\n", False

  # a new day: one blank line, the group heading, then the bullet
  lines[insert_at:insert_at] = [ "", HistoryShape.DAY_PREFIX + date, bullet ]
  return "\n".join(lines) + "\n", True


def _today() -> str:
  """
  Return today's date in UTC as `YYYY-MM-DD`.

  Returns:
    The ISO date string.
  """
  return datetime.now(UTC).date().isoformat()


def _run_stdin(heading_default: str) -> int:
  """
  Transform a JSON-carried note read from stdin and print the result as JSON.

  Args:
    heading_default: The section heading used when the request names none.

  Returns:
    Process exit code — `0` on success.

  Raises:
    ValueError: If stdin is not one JSON object carrying string `text` and `line` fields.
  """
  request = json.load(sys.stdin)

  # guard: anything but an object with string text/line is a malformed request
  if not isinstance(request, dict) or not all(
    isinstance(request.get(key), str) for key in (IoKey.TEXT, IoKey.LINE)
  ):
    raise ValueError("stdin must be one JSON object with string \"text\" and \"line\"")
  date = request.get(IoKey.DATE) or _today()
  new_text, new_day = append_line(
    request[IoKey.TEXT], request[IoKey.LINE], date, request.get(IoKey.HEADING) or heading_default,
  )
  print(json.dumps({ IoKey.TEXT: new_text, IoKey.DATE: date, IoKey.NEW_DAY: new_day }))
  return 0


def _run_file(file: str | None, line: str | None, date: str | None, heading: str) -> int:
  """
  Rewrite one note in place and print a JSON report.

  Args:
    file: The note path as given on the command line.
    line: The history text to append.
    date: The `YYYY-MM-DD` day, or None for today in UTC.
    heading: The section heading.

  Returns:
    Process exit code — `0` on success.

  Raises:
    ValueError: If the file or line is missing, the file does not exist, or the line / date is
      malformed.
  """
  # guard: file mode needs both a path and a line
  if file is None or line is None:
    raise ValueError("usage: <file> --line <text> [--date YYYY-MM-DD] [--heading <h1>]")
  path = Path(file)

  # guard: a missing note is the caller's error, never something to create silently
  if not path.is_file():
    raise ValueError(f"no such file: {file}")
  day = date or _today()
  new_text, new_day = append_line(path.read_text(encoding = _UTF8), line, day, heading)
  path.write_text(new_text, encoding = _UTF8)
  print(json.dumps({ IoKey.FILE: file, IoKey.DATE: day, IoKey.NEW_DAY: new_day }))
  return 0


def main(argv: list[str] | None = None) -> int:
  """
  CLI entry point: append one history bullet in file mode or stdin mode.

  Args:
    argv: CLI arguments after the subcommand token — `<file> --line <text> [--date D]
      [--heading H]`, or `--stdin` with a JSON request on standard input.

  Returns:
    Process exit code — `0` on success, `2` with a one-line stderr message on a missing file,
    an empty or multi-line line, a bad date, or malformed stdin JSON.
  """
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("file", nargs = "?", help = "Note to rewrite in place")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("--line", help = "History text to append")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("--date", help = "YYYY-MM-DD; default today in UTC")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("--heading", default = HISTORY_HEADING, help = "H1 that opens the section")
  # waiver: argparse CLI signature — argument names and help copy, not domain keys
  parser.add_argument("--stdin", action = "store_true", help = "Read a JSON request from stdin")
  args = parser.parse_args(argv)

  # every refusal is one stderr line and exit 2; JSON decode errors are ValueErrors too
  try:
    if args.stdin:
      return _run_stdin(args.heading)
    return _run_file(args.file, args.line, args.date, args.heading)
  except ValueError as exc:
    print(f"history-append: {exc}", file = sys.stderr)
    return _EXIT_USAGE


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
