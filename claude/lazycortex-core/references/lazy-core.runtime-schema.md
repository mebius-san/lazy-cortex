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
| `cleanup_dead_after` | duration string | `"7d"` | Age after which a DEAD-marked stuck job dir is deleted. DEAD jobs are marked by `expert_pump._detect_dead_jobs` when their PID file references a dead process; the forensic window before cleanup matches `cleanup_completed_after` by default. |
| `cleanup_runtime_log_after` | duration string | `"30d"` | Age after which a per-day `.logs/lazy-core/runtime/<date>.jsonl` file is deleted. `tokens.jsonl` is append-only and not subject to this retention — operators rotate it manually. |
| `loop_detect_window` | int | `threshold * 4` | Number of recent commits to inspect for the per-(author, file) loop-detection heuristic. Must be ≥ `loop_detect_threshold`. Larger values give better accuracy at the cost of a slightly slower `git log` query. |

Duration strings: a number followed by a unit suffix — `s`, `m`, `h`, or `d` (e.g. `"30d"`, `"12h"`, `"300s"`).

### `daemon.errors` sub-fields

The `errors` key (nested under the flat `daemon` section) is optional and tunes the error-ledger retention. It is the only setting the error registry has — display and delivery of errors live in consumer plugins (observe / Grafana), not here.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `retention_days` | int | `30` | The daemon prunes error-journal events (`.runtime/errors.jsonl`) older than this window on its hourly maintenance pass. The latest event of a still-open / needs-operator incident is always retained regardless of age, so a live incident never vanishes. |

### `daemon.git` sub-fields

| Field | Type | Description |
|---|---|---|
| `base_branch` | string | **Required.** The operator's base branch the daemon checks out and rides each iteration — no longer reset. Operator commits arrive via the pre-iteration fast-forward pull; routine output lands on this branch directly. |
| `remote_sync` | `"pull"` / `"pull_push"` | Optional. `"pull"` does pre-iteration fetch+ff-pull. `"pull_push"` additionally does fetch+rebase+push after routines run. Absent = no remote sync. |
| `worktree_root` | string | Optional. Repo-relative directory that holds per-task worktrees for `isolate: true` routines (see § 13). Default `".worktrees"`. Listed in `.gitignore` so in-tree worktrees stay untracked. |
| `max_concurrent_tasks` | int | Optional. Maximum number of live worktree tasks allowed at once (see § 13). Default `3`. When the cap is reached, an `isolate: true` routine is left due and retried on a later tick rather than erroring. |

**Pre-iteration ops** (when `daemon.git.remote_sync` is `"pull"` or `"pull_push"`):

1. `git checkout <base_branch>` (plain checkout — NOT `-B`; the base branch is never reset to HEAD).
2. `git fetch origin <base_branch>`.
3. Compare `HEAD` against `origin/<base_branch>` via `merge-base`:
   - **In sync** (HEAD == origin/base_branch) → no-op.
   - **Local-ahead** (origin is an ancestor of HEAD) → no-op; unpushed local commits will be pushed by the next post-iteration ops.
   - **Remote-ahead** (HEAD is an ancestor of origin) → `git pull --ff-only origin <base_branch>` (absorbs operator commits).
   - **Diverged** (both sides have commits the other doesn't) → halt with `reason: git_pull_diverged`. Automatic resolution is unsafe (could drop the operator's commits); requires `/lazy-runtime.recover`.

**Post-iteration ops** (when `daemon.git.remote_sync` is `"pull_push"`):

A retry loop (max 3 attempts):

1. `git fetch origin <base_branch>`.
2. Compare HEAD vs `origin/<base_branch>`:
   - **Equal** → nothing to push; exit.
   - **Local-ahead** (origin is ancestor of HEAD) → fast-forward `git push origin <base_branch>`. On race (push refused because origin moved between our fetch and our push), retry.
   - **Diverged** → `git rebase origin/<base_branch>`. On conflict, `git rebase --abort && git reset --hard origin/<base_branch>` (this tick's work is discarded; the next tick re-runs the routine on top of the operator's commits) and exit cleanly (NO halt). On clean rebase, push; on race, retry.

After the third failed push attempt, halt with `reason: git_push_failed`.

Any other git failure during pre-iteration or post-iteration ops (network unreachable, missing remote tracking, permission denied, force-protection rejection) halts with `reason: git_remote_unavailable`.

The daemon rides the operator's base branch directly rather than a perpetual daemon-exclusive branch: operator commits flow in every tick via the pre-tick fast-forward pull, and routine output lands on the base branch and is pushed by the post-tick ops. Operator pushes from a second machine coexist safely — they are absorbed by the pre-tick pull or the post-tick rebase. Because the pre-tick checkout is plain (never `-B`), it does not reset the branch and does not clobber operator history.

### Example `daemon` + `routines` sections

The daemon reads two flat top-level sections — `daemon` and `routines`. Each carries its own `_version`. There is no nested wrapper object; `lazy_settings.load_section` reads each section directly off the top-level JSON keys.

```json
{
  "daemon": {
    "_version": 2,
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
    "cleanup_dead_after": "7d"
  },
  "routines": {
    "_version": 2,
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
| `interval_sec` | int | yes (interval types) | How often to run this routine (in seconds). Required for `subprocess`, `inbox`, `git`, `md-scan`; `schedule` uses `cron` instead (see § 8). |
| `command` | array of strings | one of `command` / `expert`+`request` | `[<plugin-name>, <args>...]`. First element is resolved via plugin cache (see § 4). A routine sets EITHER `command` OR `expert` + `request`, never both, never neither. |
| `expert` | string | one of `command` / `expert`+`request` | Expert name (optionally `expert@<repo>` for cross-repo dispatch). When set, `request` is also required. The mutually-exclusive alternative to `command`. |
| `request` | string \| object | with `expert` | Request template dispatched to `expert`. Required whenever `expert` is set; ignored when `command` is used. |
| `timeout_sec` | int | no | Per-run timeout. Default: 300 seconds. |

A routine is considered due when `now - last_run >= interval_sec`. If the daemon was down, overdue routines run on the first iteration after restart — there is no skip-if-late logic.

The `command` / `expert`+`request` choice is the EITHER/OR dispatch contract enforced uniformly across every routine type by `validate_routine_entry` — see § 8 for the per-type required/optional field split.

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

`expert-pump-once` processes AT MOST ONE Claude spawn per invocation; transient Claude failures (non-zero exit, missing `response.json`, daemon-issued SIGTERM via routine timeout) leave the job in `READY+ERROR` state, and the next pump tick retries it from scratch. There is no in-loop retry inside pump — retry granularity is one Claude attempt per pump tick (= every `interval_sec` seconds, default 5s).

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
register_routine(repo, "my-plugin.task", ["my-plugin", "run-task"], interval_sec=5)
# Typed cfg shape (required for inbox / schedule / git — see § 8)
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

Each entry under `routines` may carry an optional `type` field. Default is `subprocess`. Allowed values + per-type shape:

| Type | Required fields | Optional fields |
|---|---|---|
| `subprocess` (default) | `command`, `interval_sec` | `timeout_sec` |
| `inbox` | `inbox_dir`, `expert`, `request`, `interval_sec` | `timeout_sec` |
| `schedule` | `cron`, plus EITHER `command` OR `expert`+`request` | `timeout_sec` |
| `git` | `branch`, `watch`, `expert`, `request`, `interval_sec` | `repo_dir`, `remote`, `path_filter`, `timeout_sec` |
| `md-scan` | `paths`, `expert`, `interval_sec` | `filter`, `request`, `cadence`, `timeout_sec` |

Closed-set strict validation: unknown type, unknown field, missing required, or per-type custom constraint violation → `RoutineConfigError` at registration time.

**Common optional fields (any type):** `protocol: <ref>` or `protocols: [<ref>, ...]` — declares which protocol(s) the routine's dispatched jobs follow. The dispatcher resolves each ref via `reference_resolver.resolve(..., category="protocols", ...)` and threads the resolved paths through to each job's `config.json`. Protocols are routine-side, not expert-side — expert entries in `lazy.settings.json[experts]` do NOT carry a `protocol` field. See `lazy-core.expert-protocols-contract.md`.

**Worktree-isolation fields (any type):**

| Field | Type | Default | Description |
|---|---|---|---|
| `isolate` | bool | `false` | When `true`, the routine's unit of work runs on a dedicated `task-<id>` branch in an in-tree worktree instead of writing directly to the base branch (see § 13). When absent or `false`, the routine takes the unchanged direct-write dispatch path. |
| `allow_merge` | bool | `false` | Only meaningful with `isolate: true`. When `true`, a completed task is rebased onto base and fast-forward merged (degrading to a pull request on conflict). When `false`, completion always opens a pull request rather than merging. |

Both must be booleans when present — a non-boolean value raises `RoutineConfigError` at registration time.

### `inbox`

Scans `inbox_dir` each tick. The input file is never copied into the job bundle — only its **path** is passed, so the inbox is the single source of truth for the file (parity with `git` / `md-scan`, which also pass a path).

`command` sub-shape — spawn `command + [<absolute-path-to-file>]` per file (blocking, one at a time). The consumer command owns the file; the routine never removes it.

`expert + request` sub-shape — two passes per tick:

1. **Reconcile** finished work via `completed_dedup_jobs`: for every prior job keyed on an inbox path, if it **succeeded** (`outcome` ≠ `error`) drain the input (`unlink`, best-effort — the expert may have filed it away itself on success) and mark the bundle `CONSUMED`; if it **failed** leave the input parked — the bundle stays `DONE`-but-unconsumed so its dedup key keeps the file from re-dispatching. This is a **dead-letter**: the failed input sits in the inbox with its bundle's forensics retained for the operator to triage; it is not retried automatically (a crashed/`DEAD` job is the doctor's retry path, not this one).
2. **Dispatch** every remaining non-hidden, non-dir, non-symlink file: render `request` (substitute `{file}` with the file's **absolute path** in any string value) and dispatch one job keyed on that path (`dedup_key = <path>`), so an in-flight or parked file is never dispatched twice.

The expert reads the file at the given path in place. It may move or delete the input **only as its last action on success** — see `lazy-core.expert-runtime-contract.md` ("What you must not touch"). On any failure the original must stay put: it is the only copy left to reprocess.

### `schedule`

Fires when the cron expression has crossed a fire boundary since `last_run`. Skip-on-miss: multiple missed boundaries collapse to one fire (no catch-up).

Cron grammar: standard 5-field POSIX cron (`minute hour day month dow`). Supports `*`, `N`, `*/S`, `N-M`, `N-M/S`, comma lists. Day-of-week uses Sun=0..Sat=6. Day/dow uses AND when both restricted (deviation from POSIX OR — uncommon in real patterns). See `bin/cron.py`.

Sub-shapes:
- `command`: spawn subprocess (delegates to `dispatch_subprocess`).
- `expert + request`: dispatch one job to the expert; request template gets `{cron_fire_ts}` (ISO-8601) and `{cron_fire_unix}` (unix seconds) substituted.

### `git`

Watches local `HEAD` and dispatches one job per item per `watch`. Closed enum + per-watch templating variables:

| `watch` | Variables exposed in `request` template |
|---|---|
| `new_commits` | `{sha}`, `{short_sha}`, `{subject}`, `{author_name}`, `{author_email}`, `{commit_ts}` |
| `new_files` | `{path}`, `{status}`=A, `{sha}` |
| `changed_files` | `{path}`, `{status}` (A or M), `{sha}` |
| `deleted_files` | `{path}`, `{status}`=D, `{sha}` |
| `renamed_files` | `{old_path}`, `{new_path}`, `{sha}` |

`last_seen_sha` tracked in state.json's `git_watch.<name>` block. First run records the current local HEAD and dispatches nothing (no history backfill). Non-ancestor baseline-reset (e.g. after a rebase pull rewrites history) resets the baseline and dispatches nothing.

The `remote` config field is vestigial for the watch — remote sync is the daemon's job (`daemon.git.remote_sync` / `_git_pre`). It is accepted but ignored. By the time `dispatch_git` runs, `_git_pre` has already pulled remote commits into the local branch, so local HEAD reflects both local system commits and pulled-in remote commits — one watch covers both, and a remote-less repo works with no fetch.

The git type is working-tree-neutral by construction: only read-only `rev-parse`/`log`/`diff`. Cannot trigger the halt invariant on its own.

### Composite `filter` block (`inbox`, `git`, `md-scan`)

The optional `filter` key on `inbox`, `git`, and `md-scan` routines is a composite predicate block. Each declared sub-key must pass (AND semantics). An empty or absent block accepts every item.

**`filter.frontmatter`** — per-key `{ in, not_in }` predicates applied to the item's parsed YAML frontmatter. `in` (allow-list) and `not_in` (deny-list) both AND with each other and with other keys. `null` in either list matches a missing key or an explicit `null`. Non-markdown items and unreadable files parse to `{}` — a `null`-accepting predicate keeps them; a value-requiring predicate drops them. The legacy bare-list/scalar form is rejected.

**`filter.folder_note`** (tri-state) — constrains matches by folder-note status. A file `p` is a folder note iff `Path(p).stem == Path(p).parent.name` (e.g. `claude/lazycortex-core/lazycortex-core.md`). Obsidian plugin settings are never consulted; the convention is hardcoded.

| Value | Effect |
|---|---|
| `true` | Match only folder notes. |
| `false` | Exclude folder notes. |
| absent | No constraint — both pass. |

Items with no file path (e.g. `new_commits` git-watch items) are treated as non-folder-notes: `folder_note: true` excludes them, `folder_note: false` keeps them. Must be a boolean when present — a non-boolean value raises `RoutineConfigError`.

Example combining both sub-keys:

```json
{
  "filter": {
    "folder_note": true,
    "frontmatter": {
      "stage": { "in": ["draft"], "not_in": [] }
    }
  }
}
```

---

## 9. State persistence

The daemon persists scheduling and halt state at `<repo>/.runtime/state.json`. Atomic temp+rename writes; load returns an empty schema on absent or unparseable file (so a corrupt state file never crashes the daemon). The directory is bootstrapped alongside `.logs/` by `/lazy-core.install` Step 7 and is listed in `.gitignore`.

Schema:

```json
{
  "last_run": {
    "<routine_name>": <unix_ts>
  },
  "git_watch": {
    "<routine_name>": { "last_seen_sha": "<full_hex>" }
  },
  "worktree_tasks": {
    "<work_id>": {
      "branch": "task-<work_id>",
      "worktree_path": "<abs path under worktree_root>",
      "routine": "<routine_name>",
      "allow_merge": false,
      "job_id": "<job_id|null>",
      "started": <unix_ts>
    }
  },
  "daemon_halted": {
    "halted_since": <unix_ts>,
    "triggered_by": "<routine_name|_git_pre|_git_post|lazy-expert.pump>",
    "reason": "uncommitted_changes|git_pull_diverged|git_push_failed|git_remote_unavailable|suspected_loop",
    "dirty_paths": ["<git status --porcelain line>", ...],
    "expert": "<expert_name|null>",
    "job_id": "<job_id|null>"
  }
}
```

`daemon_halted` is absent when healthy. `git_watch` is absent when no `git`-type routines are registered. `worktree_tasks` is absent when no `isolate: true` routine has ever started a task; it persists across daemon restarts so an in-flight task is re-attached and polled after a relaunch (see § 13). `dirty_paths` is empty for git-related halt reasons (the tree is presumed clean at halt time; the halt cause is in the branch/remote state, not the working tree).

**Halt reasons (closed set):**

- `uncommitted_changes` — routine left the working tree dirty (see § 10). Recovery: dirt-cleanup wizard via `/lazy-runtime.recover`.
- `git_pull_diverged` — pre-tick fetch found that local and origin both have commits the other doesn't. Recovery: operator repairs branch state manually, then `/lazy-runtime.recover` clears the halt.
- `git_push_failed` — post-tick push retried `POST_TICK_MAX_PUSH_ATTEMPTS` (3) times and kept failing. Recovery: operator investigates push refusal (auth, branch protection, persistent race), then `/lazy-runtime.recover`.
- `git_remote_unavailable` — any other unexpected git failure during pre- or post-tick remote sync (network, permission, missing remote). Recovery: operator restores network/auth, then `/lazy-runtime.recover`.
- `suspected_loop` — loop-detection heuristic fired: one file was committed ≥ `loop_detect_threshold` times by the same registered-bot author within the `loop_detect_window` commit window. The halt block names the offending `(author, file)` pair. Recovery: operator investigates the routine's commit pattern and runs `/lazy-runtime.recover` once resolved.

Persistence consequences:
- `last_run` survives daemon restart and laptop sleep — slow routines (e.g. every 6h) are honored across restarts.
- `git_watch.<name>.last_seen_sha` survives daemon restart — `git` routines do not re-dispatch already-handled commits after a reboot.
- `daemon_halted` survives daemon restart — a halted daemon stays halted across reboots until the operator runs `/lazy-runtime.recover`.

---

## 10. Working-tree protection and halt invariants

The daemon halts (writes a top-level `daemon_halted` block to state.json and stops scheduling routines) on any of these conditions:

- **Dirty working tree after a routine** — `git status --porcelain` non-empty → `reason: uncommitted_changes`. Why daemon-wide rather than per-routine: the daemon rides the operator's base branch directly, so leftover dirt is operator/routine WIP that the next iteration's routines would read as inconsistent tree state (and commit over). If a single routine left dirt, even routines that operate purely in gitignored paths would see that inconsistent state in the next iteration. Halting everything is the safe default.
- **Pre-tick divergence** — local and origin branches both have commits the other doesn't → `reason: git_pull_diverged`. Automatic resolution would risk dropping the operator's commits, so the daemon halts and waits.
- **Post-tick push exhausted retries** — the rebase+push retry loop failed `POST_TICK_MAX_PUSH_ATTEMPTS` times → `reason: git_push_failed`. Indicates either persistent operator-side races (rare) or branch-protection / auth refusal.
- **Other pre- or post-tick git failure** — network, missing remote, permission, etc. → `reason: git_remote_unavailable`.

Per-job attribution: when an expert (inside `expert-pump`) is the cause of a dirty-tree halt, the halt block also records `expert` + `job_id`. The job's `response.json` is overridden with `outcome: "error", error.category: "uncommitted_changes"` and `DONE` is touched. Git-related halts carry no expert attribution (the daemon, not a routine, owns remote sync).

A pre-tick rebase conflict during post-tick remote sync is **not** a halt — the daemon discards the current tick's work (`rebase --abort && reset --hard origin/<base_branch>`) and logs `tick discarded: operator-conflict`. The next tick re-runs the routine on top of the operator's commits. Halting on a routine-conflict would block forever for any operator who edits the same files the routine touches.

Recovery for every halt path: `/lazy-runtime.recover`. For `uncommitted_changes` the skill walks the operator through commit / stash / discard / abort. For git-related reasons the skill prints reason-specific repair guidance and asks the operator to fix the state externally before confirming resume (mode `manual-fix`). Once the tree is clean, the halt block is atomically cleared. See `claude/lazycortex-core/skills/lazy-runtime.recover/SKILL.md`.

The check is read-only on the daemon side — the daemon never cleans the tree itself. The operator authors every commit in the recovery path.

---

## 11. Expert runtime contract

Every expert run receives `claude/lazycortex-core/references/lazy-core.expert-runtime-contract.md` via `claude -p --append-system-prompt-file ...`. The contract is loaded as a system-prompt-level rule on top of the expert's per-protocol contract.

Contract sections:
- **Working tree** — every change must be committed before exit. No push, no branch switching.
- **Input** — `request.json` schema (required `role`, plus protocol-specific fields).
- **Output** — `response.json` schema (`outcome`, `result`, `error`).
- **What you must not touch** — `DONE`, other experts' job dirs, state.json, branches.

### MCP servers — hermetic by default

Expert spawns always run `claude -p --strict-mcp-config`, so **ambient operator MCP servers are never inherited** (`~/.claude.json`, project `.mcp.json`). This is deliberate: the daemon spawns experts headless with no TTY, and an interactively-authenticated MCP server (OAuth / claude.ai connectors) blocks on initialization until the job hits its routine timeout and dies. Expert memory is file-based (`.memory/<self>/`, see `lazy-memory.persona-aspect`), not MCP — hermetic spawns lose no capability by default.

An expert that genuinely needs one or more MCP servers declares them per-expert:

```
experts:
  <name>:
    mcp_config: .claude/mcp/<name>.json          # single path
    # or: mcp_config: [.claude/mcp/a.json, .claude/mcp/b.json]
```

Each path (relative to the repo root) is passed as `--mcp-config <path>`; under `--strict-mcp-config` the spawn loads **only** those servers. The referenced files use the standard MCP-config JSON shape. Only headless-safe servers work here (token/env auth, no interactive login, launcher on `PATH`); an interactive-auth server declared this way still blocks. Validate a config's launchability with `/lazy-runtime.preflight` before wiring it into a live routine.

### Settings sources — hermetic by default

Expert spawns always pass `claude -p --setting-sources project,local`, so **operator user-scope settings are never loaded** by default. This is the settings-file analogue of `--strict-mcp-config`: user-scope (`~/.claude/settings.json` and the plugins it enables) is where interactively-oriented operator plugins and their hooks live, and a headless spawn that inherits them can hang. For example a `PostToolUse [*]` hook that blocks on a terminal/OAuth round-trip stalls every tool call until the routine timeout kills the job. Dropping `user` scope keeps the project's own skills / agents / plugins (`project`, `local`) while shedding that ambient risk.

An expert that genuinely needs user-scope settings opts back in explicitly:

```
experts:
  <name>:
    setting_sources: [user, project, local]   # or a comma string "user,project,local"
```

Valid scopes are exactly `user`, `project`, `local`; anything else is dropped (surfaced as a `warn` by `/lazy-runtime.preflight`). An absent or empty `setting_sources`, or one that leaves no valid scope, resolves to the hermetic `project,local` default — the flag is always emitted, so every expert is hermetic out of the box with no per-expert config, exactly like `--strict-mcp-config`. The default does not touch authentication: OAuth login keeps working.

---

## 12. Metrics

The daemon can serve a Prometheus-format `/metrics` HTTP endpoint covering routine throughput, error rates, tick durations, queue depth, halt status, and Anthropic API token usage. Off by default — opt in by adding a `metrics` block to the flat `daemon` section (`daemon.metrics`).

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

`status` ∈ `{ok, error, timeout, crash}`. `state` ∈ `{ready, running, done}`. `kind` ∈ `{input, output, cache_read, cache_write}`.

The `reason` label is metric-specific:

- On `routine_errors_total` (routine tick failures): `{timeout, resolve, subprocess_error, unexpected, git_pre_failed, git_post_failed}`.
- On `daemon_halts_total` / `daemon_halted` (gauge): `{uncommitted_changes, git_pull_diverged, git_push_failed, git_remote_unavailable, suspected_loop}` — matches the closed set in § 9.

### Shipping to a Prometheus + Grafana stack

The endpoint is local-only by default. To ship metrics to a self-hosted observer, install the public `lazycortex-observe` plugin — it ships generic Grafana Alloy / OpenTelemetry Collector templates, launchd / systemd service units, a Grafana dashboard JSON, and Prometheus alert rules. The plugin is observer-server-blind: no hostnames, tokens, or operator-private identifiers in any shipped file. Operator-private values live in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and the `LAZYCORTEX_OBSERVE_TOKEN` env var.

Versioned independently of `lazycortex-core` via the file's `version:` frontmatter. Bump the contract's version when the schema changes; experts re-read it on next dispatch (no daemon restart needed).

---

## 13. Worktree-isolated tasks

A routine flagged `isolate: true` (see § 8) does not write directly to the base branch. Instead the daemon runs its unit of work on a dedicated `task-<id>` branch inside an in-tree git worktree under `<repo>/<worktree_root>/task-<id>/`, then reintegrates the branch to base by auto-merge or pull request. This keeps slow, multi-commit code tasks off the base branch and out of the fast direct-write routines' way. Owned by `WorktreeTaskManager` in `bin/worktree_tasks.py`; wired into the daemon loop in `bin/runtime_daemon.py`.

The feature is **inert** when no `isolate: true` routine is registered and no task is in flight — direct-write routines take the unchanged dispatch path, and the polling / sweep steps are no-ops.

### Lifecycle

1. **Start.** When an `isolate: true` routine comes due, the daemon calls `mgr.start(...)` instead of the direct-write path. The manager:
   - Forks a `task-<id>` branch from fresh base — `origin/<base_branch>` when a remote tracking ref exists, else the local base branch.
   - Creates the worktree directory under `worktree_root` and checks the branch out into it.
   - Provisions the gitignored local config (`.claude/settings.local.json`, `.claude/lazy.settings.local.json`) by symlinking the primary checkout's copies in, so task agents inherit the operator's permission and path posture (a fresh checkout materialises only tracked files).
   - Registers the task in `state.json`'s `worktree_tasks.<work_id>` block (see § 9).
   - When the concurrency cap (`max_concurrent_tasks`) is already reached, `start` returns `{"result": "at_capacity"}`; the daemon leaves the routine due and retries on a later tick.
2. **Poll.** Each iteration, before dispatching new work, the daemon polls every registered task whose entry carries a `job_id` via `expert_runtime.collect_job`. A task whose job reports `done` advances to finish.
3. **Finish.** `mgr.finish(work_id)` reintegrates and tears down:
   - For an `allow_merge: true` task, the branch is rebased onto base and fast-forward merged; a clean merge deletes the task branch.
   - On rebase or fast-forward conflict, or for an `allow_merge: false` task, the branch is pushed (best effort) and a pull request is opened via `gh`, keeping the branch for review.
   - Either way the worktree is removed and the registry entry deleted. The primary checkout is returned to the base branch before the worktree is torn down, so the next tick rides base.
4. **Sweep.** On the same hourly cadence as runtime-log cleanup, `mgr.sweep()` runs `git worktree prune` and force-removes any directory under `worktree_root` that is not in the registry — an orphan left by a crashed task.

### Integration outcomes

`finish` returns one of: `merged` (clean auto-merge), `pr_opened` (pull request created), `pr_deferred` (pull request could not be opened — see below), or `unknown` (work id not registered).

### `gh` dependency (optional)

The pull-request path shells out to the `gh` CLI. When `gh` is absent, or no GitHub remote / auth is configured, `_open_pr` returns `pr_deferred` with a reason — the task branch is kept, the worktree is still torn down, and the daemon continues. The operator opens the pull request by hand later. `gh` is an optional external dependency.

---

## 14. Daemon self-restart on own code change

The daemon watches its own loaded `.py` source and restarts at an iteration boundary when that source changes — so a `/plugin update` (or a dev-vault source edit under `--dev-mode`) takes effect without a manual restart. Owned by `CodeFingerprint` in `bin/code_fingerprint.py`.

- At `run()` startup the daemon snapshots the hashes of every loaded module whose file lives under a watched plugin root. Watched roots are the directories in `LAZYCORTEX_PLUGIN_DIRS` plus the running module's own parent directory.
- After each iteration (and only when the daemon is not halted), the fingerprint is re-checked. A change is acted on **only once it is stable across two consecutive observations**, so an in-flight half-written update never triggers a premature restart.
- On a stable change the daemon logs `restart: own code changed` and restarts:
  - Under a supervisor (`LAZYCORTEX_SUPERVISED=1`, exported by the launchd plist / systemd unit) → clean `SystemExit(0)`; the supervisor relaunches the process with fresh code. The systemd unit uses `Restart=always` (not `on-failure`) so the clean exit-0 still relaunches; launchd's `KeepAlive` relaunches on any exit.
  - Unsupervised → `os.execv` replaces the process image with a fresh interpreter.
- The restart happens at the iteration boundary, after any commit has landed and outside the halt path, so it never interrupts mid-commit work or masks a halt the operator still needs to recover from. In-flight worktree tasks (§ 13) survive the restart because the registry and worktrees persist on disk and the next iteration's poll re-attaches them.
