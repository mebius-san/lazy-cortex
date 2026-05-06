---
description: Architecture reference for the per-repo runtime daemon — lifecycle, routine registration, plugin-cache resolution, and the `lazy-core.runtime` section of `lazy.settings.json`.
---
# lazy-core.runtime

Architecture reference for the per-repo runtime daemon. Audience: plugin authors who need to register routines or understand how the daemon behaves at runtime.

---

## 1. Daemon lifecycle

One runtime daemon process runs per repo. It runs as a supervised service; the supervisor (launchd on macOS, systemd on Linux) restarts it if it crashes. The daemon itself is single-threaded and runs routines serially — no two routines execute concurrently.

On every iteration the daemon re-reads `.claude/lazy.settings.json` (section `lazy-core.runtime`). Config changes take effect on the next iteration without a restart.

The daemon's main cycle:

1. Re-read `lazy-core.runtime` section from settings.
2. Execute pre-iteration git ops (if `daemon.git` is set).
3. Run all due routines in registration order.
4. Execute post-iteration git ops (if `daemon.git` is set).
5. Sleep until the earliest next-due routine (capped at `polling_interval_sec`).

---

## 2. `daemon` block fields

The `daemon` key is optional. When absent, no git ops are performed and `polling_interval_sec` defaults to 5 seconds.

| Field | Type | Default | Description |
|---|---|---|---|
| `git` | `null` or object | `null` | Git integration block. `null` means no git ops. |
| `polling_interval_sec` | int | `5` | Maximum sleep between runtime iterations. |
| `cleanup_completed_after` | duration string | `"7d"` | Age after which a completed job dir is deleted. |
| `cleanup_failed_after` | duration string | `"30d"` | Age after which a failed job dir is deleted. |
| `cleanup_runtime_log_after` | duration string | `"30d"` | Age after which a per-day `.logs/lazy-core/runtime/<date>.jsonl` file is deleted. `tokens.jsonl` is append-only and not subject to this retention — operators rotate it manually. |

Duration strings: a number followed by a unit suffix — `s`, `m`, `h`, or `d` (e.g. `"30d"`, `"12h"`, `"300s"`).

### `daemon.git` sub-fields

| Field | Type | Description |
|---|---|---|
| `branch` | string | **Required.** Branch the daemon checks out exclusively each iteration. |
| `remote_sync` | `"pull"` / `"pull_push"` | Optional. `"pull"` does `git pull --ff-only` after checkout. `"pull_push"` additionally does `git push` after routines run. Absent = no remote sync. |

**Pre-iteration ops** (when `daemon.git` is set): `git checkout -B <branch>` (reset to current HEAD), then `git pull --ff-only` if `remote_sync` is `"pull"` or `"pull_push"`.

**Post-iteration ops**: `git push` if `remote_sync` is `"pull_push"`.

The daemon's branch is daemon-exclusive. Do not push to it from other processes while the daemon is running.

### Example `lazy-core.runtime` block

```json
{
  "lazy-core.runtime": {
    "_version": 1,
    "daemon": {
      "git": {
        "branch": "daemon/main",
        "remote_sync": "pull_push"
      },
      "polling_interval_sec": 30,
      "cleanup_completed_after": "7d",
      "cleanup_failed_after": "30d"
    },
    "routines": {
      "lazy-expert.pump": {
        "interval_sec": 30,
        "command": ["lazycortex-core", "expert-pump-once"]
      },
      "my-plugin.nightly-sync": {
        "interval_sec": 3600,
        "command": ["my-plugin", "sync"],
        "timeout_sec": 120
      }
    }
  }
}
```

---

## 3. `routines` block fields

Each key under `routines` is the routine name (dot-namespaced, e.g. `lazy-expert.pump`). The value is:

| Field | Type | Required | Description |
|---|---|---|---|
| `interval_sec` | int | yes | How often to run this routine (in seconds). |
| `command` | array of strings | yes | `[<plugin-name>, <args>...]`. First element is resolved via plugin cache (see § 4). |
| `timeout_sec` | int | no | Per-run timeout. Default: 300 seconds. |

A routine is considered due when `now - last_run >= interval_sec`. If the daemon was down, overdue routines run on the first iteration after restart — there is no skip-if-late logic.

---

## 4. Plugin-cache resolution

The first element of `command` is a plugin name. The daemon resolves it at runtime to:

```
~/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>
```

Resolution steps:

1. Glob `~/.claude/plugins/cache/*/<plugin>` to find all registry/plugin dirs.
2. Collect all version subdirectories across those dirs.
3. Lex-sort version directory names in descending order; take the first (latest).
4. Assert `<version>/bin/<plugin>` exists and is executable.

**Always-latest semantics**: no pin syntax. The daemon always runs the latest cached version of the plugin. If two registries both carry a plugin by the same name, all versions from both are pooled and the globally-latest wins.

**Lex-sort caveat**: works correctly for single-digit major versions (`1.x`, `9.x`). When a plugin crosses `10.0`, lex sort will mis-rank it. This is a known deferred limitation.

---

## 5. Retry policy boundary

**The runtime daemon does not retry plain routine commands.** If a routine exits non-zero, the daemon logs the result and moves on. No automatic backoff or re-schedule.

The only built-in retry is in `expert-pump-once` for `claude --agent` spawns: 5 attempts with exponential backoff (delays: 1, 2, 4, 8, 16 seconds). This lives in `bin/expert_pump.py`, not in the daemon.

Plugin authors writing their own routine commands are responsible for their own retry and backoff logic.

**Working-tree protection (§ 10) is a separate invariant from retry.** A routine that leaves the working tree dirty is halted permanently — no retry, no backoff, no re-schedule. The operator must run `/lazy-runtime.recover` before any routine fires again.

---

## 6. Where logs land

Each routine result is appended as a JSON line to:

```
<repo>/.logs/lazy-core/runtime/<YYYY-MM-DD>.jsonl
```

Dates are UTC. A new file is created each calendar day; no rotation beyond daily files.

Per-routine record shape:

```json
{
  "ts": 1746230400.0,
  "name": "lazy-expert.pump",
  "exit": 0,
  "duration_sec": 1.23,
  "stdout_tail": "...",
  "stderr_tail": "...",
  "error": "timeout"
}
```

`error` is present only on exception-level failures (timeout, resolve failure, unexpected exception). `exit` is `-1` on those failures; `stdout_tail` / `stderr_tail` may be absent. `error` is absent on normal subprocess completion (even if exit != 0).

---

## 7. Public API

**Adding a routine from Python:**

```python
from expert_runtime import register_routine
# Legacy subprocess shape (still supported)
register_routine(repo, "my-plugin.task", ["my-plugin", "run-task"], interval_sec=300)
# Typed cfg shape (required for inbox / schedule / git — see § 8)
register_routine(repo, "docs.inbox", {
    "type": "inbox",
    "inbox_dir": ".inbox/docs/",
    "expert": "doc-ingester",
    "request": {"role": "process", "file": "{file}"},
    "interval_sec": 600,
})
```

Both call shapes go through `routine_types.validate_routine_entry` before write — bad cfg raises `RoutineConfigError` at the boundary. Or use the `lazy-routine.register` skill (type-aware interactive wizard, writes to `.claude/lazy.settings.json`).

**Removing a routine:**

```python
from expert_runtime import unregister_routine
unregister_routine(repo, "my-plugin.task")
```

Or via the `lazy-routine.unregister` skill.

Both helpers are idempotent and use the atomic write path in `lazy_settings.py`.

---

## 8. Routine types

Each entry under `routines` may carry an optional `type` field. Default is `subprocess`. Allowed values + per-type shape:

| Type | Required fields | Optional fields |
|---|---|---|
| `subprocess` (default) | `command`, `interval_sec` | `timeout_sec` |
| `inbox` | `inbox_dir`, `expert`, `request`, `interval_sec` | `timeout_sec` |
| `schedule` | `cron`, plus EITHER `command` OR `expert`+`request` | `timeout_sec` |
| `git` | `branch`, `watch`, `expert`, `request`, `interval_sec` | `repo_dir`, `remote`, `path_filter`, `timeout_sec` |

Closed-set strict validation: unknown type, unknown field, missing required, or per-type custom constraint violation → `RoutineConfigError` at registration time.

### `inbox`

Scans `inbox_dir` each tick. For every non-hidden, non-dir, non-symlink file:

1. Create `<repo>/.experts/.jobs/<expert>/<uuid>/source/`.
2. `f.rename(...)` the file into `source/<filename>` (atomic on same filesystem).
3. Render `request` template — substitute `{file}` with the filename in any string value.
4. Write `request.json`, touch `READY`.

The inbox dir is empty when the routine returns. The expert handles the file from `<job_dir>/source/<filename>` afterwards.

### `schedule`

Fires when the cron expression has crossed a fire boundary since `last_run`. Skip-on-miss: multiple missed boundaries collapse to one fire (no catch-up).

Cron grammar: standard 5-field POSIX cron (`minute hour day month dow`). Supports `*`, `N`, `*/S`, `N-M`, `N-M/S`, comma lists. Day-of-week uses Sun=0..Sat=6. Day/dow uses AND when both restricted (deviation from POSIX OR — uncommon in real patterns). See `bin/cron.py`.

Sub-shapes:
- `command`: spawn subprocess (delegates to `dispatch_subprocess`).
- `expert + request`: dispatch one job to the expert; request template gets `{cron_fire_ts}` (ISO-8601) and `{cron_fire_unix}` (unix seconds) substituted.

### `git`

Watches `<remote>/<branch>` and dispatches one job per item per `watch`. Closed enum + per-watch templating variables:

| `watch` | Variables exposed in `request` template |
|---|---|
| `new_commits` | `{sha}`, `{short_sha}`, `{subject}`, `{author_name}`, `{author_email}`, `{commit_ts}` |
| `new_files` | `{path}`, `{status}`=A, `{sha}` |
| `changed_files` | `{path}`, `{status}` (A or M), `{sha}` |
| `deleted_files` | `{path}`, `{status}`=D, `{sha}` |
| `renamed_files` | `{old_path}`, `{new_path}`, `{sha}` |

`last_seen_sha` tracked in state.json's `git_watch.<name>` block. First run records the current ref and dispatches nothing (no history backfill). Force-push detection (last_seen not ancestor of remote head) resets the baseline and dispatches nothing.

The git type is working-tree-neutral by construction: only `git fetch` (refs) and read-only `log`/`diff`/`rev-parse`. Cannot trigger the halt invariant on its own.

---

## 9. State persistence

The daemon persists scheduling and halt state at `<repo>/.logs/lazy-core/runtime/state.json`. Atomic temp+rename writes; load returns an empty schema on absent or unparseable file (so a corrupt state file never crashes the daemon).

Schema:

```json
{
  "last_run": {
    "<routine_name>": <unix_ts>
  },
  "git_watch": {
    "<routine_name>": { "last_seen_sha": "<full_hex>" }
  },
  "daemon_halted": {
    "halted_since": <unix_ts>,
    "triggered_by": "<routine_name>",
    "reason": "uncommitted_changes",
    "dirty_paths": ["<git status --porcelain line>", ...],
    "expert": "<expert_name|null>",
    "job_id": "<job_id|null>"
  }
}
```

`daemon_halted` is absent when healthy. `git_watch` is absent when no `git`-type routines are registered.

Persistence consequences:
- `last_run` survives daemon restart and laptop sleep — slow routines (e.g. every 6h) are honored across restarts.
- `git_watch.<name>.last_seen_sha` survives daemon restart — `git` routines do not re-dispatch already-handled commits after a reboot.
- `daemon_halted` survives daemon restart — a halted daemon stays halted across reboots until the operator runs `/lazy-runtime.recover`.

---

## 10. Working-tree protection

After every routine tick, the daemon runs `git status --porcelain` in the repo. Non-empty output writes a top-level `daemon_halted` block to state.json with `triggered_by`, `reason`, and `dirty_paths`, then stops scheduling routines until the operator runs `/lazy-runtime.recover`.

Why daemon-wide rather than per-routine: the daemon's pre-iteration `git checkout -B <branch>` (when `daemon.git` is set) silently nukes any dirty work. If a single routine left dirt, even routines that operate purely in gitignored paths would read inconsistent tree state in the next iteration. Halting everything is the safe default.

Per-job attribution: when an expert (inside `expert-pump`) is the cause, the halt block also records `expert` + `job_id`. The job's `response.json` is overridden with `outcome: "error", error.category: "uncommitted_changes"` and `DONE` is touched.

Recovery: `/lazy-runtime.recover` walks the operator through commit / stash / discard / abort, then atomically clears the halt block once the tree is clean. See `claude/lazycortex-core/skills/lazy-runtime.recover/SKILL.md`.

The check is read-only on the daemon side — the daemon never cleans the tree itself. The operator authors every commit in the recovery path.

---

## 11. Expert runtime contract

Every expert run receives `claude/lazycortex-core/templates/expert-runtime-contract.md` via `claude -p --append-system-prompt-file ...`. The contract is loaded as a system-prompt-level rule on top of the expert's per-protocol contract.

Contract sections:
- **Working tree** — every change must be committed before exit. No push, no branch switching.
- **Input** — `request.json` schema (required `role`, plus protocol-specific fields).
- **Output** — `response.json` schema (`outcome`, `result`, `error`).
- **What you must not touch** — `DONE`, other experts' job dirs, state.json, branches.

---

## 12. Metrics

The daemon can serve a Prometheus-format `/metrics` HTTP endpoint covering routine throughput, error rates, tick durations, queue depth, halt status, and Anthropic API token usage. Off by default — opt in by adding a `metrics` block to `lazy-core.runtime`.

### Settings

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. When false the metrics module is dormant — `import metrics` is free, no HTTP server runs. |
| `bind` | string | `"127.0.0.1"` | Listening address. **Default is loopback** — never expose off-host without an explicit operator decision. |
| `port` | int | `9464` | TCP port. `0` lets the OS pick (used in tests). |
| `repo_label` | string or null | `null` | Override for the `repo` label. Default derives a 12-char SHA1 prefix of `git remote get-url origin`, or `local-<basename>` if no origin. |
| `daemon_name` | string or null | `null` | Override for the `daemon_name` label. Default constant `"lazycortex-runtime"`. **The daemon never reads `os.uname()`** — operator hostname must not leak into the metric stream. |

### Example

```json
{
  "lazy-core.runtime": {
    "metrics": {
      "enabled": true,
      "bind": "127.0.0.1",
      "port": 9464
    }
  }
}
```

Restart the daemon to flip enablement on or off. Settings are reloaded inside the loop for routine hot-reload, but `metrics.init()` runs once at startup.

### Metric shape

Closed label vocabulary — values come from a fixed enum, never from raw exception text, file paths, branch names, commit shas, hostnames, or any user-supplied string. The `repo` label disambiguates daemon instances; the constant `daemon_name` keeps operator identity out.

```
# Counters
lazycortex_runtime_routine_ticks_total{routine,repo,status}
lazycortex_runtime_routine_errors_total{routine,repo,reason}
lazycortex_runtime_tokens_total{routine,repo,model,kind}
lazycortex_runtime_daemon_halts_total{repo,reason,triggered_by}

# Histograms
lazycortex_runtime_routine_tick_duration_seconds{routine,repo}

# Gauges
lazycortex_runtime_routine_last_tick_timestamp{routine,repo}
lazycortex_runtime_queue_depth{expert,repo,state}
lazycortex_runtime_daemon_halted{repo,reason,triggered_by}
lazycortex_runtime_up
lazycortex_runtime_build_info{version,daemon_name,repo}
```

`status` ∈ `{ok, error, timeout, crash}`; `reason` ∈ `{timeout, resolve, subprocess_error, unexpected, git_pre_failed, git_post_failed, uncommitted_changes}`; `state` ∈ `{ready, running, done}`; `kind` ∈ `{input, output, cache_read, cache_write}`.

### Shipping to a Prometheus + Grafana stack

The endpoint is local-only by default. To ship metrics to a self-hosted observer, install the public `lazycortex-observe` plugin — it ships generic Grafana Alloy / OpenTelemetry Collector templates, launchd / systemd service units, a Grafana dashboard JSON, and Prometheus alert rules. The plugin is observer-server-blind: no hostnames, tokens, or operator-private identifiers in any shipped file. Operator-private values live in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and the `LAZYCORTEX_OBSERVE_TOKEN` env var.

Versioned independently of `lazycortex-core` via the file's `version:` frontmatter. Bump the contract's version when the schema changes; experts re-read it on next dispatch (no daemon restart needed).
