---
name: lazy-core.migrate
description: "Run when the operator asks to migrate consumer state after a plugin update; also the closing stage of `/lazy-core.setup`. Applies every migration step the enabled plugins ship that still applies to this repository, without asking questions, commits each applied step on its own, and stamps the migrated version per plugin."
lazy_setup_phase: post-install
lazy_setup_last: true
---
# Migrate consumer state

Brings a repository's state in line with the installed plugins after `/plugin update`. Each plugin ships ordered step files under `migrations/`; the core `migrate-plan` verb picks the ones that still apply there, this skill runs them in order, commits each applied step by itself, and records per plugin the version whose steps are all applied. It asks no questions: every step is deterministic, and a step that cannot run is reported, never negotiated. Run it after the install chain, which `/lazy-core.setup` does by placing it last in its post-install phase.

## Arguments

- `<repo-root>` — the absolute root of the repository to migrate. Without it, the root of the repository the session runs in.
- `--snapshot <file>` — the before-run snapshot `/lazy-core.setup` (or the `lazy-core.autosetup` agent) took before the install chain wrote anything. With it, the files the install chain changed are committed before the first step runs; without it, the skill commits only what its steps write.

Every command below names `<repo-root>`: git runs as `git -C "<repo-root>" …`, the core verbs take `--repo "<repo-root>"`, a removed file is `"<repo-root>/<path>"`. The skill never relies on its working directory and never `cd`s.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Plan`
   - `Phase 2 — Apply steps`
   - `Phase 3 — Stamp`
   - `Phase 4 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`up-to-date`, `skipped`, `none`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Plan

1. Resolve `<repo-root>` once: the `<repo-root>` argument when given, else the line `Bash(git rev-parse --show-toplevel)` prints. A non-zero exit ends the plan with `failed: repo-root: <stderr>`; Phase 2 and Phase 3 take the outcome `skipped`, and the run goes to Phase 4.
2. Run exactly:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" migrate-plan --repo "<repo-root>")
   ```

3. A non-zero exit ends the plan: the outcome is `failed: <reason>` when stdout carries `{"status": "error", "reason": ...}`, and `failed: <stderr>` when stdout carries no JSON (an argument error prints its usage on stderr). Phase 2 and Phase 3 take the outcome `skipped`, and the run goes to Phase 4.
4. Otherwise the output is `{"plugins": {<plugin>: {...}}}`. Per plugin keep:
   - `applicable` — the steps to run, already in run order; each entry carries `path` (the absolute step file), `number`, `slug`, `since`, and `writes` (repo-relative globs, the spec root already expanded);
   - `skipped` — steps left out, with `reason` (`stamped`, `superseded`, `not-applicable`, the last with a `detail` such as `no-spec-territory` when the repository has no spec catalog); they are not run and not listed in the report;
   - `invalid` — step files, stamps, or conditions that could not be read or judged, with `reason`;
   - `installed_version` — the version the installed plugin records, or null.
5. Name each applicable step `<NNN>-<slug>`, `<NNN>` being `number` padded to three digits; this is the step file's own basename without `.md`.

Outcome: `up-to-date` when no plugin has an `applicable` step and no plugin has an `invalid` entry (Phase 2 and Phase 3 then take `skipped`); otherwise `planned: <N> steps across <P> plugins, <I> invalid`; or `failed: <reason>`.

## Phase 2 — Apply steps

Plugins in the order the plan lists them, and within a plugin the steps in `applicable` order. Every step gets exactly one outcome: `applied`, `not-applicable`, `failed: <reason>`, or `blocked`. The `failed` reasons are `dirty: <paths>`, `plugin-root: <stderr>`, `step <k>: <stderr>`, `not-done: <condition>`, `outside-writes: <paths>`, and `commit-refused: <message>`. Once a step of a plugin is `failed`, every later step of the same plugin is `blocked` without being read; steps of other plugins still run. A `not-applicable` step blocks nothing: the plugin's next step runs as usual.

Every migration verb a step runs, and every verb a `verb` predicate names, answers with one exit code:

| Exit | Meaning |
|---|---|
| 0 | the verb did its work, or, as a predicate, the condition holds |
| 1 | nothing to do: the work is already done, or, as a predicate, the condition does not hold |
| 2 | the verb itself broke and could not judge or act |
| 3 | not applicable here: a precondition the step needs is absent in this repository (a feature not configured, say), so there is nothing it can do |

As a predicate, exit 3 leaves the condition unmet, exactly as exit 1 does.

For one step, `<writes>` below stands for its `writes` globs, each passed as its own quoted pathspec in glob form, `":(glob)<glob>"`.

Every status call the skill reads uses `--porcelain=v1 -z`: entries are separated by NUL, and each entry is a two-letter status `XY`, a space, and the repo-relative path exactly as on disk, never quoted or escaped. That path is passed as one quoted argument to `git -C "<repo-root>" restore`, `git -C "<repo-root>" add -N` and `git -C "<repo-root>" commit` unchanged, and to `rm` as `"<repo-root>/<path>"`. In an entry, `??` is a new file, ` D` a deleted file, anything else a modified file.

**Install-chain writes, before the first step.** Without `--snapshot`, or when no plugin has an applicable step, the install-chain outcome is `skipped`. Otherwise the install chain has just rewritten files a step may also write, and a step would refuse them as dirty; they are committed first:

- Run `Bash(test -f "<snapshot>")`. A non-zero exit is the install-chain outcome `failed: snapshot-missing: <snapshot>`, and the two bullets below are not run; the steps still run, and those whose `writes` meet a file the install chain changed end `failed: dirty`.
- Run exactly:

   ```
   Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazy_setup.py" verify "<repo-root>" --snapshot "<snapshot>")
   ```

   `touched` lists every path dirty now that was clean in the snapshot — the install chain's writes; `new` repeats the untracked ones. A path dirty in the snapshot is the operator's work and is never in `touched`, even when `violations` names it because the install chain changed it too; it stays uncommitted, and a step whose `writes` meet it ends `failed: dirty`.
- An empty `touched` is the outcome `none`. Otherwise register each `new` path, one call per path, `Bash(git -C "<repo-root>" add -N -- "<path>")`, then commit every `touched` path by name:

   ```
   Bash(git -C "<repo-root>" commit -m "chore(setup): install chain writes" -m "Lazy-Watch: skip" -- "<path>" "<path>" …)
   ```

   A commit that exits zero is the outcome `committed`. A refused commit is `failed: commit-refused: <message>`, quoted verbatim; the files stay in the tree, and the steps still run.

Then per step:

1. **Dirty check.** Run:

   ```
   Bash(git -C "<repo-root>" status --porcelain=v1 -z --untracked-files=all -- <writes>)
   ```

   Any output means the operator has uncommitted work where the step would write: the outcome is `failed: dirty: <paths>`, naming every path printed, and nothing is written. Empty output continues to the snapshot:

   ```
   Bash(git -C "<repo-root>" status --porcelain=v1 -z --untracked-files=all)
   ```

   Keep the set of paths it prints as the **before-snapshot**. Those paths are the operator's uncommitted work elsewhere in the tree; the skill never restores, removes, or commits any of them.
2. **Read.** `Read` the step file at `path`. It holds `## Why`, `## Steps`, and `## Done when`.
3. **Resolve the step's CLI.** A step runs verbs of its own plugin or of core, each through the interpreter as `"${LAZYCORTEX_PYTHON:-python3}" <cli> <verb> …`. Core's CLI is `"${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core"`. For a call against the step's own plugin CLI (the file `bin/lazycortex-<short>`, `<short>` being the plugin name without its `lazycortex-` prefix), resolve that plugin's root once per plugin:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" plugin-root <plugin> --cwd "<repo-root>")
   ```

   and append `bin/lazycortex-<short>` to the root it prints. A non-zero exit is `failed: plugin-root: <stderr>`, with nothing written.
4. **Run `## Steps`.** Execute the numbered steps in order, one command per `Bash` call, exactly as written apart from the CLI path resolved above and the `<repo-root>` placeholder, which stands for the resolved root, quotes kept. Never write a path outside `writes`, never ask the operator, never improvise a command the step does not name. A command that exits 3 ends the step with `not-applicable`: the rest of `## Steps` is not run and `## Done when` is not checked. A command that exits any other non-zero code ends the step with `failed: step <k>: <stderr>`, `<k>` being the step's number in `## Steps`.
5. **Check `## Done when`.** Verify every condition with read-only tools (`Read`, `Grep`, `Glob`, or the verb the condition names, `<repo-root>` substituted as in item 4). A condition that does not hold is `failed: not-done: <condition>`.
6. **Collect the step's changes.** Run both status commands from item 1 again, whatever items 3–5 ended in:
   - the `writes`-restricted one: since it printed nothing before the step, every path it prints now is the step's own change inside `writes` — the **inside paths**;
   - the unrestricted one: every path it prints that is not in the before-snapshot and not among the inside paths is a write outside `writes` — the **outside paths**.

   Any outside path makes the outcome `failed: outside-writes: <paths>`, naming every outside path, unless items 3–5 already recorded a `failed` reason, which then stands with the outside paths appended. A `not-applicable` step with an outside path becomes `failed: outside-writes: <paths>` too.
7. **Roll back a failed or not-applicable step.** When the step is `failed` or `not-applicable` and item 6 found inside or outside paths, undo exactly those paths, since none of them was dirty before the step: a modified or deleted path with `Bash(git -C "<repo-root>" restore --worktree -- "<path>")`, a new file with `Bash(rm "<repo-root>/<path>")`, one path per call. A before-snapshot path is never touched. The outcome stays the one already recorded, and a `not-applicable` step makes no commit.
8. **Commit an applied step.** For a step not already `failed` or `not-applicable`: when item 6 found no inside path and no outside path, the step changed nothing: the outcome is `applied` and no commit is made. Otherwise, with no outside path:
   - register each new inside path without staging its content, one call per path: `Bash(git -C "<repo-root>" add -N -- "<path>")`. No other `git add` is ever run;
   - commit every inside path by name, deleted ones included — never a glob, a directory, or `.`:

     ```
     Bash(git -C "<repo-root>" commit -m "chore(migrate): <plugin> <NNN>-<slug>" -m "Lazy-Watch: skip" -- "<path>" "<path>" …)
     ```

   The second paragraph is the `Lazy-Watch: skip` trailer, which keeps the commit out of every git routine's watch. A commit that exits zero makes the outcome `applied`. A commit the git guard or a hook refuses is `failed: commit-refused: <message>`, quoted verbatim, and the step is rolled back: each new inside path registered above leaves the index first, one call per path, `Bash(git -C "<repo-root>" restore --staged -- "<path>")`, then every inside path is undone exactly as item 7 undoes a failed step's paths. A before-snapshot path is never touched. The plugin's later steps are `blocked` as after any failure, the step is offered again on the next run, and the refusal is never rephrased around or bypassed.

Outcome: `install-chain: <committed | none | skipped | failed: <reason>>; applied: <A>, not-applicable: <N>, failed: <F>, blocked: <B>`, or `skipped` when Phase 1 ended `up-to-date` or `failed`.

## Phase 3 — Stamp

A plugin is stamped only when its plan had at least one applicable step, every one of them ended `applied` or `not-applicable`, its `invalid` list is empty, and its `installed_version` is not null. Every other plugin keeps its current stamp; a plugin with an `invalid` entry, a `failed` step, or a `blocked` step never gets one. Per plugin to stamp:

1. Run the dirty check on the stamp file:

   ```
   Bash(git -C "<repo-root>" status --porcelain=v1 -z --untracked-files=all -- .state/lazy-core.migrated.<plugin>.json)
   ```

   Any output is `failed: dirty: .state/lazy-core.migrated.<plugin>.json`, and the plugin is not stamped.
2. Run:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" migrate-stamp --repo "<repo-root>" --plugin <plugin> --version <installed_version>)
   ```

   A non-zero exit prints `{"status": "error", "reason": ...}` and is `failed: <reason>`.
3. Rerun the item 1 command. A `??` line means the stamp file is new: `Bash(git -C "<repo-root>" add -N -- .state/lazy-core.migrated.<plugin>.json)`. Then commit it:

   ```
   Bash(git -C "<repo-root>" commit -m "chore(migrate): <plugin> stamp <installed_version>" -m "Lazy-Watch: skip" -- .state/lazy-core.migrated.<plugin>.json)
   ```

   A refused commit is `failed: commit-refused: <message>`, quoted verbatim.

The per-plugin outcome is `stamped <installed_version>` or the `failed` reason.

Outcome: `stamped: <N>`, `none` when no plugin qualifies, or `skipped` when Phase 2 was `skipped`.

## Phase 4 — Report

One line per phase with its outcome word, then a table with one row per step Phase 1 planned, in run order, and one row per `invalid` entry:

```
Phase 1 — Plan: <outcome>
Phase 2 — Apply steps: <outcome>
Phase 3 — Stamp: <outcome>
Phase 4 — Report: reported

| Plugin | Step | Outcome |
|---|---|---|
| setup | install-chain writes | committed / none / skipped / failed: <reason> |
| <plugin> | <NNN>-<slug> | applied / not-applicable / failed: <reason> / blocked |
| <plugin> | <path> | invalid: <reason> |
| <plugin> | stamp | stamped <version> / failed: <reason> |
```

Then, in this order, each line only when it applies:

- At least one `failed: dirty: <paths>`: `Commit or clean <paths>, then re-run /lazy-core.setup.` — one line per dirty step, naming its paths.
- At least one `invalid` entry: `Plugin <plugin> has an unreadable migration file or stamp (<path>); it stays unstamped until the plugin ships a fix.`
- At least one `applied` step: `Restart open Claude Code sessions and the runtime daemon so they pick up the migrated state.`

A row missing from the table is a bug; do not render the report with gaps.

## Failure modes

- **`/lazy-core.migrate` reports `failed: dirty: <paths>`** — uncommitted work sits on paths the step rewrites, so it did not start; under `/lazy-core.setup` these are paths that were already uncommitted before the setup run, since the install chain's own writes are committed first → commit or discard the changes on those paths, then re-run `/lazy-core.setup`.
- **`/lazy-core.migrate` reports the install-chain writes `failed: commit-refused: <message>` or `failed: snapshot-missing: <file>`** — the files the install chain changed could not be committed before the steps, so steps writing them end `failed: dirty` → clear what the message names, commit or discard the install chain's changes, and re-run `/lazy-core.setup`.
- **`/lazy-core.migrate` reports a step `failed` and the plugin's later steps `blocked`** — a command in the step failed or its `## Done when` did not hold; the step's own changes were rolled back → fix what the reason names and re-run `/lazy-core.setup`; the plugin stays unstamped until every step ends `applied` or `not-applicable`.
- **`/lazy-core.migrate` reports a step `not-applicable`** — a command of the step exited 3: something the step needs is absent in this repository, such as a feature that is not configured; anything the step changed was rolled back, the plugin's later steps still ran, and the step does not keep the plugin from being stamped → nothing to fix; once the plugin is stamped, the step is not offered again, even if the missing piece is configured later.
- **`/lazy-core.migrate` reports `failed: outside-writes: <paths>`** — the step changed files its `writes` list does not name; the skill rolled back every path the step changed, inside and outside `writes`, and left the operator's earlier uncommitted work alone → report the step to the plugin's maintainer; the plugin stays unstamped until a fixed step applies.
- **`/lazy-core.migrate` reports `failed: commit-refused: <message>`** — the git guard or a hook refused the step's commit, typically because the index holds staged content; the skill rolled the step's changes back and blocked the plugin's later steps → clear what the message names, then re-run `/lazy-core.setup`, which offers the step again.
- **`/lazy-core.migrate` lists an `invalid` row** — a step file, a stamp file, or a step condition could not be read or judged → update the plugin; a broken stamp file under `.state/` can be deleted, and the next run re-judges every step.
- **Phase 1 ends `failed: <reason>`** — `migrate-plan` refused, usually because `.claude/lazy.settings.json` is not valid JSON → fix the file and re-run `/lazy-core.migrate`.
