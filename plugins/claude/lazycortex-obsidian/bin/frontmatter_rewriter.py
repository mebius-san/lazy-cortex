"""
Surgical rewriter for `iconize_icon` / `iconize_color` frontmatter keys.

Sets, updates, or removes the two managed keys at the top of a Markdown
document while preserving every other byte of the source. No external deps.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# opening fence, block (possibly empty, each line newline-terminated), closing fence at a line start
# followed by a newline or end of text; LF and CRLF alike
_FENCE_RE = re.compile(r"(?s)\A(---[ \t]*\r?\n)((?:.*?\n)??)(---[ \t]*(?:\r?\n|\Z))")
# UTF-8 byte-order mark some editors put in front of the whole document
_BOM = "\ufeff"
_ICON_LINE_RE = re.compile(r"(?m)^iconize_icon:.*\n")
_COLOR_LINE_RE = re.compile(r"(?m)^iconize_color:.*\n")
# plain scalars YAML would resolve to a bool, null, or number instead of a string
_YAML_SPECIAL_RE = re.compile(
  r"(?i)(?:true|false|yes|no|on|off|y|n|null|~|[-+]?(?:\.?[0-9][0-9_.eE+-]*|\.inf)|\.nan)")


def _yaml_quoted(value: str) -> str:
  """
  Return `value` as a double-quoted, escaped YAML scalar.

  Args:
    value: Text to encode as a quoted scalar.

  Returns:
    The quoted and escaped representation of `value`, safe to embed directly in a YAML line.
  """
  return json.dumps(value, ensure_ascii = False)


def _needs_quotes(value: str) -> bool:
  """
  Determine whether `value` needs YAML quoting to round-trip as the same string.

  Args:
    value: Candidate scalar text for an `iconize_icon` or `iconize_color` line.

  Returns:
    `True` if emitting `value` as a bare YAML scalar would change its parsed meaning, `False`
    if it can be emitted bare.
  """
  return (value == "" or value != value.strip() or value[0] in "?:,[]{}#&*!|>'\"%@`"
          or value == "-" or value.startswith("- ") or ": " in value or " #" in value
          or value.endswith(":") or any(c < " " or c == "\x7f" for c in value)
          or bool(_YAML_SPECIAL_RE.fullmatch(value)))


def _newline_of(text: str) -> str:
  """
  Return the newline sequence used by the first line of `text`.

  Args:
    text: Document content to inspect.

  Returns:
    `"\\r\\n"` if the first line ends with a carriage return, `"\\n"` otherwise.
  """
  i = text.find("\n")
  return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def _format_icon_line(value: str, nl: str = "\n") -> str:
  """
  Return the canonical YAML line for the `iconize_icon` key.

  Args:
    value: Icon name to embed; quoted only when the raw text needs YAML quoting, otherwise
      emitted bare.
    nl: Newline sequence appended after the key, matching the document's newline convention.

  Returns:
    A single line of the form `iconize_icon: <value>` terminated by `nl`.
  """
  scalar = _yaml_quoted(value) if _needs_quotes(value) else value
  return f"iconize_icon: {scalar}{nl}"


def _format_color_line(value: str, nl: str = "\n") -> str:
  """
  Return the canonical YAML line for the `iconize_color` key.

  Args:
    value: Color string to embed; double-quoted and escaped so a leading `#` isn't read as a
      comment.
    nl: Newline sequence appended after the key, matching the document's newline convention.

  Returns:
    A single line of the form `iconize_color: "<value>"` terminated by `nl`.
  """

  # Domain(obsidian.icon-repaint):
  # # Icon and color value encoding
  # An icon name is written as a bare YAML scalar whenever that text reads back unchanged; it is
  # quoted and escaped only when the bare form would be misread — as a different type, as broken
  # syntax, or with leading or trailing content lost. A color value is always quoted and escaped,
  # because color values are hex codes that start with a hash sign, and an unquoted `#` at the
  # start of a YAML scalar reads as a comment marker and would silently drop everything after it.

  # Colors ALWAYS double-quoted so YAML doesn't read `#abc` as a comment.
  return f"iconize_color: {_yaml_quoted(value)}{nl}"


def rewrite_frontmatter(text: str, *, icon: str | None, color: str | None) -> str:
  """
  Return a new version of `text` with `iconize_icon` / `iconize_color` set or removed.

  The two managed keys are upserted, removed, or left alone according to `icon` and `color`:

  - A non-`None` value upserts the corresponding key with that value.
  - A `None` value removes the corresponding key if it is present.
  - If no frontmatter block exists and any key needs to be added, a new block is created at the
    top of the document.
  - If removing all managed keys leaves the frontmatter block empty, the entire fence is stripped.
  - An existing frontmatter block that is already empty is recognized the same as one with content.
  - A closing fence with no trailing newline, when the frontmatter fence ends the document, is
    recognized as valid.
  - When no change is required, the returned string is byte-identical to the input.

  Guarantees:
    - Every byte outside the `iconize_icon` / `iconize_color` lines is preserved unchanged.
    - When neither key needs to change, the returned string is byte-identical to `text`.
    - If removing the managed keys leaves the frontmatter block with no other content, the
      entire fence is dropped rather than kept as an empty shell.
    - Each written `iconize_icon` / `iconize_color` line is a valid YAML scalar, quoted and
      escaped whenever a bare scalar would be misread as a different type or break the line.
    - An existing frontmatter fence is recognized whether its block is empty, its lines end in
      CRLF, its closing fence ends the document with no trailing newline, or the document opens
      with a byte-order mark; a document that already carries a fence never ends up with a
      second one, and a leading byte-order mark stays the first character of the result.
    - Newly inserted or replaced key lines use the same newline convention, LF or CRLF, as the
      rest of `text`.

  Args:
    text: Document content to rewrite, including any existing frontmatter fence and body.
    icon: New value for `iconize_icon`, or `None` to remove the key.
    color: New value for `iconize_color`, or `None` to remove the key.

  Returns:
    The rewritten document text, or the original `text` if no change was needed.
  """

  # Domain(obsidian.icon-repaint):
  # # Managed-key frontmatter surgery
  # Repainting a note's icon or color touches only the two managed keys that carry that state;
  # every other line in the frontmatter block and the entire document body stay byte-for-byte
  # identical. Setting a key writes or replaces its single line; clearing a key removes that line
  # outright, and if clearing leaves the frontmatter block with nothing left in it, the whole
  # fence is dropped rather than kept as an empty shell. A note with no frontmatter yet only gets
  # a new block created when there is actually something to add, and a note that already carries
  # a frontmatter block never gains a second one alongside it. An existing block is recognized as
  # such whether it is empty, its lines end with a carriage return and line feed, or its closing
  # fence is the note's last line with no trailing newline after it. When the note opens with a
  # byte-order mark, that mark stays the very first character of the result, and the fence is
  # recognized in the text that follows it. When nothing changes, the result is the exact same
  # text the caller passed in, so a plain equality check tells a caller whether a rewrite
  # happened.

  # Contract:
  # Every byte of `text` that lies outside the `iconize_icon` / `iconize_color` lines MUST be
  # preserved unchanged, including the rest of the frontmatter block and the entire document body.

  # Contract:
  # When neither key needs to change, the returned string MUST be byte-identical to `text`, so
  # callers can detect a no-op rewrite with a plain equality check.

  # Contract:
  # Every `iconize_icon` / `iconize_color` line this function writes MUST be a valid YAML
  # scalar — quoted and escaped whenever the raw value would otherwise be read as a different
  # type or break the line, left bare otherwise.

  # Contract:
  # An existing frontmatter fence MUST be recognized whether its block is empty, its lines end
  # in CRLF, its closing fence is the last line of the document with no trailing newline, or the
  # document opens with a UTF-8 byte-order mark; a document that already carries a frontmatter
  # fence MUST NEVER end up with a second one added on top of it, and a leading byte-order mark
  # MUST remain the first character of the result rather than being preceded by a fence.

  # guard: a leading byte-order mark stays in front; the fence is detected and written after it
  if text.startswith(_BOM):
    return _BOM + rewrite_frontmatter(text[len(_BOM):], icon = icon, color = color)

  # locate an existing fence and the document's newline convention
  m = _FENCE_RE.match(text)
  nl = _newline_of(text)

  # guard: no existing frontmatter fence — only act if we have something to add
  if m is None:
    # guard: nothing to add either — return input unchanged
    if icon is None and color is None:
      return text
    lines = []
    if icon is not None:
      lines.append(_format_icon_line(icon, nl))
    if color is not None:
      lines.append(_format_color_line(color, nl))
    return "---" + nl + "".join(lines) + "---" + nl + text

  # existing fence captured: the block is the block body (trailing newline included, may be empty)
  opening, block, closing = m.groups()
  rest = text[m.end():]

  # for each managed key: replace in-place if present, else queue for append.
  # removal (None) means strip the line outright.
  new_block = block
  icon_present = bool(_ICON_LINE_RE.search(new_block))
  color_present = bool(_COLOR_LINE_RE.search(new_block))

  # handle icon key — upsert or strip in place
  if icon_present:
    if icon is not None:
      new_block = _ICON_LINE_RE.sub(lambda _: _format_icon_line(icon, nl), new_block)
    else:
      new_block = _ICON_LINE_RE.sub("", new_block)

  # handle color key — upsert or strip in place
  if color_present:
    if color is not None:
      new_block = _COLOR_LINE_RE.sub(lambda _: _format_color_line(color, nl), new_block)
    else:
      new_block = _COLOR_LINE_RE.sub("", new_block)

  # append keys that weren't already in the block
  if icon is not None and not icon_present:
    new_block += _format_icon_line(icon, nl)
  if color is not None and not color_present:
    new_block += _format_color_line(color, nl)

  # guard: managed keys already hold the requested values — return input unchanged
  if new_block == block:
    return text

  # Contract:
  # If removing the managed keys leaves the frontmatter block with no other content, the entire
  # `---` fence MUST be dropped rather than kept as an empty shell.

  # if the block becomes empty, strip the whole fence
  if new_block.strip() == "":
    new = rest
  else:
    new = opening + new_block + closing + rest

  # the reassembled document is the result; callers compare it with the input to detect a no-op
  return new if new != text else text


def _write_in_place(target: Path, data: bytes) -> None:
  """
  Overwrite an existing note's content in place, restoring its original bytes if the write fails.

  Args:
    target: Real path of the existing note to overwrite.
    data: Encoded bytes of the new content.

  Raises:
    OSError: If the new content cannot be written; the original bytes are back on disk first.
  """
  original = target.read_bytes()
  try:
    # write over the old bytes, cut the old tail, then flush to disk — the note keeps its inode and mode
    with open(target, "r+b") as handle:
      handle.write(data)
      handle.truncate()
      handle.flush()
      os.fsync(handle.fileno())
  except BaseException:
    # a failed write (full disk, file-size limit) must not leave a truncated note: put the old bytes back
    with open(target, "r+b") as handle:
      handle.write(original)
      handle.truncate()
      handle.flush()
      os.fsync(handle.fileno())
    raise


def rewrite_file(path: Path, *, icon: str | None, color: str | None) -> bool:
  """
  Rewrite the frontmatter of the file at `path` and report whether it changed.

  The file is read as UTF-8 and passed through `rewrite_frontmatter`. When the result differs
  from the input, the file is replaced atomically via a uniquely created sibling temp file so
  concurrent readers never observe a partial write, except when the note's directory refuses to
  create that temp file, in which case the note is rewritten in place instead; when the result
  matches, the file is left untouched.

  Guarantees:
    - A reader that opens the file while the rewrite is in progress observes either the
      complete original content or the complete new content, never a partial write, except when
      the directory refuses to create the temp file. On that path the note is rewritten in
      place; a failed in-place write restores the note's previous bytes before the error
      propagates, but a concurrent reader may still observe a partial write while it is in
      progress, and a process crash mid-write, as opposed to a raised exception, can still
      leave partial content.
    - If anything fails after the temporary file is created but before it replaces the note,
      the temporary file is removed and the note on disk is left unchanged.
    - If the computed content matches what is already on disk, the file is left untouched — no
      write occurs and its modification time is not changed.
    - The file's permission bits are unchanged after a rewrite.
    - If `path` is a symlink, its target file is replaced in place and the symlink itself is
      preserved.
    - CRLF line endings present in the original file are preserved in the rewritten content.

  Args:
    path: Path to the Markdown file whose frontmatter should be rewritten.
    icon: New value for `iconize_icon`, or `None` to remove the key.
    color: New value for `iconize_color`, or `None` to remove the key.

  Returns:
    `True` if the file was rewritten on disk, `False` if it already had the desired content.

  Raises:
    OSError: If the file cannot be read, the temp file cannot be written after it is created,
      the atomic replace fails, or the in-place fallback write fails when the directory refuses
      to create a temp file.
  """

  # Contract:
  # CRLF line endings present in the original file MUST be preserved in the rewritten content.

  # read bytes so CRLF line endings survive untranslated
  # waiver: stdlib encoding-mode idiom
  src = path.read_bytes().decode("utf-8")
  out = rewrite_frontmatter(src, icon = icon, color = color)

  # Contract:
  # If the computed content matches what is already on disk, the file MUST be left untouched —
  # no write occurs and its modification time is not changed.

  # guard: no change needed — leave the file untouched
  if out == src:
    return False

  # Contract:
  # A reader that opens the file while the rewrite is in progress MUST observe either the
  # complete original content or the complete new content, never a partial write, except when
  # the note's directory refuses to create the temp file: on that path the note is rewritten in
  # place, and a failed in-place write MUST restore the note's previous bytes before the
  # exception propagates. That in-place path is NOT atomic — a concurrent reader MAY observe a
  # partial write while it is in progress, and a process crash mid-write, as opposed to a raised
  # exception, can still leave partial content.

  # Contract:
  # When `path` is a symlink, the write MUST go through to the file it resolves to, and the
  # symlink itself MUST remain in place afterward.

  # Contract:
  # The file's permission bits MUST be unchanged by a rewrite.

  # Domain(obsidian.icon-repaint):
  # # Atomic repaint write
  # A repainted note is never edited in place when its folder allows a sibling file to be
  # created. The new content goes to a freshly created sibling file with a name no existing
  # file could already hold, and is then swapped into the note's place with a single rename, so
  # a reader that opens the note mid-write always sees either the old content or the new content
  # in full, never a partially written file. If anything goes wrong before that swap, the
  # sibling is discarded and the note on disk stays exactly as it was. Only when the note's
  # folder refuses to let a sibling file be created, and the note itself can still be written,
  # is the note rewritten in place instead — the one path on which a reader may briefly observe
  # a partial file. The rewrite carries the note's permission mode and line-ending convention
  # forward unchanged. A note that is a symlink is repainted by writing through the link to the
  # file it points at, leaving the link itself in place. A note whose content would not change
  # after repaint is left untouched on disk entirely.

  # atomic replace so concurrent readers never see a partial write; a symlink is written through
  # to its target, and the target keeps its permission bits
  target = path.resolve()
  # waiver: stdlib encoding-mode idiom
  payload = out.encode("utf-8")

  # Decision: rewrite in place, not fail — a directory that refuses a sibling file still lets the
  # writable note be repainted; atomicity is lost only on that path

  # Contract:
  # If anything fails after the temporary file is created but before it replaces the note, the
  # temporary file MUST be removed and the note on disk MUST be left unchanged.

  # a uniquely named hidden sibling, created exclusively, so no existing file is ever reused
  try:
    # waiver: filesystem path idiom (.tmp)
    fd, tmp = tempfile.mkstemp(dir = target.parent, prefix = f".{target.name}.", suffix = ".tmp")
  except PermissionError:
    _write_in_place(target, payload)
    return True

  # the unique temp file is filled, given the note's mode, and swapped in; any failure removes it
  try:
    with open(fd, "wb") as handle:
      handle.write(payload)
      handle.flush()
      os.fsync(handle.fileno())
    os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
    os.replace(tmp, target)
  except BaseException:
    os.unlink(tmp)
    raise
  return True
