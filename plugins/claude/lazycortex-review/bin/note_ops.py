"""Deterministic read/write primitives for one review document: `parse-note`, `set-key`, `paint-banner`.

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
      "job_markers": {"coordinator_job": str | None, "active_job": str | None,
                      "pending_wake": str | None},
    }

Each banner gesture's `kind` is derived from the checkbox's position inside the banner callout, never from its
label, so every banner language yields the same kinds. In the ready state the closed set is `approve`,
`approve-autorun`, and `approve-skip-validation` (the first, second, and third box, as in
`banner.READY_GESTURE_KINDS`). A box beyond the third, and any box in a non-ready state, reports `kind: null`.
Every checkbox is reported in banner order with its `ticked` flag, so two simultaneous ticks both appear and
resolving them is the caller's job.

`job_markers` is the one block that does not come from the document's own bytes: the review
loop's job markers are runtime state in `job_markers.py`'s sidecar, not frontmatter, and they
ride along here so one `parse-note` call still shows the coordinator the whole picture.

`set_key` and `repaint_banner` are mutating writers over the same document; both raise
`ParseError` on a malformed frontmatter block rather than reporting it in a return value.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import ParseError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import LANG_EN as _LANG_EN, AutorunState, Bucket, Phase, ReviewKey, Tag  # noqa: E402


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

# Any `[!<marker>] ... #review/<tag>` callout head line — generalises banner.py's own
# `_FIRST_LINE_RE` (which only recognises the four banner-state tags) to any review-owned
# callout marker (`todo`, `question`, `attention`, ...), per the reference shape in
# `lazycortex-specs/bin/coordinator_dispatch.py`'s `_QUESTION_HEAD_RE`, rewritten here rather
# than imported (plugin boundary).
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!(\w+)\][^#\n]*#review/([a-z-]+)\s*$", re.MULTILINE)

# A ticked option line inside a callout block, once its leading `> ` quote prefix is stripped.
_TICKED_OPTION_RE = re.compile(r"^-\s*\[[xX]\]\s*(.+)$")

_QUOTE_PREFIX_RE = re.compile(r"^>\s?")

# The checkbox-ticked marker character `_GESTURE_RE` / `_TICKED_OPTION_RE` capture.
_TICK_CHAR = "x"

# The `[!question]` marker and `#review/question` tag value — the only callout kind whose block
# is also scanned for ticked options.
_QUESTION_MARKER = "question"

# The vault settings file `resolve_language` walks up to and the key it reads there; the
# shipped floor it returns when neither is found is `keys.LANG_EN`.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_LANGUAGE_KEY = "language"


def _coerce_known_value(key: str, raw: str) -> bool | int | str:
  """
  Coerce a raw frontmatter string to the type its `ReviewKey` carries.

  Args:
    key: A member of `_KNOWN_REVIEW_KEYS`.
    raw: The raw string value `frontmatter.parse` read for `key`.

  Returns:
    `bool` for the flag keys, `int` for the two round-counter keys (falling back to the
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


def _callout_block_lines(body: str, start: int) -> list[str]:
  """
  Collect the consecutive `>`-prefixed lines of a callout, starting at `start`.

  Args:
    body: Document body text to slice from.
    start: Byte offset immediately after the callout's head line.

  Returns:
    The block's continuation lines (head line excluded), still carrying their `>` prefix.
  """
  collected: list[str] = []
  for line in body[start:].splitlines():
    if not line.startswith(">"):
      break
    collected.append(line)
  return collected


def _line_number(text: str, offset: int) -> int:
  """
  Return the 1-indexed line number of `offset` within `text`.

  Args:
    text: Full document text the offset is measured against.
    offset: Byte offset into `text`.

  Returns:
    The 1-indexed line number containing `offset`.
  """
  return text.count("\n", 0, offset) + 1


def _empty_banner_report() -> dict:
  """
  Return the default `banner` report block for a document with no detected banner.

  Returns:
    Dict with `present: False`, `state_tag: None`, and an empty `gestures` list.
  """
  return { "present": False, "state_tag": None, "gestures": [] }


def _build_banner_report(body: str) -> dict:
  """
  Build the `banner` report block for one document.

  Args:
    body: Document body text (post-frontmatter) to scan for the banner and its gestures.

  Returns:
    Dict with `present`, `state_tag`, and `gestures` — see module docstring. Gestures come only from the banner
    callout block itself, never from a question or any other callout before the first H1. Each gesture's `kind`
    follows the checkbox's position among the ready banner's checkboxes (so every language's banner reports the
    same kinds), and is `None` for a checkbox past the last known position and for every checkbox of a banner
    that is not the ready one.
  """
  state = _banner.extract(body)

  # guard: no banner present — nothing further to report
  if state is None:
    return _empty_banner_report()

  # only the banner callout's own lines are gestures: a question or any other callout near the
  # banner, before the first H1 or in a document with none, never reads as one
  banner_block = _banner.extract_block(body)

  # a checkbox's gesture kind follows its position among the ready banner's checkboxes, never
  # its label, so every language's banner reports the same kinds; a checkbox past the last
  # known position, or on a banner that is not the ready one, has no kind
  kinds = _banner.READY_GESTURE_KINDS if state is _banner.State.READY else ()
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


def _build_callout_reports(text: str, body: str) -> tuple[list[dict], list[dict]]:
  """
  Build the `callouts` and `ticked_question_options` report blocks in one pass.

  Args:
    text: Full document text, used to compute absolute line numbers.
    body: Document body text to scan for `#review/<tag>` callouts.

  Returns:
    A `(callouts, ticked_question_options)` tuple.
  """
  fm_length = len(text) - len(body)
  callouts: list[dict] = []
  ticked_question_options: list[dict] = []
  for m in _CALLOUT_HEAD_RE.finditer(body):
    marker, tag = m.group(1), m.group(2)

    # guard: a banner-state tag is reported via `banner`, never duplicated here
    if tag in _BANNER_STATE_TAGS:
      continue

    # gather the callout's block (head line's own end through its trailing `>` lines) and turn
    # it into the plain-text `body` this callout reports
    head_line_end = body.find("\n", m.end())
    head_line_end = len(body) if head_line_end == -1 else head_line_end + 1
    block_lines = _callout_block_lines(body, head_line_end)
    callout_body = "\n".join(_strip_quote_prefix(line) for line in block_lines).strip()
    line_no = _line_number(text, fm_length + m.start())
    callouts.append({
        "type": marker, "tag": f"{Tag.REVIEW_PREFIX}{tag}", "line": line_no, "body": callout_body,
    })

    # guard: ticked options only matter inside a `[!question] ... #review/question` callout
    if marker != _QUESTION_MARKER or tag != _QUESTION_MARKER:
      continue
    for raw_line in block_lines:
      opt_match = _TICKED_OPTION_RE.match(_strip_quote_prefix(raw_line))
      if opt_match:
        ticked_question_options.append({ "callout_line": line_no, "option": opt_match.group(1).strip() })
  return callouts, ticked_question_options


def build_report(text: str, job_markers: dict[str, str | None] | None = None) -> dict:
  """
  Parse a review document into the structural report the coordinator and watch worker act on.

  Guarantees:
    - When `parse_failed` is `True`, every other report field is empty rather than
      partially populated.

  Args:
    text: Full document text to inspect.
    job_markers: The document's runtime marker entry from `job_markers.read`, reported
      verbatim under `job_markers`. Defaults to the all-absent entry, which is what a caller
      reading a bare text snapshot (a pre-commit blob, a test fixture) has.

  Returns:
    Dict with `parse_failed`, `frontmatter`, `unknown_review_keys`, `banner`, `sections`,
    `callouts`, `ticked_question_options`, and `job_markers` — see module docstring for the
    exact shape. `parse_failed` is `True` when the document carries no frontmatter block (or a
    malformed one), in which case every other field is empty rather than partially populated.
  """
  markers = dict(job_markers) if job_markers is not None else _job_markers.empty_entry()
  try:
    meta, body = _fm.parse(text)
  except ParseError:
    meta, body = {}, ""

  # Contract:
  # When `parse_failed` is True, every other report field is empty rather than
  # partially populated.

  # guard: no usable frontmatter — the document is structurally broken for review purposes
  if not meta:
    return {
        "parse_failed": True,
        "frontmatter": {},
        "unknown_review_keys": [],
        "banner": _empty_banner_report(),
        "sections": [],
        "callouts": [],
        "ticked_question_options": [],
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
  callouts, ticked_question_options = _build_callout_reports(text, body)
  return {
      "parse_failed": False,
      "frontmatter": frontmatter,
      "unknown_review_keys": unknown_review_keys,
      "banner": _build_banner_report(body),
      "sections": _build_sections_report(text),
      "callouts": callouts,
      "ticked_question_options": ticked_question_options,
      "job_markers": markers,
  }


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
    value = _non_negative_int(key, value)

  # set or overwrite the key using line-surgery (preserves body byte-for-byte)
  return _fm.set_field(text, key, value)


def _non_negative_int(key: str, value: object) -> int:
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


def _int_field(meta: dict[str, str], key: str) -> int:
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

  Walks up from the document to the nearest `.claude/lazy.settings.json` and
  returns the top-level `language` key, or the shipped `en` floor. Review has
  no language key of its own — the prose it writes follows the document under
  review, and only its fixed operator-facing strings follow this value.

  Guarantees:
    - Always returns a language tag; a document outside any vault, or an
      unreadable settings document, resolves to `en` instead of raising.

  Args:
    file_path: The document the language is resolved for.

  Returns:
    The repo-wide language tag; `en` when no settings file is found or readable.
  """

  # Contract:
  # Resolution MUST always yield a language tag: a document outside any vault, or
  # an unreadable settings document, resolves to `en` rather than raising.

  # walk up to the nearest settings root; a doc outside any vault keeps the floor
  settings = None
  for cand in file_path.resolve().parents:
    candidate = cand / _SETTINGS_REL
    if candidate.is_file():
      try:
        settings = json.loads(candidate.read_text(encoding = "utf-8"))
      except (OSError, json.JSONDecodeError):
        settings = None
      break

  # guard: no settings file, or an unreadable one — English is the shipped floor
  if not isinstance(settings, dict):
    return _LANG_EN

  # the repo-wide key is the only one consulted — review has no language of its own
  value = settings.get(_LANGUAGE_KEY)

  # guard: an absent or empty key leaves the floor in place
  if not isinstance(value, str) or not value:
    return _LANG_EN
  return value


def repaint_banner(text: str, *, job_in_flight: bool = False, lang: str = _LANG_EN) -> str:
  """
  Recompute and repaint the top banner from the document's current frontmatter state.

  The banner state is driven by frontmatter (`review_approved`, `review_phase`,
  `review_validation_round`, `review_autorun`, `review_autorun_cycles`) plus the
  body's own open-question and decision-candidate content — no class-config lookup. A
  `review_validation_round` of 1 or more paints the three-checkbox ready banner. A job in flight
  always paints the in-process banner.

  Guarantees:
    - Repainting is idempotent: calling this function again on its own output, with the
      same `job_in_flight` value, returns identical text.

  Args:
    text: Full document text, frontmatter included.
    job_in_flight: Whether an expert job is currently out on this document, from the caller's
      own read of the runtime marker sidecar (`job_markers.read`). Defaults to `False`, which
      is what a caller that has just seated a document's frontmatter itself knows.
    lang: Resolved language code for the banner's fixed strings; a language with no table of
      its own paints the shipped English wording.

  Returns:
    `text` with its banner replaced (or inserted, if absent) to match the current frontmatter.
    Returned unchanged when the document carries no frontmatter block. A second call over the
    unchanged document returns the identical text.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # Repainting is idempotent: calling this function again on its own output, with the
  # same `job_in_flight` value, returns identical text.

  meta, body = _fm.parse(text)

  # guard: no frontmatter — nothing to derive a banner state from
  if not meta:
    return text

  # read the frontmatter fields that drive the banner state — mirrors the minimal slice of
  # dispatcher.py's end-of-tick banner repaint; the caller's `job_in_flight` stands in for the
  # old dispatch-state chain, since the marker it comes from is set on dispatch and cleared on collect
  approved = _is_flag_true(meta, ReviewKey.APPROVED)
  review_phase_raw = meta.get(ReviewKey.PHASE)
  review_phase = review_phase_raw.strip() or None if review_phase_raw is not None else None
  dispatch_state = (
      _banner.DispatchState.CHAIN_IN_PROGRESS if job_in_flight
      else _banner.DispatchState.CHAIN_EXHAUSTED
  )

  # feed the frontmatter snapshot into banner.py's own state ladder
  # limit: no `domain_ready_when` class-config gate here (dispatcher._eval_domain_ready)
  # — paint-banner has no class-resolution wiring; add it if a future review class needs the
  # ACTION_NEEDED gate from this verb specifically rather than from the coordinator's judgment.
  state = _banner.desired_state(
      body = body,
      dispatch_state = dispatch_state,
      approved = approved,
      review_phase = review_phase,
  )

  # render the callout for that state and splice it back into the document
  waiting_context = waiting_context_for_phase(review_phase) if state is _banner.State.IN_PROCESS else None
  new_body = _banner.replace_banner(
      body, state,
      approved = approved,
      validation_seen = _int_field(meta, ReviewKey.VALIDATION_ROUND) >= 1,
      autorun = meta.get(ReviewKey.AUTORUN, "").strip() or None,
      autorun_cycles = _int_field(meta, ReviewKey.AUTORUN_CYCLES),
      waiting_context = waiting_context,
      lang = lang,
  )
  return text[: len(text) - len(body)] + new_body


def main(argv: list[str]) -> int:
  """
  Print the structural report for a review document as JSON to stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

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
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # `file` resolves against `--repo` unless it's already absolute (pathlib drops the left
  # operand of `/` when the right one is absolute, so this is safe either way)
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # build the structural report and print it as JSON
  print(json.dumps(
      build_report(file_path.read_text(encoding = "utf-8"), _job_markers.read(repo, file_path)), indent = 2
  ))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
