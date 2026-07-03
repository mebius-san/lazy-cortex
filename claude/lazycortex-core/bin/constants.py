"""
Centralized string-literal constants for the lazycortex-core runtime.

The daemon, pump, routine taxonomy, recovery primitives, and the lifecycle
hooks all read and write a fixed vocabulary of dict keys, marker filenames,
and settings-section names. Defining each one here once means a mistyped key
surfaces as an `AttributeError` at import time rather than as silent state
corruption in the running loop.

Every value is a plain `str` (byte-identical to the literal it replaces), not
an `enum.Enum` member — these tokens are compared against parsed JSON/dict
strings and used as path segments, so they must stay `str`-typed to keep
those comparisons working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class StateKey:
  """
  Top-level keys in the daemon's persisted `state.json`.

  Attributes:
    DAEMON_HALTED: The optional halt-reason block written when the daemon stops.
    GIT_WATCH: The per-`git`-watch baseline-SHA tracking sub-map.
    LAST_RUN: The per-routine last-successful-run timestamp sub-map.
    LAST_SEEN_SHA: The per-watch baseline SHA stored inside a `git_watch` entry.
    WORKTREE_TASKS: The worktree-task registry sub-map.
    LAST_CLEANUP_AT: The wall-clock timestamp of the last housekeeping pass.
  """

  DAEMON_HALTED = "daemon_halted"
  GIT_WATCH = "git_watch"
  LAST_RUN = "last_run"
  LAST_SEEN_SHA = "last_seen_sha"
  WORKTREE_TASKS = "worktree_tasks"
  LAST_CLEANUP_AT = "last_cleanup_at"


# ----------------------------------------------------------------------------------------
class JobMarker:
  """
  Marker filenames that encode a job bundle's lifecycle state on disk.

  Attributes:
    READY: Atomic activation marker — the bundle is complete and may be spawned.
    DONE: Producer-side terminal marker — the pump finished processing the job.
    DEAD: Marker for a job whose claimant process died before producing output.
    CONSUMED: Consumer-side marker — whoever read the response is finished with it.
    PID: Holds the OS process id of the pump worker that claimed the job.
  """

  READY = "READY"
  DONE = "DONE"
  DEAD = "DEAD"
  CONSUMED = "CONSUMED"
  PID = "PID"


# ----------------------------------------------------------------------------------------
class JobFile:
  """
  Data filenames inside a job bundle directory.

  Attributes:
    REQUEST: The JSON request payload the expert reads.
    RESPONSE: The JSON outcome the expert writes.
    CONFIG: The per-job config snapshot the pump reads at spawn time.
  """

  REQUEST = "request.json"
  RESPONSE = "response.json"
  CONFIG = "config.json"


# ----------------------------------------------------------------------------------------
class PluginFile:
  """
  Filenames and directory names in a plugin's source layout.

  Attributes:
    MANIFEST: The plugin manifest filename.
    MANIFEST_DIR: The directory that holds the plugin manifest.
    NAME: The plugin-scope key inside the manifest payload.
    VERSION: The version key inside the manifest payload.
  """

  MANIFEST = "plugin.json"
  MANIFEST_DIR = ".claude-plugin"
  NAME = "name"
  VERSION = "version"


# ----------------------------------------------------------------------------------------
class RepoDir:
  """
  Repository-relative directory names owned by the expert runtime.

  Attributes:
    EXPERTS: The root of the per-repo expert work tree.
    JOBS: The job-queue subdirectory under the expert root.
    TAGS: The memory tag-index subdirectory.
    REMOTE_JOBS: The cross-repo remote-job tracker subdirectory.
  """

  EXPERTS = ".experts"
  JOBS = ".jobs"
  TAGS = ".tags"
  REMOTE_JOBS = ".remote-jobs"


# ----------------------------------------------------------------------------------------
class RoutineKey:
  """
  Keys in a single `routines.<name>` configuration block.

  Attributes:
    NAME: The routine's registered name.
    TYPE: The routine type discriminator (`subprocess`, `git`, `md-scan`, ...).
    COMMAND: The subprocess command vector for the `command` dispatch shape.
    EXPERT: The expert name for the `expert + request` dispatch shape.
    INTERVAL_SEC: The minimum seconds between interval-based ticks.
    TIMEOUT_SEC: The per-tick subprocess timeout in seconds.
    PRIORITY: The ascending per-tick execution-order key.
    PROTOCOLS: The list of protocol identifiers declared by the routine.
    BRANCH: The watched branch for a `git` routine.
    IGNORE_HALT: The flag letting a routine tick even while the daemon is halted.
    ISOLATE: The flag routing a routine's work through an isolated worktree.
  """

  NAME = "name"
  TYPE = "type"
  COMMAND = "command"
  EXPERT = "expert"
  INTERVAL_SEC = "interval_sec"
  TIMEOUT_SEC = "timeout_sec"
  PRIORITY = "priority"
  PROTOCOLS = "protocols"
  BRANCH = "branch"
  IGNORE_HALT = "ignore_halt"
  ISOLATE = "isolate"


# ----------------------------------------------------------------------------------------
class DaemonKey:
  """
  Keys in the `daemon` configuration section of `lazy.settings.json`.

  Attributes:
    METRICS: The metrics sub-configuration block.
    ENABLED: The on/off flag inside a sub-block.
    DAEMON_NAME: The daemon-identifier label for metrics.
    BIND: The metrics endpoint bind address.
    PORT: The metrics endpoint TCP port.
    LOOP_DETECT_THRESHOLD: The repeated-identical-tick halt threshold.
    ERRORS: The error-ledger sub-configuration block.
    RETENTION_DAYS: The journal-retention window in days.
    GIT: The git-integration sub-configuration block.
    CLEANUP_RUNTIME_LOG_AFTER: The runtime-log retention window.
    POLLING_INTERVAL_SEC: The main-loop polling cadence in seconds.
  """

  METRICS = "metrics"
  ENABLED = "enabled"
  DAEMON_NAME = "daemon_name"
  BIND = "bind"
  PORT = "port"
  LOOP_DETECT_THRESHOLD = "loop_detect_threshold"
  ERRORS = "errors"
  RETENTION_DAYS = "retention_days"
  GIT = "git"
  CLEANUP_RUNTIME_LOG_AFTER = "cleanup_runtime_log_after"
  POLLING_INTERVAL_SEC = "polling_interval_sec"


# ----------------------------------------------------------------------------------------
class GitConfigKey:
  """
  Keys in the `daemon.git` integration sub-configuration block.

  Attributes:
    BASE_BRANCH: The integration base branch.
    WORKTREE_ROOT: The directory isolated task worktrees are created under.
    MAX_CONCURRENT_TASKS: The concurrency cap on isolated worktree tasks.
    REMOTE_SYNC: The remote-sync mode (`pull`, `pull_push`, or off).
  """

  BASE_BRANCH = "base_branch"
  WORKTREE_ROOT = "worktree_root"
  MAX_CONCURRENT_TASKS = "max_concurrent_tasks"
  REMOTE_SYNC = "remote_sync"


# ----------------------------------------------------------------------------------------
class JobConfigKey:
  """
  Keys in a job bundle's `config.json` snapshot.

  Attributes:
    AGENT: The agent dispatch reference the pump spawns.
    PROTOCOLS: The resolved protocol references for the spawn.
    ASPECTS: The resolved aspect references for the spawn.
    ARGUMENTS: The routine-supplied keyword arguments for the expert.
    GIT_AUTHOR: The git identity block for any commits the expert makes.
    MODEL: The model tier pin, or unset to inherit the CLI default.
    MCP_CONFIG: Explicit MCP-config path(s) the spawn loads under strict mode, or unset for none.
  """

  AGENT = "agent"
  PROTOCOLS = "protocols"
  ASPECTS = "aspects"
  ARGUMENTS = "arguments"
  GIT_AUTHOR = "git_author"
  MODEL = "model"
  CAN_COMMIT_IN_REPO = "can_commit_in_repo"
  MCP_CONFIG = "mcp_config"


# ----------------------------------------------------------------------------------------
class SettingsKey:
  """
  Section names and the per-section version key in `lazy.settings.json`.

  Attributes:
    VERSION: The per-section schema-version sentinel key.
    DAEMON: The daemon configuration section name.
    ROUTINES: The routine registry section name.
    EXPERTS: The expert registry section name.
    AGENT_MODELS: The agent-model-tier registry section name.
    REPOS: The cross-repo target registry section name.
    LEGACY_VERSION: The pre-split root-level version key migrations fold away.
  """

  VERSION = "_version"
  DAEMON = "daemon"
  ROUTINES = "routines"
  EXPERTS = "experts"
  AGENT_MODELS = "agent_models"
  REPOS = "repos"
  LEGACY_VERSION = "version"


# ----------------------------------------------------------------------------------------
class RepoEntryKey:
  """
  Keys in a single `repos.<key>` cross-repo registry entry.

  Attributes:
    PATH: The filesystem path to the target repository.
  """

  PATH = "path"


# ----------------------------------------------------------------------------------------
class MemoryFrontmatterKey:
  """
  Required frontmatter keys in a persona-memory note.

  Attributes:
    TITLE: The note's human-facing title.
    TAGS: The list of `memory/`-prefixed topic tags.
    TYPE: The note's closed-set kind discriminator.
    SUMMARY: The one-line note summary.
  """

  TITLE = "title"
  TAGS = "tags"
  TYPE = "type"
  SUMMARY = "summary"


# ----------------------------------------------------------------------------------------
class IncidentKey:
  """
  Keys an error-ledger caller fills in the event dict it records.

  Attributes:
    INCIDENT: The stable incident-folding key.
    KIND: The closed-set event kind.
    CAUSE: The closed-set cause string.
    SEVERITY: The event severity.
    EXPERT: The owning expert name, when the incident is job-scoped.
    ROUTINE: The owning routine name, when the incident is routine-scoped.
  """

  INCIDENT = "incident"
  KIND = "kind"
  CAUSE = "cause"
  SEVERITY = "severity"
  EXPERT = "expert"
  ROUTINE = "routine"
  PHASE = "phase"
  ACTOR = "actor"
  JOB_ID = "job_id"
  DETAIL = "detail"
  REFS = "refs"
  STATE = "state"


# ----------------------------------------------------------------------------------------
class HookKey:
  """
  Keys in a Claude Code lifecycle-hook stdin payload.

  Attributes:
    TOOL_NAME: The tool identifier the hook fired for.
    TOOL_INPUT: The tool's input payload.
    HOOK_EVENT_NAME: The lifecycle event name (`PreToolUse`, `Stop`, ...).
    CWD: The working directory the hook payload reports.
  """

  TOOL_NAME = "tool_name"
  TOOL_INPUT = "tool_input"
  HOOK_EVENT_NAME = "hook_event_name"
  CWD = "cwd"


# ----------------------------------------------------------------------------------------
class ToolName:
  """
  Claude Code built-in tool identifiers the hooks match against.

  Attributes:
    AGENT: The subagent-dispatch tool.
  """

  AGENT = "Agent"


# ----------------------------------------------------------------------------------------
class AgentToolInput:
  """
  Keys the model-router reads and writes in an `Agent` tool-input payload.

  Attributes:
    MODEL: The model-tier field the router pins on a subagent spawn.
    SUBAGENT_TYPE: The dispatched subagent's registered name.
  """

  MODEL = "model"
  SUBAGENT_TYPE = "subagent_type"


# ----------------------------------------------------------------------------------------
class IncidentPhase:
  """
  Phase value tokens stored on an error-ledger event's `phase` field.

  Attributes:
    OPENED: The phase of the first event that opens an incident.
    TRIAGED: The phase of a triage event that classifies an open incident.
  """

  OPENED = "opened"
  TRIAGED = "triaged"


# ----------------------------------------------------------------------------------------
class IncidentKind:
  """
  Closed-set `kind` value tokens core-internal callers record on incidents.

  Attributes:
    JOB_DEAD: A job whose claimant process died before producing output.
    JOB_ERROR: A job that completed with an error outcome.
    ROUTINE_ERROR: A routine tick that failed.
    DAEMON_HALT: A daemon-wide halt block.
    DAEMON_ERROR: An unexpected daemon-loop exception.
    WORKTREE_TASK_ERROR: A worktree-task lifecycle failure.
  """

  JOB_DEAD = "job_dead"
  JOB_ERROR = "job_error"
  ROUTINE_ERROR = "routine_error"
  DAEMON_HALT = "daemon_halt"
  DAEMON_ERROR = "daemon_error"
  WORKTREE_TASK_ERROR = "worktree_task_error"


# ----------------------------------------------------------------------------------------
class IncidentActor:
  """
  `actor` value tokens naming which subsystem recorded an incident event.

  Attributes:
    DAEMON: The runtime daemon loop itself.
    PUMP: The expert-job pump.
    DOCTOR: The recovery doctor primitives.
    RECOVER: The halt-recovery primitives.
  """

  DAEMON = "daemon"
  PUMP = "pump"
  DOCTOR = "doctor"
  RECOVER = "recover"


# ----------------------------------------------------------------------------------------
class IncidentResolution:
  """
  `resolution` value tokens a recovery primitive folds onto a halt incident.

  Attributes:
    RESUMED: The halt was cleared by resuming the daemon on a clean tree.
    REVERTED: The halt was cleared by reverting the dirty paths to HEAD.
  """

  RESUMED = "resumed"
  REVERTED = "reverted"


# ----------------------------------------------------------------------------------------
class RecoverMode:
  """
  Cleanup-mode value tokens the halt-recovery `cleanup` primitive accepts.

  Attributes:
    COMMIT: Stage and commit the dirty tree with an operator-supplied message.
    STASH: Push the dirty tree (including untracked) onto the stash.
    DISCARD: Revert tracked changes and remove untracked files.
    ABORT: A no-op shape that leaves the tree untouched.
    MANUAL_FIX: A no-op shape signalling the operator will fix the tree by hand.
  """

  COMMIT = "commit"
  STASH = "stash"
  DISCARD = "discard"
  ABORT = "abort"
  MANUAL_FIX = "manual-fix"


# ----------------------------------------------------------------------------------------
class IncidentState:
  """
  Folded incident-state value tokens a caller filters error-ledger reads by.

  Attributes:
    OPEN: An incident with no terminal resolution yet.
    NEEDS_OPERATOR: An incident escalated for manual operator action.
    ALL: The wildcard selector matching every state.
  """

  OPEN = "open"
  NEEDS_OPERATOR = "needs_operator"
  ALL = "all"


# ----------------------------------------------------------------------------------------
class HaltKey:
  """
  Keys in the daemon's `daemon_halted` block stored in `state.json`.

  Attributes:
    HALTED_SINCE: The wall-clock timestamp at which the halt was raised.
    TRIGGERED_BY: The routine or subsystem name that triggered the halt.
    REASON: The closed-set halt-reason code.
    DIRTY_PATHS: The repository-relative paths reported dirty at halt time.
  """

  HALTED_SINCE = "halted_since"
  TRIGGERED_BY = "triggered_by"
  REASON = "reason"
  DIRTY_PATHS = "dirty_paths"


# ----------------------------------------------------------------------------------------
class HaltReason:
  """
  Closed-set `reason` value tokens written into a `daemon_halted` block.

  Attributes:
    UNCOMMITTED_CHANGES: An expert or routine left the working tree dirty.
    SUSPECTED_LOOP: The loop detector tripped on repeated identical ticks.
    GIT_PULL_DIVERGED: A pre-tick pull found diverged history.
    GIT_PUSH_FAILED: A post-tick push could not complete.
    GIT_REMOTE_UNAVAILABLE: The git remote could not be reached.
  """

  UNCOMMITTED_CHANGES = "uncommitted_changes"
  SUSPECTED_LOOP = "suspected_loop"
  GIT_PULL_DIVERGED = "git_pull_diverged"
  GIT_PUSH_FAILED = "git_push_failed"
  GIT_REMOTE_UNAVAILABLE = "git_remote_unavailable"


# ----------------------------------------------------------------------------------------
class SettingsFile:
  """
  Repository-relative path of the tracked runtime settings file.

  Attributes:
    REL: The repo-relative location of `lazy.settings.json`.
  """

  REL = ".claude/lazy.settings.json"


# ----------------------------------------------------------------------------------------
class RuntimeFile:
  """
  Repository-relative paths of daemon-owned files under the `.runtime/` directory.

  Attributes:
    SANDBOX_SETTINGS: The Claude Code settings file that confines expert spawns to the sandbox scope.
  """

  SANDBOX_SETTINGS = ".runtime/sandbox.settings.json"


# ----------------------------------------------------------------------------------------
class JobArtifact:
  """
  Per-attempt forensic filenames written inside a job bundle directory.

  Attributes:
    DEAD_JSON: The forensic payload describing a job marked dead.
    DIAGNOSIS_JSON: The doctor's diagnosis written when a job is permanently failed.
    ATTEMPTS: The cumulative attempt-counter file.
    TRANSCRIPT: The captured stream-json transcript of the expert spawn.
    ERROR_JSON: The legacy per-attempt error payload cleared on retry.
  """

  DEAD_JSON = "dead.json"
  DIAGNOSIS_JSON = "diagnosis.json"
  ATTEMPTS = "attempts"
  TRANSCRIPT = "transcript.jsonl"
  ERROR_JSON = "error.json"


# ----------------------------------------------------------------------------------------
class JobIODir:
  """
  Auxiliary work-file subdirectory names inside a job bundle directory.

  Attributes:
    SOURCE: The read-only input files the expert consumes.
    CONTEXT: The optional supplementary context files.
    RESULT: The directory the expert writes its output files into.
  """

  SOURCE = "source"
  CONTEXT = "context"
  RESULT = "result"


# ----------------------------------------------------------------------------------------
class JobRequestKey:
  """
  Reserved keys the runtime injects into a job's `request.json` payload.

  Attributes:
    DEDUP_KEY: The optional dedup marker that suppresses duplicate dispatches.
  """

  DEDUP_KEY = "_dedup_key"


# ----------------------------------------------------------------------------------------
class JobResponseKey:
  """
  Keys in a job's `response.json` outcome payload.

  Attributes:
    OUTCOME: The terminal outcome discriminator the expert writes.
    ERROR: The error sub-object present when the outcome is an error.
    CATEGORY: The error category label inside the error sub-object.
    MESSAGE: The human-readable error message inside the error sub-object.
  """

  OUTCOME = "outcome"
  ERROR = "error"
  CATEGORY = "category"
  MESSAGE = "message"


# ----------------------------------------------------------------------------------------
class JobErrorCategory:
  """
  `category` value tokens the pump writes inside a job error payload.

  Attributes:
    LOGICAL: A config-level fault the pump can attribute deterministically.
    TRANSIENT: A spawn-level fault that may succeed on a later retry.
    UNCOMMITTED_CHANGES: A clean exit that left the working tree dirty.
  """

  LOGICAL = "logical"
  TRANSIENT = "transient"
  UNCOMMITTED_CHANGES = "uncommitted_changes"


# ----------------------------------------------------------------------------------------
class JobOutcome:
  """
  `outcome` value tokens compared against a `response.json` payload.

  Attributes:
    ERROR: The outcome value marking a job that failed.
  """

  ERROR = "error"


# ----------------------------------------------------------------------------------------
class JobCollectKey:
  """
  Keys in the descriptor dicts that job-collect and job-list return.

  Attributes:
    STATUS: The job's classified lifecycle status.
    RESPONSE: The parsed `response.json` payload carried on a finished job.
    EXPERT: The owning expert name.
    JOB_ID: The job identifier within the expert's queue.
    PATH: The absolute job-directory path.
    TARGET_REPO: The label of the foreign repo for a remote tracker entry.
    DISPATCHED_AT: The dispatch timestamp carried on a remote tracker entry.
    DEDUP_KEY: The dedup key carried on a reconcilable finished-job entry.
  """

  STATUS = "status"
  RESPONSE = "response"
  EXPERT = "expert"
  JOB_ID = "job_id"
  PATH = "path"
  TARGET_REPO = "target_repo"
  DISPATCHED_AT = "dispatched_at"
  DEDUP_KEY = "dedup_key"


# ----------------------------------------------------------------------------------------
class JobStatus:
  """
  Classified lifecycle status value tokens for a job bundle.

  Attributes:
    MISSING: The bundle directory does not exist.
    PENDING: The pump has not produced a terminal marker yet.
    QUEUED: The bundle is READY but not yet claimed (no PID).
    ACTIVE: The bundle is READY and claimed (PID present).
    DONE: The bundle finished without an error outcome.
    FAILED: The bundle finished with an error outcome.
    DEAD: The bundle carries a DEAD marker.
    ALREADY_QUEUED: Dispatch result token — a live bundle already owns the dedup key.
  """

  MISSING = "missing"
  PENDING = "pending"
  QUEUED = "queued"
  ACTIVE = "active"
  DONE = "done"
  FAILED = "failed"
  DEAD = "dead"
  ALREADY_QUEUED = "already-queued"


# ----------------------------------------------------------------------------------------
class RemoteTrackerKey:
  """
  Keys in a cross-repo remote-job visibility tracker payload.

  Attributes:
    TARGET_REPO: The label of the foreign repository the job runs in.
    ABS_PATH: The absolute path to the foreign job directory.
    DISPATCHED_AT: The dispatch timestamp.
  """

  TARGET_REPO = "target_repo"
  ABS_PATH = "abs_path"
  DISPATCHED_AT = "dispatched_at"


# ----------------------------------------------------------------------------------------
class TickResultKey:
  """
  Keys in a routine-tick result dict the daemon logs.

  Attributes:
    NAME: The routine name the tick ran for.
    EXIT: The tick exit code (`0` success, non-zero failure).
    DURATION_SEC: The wall-clock duration of the tick in seconds.
    NOTE: An optional non-error status note.
    ERROR: The failure message present when the tick failed.
    OUTCOME: The integration outcome carried on a worktree-finish tick.
    WORK_ID: The unit-of-work identifier carried on a worktree tick.
    BRANCH: The task branch name carried on a worktree tick.
  """

  NAME = "name"
  EXIT = "exit"
  DURATION_SEC = "duration_sec"
  NOTE = "note"
  ERROR = "error"
  OUTCOME = "outcome"
  WORK_ID = "work_id"
  BRANCH = "branch"


# ----------------------------------------------------------------------------------------
class WorktreeEntryKey:
  """
  Keys in a single worktree-task registry entry under `worktree_tasks`.

  Attributes:
    BRANCH: The task branch name.
    WORKTREE_PATH: The absolute path to the task's worktree directory.
    ROUTINE: The routine that originated the unit of work.
    ALLOW_MERGE: Whether completion auto-merges to base or opens a pull request.
    JOB_ID: The dispatched job id whose completion triggers integration.
    STARTED: The wall-clock timestamp at which the task was registered.
  """

  BRANCH = "branch"
  WORKTREE_PATH = "worktree_path"
  ROUTINE = "routine"
  ALLOW_MERGE = "allow_merge"
  JOB_ID = "job_id"
  STARTED = "started"


# ----------------------------------------------------------------------------------------
class WorktreeResultKey:
  """
  Keys in the integration-outcome dicts the worktree manager returns.

  Attributes:
    RESULT: The integration-outcome discriminator.
    BRANCH: The task branch name.
    WORK_ID: The unit-of-work identifier.
    REASON: The deferral cause carried on a deferred pull request.
  """

  RESULT = "result"
  BRANCH = "branch"
  WORK_ID = "work_id"
  REASON = "reason"


# ----------------------------------------------------------------------------------------
class MetricStateKey:
  """
  Keys in the metrics module's process-local registry dict.

  Attributes:
    INITIALIZED: Whether `init_metrics` has run.
    REPO: The repo label captured at init.
    VERSION: The plugin version captured at init.
    DAEMON_NAME: The daemon identifier captured at init.
    LOCK: The threading lock guarding metric mutations.
    TICKS: The routine-tick counter instrument.
    ERRORS: The routine-error counter instrument.
    TOKENS: The token-consumption counter instrument.
    DURATION: The tick-duration histogram instrument.
    LAST_TICK: The last-tick-timestamp gauge instrument.
    QUEUE_DEPTH: The expert-queue-depth gauge instrument.
    UP: The endpoint-up gauge instrument.
    DAEMON_HALTED: The daemon-halted gauge instrument.
    BUILD_INFO: The build-info gauge instrument.
    HALT_COUNT: The cumulative-halt counter instrument.
    TOKEN_OFFSET: The byte offset into the token log read so far.
    SERVER: The WSGI server object.
    SERVER_THREAD: The server's background thread.
  """

  INITIALIZED = "initialized"
  REPO = "repo"
  VERSION = "version"
  DAEMON_NAME = "daemon_name"
  LOCK = "lock"
  TICKS = "ticks"
  ERRORS = "errors"
  TOKENS = "tokens"
  DURATION = "duration"
  LAST_TICK = "last_tick"
  QUEUE_DEPTH = "queue_depth"
  UP = "up"
  DAEMON_HALTED = "daemon_halted"
  BUILD_INFO = "build_info"
  HALT_COUNT = "halt_count"
  TOKEN_OFFSET = "token_offset"
  SERVER = "server"
  SERVER_THREAD = "server_thread"


# ----------------------------------------------------------------------------------------
class MetricLabel:
  """
  Prometheus label names attached to runtime metric samples.

  These are the external metric-label vocabulary, distinct from any internal
  dict key that happens to share a spelling (e.g. a `repo` config key).

  Attributes:
    REPO: The repository label.
    ROUTINE: The routine-name label.
    STATUS: The tick-status label.
    REASON: The error-reason label.
    MODEL: The model-tier label.
    KIND: The token-kind label.
    VERSION: The plugin-version label.
    DAEMON_NAME: The daemon-identifier label.
  """

  REPO = "repo"
  ROUTINE = "routine"
  STATUS = "status"
  REASON = "reason"
  MODEL = "model"
  KIND = "kind"
  VERSION = "version"
  DAEMON_NAME = "daemon_name"


# ----------------------------------------------------------------------------------------
class WorktreeResult:
  """
  `result` value tokens for a worktree-task start or finish outcome.

  Attributes:
    MERGED: The task branch fast-forward merged into base.
    CONFLICT: The rebase or fast-forward merge conflicted.
    PR_OPENED: A pull request was opened for the task branch.
    PR_DEFERRED: The pull request could not be opened and was deferred.
    AT_CAPACITY: The concurrency cap blocked the start.
    UNKNOWN: The work id was not registered.
  """

  MERGED = "merged"
  CONFLICT = "conflict"
  PR_OPENED = "pr_opened"
  PR_DEFERRED = "pr_deferred"
  AT_CAPACITY = "at_capacity"
  UNKNOWN = "unknown"
