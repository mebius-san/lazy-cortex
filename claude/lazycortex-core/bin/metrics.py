"""
Stdlib-only Prometheus metrics for the lazycortex-core runtime daemon.

Every label value comes from a closed set declared in the observability plan
(`docs/plans/2026-05-05-runtime-observability.md`, `## Cross-cutting design decisions`).
Label values derived from raw user input, raw exception text, file paths, job ids,
branch names, commit shas, or hostnames are rejected. The `daemon_name` label is
intentionally a constant — operator identity (hostname) must not leak into metric
streams.

The module is inert until `init()` is called: the daemon invokes it only when
`lazy-core.runtime.metrics.enabled` is true, so importing this module is free
when metrics are disabled.

The text exposition format follows the OpenMetrics spec
(https://prometheus.io/docs/instrumenting/exposition_formats/) so the daemon does
not need to pull in the `prometheus-client` third-party dependency.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server


_LABEL_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_label_value(label: str, value: str) -> None:
  """
  Validate that a label value belongs to the closed character set.

  Args:
    label: Name of the label being validated, used in the error message.
    value: Candidate value to validate.

  Raises:
    ValueError: If `value` contains characters outside `[A-Za-z0-9._-]`.
  """
  # guard: closed-vocabulary check rejects anything outside the allowed character set
  if not _LABEL_VALUE_RE.match(value):
    raise ValueError(
      f"label {label!r} got value {value!r} — closed-vocabulary guard "
      "rejects values outside [A-Za-z0-9._-]"
    )


def _format_labels(labels: dict[str, str]) -> str:
  """
  Render a label dict as the Prometheus exposition-format label block.

  Args:
    labels: Mapping of label names to label values.

  Returns:
    Empty string when `labels` is empty; otherwise a `{name="value",...}` block
    with keys sorted for deterministic output.
  """
  # guard: empty label set renders as no block at all
  if not labels:
    return ""
  # sort keys for deterministic output (tests + diff stability)
  pairs = []
  for key in sorted(labels):
    val = str(labels[key]).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    pairs.append(f'{key}="{val}"')
  return "{" + ",".join(pairs) + "}"


def _format_value(value: float) -> str:
  """
  Render a numeric metric value for the Prometheus exposition format.

  Args:
    value: Numeric value to render.

  Returns:
    Integer form when the value is whole; `repr` form otherwise so non-integer
    floats round-trip without precision loss.
  """
  # guard: integer-valued floats render as bare integers for cleaner output
  if value == int(value):
    return str(int(value))
  return repr(value)


class _Counter:
  """
  Monotonically increasing Prometheus counter with a fixed label schema.

  Attributes:
    name: Metric name as it appears in the exposition output.
    help: Human-readable description rendered as the `# HELP` line.
    labelnames: Tuple of label names accepted by this counter; every `inc` call
      must provide values for exactly these labels.
    values: Mapping from label-value tuples to the accumulated counter value.
  """


  def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...]):
    """
    Initialize the counter with a fixed name, help string, and label schema.

    Args:
      name: Metric name as it appears in the exposition output.
      help_text: Human-readable description rendered as the `# HELP` line.
      labelnames: Tuple of label names accepted by this counter.
    """
    self.name = name
    self.help = help_text
    self.labelnames = labelnames
    self.values: dict[tuple[str, ...], float] = {}


  def inc(self, label_values: dict[str, str], amount: float = 1.0) -> None:
    """
    Increment the counter series identified by the given label values.

    Args:
      label_values: Mapping providing a value for every label declared in `labelnames`.
      amount: Quantity to add to the current series value.

    Raises:
      ValueError: If any label value fails the closed-vocabulary check.
      KeyError: If `label_values` is missing one of the declared label names.
    """
    for key in self.labelnames:
      _validate_label_value(key, label_values[key])
    key = tuple(label_values[name] for name in self.labelnames)
    self.values[key] = self.values.get(key, 0.0) + amount


  def render(self) -> list[str]:
    """
    Render the counter as Prometheus exposition-format lines.

    Returns:
      A list of lines beginning with `# HELP` and `# TYPE` headers, followed by
      one line per label-value combination present in the counter.
    """
    out = [ f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter" ]
    for key, val in self.values.items():
      label_str = _format_labels(dict(zip(self.labelnames, key)))
      out.append(f"{self.name}{label_str} {_format_value(val)}")
    return out


class _Gauge:
  """
  Prometheus gauge holding a settable numeric value per label combination.

  Attributes:
    name: Metric name as it appears in the exposition output.
    help: Human-readable description rendered as the `# HELP` line.
    labelnames: Tuple of label names accepted by this gauge; an empty tuple
      means the gauge has a single unlabelled series.
    values: Mapping from label-value tuples to the current gauge value.
  """


  def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...] = ()):
    """
    Initialize the gauge with a fixed name, help string, and label schema.

    Args:
      name: Metric name as it appears in the exposition output.
      help_text: Human-readable description rendered as the `# HELP` line.
      labelnames: Tuple of label names accepted by this gauge; default is no labels.
    """
    self.name = name
    self.help = help_text
    self.labelnames = labelnames
    self.values: dict[tuple[str, ...], float] = {}


  def set(self, label_values: dict[str, str] | None, value: float) -> None:
    """
    Set the gauge series identified by the given label values to `value`.

    Args:
      label_values: Mapping providing a value for every label declared in `labelnames`,
        or None for an unlabelled gauge.
      value: New value to record for the series.

    Raises:
      ValueError: If any label value fails the closed-vocabulary check.
      KeyError: If `label_values` is missing one of the declared label names.
    """
    label_values = label_values or {}
    for key in self.labelnames:
      _validate_label_value(key, label_values[key])
    key = tuple(label_values[name] for name in self.labelnames)
    self.values[key] = float(value)


  def clear(self) -> None:
    """
    Remove every recorded series so subsequent renders emit only the headers.
    """
    self.values = {}


  def render(self) -> list[str]:
    """
    Render the gauge as Prometheus exposition-format lines.

    Returns:
      A list of lines beginning with `# HELP` and `# TYPE` headers, followed by
      one line per label-value combination present in the gauge.
    """
    out = [ f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge" ]
    for key, val in self.values.items():
      label_str = _format_labels(dict(zip(self.labelnames, key)))
      out.append(f"{self.name}{label_str} {_format_value(val)}")
    return out


_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)


def _bucket_label(bucket: float) -> str:
  """
  Render a histogram bucket boundary as the string used in the `le` label.

  Args:
    bucket: Bucket upper-bound value.

  Returns:
    Integer string when the boundary is whole; `repr` form otherwise.
  """
  # guard: whole-number bucket boundaries render as bare integers
  if bucket == int(bucket):
    return str(int(bucket))
  return repr(bucket)


class _Histogram:
  """
  Prometheus histogram with a fixed bucket schedule and a fixed label schema.

  Attributes:
    name: Metric name as it appears in the exposition output.
    help: Human-readable description rendered as the `# HELP` line.
    labelnames: Tuple of label names accepted by this histogram.
    values: Mapping from label-value tuples to a `[bucket_counts, sum, count]`
      list. `bucket_counts` has one slot per entry in `_BUCKETS` plus a trailing
      `+Inf` slot that accumulates every observation.
  """


  def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...]):
    """
    Initialize the histogram with a fixed name, help string, and label schema.

    Args:
      name: Metric name as it appears in the exposition output.
      help_text: Human-readable description rendered as the `# HELP` line.
      labelnames: Tuple of label names accepted by this histogram.
    """
    self.name = name
    self.help = help_text
    self.labelnames = labelnames
    # key = label tuple; value = [bucket_counts, sum, count]
    self.values: dict[tuple[str, ...], list] = {}


  def observe(self, label_values: dict[str, str], value: float) -> None:
    """
    Record one observation against the histogram series identified by `label_values`.

    Args:
      label_values: Mapping providing a value for every label declared in `labelnames`.
      value: Observed numeric value.

    Raises:
      ValueError: If any label value fails the closed-vocabulary check.
      KeyError: If `label_values` is missing one of the declared label names.
    """
    for key in self.labelnames:
      _validate_label_value(key, label_values[key])
    key = tuple(label_values[name] for name in self.labelnames)
    # guard: lazily initialize the per-key bucket state on first observation
    if key not in self.values:
      # trailing +1 slot is the +Inf bucket
      self.values[key] = [ [ 0 ] * (len(_BUCKETS) + 1), 0.0, 0 ]
    buckets, total_sum, total_count = self.values[key]
    for idx, bucket in enumerate(_BUCKETS):
      if value <= bucket:
        buckets[idx] += 1
    # +Inf bucket accumulates every observation regardless of magnitude
    buckets[-1] += 1
    self.values[key] = [ buckets, total_sum + value, total_count + 1 ]


  def render(self) -> list[str]:
    """
    Render the histogram as Prometheus exposition-format lines.

    Returns:
      A list of lines beginning with `# HELP` and `# TYPE` headers, followed by
      per-bucket, `_sum`, and `_count` lines for each label-value combination.
    """
    out = [ f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram" ]
    for key, (buckets, total_sum, total_count) in self.values.items():
      base_labels = dict(zip(self.labelnames, key))
      for idx, bucket in enumerate(_BUCKETS):
        lbls = { **base_labels, "le": _bucket_label(bucket) }
        out.append(f"{self.name}_bucket{_format_labels(lbls)} {buckets[idx]}")
      inf_lbls = { **base_labels, "le": "+Inf" }
      out.append(f"{self.name}_bucket{_format_labels(inf_lbls)} {buckets[-1]}")
      out.append(f"{self.name}_sum{_format_labels(base_labels)} {_format_value(total_sum)}")
      out.append(f"{self.name}_count{_format_labels(base_labels)} {total_count}")
    return out


# Module-level state — populated by init().
_state: dict = {}


def _reset_for_tests() -> None:
  """
  Discard every metric series and registered configuration recorded by `init`.

  Intended for use only by test fixtures that need to start each test from a
  pristine module state.
  """
  _state.clear()


def is_enabled() -> bool:
  """
  Return whether the metrics module has been initialized.

  Returns:
    True after a successful `init` call; False otherwise.
  """
  return bool(_state.get("initialized"))


def init(repo_label: str, version: str, daemon_name: str) -> None:
  """
  Initialize module state so subsequent `record_*` calls produce metrics.

  Must be called before any other module-level recording function. The
  `daemon_name` label is constant per repo; passing a hostname or other
  per-machine identifier here violates the closed-vocabulary contract.

  Args:
    repo_label: Per-repo identifier used as the value of the `repo` label.
    version: Version of the lazycortex-core plugin reported via `build_info`.
    daemon_name: Constant identifier of the running daemon (never the hostname).

  Raises:
    ValueError: If any argument fails the closed-vocabulary label check.
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
    { "repo": repo_label, "version": version, "daemon_name": daemon_name }, 1,
  )

  # token_offset is populated by aggregate_tokens_from_log on each scrape
  _state["token_offset"] = 0


def _resolve_status(exit_code: int, error: str | None) -> tuple[str, str | None]:
  """
  Map a routine subprocess outcome to a (status, reason) label pair.

  Args:
    exit_code: Exit code reported by the routine subprocess.
    error: Optional error tag reported by the runtime daemon. The daemon's broad
      `except` wraps the original message as `"resolve: ..."` or `"unexpected: ..."`;
      this function matches those prefixes.

  Returns:
    A `(status, reason)` tuple. `status` is one of `"ok"`, `"timeout"`, `"error"`,
    `"crash"`; `reason` is None when status is `"ok"` and a closed-set string otherwise.
  """
  # guard: clean exit short-circuits to ok with no reason
  if exit_code == 0:
    return ("ok", None)
  if error == "timeout":
    return ("timeout", "timeout")
  if error == "git_pre_failed":
    return ("error", "git_pre_failed")
  if error == "git_post_failed":
    return ("error", "git_post_failed")
  if exit_code == -1 and error is not None:
    # the daemon's broad except wraps the original message as
    # "resolve: ..." or "unexpected: ..." — match the prefix
    if error.startswith("resolve:"):
      return ("error", "resolve")
    if error.startswith("unexpected:"):
      return ("crash", "unexpected")
  return ("error", "subprocess_error")


def record_tick(routine: str, exit_code: int, duration_sec: float, error: str | None) -> None:
  """
  Record one completed routine tick across the relevant counters, histogram, and gauge.

  Args:
    routine: Routine name; must satisfy the closed-vocabulary label check.
    exit_code: Exit code reported by the routine subprocess.
    duration_sec: Wall-clock duration of the tick in seconds.
    error: Optional error tag from the runtime daemon, in the format described
      by `_resolve_status`.

  Raises:
    ValueError: If `routine` fails the closed-vocabulary label check.
  """
  # guard: metrics are off — recording is a no-op
  if not is_enabled():
    return
  _validate_label_value("routine", routine)
  repo = _state["repo"]
  status, reason = _resolve_status(exit_code, error)

  with _state["lock"]:
    _state["ticks"].inc({ "repo": repo, "routine": routine, "status": status })
    if reason is not None:
      _state["errors"].inc({ "repo": repo, "routine": routine, "reason": reason })
    _state["duration"].observe({ "repo": repo, "routine": routine }, float(duration_sec))
    _state["last_tick"].set({ "repo": repo, "routine": routine }, time.time())


def record_daemon_halt(reason: str, triggered_by: str) -> None:
  """
  Record that the daemon has halted, raising the gauge and incrementing the halt counter.

  Args:
    reason: Closed-set string identifying why the daemon halted.
    triggered_by: Closed-set string identifying the trigger of the halt.
  """
  # guard: metrics are off — recording is a no-op
  if not is_enabled():
    return
  repo = _state["repo"]
  with _state["lock"]:
    labels = { "repo": repo, "reason": reason, "triggered_by": triggered_by }
    _state["daemon_halted"].set(labels, 1)
    _state["halt_count"].inc(labels)


def clear_daemon_halt() -> None:
  """
  Clear every recorded daemon-halted series so subsequent scrapes show no halt.

  The cumulative `halt_count` counter is left intact — only the live gauge is cleared.
  """
  # guard: metrics are off — recording is a no-op
  if not is_enabled():
    return
  with _state["lock"]:
    _state["daemon_halted"].clear()


# --- Read API for tests ------------------------------------------------------

def _registry_for(name: str):
  """
  Look up a registered metric instance by its exposition-format name.

  Args:
    name: Metric base name (the same string passed to the metric's constructor;
      no `_bucket`, `_sum`, or `_count` suffix).

  Returns:
    The matching `_Counter`, `_Gauge`, or `_Histogram` instance, or None when
    the module is not initialized or no metric matches the name.
  """
  # guard: metrics are off — no registry to look up
  if not is_enabled():
    return None
  for key in (
    "ticks", "errors", "tokens", "duration", "last_tick",
    "queue_depth", "up", "daemon_halted", "build_info", "halt_count",
  ):
    metric = _state.get(key)
    if metric is not None and metric.name == name:
      return metric
  return None


def get_value(metric_name: str, labels: dict[str, str]) -> float | None:
  """
  Return the current value of a counter or gauge series.

  Args:
    metric_name: Exposition-format name of the counter or gauge.
    labels: Mapping providing a value for every label declared by the metric.

  Returns:
    The current series value, or None when the metric is not registered, is not
    a counter or gauge, or has no value recorded for the given label combination.
  """
  metric = _registry_for(metric_name)
  # guard: metric not registered
  if metric is None:
    return None
  # guard: histograms expose values via get_bucket_value, not this entry point
  if not isinstance(metric, (_Counter, _Gauge)):
    return None
  key = tuple(labels.get(name, "") for name in metric.labelnames)
  return metric.values.get(key)


def get_bucket_value(metric_name: str, labels: dict[str, str], le: str) -> float | None:
  """
  Return the count in one histogram bucket for the given label combination.

  Args:
    metric_name: Exposition-format base name of the histogram.
    labels: Mapping providing a value for every label declared by the histogram.
    le: Bucket label string — `'0.5'`, `'1'`, `'+Inf'`, etc.

  Returns:
    The bucket count as a float, or None when the metric is not a registered
    histogram, has no series for the given labels, or the `le` value does not
    match any configured bucket boundary.
  """
  metric = _registry_for(metric_name)
  # guard: only histograms expose bucket values
  if not isinstance(metric, _Histogram):
    return None
  key = tuple(labels.get(name, "") for name in metric.labelnames)
  state = metric.values.get(key)
  # guard: series has no observations yet
  if state is None:
    return None
  buckets, _sum, _count = state
  if le == "+Inf":
    return float(buckets[-1])
  for idx, bucket in enumerate(_BUCKETS):
    if _bucket_label(bucket) == le:
      return float(buckets[idx])
  return None


# --- Render + HTTP -----------------------------------------------------------

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def render() -> bytes:
  """
  Render every registered metric as a single Prometheus exposition document.

  Returns:
    UTF-8 encoded exposition document, or an empty byte string when the module
    has not been initialized.
  """
  # guard: metrics are off — render an empty document
  if not is_enabled():
    return b""
  lines: list[str] = []
  for key in (
    "up", "build_info", "ticks", "errors", "tokens",
    "duration", "last_tick", "queue_depth",
    "daemon_halted", "halt_count",
  ):
    metric = _state.get(key)
    # guard: metric not yet registered — skip silently
    if metric is None:
      continue
    lines.extend(metric.render())
  return ("\n".join(lines) + "\n").encode("utf-8")


def _wsgi_app(environ, start_response):
  """
  Serve the Prometheus exposition document for the `/metrics` and root endpoints.

  Args:
    environ: WSGI environ dict supplied by the server.
    start_response: WSGI start-response callable supplied by the server.

  Returns:
    A list containing one byte string — the exposition body for known paths or
    a short `404\\n` for everything else.
  """
  # guard: unknown path — return 404 without rendering metrics
  if environ.get("PATH_INFO", "/") not in ("/metrics", "/"):
    start_response("404 Not Found", [ ("Content-Type", "text/plain; charset=utf-8") ])
    return [ b"404\n" ]
  body = render()
  start_response("200 OK", [
    ("Content-Type", CONTENT_TYPE),
    ("Content-Length", str(len(body))),
  ])
  return [ body ]


def expose(bind: str = "127.0.0.1", port: int = 9464) -> WSGIServer:
  """
  Start a background HTTP server that serves the Prometheus exposition document.

  Args:
    bind: Interface address to bind the server to.
    port: TCP port to listen on; pass 0 to let the OS choose a free port.

  Returns:
    The `WSGIServer` instance; callers may inspect `.server_port` (useful when
    `port=0`) and may store the reference to shut the server down later.

  Raises:
    RuntimeError: If called before `init()`.
  """
  # guard: refuse to expose metrics that have not been initialized
  if not is_enabled():
    raise RuntimeError("metrics.expose() called before metrics.init()")
  server = make_server(bind, port, _wsgi_app)
  thread = threading.Thread(target = server.serve_forever, name = "lazycortex-metrics", daemon = True)
  thread.start()
  _state["server"] = server
  _state["server_thread"] = thread
  return server


# --- Repo-label resolver (Task A2) -------------------------------------------

def resolve_repo_label(repo_root: Path, override: str | None) -> str:
  """
  Resolve a stable, low-cardinality `repo` label for the given checkout.

  Args:
    repo_root: Absolute path to the repository root.
    override: Explicit label provided by configuration; when non-empty, returned as-is.

  Returns:
    The override when supplied; otherwise the first 12 hex chars of the SHA-1
    of the `origin` remote URL when one is configured; otherwise a `local-<name>`
    fallback derived from the directory name.
  """
  # guard: explicit override wins
  if override:
    return override
  try:
    rc = subprocess.run(
      ["git", "remote", "get-url", "origin"],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
    if rc.returncode == 0:
      url = rc.stdout.strip()
      if url:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return digest[:12]
  except FileNotFoundError:
    # git binary not present on PATH — fall through to the local-name fallback
    pass
  return f"local-{repo_root.name}"


# --- Queue-depth filesystem scan (Task A3) -----------------------------------

def set_queue_depth_from_filesystem(repo_root: Path) -> None:
  """
  Populate the `queue_depth` gauge from the on-disk shape of the expert job dirs.

  Scans `<repo_root>/.experts/.jobs/<expert>/<job>/` and emits one gauge series
  per `(expert, state)` combination. The gauge is cleared before re-populating
  so jobs that have been removed disappear from the next scrape.

  Args:
    repo_root: Absolute path to the repository root.
  """
  # guard: metrics are off — scanning the filesystem is wasted work
  if not is_enabled():
    return
  # `expert_pump.JOBS_BASE` is the source of truth: `.experts/.jobs`
  base = repo_root / ".experts" / ".jobs"
  # guard: no jobs directory — clear the gauge and bail
  if not base.exists():
    _state["queue_depth"].clear()
    return

  counts: dict[tuple[str, str], int] = {}
  for expert_dir in base.iterdir():
    if not expert_dir.is_dir():
      continue
    expert = expert_dir.name
    # guard: skip names that would expand label cardinality outside the closed set
    if not _LABEL_VALUE_RE.match(expert):
      continue
    for job_dir in expert_dir.iterdir():
      if not job_dir.is_dir():
        continue
      state = _classify_job_state(job_dir)
      counts[(expert, state)] = counts.get((expert, state), 0) + 1

  repo = _state["repo"]
  with _state["lock"]:
    _state["queue_depth"].clear()
    for (expert, state), num in counts.items():
      _state["queue_depth"].set(
        { "repo": repo, "expert": expert, "state": state }, num,
      )


def _classify_job_state(job_dir: Path) -> str:
  """
  Classify an expert job directory into the closed-set state label.

  Mirrors `expert_runtime._job_status` so the metric matches the runtime's own
  view of each job. Possible return values: `queued`, `active`, `dead`, `done`,
  `failed`. The filesystem signatures consulted are:

  - DEAD marker present                                  → dead
  - DONE marker + response.json with outcome == "error"  → failed
  - DONE marker present                                  → done
  - READY marker + PID file (no DEAD, no response.json)  → active
  - READY marker only (no PID file)                      → queued
  - none of the above                                    → queued (fallback)

  Args:
    job_dir: Path to the job directory under `.experts/.jobs/<expert>/`.

  Returns:
    The closed-set state label for the job.
  """
  if (job_dir / "DEAD").exists():
    return "dead"
  if (job_dir / "DONE").exists():
    resp_path = job_dir / "response.json"
    if resp_path.exists():
      try:
        outcome = json.loads(resp_path.read_text()).get("outcome")
        if outcome == "error":
          return "failed"
      except json.JSONDecodeError:
        # malformed response.json — treat as a generic done
        pass
    return "done"
  if (job_dir / "READY").exists():
    if (job_dir / "PID").exists():
      return "active"
    return "queued"
  # fallback for partial / in-flight job dirs
  return "queued"


# --- Token aggregation (Task B2) ---------------------------------------------

# Tokens are recorded into <repo>/.logs/lazy-core/runtime/tokens.jsonl by
# the expert pump. This module reads from a checkpointed offset stored
# in `_state["token_offset"]` (process-local; durable persistence comes
# with the Phase B XDG_STATE checkpoint file — Task B2 step 2).

def aggregate_tokens_from_log(repo_root: Path) -> None:
  """
  Fold new entries from the expert-pump token log into the `tokens` counter.

  Reads `<repo_root>/.logs/lazy-core/runtime/tokens.jsonl` starting from the
  byte offset recorded in module state and advances the offset to the end of
  the file. Malformed lines and entries with label values outside the closed
  set are skipped silently so a corrupt suffix does not poison the counter.

  Args:
    repo_root: Absolute path to the repository root.
  """
  # guard: metrics are off — skip the log read entirely
  if not is_enabled():
    return
  log_path = repo_root / ".logs" / "lazy-core" / "runtime" / "tokens.jsonl"
  # guard: no token log yet — nothing to aggregate
  if not log_path.exists():
    return
  offset = _state.get("token_offset", 0)
  repo = _state["repo"]
  with log_path.open("rb") as f:
    f.seek(offset)
    for raw in f:
      try:
        rec = json.loads(raw.decode("utf-8"))
      except (UnicodeDecodeError, json.JSONDecodeError):
        # malformed line — skip without poisoning the counter
        continue
      routine = rec.get("routine") or "expert-pump"
      model = rec.get("model") or "unknown"
      # guard: closed-vocabulary check rejects entries with unsafe label values
      if not _LABEL_VALUE_RE.match(routine) or not _LABEL_VALUE_RE.match(model):
        continue
      for kind, key in (
        ("input", "input_tokens"),
        ("output", "output_tokens"),
        ("cache_read", "cache_read"),
        ("cache_write", "cache_write"),
      ):
        num = rec.get(key) or 0
        if num:
          _state["tokens"].inc(
            { "repo": repo, "routine": routine, "model": model, "kind": kind },
            amount = float(num),
          )
    offset = f.tell()
  _state["token_offset"] = offset
