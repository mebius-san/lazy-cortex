"""
In-place extension of a TOML array, shared by the install phases and the plugin's migration scripts.

The edit is text surgery: the array gains its new entries and every other byte of the document — entries, comments,
layout, line endings — stays as it was. Callers validate the result by parsing it.
"""
from __future__ import annotations

import json
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def append_to_array(toml_text: str, top_name: str, key: str, *, values: list[str], comment: str = "") -> str:
  """
  Append string values to an array a key holds directly under `[tool.<top_name>]`, keeping
  the array's existing entries, comments and layout.

  Notes:
    - A multi-line array whose closing bracket stands on its own line gains one new line per
      call, indented like its first entry and ended with the document's own line break; any
      other array gains the values inline after its last entry.
    - The comment is written only on a new line of its own; an inline append carries none.

  Args:
    toml_text: Full TOML document to edit.
    top_name: Name of the section under `tool`, dotted for a nested table (`ruff.lint`).
    key: Bare key whose array value is extended.
    values: String values to append, in order.
    comment: Text of a `#` comment ending the new line; empty for none.

  Returns:
    The edited document, or `toml_text` unchanged when the key's array cannot be located.
  """
  opening = _find_array_start(toml_text, top_name, key)

  # guard: no `key = [` line directly under the section's own header
  if opening is None:
    return toml_text

  # where the array closes, where its last entry ends, and whether a comma already follows that entry
  close, last_end, has_comma = _scan_array(toml_text, opening)

  # guard: an array that never closes cannot be extended
  if close is None:
    return toml_text

  # the new entries as TOML strings, and the start of the line holding the closing bracket
  quoted = ", ".join(json.dumps(value) for value in values)
  line_start = toml_text.rfind("\n", 0, close) + 1

  # a closing bracket alone on its line marks a one-entry-per-line array: the last entry gets its missing comma and
  # the new entries go on a line of their own, indented like the first entry
  if "\n" in toml_text[opening:close] and not toml_text[line_start:close].strip():
    indent = re.search(r"\n([ \t]*)\S", toml_text[opening:close])

    # an empty array keeps the text before the closing line as is
    before_close = toml_text[:line_start]

    # an existing last entry gets its missing comma before the new line is added
    if last_end is not None:
      before_close = toml_text[:last_end] + ("" if has_comma else ",") + toml_text[last_end:line_start]

    # the new line ends like the document's lines do, after the optional comment
    newline = "\r\n" if "\r\n" in toml_text else "\n"
    tail = f",   # {comment}" if comment else ","
    return before_close + (indent.group(1) if indent else "  ") + quoted + tail + newline + toml_text[line_start:]

  # an empty inline array takes the values as its only entries
  if last_end is None:
    return toml_text[:opening] + quoted + toml_text[opening:]
  return toml_text[:last_end] + ", " + quoted + toml_text[last_end:]


def _find_array_start(toml_text: str, top_name: str, key: str) -> int | None:
  """
  Locate the opening bracket of an array a bare key holds directly under `[tool.<top_name>]`.

  Args:
    toml_text: Full TOML document to scan.
    top_name: Name of the top-level tool section holding the key.
    key: Bare key whose array value is located.

  Returns:
    The offset just past the opening `[`, or `None` when the section header or a
    `key = [` line under it is missing.
  """
  header = f"[tool.{top_name}]"
  key_line = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*\[")
  offset = 0
  in_section = False
  for line in toml_text.splitlines(keepends = True):
    stripped = line.strip()

    # the section's own header switches scanning on
    if stripped == header:
      in_section = True
    # a nested sub-table or the next section ends the section's own keys
    elif in_section and stripped.startswith("["):
      return None
    # the key's `key = [` line inside the section yields the offset just past its opening bracket
    elif in_section and (match := key_line.match(line)):
      return offset + match.end()

    # track the offset of the next line for the match arithmetic above
    offset += len(line)
  return None


def _scan_array(toml_text: str, opening: int) -> tuple[int | None, int | None, bool]:
  """
  Walk a TOML array from just past its opening bracket to its closing one.

  Args:
    toml_text: Full TOML document.
    opening: Offset just past the array's opening `[`.

  Returns:
    The offset of the closing `]` (or `None` when the array never closes), the offset just
    past the last entry (or `None` for an empty array), and whether a comma follows that entry.
  """
  depth = 1
  last_end: int | None = None
  has_comma = False
  pos = opening
  while pos < len(toml_text):
    char = toml_text[pos]

    # a comment runs to the end of its line and holds no entry
    if char == "#":
      pos = toml_text.find("\n", pos)
      # guard: a comment that runs to the end of the document leaves the array unterminated
      if pos == -1:
        return None, None, False

      # resume scanning on the line that follows the comment
      continue

    # a string is skipped whole, so brackets and commas inside it are not structure
    if char in "\"'":
      end = _find_string_end(toml_text, pos)
      # guard: a string that never closes leaves the array unterminated
      if end is None:
        return None, None, False

      # a string directly in the array is an entry: it becomes the last one and no comma follows it yet
      if depth == 1:
        last_end, has_comma = end, False

      # resume scanning just past the closing quote
      pos = end
      continue

    # brackets nest; the bracket that returns to depth 0 closes the array
    if char == "[":
      depth += 1
    elif char == "]":
      depth -= 1
      if depth == 0:
        return pos, last_end, has_comma
      # a nested array closing back to depth 1 is itself an entry, so it becomes the last one
      if depth == 1:
        last_end, has_comma = pos + 1, False
    # a depth-1 comma separates entries: the entry before it already has its comma
    elif char == "," and depth == 1:
      has_comma = True
    # any other depth-1 token (a number, a bare word) is an entry, so it becomes the last one
    elif not char.isspace() and depth == 1:
      last_end, has_comma = pos + 1, False
    pos += 1
  return None, None, False


def _find_string_end(toml_text: str, start: int) -> int | None:
  """
  Find where a TOML string starting at `start` ends.

  Args:
    toml_text: Full TOML document.
    start: Offset of the string's opening quote.

  Returns:
    The offset just past the closing quote, or `None` when the string never closes.
  """
  quote = toml_text[start]

  # a multi-line string ends at the next triple quote
  if toml_text.startswith(quote * 3, start):
    end = toml_text.find(quote * 3, start + 3)
    return None if end == -1 else end + 3

  # a single-line string ends at its quote; a basic string skips escaped characters
  pos = start + 1
  while pos < len(toml_text) and toml_text[pos] != "\n":
    # an escape hides the next character, so an escaped quote does not end the string
    if quote == '"' and toml_text[pos] == "\\":
      pos += 2
      continue

    # an unescaped quote of the opening kind closes the string
    if toml_text[pos] == quote:
      return pos + 1
    pos += 1
  return None
