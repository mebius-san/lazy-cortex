---
name: lazy-diagram.install
description: "Bootstrap the lazycortex-diagram plugin for the current project (or globally). Syncs the authoring rule shipped by the plugin into the consumer's rules directory and seeds agent model tiers for the per-format drawer agents. Idempotent and quiet on re-run — an enabled plugin installs its whole surface, decisions are derived not asked, and orphaned rules are left in place. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(test *), Bash(date *), Bash(diff *), AskUserQuestion
---
# Install lazycortex-diagram

Bootstrap the plugin in the right scope: sync every rule template shipped by the plugin into the consumer's rules directory and seed agent model tiers for the per-format drawer subagents (`lazy-diagram.draw-mermaid`, `lazy-diagram.draw-ascii`). No-longer-shipped rules in an owned namespace are left in place silently.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Seed lazy.settings.json`
   - `Step 5 — Verify / Report`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is persisted (in `lazy.settings.json` or `installed_plugins.json`), and on the next run the persisted value is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-rule "install this rule?" prompt and no per-artifact opt-in — wanting the plugin means wanting its surface.
- **Everything derivable is derived, not asked:** install scope (from `installed_plugins.json`), agent tiers (from `lazycortex-core`'s `default-tiers.json`).
- This skill collects no genuine project config of its own; every action is mechanical file-sync or tier-seeding.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write the new version silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged from shipped, but the shipped delta applies without contradicting local edits (new sections / keys / entries added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, and showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-diagram@lazycortex` key holds an **array of entries** — one per project where `/plugin install` was last run. The plugin **cache is shared globally across all projects**, so any non-empty array proves the plugin is installed and usable in the current cwd.

**Do NOT compare an entry's `projectPath` against the current working directory.** `projectPath` records where the install command was last run, not where the plugin "belongs" — Step 2 targets `<repo-root>` (i.e. `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Look at the `scope` field of the entries in the array:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled per-project in `.claude/settings.json`

The scope is already recorded — derive it, do not ask. Use the entry's `scope`. If both scopes appear in the array, default to `project` silently.

Abort **only** if the `lazycortex-diagram@lazycortex` key is absent or its array is empty. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-diagram@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-diagram`.

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-diagram@lazycortex`.

For each source file `<installPath>/rules/<name>.md`, the rule destination by scope is:

| Scope | Rule destination |
|---|---|
| `user` | `~/.claude/rules/<name>.md` |
| `project` | `<repo-root>/.claude/rules/<name>.md` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — but warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-diagram@lazycortex` first.

## Step 3: Sync rule templates

An enabled plugin installs its whole rule surface — apply the **File-sync policy** per rule, no per-rule "install?" prompt.

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md`.
- Owned namespaces: `lazy-diagram`, plus every unique `<ns>.` prefix appearing in source rule filenames.
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace. Union them.
- Ensure the destination directory exists with `mkdir -p`.

### Apply the File-sync policy per rule

For every rule name in (source ∪ target):

- **New** (target missing) → copy source to target silently. State **installed**.
- **Unchanged** (byte-identical) → no action. State **unchanged**.
- **Drift, cleanly mergeable** (both present, differ, the shipped delta applies without contradicting local edits — new headings / list items added, every local-only chunk preserved) → merge silently via `Edit`. State **merged**.
- **Conflict** (the same region changed incompatibly in both) → the only case that asks, per File-sync policy case 3. State **merged** or **kept-local** by the user's choice.
- **Orphan** (target present, source gone, within an owned namespace) → leave in place silently. State **kept-orphan**.

Target files outside this plugin's owned namespaces (other plugins, user-authored rules) are never touched and never reported as orphans.

## Step 4: Seed lazy.settings.json

Non-destructively seed the `lazycortex` domain group in `agent_models` with the subagents this plugin ships. **Tier values are read from `lazycortex-core`'s `default-tiers.json` at runtime** — there is no hardcoded table here. Adding/removing a `lazycortex-diagram:*` agent and updating `default-tiers.json` is enough; this step picks the change up automatically.

### Target file

| Scope | Path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` |

### Read or initialize

Read the target file. If missing or unparseable, treat its contents as `{"version": 1, "agent_models": {}}`.

### Ensure domain group exists

Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite existing content, and never touch other groups).

### Build the seed set from `default-tiers.json`

`lazycortex-core` is a declared dependency (`plugin.json`), so it must be installed (in the cache) or co-resident (in the dev vault). Locate the canonical defaults file per the inter-plugin boundary contract — walk `$LAZYCORTEX_PLUGIN_DIRS` first, fall back to the cache glob when env is unset (install-time invocation outside the daemon):

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

The newest version wins. Read the file, parse the JSON, and select every key under `defaults` that starts with `lazycortex-diagram:`. Those are the entries to seed (key + tier verbatim).

If the file is absent → FAIL with `lazycortex-core not installed; install it before /lazy-diagram.install`. Don't fall through to a hardcoded fallback — silent drift is exactly what the SOT is meant to prevent.

### Apply per-key semantics

For each `(dispatch, tier)` pulled from the JSON (write back only if anything changed):

- **absent** in `agent_models.lazycortex` → add the entry with the JSON's tier. State **added**.
- **equal** → leave untouched. State **unchanged**.
- **different** → leave the user's value untouched. State **kept-local** (report user's value alongside the JSON's).

Never touch other `lazycortex` entries (e.g. `lazycortex-log:*` seeded by `lazy-log.install`).

### Write back

If any mutation happened, write the file with `version: 1` at the top.

### Report outcome

One line per seeded entry: `lazycortex.<key> = <value> (<state>)`. Include the resolved `default-tiers.json` path so the user can see where the defaults came from.

## Step 5: Verify / Report

- Read back each installed rule file and confirm its `---` frontmatter parses.
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**installed**, **merged**, **unchanged**, **kept-local**, **kept-orphan**) and target `<path>`
  - Per-key `agent_models` seed outcome from Step 4

## Step 6: Log the run

Log to `./.logs/claude/lazy-diagram.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Failure modes

- **`/lazy-diagram.install` aborts: "plugin not installed"** — `lazycortex-diagram@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-diagram@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/lazy-diagram.install` aborts: "plugin cache is empty"** — the plugin glob returned zero rule files → run `/plugin update lazycortex-diagram@lazycortex` to refresh the cache, then re-run.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Next steps shown to user**: if any rule was **installed** or **merged**, remind the user to restart Claude Code (rules are loaded on session start).
