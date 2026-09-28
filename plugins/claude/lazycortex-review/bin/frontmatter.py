"""Surgical line-edit frontmatter operations.

Lazy-review's frontmatter rules (spec § Frontmatter schema):

- Three reserved keys (`review_active`, `review_round`, `approved`) are
  managed by the dispatcher; agents may not write them.
- All other keys belong to the consumer and survive byte-for-byte
  through any dispatcher-side edit.
- Block-style values (`tags:\\n  - one\\n  - two`), inline arrays,
  comments and quoting style MUST survive byte-for-byte. A
  parse → render round-trip via PyYAML collapses or rewrites these
  forms; we never do that.

This module operates on the raw text of the `---`-fenced block. The
`parse` helper exposes a string-typed dict for membership tests and
quick reads; mutations always go through `set_field` / `unset_field`
which perform a single targeted line edit and leave every other byte
of the document untouched.
"""
from __future__ import annotations

import json
import re

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from errors import ParseError  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_FENCE = "---"
_FENCE_LINE = re.compile(r"^---[ \t]*\r?$", re.MULTILINE)

# the opening fence: an optional BOM, `---`, trailing blanks, then a line end or end of text
_OPEN_FENCE = re.compile(r"\A\ufeff?---[ \t]*(?:\r?\n|\Z)")


# ----------------------------------------------------------------- helpers


def _find_fences(text: str) -> tuple[int, int, int] | None:
  """
  Return the byte offsets of the frontmatter fences, or `None` if none exist.

  A document has frontmatter iff its first non-empty line is `---` and a later
  `---`-only line closes the block. An opening fence with no matching close raises
  `ParseError` rather than silently skipping.

  Args:
    text: Raw document text to inspect.

  Returns:
    A three-tuple `(open_end, close_start, close_end)` byte offsets, or `None`
    when no frontmatter is present.

  Raises:
    ParseError: If an opening fence exists but no matching closing fence is found.
  """
  # guard: no opening fence on the first line (after an optional BOM) → no frontmatter
  opening = _OPEN_FENCE.match(text)
  if opening is None:
    return None

  # locate the closing fence as the next `---`-only line after the opening fence
  after_open = opening.end()
  rest = text[after_open:]
  match = _FENCE_LINE.search(rest)

  # guard: an opening fence with no closing fence is malformed, not "no frontmatter"
  if match is None:
    raise ParseError(
        "frontmatter opening fence has no matching closing fence",
        text_excerpt=text[:200],
    )

  # translate the match back into offsets over the original text
  close_start = after_open + match.start()
  close_end = after_open + match.end()

  # The fence may be followed by `\n` (typical), `\r\n`, or end-of-file.
  if close_end < len(text) and text[close_end] == "\n":
    close_end += 1

  # the three offsets every caller slices frontmatter and body apart with
  return (after_open, close_start, close_end)


def _serialise_scalar(value: object) -> str:
  """
  Render a Python scalar into a YAML literal, double-quoting a string that YAML cannot hold bare.

  Guarantees:
    - A Python bool, None, or int value is emitted using its YAML literal spelling.
    - A string is emitted double-quoted when writing it bare would break the YAML line or
      structure: empty, surrounding whitespace, a line break, a leading indicator character,
      an embedded `: ` or ` #`, or a trailing colon.
    - A string already written as a strict single-line flow list or mapping is emitted as is.
    - A string that YAML would merely retype, such as `9`, `true`, `null`, or a date, is emitted
      bare on purpose.

  Args:
    value: The Python value to serialise.

  Returns:
    The YAML representation of the value.
  """

  # Contract:
  # A Python bool, None, or int value MUST be emitted using its YAML literal spelling.
  # A string MUST be emitted double-quoted when writing it bare would break the YAML line or
  # structure: an empty string, one with surrounding whitespace, one containing a line break, one
  # starting with a leading indicator character, one containing `: ` or ` #`, or one ending in a
  # trailing colon.
  # A string already written as a strict single-line flow list or mapping MUST be emitted as is.
  # A string that YAML would merely retype, such as `9`, `true`, `null`, or a date, MUST be
  # emitted bare — a caller passes a real Python type when a number or boolean is meant.

  # booleans, null, and numbers have one YAML spelling each
  if isinstance(value, bool):
    return "true" if value else "false"
  if value is None:
    return "null"
  if isinstance(value, (int, float)):
    return str(value)
  # a Python list or mapping renders as JSON, which is a valid YAML flow collection
  if isinstance(value, (list, tuple, dict)):
    return json.dumps(value, ensure_ascii = False, default = str)
  text = str(value)

  # guard: a caller-rendered flow list or mapping is already YAML
  if _FLOW_COLLECTION_RE.fullmatch(text):
    return text

  # a JSON string literal is a valid YAML double-quoted scalar
  return json.dumps(text, ensure_ascii = False) if _NEEDS_QUOTES_RE.search(text) else text


# one item of a single-line flow collection: a quoted scalar, or a plain scalar holding no flow
# indicator, no comment `#`, and no `:` followed by a blank or an indicator
_FLOW_ITEM = (
    r"(?:\"(?:[^\"\\\r\n]|\\.)*\"|'(?:[^'\r\n]|'')*'"
    r"|[^\s\-?:,\[\]{}#&*!|>'\"%@`](?:[^,\[\]{}#:\r\n]|:(?=[^\s,\[\]{}]))*)"
)

# a string a caller already rendered as a genuine YAML flow list or mapping, all on one line
_FLOW_COLLECTION_RE = re.compile(
    rf"\[[ \t]*(?:{_FLOW_ITEM}(?:[ \t]*,[ \t]*{_FLOW_ITEM})*[ \t]*)?\]"
    rf"|\{{[ \t]*(?:{_FLOW_ITEM}[ \t]*:[ \t]+{_FLOW_ITEM}"
    rf"(?:[ \t]*,[ \t]*{_FLOW_ITEM}[ \t]*:[ \t]+{_FLOW_ITEM})*[ \t]*)?\}}"
)

# any shape YAML's plain-scalar syntax cannot carry: empty, surrounding whitespace, a line break,
# a leading indicator character, a `: ` or ` #` inside, or a trailing colon
_NEEDS_QUOTES_RE = re.compile(
    r"\A\Z|\A\s|\s\Z|[\r\n]|\A[-?:](?:\s|\Z)|\A[,\[\]{}#&*!|>'\"%@`]|:(?:\s|\Z)|\s#"
)

# a line that continues the previous key's value: indented, or a column-0 list item
_CONTINUATION_LINE_RE = re.compile(r"^(?:[ \t]+\S|-(?:[ \t]|$))")

_KEY_LINE = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?:\s|$)")


def _line_starts_top_level_key(line: str) -> bool:
  """
  Return whether a frontmatter line begins a new top-level key.

  A top-level key line has no leading whitespace and matches the `key:` shape.
  Used to identify the end of a block-style value owned by the previous key.

  Args:
    line: A single line from the frontmatter block (without trailing newline).

  Returns:
    `True` if the line starts a new top-level key, `False` otherwise.
  """
  if not line or line[0] in (" ", "\t", "#"):
    return False
  return bool(_KEY_LINE.match(line))


def _key_block_span(block: str, key: str) -> tuple[int, int] | None:
  """
  Return the byte offsets of the full logical entry for `key` within `block`.

  The span covers the key's header line plus its continuation lines: indented lines and list
  items, with blank lines between them. A blank line or a comment line not followed by more of
  the value ends the span.

  Args:
    block: The raw frontmatter YAML body (text between the two `---` fences).
    key: The top-level key to locate.

  Returns:
    A `(start, end)` tuple of byte offsets inside `block`, or `None` if `key`
    is not present at the top level.
  """
  # the header stays on its own line: horizontal whitespace only, so an empty `key:` never
  # swallows its own newline and drags the next line into the span
  pattern = re.compile(
      rf"(?m)^{re.escape(key)}[ \t]*:(?=[ \t]|\r?$)",
  )
  match = pattern.search(block)
  if match is None:
    return None
  start = match.start()

  # Walk forward line-by-line: indented lines and list items continue the value; blank lines
  # continue it only when more of the value follows them.
  cursor = block.find("\n", match.end())
  if cursor == -1:
    return (start, len(block))
  cursor += 1  # consume the newline of the header line
  end = cursor
  while cursor < len(block):
    next_nl = block.find("\n", cursor)
    line_end = next_nl if next_nl != -1 else len(block)
    line = block[cursor:line_end].rstrip("\r")
    cursor = line_end + 1 if next_nl != -1 else line_end
    if _CONTINUATION_LINE_RE.match(line):
      end = cursor
      continue

    # guard: anything but a blank line (a comment, the next key) ends the value
    if line.strip():
      break
  return (start, end)


# -------------------------------------------------------------------- parse


def parse(text: str) -> tuple[dict[str, str], str]:
  """
  Split a document into its frontmatter key dict and post-fence body.

  Block-style values, inline arrays, and nested mappings are flattened to the
  raw post-colon text (everything after the first `:`, leading whitespace
  stripped). The dict is intended for membership tests and quick scalar reads;
  mutations must go through `set_field` or `unset_field` to preserve the
  original text byte-for-byte.

  Args:
    text: Raw document text, with or without a frontmatter block.

  Returns:
    A `(meta, body)` tuple where `meta` maps top-level scalar key names to
    their raw string values, and `body` is the text following the closing fence.
    When no frontmatter is present, `meta` is empty and `body` is the full text.
  """
  span = _find_fences(text)
  if span is None:
    return ({}, text)
  open_end, close_start, close_end = span
  block = text[open_end:close_start]
  body = text[close_end:]
  meta: dict[str, str] = {}
  for line in block.splitlines():
    # guard: skip continuation/list/indented lines so only top-level `key: value` pairs are collected into meta
    if not _line_starts_top_level_key(line):
      continue
    key, _, rest = line.partition(":")
    meta[key.strip()] = rest.strip()
  return (meta, body)


# --------------------------------------------------------- read_list_field


def read_list_field(text: str, key: str) -> list[str]:
  """
  Read a frontmatter key's list value, whether written inline or as a block-style YAML list.

  `parse()` flattens block-style continuation lines away — it exists for scalar reads, not
  multi-line lists. This helper walks the same key-block span `set_field` targets, but returns
  every list item instead of replacing them, so callers can read fields a producer writes as a
  block list (e.g. `spec_source_requests`, one `- "value"` line per entry).

  Args:
    text: Raw document text, with or without a frontmatter block.
    key: The top-level frontmatter key to read.

  Returns:
    List of item strings (surrounding quotes stripped), in document order. Empty when the
    document has no frontmatter, the key is absent, or the key's value is not a list.
  """
  span = _find_fences(text)
  if span is None:
    return []
  open_end, close_start, _close_end = span
  block = text[open_end:close_start]
  key_span = _key_block_span(block, key)
  if key_span is None:
    return []
  entry = block[key_span[0]:key_span[1]]
  header, _, continuation = entry.partition("\n")
  _, _, inline_value = header.partition(":")
  inline_value = inline_value.strip()

  # inline array form: `key: ["a", "b"]` or `key: []`
  if inline_value.startswith("[") and inline_value.endswith("]"):
    inner = inline_value[1:-1].strip()
    if not inner:
      return []
    return [item.strip().strip('"').strip("'") for item in inner.split(",")]

  # block-style form: header line bare, items as indented `- value` continuation lines
  return [
      line.strip()[2:].strip().strip('"').strip("'")
      for line in continuation.splitlines()
      if line.strip().startswith("- ")
  ]


# ---------------------------------------------------------------- set_field


def set_field(text: str, key: str, value: object) -> str:
  """
  Set `key` to `value` in the frontmatter, preserving all other text byte-for-byte.

  Creates the frontmatter block if the document has none. When the key already
  exists, its entire logical entry (header line plus any block-style continuation
  lines) is replaced with a single-line scalar form.

  Guarantees:
    - Every byte of `text` outside the `key` entry's own span is left unchanged.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to set.
    value: The Python value to write; serialised to a bare YAML literal.

  Returns:
    The updated document text with the key set and all other bytes unchanged.
  """

  # Contract:
  # Every byte of the input outside the `key` entry's own span (its header
  # line plus any block-style continuation lines) is left unchanged; other
  # frontmatter keys, body text, and formatting survive byte-for-byte.

  rendered = f"{key}: {_serialise_scalar(value)}"
  span = _find_fences(text)
  if span is None:
    # Document has no frontmatter at all — synthesize one.
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    return f"{bom}---\n{rendered}\n---\n{text[len(bom):]}"
  open_end, close_start, _close_end = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  if existing is None:
    # Append before the closing fence, preserving the block's
    # trailing newline if any.
    newline = "\r\n" if "\r\n" in text[:close_start] else "\n"
    if block and not block.endswith("\n"):
      new_block = block + newline + rendered + newline
    else:
      new_block = block + rendered + newline
    return text[:open_end] + new_block + text[close_start:]

  # Replace the whole existing entry (header + any continuation lines)
  # with a single-line scalar form. Preserve the entry's trailing
  # newline so the closing fence stays on its own line.
  start, end = existing
  entry = block[start:end]
  suffix = "\r\n" if entry.endswith("\r\n") else "\n" if entry.endswith("\n") else ""
  new_block = block[:start] + rendered + suffix + block[end:]
  return text[:open_end] + new_block + text[close_start:]


# -------------------------------------------------------------- unset_field


def is_empty(text: str) -> bool:
  """
  Return whether the frontmatter block in `text` contains no top-level keys.

  Useful after a series of `unset_field` calls to detect when the block has
  degenerated into bare `---\n---\n` fences that should be dropped rather than
  left as visual noise.

  Args:
    text: Raw document text whose frontmatter is to be inspected.

  Returns:
    `True` if the frontmatter body contains only whitespace and blank lines,
    or if there is no frontmatter block. `False` otherwise.
  """
  span = _find_fences(text)
  if span is None:
    return False
  open_end, close_start, _close_end = span
  block = text[open_end:close_start]
  return all(not line.strip() for line in block.split("\n"))


def unset_field(text: str, key: str) -> str:
  """
  Remove `key` and any block-style continuation lines from the frontmatter.

  No-op when the key is absent or the document has no frontmatter.

  Guarantees:
    - Every byte of `text` outside the removed `key` entry's own span is left unchanged.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to remove.

  Returns:
    The updated document text with the key removed and all other bytes unchanged.
  """

  # Contract:
  # Every byte of the input outside the removed `key` entry's own span is
  # left unchanged; when the key is absent or no frontmatter exists, the
  # input is returned unchanged.

  span = _find_fences(text)
  if span is None:
    return text
  open_end, close_start, _close_end = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  if existing is None:
    return text
  start, end = existing
  new_block = block[:start] + block[end:]
  return text[:open_end] + new_block + text[close_start:]
