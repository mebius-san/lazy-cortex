"""
Generic per-repo serial runtime daemon.

Drives one repository's routine schedule on a single timeline. Routines registered in `lazy.settings.json`
are evaluated each iteration; eligible ones dispatch sequentially, log their result, and update last-run
state. Health is guarded by pre-iteration git sync, post-iteration push, dirty-tree skip, and loop
detection on bot-author commits. Retry policy lives in routine implementations, not in the daemon.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from lazy_settings import load_section
import error_ledger
import runtime_state
from routine_types import dispatch_routine
from worktree_tasks import WorktreeTaskManager
from code_fingerprint import CodeFingerprint
from constants import (
  DaemonKey, GitConfigKey, HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  JobCollectKey, JobConfigKey, JobStatus, PluginFile, RoutineKey, SettingsFile, SettingsKey, StateKey,
  TickResultKey, WorktreeEntryKey, WorktreeResult, WorktreeResultKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# default per-routine subprocess timeout; overridable per-routine via routines[<name>].timeout_sec
DEFAULT_TIMEOUT_SEC = 300
POST_TICK_MAX_PUSH_ATTEMPTS = 3
# default wall-clock cap for the operator's post-push hook; overridable via daemon.git.post_push_timeout_sec
DEFAULT_POST_PUSH_TIMEOUT_SEC = 30
# Hourly throttle for runtime-log + worktree cleanup (seconds).
_CLEANUP_INTERVAL_SEC = 3600
# A tick faster than this with no work done is treated as quiet (not log-worthy).
_QUIET_TICK_MAX_SEC = 1.5
# Dirty-tree halt messages truncate the path list to this many lines.
_MAX_DIRTY_PATH_LINES = 50


class GitPullDiverged(RuntimeError):
  """
  Raised when the daemon's pre-iteration git sync detects divergent histories.

  Signals that local `HEAD` and `origin/<branch>` share a common ancestor that is neither side, meaning
  both ends carry commits the other does not. The daemon's branch is contractually exclusive to the
  daemon, so divergence is treated as unsafe-to-resolve and requires human intervention.
  """


class GitPushFailed(RuntimeError):
  """
  Raised when the daemon's post-iteration push exhausts every retry.

  Signals that the routine commit cannot be published to `origin/<branch>`. Either an operator is
  pushing into the daemon's branch (rare and indicative of a coordination bug) or the push is refused
  for non-race reasons such as authentication, force-protection, or permission.
  """


# Set by `set_plugin_dirs`. When non-empty, `resolve_routine_command` consults these paths first (each is
# a plugin source dir containing `.claude-plugin/` and `bin/`) and falls back to the plugin cache if no
# match. Mirrors Claude Code's `--plugin-dir` for the daemon's separate-process world: a dev-vault
# operator points the daemon at the source plugins they're working on, instead of routing through a
# cached install.
_PLUGIN_DIRS: list[Path] = []


def set_plugin_dirs(dirs: list[Path]) -> None:
  """
  Register plugin source directories the daemon should prefer over the plugin cache.

  Also exports the resolved paths to the environment so downstream subprocess routines (such as
  `lazycortex-core expert-pump-once` or `lazycortex-review tick`) and their own resolvers can match
  the same dev-plugin paths.

  Args:
    dirs: Plugin source directories to register, in caller-preferred order. Each entry should be the
      root of a plugin source tree containing `.claude-plugin/` and `bin/`.
  """
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  global _PLUGIN_DIRS  # noqa: PLW0603  # pylint: disable=global-statement
  _PLUGIN_DIRS = [ Path(d).resolve() for d in dirs ]
  # arguments are not ref-resolved (pass-through JSON values), but flow through to <jdir>/config.json
  # the same way; daemon-internal `resolve_routine_command` uses `_PLUGIN_DIRS` directly, while this
  # env handle exists for everyone else
  os.environ["LAZYCORTEX_PLUGIN_DIRS"] = os.pathsep.join(str(p) for p in _PLUGIN_DIRS)


def _resolve_in_plugin_dir(plugin_dir: Path, plugin_name: str) -> Path | None:
  """
  Resolve the bin entrypoint for a single plugin source directory.

  Reads the directory's `plugin.json` "name" field and returns its entrypoint when it matches the
  requested plugin. Prefers `bin/<plugin-name>`; otherwise falls back to the single executable script
  under `bin/`. Ambiguous directories with multiple executables are skipped so the caller can keep
  searching.

  Args:
    plugin_dir: Plugin source root containing `.claude-plugin/` and `bin/`.
    plugin_name: Expected plugin identifier as declared in `plugin.json`.

  Returns:
    Path to the resolved bin entrypoint, or `None` when the directory does not match or no
    unambiguous executable is available.
  """
  manifest = plugin_dir / PluginFile.MANIFEST_DIR / PluginFile.MANIFEST
  try:
    data = json.loads(manifest.read_text())
  except (FileNotFoundError, json.JSONDecodeError):
    return None
  # guard: directory's manifest names a different plugin
  if data.get(PluginFile.NAME) != plugin_name:
    return None
  # waiver: filesystem path idiom, not a domain constant
  bin_dir = plugin_dir / "bin"
  # guard: no bin directory present
  if not bin_dir.is_dir():
    return None
  primary = bin_dir / plugin_name
  # guard: preferred entrypoint exists and is executable
  if primary.is_file() and os.access(primary, os.X_OK):
    return primary
  execs = [
    p for p in bin_dir.iterdir()
    if p.is_file()
    # waiver: filesystem path idiom, not a domain constant
    and not p.name.endswith(".py")
    and not p.name.startswith(".")
    and os.access(p, os.X_OK)
  ]
  # guard: unique executable fallback only
  if len(execs) == 1:
    return execs[0]
  return None


def _read_plugin_version() -> str:
  """
  Read the running plugin's version string from its shipped manifest.

  Returns:
    The `"version"` value from this plugin's `plugin.json`, or the literal `"unknown"` when the file
    is missing or malformed. The fallback is chosen to satisfy the `[A-Za-z0-9._-]` label format
    required by the metrics module.
  """
  here = Path(__file__).resolve().parent  # claude/lazycortex-core/bin
  plugin_json = here.parent / PluginFile.MANIFEST_DIR / PluginFile.MANIFEST
  try:
    return json.loads(plugin_json.read_text())[PluginFile.VERSION]
  except (FileNotFoundError, KeyError, json.JSONDecodeError):
    # waiver: stdlib idiom, not a domain constant
    return "unknown"


def _init_metrics_if_enabled(repo_root: Path) -> None:
  """
  Bring up the metrics endpoint when settings turn it on.

  Reads daemon settings once before the main loop starts. Metrics initialization is one-shot — the
  operator must restart the daemon to flip enablement on or off, even though the routine registry
  itself is hot-reloaded inside the loop.

  Notes:
    - When metrics are disabled in settings, the call returns without side effects.
    - When enabled, the metrics module is loaded, initialized with the resolved labels, and exposed
      on the configured bind address and port.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
  """
  settings_path = repo_root / SettingsFile.REL
  daemon = load_section(settings_path, SettingsKey.DAEMON)
  metrics_cfg = daemon.get(DaemonKey.METRICS, {})
  # guard: metrics opt-in not set
  if not metrics_cfg.get(DaemonKey.ENABLED):
    return
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import metrics
  repo_label = metrics.resolve_repo_label(repo_root, metrics_cfg.get("repo_label"))
  metrics.init(
    repo_label = repo_label,
    version = _read_plugin_version(),
    daemon_name = metrics_cfg.get(DaemonKey.DAEMON_NAME) or "lazycortex-runtime",
  )
  metrics.expose(
    # waiver: inline numeric/default literal, not a domain constant
    bind = metrics_cfg.get(DaemonKey.BIND, "127.0.0.1"),
    # waiver: inline numeric/default literal, not a domain constant
    port = int(metrics_cfg.get(DaemonKey.PORT, 9464)),
  )


def compute_sleep(time_until_next: float, polling_interval_sec: float) -> float:
  """
  Compute the daemon's between-iteration sleep duration.

  Args:
    time_until_next: Seconds until the next routine becomes due.
    polling_interval_sec: Maximum sleep allowed before re-evaluating the schedule.

  Returns:
    A non-negative number of seconds; the smaller of `time_until_next` and `polling_interval_sec`,
    clamped to zero when either value is negative.
  """
  return max(0.0, min(time_until_next, polling_interval_sec))


def due_routines(now: float, registry: dict, last_run: dict,
                 system_stuck: bool = False) -> list[tuple[str, dict]]:
  """
  Return routines that are eligible to run right now, sorted by ascending priority.

  Args:
    now: Current wall-clock timestamp in seconds since the epoch.
    registry: Routine registry as loaded from `lazy.settings.json[routines]`, keyed by routine name.
    last_run: Mapping of routine name to its last successful run timestamp.
    system_stuck: When true, the daemon is halted or the working tree is dirty; only routines marked
      with `ignore_halt: true` survive the filter so recovery routines can still run.

  Returns:
    A list of `(name, cfg)` pairs ordered by `priority` ascending. Ties on equal priority preserve
    registry insertion order.
  """
  out = []
  for name, cfg in registry.items():
    # filter out normal routines while system is stuck; recovery routines stay
    # guard: skip the routine while the daemon is halted, unless it opts out of halt
    if system_stuck and not cfg.get(RoutineKey.IGNORE_HALT, False):
      continue
    if cfg.get(RoutineKey.TYPE) == "schedule":
      # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
      from routine_types import due_for_schedule
      if due_for_schedule(name, cfg, now, last_run.get(name, 0)):
        out.append((name, cfg))
    # waiver: inline numeric/default literal, not a domain constant
    elif now - last_run.get(name, 0) >= cfg.get(RoutineKey.INTERVAL_SEC, 5):
      out.append((name, cfg))
  # waiver: inline numeric/default literal, not a domain constant
  out.sort(key = lambda item: item[1].get(RoutineKey.PRIORITY, 100))
  return out


def time_until_next_due(now: float, registry: dict, last_run: dict) -> float:
  """
  Compute seconds until the soonest routine becomes due.

  Args:
    now: Current wall-clock timestamp in seconds since the epoch.
    registry: Routine registry as loaded from `lazy.settings.json[routines]`, keyed by routine name.
    last_run: Mapping of routine name to its last successful run timestamp.

  Returns:
    The minimum number of seconds until any routine becomes due. Returns `float("inf")` when the
    registry is empty. May be negative when a routine is already overdue.
  """
  candidates = []
  for n, cfg in registry.items():
    # waiver: cross-module routine-type token, not an internal key
    if cfg.get(RoutineKey.TYPE) == "schedule":
      # schedule routines wake up to be re-checked on each tick; the daemon's polling_interval_sec
      # floor keeps the loop honest
      # waiver: inline numeric/default literal, not a domain constant
      candidates.append(60.0)
    else:
      # waiver: inline numeric/default literal, not a domain constant
      candidates.append(last_run.get(n, 0) + cfg.get(RoutineKey.INTERVAL_SEC, 5) - now)
  return min(candidates) if candidates else float("inf")


LOOP_DETECT_THRESHOLD = 5
"""
Threshold for the per-(author, file-set) loop-detection halt rule.

Halt when any single (bot-email, committed-file-set) signature accumulates this many commits within
the detection window — i.e. the bot keeps re-committing the *same set of files*. Sized so a busted
state machine caps its damage at a few spawns before a human shows up. Overridable via
`daemon.loop_detect_threshold` in settings.
"""

LOOP_DETECT_WINDOW_FACTOR = 4
"""
Default multiplier applied to threshold to derive the commit-history window size.

`loop_detect_window = loop_detect_threshold * LOOP_DETECT_WINDOW_FACTOR` unless overridden by
`daemon.loop_detect_window` in settings.
"""


def _loop_detect_check(
  repo_root: Path,
  state: dict,
  settings_path: Path,
) -> None:
  """
  Run the post-iteration loop-detect safety net against recent commit history.

  Halts the daemon when a single (bot-email, committed-file-set) signature accumulates commits at or
  above the configured threshold within the detection window — i.e. the same bot keeps committing
  the *same set of files*. Bot identities are resolved from `experts.<name>.git_author.email` in
  `lazy.settings.json`; operator commits never trigger the rule because humans are not in the experts
  table. A file that recurs across commits alongside a *different* set of other files each time (e.g.
  a regenerated index committed next to distinct edits) does not trigger the rule — only a repeated
  whole-commit file-set does.

  Notes:
    - Skipped when not in a git repo, when the threshold is set below 2, or when no experts are
      registered.
    - The check costs a single `git log -<window> --no-merges --name-only -z` invocation.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    state: In-memory copy of the daemon's persisted state, mutated in place when a halt is recorded.
    settings_path: Absolute path to `lazy.settings.json`.
  """
  daemon = load_section(settings_path, SettingsKey.DAEMON)
  threshold = int(daemon.get(DaemonKey.LOOP_DETECT_THRESHOLD, LOOP_DETECT_THRESHOLD))
  # guard: rule disabled via configuration
  if threshold < 2:
    return
  # waiver: "loop_detect_window" is a settings key string, not a magic literal
  window = int(daemon.get("loop_detect_window", threshold * LOOP_DETECT_WINDOW_FACTOR))
  # noinspection PyBroadException
  try:
    experts = load_section(settings_path, SettingsKey.EXPERTS)
  except Exception:
    return
  bot_emails: set[str] = set()
  for nm, entry in experts.items():
    # guard: skip the version key and any non-dict entry
    if nm == SettingsKey.VERSION or not isinstance(entry, dict):
      continue
    # waiver: small internal subkey, not a reusable domain key
    email = ((entry.get(JobConfigKey.GIT_AUTHOR) or {}).get("email") or "").strip()
    if email:
      bot_emails.add(email)
  # guard: no registered bot authors to attribute commits to
  if not bot_emails:
    return
  try:
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "log", f"-{window}",
        "--no-merges", "--format=%x01%ae", "--name-only", "-z" ],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
  except FileNotFoundError:
    return
  # guard: git invocation failed
  if rc.returncode != 0:
    return
  # Parse `\x01<email>\x00\n<file>\x00...` commit records separated by \x01.
  # git -z NUL-terminates the format output too, so head may carry a trailing \x00.
  tally: dict[tuple[str, frozenset[str]], int] = {}
  for record in rc.stdout.split("\x01"):
    # guard: empty record between delimiters — skip
    if not record.strip():
      continue
    head, _, rest = record.partition("\n")
    email = head.strip("\x00\r\n\t ")
    # guard: commit not by a registered bot — irrelevant to the loop rule
    if email not in bot_emails:
      continue
    files = frozenset(f.strip() for f in rest.split("\x00") if f.strip())
    # guard: commit touched no files (empty / merge) — no file-set signature to tally
    if not files:
      continue
    key = ( email, files )
    tally[key] = tally.get(key, 0) + 1
    # guard: this (bot, file-set) signature hit the threshold — assume a loop
    if tally[key] >= threshold:
      _halt_daemon(
        # waiver: daemon error/trigger token, not an internal key
        repo_root, state, HaltReason.SUSPECTED_LOOP, "_loop_detect",
        f"file-set {sorted(files)!r} committed {tally[key]}x by {email!r} in last {window}",
      )
      return


def _check_working_tree(repo_root: Path) -> list[str] | None:
  """
  Inspect the daemon repository's working tree for uncommitted changes.

  Notes:
    - Uses `--no-optional-locks` so the stat-cache refresh does not race the index lock — the dirty-
      tree check runs every daemon iteration and without this flag would grab the lock dozens of
      times per minute.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.

  Returns:
    A list of dirty `git status --porcelain` lines, capped at 50 entries with the last one replaced
    by a truncation sentinel when more dirt exists. Returns `None` when the tree is clean, when git
    is unavailable, or when the path is not a git repository.
  """
  try:
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never",
        "status", "--porcelain" ],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
  except FileNotFoundError:
    return None
  # guard: git invocation failed
  if rc.returncode != 0:
    return None
  raw = rc.stdout.rstrip("\n")
  # guard: clean tree — nothing to report
  if not raw:
    return None
  lines = raw.split("\n")
  if len(lines) > _MAX_DIRTY_PATH_LINES:
    lines = [ *lines[:_MAX_DIRTY_PATH_LINES], "... (truncated, more dirty paths exist)" ]
  return lines


def _halt_daemon(
  repo_root: Path,
  state: dict,
  reason: str,
  triggered_by: str,
  detail: str,
) -> None:
  """
  Record a daemon halt to persistent state and emit the corresponding metric.

  Writes a `daemon_halted` block into `state.json` when one is not already present, and logs the
  trigger detail to the runtime log so the operator running `/lazy-runtime.recover` can correlate
  the halt with a routine result entry.

  Notes:
    - When a halt block already exists, the existing entry is preserved — earlier halts with more-
      specific attribution (e.g. expert + job_id) are never clobbered.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    state: In-memory copy of the daemon's persisted state, mutated in place.
    reason: Halt-reason code (e.g. `uncommitted_changes`, `git_pull_diverged`, `suspected_loop`).
    triggered_by: Routine or internal step that surfaced the halt condition.
    detail: Human-readable description routed into the routine log entry.
  """
  _log_routine_result(repo_root, {
    TickResultKey.NAME: triggered_by, TickResultKey.EXIT: -1, TickResultKey.DURATION_SEC: 0.0,
    TickResultKey.ERROR: f"{reason}: {detail}",
  })
  # guard: keep the earlier, more-specific halt attribution
  if StateKey.DAEMON_HALTED in state:
    return
  block = {
    HaltKey.HALTED_SINCE: time.time(),
    HaltKey.TRIGGERED_BY: triggered_by,
    HaltKey.REASON: reason,
    HaltKey.DIRTY_PATHS: [],
    IncidentKey.EXPERT: None,
    IncidentKey.JOB_ID: None,
  }
  # write via atomic read-modify-write so a routine's intervening state change is not clobbered;
  # also mirror into the passed in-memory state so callers checking state[StateKey.DAEMON_HALTED] see it
  state[StateKey.DAEMON_HALTED] = block
  runtime_state.update(repo_root, lambda s: s.setdefault(StateKey.DAEMON_HALTED, block))
  _emit_halt_metric_if_available(reason = reason, triggered_by = triggered_by)
  error_ledger.record(repo_root, {
    IncidentKey.INCIDENT: f"halt:{repo_root.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.DAEMON_HALT,
    IncidentKey.CAUSE: reason, IncidentKey.ACTOR: triggered_by or IncidentActor.DAEMON,
    IncidentKey.DETAIL: detail[:200],
  })


def _emit_halt_metric_if_available(reason: str, triggered_by: str) -> None:
  """
  Record a halt to the metrics module when available and enabled.

  Notes:
    - The metrics module is an optional dependency; an import failure is silently absorbed so the
      observability subsystem and the halt path stay independent.

  Args:
    reason: Halt-reason code matching the `daemon_halted.reason` field.
    triggered_by: Routine or internal step that surfaced the halt condition.
  """
  try:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import metrics
    if metrics.is_enabled():
      metrics.record_daemon_halt(reason = reason, triggered_by = triggered_by)
  except ImportError:
    pass


def _reconcile_halt_metric(state: dict) -> None:
  """
  Reconcile the daemon-halted gauge with the persisted halt block when metrics are available.

  Self-heals a stale gauge reading left over from an external recover or an auto-cleared halt,
  without touching the cumulative halt counter.

  Notes:
    - The metrics module is an optional dependency; an import failure is silently absorbed so the
      observability subsystem and the halt path stay independent.

  Args:
    state: In-memory copy of the daemon's persisted state; carries the halt block when halted.
  """
  halt = state.get(StateKey.DAEMON_HALTED)
  reason = halt.get(HaltKey.REASON) if halt else None
  triggered_by = halt.get(HaltKey.TRIGGERED_BY) if halt else None
  try:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import metrics
    if metrics.is_enabled():
      metrics.set_halt_gauge(reason = reason, triggered_by = triggered_by)
  except ImportError:
    pass


def _classify_routine_error(err: str) -> str:
  """
  Map a failed routine tick's error text to a closed-set cause string.

  Any error text from a plugin CLI tagged with `compute_inputs_failed` or `config_violation`
  maps to `config_violation` so the daemon can escalate to the class-1 halt path.

  Returns:
    One of `config_violation`, `timeout`, `git_pre_failed`, `git_post_failed`, or `error`.
  """
  e = err.lower()
  # guard: settings-invariant violation — escalate to class-1 halt path (GAP B)
  # waiver: daemon error/trigger token, not an internal key
  if "config_violation" in e or "compute_inputs_failed" in e:
    # waiver: daemon error/trigger token, not an internal key
    return "config_violation"
  # guard: timeout is the most specific signal
  # waiver: daemon error/trigger token, not an internal key
  if "timeout" in e:
    # waiver: daemon error/trigger token, not an internal key
    return "timeout"
  # waiver: daemon error/trigger token, not an internal key
  if "git_pre" in e:
    # waiver: daemon error/trigger token, not an internal key
    return "git_pre_failed"
  # waiver: daemon error/trigger token, not an internal key
  if "git_post" in e:
    # waiver: daemon error/trigger token, not an internal key
    return "git_post_failed"
  # waiver: daemon error/trigger token, not an internal key
  return "error"


def _maybe_prune_errors(repo_root: Path) -> None:
  """
  Prune the error journal by the configured retention window.

  Reads `daemon.errors.retention_days` (default 30) and drops journal events older than
  the window; the latest event of a still-open incident is retained regardless of age.

  Args:
    repo_root: Repository root the daemon is driving.
  """
  daemon = load_section(repo_root / SettingsFile.REL, SettingsKey.DAEMON)
  # waiver: inline numeric/default literal, not a domain constant
  retention = int(daemon.get(DaemonKey.ERRORS, {}).get(DaemonKey.RETENTION_DAYS, 30))
  error_ledger.prune(repo_root, retention)


def _advance_last_run(repo_root: Path, name: str) -> None:
  """
  Atomically record one routine's last-run timestamp.

  Re-reads the state file and updates only `last_run[name]`, so an intervening write to
  another key by the routine just run (e.g. a git-watch baseline) is never clobbered.

  Args:
    repo_root: Repository root the daemon is driving.
    name: Routine name whose last-run timestamp to advance.
  """
  runtime_state.update(repo_root, lambda s: s.setdefault(StateKey.LAST_RUN, {}).update({name: time.time()}))


def _run_iteration(repo_root: Path) -> None:
  """
  Execute one full iteration of the daemon's main loop.

  Loads persisted state and settings, performs pre-iteration git sync, dispatches every due routine
  in priority order, performs post-iteration git push, and runs the loop-detect safety net. Idempotent
  on `state.json`, providing a clean test seam.

  Notes:
    - When the daemon is halted with `uncommitted_changes` and the tree has become clean, the halt
      is auto-cleared at the start of the iteration.
    - Routines flagged `ignore_halt: true` (typically the autonomous doctor) run even while the
      system is stuck so they can triage and fix the halt condition.
    - When a routine leaves the tree dirty in a non-stuck system, the daemon records a halt and
      stops dispatching for the remainder of the iteration.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
  """
  state = runtime_state.load(repo_root)
  halt = state.get(StateKey.DAEMON_HALTED)
  if halt:
    # auto-clear dirty-tree halt as soon as the tree becomes clean; other halt reasons
    # (git_pull_diverged / git_push_failed / git_remote_unavailable) require human investigation
    # and stay until /lazy-runtime.recover
    if halt.get(HaltKey.REASON) == HaltReason.UNCOMMITTED_CHANGES and _check_working_tree(repo_root) is None:
      halt = None
      state = runtime_state.update(repo_root, lambda s: s.pop(StateKey.DAEMON_HALTED, None))
      _log_routine_result(repo_root, {
        TickResultKey.NAME: "_auto_recover", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
        "message": "dirty-tree halt auto-cleared — tree now clean",
      })
      # Finding 4.1: state-only auto-clear leaves the ledger halt incident dangling open forever.
      # Close it on the same axis so /error-list reflects reality once the tree settles.
      error_ledger.resolve(
        # waiver: daemon error/trigger token, not an internal key
        repo_root, f"halt:{repo_root.name}", resolution = "auto_recovered",
        kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.DAEMON,
      )
    # do not early-return on halt — routines with `ignore_halt: true` (typically the autonomous
    # doctor) still need to run so they can triage and fix whatever caused the halt; `due_routines`
    # filters out non-ignore_halt routines based on the `system_stuck` flag

  # reconcile the in-memory halt gauge with the on-disk block on every iteration: the gauge is a
  # set-only signal on the halt path, so a cleared halt (auto-recover above, external recover, or a
  # halt cleared before this reconcile shipped) otherwise stays pinned in Grafana until a restart.
  _reconcile_halt_metric(state)

  settings_path = repo_root / SettingsFile.REL
  daemon = load_section(settings_path, SettingsKey.DAEMON)
  registry = load_section(settings_path, SettingsKey.ROUTINES)
  registry.pop(SettingsKey.VERSION, None)
  last_run = state.setdefault(StateKey.LAST_RUN, {})

  # hourly cleanup — throttled via state so the floor on filesystem churn is independent of the
  # loop's polling interval
  mgr = _build_worktree_manager(repo_root, daemon.get(DaemonKey.GIT))
  last_cleanup = state.get(StateKey.LAST_CLEANUP_AT, 0)
  if time.time() - last_cleanup >= _CLEANUP_INTERVAL_SEC:
    # waiver: inline numeric/default literal, not a domain constant
    _cleanup_runtime_logs(repo_root, daemon.get(DaemonKey.CLEANUP_RUNTIME_LOG_AFTER, "30d"))
    # prune git worktree bookkeeping + remove crashed-task orphan dirs on the same hourly cadence;
    # `sweep` returns early (no-op) when no worktree root or git config is present
    if mgr is not None:
      try:
        mgr.sweep()
      except Exception as e:  # GAP C: orphan-sweep failure lands in the ledger, never crashes the iteration
        error_ledger.record(repo_root, {
          IncidentKey.INCIDENT: f"worktree:sweep/{repo_root.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
          IncidentKey.KIND: IncidentKind.WORKTREE_TASK_ERROR,
          IncidentKey.CAUSE: "sweep_failed",
          IncidentKey.ACTOR: IncidentActor.DAEMON,
          IncidentKey.DETAIL: str(e)[:200],
        })
    _maybe_prune_errors(repo_root)
    runtime_state.update(repo_root, lambda s: s.__setitem__(StateKey.LAST_CLEANUP_AT, time.time()))

  try:
    _git_pre(repo_root, daemon.get(DaemonKey.GIT))
  except GitPullDiverged as e:
    # waiver: daemon error/trigger token, not an internal key
    _halt_daemon(repo_root, state, HaltReason.GIT_PULL_DIVERGED, "_git_pre", str(e))
    return
  except Exception as e:
    _log_routine_result(repo_root, {
      TickResultKey.NAME: "_git_pre", TickResultKey.EXIT: -1, TickResultKey.DURATION_SEC: 0.0,
      TickResultKey.ERROR: f"git_pre failed: {e}",
    })
    # waiver: daemon error/trigger token, not an internal key
    _halt_daemon(repo_root, state, HaltReason.GIT_REMOTE_UNAVAILABLE, "_git_pre", str(e))
    return

  # pre-iteration tree check — daemon does NOT run routines while the working tree has uncommitted
  # changes; the operator may be mid-edit, or another process (a manual git op, a hand-run consumer
  # CLI) may be in flight. Either way, routines like `lazy-review.scan` would read the dirty file,
  # generate output from the WIP state, and commit over the operator's work. Skip silently — no
  # halt, no log spam — so the daemon resumes cleanly the next iteration after the tree settles.
  # EXCEPTION: routines with `ignore_halt: true` (the autonomous doctor) are explicitly designed to
  # triage stuck state and run anyway.
  pre_dirty = _check_working_tree(repo_root) is not None
  system_stuck = pre_dirty or (halt is not None)

  # poll in-flight worktree tasks BEFORE dispatching new work — a task whose dispatched job has
  # finished is integrated (merge / PR) and its worktree torn down, which frees a concurrency slot
  # for an `isolate: true` routine started later in this same iteration. No-op when the registry is
  # empty (the common, inert case for a direct-write-only daemon).
  if mgr is not None:
    _poll_worktree_tasks(repo_root, mgr)

  now = time.time()
  halted_this_iter = False
  for name, routine_cfg in due_routines(now, registry, last_run, system_stuck = system_stuck):
    # `isolate: true` routines run their unit of work on a dedicated task branch in an in-tree
    # worktree instead of writing directly. Route them to the manager; everything else stays on the
    # existing direct-write `dispatch_routine` path, completely unchanged.
    if routine_cfg.get(RoutineKey.ISOLATE) and mgr is not None:
      result = _start_isolated_task(mgr, name, routine_cfg)
      _log_routine_result(repo_root, result)
      # only advance last_run when the task actually started; at_capacity leaves it due so a later
      # tick retries once a slot frees
      if result.get(TickResultKey.EXIT) == 0:
        _advance_last_run(repo_root, name)
      continue
    result = dispatch_routine(repo_root, name, routine_cfg)
    _log_routine_result(repo_root, result)
    # a failed routine tick (any type) lands in the error ledger
    if result.get(TickResultKey.EXIT, 0) != 0 or result.get(TickResultKey.ERROR):
      detail = str(result.get(TickResultKey.ERROR, ""))
      cause = _classify_routine_error(detail)
      error_ledger.record(repo_root, {
        IncidentKey.INCIDENT: f"routine:{name}", IncidentKey.PHASE: IncidentPhase.OPENED,
        IncidentKey.KIND: IncidentKind.ROUTINE_ERROR,
        IncidentKey.CAUSE: cause, IncidentKey.ACTOR: IncidentActor.DAEMON,
        IncidentKey.ROUTINE: name, IncidentKey.DETAIL: detail[:200],
      })
      # GAP B closure: settings-invariant violation (e.g. `compute_inputs_failed` from a plugin CLI)
      # escalates to a class-1 halt so the operator hits the same `/lazy-runtime.recover` path that
      # handles git divergence / push failure. The routine_error already landed above for visibility.
      # waiver: daemon error/trigger token, not an internal key
      if cause == "config_violation":
        # waiver: daemon error/trigger token, not an internal key
        _halt_daemon(repo_root, state, "config_violation", name, detail[:200])
        halted_this_iter = True
        break
    _advance_last_run(repo_root, name)

    # tree was clean at iteration start; any dirt now is the routine's own output that didn't make
    # it into a commit — that's a contract violation and the daemon halts so the operator can
    # investigate. EXCEPTION: routines with `ignore_halt: true` (doctor) are explicitly designed
    # to handle stuck state — they may intentionally leave dirt (e.g. writing diagnosis.json for
    # human triage). Don't halt on their post-state, and don't re-halt if we're ALREADY in the
    # system-stuck branch (the halt block they're recovering from already exists).
    # guard: skip while halted, or when the routine ignores halt
    if system_stuck or routine_cfg.get(RoutineKey.IGNORE_HALT, False):
      continue
    post_dirty = _check_working_tree(repo_root)
    if post_dirty is not None:
      # do not overwrite an existing halt block — pump may have already written a more specific
      # one with expert + job_id attribution
      if StateKey.DAEMON_HALTED not in state:
        block = {
          HaltKey.HALTED_SINCE: time.time(),
          HaltKey.TRIGGERED_BY: name,
          HaltKey.REASON: HaltReason.UNCOMMITTED_CHANGES,
          "dirty_paths": post_dirty,
          "expert": None,
          "job_id": None,
        }
        # setdefault on the freshly-read state preserves a more-specific halt the pump may have written;
        # also mirror into the passed in-memory state so callers checking state[StateKey.DAEMON_HALTED] see it
        state[StateKey.DAEMON_HALTED] = block
        runtime_state.update(
          repo_root,
          # waiver: lambda captures the loop var `block`; each iteration persists it before the next, so the late binding is intentional
          lambda s: s.setdefault(StateKey.DAEMON_HALTED, block),  # noqa: B023  # pylint: disable=cell-var-from-loop
        )
        _emit_halt_metric_if_available(
          reason = HaltReason.UNCOMMITTED_CHANGES, triggered_by = name,
        )
      halted_this_iter = True
      break

  if not halted_this_iter:
    try:
      _git_post(repo_root, daemon.get(DaemonKey.GIT))
    except GitPushFailed as e:
      # waiver: daemon error/trigger token, not an internal key
      _halt_daemon(repo_root, state, HaltReason.GIT_PUSH_FAILED, "_git_post", str(e))
    except Exception as e:
      _log_routine_result(repo_root, {
        TickResultKey.NAME: "_git_post", TickResultKey.EXIT: -1, TickResultKey.DURATION_SEC: 0.0,
        TickResultKey.ERROR: f"git_post failed: {e}",
      })
      # waiver: daemon error/trigger token, not an internal key
      _halt_daemon(repo_root, state, HaltReason.GIT_REMOTE_UNAVAILABLE, "_git_post", str(e))

  # loop-detect — bound the cost of a buggy state machine that commits forever as the same bot;
  # cheap post-iteration scan: if the N most recent commits in the repo all share the same author
  # email AND that author is a registered bot (per `lazy.settings.json[experts]`), halt the daemon.
  # Threshold low enough that a real burst (~5 bot commits = ~8k sonnet output tokens) caps the
  # cost before a human shows up to investigate.
  if StateKey.DAEMON_HALTED not in state:
    _loop_detect_check(repo_root, state, settings_path)


def _build_worktree_manager(repo_root: Path, git_cfg: dict | None) -> WorktreeTaskManager | None:
  """
  Construct a worktree-task manager from the daemon's git configuration.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    git_cfg: Sub-section of `daemon.git` from `lazy.settings.json`, or `None` when git sync is off.

  Returns:
    A manager bound to `base_branch`, `worktree_root`, and `max_concurrent_tasks` from the git
    config, or `None` when no git config is present (the daemon then has no base branch to fork
    from and the worktree feature is inert).
  """
  # guard: no git config — worktree tasks need a base branch to fork from; feature stays inert
  if not git_cfg:
    return None
  return WorktreeTaskManager(
    repo_root,
    base_branch = git_cfg[GitConfigKey.BASE_BRANCH],
    # waiver: filesystem path idiom, not a domain constant
    worktree_root = git_cfg.get(GitConfigKey.WORKTREE_ROOT, ".worktrees"),
    # waiver: inline numeric/default literal, not a domain constant
    max_concurrent = int(git_cfg.get(GitConfigKey.MAX_CONCURRENT_TASKS, 3)),
  )


def _start_isolated_task(mgr: WorktreeTaskManager, name: str, cfg: dict) -> dict:
  """
  Start a worktree-isolated task for one due `isolate: true` routine.

  Args:
    mgr: The worktree-task manager bound to the daemon's repository.
    name: Registered routine name as it appears in `lazy.settings.json[routines]`.
    cfg: Routine configuration sub-section; `allow_merge` governs the reintegration path.

  Returns:
    A tick result dict. `exit = 0` with `work_id` when a worktree was created, or `exit = 0` with
    `note = "at_capacity"` when the concurrency cap left the work for a later tick. Failures set
    `exit = -1` and populate `error`. The work id is the routine name so each routine holds at most
    one live task; a task already in flight collides on the existing `task-<name>` branch and fails
    cleanly rather than spawning a duplicate.
  """
  started = time.time()
  try:
    outcome = mgr.start(
      routine = name, work_id = name, allow_merge = bool(cfg.get(WorktreeEntryKey.ALLOW_MERGE, False)),
    )
    # guard: concurrency cap reached — leave the routine due, retry on a later tick
    if outcome.get(WorktreeResultKey.RESULT) == WorktreeResult.AT_CAPACITY:
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: time.time() - started,
        TickResultKey.NOTE: WorktreeResult.AT_CAPACITY,
      }
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: time.time() - started,
      TickResultKey.WORK_ID: name, TickResultKey.BRANCH: outcome.get(WorktreeResultKey.BRANCH),
    }
  except Exception as e:  # broad catch — daemon must not die on a single task-start failure
    error_ledger.record(mgr.repo, {
      IncidentKey.INCIDENT: f"worktree:{name}/{name}", IncidentKey.PHASE: IncidentPhase.OPENED,
      IncidentKey.KIND: IncidentKind.WORKTREE_TASK_ERROR,
      IncidentKey.CAUSE: "start_failed", IncidentKey.ACTOR: IncidentActor.DAEMON,
      IncidentKey.ROUTINE: name, IncidentKey.DETAIL: str(e)[:200],
    })
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: -1, TickResultKey.DURATION_SEC: time.time() - started,
      TickResultKey.ERROR: f"worktree start failed: {e}",
    }


def _poll_worktree_tasks(repo_root: Path, mgr: WorktreeTaskManager) -> None:
  """
  Poll every registered worktree task and integrate the ones whose job has finished.

  A task is integrated only once its dispatched job reports `done` via `expert_runtime.collect_job`,
  and only when the registry entry carries a `job_id` — a task with no job id yet has nothing to
  poll (the trigger that fills the branch is out of scope here). On completion the manager merges or
  opens a pull request and tears the worktree down; the outcome is logged.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    mgr: The worktree-task manager bound to the daemon's repository.
  """
  state = runtime_state.load(repo_root)
  tasks = state.get(StateKey.WORKTREE_TASKS, {})
  # guard: no registered tasks — nothing to poll (the inert common case)
  if not tasks:
    return
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from expert_runtime import collect_job
  for work_id, entry in list(tasks.items()):
    job_id = entry.get(WorktreeEntryKey.JOB_ID)
    # guard: task has no dispatched job to poll yet
    if not job_id:
      continue
    try:
      outcome = collect_job(repo_root, entry.get(WorktreeEntryKey.ROUTINE) or work_id, job_id)
    except Exception as e:  # broad catch — one bad poll must not abort the others
      _log_routine_result(repo_root, {
        TickResultKey.NAME: "_worktree_poll", TickResultKey.EXIT: -1, TickResultKey.DURATION_SEC: 0.0,
        TickResultKey.ERROR: f"collect_job failed for {work_id}: {e}",
      })
      continue
    # guard: job still running — leave the task in flight
    if outcome.get(JobCollectKey.STATUS) != JobStatus.DONE:
      continue
    # waiver: small internal subkey, not a reusable domain key
    incident = f"worktree:{entry.get('routine') or work_id}/{work_id}"
    try:
      result = mgr.finish(work_id)
    except Exception as e:  # GAP C: a finish exception must not abort the poll loop / crash the daemon
      error_ledger.record(repo_root, {
        IncidentKey.INCIDENT: incident, IncidentKey.PHASE: IncidentPhase.OPENED,
        IncidentKey.KIND: IncidentKind.WORKTREE_TASK_ERROR,
        IncidentKey.CAUSE: "finish_failed",
        IncidentKey.ACTOR: IncidentActor.DAEMON,
        IncidentKey.ROUTINE: entry.get(WorktreeEntryKey.ROUTINE),
        IncidentKey.DETAIL: str(e)[:200],
      })
      continue
    _log_routine_result(repo_root, {
      TickResultKey.NAME: "_worktree_finish", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
      TickResultKey.WORK_ID: work_id, TickResultKey.OUTCOME: result.get(WorktreeResultKey.RESULT),
      TickResultKey.BRANCH: result.get(WorktreeResultKey.BRANCH),
    })
    # GAP C: non-integrated finish outcomes (PR could not open / lost work_id) land in the ledger
    if result.get(WorktreeResultKey.RESULT) in ( WorktreeResult.PR_DEFERRED, WorktreeResult.UNKNOWN ):
      error_ledger.record(repo_root, {
        IncidentKey.INCIDENT: incident, IncidentKey.PHASE: IncidentPhase.OPENED,
        IncidentKey.KIND: IncidentKind.WORKTREE_TASK_ERROR,
        IncidentKey.CAUSE: (
          WorktreeResult.PR_DEFERRED
          if result.get(WorktreeResultKey.RESULT) == WorktreeResult.PR_DEFERRED
          else "unknown_work_id"
        ),
        IncidentKey.ACTOR: IncidentActor.DAEMON, IncidentKey.ROUTINE: entry.get(WorktreeEntryKey.ROUTINE),
        IncidentKey.DETAIL: str(result.get(WorktreeResultKey.REASON, ""))[:200],
      })


def _plugin_roots() -> list[Path]:
  """
  Resolve the plugin source roots whose `.py` files the daemon watches for self-restart.

  Returns:
    The directories registered in `LAZYCORTEX_PLUGIN_DIRS` plus the running module's own parent,
    de-duplicated. The running module's parent is always included so the daemon notices changes to
    its own bin directory even when no dev-plugin dirs are configured.
  """
  roots: list[Path] = []
  env = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "")
  for part in env.split(os.pathsep):
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    part = part.strip()  # noqa: PLW2901
    if part:
      roots.append(Path(part).resolve())
  roots.append(Path(__file__).resolve().parent)
  # de-dup while preserving order
  seen: set[str] = set()
  out: list[Path] = []
  for r in roots:
    # guard: already collected this root
    if str(r) in seen:
      continue
    seen.add(str(r))
    out.append(r)
  return out


def _restart_in_place() -> None:
  """
  Restart the daemon process so it reloads its own updated source.

  Under a supervisor (`LAZYCORTEX_SUPERVISED=1`), exits cleanly so launchd / systemd relaunches the
  process with fresh code. Otherwise replaces the current process image with a fresh interpreter via
  `os.execv`, so the restart works even when no supervisor is present.

  Raises:
    SystemExit: When running under a supervisor — the supervisor owns the relaunch.
  """
  # guard: under a supervisor (systemd / launchd) — clean exit, it relaunches with fresh code
  if os.environ.get("LAZYCORTEX_SUPERVISED") == "1":
    raise SystemExit(0)
  # unsupervised — replace the process image with a fresh interpreter
  os.execv(sys.executable, [ sys.executable, *sys.argv ])


def _record_daemon_error(repo_root: Path, cause: str, e: Exception) -> None:
  """
  Best-effort daemon_error event for the GAP A guard family.

  Single helper so iteration / startup / loop-tail guards emit a uniform incident shape
  (`incident=daemon:<repo>`, `kind=daemon_error`, `actor=daemon`).

  Args:
    repo_root: Repository root the daemon is driving.
    cause: Closed-set cause; one of `internal_exception` / `startup_exception` / `loop_tail_exception`.
    e: The caught exception whose type and message land in `detail`.
  """
  error_ledger.record(repo_root, {
    IncidentKey.INCIDENT: f"daemon:{repo_root.name}", IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.DAEMON_ERROR,
    IncidentKey.CAUSE: cause, IncidentKey.ACTOR: IncidentActor.DAEMON,
    # waiver: reporting the type name of an arbitrary value; type(x).__name__ is the right idiom here — no class-system object
    IncidentKey.DETAIL: f"{type(e).__name__}: {e}",
    "refs": { "traceback": traceback.format_exc()[-500:] },
  })


def _run_iteration_guarded(repo_root: Path) -> None:
  """
  Run one daemon iteration; on any uncaught exception record `daemon_error` and survive.

  This is GAP A: without it, an exception anywhere in the iteration (dispatch, prune,
  loop-detect, worktree calls) crashes the daemon process with nothing in the ledger.

  Args:
    repo_root: Repository root the daemon is driving.
  """
  try:
    _run_iteration(repo_root)
  except Exception as e:  # GAP A: the daemon must never die silently on an internal exception
    # waiver: daemon error/trigger token, not an internal key
    _record_daemon_error(repo_root, "internal_exception", e)


def run(repo_root: Path) -> None:
  """
  Run the daemon's main loop against the given repository until terminated.

  Installs SIGTERM and SIGINT handlers, brings up metrics if configured, then iterates the routine
  schedule indefinitely, sleeping between iterations based on the next-due time and the configured
  polling interval.

  Notes:
    - When the daemon is halted, the loop sleeps for the polling interval directly to avoid a tight
      CPU loop driven by stale `last_run` timestamps.
    - The signal handlers set a stop flag that ends the loop after the current iteration completes.
    - When the daemon's own loaded source changes (detected by a stable two-read fingerprint), the
      process restarts at the iteration boundary so it picks up the new code.

  Args:
    repo_root: Absolute path to the repository the daemon should drive.
  """
  settings_path = repo_root / SettingsFile.REL
  stop = { "flag": False }
  signal.signal(signal.SIGTERM, lambda *_: stop.update(flag = True))
  signal.signal(signal.SIGINT, lambda *_: stop.update(flag = True))

  # GAP A: a startup failure (metrics bring-up, fingerprint snapshot, settings migration) must leave a
  # ledger trace rather than a silent dead daemon. The iteration body is guarded separately (#9).
  try:
    _init_metrics_if_enabled(repo_root)
    # snapshot the daemon's own loaded source so a later in-place update triggers a clean restart at an
    # iteration boundary; `changed()` only fires once a change is stable across two consecutive reads
    fp = CodeFingerprint(roots = _plugin_roots())
    fp.snapshot()
  except Exception as e:
    # waiver: daemon error/trigger token, not an internal key
    _record_daemon_error(repo_root, "startup_exception", e)
    raise

  # M5 / GAP A residual: the iteration body has its own guard, but the post-iteration tail
  # (self-restart check, settings reload, halt-state read, sleep-time compute) was bare. An
  # exception in fp.changed() / load_section / state.load would kill the daemon process with
  # nothing in the ledger. Wrap the same family so the daemon survives, falls back to a safe
  # polling sleep, and loops.
  # waiver: small internal subkey, not a reusable domain key
  while not stop["flag"]:
    _run_iteration_guarded(repo_root)
    sleep_s: float = 5.0   # safe default when the tail blows up
    try:
      # restart boundary — after the iteration completed and any commit landed; an own-code change
      # detected here means the loaded daemon source no longer matches disk. Skip while halted so a
      # restart never masks a halt the operator still needs to see and recover from.
      if not runtime_state.load(repo_root).get(StateKey.DAEMON_HALTED) and fp.changed():
        _log_routine_result(repo_root, {
          TickResultKey.NAME: "_self_restart", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
          "message": "restart: own code changed",
        })
        _restart_in_place()
      # compute sleep based on latest cfg + last_run state
      daemon = load_section(settings_path, SettingsKey.DAEMON)
      # waiver: inline numeric/default literal, not a domain constant
      polling = daemon.get(DaemonKey.POLLING_INTERVAL_SEC, 5)
      state = runtime_state.load(repo_root)
      if state.get(StateKey.DAEMON_HALTED):
        # when halted, `_run_iteration` returns immediately without touching `last_run`;
        # `compute_sleep` would otherwise see stale last_run timestamps + short intervals → return 0
        # → tight CPU loop. Sleep the polling floor directly so a halted daemon idles cleanly until
        # the operator runs /lazy-runtime.recover.
        sleep_s = polling
      else:
        registry = load_section(settings_path, SettingsKey.ROUTINES)
        registry.pop(SettingsKey.VERSION, None)
        last_run = state.get(StateKey.LAST_RUN, {})
        sleep_s = compute_sleep(
          time_until_next_due(time.time(), registry, last_run),
          polling,
        )
    # waiver: explicit SystemExit re-raise documents/guards propagation ahead of the broad `except Exception` below
    except SystemExit:  # pylint: disable=try-except-raise
      # guard: _restart_in_place raises SystemExit under a supervisor — propagate so it relaunches
      raise
    except Exception as e:  # M5: tail exception lands in the ledger; fall back to the safe-default sleep
      # waiver: daemon error/trigger token, not an internal key
      _record_daemon_error(repo_root, "loop_tail_exception", e)
    # sleep is intentionally outside the guard so a sleep-mock-raises-to-stop test idiom still works
    # and so a tail exception does not also swallow a SIGTERM-induced KeyboardInterrupt mid-sleep
    time.sleep(sleep_s)


def resolve_routine_command(cmd: list[str]) -> list[str]:
  """
  Resolve a `[plugin, *args]` command vector to a runnable `[bin_path, *args]` invocation.

  Consults dev-plugin source directories registered via `set_plugin_dirs` first, then falls back to
  the Claude Code plugin cache. When the cache holds multiple versions of the plugin, the latest is
  picked by lexicographic version-string ordering.

  Args:
    cmd: Routine command vector whose first element is the plugin name and the rest are arguments
      passed through unchanged.

  Returns:
    A new list where the first element is the resolved absolute path to the plugin's bin entrypoint
    and the remaining elements are the original arguments.

  Raises:
    FileNotFoundError: When the plugin is not present in any registered source directory or in the
      plugin cache, or when the resolved version has no bin entrypoint.
  """
  plugin = cmd[0]
  # dev-plugin paths take precedence over the plugin cache
  for pd in _PLUGIN_DIRS:
    bin_path = _resolve_in_plugin_dir(pd, plugin)
    if bin_path is not None:
      return [ str(bin_path), *cmd[1:] ]
  # waiver: filesystem path idiom, not a domain constant
  cache = Path.home() / ".claude/plugins/cache"
  # real layout: cache/<registry>/<plugin>/<version>/bin/<plugin>
  plugin_dirs: list[Path] = []
  if cache.is_dir():
    for registry in cache.iterdir():
      # guard: skip non-directory entries
      if not registry.is_dir():
        continue
      candidate = registry / plugin
      if candidate.is_dir():
        plugin_dirs.append(candidate)
  # guard: plugin missing from both dev-plugin paths and the cache
  if not plugin_dirs:
    raise FileNotFoundError(
      f"plugin not in cache and no matching --plugin-dir for: {plugin}"
    )
  # across all <registry>/<plugin> dirs, descend into versions and pick latest
  all_versions: list[Path] = []
  for pd in plugin_dirs:
    all_versions.extend(v for v in pd.iterdir() if v.is_dir())
  # guard: no version subdirectories present
  if not all_versions:
    raise FileNotFoundError(f"no versions cached for plugin: {plugin}")
  # lex-sort by version-string-name, take latest; caveat: lex sort works for single-digit majors —
  # revisit when 10.x ships (matches the deferred decision in reference_resolver)
  latest = sorted(all_versions, key = lambda v: v.name, reverse = True)[0]
  # waiver: filesystem path idiom, not a domain constant
  bin_path = latest / "bin" / plugin
  # guard: latest version has no bin entrypoint
  if not bin_path.exists():
    raise FileNotFoundError(f"no bin for plugin: {bin_path}")
  return [ str(bin_path), *cmd[1:] ]


def _run_git(repo_root: Path, args: list[str]) -> None:
  """
  Run a git command in the daemon repository and surface its stderr on failure.

  Args:
    repo_root: Absolute path to the repository the git command targets.
    args: Argument vector passed to the `git` executable (without the leading `git` token).

  Raises:
    subprocess.CalledProcessError: When the git invocation exits non-zero. Stderr is written to the
      daemon's standard error stream before the exception propagates.
  """
  try:
    subprocess.run([ "git", *args ], cwd = repo_root, check = True, capture_output = True)
  except subprocess.CalledProcessError as e:
    sys.stderr.write(f"git {' '.join(args)} failed:\n{e.stderr.decode()}\n")
    raise


def _run_git_capture(repo_root: Path, args: list[str]) -> str:
  """
  Run a git command in the daemon repository and return its stripped standard output.

  Used for `rev-parse` and `merge-base` calls where the daemon needs the resulting sha as a string.

  Args:
    repo_root: Absolute path to the repository the git command targets.
    args: Argument vector passed to the `git` executable (without the leading `git` token).

  Returns:
    The command's standard output with leading and trailing whitespace removed.

  Raises:
    subprocess.CalledProcessError: When the git invocation exits non-zero.
  """
  proc = subprocess.run(
    [ "git", *args ], cwd = repo_root, check = True, capture_output = True, text = True,
  )
  return proc.stdout.strip()


def _git_pre(repo_root: Path, git_cfg: dict | None) -> None:
  """
  Perform the daemon's pre-iteration git synchronization.

  Checks out the operator's base branch without resetting it, then optionally fast-forwards from the
  remote when settings request pull or pull/push. Divergent histories trigger an explicit halt path
  rather than a silent merge or rebase.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    git_cfg: Sub-section of `daemon.git` from `lazy.settings.json`, or `None` to disable sync.

  Raises:
    GitPullDiverged: When local `HEAD` and `origin/<base_branch>` have diverged — both sides carry
      commits the other does not.
    subprocess.CalledProcessError: When an underlying git invocation fails for any other reason.
  """
  # guard: git sync disabled
  if not git_cfg:
    return
  base_branch = git_cfg[GitConfigKey.BASE_BRANCH]
  # NOTE: plain checkout — NOT `-B`. The daemon now rides the operator's base branch and must never
  # reset it to HEAD; operator commits arrive via the ff-pull below.
  _run_git(repo_root, [ "checkout", base_branch ])
  # guard: remote sync not requested
  if git_cfg.get(GitConfigKey.REMOTE_SYNC) not in ( "pull", "pull_push" ):
    return
  _run_git(repo_root, [ "fetch", "origin", base_branch ])
  local = _run_git_capture(repo_root, [ "rev-parse", "HEAD" ])
  remote = _run_git_capture(repo_root, [ "rev-parse", f"origin/{base_branch}" ])
  # guard: already in sync
  if local == remote:
    return
  base = _run_git_capture(repo_root, [ "merge-base", "HEAD", f"origin/{base_branch}" ])
  # local is an ancestor of remote → fast-forward pull is safe (operator pushed ahead)
  if base == local:
    _run_git(repo_root, [ "pull", "--ff-only", "origin", base_branch ])
    return
  # remote is an ancestor of local → unpushed routine commits from a prior tick; _git_post pushes them
  if base == remote:
    return
  # otherwise histories diverged
  raise GitPullDiverged(
    f"local HEAD {local[:8]} and origin/{base_branch} {remote[:8]} have diverged"
  )


def _run_post_push_hook(repo_root: Path, git_cfg: dict, branch: str, old_sha: str) -> None:
  """
  Run the operator's post-push hook after a push that advanced the remote, isolated from daemon health.

  Executes the `daemon.git.post_push_hook` shell command with the push context exposed through
  `LAZY_PUSH_*` environment variables. Every failure mode — non-zero exit, timeout, spawn error — is
  caught and logged as a journal record; nothing propagates to the caller.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    git_cfg: Sub-section of `daemon.git` from `lazy.settings.json`.
    branch: The branch that was just pushed.
    old_sha: The `origin/<branch>` tip observed before the push.
  """
  cmd = git_cfg.get(GitConfigKey.POST_PUSH_HOOK)
  # guard: hook not configured
  if not cmd:
    return
  # waiver: blanket except is the isolation contract — the hook must never affect daemon health
  try:
    timeout = max(1, int(git_cfg.get(GitConfigKey.POST_PUSH_TIMEOUT_SEC, DEFAULT_POST_PUSH_TIMEOUT_SEC)))
    new_sha = _run_git_capture(repo_root, [ "rev-parse", "HEAD" ])
    env = {
      **os.environ,
      "LAZY_PUSH_REPO": str(repo_root),
      "LAZY_PUSH_BRANCH": branch,
      "LAZY_PUSH_REMOTE": "origin",
      "LAZY_PUSH_OLD_SHA": old_sha,
      "LAZY_PUSH_NEW_SHA": new_sha,
    }
    proc = subprocess.run(
      [ "sh", "-c", cmd ], cwd = repo_root, env = env, timeout = timeout,
      check = False, stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL,
    )
    # guard: hook failed — journal visibility only, no incident, no halt
    if proc.returncode != 0:
      _log_routine_result(repo_root, {
        TickResultKey.NAME: "_post_push_hook", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
        TickResultKey.ERROR: f"post-push hook exited {proc.returncode}",
      })
  except Exception as exc:
    _log_routine_result(repo_root, {
      TickResultKey.NAME: "_post_push_hook", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
      TickResultKey.ERROR: f"post-push hook failed: {exc}",
    })


def _git_post(repo_root: Path, git_cfg: dict | None) -> None:
  """
  Perform the daemon's post-iteration push, with conflict-aware retry.

  Fetches, compares local against origin, and either fast-forwards a push or rebases on top of new
  origin commits and re-pushes. A rebase conflict with operator commits is resolved by discarding
  the current tick's work and resetting to origin — the next tick re-runs the routine on the fresh
  operator state. After a push that advances the remote, the operator's post-push hook runs (see
  _run_post_push_hook).

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    git_cfg: Sub-section of `daemon.git` from `lazy.settings.json`, or `None` to disable push.

  Raises:
    GitPushFailed: When every retry attempt fails to publish the routine commit to
      `origin/<branch>`.
    subprocess.CalledProcessError: When an underlying git invocation fails outside the rebase /
      push retry paths.
  """
  # guard: git sync disabled
  if not git_cfg:
    return
  # guard: push not requested
  # waiver: daemon error/trigger token, not an internal key
  if git_cfg.get(GitConfigKey.REMOTE_SYNC) != "pull_push":
    return
  branch = git_cfg[GitConfigKey.BASE_BRANCH]

  for _attempt in range(POST_TICK_MAX_PUSH_ATTEMPTS):
    _run_git(repo_root, [ "fetch", "origin", branch ])
    local = _run_git_capture(repo_root, [ "rev-parse", "HEAD" ])
    remote = _run_git_capture(repo_root, [ "rev-parse", f"origin/{branch}" ])

    # guard: nothing to push, local and remote agree
    if local == remote:
      return

    base = _run_git_capture(repo_root, [ "merge-base", "HEAD", f"origin/{branch}" ])

    if base == remote:
      # local is strictly ahead of origin (no operator commits in the gap) → fast-forward push
      try:
        _run_git(repo_root, [ "push", "origin", branch ])
      except subprocess.CalledProcessError:
        # race: operator pushed between our fetch and our push; retry
        continue
      _run_post_push_hook(repo_root, git_cfg, branch, old_sha = remote)
      return

    if base == local:
      # origin moved forward but contains nothing of ours — our local HEAD became an ancestor of
      # origin between our fetch and now; extremely unlikely but possible if another process
      # already rebased + pushed for us. Just fall through to "no work".
      return

    # histories diverged within the tick (operator pushed a commit while the routine was running);
    # try to rebase our local commits onto the new origin tip
    try:
      _run_git(repo_root, [ "rebase", f"origin/{branch}" ])
    except subprocess.CalledProcessError:
      # conflict on rebase — operator's commits and ours touch the same content; abort the rebase,
      # hard-reset to origin (discarding this tick's work), log the discard, and let the next tick
      # re-run the routine on the fresh operator state
      _run_git(repo_root, [ "rebase", "--abort" ])
      _run_git(repo_root, [ "reset", "--hard", f"origin/{branch}" ])
      _log_routine_result(repo_root, {
        TickResultKey.NAME: "_git_post", TickResultKey.EXIT: 0, TickResultKey.DURATION_SEC: 0.0,
        TickResultKey.ERROR: "tick discarded: operator-conflict",
      })
      return

    # rebase clean — push the rebased commits
    try:
      _run_git(repo_root, [ "push", "origin", branch ])
    except subprocess.CalledProcessError:
      # race again: another operator push slid in between our rebase and our push; retry the whole
      # loop
      continue
    _run_post_push_hook(repo_root, git_cfg, branch, old_sha = remote)
    return

  raise GitPushFailed(
    f"push to origin/{branch} failed after {POST_TICK_MAX_PUSH_ATTEMPTS} attempts"
  )


def dispatch_subprocess(repo_root: Path, name: str, cfg: dict) -> dict:
  """
  Run a `type='subprocess'` routine on the current tick and produce its result record.

  Supports two sub-shapes that the validator enforces as exactly-one:
    - `command`: resolve the plugin binary, run it synchronously, return stdout/stderr tails plus
      exit code. The default historical shape.
    - `expert + request`: dispatch a single job to the named expert via `expert_runtime.dispatch_job`
      with `dedup_key` set to the routine name, so a still-active job from a prior tick blocks the
      next tick's re-queue.

  Lives here rather than in `routine_types` because the `command` path depends on the plugin-cache
  resolver, which is daemon-internal infrastructure.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    name: Registered routine name as it appears in `lazy.settings.json[routines]`.
    cfg: Routine configuration sub-section, carrying either `command` or `expert` + `request`.

  Returns:
    A result record with `name`, `exit`, `duration_sec`, and shape-specific fields. The `command`
    shape includes `stdout_tail` and `stderr_tail`; the `expert` shape includes `dispatched_count`.
    Failures populate an `error` field and set `exit` to `-1`.
  """
  started = time.time()

  if RoutineKey.EXPERT in cfg:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from expert_runtime import dispatch_job
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from routine_types import _routine_protocols, _resolve_cross_repo_target
    try:
      bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(
        Path(repo_root), cfg[RoutineKey.EXPERT]
      )
      result = dispatch_job(
        # waiver: small internal subkey, not a reusable domain key
        target_repo, bare_expert, dict(cfg["request"]),
        protocols = _routine_protocols(cfg),
        dedup_key = name,
        **xrepo_kwargs,
      )
      # waiver: small internal subkey, not a reusable domain key
      count = 0 if result.get("status") == "already-queued" else 1
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: 0,
        TickResultKey.DURATION_SEC: time.time() - started,
        "dispatched_count": count,
      }
    except Exception as e:
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: -1,
        TickResultKey.DURATION_SEC: time.time() - started,
        TickResultKey.ERROR: f"dispatch_job failed: {e}",
      }

  try:
    argv = resolve_routine_command(cfg[RoutineKey.COMMAND])
    timeout = cfg.get(RoutineKey.TIMEOUT_SEC, DEFAULT_TIMEOUT_SEC)
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from routine_types import routine_protocols_env
    subprocess_env = { **os.environ, **routine_protocols_env(cfg) }
    proc = subprocess.run(
      argv, cwd = repo_root, timeout = timeout,
      capture_output = True, text = True, env = subprocess_env, check = False,
    )
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: proc.returncode,
      TickResultKey.DURATION_SEC: time.time() - started,
      "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:],
    }
  except subprocess.TimeoutExpired:
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: -1,
      TickResultKey.DURATION_SEC: time.time() - started, TickResultKey.ERROR: "timeout",
    }
  except FileNotFoundError as e:
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: -1,
      TickResultKey.DURATION_SEC: time.time() - started, TickResultKey.ERROR: f"resolve: {e}",
    }
  except Exception as e:  # broad catch — daemon must not die on a single routine failure
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: -1,
      TickResultKey.DURATION_SEC: time.time() - started, TickResultKey.ERROR: f"unexpected: {e}",
    }


_DURATION_UNITS = { "s": 1, "m": 60, "h": 3600, "d": 86400 }


def _parse_duration(s: str) -> float:
  """
  Parse a short duration literal of the form `<number><unit>` into seconds.

  Args:
    s: Duration literal whose final character is one of `s`, `m`, `h`, or `d`, and whose prefix is a
      float-parseable number (e.g. `30d`, `1.5h`).

  Returns:
    The duration expressed in seconds.

  Raises:
    KeyError: When the final character is not a recognized unit.
    ValueError: When the numeric prefix is not parseable as a float.
  """
  return float(s[:-1]) * _DURATION_UNITS[s[-1]]


def _cleanup_runtime_logs(repo_root: Path, max_age: str) -> None:
  """
  Delete dated runtime log files older than the configured retention window.

  Notes:
    - Operates on `.logs/lazy-core/runtime/<date>.jsonl` files only.
    - `tokens.jsonl` is intentionally exempted because it has no date in its name and is rotated
      manually by operators.
    - Files removed by a concurrent cleanup are silently skipped.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    max_age: Retention duration as a short literal accepted by `_parse_duration` (e.g. `30d`).
  """
  # waiver: filesystem path idiom, not a domain constant
  log_dir = repo_root / ".logs/lazy-core/runtime"
  # guard: nothing to clean
  if not log_dir.exists():
    return
  threshold = time.time() - _parse_duration(max_age)
  for entry in os.listdir(log_dir):
    # guard: skip non-jsonl files
    # waiver: filesystem path idiom, not a domain constant
    if not entry.endswith(".jsonl"):
      continue
    # guard: skip the tokens log
    # waiver: filesystem path idiom, not a domain constant
    if entry == "tokens.jsonl":
      continue
    f = log_dir / entry
    try:
      if f.stat().st_mtime < threshold:
        f.unlink()
    except FileNotFoundError:  # raced with another cleanup
      continue


def _is_no_op_log(result: dict) -> bool:
  """
  Decide whether a routine result should be suppressed from the journal as a no-op.

  Short, successful routine ticks that did nothing notable do not deserve a journal entry. Every
  routine runs every few seconds in a healthy daemon; without this filter the jsonl would grow by
  roughly twelve thousand lines a day of repetitive no-ops, exceeding Obsidian's reasonable file-
  size guard.

  Args:
    result: Result record produced by `dispatch_subprocess` (or an equivalent routine path).

  Returns:
    True when the record represents a no-op that should be elided from the journal. False when the
    record has a non-zero exit, an error field, a duration above 1.5 seconds, or content signalling
    real activity (pump that processed or cleaned at least one job, dispatched count above zero,
    review tick whose actions include anything other than skips).
  """
  # guard: non-zero exit is always logged
  if result.get(TickResultKey.EXIT) != 0:
    return False
  # guard: any reported error is always logged
  if result.get(TickResultKey.ERROR):
    return False
  # guard: long runs are always logged
  if result.get(TickResultKey.DURATION_SEC, 0) > _QUIET_TICK_MAX_SEC:
    return False
  # waiver: small internal subkey, not a reusable domain key
  stdout = result.get("stdout_tail") or ""
  name = result.get(TickResultKey.NAME) or ""
  # waiver: external stdout-scan token, not an internal key
  if name == "lazy-expert.pump" and "processed=0" in stdout and "cleaned=0" in stdout:
    return True
  # waiver: external stdout-scan token, not an internal key
  if '"dispatched_count": 0' in stdout:
    return True
  if (
    # waiver: external stdout-scan token, not an internal key
    '"kind": "skip"' in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "dispatched"' not in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "banner-repaint"' not in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "main"' not in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "history"' not in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "section"' not in stdout
    # waiver: external stdout-scan token, not an internal key
    and '"kind": "final"' not in stdout
  ):
    return True
  return False


def _log_routine_result(repo_root: Path, result: dict) -> None:
  """
  Append a routine result record to the daemon's daily journal and emit tick metrics.

  Notes:
    - Records classified as no-ops by `_is_no_op_log` are not written to the journal but still
      contribute to tick metrics so observability remains accurate.
    - The journal file path is `.logs/lazy-core/runtime/<UTC-date>.jsonl`.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    result: Result record produced by a routine dispatch.
  """
  if _is_no_op_log(result):
    # metrics still record the tick (zero-duration latency, no error); observability stays accurate
    # without journal spam
    _emit_tick_metrics_if_available(repo_root, result)
    return
  # waiver: filesystem path idiom, not a domain constant
  log_dir = repo_root / ".logs/lazy-core/runtime"
  log_dir.mkdir(parents = True, exist_ok = True)
  log_file = log_dir / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
  record = { "ts": time.time(), **result }
  # waiver: stdlib idiom, not a domain constant
  with log_file.open("a") as f:
    f.write(json.dumps(record) + "\n")
  _emit_tick_metrics_if_available(repo_root, result)


def _emit_tick_metrics_if_available(repo_root: Path, result: dict) -> None:
  """
  Record tick, queue-depth, and token-aggregation metrics when the metrics module is enabled.

  Notes:
    - The metrics module is opt-in; when it is not installed or not enabled, the call returns
      without observable cost so a disabled daemon pays no overhead here.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    result: Result record produced by a routine dispatch.
  """
  try:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import metrics
  except ImportError:
    return
  # guard: metrics disabled
  if not metrics.is_enabled():
    return
  metrics.record_tick(
    routine = result.get(TickResultKey.NAME) or "unknown",
    exit_code = int(result.get(TickResultKey.EXIT, 0)),
    duration_sec = float(result.get(TickResultKey.DURATION_SEC, 0.0)),
    error = result.get(TickResultKey.ERROR),
  )
  metrics.set_queue_depth_from_filesystem(repo_root)
  metrics.aggregate_tokens_from_log(repo_root)


if __name__ == "__main__":
  run(Path(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
