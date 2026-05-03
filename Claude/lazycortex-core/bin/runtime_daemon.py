"""Generic per-repo serial runtime daemon.

# retry policy lives in routine implementations (e.g. expert-pump), not in the daemon
"""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path
from typing import Iterable
from lazy_settings import load_section

DEFAULT_TIMEOUT_SEC = 300


def compute_sleep(time_until_next: float, polling_interval_sec: float) -> float:
    return max(0.0, min(time_until_next, polling_interval_sec))


def due_routines(now: float, registry: dict, last_run: dict) -> list[tuple[str, dict]]:
    out = []
    for name, cfg in registry.items():
        if now - last_run.get(name, 0) >= cfg["interval_sec"]:
            out.append((name, cfg))
    return out


def time_until_next_due(now: float, registry: dict, last_run: dict) -> float:
    candidates = [
        last_run.get(n, 0) + cfg["interval_sec"] - now
        for n, cfg in registry.items()
    ]
    return min(candidates) if candidates else float("inf")


def run(repo_root: Path) -> None:
    settings_path = repo_root / ".claude/lazy.settings.json"
    last_run: dict[str, float] = {}
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    while not stop["flag"]:
        cfg = load_section(settings_path, "lazy-core.runtime")
        daemon = cfg.get("daemon", {})
        registry = cfg.get("routines", {})

        try:
            _git_pre(repo_root, daemon.get("git"))
        except Exception as e:
            _log_routine_result(repo_root, {
                "name": "_git_pre", "exit": -1, "duration_sec": 0.0,
                "error": f"git_pre failed: {e}",
            })
        now = time.time()
        for name, routine_cfg in due_routines(now, registry, last_run):
            result = _run_routine(repo_root, name, routine_cfg)
            _log_routine_result(repo_root, result)
            last_run[name] = time.time()
        try:
            _git_post(repo_root, daemon.get("git"))
        except Exception as e:
            _log_routine_result(repo_root, {
                "name": "_git_post", "exit": -1, "duration_sec": 0.0,
                "error": f"git_post failed: {e}",
            })

        sleep_s = compute_sleep(
            time_until_next_due(time.time(), registry, last_run),
            daemon.get("polling_interval_sec", 5),
        )
        time.sleep(sleep_s)


def resolve_routine_command(cmd: list[str]) -> list[str]:
    plugin = cmd[0]
    cache = Path.home() / ".claude/plugins/cache"
    # Real layout: cache/<registry>/<plugin>/<version>/bin/<plugin>
    plugin_dirs = list(cache.glob(f"*/{plugin}"))
    if not plugin_dirs:
        raise FileNotFoundError(f"plugin not in cache: {plugin}")
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


def _git_pre(repo_root: Path, git_cfg: dict | None) -> None:
    if not git_cfg:
        return
    branch = git_cfg["branch"]
    # `-B` is intentional: the daemon's branch is reset to current HEAD each
    # iteration. The branch is daemon-exclusive (per daemon.git.branch contract).
    _run_git(repo_root, ["checkout", "-B", branch])
    if git_cfg.get("remote_sync") in ("pull", "pull_push"):
        # Explicit `origin <branch>` — `git checkout -B <branch>` does not set
        # upstream tracking, so a bare `git pull --ff-only` would fail with
        # "There is no tracking information for the current branch."
        _run_git(repo_root, ["pull", "--ff-only", "origin", branch])


def _git_post(repo_root: Path, git_cfg: dict | None) -> None:
    if not git_cfg:
        return
    if git_cfg.get("remote_sync") == "pull_push":
        # Explicit `origin <branch>` so we don't rely on upstream tracking
        # that `git checkout -B` does not set.
        _run_git(repo_root, ["push", "origin", git_cfg["branch"]])


def _run_routine(repo_root: Path, name: str, cfg: dict) -> dict:
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


def _log_routine_result(repo_root: Path, result: dict) -> None:
    log_dir = repo_root / ".logs/lazy-core/runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
    record = {"ts": time.time(), **result}
    with log_file.open("a") as f:
        f.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    run(Path(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
