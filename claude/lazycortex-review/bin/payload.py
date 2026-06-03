"""Build agent requests and validate agent responses.

Together with :mod:`body` and :mod:`reapply`, this module enforces the
ownership-isolation contract: the dispatcher only ever applies an
agent response that passed validation, and validation refuses
responses that overstep the role's mandate.

Request shape (matches the trimmed protocol contract in
`references/lazy-review.doc-review-protocol.md`):

    {
      "role":   "<free-form string from expert config>",
      "round":  N,
      "source": [{"path": "source/<file>"}],
      "context": [{"path": "context/<file>"}, ...],
      "result": [{"path": "result/<file>"}],
      "edit_marker_style": "simple | diff | criticmarkup | html",
      "owned_section": "<H1 title>"   # section-writer only
    }

`kind` is no longer on the wire — it was an internal-only enum
(`review` / `repair` / `history`) that the dispatcher already knows
from its entry point. The agent never branched on it.

`edit_marker_template` (a per-style copy-paste snippet) was retired
in favour of the agent reading `edit_marker_style` directly and
fetching its rules block from the `lazy-core.markdown-style`
protocol that the routine attaches to every job's `config.json`. One
source of truth for marker shape, no duplication in the payload.

Response shape:

    {
      "outcome":       "edited | empty | noop | error",
      "result":        ["result/<file>"],
      "history_entry": "<one-sentence summary>",
      "error":         {"category": "...", "message": "..."}
    }

For `outcome=edited` every writer returns `result: ["path"]` — main
writers write the full document body, section writers write only the
markdown body of their owned section (no H1 heading, no ownership tag —
the dispatcher emits both itself). The output transport is unified;
`response.json` carries only metadata.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re
from dataclasses import dataclass

from errors import PayloadError
from keys import JobKey, Outcome, Phase, Tag

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable, Mapping


@dataclass(frozen=True)
class OwnershipViolationInfo:
  """
  Diagnostic record produced when a section-writer touches content outside its owned section.

  Not an exception — the reapply pipeline applies the graceful-clipped result and surfaces this
  info alongside so the dispatcher can log it, raise a UX warning, or quarantine the misbehaving
  expert without discarding the agent's owned-section work.

  Attributes:
    expert: Flat name of the expert whose section-write was flagged.
    message: Human-readable description of the ownership violation.
  """
  expert: str
  message: str


# Per-kind valid outcomes (spec table in protocol doc).
_OUTCOMES_BY_KIND: dict[str, set[str]] = {
    "review":   {"edited", "empty", "error"},
    "repair":   {"edited", "error"},
    "history":  {"summarized", "noop", "error"},
}

# Outcomes that require `result` in the response.
_OUTCOMES_REQUIRING_RESULT = {"edited"}
# Outcomes that require `history_entry` in the response.
_OUTCOMES_REQUIRING_HISTORY_ENTRY = {"edited", "summarized"}

# ------------------------------------------------------------ build_request


_VALID_MODES = frozenset({"main", "validation", "terminal", "history", "repair"})


def build_request(
    *,
    kind: str,
    mode: str,
    role: str,
    round_: int,
    source_path: str,
    context_paths: Iterable[str],
    result_path: str,
    edit_marker_style: str,
    concerns: list[dict] | None = None,
) -> dict:
  """
  Build the agent request envelope.

  `mode` is the structural classification of the dispatch — one of
  `main` / `validation` / `terminal` / `history` / `repair`
  — derived from the expert's bucket in config. The dispatcher
  enforces ownership / IO contract by mode; the protocol's per-mode
  rules describe what is wire-true (where output goes, what the
  dispatcher strips on reapply).

  `role` is a free-form string from the expert's config — the agent
  consumes it via `request.json.role` and decides how to branch
  (or whether to branch at all). The dispatcher transports it
  verbatim and does NOT enforce semantics. Two experts sharing a
  bucket (and therefore a mode) may carry different roles.

  Args:
    kind: Dispatch kind (`review`, `repair`, or `history`); used for validation only, not written to wire.
    mode: Structural classification of the dispatch (`main`, `validation`, `terminal`, `history`, or `repair`).
    role: Free-form role string from the expert's config, transported verbatim.
    round_: Current round number.
    source_path: Path to the source file, or empty string to omit the field.
    context_paths: Paths to attach as context entries.
    result_path: Path to the result file, or empty string to omit the field.
    edit_marker_style: Edit marker style identifier (`simple`, `diff`, `criticmarkup`, or `html`).
    concerns: Optional list of `{group, writer, section_h1_title, content}` entries describing
      currently-non-empty validation H1 sections. Omitted from the request when `None` or empty.

  Returns:
    Request envelope dict ready to serialize as `request.json`.

  Raises:
    PayloadError: If `kind` is not a recognized dispatch kind or `mode` is not a valid mode.
  """
  if kind not in _OUTCOMES_BY_KIND:
    raise PayloadError(f"unknown kind: {kind!r}")
  if mode not in _VALID_MODES:
    raise PayloadError(
        f"unknown mode: {mode!r}; allowed: {sorted(_VALID_MODES)}"
    )
# `kind` is no longer written to the request — see module
# docstring. It survives as a build-time sanity input
# (`_OUTCOMES_BY_KIND` enum gate) and as a validate_response
# parameter, both driven by the dispatcher's local context.
  request: dict = {
      JobKey.MODE: mode,
      JobKey.ROLE: role,
      JobKey.ROUND: round_,
      JobKey.EDIT_MARKER_STYLE: edit_marker_style,
      JobKey.SOURCE: [{JobKey.PATH: source_path}] if source_path else [],
      JobKey.CONTEXT: [{JobKey.PATH: p} for p in context_paths],
      JobKey.RESULT: [{JobKey.PATH: result_path}] if result_path else [],
  }
  if concerns:
    request[Outcome.CONCERNS] = concerns
  return request


# ------------------------------------------------------- validate_response


def validate_response(response: Mapping, *, kind: str) -> None:
  """
  Raise `PayloadError` if `response` violates the per-kind contract.

  `role` is no longer an input — every writer returns body content via `result: [path]` under
  the unified transport, so the validator does not need to know which role the response came from.

  Args:
    response: Parsed response mapping from the agent's `response.json`.
    kind: Dispatch kind (`review`, `repair`, or `history`) that governs which outcomes are valid.

  Raises:
    PayloadError: If `outcome` is missing, not valid for the given `kind`, or required fields
      (`result`, `history_entry`) are absent or empty.
  """
  outcome = response.get(JobKey.OUTCOME)
  if not isinstance(outcome, str):
    raise PayloadError("response missing 'outcome' (must be a string)")
  valid = _OUTCOMES_BY_KIND.get(kind)
  # Special tolerance: kind=history may legitimately return either
  # 'noop' or 'summarized'; 'summarized' is the in-spec name, 'noop'
  # is the metadata-only signal.
  if kind == Phase.HISTORY and outcome == Outcome.NOOP:
    return
  if valid is None:
    raise PayloadError(f"unknown kind: {kind!r}")
  if outcome not in valid:
    raise PayloadError(
        f"outcome={outcome!r} not valid for kind={kind!r}; "
        f"allowed: {sorted(valid)}"
    )
  if outcome in _OUTCOMES_REQUIRING_RESULT:
      # Unified output transport: every writer (main / section /
      # repair) returns `result: ["path"]`. Main writers write the
      # full document body; section writers write only the section
      # body (no H1 heading, no ownership tag — the dispatcher emits
      # both itself).
    result = response.get(JobKey.RESULT)
    if not isinstance(result, list) or not result:
      raise PayloadError(
          f"outcome={outcome!r} requires non-empty 'result' array"
      )
  if outcome in _OUTCOMES_REQUIRING_HISTORY_ENTRY and kind != Outcome.REPAIR:
    entry = response.get(JobKey.HISTORY_ENTRY)
    if not isinstance(entry, str) or not entry.strip():
      raise PayloadError(
          f"outcome={outcome!r} on kind={kind!r} requires non-empty 'history_entry'"
      )


# ------------------------------------------- section-writer body guard


_H1_RE = re.compile(r"^# (.+?)\s*$", re.MULTILINE)


def _strip_owned_section(body: str, owned_expert: str) -> str:
  """
  Remove the H1 section owned by `owned_expert` so the remaining text can be compared against
  the operator's same-stripped body.

  Args:
    body: Full document body text to strip from.
    owned_expert: Flat expert name identifying the section to remove.

  Returns:
    Document body with the owned section removed; all other sections are preserved verbatim.
  """
  matches = list(_H1_RE.finditer(body))
  keep_ranges: list[tuple[int, int]] = []
  if not matches:
    return body
  if matches[0].start() > 0:
    keep_ranges.append((0, matches[0].start()))
  for i, m in enumerate(matches):
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
    section = body[start:end]
    line_end = body.find("\n", m.end())
    heading_len = (line_end + 1 - start) if line_end != -1 else (end - start)
    rest = section[heading_len:]
    # First non-empty line under heading.
    # Extract the flat name (first component of the tag) to compare
    # against owned_expert. Tag format is #expert/<flat>/<section_id>
    # — take only the first /-delimited component.
    owner_flat = None
    for raw in rest.splitlines():
      stripped = raw.strip()
      # guard: skip blank lines so the owner tag is read from the first line carrying content
      if not stripped:
        continue
      if stripped.startswith(Tag.EXPERT_PREFIX):
        rest_tag = stripped[len(Tag.EXPERT_PREFIX):].strip()
        owner_flat = rest_tag.split("/")[0]
      break
    # guard: this is the owned section being stripped — skip it so it is excluded from the kept ranges
    if owner_flat == owned_expert:
      continue  # skip — this is the owned section we want gone
    keep_ranges.append((start, end))
  return "".join(body[s:e] for s, e in keep_ranges)


def check_section_writer_response(
    *,
    operator_body: str,
    agent_body: str,
    owned_expert: str,
) -> OwnershipViolationInfo | None:
  """
  Detect whether the agent's body modifies content outside its owned section.

  Does NOT raise — `reapply` always grafts the operator's body around the agent's owned section
  regardless. The returned info exists so the dispatcher can log the violation, surface a UX
  warning, or quarantine the misbehaving expert without losing the agent's owned-section work.

  Args:
    operator_body: The authoritative document body from the operator.
    agent_body: The document body produced by the section-writer agent.
    owned_expert: Flat expert name identifying the section the agent is permitted to modify.

  Returns:
    `OwnershipViolationInfo` describing the violation if the agent modified content outside its
    owned section, or `None` if the bodies agree on all non-owned content.
  """
  op_view = _strip_owned_section(operator_body, owned_expert)
  agent_view = _strip_owned_section(agent_body, owned_expert)
  if op_view != agent_view:
    return OwnershipViolationInfo(
        expert=owned_expert,
        message=(
            f"section-writer for expert {owned_expert!r} modified content "
            "outside its owned section"
        ),
    )
  return None
