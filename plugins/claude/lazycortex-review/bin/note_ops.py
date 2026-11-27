"""
Deterministic read/write primitives for one review document.

The `parse-note` report (`build_report`) is what the `spec.coordinator`-style watch worker and
coordinator agent read to decide what a review document needs next, without re-implementing
frontmatter / banner / section parsing themselves. Structural breakage (no frontmatter, or a
malformed one) is reported as `parse_failed: true` rather than raised — a caller dispatches on
the dict shape, never wraps the call in a try/except.

Report shape (see `build_report`):

    {
      "parse_failed": bool,
      "frontmatter": {<ReviewKey>: bool | int | str},
      "unknown_review_keys": [str, ...],
      "banner": {"present": bool, "state_tag": str | None, "gestures": [{"label", "ticked", "kind"}]},
      "sections": [{"title": str, "owner_tag": str}],
      "callouts": [{"type": str, "tag": str, "line": int, "body": str}],
      "ticked_question_options": [{"callout_line": int, "option": str}],
      "multi_ticked_questions": [{"callout_line": int}],
      "both_ticked_candidates": [{"callout_line": int}],
      "send_back_items": [{"line": int, "text": str, "ticked": bool}],
      "job_markers": {"coordinator_job": str | None, "active_job": str | None,
                      "pending_wake": str | None},
    }

`callouts`, `ticked_question_options` and `multi_ticked_questions` list only callouts outside code fences and
foreign `#protected/...` sections, and every `line` is the callout's own line in the document. A question with
exactly one ticked option reports that option under `ticked_question_options`; a question with several ticked options
reports none of them there and is listed under `multi_ticked_questions` instead, since several ticks are no answer.
A `[!decision-candidate]` with both its accept and reject boxes ticked decides nothing and is listed under
`both_ticked_candidates`, outside code fences and foreign `#protected/...` sections alike.

Each banner gesture's `kind` is derived from the checkbox's position inside the banner callout, never from its
label, so every banner language yields the same kinds. Which kinds the boxes can carry is decided by the document's
review class, never by the banner text. For a plain class the ready state's closed set is `approve`,
`approve-autorun`, and `approve-skip-validation` (the first, second, and third box, as in
`banner.READY_GESTURE_KINDS`). For a report class the ready banner carries two boxes whose closed set is `accept` and
`fix` (the first and the second box, as in `banner.READY_REPORT_GESTURE_KINDS`). A box beyond the last known
position, any box in a non-ready state, every box of a banner that contradicts the class (a report class under a
title that is not the report title, a plain class under a report banner), and both boxes of a report banner ticked at
once (neither is a decision) report `kind: null`. When the class is unknown, every box of every banner reports
`kind: null`.
Every checkbox is reported in banner order with its `ticked` flag, so two simultaneous ticks both appear and
resolving them is the caller's job.

`job_markers` is the one block that does not come from the document's own bytes: the review
loop's job markers are runtime state in `job_markers.py`'s sidecar, not frontmatter, and they
ride along here so one `parse-note` call still shows the coordinator the whole picture.

`set_key`, `repaint_banner`, `strip_open_command`, `clear_multi_ticked_questions` and `clear_both_ticked_candidates`
are mutating writers over the same document. The first two raise `ParseError` on a malformed frontmatter block rather
than reporting it in a return value; the others return the text unchanged instead of raising.
"""
from __future__ import annotations

from typing import NamedTuple

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import doc_class as _doc_class  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import send_back as _send_back  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import ParseError, SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import (  # noqa: E402
    AutorunState, Bucket, CoreCommand, JobKey, JobMarker, LangId, Phase, ReportVerdictKind, ReviewKey, Tag,
)


# The closed `review_*` frontmatter schema (spec § Frontmatter schema) — any `review_`-prefixed
# key outside this set surfaces in the report as `unknown_review_keys` instead of `frontmatter`.
_KNOWN_REVIEW_KEYS = frozenset({
    ReviewKey.ACTIVE, ReviewKey.ROUND, ReviewKey.APPROVED, ReviewKey.PHASE, ReviewKey.RESULT,
    ReviewKey.MARKER_STYLE, ReviewKey.MAIN_DONE, ReviewKey.EXPERT, ReviewKey.VALIDATION_ROUND,
    ReviewKey.SKIP_VALIDATION, ReviewKey.AUTORUN, ReviewKey.AUTORUN_CYCLES,
})
_BOOL_REVIEW_KEYS = frozenset({ ReviewKey.ACTIVE, ReviewKey.APPROVED, ReviewKey.SKIP_VALIDATION })
_INT_REVIEW_KEYS = frozenset({ ReviewKey.ROUND, ReviewKey.VALIDATION_ROUND, ReviewKey.AUTORUN_CYCLES })

# The closed value set `set_key` accepts for `review_autorun`.
_AUTORUN_STATES = frozenset({ AutorunState.RUNNING, AutorunState.CLEAN, AutorunState.CAP, AutorunState.QUESTION })

# Banner-state tags (`banner.State` values) are reported via `banner`, never duplicated in
# `callouts` — computed from the enum so a future banner state stays in sync automatically.
_BANNER_STATE_TAGS = frozenset(state.value for state in _banner.State)

# Maps a `review_phase` frontmatter value to the `waiting_context` label
# `banner._WAITING_CONTEXT_LABELS` renders a distinct title for. Not an identity map: the
# frontmatter value for the finalize stage is `banner.State.FINALIZING.value` ("finalizing"),
# while the waiting-context label banner.py recognises for it is `Phase.FINALIZE` ("finalize")
# — two different token spaces that happen to coincide for `validators` / `terminals`. Any
# other phase (main, awaiting-operator, bootstrapping, absent) falls back to the main-writer
# label in `waiting_context_for_phase`.
_WAITING_CONTEXT_BY_PHASE = {
    Bucket.VALIDATORS: Bucket.VALIDATORS,
    Bucket.TERMINALS: Bucket.TERMINALS,
    _banner.State.FINALIZING.value: Phase.FINALIZE,
}

# A `- [ ]` / `- [x]` checkbox line inside the banner region, e.g. `> - [x] approve the whole
# document`. Scoped to the region before the first H1 (the banner's own territory).
_GESTURE_RE = re.compile(r"^>\s*-\s*\[([ xX])\]\s*(.+)$", re.MULTILINE)

# Any `[!<marker>] ... #review/<tag>` callout head line, whatever the marker (`todo`, `question`,
# `attention`, ...) and whatever the review tag; captures the marker and the tag. Only spaces, tabs and a CRLF line's
# carriage return may trail the tag, so the match never runs past the head line's own end into a blank line below it.
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!(\w+)\][^#\n]*#review/([a-z-]+)[ \t\r]*$", re.MULTILINE)

# A ticked option line inside a callout block, once its leading `> ` quote prefix is stripped.
_TICKED_OPTION_RE = re.compile(r"^-\s*\[[xX]\]\s*(.+)$")

# A decision-candidate callout's head line; the type token alone is its identity, it carries no review tag.
_CANDIDATE_HEAD_RE = re.compile(r"^>\s*\[!decision-candidate\]", re.MULTILINE)

# A checkbox option line inside a callout block, once its leading `> ` quote prefix is stripped.
_OPTION_RE = re.compile(r"^-\s*\[[^\]\n]*\]")

# The ticked checkbox of a quoted option line, captured up to the tick so the tick alone is replaced.
_QUOTED_TICK_RE = re.compile(r"^(>\s*-\s*\[)[xX](\])")
# What `_QUOTED_TICK_RE` puts back: the checkbox with a space where its tick stood.
_UNTICKED_BOX = r"\1 \2"

_QUOTE_PREFIX_RE = re.compile(r"^>\s?")

# One line of a document with its `\n` kept, the last line possibly without one; no other character ends a line.
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+$")

# The checkbox-ticked marker character `_GESTURE_RE` / `_TICKED_OPTION_RE` capture.
_TICK_CHAR = "x"

# The `[!question]` marker and `#review/question` tag value — the only callout kind whose block
# is also scanned for ticked options.
_QUESTION_MARKER = "question"

# The `[!todo]` marker and `#review/command` tag of the operator's command callout.
_COMMAND_MARKER = "todo"
_COMMAND_TAG = f"{Tag.REVIEW_PREFIX}command"

# The vault settings file `resolve_language` walks up to; the shipped floor it returns when
# none is found is `keys.LangId.EN`.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
# Core CLI flag naming the repository root the language verb reads.
_ARG_CWD = "--cwd"


# ----------------------------------------------------------------------------------------
class _CommandSpotRecord(NamedTuple):
  """
  Where a document's open operator command callout sits, with its text.

  Attributes:
    head: Zero-based index of the callout's head line in the full document text.
    body: The callout's text, quote prefixes stripped, as the `parse-note` report gives it.
  """

  head: int
  body: str



# ----------------------------------------------------------------------------------------
def _coerce_known_value(key: str, raw: str) -> bool | int | str:
  """
  Coerce a raw frontmatter string to the type its `ReviewKey` carries.

  Args:
    key: A member of `_KNOWN_REVIEW_KEYS`.
    raw: The raw string value `frontmatter.parse` read for `key`.

  Returns:
    `bool` for the flag keys, `int` for the counter keys (falling back to the
    raw string when it isn't numeric), and the raw string for everything else.
  """
  if key in _BOOL_REVIEW_KEYS:
    # waiver: the bare YAML boolean literal frontmatter.py's own `_serialise_scalar` writes
    return raw.strip().lower() == "true"
  if key in _INT_REVIEW_KEYS:
    stripped = raw.strip()
    return int(stripped) if stripped.lstrip("-").isdigit() else stripped
  return raw


def _strip_quote_prefix(line: str) -> str:
  """
  Return `line` with its leading `>` blockquote marker (and one following space) removed.

  Args:
    line: A single line of callout text, still carrying its `> ` prefix.

  Returns:
    The line with the prefix stripped.
  """
  return _QUOTE_PREFIX_RE.sub("", line, count = 1)


def _find_all_callout_lines(body: str, start: int) -> list[str]:
  """
  Collect the consecutive `>`-prefixed lines of a callout, starting at `start`.

  Args:
    body: Document body text to slice from.
    start: Character offset into `body` immediately after the callout's head line.

  Returns:
    The block's continuation lines (head line excluded), still carrying their `>` prefix and without any trailing
    carriage return.
  """
  # only `\n` ends a line, so a Unicode line separator inside a quoted line never cuts the block short; a CRLF
  # line's carriage return is not part of its text
  collected: list[str] = []
  for line in body[start:].split("\n"):
    # guard: the first line without a `>` prefix ends the callout block
    if not line.startswith(">"):
      break
    collected.append(line.removesuffix("\r"))
  return collected


def _line_number(text: str, offset: int) -> int:
  """
  Return the 1-indexed line number of `offset` within `text`.

  Args:
    text: Full document text the offset is measured against.
    offset: Character offset into `text`.

  Returns:
    The 1-indexed line number containing `offset`.
  """
  return text.count("\n", 0, offset) + 1


def _build_empty_banner_report() -> dict:
  """
  Return the default `banner` report block for a document with no detected banner.

  Returns:
    Dict with `present: False`, `state_tag: None`, and an empty `gestures` list.
  """
  return { "present": False, "state_tag": None, "gestures": [] }


def _build_banner_report(body: str, report: bool | None) -> dict:
  """
  Build the `banner` report block for one document.

  Args:
    body: Document body text (post-frontmatter) to scan for the banner and its gestures.
    report: Whether the document's review class is a report class, or `None` when the class is unknown.

  Returns:
    Dict with `present`, `state_tag`, and `gestures` — see module docstring. Gestures come only from the banner
    callout block itself, never from a question or any other callout before the first H1. Each gesture's `kind`
    follows the checkbox's position among the ready banner's checkboxes (so every language's banner reports the
    same kinds), as the document's class reads them: the approve kinds for a plain class, `accept` and `fix` for a
    report class. It is `None` for a checkbox past the last known position, for every checkbox of a banner that is
    not the ready one, for every checkbox of a banner that contradicts the class, for both checkboxes of a report
    banner ticked at once, and for every checkbox when the class is unknown.
  """
  state = _banner.extract(body)

  # guard: no banner present — nothing further to report
  if state is None:
    return _build_empty_banner_report()

  # only the banner callout's own lines are gestures: a question or any other callout near the
  # banner, before the first H1 or in a document with none, never reads as one
  banner_block = _banner.extract_block(body)

  # a checkbox's gesture kind follows its position among the ready banner's checkboxes, never
  # its label, so every language's banner reports the same kinds; the document's class decides which kinds the
  # boxes can carry, and a checkbox past the last known position, on a banner that is not the ready one, or on a
  # document whose class is unknown has no kind
  is_ready = state is _banner.State.READY and report is not None
  kinds = _banner.ready_gesture_kinds(banner_block, report = bool(report)) if is_ready else ()
  gestures = [
      {
          "label": match.group(2).strip(),
          "ticked": match.group(1).lower() == _TICK_CHAR,
          "kind": kinds[index] if index < len(kinds) else None,
      }
      for index, match in enumerate(_GESTURE_RE.finditer(banner_block))
  ]
  return { "present": True, "state_tag": state.value, "gestures": gestures }


def _build_sections_report(text: str) -> list[dict]:
  """
  Build the `sections` report block — every H1 section carrying a 2-part `#expert/...` tag.

  Args:
    text: Full document text to parse into sections.

  Returns:
    List of `{"title", "owner_tag"}` dicts, one per owned section, in document order.
  """
  sections = []
  for section in _parser.parse(text).sections:
    owner = _body.owner_of_section(section.content)

    # guard: an untagged (or non-`#expert/`-tagged) section carries no ownership to report
    if owner is None:
      continue
    flat_name, section_id = owner
    sections.append({ "title": section.title, "owner_tag": f"{Tag.EXPERT_PREFIX}{flat_name}/{section_id}" })
  return sections


def _blank_inert_regions(body: str) -> str:
  """
  Blank out the parts of a document body that can hold no live review callout.

  Args:
    body: Document body text.

  Returns:
    `body` with every foreign protected section and every fenced code block replaced by empty lines, the line count
    kept, so a line number counted on the result names the same line in `body`.
  """
  # a protected section is lifted out, then put back as the same number of empty lines as it held
  lifted, saved = _body.split_out_protected_sections(body)
  blanked = _body.restore_protected_sections(lifted, [ "\n" * section.count("\n") for section in saved ])

  # fenced text is literal: its lines read as empty too
  return _parser.strip_code_fences(blanked)


def _build_callout_reports(text: str, body: str) -> tuple[list[dict], list[dict], list[dict]]:
  """
  Build the `callouts`, `ticked_question_options` and `multi_ticked_questions` report blocks.

  Args:
    text: Full document text, used to compute absolute line numbers.
    body: Document body text to scan for `#review/<tag>` callouts.

  Returns:
    A `(callouts, ticked_question_options, multi_ticked_questions)` tuple.
  """

  # Domain(review.markup):
  # # Only live callouts are review signals
  # A callout shown inside a code fence is example text, and a callout inside a section another plugin owns is that
  # plugin's content. Neither is a question, a command or any other signal to the review loop, so neither is
  # reported, acted on or checked against the review's own vocabulary. Every callout that is reported keeps the line
  # it stands on in the document as the operator sees it.

  # fenced and protected regions read as empty lines, so offsets in the scan count lines exactly as the document does
  fm_text = text[: len(text) - len(body)]
  scan = _blank_inert_regions(body)
  callouts: list[dict] = []
  ticked_question_options: list[dict] = []
  multi_ticked_questions: list[dict] = []
  for match in _CALLOUT_HEAD_RE.finditer(scan):
    marker, tag = match.group(1), match.group(2)

    # guard: a banner-state tag is reported via `banner`, never duplicated here
    if tag in _BANNER_STATE_TAGS:
      continue

    # gather the callout's block (head line's own end through its trailing `>` lines) and turn
    # it into the plain-text `body` this callout reports
    head_line_end = scan.find("\n", match.end())
    head_line_end = len(scan) if head_line_end == -1 else head_line_end + 1
    block_lines = _find_all_callout_lines(scan, head_line_end)
    callout_body = "\n".join(_strip_quote_prefix(line) for line in block_lines).strip()
    line_no = _line_number(fm_text + scan, len(fm_text) + match.start())
    callouts.append({
        "type": marker, "tag": f"{Tag.REVIEW_PREFIX}{tag}", "line": line_no, "body": callout_body,
    })

    # guard: ticked options only matter inside a `[!question] ... #review/question` callout
    if marker != _QUESTION_MARKER or tag != _QUESTION_MARKER:
      continue

    # Domain(review.markup):
    # # Several ticks on one question are no answer
    # The options of a question exclude one another, so a question the operator ticked more than once carries no
    # answer: none of the ticked options is applied. Such a question is reported apart from the answered ones, so
    # its ticks can be cleared and the operator told to tick one; a question with exactly one tick is answered by
    # that option as before.

    # the question's ticked options, each against the question's head line
    ticked = [
        opt_match.group(1).strip() for raw_line in block_lines
        if (opt_match := _TICKED_OPTION_RE.match(_strip_quote_prefix(raw_line)))
    ]

    # guard: several ticks answer nothing — the question is listed apart and none of its options is reported
    if len(ticked) > 1:
      multi_ticked_questions.append({ "callout_line": line_no })
      continue
    ticked_question_options.extend({ "callout_line": line_no, "option": option } for option in ticked)
  return callouts, ticked_question_options, multi_ticked_questions


def _build_candidate_report(text: str, body: str) -> list[dict]:
  """
  Build the `both_ticked_candidates` report block.

  Args:
    text: Full document text, used to compute absolute line numbers.
    body: Document body text to scan for decision-candidate callouts.

  Returns:
    One `{"callout_line"}` entry per decision-candidate outside code fences and foreign protected sections whose
    accept and reject boxes are both ticked, in document order.
  """

  # Domain(review.markup):
  # # Both boxes of a decision candidate ticked decide nothing
  # A decision candidate is accepted or rejected, never both, so a candidate the operator ticked both ways carries no
  # decision: neither branch is taken, the candidate stays open, and it is reported apart so its ticks can be cleared
  # and the operator told to tick one. A candidate with exactly one tick is decided by that tick.

  # fenced and protected regions read as empty lines, so the head line counts as the document does
  fm_text = text[: len(text) - len(body)]
  scan = _blank_inert_regions(body)
  entries: list[dict] = []
  for match in _CANDIDATE_HEAD_RE.finditer(scan):
    head_line_end = scan.find("\n", match.end())
    head_line_end = len(scan) if head_line_end == -1 else head_line_end + 1
    ticks = [
        line for line in _find_all_callout_lines(scan, head_line_end)
        if _TICKED_OPTION_RE.match(_strip_quote_prefix(line))
    ]

    # one tick or none is a decision, or none yet, and is not listed
    if len(ticks) < 2:
      continue
    entries.append({ "callout_line": _line_number(fm_text + scan, len(fm_text) + match.start()) })
  return entries


def _build_send_back_report(text: str, body: str) -> list[dict]:
  """
  Build the report entries of the document's send-back items.

  Args:
    text: Full document text, frontmatter included.
    body: The part of `text` after the frontmatter.

  Returns:
    One entry per send-back item in document order, with its line counted from the top of `text`.
  """
  # an item's line is counted from the top of the whole text, frontmatter lines included, as a callout's is
  body_offset = text[: len(text) - len(body)].count("\n")
  return [
      { "line": body_offset + item.line, "text": item.text, "ticked": item.ticked }
      for item in _send_back.find_all_send_back_items(body)
  ]


def build_report(
    text: str, job_markers: dict[str, str | None] | None = None, *, report: bool | None = False,
) -> dict:
  """
  Parse a review document into the structural report the coordinator and watch worker act on.

  Guarantees:
    - When `parse_failed` is `True`, every field read from the document is empty (or its empty shape), and
      `job_markers` passes through from the sidecar as given.
    - `callouts`, `ticked_question_options`, `multi_ticked_questions` and `both_ticked_candidates` never list a
      callout inside a code fence or a foreign `#protected/...` section, and every listed callout's `line` is its
      line in `text`.

  Args:
    text: Full document text to inspect.
    job_markers: The document's runtime marker entry from `job_markers.read`, reported
      verbatim under `job_markers`. Defaults to the all-absent entry, which is what a caller
      reading a bare text snapshot (a pre-commit blob, a test fixture) has.
    report: Whether the document's review class is a report class, from the caller's own class lookup, or `None`
      when the class cannot be resolved, which leaves every banner box without a kind. Selects which kinds the
      banner's boxes can carry.

  Returns:
    Dict with `parse_failed`, `frontmatter`, `unknown_review_keys`, `banner`, `sections`,
    `callouts`, `ticked_question_options`, `multi_ticked_questions`, `both_ticked_candidates`, `send_back_items`,
    and `job_markers` — see module docstring for the exact shape. `parse_failed` is `True` when the document
    carries no frontmatter block (or a malformed one), in which case every field read from the document is empty
    (`banner` takes its empty shape) and `job_markers` passes through as given.
  """
  markers = dict(job_markers) if job_markers is not None else _job_markers.empty_entry()
  try:
    meta, body = _fm.parse(text)
  except ParseError:
    meta, body = {}, ""

  # Contract:
  # When `parse_failed` is True, every field read from the document is empty (or its empty shape),
  # and `job_markers` passes through from the sidecar as given.

  # Contract:
  # `callouts`, `ticked_question_options`, `multi_ticked_questions` and `both_ticked_candidates` NEVER list a
  # callout inside a code fence or inside a foreign protected section, and every listed callout's `line` is its
  # line in `text`. The coordinator acts on these entries (`clear-multi-ticks` on the last two), the audit checks
  # their tags, and the command wake, `strip-command` and the operator-text attribution all read the open command
  # from them; a fenced example listed here would be acted on as a live signal.

  # guard: no usable frontmatter — the document is structurally broken for review purposes
  if not meta:
    return {
        "parse_failed": True,
        "frontmatter": {},
        "unknown_review_keys": [],
        "banner": _build_empty_banner_report(),
        "sections": [],
        "callouts": [],
        "ticked_question_options": [],
        "multi_ticked_questions": [],
        "both_ticked_candidates": [],
        "send_back_items": [],
        "job_markers": markers,
    }

  # Domain(review.config):
  # # Closed vocabulary for review frontmatter signals
  # A review document's frontmatter carries the review system's own control state as a closed
  # set of `review_`-prefixed keys; nothing else in that namespace is state the review system
  # recognizes. A key that carries the same prefix but sits outside the closed set is reported
  # on its own rather than silently folded into the recognized state or silently dropped, so a
  # signal from a newer or unrelated system stays visible to whoever reads the report instead
  # of vanishing into either bucket.

  # split the parsed keys into the closed schema and everything outside it
  frontmatter: dict[str, bool | int | str] = {}
  unknown_review_keys: list[str] = []
  for key, raw in meta.items():
    if key in _KNOWN_REVIEW_KEYS:
      frontmatter[key] = _coerce_known_value(key, raw)
    elif key.startswith(ReviewKey.PREFIX):
      unknown_review_keys.append(key)

  # assemble the remaining report blocks and return the full report
  callouts, ticked_question_options, multi_ticked_questions = _build_callout_reports(text, body)
  return {
      "parse_failed": False,
      "frontmatter": frontmatter,
      "unknown_review_keys": unknown_review_keys,
      "banner": _build_banner_report(body, report),
      "sections": _build_sections_report(text),
      "callouts": callouts,
      "ticked_question_options": ticked_question_options,
      "multi_ticked_questions": multi_ticked_questions,
      "both_ticked_candidates": _build_candidate_report(text, body),
      "send_back_items": _build_send_back_report(text, body),
      "job_markers": markers,
  }


def has_open_command(text: str) -> bool:
  """
  Report whether a review document carries an operator command the coordinator still owes.

  Guarantees:
    - A command callout inside a code fence or a foreign `#protected/...` section is never reported as open.
    - A command reported as open is the one `strip_open_command` removes.

  Args:
    text: Full document text, frontmatter included, with LF line endings.

  Returns:
    `True` when a `[!todo] #review/command` callout with a non-empty body sits outside code fences and foreign
    protected sections; `False` otherwise, including for a document whose frontmatter does not parse.
  """

  # Contract:
  # A command callout inside a code fence or inside a foreign protected section is NEVER an open command; this
  # answer and `strip_open_command` read the document the same way, so a command this reports open is the one
  # `strip_open_command` removes. The coordinator's command wake builds on it: a command it could not remove
  # would wake the coordinator forever.

  # the one reading of an open command that the removal also uses
  return _find_open_command(text) is not None


def find_open_command_body(text: str) -> str | None:
  """
  Return the text of the operator command standing open in a review document.

  Guarantees:
    - The body returned is that of the command `has_open_command` reports open and `strip_open_command` removes;
      a command callout inside a code fence or a foreign `#protected/...` section is never returned.

  Args:
    text: Full document text, frontmatter included, with LF line endings.

  Returns:
    The body of the open command `has_open_command` reports, or `None` when the document holds none.
  """

  # Contract:
  # The body returned is that of the command `has_open_command` reports open and `strip_open_command` removes; a
  # command callout inside a code fence or inside a foreign protected section is NEVER returned. The operator-text
  # attribution builds on it: a fenced example returned here would credit a writer's landing to the operator.

  # the same reading `has_open_command` and `strip_open_command` use
  return None if (spot := _find_open_command(text)) is None else spot.body


def _find_open_command(text: str) -> _CommandSpotRecord | None:
  """
  Find the first open operator command callout outside code fences and foreign protected sections.

  Args:
    text: Full document text, frontmatter included, with LF line endings.

  Returns:
    Where the callout sits and its text, or `None` when the document holds no open command or its frontmatter
    cannot be parsed.
  """
  # the report lists only live callouts — none inside a fence or a foreign protected section — and none at all for a
  # document whose frontmatter cannot be parsed
  # waiver: 'callouts' is build_report's own wire-shape key (module docstring), not a keys.py constant
  callouts = build_report(text)["callouts"]

  # guard: no open command among them
  if (command := next((callout for callout in callouts if _is_open_command(callout)), None)) is None:
    return None

  # the spot the command sits at, its head line counted in the document itself
  # waiver: 'line'/'body' are build_report's own wire-shape keys (module docstring), not keys.py constants
  return _CommandSpotRecord(head = command["line"] - 1, body = str(command["body"]))


def _is_open_command(callout: dict) -> bool:
  """
  Report whether one `parse-note` callout entry is an open operator command.

  Args:
    callout: One entry of the report's `callouts` list.

  Returns:
    `True` for a `[!todo] #review/command` callout whose body is not empty; `False` for any other callout.
  """
  # waiver: 'type'/'tag'/'body' are build_report's own wire-shape keys (module docstring), not keys.py constants
  return callout["type"] == _COMMAND_MARKER and callout["tag"] == _COMMAND_TAG and bool(callout["body"].strip())


def strip_open_command(text: str) -> str:
  """
  Remove the document's first open operator command callout, leaving every other byte as it was.

  Guarantees:
    - Only the first open command callout outside code fences and foreign `#protected/...` sections is removed:
      its head line, its consecutive `>` lines, and one blank line only when the removal would otherwise leave
      two blank lines adjacent.
    - Every other byte of the document stays identical.
    - A document with no such callout, or with frontmatter that cannot be parsed, is returned unchanged.

  Args:
    text: Full document text, frontmatter included, with LF line endings.

  Returns:
    The document text without the removed callout, or `text` itself when nothing was removed.
  """

  # Contract:
  # Only the first open command callout outside code fences and foreign protected sections is removed: its head
  # line, its consecutive `>` lines, and at most one blank line where the removal would leave two in a row. Every
  # other byte of the document stays identical, and a document with no such callout, or with frontmatter that
  # cannot be parsed, is returned unchanged.

  # Domain(review.markup):
  # # Removing a finished operator command
  # A command the operator wrote into a document under review is a callout block: its head line and every quoted
  # line that follows it without a break, whatever those lines hold. Once the command is done, exactly that block
  # comes off the document, and nothing after the first unquoted line: a template comment, a heading or another
  # callout that follows the block stays. Where the block stood between two
  # blank lines, one of them goes too, so the removal never leaves a double gap. A command shown inside a code
  # fence is example text, and a command inside a section another plugin owns is that plugin's content; neither
  # is ever removed.

  # guard: no open command, or frontmatter that cannot be parsed — the document stays byte-identical
  if (spot := _find_open_command(text)) is None:
    return text

  # the block runs from its head line over every `>` line after it, by the extent the report reads it with; lines
  # are split on `\n` alone, as the report counts them
  lines = _LINE_RE.findall(text)
  end = spot.head + 1 + len(_find_all_callout_lines("".join(lines[spot.head + 1:]), 0))

  # a blank line on both sides would be left doubled, so the one after the block goes with it
  if spot.head > 0 and end < len(lines) and not lines[spot.head - 1].strip() and not lines[end].strip():
    end += 1

  # every line outside the cut is kept as it was
  return "".join(lines[:spot.head] + lines[end:])


def clear_multi_ticked_questions(text: str, notice: str) -> str:
  """
  Clear every tick of each question the operator ticked more than once, and say why under its options.

  Guarantees:
    - Every question `build_report` lists under `multi_ticked_questions` comes back with all its options unticked
      and one `notice` line under its last option; a question that already carries the line gets no second one.
    - Every other byte of the document stays identical, a question with one tick or none included.

  Args:
    text: Full document text, frontmatter included, with LF line endings.
    notice: The line written under the options, in the document's language.

  Returns:
    The document text with the ticks cleared, or `text` itself when no question carries several ticks.
  """

  # Contract:
  # Every question listed under `multi_ticked_questions` comes back with all its options unticked and one notice
  # line under its last option, never two; every other byte stays identical. The coordinator runs this on the wake
  # that brought the ticks, and a question left ticked would be read again on the next one.

  # waiver: 'multi_ticked_questions'/'callout_line' are build_report's own wire-shape keys, not keys.py constants
  return _clear_ticks_at([ entry["callout_line"] - 1 for entry in build_report(text)["multi_ticked_questions"] ],
                         text, notice)


def clear_both_ticked_candidates(text: str, notice: str) -> str:
  """
  Clear both boxes of each decision-candidate the operator ticked both ways, and say why under them.

  Guarantees:
    - Every candidate `build_report` lists under `both_ticked_candidates` comes back with both boxes unticked and one
      `notice` line under its last box; a candidate that already carries the line gets no second one.
    - Every other byte of the document stays identical.

  Args:
    text: Full document text, frontmatter included, with LF line endings.
    notice: The line written under the boxes, in the document's language.

  Returns:
    The document text with the boxes cleared, or `text` itself when no candidate is ticked both ways.
  """

  # Contract:
  # Every candidate listed under `both_ticked_candidates` comes back with both boxes unticked and one notice line
  # under its last box, never two; every other byte stays identical. The coordinator runs this on the wake that
  # brought the ticks, and a candidate left ticked both ways would be read again on the next one.

  # waiver: 'both_ticked_candidates'/'callout_line' are build_report's own wire-shape keys, not keys.py constants
  return _clear_ticks_at([ entry["callout_line"] - 1 for entry in build_report(text)["both_ticked_candidates"] ],
                         text, notice)


def _clear_ticks_at(heads: list[int], text: str, notice: str) -> str:
  """
  Untick every option of the callouts starting at the given lines and write a notice under each one's options.

  Args:
    heads: Zero-based indices of the callouts' head lines in `text`.
    text: Full document text, with LF line endings.
    notice: The line written under the options.

  Returns:
    The document text with those callouts rewritten, or `text` itself when `heads` is empty.
  """

  # guard: no callout to clear — the document stays byte-identical
  if not heads:
    return text

  # each callout's lines are rewritten in place, from the last one up so earlier indices stay valid
  lines = _LINE_RE.findall(text)
  for head in reversed(heads):
    end = head + 1 + len(_find_all_callout_lines("".join(lines[head + 1:]), 0))
    last_option = head
    for index in range(head + 1, end):
      lines[index] = _QUOTED_TICK_RE.sub(_UNTICKED_BOX, lines[index], count = 1)
      if _OPTION_RE.match(_strip_quote_prefix(lines[index])):
        last_option = index

    # guard: the notice already stands in the callout — a second tick round adds no second line
    if any(_strip_quote_prefix(line).strip() == notice for line in lines[head + 1:end]):
      continue

    # the notice goes on its own line under the last option, even when that option ends the document unterminated
    if not lines[last_option].endswith("\n"):
      lines[last_option] += "\n"
    lines.insert(last_option + 1, f"> {notice}\n")
  return "".join(lines)


def set_key(text: str, key: str, value: object) -> str:
  """
  Set a frontmatter key to a value, using line-surgery to preserve byte-for-byte.

  The key must be a member of the closed schema. When the value is `None`, the key line is
  deleted instead. A retired key accepts only `None`. The autorun state must be one of the
  autorun states, and the autorun cycle count must be a non-negative integer.

  Guarantees:
    - The document body (everything after the frontmatter block) is preserved byte-for-byte;
      only the target key's frontmatter line is added, updated, or removed.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to set or delete.
    value: The value to write, or `None` to delete the key. Serialised to a bare YAML
      literal (true/false for bool, null for None, string/int otherwise). The autorun cycle
      count accepts a non-negative `int` or its ASCII digit string and is written as an `int`;
      a `bool` is refused.

  Returns:
    The updated document text with the key set/deleted and all other bytes unchanged.

  Raises:
    ValueError: If `key` is not in the closed schema, is retired and the value is not `None`, the
      autorun state is not one of the autorun states, or the cycle count is not a non-negative integer.
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # The document body (everything after the frontmatter block) remains byte-for-byte
  # unchanged; only the target key's frontmatter line is added, updated, or removed.

  # guard: a retired key may only be deleted, so a stale document can be cleaned up
  if key in ReviewKey.RETIRED:
    # guard: null on a retired key deletes its line
    if value is None:
      return _fm.unset_field(text, key)
    raise ValueError(f"set-key: key '{key}' is retired; only null (delete) is accepted")

  # guard: key must be in the known schema
  if key not in _KNOWN_REVIEW_KEYS:
    raise ValueError(
        f"set-key: key '{key}' is not in the reserved schema"
    )

  # guard: None value means delete the key
  if value is None:
    return _fm.unset_field(text, key)

  # guard: the autorun state is a closed value set
  if key == ReviewKey.AUTORUN and value not in _AUTORUN_STATES:
    raise ValueError(
        f"set-key: value {value!r} for '{key}' is not one of {', '.join(sorted(_AUTORUN_STATES))}"
    )

  # normalise the autorun cycle counter to a non-negative integer, given as an int or its digit string
  if key == ReviewKey.AUTORUN_CYCLES:
    value = _to_non_negative_int(key, value)

  # set or overwrite the key using line-surgery (preserves body byte-for-byte)
  return _fm.set_field(text, key, value)


def _to_non_negative_int(key: str, value: object) -> int:
  """
  Normalize a value to a non-negative integer.

  Args:
    key: The frontmatter key being set, named in the error message.
    value: A non-negative `int` or its ASCII digit string; a `bool` is refused.

  Returns:
    The value as a non-negative integer.

  Raises:
    ValueError: If the value is neither a non-negative `int` nor an ASCII digit string.
  """
  # guard: an int (never a bool) passes through
  if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
    return value

  # guard: an ASCII digit string is the CLI's spelling of the same integer
  if isinstance(value, str) and value.isascii() and value.isdigit():
    return int(value)

  # anything else is not a cycle count
  raise ValueError(f"set-key: value {value!r} for '{key}' is not an integer >= 0")


def _is_flag_true(meta: dict[str, str], key: str) -> bool:
  """
  Read a `ReviewKey` boolean field, defaulting to `False` when absent.

  Args:
    meta: Parsed frontmatter dict from `frontmatter.parse`.
    key: The boolean `ReviewKey` to read.

  Returns:
    `True` when the field's raw value is the literal `true` (case-insensitive), `False` otherwise.
  """
  # waiver: the bare YAML boolean literal frontmatter.py's own `_serialise_scalar` writes
  return meta.get(key, "").strip().lower() == "true"


def _parse_int_field(meta: dict[str, str], key: str) -> int:
  """
  Read a `ReviewKey` counter field from the parsed frontmatter.

  Args:
    meta: Parsed frontmatter dict from `frontmatter.parse`.
    key: The counter `ReviewKey` to read.

  Returns:
    The integer for a plain ASCII digit string, `0` when the field is absent, empty, negative, or
    otherwise not a plain non-negative integer.
  """
  raw = meta.get(key, "").strip()
  return int(raw) if raw.isascii() and raw.isdigit() else 0


def waiting_context_for_phase(review_phase: str | None) -> str:
  """
  Map a `review_phase` frontmatter value to a `banner.render` waiting-context label.

  Args:
    review_phase: The current `review_phase` value, or `None` when absent.

  Returns:
    The matching barrier/finalize label, or `Bucket.WRITER` for any phase without one — an
    active job outside a named barrier phase is a main-writer round waiting on that writer.
  """

  # Domain(review.markup):
  # # Waiting-context label scope
  # The banner's in-process title names the barrier a round is waiting on only while that
  # barrier is a distinct phase of the round machine — a validation pass, a terminal pass, or
  # the finalize step. Every other phase, including no phase at all, reports the same generic
  # "waiting on the writer" label, because outside those three barriers there is only one thing
  # a round can be waiting on.

  # guard: no phase to look up — fall back to the writer label
  if review_phase is None:
    return Bucket.WRITER
  return _WAITING_CONTEXT_BY_PHASE.get(review_phase, Bucket.WRITER)


def resolve_language(file_path: Path) -> str:
  """
  Resolve the language the review system's own fixed strings are written in.

  Answers with the repo-wide language of the vault that holds the document, as resolved by the
  `lazycortex-core` language chain, or the shipped `en` floor. Review has no language key of its
  own — the prose it writes follows the document under review, and only its fixed operator-facing
  strings follow this value.

  Guarantees:
    - A document outside any vault resolves to `en` without raising.
    - A document inside a vault resolves only to the language the `lazycortex-core` language chain answers; when core
      cannot be reached or answers nothing, `RuntimeError` is raised and no language is substituted.

  Args:
    file_path: The document the language is resolved for.

  Returns:
    The repo-wide language tag; `en` when the document sits outside any vault.

  Raises:
    RuntimeError: If the `lazycortex-core` CLI cannot be resolved, exits non-zero, or answers nothing.
  """

  # Contract:
  # A document with no vault settings file above it MUST resolve to `en`, the shipped floor, without raising.

  # Contract:
  # A document inside a vault MUST resolve only to the language the `lazycortex-core` language chain answers.
  # When core cannot be reached or answers nothing, resolution raises `RuntimeError` and NEVER substitutes a
  # language.

  # the nearest settings root within the document's checkout; a doc outside any vault keeps the floor
  root = _review_locator.find_nearest_dir(file_path.resolve().parent, _SETTINGS_REL)

  # guard: no settings file above the document — English is the shipped floor
  if root is None:
    return LangId.EN

  # core owns the chain, and a missing core is a failure rather than a language; review names no section of its
  # own, so only the repo-wide key is read
  proc = subprocess.run(
      [ sys.executable, str(_git_ops.require_core_cli(root)), CoreCommand.RESOLVE_LANGUAGE, _ARG_CWD, str(root) ],
      capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
  )

  # guard: a non-zero exit or an empty answer — surface stdout+stderr instead of inventing a language
  if proc.returncode != 0 or not proc.stdout.strip():
    raise RuntimeError(
        f"lazycortex-core {CoreCommand.RESOLVE_LANGUAGE} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return proc.stdout.removesuffix("\n")


def repaint_banner(
    text: str,
    *,
    job_in_flight: bool = False,
    lang: str = LangId.EN,
    report: bool = False,
    verdict: str | None = None,
) -> str:
  """
  Recompute and repaint the top banner from the document's current frontmatter state, or take it down when the
  review is not active.

  The banner state follows the document's review frontmatter and the open questions and decision candidates in
  its body. A validation round paints the three-checkbox ready banner unless the autorun stopped clean, which
  keeps the one-checkbox ready banner with the autorun stop line. For a report class the ready banner is instead
  the two-checkbox report banner, shown only once the writer has recorded a known verdict; until then the
  in-process banner waits for the implementer's answer. A job in flight always paints the in-process banner.

  Guarantees:
    - Repainting is idempotent: calling this function again on its own output, with the
      same `job_in_flight` value, returns identical text.
    - Never paints the ready banner on an unapproved document whose `review_phase` is `main` or
      that carries an open operator command, as `has_open_command` reads it.
    - With `report` set, never paints the ready banner on an unapproved document whose `verdict` is not
      `sufficient` or `new-plan`; the in-process banner then says the implementer's answer is awaited.
    - When `review_active` is not `true` the text comes back with no banner: an existing banner is stripped and none
      is inserted. A document with no frontmatter block and no banner comes back unchanged.

  Args:
    text: Full document text, frontmatter included.
    job_in_flight: Whether an expert job is currently out on this document, from the caller's
      own read of the runtime marker sidecar (`job_markers.read`). Defaults to `False`, which
      is what a caller that has just seated a document's frontmatter itself knows.
    lang: Resolved language code for the banner's fixed strings; a language with no table of
      its own paints the shipped English wording.
    report: Whether the document's class is a report class, from the caller's own class lookup; paints the
      two-checkbox ready banner.
    verdict: The report writer's verdict (`sufficient` / `new-plan`) choosing the line under the report banner's
      fix box; with `report` set, any other value, including `None`, keeps the ready banner away.

  Returns:
    `text` with its banner replaced (or inserted, if absent) to match the current frontmatter, or with no banner
    when the review is not active. A second call over the unchanged document returns the identical text.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # Repainting is idempotent: calling this function again on its own output, with the
  # same `job_in_flight` value, returns identical text.

  # Contract:
  # The ready banner is NEVER painted on an unapproved document whose `review_phase` is
  # `main` or that carries an open operator command, as `has_open_command` reads it.

  # Contract:
  # With `report` set, the ready banner is NEVER painted on an unapproved document whose `verdict` is
  # not `sufficient` or `new-plan`.

  # Contract:
  # When `review_active` is not `true` the text comes back with no banner: an existing banner is stripped and none is
  # inserted. A document with no frontmatter block and no banner comes back unchanged.

  # Domain(review.markup):
  # # A document out of review carries no banner
  # The banner belongs to a review that is running. A document whose review is not active, stopped or never started,
  # carries no banner at all. A repaint, such as a coordinator wake still in flight while the review is being
  # stopped, never puts one back, and removes one it finds left there.

  meta, body = _fm.parse(text)

  # a document out of review comes back with its banner stripped, so a repaint racing a stop never puts one back
  if not _is_flag_true(meta, ReviewKey.ACTIVE):
    return text[: len(text) - len(body)] + _banner.strip_banner(body)

  # read the approve flag and the review phase from the frontmatter; `job_in_flight` decides the dispatch
  # state, because a job in flight means an agent still works on the document and the operator waits
  approved = _is_flag_true(meta, ReviewKey.APPROVED)
  review_phase_raw = meta.get(ReviewKey.PHASE)
  review_phase = review_phase_raw.strip() or None if review_phase_raw is not None else None
  dispatch_state = (
      _banner.DispatchState.CHAIN_IN_PROGRESS if job_in_flight
      else _banner.DispatchState.CHAIN_EXHAUSTED
  )

  # feed the frontmatter snapshot into banner.py's own state ladder
  # limit: no `domain_ready_when` class-config gate here (dispatcher._eval_domain_ready) — the caller resolves
  # the class only for its `report` flag; wire the gate in if a future review class needs the ACTION_NEEDED
  # state from this verb specifically rather than from the coordinator's judgment.
  state = _banner.desired_state(
      body = body,
      dispatch_state = dispatch_state,
      approved = approved,
      review_phase = review_phase,
      command_pending = has_open_command(text),
      verdict_owed = report and verdict not in set(ReportVerdictKind),
  )

  # render the callout for that state and splice it back into the document
  waiting_context = waiting_context_for_phase(review_phase) if state is _banner.State.IN_PROCESS else None
  new_body = _banner.replace_banner(
      body, state,
      approved = approved,
      validation_seen = _parse_int_field(meta, ReviewKey.VALIDATION_ROUND) >= 1,
      autorun = meta.get(ReviewKey.AUTORUN, "").strip() or None,
      autorun_cycles = _parse_int_field(meta, ReviewKey.AUTORUN_CYCLES),
      waiting_context = waiting_context,
      lang = lang,
      report = report,
      verdict = verdict,
  )
  return text[: len(text) - len(body)] + new_body


def main(argv: list[str]) -> int:
  """
  Print the structural report for a review document as JSON to stdout.

  The banner's boxes are read by the document's review class, resolved from the merged settings nearest to the
  document. When the settings cannot be read, the class is unknown and every banner box reports `kind: null`. The
  reported job markers come from the checkout the command works in, except the verdict, which is the one recorded for
  the document's own repository root.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the working directory), and the checkout it sits in is the one worked in.

  Returns:
    Exit code: always `0` — a structurally broken document is reported as `parse_failed: true`
    data, never an exception; only a missing file (an operator/caller mistake, not a document
    defect) exits non-zero.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-review parse-note")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = None)
  args = parser.parse_args(argv)

  # `file` resolves against the root of the checkout `--repo`, `$LAZY_REPO_ROOT` or the cwd sits in, unless it is
  # already absolute (pathlib drops the left operand of `/` when the right one is absolute)
  repo = _review_locator.query_repo_root(args.repo)
  file_path = (repo / args.file).resolve()

  # guard: a missing document cannot be reported on
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # the banner's boxes are read by the document's class; settings or a core that cannot be read leave it unknown
  report: bool | None
  try:
    settings_root = _core_settings.query_settings_root_for(file_path)
    settings = _core_settings.read_merged_sections(settings_root, JobKey.REVIEW)
    report = _doc_class.is_report_class(settings, settings_root, file_path)
  except (SettingsReadError, RuntimeError):
    report = None

  # the writer's verdict is keyed by the document's repository root, whatever `--repo` names
  markers = _job_markers.read(repo, file_path)
  markers[JobMarker.VERDICT] = \
      _job_markers.read(_finalize.query_repo_root_for(file_path), file_path)[JobMarker.VERDICT]

  # build the structural report and print it as JSON
  print(json.dumps(
      build_report(file_path.read_text(encoding = "utf-8"), markers, report = report),
      indent = 2,
  ))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
