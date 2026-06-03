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
    MAIN_DONE: The bracketed list of main writers already run.
    EXPERT: A per-document main-writer override.
    VALIDATION_ROUND: The post-approve validation-barrier round counter.
    APPROVED_WITH_CONCERNS: The accept-concerns-and-finalize flag.
    PREFIX: The shared prefix of every review-lifecycle frontmatter key.
  """

  ACTIVE = "review_active"
  ROUND = "review_round"
  APPROVED = "review_approved"
  PHASE = "review_phase"
  RESULT = "review_result"
  MAIN_DONE = "review_main_done"
  EXPERT = "review_expert"
  VALIDATION_ROUND = "review_validation_round"
  APPROVED_WITH_CONCERNS = "review_approved_with_concerns"
  PREFIX = "review_"


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

  FAIL = "FAIL"
  WARN = "WARN"
  PASS = "PASS"
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

  MAIN = "main"
  SECTION = "section"
  MECHANICAL = "mechanical"
  FINALIZE = "finalize"
  HISTORY = "history"
  HISTORY_APPEND = "history:append"
  HISTORY_NOOP = "history:noop"
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

  SKIP = "skip"
  MISSING = "missing"
  EMPTY = "empty"
  NOOP = "noop"
  CONCERNS = "concerns"
  CONSUMED = "CONSUMED"
  REPAIR = "repair"
  EDITED = "edited"
  SUMMARIZED = "summarized"
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
    APPROVE_WITH_CONCERNS_MIRROR: Mirror the approve-with-concerns gesture into frontmatter.
    CONTINUE_REVIEW_MIRROR: Process the continue-review-cycle gesture.
    BANNER_REPAINT: Repaint the top banner to the desired state.
    RESET_APPROVAL: Reset approval and re-open the validator barrier.
    BARRIER_DISPATCH: Queue every pending writer of the active barrier at once.
    BARRIER_COLLECT: Sweep-collect the drained barrier in a single pass.
    REVERT_TO_MAIN: Revert a final-concerns document back to the main-writer round.
  """

  APPROVE_MIRROR = "approve-mirror"
  APPROVE_WITH_CONCERNS_MIRROR = "approve-with-concerns-mirror"
  CONTINUE_REVIEW_MIRROR = "continue-review-mirror"
  BANNER_REPAINT = "banner-repaint"
  RESET_APPROVAL = "reset-approval"
  BARRIER_DISPATCH = "barrier-dispatch"
  BARRIER_COLLECT = "barrier-collect"
  REVERT_TO_MAIN = "revert-to-main"


# ----------------------------------------------------------------------------------------
class JobKey:
  """
  Record / payload / config dict-key names compared as strings.

  Attributes:
    NAME: A writer / expert name field.
    EXPERTS: The experts catalog / group block.
    ERROR: An error-message field.
    COMMIT_SHA: A commit-SHA field.
    FILE: A file-path field.
    OUTCOME: A job-outcome field.
    RESULT: A result-payload field.
    STATUS: A status field.
    EMAIL: A git-author email field.
    EDIT_MARKER_STYLE: The configured edit-marker style key.
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
    DISPATCHED_FROM: The dispatch-origin repo field on a job bundle.
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
    REPOS: The top-level `repos` config block key.
    CLASS: A class-entry name field.
    PATHS: A class-entry paths-glob list field.
    CHECK: An audit-finding check-id field.
    LEVEL: An audit-bundle aggregate-level field.
    FINDINGS: An audit-bundle findings-list field.
    BANNER: A status-record banner-state field.
    OWNERS: A status-record section-owners list field.
    OWNER: A status-record section-owner field.
    SECTION: A status-record / writer section-title field.
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
    CONCERNS_DECISION_THRESHOLD: The per-class concerns-pause round-threshold config key.
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
    DECISION_COMMIT_SHA: A concerns-decision summary commit-sha field.
    HISTORY_PICKUP: A consume-pass summary history-pickup field.
  """

  NAME = "name"
  EXPERTS = "experts"
  ERROR = "error"
  COMMIT_SHA = "commit_sha"
  FILE = "file"
  OUTCOME = "outcome"
  RESULT = "result"
  STATUS = "status"
  EMAIL = "email"
  EDIT_MARKER_STYLE = "edit_marker_style"
  OPERATOR_COMMIT_SHA = "operator_commit_sha"
  OPERATOR_SHA_AT_DISPATCH = "_operator_sha_at_dispatch"
  VERSION = "_version"
  KIND = "kind"
  INCIDENT = "incident"
  SEVERITY = "severity"
  AGENT = "agent"
  GIT_AUTHOR = "git_author"
  COMMAND = "command"
  HISTORY_ENTRY = "history_entry"
  PAYLOAD = "payload"
  SOURCE = "source"
  CONTEXT = "context"
  PATH = "path"
  DEDUP_KEY = "dedup_key"
  PROTOCOLS = "protocols"
  DISPATCHED_FROM = "dispatched_from"
  ROLE = "role"
  MODE = "mode"
  ROUND = "round"
  JOB_ID = "job_id"
  JOBS = "jobs"
  PICKED_UP = "picked_up"
  RESPONSE = "response"
  TIMESTAMP = "timestamp"
  REASON = "reason"
  CATEGORY = "category"
  MESSAGE = "message"
  GROUP = "group"
  WRITER = "writer"
  POSITION = "position"
  FRONTMATTER = "frontmatter"
  ALLOW = "allow"
  REQUIRE = "require"
  CLASSES = "classes"
  REVIEW = "review"
  REPOS = "repos"
  CLASS = "class"
  PATHS = "paths"
  CHECK = "check"
  LEVEL = "level"
  FINDINGS = "findings"
  BANNER = "banner"
  OWNERS = "owners"
  OWNER = "owner"
  SECTION = "section"
  ACTIONS = "actions"
  STATE = "state"
  MARKER = "marker"
  TITLE = "title"
  BODY_LINES = "body_lines"
  META = "meta"
  TEXT = "text"
  BODY = "body"
  SECTION_H1_TITLE = "section_h1_title"
  CONTENT = "content"
  EXPERT = "expert"
  WAITING_CONTEXT = "waiting_context"
  TO_DISPATCH = "to_dispatch"
  OPEN = "open"
  READY = "ready"
  RESET = "reset"
  CLASS_CFG = "class_cfg"
  HISTORY = "history"
  APPROVED = "approved"
  LAST_COMMIT_IS_HUMAN = "last_commit_is_human"
  TARGET_FILE = "_target_file"
  WRITER_COMMIT_TIMESTAMP = "_writer_commit_timestamp"
  FILE_SNAPSHOT_HASH = "_file_snapshot_hash"
  DEDUP_TRACKER = "_dedup_key"
  CONCERNS_DECISION_THRESHOLD = "concerns_decision_threshold"
  DOC_DOCTOR = "doc_doctor"
  FOUND = "found"
  ENTRY = "entry"
  HISTORY_KICK = "history_kick"
  HISTORY_KICK_ERROR = "history_kick_error"
  DISPATCH_ERRORS = "dispatch_errors"
  DISPATCHED = "dispatched"
  NEW_REVIEW_ROUND = "new_review_round"
  CLEANUP_COMMIT_SHA = "cleanup_commit_sha"
  OWNERSHIP_VIOLATION = "ownership_violation"
  WRITER_COMMIT_SHA = "_writer_commit_sha"
  REPAIRED_HISTORY_SECTION = "repaired_history_section"
  SECTION_COMMITS = "section_commits"
  NEW_VALIDATION_ROUND = "new_validation_round"
  DECISION_COMMIT_SHA = "decision_commit_sha"
  HISTORY_PICKUP = "history_pickup"


# ----------------------------------------------------------------------------------------
class Tag:
  """
  Obsidian tag prefixes compared as string prefixes.

  Attributes:
    EXPERT_PREFIX: The ownership-tag prefix `#expert/`.
    REVIEW_PREFIX: The system-callout tag prefix `#review/`.
    PROTECTED_PREFIX: The cross-plugin persistent-owner tag prefix `#protected/`.
  """

  EXPERT_PREFIX = "#expert/"
  REVIEW_PREFIX = "#review/"
  PROTECTED_PREFIX = "#protected/"


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
    REMOTE_JOBS_DIR: The cross-repo dispatch-tracker root directory name.
  """

  REQUEST = "request.json"
  RESPONSE = "response.json"
  EXPERTS_DIR = ".experts"
  JOBS_DIR = ".jobs"
  DEAD = "DEAD"
  DONE = "DONE"
  REMOTE_JOBS_DIR = ".remote-jobs"


# ----------------------------------------------------------------------------------------
class JobStatus:
  """
  Job-lifecycle status value tokens compared as strings.

  Attributes:
    PENDING: A job that has been queued but not yet picked up.
    DISPATCHED: A job that has been handed to the runtime for execution.
    DONE: A job that completed and whose result is available.
    DEAD: A job that terminated in failure.
  """

  PENDING = "pending"
  DISPATCHED = "dispatched"
  DONE = "done"
  DEAD = "dead"


# ----------------------------------------------------------------------------------------
class Position:
  """
  Section-writer placement value tokens compared as strings.

  Attributes:
    TOP: The owned section is placed before the operator's free body.
    BOTTOM: The owned section is placed after the operator's free body.
  """

  TOP = "top"
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
    CONCERNS_PAUSE: The `review_phase` for the outstanding-concerns operator pause.
  """

  VALIDATION = "validation"
  TERMINAL = "terminal"
  VALIDATORS = "validators"
  TERMINALS = "terminals"
  WRITER = "writer"
  AWAITING_OPERATOR = "awaiting-operator"
  CONCERNS_PAUSE = "concerns-pause"


# ----------------------------------------------------------------------------------------
class ResultValue:
  """
  Terminal `review_result` apply-gate discriminator value tokens compared as strings.

  Attributes:
    APPROVED: The document was approved and finalized cleanly.
    APPROVED_WITH_CONCERNS: The document was finalized with outstanding concerns accepted.
  """

  APPROVED = "approved"
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

  HUMAN = "human"
  EXPERT = "expert"
  FINAL = "final"
  BOT = "bot"


# ----------------------------------------------------------------------------------------
class Trailer:
  """
  Git commit-trailer key names compared as strings.

  Attributes:
    PHASE: The `Doc-Review-Phase` trailer key carried by every review-loop commit.
  """

  PHASE = "Doc-Review-Phase"


# ----------------------------------------------------------------------------------------
class Style:
  """
  Edit-marker annotation-style value tokens compared as strings.

  Attributes:
    SIMPLE: The default edit-marker style assumed when no `review.edit_marker_style` is configured.
  """

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
    PLUGIN_CACHE: The Claude Code plugin-cache root, relative to the home directory.
  """

  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  GIT_DIR = ".git"
  BIN_DIR = "bin"
  PLUGIN_CACHE = ".claude/plugins/cache"


# ----------------------------------------------------------------------------------------
class EnvVar:
  """
  Environment-variable names compared as strings.

  Attributes:
    LAZY_REPO_ROOT: The expert-runtime repo-root environment variable.
  """

  LAZY_REPO_ROOT = "LAZY_REPO_ROOT"


# ----------------------------------------------------------------------------------------
class Plugin:
  """
  Sibling-plugin identifier value tokens compared as strings.

  Attributes:
    CORE: The `lazycortex-core` plugin name used for CLI / cache binary resolution.
  """

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

  DISPATCH_JOB = "dispatch-job"
  LOOKUP_EXPERT = "lookup-expert"
  COLLECT_JOB = "collect-job"
  CONSUME_JOB = "consume-job"


# ----------------------------------------------------------------------------------------
class Role:
  """
  Expert role / name value tokens compared as strings.

  Attributes:
    HISTORIAN: The history-writer expert role.
    DOC_DOCTOR: The structural-repair expert default name.
  """

  HISTORIAN = "historian"
  DOC_DOCTOR = "doc_doctor"


# ----------------------------------------------------------------------------------------
class ErrorCause:
  """
  Error-ledger `cause` value tokens compared as strings.

  Attributes:
    LOGICAL: A writer logical-error cause (the writer cannot proceed on the section).
  """

  LOGICAL = "logical"


# ----------------------------------------------------------------------------------------
class Kind:
  """
  Request-bundle `kind` value tokens compared as strings.

  Attributes:
    REVIEW: The review-loop request kind.
  """

  REVIEW = "review"


# ----------------------------------------------------------------------------------------
class BotIdentity:
  """
  The review-bot git-author identity value tokens compared as strings.

  Attributes:
    NAME: The mechanical-commit author name.
    EMAIL: The mechanical-commit author email fallback.
  """

  NAME = "lazy-review"
  EMAIL = "lazy-review@bot.invalid"
