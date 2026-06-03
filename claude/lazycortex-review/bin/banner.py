"""Top-of-body status callout (the "banner").

Pure-function module. Recognises and renders the three banner states
defined by the spec § Top-banner. The state machine owns the *when*
of repaints; this module owns the *what*.

Key invariants enforced here:

- Recognition keys on the `#review/<tag>` token in the callout's
  first line — never on the `[!hint]` / `[!caution]` / `[!success]`
  marker. Operator-authored callouts without the tag are invisible to
  this module.
- :func:`desired_state` for `OPERATOR_COMMITTED` and
  `CHAIN_IN_PROGRESS` dispatch states always returns
  :attr:`State.IN_PROCESS`: the operator's hand-off is unconditional
  ("Waiting" rules until the chain exhausts and is ready to hand back").
- :func:`render` for :attr:`State.READY` is the SOLE place the
  `- [ ] approve the whole document` checkbox appears. The other
  two states never carry it.
- Banner is anchored above the first H1 of the body. Mid-body banner-
  shaped callouts (stale, mis-pasted) are ignored by :func:`extract`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,deprecated-module

import enum
import re

from keys import Phase

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------- enums


class State(enum.Enum):
  """
  Banner state rendered at the top of a review document.

  Callers read this to determine what the current document banner communicates to the operator
  and drive banner-repaint decisions.
  """

  IN_PROCESS = "in-process"
  ACTION_NEEDED = "action-needed"
  READY = "ready"
  CONCERNS_DECISION = "concerns-decision"
  FINALIZING = "finalizing"


class DispatchState(enum.Enum):
  """
  Phase of the current dispatch cycle for a review document.

  Callers use this to determine whether agents are still working or whether the chain has
  returned control to the operator.
  """

  OPERATOR_COMMITTED = "operator-committed"
  CHAIN_IN_PROGRESS = "chain-in-progress"
  CHAIN_EXHAUSTED = "chain-exhausted"


# --------------------------------------------------------- tag / shape


_TAG_TO_STATE = {
    "in-process": State.IN_PROCESS,
    "action-needed": State.ACTION_NEEDED,
    "ready": State.READY,
    "concerns-decision": State.CONCERNS_DECISION,
    "finalizing": State.FINALIZING,
}

_FIRST_LINE_RE = re.compile(r"^>\s*\[!\w+\][^#\n]*#review/([a-z-]+)\s*$")

_H1_RE = re.compile(r"^# .+$", re.MULTILINE)


# ------------------------------------------------------------ extract


def extract(body: str) -> State | None:
  """
  Find the banner above the first H1 of `body` and return its `State`, or `None` when no banner is present.

  Mid-body callouts (anything after the first H1) are scaffold logs or stale snapshots, never the banner.

  Args:
    body: Full document text to search.

  Returns:
    The `State` encoded in the banner tag, or `None` if no banner is found above the first H1.
  """
  h1 = _H1_RE.search(body)
  scan_end = h1.start() if h1 else len(body)
  region = body[:scan_end]
  for line in region.splitlines():
    match = _FIRST_LINE_RE.match(line)
    # guard: skip non-banner lines in the pre-H1 region so only the first banner-tag line decides the state
    if match is None:
      continue
    return _TAG_TO_STATE.get(match.group(1))
  return None


# -------------------------------------------------------- desired_state


_QUESTION_OPEN_RE = re.compile(
    r"^>\s*\[!question\].*#review/question.*$",
    re.MULTILINE,
)
_CONCERN_RE = re.compile(
    r"^>\s*\[!attention\].*#review/concern.*$",
    re.MULTILINE,
)
_TICKED_OPTION_RE = re.compile(r"^>\s*-\s*\[x\]", re.MULTILINE | re.IGNORECASE)


def _find_callout_block(body: str, header_match: re.Match[str]) -> str:
  """
  Return the full `> `-prefixed block starting at `header_match`.

  Args:
    body: Document text to slice from.
    header_match: Regex match whose `start()` marks the callout header line.

  Returns:
    All consecutive `>`-prefixed lines from the match position, joined by newlines.
  """
  start = header_match.start()
  lines = body[start:].splitlines()
  collected: list[str] = []
  for line in lines:
    if not line.startswith(">"):
      break
    collected.append(line)
  return "\n".join(collected)


def _any_unanswered_question(body: str) -> bool:
    # Strip code-fence regions — callout-shaped lines inside ```...```
    # fences are body content, never gating callouts (see parser.strip_code_fences).
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import parser as _parser
  scan_body = _parser.strip_code_fences(body)
  for m in _QUESTION_OPEN_RE.finditer(scan_body):
    block = _find_callout_block(scan_body, m)
    if not _TICKED_OPTION_RE.search(block):
      return True
  return False


def _any_concern(body: str) -> bool:
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import parser as _parser
  scan_body = _parser.strip_code_fences(body)
  return _CONCERN_RE.search(scan_body) is not None


def desired_state(
    *,
    body: str,
    dispatch_state: DispatchState,
    approved: bool = False,
    domain_ready: bool = True,
    concerns_decision_pending: bool = False,
    review_phase: str | None = None,
) -> State:
  """
  Compute the banner state appropriate for the current tick.

  - `OPERATOR_COMMITTED` / `CHAIN_IN_PROGRESS` → always `State.IN_PROCESS` (agents work next; operator waits).
  - `CHAIN_EXHAUSTED` → recompute by the spec table:

    1. `concerns_decision_pending` (approved + validation H1 non-empty +
       `review_validation_round >= concerns_decision_threshold` (per-class config, default 2) + no
       `review_approved_with_concerns: true`) → CONCERNS_DECISION (highest priority — operator must
       choose continue vs finalize-with-concerns before any other gate applies).
    2. open `#review/question` or `#review/concern` → ACTION_NEEDED
    3. consumer's `domain_ready` predicate False → ACTION_NEEDED
    4. `approved == True` → phase-aware:
         - `review_phase in {"validators", "terminals"}` → `IN_PROCESS`. Validators (Стадия 5) and
           terminals (Стадия 6) are post-approve barriers that run BEFORE finalize; the caller passes
           a matching `waiting_context` to `replace_banner` so the rendered title reads "Waiting:
           validators" / "Waiting: terminals". Without this branch the generic post-tick repaint
           paints "Waiting: finalize" while validators or terminals are still in flight, which
           misrepresents the current phase to the operator.
         - `review_phase in {None, "finalizing"}` (or any other value) → `FINALIZING`. Finalize is
           in flight, no further waiting work; the chain is heading to the finalize commit, not
           back to the pre-approve `Ready to approve` callout. (Bug 114 — without this gate the
           post-approve banner-tick would repaint over the approved-mirror, showing
           `- [ ] approve the whole document` on top of a doc whose frontmatter already carries
           `review_approved: true`.)
    5. else → READY

  Args:
    body: Full document text, scanned for open questions and concerns.
    dispatch_state: Current phase of the dispatch cycle.
    approved: Frontmatter-mirrored approve flag; `True` after the dispatcher has mirrored the operator's
      `- [x] approve the whole document` tick into `review_approved`.
    domain_ready: Consumer-supplied predicate; `False` forces `ACTION_NEEDED`.
    concerns_decision_pending: When `True`, forces `CONCERNS_DECISION` before all other gates.
    review_phase: Frontmatter `review_phase` value (`validators` / `terminals` / `concerns-pause` /
      `finalizing` / `main` / `awaiting-operator` / `bootstrapping`) or `None` when absent. When
      `approved == True` and `dispatch_state == CHAIN_EXHAUSTED`, drives the validators/terminals →
      `IN_PROCESS` vs finalizing → `FINALIZING` branch above. Ignored when `approved == False`.

  Returns:
    The `State` the banner should display for this tick.
  """
  if dispatch_state is not DispatchState.CHAIN_EXHAUSTED:
    return State.IN_PROCESS
  if concerns_decision_pending:
    return State.CONCERNS_DECISION
  if _any_unanswered_question(body) or _any_concern(body):
    return State.ACTION_NEEDED
  if not domain_ready:
    return State.ACTION_NEEDED
  if approved:
    # guard: validators / terminals run BEFORE finalize; caller passes waiting_context to replace_banner
    if review_phase in ("validators", "terminals"):
      return State.IN_PROCESS
    return State.FINALIZING
  return State.READY


# ------------------------------------------------------------- render


# Spec § Top banner: the "Waiting" title is enriched with the phase the
# document is waiting on ("Waiting: validators" / ": writer" / ": terminals").
# Recognition keys on the `#review/in-process` TAG, never the title, so
# enriched and bare titles both extract to `State.IN_PROCESS`.
_WAITING_CONTEXT_LABELS = {
    "writer":     "Waiting: writer",
    "validators": "Waiting: validators",
    "terminals":  "Waiting: terminals",
    Phase.FINALIZE:   "Waiting: finalize",
}

_TEMPLATES: dict[State, str] = {
    State.IN_PROCESS: "> [!hint] {title} #review/in-process\n",
    State.ACTION_NEEDED: "> [!caution] Action needed #review/action-needed\n",
    State.READY: (
        "> [!success] Ready to approve #review/ready\n"
        "> Tick the box below to approve the whole document.\n"
        "> - [{tick}] approve the whole document\n"
    ),
    State.FINALIZING: "> [!hint] Waiting: finalize #review/finalizing\n",
}

_CONCERNS_DECISION_TEMPLATE = (
    "> [!warning] Outstanding concerns — choose how to proceed #review/concerns-decision\n"
    "> The validation writer raised concerns up to the configured pause threshold. The section(s) below show them. Tick ONE of the boxes:\n"
    "> - [{tick_continue}] continue review cycle — answer the concerns in the next main-writer round and re-approve\n"
    "> - [{tick_approve}] approve with concerns — accept the concerns recorded below as-is and finalize the document\n"
)


def render(
    state: State,
    *,
    approved: bool = False,
    continue_review: bool = False,
    approve_with_concerns: bool = False,
    waiting_context: str | None = None,
) -> str:
  """
  Render the callout markdown for `state`.

  - For `State.READY`, `approved=True` produces a ticked checkbox (mirrors frontmatter `review_approved`
    for visual consistency).
  - For `State.CONCERNS_DECISION`, the dual-checkbox body is rendered; `continue_review` ticks the first
    option and `approve_with_concerns` ticks the second.
  - For `State.IN_PROCESS`, `waiting_context` enriches the title ("Waiting: validators" etc.);
    unknown or `None` → bare "Waiting".

  Args:
    state: Banner state to render.
    approved: Ticks the approval checkbox when rendering `State.READY`.
    continue_review: Ticks the "continue review cycle" checkbox when rendering `State.CONCERNS_DECISION`.
    approve_with_concerns: Ticks the "approve with concerns" checkbox when rendering `State.CONCERNS_DECISION`.
    waiting_context: Phase label inserted into the `State.IN_PROCESS` title; `None` yields bare "Waiting".

  Returns:
    Callout markdown string for the given state, ready to embed in the document body.
  """
  if state is State.CONCERNS_DECISION:
    return _CONCERNS_DECISION_TEMPLATE.format(
        tick_continue = "x" if continue_review        else " ",
        tick_approve = "x" if approve_with_concerns else " ",
    )
  template = _TEMPLATES[state]
  if state is State.READY:
    return template.format(tick="x" if approved else " ")
  if state is State.IN_PROCESS:
    # waiver: one-off human-facing message
    title = _WAITING_CONTEXT_LABELS.get(waiting_context or "", "Waiting")
    return template.format(title=title)
  return template


# ---------------------------------------------------- replace_banner


_BANNER_BLOCK_RE = re.compile(
    r"(?ms)"  # multiline + dotall
    r"^>\s*\[!\w+\][^\n]*#review/(?:in-process|action-needed|ready|concerns-decision|finalizing)[^\n]*\n"
    r"(?:>[^\n]*\n)*"  # continuation lines of the callout
    r"(?:\n)*"  # optional blank lines after the callout
)

# A leading YAML frontmatter block, when the caller passes a full-document
# body rather than a post-frontmatter one. The banner anchors BELOW it.
_LEADING_FRONTMATTER_RE = re.compile(r"(?s)\A---\n.*?\n---\n")


def replace_banner(
    body: str,
    state: State,
    *,
    approved: bool = False,
    continue_review: bool = False,
    approve_with_concerns: bool = False,
    waiting_context: str | None = None,
) -> str:
  """Return `body` with its banner replaced (or inserted, if absent).

    The new banner is rendered for `state` and anchored as the first
    non-empty line of the body — directly below a leading YAML
    frontmatter block when the caller passes one, never above it. Any
    existing banner block is removed first, *wherever* it sits: a round
    that assembled a body without its title H1 leaves the prior banner
    mis-anchored below the content (the old "above the first H1" rule
    then picked `# History` as the anchor and parked the banner at the
    bottom — Bug 105), so a head-only strip would duplicate it. Leading
    whitespace ahead of the banner is dropped so the banner sits flush
    against whatever precedes the body and the blank-line-or-not
    ambiguity (Bug 30 part a) can't bleed in.

    Returns:
      The body with exactly one banner block, anchored at the top of the
      content below any leading frontmatter.
    """
  new_banner = render(
      state,
      approved=approved,
      continue_review=continue_review,
      approve_with_concerns=approve_with_concerns,
      waiting_context=waiting_context,
  ) + "\n"
  # Split a leading frontmatter block so the banner never lands above it.
  fm = _LEADING_FRONTMATTER_RE.match(body)
  fm_prefix = fm.group(0) if fm is not None else ""
  rest = body[len(fm_prefix):]
  # Strip the existing banner block wherever it sits (top OR mis-anchored
  # below the content), then anchor the fresh banner flush at the top of
  # the remaining content. Independent of where the first H1 is, so a
  # dropped title can no longer push the banner down to `# History`.
  rest = _BANNER_BLOCK_RE.sub("", rest, count=1).lstrip("\n")
  return fm_prefix + new_banner + rest
