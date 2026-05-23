"""
Generic per-repo serial runtime daemon.

Drives one repository's routine schedule on a single timeline. Routines registered in `lazy.settings.json`
are evaluated each iteration; eligible ones dispatch sequentially, log their result, and update last-run
state. Health is guarded by pre-iteration git sync, post-iteration push, dirty-tree skip, and loop
detection on bot-author commits. Retry policy lives in routine implementations, not in the daemon.
"""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path
from typing import Iterable
from lazy_settings import load_section
import runtime_state
from routine_types import dispatch_routine

# default per-routine subprocess timeout; overridable per-routine via routines[<name>].timeout_sec
DEFAULT_TIMEOUT_SEC = 300
POST_TICK_MAX_PUSH_ATTEMPTS = 3


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
  global _PLUGIN_DIRS
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
  manifest = plugin_dir / ".claude-plugin" / "plugin.json"
  try:
    data = json.loads(manifest.read_text())
  except (FileNotFoundError, json.JSONDecodeError):
    return None
  # guard: directory's manifest names a different plugin
  if data.get("name") != plugin_name:
    return None
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
  plugin_json = here.parent / ".claude-plugin" / "plugin.json"
  try:
    return json.loads(plugin_json.read_text())["version"]
  except (FileNotFoundError, KeyError, json.JSONDecodeError):
    return "unknown"


def _init_metrics_if_enabled(repo_root: Path) -> None:
  """
  Bring up the metrics endpoint when settings turn it on.

  Reads daemon settings once before the main loop starts. Metrics initialization is one-shot — the
  operator must restart the daemon to flip enablement on or off, even though the routine registry
  itself is hot-reloaded inside the loop.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.

  Notes:
    - When metrics are disabled in settings, the call returns without side effects.
    - When enabled, the metrics module is loaded, initialized with the resolved labels, and exposed
      on the configured bind address and port.
  """
  settings_path = repo_root / ".claude/lazy.settings.json"
  daemon = load_section(settings_path, "daemon")
  metrics_cfg = daemon.get("metrics", {})
  # guard: metrics opt-in not set
  if not metrics_cfg.get("enabled"):
    return
  import metrics
  repo_label = metrics.resolve_repo_label(repo_root, metrics_cfg.get("repo_label"))
  metrics.init(
    repo_label = repo_label,
    version = _read_plugin_version(),
    daemon_name = metrics_cfg.get("daemon_name") or "lazycortex-runtime",
  )
  metrics.expose(
    bind = metrics_cfg.get("bind", "127.0.0.1"),
    port = int(metrics_cfg.get("port", 9464)),
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
    if system_stuck and not cfg.get("ignore_halt", False):
      continue
    if cfg.get("type") == "schedule":
      from routine_types import due_for_schedule
      if due_for_schedule(name, cfg, now, last_run.get(name, 0)):
        out.append((name, cfg))
    else:
      if now - last_run.get(name, 0) >= cfg.get("interval_sec", 5):
        out.append((name, cfg))
  out.sort(key = lambda item: item[1].get("priority", 100))
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
    if cfg.get("type") == "schedule":
      # schedule routines wake up to be re-checked on each tick; the daemon's polling_interval_sec
      # floor keeps the loop honest
      candidates.append(60.0)
    else:
      candidates.append(last_run.get(n, 0) + cfg.get("interval_sec", 5) - now)
  return min(candidates) if candidates else float("inf")


LOOP_DETECT_THRESHOLD = 5
"""
Threshold for the consecutive-bot-commit halt rule.

Halt when this many of the most recent commits share the same bot author email. Sized so a busted
state machine caps its damage at a few sonnet spawns before a human shows up. Overridable via
`daemon.loop_detect_threshold` in settings.
"""


def _loop_detect_check(
  repo_root: Path,
  state: dict,
  settings_path: Path,
) -> None:
  """
  Run the post-iteration loop-detect safety net against recent commit history.

  Halts the daemon when the most recent N commits share the same bot identity, where N is the
  configured threshold. Bot identities are resolved from `experts.<name>.git_author.email` in
  `lazy.settings.json`; operator commits never trigger the rule because humans are not in the
  experts table.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    state: In-memory copy of the daemon's persisted state, mutated in place when a halt is recorded.
    settings_path: Absolute path to `lazy.settings.json`.

  Notes:
    - Skipped when not in a git repo, when fewer than threshold commits exist, when the threshold is
      set below 2, or when no experts are registered.
    - The check costs a single `git log -N --format=%ae` invocation.
  """
  daemon = load_section(settings_path, "daemon")
  threshold = int(daemon.get("loop_detect_threshold", LOOP_DETECT_THRESHOLD))
  # guard: rule disabled via configuration
  if threshold < 2:
    return
  # noinspection PyBroadException
  try:
    experts = load_section(settings_path, "experts")
  except Exception:
    return
  bot_emails: set[str] = set()
  for name, entry in experts.items():
    if name == "_version" or not isinstance(entry, dict):
      continue
    email = ((entry.get("git_author") or {}).get("email") or "").strip()
    if email:
      bot_emails.add(email)
  # guard: no registered bot authors to attribute commits to
  if not bot_emails:
    return
  try:
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "log",
        f"-{threshold}", "--format=%ae" ],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
  except FileNotFoundError:
    return
  # guard: git invocation failed
  if rc.returncode != 0:
    return
  emails = [ line.strip() for line in rc.stdout.splitlines() if line.strip() ]
  # guard: not enough commits yet to evaluate the rule
  if len(emails) < threshold:
    return
  # guard: recent commits are not all by the same author
  if not all(e == emails[0] for e in emails):
    return
  # guard: shared author is an operator, not a registered bot
  if emails[0] not in bot_emails:
    return
  # all N most recent commits are by the same bot — assume loop
  _halt_daemon(
    repo_root, state, "suspected_loop",
    "_loop_detect",
    f"last {threshold} commits all by {emails[0]!r}",
  )


def _check_working_tree(repo_root: Path) -> list[str] | None:
  """
  Inspect the daemon repository's working tree for uncommitted changes.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.

  Returns:
    A list of dirty `git status --porcelain` lines, capped at 50 entries with the last one replaced
    by a truncation sentinel when more dirt exists. Returns `None` when the tree is clean, when git
    is unavailable, or when the path is not a git repository.

  Notes:
    - Uses `--no-optional-locks` so the stat-cache refresh does not race the index lock — the dirty-
      tree check runs every daemon iteration and without this flag would grab the lock dozens of
      times per minute.
  """
  try:
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never",
        "status", "--porcelain" ],
      cwd = str(repo_root), capture_output = True, text = True,
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
  if len(lines) > 50:
    lines = lines[:50] + [ "... (truncated, more dirty paths exist)" ]
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

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    state: In-memory copy of the daemon's persisted state, mutated in place.
    reason: Halt-reason code (e.g. `uncommitted_changes`, `git_pull_diverged`, `suspected_loop`).
    triggered_by: Routine or internal step that surfaced the halt condition.
    detail: Human-readable description routed into the routine log entry.

  Notes:
    - When a halt block already exists, the existing entry is preserved — earlier halts with more-
      specific attribution (e.g. expert + job_id) are never clobbered.
  """
  _log_routine_result(repo_root, {
    "name": triggered_by, "exit": -1, "duration_sec": 0.0,
    "error": f"{reason}: {detail}",
  })
  # guard: keep the earlier, more-specific halt attribution
  if "daemon_halted" in state:
    return
  state["daemon_halted"] = {
    "halted_since": time.time(),
    "triggered_by": triggered_by,
    "reason": reason,
    "dirty_paths": [],
    "expert": None,
    "job_id": None,
  }
  runtime_state.save(repo_root, state)
  _emit_halt_metric_if_available(reason = reason, triggered_by = triggered_by)


def _emit_halt_metric_if_available(reason: str, triggered_by: str) -> None:
  """
  Record a halt to the metrics module when available and enabled.

  Args:
    reason: Halt-reason code matching the `daemon_halted.reason` field.
    triggered_by: Routine or internal step that surfaced the halt condition.

  Notes:
    - The metrics module is an optional dependency; an import failure is silently absorbed so the
      observability subsystem and the halt path stay independent.
  """
  try:
    import metrics
    if metrics.is_enabled():
      metrics.record_daemon_halt(reason = reason, triggered_by = triggered_by)
  except ImportError:
    pass


def _run_iteration(repo_root: Path) -> None:
  """
  Execute one full iteration of the daemon's main loop.

  Loads persisted state and settings, performs pre-iteration git sync, dispatches every due routine
  in priority order, performs post-iteration git push, and runs the loop-detect safety net. Idempotent
  on `state.json`, providing a clean test seam.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.

  Notes:
    - When the daemon is halted with `uncommitted_changes` and the tree has become clean, the halt
      is auto-cleared at the start of the iteration.
    - Routines flagged `ignore_halt: true` (typically the autonomous doctor) run even while the
      system is stuck so they can triage and fix the halt condition.
    - When a routine leaves the tree dirty in a non-stuck system, the daemon records a halt and
      stops dispatching for the remainder of the iteration.
  """
  state = runtime_state.load(repo_root)
  halt = state.get("daemon_halted")
  if halt:
    # auto-clear dirty-tree halt as soon as the tree becomes clean; other halt reasons
    # (git_pull_diverged / git_push_failed / git_remote_unavailable) require human investigation
    # and stay until /lazy-runtime.recover
    if halt.get("reason") == "uncommitted_changes" and _check_working_tree(repo_root) is None:
      state.pop("daemon_halted")
      halt = None
      runtime_state.save(repo_root, state)
      _log_routine_result(repo_root, {
        "name": "_auto_recover", "exit": 0, "duration_sec": 0.0,
        "message": "dirty-tree halt auto-cleared — tree now clean",
      })
    # do not early-return on halt — routines with `ignore_halt: true` (typically the autonomous
    # doctor) still need to run so they can triage and fix whatever caused the halt; `due_routines`
    # filters out non-ignore_halt routines based on the `system_stuck` flag

  settings_path = repo_root / ".claude/lazy.settings.json"
  daemon = load_section(settings_path, "daemon")
  registry = load_section(settings_path, "routines")
  registry.pop("_version", None)
  last_run = state.setdefault("last_run", {})

  # hourly cleanup — throttled via state so the floor on filesystem churn is independent of the
  # loop's polling interval
  last_cleanup = state.get("last_cleanup_at", 0)
  if time.time() - last_cleanup >= 3600:
    _cleanup_runtime_logs(repo_root, daemon.get("cleanup_runtime_log_after", "30d"))
    state["last_cleanup_at"] = time.time()
    runtime_state.save(repo_root, state)

  try:
    _git_pre(repo_root, daemon.get("git"))
  except GitPullDiverged as e:
    _halt_daemon(repo_root, state, "git_pull_diverged", "_git_pre", str(e))
    return
  except Exception as e:
    _log_routine_result(repo_root, {
      "name": "_git_pre", "exit": -1, "duration_sec": 0.0,
      "error": f"git_pre failed: {e}",
    })
    _halt_daemon(repo_root, state, "git_remote_unavailable", "_git_pre", str(e))
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

  now = time.time()
  halted_this_iter = False
  for name, routine_cfg in due_routines(now, registry, last_run, system_stuck = system_stuck):
    result = dispatch_routine(repo_root, name, routine_cfg)
    _log_routine_result(repo_root, result)
    last_run[name] = time.time()
    runtime_state.save(repo_root, state)

    # tree was clean at iteration start; any dirt now is the routine's own output that didn't make
    # it into a commit — that's a contract violation and the daemon halts so the operator can
    # investigate. EXCEPTION: routines with `ignore_halt: true` (doctor) are explicitly designed
    # to handle stuck state — they may intentionally leave dirt (e.g. writing diagnosis.json for
    # human triage). Don't halt on their post-state, and don't re-halt if we're ALREADY in the
    # system-stuck branch (the halt block they're recovering from already exists).
    if system_stuck or routine_cfg.get("ignore_halt", False):
      continue
    post_dirty = _check_working_tree(repo_root)
    if post_dirty is not None:
      # do not overwrite an existing halt block — pump may have already written a more specific
      # one with expert + job_id attribution
      if "daemon_halted" not in state:
        state["daemon_halted"] = {
          "halted_since": time.time(),
          "triggered_by": name,
          "reason": "uncommitted_changes",
          "dirty_paths": post_dirty,
          "expert": None,
          "job_id": None,
        }
        runtime_state.save(repo_root, state)
        _emit_halt_metric_if_available(
          reason = "uncommitted_changes", triggered_by = name,
        )
      halted_this_iter = True
      break

  if not halted_this_iter:
    try:
      _git_post(repo_root, daemon.get("git"))
    except GitPushFailed as e:
      _halt_daemon(repo_root, state, "git_push_failed", "_git_post", str(e))
    except Exception as e:
      _log_routine_result(repo_root, {
        "name": "_git_post", "exit": -1, "duration_sec": 0.0,
        "error": f"git_post failed: {e}",
      })
      _halt_daemon(repo_root, state, "git_remote_unavailable", "_git_post", str(e))

  # loop-detect — bound the cost of a buggy state machine that commits forever as the same bot;
  # cheap post-iteration scan: if the N most recent commits in the repo all share the same author
  # email AND that author is a registered bot (per `lazy.settings.json[experts]`), halt the daemon.
  # Threshold low enough that a real burst (~5 bot commits = ~8k sonnet output tokens) caps the
  # cost before a human shows up to investigate.
  if "daemon_halted" not in state:
    _loop_detect_check(repo_root, state, settings_path)


def run(repo_root: Path) -> None:
  """
  Run the daemon's main loop against the given repository until terminated.

  Installs SIGTERM and SIGINT handlers, brings up metrics if configured, then iterates the routine
  schedule indefinitely, sleeping between iterations based on the next-due time and the configured
  polling interval.

  Args:
    repo_root: Absolute path to the repository the daemon should drive.

  Notes:
    - When the daemon is halted, the loop sleeps for the polling interval directly to avoid a tight
      CPU loop driven by stale `last_run` timestamps.
    - The signal handlers set a stop flag that ends the loop after the current iteration completes.
  """
  settings_path = repo_root / ".claude/lazy.settings.json"
  stop = { "flag": False }
  signal.signal(signal.SIGTERM, lambda *_: stop.update(flag = True))
  signal.signal(signal.SIGINT, lambda *_: stop.update(flag = True))

  _init_metrics_if_enabled(repo_root)

  while not stop["flag"]:
    _run_iteration(repo_root)
    # compute sleep based on latest cfg + last_run state
    daemon = load_section(settings_path, "daemon")
    polling = daemon.get("polling_interval_sec", 5)
    state = runtime_state.load(repo_root)
    if state.get("daemon_halted"):
      # when halted, `_run_iteration` returns immediately without touching `last_run`;
      # `compute_sleep` would otherwise see stale last_run timestamps + short intervals → return 0
      # → tight CPU loop. Sleep the polling floor directly so a halted daemon idles cleanly until
      # the operator runs /lazy-runtime.recover.
      time.sleep(polling)
      continue
    registry = load_section(settings_path, "routines")
    registry.pop("_version", None)
    last_run = state.get("last_run", {})
    sleep_s = compute_sleep(
      time_until_next_due(time.time(), registry, last_run),
      polling,
    )
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
  cache = Path.home() / ".claude/plugins/cache"
  # real layout: cache/<registry>/<plugin>/<version>/bin/<plugin>
  plugin_dirs: list[Path] = []
  if cache.is_dir():
    for registry in cache.iterdir():
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
  all_versions = []
  for pd in plugin_dirs:
    all_versions.extend(v for v in pd.iterdir() if v.is_dir())
  # guard: no version subdirectories present
  if not all_versions:
    raise FileNotFoundError(f"no versions cached for plugin: {plugin}")
  # lex-sort by version-string-name, take latest; caveat: lex sort works for single-digit majors —
  # revisit when 10.x ships (matches the deferred decision in reference_resolver)
  latest = sorted(all_versions, key = lambda v: v.name, reverse = True)[0]
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

  Resets the daemon's exclusive branch to current `HEAD`, then optionally fast-forwards from the
  remote when settings request pull or pull/push. Divergent histories trigger an explicit halt path
  rather than a silent merge or rebase.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    git_cfg: Sub-section of `daemon.git` from `lazy.settings.json`, or `None` to disable sync.

  Raises:
    GitPullDiverged: When local `HEAD` and `origin/<branch>` have diverged — both sides carry
      commits the other does not.
    subprocess.CalledProcessError: When an underlying git invocation fails for any other reason.
  """
  # guard: git sync disabled
  if not git_cfg:
    return
  branch = git_cfg["branch"]
  # `-B` is intentional: the daemon's branch is reset to current HEAD each iteration; the branch is
  # daemon-exclusive (per daemon.git.branch contract)
  _run_git(repo_root, [ "checkout", "-B", branch ])
  # guard: remote sync not requested
  if git_cfg.get("remote_sync") not in ("pull", "pull_push"):
    return
  # explicit `origin <branch>` everywhere — `git checkout -B` does not set upstream tracking, so
  # bare commands would fail on "no tracking information"
  _run_git(repo_root, [ "fetch", "origin", branch ])
  local = _run_git_capture(repo_root, [ "rev-parse", "HEAD" ])
  remote = _run_git_capture(repo_root, [ "rev-parse", f"origin/{branch}" ])
  # guard: already in sync, nothing to pull
  if local == remote:
    return
  base = _run_git_capture(repo_root, [ "merge-base", "HEAD", f"origin/{branch}" ])
  if base == local:
    # local is an ancestor of remote → fast-forward pull is safe
    _run_git(repo_root, [ "pull", "--ff-only", "origin", branch ])
    return
  if base == remote:
    # remote is an ancestor of local — we carry unpushed local commits (e.g. previous tick's
    # `_git_post` push got blocked); no pull needed, the next `_git_post` will rebase + push these
    # forward
    return
  # otherwise: histories diverged — both sides have commits the other doesn't
  raise GitPullDiverged(
    f"local HEAD {local[:8]} and origin/{branch} {remote[:8]} have diverged"
  )


def _git_post(repo_root: Path, git_cfg: dict | None) -> None:
  """
  Perform the daemon's post-iteration push, with conflict-aware retry.

  Fetches, compares local against origin, and either fast-forwards a push or rebases on top of new
  origin commits and re-pushes. A rebase conflict with operator commits is resolved by discarding
  the current tick's work and resetting to origin — the next tick re-runs the routine on the fresh
  operator state.

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
  if git_cfg.get("remote_sync") != "pull_push":
    return
  branch = git_cfg["branch"]

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
        return
      except subprocess.CalledProcessError:
        # race: operator pushed between our fetch and our push; retry
        continue

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
        "name": "_git_post", "exit": 0, "duration_sec": 0.0,
        "error": "tick discarded: operator-conflict",
      })
      return

    # rebase clean — push the rebased commits
    try:
      _run_git(repo_root, [ "push", "origin", branch ])
      return
    except subprocess.CalledProcessError:
      # race again: another operator push slid in between our rebase and our push; retry the whole
      # loop
      continue

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

  if "expert" in cfg:
    from expert_runtime import dispatch_job
    from routine_types import _routine_protocols, _resolve_cross_repo_target
    try:
      bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(
        Path(repo_root), cfg["expert"]
      )
      result = dispatch_job(
        target_repo, bare_expert, dict(cfg["request"]),
        protocols = _routine_protocols(cfg),
        dedup_key = name,
        **xrepo_kwargs,
      )
      count = 0 if result.get("status") == "already-queued" else 1
      return {
        "name": name, "exit": 0,
        "duration_sec": time.time() - started,
        "dispatched_count": count,
      }
    except Exception as e:
      return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "error": f"dispatch_job failed: {e}",
      }

  try:
    argv = resolve_routine_command(cfg["command"])
    timeout = cfg.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
    from routine_types import routine_protocols_env
    subprocess_env = { **os.environ, **routine_protocols_env(cfg) }
    proc = subprocess.run(
      argv, cwd = repo_root, timeout = timeout,
      capture_output = True, text = True, env = subprocess_env,
    )
    return {
      "name": name, "exit": proc.returncode, "duration_sec": time.time() - started,
      "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:],
    }
  except subprocess.TimeoutExpired:
    return { "name": name, "exit": -1, "duration_sec": time.time() - started, "error": "timeout" }
  except FileNotFoundError as e:
    return { "name": name, "exit": -1, "duration_sec": time.time() - started, "error": f"resolve: {e}" }
  except Exception as e:  # broad catch — daemon must not die on a single routine failure
    return { "name": name, "exit": -1, "duration_sec": time.time() - started, "error": f"unexpected: {e}" }


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

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    max_age: Retention duration as a short literal accepted by `_parse_duration` (e.g. `30d`).

  Notes:
    - Operates on `.logs/lazy-core/runtime/<date>.jsonl` files only.
    - `tokens.jsonl` is intentionally exempted because it has no date in its name and is rotated
      manually by operators.
    - Files removed by a concurrent cleanup are silently skipped.
  """
  log_dir = repo_root / ".logs/lazy-core/runtime"
  # guard: nothing to clean
  if not log_dir.exists():
    return
  threshold = time.time() - _parse_duration(max_age)
  import os
  for entry in os.listdir(log_dir):
    if not entry.endswith(".jsonl"):
      continue
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
  if result.get("exit") != 0:
    return False
  # guard: any reported error is always logged
  if result.get("error"):
    return False
  # guard: long runs are always logged
  if result.get("duration_sec", 0) > 1.5:
    return False
  stdout = result.get("stdout_tail") or ""
  name = result.get("name") or ""
  if name == "lazy-expert.pump" and "processed=0" in stdout and "cleaned=0" in stdout:
    return True
  if '"dispatched_count": 0' in stdout:
    return True
  if (
    '"kind": "skip"' in stdout
    and '"kind": "dispatched"' not in stdout
    and '"kind": "banner-repaint"' not in stdout
    and '"kind": "main"' not in stdout
    and '"kind": "history"' not in stdout
    and '"kind": "section"' not in stdout
    and '"kind": "final"' not in stdout
  ):
    return True
  return False


def _log_routine_result(repo_root: Path, result: dict) -> None:
  """
  Append a routine result record to the daemon's daily journal and emit tick metrics.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    result: Result record produced by a routine dispatch.

  Notes:
    - Records classified as no-ops by `_is_no_op_log` are not written to the journal but still
      contribute to tick metrics so observability remains accurate.
    - The journal file path is `.logs/lazy-core/runtime/<UTC-date>.jsonl`.
  """
  if _is_no_op_log(result):
    # metrics still record the tick (zero-duration latency, no error); observability stays accurate
    # without journal spam
    _emit_tick_metrics_if_available(repo_root, result)
    return
  log_dir = repo_root / ".logs/lazy-core/runtime"
  log_dir.mkdir(parents = True, exist_ok = True)
  log_file = log_dir / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
  record = { "ts": time.time(), **result }
  with log_file.open("a") as f:
    f.write(json.dumps(record) + "\n")
  _emit_tick_metrics_if_available(repo_root, result)


def _emit_tick_metrics_if_available(repo_root: Path, result: dict) -> None:
  """
  Record tick, queue-depth, and token-aggregation metrics when the metrics module is enabled.

  Args:
    repo_root: Absolute path to the repository the daemon is driving.
    result: Result record produced by a routine dispatch.

  Notes:
    - The metrics module is opt-in; when it is not installed or not enabled, the call returns
      without observable cost so a disabled daemon pays no overhead here.
  """
  try:
    import metrics
  except ImportError:
    return
  # guard: metrics disabled
  if not metrics.is_enabled():
    return
  metrics.record_tick(
    routine = result.get("name") or "unknown",
    exit_code = int(result.get("exit", 0)),
    duration_sec = float(result.get("duration_sec", 0.0)),
    error = result.get("error"),
  )
  metrics.set_queue_depth_from_filesystem(repo_root)
  metrics.aggregate_tokens_from_log(repo_root)


if __name__ == "__main__":
  run(Path(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
