"""
Centralized frontmatter key names for the lazy-review lifecycle.

The review state machine reads and writes a fixed set of `review_*` frontmatter
keys across many modules. Defining them once here means a mistyped key surfaces
as an `AttributeError` at import time rather than as silent state corruption in
the running loop.

The same discipline extends to the other string tokens the lifecycle compares as
strings: audit severities, writer-phase / outcome value tokens, record / payload
dict-key names, tag prefixes, and job-dir filenames. Each container below holds
plain `str` constants whose values are byte-identical to the literals they
replace — they are NOT enums, so `value == Container.X` stays a string
comparison and parsed strings keep matching.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The shipped language floor: the code every per-language string table is guaranteed to hold,
# and what the language resolver returns when a vault names none. One definition for the whole
# plugin — `note_ops`, `start` and `banner` all read this one.
LANG_EN = "en"

# The autorun cycle cap a review class gets when its config names none.
DEFAULT_AUTORUN_MAX_CYCLES = 7


# ----------------------------------------------------------------------------------------
class ReviewKey:
  """
  Frontmatter key names managed by the review lifecycle.

  Attributes:
    ACTIVE: Whether a document is opted into the review loop.
    ROUND: The current review round counter.
    APPROVED: The whole-document approval flag.
    PHASE: The current writer phase (`main`, `section`, ...).
    RESULT: The terminal apply-gate discriminator stamped at finalize.
    MARKER_STYLE: The edit-marker style pinned to the review cycle at open time.
    MAIN_DONE: The bracketed list of main writers already run.
    EXPERT: A per-document main-writer override.
    VALIDATION_ROUND: The post-approve validation-barrier round counter.
    SKIP_VALIDATION: Whether the operator chose to finalize without the validation barrier.
    AUTORUN: The autorun state, one of the `AutorunState` tokens.
    AUTORUN_CYCLES: The count of autorun cycles run in this review.
    PREFIX: The shared prefix of every review-lifecycle frontmatter key.
    RETIRED: The retired key names, which only accept deletion and are never written again.
  """

  # Whether a document is opted into the review loop.
  ACTIVE = "review_active"
  # The current review round counter.
  ROUND = "review_round"
  # The whole-document approval flag.
  APPROVED = "review_approved"
  # The current writer phase (`main`, `section`, ...).
  PHASE = "review_phase"
  # The terminal apply-gate discriminator stamped at finalize.
  RESULT = "review_result"
  # The edit-marker style pinned to the review cycle at open time.
  MARKER_STYLE = "review_marker_style"
  # The bracketed list of main writers already run.
  MAIN_DONE = "review_main_done"
  # A per-document main-writer override.
  EXPERT = "review_expert"
  # The post-approve validation-barrier round counter.
  VALIDATION_ROUND = "review_validation_round"
  # Whether the operator chose to finalize without the validation barrier.
  SKIP_VALIDATION = "review_skip_validation"
  # The autorun state, one of the `AutorunState` tokens.
  AUTORUN = "review_autorun"
  # The count of autorun cycles run in this review.
  AUTORUN_CYCLES = "review_autorun_cycles"
  # The shared prefix of every review-lifecycle frontmatter key.
  PREFIX = "review_"
  # The retired key names, which only accept deletion and are never written again.
  RETIRED: frozenset[str] = frozenset({ "review_concerns_auto_continue", "review_approved_with_concerns" })


# ----------------------------------------------------------------------------------------
class AutorunState:
  """
  Autorun state value tokens compared as strings.

  Attributes:
    RUNNING: The autorun is advancing the review loop on its own.
    CLEAN: The autorun stopped on a clean validator barrier after at least one automatic approve.
    CAP: The autorun stopped at the configured cycle cap.
    QUESTION: The autorun stopped because a writer raised a question for the operator.
  """

  # The autorun is advancing the review loop on its own.
  RUNNING = "running"
  # The autorun stopped on a clean validator barrier after at least one automatic approve.
  CLEAN = "clean"
  # The autorun stopped at the configured cycle cap.
  CAP = "cap"
  # The autorun stopped because a writer raised a question for the operator.
  QUESTION = "question"


# ----------------------------------------------------------------------------------------
class JobMarker:
  """
  Per-document job-marker field names in the runtime sidecar, and the wake token one carries.

  These name fields of `.runtime/lazy-review.jobs.json`, not frontmatter: the markers are
  runtime state the review system owns, invisible in the document and unreachable by a
  hand-edit (`job_markers.py`).

  Attributes:
    COORDINATOR_JOB: The id of the coordinator job currently in flight on the document.
    ACTIVE_JOB: The id of the expert job currently in flight on the document.
    PENDING_WAKE: The wake the postman raised and the watch worker has yet to consume.
    LAST_SEEN_SHA: The last git-watch item sha the wake worker judged for this document.
    JOB_DONE: The `PENDING_WAKE` value a landed expert payload raises.
    KIND_COORDINATOR: The `mark-job` CLI token selecting `COORDINATOR_JOB`.
    KIND_WRITER: The `mark-job` CLI token selecting `ACTIVE_JOB`.
  """

  # The id of the coordinator job currently in flight on the document.
  COORDINATOR_JOB = "coordinator_job"
  # The id of the expert job currently in flight on the document.
  ACTIVE_JOB = "active_job"
  # The wake the postman raised and the watch worker has yet to consume.
  PENDING_WAKE = "pending_wake"
  # The last git-watch item sha the wake worker judged for this document.
  LAST_SEEN_SHA = "last_seen_sha"
  # The `PENDING_WAKE` value a landed expert payload raises.
  JOB_DONE = "job-done"
  # The `mark-job` CLI token selecting `COORDINATOR_JOB`.
  KIND_COORDINATOR = "coordinator"
  # The `mark-job` CLI token selecting `ACTIVE_JOB`.
  KIND_WRITER = "writer"


# ----------------------------------------------------------------------------------------
class ReviewStatus:
  """
  Audit / finding severity tokens compared as strings.

  Attributes:
    FAIL: A blocking finding; aggregate level escalates to FAIL.
    WARN: A non-blocking advisory finding.
    PASS: A clean check with no issues.
    INFO: An informational, non-severity finding.
  """

  # A blocking finding; aggregate level escalates to FAIL.
  FAIL = "FAIL"
  # A non-blocking advisory finding.
  WARN = "WARN"
  # A clean check with no issues.
  PASS = "PASS"
  # An informational, non-severity finding.
  INFO = "INFO"


# ----------------------------------------------------------------------------------------
class Phase:
  """
  Writer-phase value tokens compared as strings.

  Attributes:
    MAIN: The opening main-writer phase.
    SECTION: The per-section writer phase.
    MECHANICAL: The mechanical-edit phase.
    FINALIZE: The finalize phase.
    HISTORY: The historian phase.
    HISTORY_APPEND: The `Doc-Review-Phase` trailer value for an appended history entry.
    HISTORY_NOOP: The `Doc-Review-Phase` trailer value for a history no-op placeholder.
    INITIAL: The `Doc-Review-Phase` trailer value for a `lazy-review.submit` bootstrap commit.
  """

  # The opening main-writer phase.
  MAIN = "main"
  # The per-section writer phase.
  SECTION = "section"
  # The mechanical-edit phase.
  MECHANICAL = "mechanical"
  # The finalize phase.
  FINALIZE = "finalize"
  # The historian phase.
  HISTORY = "history"
  # The `Doc-Review-Phase` trailer value for an appended history entry.
  HISTORY_APPEND = "history:append"
  # The `Doc-Review-Phase` trailer value for a history no-op placeholder.
  HISTORY_NOOP = "history:noop"
  # The `Doc-Review-Phase` trailer value for a `lazy-review.submit` bootstrap commit.
  INITIAL = "initial"


# ----------------------------------------------------------------------------------------
class Outcome:
  """
  Outcome / transient-state value tokens compared as strings.

  Attributes:
    SKIP: An iteration that did no work.
    MISSING: A referenced artifact that was absent.
    EMPTY: A present-but-empty artifact.
    NOOP: A no-operation result.
    CONCERNS: The outstanding-concerns decision state.
    CONSUMED: A job whose result has been consumed.
    REPAIR: The history-repair action.
    EDITED: A writer outcome that produced edited content.
    SUMMARIZED: A historian outcome that produced a summary entry.
    ERROR: An outcome indicating the agent reported an error.
  """

  # An iteration that did no work.
  SKIP = "skip"
  # A referenced artifact that was absent.
  MISSING = "missing"
  # A present-but-empty artifact.
  EMPTY = "empty"
  # A no-operation result.
  NOOP = "noop"
  # The outstanding-concerns decision state.
  CONCERNS = "concerns"
  # A job whose result has been consumed.
  CONSUMED = "CONSUMED"
  # The history-repair action.
  REPAIR = "repair"
  # A writer outcome that produced edited content.
  EDITED = "edited"
  # A historian outcome that produced a summary entry.
  SUMMARIZED = "summarized"
  # An outcome indicating the agent reported an error.
  ERROR = "error"


# ----------------------------------------------------------------------------------------
class Action:
  """
  Dispatcher tick-action `kind` value tokens compared as strings.

  Produced by the state machine's `decide` and matched by the dispatcher's apply dispatch.
  Pipeline-phase actions (`main`, `finalize`) and the `skip` / `repair` no-action kinds carry
  their tokens in `Phase` / `Outcome`; the tokens below are the mechanical / barrier actions.

  Attributes:
    APPROVE_MIRROR: Mirror the operator's whole-document approval into frontmatter.
    APPROVE_AUTORUN_MIRROR: Mirror the operator's approve-with-autorun gesture into frontmatter.
    APPROVE_SKIP_VALIDATION_MIRROR: Mirror the operator's approve-without-validation gesture into frontmatter.
    AUTORUN_ADVANCE: Advance an autorunning document into its next cycle without waiting for the operator.
    BANNER_REPAINT: Repaint the top banner to the desired state.
    RESET_APPROVAL: Reset approval and re-open the validator barrier.
    BARRIER_DISPATCH: Queue every pending writer of the active barrier at once.
    BARRIER_COLLECT: Sweep-collect the drained barrier in a single pass.
    REVERT_TO_MAIN: Revert a final-concerns document back to the main-writer round.
  """

  # Mirror the operator's whole-document approval into frontmatter.
  APPROVE_MIRROR = "approve-mirror"
  # Mirror the operator's approve-with-autorun gesture into frontmatter.
  APPROVE_AUTORUN_MIRROR = "approve-autorun-mirror"
  # Mirror the operator's approve-without-validation gesture into frontmatter.
  APPROVE_SKIP_VALIDATION_MIRROR = "approve-skip-validation-mirror"
  # Advance an autorunning document into its next cycle without waiting for the operator.
  AUTORUN_ADVANCE = "autorun-advance"
  # Repaint the top banner to the desired state.
  BANNER_REPAINT = "banner-repaint"
  # Reset approval and re-open the validator barrier.
  RESET_APPROVAL = "reset-approval"
  # Queue every pending writer of the active barrier at once.
  BARRIER_DISPATCH = "barrier-dispatch"
  # Sweep-collect the drained barrier in a single pass.
  BARRIER_COLLECT = "barrier-collect"
  # Revert a final-concerns document back to the main-writer round.
  REVERT_TO_MAIN = "revert-to-main"


# ----------------------------------------------------------------------------------------
class JobKey:
  """
  Record / payload / config dict-key names compared as strings.

  Attributes:
    NAME: A writer / expert name field.
    EXPERTS: The experts catalog / group block.
    ROUTINES: The routine registry block.
    ERROR: An error-message field.
    COMMIT_SHA: A commit-SHA field.
    FILE: A file-path field.
    OUTCOME: A job-outcome field.
    RESULT: A result-payload field.
    STATUS: A status field.
    EMAIL: A git-author email field.
    EDIT_MARKER_STYLE: The configured edit-marker style key.
    WATCH_ROOT: The folder whose commits the coordinator's git-watch hears about.
    OPERATOR_COMMIT_SHA: The operator's commit-SHA field.
    OPERATOR_SHA_AT_DISPATCH: The snapshot of the operator SHA at dispatch.
    VERSION: A schema-version sentinel key.
    KIND: An action / record kind field.
    INCIDENT: An error-ledger incident key.
    SEVERITY: A finding-severity field.
    AGENT: An expert agent-name field.
    GIT_AUTHOR: An expert git-author block.
    COMMAND: A routine command field.
    HISTORY_ENTRY: A history-entry payload field.
    PAYLOAD: A job-bundle request-payload field.
    SOURCE: A job-bundle source work-file field.
    CONTEXT: A request / job-bundle context-file field.
    PATH: A path-entry field inside a source / context / result list item.
    DEDUP_KEY: A job-bundle dedup-key field.
    PROTOCOLS: A routine / job-bundle attached-protocols field.
    ROLE: A free-form expert role field.
    MODE: The structural dispatch-mode field of a request.
    ROUND: The request round-number field.
    JOB_ID: A job-directory identifier field.
    JOBS: A pickup-result jobs-list field.
    PICKED_UP: A pickup-result count field.
    RESPONSE: A job response-payload field.
    TIMESTAMP: A job pickup timestamp field.
    REASON: A skip / no-action reason field.
    CATEGORY: An error-category discriminator field.
    MESSAGE: A human-readable message field.
    GROUP: A concern-record writer-group field.
    WRITER: A concern-record / writer-name field.
    POSITION: A section-writer position field.
    FRONTMATTER: A routine-filter / expert frontmatter block.
    ALLOW: A frontmatter-overlay allow-list field.
    REQUIRE: A frontmatter-overlay require-list field.
    CLASSES: The `review.classes` list key.
    REVIEW: The top-level `review` config block key.
    CLASS: A class-entry name field.
    PATHS: A class-entry paths-glob list field.
    CHECK: An audit-finding check-id field.
    LEVEL: An audit-bundle aggregate-level field.
    FINDINGS: An audit-bundle findings-list field.
    BANNER: A status-record banner-state field.
    OWNERS: A status-record section-owners list field.
    OWNER: A status-record section-owner field.
    SECTION: A status-record / writer section-title field.
    SECTION_ID: A job-request owned-section identifier field.
    ACTIONS: A tick-log actions-list field.
    STATE: A status-callout terminal-state field.
    MARKER: A status-callout callout-marker field.
    TITLE: A status-callout title field.
    BODY_LINES: A status-callout body-lines field.
    META: A dispatcher-context frontmatter-meta field.
    TEXT: A dispatcher-context full-text field.
    BODY: A dispatcher-context body field.
    SECTION_H1_TITLE: A concern-record section-title field.
    CONTENT: A concern-record section-content field.
    EXPERT: A job-bundle / summary expert-name field.
    WAITING_CONTEXT: A barrier-result waiting-banner-context field.
    TO_DISPATCH: A barrier-result writers-to-dispatch field.
    OPEN: A barrier-result open-in-flight flag field.
    READY: A barrier-result ready-to-collect flag field.
    RESET: A barrier-result operator-reset-pending flag field.
    CLASS_CFG: A dispatcher-context resolved-review-class field.
    HISTORY: A dispatcher-context commit-history-records field.
    APPROVED: A dispatcher-context whole-document-approved flag field.
    LAST_COMMIT_IS_HUMAN: A dispatcher-context operator-commit-detect flag field.
    TARGET_FILE: The per-job request target-file marker field.
    WRITER_COMMIT_TIMESTAMP: The per-job dispatch-time writer-commit timestamp field.
    FILE_SNAPSHOT_HASH: The per-job dispatch-time file-content snapshot-hash field.
    DEDUP_TRACKER: The per-job dispatch-dedup tracker key field.
    AUTORUN_MAX_CYCLES: The review-class config key capping the autorun cycles.
    DOC_DOCTOR: The `review.doc_doctor` repair-expert config key.
    FOUND: The `lookup-expert` hit-flag response field.
    ENTRY: The `lookup-expert` expert-entry response field.
    HISTORY_KICK: A tick-summary historian-kick result field.
    HISTORY_KICK_ERROR: A tick-summary historian-kick error field.
    DISPATCH_ERRORS: A barrier-dispatch summary errors-list field.
    DISPATCHED: A barrier-dispatch summary dispatched-writers field.
    NEW_REVIEW_ROUND: A post-main-cleanup summary new-round field.
    CLEANUP_COMMIT_SHA: A post-main-cleanup summary commit-sha field.
    OWNERSHIP_VIOLATION: A reapply summary ownership-violation field.
    WRITER_COMMIT_SHA: A history-request payload writer-commit-sha field.
    REPAIRED_HISTORY_SECTION: A historian-response repaired-section field.
    SECTION_COMMITS: A barrier-collect summary section-commits field.
    NEW_VALIDATION_ROUND: A validator-barrier summary new-validation-round field.
    DECISION_COMMIT_SHA: A retired decision summary commit-sha field that no code sets or reads.
    HISTORY_PICKUP: A consume-pass summary history-pickup field.
    CONTEXT_FROM_FRONTMATTER: A class-config frontmatter-key-list field for job-context resolution.
    WARNINGS: A tick-summary non-fatal-warnings-list field.
  """

  # A writer / expert name field.
  NAME = "name"
  # The experts catalog / group block.
  EXPERTS = "experts"
  # The routine registry block.
  ROUTINES = "routines"
  # An error-message field.
  ERROR = "error"
  # A commit-SHA field.
  COMMIT_SHA = "commit_sha"
  # A file-path field.
  FILE = "file"
  # A job-outcome field.
  OUTCOME = "outcome"
  # A result-payload field.
  RESULT = "result"
  # A status field.
  STATUS = "status"
  # A git-author email field.
  EMAIL = "email"
  # The configured edit-marker style key.
  EDIT_MARKER_STYLE = "edit_marker_style"
  # The folder whose commits the coordinator's git-watch hears about.
  WATCH_ROOT = "watch_root"
  # The operator's commit-SHA field.
  OPERATOR_COMMIT_SHA = "operator_commit_sha"
  # The snapshot of the operator SHA at dispatch.
  OPERATOR_SHA_AT_DISPATCH = "_operator_sha_at_dispatch"
  # A schema-version sentinel key.
  VERSION = "_version"
  # An action / record kind field.
  KIND = "kind"
  # An error-ledger incident key.
  INCIDENT = "incident"
  # A finding-severity field.
  SEVERITY = "severity"
  # An expert agent-name field.
  AGENT = "agent"
  # An expert git-author block.
  GIT_AUTHOR = "git_author"
  # A routine command field.
  COMMAND = "command"
  # A history-entry payload field.
  HISTORY_ENTRY = "history_entry"
  # A job-bundle request-payload field.
  PAYLOAD = "payload"
  # A job-bundle source work-file field.
  SOURCE = "source"
  # A request / job-bundle context-file field.
  CONTEXT = "context"
  # A path-entry field inside a source / context / result list item.
  PATH = "path"
  # A job-bundle dedup-key field.
  DEDUP_KEY = "dedup_key"
  # A routine / job-bundle attached-protocols field.
  PROTOCOLS = "protocols"
  # A free-form expert role field.
  ROLE = "role"
  # The structural dispatch-mode field of a request.
  MODE = "mode"
  # The request round-number field.
  ROUND = "round"
  # A job-directory identifier field.
  JOB_ID = "job_id"
  # A pickup-result jobs-list field.
  JOBS = "jobs"
  # A pickup-result count field.
  PICKED_UP = "picked_up"
  # A job response-payload field.
  RESPONSE = "response"
  # A job pickup timestamp field.
  TIMESTAMP = "timestamp"
  # A skip / no-action reason field.
  REASON = "reason"
  # An error-category discriminator field.
  CATEGORY = "category"
  # A human-readable message field.
  MESSAGE = "message"
  # A concern-record writer-group field.
  GROUP = "group"
  # A concern-record / writer-name field.
  WRITER = "writer"
  # A section-writer position field.
  POSITION = "position"
  # A routine-filter / expert frontmatter block.
  FRONTMATTER = "frontmatter"
  # A frontmatter-overlay allow-list field.
  ALLOW = "allow"
  # A frontmatter-overlay require-list field.
  REQUIRE = "require"
  # The `review.classes` list key.
  CLASSES = "classes"
  # The top-level `review` config block key.
  REVIEW = "review"
  # A class-entry name field.
  CLASS = "class"
  # A class-entry paths-glob list field.
  PATHS = "paths"
  # An audit-finding check-id field.
  CHECK = "check"
  # An audit-bundle aggregate-level field.
  LEVEL = "level"
  # An audit-bundle findings-list field.
  FINDINGS = "findings"
  # A status-record banner-state field.
  BANNER = "banner"
  # A status-record section-owners list field.
  OWNERS = "owners"
  # A status-record section-owner field.
  OWNER = "owner"
  # A status-record / writer section-title field.
  SECTION = "section"
  # A job-request owned-section identifier field.
  SECTION_ID = "section_id"
  # A tick-log actions-list field.
  ACTIONS = "actions"
  # A status-callout terminal-state field.
  STATE = "state"
  # A status-callout callout-marker field.
  MARKER = "marker"
  # A status-callout title field.
  TITLE = "title"
  # A status-callout body-lines field.
  BODY_LINES = "body_lines"
  # A dispatcher-context frontmatter-meta field.
  META = "meta"
  # A dispatcher-context full-text field.
  TEXT = "text"
  # A dispatcher-context body field.
  BODY = "body"
  # A concern-record section-title field.
  SECTION_H1_TITLE = "section_h1_title"
  # A concern-record section-content field.
  CONTENT = "content"
  # A job-bundle / summary expert-name field.
  EXPERT = "expert"
  # A barrier-result waiting-banner-context field.
  WAITING_CONTEXT = "waiting_context"
  # A barrier-result writers-to-dispatch field.
  TO_DISPATCH = "to_dispatch"
  # A barrier-result open-in-flight flag field.
  OPEN = "open"
  # A barrier-result ready-to-collect flag field.
  READY = "ready"
  # A barrier-result operator-reset-pending flag field.
  RESET = "reset"
  # A dispatcher-context resolved-review-class field.
  CLASS_CFG = "class_cfg"
  # A dispatcher-context commit-history-records field.
  HISTORY = "history"
  # A dispatcher-context whole-document-approved flag field.
  APPROVED = "approved"
  # A dispatcher-context operator-commit-detect flag field.
  LAST_COMMIT_IS_HUMAN = "last_commit_is_human"
  # The per-job request target-file marker field.
  TARGET_FILE = "_target_file"
  # The per-job dispatch-time writer-commit timestamp field.
  WRITER_COMMIT_TIMESTAMP = "_writer_commit_timestamp"
  # The per-job dispatch-time file-content snapshot-hash field.
  FILE_SNAPSHOT_HASH = "_file_snapshot_hash"
  # The per-job dispatch-dedup tracker key field.
  DEDUP_TRACKER = "_dedup_key"
  # The review-class config key capping the autorun cycles.
  AUTORUN_MAX_CYCLES = "autorun_max_cycles"
  # The `review.doc_doctor` repair-expert config key.
  DOC_DOCTOR = "doc_doctor"
  # The `lookup-expert` hit-flag response field.
  FOUND = "found"
  # The `lookup-expert` expert-entry response field.
  ENTRY = "entry"
  # A tick-summary historian-kick result field.
  HISTORY_KICK = "history_kick"
  # A tick-summary historian-kick error field.
  HISTORY_KICK_ERROR = "history_kick_error"
  # A barrier-dispatch summary errors-list field.
  DISPATCH_ERRORS = "dispatch_errors"
  # A barrier-dispatch summary dispatched-writers field.
  DISPATCHED = "dispatched"
  # A post-main-cleanup summary new-round field.
  NEW_REVIEW_ROUND = "new_review_round"
  # A post-main-cleanup summary commit-sha field.
  CLEANUP_COMMIT_SHA = "cleanup_commit_sha"
  # A reapply summary ownership-violation field.
  OWNERSHIP_VIOLATION = "ownership_violation"
  # A history-request payload writer-commit-sha field.
  WRITER_COMMIT_SHA = "_writer_commit_sha"
  # A historian-response repaired-section field.
  REPAIRED_HISTORY_SECTION = "repaired_history_section"
  # A barrier-collect summary section-commits field.
  SECTION_COMMITS = "section_commits"
  # A validator-barrier summary new-validation-round field.
  NEW_VALIDATION_ROUND = "new_validation_round"
  # A retired decision summary commit-sha field that no code sets or reads.
  DECISION_COMMIT_SHA = "decision_commit_sha"
  # A consume-pass summary history-pickup field.
  HISTORY_PICKUP = "history_pickup"
  # A class-config frontmatter-key-list field for job-context resolution.
  CONTEXT_FROM_FRONTMATTER = "context_from_frontmatter"
  # A tick-summary non-fatal-warnings-list field.
  WARNINGS = "warnings"


# ----------------------------------------------------------------------------------------
class Tag:
  """
  Obsidian tag prefixes compared as string prefixes.

  Attributes:
    EXPERT_PREFIX: The ownership-tag prefix `#expert/`.
    REVIEW_PREFIX: The system-callout tag prefix `#review/`.
    PROTECTED_PREFIX: The cross-plugin persistent-owner tag prefix `#protected/`.
    HISTORY: The persistent ownership tag of the `# History` section.
  """

  # The ownership-tag prefix `#expert/`.
  EXPERT_PREFIX = "#expert/"
  # The system-callout tag prefix `#review/`.
  REVIEW_PREFIX = "#review/"
  # The cross-plugin persistent-owner tag prefix `#protected/`.
  PROTECTED_PREFIX = "#protected/"
  # The persistent ownership tag of the `# History` section.
  HISTORY = "#protected/review/history"


# ----------------------------------------------------------------------------------------
class JobFile:
  """
  Job-dir filenames and subdirectory names.

  Attributes:
    REQUEST: The per-job request payload filename.
    RESPONSE: The per-job response payload filename.
    EXPERTS_DIR: The per-repo experts root directory name.
    JOBS_DIR: The job-queue subdirectory name.
    DEAD: The job-dir terminal-failure marker filename.
    DONE: The job-dir completion marker filename.
    CANCELLED: The job-dir cancellation marker filename.
  """

  # The per-job request payload filename.
  REQUEST = "request.json"
  # The per-job response payload filename.
  RESPONSE = "response.json"
  # The per-repo experts root directory name.
  EXPERTS_DIR = ".experts"
  # The job-queue subdirectory name.
  JOBS_DIR = ".jobs"
  # The job-dir terminal-failure marker filename.
  DEAD = "DEAD"
  # The job-dir completion marker filename.
  DONE = "DONE"
  # The job-dir cancellation marker filename.
  CANCELLED = "CANCELLED"


# ----------------------------------------------------------------------------------------
class JobStatus:
  """
  Job-lifecycle status value tokens compared as strings.

  Attributes:
    PENDING: A job that has been queued but not yet picked up.
    DISPATCHED: A job that has been handed to the runtime for execution.
    DONE: A job that completed and whose result is available.
    DEAD: A job that terminated in failure.
    CANCELLED: A job that was cancelled before completing.
  """

  # A job that has been queued but not yet picked up.
  PENDING = "pending"
  # A job that has been handed to the runtime for execution.
  DISPATCHED = "dispatched"
  # A job that completed and whose result is available.
  DONE = "done"
  # A job that terminated in failure.
  DEAD = "dead"
  # A job that was cancelled before completing.
  CANCELLED = "cancelled"


# ----------------------------------------------------------------------------------------
class Position:
  """
  Section-writer placement value tokens compared as strings.

  Attributes:
    TOP: The owned section is placed before the operator's free body.
    BOTTOM: The owned section is placed after the operator's free body.
  """

  # The owned section is placed before the operator's free body.
  TOP = "top"
  # The owned section is placed after the operator's free body.
  BOTTOM = "bottom"


# ----------------------------------------------------------------------------------------
class Bucket:
  """
  Writer-group / barrier-phase value tokens compared as strings.

  These name the structural classification of a writer (the config umbrella it sits under) and
  the post-approve barrier phase the document is in. Distinct from `Phase` (pipeline phase) and
  `Outcome` (per-job result).

  Attributes:
    VALIDATION: The validation-umbrella writer group key.
    TERMINAL: The terminal-umbrella writer group key.
    VALIDATORS: The validator barrier phase / waiting-context label.
    TERMINALS: The terminal barrier phase / waiting-context label.
    WRITER: The main-writer waiting-context label.
    AWAITING_OPERATOR: The post-main-round `review_phase` awaiting an operator gesture.
  """

  # The validation-umbrella writer group key.
  VALIDATION = "validation"
  # The terminal-umbrella writer group key.
  TERMINAL = "terminal"
  # The validator barrier phase / waiting-context label.
  VALIDATORS = "validators"
  # The terminal barrier phase / waiting-context label.
  TERMINALS = "terminals"
  # The main-writer waiting-context label.
  WRITER = "writer"
  # The post-main-round `review_phase` awaiting an operator gesture.
  AWAITING_OPERATOR = "awaiting-operator"


# ----------------------------------------------------------------------------------------
class ResultValue:
  """
  Terminal `review_result` apply-gate discriminator value tokens compared as strings.

  Attributes:
    APPROVED: The document was approved and finalized cleanly.
    APPROVED_WITH_CONCERNS: The document was finalized with outstanding concerns accepted.
  """

  # The document was approved and finalized cleanly.
  APPROVED = "approved"
  # The document was finalized with outstanding concerns accepted.
  APPROVED_WITH_CONCERNS = "approved-with-concerns"


# ----------------------------------------------------------------------------------------
class CommitterKind:
  """
  Last-contentful-commit author classification value tokens compared as strings.

  Attributes:
    HUMAN: An operator commit (no `Doc-Review-Phase` trailer, non-bot identity).
    EXPERT: A writer commit carrying a `Doc-Review-Phase` trailer.
    FINAL: A finalize commit.
    BOT: A mechanical / historian bot commit.
  """

  # An operator commit (no `Doc-Review-Phase` trailer, non-bot identity).
  HUMAN = "human"
  # A writer commit carrying a `Doc-Review-Phase` trailer.
  EXPERT = "expert"
  # A finalize commit.
  FINAL = "final"
  # A mechanical / historian bot commit.
  BOT = "bot"


# ----------------------------------------------------------------------------------------
class Trailer:
  """
  Git commit-trailer key names compared as strings.

  Attributes:
    PHASE: The `Doc-Review-Phase` trailer key carried by every review-loop commit.
  """

  # The `Doc-Review-Phase` trailer key carried by every review-loop commit.
  PHASE = "Doc-Review-Phase"


# ----------------------------------------------------------------------------------------
class Style:
  """
  Edit-marker annotation-style value tokens compared as strings.

  Attributes:
    SIMPLE: The default edit-marker style assumed when no `review.edit_marker_style` is configured.
  """

  # The default edit-marker style assumed when no `review.edit_marker_style` is configured.
  SIMPLE = "simple"


# ----------------------------------------------------------------------------------------
class Paths:
  """
  Repo-relative filesystem path components compared as strings.

  Attributes:
    CLAUDE_DIR: The per-repo `.claude` configuration directory name.
    SETTINGS_FILE: The `lazy.settings.json` configuration filename.
    GIT_DIR: The `.git` directory name used as a repo-root marker / walk-skip entry.
    BIN_DIR: The plugin `bin` directory name used for CLI binary resolution.
    RUNTIME_DIR: The per-repo gitignored runtime-state directory name.
    JOBS_SIDECAR: The job-marker sidecar filename inside `RUNTIME_DIR`.
  """

  # The per-repo `.claude` configuration directory name.
  CLAUDE_DIR = ".claude"
  # The `lazy.settings.json` configuration filename.
  SETTINGS_FILE = "lazy.settings.json"
  # The `.git` directory name used as a repo-root marker / walk-skip entry.
  GIT_DIR = ".git"
  # The plugin `bin` directory name used for CLI binary resolution.
  BIN_DIR = "bin"
  # The per-repo gitignored runtime-state directory name.
  RUNTIME_DIR = ".runtime"
  # The job-marker sidecar filename inside `RUNTIME_DIR`.
  JOBS_SIDECAR = "lazy-review.jobs.json"


# ----------------------------------------------------------------------------------------
class EnvVar:
  """
  Environment-variable names compared as strings.

  Attributes:
    LAZY_REPO_ROOT: The expert-runtime repo-root environment variable.
  """

  # The expert-runtime repo-root environment variable.
  LAZY_REPO_ROOT = "LAZY_REPO_ROOT"


# ----------------------------------------------------------------------------------------
class Plugin:
  """
  Sibling-plugin identifier value tokens compared as strings.

  Attributes:
    CORE: The `lazycortex-core` plugin name used for CLI / cache binary resolution.
  """

  # The `lazycortex-core` plugin name used for CLI / cache binary resolution.
  CORE = "lazycortex-core"


# ----------------------------------------------------------------------------------------
class CoreCommand:
  """
  `lazycortex-core` CLI subcommand value tokens compared as strings.

  Attributes:
    DISPATCH_JOB: Queue a new expert job.
    LOOKUP_EXPERT: Resolve an expert entry by name.
    COLLECT_JOB: Collect a completed job's result.
    CONSUME_JOB: Mark a collected job consumed.
  """

  # Queue a new expert job.
  DISPATCH_JOB = "dispatch-job"
  # Resolve an expert entry by name.
  LOOKUP_EXPERT = "lookup-expert"
  # Collect a completed job's result.
  COLLECT_JOB = "collect-job"
  # Mark a collected job consumed.
  CONSUME_JOB = "consume-job"


# ----------------------------------------------------------------------------------------
class Role:
  """
  Expert role / name value tokens compared as strings.

  Attributes:
    HISTORIAN: The history-writer expert role.
    DOC_DOCTOR: The structural-repair expert default name.
  """

  # The history-writer expert role.
  HISTORIAN = "historian"
  # The structural-repair expert default name.
  DOC_DOCTOR = "doc_doctor"


# ----------------------------------------------------------------------------------------
class ErrorCause:
  """
  Error-ledger `cause` value tokens compared as strings.

  Attributes:
    LOGICAL: A writer logical-error cause (the writer cannot proceed on the section).
  """

  # A writer logical-error cause (the writer cannot proceed on the section).
  LOGICAL = "logical"


# ----------------------------------------------------------------------------------------
class Kind:
  """
  Request-bundle `kind` value tokens compared as strings.

  Attributes:
    REVIEW: The review-loop request kind.
  """

  # The review-loop request kind.
  REVIEW = "review"


# ----------------------------------------------------------------------------------------
class BotIdentity:
  """
  The review-bot git-author identity value tokens compared as strings.

  Attributes:
    NAME: The mechanical-commit author name.
    EMAIL: The mechanical-commit author email fallback.
  """

  # The mechanical-commit author name.
  NAME = "lazy-review"
  # The mechanical-commit author email fallback.
  EMAIL = "lazy-review@bot.invalid"
