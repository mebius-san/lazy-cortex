"""Generic per-repo serial runtime daemon.

# retry policy lives in routine implementations (e.g. expert-pump), not in the daemon
"""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path
from typing import Iterable
from lazy_settings import load_section
import runtime_state
from routine_types import dispatch_routine

DEFAULT_TIMEOUT_SEC = 300
POST_TICK_MAX_PUSH_ATTEMPTS = 3


class GitPullDiverged(RuntimeError):
    """Pre-tick: local HEAD and origin/<branch> have a common ancestor that
    is neither — i.e. both sides have commits the other does not. The daemon's
    branch is supposed to be exclusive to the daemon, so this should not happen
    in normal operation. Recovering automatically (rebase / merge / reset) is
    unsafe — could drop the operator's commits — so we halt and let the human
    resolve."""


class GitPushFailed(RuntimeError):
    """Post-tick: push to origin/<branch> failed after every retry. Either the
    operator is pushing continuously into the same branch (rare, points at a
    deeper coordination bug), or push is refused for non-race reasons (auth,
    force-protection, permission). Either way, requires human intervention."""

# Set by `set_plugin_dirs`. When non-empty, `resolve_routine_command` consults
# these paths first (each is a plugin source dir containing `.claude-plugin/`
# and `bin/`) and falls back to the plugin cache if no match. This mirrors
# Claude Code's `--plugin-dir` for the daemon's separate-process world: a
# dev-vault operator points the daemon at the source plugins they're working
# on, instead of routing through a cached install.
_PLUGIN_DIRS: list[Path] = []


def set_plugin_dirs(dirs: list[Path]) -> None:
    global _PLUGIN_DIRS
    _PLUGIN_DIRS = [Path(d).resolve() for d in dirs]
    # Also export to the environment so subprocess routines
    # (`lazycortex-core expert-pump-once`, `lazycortex-review tick`, …)
    # inherit the dev-plugin paths and their own resolvers — most notably
    # `reference_resolver.resolve` for `<plugin>:<name>` agent / protocol /
    # aspect refs — can match them. Arguments are not ref-resolved (pass-through
    # JSON values), but flow through to <jdir>/config.json the same way.
    # Daemon-internal `resolve_routine_command`
    # uses `_PLUGIN_DIRS` directly; this env handle is for everyone else.
    os.environ["LAZYCORTEX_PLUGIN_DIRS"] = os.pathsep.join(str(p) for p in _PLUGIN_DIRS)


def _resolve_in_plugin_dir(plugin_dir: Path, plugin_name: str) -> Path | None:
    """Match a plugin source dir against `plugin_name` (looked up from the
    dir's `plugin.json` "name" field) and return its bin entrypoint, or None
    on no match. Bin entrypoint resolution: prefer `bin/<plugin-name>`; fall
    back to the single executable script under `bin/`. Multiple executables
    → ambiguous, returns None so the caller can keep searching."""
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if data.get("name") != plugin_name:
        return None
    bin_dir = plugin_dir / "bin"
    if not bin_dir.is_dir():
        return None
    primary = bin_dir / plugin_name
    if primary.is_file() and os.access(primary, os.X_OK):
        return primary
    execs = [
        p for p in bin_dir.iterdir()
        if p.is_file()
        and not p.name.endswith(".py")
        and not p.name.startswith(".")
        and os.access(p, os.X_OK)
    ]
    if len(execs) == 1:
        return execs[0]
    return None


def _read_plugin_version() -> str:
    """Read this plugin's version from the shipped plugin.json. Returns
    "unknown" if the file is missing or malformed — metrics.init() requires
    a label value matching [A-Za-z0-9._-], so the fallback must qualify."""
    here = Path(__file__).resolve().parent  # claude/lazycortex-core/bin
    plugin_json = here.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(plugin_json.read_text())["version"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return "unknown"


def _init_metrics_if_enabled(repo_root: Path) -> None:
    """Bring up the metrics endpoint when settings turn it on. Called once,
    before the main loop. The cfg is reloaded inside the loop for routine
    hot-reload, but metrics init is one-shot — operators must restart the
    daemon to flip enablement on or off."""
    settings_path = repo_root / ".claude/lazy.settings.json"
    daemon = load_section(settings_path, "daemon")
    metrics_cfg = daemon.get("metrics", {})
    if not metrics_cfg.get("enabled"):
        return
    import metrics
    repo_label = metrics.resolve_repo_label(repo_root, metrics_cfg.get("repo_label"))
    metrics.init(
        repo_label=repo_label,
        version=_read_plugin_version(),
        daemon_name=metrics_cfg.get("daemon_name") or "lazycortex-runtime",
    )
    metrics.expose(
        bind=metrics_cfg.get("bind", "127.0.0.1"),
        port=int(metrics_cfg.get("port", 9464)),
    )


def compute_sleep(time_until_next: float, polling_interval_sec: float) -> float:
    return max(0.0, min(time_until_next, polling_interval_sec))


def due_routines(now: float, registry: dict, last_run: dict) -> list[tuple[str, dict]]:
    out = []
    for name, cfg in registry.items():
        if cfg.get("type") == "schedule":
            from routine_types import due_for_schedule
            if due_for_schedule(name, cfg, now, last_run.get(name, 0)):
                out.append((name, cfg))
        else:
            if now - last_run.get(name, 0) >= cfg["interval_sec"]:
                out.append((name, cfg))
    return out


def time_until_next_due(now: float, registry: dict, last_run: dict) -> float:
    candidates = []
    for n, cfg in registry.items():
        if cfg.get("type") == "schedule":
            # Schedule routines wake up to be re-checked on each tick;
            # the daemon's polling_interval_sec floor keeps the loop honest.
            candidates.append(60.0)
        else:
            candidates.append(last_run.get(n, 0) + cfg["interval_sec"] - now)
    return min(candidates) if candidates else float("inf")


def _check_working_tree(repo_root: Path) -> list[str] | None:
    """Run `git status --porcelain` in the daemon's repo.
    Returns the list of dirty lines (capped at 50, last entry replaced with a
    sentinel if truncated), or None if the tree is clean.

    If the repo is not a git repo (or git is not on PATH), returns None — the
    working-tree-protection invariant only meaningfully applies inside a git
    repo. Operators running the daemon outside one get no protection.
    """
    try:
        # `--no-optional-locks` tells git to skip the stat-cache refresh
        # that `git status` would otherwise write to `.git/index.lock`.
        # The dirty-tree-skip check runs every daemon iteration; without
        # this flag, the daemon grabs the index lock dozens of times per
        # minute and races with any concurrent manual git command.
        rc = subprocess.run(
            ["git", "--no-optional-locks", "-c", "color.status=never",
             "status", "--porcelain"],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
    if rc.returncode != 0:
        return None
    raw = rc.stdout.rstrip("\n")
    if not raw:
        return None
    lines = raw.split("\n")
    if len(lines) > 50:
        lines = lines[:50] + ["... (truncated, more dirty paths exist)"]
    return lines


def _halt_daemon(
    repo_root: Path,
    state: dict,
    reason: str,
    triggered_by: str,
    detail: str,
) -> None:
    """Write the `daemon_halted` block to state.json (if not already present)
    and emit a halt metric. Used by both git-failure and dirty-tree halt paths.

    Logs the trigger detail to the runtime log too, so the operator running
    `/lazy-runtime.recover` can correlate the halt with a routine result entry."""
    _log_routine_result(repo_root, {
        "name": triggered_by, "exit": -1, "duration_sec": 0.0,
        "error": f"{reason}: {detail}",
    })
    if "daemon_halted" in state:
        return  # Don't clobber an earlier, more-specific halt (e.g. expert attribution).
    state["daemon_halted"] = {
        "halted_since": time.time(),
        "triggered_by": triggered_by,
        "reason": reason,
        "dirty_paths": [],
        "expert": None,
        "job_id": None,
    }
    runtime_state.save(repo_root, state)
    _emit_halt_metric_if_available(reason=reason, triggered_by=triggered_by)


def _emit_halt_metric_if_available(reason: str, triggered_by: str) -> None:
    """Best-effort metrics emission. The metrics module may not be installed yet
    (it lands with the observability plan); guarded import keeps both plans
    independent."""
    try:
        import metrics
        if metrics.is_enabled():
            metrics.record_daemon_halt(reason=reason, triggered_by=triggered_by)
    except ImportError:
        pass


def _run_iteration(repo_root: Path) -> None:
    """One iteration of the daemon's main loop. Idempotent on state.json
    so this is a clean test seam."""
    state = runtime_state.load(repo_root)
    if state.get("daemon_halted"):
        return  # halted — wait for /lazy-runtime.recover

    settings_path = repo_root / ".claude/lazy.settings.json"
    daemon = load_section(settings_path, "daemon")
    registry = load_section(settings_path, "routines")
    registry.pop("_version", None)
    last_run = state.setdefault("last_run", {})

    # Hourly cleanup — throttled via state so the floor on filesystem churn
    # is independent of the loop's polling interval.
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

    # Pre-iteration tree check — daemon does NOT run routines while the
    # working tree has uncommitted changes. The operator may be mid-edit,
    # or another process (a hand-run `lazy-review tick`, a manual git op)
    # may be in flight. Either way, routines like `lazy-review.tick` would
    # read the dirty file, generate output from the WIP state, and commit
    # over the operator's work. Skip silently — no halt, no log spam — so
    # the daemon resumes cleanly the next iteration after the tree settles.
    pre_dirty = _check_working_tree(repo_root)
    if pre_dirty is not None:
        return

    now = time.time()
    halted_this_iter = False
    for name, routine_cfg in due_routines(now, registry, last_run):
        result = dispatch_routine(repo_root, name, routine_cfg)
        _log_routine_result(repo_root, result)
        last_run[name] = time.time()
        runtime_state.save(repo_root, state)

        # Tree was clean at iteration start; any dirt now is the routine's
        # own output that didn't make it into a commit — that's a contract
        # violation and the daemon halts so the operator can investigate.
        post_dirty = _check_working_tree(repo_root)
        if post_dirty is not None:
            # Don't overwrite an existing halt block — pump may have already
            # written a more specific one (with expert + job_id attribution).
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
                    reason="uncommitted_changes", triggered_by=name,
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


def run(repo_root: Path) -> None:
    settings_path = repo_root / ".claude/lazy.settings.json"
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    _init_metrics_if_enabled(repo_root)

    while not stop["flag"]:
        _run_iteration(repo_root)
        # Compute sleep based on latest cfg + last_run state.
        daemon = load_section(settings_path, "daemon")
        registry = load_section(settings_path, "routines")
        registry.pop("_version", None)
        last_run = runtime_state.load(repo_root).get("last_run", {})
        sleep_s = compute_sleep(
            time_until_next_due(time.time(), registry, last_run),
            daemon.get("polling_interval_sec", 5),
        )
        time.sleep(sleep_s)


def resolve_routine_command(cmd: list[str]) -> list[str]:
    plugin = cmd[0]
    # Dev-plugin paths take precedence over the plugin cache.
    for pd in _PLUGIN_DIRS:
        bin_path = _resolve_in_plugin_dir(pd, plugin)
        if bin_path is not None:
            return [str(bin_path), *cmd[1:]]
    cache = Path.home() / ".claude/plugins/cache"
    # Real layout: cache/<registry>/<plugin>/<version>/bin/<plugin>
    plugin_dirs: list[Path] = []
    if cache.is_dir():
        for registry in cache.iterdir():
            if not registry.is_dir():
                continue
            candidate = registry / plugin
            if candidate.is_dir():
                plugin_dirs.append(candidate)
    if not plugin_dirs:
        raise FileNotFoundError(
            f"plugin not in cache and no matching --plugin-dir for: {plugin}"
        )
    # Across all <registry>/<plugin> dirs, descend into versions and pick latest.
    all_versions = []
    for pd in plugin_dirs:
        all_versions.extend(v for v in pd.iterdir() if v.is_dir())
    if not all_versions:
        raise FileNotFoundError(f"no versions cached for plugin: {plugin}")
    # Lex-sort by version-string-name, take latest.
    # Caveat: lex sort works for single-digit majors; revisit when 10.x ships
    # (matches the deferred decision in reference_resolver).
    latest = sorted(all_versions, key=lambda v: v.name, reverse=True)[0]
    bin_path = latest / "bin" / plugin
    if not bin_path.exists():
        raise FileNotFoundError(f"no bin for plugin: {bin_path}")
    return [str(bin_path), *cmd[1:]]


def _run_git(repo_root: Path, args: list[str]) -> None:
    try:
        subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"git {' '.join(args)} failed:\n{e.stderr.decode()}\n")
        raise


def _run_git_capture(repo_root: Path, args: list[str]) -> str:
    """Like `_run_git`, but returns stripped stdout. Used for rev-parse and
    merge-base where we need the sha output."""
    proc = subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _git_pre(repo_root: Path, git_cfg: dict | None) -> None:
    if not git_cfg:
        return
    branch = git_cfg["branch"]
    # `-B` is intentional: the daemon's branch is reset to current HEAD each
    # iteration. The branch is daemon-exclusive (per daemon.git.branch contract).
    _run_git(repo_root, ["checkout", "-B", branch])
    if git_cfg.get("remote_sync") not in ("pull", "pull_push"):
        return
    # Explicit `origin <branch>` everywhere — `git checkout -B` does not set
    # upstream tracking, so bare commands would fail on "no tracking information".
    _run_git(repo_root, ["fetch", "origin", branch])
    local = _run_git_capture(repo_root, ["rev-parse", "HEAD"])
    remote = _run_git_capture(repo_root, ["rev-parse", f"origin/{branch}"])
    if local == remote:
        return  # In sync, nothing to pull.
    base = _run_git_capture(repo_root, ["merge-base", "HEAD", f"origin/{branch}"])
    if base == local:
        # Local is an ancestor of remote → fast-forward pull is safe.
        _run_git(repo_root, ["pull", "--ff-only", "origin", branch])
        return
    if base == remote:
        # Remote is an ancestor of local — we carry unpushed local commits
        # (e.g. previous tick's `_git_post` push got blocked). No pull needed;
        # the next `_git_post` will rebase + push these forward.
        return
    # Otherwise: histories diverged — both sides have commits the other doesn't.
    raise GitPullDiverged(
        f"local HEAD {local[:8]} and origin/{branch} {remote[:8]} have diverged"
    )


def _git_post(repo_root: Path, git_cfg: dict | None) -> None:
    if not git_cfg:
        return
    if git_cfg.get("remote_sync") != "pull_push":
        return
    branch = git_cfg["branch"]

    for _attempt in range(POST_TICK_MAX_PUSH_ATTEMPTS):
        _run_git(repo_root, ["fetch", "origin", branch])
        local = _run_git_capture(repo_root, ["rev-parse", "HEAD"])
        remote = _run_git_capture(repo_root, ["rev-parse", f"origin/{branch}"])

        if local == remote:
            return  # Nothing to push.

        base = _run_git_capture(repo_root, ["merge-base", "HEAD", f"origin/{branch}"])

        if base == remote:
            # Local is strictly ahead of origin (no operator commits in the
            # gap) → fast-forward push.
            try:
                _run_git(repo_root, ["push", "origin", branch])
                return
            except subprocess.CalledProcessError:
                # Race: operator pushed between our fetch and our push. Retry.
                continue

        if base == local:
            # Origin moved forward but contains nothing of ours? That means
            # our local HEAD became an ancestor of origin between our fetch
            # and now — extremely unlikely but possible if another process
            # already rebased + pushed for us. Just fall through to "no work".
            return

        # Histories diverged within the tick (operator pushed a commit while
        # the routine was running). Try to rebase our local commits onto the
        # new origin tip.
        try:
            _run_git(repo_root, ["rebase", f"origin/{branch}"])
        except subprocess.CalledProcessError:
            # Conflict on rebase — operator's commits and ours touch the same
            # content. Bail out: abort the rebase, hard-reset to origin
            # (discarding this tick's work), and log the discard. Next tick
            # re-runs the routine on the fresh operator state.
            _run_git(repo_root, ["rebase", "--abort"])
            _run_git(repo_root, ["reset", "--hard", f"origin/{branch}"])
            _log_routine_result(repo_root, {
                "name": "_git_post", "exit": 0, "duration_sec": 0.0,
                "error": "tick discarded: operator-conflict",
            })
            return

        # Rebase clean — push the rebased commits.
        try:
            _run_git(repo_root, ["push", "origin", branch])
            return
        except subprocess.CalledProcessError:
            # Race again: another operator push slid in between our rebase and
            # our push. Retry the whole loop.
            continue

    raise GitPushFailed(
        f"push to origin/{branch} failed after {POST_TICK_MAX_PUSH_ATTEMPTS} attempts"
    )


def dispatch_subprocess(repo_root: Path, name: str, cfg: dict) -> dict:
    """Subprocess routine handler — resolves the plugin binary, runs it, captures result.

    Called from routine_types.dispatch_routine for type='subprocess' (default).
    Lives here (not in routine_types) because it depends on the plugin-cache
    resolver which is daemon-internal infrastructure.
    """
    started = time.time()
    try:
        argv = resolve_routine_command(cfg["command"])
        timeout = cfg.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
        proc = subprocess.run(argv, cwd=repo_root, timeout=timeout, capture_output=True, text=True)
        return {
            "name": name, "exit": proc.returncode, "duration_sec": time.time() - started,
            "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "exit": -1, "duration_sec": time.time() - started, "error": "timeout"}
    except FileNotFoundError as e:
        return {"name": name, "exit": -1, "duration_sec": time.time() - started, "error": f"resolve: {e}"}
    except Exception as e:  # broad catch — daemon must not die on a single routine failure
        return {"name": name, "exit": -1, "duration_sec": time.time() - started, "error": f"unexpected: {e}"}


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(s: str) -> float:
    return float(s[:-1]) * _DURATION_UNITS[s[-1]]


def _cleanup_runtime_logs(repo_root: Path, max_age: str) -> None:
    """Delete `.logs/lazy-core/runtime/<date>.jsonl` files older than `max_age`.
    `tokens.jsonl` is intentionally exempted — it has no date in its name and
    operators rotate it manually."""
    log_dir = repo_root / ".logs/lazy-core/runtime"
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


def _log_routine_result(repo_root: Path, result: dict) -> None:
    log_dir = repo_root / ".logs/lazy-core/runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
    record = {"ts": time.time(), **result}
    with log_file.open("a") as f:
        f.write(json.dumps(record) + "\n")
    _emit_tick_metrics_if_available(repo_root, result)


def _emit_tick_metrics_if_available(repo_root: Path, result: dict) -> None:
    """Best-effort tick + queue-depth + token aggregation. The metrics
    module is opt-in, so a disabled daemon pays no observable cost here."""
    try:
        import metrics
    except ImportError:
        return
    if not metrics.is_enabled():
        return
    metrics.record_tick(
        routine=result.get("name") or "unknown",
        exit_code=int(result.get("exit", 0)),
        duration_sec=float(result.get("duration_sec", 0.0)),
        error=result.get("error"),
    )
    metrics.set_queue_depth_from_filesystem(repo_root)
    metrics.aggregate_tokens_from_log(repo_root)


if __name__ == "__main__":
    run(Path(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
