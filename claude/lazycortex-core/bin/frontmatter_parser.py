"""Minimal YAML frontmatter parser for routine_types.dispatch_md_scan.

Permissive: if frontmatter is missing or malformed, returns {}. Supports
scalar values, blank values (returned as None), and inline arrays via the
`-` line-list shape. Quoted strings are unquoted. Anything more exotic
(nested mappings, anchors, multi-line scalars) is out of scope — the
filter use case is flat key→scalar/list.
"""
from __future__ import annotations


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a flat dict.

    Returns {} when:
      - Text is empty
      - First non-empty line is not exactly '---'
      - Closing '---' is missing
      - A line in the block is unparseable
    """
    if not text:
        return {}

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        return {}

    block = lines[1:close_idx]
    result: dict = {}
    current_key: str | None = None

    for raw in block:
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if indent > 0 and stripped.startswith("- ") and current_key is not None:
            value = _unquote(stripped[2:].strip())
            if not isinstance(result.get(current_key), list):
                result[current_key] = []
            result[current_key].append(value)
            continue

        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value == "":
            result[key] = None
            current_key = key
        else:
            result[key] = _coerce_scalar(value)
            current_key = key

    return result


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _coerce_scalar(s: str):
    s = _unquote(s)
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in ("null", "~"):
        return None
    try:
        if "." not in s:
            return int(s)
        return float(s)
    except ValueError:
        return s
