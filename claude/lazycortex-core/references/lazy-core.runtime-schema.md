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
| `stream_idle_timeout_sec` | int | `900` | Seconds of stdout silence from a `claude -p` expert spawn before it is treated as a frozen stream, its process group killed, and the spawn re-tried. Sized for opus-tier experts, which legitimately stay silent for minutes while thinking. |
| `stream_max_retries` | int | `3` | Maximum number of in-memory re-spawns on stream-idle-stall before the job is left with a transient error for the next tick. Separate from the on-disk `attempts` counter. |
| `cleanup_runtime_log_after` | duration string | `"30d"` | Age after which a dated `<YYYY-MM-DD>.jsonl` journal is deleted. The hourly sweep walks all of `.logs/`, so a journal written by any plugin (`.logs/lazy-review/runs/…`, and whatever a future plugin adds) is retained on the same window without registering itself. Journals with no date in the name — `tokens.jsonl`, `jobs.jsonl`, `commits.jsonl` — are append-only ledgers whose age says nothing about which lines are still wanted; operators rotate those. |
| `loop_detect_window` | int | `threshold * 4` | Number of recent commits to inspect for the per-(author, patch-id) loop-detection heuristic. Must be ≥ `loop_detect_threshold`. Larger values give better accuracy at the cost of a slightly slower `git log` query. |

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
| `worktree_root` | string | Optional. Repo-relative directory that holds per-job worktrees for `workspace: branch` jobs (see § 13). Default `".worktrees"`. Listed in `.gitignore` so in-tree worktrees stay untracked. |
| `worktree_bootstrap_cmd` | string | Optional. Shell command (`sh -c`) run inside every freshly created job worktree, after config provisioning and before the spawn, to rebuild the gitignored execution environment (venv and the like) a worktree does not materialise. Absent = no bootstrap. A non-zero exit fails the job (`transient`) before any spawn. Everything the command creates MUST be gitignored — the post-job dirty-worktree check reads `git status --porcelain`, so an un-ignored bootstrap artifact fails every otherwise-correct job. The same obligation covers `settings.local.json` / `lazy.settings.local.json` (already gitignored by install). |
| `post_push_hook` | string | Optional. Shell command run via `sh -c` (cwd = repo root) after each post-iteration push that actually advances `origin/<base_branch>`. Absent or empty = disabled. Fully isolated: non-zero exit, timeout, or spawn failure is journaled and never affects the tick. |
| `post_push_timeout_sec` | int | Optional. Wall-clock cap on the post-push hook process. Default `30`. On expiry the hook is killed and the timeout journaled. |
| `allowed_hooks` | list | Optional. Operator git-hook filenames (`pre-commit`, `commit-msg`, …) allowed to run under the daemon. At startup the daemon rebuilds `<git-common-dir>/lazy-hooks/` with a symlink per vetted name and points `core.hooksPath` at it through the environment, so a hook absent from the list never fires on a routine's commit. Absent or empty = no operator git hook runs under the daemon; the operator's own sessions are untouched. |

`base_branch` and `remote_sync` are seeded by `lazy-core.install` from the checkout itself — the current branch, and `"pull_push"` when an `origin` remote exists. The block is written only when absent or `null`, so a hand-tuned one survives re-installs; `post_push_hook` is never seeded. A daemon-enabled repo whose `git` block stays `null` is a `lazy-core.audit` D3 finding.

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

**Post-push hook** (when `daemon.git.post_push_hook` is set): immediately after either successful push above (fast-forward or post-rebase), the daemon runs the configured command via `sh -c` with cwd = repo root and five env overrides: `LAZY_PUSH_REPO` (absolute repo path), `LAZY_PUSH_BRANCH` (the pushed branch), `LAZY_PUSH_REMOTE` (`origin`), `LAZY_PUSH_OLD_SHA` (the `origin/<branch>` tip before the push), `LAZY_PUSH_NEW_SHA` (local HEAD after the push — re-read after any rebase). The hook does NOT fire when nothing was pushed: in-sync ticks, the already-published fallthrough, and the rebase-conflict discard all skip it. Hook failures (non-zero exit, timeout past `post_push_timeout_sec`, spawn errors) land in the runtime journal as a `_post_push_hook` record and never halt, retry, or fail the tick.

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
    "cleanup_dead_after": "7d",
    "stream_idle_timeout_sec": 900,
    "stream_max_retries": 3
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
| `expert` | string | one of `command` / `expert`+`request` | Expert name. When set, `request` is also required. The mutually-exclusive alternative to `command`. |
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

A tick that did nothing is not journaled. Every routine runs every few seconds, so recording quiet ticks would add thousands of identical lines a day and bury the ones that matter. A tick is quiet when it exited zero, reported no error, ran under 1.5 s, and reported no dispatched work — whether that count arrives as a `dispatched_count` result field or inside the stdout tail. Metrics still count the tick, so rates and latencies stay complete.

**Supervisor captures.** On macOS the launch agent redirects the daemon's stdout and stderr to `.logs/lazy-core/runtime/launchd.out.log` and `launchd.err.log`. Neither carries a date, both are held open for the life of the daemon, and nothing else writes them, so the hourly sweep trims a capture in place once it passes 1 MB, keeping the last 256 KB from the first whole line onward. Deleting them instead would leave the supervisor writing to an unlinked inode while the visible file stayed empty. On Linux the unit has no file redirect — stdout and stderr go to the systemd journal, which journald rotates.

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
| `git` | `branch`, `watch`, plus EITHER `command` OR `expert`+`request`, `interval_sec` | `repo_dir`, `remote`, `path_filter`, `filter`, `group_globs`, `timeout_sec` |
| `md-scan` | `paths`, `expert`, `interval_sec` | `filter`, `request`, `cadence`, `timeout_sec` |

Every type additionally accepts the common keys `type`, `priority`, `protocol` / `protocols`, `ignore_halt`, `hooks_enabled`, and `git_author` (plus the retired `isolate` / `allow_merge`, accepted but ignored) — `hooks_enabled` is the allow-list of lazycortex hook short names this routine's own subprocess may run (empty or absent silences all of them). `ignore_halt` lets a routine tick while the daemon is halted AND skips the post-tick working-tree check for it, so a routine that carries it must report its own failures.

`git_author` (`{name, email}`, the same shape as an expert entry's block) names the bot identity for any commits the routine's own subprocess makes: the daemon exports `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` into every command-shape spawn via `routine_subprocess_env`, same coverage as the pump gives expert jobs. Committer is deliberately untouched — both consumers of automatic-commit identity (loop-detect and the coordinators' operator-vs-bot check) read the author. Canonical form: `<routine-family>@bot.invalid` (the RFC 2606 `.invalid` TLD is undeliverable by construction). Absent key is not an error — the routine commits under the daemon process's identity, as before. Loop-detect collects `git_author.email` from routines and experts alike, so a deterministic routine cycling on its own diff halts the daemon the same way an expert does.

`paths` globs: a pattern containing `**` is matched full-path-anchored with `**` spanning any number of segments (including zero); a pattern without `**` keeps `PurePath.match` semantics (right-anchored, `*` never crosses `/`). In `**`-bearing patterns character classes like `[abc]` are treated as literal text (only `*` and `?` are wildcards); patterns without `**` keep full `PurePath.match` semantics.

Closed-set strict validation: unknown type, unknown field, missing required, or per-type custom constraint violation → `RoutineConfigError` at registration time. The daemon re-validates every entry each time it loads the registry, so an entry written by hand, seeded by an install skill, or left behind by a schema change is rejected on read rather than at first dispatch — see § 10.

**Common optional fields (any type):** `protocol: <ref>` or `protocols: [<ref>, ...]` — declares which protocol(s) the routine's dispatched jobs follow. The dispatcher resolves each ref via `reference_resolver.resolve(..., category="protocols", ...)` and threads the resolved paths through to each job's `config.json`. Protocols are routine-side, not expert-side — expert entries in `lazy.settings.json[experts]` do NOT carry a `protocol` field. See `lazy-core.expert-protocols-contract.md`.

**Retired worktree-isolation fields (any type):** `isolate` and `allow_merge` belonged to the retired routine-side worktree path. They are still ACCEPTED by validation (a consumer's config must not start failing over a dead flag) but ignored, with a stderr warning per occurrence; `lazy-core.doctor` / `lazy-core.autocheckup` offer the prune. Job-level isolation lives in `experts[<name>].workspace` instead — see § Workspace.

### `inbox`

Scans `inbox_dir` each tick. The input file is never copied into the job bundle — only its **path** is passed, so the inbox is the single source of truth for the file (parity with `git` / `md-scan`, which also pass a path).

`command` sub-shape — spawn `command + [<absolute-path-to-file>]` per file (blocking, one at a time). The consumer command owns the file; the routine never removes it.

`expert + request` sub-shape — two passes per tick:

1. **Reconcile** finished work via `completed_dedup_jobs`: for every prior job keyed on an inbox path, if it **succeeded** (`outcome` ≠ `error`) drain the input (`unlink`, best-effort — the expert may have filed it away itself on success) and mark the bundle `CONSUMED`; if it **failed** leave the input parked — the bundle stays `DONE`-but-unconsumed so its dedup key keeps the file from re-dispatching. This is a **dead-letter**: the failed input sits in the inbox with its bundle's forensics retained for the operator to triage; it is not retried automatically (a crashed/`DEAD` job is the doctor's retry path, not this one). **Exception — a stale transient failure:** a bundle whose error `category` is `transient` (the spawn faulted, not the work) and that finished more than `TRANSIENT_RETRY_AGE_SEC` (1 h) ago is marked `CONSUMED` **without** draining the input, so pass 2 of the same tick re-dispatches the file. Retries repeat at that cadence for as long as the spawn keeps faulting.
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
| `new_files` | `{path}`, `{status}`=A, `{sha}`, `{author_name}`, `{author_email}` |
| `changed_files` | `{path}`, `{status}` (A or M), `{sha}`, `{author_name}`, `{author_email}` |
| `deleted_files` | `{path}`, `{status}`=D, `{sha}`, `{author_name}`, `{author_email}` |
| `renamed_files` | `{old_path}`, `{new_path}`, `{sha}`, `{author_name}`, `{author_email}` |

**`group_globs`** (optional, file-level watches only — rejected with `new_commits`) — an ordered list of directory globs; after the composite filter runs, file items whose path sits strictly below a matching glob collapse into ONE item per matched directory. The first glob in list order wins; a glob matches segment-by-segment (`*` never crosses `/`); a file lying AT the glob's depth (a folder-note beside the group dirs) and any path outside every glob stay ordinary file-level items. A group item exposes `{dir}` (the matched directory), `{paths}` (sorted member paths), and `{sha}` / `{author_name}` / `{author_email}` of the last commit touching the dir in the scanned range. The group is also the retry unit: a failing group re-dispatches whole.

`last_seen_sha` tracked in state.json's `git_watch.<name>` block. First run records the current local HEAD and dispatches nothing (no history backfill). Non-ancestor baseline-reset (e.g. after a rebase pull rewrites history) resets the baseline and computes no fresh items over the discarded range.

**`command`-shape retry cursor.** An item whose spawned worker exits non-zero is recorded in `git_watch.<name>.failed_items` (`{sha, ..., reason}` — the full item dict plus a bounded `reason` string carrying the exit code and a trimmed stderr tail) instead of being silently dropped; `last_seen_sha` still advances past it so one broken item never stalls the rest of the range. The next tick retries every `failed_items` entry — in order, before any fresh item — and clears an entry on success; a repeat failure leaves it in place (no retry cap: a permanently failing item is a permanently visible line in the daemon's routine-tick journal, the operator's diagnostic). An entry whose `sha` history no longer knows (a later force-push rewrote it away) is dropped instead of replayed, using the same ancestry check the baseline-reset guard uses; the tick's `note` field reports the drop. This applies only to the `command` sub-shape — the `expert + request` sub-shape dispatches jobs asynchronously and has no synchronous exit code to observe.

The `remote` config field is vestigial for the watch — remote sync is the daemon's job (`daemon.git.remote_sync` / `_git_pre`). It is accepted but ignored. By the time `dispatch_git` runs, `_git_pre` has already pulled remote commits into the local branch, so local HEAD reflects both local system commits and pulled-in remote commits — one watch covers both, and a remote-less repo works with no fetch.

The git watch itself is working-tree-neutral: only read-only `rev-parse`/`log`/`diff`. What it dispatches is not — a `command` routine may write and commit, so the halt invariant is the consumer's responsibility, not the watch's.

### Composite `filter` block (`inbox`, `git`, `md-scan`)

The optional `filter` key on `inbox`, `git`, and `md-scan` routines is a composite predicate block. Each declared sub-key must pass (AND semantics), except `any_of` (below), which is itself an OR over composite members. An empty or absent block accepts every item.

**`filter.frontmatter`** — per-key `{ in, not_in }` predicates applied to the item's parsed YAML frontmatter. `in` (allow-list) and `not_in` (deny-list) both AND with each other and with other keys. `null` in either list matches a missing key or an explicit `null`. Non-markdown items and unreadable files parse to `{}` — a `null`-accepting predicate keeps them; a value-requiring predicate drops them. The legacy bare-list/scalar form is rejected.

**`filter.folder_note`** (tri-state) — constrains matches by folder-note status. A file `p` is a folder note iff `Path(p).stem == Path(p).parent.name` (e.g. `claude/lazycortex-core/lazycortex-core.md`). Obsidian plugin settings are never consulted; the convention is hardcoded.

| Value | Effect |
|---|---|
| `true` | Match only folder notes. |
| `false` | Exclude folder notes. |
| absent | No constraint — both pass. |

Items with no file path (e.g. `new_commits` git-watch items) are treated as non-folder-notes: `folder_note: true` excludes them, `folder_note: false` keeps them. Must be a boolean when present — a non-boolean value raises `RoutineConfigError`.

**`filter.basename`** — a `{ in, not_in }` predicate applied to the item's file basename (`Path(path).name`). Same allow-list/deny-list semantics as `filter.frontmatter`'s per-key predicates. Items with no file path (e.g. `new_commits` git-watch items) match against `None` — a `null`-accepting predicate keeps them; a value-requiring predicate drops them.

Example combining all three flat sub-keys:

```json
{
  "filter": {
    "folder_note": true,
    "frontmatter": {
      "stage": { "in": ["draft"], "not_in": [] }
    },
    "basename": { "in": ["design.md", "tech.md"], "not_in": [] }
  }
}
```

**`filter.any_of`** — a non-empty list of composite filters (each shaped like the `filter` block itself: `frontmatter` / `folder_note` / `basename`), matching when **any** member matches (OR semantics). Mutually exclusive with a flat `frontmatter` / `folder_note` / `basename` at the same level as `any_of` — declaring both raises `RoutineConfigError`. Each member is validated with the same closed sub-key vocabulary; an unknown key inside a member raises `RoutineConfigError`. Members do not nest further `any_of`. An empty `any_of: []` raises `RoutineConfigError` rather than silently matching nothing forever — the inverted polarity of an absent/empty flat filter, which accepts everything.

Example — matches a status folder-note OR any of a fixed set of sibling doc basenames:

```json
{
  "filter": {
    "any_of": [
      { "frontmatter": { "spec_role": { "in": ["status"], "not_in": [] } } },
      { "basename": { "in": ["design.md", "architecture.md", "code-plan.md"], "not_in": [] } }
    ]
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
    "<routine_name>": {
      "last_seen_sha": "<full_hex>",
      "failed_items": [{ "sha": "<full_hex>", "...": "<rest of the item dict>", "reason": "<exit code + trimmed stderr tail>" }]
    }
  },
  "daemon_halted": {
    "halted_since": <unix_ts>,
    "triggered_by": "<routine_name|_git_pre|_git_post|lazy-expert.pump>",
    "reason": "uncommitted_changes|git_pull_diverged|git_push_failed|git_remote_unavailable|suspected_loop|routine_config_invalid|rate_limit",
    "dirty_paths": ["<git status --porcelain line>", ...],
    "resets_at": <unix_ts, rate_limit only>,
    "expert": "<expert_name|null>",
    "job_id": "<job_id|null>"
  }
}
```

`daemon_halted` is absent when healthy. `git_watch` is absent when no `git`-type routines are registered. `failed_items` is absent (or empty) when nothing has ever failed, or once every prior failure has cleared. A legacy `worktree_tasks` block may linger from the retired routine-side worktree path; nothing reads it anymore. `dirty_paths` is empty for git-related halt reasons (the tree is presumed clean at halt time; the halt cause is in the branch/remote state, not the working tree).

**Halt reasons (closed set):**

- `uncommitted_changes` — routine left the working tree dirty (see § 10). Recovery: dirt-cleanup wizard via `/lazy-runtime.recover`.
- `git_pull_diverged` — pre-tick fetch found that local and origin both have commits the other doesn't. Recovery: operator repairs branch state manually, then `/lazy-runtime.recover` clears the halt.
- `git_push_failed` — post-tick push retried `POST_TICK_MAX_PUSH_ATTEMPTS` (3) times and kept failing. Recovery: operator investigates push refusal (auth, branch protection, persistent race), then `/lazy-runtime.recover`.
- `git_remote_unavailable` — any other unexpected git failure during pre- or post-tick remote sync (network, permission, missing remote). Recovery: operator restores network/auth, then `/lazy-runtime.recover`.
- `suspected_loop` — loop-detection heuristic fired: one identical diff (`git patch-id --stable`) was committed ≥ `loop_detect_threshold` times by the same registered-bot author within the `loop_detect_window` commit window. Commit volume alone never trips it — only a diff that keeps re-landing unchanged, directly or as one leg of an oscillation. The halt block names the offending patch-id, author, and the repeated commits' subjects. Recovery: operator investigates the routine's commit pattern and runs `/lazy-runtime.recover` once resolved.
- `routine_config_invalid` — a `routines[*]` entry failed `validate_routine_entry` when the daemon read the registry (see § 10). `triggered_by` names the offending routine; the schema error text is in the routine's own `routine:<name>` incident. Recovery: operator fixes the settings entry, then `/lazy-runtime.recover` (mode `manual-fix`).
- `rate_limit` — an expert run's `rate_limit_event` frame tripped the rate-limit guard (`daemon.rate_limit_guard`): the subscription window is closed. The block carries `resets_at` — the latest reopening time across the host-local flag records at `${XDG_CACHE_HOME:-$HOME/.cache}/lazycortex/rate-limit/`. Self-lifting: `_run_iteration` clears the halt (and resolves the `halt:<repo>` incident) once `now >= resets_at`; a block with no `resets_at` is treated as already expired. While halted the loop sleeps `min(resets_at − now, 3600)` instead of the polling interval, git sync stays alive, and the self-update restart is NOT skipped for this reason (state survives the restart, a restart burns no tokens). Recovery: none needed; `/lazy-runtime.recover` (mode `manual-fix`) resumes early — safe, the pump's pre-spawn flag check still defers spawns while the flag lives.

Persistence consequences:
- `last_run` survives daemon restart and laptop sleep — slow routines (e.g. every 6h) are honored across restarts.
- `git_watch.<name>.last_seen_sha` survives daemon restart — `git` routines do not re-dispatch already-handled commits after a reboot.
- `git_watch.<name>.failed_items` survives daemon restart — a `command`-shape worker crash across a restart still retries on the next tick rather than being lost with the in-memory tick.
- `daemon_halted` survives daemon restart — a halted daemon stays halted across reboots until the operator runs `/lazy-runtime.recover`.

---

## 10. Working-tree protection and halt invariants

The daemon halts (writes a top-level `daemon_halted` block to state.json and stops scheduling routines) on any of these conditions:

- **Dirty working tree after a routine** — `git status --porcelain` non-empty → `reason: uncommitted_changes`. Why daemon-wide rather than per-routine: the daemon rides the operator's base branch directly, so leftover dirt is operator/routine WIP that the next iteration's routines would read as inconsistent tree state (and commit over). If a single routine left dirt, even routines that operate purely in gitignored paths would see that inconsistent state in the next iteration. Halting everything is the safe default.
- **Pre-tick divergence** — local and origin branches both have commits the other doesn't → `reason: git_pull_diverged`. Automatic resolution would risk dropping the operator's commits, so the daemon halts and waits.
- **Post-tick push exhausted retries** — the rebase+push retry loop failed `POST_TICK_MAX_PUSH_ATTEMPTS` times → `reason: git_push_failed`. Indicates either persistent operator-side races (rare) or branch-protection / auth refusal.
- **Other pre- or post-tick git failure** — network, missing remote, permission, etc. → `reason: git_remote_unavailable`.
- **Malformed registry entry** — an entry under `routines` fails `validate_routine_entry` when the daemon loads the registry, before any scheduling decision reads it → `reason: routine_config_invalid`. The entry is dropped from that iteration's registry and opens a `routine:<name>` incident carrying the schema error verbatim; every further broken entry increments `routine_errors_total{reason="routine_config_invalid"}` under its own routine label, while the halt block keeps the first one's attribution. Why daemon-wide: a schema violation never self-heals — it stands until the operator edits the settings — so skipping it quietly every tick would hide a routine that silently stopped working.

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

### Lazycortex hooks — hermetic by default

`--setting-sources project,local` sheds *operator user-scope* hooks, but the project's own lazycortex hooks (`lazy-core.git-guard`, `lazy-guard.check-public`, `lazy-core.model-router`, `lazy-guard.settings`, `lazy-log.commit-recorder`) still load at `project` scope — and each one runs on every `Bash` boundary of the spawn. For a headless expert that is pure tax: `lazy-guard.check-public` and `lazy-core.git-guard` alone add tens of seconds per tool call and gate nothing the expert needs.

So the daemon exports `LAZYCORTEX_HOOKS_ALLOW_LIST` for every routine it dispatches, from that routine's own `hooks_enabled`, and each lazycortex hook consults it as its first action (`bin/hook_gate.py` for python hooks; shell hooks read the variable directly, since a git hook gets no path into the plugin tree). Expert spawns inherit it from the routine that runs the pump — the pump is itself a routine, so the setting lives in exactly one place. The variable is named for the action it exerts — "these hooks may run" — not for who set it: an operator can export the same variable in a shell to the same effect. Its **presence** flips every hook into allow-list mode; only the named hooks run, so a routine with no config runs none of them.

`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` is pinned to `3` the same way, on every headless expert spawn — daemon-driven or a manual `expert-pump-once` from `/lazy-spec.drive` alike, since both go through this same `env` construction — and on the daemon's own subprocess environment (`EnvVar.SUBAGENT_SPAWN_DEPTH_PIN`). Only the operator's own interactive session, never itself spawned by the pump, inherits whatever the ambient shell already has.

A routine opts specific hooks back in:

```
routines:
  <name>:
    hooks_enabled: [lazy-core.git-guard]   # only the git guard runs in this routine's subprocesses; the rest no-op
```

Absent or empty, the exported allow-list is empty → every lazycortex hook no-ops in anything the routine spawns (the hermetic default, mirroring `setting_sources`). On an `expert`-shape routine the key is inert: that session is spawned by the pump routine and therefore carries the pump's list.

The same gate powers the mirror-image interactive control. In a normal session (no `LAZYCORTEX_HOOKS_ALLOW_LIST`) every hook runs unless the operator silences it by short name in a root-level block-list:

```
hooks:
  disabled: [lazy-core.model-router]   # this hook no-ops in interactive sessions; the rest run
```

`hooks.disabled` reads the tracked value with the local overlay merged on top, so a personal silence can live in the gitignored `lazy.settings.local.json`. The block-list read fails open — a missing or malformed settings file silences nothing. Operator hooks outside the lazycortex tree do not read this variable; user-scope ones are already shed by `--setting-sources`, and operator *git* hooks are handled by a different mechanism — the daemon points `core.hooksPath` at a directory of symlinks to the hooks named in `daemon.git.allowed_hooks`, so an unvetted one never runs under it.

### Workspace — branch enforcement, main by default

An expert's spawn runs on the daemon's base branch by default (`workspace: main`, or the key absent — today's behavior). An expert that carries out the acceptance-cycle work `lazycortex-specs.optional-plan-and-auto-implementation.md` describes (implementer/tester classes on a launch-checkbox job and its continuations) opts into a job-scoped branch instead:

```
experts:
  <name>:
    workspace: branch   # main | branch — default main
    merge: ask           # auto | ask — default ask; consulted by the DISPATCHER's own
                          # merge logic, never read by the pump itself
```

`workspace: branch` is a CAPABILITY the expert opts into, not a mandate every one of its jobs must satisfy: it is enforced by the pump (`expert_pump._process_one`), never by the expert — the expert never runs git worktree or checkout commands itself (`lazy-core.expert-runtime-contract.md` "What you must not touch" already forbids it) — and it activates only when the job's own `request.json` carries a `branch` field. When a `workspace: branch` expert is also dispatched for work that carries no `branch` (an ordinary review-rewrite from `review.coordinator`, say, sharing the same implementer/tester expert the acceptance cycle uses), that job runs on whatever is already checked out, byte-identical to a `workspace: main` job — no refusal. The reverse mismatch — a `branch` present in the payload of a `workspace: main` (or absent) expert's job — is also never a refusal: the field is ignored (a warning line goes to the daemon log) because a main-workspace expert never branches, full stop.

**The token stays `branch`; the mechanism is a linked worktree.** When `branch` IS present and `workspace: branch` applies, the pump runs the job in an isolated git worktree at `<worktree_root>/job-<job_id>/` instead of switching the primary checkout: a fresh dispatch's branch is created off fresh base (`origin/<base_branch>` when the tracking ref exists, else the local base), a continuation's existing branch is reused as-is; the gitignored local config (`settings.local.json`, `lazy.settings.local.json`) is symlinked in; `daemon.git.worktree_bootstrap_cmd` (when configured) runs in the worktree to rebuild the gitignored execution environment (a bootstrap failure fails the job as `transient` before any spawn); the spawn's cwd is the worktree; and the worktree is removed on EVERY outcome — success, failure, crash — with the branch as the only durable product. The primary checkout never leaves base, so the operator's tree and the daemon's `_git_pre` are untouched by isolated jobs. The one refusal left in this path is a missing `daemon.git.base_branch` — a fresh job branch has nothing to fork from — so the job errors (`error`, category `logical`) rather than forking off an arbitrary point.

**Commit obligation and job-failure checks.** The isolated agent's prompt carries the obligation to commit all work to its branch (with resume wording on a continuation: build on the existing commits, never rewrite them). After a clean exit the pump verifies the worktree: uncommitted changes, or zero commits over base with a clean tree, fail the JOB (`error`, category `logical`) — never the daemon; the daemon-wide dirty-tree halt applies only to non-isolated jobs, whose spawns share the operator's tree. Uncommitted dirt disappears with the worktree (operator decision, 2026-08-14); diagnosis lives in the job's transcript and error record.

**Continuation reuses the same branch.** A dispatcher driving the acceptance cycle's comment-and-redo loop passes the SAME `branch` value on every continuation job as the original dispatch — the pump's create-or-reuse check (`git rev-parse --verify`) makes this idempotent; a continuation never gets a fresh branch of its own, though it does get a fresh worktree and a fresh bootstrap run. Only the coordinator ever writes the `branch` field — for a fresh launch-checkbox dispatch and every one of its continuations; every other dispatch to the same expert (review rewrites) simply omits it. The pump itself never persists the branch name anywhere — it is RECOMPUTED by the dispatcher from the asset's own identity on every dispatch (`lazy-spec.coordination-playbook.md` § 6), so a dispatcher whose naming scheme depends on a renameable asset identifier (a slug, a folder path) silently orphans an in-flight branch the moment that identifier changes underneath it; this is the dispatcher's own constraint to document, not something the pump's create-or-reuse check can catch.

**`merge` is dispatcher-owned, not pump-owned.** The pump never merges a branch back — only the coordinating dispatcher does, per its own playbook judgment (see `lazy-spec.coordination-playbook.md` § 6 for the spec-system's own instance of this). `merge: auto` / `merge: ask` (default `ask`) is read by that dispatcher logic alone; it has no runtime effect inside `expert_pump.py`.

**A claimant killed mid-job leaves only an orphan directory.** The primary checkout was never switched, so there is nothing to restore; the abandoned worktree is collected by the hourly `sweep()` (every directory under `worktree_root` is an orphan by definition — a live worktree exists only inside one synchronous pump run, and the serial main loop never sweeps concurrently with one). The same holds in a no-daemon drive session (`lazycortex-specs.lazy-spec.drive` pumping `expert-pump-once` by hand): an interrupted manual pump leaves an orphan worktree and an untouched checkout, nothing more.

**The git guard stands down inside a linked worktree.** `lazy-core.git-guard` skips both the pathspec discipline and the staging-window mutex when the invocation's `--git-dir` differs from `--git-common-dir` — a linked worktree has its own index, so the shared-index premise both rows rest on does not hold there.

### Filesystem sandbox — resolved paths only

Every expert spawn is confined by `.runtime/sandbox.settings.json` (daemon-owned, gitignored, passed as `--settings`; absent file = unconfined spawn). The confinement is checked against the path the OS **resolves**, not the path the allowlist spells: an entry naming a directory reached through a symlink permits nothing where the data actually lives, and every write there fails with `Operation not permitted` while the recorded config still reads as correct.

So the file is written by CLI, never by hand:

```
lazycortex-core sandbox-sync --repo-root <repo> [--allow-read <path>]... [--allow-write <path>]...
```

The repo root is granted read+write implicitly; whatever is writable is also readable. Each entry — recorded, passed, or the root — contributes the location it resolves to, plus the targets of the symlinks directly inside it (the `external_dirs` slots of § 15). Recorded entries are never dropped or reordered and a recorded `enabled` is never overwritten, so the call is idempotent; `enabled: false` comes back in the result for the caller to act on. `sandbox-audit --repo-root <repo>` is the read-only companion: it reports `missing_read` / `missing_write` — locations the recorded entries resolve to but do not grant. `/lazy-runtime.preflight` folds that audit into its checkout-level findings (`fail` on write, `warn` on read), so a symlink that moves after install surfaces as a finding instead of as a run of jobs failing on every write.

---

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

- **Registry** — the supervisor units themselves (`com.lazycortex.runtime.<REPO_ID>.plist` / `lazy-core-runtime-<REPO_ID>.service`) are the source of truth for "all daemons on this host". `lazycortex-core daemon-list` prints them joined with each repo's `daemon.metrics` settings.
- **Port allocation** — `lazycortex-core metrics-alloc-port --repo-root <path>` hands out the first free port from 9464 upward, skipping ports recorded by other daemons and ports that fail a live bind probe; a repo's already-recorded port is reused, unless a second registered daemon records the same one — a port that arrived by config copy rather than by allocation is not the repo's to keep, and the asking checkout is moved. The install skill runs this when enabling metrics.
- **Scrape targets file** — `lazycortex-core metrics-scrape-file` writes `${XDG_CONFIG_HOME:-~/.config}/lazycortex/scrape-targets.json` in Prometheus `file_sd` format: one `{"targets": ["127.0.0.1:<port>"], "labels": {"repo": "<label>"}}` entry per metrics-enabled daemon, nothing else (no paths, no hostnames). Point an existing Prometheus at it once with `file_sd_configs` and new daemons appear without further edits.
- **Port conflict at startup** — when the configured port is already bound, the daemon records a `daemon_error` incident with cause `metrics_port_conflict` (naming the holder: pid, command, and the owning repo when it is another registered daemon) and **keeps running without metrics**. A taken port never restart-loops the dispatch engine; the fix is re-running the install's metrics step (or editing the local-overlay port) and restarting the daemon.

### Metric shape

Closed label vocabulary — values come from a fixed enum, never from raw exception text, file paths, branch names, commit shas, hostnames, or any user-supplied string. The `repo` label disambiguates daemon instances; the constant `daemon_name` keeps operator identity out.

```
# Counters
lazycortex_runtime_routine_ticks_total{routine,repo,status}
lazycortex_runtime_routine_runs_total{routine,repo}
lazycortex_runtime_routine_errors_total{routine,repo,reason}
lazycortex_runtime_tokens_total{routine,repo,model,kind}
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

`status` ∈ `{ok, error, timeout, crash}`. `state` ∈ `{ready, running, done}`. `kind` ∈ `{input, output, cache_read, cache_write}`. `outcome` ∈ `{done, failed, dead, error}` — per job attempt, aggregated from the pump's `.logs/lazy-core/runtime/jobs.jsonl`; `error` marks an attempt that failed transiently and left the job queued for retry, the other three are terminal.

`dirty_tree` is 1 while the daemon's pre-iteration check finds uncommitted changes and routine dispatch is silently paused (the operator may be mid-edit); it drops back to 0 on the first iteration after the tree settles. This is the only externally visible trace of the silent skip — it is not a halt and records no incident.

`routine_runs_total` counts only non-idle ticks: a tick whose routine type reports an explicit `dispatched_count` of 0 (an inbox / md-scan / git poll that matched nothing) increments `ticks_total` but not `runs_total`. Ticks from types that report no dispatch count always count as runs. `ticks_total` is the scheduler heartbeat; `runs_total` is the real-work rate.

The `reason` label is metric-specific:

- On `routine_errors_total` (routine tick failures): `{timeout, resolve, subprocess_error, unexpected, git_pre_failed, git_post_failed, external_dir_broken, routine_config_invalid}`. `routine_config_invalid` is the one value that marks a permanently broken entry rather than a failed run — it never clears on its own and needs a settings edit.
- On `daemon_halts_total` / `daemon_halted` (gauge): `{uncommitted_changes, git_pull_diverged, git_push_failed, git_remote_unavailable, suspected_loop, routine_config_invalid}` — matches the closed set in § 9.

### Shipping to a Prometheus + Grafana stack

The endpoint is local-only by default. To ship metrics to a self-hosted observer, install the public `lazycortex-observe` plugin — it ships generic Grafana Alloy / OpenTelemetry Collector templates, launchd / systemd service units, a Grafana dashboard JSON, and Prometheus alert rules. The plugin is observer-server-blind: no hostnames, tokens, or operator-private identifiers in any shipped file. Operator-private values live in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and the `LAZYCORTEX_OBSERVE_TOKEN` env var.

Versioned independently of `lazycortex-core` via the file's `version:` frontmatter. Bump the contract's version when the schema changes; experts re-read it on next dispatch (no daemon restart needed).

---

## 13. Job worktrees

Isolated expert jobs (`workspace: branch` — see § Workspace above) run inside linked git worktrees under `<repo>/<worktree_root>/job-<job_id>/`, owned by `WorktreeTaskManager` in `bin/worktree_tasks.py` and driven synchronously by the pump inside one `_process_one` run. The manager never merges, never opens pull requests, and keeps no registry — reintegration is the coordinating dispatcher's business, and a worktree lives exactly as long as the pump run over its job.

The retired routine-side path (`isolate: true` routines, `allow_merge`, `max_concurrent_tasks`, the `worktree_tasks` registry in `state.json`) is gone: those settings keys are ignored with a stderr warning when present, and `lazy-core.doctor` / `lazy-core.autocheckup` offer the prune.

### Sweep

On the same hourly cadence as runtime-log cleanup, `mgr.sweep()` runs `git worktree prune` and force-removes every directory under `worktree_root` — each one is an orphan left by a crashed pump run, since a live worktree exists only inside one synchronous run of the serial main loop.

---

## 14. Daemon self-restart on own code change

The daemon watches its own loaded `.py` source and restarts at an iteration boundary when that source changes — so a `/plugin update` (or a dev-vault source edit under `--dev-mode`) takes effect without a manual restart. Owned by `CodeFingerprint` in `bin/code_fingerprint.py`.

- At `run()` startup the daemon snapshots the hashes of every loaded module whose file lives under a watched plugin root. Watched roots are the directories in `LAZYCORTEX_PLUGIN_DIRS` plus the running module's own parent directory.
- After each iteration (and only when the daemon is not halted), the fingerprint is re-checked. A change is acted on **only once it is stable across two consecutive observations**, so an in-flight half-written update never triggers a premature restart.
- On a stable change the daemon logs `restart: own code changed` and restarts:
  - Under a supervisor (`LAZYCORTEX_SUPERVISED=1`, exported by the launchd plist / systemd unit) → clean `SystemExit(0)`; the supervisor relaunches the process with fresh code. The systemd unit uses `Restart=always` (not `on-failure`) so the clean exit-0 still relaunches; launchd's `KeepAlive` relaunches on any exit.
  - Unsupervised → `os.execv` replaces the process image with a fresh interpreter.
- The restart happens at the iteration boundary, after any commit has landed and outside the halt path (except the self-lifting `rate_limit` halt, where restarting is allowed), so it never interrupts mid-commit work or masks a halt the operator still needs to recover from. A worktree left by an interrupted job (§ 13) is collected by the next hourly sweep.

---

## 15. `external_dirs` — externally-sourced working directories

A repository whose working directories are partly untracked declares them across both settings layers. The split follows what travels: the list is a property of the project and rides along with every clone; the location is a property of the machine.

Tracked `lazy.settings.json`:

```json
{
  "external_dirs": {
    "_version": 1,
    "paths": ["Data", "-Inbox", "-config"]
  }
}
```

Gitignored `lazy.settings.local.json`:

```json
{
  "external_dirs": {
    "root": "~/box/Project",
    "declined": false
  }
}
```

| Field | Layer | Meaning |
|---|---|---|
| `paths` | tracked | Repo-relative paths sourced from outside the repository. |
| `root` | local | Absolute path the declared paths are linked from on this machine. `~` and `$VAR` expand on read; a relative value is anchored to the repository root, never to the reading process's working directory. |
| `declined` | local | Records that the operator chose not to configure a source, so install never re-asks. |

Each declared path resolves to `<root>/<path>`. A declared entry that climbs out of the repository (`../…`) is dropped on read: the list is tracked and travels with every clone, while repair creates directories and plants symlinks, so only paths the repository contains are ever acted on.

A path is diagnosed as one of `ok`, `missing`, `dangling`, `wrong_target`, `not_a_symlink`, `source_missing`, or `unconfigured`. Exactly three are repaired by re-linking — `missing`, `dangling`, and `wrong_target`, and the last two only while the source exists. `ok` is already correct and left `unchanged`; `not_a_symlink`, `source_missing`, `unconfigured`, and a `dangling` link whose source is gone are reported to the operator and left untouched. Real content occupying a declared path is never removed. A repair the filesystem refuses is reported like any other unrepairable state, with the reason appended to the observed status, and the remaining paths are still repaired.

Alongside the status, each declared path carries an ignore verdict: `ignored`, `dir_only`, or `absent`. The distinction exists because a repaired slot holds a symlink, which git classifies as a file, while the ordinary `.gitignore` form for a working directory (`Data/`) matches directories only — so a repository whose ignore rules look complete still sees every linked path, its tree is dirty, and the daemon halts on its first tick. `dir_only` names exactly that case and is fixed by adding the anchored slashless line (`/Data`) next to the existing one, never by replacing it; `absent` means no rule covers the name in any form. Install proposes the missing lines after the repair and appends them only with the operator's confirmation, since `.gitignore` is tracked; audit reports the two cases separately and `lazy-core.autocheckup` reports rather than applies.

An absent or empty section is the default and changes no behaviour. Four consequences of a non-empty section:

- The expert sandbox must grant the location each declared slot points at, not the slot itself (§ 11, *Filesystem sandbox*). `sandbox-sync` derives those locations from the planted symlinks, so it runs after the repair, and `sandbox-audit` catches a source root that moves later.

- An `inbox` routine whose `inbox_dir` is declared and does not resolve fails its tick with `exit = -1` and the error tag `external_dir_broken: <path>`, which folds into the routine's own `routine:<name>` incident and carries the metric label `reason="external_dir_broken"`. An **undeclared** missing inbox stays a silent idle tick, unchanged.
- `daemon.run_here` is where the second daemon is refused, and it must name both halves of the answer. See *The run-here gate* below.
- Install refuses to put a supervisor on a checkout whose inbox another daemon on this host already drives, and skips the supervisor, sandbox, and metrics steps entirely rather than installing them and reporting afterwards.

**The inbox-ownership halt is not gated on this section.** Every daemon checks at startup whether another checkout on the host resolves an inbox routine to the same physical directory, including a repository that declares no external directories at all — the collision is reachable through any symlink, not only a declared one. Where it fires the condition is real: two daemons over one inbox import every document twice.

That halt is symmetric and permanent. Both checkouts raise it at their own next start, and removing the stray supervisor unit does not release the survivor — the halt is persisted state, and only a dirty-tree halt auto-clears. Decide which checkout drives the inbox, take the other out of its project's `daemon.run_here`, then run `/lazy-runtime.recover` in the one that should keep going. The check runs once per daemon start, so a collision created while a daemon is already running is seen by the newly started daemon, not by the incumbent.

### The run-here gate

Nothing in this runtime reconciles two daemons driving one project. They duplicate every dispatch, overwrite each other's `last_run` ledger, and commit over each other. `daemon.run_here`, in the **tracked** settings file, is the single answer to which daemon is the real one, and the daemon itself enforces it at startup — not only the install that placed the supervisor, so a leaked or hand-copied unit cannot outlive the answer.

The value maps a hostname to the absolute path of the checkout that machine drives:

```json
"run_here": { "nexus": "~/lazy-runtime/Money" }
```

Both halves are load-bearing, and neither older shape is accepted:

- A boolean cannot say which machine answered it. A project reached from a second machine — a synced path, or an independent clone — reads the same `true` on all of them.
- A bare hostname cannot say which checkout. One machine commonly holds several checkouts of a project, a working copy alongside the one the daemon drives, and a hostname grants a daemon in each.

The key is matched against `hostname -s` lowercased; the value is matched against the checkout the process was started in, with `~` expanded and both sides resolved, so a symlinked path still matches. `{}` names nothing and no machine runs the daemon. The map is tracked rather than local because a gitignored overlay never reaches a machine that cloned the repository independently, which is exactly where a second daemon appears.

A daemon started anywhere the map does not name records a `daemon_error` incident with cause `run_here_denied` and exits non-zero. It raises no halt block: `.runtime/` is shared by every machine reaching a synced checkout, and a halt written there by a machine with no claim would stop the daemon that does have one.
