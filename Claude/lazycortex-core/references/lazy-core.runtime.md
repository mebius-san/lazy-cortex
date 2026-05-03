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
register_routine(repo, "my-plugin.task", ["my-plugin", "run-task"], interval_sec=300)
```

Or via the `lazy-routine.register` skill (interactive wizard, writes to `.claude/lazy.settings.json`).

**Removing a routine:**

```python
from expert_runtime import unregister_routine
unregister_routine(repo, "my-plugin.task")
```

Or via the `lazy-routine.unregister` skill.

Both helpers are idempotent and use the atomic write path in `lazy_settings.py`.
