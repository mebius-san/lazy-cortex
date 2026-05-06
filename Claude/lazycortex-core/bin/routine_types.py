"""Routine type taxonomy + per-type schema validation for lazy-core.runtime.

Each entry under `lazy-core.runtime.routines` may carry an optional `type`
field. Default is `subprocess` (current behavior, unchanged). Allowed values:
`subprocess`, `inbox`, `schedule`, `git`.

Validation is closed-set strict: unknown types or unknown fields raise
RoutineConfigError. Per-type custom constraints (e.g. schedule's exactly-one
between `command` vs `expert+request`) are enforced too.
"""
from __future__ import annotations

VALID_TYPES = {"subprocess", "inbox", "schedule", "git"}

VALID_GIT_WATCH = {
    "new_commits", "new_files", "changed_files", "deleted_files", "renamed_files",
}

SCHEMAS = {
    "subprocess": {
        "required": {"command", "interval_sec"},
        "optional": {"timeout_sec"},
    },
    "inbox": {
        "required": {"inbox_dir", "expert", "request", "interval_sec"},
        "optional": {"timeout_sec"},
    },
    "schedule": {
        "required": {"cron"},
        "optional": {"command", "expert", "request", "timeout_sec"},
    },
    "git": {
        "required": {"branch", "watch", "expert", "request", "interval_sec"},
        "optional": {"repo_dir", "remote", "path_filter", "timeout_sec"},
    },
}

COMMON_ALLOWED = {"type"}


class RoutineConfigError(ValueError):
    """Raised when a routine entry's config does not conform to its type schema."""


def validate_routine_entry(name: str, cfg: dict) -> None:
    """Validate one entry from `lazy-core.runtime.routines`.

    Raises RoutineConfigError on:
      - unknown type
      - missing required fields
      - unknown fields (anything not in required ∪ optional ∪ COMMON_ALLOWED)
      - per-type custom constraints
    """
    rtype = cfg.get("type", "subprocess")
    if rtype not in VALID_TYPES:
        raise RoutineConfigError(
            f"routine '{name}': unknown type '{rtype}'. "
            f"Valid: {sorted(VALID_TYPES)}."
        )

    schema = SCHEMAS[rtype]
    required = schema["required"]
    optional = schema["optional"]
    allowed = required | optional | COMMON_ALLOWED

    keys = set(cfg)
    missing = required - keys
    if missing:
        raise RoutineConfigError(
            f"routine '{name}' (type={rtype}): missing required field(s): {sorted(missing)}"
        )

    unknown = keys - allowed
    if unknown:
        raise RoutineConfigError(
            f"routine '{name}' (type={rtype}): unknown field(s): {sorted(unknown)}"
        )

    if rtype == "schedule":
        has_command = "command" in cfg
        has_expert = "expert" in cfg
        has_request = "request" in cfg
        if has_command and (has_expert or has_request):
            raise RoutineConfigError(
                f"routine '{name}' (type=schedule): set EITHER 'command' OR 'expert' + 'request', not both"
            )
        if not has_command and not (has_expert and has_request):
            raise RoutineConfigError(
                f"routine '{name}' (type=schedule): must set EITHER 'command' OR 'expert' + 'request'"
            )

    if rtype == "git":
        watch = cfg.get("watch")
        if watch not in VALID_GIT_WATCH:
            raise RoutineConfigError(
                f"routine '{name}' (type=git): invalid watch value '{watch}'. "
                f"Valid: {sorted(VALID_GIT_WATCH)}."
            )


def dispatch_routine(repo, name: str, cfg: dict) -> dict:
    """Dispatch one routine tick. Returns the standard tick result dict.

    Switches on cfg.get("type", "subprocess"). For non-default types, delegates
    to the per-type handler in this module. For `subprocess`, delegates to
    runtime_daemon.dispatch_subprocess (lazy import to avoid module cycle).
    """
    rtype = cfg.get("type", "subprocess")
    if rtype == "subprocess":
        from runtime_daemon import dispatch_subprocess
        return dispatch_subprocess(repo, name, cfg)
    if rtype == "inbox":
        return dispatch_inbox(repo, name, cfg)
    if rtype == "schedule":
        return dispatch_schedule(repo, name, cfg)
    if rtype == "git":
        return dispatch_git(repo, name, cfg)
    # Validator should have caught this; this is a defensive guard.
    raise RoutineConfigError(f"routine '{name}': unknown type '{rtype}' at dispatch time")


# Per-type handlers — implementations land in their own phases (C/D/E).
# Until then, calling these returns a clean error result so the daemon's
# tick loop doesn't crash; just logs and moves on.

def _not_implemented(name: str, rtype: str) -> dict:
    import time
    return {
        "name": name,
        "exit": -1,
        "duration_sec": 0.0,
        "error": f"type {rtype!r} not yet implemented",
    }


def _render_template(template, vars: dict):
    """Substitute {field} placeholders in string values of a JSON-shaped template.

    Walks dicts and lists; runs str.format(**vars) on string leaves. Literal
    `{` and `}` must be doubled (`{{`, `}}`). Raises KeyError if a placeholder
    references a var that isn't provided — caller treats this as a routine
    failure rather than silently emitting a malformed request.
    """
    if isinstance(template, dict):
        return {k: _render_template(v, vars) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_template(v, vars) for v in template]
    if isinstance(template, str):
        return template.format(**vars)
    return template


def dispatch_inbox(repo, name: str, cfg: dict) -> dict:
    """Scan cfg['inbox_dir']; move each non-hidden, non-dir, non-symlink file
    into a new job dir under .experts/.jobs/<expert>/<uuid>/source/, write
    request.json with the {file} placeholder substituted, then touch READY.

    The inbox directory is empty when the routine returns successfully.
    """
    import json, time, uuid
    from pathlib import Path
    started = time.time()
    repo = Path(repo)
    inbox_dir = repo / cfg["inbox_dir"]
    expert = cfg["expert"]
    request_template = cfg["request"]

    if not inbox_dir.exists():
        return {
            "name": name, "exit": 0,
            "duration_sec": time.time() - started,
            "dispatched_count": 0,
            "note": "inbox_dir does not exist",
        }

    # Sorted for deterministic dispatch order
    candidates = []
    for entry in sorted(inbox_dir.iterdir()):
        if entry.name.startswith("."):  # hidden
            continue
        if entry.is_symlink():  # symlinks are operator state, never moved
            continue
        if not entry.is_file():  # subdirs etc.
            continue
        candidates.append(entry)

    # Lazy import to avoid hard coupling on expert_runtime layout details.
    from expert_runtime import JOBS_BASE

    dispatched = 0
    for f in candidates:
        job_id = uuid.uuid4().hex[:12]
        job_dir = repo / JOBS_BASE / expert / job_id
        try:
            (job_dir / "source").mkdir(parents=True, exist_ok=True)
            f.rename(job_dir / "source" / f.name)  # atomic on same filesystem
            request = _render_template(request_template, {"file": f.name})
            (job_dir / "request.json").write_text(json.dumps(request, indent=2))
            (job_dir / "READY").touch()
            dispatched += 1
        except Exception as e:
            return {
                "name": name, "exit": -1,
                "duration_sec": time.time() - started,
                "dispatched_count": dispatched,
                "error": f"inbox dispatch failed at {f.name}: {e}",
            }

    return {
        "name": name, "exit": 0,
        "duration_sec": time.time() - started,
        "dispatched_count": dispatched,
    }


def dispatch_schedule(repo, name: str, cfg: dict) -> dict:
    """Schedule routine — fires when the cron expression has crossed a boundary
    since last_run (the daemon-level due_routines decides; this just dispatches).

    Two sub-shapes (validator enforces exactly-one):
      - command: spawn subprocess (delegates to runtime_daemon.dispatch_subprocess)
      - expert + request: dispatch a single job to the named expert
    """
    import time
    from datetime import datetime, timezone
    from pathlib import Path
    started = time.time()

    if "command" in cfg:
        from runtime_daemon import dispatch_subprocess
        sub_cfg = {"command": cfg["command"]}
        if "timeout_sec" in cfg:
            sub_cfg["timeout_sec"] = cfg["timeout_sec"]
        return dispatch_subprocess(Path(repo), name, sub_cfg)

    expert = cfg["expert"]
    request_template = cfg["request"]
    now = datetime.now(timezone.utc)
    request = _render_template(request_template, {
        "cron_fire_ts": now.isoformat(),
        "cron_fire_unix": str(int(now.timestamp())),
    })
    from expert_runtime import dispatch_job
    dispatch_job(Path(repo), expert, request)
    return {
        "name": name, "exit": 0,
        "duration_sec": time.time() - started,
        "dispatched_count": 1,
    }


def due_for_schedule(name: str, cfg: dict, now_unix: float, last_run_unix: float) -> bool:
    """Whether a `schedule` routine has crossed a fire boundary since last_run.

    Wraps cron.due_since with unix-time arguments so the daemon-level scheduler
    can mix interval-based and cron-based routines uniformly.
    """
    from datetime import datetime, timezone
    from cron import parse, due_since
    spec = parse(cfg["cron"])
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    last_run_dt = (
        datetime.fromtimestamp(last_run_unix, tz=timezone.utc)
        if last_run_unix > 0 else EPOCH
    )
    now_dt = datetime.fromtimestamp(now_unix, tz=timezone.utc)
    return due_since(spec, last_run_dt, now_dt)


def dispatch_git(repo, name: str, cfg: dict) -> dict:
    """Watch <remote>/<branch> and dispatch a job per new item per cfg['watch'].

    `last_seen_sha` is tracked in state.json's git_watch.<name> block. First
    run records the current ref and dispatches nothing (no history backfill).
    Force-push (last_seen_sha not in remote branch history) resets baseline
    and dispatches nothing.
    """
    import subprocess, time
    from pathlib import Path
    started = time.time()
    repo = Path(repo)

    work_dir = (repo / cfg.get("repo_dir", ".")).resolve()
    remote = cfg.get("remote", "origin")
    branch = cfg["branch"]
    watch = cfg["watch"]
    path_filter = cfg.get("path_filter")
    expert = cfg["expert"]
    request_template = cfg["request"]

    if not (work_dir / ".git").exists() and not (work_dir.is_dir() and _is_git_dir(work_dir)):
        return _err(name, started, "not_a_git_repo", f"{work_dir} is not a git repo")

    fetch = subprocess.run(
        ["git", "fetch", "--quiet", remote, branch],
        cwd=str(work_dir), capture_output=True, text=True,
    )
    if fetch.returncode != 0:
        return _err(name, started, "fetch_failed", fetch.stderr.strip()[-500:])

    try:
        head_sha = subprocess.check_output(
            ["git", "rev-parse", f"{remote}/{branch}"],
            cwd=str(work_dir), text=True,
        ).strip()
    except subprocess.CalledProcessError as e:
        return _err(name, started, "rev_parse_failed", str(e))

    import runtime_state
    state = runtime_state.load(repo)
    git_state = state.setdefault("git_watch", {}).setdefault(name, {})
    last_seen = git_state.get("last_seen_sha")

    if last_seen is None:
        git_state["last_seen_sha"] = head_sha
        runtime_state.save(repo, state)
        return _ok(name, started, dispatched_count=0, note="first_run_baseline_recorded")

    if last_seen == head_sha:
        return _ok(name, started, dispatched_count=0)

    if not _is_ancestor(work_dir, last_seen, head_sha):
        git_state["last_seen_sha"] = head_sha
        runtime_state.save(repo, state)
        return _ok(name, started, dispatched_count=0, note="force_push_baseline_reset")

    items = _compute_git_items(work_dir, last_seen, head_sha, watch, path_filter)

    from expert_runtime import dispatch_job
    for item in items:
        rendered = _render_template(request_template, item)
        dispatch_job(repo, expert, rendered)

    git_state["last_seen_sha"] = head_sha
    runtime_state.save(repo, state)
    return _ok(name, started, dispatched_count=len(items))


def _ok(name, started, **extra):
    import time
    return {
        "name": name, "exit": 0,
        "duration_sec": time.time() - started,
        **extra,
    }


def _err(name, started, error_kind, detail):
    import time
    return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "error": f"{error_kind}: {detail}",
    }


def _is_git_dir(path) -> bool:
    """Check via `git rev-parse --git-dir` rather than just .git existence
    (works for worktrees and bare repos)."""
    import subprocess
    rc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(path), capture_output=True,
    )
    return rc.returncode == 0


def _is_ancestor(work_dir, ancestor: str, descendant: str) -> bool:
    import subprocess
    rc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=str(work_dir), capture_output=True,
    )
    return rc.returncode == 0


def _compute_git_items(work_dir, last_seen: str, head_sha: str,
                      watch: str, path_filter: str | None) -> list[dict]:
    """Per-watch-value item enumeration. Returns list of dicts with the
    templating variables documented in references/lazy-core.runtime-schema.md."""
    import subprocess
    rng = f"{last_seen}..{head_sha}"
    pathspec = ["--", path_filter] if path_filter else []

    if watch == "new_commits":
        out = subprocess.check_output(
            ["git", "log",
             "--format=%H%x09%h%x09%s%x09%an%x09%ae%x09%ct",
             rng, *pathspec],
            cwd=str(work_dir), text=True,
        ).strip()
        items = []
        if out:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 6:
                    sha, short_sha, subj, an, ae, ct = parts[:6]
                    items.append({
                        "sha": sha,
                        "short_sha": short_sha,
                        "subject": subj,
                        "author_name": an,
                        "author_email": ae,
                        "commit_ts": ct,
                    })
        return items

    if watch in ("new_files", "changed_files", "deleted_files"):
        # Use diff --name-status for added/modified/deleted classification.
        out = subprocess.check_output(
            ["git", "diff", "--name-status", rng, *pathspec],
            cwd=str(work_dir), text=True,
        ).strip()
        wanted = {
            "new_files": {"A"},
            "changed_files": {"A", "M"},
            "deleted_files": {"D"},
        }[watch]
        items = []
        if out:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                status = parts[0][:1]  # strip percent for renames etc.
                if status not in wanted:
                    continue
                path = parts[1]
                sha = _last_change_sha(work_dir, path, rng, status)
                items.append({"path": path, "status": status, "sha": sha})
        return items

    if watch == "renamed_files":
        out = subprocess.check_output(
            ["git", "diff", "--name-status", "--find-renames", rng, *pathspec],
            cwd=str(work_dir), text=True,
        ).strip()
        items = []
        if out:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].startswith("R"):
                    old_path, new_path = parts[1], parts[2]
                    sha = _last_change_sha(work_dir, new_path, rng, "R")
                    items.append({
                        "old_path": old_path,
                        "new_path": new_path,
                        "sha": sha,
                    })
        return items

    raise RoutineConfigError(f"unknown git watch value: {watch!r}")


def _last_change_sha(work_dir, path: str, rng: str, status: str) -> str:
    """Find the most recent commit SHA in `rng` that matches the status filter
    for this path. Returns 'unknown' if not findable."""
    import subprocess
    flag = {"A": "A", "M": "M", "D": "D", "R": "AMDR"}.get(status, "AMDR")
    try:
        out = subprocess.check_output(
            ["git", "log", f"--diff-filter={flag}",
             "--format=%H", "-1", rng, "--", path],
            cwd=str(work_dir), text=True,
        ).strip()
        return out or "unknown"
    except subprocess.CalledProcessError:
        return "unknown"
