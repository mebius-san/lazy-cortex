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
    REVIEW_RESULT: The terminal apply-gate discriminator stamped at finalize.
  """

  ROLE = "spec_role"
  STATUS = "request_status"
  CLASS = "request_class"
  REVIEW_ACTIVE = "review_active"
  REVIEW_ROUND = "review_round"
  REVIEW_APPROVED = "review_approved"
  REVIEW_RESULT = "review_result"


# ----------------------------------------------------------------------------------------
class SpecValue:
  """
  Frontmatter value tokens written and compared as strings.

  Attributes:
    ROLE_REQUEST: The canonical `spec_role` value for a request file.
    CLASS_UNKNOWN: The unclassified `request_class` value.
    STATUS_DRAFT: The pre-terminal `request_status` value.
    TRUE: The boolean-true frontmatter value literal.
    FALSE: The boolean-false frontmatter value literal.
    ROUND_ONE: The initial `review_round` value.
    TAG_DRAFT: The `tags:` member added on opt-in.
  """

  ROLE_REQUEST = "request"
  CLASS_UNKNOWN = "unknown"
  STATUS_DRAFT = "draft"
  TRUE = "true"
  FALSE = "false"
  ROUND_ONE = "1"
  TAG_DRAFT = "request/draft"


# ----------------------------------------------------------------------------------------
class BannerTag:
  """
  Review-status banner tags compared as substrings.

  Attributes:
    IN_PROCESS: The Waiting banner tag for a file under review.
    ACTION_NEEDED: The banner tag for a file awaiting an operator gesture.
    READY: The banner tag for a finalized-ready file.
  """

  IN_PROCESS = "#review/in-process"
  ACTION_NEEDED = "#review/action-needed"
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

  NAKED = "naked"
  PARTIAL = "partial"
  READY = "ready"
  READY_FOR_APPLY = "ready-for-apply"
  TERMINAL = "terminal"
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

  OPENED = "opened"
  REPAIRED = "repaired"
  ALREADY_OPTED_IN = "already-opted-in"
  READY_FOR_APPLY_SKIP = "ready-for-apply-skip"
  TERMINAL_STATE_SKIP = "terminal-state-skip"
  UNKNOWN_STATE_SKIP = "unknown-state-skip"


# ----------------------------------------------------------------------------------------
class Gate:
  """
  Flat top-level boolean gate key names carried by an asset status folder-note.

  Attributes:
    DESIGN_DONE: The design-accepted gate.
    PLAN_DONE: The plan-accepted gate.
    DEVELOP_DONE: The development-complete gate.
    TESTS_PASSING: The tests-passing gate.
    RELEASED: The released gate.
    SPEC_CANCELLED: The asset-cancelled flag that refuses every gate flip.
  """

  DESIGN_DONE = "spec_design_done"
  PLAN_DONE = "spec_plan_done"
  DEVELOP_DONE = "spec_develop_done"
  TESTS_PASSING = "spec_tests_passing"
  RELEASED = "spec_released"
  SPEC_CANCELLED = "spec_cancelled"


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
  """

  EMPTY = "empty"
  DRAFT = "draft"
  APPROVED = "approved"
  REJECTED = "rejected"
  CANCELLED = "cancelled"


# Gates whose precondition is strictly derivable from per-file approval stages.
DERIVED_GATES = frozenset({Gate.DESIGN_DONE, Gate.PLAN_DONE})

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


# ----------------------------------------------------------------------------------------
class StageKey:
  """
  Per-file frontmatter key carried by authored spec docs.

  Attributes:
    STAGE: The `spec_stage` key naming a doc's lifecycle stage.
  """

  STAGE = "spec_stage"


# ----------------------------------------------------------------------------------------
class SiblingDoc:
  """
  Authored sibling-doc filenames inside an asset folder.

  Attributes:
    DESIGN: The feature/change design doc.
    BUG: The bug-layout design-side doc.
    PLAN: The plan doc.
  """

  DESIGN = "design.md"
  BUG = "bug.md"
  PLAN = "plan.md"


# ----------------------------------------------------------------------------------------
class Section:
  """
  Body section headings the gate primitives read and append to.

  Attributes:
    GATES: The `## Gates` heading carrying gate callouts.
    HISTORY: The `## History` heading carrying gate-change log lines.
  """

  GATES = "## Gates"
  HISTORY = "## History"


# ----------------------------------------------------------------------------------------
class FlipResult:
  """
  Result-dict status and field tokens emitted by the flip-gate primitive.

  Attributes:
    STATUS: The status-field key.
    FLIPPED: The success status value.
    REFUSED: The refusal status value.
  """

  STATUS = "status"
  FLIPPED = "flipped"
  REFUSED = "refused"


# Frontmatter boolean literal compared and written for gate values.
BOOL_TRUE = "true"


# ----------------------------------------------------------------------------------------
class PlanReview:
  """
  Post-flip plan-review auto-open status tokens and resolution constants.

  Attributes:
    KEY: The result-dict field carrying the auto-open status.
    OPENED: Review was opened on the sibling `plan.md`.
    SKIP_STAGE: Skipped because `plan.md` is past the openable stage set.
    SKIP_ACTIVE: Skipped because `plan.md` is already in active review.
    SKIP_NO_PLAN: Skipped because the asset has no `plan.md` sibling.
    SKIP_CLI_UNAVAILABLE: Skipped because the review CLI could not be resolved or run.
    REVIEW_ACTIVE_KEY: The `plan.md` frontmatter key marking active review.
    REVIEW_CLI: The `lazycortex-review` CLI binary name resolved under a plugin dir.
    START_VERB: The review CLI subcommand that opts a document into review.
    PLUGIN_DIRS_ENV: The env var listing plugin dirs to walk for the CLI.
    BIN_DIR: The per-plugin `bin/` subdir holding the CLI binary.
    START_TIMEOUT_S: Seconds the best-effort `start` subprocess may run.
  """

  KEY = "plan_review"
  OPENED = "opened"
  SKIP_STAGE = "skip:stage"
  SKIP_ACTIVE = "skip:active"
  SKIP_NO_PLAN = "skip:no-plan"
  SKIP_CLI_UNAVAILABLE = "skip:review-cli-unavailable"
  REVIEW_ACTIVE_KEY = "review_active"
  REVIEW_CLI = "lazycortex-review"
  START_VERB = "start"
  PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
  BIN_DIR = "bin"
  START_TIMEOUT_S = 60


# Per-file stages from which a follow-up plan review may be auto-opened.
PLAN_OPENABLE_STAGES = frozenset({Stage.EMPTY, Stage.DRAFT})

# Run-logging helper constants.
LOG_NO_GIT = "no-git"
LOG_ROOT = ".logs"
LOG_CLAUDE = "claude"
FLIP_GATE_NAME = "spec.flip-gate"


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
    NOOP: Nothing to do this tick.
  """

  ACTION = "action"
  AUTO_FLIPPED = "auto-flipped"
  READY_CALLOUT = "ready-callout"
  READINESS_WITHDRAWN = "readiness-withdrawn"
  STAGE_PROMOTED = "stage-promoted"
  NOOP = "noop"
