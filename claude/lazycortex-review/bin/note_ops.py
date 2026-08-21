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
      "banner": {"present": bool, "state_tag": str | None, "gestures": [{"label", "ticked"}]},
      "sections": [{"title": str, "owner_tag": str}],
      "callouts": [{"type": str, "tag": str, "line": int, "body": str}],
      "ticked_question_options": [{"callout_line": int, "option": str}],
      "job_markers": {"coordinator_job": str | None, "active_job": str | None,
                      "pending_wake": str | None},
    }

`job_markers` is the one block that does not come from the document's own bytes: the review
loop's job markers are runtime state in `job_markers.py`'s sidecar, not frontmatter, and they
ride along here so one `parse-note` call still shows the coordinator the whole picture.

`set_key` and `repaint_banner` are mutating writers over the same document; both raise
`ParseError` on a malformed frontmatter block rather than reporting it in a return value.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,wrong-import-position,deprecated-module

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
import banner as _banner  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import body as _body  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import parser as _parser  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import ParseError  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import Bucket, Phase, ReviewKey, Tag  # noqa: E402


# The closed `review_*` frontmatter schema (spec § Frontmatter schema) — any `review_`-prefixed
# key outside this set surfaces in the report as `unknown_review_keys` instead of `frontmatter`.
_KNOWN_REVIEW_KEYS = frozenset({
    ReviewKey.ACTIVE, ReviewKey.ROUND, ReviewKey.APPROVED, ReviewKey.PHASE, ReviewKey.RESULT,
    ReviewKey.MAIN_DONE, ReviewKey.EXPERT, ReviewKey.VALIDATION_ROUND,
    ReviewKey.APPROVED_WITH_CONCERNS,
})
_BOOL_REVIEW_KEYS = frozenset({ ReviewKey.ACTIVE, ReviewKey.APPROVED, ReviewKey.APPROVED_WITH_CONCERNS })
_INT_REVIEW_KEYS = frozenset({ ReviewKey.ROUND, ReviewKey.VALIDATION_ROUND })

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
# `_FIRST_LINE_RE` (which only recognises the five banner-state tags) to any review-owned
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


def _coerce_known_value(key: str, raw: str) -> bool | int | str:
  """
  Coerce a raw frontmatter string to the type its `ReviewKey` carries.

  Args:
    key: A member of `_KNOWN_REVIEW_KEYS`.
    raw: The raw string value `frontmatter.parse` read for `key`.

  Returns:
    `bool` for the three flag keys, `int` for the two round-counter keys (falling back to the
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


def _build_banner_report(text: str, body: str) -> dict:
  """
  Build the `banner` report block for one document.

  Args:
    text: Full document text (frontmatter included), used to locate the first H1 heading.
    body: Document body text (post-frontmatter) to scan for the banner and its gestures.

  Returns:
    Dict with `present`, `state_tag`, and `gestures` — see module docstring.
  """
  state = _banner.extract(body)
  # guard: no banner present — nothing further to report
  if state is None:
    return _empty_banner_report()

  # the banner's own territory is everything before the first H1; a document with no H1 at all
  # treats the whole body as banner territory (mirrors `banner.extract`'s own scan region)
  top = _parser.parse(text).top_heading
  banner_region = body[: body.index(top.heading_line)] if top is not None else body
  gestures = [
      { "label": m.group(2).strip(), "ticked": m.group(1).lower() == _TICK_CHAR }
      for m in _GESTURE_RE.finditer(banner_region)
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
      "banner": _build_banner_report(text, body),
      "sections": _build_sections_report(text),
      "callouts": callouts,
      "ticked_question_options": ticked_question_options,
      "job_markers": markers,
  }


def set_key(text: str, key: str, value: object) -> str:
  """
  Set a frontmatter key to a value, using line-surgery to preserve byte-for-byte.

  The key must be a member of the closed schema `_KNOWN_REVIEW_KEYS`. When the value
  is `None`, the key line is deleted instead. Document body is preserved byte-for-byte.

  Args:
    text: Raw document text to modify.
    key: The frontmatter key to set or delete.
    value: The value to write, or `None` to delete the key. Serialised to a bare YAML
      literal (true/false for bool, null for None, string/int otherwise).

  Returns:
    The updated document text with the key set/deleted and all other bytes unchanged.

  Raises:
    ValueError: If `key` is not in the closed schema.
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """
  # guard: key must be in the known schema
  if key not in _KNOWN_REVIEW_KEYS:
    raise ValueError(
        f"set-key: key '{key}' is not in the reserved schema"
    )

  # guard: None value means delete the key
  if value is None:
    return _fm.unset_field(text, key)

  # set or overwrite the key using line-surgery (preserves body byte-for-byte)
  return _fm.set_field(text, key, value)


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


def waiting_context_for_phase(review_phase: str | None) -> str:
  """
  Map a `review_phase` frontmatter value to a `banner.render` waiting-context label.

  Args:
    review_phase: The current `review_phase` value, or `None` when absent.

  Returns:
    The matching barrier/finalize label, or `Bucket.WRITER` for any phase without one — an
    active job outside a named barrier phase is a main-writer round waiting on that writer.
  """
  # guard: no phase to look up — fall back to the writer label
  if review_phase is None:
    return Bucket.WRITER
  return _WAITING_CONTEXT_BY_PHASE.get(review_phase, Bucket.WRITER)


def repaint_banner(text: str, *, job_in_flight: bool = False) -> str:
  """
  Recompute and repaint the top banner from the document's current frontmatter state.

  The banner state is driven by frontmatter (`review_approved`,
  `review_approved_with_concerns`, `review_phase`) plus the body's own open-question/-concern
  content — no class-config lookup. A job in flight always paints the in-process banner.

  Args:
    text: Full document text, frontmatter included.
    job_in_flight: Whether an expert job is currently out on this document, from the caller's
      own read of the runtime marker sidecar (`job_markers.read`). Defaults to `False`, which
      is what a caller that has just seated a document's frontmatter itself knows.

  Returns:
    `text` with its banner replaced (or inserted, if absent) to match the current frontmatter.
    Returned unchanged when the document carries no frontmatter block. A second call over the
    unchanged document returns the identical text.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """
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
      concerns_decision_pending = review_phase == Bucket.CONCERNS_PAUSE,
      review_phase = review_phase,
  )

  # render the callout for that state and splice it back into the document
  waiting_context = waiting_context_for_phase(review_phase) if state is _banner.State.IN_PROCESS else None
  new_body = _banner.replace_banner(
      body, state,
      approved = approved,
      approve_with_concerns = _is_flag_true(meta, ReviewKey.APPROVED_WITH_CONCERNS),
      waiting_context = waiting_context,
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
  print(json.dumps(build_report(file_path.read_text(), _job_markers.read(repo, file_path)), indent = 2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
