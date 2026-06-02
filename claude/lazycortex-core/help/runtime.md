---
chapter_type: block
summary: Register, unregister, and recover routines in the per-repo serial daemon — five routine types keep the async team running in order; the recovery skill handles both dirty-tree and remote-sync halts.
last_regen: 2026-06-02
diagram_spec:
  anchor: "Runtime lifecycle"
  request: "State diagram showing the daemon lifecycle: routines registered in lazy.settings.json feed the serial daemon loop; the daemon runs each routine in order per interval_sec or cron schedule; a dirty working tree triggers an uncommitted_changes halt; a failed remote sync triggers a git_pull_diverged / git_push_failed / git_remote_unavailable halt; /lazy-runtime.recover (commit/stash/discard/abort for tree halts; manual-fix + resume for remote-sync halts) cleans the precondition and resumes; unregister removes a routine from the loop."
source_skills:
  - lazy-routine.register
  - lazy-routine.unregister
  - lazy-runtime.recover
---
# Runtime daemon — routine management and recovery

The lazycortex-core runtime daemon is a per-repo serial loop. It reads the routine registry from `.claude/lazy.settings.json`, runs each entry in order according to its `interval_sec` or cron schedule, and repeats. Because routines execute one at a time, no two ever contend over the working tree or git state — the daemon is the single serializing authority for all background work in the repo.

Three skills manage that loop from the outside. `/lazy-routine.register` adds a named periodic job to the registry using a type-aware wizard that supports five routine types and two dispatch shapes. `/lazy-routine.unregister` removes a named routine cleanly and is idempotent. `/lazy-runtime.recover` is the escape hatch when the daemon halts: it reads the halt context, branches on the reason — dirty working tree or failed remote sync — walks you through the appropriate fix, and clears the halt so the daemon resumes on its next iteration.

## What's in this block

**`/lazy-routine.register`** is the entry point for adding a periodic background job to the daemon. It runs as a type-aware wizard that collects only the fields the chosen routine type needs, validates the result against a per-type schema, and enforces `<plugin>.<verb>` dot-namespace naming. Five types are available — `subprocess`, `inbox`, `schedule`, `git`, and `md-scan` — each covering a distinct shape of recurring work:

- `subprocess` — run any shell command on a fixed interval. Use it for scripts, CLI tools, or any periodic task that does not need expert routing.
- `inbox` — watch a directory and process each file once. With an `expert + request` dispatch the daemon moves each file into job staging; with a `command` dispatch the file stays in the inbox until the consumer removes it.
- `schedule` — fire once per cron boundary using a standard five-field cron expression. Use it for calendar-driven tasks like nightly backups or weekly audits.
- `git` — poll local HEAD for `new_commits`, `new_files`, `changed_files`, `deleted_files`, or `renamed_files` and fire once per match. Use it for CI-like reactions to changes in the working repo.
- `md-scan` — scan vault-relative glob patterns, filter matching markdown files by frontmatter key-value pairs, and fire in-place once per match. Use it for processing request-queue notes tracked in git, such as design-request or review-request documents.

Every type accepts the same two dispatch shapes: either a `command` list (spawn a subprocess) or an `expert + request` pair (queue a job to a named expert). For cross-repo dispatch, the `expert` field accepts an `<expert>@<repo>` suffix — the daemon resolves the target repo from `lazy.settings.json` and routes the job there. The skill refuses to overwrite an existing routine unless you pass `--force`.

**`/lazy-routine.unregister`** removes a named routine from the registry and is idempotent — calling it on a name that does not exist is an INFO, not an error. One routine is protected: `lazy-expert.pump`, the built-in job that drains the expert queue. Removing it requires `--force` and surfaces a warning that expert jobs will stop processing until the routine is re-registered or `/lazy-core.install` is re-run.

**`/lazy-runtime.recover`** handles daemon halts. The daemon halts in two distinct families: a dirty working tree (a routine or expert left uncommitted changes) and a failed remote sync (the daemon's pre- or post-tick git pull or push hit an unrecoverable state). The skill reads the halt context from `.runtime/state.json`, surfaces which routine triggered the halt — a routine name, `_git_pre` or `_git_post` for daemon-side remote-sync halts, or `lazy-expert.pump` for pump-internal halts — and for dirty-tree halts, which paths are dirty. It then guides you through the appropriate fix and clears the halt atomically once the precondition holds.

## How they work together

Routine management follows a natural lifecycle. You run `/lazy-routine.register` once — typically as part of your plugin's install step — and the daemon picks up the new entry on its very next cycle without a restart. The wizard collects type-specific fields, validates against the per-type schema, and for `inbox` routines also checks whether the working directory is gitignored. An unignored inbox path dirties the tree on every cycle and triggers repeated halts; the wizard offers to add it to `.gitignore` on the spot.

Switching dispatch shapes or routine types is a single step: run `/lazy-routine.register <name> --force` to overwrite in place, or run `/lazy-routine.unregister <name>` and re-register with the new parameters. When you no longer need a routine, run `/lazy-routine.unregister <name>` and the daemon drops it from the schedule immediately.

The halt-and-recover path is a separate concern. When the daemon halts, `/lazy-runtime.recover` reads `.runtime/state.json` and surfaces the context: which routine triggered the halt (`triggered_by`), which expert and job were involved if applicable, the halt reason, and for dirty-tree halts the list of dirty paths.

For `uncommitted_changes` halts — the most common case — you choose one of four cleanup modes:

- `commit` — keeps the dirty changes permanently (you supply the message).
- `stash` — tucks them into a git stash you can restore later with `git stash pop`.
- `discard` — throws away every dirty change irreversibly.
- `abort` — leaves everything as-is and exits, keeping the daemon halted so you can investigate.

Once cleanup produces a clean tree the skill clears the `daemon_halted` block and the daemon resumes. If the tree is still dirty after cleanup the skill reports `still-dirty` without clearing the halt — run `git status` manually, resolve, and re-invoke `/lazy-runtime.recover`.

For remote-sync halts (`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`) the daemon cannot safely resolve the situation automatically. The skill surfaces reason-specific guidance and asks you to repair the state by hand before confirming resume:

- `git_pull_diverged` — inspect with `git log --oneline HEAD origin/<branch>`, then rebase, merge, or reset to reconcile the diverged histories.
- `git_push_failed` — try `git push origin <branch>` manually to read the underlying error (auth failure, branch protection, push race).
- `git_remote_unavailable` — check network and VPN, then run `git fetch origin <branch>` to confirm reachability before resuming.

After you confirm, the skill clears the halt block. It runs no git commands itself — the next daemon tick re-evaluates the actual git state. If the halt re-fires immediately, the underlying issue was not fully resolved; reinspect and address the root cause before re-running `/lazy-runtime.recover`.

## Common adjustments

- **Change a routine's configuration** — run `/lazy-routine.register <name> --force` to overwrite in one step, or run `/lazy-routine.unregister <name>` first and then re-register with the new parameters.
- **Remove `lazy-expert.pump`** — only do this if you are intentionally disabling expert job processing. Pass `--force` to `/lazy-routine.unregister lazy-expert.pump`. Run `/lazy-core.install` to restore it.
- **Recover without losing changes** — pick `stash` in the `/lazy-runtime.recover` wizard. Your dirty changes land in a git stash you can restore later with `git stash pop`. Pick `commit` if you want to keep them permanently.
- **Investigate before cleaning up** — pick `abort` in the `/lazy-runtime.recover` wizard. The daemon stays halted and no changes are made; run `git status` to inspect the dirty paths, then re-invoke `/lazy-runtime.recover` when you are ready.
- **Check daemon halt status before recovering** — inspect `.runtime/state.json` directly to confirm halt state, read the halt reason and `dirty_paths`, and identify which routine or expert triggered the halt (`triggered_by`, `expert`, `job_id`).
- **Narrow an `md-scan` to specific frontmatter states** — the `filter` field accepts a composite filter block; `null` in the `in` list matches files where the key is absent entirely, so `{"frontmatter": {"request_status": {"in": [null, "draft"], "not_in": []}}}` catches both new files and in-progress ones.
- **Route a routine's jobs to a remote repo's expert** — use `<expert>@<repo>` in the `expert` field when registering. The target repo must be registered in `lazy.settings.json` and reachable from the daemon's working directory.
- **Halt re-fires immediately after resume** — if a remote-sync halt returns on the very next daemon tick, the underlying condition was not fully resolved. Run `git fetch origin <branch>; git log --oneline HEAD origin/<branch>` and address the actual cause before re-running `/lazy-runtime.recover`.

## Runtime lifecycle

```mermaid
%%{init: {'themeVariables':{'background':'transparent','transitionColor':'#000','transitionLabelColor':'#000','labelBackgroundColor':'#fff','edgeLabelBackground':'#fff','stateLabelColor':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','state':{'diagramPadding':5,'useMaxWidth':true}}}%%
stateDiagram-v2
  [*] --> idle

  idle --> running : routine registered

  running --> running : interval_sec or cron tick - execute next routine

  running --> uncommittedChangesHalt : dirty working tree detected

  running --> gitPullDivergedHalt : remote sync diverged

  running --> gitPushFailedHalt : push rejected

  running --> gitRemoteUnavailableHalt : remote unreachable

  uncommittedChangesHalt --> running : lazy-runtime.recover - commit or stash or discard

  uncommittedChangesHalt --> idle : lazy-runtime.recover - abort

  gitPullDivergedHalt --> running : lazy-runtime.recover - manual-fix then resume

  gitPushFailedHalt --> running : lazy-runtime.recover - manual-fix then resume

  gitRemoteUnavailableHalt --> running : lazy-runtime.recover - manual-fix then resume

  running --> idle : routine unregistered - loop empty

  idle --> [*]

  style idle fill:#1e3a5f,stroke:#4a90e2,color:#fff
  style running fill:#1e5f3a,stroke:#4ae290,color:#fff
  style uncommittedChangesHalt fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px
  style gitPullDivergedHalt fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px
  style gitPushFailedHalt fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px
  style gitRemoteUnavailableHalt fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px
```


## See also

- [install-and-audit](install-and-audit.md) — Bootstrap the daemon via `/lazy-core.install`, which writes the `lazy-core.runtime` block and optionally sets up a launchd/systemd supervisor.
- [experts](experts.md) — The async expert team whose jobs are drained by the `lazy-expert.pump` routine this block manages.
- [setup-runtime](walkthroughs/setup-runtime.md) — Bootstrap the per-repo serial daemon so the async expert team has an executor.
- [setup-routine](walkthroughs/setup-routine.md) — Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
