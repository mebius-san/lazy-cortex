"""
Surgical rewriter for `iconize_icon` / `iconize_color` frontmatter keys.

Sets, updates, or removes the two managed keys at the top of a Markdown
document while preserving every other byte of the source. No external deps.
"""
from __future__ import annotations

import os
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


_FENCE_RE = re.compile(r"(?ms)\A---[ \t]*\n(.*?\n)^---[ \t]*\n")
_ICON_LINE_RE = re.compile(r"(?m)^iconize_icon:.*\n")
_COLOR_LINE_RE = re.compile(r"(?m)^iconize_color:.*\n")


def _format_icon_line(value: str) -> str:
  """
  Return the canonical YAML line for the `iconize_icon` key.

  Args:
    value: Icon name to embed; expected to match `[A-Za-z0-9_-]+`, emitted bare without quoting.

  Returns:
    A single newline-terminated YAML line of the form `iconize_icon: <value>\n`.
  """
  # Icon names always match [A-Za-z0-9_-]+; emit bare.
  return f"iconize_icon: {value}\n"


def _format_color_line(value: str) -> str:
  """
  Return the canonical YAML line for the `iconize_color` key.

  Args:
    value: Color string to embed; always double-quoted so a leading `#` is not read as a YAML comment.

  Returns:
    A single newline-terminated YAML line of the form `iconize_color: "<value>"\n`.
  """
  # Colors ALWAYS double-quoted so YAML doesn't read `#abc` as a comment.
  return f'iconize_color: "{value}"\n'


def rewrite_frontmatter(text: str, *, icon: str | None, color: str | None) -> str:
  """
  Return a new version of `text` with `iconize_icon` / `iconize_color` set or removed.

  The two managed keys are upserted, removed, or left alone according to `icon` and `color`:

  - A non-`None` value upserts the corresponding key with that value.
  - A `None` value removes the corresponding key if it is present.
  - If no frontmatter block exists and any key needs to be added, a new block is created at the
    top of the document.
  - If removing all managed keys leaves the frontmatter block empty, the entire fence is stripped.
  - When no change is required, the returned string is byte-identical to the input.

  Args:
    icon: New value for `iconize_icon`, or `None` to remove the key.
    color: New value for `iconize_color`, or `None` to remove the key.

  Returns:
    The rewritten document text, or the original `text` if no change was needed.
  """
  m = _FENCE_RE.match(text)
  # guard: no existing frontmatter fence — only act if we have something to add
  if m is None:
    # guard: nothing to add either — return input unchanged
    if icon is None and color is None:
      return text
    lines = []
    if icon is not None:
      lines.append(_format_icon_line(icon))
    if color is not None:
      lines.append(_format_color_line(color))
    return "---\n" + "".join(lines) + "---\n" + text

  # existing fence captured: group(1) is the block body (trailing \n included)
  block = m.group(1)
  rest = text[m.end():]

  # for each managed key: replace in-place if present, else queue for append.
  # removal (None) means strip the line outright.
  new_block = block
  icon_present = bool(_ICON_LINE_RE.search(new_block))
  color_present = bool(_COLOR_LINE_RE.search(new_block))

  # handle icon key — upsert or strip in place
  if icon_present:
    if icon is not None:
      new_block = _ICON_LINE_RE.sub(_format_icon_line(icon), new_block)
    else:
      new_block = _ICON_LINE_RE.sub("", new_block)

  # handle color key — upsert or strip in place
  if color_present:
    if color is not None:
      new_block = _COLOR_LINE_RE.sub(_format_color_line(color), new_block)
    else:
      new_block = _COLOR_LINE_RE.sub("", new_block)

  # append keys that weren't already in the block
  if icon is not None and not icon_present:
    new_block += _format_icon_line(icon)
  if color is not None and not color_present:
    new_block += _format_color_line(color)

  # if the block becomes empty, strip the whole fence
  if new_block.strip() == "":
    new = rest
  else:
    new = "---\n" + new_block + "---\n" + rest

  return new if new != text else text


def rewrite_file(path: Path, *, icon: str | None, color: str | None) -> bool:
  """
  Rewrite the frontmatter of the file at `path` and report whether it changed.

  The file is read as UTF-8 and passed through `rewrite_frontmatter`. When the result differs
  from the input, the file is replaced atomically via a sibling temp file so concurrent readers
  never observe a partial write; when the result matches, the file is left untouched.

  Args:
    path: Path to the Markdown file whose frontmatter should be rewritten.
    icon: New value for `iconize_icon`, or `None` to remove the key.
    color: New value for `iconize_color`, or `None` to remove the key.

  Returns:
    `True` if the file was rewritten on disk, `False` if it already had the desired content.

  Raises:
    OSError: If the file cannot be read, the temp file cannot be written, or the atomic replace
      fails.
  """
  # waiver: stdlib encoding-mode idiom
  src = path.read_text(encoding = "utf-8")
  out = rewrite_frontmatter(src, icon = icon, color = color)
  # guard: no change needed — leave the file untouched
  if out == src:
    return False
  # atomic replace so concurrent readers never see a partial write
  # waiver: filesystem path idiom (.tmp)
  tmp = path.with_suffix(path.suffix + ".tmp")
  # waiver: stdlib encoding-mode idiom
  tmp.write_text(out, encoding = "utf-8")
  os.replace(tmp, path)
  return True
