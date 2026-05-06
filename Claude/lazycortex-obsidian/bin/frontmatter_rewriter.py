"""Surgical rewriter for iconize_icon / iconize_color frontmatter keys.

Preserves every other byte of the source file. No external deps.
"""
from __future__ import annotations
import os
import re
from pathlib import Path

_FENCE_RE = re.compile(r"(?ms)\A---[ \t]*\n(.*?\n)^---[ \t]*\n")
_ICON_LINE_RE = re.compile(r"(?m)^iconize_icon:.*\n")
_COLOR_LINE_RE = re.compile(r"(?m)^iconize_color:.*\n")


def _format_icon_line(value: str) -> str:
    # Icon names always match [A-Za-z0-9_-]+; emit bare.
    return f"iconize_icon: {value}\n"


def _format_color_line(value: str) -> str:
    # Colors ALWAYS double-quoted so YAML doesn't read `#abc` as a comment.
    return f'iconize_color: "{value}"\n'


def rewrite_frontmatter(text: str, *, icon: str | None, color: str | None) -> str:
    """Return a new version of `text` with iconize_icon / iconize_color set or removed.

    - icon/color None -> remove that key if present.
    - icon/color str -> upsert with that value.
    - If no frontmatter block exists and we need to add keys, create one.
    - If removing all managed keys leaves the block empty, strip the fence entirely.
    - Returns a string byte-identical to the input when no change is needed.
    """
    m = _FENCE_RE.match(text)
    if m is None:
        # No fence. Only act if adding something.
        if icon is None and color is None:
            return text
        lines = []
        if icon is not None:
            lines.append(_format_icon_line(icon))
        if color is not None:
            lines.append(_format_color_line(color))
        return "---\n" + "".join(lines) + "---\n" + text

    block = m.group(1)  # trailing \n included
    rest = text[m.end():]

    # For each managed key: replace in-place if present, else queue for append.
    # Removal (None) means strip the line outright.
    new_block = block
    icon_present = bool(_ICON_LINE_RE.search(new_block))
    color_present = bool(_COLOR_LINE_RE.search(new_block))

    # Handle icon key
    if icon_present:
        if icon is not None:
            new_block = _ICON_LINE_RE.sub(_format_icon_line(icon), new_block)
        else:
            new_block = _ICON_LINE_RE.sub("", new_block)

    # Handle color key
    if color_present:
        if color is not None:
            new_block = _COLOR_LINE_RE.sub(_format_color_line(color), new_block)
        else:
            new_block = _COLOR_LINE_RE.sub("", new_block)

    # Append keys that weren't already in the block.
    if icon is not None and not icon_present:
        new_block += _format_icon_line(icon)
    if color is not None and not color_present:
        new_block += _format_color_line(color)

    # If the block becomes empty, strip the whole fence.
    if new_block.strip() == "":
        new = rest
    else:
        new = "---\n" + new_block + "---\n" + rest

    return new if new != text else text


def rewrite_file(path: Path, *, icon: str | None, color: str | None) -> bool:
    """Rewrite `path`'s frontmatter. Returns True iff the file was actually written."""
    src = path.read_text(encoding="utf-8")
    out = rewrite_frontmatter(src, icon=icon, color=color)
    if out == src:
        return False
    # Atomic replace so concurrent readers never see a partial write.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    return True
