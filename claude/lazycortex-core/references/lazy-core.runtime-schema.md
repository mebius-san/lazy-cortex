---
description: Architecture reference for the per-repo runtime daemon — lifecycle, routine registration, plugin-cache resolution, and the flat `daemon` / `routines` sections of `lazy.settings.json`.
---
# lazy-core.runtime

Architecture reference for the per-repo runtime daemon. Audience: plugin authors who need to register routines or understand how the daemon behaves at runtime.

---

## 1. Daemon lifecycle

One runtime daemon process runs per repo. It runs as a supervised service; the supervisor (launchd on macOS, systemd on Linux) restarts it if it crashes. The daemon itself is single-threaded and runs routines serially — no two routines execute concurrently.

On every iteration the daemon re-reads `.claude/lazy.settings.json` (the flat top-level `daemon` and `routines` sections). Config changes take effect on the next iteration without a restart.

The daemon's main cycle:

1. Re-read the `daemon` and `routines` sections from settings.
2. Execute pre-iteration git ops (if `daemon.git` is set).
3. Run all due routines in ascending `priority` order (missing `priority` counts as `100`); routines sharing a priority keep registry insertion order.
4. Execute post-iteration git ops (if `daemon.git` is set).
5. Sleep until the earliest next-due routine (capped at `polling_interval_sec`).

---

## 2. `daemon` block fields

The `daemon` key is optional. When absent, no git ops are performed and `polling_interval_sec` defaults to 5 seconds.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Whether this checkout may run a **supervised** daemon. Seeded `false` by `/lazy-core.install`, whose Step 13 reads it as the one gate on installing the launchd / systemd unit (Gate 1, before the `run_here` pairing of `lazy-core.state-schema.md` § 15); flipping it is a deliberate edit followed by a re-run of install, never an install-time prompt. The daemon process itself never reads the flag — every routine still runs by hand through `/lazy-runtime.tick` on a checkout where it stays `false`. Its other reader is the inbox-collision guard (`inbox_guard.daemon_inbox_findings`), which treats a disabled checkout as contesting no shared inbox. |
| `git` | `null` or object | `null` | Git integration block. `null` means no git ops. |
| `rate_limit_guard` | object | every trigger on | Subscription-rate-limit guard, gating spawns against the host-local flag. See `daemon.rate_limit_guard` sub-fields below. |
| `polling_interval_sec` | int | `5` | Maximum sleep between runtime iterations. |
| `cleanup_completed_after` | duration string | `"7d"` | Age after which a completed job dir is deleted. |
| `cleanup_failed_after` | duration string | `"30d"` | Age after which a failed job dir is deleted. |
| `cleanup_dead_after` | duration string | `"7d"` | Age after which a DEAD-marked stuck job dir is deleted. DEAD jobs are marked by `expert_pump._detect_dead_jobs` when their PID file references a dead process; the forensic window before cleanup matches `cleanup_completed_after` by default. |
| `stream_idle_timeout_sec` | int | `900` | Seconds of stdout silence from a `claude -p` expert spawn before it is treated as a frozen stream, its process group killed, and the spawn re-tried. Sized for opus-tier experts, which legitimately stay silent for minutes while thinking. |
| `stream_max_retries` | int | `3` | Maximum number of in-memory re-spawns on stream-idle-stall before the job is left with a transient error for the next tick. Separate from the on-disk `attempts` counter. |
| `transient_max_retries` | int | `5` | Transient-error budget per expert job bundle. Each transient failure (non-zero spawn exit, missing `response.json`, a routine-timeout SIGTERM) increments the bundle's own on-disk counter and leaves the job in `READY+ERROR` for the next pump tick to retry; once the counter reaches this budget the pump closes the bundle as failed instead of releasing it again. Separate from `stream_max_retries`, which caps in-memory re-spawns inside a single tick. A missing or unreadable counter file restarts the budget from zero — the cap exists to stop retry storms, not to lose work. |
| `token_env` | string | — (required) | Name of the environment variable holding this daemon's OAuth token, resolved at startup from the environment first, then from `~/.claude/.env`, and exported as `CLAUDE_CODE_OAUTH_TOKEN` to every spawn. The daemon refuses to start without it — running on the machine's ambient login is unpredictable and burns a usage window nobody chose. The secret itself never lands in settings; only the variable's name does. |
| `cleanup_runtime_log_after` | duration string | `"30d"` | Age after which a dated `<YYYY-MM-DD>.jsonl` journal is deleted. The hourly sweep walks all of `.logs/`, so a journal written by any plugin (`.logs/lazy-review/runs/…`, and whatever a future plugin adds) is retained on the same window without registering itself. Journals with no date in the name — `tokens.jsonl`, `jobs.jsonl`, `commits.jsonl` — are append-only ledgers whose age says nothing about which lines are still wanted; operators rotate those. |
| `loop_detect_threshold` | int | `5` | How many commits carrying the same (bot author email, patch-id) signature must fall inside the detection window before the post-iteration loop check halts the daemon with `reason: suspected_loop` (`lazy-core.state-schema.md` § 9) — i.e. how many times a bot may re-commit the identical diff. Bot identities come from `experts.<name>.git_author.email` and `routines.<name>.git_author.email`, so operator commits never trip it. Any value below `2` disables the rule outright. |
| `loop_detect_window` | int | `threshold * 4` | Number of recent commits to inspect for the per-(author, patch-id) loop-detection heuristic. Must be ≥ `loop_detect_threshold`. Larger values give better accuracy at the cost of a slightly slower `git log` query. |

Duration strings: a number followed by a unit suffix — `s`, `m`, `h`, or `d` (e.g. `"30d"`, `"12h"`, `"300s"`).

### `daemon.errors` sub-fields

The `errors` key (nested under the flat `daemon` section) is optional and tunes the error-ledger retention. It is the only setting the error registry has — display and delivery of errors live in consumer plugins (observe / Grafana), not here.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `retention_days` | int | `30` | The daemon prunes error-journal events (`.runtime/errors.jsonl`) older than this window on its hourly maintenance pass. The latest event of a still-open / needs-operator incident is always retained regardless of age, so a live incident never vanishes. |

### `daemon.rate_limit_guard` sub-fields

The `rate_limit_guard` key is optional and tunes the subscription-rate-limit guard. Every field defaults to the protective value, so a section predating the guard — or one no migration has reached — protects the subscription rather than exposing it (`rate_limit_flag.config`).

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `true` | Master switch. `false` and the pump neither defers a spawn on a raised flag nor halts after one, and `/lazy-runtime.preflight` stops skipping its live probe — frames are still parsed and recorded, so the flag keeps being written for other readers on the host. |
| `on_allowed_warning` | bool | `true` | Whether a provider `allowed_warning` frame can raise the flag — and only then at or above `warning_utilization_threshold`. |
| `on_rejected` | bool | `true` | Whether a provider `rejected` frame (the window is already closed) raises the flag. |
| `on_overage` | bool | `true` | Whether a frame reporting spend has crossed into paid overage raises the flag. |
| `warning_utilization_threshold` | float | `0.9` | Share of the window at or above which an `allowed_warning` frame counts as a stop signal. The provider marks frames as warnings long before exhaustion; a warning below this reading — or one carrying no reading at all — never trips the guard. |

The flag itself lives outside any repository, at `${XDG_CACHE_HOME:-$HOME/.cache}/lazycortex/rate-limit/`, one record per (window, account): every daemon and wrapper on the host observes the same closed windows, and a record expires on its own once the window reopens. The guard is consulted three times — before the pump picks a job (a raised flag defers the tick rather than burning the call), after a job's run (a flag raised during it halts the daemon with `reason: rate_limit`, `lazy-core.state-schema.md` § 9), and before `/lazy-runtime.preflight`'s live probe spawn.

### `daemon.git` sub-fields

| Field | Type | Description |
|---|---|---|
| `base_branch` | string | **Required.** The operator's base branch the daemon checks out and rides each iteration — no longer reset. Operator commits arrive via the pre-iteration fast-forward pull; routine output lands on this branch directly. |
| `remote_sync` | `"pull"` / `"pull_push"` | Optional. `"pull"` does pre-iteration fetch+ff-pull. `"pull_push"` additionally does fetch+rebase+push after routines run. Absent = no remote sync. |
| `worktree_root` | string | Optional. Repo-relative directory that holds per-job worktrees for `workspace: branch` jobs (see § 13). Default `".worktrees"`. `WorktreeTaskManager.create()` drops its own self-ignoring `.gitignore` into it the first time it materialises the directory, so in-tree worktrees stay untracked with no operator setup. |
| `worktree_bootstrap_cmd` | string | Optional. Shell command (`sh -c`) run inside every freshly created job worktree, after config provisioning and before the spawn, to rebuild the gitignored execution environment (venv and the like) a worktree does not materialise. Absent = no bootstrap. A non-zero exit fails the job (`transient`) before any spawn. Whatever new untracked paths the command produces are recorded automatically into the worktree's own `.gitignore` (the diff between the worktree's untracked-path set before and after the run) — the operator never gitignores bootstrap artifacts by hand. This covers only what the command itself creates: an artefact that appears later, during the spawn, still has to be ignored by the repository's own `.gitignore` / `.lazyignore` or it fails the post-job dirty-tree check like any other uncommitted change. `settings.local.json` / `lazy.settings.local.json` are already gitignored by install and are unaffected. |
| `post_push_hook` | string | Optional. Shell command run via `sh -c` (cwd = repo root) after each post-iteration push that actually advances `origin/<base_branch>`. Absent or empty = disabled. Fully isolated: non-zero exit, timeout, or spawn failure is journaled and never affects the tick. |
| `post_push_timeout_sec` | int | Optional. Wall-clock cap on the post-push hook process. Default `30`. On expiry the hook is killed and the timeout journaled. |
| `allowed_hooks` | list | Optional. Operator git-hook filenames (`pre-commit`, `commit-msg`, …) allowed to run under the daemon. At startup the daemon rebuilds `<git-common-dir>/lazy-hooks/` with a symlink per vetted name and points `core.hooksPath` at it through the environment, so a hook absent from the list never fires on a routine's commit. Absent or empty = no operator git hook runs under the daemon; the operator's own sessions are untouched. |

`base_branch` and `remote_sync` are seeded by `lazy-core.install` from the checkout itself — the current branch, and `"pull_push"` when an `origin` remote exists. The block is written only when absent or `null`, so a hand-tuned one survives re-installs; `post_push_hook` is never seeded. A repo whose `git` block stays `null` is a `lazy-core.audit` D3 finding — the block is what routine commits ride, under a daemon or under a manual tick alike.

**Pre-iteration ops** (when `daemon.git.remote_sync` is `"pull"` or `"pull_push"`):

1. `git checkout <base_branch>` (plain checkout — NOT `-B`; the base branch is never reset to HEAD).
2. `git fetch origin <base_branch>`.
3. Compare `HEAD` against `origin/<base_branch>` via `merge-base`:
   - **In sync** (HEAD == origin/base_branch) → no-op.
   - **Local-ahead** (origin is an ancestor of HEAD) → no-op; unpushed local commits will be pushed by the next post-iteration ops.
   - **Remote-ahead** (HEAD is an ancestor of origin) → `git pull --ff-only origin <base_branch>` (absorbs operator commits).
   - **Diverged** (both sides have commits the other doesn't) → halt with `reason: git_pull_diverged`. Automatic resolution is unsafe (could drop the operator's commits); requires `/lazy-runtime.recover`.

**Post-iteration ops** (when `daemon.git.remote_sync` is `"pull_push"`):

The publish runs once at the end of the tick and, before that, immediately after every routine whose run moved `HEAD` — so a routine's commits are on origin before the next routine starts, and a later routine's conflict can discard only its own commits. A routine that left the tree dirty is not published: the dirty-tree halt (`lazy-core.state-schema.md` § 10) comes first.

A retry loop (max 3 attempts):

1. `git fetch origin <base_branch>`.
2. Compare HEAD vs `origin/<base_branch>`:
   - **Equal** → nothing to push; exit.
   - **Local-ahead** (origin is ancestor of HEAD) → fast-forward `git push origin <base_branch>`. On race (push refused because origin moved between our fetch and our push), retry.
   - **Diverged** → `git rebase origin/<base_branch>`. On conflict, `git rebase --abort && git reset --hard origin/<base_branch>` — the unpublished work is discarded and its side effects are wound back: every expert job consumed since the last publish loses its `CONSUMED` marker again (the unpushed-consume record, `lazy-core.state-schema.md` § 9) so the next collector lands it anew, and every `git_watch.<name>.last_seen_sha` no longer reachable from the new `HEAD` is rewound to the merge-base so the routine rescans from the last published commit. Exit cleanly (NO halt); a git-watch routine re-runs on its next tick, an interval routine at its next interval. On clean rebase, push; on race, retry.

**Post-push hook** (when `daemon.git.post_push_hook` is set): immediately after either successful push above (fast-forward or post-rebase), the daemon runs the configured command via `sh -c` with cwd = repo root and five env overrides: `LAZY_PUSH_REPO` (absolute repo path), `LAZY_PUSH_BRANCH` (the pushed branch), `LAZY_PUSH_REMOTE` (`origin`), `LAZY_PUSH_OLD_SHA` (the `origin/<branch>` tip before the push), `LAZY_PUSH_NEW_SHA` (local HEAD after the push — re-read after any rebase). The hook does NOT fire when nothing was pushed: in-sync ticks, the already-published fallthrough, and the rebase-conflict discard all skip it. Hook failures (non-zero exit, timeout past `post_push_timeout_sec`, spawn errors) land in the runtime journal as a `_post_push_hook` record and never halt, retry, or fail the tick.

After the third failed push attempt, halt with `reason: git_push_failed`.

Any other git failure during pre-iteration or post-iteration ops halts with `reason: git_remote_unavailable` when stderr names an unreachable remote (network unreachable, could-not-resolve-host, remote read failure), and with `reason: git_local_failed` otherwise — a purely local failure (a held `index.lock` past the retry backoff, a bad ref, permission on the checkout) never blames the remote. A transient `index.lock` race is retried in place before it can halt at all.

The daemon rides the operator's base branch directly rather than a perpetual daemon-exclusive branch: operator commits flow in every tick via the pre-tick fast-forward pull, and routine output lands on the base branch and is pushed by the post-tick ops. Operator pushes from a second machine coexist safely — they are absorbed by the pre-tick pull or the post-tick rebase. Because the pre-tick checkout is plain (never `-B`), it does not reset the branch and does not clobber operator history.

### Example `daemon` + `routines` sections

The daemon reads two flat top-level sections — `daemon` and `routines`. Each carries its own `_version`. There is no nested wrapper object; `lazy_settings.load_section` reads each section directly off the top-level JSON keys.

```json
{
  "daemon": {
    "_version": 4,
    "supervisor": {
      "dev_mode": false
    },
    "git": {
      "base_branch": "main",
      "remote_sync": "pull_push"
    },
    "polling_interval_sec": 5,
    "cleanup_completed_after": "7d",
    "cleanup_failed_after": "30d",
    "cleanup_dead_after": "7d",
    "stream_idle_timeout_sec": 900,
    "stream_max_retries": 3
  },
  "routines": {
    "_version": 7,
    "lazy-expert.pump": {
      "interval_sec": 5,
      "timeout_sec": 1800,
      "priority": 100,
      "command": ["lazycortex-core", "expert-pump-once"]
    },
    "lazy-runtime.doctor": {
      "interval_sec": 3600,
      "timeout_sec": 60,
      "priority": 30,
      "ignore_halt": true,
      "command": ["lazycortex-core", "doctor-tick"]
    },
    "my-plugin.nightly-sync": {
      "interval_sec": 3600,
      "command": ["my-plugin", "sync"],
      "timeout_sec": 120
    }
  }
}
```

### `daemon.supervisor` block fields

The `supervisor` key (nested under the flat `daemon` section) is optional and records install-time choices about how the supervisor unit (launchd plist / systemd service) was rendered. The daemon process itself does not read this block — it is consumed by `/lazy-core.install` Step 13 when (re-)rendering the unit.

| Field | Type | Default | Description |
|---|---|---|---|
| `dev_mode` | bool | `false` | When `true`, the rendered supervisor invokes `lazy.runtime.sh` with `--dev-mode`. The shim then scans `<repo-root>/claude/*/.claude-plugin/plugin.json` and injects one `--plugin-dir <plugin-root>` per match before the runner's positional repo-root. The runner consults those paths first and falls back to the plugin cache. Useful when this repo IS the authoring vault for the plugins the daemon needs — local source edits take effect without a `/plugin update` cycle. |
| `login_shell` | bool | `false` | When `true`, the rendered supervisor invokes `lazy.runtime.sh` with `--login-shell`. The shim re-execs itself through a login shell (`$SHELL -lc`, default `/bin/zsh`) so the daemon inherits the operator's login environment (`.zprofile` / `.zshrc` → `CLAUDE_CODE_OAUTH_TOKEN` + full PATH). See § Headless hosts below. |
| `env_files` | `[string]` | `[]` | A list of env-file paths. Each is rendered as a `--env-file <path>` flag on the shim invocation; the shim sources each (`set -a; . <path>; set +a`) so its exported vars reach the runner → daemon → `claude`. A leading `~` is expanded by the shim. Surgical alternative to `login_shell` when only a token file is needed, not a full login PATH. |

`LAZYCORTEX_PYTHON` — absolute interpreter derived by install step 13b and exported by the supervisor unit to the shim, which starts the runner through it. It lives nowhere but the unit file: an interactive session runs skills and hooks as `"${LAZYCORTEX_PYTHON:-python3}"` and resolves `python3` from its own `PATH`.

`dev_mode`, `login_shell`, and `env_files` are install-skill state, not runtime config — changing them in `lazy.settings.json` does NOT affect the running daemon. To apply a change, re-run `/lazy-core.install` so the supervisor unit is re-rendered, then reload the unit (`launchctl unload && launchctl load` on macOS, `systemctl --user daemon-reload && systemctl --user restart` on Linux).

### Headless hosts: giving the daemon a login environment

launchd and systemd `exec` the shim directly — not through a login shell — so the daemon does not run the operator's `.zprofile` / `.zshrc`. On an interactive box this is invisible (the operator's own shell already exported everything), but on a headless host the daemon spawns `claude -p` with no `CLAUDE_CODE_OAUTH_TOKEN` (→ "Not logged in") and an incomplete PATH (→ `claude` may not resolve). The environment the shim sets up flows all the way down: shim → runner → daemon → `expert-pump` `claude` spawn and routine commands all inherit it.

Two opt-in remedies, both off by default (absent → byte-identical to the historical behaviour):

- `supervisor.login_shell: true` — full login-equivalent environment (token **and** PATH), host-agnostic, no personal paths in plugin code. This is the minimally-sufficient fix for both symptoms.
- `supervisor.env_files: ["~/.claude/.env"]` — sources just the named file(s); fixes the token without a full login PATH. Combine with `login_shell` when both a custom env file and a login PATH are wanted.

Edge: under launchd `$SHELL` is often unset, so the shim falls back to `/bin/zsh` (present on macOS); the chosen login shell must exist and read the dotfiles that export the token.

---

## 3. `routines` block fields

Each key under `routines` is the routine name (dot-namespaced, e.g. `lazy-expert.pump`). The value is:

| Field | Type | Required | Description |
|---|---|---|---|
| `interval_sec` | int | yes (interval types) | How often to run this routine (in seconds). Required for `subprocess`, `inbox`, `git`, `md-scan`; `schedule` uses `cron` instead (see `lazy-core.routine-types-schema.md`). |
| `command` | array of strings | one of `command` / `expert`+`request` | `[<plugin-name>, <args>...]`. First element is resolved via plugin cache (see § 4). A routine sets EITHER `command` OR `expert` + `request`, never both, never neither. |
| `expert` | string | one of `command` / `expert`+`request` | Expert name. When set, `request` is also required. The mutually-exclusive alternative to `command`. |
| `request` | string \| object | with `expert` | Request template dispatched to `expert`. Required whenever `expert` is set; ignored when `command` is used. |
| `timeout_sec` | int | no | Per-run timeout. Default: 300 seconds. |

A routine is considered due when `now - last_run >= interval_sec`. If the daemon was down, overdue routines run on the first iteration after restart — there is no skip-if-late logic.

The `command` / `expert`+`request` choice is the EITHER/OR dispatch contract enforced uniformly across every routine type by `validate_routine_entry` — see `lazy-core.routine-types-schema.md` for the per-type required/optional field split.

---

## 4. Plugin-cache resolution

The first element of `command` is a plugin name. The daemon resolves it at runtime to:

```
~/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>
```

Resolution steps:

1. Glob `~/.claude/plugins/cache/*/<plugin>` to find all registry/plugin dirs.
2. Collect all version subdirectories across those dirs.
3. Sort version directory names numerically and take the highest (latest). The key is built component-wise: the name is split on `.`, each component contributes the integer formed by its leading digits, and a component carrying no digits contributes `0`. String comparison is never used — it ranks `9.1.1` above `10.0.0` and would pick the wrong directory.
4. Assert `<version>/bin/<plugin>` exists and is executable.

**Always-latest semantics**: no pin syntax. The daemon always runs the latest cached version of the plugin. If two registries both carry a plugin by the same name, all versions from both are pooled and the globally-latest wins.

---

## 5. Retry policy boundary

**The runtime daemon does not retry plain routine commands.** If a routine exits non-zero, the daemon logs the result and moves on. No automatic backoff or re-schedule.

`expert-pump-once` processes AT MOST ONE Claude spawn per invocation; transient Claude failures (non-zero exit, missing `response.json`, daemon-issued SIGTERM via routine timeout) leave the job in `READY+ERROR` state, and the next pump tick retries it from scratch. There is no in-loop retry inside pump — retry granularity is one Claude attempt per pump tick (= every `interval_sec` seconds, default 5s).

Plugin authors writing their own routine commands are responsible for their own retry and backoff logic.

**Working-tree protection (`lazy-core.state-schema.md` § 10) is a separate invariant from retry.** A routine that leaves the working tree dirty is halted permanently — no retry, no backoff, no re-schedule. The operator must run `/lazy-runtime.recover` before any routine fires again.

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

A tick that did nothing is not journaled. Every routine runs every few seconds, so recording quiet ticks would add thousands of identical lines a day and bury the ones that matter. A tick is quiet when it exited zero, reported no error, ran under 1.5 s, and reported no dispatched work — whether that count arrives as a `dispatched_count` result field or inside the stdout tail. Metrics still count the tick, so rates and latencies stay complete.

**Supervisor captures.** On macOS the launch agent redirects the daemon's stdout and stderr to `.logs/lazy-core/runtime/launchd.out.log` and `launchd.err.log`. Neither carries a date, both are held open for the life of the daemon, and nothing else writes them, so the hourly sweep trims a capture in place once it passes 1 MB, keeping the last 256 KB from the first whole line onward. Deleting them instead would leave the supervisor writing to an unlinked inode while the visible file stayed empty. On Linux the unit has no file redirect — stdout and stderr go to the systemd journal, which journald rotates.

---

## 7. Public API

**Adding a routine from Python:**

```python
from expert_runtime import register_routine
# Legacy subprocess shape (still supported)
register_routine(repo, "my-plugin.task", ["my-plugin", "run-task"], interval_sec=5)
# Typed cfg shape (required for inbox / schedule / git — see lazy-core.routine-types-schema.md)
register_routine(repo, "docs.inbox", {
    "type": "inbox",
    "inbox_dir": ".inbox/docs/",
    "expert": "doc-ingester",
    "request": {"role": "process", "file": "{file}"},
    "interval_sec": 5,
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

### Personal-overlay file (`lazy.settings.local.json`)

`lazy_settings.py` reads a two-file stack, mirroring Claude Code's own `settings.json` / `settings.local.json` semantics:

| File | In git | Owns |
|---|---|---|
| `.claude/lazy.settings.json` | tracked | shared, team-visible config — `routines`, `experts`, `daemon`, `agent_models`, etc. |
| `.claude/lazy.settings.local.json` | gitignored | per-machine / personal overrides applied on top of the tracked file |

**Read semantics** — `lazy_settings.load_section(path, key)` returns the merged view: tracked content with the sibling `.local.json` overlay deep-merged on top, per Claude Code's rules.

| Value shape | Merge behaviour |
|---|---|
| scalar (`interval_sec`, `git_author`) | local replaces tracked |
| array (`aspects[]`, `additionalDirectories[]`) | union with dedupe — tracked order first, novel local entries appended |
| object (`experts`, `routines`, nested dicts) | recursive deep merge with the rules above |

`_version` is sticky to tracked — migration ladders never run against the local file, and any `_version` field in the overlay is ignored.

**Write semantics** — `save_section(...)` writes **only** to the tracked file. The local overlay is never touched programmatically; the operator edits it by hand. Callers that perform a load → modify → save round-trip on a single layer (e.g. `register_routine`, `unregister_routine`) call `load_tracked_section(...)` instead of `load_section(...)` to avoid leaking overlay entries into the shared tracked file.

**Read-only inspection** — `load_local_only_section(path, key)` returns just the overlay's view of one section (or `{}` when the file is absent). Used by diagnostics and audits.

**Gitignore** — `bootstrap_lazy_settings_local_gitignore` (invoked by `/lazy-core.install` Step 7) ensures `.claude/lazy.settings.local.json` is listed in the consumer's `.gitignore`. No directory is created — the file is opt-in.

---

## 8. Routine types

**Extracted — see `lazy-core.routine-types-schema.md`.** The five `type` values (`subprocess`, `inbox`, `schedule`, `git`, `md-scan`), their required and optional fields, the common keys every type accepts (`priority`, `protocol` / `protocols`, `ignore_halt`, `hooks_enabled`, `git_author`, `can_commit_in_repo`), the per-type dispatch sub-shapes, and the composite `filter` block all live in that sibling. Read it when registering, validating, or debugging a `routines[<name>]` entry; the rest of this file needs none of it.

---

## 9. State persistence

**Extracted — see `lazy-core.state-schema.md`.** The `<repo>/.runtime/state.json` schema (`last_run`, `git_watch`, `daemon_halted`), the ten halt reasons with their recovery paths, the unpushed-consume record, and what survives a daemon restart all live in that sibling, next to the halt invariants of § 10 that write them. Read it when a daemon is halted, or when reasoning about state that outlives a restart.

---

## 10. Working-tree protection and halt invariants

**Extracted — see `lazy-core.state-schema.md`.** Which conditions halt the daemon, the per-job attribution of a dirty-tree halt, why a post-tick rebase conflict is a discard rather than a halt, and the single recovery entry point live in that sibling, beside the § 9 schema they write into. Read it when judging whether a routine may leave the working tree dirty.

---

## 11. Expert runtime contract

**Extracted — see `lazy-core.expert-runtime-schema.md`.** How the runtime configures one expert spawn — commit rights, hermetic MCP servers, settings sources and lazycortex hooks, `workspace: branch` and its linked worktree, the filesystem sandbox, and foreign providers — lives in that sibling. Read it when wiring an `experts[<name>]` entry. It is not `lazy-core.expert-runtime-contract.md`, which is the prompt text the expert agent itself receives at spawn.

---

## 12. Metrics

**Extracted — see `lazy-core.metrics-schema.md`.** The `daemon.metrics` settings block, multi-daemon port allocation on one host, the closed metric and label vocabulary, and how to ship the endpoint to a Prometheus + Grafana stack live in that sibling. Read it when turning metrics on, or when reading a metric name off a dashboard.

---

## 13. Job worktrees

Isolated expert jobs (`workspace: branch` — see `lazy-core.expert-runtime-schema.md` § Workspace) run inside linked git worktrees under `<repo>/<worktree_root>/job-<job_id>/`, owned by `WorktreeTaskManager` in `bin/worktree_tasks.py` and driven synchronously by the pump inside one `_process_one` run. The manager never merges, never opens pull requests, and keeps no registry — reintegration is the coordinating dispatcher's business, and a worktree lives exactly as long as the pump run over its job.

The retired routine-side path (`isolate: true` routines, `allow_merge`, `max_concurrent_tasks`, the `worktree_tasks` registry in `state.json`) is gone: those settings keys are ignored with a stderr warning when present, and `lazy-core.doctor` / `lazy-core.autocheckup` offer the prune.

### Sweep

On the same hourly cadence as runtime-log cleanup, `mgr.sweep()` runs `git worktree prune` and force-removes every directory under `worktree_root` — each one is an orphan left by a crashed pump run, since a live worktree exists only inside one synchronous run of the serial main loop.

---

## 14. Daemon self-restart on own code change

The daemon watches its own loaded `.py` source and restarts at an iteration boundary when that source changes — so a `/plugin update` (or a dev-vault source edit under `--dev-mode`) takes effect without a manual restart. Owned by `CodeFingerprint` in `bin/code_fingerprint.py`.

- At `run()` startup the daemon snapshots the hashes of every loaded module whose file lives under a watched plugin root. Watched roots are the `--plugin-dir` source trees in `LAZYCORTEX_PLUGIN_DIRS` (cached versions in that list are skipped — they never change in place, and a `/plugin update` lands a new version directory that the newer-runner check picks up) plus the running module's own parent directory.
- After each iteration (and only when the daemon is not halted), the fingerprint is re-checked. A change is acted on **only once it is stable across two consecutive observations**, so an in-flight half-written update never triggers a premature restart.
- On a stable change the daemon logs `restart: own code changed` and restarts:
  - Under a supervisor (`LAZYCORTEX_SUPERVISED=1`, exported by the launchd plist / systemd unit) → clean `SystemExit(0)`; the supervisor relaunches the process with fresh code. The systemd unit uses `Restart=always` (not `on-failure`) so the clean exit-0 still relaunches; launchd's `KeepAlive` relaunches on any exit.
  - Unsupervised → `os.execv` replaces the process image with a fresh interpreter.
- The restart happens at the iteration boundary, after any commit has landed and outside the halt path (except the self-lifting `rate_limit` halt, where restarting is allowed), so it never interrupts mid-commit work or masks a halt the operator still needs to recover from. A worktree left by an interrupted job (§ 13) is collected by the next hourly sweep.

---

## 15. `external_dirs` — externally-sourced working directories

**Extracted — see `lazy-core.state-schema.md`.** The two-layer `external_dirs` declaration, the per-path status and ignore verdicts, the inbox-collision halt, and the `daemon.run_here` gate live in that sibling. Read it when a checkout's working directories are symlinked in from outside the repository, or when deciding which machine drives a project's daemon.
