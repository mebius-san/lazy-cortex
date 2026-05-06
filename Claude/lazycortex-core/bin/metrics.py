"""Stdlib-only Prometheus metrics for the lazycortex-core runtime daemon.

# Hard rule: every label value comes from a closed set declared in the
# observability plan (`docs/plans/2026-05-05-runtime-observability.md`,
# `## Cross-cutting design decisions`). Never accept a label value derived
# from raw user input, raw exception text, file paths, job ids, branch names,
# commit shas, or hostnames. The `daemon_name` label is intentionally a
# constant — operator identity (hostname) must not leak into metric streams.

Off by default. The daemon calls `init()` only when
`lazy-core.runtime.metrics.enabled` is true, so importing this module is free.

Implementation rationale: `prometheus-client` would add a Python dep this
repo otherwise doesn't have. The text format is small and stable, so we
emit it directly per the OpenMetrics spec
(https://prometheus.io/docs/instrumenting/exposition_formats/).
"""
from __future__ import annotations
import hashlib
import re
import subprocess
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server


_LABEL_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_label_value(label: str, value: str) -> None:
    if not _LABEL_VALUE_RE.match(value):
        raise ValueError(
            f"label {label!r} got value {value!r} — closed-vocabulary guard "
            "rejects values outside [A-Za-z0-9._-]"
        )


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    # Sort keys for deterministic output (tests + diff stability).
    pairs = []
    for k in sorted(labels):
        v = str(labels[k]).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        pairs.append(f'{k}="{v}"')
    return "{" + ",".join(pairs) + "}"


def _format_value(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return repr(v)


class _Counter:
    def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...]):
        self.name = name
        self.help = help_text
        self.labelnames = labelnames
        self.values: dict[tuple[str, ...], float] = {}

    def inc(self, label_values: dict[str, str], amount: float = 1.0) -> None:
        for k in self.labelnames:
            _validate_label_value(k, label_values[k])
        key = tuple(label_values[k] for k in self.labelnames)
        self.values[key] = self.values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, val in self.values.items():
            label_str = _format_labels(dict(zip(self.labelnames, key)))
            out.append(f"{self.name}{label_str} {_format_value(val)}")
        return out


class _Gauge:
    def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...] = ()):
        self.name = name
        self.help = help_text
        self.labelnames = labelnames
        self.values: dict[tuple[str, ...], float] = {}

    def set(self, label_values: dict[str, str] | None, value: float) -> None:
        label_values = label_values or {}
        for k in self.labelnames:
            _validate_label_value(k, label_values[k])
        key = tuple(label_values[k] for k in self.labelnames)
        self.values[key] = float(value)

    def clear(self) -> None:
        self.values = {}

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        for key, val in self.values.items():
            label_str = _format_labels(dict(zip(self.labelnames, key)))
            out.append(f"{self.name}{label_str} {_format_value(val)}")
        return out


_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)


def _bucket_label(b: float) -> str:
    if b == int(b):
        return str(int(b))
    return repr(b)


class _Histogram:
    def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...]):
        self.name = name
        self.help = help_text
        self.labelnames = labelnames
        # key = label tuple; value = (bucket_counts, sum, count)
        self.values: dict[tuple[str, ...], list] = {}

    def observe(self, label_values: dict[str, str], value: float) -> None:
        for k in self.labelnames:
            _validate_label_value(k, label_values[k])
        key = tuple(label_values[k] for k in self.labelnames)
        if key not in self.values:
            self.values[key] = [[0] * (len(_BUCKETS) + 1), 0.0, 0]  # +1 for +Inf
        buckets, total_sum, total_count = self.values[key]
        for i, b in enumerate(_BUCKETS):
            if value <= b:
                buckets[i] += 1
        buckets[-1] += 1  # +Inf bucket gets every observation
        self.values[key] = [buckets, total_sum + value, total_count + 1]

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, (buckets, total_sum, total_count) in self.values.items():
            base_labels = dict(zip(self.labelnames, key))
            for i, b in enumerate(_BUCKETS):
                lbls = {**base_labels, "le": _bucket_label(b)}
                out.append(f"{self.name}_bucket{_format_labels(lbls)} {buckets[i]}")
            inf_lbls = {**base_labels, "le": "+Inf"}
            out.append(f"{self.name}_bucket{_format_labels(inf_lbls)} {buckets[-1]}")
            out.append(f"{self.name}_sum{_format_labels(base_labels)} {_format_value(total_sum)}")
            out.append(f"{self.name}_count{_format_labels(base_labels)} {total_count}")
        return out


# Module-level state — populated by init().
_state: dict = {}


def _reset_for_tests() -> None:
    """Drop all module state. Called by test fixtures only."""
    _state.clear()


def is_enabled() -> bool:
    return bool(_state.get("initialized"))


def init(repo_label: str, version: str, daemon_name: str) -> None:
    """Initialize module state. Must be called before any record_* call.

    `repo_label` is the per-repo identifier; `version` is the lazycortex-core
    plugin version; `daemon_name` is a constant (overridable but ALWAYS a
    constant per repo, never the hostname).
    """
    _validate_label_value("repo", repo_label)
    _validate_label_value("version", version)
    _validate_label_value("daemon_name", daemon_name)

    _state["initialized"] = True
    _state["repo"] = repo_label
    _state["version"] = version
    _state["daemon_name"] = daemon_name
    _state["lock"] = threading.Lock()

    _state["ticks"] = _Counter(
        "lazycortex_runtime_routine_ticks_total",
        "Routine ticks dispatched by the runtime daemon.",
        ("repo", "routine", "status"),
    )
    _state["errors"] = _Counter(
        "lazycortex_runtime_routine_errors_total",
        "Routine ticks that ended in error.",
        ("repo", "routine", "reason"),
    )
    _state["tokens"] = _Counter(
        "lazycortex_runtime_tokens_total",
        "Anthropic API tokens consumed by routine subprocesses.",
        ("repo", "routine", "model", "kind"),
    )
    _state["duration"] = _Histogram(
        "lazycortex_runtime_routine_tick_duration_seconds",
        "Routine tick duration in seconds.",
        ("repo", "routine"),
    )
    _state["last_tick"] = _Gauge(
        "lazycortex_runtime_routine_last_tick_timestamp",
        "Unix timestamp of the most recent tick for this routine.",
        ("repo", "routine"),
    )
    _state["queue_depth"] = _Gauge(
        "lazycortex_runtime_queue_depth",
        "Expert queue depth by state — populated at scrape time from .experts/.jobs/.",
        ("repo", "expert", "state"),
    )
    _state["up"] = _Gauge(
        "lazycortex_runtime_up",
        "1 if the daemon's metrics endpoint is up.",
        (),
    )
    _state["daemon_halted"] = _Gauge(
        "lazycortex_runtime_daemon_halted",
        "1 if the daemon has halted on a dirty working tree, 0 otherwise.",
        ("repo", "reason", "triggered_by"),
    )
    _state["build_info"] = _Gauge(
        "lazycortex_runtime_build_info",
        "Static metadata for the running daemon (constant value 1).",
        ("repo", "version", "daemon_name"),
    )
    _state["halt_count"] = _Counter(
        "lazycortex_runtime_daemon_halts_total",
        "Cumulative number of times the daemon has halted.",
        ("repo", "reason", "triggered_by"),
    )

    _state["up"].set(None, 1)
    _state["build_info"].set(
        {"repo": repo_label, "version": version, "daemon_name": daemon_name}, 1,
    )

    _state["token_offset"] = 0  # populated by aggregate_tokens_from_log


def _resolve_status(exit_code: int, error: str | None) -> tuple[str, str | None]:
    """Map (exit_code, error) → (status, reason).

    Returns (status, None) for ok, else (status, reason).
    """
    if exit_code == 0:
        return ("ok", None)
    if error == "timeout":
        return ("timeout", "timeout")
    if error == "git_pre_failed":
        return ("error", "git_pre_failed")
    if error == "git_post_failed":
        return ("error", "git_post_failed")
    if exit_code == -1 and error is not None:
        # The pump's broad except wraps the original message as
        # "resolve: ..." or "unexpected: ..." — match the prefix.
        if error.startswith("resolve:"):
            return ("error", "resolve")
        if error.startswith("unexpected:"):
            return ("crash", "unexpected")
    return ("error", "subprocess_error")


def record_tick(routine: str, exit_code: int, duration_sec: float, error: str | None) -> None:
    if not is_enabled():
        return
    _validate_label_value("routine", routine)
    repo = _state["repo"]
    status, reason = _resolve_status(exit_code, error)

    with _state["lock"]:
        _state["ticks"].inc({"repo": repo, "routine": routine, "status": status})
        if reason is not None:
            _state["errors"].inc({"repo": repo, "routine": routine, "reason": reason})
        _state["duration"].observe({"repo": repo, "routine": routine}, float(duration_sec))
        _state["last_tick"].set({"repo": repo, "routine": routine}, time.time())


def record_daemon_halt(reason: str, triggered_by: str) -> None:
    if not is_enabled():
        return
    repo = _state["repo"]
    with _state["lock"]:
        labels = {"repo": repo, "reason": reason, "triggered_by": triggered_by}
        _state["daemon_halted"].set(labels, 1)
        _state["halt_count"].inc(labels)


def clear_daemon_halt() -> None:
    if not is_enabled():
        return
    with _state["lock"]:
        _state["daemon_halted"].clear()


# --- Read API for tests ------------------------------------------------------

def _registry_for(name: str):
    """Find the metric instance whose .name matches `name` (incl. histogram
    base name without _bucket/_sum/_count suffixes)."""
    if not is_enabled():
        return None
    for key in (
        "ticks", "errors", "tokens", "duration", "last_tick",
        "queue_depth", "up", "daemon_halted", "build_info", "halt_count",
    ):
        m = _state.get(key)
        if m is not None and m.name == name:
            return m
    return None


def get_value(metric_name: str, labels: dict[str, str]) -> float | None:
    """Return the current value of a counter or gauge series, or None if absent."""
    m = _registry_for(metric_name)
    if m is None:
        return None
    if not isinstance(m, (_Counter, _Gauge)):
        return None
    key = tuple(labels.get(k, "") for k in m.labelnames)
    return m.values.get(key)


def get_bucket_value(metric_name: str, labels: dict[str, str], le: str) -> float | None:
    """Return histogram bucket count for `le=...`. `le` is the bucket label
    string ('0.5', '1', '+Inf'). Returns None if the series is absent."""
    m = _registry_for(metric_name)
    if not isinstance(m, _Histogram):
        return None
    key = tuple(labels.get(k, "") for k in m.labelnames)
    state = m.values.get(key)
    if state is None:
        return None
    buckets, _sum, _count = state
    if le == "+Inf":
        return float(buckets[-1])
    for i, b in enumerate(_BUCKETS):
        if _bucket_label(b) == le:
            return float(buckets[i])
    return None


# --- Render + HTTP -----------------------------------------------------------

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def render() -> bytes:
    """Render the full Prometheus exposition document as UTF-8 bytes."""
    if not is_enabled():
        return b""
    lines: list[str] = []
    for key in (
        "up", "build_info", "ticks", "errors", "tokens",
        "duration", "last_tick", "queue_depth",
        "daemon_halted", "halt_count",
    ):
        m = _state.get(key)
        if m is None:
            continue
        lines.extend(m.render())
    return ("\n".join(lines) + "\n").encode("utf-8")


def _wsgi_app(environ, start_response):
    if environ.get("PATH_INFO", "/") not in ("/metrics", "/"):
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404\n"]
    body = render()
    start_response("200 OK", [
        ("Content-Type", CONTENT_TYPE),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def expose(bind: str = "127.0.0.1", port: int = 9464) -> WSGIServer:
    """Start a background HTTP server serving the exposition. Returns the
    WSGIServer; caller may inspect `.server_port` (useful when port=0)."""
    if not is_enabled():
        raise RuntimeError("metrics.expose() called before metrics.init()")
    server = make_server(bind, port, _wsgi_app)
    t = threading.Thread(target=server.serve_forever, name="lazycortex-metrics", daemon=True)
    t.start()
    _state["server"] = server
    _state["server_thread"] = t
    return server


# --- Repo-label resolver (Task A2) -------------------------------------------

def resolve_repo_label(repo_root: Path, override: str | None) -> str:
    if override:
        return override
    try:
        rc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_root), capture_output=True, text=True, check=False,
        )
        if rc.returncode == 0:
            url = rc.stdout.strip()
            if url:
                digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
                return digest[:12]
    except FileNotFoundError:
        pass
    return f"local-{repo_root.name}"


# --- Queue-depth filesystem scan (Task A3) -----------------------------------

def set_queue_depth_from_filesystem(repo_root: Path) -> None:
    """Populate the queue_depth gauge from the on-disk shape of
    `<repo_root>/.experts/.jobs/<expert>/<job>/`. Idempotent — clears the
    gauge before re-populating so removed jobs disappear."""
    if not is_enabled():
        return
    # `expert_pump.JOBS_BASE` is the source of truth: `.experts/.jobs`.
    base = repo_root / ".experts" / ".jobs"
    if not base.exists():
        _state["queue_depth"].clear()
        return

    counts: dict[tuple[str, str], int] = {}
    for expert_dir in base.iterdir():
        if not expert_dir.is_dir():
            continue
        expert = expert_dir.name
        if not _LABEL_VALUE_RE.match(expert):
            continue  # don't expand label cardinality on weird names
        for job_dir in expert_dir.iterdir():
            if not job_dir.is_dir():
                continue
            state = _classify_job_state(job_dir)
            counts[(expert, state)] = counts.get((expert, state), 0) + 1

    repo = _state["repo"]
    with _state["lock"]:
        _state["queue_depth"].clear()
        for (expert, state), n in counts.items():
            _state["queue_depth"].set(
                {"repo": repo, "expert": expert, "state": state}, n,
            )


def _classify_job_state(job_dir: Path) -> str:
    if (job_dir / "DONE").exists():
        return "done"
    # Heuristic for "running" — DONE absent and dir mtime < 30s ago suggests
    # active work. Plan accepts the simple version for v1.
    if time.time() - job_dir.stat().st_mtime < 30:
        return "running"
    if (job_dir / "READY").exists():
        return "ready"
    return "ready"  # default — anything in the queue without DONE is pending


# --- Token aggregation (Task B2) ---------------------------------------------

# Tokens are recorded into <repo>/.logs/lazy-core/runtime/tokens.jsonl by
# the expert pump. This module reads from a checkpointed offset stored
# in `_state["token_offset"]` (process-local; durable persistence comes
# with the Phase B XDG_STATE checkpoint file — Task B2 step 2).

def aggregate_tokens_from_log(repo_root: Path) -> None:
    if not is_enabled():
        return
    log_path = repo_root / ".logs" / "lazy-core" / "runtime" / "tokens.jsonl"
    if not log_path.exists():
        return
    import json
    offset = _state.get("token_offset", 0)
    repo = _state["repo"]
    with log_path.open("rb") as f:
        f.seek(offset)
        for raw in f:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            routine = rec.get("routine") or "expert-pump"
            model = rec.get("model") or "unknown"
            if not _LABEL_VALUE_RE.match(routine) or not _LABEL_VALUE_RE.match(model):
                continue
            for kind, key in (
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("cache_read", "cache_read"),
                ("cache_write", "cache_write"),
            ):
                n = rec.get(key) or 0
                if n:
                    _state["tokens"].inc(
                        {"repo": repo, "routine": routine, "model": model, "kind": kind},
                        amount=float(n),
                    )
        offset = f.tell()
    _state["token_offset"] = offset
