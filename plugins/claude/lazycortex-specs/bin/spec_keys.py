"""
Centralized frontmatter key names, value tokens, and outcome tokens for the
mechanical request opt-in transition.

The opt-in handler reads and writes a fixed set of `spec_*` / `review_*`
frontmatter keys and compares a fixed set of status / state / outcome tokens as
strings. Defining them once here means a mistyped key surfaces as an
`AttributeError` at import time rather than as silent state corruption in the
running md-scan routine.

Each container below holds plain `str` constants whose values are byte-identical
to the literals they replace — they are NOT enums, so `value == Container.X`
stays a string comparison and parsed strings keep matching.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class SpecKey:
  """
  Frontmatter key names managed by the request opt-in transition.

  Attributes:
    ROLE: The `spec_role` discriminator marking a file as a request.
    STATUS: The `request_status` lifecycle field.
    CLASS: The `request_class` classification field.
    REVIEW_ACTIVE: Whether the file is opted into the review loop.
    REVIEW_ROUND: The current review round counter.
    REVIEW_APPROVED: The whole-document approval flag.
    REVIEW_PHASE: The current review-loop writer phase, seeded by lazycortex-review's
      `start` verb (mirrors `keys.ReviewKey.PHASE`).
    REVIEW_MAIN_DONE: The bracketed list of main writers already run, seeded alongside
      `REVIEW_PHASE` (mirrors `keys.ReviewKey.MAIN_DONE`).
    REVIEW_RESULT: The terminal apply-gate discriminator stamped at finalize.
  """

  # The `spec_role` discriminator marking a file as a request.
  ROLE = "spec_role"
  # The `request_status` lifecycle field.
  STATUS = "request_status"
  # The `request_class` classification field.
  CLASS = "request_class"
  # Whether the file is opted into the review loop.
  REVIEW_ACTIVE = "review_active"
  # The current review round counter.
  REVIEW_ROUND = "review_round"
  # The whole-document approval flag.
  REVIEW_APPROVED = "review_approved"
  # The current review-loop writer phase, seeded by lazycortex-review's `start` verb (mirrors
  # `keys.ReviewKey.PHASE`).
  REVIEW_PHASE = "review_phase"
  # The bracketed list of main writers already run, seeded alongside `REVIEW_PHASE` (mirrors
  # `keys.ReviewKey.MAIN_DONE`).
  REVIEW_MAIN_DONE = "review_main_done"
  # The terminal apply-gate discriminator stamped at finalize.
  REVIEW_RESULT = "review_result"


# ----------------------------------------------------------------------------------------
class ReviewResultValue:
  """
  The `review_result` verdict tokens a finalized review round stamps onto a document.

  Attributes:
    APPROVED: A round that closed with no reviewer concerns.
    APPROVED_WITH_CONCERNS: A round that closed accepted, with concerns recorded alongside it.
    ACCEPTED: Both terminal values that count as the document being accepted — a coordinator
      reacting to `SpecKey.REVIEW_RESULT` treats either the same way; only a value outside this
      set (a rejection, or the reopened token) withholds acceptance.
  """

  # A round that closed with no reviewer concerns.
  APPROVED = "approved"
  # A round that closed accepted, with concerns recorded alongside it.
  APPROVED_WITH_CONCERNS = "approved-with-concerns"
  # Both terminal values that count as the document being accepted — a coordinator reacting to
  # `SpecKey.REVIEW_RESULT` treats either the same way; only a value outside this set (a rejection, or the reopened
  # token) withholds acceptance.
  ACCEPTED = frozenset({ APPROVED, APPROVED_WITH_CONCERNS })


# ----------------------------------------------------------------------------------------
class SpecValue:
  """
  Frontmatter value tokens written and compared as strings.

  Attributes:
    ROLE_REQUEST: The canonical `spec_role` value for a request file.
    ROLE_STATUS: The `spec_role` value marking an asset's own status folder-note.
    ROLE_PRODUCT: The `spec_role` value marking a product's level note — the folder-note
      owning the product's own system documents.
    ROLE_CATALOG: The `spec_role` value marking the catalog root's level note — the
      folder-note owning the content-root's system documents and its split into products.
    CLASS_UNKNOWN: The unclassified `request_class` value.
    STATUS_DRAFT: The pre-terminal `request_status` value.
    TAG_DRAFT: The `tags:` member added on opt-in.
  """

  # Domain(spec.lifecycle):
  # # A note's declared role decides which coordinator drives it
  # Every folder-note that participates in automation declares what kind of note it is, and that
  # declaration alone decides which of two coordinating personas acts on it — never its position
  # in the folder tree, never a guess from its content. A note declaring itself a product's own
  # level note or the catalog root's own level note is driven by the persona that owns the whole
  # catalog structure; every other participating note is driven by the persona that owns one
  # asset's own progress. The two personas never both react to the same note, so a role that a
  # note has not declared is a role nothing is watching for it.

  # The canonical `spec_role` value for a request file.
  ROLE_REQUEST = "request"
  # The `spec_role` value marking an asset's own status folder-note.
  ROLE_STATUS = "status"
  # The `spec_role` value marking a product's level note — the folder-note owning the product's own system documents.
  ROLE_PRODUCT = "product"
  # The `spec_role` value marking the catalog root's level note — the folder-note owning the content-root's system
  # documents and its split into products.
  ROLE_CATALOG = "catalog"
  # The unclassified `request_class` value.
  CLASS_UNKNOWN = "unknown"
  # The pre-terminal `request_status` value.
  STATUS_DRAFT = "draft"
  # The `tags:` member added on opt-in.
  TAG_DRAFT = "request/draft"


# The two roles the catalog coordinator owns; an asset's `ROLE_STATUS` note stays the asset
# coordinator's, so the dispatcher routes on membership here rather than on a per-role branch.
LEVEL_ROLES = frozenset({ SpecValue.ROLE_PRODUCT, SpecValue.ROLE_CATALOG })


# ----------------------------------------------------------------------------------------
class BannerTag:
  """
  Review-status banner tags compared as substrings.

  Attributes:
    IN_PROCESS: The Waiting banner tag for a file under review.
    ACTION_NEEDED: The banner tag for a file awaiting an operator gesture.
    READY: The banner tag for a finalized-ready file.
  """

  # The Waiting banner tag for a file under review.
  IN_PROCESS = "#review/in-process"
  # The banner tag for a file awaiting an operator gesture.
  ACTION_NEEDED = "#review/action-needed"
  # The banner tag for a finalized-ready file.
  READY = "#review/ready"


# ----------------------------------------------------------------------------------------
class State:
  """
  Classifier state value tokens compared as strings.

  Attributes:
    NAKED: A file with no frontmatter.
    PARTIAL: A file with incomplete opt-in shape.
    READY: A fully opted-in file.
    READY_FOR_APPLY: A post-finalize file owned by the apply-gate routine.
    TERMINAL: A file in a terminal `request_status`.
    UNKNOWN: A file with frontmatter but no recognised `request_status`.
  """

  # A file with no frontmatter.
  NAKED = "naked"
  # A file with incomplete opt-in shape.
  PARTIAL = "partial"
  # A fully opted-in file.
  READY = "ready"
  # A post-finalize file owned by the apply-gate routine.
  READY_FOR_APPLY = "ready-for-apply"
  # A file in a terminal `request_status`.
  TERMINAL = "terminal"
  # A file with frontmatter but no recognised `request_status`.
  UNKNOWN = "unknown-state"


# ----------------------------------------------------------------------------------------
class Outcome:
  """
  Opt-in transition outcome value tokens compared as strings.

  Attributes:
    OPENED: A naked file brought to the canonical opt-in shape.
    REPAIRED: A partial file completed to the canonical shape.
    ALREADY_OPTED_IN: A no-op on an already-ready file.
    READY_FOR_APPLY_SKIP: A no-op on a post-finalize file.
    TERMINAL_STATE_SKIP: A no-op on a terminal-status file.
    UNKNOWN_STATE_SKIP: A no-op on an unrecognised-status file.
  """

  # A naked file brought to the canonical opt-in shape.
  OPENED = "opened"
  # A partial file completed to the canonical shape.
  REPAIRED = "repaired"
  # A no-op on an already-ready file.
  ALREADY_OPTED_IN = "already-opted-in"
  # A no-op on a post-finalize file.
  READY_FOR_APPLY_SKIP = "ready-for-apply-skip"
  # A no-op on a terminal-status file.
  TERMINAL_STATE_SKIP = "terminal-state-skip"
  # A no-op on an unrecognised-status file.
  UNKNOWN_STATE_SKIP = "unknown-state-skip"


# ----------------------------------------------------------------------------------------
class Gate:
  """
  Flat top-level boolean gate key names carried by an asset status folder-note, or — for the
  five level gates — by a product's or the catalog root's own level note.

  `DESIGN_DONE` serves both ladders: the key is the same string on either note, and the note's
  own `spec_role` says which ladder it belongs to.

  Attributes:
    DESIGN_DONE: The design-accepted gate.
    PLAN_DONE: The plan-accepted gate.
    DEVELOP_DONE: The development-complete gate.
    TESTS_PASSING: The tests-passing gate.
    RELEASED: The released gate.
    SPEC_CANCELLED: The asset-cancelled flag that refuses every gate flip.
    VISION_DONE: The level ladder's vision-accepted gate.
    USE_CASES_DONE: The level ladder's use-cases-accepted gate.
    UI_DESIGN_DONE: The level ladder's ui-design-accepted gate.
    TECH_DONE: The level ladder's tech-accepted gate.
  """

  # Domain(spec.lifecycle):
  # # Derived gates versus human-confirmed gates
  # A checkpoint closes one of two ways. Every checkpoint of a product's or the catalog's ladder,
  # and the first two checkpoints of an asset's five-step ladder, are settled entirely by a
  # sibling document's own approval — once that document is accepted, the checkpoint simply
  # reflects it, with no separate confirmation of its own. The remaining three checkpoints of the
  # asset ladder —
  # the deliverable being built, its tests passing, its release — answer a question no document
  # approval can settle by itself, so each one waits for an explicit confirmation from outside
  # the automation before it closes.

  # The design-accepted gate.
  DESIGN_DONE = "spec_design_done"
  # The plan-accepted gate.
  PLAN_DONE = "spec_plan_done"
  # The development-complete gate.
  DEVELOP_DONE = "spec_develop_done"
  # The tests-passing gate.
  TESTS_PASSING = "spec_tests_passing"
  # The released gate.
  RELEASED = "spec_released"
  # The asset-cancelled flag that refuses every gate flip.
  SPEC_CANCELLED = "spec_cancelled"
  # The level ladder's vision-accepted gate.
  VISION_DONE = "spec_vision_done"
  # The level ladder's use-cases-accepted gate.
  USE_CASES_DONE = "spec_use_cases_done"
  # The level ladder's ui-design-accepted gate.
  UI_DESIGN_DONE = "spec_ui_design_done"
  # The level ladder's tech-accepted gate.
  TECH_DONE = "spec_tech_done"


# ----------------------------------------------------------------------------------------
class Stage:
  """
  Per-file `spec_stage` value tokens carried by authored spec docs.

  Attributes:
    EMPTY: A scaffolded but unwritten doc.
    DRAFT: A doc with content awaiting approval.
    APPROVED: An accepted doc.
    REJECTED: A doc turned away.
    CANCELLED: A doc whose work is abandoned.
    DEFERRED: A doc parked out of the automation's reach — no coordinator reacts to it, no gate
      reads it, and `draft` is the only way back out.
  """

  # Domain(spec.lifecycle):
  # # A deferred document is invisible to automation until reclaimed
  # A document can be parked outside the automation's reach at any point in its own approval
  # cycle — nothing reacts to it, and nothing that depends on its acceptance is unblocked by it,
  # for as long as it stays parked. There is exactly one way back: putting the document back into
  # active drafting is what makes it visible again, at which point its approval cycle resumes
  # from that same starting point rather than from wherever it was parked.

  # A scaffolded but unwritten doc.
  EMPTY = "empty"
  # A doc with content awaiting approval.
  DRAFT = "draft"
  # An accepted doc.
  APPROVED = "approved"
  # A doc turned away.
  REJECTED = "rejected"
  # A doc whose work is abandoned.
  CANCELLED = "cancelled"
  # A doc parked out of the automation's reach — no coordinator reacts to it, no gate reads it, and `draft` is the
  # only way back out.
  DEFERRED = "deferred"


# Decision: the asset's paint state is a written key, not a matcher-computed one — `IN_REVIEW`
# lives as `review_active` on a sibling document and `IMPLEMENTATION` / `TESTING` track a job in
# the gitignored runtime sidecar, neither of which an iconize matcher can read from the status
# note it paints.

# ----------------------------------------------------------------------------------------
class AssetState:
  """
  `spec_state` value tokens carried by an asset's status folder-note.

  The key is derived, not recorded: the coordinator writes it on the same wake that rebuilds
  `# Status brief`, and the iconize registry paints the asset folder from it.

  Attributes:
    DRAFT: Design is being written and is not approved yet.
    IN_REVIEW: One of the asset's documents is in the review loop.
    IMPLEMENTATION: An implementation job is in flight, or `spec_develop_done` is still open.
    TESTING: A test run is under way, or `spec_tests_passing` is still open.
    DEFERRED: Every stage-bearing sibling document sits at `spec_stage: deferred` and the only
      launch rows hanging are those documents' own `Review <doc>` rows — a parked backlog, not
      an operator anyone is waiting on. Judged ahead of `WAITS_OPERATOR`, whose hanging-checkbox
      condition those `Review` rows would otherwise satisfy.
    WAITS_OPERATOR: A launch checkbox or a `[!question]` callout is hanging; automation stands.
    BLOCKED: An asset named in `spec_depends_on` has not reached the state this one needs.
    DONE: `spec_released` is true.
  """

  # Domain(spec.lifecycle):
  # # One state wins when several conditions hold at once
  # An asset's visible state names the single condition that best describes where it stands
  # right now, chosen by checking a fixed list of conditions in order and stopping at the first
  # one that holds — never by combining several that are true at the same time. A backlog of
  # parked work is called out ahead of a lone operator gesture still hanging, because a whole
  # backlog sitting idle is a different situation from one small thing waiting on a person, even
  # though the second condition's own trigger would otherwise also be satisfied by the same
  # parked work.

  # Design is being written and is not approved yet.
  DRAFT = "draft"
  # One of the asset's documents is in the review loop.
  IN_REVIEW = "in-review"
  # An implementation job is in flight, or `spec_develop_done` is still open.
  IMPLEMENTATION = "implementation"
  # A test run is under way, or `spec_tests_passing` is still open.
  TESTING = "testing"
  # Every stage-bearing sibling document sits at `spec_stage: deferred` and the only launch rows hanging are those
  # documents' own `Review <doc>` rows — a parked backlog, not an operator anyone is waiting on. Judged ahead of
  # `WAITS_OPERATOR`, whose hanging-checkbox condition those `Review` rows would otherwise satisfy.
  DEFERRED = "deferred"
  # A launch checkbox or a `[!question]` callout is hanging; automation stands.
  WAITS_OPERATOR = "waits-operator"
  # An asset named in `spec_depends_on` has not reached the state this one needs.
  BLOCKED = "blocked"
  # `spec_released` is true.
  DONE = "done"


# Every legal `spec_state` value; anything else on a status note is a doctor finding.
ASSET_STATES = frozenset({
    AssetState.DRAFT,
    AssetState.IN_REVIEW,
    AssetState.IMPLEMENTATION,
    AssetState.TESTING,
    AssetState.DEFERRED,
    AssetState.WAITS_OPERATOR,
    AssetState.BLOCKED,
    AssetState.DONE,
})


# Linear precedence order of the level ladder — the order the level documents are written in.
LEVEL_GATE_ORDER = [
    Gate.VISION_DONE,
    Gate.USE_CASES_DONE,
    Gate.DESIGN_DONE,
    Gate.UI_DESIGN_DONE,
    Gate.TECH_DONE,
]

# Every gate a level note carries; the asset ladder's `GATE_ORDER` is a separate set.
LEVEL_GATES = frozenset(LEVEL_GATE_ORDER)

# Gates whose precondition is strictly derivable from per-file approval stages — every level
# gate is one of these: the level ladder has no human-signal gate at all.
DERIVED_GATES = frozenset({Gate.DESIGN_DONE, Gate.PLAN_DONE}) | LEVEL_GATES

# Gates whose flip depends on an out-of-band human signal, not a derivable stage.
HUMAN_GATES = frozenset({Gate.DEVELOP_DONE, Gate.TESTS_PASSING, Gate.RELEASED})

# Linear precedence order — each gate's precondition references the one before it.
GATE_ORDER = [
    Gate.DESIGN_DONE,
    Gate.PLAN_DONE,
    Gate.DEVELOP_DONE,
    Gate.TESTS_PASSING,
    Gate.RELEASED,
]

# Every gate an asset's own status folder-note carries: the five-rung ladder plus the terminal
# cancellation flag that freezes it.
ASSET_GATES = frozenset(GATE_ORDER) | { Gate.SPEC_CANCELLED }

# Every gate name the flip primitive accepts at all. A name outside this set is a caller typo,
# refused before the folder-note is touched — `Gate.DESIGN_DONE` is the one member both ladders
# share, and the note's own role decides which of the two it means.
FLIPPABLE_GATES = ASSET_GATES | LEVEL_GATES

# The gates each folder-note role may flip. An asset's status note runs the asset ladder; a
# product's or the catalog root's level note runs the level ladder and nothing else. A role
# absent from this mapping bears no gates at all, so every flip on such a note is refused.
ROLE_GATES = {
    SpecValue.ROLE_STATUS: ASSET_GATES,
    SpecValue.ROLE_PRODUCT: LEVEL_GATES,
    SpecValue.ROLE_CATALOG: LEVEL_GATES,
}


# ----------------------------------------------------------------------------------------
class StageKey:
  """
  Per-file frontmatter key carried by authored spec docs.

  Attributes:
    STAGE: The `spec_stage` key naming a doc's lifecycle stage.
  """

  # The `spec_stage` key naming a doc's lifecycle stage.
  STAGE = "spec_stage"


# ----------------------------------------------------------------------------------------
class SiblingDoc:
  """
  Authored sibling-doc filenames, asset-level or product-level.

  Attributes:
    DESIGN: The feature/change design doc (asset-level; also product-level, loose at the
      product root).
    ARCHITECTURE: The asset-level architecture doc (feature/change only, never a bug) — the
      mandatory step between design and planning for a code-bearing asset, written by the
      architect and reviewed through its own `architecture` review class.
    BUG: The bug-layout design-side doc.
    CODE_PLAN: The code-plan sibling doc.
    TEST_PLAN: The test-plan sibling doc.
    TECH: The product-level tech doc, loose at the product root.
    CODE_REPORT: The code-report sibling doc.
    TEST_REPORT: The test-report sibling doc.
    DECISIONS: The append-only decisions-registry sibling doc (asset-level; also
      product-level, loose at the product root). Opt-in and lazily created by the `decide`
      primitive — never scaffolded, never opted into review, and carries no `spec_stage`.
      Never a review-tracked sibling: carrying no `review_result`, it transitions nothing and
      wakes no coordinator, whatever the git-watch filter delivers.
  """

  # Domain(spec.lifecycle):
  # # Architecture is a mandatory step only for code-bearing work
  # Once a design is accepted for an asset that will ship its own code, the code's own shape —
  # its module boundaries and where responsibility sits — is settled as its own separate step
  # before any plan is written, never folded into planning itself and never skipped. A bug
  # carries no such step: fixing an already-shaped system needs no shape of its own to settle
  # first.

  # The feature/change design doc (asset-level; also product-level, loose at the product root).
  DESIGN = "design.md"
  # The asset-level architecture doc (feature/change only, never a bug) — the mandatory step between design and
  # planning for a code-bearing asset, written by the architect and reviewed through its own `architecture` review
  # class.
  ARCHITECTURE = "architecture.md"
  # The bug-layout design-side doc.
  BUG = "bug.md"
  # The code-plan sibling doc.
  CODE_PLAN = "code-plan.md"
  # The test-plan sibling doc.
  TEST_PLAN = "test-plan.md"
  # The product-level tech doc, loose at the product root.
  TECH = "tech.md"
  # The code-report sibling doc.
  CODE_REPORT = "code-report.md"
  # The test-report sibling doc.
  TEST_REPORT = "test-report.md"
  # The append-only decisions-registry sibling doc (asset-level; also product-level, loose at the product root). Opt-
  # in and lazily created by the `decide` primitive — never scaffolded, never opted into review, and carries no
  # `spec_stage`. Never a review-tracked sibling: carrying no `review_result`, it transitions nothing and wakes no
  # coordinator, whatever the git-watch filter delivers.
  DECISIONS = "decisions.md"


# ----------------------------------------------------------------------------------------
class LevelDoc:
  """
  The system documents a level note owns, paired with their doc types and gates.

  A level note is a product's or the catalog root's own folder-note. Only `VISION` is
  mandatory; the other four are opt-in and hang as launch checkboxes once the vision gate
  closes — `USE_CASES` and `UI_DESIGN` on a product root only. `DESIGN` and `TECH` share their
  basenames with the product-level docs the asset coordinator already reads, and the doc types
  keep them apart.

  Attributes:
    VISION: The level vision doc.
    USE_CASES: The level use-cases doc.
    DESIGN: The level design doc.
    UI_DESIGN: The level ui-design doc.
    TECH: The level tech doc.
    CHAIN: The ladder as `(filename, doc_type, gate)` triples, in writing order.
    BASENAMES: The five filenames, for deciding whether a changed file is a level document.
  """

  # The level vision doc.
  VISION = "vision.md"
  # The level use-cases doc.
  USE_CASES = "use-cases.md"
  # The level design doc.
  DESIGN = "design.md"
  # The level ui-design doc.
  UI_DESIGN = "ui-design.md"
  # The level tech doc.
  TECH = "tech.md"
  # The ladder as `(filename, doc_type, gate)` triples, in writing order.
  CHAIN = [
      ( VISION, "system-vision", Gate.VISION_DONE ),
      ( USE_CASES, "system-use-cases", Gate.USE_CASES_DONE ),
      ( DESIGN, "system-design", Gate.DESIGN_DONE ),
      ( UI_DESIGN, "system-ui-design", Gate.UI_DESIGN_DONE ),
      ( TECH, "system-tech", Gate.TECH_DONE ),
  ]
  # The five filenames, for deciding whether a changed file is a level document.
  BASENAMES = frozenset({ VISION, USE_CASES, DESIGN, UI_DESIGN, TECH })


# ----------------------------------------------------------------------------------------
class Section:
  """
  Folder-note body section headings (H1).

  Attributes:
    SUMMARY: The `# Summary` heading carrying the plugin-owned précis/stats.
    GATES: The `# Gates` heading carrying gate callouts.
    ATTACHMENTS: The `# Attachments` heading carrying the coordinator's registry of
      non-markdown attachment files and the document each one belongs to.
    STATUS_BRIEF: The `# Status brief` heading carrying the coordinator's own
      rewritten-on-every-invocation prose, protected against foreign writers.
    COORD_RULES: The `# Coordinator rules` heading carrying operator-authored,
      persistent constraints the coordinator reads before every decision.
    COORD_COMMANDS: The `# Coordinator commands` heading carrying operator
      instructions the coordinator executes and clears; the coordinator
      locks progress marks into it and moves the finished block to History.
    HISTORY: The `# History` heading carrying gate/stage-change log lines.
  """

  # The `# Summary` heading carrying the plugin-owned précis/stats.
  SUMMARY = "# Summary"
  # The `# Gates` heading carrying gate callouts.
  GATES = "# Gates"
  # The `# Attachments` heading carrying the coordinator's registry of non-markdown attachment files and the document
  # each one belongs to.
  ATTACHMENTS = "# Attachments"
  # The `# Status brief` heading carrying the coordinator's own rewritten-on-every-invocation prose, protected
  # against foreign writers.
  STATUS_BRIEF = "# Status brief"
  # The `# Coordinator rules` heading carrying operator-authored, persistent constraints the coordinator reads before
  # every decision.
  COORD_RULES = "# Coordinator rules"
  # The `# Coordinator commands` heading carrying operator instructions the coordinator executes and clears; the
  # coordinator locks progress marks into it and moves the finished block to History.
  COORD_COMMANDS = "# Coordinator commands"
  # The `# History` heading carrying gate/stage-change log lines.
  HISTORY = "# History"


# ----------------------------------------------------------------------------------------
class HistoryEvent:
  """
  Event keys of the language-resolved `# History` line templates.

  Attributes:
    SCAFFOLDED: An asset folder-note was scaffolded by `lazy-spec.create-asset`.
    HALTED: An asset was halted with a recorded reason.
    HALTED_CALLOUT: Tail of the persistent `[!failure]` Gates callout the same halt appends.
    JOB_DONE: A launch-checkbox expert job finished.
    JOB_CANCELLED: A launch-checkbox expert job was cancelled.
    JOB_DEAD: A coordinator job died and its marker was cleared.
    REQUEST_PROCESSED: An upstream request reached its processed state.
  """

  # An asset folder-note was scaffolded by `lazy-spec.create-asset`.
  SCAFFOLDED = "scaffolded"
  # An asset was halted with a recorded reason.
  HALTED = "halted"
  # Tail of the persistent `[!failure]` Gates callout the same halt appends.
  HALTED_CALLOUT = "halted-callout"
  # A launch-checkbox expert job finished.
  JOB_DONE = "job-done"
  # A launch-checkbox expert job was cancelled.
  JOB_CANCELLED = "job-cancelled"
  # A coordinator job died and its marker was cleared.
  JOB_DEAD = "job-dead"
  # An upstream request reached its processed state.
  REQUEST_PROCESSED = "request-processed"


# Protected-owner tags marking the coordinator's own sections (`#protected/<owner>/<region>`).
PROTECTED_STATUS_BRIEF = "#protected/spec/status-brief"
PROTECTED_COORD_RULES = "#protected/spec/coordinator-rules"
PROTECTED_COORD_COMMANDS = "#protected/spec/coordinator-commands"
PROTECTED_ATTACHMENTS = "#protected/spec/attachments"


# ----------------------------------------------------------------------------------------
class FlipResult:
  """
  Result-dict status and field tokens emitted by the flip-gate primitive.

  Attributes:
    STATUS: The status-field key.
    FLIPPED: The success status value.
    REFUSED: The refusal status value.
  """

  # The status-field key.
  STATUS = "status"
  # The success status value.
  FLIPPED = "flipped"
  # The refusal status value.
  REFUSED = "refused"


# Frontmatter boolean literals compared and written for gate values.
BOOL_TRUE = "true"
BOOL_FALSE = "false"


# ----------------------------------------------------------------------------------------
class PlanReview:
  """
  Post-flip plan-review auto-open status tokens and resolution constants.

  Attributes:
    KEY: The result-dict field carrying the auto-open status.
    OPENED: Review was opened on the sibling `code-plan.md`.
    SKIP_STAGE: Skipped because `code-plan.md` is past the openable stage set.
    SKIP_ACTIVE: Skipped because `code-plan.md` is already in active review.
    NO_PLAN_DOC: No-op because the asset has no `code-plan.md` sibling — the
      doc is opt-in, so its absence is not a skip, just nothing to do.
    SKIP_CLI_UNAVAILABLE: Skipped because the review CLI could not be resolved or run.
    REVIEW_ACTIVE_KEY: The `code-plan.md` frontmatter key marking active review.
    REVIEW_CLI: The `lazycortex-review` CLI binary name resolved under a plugin dir.
    START_VERB: The review CLI subcommand that opts a document into review.
    SUBMIT_VERB: The review CLI subcommand that opts a document straight to a reviewer,
      skipping the opening writer round.
    PLUGIN_DIRS_ENV: The env var listing plugin dirs to walk for the CLI.
    BIN_DIR: The per-plugin `bin/` subdir holding the CLI binary.
    START_TIMEOUT_S: Seconds the best-effort `start` subprocess may run.
  """

  # Domain(spec.lifecycle):
  # # Accepting a design can auto-open review on its own follow-up plan
  # The moment a design is accepted, the plan document that follows it is offered straight into
  # review on its own, without waiting for anything else to notice — but only when that offer
  # still makes sense: the plan must still be at a stage where opening review means something,
  # and must not already be under review from something else. When the plan document does not
  # exist at all, there is nothing to offer, which is a normal shape rather than a failure to
  # act on. A reviewing tool that cannot be reached in time leaves the plan exactly as accepting
  # the design found it, for a later pass to try again.

  # The result-dict field carrying the auto-open status.
  KEY = "plan_review"
  # Review was opened on the sibling `code-plan.md`.
  OPENED = "opened"
  # Skipped because `code-plan.md` is past the openable stage set.
  SKIP_STAGE = "skip:stage"
  # Skipped because `code-plan.md` is already in active review.
  SKIP_ACTIVE = "skip:active"
  # No-op because the asset has no `code-plan.md` sibling — the doc is opt-in, so its absence is not a skip, just
  # nothing to do.
  NO_PLAN_DOC = "no-plan-doc"
  # Skipped because the review CLI could not be resolved or run.
  SKIP_CLI_UNAVAILABLE = "skip:review-cli-unavailable"
  # The `code-plan.md` frontmatter key marking active review.
  REVIEW_ACTIVE_KEY = "review_active"
  # The `lazycortex-review` CLI binary name resolved under a plugin dir.
  REVIEW_CLI = "lazycortex-review"
  # The review CLI subcommand that opts a document into review.
  START_VERB = "start"
  # The review CLI subcommand that opts a document straight to a reviewer, skipping the opening writer round.
  SUBMIT_VERB = "submit"
  # The env var listing plugin dirs to walk for the CLI.
  PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
  # The per-plugin `bin/` subdir holding the CLI binary.
  BIN_DIR = "bin"
  # Seconds the best-effort `start` subprocess may run.
  START_TIMEOUT_S = 60


# Per-file stages from which a follow-up plan review may be auto-opened.
PLAN_OPENABLE_STAGES = frozenset({Stage.EMPTY, Stage.DRAFT})

# Run-logging helper constants.
LOG_NO_GIT = "no-git"
LOG_ROOT = ".logs"
LOG_CLAUDE = "claude"
FLIP_GATE_NAME = "lazy-spec.flip-gate"


# ----------------------------------------------------------------------------------------
class TickAction:
  """
  Action-token vocabulary emitted by the gate-tick worker.

  Attributes:
    ACTION: The action-field key in the result dict.
    AUTO_FLIPPED: A derived gate was auto-flipped in-process.
    READY_CALLOUT: A human-signal gate's readiness callout was appended.
    READINESS_WITHDRAWN: A stale readiness callout was withdrawn.
    STAGE_PROMOTED: One or more sibling docs were promoted `draft → approved`
      after their review finalized as approved.
    CHECKBOXES_RECONCILED: One or more launch checkboxes were hung or removed
      in `# Gates`, with no other gate action this tick.
    DISPATCHED: A ticked launch checkbox was dispatched to an expert job.
    AUTO_FLIPPED_OFF: `spec_plan_done` or `spec_tests_passing` was auto-flipped
      back to false because its governing sibling doc reappeared un-accepted.
    JOB_DONE: An active expert job's bundle carried a `DONE` marker; the
      `active_job` marker was cleared.
    JOB_CANCELLED: An active expert job's bundle carried a `CANCELLED` marker;
      the `active_job` marker was cleared.
    ASSET_HALTED: An active expert job's bundle carried a `DEAD` marker; the
      asset was halted.
    NOOP: Nothing to do this tick.
    DISPATCH_STALE: A dispatch returned an already-terminal job (a dedup hit on a
      finished-but-unconsumed bundle); no `active_job` marker was written, a warning
      landed in `# History` instead, and the tick that provoked it retries next time.
    CASCADE_TARGET_SKIPPED: A declared `spec_targets` token did not resolve to an
      existing asset; it was folded into `spec_cascade_targets_done` as skipped
      (with a `# History` note) so later targets are not blocked forever.
    COORDINATOR_JOB_CONSUMED: A `coordinator_job` bundle carried a `DONE` or
      `CANCELLED` marker; the bundle was retired and the marker was cleared.
    COORDINATOR_JOB_DEAD: A `coordinator_job` bundle carried a `DEAD` marker; the
      marker was cleared with a `# History` warning, the asset was NOT halted (the
      coordinator's own wake job is not a ladder expert job).
    TRIGGER: The result-dict key carrying the wake trigger a dispatch acted on.
    EXPERT: The result-dict key carrying the expert a dispatch went to.
    JOB_ID: The result-dict key carrying the job id a dispatch queued or retired.
    WARNINGS: The result-dict key carrying the dispatch warnings landed in `# History`.
  """

  # The action-field key in the result dict.
  ACTION = "action"
  # The result-dict key carrying the wake trigger a dispatch acted on.
  TRIGGER = "trigger"
  # The result-dict key carrying the expert a dispatch went to.
  EXPERT = "expert"
  # The result-dict key carrying the job id a dispatch queued or retired.
  JOB_ID = "job_id"
  # The result-dict key carrying the dispatch warnings landed in `# History`.
  WARNINGS = "warnings"
  # A derived gate was auto-flipped in-process.
  AUTO_FLIPPED = "auto-flipped"
  # A human-signal gate's readiness callout was appended.
  READY_CALLOUT = "ready-callout"
  # A stale readiness callout was withdrawn.
  READINESS_WITHDRAWN = "readiness-withdrawn"
  # One or more sibling docs were promoted `draft → approved` after their review finalized as approved.
  STAGE_PROMOTED = "stage-promoted"
  # One or more launch checkboxes were hung or removed in `# Gates`, with no other gate action this tick.
  CHECKBOXES_RECONCILED = "checkboxes-reconciled"
  # A ticked launch checkbox was dispatched to an expert job.
  DISPATCHED = "dispatched"
  # `spec_plan_done` or `spec_tests_passing` was auto-flipped back to false because its governing sibling doc
  # reappeared un-accepted.
  AUTO_FLIPPED_OFF = "auto-flipped-off"
  # An active expert job's bundle carried a `DONE` marker; the `active_job` marker was cleared.
  JOB_DONE = "job-done"
  # An active expert job's bundle carried a `CANCELLED` marker; the `active_job` marker was cleared.
  JOB_CANCELLED = "job-cancelled"
  # An active expert job's bundle carried a `DEAD` marker; the asset was halted.
  ASSET_HALTED = "asset-halted"
  # Nothing to do this tick.
  NOOP = "noop"
  # A dispatch returned an already-terminal job (a dedup hit on a finished-but-unconsumed bundle); no `active_job`
  # marker was written, a warning landed in `# History` instead, and the tick that provoked it retries next time.
  DISPATCH_STALE = "dispatch-stale"
  # A declared `spec_targets` token did not resolve to an existing asset; it was folded into
  # `spec_cascade_targets_done` as skipped (with a `# History` note) so later targets are not blocked forever.
  CASCADE_TARGET_SKIPPED = "cascade-target-skipped"
  # A `coordinator_job` bundle carried a `DONE` or `CANCELLED` marker; the bundle was retired and the marker was
  # cleared.
  COORDINATOR_JOB_CONSUMED = "coordinator-job-consumed"
  # A `coordinator_job` bundle carried a `DEAD` marker; the marker was cleared with a `# History` warning, the asset
  # was NOT halted (the coordinator's own wake job is not a ladder expert job).
  COORDINATOR_JOB_DEAD = "coordinator-job-dead"


# ----------------------------------------------------------------------------------------
class GateCheckbox:
  """
  Gate-readiness checkbox labels written to the folder-note's `# Gates` section.

  Attributes:
    WRITE_CODE_PLAN: Label for the code-plan-readiness checkbox.
    WRITE_TEST_PLAN: Label for the test-plan-readiness checkbox.
    WRITE_ARCHITECTURE: Label for the architecture-readiness checkbox on a
      code-bearing asset (playbook Chapter 8's architecture step; also used
      reflexively by a code-free decomposer asset against its own ladder).
    START_IMPLEMENTATION: Label for the implementation-readiness checkbox.
    START_TESTING: Label for the testing-readiness checkbox.
    PUBLISH: Label for the release-readiness checkbox the coordinator hangs once an asset's
      terminal gate closes — unlike the other five, its tick never dispatches an expert job
      (it clears `spec_draft` directly via `note-set-key`) and so never carries an `active_job`
      entry of its own.
    REVIEW_PREFIX: Prefix of the parameterised review-launch label — the full label is this
      prefix followed by the reviewable markdown file's basename. Unlike the six fixed
      labels, its tick opens a review rather than dispatching an expert job, so it never
      carries an `active_job` entry.
    GATE_CALLOUT_MARK: Markdown callout prefix marking a gate-readiness block.
  """

  # Label for the code-plan-readiness checkbox.
  WRITE_CODE_PLAN = "Write code-plan"
  # Label for the test-plan-readiness checkbox.
  WRITE_TEST_PLAN = "Write test-plan"
  # Label for the architecture-readiness checkbox on a code-bearing asset (playbook Chapter 8's architecture step;
  # also used reflexively by a code-free decomposer asset against its own ladder).
  WRITE_ARCHITECTURE = "Write architecture"
  # Label for the implementation-readiness checkbox.
  START_IMPLEMENTATION = "Start implementation"
  # Label for the testing-readiness checkbox.
  START_TESTING = "Start testing"
  # Label for the release-readiness checkbox the coordinator hangs once an asset's terminal gate closes — unlike the
  # other five, its tick never dispatches an expert job (it clears `spec_draft` directly via `note-set-key`) and so
  # never carries an `active_job` entry of its own.
  PUBLISH = "Publish"
  # Prefix of the parameterised review-launch label — the full label is this prefix followed by the reviewable
  # markdown file's basename. Unlike the six fixed labels, its tick opens a review rather than dispatching an expert
  # job, so it never carries an `active_job` entry.
  REVIEW_PREFIX = "Review "
  # Markdown callout prefix marking a gate-readiness block.
  GATE_CALLOUT_MARK = "[!gate]"


# ----------------------------------------------------------------------------------------
class SpecHaltKey:
  """
  Halt-state frontmatter key for assets awaiting resolution.

  Attributes:
    HALTED: The `spec_halted` frontmatter key marking a blocked asset.
  """

  # The `spec_halted` frontmatter key marking a blocked asset.
  HALTED = "spec_halted"


# ----------------------------------------------------------------------------------------
class SpecMomentKey:
  """
  Frontmatter keys recording WHEN a state was reached, for the staleness rule to compare.

  A moment is an ISO 8601 UTC datetime (`2026-09-19T08:11:19Z`). These keys replace the dates
  the coordinator used to read out of `# History` lines: the journal is for the operator, the
  moments are for the code.

  Attributes:
    APPROVED_AT: The `spec_approved_at` key on a stage-bearing document — the last moment it
      entered `approved`, written by `lazy-spec.set-stage`.
    AT_SUFFIX: The suffix that turns a gate key into its moment key (`spec_design_done_at`),
      written by `flip-gate` when the gate turns true and dropped when it turns false.
  """

  # The `spec_approved_at` key on a stage-bearing document — the last moment it entered `approved`, written by `lazy-
  # spec.set-stage`.
  APPROVED_AT = "spec_approved_at"
  # The suffix that turns a gate key into its moment key (`spec_design_done_at`), written by `flip-gate` when the
  # gate turns true and dropped when it turns false.
  AT_SUFFIX = "_at"


# ----------------------------------------------------------------------------------------
class SpecStateKey:
  """
  Derived-state frontmatter key on an asset's status folder-note.

  Attributes:
    STATE: The `spec_state` key naming the asset's current state, one of `ASSET_STATES`.
  """

  # The `spec_state` key naming the asset's current state, one of `ASSET_STATES`.
  STATE = "spec_state"


# ----------------------------------------------------------------------------------------
class AttachmentKey:
  """
  Ownership frontmatter key carried by a markdown attachment.

  Attributes:
    OWNER_DOC: The `spec_owner_doc` key naming the sibling document an attachment belongs
      to, written by the expert that creates the file.
  """

  # The `spec_owner_doc` key naming the sibling document an attachment belongs to, written by the expert that creates
  # the file.
  OWNER_DOC = "spec_owner_doc"


# ----------------------------------------------------------------------------------------
class JobMarker:
  """
  Per-note job-marker field names in the runtime sidecar, their sub-fields, and the wake token
  one carries.

  These name fields of `.runtime/lazy-specs.jobs.json`, not frontmatter: the markers are runtime
  state the spec system owns, invisible in the folder-note and unreachable by a hand-edit
  (`spec_job_markers.py`). Each of the two job fields carries a dict — `{trigger, expert, job_id}` for
  the coordinator's own one-job-per-asset slot, `{checkbox, expert, job_id}` for the asset's
  launch-checkbox job slot — kept in separate fields so a coordinator job never collides with a
  ladder job.

  Attributes:
    COORDINATOR_JOB: The coordinator job currently in flight on the asset.
    ACTIVE_JOB: The launch-checkbox expert job currently in flight on the asset.
    PENDING_WAKE: The wake `gate_tick` raised and `coordinator_dispatch` has yet to consume.
    JOB_DONE: The `PENDING_WAKE` value a cleared `ACTIVE_JOB` raises.
    DECLINED: A wake the busy-guard declined while a coordinator job was running; redeemed by
      re-resolving triggers against the asset's current state once the job frees.
    CHECKBOX: The checkbox-label field in the active-job dict.
    TRIGGER: The wake-trigger-token field in the coordinator-job dict — the `CHECKBOX` analogue,
      naming what woke the coordinator (operator edit, command, question answer, routing)
      instead of which checkbox was ticked.
    EXPERT: The expert-name field in both job dicts.
    JOB_ID: The job-id field in both job dicts.
    KIND_COORDINATOR: The `mark-job` CLI token selecting `COORDINATOR_JOB`.
    KIND_ACTIVE: The `mark-job` CLI token selecting `ACTIVE_JOB`.
    KIND_WAKE: The `mark-job` CLI token selecting `PENDING_WAKE`.
  """

  # The coordinator job currently in flight on the asset.
  COORDINATOR_JOB = "coordinator_job"
  # The launch-checkbox expert job currently in flight on the asset.
  ACTIVE_JOB = "active_job"
  # The wake `gate_tick` raised and `coordinator_dispatch` has yet to consume.
  PENDING_WAKE = "pending_wake"
  # The `PENDING_WAKE` value a cleared `ACTIVE_JOB` raises.
  JOB_DONE = "job-done"
  # A wake the busy-guard declined while a coordinator job was running; redeemed by re-resolving triggers against the
  # asset's current state once the job frees.
  DECLINED = "declined"
  # The checkbox-label field in the active-job dict.
  CHECKBOX = "checkbox"
  # The wake-trigger-token field in the coordinator-job dict — the `CHECKBOX` analogue, naming what woke the
  # coordinator (operator edit, command, question answer, routing) instead of which checkbox was ticked.
  TRIGGER = "trigger"
  # The expert-name field in both job dicts.
  EXPERT = "expert"
  # The job-id field in both job dicts.
  JOB_ID = "job_id"
  # The `mark-job` CLI token selecting `COORDINATOR_JOB`.
  KIND_COORDINATOR = "coordinator"
  # The `mark-job` CLI token selecting `ACTIVE_JOB`.
  KIND_ACTIVE = "active"
  # The `mark-job` CLI token selecting `PENDING_WAKE`.
  KIND_WAKE = "wake"


# ----------------------------------------------------------------------------------------
class CoordinatorTrigger:
  """
  Wake-trigger tokens a dispatched coordinator job carries in `payload.trigger`.

  Attributes:
    OPERATOR_EDIT: A non-`@bot.`-authored commit that changed the asset note, or — on a grouped
      tick — a sibling doc not carrying `review_active: true` (a review-active sibling's own
      edits are the review loop's business, not a wake signal, until `DOC_TRANSITION` covers its
      review ending; operator decision 2026-08-15), as reported by the `lazy-spec.coordinator-watch`
      git-watch routine's own item (no dirty-tree signal exists — the daemon runs in its own
      checkout, see `coordinator_dispatch.py`'s module docstring).
    COMMAND: A non-empty `# Coordinator commands` section.
    ANSWER: A ticked option under one of the coordinator's own `[!question]` callouts.
    JOB_DONE: The sidecar's `active_job` marker was cleared and a `JobMarker.PENDING_WAKE` of
      `job-done` raised in its place — a launch-checkbox job's terminal marker was just applied
      (`gate_tick.apply_job_marker`). Wakes the coordinator regardless of who authored the
      commit this tick carries: the bot-suppression rule exists to ignore the coordinator's own
      idle re-triggers, not to hide a real state transition the playbook's acceptance cycle
      (Chapter 6) needs to react to — the exemption is per-transition, not per-author
      (model-audit.md C3), and the raised flag rather than any commit's identity is what makes
      the wake visible.
    DOC_TRANSITION: A sibling doc's `review_result` appeared or changed against the value
      previously recorded on the asset's status note (`SpecCoordinatorDocStateKey.STATE`).
      Wakes the coordinator REGARDLESS of the sibling doc's commit author — the exemption is
      per-transition like `JOB_DONE`, not per-author, and a non-review commit to the sibling
      (operator prose edit, a writer's draft) naturally carries no `review_result` change, so
      it never fires this trigger without any author check needed (model-audit.md C3, the
      deferred half — `lazy-spec.coordination-playbook.md` § 1 trigger 1's own scope only ever
      covered the status folder-note itself).
    ASSET_RELEASED: An asset's `Gate.RELEASED` crossed to true, dispatched upward onto the
      product's own level note so the catalog coordinator can reconcile the released asset
      against the product design. One hop, best-effort, raised on the same asset wake that
      already scans reverse dependencies; no gate of the asset's own is touched.
    DEPENDENCY_READY: A wake resolved on a dependency asset — one this asset itself names in
      its own `spec_depends_on` — reached this asset as a one-hop reverse-edge dispatch
      (`coordinator_dispatch.scan_dependents`). Carries `payload["dep"]` naming the ready
      dependency's product-relative path token, of any depth. Synthetic: never derived from
      `item`, so it
      carries no author of its own to check (C2). Listed as the playbook's eighth wake trigger
      (`lazy-spec.coordination-playbook.md` § 1).
    CHILD_REAPPROVED: A nested product's `vision.md` or `design.md` reaches `approved`,
      dispatched one hop upward onto the enclosing product's level note so it can compare its
      own design against the child's. Carries `payload["child"]` naming the child product's
      key. Synthetic, never derived from `item`.
  """

  # A non-`@bot.`-authored commit that changed the asset note, or — on a grouped tick — a sibling doc not carrying
  # `review_active: true` (a review-active sibling's own edits are the review loop's business, not a wake signal,
  # until `DOC_TRANSITION` covers its review ending; operator decision 2026-08-15), as reported by the `lazy-
  # spec.coordinator-watch` git-watch routine's own item (no dirty-tree signal exists — the daemon runs in its own
  # checkout, see `coordinator_dispatch.py`'s module docstring).
  OPERATOR_EDIT = "operator-edit"
  # A non-empty `# Coordinator commands` section.
  COMMAND = "command"
  # A ticked option under one of the coordinator's own `[!question]` callouts.
  ANSWER = "answer"
  # The sidecar's `active_job` marker was cleared and a `JobMarker.PENDING_WAKE` of `job-done` raised in its place —
  # a launch-checkbox job's terminal marker was just applied (`gate_tick.apply_job_marker`). Wakes the coordinator
  # regardless of who authored the commit this tick carries: the bot-suppression rule exists to ignore the
  # coordinator's own idle re-triggers, not to hide a real state transition the playbook's acceptance cycle (Chapter
  # 6) needs to react to — the exemption is per-transition, not per-author (model-audit.md C3), and the raised flag
  # rather than any commit's identity is what makes the wake visible.
  JOB_DONE = "job-done"
  # A sibling doc's `review_result` appeared or changed against the value previously recorded on the asset's status
  # note (`SpecCoordinatorDocStateKey.STATE`). Wakes the coordinator REGARDLESS of the sibling doc's commit author —
  # the exemption is per-transition like `JOB_DONE`, not per-author, and a non-review commit to the sibling (operator
  # prose edit, a writer's draft) naturally carries no `review_result` change, so it never fires this trigger without
  # any author check needed (model-audit.md C3, the deferred half — `lazy-spec.coordination-playbook.md` § 1 trigger
  # 1's own scope only ever covered the status folder-note itself).
  DOC_TRANSITION = "doc-transition"
  # A wake resolved on a dependency asset — one this asset itself names in its own `spec_depends_on` — reached this
  # asset as a one-hop reverse-edge dispatch (`coordinator_dispatch.scan_dependents`). Carries `payload["dep"]`
  # naming the ready dependency's product-relative path token, of any depth. Synthetic: never derived from `item`, so
  # it carries no author of its own to check (C2). Listed as the playbook's eighth wake trigger (`lazy-
  # spec.coordination-playbook.md` § 1).
  DEPENDENCY_READY = "dependency-ready"
  # An asset's `Gate.RELEASED` crossed to true, dispatched upward onto the product's own level note so the catalog
  # coordinator can reconcile the released asset against the product design. One hop, best-effort, raised on the same
  # asset wake that already scans reverse dependencies; no gate of the asset's own is touched.
  ASSET_RELEASED = "asset-released"
  # A nested product's `vision.md` or `design.md` reaches `approved`, dispatched one hop upward onto the enclosing
  # product's level note so it can compare its own design against the child's. Carries `payload["child"]` naming the
  # child product's key. Synthetic, never derived from `item`.
  CHILD_REAPPROVED = "child-reapproved"


# ----------------------------------------------------------------------------------------
class AnsweredQuestionKey:
  """
  Frontmatter key recording the content fingerprint of the last `[!question]` answer the
  `lazy-spec.coordinator-watch` worker has already dispatched on.

  Worker-internal bookkeeping, not part of the coordinator persona's own writable schema — only
  `coordinator_dispatch.py`'s own direct write path ever sets it, so the persona can't clear or
  game it through `note-set-key`. A content hash rather than a commit sha (`model-audit.md` I-A:
  a sha-valued marker can name a commit the daemon later rewrites or destroys on push conflict)
  — the fingerprint survives a destroyed removal commit resurrecting the identical ticked block.

  Attributes:
    FINGERPRINT: The `spec_coordinator_answered` frontmatter key.
  """

  # The `spec_coordinator_answered` frontmatter key.
  FINGERPRINT = "spec_coordinator_answered"


# ----------------------------------------------------------------------------------------
class SpecCoordinatorDocStateKey:
  """
  Frontmatter key recording the last `review_result` value this worker has already dispatched
  `CoordinatorTrigger.DOC_TRANSITION` on, per sibling-doc basename.

  Worker-internal bookkeeping, same convention as `AnsweredQuestionKey` — only
  `coordinator_dispatch.py`'s own direct write path ever sets it, so the persona can't clear or
  game it through `note-set-key`. Content-shaped rather than sha-keyed (`model-audit.md` I-A):
  the value is the sibling's own `review_result` string, not a commit reference, so it keeps
  meaning across a rewritten or destroyed commit exactly like `AnsweredQuestionKey`'s fingerprint.

  Attributes:
    STATE: The `spec_coordinator_doc_state` frontmatter key. Its value is a JSON object mapping
      a sibling-doc basename (`design.md`, `code-plan.md`, ...) to the `review_result` value last
      seen on that doc when this worker dispatched `DOC_TRANSITION` for it.
    REVIEW_REOPENED: The doc-state marker value recorded when a sibling's review_result is
      cleared (review reopened).
  """

  # The `spec_coordinator_doc_state` frontmatter key. Its value is a JSON object mapping a sibling-doc basename
  # (`design.md`, `code-plan.md`, ...) to the `review_result` value last seen on that doc when this worker dispatched
  # `DOC_TRANSITION` for it.
  STATE = "spec_coordinator_doc_state"
  # The doc-state marker value recorded when a sibling's review_result is cleared (review reopened).
  REVIEW_REOPENED = ""


# ----------------------------------------------------------------------------------------
class SpecCoordinatorChildWakeStateKey:
  """
  Frontmatter key recording, on a PRODUCT level note, which of its own system documents this
  worker has already forwarded upward as a `CoordinatorTrigger.CHILD_REAPPROVED` wake of the
  enclosing product, per document basename.

  Worker-internal bookkeeping, same convention as `SpecCoordinatorDocStateKey` — only
  `coordinator_dispatch.py`'s own direct write path ever sets it, so the persona can't clear or
  game it through `note-set-key`. It is a SECOND marker rather than a reuse of the doc-state
  one because the two edges fire on different ticks: the upward edge is resolved outside the
  trigger ladder, so a command or a ticked answer winning the tick forwards the child hop while
  leaving the level's own `DOC_TRANSITION` still to come. Stamping the doc-state marker there
  would consume that transition and lose the level's own stage promotion with it.

  Attributes:
    STATE: The `spec_coordinator_child_wake_state` frontmatter key. Its value is a JSON object
      mapping a level-document basename (`vision.md`, `design.md`) to the `review_result` value
      the wake it last forwarded for that document carried.
  """

  # The `spec_coordinator_child_wake_state` frontmatter key. Its value is a JSON object mapping a level-document
  # basename (`vision.md`, `design.md`) to the `review_result` value the wake it last forwarded for that document
  # carried.
  STATE = "spec_coordinator_child_wake_state"


# ----------------------------------------------------------------------------------------
class SpecCoordinatorReadyStateKey:
  """
  Frontmatter key recording this asset's own readiness-gate values as last observed by this
  worker, so a later wake can tell whether `spec_develop_done` / `spec_tests_passing` actually
  crossed to true rather than fired for an unrelated reason.

  Worker-internal bookkeeping, same convention as `SpecCoordinatorDocStateKey` — only
  `coordinator_dispatch.py`'s own direct write path ever sets it. Content-shaped rather than
  sha-keyed (`model-audit.md` I-A): the value is the gates' own booleans, not a commit
  reference, so it keeps meaning across a rewritten or destroyed commit. Any OTHER asset that
  names this one in its own `spec_depends_on` is woken (`CoordinatorTrigger.DEPENDENCY_READY`)
  only when a wake here crosses one of these gates against this marker's prior value — a wake
  that leaves both gates unchanged has nothing for a dependent to react to.

  Attributes:
    STATE: The `spec_coordinator_ready_state` frontmatter key. Its value is a JSON object
      `{Gate.DEVELOP_DONE: bool, Gate.TESTS_PASSING: bool}` snapshotting the two gates this
      worker's reverse-dependency scan watches for a crossing.
  """

  # The `spec_coordinator_ready_state` frontmatter key. Its value is a JSON object `{Gate.DEVELOP_DONE: bool,
  # Gate.TESTS_PASSING: bool}` snapshotting the two gates this worker's reverse-dependency scan watches for a
  # crossing.
  STATE = "spec_coordinator_ready_state"


# ----------------------------------------------------------------------------------------
class SpecTargetsKey:
  """
  Frontmatter key for a change asset's list of design-cascade target features.

  Attributes:
    TARGETS: The `spec_targets` frontmatter key naming the feature assets a
      change's design cascades into.
  """

  # The `spec_targets` frontmatter key naming the feature assets a change's design cascades into.
  TARGETS = "spec_targets"


# ----------------------------------------------------------------------------------------
class SpecDependsOnKey:
  """
  Frontmatter key for an asset's dependency graph (`lazy-spec.coordination-playbook.md` § 8).

  Attributes:
    DEPENDS_ON: The `spec_depends_on` frontmatter key naming the assets this asset needs —
      either an ordinary implementation-order dependency, or (for a code-free decomposer asset)
      the children its own `architecture.md` proposed and the coordinator materialized.
  """

  # The `spec_depends_on` frontmatter key naming the assets this asset needs — either an ordinary implementation-
  # order dependency, or (for a code-free decomposer asset) the children its own `architecture.md` proposed and the
  # coordinator materialized.
  DEPENDS_ON = "spec_depends_on"


# ----------------------------------------------------------------------------------------
class CascadeLabel:
  """
  Virtual dispatch-label constants for the change-cascade job pair.

  Unlike a `GateCheckbox` label, neither of these ever appears as a ticked `[!gate]` block in
  `# Gates` — the cascade dispatches automatically once a change's design is approved, with no
  operator tick. They share `gate_dispatch`'s wire-bundle shape and the `active_job` marker /
  dedup-key machinery with the launch ladder's checkboxes, so the resulting History lines and
  dedup keys read consistently with the ladder's own.

  Attributes:
    DESIGN: The designer half of the pair — folds the change's Target State into the target
      feature's own `design.md`.
    TEST_PLAN: The tester half of the pair — folds the same delta into the target's own
      `test-plan.md`, dispatched once the designer half's job completes.
  """

  # Domain(spec.lifecycle):
  # # A change's design cascades into its targets automatically
  # Once a change's own design is accepted, its approved delta is folded into every feature it
  # targets without an operator ticking anything — first into the target's own design, then,
  # once that step finishes, into the target's own test plan. The two steps always run in that
  # order because the second step folds a delta whose shape the first step just settled; folding
  # the test-plan half first would have nothing accepted yet to fold against.

  # The designer half of the pair — folds the change's Target State into the target feature's own `design.md`.
  DESIGN = "Cascade design"
  # The tester half of the pair — folds the same delta into the target's own `test-plan.md`, dispatched once the
  # designer half's job completes.
  TEST_PLAN = "Cascade test-plan"


# ----------------------------------------------------------------------------------------
class SpecCascadeKey:
  """
  Frontmatter keys tracking a change asset's progress cascading into its `spec_targets`.

  Attributes:
    DONE: The `spec_cascade_done` flag set once every declared target is accounted for in
      `TARGETS_DONE` — either folded by a completed designer/tester pair, or skipped because
      the token never resolved to an existing asset.
    TARGETS_DONE: The `spec_cascade_targets_done` list of product-relative target path tokens no
      longer pending dispatch — most having completed their designer/tester pair, plus any
      unresolvable token `gate_tick`'s Step 0.7 gave up on (see `TickAction.CASCADE_TARGET_SKIPPED`)
      so it does not block every later target forever.
  """

  # The `spec_cascade_done` flag set once every declared target is accounted for in `TARGETS_DONE` — either folded by
  # a completed designer/tester pair, or skipped because the token never resolved to an existing asset.
  DONE = "spec_cascade_done"
  # The `spec_cascade_targets_done` list of product-relative target path tokens no longer pending dispatch — most
  # having completed their designer/tester pair, plus any unresolvable token `gate_tick`'s Step 0.7 gave up on (see
  # `TickAction.CASCADE_TARGET_SKIPPED`) so it does not block every later target forever.
  TARGETS_DONE = "spec_cascade_targets_done"


# Decision: `spec_draft` (negative gate) replaces `spec_handoff_ready` (positive gate), not a
# same-semantics rename — a fresh asset needs no flag written to read as ready, and a downstream
# consumer written before an asset canonizes still reads it correctly (missing key = ready).

# ----------------------------------------------------------------------------------------
class DraftKey:
  """
  Frontmatter key for an asset's draft (not-yet-ready-for-downstream-pickup) state.

  Attributes:
    DRAFT: The `spec_draft` frontmatter key — this asset is still a draft, not yet ready for
      a downstream consumer to pick up, where the downstream repo mirrors this spec repo as
      its own upstream (read by `upstream_tick.py`'s own draft-gate when a consuming repo's
      `spec.upstream` source happens to be another canon repo carrying this same key). A
      negative gate: absent or false means ready. Set true by the coordinator when it
      canonizes a fresh full-mode asset. On a spec-only-mode asset
      (`lazy-spec.coordination-playbook.md` Chapter 14) the coordinator clears it once `design.md`
      is approved AND the operator gives their own word; on a full-mode asset it clears only
      when the operator ticks the `GateCheckbox.PUBLISH` checkbox the coordinator hangs once
      `spec_released` closes.
  """

  # The `spec_draft` frontmatter key — this asset is still a draft, not yet ready for a downstream consumer to pick
  # up, where the downstream repo mirrors this spec repo as its own upstream (read by `upstream_tick.py`'s own draft-
  # gate when a consuming repo's `spec.upstream` source happens to be another canon repo carrying this same key). A
  # negative gate: absent or false means ready. Set true by the coordinator when it canonizes a fresh full-mode
  # asset. On a spec-only-mode asset (`lazy-spec.coordination-playbook.md` Chapter 14) the coordinator clears it once
  # `design.md` is approved AND the operator gives their own word; on a full-mode asset it clears only when the
  # operator ticks the `GateCheckbox.PUBLISH` checkbox the coordinator hangs once `spec_released` closes.
  DRAFT = "spec_draft"


# ----------------------------------------------------------------------------------------
class AssetTypeKey:
  """
  Frontmatter keys naming what an asset is and what it is built with.

  Attributes:
    TYPE: The `spec_asset_type` frontmatter key — the asset's kind, declared under
      `products[<key>].asset_types` or shipped by the plugin, and resolved through
      `asset_types.py`. It decides which playbook the coordinator loads, which document the
      asset starts from, and which folder a new asset lands in.
    UNKNOWN: The `unknown` sentinel written when nobody has judged the asset's kind yet — a
      backfilled note whose folder matched no declaration, or a spawn whose router could not
      tell. The coordinator resolves it on its own wake rather than leaving it standing.
    TOOLS: The `spec_tools` frontmatter key — the tools the asset is realised and checked
      with, declared under `products[<key>].tool_types` or shipped by the plugin, and resolved
      through `tool_types.py`. An absent key means the tools are not determined yet, which is
      not the same as an empty list, which means determined to need none.
  """

  # The `spec_asset_type` frontmatter key — the asset's kind, declared under `products[<key>].asset_types` or shipped
  # by the plugin, and resolved through `asset_types.py`. It decides which playbook the coordinator loads, which
  # document the asset starts from, and which folder a new asset lands in.
  TYPE = "spec_asset_type"
  # The `unknown` sentinel written when nobody has judged the asset's kind yet — a backfilled note whose folder
  # matched no declaration, or a spawn whose router could not tell. The coordinator resolves it on its own wake
  # rather than leaving it standing.
  UNKNOWN = "unknown"
  # The `spec_tools` frontmatter key — the tools the asset is realised and checked with, declared under
  # `products[<key>].tool_types` or shipped by the plugin, and resolved through `tool_types.py`. An absent key means
  # the tools are not determined yet, which is not the same as an empty list, which means determined to need none.
  TOOLS = "spec_tools"


# ----------------------------------------------------------------------------------------
class HaltReason:
  """
  Halt-reason building blocks passed to the halt-asset primitive.

  These are short natural-English clauses naming what went wrong, not full
  sentences — the caller wraps them into the final `spec_halted`-callout /
  History-line text (which inserts the reason verbatim, so an internal slug
  would otherwise render raw to the operator). `JOB_DIED` is the one member
  that is a format template rather than a bare phrase: it reproduces the
  DEAD-branch wording verbatim (`job {job_id} ({label}) died`).

  Attributes:
    JOB_DIED: An expert job's bundle carried a `DEAD` marker; format template
      taking `job_id` and `label`.
    MERGE_CONFLICT: A cascade job reported a merge conflict while folding its
      result into the target document.
    PLAN_DROP_PARTIAL: A plan-dropping step (pre-launch rollback, or cascade
      code-plan removal) failed partway, leaving asset state half-dropped.
    GATE_PRECEDENCE: The doctor found a gate flipped true out of the
      documented precedence order.
  """

  # An expert job's bundle carried a `DEAD` marker; format template taking `job_id` and `label`.
  JOB_DIED = "job {job_id} ({label}) died"
  # A cascade job reported a merge conflict while folding its result into the target document.
  MERGE_CONFLICT = "change delta could not be applied cleanly to the feature docs"
  # A plan-dropping step (pre-launch rollback, or cascade code-plan removal) failed partway, leaving asset state
  # half-dropped.
  PLAN_DROP_PARTIAL = "plan drop left the asset half-cleaned"
  # The doctor found a gate flipped true out of the documented precedence order.
  GATE_PRECEDENCE = "later gate true while an earlier gate is false"


# ----------------------------------------------------------------------------------------
class UpstreamRole:
  """
  `spec_role` value for an upstream unit's own folder-note, declared into the closed
  `spec_role` vocabulary the same way `SpecValue.ROLE_REQUEST` and `coordinator_dispatch`'s
  status-note role are (`docs/tasks/lazycortex-specs.upstream.md` appendix).

  Attributes:
    UNIT: The `spec_role` value marking a file as an upstream unit's own note — distinct
      from any canon folder-note the mirrored `source/` tree may itself carry.
    SOURCE: The `spec_role` value marking a file as one configured source's own repo-level
      folder-note (`upstream/<repo-key>/<repo-key>.md`, § 5) — fetch status plus a live
      Dataview summary of its units, distinct from any one unit's own note.
  """

  # The `spec_role` value marking a file as an upstream unit's own note — distinct from any canon folder-note the
  # mirrored `source/` tree may itself carry.
  UNIT = "upstream-unit"
  # The `spec_role` value marking a file as one configured source's own repo-level folder-note (`upstream/<repo-
  # key>/<repo-key>.md`, § 5) — fetch status plus a live Dataview summary of its units, distinct from any one unit's
  # own note.
  SOURCE = "upstream-source"


# ----------------------------------------------------------------------------------------
class UpstreamStatus:
  """
  Closed vocabulary of `spec_upstream_status` values an upstream unit's note carries
  (`docs/tasks/lazycortex-specs.upstream.md` § 6).

  Attributes:
    NEW: Landed, never processed.
    DRIFTED: Source diverged from the last processed snapshot.
    IN_REVIEW: A request is open on this unit; frozen against the fetch phase.
    POSTPONED: The operator toggled this exact source state as skipped.
    PROCESSED: Processed, no divergence from source.
    ORPHANED: The unit's directory disappeared from the source tree.
    INVALID: The unit's directory carries no markdown file.
    EXCLUDED: The unit's path fell out of the mount's `units` glob or into `exclude`.
  """

  # Domain(spec.upstream):
  # # Most upstream statuses recompute every pass; two stay frozen
  # An upstream unit's own status is normally free to be recomputed from scratch on every pass —
  # nothing about a prior pass constrains what the next one may conclude. Two statuses are the
  # exception. A unit under an open request is frozen against recomputation entirely, because the
  # request already owns deciding what happens to it next; a unit the operator postponed stays
  # frozen only as long as the source content it was postponed against has not itself moved on —
  # once the source changes again, the postponement no longer applies to the same thing it was
  # given for, and the unit is free to be judged fresh.

  # Landed, never processed.
  NEW = "new"
  # Source diverged from the last processed snapshot.
  DRIFTED = "drifted"
  # A request is open on this unit; frozen against the fetch phase.
  IN_REVIEW = "in-review"
  # The operator toggled this exact source state as skipped.
  POSTPONED = "postponed"
  # Processed, no divergence from source.
  PROCESSED = "processed"
  # The unit's directory disappeared from the source tree.
  ORPHANED = "orphaned"
  # The unit's directory carries no markdown file.
  INVALID = "invalid"
  # The unit's path fell out of the mount's `units` glob or into `exclude`.
  EXCLUDED = "excluded"


# Statuses the fetch/detect phase (`upstream_tick.py`) is free to (re)compute every tick —
# the remaining two (`IN_REVIEW`, and `POSTPONED` while its stored hash still matches) are
# either frozen or conditionally held, never freely overwritten.
UPSTREAM_RECOMPUTABLE_STATUSES = frozenset({
    UpstreamStatus.NEW, UpstreamStatus.DRIFTED, UpstreamStatus.PROCESSED,
    UpstreamStatus.ORPHANED, UpstreamStatus.INVALID, UpstreamStatus.EXCLUDED,
})

# Statuses frozen against the fetch/detect phase — `# History` intro, § 8: frozen while in-review.
UPSTREAM_FROZEN_STATUSES = frozenset({UpstreamStatus.IN_REVIEW})


# ----------------------------------------------------------------------------------------
class UpstreamKey:
  """
  Frontmatter keys carried by an upstream unit's own folder-note.

  Attributes:
    STATUS: The `spec_upstream_status` key — one of `UpstreamStatus`'s closed set.
    REQUEST: The `spec_upstream_request` key naming the active request path; present only
      while `STATUS` is `UpstreamStatus.IN_REVIEW` (written by the request-dispatch phase,
      not `upstream_tick.py`'s own fetch/detect phase).
    POSTPONED_HASH: The `spec_upstream_postponed_hash` key — content hash of the exact
      source state the operator postponed; present only while `STATUS` is
      `UpstreamStatus.POSTPONED`. Set by the operator's own postpone toggle (not this
      module); cleared by the fetch/detect phase once the source state no longer matches it.
    REVISION: The `spec_upstream_revision` key — informational source commit SHA the unit's
      `source/` was last synced from, used to build forge blob links.
  """

  # The `spec_upstream_status` key — one of `UpstreamStatus`'s closed set.
  STATUS = "spec_upstream_status"
  # The `spec_upstream_request` key naming the active request path; present only while `STATUS` is
  # `UpstreamStatus.IN_REVIEW` (written by the request-dispatch phase, not `upstream_tick.py`'s own fetch/detect
  # phase).
  REQUEST = "spec_upstream_request"
  # The `spec_upstream_postponed_hash` key — content hash of the exact source state the operator postponed; present
  # only while `STATUS` is `UpstreamStatus.POSTPONED`. Set by the operator's own postpone toggle (not this module);
  # cleared by the fetch/detect phase once the source state no longer matches it.
  POSTPONED_HASH = "spec_upstream_postponed_hash"
  # The `spec_upstream_revision` key — informational source commit SHA the unit's `source/` was last synced from,
  # used to build forge blob links.
  REVISION = "spec_upstream_revision"


# ----------------------------------------------------------------------------------------
class UpstreamAction:
  """
  Operator action-checkbox labels the fetch/detect phase hangs under an upstream unit
  note's `# Actions` section (`docs/tasks/lazycortex-specs.upstream.md` §§ 7, on merge
  decisions). `NEW` and `DRIFTED` each carry a primary checkbox plus `POSTPONE` alongside it;
  a unit already `POSTPONED` carries only its own resume checkbox (the primary label its
  shadowed content status would use), never a second `POSTPONE` box — every other status
  renders an inert one-line note instead.

  Attributes:
    TAKE_INTO_WORK: The checkbox label hung on a `UpstreamStatus.NEW` unit.
    PROCESS_UPDATE: The checkbox label hung on a `UpstreamStatus.DRIFTED` unit.
    POSTPONE: The checkbox label hung alongside the primary one on a `NEW` / `DRIFTED` unit —
      ticking it freezes the unit's exact current content state as `UpstreamStatus.POSTPONED`
      (§ 7: set by the operator). Never rendered on an already-postponed unit, whose own resume
      checkbox already cancels the postpone when ticked.
  """

  # The checkbox label hung on a `UpstreamStatus.NEW` unit.
  TAKE_INTO_WORK = "Take into work"
  # The checkbox label hung on a `UpstreamStatus.DRIFTED` unit.
  PROCESS_UPDATE = "Process update"
  # The checkbox label hung alongside the primary one on a `NEW` / `DRIFTED` unit — ticking it freezes the unit's
  # exact current content state as `UpstreamStatus.POSTPONED` (§ 7: set by the operator). Never rendered on an
  # already-postponed unit, whose own resume checkbox already cancels the postpone when ticked.
  POSTPONE = "Postpone"


# Closed label set `UpstreamAction` declares — the doctor (`docs/tasks/lazycortex-specs.upstream.md`
# § 13) reads this to FAIL an unrecognized checkbox label under a unit note's `# Actions` section,
# the same "closed set, unknown value is FAIL" shape `GateCheckbox`'s six labels use.
UPSTREAM_ACTION_LABELS = frozenset({
    UpstreamAction.TAKE_INTO_WORK, UpstreamAction.PROCESS_UPDATE, UpstreamAction.POSTPONE,
})


# ----------------------------------------------------------------------------------------
class UpstreamSourceStatus:
  """
  Closed vocabulary of `spec_upstream_fetch_status` values a source note carries (§ 5).

  Attributes:
    OK: The source's most recent fetch attempt succeeded, or its consecutive failure streak
      has not yet reached `fetch_failure_threshold`.
    FAILING: The source's consecutive failure streak reached `fetch_failure_threshold`; the
      note carries the last fetch error verbatim.
  """

  # The source's most recent fetch attempt succeeded, or its consecutive failure streak has not yet reached
  # `fetch_failure_threshold`.
  OK = "ok"
  # The source's consecutive failure streak reached `fetch_failure_threshold`; the note carries the last fetch error
  # verbatim.
  FAILING = "failing"


# ----------------------------------------------------------------------------------------
class UpstreamSourceKey:
  """
  Frontmatter keys carried by one configured source's own repo-level folder-note
  (`upstream/<repo-key>/<repo-key>.md`, § 5).

  Attributes:
    FETCH_STATUS: The `spec_upstream_fetch_status` key — one of `UpstreamSourceStatus`'s
      closed set.
    FETCH_FAILURES: The `spec_upstream_fetch_failures` key — the consecutive fetch-failure
      streak this source's `fetch_failure_threshold` counts against; reset to `0` by the next
      success.
    FETCH_ERROR: The `spec_upstream_fetch_error` key — the last fetch failure's own message;
      present only while `FETCH_STATUS` is `UpstreamSourceStatus.FAILING`.
    FETCH_LAST_SUCCESS: The `spec_upstream_fetch_last_success` key — the date of the most
      recent successful fetch, informational; absent before the first-ever success.
  """

  # The `spec_upstream_fetch_status` key — one of `UpstreamSourceStatus`'s closed set.
  FETCH_STATUS = "spec_upstream_fetch_status"
  # The `spec_upstream_fetch_failures` key — the consecutive fetch-failure streak this source's
  # `fetch_failure_threshold` counts against; reset to `0` by the next success.
  FETCH_FAILURES = "spec_upstream_fetch_failures"
  # The `spec_upstream_fetch_error` key — the last fetch failure's own message; present only while `FETCH_STATUS` is
  # `UpstreamSourceStatus.FAILING`.
  FETCH_ERROR = "spec_upstream_fetch_error"
  # The `spec_upstream_fetch_last_success` key — the date of the most recent successful fetch, informational; absent
  # before the first-ever success.
  FETCH_LAST_SUCCESS = "spec_upstream_fetch_last_success"
