"""
Minimal YAML frontmatter parser for routine_types.dispatch_md_scan.

Permissive: if frontmatter is missing or malformed, returns {}. Supports
column-0 keys with scalar values, blank values (returned as None), inline
arrays via the `-` line-list shape, and `|` / `>` block scalars. Quoted
strings are unquoted and never coerced. Nested mappings are skipped and
anchors are out of scope — the filter use case is flat key→scalar/list.
"""
from __future__ import annotations

import json
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# a block-scalar indicator: `|` or `>`, an optional chomping sign and indentation digit, either order
_BLOCK_RE = re.compile(r"^[|>](?:[+-]?[1-9]?|[1-9][+-])$")


def parse_frontmatter(text: str) -> dict:
  """
  Return the YAML frontmatter at the head of a document as a flat dict.

  Only a column-0 `key:` line is a top-level key. Recognised values are scalars, blank values (mapped
  to None), inline `- item` lists attached to the most recent key, and `|` / `>` block scalars, whose
  indented lines belong to their value. Quoted strings are unquoted with their escapes resolved and
  stay strings; the lines of a nested mapping are skipped, and anchors are not supported.

  Guarantees:
    - Never raises on malformed input; missing, malformed, or empty frontmatter always
      resolves to an empty dict rather than an exception.
    - Only a column-0 `key:` line opens a top-level key; a line indented under it belongs to a
      nested value and is skipped, never misread as a sibling key.
    - A quoted scalar value is always returned as a string, with its quoting escapes resolved,
      and is never coerced to a bool, null, or number.

  Args:
    text: Full document text whose frontmatter block (if any) is delimited by lines containing
      exactly `---`.

  Returns:
    The parsed frontmatter mapping, or an empty dict when the input is empty, lacks an opening
    `---` fence, has no matching closing `---`, or carries no parseable key.
  """

  # Contract:
  # This function MUST NEVER raise on malformed input. Missing, malformed, or empty
  # frontmatter always resolves to an empty dict rather than propagating an exception.

  # guard: empty input — nothing to parse
  if not text:
    return {}

  # frontmatter is only frontmatter when the very first line opens the fence
  lines = text.splitlines()

  # guard: missing opening fence
  if not lines or lines[0].strip() != "---":
    return {}

  # locate the closing fence inside the block
  close_idx = None
  for i in range(1, len(lines)):
    if lines[i].strip() == "---":
      close_idx = i
      break

  # guard: no closing fence — frontmatter is malformed
  if close_idx is None:
    return {}

  # slice the body between fences and walk line-by-line
  block = lines[1:close_idx]
  result: dict = {}
  current_key: str | None = None
  # the open block scalar: its key (None when no scalar is open), its `|` / `>` indicator, and the
  # lines collected so far
  scalar_key: str | None = None
  scalar_indicator = ""
  scalar_lines: list[str] = []

  # one pass over the block: every line is a block-scalar line, a list item for the previous key,
  # a nested line to skip, or a new column-0 key
  for raw in block:
    stripped = raw.lstrip()
    indent = len(raw) - len(stripped)

    # an indented or blank line continues an open block scalar
    if scalar_key is not None and (indent > 0 or not stripped):
      scalar_lines.append(raw)
      continue
    if scalar_key is not None:
      result[scalar_key] = _block_value(scalar_indicator, scalar_lines)
      scalar_key = None

    # indented `- item` line under the most recent key — append to its list
    if indent > 0 and stripped.startswith("- ") and current_key is not None:
      value = _unquote(stripped[2:].strip())
      if not isinstance(result.get(current_key), list):
        result[current_key] = []
      result[current_key].append(value)
      continue

    # Contract:
    # Only a column-0 `key:` line opens a top-level key. A line indented under it belongs to a
    # nested value and is skipped, never misread as a sibling key.

    # guard: only a column-0 line is a top-level key — an indented one belongs to a nested value
    if indent > 0 or ":" not in raw:
      continue
    key, _, value = raw.partition(":")
    key = key.strip()
    value = value.strip()

    # guard: empty key after stripping
    if not key:
      continue

    # blank value → None placeholder; a `|` / `>` indicator opens a block scalar; current_key
    # tracks the most recent key so subsequent `- item` lines attach to it
    current_key = key
    if value == "":
      result[key] = None
    elif _BLOCK_RE.match(value):
      scalar_key, scalar_indicator, scalar_lines = key, value, []
    else:
      result[key] = _coerce_scalar(value)

  # a block scalar running to the closing fence ends there
  if scalar_key is not None:
    result[scalar_key] = _block_value(scalar_indicator, scalar_lines)

  # a block with no parseable key yields an empty mapping, never an error
  return result


def _block_value(indicator: str, raw_lines: list[str]) -> str:
  """
  Assemble a YAML block scalar's value from its indented lines.

  Guarantees:
    - A literal (`|`) scalar joins its lines with newlines; a folded (`>`) scalar joins them
      with spaces, turning a blank line into a paragraph break.
    - The chomping sign in `indicator` decides the trailing newlines: `-` drops every one of
      them, `+` keeps every one the source carried, and no sign keeps exactly one.

  Args:
    indicator: The `|` (literal) or `>` (folded) indicator, with an optional chomping sign.
    raw_lines: The scalar's lines as written, indentation included.

  Returns:
    The dedented value — literal lines joined by newlines, folded lines by spaces — ending in one
    newline, none with the `-` chomping sign, or every trailing newline with `+`.
  """
  # the first non-blank line sets the indentation every other line is measured against
  indents = [ len(ln) - len(ln.lstrip()) for ln in raw_lines if ln.strip() ]
  width = indents[0] if indents else 0
  body = [ ln[width:] if ln.strip() else "" for ln in raw_lines ]

  # trailing blank lines are held back for the chomping rule
  trailing = 0
  while body and not body[-1]:
    body.pop()
    trailing += 1

  # guard: no content at all — an empty value
  if not body:
    return ""

  # Contract:
  # The assembled text ends according to the chomping sign in `indicator`: `-` drops every
  # trailing newline, `+` keeps every trailing newline the source carried, and no sign keeps
  # exactly one trailing newline.

  # join literal lines with newlines, folded lines with spaces, then chomp the trailing newlines
  text = "\n".join(body) if indicator[0] == "|" else _fold(body)
  if "-" in indicator:
    return text
  if "+" in indicator:
    return text + "\n" * (trailing + 1)
  return text + "\n"


def _fold(body: list[str]) -> str:
  """
  Fold a `>` block scalar's lines: a single line break becomes a space, a blank line a newline.

  Args:
    body: The dedented content lines, trailing blank lines already removed.

  Returns:
    The folded text without a final newline.
  """
  out = ""
  for ln in body:
    if not ln:
      out += "\n"
    elif out and not out.endswith("\n"):
      out += " " + ln
    else:
      out += ln
  return out


def _unquote(s: str) -> str:
  """
  Return the string with one matched layer of surrounding single or double quotes removed.

  A single-quoted value turns each doubled `''` into one quote; a double-quoted value resolves its
  backslash escapes.

  Guarantees:
    - A single-quoted scalar has every doubled `''` resolved to one `'`; a double-quoted
      scalar has its backslash escapes resolved the same way JSON's are.

  Args:
    s: Candidate string that may be wrapped in matching `"` or `'` characters.

  Returns:
    The unquoted, unescaped string when both ends carry the same quote character; the input
    unchanged otherwise.
  """
  # guard: not a quoted scalar
  if not _is_quoted(s):
    return s

  # Contract:
  # A single-quoted scalar's doubled `''` sequences are each resolved to one `'`; a
  # double-quoted scalar's backslash escapes are resolved using JSON's escape rules, which YAML
  # double-quote escapes are a superset of.

  # a single-quoted scalar only ever doubles its own quote character
  if s[0] == "'":
    return s[1:-1].replace("''", "'")

  # YAML double-quote escapes are a superset of JSON's; an escape JSON rejects keeps its text
  try:
    decoded = json.loads(s, strict = False)
  except ValueError:
    return s[1:-1]
  return decoded if isinstance(decoded, str) else s[1:-1]


def _is_quoted(s: str) -> bool:
  """
  Tell whether a scalar is wrapped in one matching pair of quotes.

  Args:
    s: Raw scalar text.

  Returns:
    True when both ends carry the same `"` or `'` character.
  """
  return len(s) >= 2 and s[0] == s[-1] and s[0] in ( '"', "'" )


def _coerce_scalar(s: str) -> bool | int | float | str | None:
  """
  Convert a raw YAML scalar literal into the closest matching Python value.

  Recognises the YAML boolean literals `true` / `false`, the null literals `null` / `~`, integer and
  floating-point numerics, and falls back to the original string for anything else. A quoted scalar
  is returned as its unquoted string and is never classified; only an unquoted scalar is classified
  as a bool, null, or number.

  Guarantees:
    - A quoted scalar is always returned as its unquoted string; it is never coerced to a
      bool, null, or number, regardless of what its text would otherwise parse as.

  Args:
    s: Raw scalar text taken from the right-hand side of a frontmatter `key: value` pair.

  Returns:
    A `bool`, `None`, `int`, `float`, or `str` value depending on which literal shape the input matches.
  """

  # Contract:
  # A quoted scalar is a string by declaration: it is always returned unquoted, never coerced
  # to a bool, null, or number even when its text would otherwise match one of those literals.

  # guard: a quoted scalar is a string by declaration, never a bool, null, or number
  if _is_quoted(s):
    return _unquote(s)
  # waiver: YAML scalar keyword, external-format token, not an internal key
  if s.lower() == "true":
    return True
  # waiver: YAML scalar keyword, external-format token, not an internal key
  if s.lower() == "false":
    return False
  if s.lower() in ( "null", "~" ):
    return None

  # try numeric coercion: prefer int when there's no decimal point, fall back to float
  try:
    if "." not in s:
      return int(s)
    return float(s)
  except ValueError:
    # not a numeric literal — return the original string as-is
    return s
