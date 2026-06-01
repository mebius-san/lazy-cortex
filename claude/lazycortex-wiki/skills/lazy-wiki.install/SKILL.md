---
name: lazy-wiki.install
description: "Bootstrap the lazycortex-wiki plugin for the current project (or globally). Creates the template dir, syncs the navigation rule, seeds wiki settings + agent_models + routines + expert entry. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(ls *), Bash(python3 *)
---
# Install lazycortex-wiki

Bootstrap the plugin in the right scope: create the wiki template directory, sync the `lazy-wiki.navigation` rule shipped by the plugin into the consumer's rules directory, seed the `wiki` settings section, seed agent model tiers for the curator, register the two routines (`wiki.scan` and `wiki.relink-weekly`), and compose the `wiki-curator` expert. Idempotent — never overwrites existing user values; asks on drift.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Create template directory`
   - `Step 4 — Sync navigation rule`
   - `Step 5 — Seed wiki settings section`
   - `Step 6 — Seed agent_models`
   - `Step 7 — Seed routines + expert`
   - `Step 8 — Verify / Report + Log`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they produced an explicit outcome (`unchanged`, `skipped-per-user-choice`, `already-present`, …).
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-wiki@lazycortex` key holds an array of entries. A non-empty array proves the plugin is installed and usable.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless of any entry's `projectPath`.

Inspect the `scope` field of the entries:
- `"user"` → globally enabled, target `~/.claude/`
- `"project"` → per-project, target `<repo-root>/.claude/`

If both scopes appear, ask the user which to target. Default: `project`.

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

For each rule name in (source ∪ target), determine its state and act — one `AskUserQuestion` at a time:

1. **New** — target missing, source present → `AskUserQuestion`:
   - question: ``Install rule `<name>.md`?``
   - description: ``**Purpose:** <source `description:` frontmatter>\n\n**What this does:** Copies the shipped rule into `<targetPath>`. Rules are loaded into every Claude Code session per their `paths:` / `always_loaded:` scope.``
   - options: **install** / **skip**.
   - Install → `Bash(cp <source> <target>)`. State **installed**. Skip → state **skipped**.
2. **Unchanged** — both present, byte-identical → no prompt. State **unchanged**.
3. **Drift** — both present, differ → `AskUserQuestion`:
   - question: ``Rule `<name>.md` has drift — overwrite with shipped version?``
   - description: ``**Purpose:** <source description>\n\n**What changed:** <one-sentence diff summary>\n\n**Full diff:**\n```diff\n<unified diff, truncated to ~40 lines>\n`````
   - options: **overwrite** / **keep-local**.
   - Overwrite → `Bash(cp <source> <target>)`. State **updated**. Keep-local → state **kept-local**.
4. **Orphan** — target present, source missing → `AskUserQuestion`:
   - question: ``Rule `<name>.md` is no longer shipped by the plugin — delete from `<rulesDir>`?``
   - description: ``**Purpose (from your local copy):** <target description>\n\n**Why you're seeing this:** The plugin no longer ships this rule. Keeping it means it stays loaded but never receives updates.``
   - options: **delete** / **keep**.
   - Delete → `Bash(rm <target>)`. State **deleted**. Keep → state **kept-orphan**.

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

## Step 7: Seed routines + expert

### Routines

Ensure `routines` exists as an object (create `{"_version": 1}` if absent — never overwrite existing content). For each of the two routines below, apply absent-only semantics (present → **kept-local**, absent → **seeded**):

**`wiki.scan`** — event-driven git-watch routine, processes changed files:

```json
"wiki.scan": {
  "type": "git",
  "watch": "changed_files",
  "branch": "<current-branch>",
  "interval_sec": 60,
  "command": ["lazycortex-wiki", "process-file"]
}
```

Substitute `<current-branch>` with the output of `Bash(git rev-parse --abbrev-ref HEAD)` (the branch the daemon watches). The core `dispatch_git` routine type reads `branch` as a branch-name string for `git rev-parse <remote>/<branch>` — a boolean breaks it.

**`wiki.relink-weekly`** — weekly full rescan:

```json
"wiki.relink-weekly": {
  "type": "schedule",
  "cron": "0 4 * * 1",
  "command": ["lazycortex-wiki", "relink-all"]
}
```

### Expert

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). Apply absent-only semantics for the `wiki-curator` key:

```json
"wiki-curator": {
  "agent": "lazycortex-wiki:lazy-wiki.curator",
  "aspects": ["lazycortex-core:lazy-memory.persona-aspect"],
  "git_author": {
    "name": "Wiki Curator",
    "email": "wiki-curator@lazycortex.local"
  },
  "can_commit_in_repo": true
}
```

Write the file if any mutation happened (preserve `_version: 1` for both `routines` and `experts`).

Outcome (one line per seeded entry): `routines.<key>: <seeded|kept-local>`, `experts.wiki-curator: <seeded|kept-local>`.

### First scope offer

Skip this prompt entirely if `wiki.scopes` already has entries (a re-run on an already-configured repo must not re-ask). Only when `wiki.scopes` is empty, ask the user: *"No scopes are configured yet — create the first scope now with `/wiki.configure`?"* options: **yes** / **skip**.

If yes → invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.configure")`.

## Step 8: Verify / Report + Log

- Read back the written `lazy.settings.json` and confirm it parses.
- Confirm `wiki`, `agent_models.lazycortex`, `routines.wiki.scan`, `routines.wiki.relink-weekly`, and `experts.wiki-curator` are all present.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from `installed_plugins.json`.
  - Defaults file path used.
  - Per-rule outcome from Step 4.
  - Settings-section outcomes from Steps 5–7.

Log to `./.logs/claude/lazy-wiki.install/<UTC-timestamp>.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-wiki.install)` then `Write` tool. Never chain.

Outcome: `verified` / `logged`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/wiki.install` aborts: "plugin not enabled"** — `lazycortex-wiki@lazycortex` absent or empty in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins`, restart Claude Code, re-run.
- **`/wiki.install` aborts: "lazycortex-core not installed"** — `default-tiers.json` not found → install `lazycortex-core` first, then re-run.
- **`/wiki.install` aborts: "plugin cache is empty"** — rule glob returned zero files → run `/plugin update lazycortex-wiki@lazycortex`, then re-run.
