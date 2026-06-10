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


def _parse_fence_body(block_body: str) -> tuple[list[tuple[bool, str]], list[str]]:
  """
  Split one `diff` fence body into its retained emissions and its retraction targets.

  Each emission carries a `cancellable` flag — `True` for `+` / `!` / unknown lines (the writer's
  own inserted or emphasised content) and `False` for `  ` context lines (the prior body shown
  unchanged for reference). `deletions` lists the contents of `-` lines this fence wants to
  retract; the renderer matches each against a `cancellable` emission from an earlier fence.

  Args:
    block_body: Raw text between the opening `\\u0060\\u0060\\u0060diff` and closing `\\u0060\\u0060\\u0060` fences.

  Returns:
    `(output_lines, deletions)` where `output_lines` is `[(cancellable, content), ...]` and
    `deletions` is `[content, ...]`.
  """
  output_lines: list[tuple[bool, str]] = []
  deletions: list[str] = []
  for raw in block_body.splitlines():
      # A diff line is a 1-char marker ("-"/"+"/"!"/" ") optionally followed
      # by " " + content. A BARE marker (no trailing space) is that marker on
      # an empty line — a deleted / inserted blank line — and folds like its
      # content form (Bug 102): "-" drops; "+"/"!" keep an empty line. raw[2:]
      # already yields "" for a 1-char marker, so the append needs no special-case.
    # guard: a deletion-marked diff line is captured for cross-fence cancellation, then dropped from this fence's output
    if raw == "-" or raw.startswith("- "):
      deletions.append(raw[2:])
      continue
    # guard: an insertion-marked diff line is appended as a cancellable emission
    if raw == "+" or raw.startswith("+ "):
      output_lines.append((True, raw[2:]))
      continue
    # guard: an emphasis-marked diff line is appended as a cancellable emission (same semantics as +)
    if raw == "!" or raw.startswith("! "):
      output_lines.append((True, raw[2:]))
      continue
    # guard: a context line is appended as NOT cancellable (kept verbatim, never targeted by a cross-fence `-`)
    if raw.startswith("  "):
      output_lines.append((False, raw[2:]))
      continue
  # Anything else (e.g. unknown marker): keep verbatim, treat as cancellable.
    output_lines.append((True, raw))
  return output_lines, deletions


def _strip_diff(text: str) -> str:
  """
  Resolve every `diff` fence in `text`, applying cross-fence `+` / `-` cancellation.

  A `- X` line in any fence retracts the FIRST surviving `+ X` (or `! X`) emission from any
  earlier fence (exact byte-for-byte line match, not similarity-based). This is the protocol's
  intended semantics for a writer that revises a prior round's insertion: the writer emits a new
  fence with `- <prior-content> / + <revision>`, and the prior `+ <prior-content>` is removed
  instead of surviving alongside the revision. Context (`  `) emissions are never cancellable —
  they show the surrounding text the writer did not edit, not a writer-emitted change.

  Within-fence semantics are unchanged: a `-` line that does not match any earlier emission is
  silently dropped from its own fence (legacy behaviour for a deletion against plain body prose).

  Args:
    text: Source text containing zero or more `diff` fences.

  Returns:
    Text with each fence span replaced by its surviving emissions, cancelled lines removed, and
    everything outside fences kept byte-for-byte.
  """
  fences = list(_DIFF_FENCE_RE.finditer(text))
  # guard: no fences present — return source verbatim
  if not fences:
    return text
  parsed = [_parse_fence_body(m.group(1)) for m in fences]
  # cancelled[(fence_idx, emit_idx)] — emissions retracted by a later fence's deletion.
  cancelled: set[tuple[int, int]] = set()
  for later_idx, (_, deletions) in enumerate(parsed):
    for del_content in deletions:
        # Find the earliest prior fence with a still-live cancellable emission matching this deletion.
      matched = False
      for earlier_idx in range(later_idx):
        emissions = parsed[earlier_idx][0]
        for emit_idx, (cancellable, content) in enumerate(emissions):
          # guard: non-cancellable / already-cancelled / content mismatch — skip this emission
          if not cancellable or (earlier_idx, emit_idx) in cancelled or content != del_content:
            continue
          cancelled.add((earlier_idx, emit_idx))
          matched = True
          break
        # guard: cancellation done for this deletion — stop scanning earlier fences
        if matched:
          break
  pieces: list[str] = []
  last_end = 0
  for fence_idx, m in enumerate(fences):
    pieces.append(text[last_end:m.start()])
    emissions = parsed[fence_idx][0]
    surviving = [
        content
        for emit_idx, (_, content) in enumerate(emissions)
        if (fence_idx, emit_idx) not in cancelled
    ]
    pieces.append("\n".join(surviving))
    last_end = m.end()
  pieces.append(text[last_end:])
  return "".join(pieces)


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
