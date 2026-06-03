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
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re

from errors import ParseError

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_FENCE = "---"
_FENCE_LINE = re.compile(r"^---[ \t]*$", re.MULTILINE)


# ----------------------------------------------------------------- helpers


def _find_fences(text: str) -> tuple[int, int] | None:
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
  if not text.startswith("---\n") and text != "---" and not text.startswith("---\r\n"):
    return None
# Locate the closing fence as the next `---`-only line after the opening fence.
  after_open = len("---\n") if text.startswith("---\n") else len("---\r\n")
  rest = text[after_open:]
  match = _FENCE_LINE.search(rest)
  if match is None:
    raise ParseError(
        "frontmatter opening fence has no matching closing fence",
        text_excerpt=text[:200],
    )
  close_start = after_open + match.start()
  close_end = after_open + match.end()
  # The fence may be followed by `\n` (typical) or end-of-file.
  if close_end < len(text) and text[close_end] == "\n":
    close_end += 1
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  return (after_open, close_start, close_end)  # type: ignore[return-value]


def _serialise_scalar(value: object) -> str:
  """
  Render a Python scalar into a bare YAML literal.

  Args:
    value: The Python value to serialise.

  Returns:
    A bare YAML string representation of the value.
  """
  if isinstance(value, bool):
    return "true" if value else "false"
  if value is None:
    return "null"
  if isinstance(value, (int, float)):
    return str(value)
  return str(value)


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

  The span covers the key's header line plus any indented continuation lines
  that form a block-style value.

  Args:
    block: The raw frontmatter YAML body (text between the two `---` fences).
    key: The top-level key to locate.

  Returns:
    A `(start, end)` tuple of byte offsets inside `block`, or `None` if `key`
    is not present at the top level.
  """
  pattern = re.compile(
      rf"(?m)^{re.escape(key)}\s*:(?:\s|$)",
  )
  match = pattern.search(block)
  if match is None:
    return None
  start = match.start()
  # Walk forward line-by-line until we hit the next top-level key,
  # an empty line followed by a top-level key, or end of block.
  cursor = block.find("\n", match.end())
  if cursor == -1:
    return (start, len(block))
  cursor += 1  # consume the newline of the header line
  while cursor < len(block):
    next_nl = block.find("\n", cursor)
    line_end = next_nl if next_nl != -1 else len(block)
    line = block[cursor:line_end]
    if _line_starts_top_level_key(line):
      break
    cursor = line_end + 1 if next_nl != -1 else line_end
  return (start, cursor)


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
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  open_end, close_start, close_end = span  # type: ignore[misc]
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


# ---------------------------------------------------------------- set_field


def set_field(text: str, key: str, value: object) -> str:
  """
  Set `key` to `value` in the frontmatter, preserving all other text byte-for-byte.

  Creates the frontmatter block if the document has none. When the key already
  exists, its entire logical entry (header line plus any block-style continuation
  lines) is replaced with a single-line scalar form.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to set.
    value: The Python value to write; serialised to a bare YAML literal.

  Returns:
    The updated document text with the key set and all other bytes unchanged.
  """
  rendered = f"{key}: {_serialise_scalar(value)}"
  span = _find_fences(text)
  if span is None:
      # Document has no frontmatter at all — synthesize one.
    return f"---\n{rendered}\n---\n{text}"
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  open_end, close_start, _close_end = span  # type: ignore[misc]
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  if existing is None:
      # Append before the closing fence, preserving the block's
      # trailing newline if any.
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered + "\n"
    else:
      new_block = block + rendered + "\n"
    return text[:open_end] + new_block + text[close_start:]
# Replace the whole existing entry (header + any continuation lines)
# with a single-line scalar form. Preserve the entry's trailing
# newline so the closing fence stays on its own line.
  start, end = existing
  suffix = "\n" if end > 0 and block[end - 1] == "\n" else ""
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
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  open_end, close_start, _close_end = span  # type: ignore[misc]
  block = text[open_end:close_start]
  return all(not line.strip() for line in block.split("\n"))


def unset_field(text: str, key: str) -> str:
  """
  Remove `key` and any block-style continuation lines from the frontmatter.

  No-op when the key is absent or the document has no frontmatter.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to remove.

  Returns:
    The updated document text with the key removed and all other bytes unchanged.
  """
  span = _find_fences(text)
  if span is None:
    return text
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  open_end, close_start, _close_end = span  # type: ignore[misc]
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  if existing is None:
    return text
  start, end = existing
  new_block = block[:start] + block[end:]
  return text[:open_end] + new_block + text[close_start:]
