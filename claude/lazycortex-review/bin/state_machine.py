"""Pure decision function: which action does the dispatcher take on
this tick for one file?

The dispatcher pre-computes a :class:`TickInputs` describing the file's
current state and asks :func:`decide` what to do. The function is
side-effect-free; all I/O lives in :mod:`dispatcher`.

Priority order (spec § Lifecycle + § Top-banner):

1. `review_active == False` → skip
2. `parse_failed` (and repair attempts remain) → repair
3. approve / continue / approve-with-concerns gestures → mirror commits
   (must run BEFORE banner-repaint — otherwise the banner-tick strips
   the callout that holds the operator's `- [x]` and the gesture is
   silently lost)
4. `current_banner != desired_banner` → banner-repaint (EXIT — the
   banner-tick invariant: every banner change is its own tick)
5. `approved` — post-approve barrier (spec § Stage 5 / 6):
   a. `operator_reset_pending` → reset-approval (operator edited body
      outside owned sections; re-open the validator barrier)
   b. `approved_with_concerns_active` → finalize (historian-gated)
   c. `concerns_decision_pending` → skip (pause banner shown)
   d. `barrier_writers_to_dispatch` → barrier-dispatch (queue ALL
      pending writers of the current `review_phase` at once)
   e. `barrier_open` → skip (writers still in flight)
   f. `barrier_ready_to_collect` → barrier-collect (N writer commits +
      ONE decision commit, single pass)
   g. `any_unanswered_question` → skip (terminal asked the operator)
   h. `historian_jobs_outstanding` → skip (closed-document gate)
   i. else → finalize
6. `main_chain_pending` → main
7. else → skip

The barrier replaces the old per-validator cascade: ALL validators
(then ALL terminals) speak before ONE decision. Which barrier is open
is explicit frontmatter state (`review_phase`) — never derived from
commit-message parsing — so an operator commit inside the phase
(answering a terminal `[!question]`) does not re-anchor the chain or
re-open a closed barrier.

Historian is NOT dispatched per writer-commit. One historian job is
kicked event-driven from the **approve-mirror** service commit (the one
moment a clean approved document state is reached), runs asynchronously
via the pump, and is picked up by
`dispatcher._pickup_historian_responses` whenever its DONE marker
appears. The only state-machine involvement is the finalize gate
(`historian_jobs_outstanding`) — finalize waits so a late entry never
lands in a closed document. Spec § historian subsystem.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from dataclasses import dataclass, field

import banner as _banner
from keys import Action, Outcome, Phase

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# An ExpertRef is (dispatch_name, role_label).
ExpertRef = tuple[str, str]
# A SectionWriterRef is (dispatch_name, role_label, owned_h1_title,
# post_approve, is_terminal, position):
#
# - `post_approve=True, is_terminal=False` (validation umbrella) —
#   final-as-section pattern (`# Final check`, `# Implementation risks`,
#   …). Non-empty section triggers revert-to-main.
# - `post_approve=True, is_terminal=True` (terminal umbrella) —
#   apply-after-tick pattern (`# Routing` for `spec.request-handler`).
#   Section persists through finalize so a downstream post-finalize
#   transition can read the operator's ticks; never triggers revert-to-
#   main (operator choices are not concerns).
#
# `position` is `"top"` or `"bottom"` — where the section sits in
# the document relative to the operator's free-prose body.
SectionWriterRef = tuple[str, str, str, bool, bool, str]


@dataclass(frozen=True)
class TickInputs:
  """
  Everything `decide` needs to choose an action.

  The dispatcher builds this from disk + git state.
  """

  parse_failed: bool
  repair_attempts_remaining: int
  approved: bool
  main_chain_pending: list[ExpertRef]
  section_writer_pending: list[SectionWriterRef]
  current_banner: _banner.State | None
  desired_banner: _banner.State
  review_active: bool
  # True iff the body shows `- [x] approve the whole document` (operator
  # gesture inside the Ready banner) AND frontmatter `approved` is not
  # yet True. Drives the approve-mirror mechanical step, which MUST run
  # before banner-repaint or the operator's tick is silently destroyed.
  approve_checkbox_ticked: bool = False
  # Post-approve section writers (final-as-section pattern). Fire only
  # after `approved == True`; gated by the same operator-block rule
  # as pre-approve section writers.
  post_approve_section_writer_pending: list[SectionWriterRef] = field(
      default_factory=list,
  )
  # True iff approved AND at least one post-approve section H1 still
  # holds non-empty content. Drives the `revert-to-main` mechanical
  # commit (Phase 3) — final-as-section concerns must be operator-
  # answered through a fresh main-writer round before finalize.
  any_post_approve_section_non_empty: bool = False
  # How many times a post-approve validation writer has emitted a
  # non-empty owned section over the document's lifetime. Counter is
  # monotonic (never resets). At `>= concerns_decision_threshold`
  # (per-class config, default 2) state machine flips from auto
  # revert-to-main into the operator-pause concerns-decision branch.
  # Sourced from frontmatter `review_validation_round`.
  validation_round: int = 0
  # True iff the body shows `- [x] approve with concerns` (operator
  # gesture inside the CONCERNS_DECISION banner body) AND frontmatter
  # `review_approved_with_concerns` is not yet True. Drives the
  # finalize-with-concerns mirror commit.
  approve_with_concerns_ticked: bool = False
  # True iff frontmatter `review_approved_with_concerns: true` is
  # set (mirror commit already wrote it). State machine then bypasses
  # post-approve writers AND any further revert-to-main and dispatches
  # finalize with `with_concerns=true` so validation-owned H1
  # sections are preserved through the strip.
  approved_with_concerns_active: bool = False
  # True iff the body shows `- [x] continue review cycle` (operator
  # gesture inside the CONCERNS_DECISION banner body). State machine
  # responds by dispatching revert-to-main (operator chose to keep
  # iterating).
  continue_review_ticked: bool = False
  # True iff the dispatcher should render the CONCERNS_DECISION banner
  # this tick: `approved == True` AND `any_post_approve_section_non_
  # empty` AND `validation_round >= concerns_decision_threshold`
  # (per-class config, default 2) AND NOT
  # `approved_with_concerns_active`. Computed by the dispatcher and
  # passed in so this module stays a pure decision function.
  concerns_decision_pending: bool = False
  # True iff the body contains at least one `[!question]
  # #review/question` callout with no operator tick inside. Spec
  # Stage 6: a terminal writer may add `[!question]` callouts in
  # its owned section to ask the operator for a choice; finalize must
  # WAIT until the operator answers (state machine reaches the
  # `finalize` branch but defers when this flag is True). Computed
  # by the dispatcher (same predicate banner.py uses for
  # ACTION_NEEDED).
  any_unanswered_question: bool = False
  # Map of (flat_name, section_id) → position ("top" | "bottom") for
  # every registered section writer. Passed through to the assembler
  # via reapply → body.reassemble so each section lands in its
  # configured slot. Default empty dict keeps existing callers working.
  section_layout: dict[tuple[str, str], str] = field(default_factory=dict)
  # True iff the file is freshly opted-in to review (`review_active:
  # true` set by external trigger) but lacks one or more reserved
  # bootstrap fields — `review_round`, `review_approved` in
  # frontmatter, OR a `# History` section. Spec § Stage 1
  # mandates ONE bootstrap commit; the dispatcher piggy-backs the
  # missing-field writes onto the next banner-repaint commit. This
  # flag forces banner-repaint to fire even when current==desired so
  # bootstrap can never silently skip.
  needs_bootstrap: bool = False

  # --- Post-approve barrier (spec § Stage 5 / 6) ---------------------
  # The post-approve phase is a barrier, not a per-writer cascade: ALL
  # validators (then ALL terminals) speak before the dispatcher makes a
  # single decision. The phase the document is in is explicit frontmatter
  # state (`review_phase`) — never derived from commit-message parsing,
  # so an operator commit inside the phase (answering a terminal
  # `[!question]`) does not re-anchor the chain and re-open a closed
  # barrier. Per-writer "spoke?" status is read from the live job queue.
  #
  # Current barrier phase: `"validators"` / `"terminals"` / `None`
  # (not in a post-approve barrier — pre-approve, paused, or finalized).
  review_phase: str | None = None
  # Writers (refs) in the active barrier whose job is missing (never
  # dispatched, or dispatched-and-consumed without landing) → need a
  # fresh dispatch. The barrier-dispatch action queues ALL of them at
  # once (spec "queues jobs for ALL").
  barrier_writers_to_dispatch: list[SectionWriterRef] = field(
      default_factory=list,
  )
  # True iff the active barrier has at least one writer whose job is
  # still in flight (READY/PID, no DONE/DEAD). State machine emits
  # `skip` — the pump drains jobs one by one; the dispatcher waits.
  barrier_open: bool = False
  # True iff every writer in the active barrier has a DONE-or-DEAD job
  # not yet collected (none missing, none in flight) AND at least one
  # such job exists → the sweep-collect tick fires. One pass writes N
  # writer commits + ONE decision commit.
  #
  # Selective respawn (spec § Stage 6) folds in here: when a post-
  # approve operator commit touches a terminal's owned section, that
  # terminal's prior output is stale and the dispatcher re-adds it to
  # `barrier_writers_to_dispatch` — re-queue only the touched ones,
  # never the whole barrier (`review_phase` stays `terminals`, so
  # the validator barrier never re-opens).
  barrier_ready_to_collect: bool = False
  # True iff a post-approve operator commit edited the document OUTSIDE
  # every owned H1 section (free prose / body). The approval is no
  # longer valid: reset `review_approved` and re-open the validator
  # barrier from a fresh main-writer round. Spec § Stage 6 boundary.
  operator_reset_pending: bool = False
  # True iff at least one historian job for this file is still in flight
  # (dispatched, not yet DONE / DEAD / CONSUMED). Finalize WAITS for it
  # — a historian entry that lands after finalize would write into an
  # already-closed document (spec § Stage 7 historian gate). All other
  # banner-flips proceed without this gate.
  historian_jobs_outstanding: bool = False
  # Waiting-banner phase context for title enrichment (spec § Top banner):
  # `"writer"` / `"validators"` / `"terminals"` / `None` (generic
  # "Waiting"). Cosmetic — drives which "Waiting: <…>" title the
  # mechanical banner / decision commit stamps; recognition still keys
  # on the `#review/in-process` tag.
  waiting_context: str | None = None


@dataclass(frozen=True)
class TickAction:
  """
  The dispatcher's marching orders for this tick.
  """

  kind: str  # see module docstring for the closed enum
  expert: ExpertRef | None = None
  owned_section: str | None = None
  banner_state: _banner.State | None = None
  # Waiting-banner title context ("writer" / "validators" / "terminals")
  # carried to the banner-repaint handler for title enrichment.
  waiting_context: str | None = None


def _finalize_ready(inputs: TickInputs) -> bool:
  """
  Return True iff the next real action for an approved document is finalize.

  Single source of truth shared by (a) the banner-repaint guard — skip
  the redundant Waiting/READY repaint when finalize is imminent, since
  finalize strips whatever banner is in body and a separate repaint just
  opens a 5-second operator-edit race (Bug 89) — and (b) the
  `inputs.approved` branch's finalize returns, so the guard can never
  fire finalize where the branch would do something else. Mirrors the
  approved-branch gate sequence exactly; keep the two in sync.

  Two finalize paths: approve-with-concerns (operator accepted the
  concerns as-is, so the remaining barrier / unanswered-question gates
  are bypassed) and clean approve (finalize only once no post-approve
  work remains). Both require: no in-flight historian entry, no pending
  operator reset, bootstrap already done.

  Returns:
    True if finalize is the correct next action; False if any gate blocks it.
  """
  if inputs.needs_bootstrap:
    return False
  if inputs.operator_reset_pending:
    return False
  if inputs.historian_jobs_outstanding:
    return False
  if inputs.approved_with_concerns_active:
    return True
  if not inputs.approved:
    return False
  if inputs.concerns_decision_pending:
    return False
  if (inputs.barrier_writers_to_dispatch
          or inputs.barrier_open
          or inputs.barrier_ready_to_collect):
    return False
  if inputs.any_unanswered_question:
    return False
  return True


def decide(inputs: TickInputs) -> TickAction:
  """
  Return the single action the dispatcher should take for this tick.

  Args:
    inputs: Snapshot of the document's current state for this tick.

  Returns:
    The action the dispatcher should execute, never `None`.
  """
  if not inputs.review_active:
    return TickAction(kind=Outcome.SKIP)

  if inputs.parse_failed:
    if inputs.repair_attempts_remaining > 0:
      return TickAction(kind=Outcome.REPAIR)
  # Exhausted — dispatcher will emit an [!error] callout instead.
    return TickAction(kind=Outcome.SKIP)

# Approve-mirror MUST precede banner-repaint. The operator's approve
# gesture is a `- [x] approve the whole document` tick inside the
# Ready banner body. The very next banner-repaint would strip the
# entire Ready callout (including the checkbox) without copying the
# gesture anywhere. The mirror step writes `approved: true` into
# frontmatter first, so by the time banner-repaint fires the operator
# intent is preserved as durable metadata.
  if inputs.approve_checkbox_ticked and not inputs.approved:
    return TickAction(kind=Action.APPROVE_MIRROR)
# Bug 44 redesign: operator gestures on the CONCERNS_DECISION
# banner. Both mirror commits MUST precede banner-repaint for the
# same reason approve-mirror does — the next banner-repaint would
# strip the entire pause-callout body and lose the operator's tick.
  if inputs.approve_with_concerns_ticked and not inputs.approved_with_concerns_active:
    return TickAction(kind=Action.APPROVE_WITH_CONCERNS_MIRROR)
  if inputs.continue_review_ticked:
      # No frontmatter mirror — the continue gesture is a one-shot
      # signal to drop the pause and run the standard revert-to-main
      # cycle. The dispatcher handles validation_round independently
      # (it's incremented by the validation writer dispatch, not the
      # operator choice).
    return TickAction(kind=Action.CONTINUE_REVIEW_MIRROR)

# Banner-tick invariant: any banner mismatch wins, even if other
# branches would also fire. Other branches re-evaluate next tick.
# `needs_bootstrap` also routes through this branch — the bootstrap
# piggy-back logic lives in the banner-repaint apply-action (writes
# the missing `review_round` / `review_approved` / `# History`
# alongside the banner). If banner already matches desired, the
# bootstrap would silently skip without this extra condition.
  if inputs.current_banner != inputs.desired_banner or inputs.needs_bootstrap:
      # Skip the redundant banner repaint when finalize is already
      # inevitable — fold it into the finalize commit. Painting a
      # Waiting/READY banner first opens a 5-second window between the
      # repaint commit and the finalize commit during which an operator
      # edit trips the conflict guard and stalls the chain; finalize
      # strips whatever banner is in body anyway, so the repaint adds
      # nothing. `_finalize_ready` is the SAME predicate the
      # `inputs.approved` branch uses, so the guard never fires
      # finalize where the branch would act differently. (Bug 89: the
      # old guard was READY-only + `review_phase is None`, so approve-
      # with-concerns and terminals-drained finalize fell through to a
      # pointless Waiting repaint.)
    if _finalize_ready(inputs):
      return TickAction(kind=Phase.FINALIZE)
    return TickAction(
        kind=Action.BANNER_REPAINT,
        banner_state=inputs.desired_banner,
        waiting_context=inputs.waiting_context,
    )

  if inputs.approved:
      # Spec § Stage 6 boundary: a post-approve operator commit that
      # edited the body OUTSIDE every owned section invalidates the
      # approval — reset and re-open the validator barrier from a fresh
      # main round. Highest post-approve priority: it supersedes any
      # in-flight barrier state.
    if inputs.operator_reset_pending:
      return TickAction(kind=Action.RESET_APPROVAL)
  # Bug 44 redesign: finalize-with-concerns bypasses the remaining
  # barriers AND any revert. The operator explicitly chose (on the
  # CONCERNS_DECISION pause banner) to accept the outstanding
  # concerns as-is; finalize preserves validation-owned H1 sections.
  # Closed-document invariant: still wait for any in-flight
  # historian entry before finalize (spec § Stage 7).
    if inputs.approved_with_concerns_active:
      if inputs.historian_jobs_outstanding:
        return TickAction(kind=Outcome.SKIP)
      return TickAction(kind=Phase.FINALIZE)
  # Bug 44 redesign: concerns-decision pause. After the configured
  # number of validator passes with concerns, the dispatcher does
  # NOT auto-revert; the banner becomes CONCERNS_DECISION and the
  # operator must choose continue vs finalize-with-concerns. The
  # banner-repaint above renders it; nothing else happens this tick.
    if inputs.concerns_decision_pending:
      return TickAction(kind=Outcome.SKIP)

  # --- Post-approve barrier (spec § Stage 5 / 6) -----------------
  # `review_phase` (frontmatter) says which barrier is open. ALL
  # writers of the phase speak before ONE decision lands. Per-writer
  # status is read from the job queue, so an operator commit inside
  # the phase never re-opens a closed barrier.
  #
  # 1. Writers needing dispatch (missing job, or a touched terminal
  #    flagged for selective respawn) → queue them ALL in one pass.
    if inputs.barrier_writers_to_dispatch:
      return TickAction(kind=Action.BARRIER_DISPATCH)
  # 2. Some writer still in flight → wait (pump drains serially).
    if inputs.barrier_open:
      return TickAction(kind=Outcome.SKIP)
  # 3. Every writer DONE-or-DEAD → sweep-collect: N writer commits +
  #    ONE decision commit, in a single pass.
    if inputs.barrier_ready_to_collect:
      return TickAction(kind=Action.BARRIER_COLLECT)

  # Barrier drained with no work pending. A terminal may have left
  # an unanswered `[!question]` for the operator → wait for the
  # answer (banner already shows ACTION_NEEDED).
    if inputs.any_unanswered_question:
      return TickAction(kind=Outcome.SKIP)

  # Ready to finalize — but the historian is event-driven and
  # asynchronous; an entry that lands after finalize would write
  # into a closed document. Wait for any in-flight historian job
  # (spec § Stage 7 historian gate).
    if inputs.historian_jobs_outstanding:
      return TickAction(kind=Outcome.SKIP)
    return TickAction(kind=Phase.FINALIZE)

  if inputs.main_chain_pending:
    return TickAction(kind=Phase.MAIN, expert=inputs.main_chain_pending[0])

  return TickAction(kind=Outcome.SKIP)
