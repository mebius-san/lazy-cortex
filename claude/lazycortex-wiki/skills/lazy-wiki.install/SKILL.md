---
name: lazy-wiki.install
description: "Bootstrap the lazycortex-wiki plugin for the current project (or globally). Creates the template dir, syncs the navigation rule, seeds the wiki settings section + agent_models, registers the `wiki.curator` expert (always), and — when the daemon is enabled — registers the two curator routines. Idempotent and quiet on re-run — every decision is persisted and never re-asked. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(ls *), Bash(python3 *), Bash(lazycortex-core *)
---
# Install lazycortex-wiki

Bootstrap the plugin in the right scope: create the wiki template directory, sync the `lazy-wiki.navigation` rule shipped by the plugin into the consumer's rules directory, seed the `wiki` settings section, seed agent model tiers for the curator, compose the `wiki.curator` expert (unconditionally — it is dispatch-routing config, not daemon-only), and — only when this project uses the background daemon — register the two curator routines (`wiki.scan` and `wiki.relink-weekly`). Idempotent and quiet on re-run.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Create template directory`
   - `Step 4 — Sync navigation rule`
   - `Step 5 — Seed wiki settings section`
   - `Step 6 — Seed agent_models`
   - `Step 7 — Register curator expert + (daemon-gated) routines`
   - `Step 8 — Register the plugin-CLI Bash allow-pattern`
   - `Step 9 — Verify / Report + Log`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they produced an explicit outcome (`unchanged`, `merged`, `kept-local`, `skipped-daemon-disabled`, `already-present`, …).
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is persisted, and on the next run the persisted value is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-rule "install this rule?" prompt and no per-artifact opt-in.
- **Daemon gate applies to routines only.** The `wiki.curator` expert is dispatch-routing config and is registered unconditionally; only the two curator *routines* depend on the background daemon. This skill reads the tracked `daemon.enabled` flag and gates the routine registration on it silently — it never asks the daemon question itself (Gate 1 belongs to `lazy-core.install`).
- **Everything derivable is derived, not asked:** install scope (from `installed_plugins.json` — both scopes → `project` silently), curator git identity (a deterministic bot id), the watched branch.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write the new version silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged from shipped, but the shipped delta applies without contradicting local edits (new sections / keys / entries added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, and showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-wiki@lazycortex` key holds an array of entries. A non-empty array proves the plugin is installed and usable.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless of any entry's `projectPath`.

Inspect the `scope` field of the entries:
- `"user"` → globally enabled, target `~/.claude/`
- `"project"` → per-project, target `<repo-root>/.claude/`

The scope is already recorded — derive it, do not ask. Use the entry's `scope`. If both scopes appear in the array, default to `project` silently.

Abort **only** if `lazycortex-wiki@lazycortex` is absent or its array is empty. Message: *"lazycortex-wiki not enabled — add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins` in your `settings.json` and run `/plugin install lazycortex/lazycortex-wiki`."*

Outcome: `scope-detected: <user|project>`.

## Step 2: Determine paths

Run `Bash(git rev-parse --show-toplevel)` to get `<repo-root>` (or use cwd if not in a git repo — warn the user). `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-wiki@lazycortex`.

Resolve paths:

| Scope | Rules dir | `lazy.settings.json` |
|---|---|---|
| `user` | `~/.claude/rules/` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/rules/` | `<repo-root>/.claude/lazy.settings.json` |

Locate `lazycortex-core`'s `default-tiers.json` per the inter-plugin contract — walk `$LAZYCORTEX_PLUGIN_DIRS` first, fall back to the cache glob when env is unset:

```bash
FILE=""
IFS=":" read -ra DIRS <<< "${LAZYCORTEX_PLUGIN_DIRS:-}"
for d in "${DIRS[@]}"; do
  if [[ "$d" == *"/lazycortex-core" ]] && [ -f "$d/skills/lazy-core.agent-models/default-tiers.json" ]; then
    FILE="$d/skills/lazy-core.agent-models/default-tiers.json"; break
  fi
done
[ -z "$FILE" ] && FILE=$(ls ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/skills/lazy-core.agent-models/default-tiers.json 2>/dev/null | sort -V | tail -1)
```

Newest version wins. If absent → FAIL: *"lazycortex-core not installed; install it before /wiki.install."*

Outcome: `target-resolved: <settings-path>`, `defaults-resolved: <tiers-path>`.

## Step 3: Create template directory

Ensure `<repo-root>/.claude/templates/wiki/` exists (project scope) or `~/.claude/templates/wiki/` exists (user scope):

```
Bash(mkdir -p <templates-wiki-dir>)
```

This directory is reserved for future per-project curator template customisation. Creating it now is idempotent.

Outcome: `created` or `already-present`.

## Step 4: Sync navigation rule

Enumerate every rule file shipped by the plugin: `Glob <installPath>/rules/*.md`. If the glob returns zero files → FAIL: *"Plugin cache is empty — run `/plugin update lazycortex-wiki@lazycortex` to refresh."*

Owned namespace: `lazy-wiki`. Target candidates: `Glob <rulesDir>/lazy-wiki.*.md`.

Ensure the rules directory exists with `Bash(mkdir -p <rulesDir>)`.

An enabled plugin installs its whole rule surface — apply the **File-sync policy** per rule, no per-rule "install?" prompt. For every rule name in (source ∪ target):

- **New** (target missing) → copy source to target silently (`Bash(cp <source> <target>)`). State **installed**.
- **Unchanged** (byte-identical) → no action. State **unchanged**.
- **Drift, cleanly mergeable** (both present, differ, the shipped delta applies without contradicting local edits — new headings / list items / scope entries added, every local-only chunk preserved) → merge silently via `Edit`. State **merged**.
- **Conflict** (the same region changed incompatibly in both) → the only case that asks, per File-sync policy case 3. State **merged** or **kept-local** by the user's choice.
- **Orphan** (target present, source gone, within the `lazy-wiki` namespace) → leave in place silently. State **kept-orphan**.

Target files outside the `lazy-wiki` namespace (other plugins, user-authored rules) are never touched and never reported as orphans.

Outcome (one line per rule): `<name>.md: <state>`.

## Step 5: Seed wiki settings section

Read the target `lazy.settings.json`. If missing or unparseable, initialise as `{"_version": 1}`.

Ensure the `wiki` key exists. If absent, add:

```json
{
  "_version": 1,
  "scopes": {}
}
```

Never overwrite an existing `wiki` key or any nested key within it. State **seeded** if added, **already-present** if the key was there.

Write the file if any mutation happened.

Outcome: `wiki-section: <seeded|already-present>`.

## Step 6: Seed agent_models

Ensure `agent_models` exists as an object and `agent_models.lazycortex` exists as an object (create both if absent — never overwrite other groups or other `lazycortex` entries).

From the resolved `default-tiers.json`, select every key under `defaults` that starts with `lazycortex-wiki:`. Those are the entries to seed.

For each `(dispatch, tier)` pair:

- **absent** in `agent_models.lazycortex` → add the entry. State `added`.
- **equal** → leave untouched. State `unchanged`.
- **different** → leave the user's value untouched. State `kept-local` (report both values).

Write the file if any mutation happened (preserve `_version: 1` at top level).

Outcome (one line per seeded entry): `agent_models.lazycortex.<key> = <tier> (<state>)`.

## Step 7: Register curator expert + (daemon-gated) routines

The `wiki.curator` **expert** is dispatch-routing config — the entry that resolves which agent + aspects run when the curator is dispatched. It is registered **unconditionally**, exactly like any other expert (not daemon-gated). The two curator **routines** (`wiki.scan`, `wiki.relink-weekly`) only ever *fire* under the background daemon, so their registration is gated on the project's `daemon.enabled` flag. The non-daemon parts of this install (rule, settings section, `agent_models`, template dir, CLI allow-pattern) are done by Steps 3–6 and Step 8.

### Expert (always registered)

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). Apply absent-only semantics for the `wiki.curator` key:

```json
"wiki.curator": {
  "agent": "lazycortex-wiki:lazy-wiki.curator",
  "aspects": ["lazycortex-core:lazy-memory.persona-aspect"],
  "git_author": {
    "name": "Wiki Curator",
    "email": "wiki.curator@lazycortex.local"
  },
  "can_commit_in_repo": true
}
```

State `experts.wiki.curator: <seeded|kept-local>`.

### Daemon gate for the routines (read-first, never ask)

Gate 1 (`daemon.enabled`) is owned by `lazy-core.install`. This skill only **reads** the tracked flag and honours it silently — it never opens an `AskUserQuestion`. Resolve `<core-bin>` (the `bin/` dir of the newest `lazycortex-core` — the parent of the directory holding `default-tiers.json` resolved in Step 2 is its `skills/...`; walk `$LAZYCORTEX_PLUGIN_DIRS` for `*/lazycortex-core/bin`, falling back to `ls ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/bin | sort -V | tail -1`), then read the flag:

```bash
PYTHONPATH=<core-bin> python3 -c "from lazy_settings import load_tracked_section; from pathlib import Path; print(load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'),'daemon').get('enabled','unset'))"
```

- Output `False` → the project does not use the daemon. **Skip ONLY the routine registration silently** (a routine that can't fire is dead config; the expert above stays registered). State the routine outcomes `skipped-daemon-disabled` and jump straight to the *First scope pointer* below.
- Output `True` or `unset` → register the routines below (do NOT ask; `lazy-core.install` owns Gate 1, and `unset` means the user has not yet run it — register so they are ready when the daemon is enabled).

### Routines

Ensure `routines` exists as an object (create `{"_version": 1}` if absent — never overwrite existing content). For each of the two routines below, apply absent-only semantics (present → **kept-local**, absent → **seeded**):

**`wiki.scan`** — event-driven git-watch routine, processes changed files:

```json
"wiki.scan": {
  "type": "git",
  "watch": "changed_files",
  "branch": "<current-branch>",
  "interval_sec": 60,
  "filter": { "frontmatter": { "review_active": { "not_in": [true] } } },
  "command": ["lazycortex-wiki", "process-file"]
}
```

Substitute `<current-branch>` with the output of `Bash(git rev-parse --abbrev-ref HEAD)` (the branch the daemon watches). The core `dispatch_git` routine type reads `branch` as a branch-name string for `git rev-parse <remote>/<branch>` — a boolean breaks it.

The `filter` block is the earliest cut: git-watch drops a changed file whose frontmatter matches before `process-file` runs, so a document under review (`review_active: true`) never reaches the curator. It mirrors the per-scope `filter` (the source of truth honored on every path); seeding it here keeps the daemon quiet during review. Absent-only semantics apply to the whole routine — a user who removed the filter is not re-seeded.

**`wiki.relink-weekly`** — weekly full rescan:

```json
"wiki.relink-weekly": {
  "type": "schedule",
  "cron": "0 4 * * 1",
  "command": ["lazycortex-wiki", "relink-all"]
}
```

Write the file if any mutation happened (preserve `_version: 1` for both `routines` and `experts`).

Outcome (one line per seeded entry): `experts.wiki.curator: <seeded|kept-local>` (always), `routines.<key>: <seeded|kept-local|skipped-daemon-disabled>`.

### First scope pointer

Do NOT ask. When `wiki.scopes` is empty, print a one-line pointer so the operator knows the next step — *"No wiki scopes configured yet — run `/wiki.configure` to add the first one."* When `wiki.scopes` already has entries, say nothing. Configuring a scope is genuine project work the operator drives via `/wiki.configure`; this install step only points at it, never prompts.

If yes → invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.configure")`.

## Step 8: Register the plugin-CLI Bash allow-pattern

The plugin ships `bin/lazycortex-wiki` which is invoked from other skills via `Bash(lazycortex-wiki ...)` — `lazy-wiki.curator` (the daemon-dispatched expert) calls it to apply node curation, build the index, and dispatch link jobs. Expert subprocesses spawned by the `lazy-core.runtime` daemon run under Claude Code's `dontAsk` permission mode — that mode silently denies any Bash command not on the auto-allow list. Without this entry, every CLI invocation from the curator (`apply-node`, `build-index`, `dispatch-link`, `retag`) fails with `Permission to use Bash has been denied because Claude Code is running in don't ask mode`, and the curator drifts off-protocol mid-job.

Per `lazy-core.hygiene` § Settings split, per-tool permissions live in `settings.local.json` (gitignored), never tracked `settings.json`. Target file resolves from Step 1's scope:

- project install → `<repo-root>/.claude/settings.local.json`
- user install → `~/.claude/settings.local.json`

Apply via the `lazycortex-core` CLI (idempotent — already-present patterns are no-ops):

```
Bash(lazycortex-core permission-allow <settings-local> "Bash(lazycortex-wiki *)")
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 9: Verify / Report + Log

- Read back the written `lazy.settings.json` and confirm it parses.
- Confirm `wiki` and `agent_models.lazycortex` are present.
- Confirm `experts.wiki.curator` is present (always registered). When the daemon gate passed (enabled or unset): also confirm `routines.wiki.scan` and `routines.wiki.relink-weekly` are present. When the routines were `skipped-daemon-disabled`, do NOT expect those two routine keys — their absence is correct; `experts.wiki.curator` must still be present.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from `installed_plugins.json`.
  - Defaults file path used.
  - Per-rule outcome from Step 4.
  - Settings-section outcomes from Steps 5–7 (including the Step 7 daemon-gate outcome).

Log to `./.logs/claude/lazy-wiki.install/<UTC-timestamp>.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-wiki.install)` then `Write` tool. Never chain.

Outcome: `verified` / `logged`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/wiki.install` aborts: "plugin not enabled"** — `lazycortex-wiki@lazycortex` absent or empty in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins`, restart Claude Code, re-run.
- **`/wiki.install` aborts: "lazycortex-core not installed"** — `default-tiers.json` not found → install `lazycortex-core` first, then re-run.
- **`/wiki.install` aborts: "plugin cache is empty"** — rule glob returned zero files → run `/plugin update lazycortex-wiki@lazycortex`, then re-run.
- **Curator never runs after install (no routines)** — Step 7 read `daemon.enabled = false` in the tracked `lazy.settings.json` and skipped the two curator *routines* (outcome `skipped-daemon-disabled`); the `wiki.curator` expert, rule, settings section, and CLI allow-pattern still installed → enable the daemon via `/lazy-core.install` (Gate 1), then re-run `/wiki.install` to register the curator routines.
