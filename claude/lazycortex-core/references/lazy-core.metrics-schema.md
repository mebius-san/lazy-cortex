---
description: The daemon's optional Prometheus `/metrics` surface — the `daemon.metrics` settings block, multi-daemon port allocation on one host, and the closed metric and label vocabulary.
---
# lazy-core.metrics — the daemon's Prometheus surface

§ 12 of `lazy-core.runtime-schema.md`, extracted and read on demand: open this file when turning metrics on for a checkout, allocating a port on a host that runs several daemons, or reading a metric or label name off a dashboard. Its main consumer is the `lazycortex-observe` plugin. A `§ N` cross-reference below that names no file names a section of the parent.

## 12. Metrics

The daemon can serve a Prometheus-format `/metrics` HTTP endpoint covering routine throughput, error rates, tick durations, queue depth, halt status, and Anthropic API token usage. Off by default — opt in by adding a `metrics` block to the flat `daemon` section (`daemon.metrics`).

### Settings

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. When false the metrics module is dormant — `import metrics` is free, no HTTP server runs. |
| `bind` | string | `"127.0.0.1"` | Listening address. **Default is loopback** — never expose off-host without an explicit operator decision. |
| `port` | int | `9464` | TCP port. `0` lets the OS pick (used in tests). On multi-daemon hosts the install skill allocates ports sequentially from 9464 and records each checkout's port in the **local overlay** (`lazy.settings.local.json`) — a port is a per-host operational fact and must not travel to other machines through the tracked file. |
| `repo_label` | string or null | `null` | Override for the `repo` label. Default is the human-readable `<basename>` — the checkout directory name verbatim (this is the key operators tell daemons apart by on dashboards); when the directory name falls outside the label charset `[A-Za-z0-9._-]`, a 12-char SHA1 prefix of `git remote get-url origin` is used instead. |
| `daemon_name` | string or null | `null` | Override for the `daemon_name` label. Default constant `"lazycortex-runtime"`. **The daemon never reads `os.uname()`** — operator hostname must not leak into the metric stream. |

### Example

```json
{
  "daemon": {
    "metrics": {
      "enabled": true,
      "bind": "127.0.0.1",
      "port": 9464
    }
  }
}
```

Restart the daemon to flip enablement on or off. Settings are reloaded inside the loop for routine hot-reload, but `metrics.init()` runs once at startup.

### Multi-daemon on one host

Several checkouts can each run their own daemon on one machine; every metrics-enabled daemon needs its own port. The pieces that make this hands-off:

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/`, or `claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

- **Registry** — the supervisor units themselves (`com.lazycortex.runtime.<REPO_ID>.plist` / `lazy-core-runtime-<REPO_ID>.service`) are the source of truth for "all daemons on this host". `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> daemon-list` prints them joined with each repo's `daemon.metrics` settings.
- **Port allocation** — `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> metrics-alloc-port --repo-root <path>` hands out the first free port from 9464 upward, skipping ports recorded by other daemons and ports that fail a live bind probe; a repo's already-recorded port is reused, unless a second registered daemon records the same one — a port that arrived by config copy rather than by allocation is not the repo's to keep, and the asking checkout is moved. The install skill runs this when enabling metrics.
- **Scrape targets file** — `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> metrics-scrape-file` writes `${XDG_CONFIG_HOME:-~/.config}/lazycortex/scrape-targets.json` in Prometheus `file_sd` format: one `{"targets": ["127.0.0.1:<port>"], "labels": {"repo": "<label>"}}` entry per metrics-enabled daemon, nothing else (no paths, no hostnames). Point an existing Prometheus at it once with `file_sd_configs` and new daemons appear without further edits.
- **Port conflict at startup** — when the configured port is already bound, the daemon records a `daemon_error` incident with cause `metrics_port_conflict` (naming the holder: pid, command, and the owning repo when it is another registered daemon) and **keeps running without metrics**. A taken port never restart-loops the dispatch engine; the fix is re-running the install's metrics step (or editing the local-overlay port) and restarting the daemon.

### Metric shape

Closed label vocabulary — values come from a fixed enum, never from raw exception text, file paths, branch names, commit shas, hostnames, or any user-supplied string. The `repo` label disambiguates daemon instances; the constant `daemon_name` keeps operator identity out.

```
# Counters
lazycortex_runtime_routine_ticks_total{routine,repo,status}
lazycortex_runtime_routine_runs_total{routine,repo}
lazycortex_runtime_routine_errors_total{routine,repo,reason}
lazycortex_runtime_tokens_total{routine,repo,expert,model,kind}
lazycortex_runtime_expert_jobs_total{expert,repo,outcome}
lazycortex_runtime_daemon_halts_total{repo,reason,triggered_by}

# Histograms
lazycortex_runtime_routine_tick_duration_seconds{routine,repo}
lazycortex_runtime_expert_job_duration_seconds{expert,repo}

# Gauges
lazycortex_runtime_routine_last_tick_timestamp{routine,repo}
lazycortex_runtime_queue_depth{expert,repo,state}
lazycortex_runtime_daemon_halted{repo,reason,triggered_by}
lazycortex_runtime_dirty_tree{repo}
lazycortex_runtime_up
lazycortex_runtime_build_info{version,daemon_name,repo}
```

`status` ∈ `{ok, error, timeout, crash}`. `state` ∈ `{queued, active, done, deferred, failed, dead, cancelled}` — the same classification `expert_runtime` applies to a bundle, read from the job dirs at scrape time; only `queued` and `active` are work the pump will still do, the other five are terminal and linger until their retention window elapses. `kind` ∈ `{input, output, cache_read, cache_write}`. `outcome` ∈ `{done, failed, dead, error}` — per job attempt, aggregated from the pump's `.logs/lazy-core/runtime/jobs.jsonl`; `error` marks an attempt that failed transiently and left the job queued for retry, the other three are terminal.

`dirty_tree` is 1 while the daemon's pre-iteration check finds uncommitted changes and routine dispatch is silently paused (the operator may be mid-edit); it drops back to 0 on the first iteration after the tree settles. This is the only externally visible trace of the silent skip — it is not a halt and records no incident.

`routine_runs_total` counts only non-idle ticks: a tick whose routine type reports an explicit `dispatched_count` of 0 (an inbox / md-scan / git poll that matched nothing) increments `ticks_total` but not `runs_total`. Ticks from types that report no dispatch count always count as runs. `ticks_total` is the scheduler heartbeat; `runs_total` is the real-work rate.

The `reason` label is metric-specific:

- On `routine_errors_total` (routine tick failures): `{timeout, resolve, subprocess_error, unexpected, git_pre_failed, git_post_failed, external_dir_broken, routine_config_invalid}`. `routine_config_invalid` is the one value that marks a permanently broken entry rather than a failed run — it never clears on its own and needs a settings edit.
- On `daemon_halts_total` / `daemon_halted` (gauge): `{uncommitted_changes, git_pull_diverged, git_push_failed, git_remote_unavailable, git_local_failed, suspected_loop, inbox_collision, routine_config_invalid, config_violation, rate_limit}` — the ten halt reasons of `lazy-core.state-schema.md` § 9. The label carries whatever reason `_halt_daemon` was handed, so it tracks that list and not the `HaltReason` enum, which is missing `config_violation`; the value is a fixed token either way, never raw exception text.

### Shipping to a Prometheus + Grafana stack

The endpoint is local-only by default. To ship metrics to a self-hosted observer, install the public `lazycortex-observe` plugin — it ships generic Grafana Alloy / OpenTelemetry Collector templates, launchd / systemd service units, a Grafana dashboard JSON, and Prometheus alert rules. The plugin is observer-server-blind: no hostnames, tokens, or operator-private identifiers in any shipped file. Operator-private values live in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and the `LAZYCORTEX_OBSERVE_TOKEN` env var.

Versioned independently of `lazycortex-core` via the file's `version:` frontmatter. Bump the contract's version when the schema changes; experts re-read it on next dispatch (no daemon restart needed).
