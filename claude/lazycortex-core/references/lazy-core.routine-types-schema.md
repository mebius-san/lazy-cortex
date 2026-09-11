---
description: The five runtime routine types (`subprocess`, `inbox`, `schedule`, `git`, `md-scan`) and their per-type cfg shapes, dispatch sub-shapes, common optional keys, and the composite `filter` block.
---
# lazy-core.routine-types — routine types and their cfg shapes

§ 8 of `lazy-core.runtime-schema.md`, extracted and read on demand: open this file when registering, validating, or debugging a `routines[<name>]` entry — which fields a type requires, what the `filter` block accepts, and how `inbox` / `schedule` / `git` / `md-scan` each turn a tick into dispatched work. The daemon's own config block and lifecycle stay in the parent, and a `§ N` cross-reference below that names no file names a section of that parent.

## 8. Routine types

Each entry under `routines` may carry an optional `type` field. Default is `subprocess`. Allowed values + per-type shape:

| Type | Required fields | Optional fields |
|---|---|---|
| `subprocess` (default) | `interval_sec` | `timeout_sec` |
| `inbox` | `inbox_dir`, `interval_sec` | `filter`, `deferred_retry_sec`, `timeout_sec` |
| `schedule` | `cron` | `timeout_sec` |
| `git` | `branch`, `watch`, `interval_sec` | `repo_dir`, `remote`, `path_filter`, `filter`, `group_globs`, `timeout_sec` |
| `md-scan` | `paths`, `interval_sec` | `filter`, `timeout_sec`, `can_commit_in_repo` |

`command`, `expert`, and `request` are absent from both columns on purpose: they sit in every type's optional set, and the dispatch shape across them is enforced separately by `_validate_command_or_expert`. So **every** row above additionally requires EITHER `command` OR `expert` + `request`, never both, never neither — the § 3 contract, uniform across all five types.

Every type additionally accepts the common keys `type`, `priority`, `protocol` / `protocols`, `ignore_halt`, `hooks_enabled`, and `git_author` (plus the retired `isolate` / `allow_merge`, accepted but ignored) — `hooks_enabled` is the allow-list of lazycortex hook short names this routine's own subprocess may run (empty or absent silences all of them). `ignore_halt` lets a routine tick while the daemon is halted AND skips the post-tick working-tree check for it, so a routine that carries it must report its own failures.

`git_author` (`{name, email}`, the same shape as an expert entry's block) names the bot identity for any commits the routine's own subprocess makes: the daemon exports `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` into every command-shape spawn via `routine_subprocess_env`, same coverage as the pump gives expert jobs. Committer is deliberately untouched — both consumers of automatic-commit identity (loop-detect and the coordinators' operator-vs-bot check) read the author. Canonical form: `<routine-family>@bot.invalid` (the RFC 2606 `.invalid` TLD is undeliverable by construction). Absent key is not an error — the routine commits under the daemon process's identity, as before. Loop-detect collects `git_author.email` from routines and experts alike, so a deterministic routine cycling on its own diff halts the daemon the same way an expert does.

`can_commit_in_repo` (md-scan only, default `true`) is the routine-side override of the per-expert commit right described in `lazy-core.expert-runtime-schema.md`. An md-scan routine is in-place by contract — the consumer edits the scanned file where it lies — so its dispatched jobs get `true` and may write and commit in the target repository. Setting it to `false` opts one routine out: the job's `config.json` carries `false`, and the pump appends the foreign-execution no-commit clause to the spawn prompt, so that expert must leave the scanned document and every other working-tree file untouched and return its output as data in `response.json` for the dispatcher to apply (its own persona side-channels — `.memory/<self>/`, `.logs/` — stay allowed). The routine's value always wins: md-scan passes an explicit boolean, so the expert entry's own default is not consulted for these jobs. No other routine type reads the field, and none accepts it.

`paths` globs: a pattern containing `**` is matched full-path-anchored with `**` spanning any number of segments (including zero); a pattern without `**` keeps `PurePath.match` semantics (right-anchored, `*` never crosses `/`). In `**`-bearing patterns character classes like `[abc]` are treated as literal text (only `*` and `?` are wildcards); patterns without `**` keep full `PurePath.match` semantics.

Closed-set strict validation: unknown type, unknown field, missing required, or per-type custom constraint violation → `RoutineConfigError` at registration time. The daemon re-validates every entry each time it loads the registry, so an entry written by hand, seeded by an install skill, or left behind by a schema change is rejected on read rather than at first dispatch — see `lazy-core.state-schema.md` § 10.

**Common optional fields (any type):** `protocol: <ref>` or `protocols: [<ref>, ...]` — declares which protocol(s) the routine's dispatched jobs follow. The dispatcher resolves each ref via `reference_resolver.resolve(..., category="protocols", ...)` and threads the resolved paths through to each job's `config.json`. Protocols are routine-side, not expert-side — expert entries in `lazy.settings.json[experts]` do NOT carry a `protocol` field. See `lazy-core.expert-protocols-contract.md`.

**Retired worktree-isolation fields (any type):** `isolate` and `allow_merge` belonged to the retired routine-side worktree path. They are still ACCEPTED by validation (a consumer's config must not start failing over a dead flag) but ignored, with a stderr warning per occurrence; `lazy-core.doctor` / `lazy-core.autocheckup` offer the prune. Job-level isolation lives in `experts[<name>].workspace` instead — see `lazy-core.expert-runtime-schema.md` § Workspace.

### `inbox`

Scans `inbox_dir` each tick. The input file is never copied into the job bundle — only its **path** is passed, so the inbox is the single source of truth for the file (parity with `git` / `md-scan`, which also pass a path).

`command` sub-shape — spawn `command + [<absolute-path-to-file>]` per file (blocking, one at a time). The consumer command owns the file; the routine never removes it.

`expert + request` sub-shape — two passes per tick:

1. **Reconcile** finished work via `completed_dedup_jobs`: for every prior job keyed on an inbox path, if it **succeeded** (`outcome` ≠ `error`) drain the input (`unlink`, best-effort — the expert may have filed it away itself on success) and mark the bundle `CONSUMED`; if it **failed** leave the input parked — the bundle stays `DONE`-but-unconsumed so its dedup key keeps the file from re-dispatching. This is a **dead-letter**: the failed input sits in the inbox with its bundle's forensics retained for the operator to triage; it is not retried automatically (a crashed/`DEAD` job is the doctor's retry path, not this one). **Exception — a stale transient failure:** a bundle whose error `category` is `transient` (the spawn faulted, not the work) and that finished more than `TRANSIENT_RETRY_AGE_SEC` (1 h) ago is marked `CONSUMED` **without** draining the input, so pass 2 of the same tick re-dispatches the file. Retries repeat at that cadence for as long as the spawn keeps faulting. **Exception — a stale deferral:** a bundle the expert closed with `outcome: "deferred"` (the work ran, judged the input not actionable yet, and left it exactly as it found it) is likewise marked `CONSUMED` **without** draining once it is older than the routine's optional `deferred_retry_sec` (default `86400`, one day) — a deferral waits on something outside the system changing, typically an operator creating the record the work depends on, so its window is a day rather than the transient path's hour, and a routine widens it when its own dependency moves slower still.
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
