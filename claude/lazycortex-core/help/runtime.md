---
chapter_type: block
summary: Register, unregister, and recover routines in the per-repo serial daemon — five routine types keep the async team running in order; the recovery skill handles both dirty-tree and remote-sync halts.
last_regen: 2026-05-23
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

**`/lazy-routine.register`** is the entry point for adding a periodic background job to the daemon. It runs as a type-aware wizard that collects only the fields the chosen routine type needs, validates the result against a per-type schema, and enforces `<plugin>.<verb>` dot-namespace naming. Five types are available — `subprocess`, `inbox`, `schedule`, `git`, and `md-scan` — each covering a distinct shape of recurring work. Every type accepts the same two dispatch shapes: either a `command` list (spawn a subprocess) or an `expert + request` pair (queue a job to a named expert in the repo or, with the `@<repo>` suffix, in a remote repo registered in `lazy.settings.json`). The skill refuses to overwrite an existing routine unless you pass `--force`.

**`/lazy-routine.unregister`** removes a named routine from the registry and is idempotent — calling it on a name that does not exist is an INFO, not an error. One routine is protected: `lazy-expert.pump`, the built-in job that drains the expert queue. Removing it requires `--force` and surfaces a warning that expert jobs will stop processing until the routine is re-registered or `/lazy-core.install` is re-run.

**`/lazy-runtime.recover`** handles daemon halts. The daemon halts in two distinct families of situations: a dirty working tree (a routine or expert left uncommitted changes) and a failed remote sync (the daemon's pre- or post-tick git pull or push hit an unrecoverable state). The skill reads the halt context from `.runtime/state.json`, surfaces which routine triggered the halt and — for dirty-tree halts — which paths are dirty, then guides you through the appropriate fix and clears the halt atomically once the precondition holds.

## How they work together

Routine management has a natural lifecycle. You run `/lazy-routine.register` once — typically as part of your plugin's install step — and the daemon picks up the new entry on its very next cycle without a restart. The wizard collects the type-specific fields, validates against the per-type schema, and if the routine type is `inbox` also checks whether the working directory is gitignored (an unignored inbox path dirties the tree on every cycle and triggers repeated halts — the wizard offers to add it to `.gitignore` on the spot).

The five types cover the common shapes of background work. `subprocess` runs any shell command on a fixed interval — use it for scripts, CLI tools, or any periodic task that does not need expert routing. `inbox` watches a directory and processes each file once: with an `expert + request` shape the daemon moves each file into job staging; with a `command` shape the file stays in the inbox until the consumer removes it. `schedule` takes a standard five-field cron expression and fires once per boundary — use it for calendar-driven tasks like nightly backups or weekly audits. `git` polls a remote branch for new commits, new files, changed files, deleted files, or renamed files and fires once per match — use it for CI-like reactions to upstream changes. `md-scan` scans vault-relative glob patterns, filters the matching markdown files by frontmatter key-value pairs, and fires once per match without moving the files — use it for processing in-place request queues tracked in git, such as design-request or review-request notes.

Every type's dispatch shape is an EITHER/OR. `command` spawns a subprocess; `expert + request` queues a job. For cross-repo dispatch, the `expert` field accepts an `<expert>@<repo>` suffix (e.g. `designer@my-design-repo`) — the daemon resolves the target repo from `lazy.settings.json` and routes the job there. The dispatch shape is the same regardless of routine type, so switching from a local expert to a cross-repo expert is a single field change.

When a routine is no longer needed, you run `/lazy-routine.unregister <name>` and the daemon drops it from the schedule immediately. If you want to change a routine's parameters without unregistering and re-registering, run `/lazy-routine.register <name> --force` to overwrite in one step.

The halt-and-recover path is a separate concern. When the daemon halts, `/lazy-runtime.recover` reads `.runtime/state.json` and surfaces the context: which routine triggered the halt (`triggered_by`), which expert and job were involved if applicable, the halt reason, and for dirty-tree halts the list of dirty paths.

For `uncommitted_changes` halts — the most common case — you have four options: `commit` keeps the dirty changes permanently (you supply the message); `stash` tucks them into a git stash you can restore later with `git stash pop`; `discard` throws them away irreversibly; and `abort` leaves everything as-is and exits, keeping the daemon halted so you can investigate. Once cleanup produces a clean tree the skill clears the `daemon_halted` block and the daemon resumes. If the tree is still dirty after cleanup the skill reports `still-dirty` without clearing the halt — run `git status` manually, resolve, and re-invoke `/lazy-runtime.recover`.

For remote-sync halts (`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`) the daemon cannot safely resolve the situation automatically. The skill surfaces reason-specific guidance describing what happened and how to repair it by hand: for a diverged branch you inspect with `git log` and choose whether to rebase, merge, or reset; for a failed push you try the push by hand and read the error; for an unreachable remote you check network and VPN. After you have repaired the situation, you confirm in the wizard and the skill clears the halt block. Confirming runs no git commands itself — the next daemon tick re-evaluates the actual git state.

## Common adjustments

- **Change a routine's configuration** — run `/lazy-routine.register <name> --force` to overwrite in one step, or run `/lazy-routine.unregister <name>` first and then re-register with the new parameters.
- **Remove `lazy-expert.pump`** — only do this if you are intentionally disabling expert job processing. Pass `--force` to `/lazy-routine.unregister lazy-expert.pump`. Run `/lazy-core.install` to restore it.
- **Recover without losing changes** — pick `stash` in the `/lazy-runtime.recover` wizard. Your dirty changes land in a git stash you can restore later with `git stash pop`. Pick `commit` if you want to keep them permanently.
- **Investigate before cleaning up** — pick `abort` in the `/lazy-runtime.recover` wizard. The daemon stays halted and no changes are made; run `git status` to inspect the dirty paths, then re-invoke `/lazy-runtime.recover` when you are ready.
- **Check daemon halt status before recovering** — inspect `.runtime/state.json` directly to confirm halt state, read the halt reason and `dirty_paths`, and identify which routine or expert triggered the halt (`triggered_by`, `expert`, `job_id`).
- **Recover from a remote-sync halt** — read the reason-specific guidance the skill surfaces, repair the git state by hand (rebase, merge, reset, re-push, fix network), then confirm in the wizard. If the halt re-fires on the next daemon tick, the underlying issue was not fully resolved — reinspect with `git fetch origin <branch>; git log --oneline HEAD origin/<branch>` and address the actual cause.
- **Narrow an `md-scan` to specific frontmatter states** — the `frontmatter_filter` field accepts a dict of key-to-value mappings; `null` matches files where the key is absent entirely, so `{"request_status": [null, "draft"]}` catches both new files and in-progress ones.
- **Route a routine's jobs to a remote repo's expert** — use `<expert>@<repo>` in the `expert` field when registering. The target repo must be registered in `lazy.settings.json` and reachable from the daemon's working directory.

## Runtime lifecycle

## See also

- [install-and-audit](install-and-audit.md) — Bootstrap the daemon via `/lazy-core.install`, which writes the `lazy-core.runtime` block and optionally sets up a launchd/systemd supervisor.
- [experts](experts.md) — The async expert team whose jobs are drained by the `lazy-expert.pump` routine this block manages.
- [setup-runtime](walkthroughs/setup-runtime.md) — Bootstrap the per-repo serial daemon so the async expert team has an executor.
- [setup-routine](walkthroughs/setup-routine.md) — Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
