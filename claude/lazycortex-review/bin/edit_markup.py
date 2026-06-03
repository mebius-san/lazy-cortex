"""Edit-annotation styles for main-writer / section-writer body edits.

Four styles per spec § Edit-annotation styles:

- `simple`   — `~~del~~`, ` ==add== `, `%%note%%`
- `diff`     — ```` ```diff ```` fences with `-`/`+`/`!`/`  ` prefixes
- `criticmarkup` — `{++add++}`, `{--del--}`, `{~~old~>new~~}`,
                     `{>>note<<}`, `{==hi==}`
- `html`     — `<ins>`, `<del>`, `<mark>`, `<!-- comment -->`

Writers MAY produce markup in the configured style; the dispatcher
hands them the chosen style via the request payload's
`edit_marker_style` field (see :mod:`payload`). At finalize time
(spec § Stage 6), the consumer calls :func:`strip_markers` to fold
the markup into the final text.
"""
from __future__ import annotations

import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# -------------------------------------------------------- simple style


_SIMPLE_RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    # Deletions: drop content entirely.
    (re.compile(r"~~(.*?)~~", re.DOTALL), lambda _: ""),
    # Comments (Obsidian hidden): drop the whole span.
    (re.compile(r"%%(.*?)%%", re.DOTALL), lambda _: ""),
    # Insertions: keep content, drop wrappers (with surrounding spaces
    # inside backticks accommodated by writers but not by us).
    (re.compile(r"==(.*?)==", re.DOTALL), lambda m: m.group(1)),
]


def _strip_simple(text: str) -> str:
  for pattern, repl in _SIMPLE_RULES:
    text = pattern.sub(repl, text)
  return text


# --------------------------------------------------------- diff style


# Closing fence consumes only horizontal whitespace on its own line
# (`[ \t]*$`), never the trailing newline(s) — otherwise the blank-line
# separator after the fence collapses and the resolved `+` content glues
# to the next paragraph / heading. (Bug 85.)
_DIFF_FENCE_RE = re.compile(
    r"(?ms)^```diff\s*\n(.*?)\n```[ \t]*$"
)


def _resolve_diff_block(block_body: str) -> str:
  out_lines: list[str] = []
  for raw in block_body.splitlines():
      # A diff line is a 1-char marker ("-"/"+"/"!"/" ") optionally followed
      # by " " + content. A BARE marker (no trailing space) is that marker on
      # an empty line — a deleted / inserted blank line — and folds like its
      # content form (Bug 102): "-" drops; "+"/"!" keep an empty line. raw[2:]
      # already yields "" for a 1-char marker, so the append needs no special-case.
    # guard: a deletion-marked diff line is dropped from the resolved output — skip before any append
    if raw == "-" or raw.startswith("- "):
      continue  # deletion accepted
    if raw == "+" or raw.startswith("+ "):
      out_lines.append(raw[2:])
      continue
    if raw == "!" or raw.startswith("! "):
      out_lines.append(raw[2:])
      continue
    if raw.startswith("  "):
      out_lines.append(raw[2:])
      continue
  # Anything else (e.g. unknown marker): keep verbatim.
    out_lines.append(raw)
  return "\n".join(out_lines)


def _strip_diff(text: str) -> str:
  def repl(match: re.Match[str]) -> str:
    body = match.group(1)
    return _resolve_diff_block(body)

  return _DIFF_FENCE_RE.sub(repl, text)


def _normalize_ws(text: str) -> str:
  """
  Collapse all whitespace runs to a single space and strip leading/trailing whitespace.

  Used to detect `diff` blocks whose `-` and `+` content are semantically identical and differ
  only in line wrapping / blank-count / trailing space.

  Args:
    text: Raw string to normalize.

  Returns:
    The input with every whitespace run replaced by a single space, leading and trailing
    whitespace removed.
  """
  return re.sub(r"\s+", " ", text).strip()


def drop_whitespace_only_diff_fences(text: str) -> str:
  """
  Replace whitespace-only `diff` fences with their resolved content.

  Every `diff` fence whose `-` payload normalize-equals its `+` payload is replaced with the
  resolved (`+`-only) text, without the fence. The writer wrapped a paragraph in `diff` even
  though only whitespace changed; the dispatcher catches this and emits the paragraph raw so the
  operator does not see a fake-edit. (Bug 28.)

  Defensive layer over the writer-protocol rule "do not reflow body you do not semantically
  change" — defends against writers that reflow anyway.

  Args:
    text: Source text possibly containing `diff` fences.

  Returns:
    The input text with whitespace-only `diff` fences replaced by their resolved content;
    real-content fences are left intact.
  """
  def repl(match: re.Match[str]) -> str:
    body = match.group(1)
    minus_lines: list[str] = []
    plus_lines: list[str] = []
    for raw in body.splitlines():
      if raw.startswith("- "):
        minus_lines.append(raw[2:])
      elif raw.startswith("+ "):
        plus_lines.append(raw[2:])
      elif raw.startswith("! "):
        plus_lines.append(raw[2:])
        minus_lines.append(raw[2:])
      elif raw.startswith("  "):
        plus_lines.append(raw[2:])
        minus_lines.append(raw[2:])
    if _normalize_ws("\n".join(minus_lines)) == _normalize_ws("\n".join(plus_lines)):
        # Whitespace-only fence: emit resolved text directly.
      return _resolve_diff_block(body)
  # Real content change: keep the fence intact.
    return match.group(0)
  return _DIFF_FENCE_RE.sub(repl, text)


# ----------------------------------------------------- criticmarkup style


_CRITIC_RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    # Substitution: old~>new — keep new only.
    (re.compile(r"\{~~(.*?)~>(.*?)~~\}", re.DOTALL), lambda m: m.group(2)),
    # Insertion.
    (re.compile(r"\{\+\+(.*?)\+\+\}", re.DOTALL), lambda m: m.group(1)),
    # Deletion.
    (re.compile(r"\{--(.*?)--\}", re.DOTALL), lambda _: ""),
    # Comment.
    (re.compile(r"\{>>(.*?)<<\}", re.DOTALL), lambda _: ""),
    # Highlight.
    (re.compile(r"\{==(.*?)==\}", re.DOTALL), lambda m: m.group(1)),
]


def _strip_criticmarkup(text: str) -> str:
  for pattern, repl in _CRITIC_RULES:
    text = pattern.sub(repl, text)
  return text


# ----------------------------------------------------------- html style


_HTML_RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    # HTML comment.
    (re.compile(r"<!--.*?-->", re.DOTALL), lambda _: ""),
    # Deletion.
    (re.compile(r"<del>(.*?)</del>", re.DOTALL | re.IGNORECASE), lambda _: ""),
    # Insertion.
    (re.compile(r"<ins>(.*?)</ins>", re.DOTALL | re.IGNORECASE), lambda m: m.group(1)),
    # Highlight.
    (re.compile(r"<mark>(.*?)</mark>", re.DOTALL | re.IGNORECASE), lambda m: m.group(1)),
]


def _strip_html(text: str) -> str:
  for pattern, repl in _HTML_RULES:
    text = pattern.sub(repl, text)
  return text


# ------------------------------------------------------------ public api


_STRIPPERS: dict[str, Callable[[str], str]] = {
    "simple": _strip_simple,
    "diff": _strip_diff,
    "criticmarkup": _strip_criticmarkup,
    "html": _strip_html,
}


SUPPORTED_STYLES = tuple(_STRIPPERS.keys())


# A block-level annotation that resolves to nothing — a deletion-only
# `diff` fence (only `-` lines), an entire-paragraph `~~del~~` /
# `{--del--}` / `<del>` span — leaves the blank line *before* it and
# the blank line *after* it both standing, since neither is inside the
# matched markup. `A\n\n` + `""` + `\n\nB` collapses to `A\n\n\n\nB`
# (three blank lines). Markdown renders that as one break, but the
# finalized document carries the gap as literal whitespace. Collapse any
# run of 3+ newlines back to a paragraph break. (Bug 90.)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _collapse_blank_runs(text: str) -> str:
  return _BLANK_RUN_RE.sub("\n\n", text)


def strip_markers(text: str, *, style: str) -> str:
  """
  Fold all edit-annotation markup of the given `style` into final text.

  After folding, blank-line runs left behind by annotations that resolve to nothing are
  normalized to a single paragraph break so the finalized document carries no stray whitespace
  gaps (Bug 90).

  Args:
    text: Source text containing edit-annotation markup.
    style: Annotation style to strip; one of `SUPPORTED_STYLES`.

  Returns:
    The finalized text with all markup folded and blank-line runs collapsed to a single
    paragraph break.

  Raises:
    ValueError: If `style` is not a recognized annotation style.
  """
  try:
    folded = _STRIPPERS[style](text)
  except KeyError as exc:
    raise ValueError(
        f"unknown edit-annotation style {style!r}; "
        f"supported: {', '.join(SUPPORTED_STYLES)}"
    ) from exc
  return _collapse_blank_runs(folded)
