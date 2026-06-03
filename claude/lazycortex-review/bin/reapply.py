"""Top-level entry that validates an agent reply and grafts it onto
the operator's current document.

The hard logic of "what flows back from the agent under each role"
lives in :mod:`body.reassemble`. This module's job is to:

- Refuse the reply when the frontmatter overlay touches reserved keys
  (`review_active` / `review_round` / `approved`) — that IS a hard
  error and the agent must be reprompted.
- For section-writers, ALWAYS produce a grafted result by ignoring the
  agent's body edits outside its owned section. If the agent did touch
  content outside its owned section, the diagnostic is surfaced via the
  `ownership_violation` field of :class:`ReapplyResult` — the caller
  decides whether to log it, raise a UX warning, or carry on silently.
  The graft itself always succeeds.

The graft is delegated to `body.reassemble`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from dataclasses import dataclass

import body as _body
import edit_markup as _edit_markup
import frontmatter as _fm
import payload as _payload
from keys import Phase

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping


# Type alias for the section-layout map forwarded from TickInputs.
_SectionLayout = dict[tuple[str, str], str]


@dataclass(frozen=True)
class ReapplyResult:
  """Result of :func:`reapply`. Always carries the grafted document
    text; `ownership_violation` is non-None only when the agent (a
    section-writer) modified content outside its owned section. The
    text in that case is the graceful-clipped version — agent's body
    edits ignored, agent's owned section spliced into the operator's
    body."""
  text: str
  ownership_violation: _payload.OwnershipViolationInfo | None = None


def reapply(
    *,
    operator_text: str,
    agent_body: str,
    phase: str,
    agent_frontmatter_overlay: Mapping[str, object],
    owned_owner: tuple[str, str] | None = None,
    section_layout: _SectionLayout | None = None,
    require_fm: frozenset[str] = frozenset(),
) -> ReapplyResult:
  """Validate `agent_body` and `agent_frontmatter_overlay` against
    the ownership-isolation contract, then graft the result onto
    `operator_text`. Returns a :class:`ReapplyResult` whose `text`
    field is the new full document text.

    `phase` is the writer pipeline phase (`'main'` / `'section'`
    / `'final'`). Distinct from the section-group label that lives
    in state-machine routing tables.

    For `phase='section'`, `owned_owner` (the `(flat_name,
    section_id)` pair) is required. A body-drift diagnostic is reported
    via `ReapplyResult.ownership_violation` but the graft proceeds
    regardless — agent's body edits outside the owned section are
    silently ignored by `body.reassemble`.

    `section_layout` is the `(flat_name, section_id) → position`
    map forwarded from `TickInputs.section_layout`. Passed unchanged
    to `body.reassemble` so each owned section lands in its configured
    top/bottom slot. `None` defaults to bottom placement for all
    sections (existing caller behaviour preserved).

    Returns:
        `ReapplyResult` with `text` set to the grafted full document. `ownership_violation`
        is non-`None` only when a section-writer modified content outside its owned section;
        in that case `text` still contains the gracefully clipped result.

    Raises:
        ValueError:          when `phase` is unrecognised, `phase="section"` but
                             `owned_owner` is missing, or a `require_fm` key is absent
                             from both the overlay and the operator's frontmatter.
    """
  # The overlay is already allow-filtered at the dispatcher collect seam
  # (review.classes[].experts.*.frontmatter.allow). Enforce the require half here: a
  # required key must end up set — written this round (overlay) OR already present from an
  # earlier round (operator frontmatter). The router declares require: [request_class] so a
  # run that fails to classify is caught rather than silently committed.
  if require_fm:
    _op_meta, _ = _fm.parse(operator_text)
    _missing = set(require_fm) - (set(agent_frontmatter_overlay) | set(_op_meta))
    # guard: a required key absent from both overlay and operator frontmatter means classification failed — fail rather than commit silently
    if _missing:
      raise ValueError(f"missing required frontmatter keys: {sorted(_missing)}")
# Defensive normalize: drop ```diff fences that only wrap whitespace
# differences (Bug 28). Writer's whitespace reflow does not earn a
# diff-block — the operator should see the paragraph raw.
  agent_body = _edit_markup.drop_whitespace_only_diff_fences(agent_body)

  # Section-writer body-drift check — diagnostic only, never blocks.
  ownership_violation: _payload.OwnershipViolationInfo | None = None
  if phase == Phase.SECTION:
    # guard: section phase needs the owner pair to run the body-drift check; bail loudly rather than NoneType-crash downstream
    if owned_owner is None:
      raise ValueError("reapply(phase='section') requires owned_owner")
    _, op_body = _fm.parse(operator_text)
    # payload.check_section_writer_response still takes a flat-name
    # string; extract the first element of the pair.
    owned_expert_flat = owned_owner[0]
    ownership_violation = _payload.check_section_writer_response(
        operator_body=op_body,
        agent_body=agent_body,
        owned_expert=owned_expert_flat,
    )

  text = _body.reassemble(
      operator_text=operator_text,
      agent_body=agent_body,
      phase=phase,
      owned_owner=owned_owner,
      agent_frontmatter_overlay=agent_frontmatter_overlay,
      section_layout=section_layout,
  )
  return ReapplyResult(text=text, ownership_violation=ownership_violation)
