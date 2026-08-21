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


# The canonical email domain for every automatic git identity (experts, routines, deterministic
# CLI bots). RFC 2606 reserves `.invalid`, so the address is undeliverable by construction, and
# consumers that classify commits by the `@bot.` substring recognise it as-is.
BOT_EMAIL_DOMAIN = "@bot.invalid"


# ----------------------------------------------------------------------------------------
class StateKey:
  """
  Top-level keys in the daemon's persisted `state.json`.

  Attributes:
    DAEMON_HALTED: The optional halt-reason block written when the daemon stops.
    GIT_WATCH: The per-`git`-watch baseline-SHA tracking sub-map.
    LAST_RUN: The per-routine last-successful-run timestamp sub-map.
    LAST_SEEN_SHA: The per-watch baseline SHA stored inside a `git_watch` entry.
    FAILED_ITEMS: The per-watch list of items whose `command`-shape worker exited non-zero,
      stored inside a `git_watch` entry; retried before fresh items on the next tick.
    LAST_CLEANUP_AT: The wall-clock timestamp of the last housekeeping pass.
  """

  DAEMON_HALTED = "daemon_halted"
  GIT_WATCH = "git_watch"
  LAST_RUN = "last_run"
  LAST_SEEN_SHA = "last_seen_sha"
  FAILED_ITEMS = "failed_items"
  LAST_CLEANUP_AT = "last_cleanup_at"


# ----------------------------------------------------------------------------------------
class JobMarker:
  """
  Marker filenames that encode a job bundle's lifecycle state on disk.

  Attributes:
    READY: Atomic activation marker — the bundle is complete and may be spawned.
    DONE: Producer-side terminal marker — the pump finished processing the job.
    DEAD: Marker for a job whose claimant process died before producing output.

    DEAD_CANDIDATE:
      Timestamped marker recording that a claimed job's claimant process appears dead.
      The dead-scan promotes it to `DEAD` only once it outlives a grace window with
      still no `response.json`.

    CONSUMED: Consumer-side marker — whoever read the response is finished with it.
    CANCELLED: Operator-side terminal marker — the job was cancelled; the bundle stays for forensics.
    PID: Holds the OS process id of the pump worker that claimed the job.
  """

  READY = "READY"
  DONE = "DONE"
  DEAD = "DEAD"
  DEAD_CANDIDATE = "DEAD_CANDIDATE"
  CONSUMED = "CONSUMED"
  CANCELLED = "CANCELLED"
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
  """

  EXPERTS = ".experts"
  JOBS = ".jobs"
  TAGS = ".tags"


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
    INBOX_DIR: The repo-relative directory an inbox routine scans.
    HOOKS_ENABLED: The allow-list of lazycortex hook short names the routine's own subprocess may
      run. Inert on the `expert` dispatch shape, whose session is spawned by the pump routine and
      therefore carries the pump's list.
    GIT_AUTHOR: The git identity block for any commits the routine's own subprocess makes.
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
  INBOX_DIR = "inbox_dir"
  HOOKS_ENABLED = "hooks_enabled"
  GIT_AUTHOR = "git_author"


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
    REPO_LABEL: The override for the `repo` metric label.
    LOOP_DETECT_THRESHOLD: The repeated-identical-tick halt threshold.
    ERRORS: The error-ledger sub-configuration block.
    RETENTION_DAYS: The journal-retention window in days.
    GIT: The git-integration sub-configuration block.
    CLEANUP_RUNTIME_LOG_AFTER: The runtime-log retention window.
    POLLING_INTERVAL_SEC: The main-loop polling cadence in seconds.
    STREAM_IDLE_TIMEOUT_SEC: Seconds of expert-spawn stdout silence before the watchdog re-spawns it.
    TRANSIENT_MAX_RETRIES: Transient-error budget per job bundle before the pump closes it.
    RUN_HERE: The hostname-to-checkout-path mapping deciding whether the daemon starts in this working copy.
    RATE_LIMIT_GUARD: The subscription-rate-limit guard sub-configuration block.
  """

  METRICS = "metrics"
  ENABLED = "enabled"
  DAEMON_NAME = "daemon_name"
  BIND = "bind"
  PORT = "port"
  REPO_LABEL = "repo_label"
  LOOP_DETECT_THRESHOLD = "loop_detect_threshold"
  ERRORS = "errors"
  RETENTION_DAYS = "retention_days"
  GIT = "git"
  CLEANUP_RUNTIME_LOG_AFTER = "cleanup_runtime_log_after"
  POLLING_INTERVAL_SEC = "polling_interval_sec"
  RUN_HERE = "run_here"
  RATE_LIMIT_GUARD = "rate_limit_guard"
  STREAM_IDLE_TIMEOUT_SEC = "stream_idle_timeout_sec"
  TRANSIENT_MAX_RETRIES = "transient_max_retries"


# ----------------------------------------------------------------------------------------
class RateLimitGuardKey:
  """
  Keys in the `daemon.rate_limit_guard` sub-configuration block.

  Attributes:
    ENABLED: The master on/off switch for the guard.
    ON_ALLOWED_WARNING: Whether a pre-exhaustion warning frame trips the guard.
    ON_REJECTED: Whether an already-closed window trips the guard.
    ON_OVERAGE: Whether spend having crossed into paid overage trips the guard.
    WARNING_UTILIZATION_THRESHOLD: Window utilization at or above which a warning frame trips
      the guard; a warning below it — or one carrying no utilization reading — never does.
  """

  ENABLED = "enabled"
  ON_ALLOWED_WARNING = "on_allowed_warning"
  ON_REJECTED = "on_rejected"
  ON_OVERAGE = "on_overage"
  WARNING_UTILIZATION_THRESHOLD = "warning_utilization_threshold"


# ----------------------------------------------------------------------------------------
class RateLimitTrigger:
  """
  Closed-set trigger tokens naming why the rate-limit flag was raised.

  The first two are byte-identical to the provider's own `status` values, so a frame's status
  is compared against them directly; `OVERAGE` has no status counterpart and is derived from
  the overage field instead.

  Attributes:
    ALLOWED_WARNING: The provider signalled the window is close to exhaustion.
    REJECTED: The provider refused the call because the window is closed.
    OVERAGE: The window was passed and spend continues as paid overage.
  """

  ALLOWED_WARNING = "allowed_warning"
  REJECTED = "rejected"
  OVERAGE = "overage"


# ----------------------------------------------------------------------------------------
class RateLimitRecordKey:
  """
  Keys in a per-window record file under the host-local rate-limit flag directory.

  Attributes:
    RESETS_AT: The epoch-second timestamp at which this window reopens.
    STATUS: The provider status token carried by the frame that raised the record.
    IS_USING_OVERAGE: Whether the frame reported spend already running as paid overage.
    TRIGGER: The closed-set trigger token that raised the record.
    WRITER: The label of the process that wrote the record.
    WRITTEN_AT: The epoch-second timestamp at which the record was written.
  """

  RESETS_AT = "resets_at"
  STATUS = "status"
  IS_USING_OVERAGE = "is_using_overage"
  TRIGGER = "trigger"
  WRITER = "writer"
  WRITTEN_AT = "written_at"


# ----------------------------------------------------------------------------------------
class MetricsNet:
  """
  Network-level constants for the daemon's Prometheus metrics endpoint.

  Attributes:
    PORT_BASE: The first port considered when allocating a metrics port for a daemon.
    PORT_CEIL: The last port considered; the allocation range is `PORT_BASE..PORT_CEIL` inclusive.
    SCRAPE_TARGETS_REL: The scrape-targets file location relative to the XDG config home.
  """

  PORT_BASE = 9464
  PORT_CEIL = 9563
  # waiver: filesystem path idiom relative to XDG config home, not an internal key
  SCRAPE_TARGETS_REL = "lazycortex/scrape-targets.json"


# ----------------------------------------------------------------------------------------
class GitConfigKey:
  """
  Keys in the `daemon.git` integration sub-configuration block.

  Attributes:
    BASE_BRANCH: The integration base branch.
    WORKTREE_ROOT: The directory isolated job worktrees are created under.
    WORKTREE_BOOTSTRAP_CMD: The shell command run in a fresh job worktree before the spawn.
    REMOTE_SYNC: The remote-sync mode (`pull`, `pull_push`, or off).
    POST_PUSH_HOOK: The operator shell command run after each push that advances origin.
    POST_PUSH_TIMEOUT_SEC: The wall-clock cap on the post-push hook process, in seconds.
    ALLOWED_HOOKS: The operator git-hook filenames allowed to run under the daemon.
  """

  BASE_BRANCH = "base_branch"
  WORKTREE_ROOT = "worktree_root"
  WORKTREE_BOOTSTRAP_CMD = "worktree_bootstrap_cmd"
  REMOTE_SYNC = "remote_sync"
  POST_PUSH_HOOK = "post_push_hook"
  POST_PUSH_TIMEOUT_SEC = "post_push_timeout_sec"
  ALLOWED_HOOKS = "allowed_hooks"


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
    CAN_COMMIT_IN_REPO: Whether the expert may write and commit inside the repo it runs in.
    MCP_CONFIG: Explicit MCP-config path(s) the spawn loads under strict mode, or unset for none.
    SETTING_SOURCES: Setting scopes the spawn loads (`user`/`project`/`local`), or unset for the hermetic default.
    WORKSPACE: The workspace mode (`main`/`branch`) the pump enforces before and after the spawn.
    SOURCE_PATHS: The `source_paths` key — repo-relative paths the pump copies into
      `source/` when it claims the job.
    CONTEXT_PATHS: The `context_paths` key — repo-relative paths the pump copies into
      `context/` when it claims the job.
  """

  AGENT = "agent"
  PROTOCOLS = "protocols"
  ASPECTS = "aspects"
  ARGUMENTS = "arguments"
  GIT_AUTHOR = "git_author"
  MODEL = "model"
  CAN_COMMIT_IN_REPO = "can_commit_in_repo"
  MCP_CONFIG = "mcp_config"
  SETTING_SOURCES = "setting_sources"
  WORKSPACE = "workspace"
  SOURCE_PATHS = "source_paths"
  CONTEXT_PATHS = "context_paths"


# ----------------------------------------------------------------------------------------
class WorkspaceMode:
  """
  `workspace` value tokens an expert entry declares in `lazy.settings.json[experts]`.

  Attributes:
    MAIN: The expert's spawn runs on the daemon's base branch — today's behavior, and the
      default when the key is absent.
    BRANCH: The pump creates or reuses a job-scoped branch before the spawn and restores
      the base branch afterward.
  """

  MAIN = "main"
  BRANCH = "branch"


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
    HOOKS: The lifecycle-hook enablement section name.
    LEGACY_VERSION: The pre-split root-level version key migrations fold away.
    EXTERNAL_DIRS: The externally-sourced working-directory declaration section name.
  """

  VERSION = "_version"
  DAEMON = "daemon"
  ROUTINES = "routines"
  EXPERTS = "experts"
  AGENT_MODELS = "agent_models"
  HOOKS = "hooks"
  LEGACY_VERSION = "version"
  EXTERNAL_DIRS = "external_dirs"


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
  Keys on an error-ledger event — those a caller fills in when recording one, plus those the
  ledger derives when listing incidents back.

  Attributes:
    INCIDENT: The stable incident-folding key.
    KIND: The closed-set event kind.
    CAUSE: The closed-set cause string.
    SEVERITY: The event severity.
    EXPERT: The owning expert name, when the incident is job-scoped.
    ROUTINE: The owning routine name, when the incident is routine-scoped.
    PHASE: The lifecycle phase the event records — an incident opening or a later triage.
    ACTOR: The component that recorded the event.
    JOB_ID: The owning job identifier, when the incident is job-scoped.
    DETAIL: The one-line human-readable description.
    REFS: The map of artifact paths an operator needs to inspect the incident.
    STATE: The folded incident state carried on a listing entry.
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
class EnvVar:
  """
  Environment-variable names the runtime sets on a spawn (and the values it pins for them),
  read back by the hooks or by the spawned `claude` CLI itself.

  Attributes:
    HOOKS_ALLOW_LIST: The comma-separated allow-list of hook short names that may run. Its
      presence (even empty) puts every lazycortex hook into allow-list mode — only the named
      hooks run; the daemon sets it from the dispatching routine's `hooks_enabled`, and every
      process that routine spawns — expert sessions included — inherits it.
    MAX_SUBAGENT_SPAWN_DEPTH: The `claude` CLI's own subagent-nesting-depth variable name.
    SUBAGENT_SPAWN_DEPTH_PIN: The value this runtime always sets it to — see the `Decision:`
      comment at `expert_pump.py`'s own env-construction site for why.
    GIT_CONFIG_COUNT: git's own variable naming how many config slots the environment carries.
    GIT_CONFIG_KEY: Prefix of a slot's config-key variable; the slot index completes the name.
    GIT_CONFIG_VALUE: Prefix of a slot's config-value variable; the slot index completes it.
    GIT_CONFIG_PREFIX: Common prefix of every variable in git's environment-config protocol,
      numbered slots and config-file handles alike.
    GIT_HOOKS_PATH: The git config key naming the directory hooks are read from.
  """

  HOOKS_ALLOW_LIST = "LAZYCORTEX_HOOKS_ALLOW_LIST"
  MAX_SUBAGENT_SPAWN_DEPTH = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
  SUBAGENT_SPAWN_DEPTH_PIN = "3"
  GIT_CONFIG_COUNT = "GIT_CONFIG_COUNT"
  GIT_CONFIG_KEY = "GIT_CONFIG_KEY_"
  GIT_CONFIG_VALUE = "GIT_CONFIG_VALUE_"
  GIT_CONFIG_PREFIX = "GIT_CONFIG_"
  GIT_HOOKS_PATH = "core.hooksPath"


# ----------------------------------------------------------------------------------------
class HookName:
  """
  Canonical short names identifying each lazycortex-core lifecycle hook to the enablement gate.

  A hook passes its own name to `hook_gate.is_enabled` so a single vocabulary drives both the
  per-routine `hooks_enabled` allow-list and the interactive `hooks.disabled` block-list. The
  names are stable configuration surface — renaming one silently breaks every operator's config.

  Attributes:
    GIT_GUARD: The staging-mutex / dirty-index guard hook.
    MODEL_ROUTER: The subagent model-tier routing hook.
    CHECK_PUBLIC: The public-repo PII / infrastructure scan hook.
    SECRETS_GUARD: The always-on secret scan hook.
    SETTINGS_GUARD: The settings-file edit guard hook.
    COMMIT_RECORDER: The commit-log recorder hook.
  """

  GIT_GUARD = "lazy-core.git-guard"
  MODEL_ROUTER = "lazy-core.model-router"
  CHECK_PUBLIC = "lazy-guard.check-public"
  SECRETS_GUARD = "lazy-guard.secrets"
  SETTINGS_GUARD = "lazy-guard.settings"
  COMMIT_RECORDER = "lazy-log.commit-recorder"


# ----------------------------------------------------------------------------------------
class HooksKey:
  """
  Keys in the `hooks` configuration block of `lazy.settings.json`.

  Attributes:
    DISABLED: Root-section block-list — hook short names silenced in interactive sessions.
  """

  DISABLED = "disabled"


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
  Closed-set `kind` value tokens recorded on incidents.

  Attributes:
    JOB_DEAD: A job whose claimant process died before producing output.
    JOB_ERROR: A job that completed with an error outcome.
    ROUTINE_ERROR: A routine tick that failed.
    DAEMON_HALT: A daemon-wide halt block.
    DAEMON_ERROR: An unexpected daemon-loop exception.
    WORKTREE_TASK_ERROR: A worktree-task lifecycle failure.
    UNPINNED_MODEL: A dispatch whose model resolved to nothing and fell back to the CLI default.
    PLUGIN_ERROR: An in-band failure a sibling plugin reported through the error-record CLI,
      for a condition neither a job nor a routine result can express.
  """

  JOB_DEAD = "job_dead"
  JOB_ERROR = "job_error"
  ROUTINE_ERROR = "routine_error"
  DAEMON_HALT = "daemon_halt"
  DAEMON_ERROR = "daemon_error"
  WORKTREE_TASK_ERROR = "worktree_task_error"
  UNPINNED_MODEL = "unpinned_model"
  PLUGIN_ERROR = "plugin_error"


# ----------------------------------------------------------------------------------------
class IncidentActor:
  """
  `actor` value tokens naming which subsystem recorded an incident event.

  Attributes:
    DAEMON: The runtime daemon loop itself.
    PUMP: The expert-job pump.
    DOCTOR: The recovery doctor primitives.
    RECOVER: The halt-recovery primitives.
    DISPATCHER: The job-dispatch primitive in the expert runtime.
  """

  DAEMON = "daemon"
  PUMP = "pump"
  DOCTOR = "doctor"
  RECOVER = "recover"
  DISPATCHER = "dispatcher"


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
    RESETS_AT: The epoch-second timestamp a rate-limit halt lifts itself at.
  """

  HALTED_SINCE = "halted_since"
  TRIGGERED_BY = "triggered_by"
  REASON = "reason"
  DIRTY_PATHS = "dirty_paths"
  RESETS_AT = "resets_at"


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
    INBOX_COLLISION: Another checkout on this host drives the same physical inbox.
    ROUTINE_CONFIG_INVALID: A registry entry does not conform to its type schema.
    RATE_LIMIT: The subscription rate-limit window is closed; spawns pause until it reopens.
  """

  UNCOMMITTED_CHANGES = "uncommitted_changes"
  SUSPECTED_LOOP = "suspected_loop"
  GIT_PULL_DIVERGED = "git_pull_diverged"
  GIT_PUSH_FAILED = "git_push_failed"
  GIT_REMOTE_UNAVAILABLE = "git_remote_unavailable"
  INBOX_COLLISION = "inbox_collision"
  ROUTINE_CONFIG_INVALID = "routine_config_invalid"
  RATE_LIMIT = "rate_limit"


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
class SandboxKey:
  """
  Field names inside the daemon-owned sandbox settings file.

  Attributes:
    SANDBOX: The top-level block that confines an expert spawn.
    ENABLED: The switch that turns the confinement on.
    FILESYSTEM: The block holding the path allowlists.
    ALLOW_READ: The allowlist of paths a confined spawn may read.
    ALLOW_WRITE: The allowlist of paths a confined spawn may write.
  """

  SANDBOX = "sandbox"
  ENABLED = "enabled"
  FILESYSTEM = "filesystem"
  ALLOW_READ = "allowRead"
  ALLOW_WRITE = "allowWrite"


# ----------------------------------------------------------------------------------------
class SandboxSyncKey:
  """
  Field names in the result of a sandbox-allowlist sync or audit.

  Attributes:
    PATH: Absolute location of the sandbox settings file the result describes.
    PRESENT: Whether that file existed before the call.
    ENABLED: The confinement switch as recorded in the file, or null when unrecorded.
    ADDED_READ: Read-allowlist entries the sync appended.
    ADDED_WRITE: Write-allowlist entries the sync appended.
    MISSING_READ: Resolved read targets no recorded entry covers.
    MISSING_WRITE: Resolved write targets no recorded entry covers.
    CHANGED: Whether the sync rewrote the file.
  """

  PATH = "path"
  PRESENT = "present"
  ENABLED = "enabled"
  ADDED_READ = "added_read"
  ADDED_WRITE = "added_write"
  MISSING_READ = "missing_read"
  MISSING_WRITE = "missing_write"
  CHANGED = "changed"


# ----------------------------------------------------------------------------------------
class JobArtifact:
  """
  Per-attempt forensic filenames written inside a job bundle directory.

  Attributes:
    DEAD_JSON: The forensic payload describing a job marked dead.
    DIAGNOSIS_JSON: The doctor's diagnosis written when a job is permanently failed.
    ATTEMPTS: The cumulative attempt-counter file.
    TRANSIENT_ERRORS: The transient-error counter file the retry budget is judged against.
    TRANSCRIPT: The captured stream-json transcript of the expert spawn.
    ERROR_JSON: The per-attempt rejection payload fed back into the next attempt's prompt.
  """

  DEAD_JSON = "dead.json"
  DIAGNOSIS_JSON = "diagnosis.json"
  ATTEMPTS = "attempts"
  TRANSIENT_ERRORS = "transient_errors"
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
    DEDUP_FINGERPRINT: The optional identity token of the artifact behind the dedup key at dispatch time.
    BRANCH: The job-scoped branch name a `workspace: branch` expert's spawn runs on; a caller
      dispatching a continuation job passes back the value read off the original dispatch so the
      continuation lands on the same branch instead of a fresh one.
  """

  DEDUP_KEY = "_dedup_key"
  DEDUP_FINGERPRINT = "_dedup_fingerprint"
  BRANCH = "branch"


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
    DEFERRED: The outcome value marking work the expert deliberately left undone with its
      input untouched, so a consumer must neither drain the input nor treat it as failed.
  """

  ERROR = "error"
  DEFERRED = "deferred"


# ----------------------------------------------------------------------------------------
class JobLogOutcome:
  """
  `outcome` value tokens in the pump's per-attempt job log records.

  Attributes:
    DONE: The attempt finished the job without an error outcome.
    FAILED: The attempt finished the job with an error outcome.
    DEFERRED: The attempt deliberately left the work undone with its input untouched.
    DEAD: The job was marked dead by the dead-job detector.
    ERROR: The attempt failed transiently or logically; the job stays queued for retry.
  """

  DONE = "done"
  FAILED = "failed"
  DEFERRED = "deferred"
  DEAD = "dead"
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
    DEDUP_FINGERPRINT: The dedup fingerprint carried on a reconcilable finished-job entry.
    PATH: The absolute job-directory path.
    DEDUP_KEY: The dedup key carried on a reconcilable finished-job entry.
    CATEGORY: The error category of a failed finished-job entry, absent on a success.
    AGE_SEC: Seconds elapsed since the entry's bundle finished.
  """

  STATUS = "status"
  RESPONSE = "response"
  EXPERT = "expert"
  JOB_ID = "job_id"
  DEDUP_FINGERPRINT = "dedup_fingerprint"
  PATH = "path"
  DEDUP_KEY = "dedup_key"
  CATEGORY = "category"
  AGE_SEC = "age_sec"


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
    DEFERRED: The bundle finished with the reserved deferred outcome — work postponed, input untouched.
    DEAD: The bundle carries a DEAD marker.
    CANCELLED: The bundle carries a CANCELLED marker — cancelled by the operator.
    ALREADY_QUEUED: Dispatch result token — a live bundle already owns the dedup key.
  """

  MISSING = "missing"
  PENDING = "pending"
  QUEUED = "queued"
  ACTIVE = "active"
  DONE = "done"
  FAILED = "failed"
  DEFERRED = "deferred"
  DEAD = "dead"
  CANCELLED = "cancelled"
  ALREADY_QUEUED = "already-queued"


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
    DISPATCHED_COUNT: The number of items the tick actually dispatched; absent when the
      routine type does not report one.
  """

  NAME = "name"
  EXIT = "exit"
  DURATION_SEC = "duration_sec"
  NOTE = "note"
  ERROR = "error"
  DISPATCHED_COUNT = "dispatched_count"


# ----------------------------------------------------------------------------------------
class MetricStateKey:
  """
  Keys in the metrics module's process-local registry dict.

  Attributes:
    INITIALIZED: Whether `init` has run.
    REPO: The repo label captured at init.
    VERSION: The plugin version captured at init.
    DAEMON_NAME: The daemon identifier captured at init.
    LOCK: The threading lock guarding metric mutations.
    TICKS: The routine-tick counter instrument.
    RUNS: The non-idle-run counter instrument.
    ERRORS: The routine-error counter instrument.
    TOKENS: The token-consumption counter instrument.
    DURATION: The tick-duration histogram instrument.
    LAST_TICK: The last-tick-timestamp gauge instrument.
    QUEUE_DEPTH: The expert-queue-depth gauge instrument.
    UP: The endpoint-up gauge instrument.
    DAEMON_HALTED: The daemon-halted gauge instrument.
    BUILD_INFO: The build-info gauge instrument.
    HALT_COUNT: The cumulative-halt counter instrument.
    DIRTY_TREE: The dirty-working-tree silent-skip gauge instrument.
    EXPERT_JOBS: The expert-job-attempt counter instrument.
    EXPERT_JOB_DURATION: The expert-job-attempt duration histogram instrument.
    INCIDENTS: The error-ledger incident counter instrument.
    TOKEN_OFFSET: The byte offset into the token log read so far.
    JOBS_OFFSET: The byte offset into the job log read so far.
    INCIDENTS_OFFSET: The byte offset into the error-ledger journal read so far.
    SERVER: The WSGI server object.
    SERVER_THREAD: The server's background thread.
  """

  INITIALIZED = "initialized"
  REPO = "repo"
  VERSION = "version"
  DAEMON_NAME = "daemon_name"
  LOCK = "lock"
  TICKS = "ticks"
  RUNS = "runs"
  ERRORS = "errors"
  TOKENS = "tokens"
  DURATION = "duration"
  LAST_TICK = "last_tick"
  QUEUE_DEPTH = "queue_depth"
  UP = "up"
  DAEMON_HALTED = "daemon_halted"
  BUILD_INFO = "build_info"
  HALT_COUNT = "halt_count"
  DIRTY_TREE = "dirty_tree"
  EXPERT_JOBS = "expert_jobs"
  EXPERT_JOB_DURATION = "expert_job_duration"
  INCIDENTS = "incidents"
  TOKEN_OFFSET = "token_offset"
  JOBS_OFFSET = "jobs_offset"
  INCIDENTS_OFFSET = "incidents_offset"
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
    EXPERT: The expert-name label.
    OUTCOME: The job-attempt outcome label.
    MODEL: The model-tier label.
    KIND: The token-kind label, reused for the incident-kind label.
    CAUSE: The incident-cause label.
    VERSION: The plugin-version label.
    DAEMON_NAME: The daemon-identifier label.
  """

  REPO = "repo"
  ROUTINE = "routine"
  STATUS = "status"
  REASON = "reason"
  EXPERT = "expert"
  OUTCOME = "outcome"
  MODEL = "model"
  KIND = "kind"
  CAUSE = "cause"
  VERSION = "version"
  DAEMON_NAME = "daemon_name"


# ----------------------------------------------------------------------------------------
class ExternalDirsKey:
  """
  Keys in the `external_dirs` section across both settings layers.

  Attributes:
    PATHS: The tracked list of repo-relative paths that live outside the repository.
    ROOT: The local-overlay absolute path the declared paths point at.
    DECLINED: The local-overlay flag recording that the operator declined to configure a source.
  """

  PATHS = "paths"
  ROOT = "root"
  DECLINED = "declined"


# ----------------------------------------------------------------------------------------
class ExternalDirStatus:
  """
  Closed-set diagnosis tokens for one declared external directory.

  Attributes:
    OK: A symlink pointing at the declared source, whose source exists.
    MISSING: Nothing in the declared slot while the source is available.
    DANGLING: A symlink whose target does not exist.
    WRONG_TARGET: A live symlink pointing somewhere other than the declared source.
    NOT_A_SYMLINK: Operator content occupying the declared slot.
    SOURCE_MISSING: Nothing in the slot and no source to link to.
    UNCONFIGURED: Paths declared while no source root is on record for this checkout.
  """

  OK = "ok"
  MISSING = "missing"
  DANGLING = "dangling"
  WRONG_TARGET = "wrong_target"
  NOT_A_SYMLINK = "not_a_symlink"
  SOURCE_MISSING = "source_missing"
  UNCONFIGURED = "unconfigured"


# ----------------------------------------------------------------------------------------
class ExternalDirFindingKey:
  """
  Keys in one external-directory finding or repair record.

  Attributes:
    PATH: The declared repo-relative path the record describes.
    STATUS: The diagnosis token from `ExternalDirStatus`.
    SOURCE: The absolute source path, or None when no source root is on record.
    GITIGNORED: Whether git ignores the declared path in this repository.
    IGNORE_RULE: The ignore-coverage token from `ExternalDirIgnore`.
    ACTION: The repair outcome from `ExternalDirAction`, present on repair records only.
  """

  PATH = "path"
  STATUS = "status"
  SOURCE = "source"
  GITIGNORED = "gitignored"
  IGNORE_RULE = "ignore_rule"
  ACTION = "action"


# ----------------------------------------------------------------------------------------
class ExternalDirIgnore:
  """
  Closed-set ignore-coverage tokens for one declared external directory.

  Attributes:
    IGNORED: The declared path as it stands is ignored — nothing dirties the tree.
    DIR_ONLY: An ignore rule covers the name as a directory only, so the symlink planted in
      the slot stays visible to git and an anchored slashless rule is missing.
    ABSENT: No ignore rule covers the name in any form.
  """

  IGNORED = "ignored"
  DIR_ONLY = "dir_only"
  ABSENT = "absent"


# ----------------------------------------------------------------------------------------
class ExternalDirAction:
  """
  Closed-set repair outcomes for one declared external directory.

  Attributes:
    LINKED: A missing symlink was created.
    RELINKED: An existing symlink was re-pointed at the declared source.
    UNCHANGED: The declared path already pointed at its source.
    SKIPPED: The state was left untouched and reported to the operator instead.
  """

  LINKED = "linked"
  RELINKED = "relinked"
  UNCHANGED = "unchanged"
  SKIPPED = "skipped"


# ----------------------------------------------------------------------------------------
class RoutineType:
  """
  Routine-type discriminator values read by callers outside the type registry.

  Attributes:
    INBOX: The inbox-scanning routine type.
  """

  INBOX = "inbox"


# ----------------------------------------------------------------------------------------
class InboxGuardKind:
  """
  Closed-set finding kinds of the shared-inbox ownership guard.

  Attributes:
    COLLISION: Two checkouts on this host drive one physical inbox.
  """

  COLLISION = "inbox_collision"


# ----------------------------------------------------------------------------------------
class InboxGuardKey:
  """
  Keys in one shared-inbox guard finding.

  Attributes:
    KIND: The finding kind from `InboxGuardKind`.
    ROUTINE: The local routine whose inbox is contested.
    INBOX: The canonical absolute path both checkouts resolve to.
    OTHER_REPO: The absolute repo root of the other checkout driving the same inbox.
    OTHER_ROUTINE: The routine name the other checkout scans it under.
    DETAIL: A one-line human-readable description.
  """

  KIND = "kind"
  ROUTINE = "routine"
  INBOX = "inbox"
  OTHER_REPO = "other_repo"
  OTHER_ROUTINE = "other_routine"
  DETAIL = "detail"


# ----------------------------------------------------------------------------------------
class ReviewClassKey:
  """
  Keys in the `review` section's class list and its per-entry records.

  Attributes:
    CLASSES: The `review.classes` list key.
    CLASS: The class name (a token from `ReviewClassName`).
    PATHS: The glob patterns routing a document to this class.
    EXPERTS: The per-class expert wiring block.
  """

  CLASSES = "classes"
  CLASS = "class"
  PATHS = "paths"
  EXPERTS = "experts"


# ----------------------------------------------------------------------------------------
class ReviewClassName:
  """
  Closed-set review-class name tokens referenced by the settings migration ladder.

  Attributes:
    LEGACY_PLAN: The pre-v2 class name retired via `DEV_PLAN` in favor of today's `CODE_PLAN`.
    DEV_PLAN: The pre-v9 planner-facing class name that `CODE_PLAN` replaces.
    CODE_PLAN: The planner-facing implementation-plan document class (v8 → v9).
    TEST_PLAN: The tester-facing test-plan document class, mirroring the plan class's experts.
    DEV_REPORT: The pre-v9 implementer-facing class name that `CODE_REPORT` replaces.
    CODE_REPORT: The implementer-facing implementation-report document class (v8 → v9).
    TEST_REPORT: The tester-facing test-report document class.
    DESIGN: The designer-facing design document class.
    BUG: The tester-facing bug-report document class.
    ARCHITECTURE: The architect-facing architecture document class (v6 → v7).
  """

  LEGACY_PLAN = "plan"
  DEV_PLAN = "dev-plan"
  CODE_PLAN = "code-plan"
  TEST_PLAN = "test-plan"
  DEV_REPORT = "dev-report"
  CODE_REPORT = "code-report"
  TEST_REPORT = "test-report"
  DESIGN = "design"
  BUG = "bug"
  ARCHITECTURE = "architecture"
