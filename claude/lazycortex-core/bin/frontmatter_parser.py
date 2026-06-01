"""
Minimal YAML frontmatter parser for routine_types.dispatch_md_scan.

Permissive: if frontmatter is missing or malformed, returns {}. Supports
scalar values, blank values (returned as None), and inline arrays via the
`-` line-list shape. Quoted strings are unquoted. Anything more exotic
(nested mappings, anchors, multi-line scalars) is out of scope — the
filter use case is flat key→scalar/list.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def parse_frontmatter(text: str) -> dict:
  """
  Return the YAML frontmatter at the head of a document as a flat dict.

  Recognised values are scalars, blank values (mapped to None), and inline `- item` lists attached to
  the most recent key. Quoted strings are unquoted; nested mappings, anchors, and multi-line scalars
  are not supported.

  Args:
    text: Full document text whose frontmatter block (if any) is delimited by lines containing
      exactly `---`.

  Returns:
    The parsed frontmatter mapping, or an empty dict when the input is empty, lacks an opening
    `---` fence, has no matching closing `---`, or carries no parseable key.
  """
  # guard: empty input — nothing to parse
  if not text:
    return {}

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

  for raw in block:
    stripped = raw.lstrip()
    indent = len(raw) - len(stripped)
    # indented `- item` line under the most recent key — append to its list
    if indent > 0 and stripped.startswith("- ") and current_key is not None:
      value = _unquote(stripped[2:].strip())
      if not isinstance(result.get(current_key), list):
        result[current_key] = []
      result[current_key].append(value)
      continue

    # guard: not a key:value line
    if ":" not in raw:
      continue
    key, _, value = raw.partition(":")
    key = key.strip()
    value = value.strip()
    # guard: empty key after stripping
    if not key:
      continue

    # blank value → None placeholder; current_key tracks the most recent key so
    # subsequent `- item` lines attach to it
    if value == "":
      result[key] = None
      current_key = key
    else:
      result[key] = _coerce_scalar(value)
      current_key = key

  return result


def _unquote(s: str) -> str:
  """
  Return the string with one matched layer of surrounding single or double quotes removed.

  Args:
    s: Candidate string that may be wrapped in matching `"` or `'` characters.

  Returns:
    The unquoted string when both ends carry the same quote character; the input unchanged otherwise.
  """
  if len(s) >= 2 and s[0] == s[-1] and s[0] in ( '"', "'" ):
    return s[1:-1]
  return s


def _coerce_scalar(s: str) -> bool | int | float | str | None:
  """
  Convert a raw YAML scalar literal into the closest matching Python value.

  Recognises the YAML boolean literals `true` / `false`, the null literals `null` / `~`, integer and
  floating-point numerics, and falls back to the original string for anything else. Surrounding
  quotes are stripped before classification.

  Args:
    s: Raw scalar text taken from the right-hand side of a frontmatter `key: value` pair.

  Returns:
    A `bool`, `None`, `int`, `float`, or `str` value depending on which literal shape the input matches.
  """
  s = _unquote(s)
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
