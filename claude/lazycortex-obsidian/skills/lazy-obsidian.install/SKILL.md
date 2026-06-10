---
name: lazy-obsidian.install
description: "Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none) and scaffolds the tag-page template used by the `lazy-obsidian.gen-tag-pages` agent (project scope only) via quiet file-sync — writes/merges silently, asks only on a genuine conflict, leaves orphans in place. At project scope it is the root entry point for the plugin family: installs the Dataview Obsidian plugin into `<repo-root>/.obsidian/` via `/lazy-obsidian.update-plugin` (Dataview renders the `Index` section of tag pages) and runs `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install` so the full vault setup completes in one pass (no per-chain opt-in — plugin enabled means full functionality). Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), AskUserQuestion
---
# Install lazycortex-obsidian

Bootstrap the plugin in the right scope: sync rule templates shipped by the plugin into the matching rules directory and scaffold the tag-page template consumed by the `lazy-obsidian.gen-tag-pages` agent (project scope only), all via quiet file-sync (write/merge silently, ask only on a genuine conflict, leave orphans in place). At project scope, this skill is the root entry point for the plugin family — after the rule/template work it installs Dataview (needed by tag pages) and runs `/lazy-obsidian.iconize-install` and `/lazy-obsidian.diagram-install` so a fresh vault reaches a usable state in one pass.

The plugin currently ships **zero rules**. If you installed an earlier version of the plugin that shipped `lazy-obsidian.vault-hygiene.md`, this skill leaves it in place as a kept-orphan (it is never auto-deleted).

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Sync the tag-page template`
   - `Step 5 — Install Dataview`
   - `Step 6 — Run /lazy-obsidian.iconize-install`
   - `Step 6.5 — Run /lazy-obsidian.diagram-install`
   - `Step 7 — Verify / Report`
   - `Step 8 — Seed lazy.settings.json`
   - `Step 9 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `installed`, `unchanged`, `merged`, `kept-orphan`, `chained`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-obsidian@lazycortex` key holds an **array of entries** — one per project where `/plugin install` was last run. The plugin **cache is shared globally across all projects**, so any non-empty array proves the plugin is installed and usable in the current cwd.

**Do NOT compare an entry's `projectPath` against the current working directory.** `projectPath` records where the install command was last run, not where the plugin "belongs" — Step 2 targets `<repo-root>` (i.e. `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Look at the `scope` field of the entries in the array:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled per-project in `.claude/settings.json`

If both scopes appear in the array, ask the user which to target. Default: `project`.

Abort **only** if the `lazycortex-obsidian@lazycortex` key is absent or its array is empty. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-obsidian@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-obsidian`.

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-obsidian@lazycortex`.

For each source file `<installPath>/rules/<name>.md`, the rule destination by scope is:

| Scope | Rule destination |
|---|---|
| `user` | `~/.claude/rules/<name>.md` |
| `project` | `<repo-root>/.claude/rules/<name>.md` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — but warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-obsidian@lazycortex` first.

## Step 3: Sync rule templates (file-sync policy)

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md` (currently returns zero files — plugin ships no rules).
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-obsidian` → `lazy-obsidian`), plus every unique `<ns>.` prefix appearing in source rule filenames. When no rules ship, the owned namespace is just `lazy-obsidian`.
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace.
- Ensure the destination directory exists with `mkdir -p`.

### Per-rule decision (quiet file-sync)

For every rule name in (source ∪ target), determine its state and act. The sync is silent by default — it prompts only on a genuine same-region conflict:

1. **Absent or byte-identical** — target missing (source present), or both present and equal → `cp <source> <target>` silently. State **installed** (missing) or **unchanged** (identical). No prompt.
2. **Locally changed, shipped delta applies cleanly** — both present and differ, but the local edits and the shipped edits touch disjoint regions → apply the shipped delta on top of the local edits silently. State **merged**.
3. **Genuine conflict** — both present and the same region changed incompatibly on both sides (can't tell which should survive) → the ONLY case that prompts. `AskUserQuestion` quoting the conflicting region + diff: **merge-shipped** / **keep-local**. State **merged** (shipped region wins) or **kept-local** (local region kept; non-conflicting shipped delta still applied).
4. **Orphan** — target present, source missing → leave it in place silently. State **kept-orphan**. Orphans are never deleted: the rule may be user-customized or still relied on, and we can't prove removal is safe.

"Conflict" ≠ "bytes differ". One `AskUserQuestion` at a time — wait for the answer before the next prompt.

With zero source rules, nothing is written and orphans are silently kept. Users upgrading from an earlier version see `lazy-obsidian.vault-hygiene.md` reported as **kept-orphan** (the rule was retired when `lazy-obsidian.config` was removed; vault-plugin setup now lives in `/lazy-obsidian.update-plugin` + `/lazy-obsidian.iconize-install`) — the report notes it is retired so the user can delete it by hand.

### Namespace-scoped orphan handling

Orphan detection only considers target files whose filename starts with one of this plugin's owned namespaces (just `lazy-obsidian.*` today). Rules from other plugins and user-authored rules in unrelated namespaces are never reported as orphans.

## Step 4: Sync the tag-page template (project scope only)

The `lazy-obsidian.gen-tag-pages` agent reads its template from the consumer repo at a fixed path. This step scaffolds (and quietly re-syncs) that file. **Skip this step entirely when scope is `user`** — tag pages only make sense per-vault, so there is no global install mode.

### Paths

- Source: `<installPath>/templates/obsidian/tag-page-template.md`
- Target: `<repo-root>/.claude/templates/obsidian.tag-page-template.md`

Ensure `<repo-root>/.claude/templates/` exists with `mkdir -p` before any write.

### Per-file decision (quiet file-sync)

Same policy as Step 3 — silent on absent/identical/clean-merge, prompt only on a genuine conflict:

1. **Absent or byte-identical** — target missing, or both present and equal → `cp <source> <target>` silently. State **installed** (missing) or **unchanged** (identical). No prompt.
2. **Locally changed, shipped delta applies cleanly** — both present and differ, local and shipped edits touch disjoint regions → merge silently. State **merged**.
3. **Genuine conflict** — both present and the same region changed incompatibly on both sides → the ONLY case that prompts. `AskUserQuestion` quoting the conflicting region (`Bash(diff -u <target> <source>)`): **merge-shipped** / **keep-local**. State **merged** or **kept-local**. The consumer is expected to customize the template, so a conflict on a customized region resolves to **keep-local** in most cases.

"Conflict" ≠ "bytes differ". No orphan detection is needed — the plugin owns exactly one template file under this name.

### Agent availability

The agent itself (`lazy-obsidian.gen-tag-pages`) is shipped by the plugin at `<installPath>/agents/lazy-obsidian.gen-tag-pages.md` and becomes available automatically when the plugin is enabled — nothing to copy into the consumer repo. Only the template is project-local.

## Step 5: Install Dataview (project scope only)

Tag pages rely on the Dataview Obsidian plugin to render the `Index` section — it is a hard dependency for the vault setup, not an optional add-on. Skip this step entirely when scope is `user` — tag pages are a vault concern. No opt-in prompt: plugin enabled means full functionality, so the full vault setup installs Dataview unconditionally.

Invoke `/lazy-obsidian.update-plugin dataview` unconditionally — it is version-aware and idempotent (installs if missing, updates if the remote is newer, no-ops when current) and re-enforces the opinionated override block from `plugin-settings.json` on every run. Record its state tuple (`binary=... overrides=... community=...`) for the final report. Outcome: state tuple.

If `update-plugin` returns FAIL (registry unreachable, id missing), surface the failure and record `failed:<reason>` — without Dataview the `Summary` section still renders but the `Index` DataviewJS block stays blank. Re-running this skill later picks Dataview up once the network is available.

## Step 6: Run `/lazy-obsidian.iconize-install` (project scope only)

Skip this step ONLY when scope is `user` — iconize-sync is a vault concern.

No opt-in prompt: the full vault setup installs iconize-sync unconditionally (plugin enabled means full functionality). The child skill is itself quiet and idempotent — it installs Iconize + Folder Notes + iconize-reloader via `/lazy-obsidian.update-plugin`, scaffolds the icon-map + pre-commit shim, asserts Iconize frontmatter settings, manages its one `.gitignore` line, and version-checks its hard deps — silently re-running every state and prompting only on a genuine conflict. None of those states are observable from the icon-map file alone, so always run it; never short-circuit on a probe.

Invoke `/lazy-obsidian.iconize-install` as the next skill call. Record **chained** for the report.

## Step 6.5: Run `/lazy-obsidian.diagram-install` (project scope only)

Skip this step ONLY when scope is `user` — diagram render glue is a vault concern.

No opt-in prompt: the full vault setup installs the diagram render glue unconditionally (plugin enabled means full functionality). The child skill is quiet and idempotent — it syncs the `mermaid-fit.css` + `ascii-fit.css` snippets, enables them in `appearance.json`, installs `mermaid-popup` via `/lazy-obsidian.update-plugin` with the calibrated zoom-ratio override, and leaves the legacy `mermaid-no-bg.css` snippet in place as a kept-orphan — silently re-running every state and prompting only on a genuine conflict. None of those states are observable from the snippet file alone, so always run it; never short-circuit on a probe.

Invoke `/lazy-obsidian.diagram-install` as the next skill call. Record **chained** for the report.

## Step 7: Verify

- Read back each installed rule file and confirm its `---` frontmatter parses.
- If the tag-page template was installed or updated this run, read back the target and confirm it still contains both `{{TAG_PATH}}` and `{{SUMMARY}}` substitution tokens. Warn (do not fail) if either is missing — the consumer may have customized them away intentionally.
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**installed**, **merged**, **unchanged**, **kept-local**, or **kept-orphan**) and target `<path>`
  - Tag-page template: state (**installed**, **merged**, **unchanged**, **kept-local**) and target `<path>` — omit when scope is `user`
  - Dataview install: `update-plugin` state tuple (`binary=... overrides=... community=...`) or **failed:`<reason>`** — omit when scope is `user`
  - iconize-install chain: **chained** — omit when scope is `user`. This line is mandatory in project scope; emit it unconditionally so a missing line is a visible gap in the report.
  - diagram-install chain: **chained** — omit when scope is `user`. This line is mandatory in project scope; emit it unconditionally so a missing line is a visible gap in the report.

## Step 8: Seed lazy.settings.json

Non-destructively seed the `lazycortex` domain group in `agent_models` with the subagents this plugin ships. **Tier values are read from `lazycortex-core`'s `default-tiers.json` at runtime** — there is no hardcoded table here. Adding/removing a `lazycortex-obsidian:*` agent and updating `default-tiers.json` is enough; this step picks the change up automatically.

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

The newest version wins. Read the file, parse the JSON, and select every key under `defaults` that starts with `lazycortex-obsidian:`. Those are the entries to seed (key + tier verbatim).

If the file is absent → FAIL with `lazycortex-core not installed; install it before /lazy-obsidian.install`. Don't fall through to a hardcoded fallback — silent drift is exactly what the SOT is meant to prevent.

### Apply per-key semantics

For each `(dispatch, tier)` pulled from the JSON (write back only if anything changed):

- **absent** in `agent_models.lazycortex` → add the entry with the JSON's tier. State **added**.
- **equal** → leave untouched. State **unchanged**.
- **different** → leave the user's value untouched. State **kept-local** (report user's value alongside the JSON's).

Never touch other `lazycortex` entries (e.g. `lazycortex-log:*` seeded by `lazy-log.install`).

### Write back

If any mutation happened, write the file with `version: 1` at the top.

### Report outcome

One line per seeded entry: `lazycortex.<key> = <value> (<state>)`. Include the resolved `default-tiers.json` path. Append to the Step 7 report.

## Step 9: Log the run

Log to `./.logs/claude/lazy-obsidian.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Failure modes

- **`/lazy-obsidian.install` aborts: "plugin not installed"** — `lazycortex-obsidian@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-obsidian@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/lazy-obsidian.install` aborts: "plugin cache is empty"** — the plugin glob returned zero rule files → run `/plugin update lazycortex-obsidian@lazycortex` to refresh the cache, then re-run.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule or template files into the consumer repo. Re-run this skill after every plugin update to pick up changes.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **User scope is rule-only**: the tag-page template and Dataview check are project-only concerns (they require a vault).
- **Next steps shown to user**: if any rule was **installed** or **merged**, remind the user to restart Claude Code (rules are loaded on session start). If the tag-page template was **installed** or **merged**, mention that the consumer is expected to customize it and that future installs merge silently, prompting only on a genuine same-region conflict. If any artifact was **kept-orphan**, note it is retired and can be deleted by hand. If Dataview reported **failed:**, remind them they can re-run `/lazy-obsidian.update-plugin dataview` later. The iconize-install and diagram-install chains run automatically as part of the full vault setup — their own reports surface inline.
