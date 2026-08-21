---
name: lazy-spec.drive
description: "Use when the operator wants to drive one spec asset through its ladder by hand, in a single continuous session, with no runtime daemon acting on this checkout — `/lazy-spec.drive <asset-note-path>`. Reads `lazy-spec.coordination-playbook.md`, the same law `spec.coordinator` follows under the daemon, and drives the identical ladder locally: the operator speaks a word, the skill translates it into the gesture (tick, question-answer, command) ON THE OPERATOR'S BEHALF — never its own decision — commits it, wakes the coordinator via the same CLI the daemon's git-watch routine uses, and pumps whatever expert jobs result to completion with the local manual pump. Refuses to start while a live daemon could act on the same checkout."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# lazy-spec.drive

The no-daemon session orchestrator for the spec system (taskdoc `lazycortex-specs.optional-plan-and-auto-implementation.md` § 8; playbook trigger 7 / mode 5 "Drive-hook"). It drives exactly ONE asset through the S0..S5 ladder on a checkout where the runtime daemon is not acting — every gesture that would normally reach `spec.coordinator` as a pushed-and-pulled commit from a separate daemon checkout instead lands directly in this checkout and is dispatched synchronously, in the same session. The skill never decides the ladder itself: it is a thin translator from the operator's spoken word to the exact gesture an operator would make in daemon mode (a checkbox tick, a `[!question]` answer, a `# Coordinator commands` line), then drives the same `coordinator-dispatch` CLI and the same primitive verbs the daemon's routines call.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered phases. The executing agent MUST NOT skip, merge, reorder, or silently omit any phase. To make dropped phases structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per phase below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Resolve asset + preflight`
   - `Phase 2 — Resume: settle outstanding state`
   - `Phase 3 — Drive the dialog loop`
   - `Phase 4 — Close the session`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the phase's logic AND produced an outcome word for it".
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above.

## The drive loop (used by Phases 2 and 3)

One named subroutine, invoked after every gesture and once on entry (Phase 2's resume). It mirrors, in one session, what the daemon's two routines (`lazy-spec.coordinator-watch` git-watch, `lazy-spec.gate-tick` md-scan) do over many ticks:

```
repeat up to 20 times (ponytail: fixed ceiling — a real ladder settles in a handful of
                        iterations; a run that still hasn't converged at 20 is a bug to
                        report, not a loop to keep spinning):
  1. Bash(lazycortex-specs gate-tick "<repo-relative asset-note-path>")
     — clears a just-finished job's active_job / coordinator_job marker in the runtime
       sidecar, runs the structural note-check. Mirrors the daemon's lazy-spec.gate-tick worker.
  2. Bash(lazycortex-specs coordinator-dispatch "$(python3 -c 'import json,sys; print(json.dumps({"path": sys.argv[1]}))' "<repo-relative asset-note-path>")")
     — wakes spec.coordinator through the SAME trigger-resolution logic the daemon's
       git-watch routine uses (reads git log on this checkout; no push/pull needed —
       the commit already landed here). Parse the JSON action field.
  3. If action is "noop" or "dispatch-stale": the ladder has settled — stop the loop.
  4. Otherwise (`action == "dispatched"`) a fresh job was queued — drain it:
       while Bash(lazycortex-core expert-pump-once) reports processed > 0: repeat.
       (Parses "experts=N processed=P cleaned=C" from stdout; a bounded drain, same
       ceiling as the outer loop — 20 pump calls without processed=0 is a bug.)
  5. Go back to step 1 — a job that just finished may have hung a fresh checkbox or
     opened a document's review, which needs its own gate-tick + coordinator-dispatch
     pass to reconcile.
```

Every commit either loop step produces lands under a `@bot.` identity already (gate-tick as `lazy-spec.gate-tick@bot.invalid`, coordinator-dispatch's own job-queued commit as `lazy-spec.coordinator-watch@bot.invalid`, the coordinator's own pen as `spec.coordinator@bot.invalid`) — none of this needs the operator's git identity; only the GESTURE that kicks the loop off (Phase 3) does.

## Phase 1 — Resolve asset + preflight

**Resolve the asset note.** `$ARGUMENTS` names the asset's status folder-note — a repo-relative path (`specs/products/<product>/features/<slug>/<slug>.md`) or a bare `<category>/<slug>` shorthand. For the shorthand, `Glob("**/<slug>/<slug>.md")` under the vault's spec content root (`spec.vault_root` in `.claude/lazy.settings.json`, default `specs/`) and pick the match whose parent dir name matches `<category>`'s folder. `Read` the result and confirm `spec_role: status` in frontmatter — refuse (outcome `not-a-status-note`) otherwise. With no argument at all: `Glob` every status note under the content root, `Read` each frontmatter, list those with `spec_released` false and `spec_cancelled` false; if the list is short enough to offer, `AskUserQuestion` with one option per asset (label = product/category/slug); otherwise print the count and ask the operator to re-invoke naming a path — never guess. Outcome: `asset-resolved` or `no-asset-picked`.

**Derive `LAZYCORTEX_PLUGIN_DIRS` for this session's own CLI calls.** `coordinator-dispatch` internally subprocesses `lazycortex-core dispatch-job` via the `$LAZYCORTEX_PLUGIN_DIRS` walk (the blessed cross-plugin CLI contract) — with the var unset it raises `lazycortex-core CLI not resolvable`, not a soft failure. Export it before any other Bash call this session makes to these CLIs, mirroring the daemon's own precedence (`runtime_daemon.set_plugin_dirs` / `expert_preflight._derive_plugin_dirs`): dev-vault sources under `<repo>/claude/*/.claude-plugin/plugin.json` first (when this checkout IS the lazycortex dev vault), then the latest cached version per plugin under `~/.claude/plugins/cache/*/<plugin>/<version>/`.

```
Bash(export LAZYCORTEX_PLUGIN_DIRS=$(python3 -c "
import os
from pathlib import Path
dirs = []
dev = Path('.').resolve() / 'claude'
if dev.is_dir():
    for entry in sorted(dev.iterdir()):
        if (entry / '.claude-plugin' / 'plugin.json').is_file():
            dirs.append(str(entry.resolve()))
cache = Path.home() / '.claude/plugins/cache'
if cache.is_dir():
    for registry in sorted(cache.iterdir()):
        if not registry.is_dir(): continue
        for plugin in sorted(registry.iterdir()):
            if not plugin.is_dir(): continue
            versions = [v for v in plugin.iterdir() if v.is_dir()]
            if not versions: continue
            latest = sorted(versions, key=lambda v: v.name, reverse=True)[0]
            r = str(latest.resolve())
            if r not in dirs: dirs.append(r)
print(os.pathsep.join(dirs))
"))
```

This is a session-local shell export (Bash tool state persists for the session's cwd/env within this skill's run) — every subsequent `lazycortex-specs` / `lazycortex-core` Bash call in this skill inherits it. If a downstream call still fails with `agent not found in dev plugin: ... cache/.../<version>/agents/<x>.md`, the installed plugin cache is behind the source that shipped this agent — see Failure modes.

**Daemon-liveness preflight.** Refuse to start while a daemon could act on this same checkout — its clean-tree invariant would conflict with this skill's own uncommitted state, and a coordinator job dispatched twice (once by it, once by this skill) races. Reuse `lazy-core.audit`'s D7 three-signal check (any one passing = a daemon is live):

1. `Bash(pgrep -f bin/runner 2>/dev/null && echo running || echo stopped)`
2. `Bash(launchctl list com.lazycortex.runtime.$(basename "$PWD") 2>/dev/null | grep -q '"PID"' && echo running || echo stopped)` (macOS; skip silently on another platform)
3. Newest `.logs/lazy-core/runtime/*.jsonl` mtime within `5 × max(routine polling_interval_sec)` (default 300s when unavailable).

Any signal `running`/`ok` → refuse: print which signal fired and that the daemon must be stopped (or this checkout removed from `daemon.run_here`) before driving by hand; outcome `refused-daemon-live`. All three `stopped`/`stale`/skipped → proceed; outcome `daemon-clear`.

## Phase 2 — Resume: settle outstanding state

Re-running this skill on an asset MUST resume, never blindly restart. `Read` the note's current frontmatter (`spec_halted`, `spec_cancelled`, the five gates), run `Bash(lazycortex-specs note-check <asset-note>)` for its `job_markers` block (the two job markers live in the runtime sidecar, not in the note), and `Bash(git status --porcelain -- <spec content root>)` for anything left uncommitted by a prior interrupted session.

Run **the drive loop** once, unconditionally — this catches a job that finished while nobody was watching (a stale `active_job` / `coordinator_job` marker) and lets the ladder settle before the operator sees anything. `spec_cancelled: true` still runs the loop (gate-tick/coordinator-dispatch are read-first and no-op safely on a cancelled asset) but the render below says so plainly.

Render the current state to the operator: `# Status brief`, every hung `[!gate] <Label>` checkbox block under `# Gates`, every unticked `[!question]` callout, a non-empty `# Coordinator commands` section, and the `git status --porcelain` dirty-path list if non-empty (this is the operator's own prior manual edits still awaiting a commit — see Phase 3's commit option). Outcome: `resumed`.

## Phase 3 — Drive the dialog loop

Repeat until the operator says stop:

**Build the menu from current state**, `AskUserQuestion` with one option per row (never a bulk prose list):

- One option per hung checkbox block: "Tick `<Label>`".
- One option per option under each unanswered `[!question]` callout.
- "Add a Coordinator command" — a follow-up free-text question for the command line.
- "Commit accumulated changes" — only offered when `git status --porcelain` on the spec content root is non-empty (the operator's own hand-edits made outside this tool between rounds, per taskdoc § 8's no-commit-until-said phase).
- "Stop driving this asset" — always offered, ends Phase 3.

**Translate the chosen word into the gesture** — the tick/answer/command is the OPERATOR's decision (they picked the menu row); this skill only performs the mechanical edit on their behalf, exactly as an operator's own hand in daemon mode would:

- **Tick a checkbox** — `Edit` the block's `- [ ] <Label>` line to `- [x] <Label>` in `# Gates`. Commit with the ambient (non-bot) git identity — `Bash(git commit -m "lazy-spec.drive: tick <Label> on <asset-slug>" -- <asset-note-path>)`, pathspec-scoped to the note only. Before ticking a box whose dispatch reads `design.md` / `architecture.md` (per the checkbox table in `lazy-spec.coordination-playbook.md` Ch. 3), the operator may run `/lazy-spec.sync-with-code <asset>` first — its asset mode is an available pre-step to check those docs against current code before trusting them.
- **Answer a question** — `Edit` the chosen option's `- [ ]` to `- [x]` under the `[!question]` callout. Commit the same way: `lazy-spec.drive: answer <question-summary> on <asset-slug>` -- `<asset-note-path>`.
- **Add a command** — `Edit` a new line into the (protected, but operator-owned-by-convention) `# Coordinator commands` section. Commit: `lazy-spec.drive: command "<text>" on <asset-slug>` -- `<asset-note-path>`.
- **Commit accumulated changes** — show the dirty pathspec, ask the operator to confirm (or narrow) it, then `Bash(git commit -m "<operator-supplied or default message>" -- <confirmed pathspec>)`. New untracked files need `git add -N <path>` first (registers the path, stages no content) before the pathspec commit picks them up.

**Run the drive loop** after every gesture, then re-render the refreshed state (same fields as Phase 2's render) before asking the next question.

**Stop** ends the loop with outcome `driving-stopped`.

## Phase 4 — Close the session

Final `Bash(git status --porcelain -- <spec content root>)`. Non-empty → warn plainly: this checkout must not run the daemon (or have `daemon.run_here` point at it) until everything here is committed — its clean-tree invariant would halt on exactly this state. Print the final `# Status brief`. Outcome: `closed-clean` or `closed-dirty`.

**Branch check.** This session's manual `expert-pump-once` calls (the drive loop, step 4) run with none of the daemon's own per-iteration `_git_pre` safety net — an interrupted pump mid-`workspace: branch` job can leave this checkout on the job's branch with nothing to restore it (`lazy-core.runtime-schema.md`'s "Safety net for a claimant killed mid-job" describes the daemon-only case; this session has no equivalent). `Bash(git rev-parse --abbrev-ref HEAD)`; compare against `daemon.git.base_branch` in `.claude/lazy.settings.json` when configured. Match (or `base_branch` unset) → outcome `branch-clean`. Mismatch → `Bash(git checkout <base_branch>)`; success → outcome `branch-restored`; failure → warn plainly that the checkout is stranded on the job branch and must be resolved by hand before the daemon (or another drive session) touches it, outcome `branch-stranded`.

## Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.drive/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.drive)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the `$ARGUMENTS` asset path, or `none`). Body: `# lazy-spec.drive` heading, then `## Actions` (one line per gesture translated and per drive-loop settle, with the resulting action word) and `## Result` (`closed-clean` / `closed-dirty` / `refused-daemon-live` / `no-asset-picked` + one-line summary).

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **`lazycortex-core CLI not resolvable: $LAZYCORTEX_PLUGIN_DIRS yields no match`** — Phase 1's export step did not run, or found no dev-vault sources and no plugin cache → re-run Phase 1's export, or confirm `~/.claude/plugins/cache/*/lazycortex-core/` exists (install/update the plugin if not).
- **`agent not found in dev plugin: <ref> → .../cache/<plugin>/<version>/agents/<name>.md`** — the resolved `LAZYCORTEX_PLUGIN_DIRS` entry points at a cached plugin version that predates the agent this job needs (common right after a dev-vault-only change that hasn't been published yet) → when this checkout IS the dev vault that ships the agent, confirm Phase 1's derivation put the `claude/<plugin>/` source dir ahead of the cache entry for the same plugin; in a consumer checkout, update the plugin so its cache carries the agent.
- **The drive loop hits its 20-iteration ceiling without settling** — either a genuine ladder bug (report it, do not raise the ceiling to paper over it) or the asset is caught in a legitimate multi-round cascade (playbook Ch. 4) that outgrew one session's patience → re-invoke `/lazy-spec.drive` on the same asset; Phase 2's resume picks up exactly where the loop left off.
- **`refused-daemon-live`** — a live daemon owns this checkout → stop it (or drop this checkout from `daemon.run_here`) before driving by hand; per taskdoc § 8, going back to daemon mode after a drive session requires Phase 4 to report `closed-clean` first.
