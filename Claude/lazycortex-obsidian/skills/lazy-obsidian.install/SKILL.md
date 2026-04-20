---
name: lazy-obsidian.install
description: "Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none), scaffolds the tag-page template used by the `obsidian.gen-tag-pages` agent (project scope only), and cleans up orphaned rules from previous versions. Idempotent — safe to re-run. Detects install scope automatically. Does not mutate any Obsidian vault — that's `lazy-obsidian.config`."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *)
---

# Install lazycortex-obsidian

Bootstrap the plugin in the right scope: sync rule templates shipped by the plugin into the matching rules directory, scaffold the tag-page template consumed by the `obsidian.gen-tag-pages` agent (project scope only), and offer to delete orphans (rules the plugin dropped between versions). Vault configuration lives in the separate `lazy-obsidian.config` skill — this skill only handles rule and template scaffolding.

The plugin currently ships **zero rules** — vault-hygiene guidance is inlined into `lazy-obsidian.config/SKILL.md` because it only applied to that one skill. If you installed an earlier version of the plugin that shipped `lazy-obsidian.vault-hygiene.md`, this skill will offer to delete it as an orphan.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json` and find the entry for `lazycortex-obsidian@lazycortex`. The `scope` field is either:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled in a project's `.claude/settings.json`

If the plugin has entries at both scopes, ask the user which to target. Default: `project`.

If no entry is found, the plugin isn't actually installed — abort and tell the user to enable it first in their `settings.json`:
```json
"enabledPlugins": { "lazycortex-obsidian@lazycortex": true }
```

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-obsidian@lazycortex`.

For each source file `<installPath>/rules/<name>.md`, the rule destination by scope is:

| Scope | Rule destination |
|---|---|
| `user` | `~/.claude/rules/<name>.md` |
| `project` | `<repo-root>/.claude/rules/<name>.md` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — but warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-obsidian@lazycortex` first.

## Step 3: Sync rule templates (per-rule + orphan detection)

Rules eat context on every session — the user owns the decision to install each one.

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md` (currently returns zero files — plugin ships no rules).
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-obsidian` → `lazy-obsidian`), plus every unique `<ns>.` prefix appearing in source rule filenames. When no rules ship, the owned namespace is just `lazy-obsidian`.
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace.
- Ensure the destination directory exists with `mkdir -p`.

### Per-rule decision (wizard-style, one question at a time)

For every rule name in (source ∪ target), determine its state and act:

1. **New** — target missing, source present → `AskUserQuestion`: "Install rule `<name>`? (<first-line-of-description>)" with options **install** / **skip**. Install → copy source to target, state **installed**. Skip → state **skipped**.
2. **Unchanged** — both present, byte-identical → no prompt. State **unchanged**.
3. **Drift** — both present, differ → show unified diff. `AskUserQuestion`: **overwrite** / **keep-local**. State **updated** or **kept-local**.
4. **Orphan** — target present, source missing → `AskUserQuestion`: "Rule `<name>` is no longer shipped by the plugin. Delete from `<targetDir>`?" with options **delete** / **keep**. Delete → `rm <target>`, state **deleted**. Keep → state **kept-orphan**.

One `AskUserQuestion` at a time — wait for the answer before the next prompt.

With zero source rules, only orphan prompts fire. Users upgrading from an earlier version see a deletion prompt for `lazy-obsidian.vault-hygiene.md` (the rule was inlined into `lazy-obsidian.config`).

### Namespace-scoped deletion

Orphan detection only considers target files whose filename starts with one of this plugin's owned namespaces (just `lazy-obsidian.*` today). Rules from other plugins and user-authored rules in unrelated namespaces are never offered for deletion.

## Step 4: Sync the tag-page template (project scope only)

The `obsidian.gen-tag-pages` agent reads its template from the consumer repo at a fixed path. This step scaffolds (or re-prompts on drift for) that file. **Skip this step entirely when scope is `user`** — tag pages only make sense per-vault, so there is no global install mode.

### Paths

- Source: `<installPath>/templates/obsidian/tag-page-template.md`
- Target: `<repo-root>/.claude/templates/obsidian.tag-page-template.md`

Ensure `<repo-root>/.claude/templates/` exists with `mkdir -p` before any write.

### Per-file decision (wizard-style, one question at a time)

Use `AskUserQuestion` exactly like Step 3. Do not batch:

1. **New** — target missing → `AskUserQuestion`: "Install tag-page template for the `obsidian.gen-tag-pages` agent at `.claude/templates/obsidian.tag-page-template.md`?" with options **install** / **skip**. Install → `cp <source> <target>`, state **installed**. Skip → state **skipped** (note to user: the agent will refuse to run until this file exists).
2. **Unchanged** — both present, byte-identical → no prompt. State **unchanged**.
3. **Drift** — both present, differ → show unified diff via `Bash(diff -u <target> <source>)`. `AskUserQuestion`: **overwrite** / **keep-local**. State **updated** or **kept-local**. The consumer is expected to customize the template, so **keep-local** is the usual choice after first install.

No orphan detection is needed — the plugin owns exactly one template file under this name.

### Agent availability

The agent itself (`obsidian.gen-tag-pages`) is shipped by the plugin at `<installPath>/agents/obsidian.gen-tag-pages.md` and becomes available automatically when the plugin is enabled — nothing to copy into the consumer repo. Only the template is project-local.

## Step 5: Dataview dependency check (project scope only, warn-only)

Tag pages rely on the Dataview Obsidian plugin to render the `Index` section. Check presence **and print a warning if missing — do not block or prompt**. Skip this step entirely when scope is `user`.

Presence signal (either is sufficient):

- `<repo-root>/.obsidian/community-plugins.json` exists and contains `"dataview"`, OR
- `<repo-root>/.obsidian/plugins/dataview/manifest.json` exists.

If neither is present, print:

> Warning: Dataview Obsidian plugin not detected in this vault. Tag pages will render their `Summary` section correctly but the `Index` DataviewJS block will stay blank until Dataview is installed. Run `/lazy-obsidian.config` to bootstrap the vault (Dataview is in the musthave set).

Record this as an INFO line in the step report; do not fail or prompt.

## Step 6: Verify

- Read back each installed rule file and confirm its `---` frontmatter parses.
- If the tag-page template was installed or updated this run, read back the target and confirm it still contains both `{{TAG_PATH}}` and `{{SUMMARY}}` substitution tokens. Warn (do not fail) if either is missing — the consumer may have customized them away intentionally.
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**created**, **updated**, **unchanged**, or **kept-local**) and target `<path>`
  - Tag-page template: state (**installed**, **updated**, **unchanged**, **kept-local**, **skipped**) and target `<path>` — omit when scope is `user`
  - Dataview check: **present** or **missing (warned)** — omit when scope is `user`

## Step 7: Log the run

Log to `./.logs/claude/lazy-obsidian.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule or template files into the consumer repo. Re-run this skill after every plugin update to pick up changes.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **User scope is rule-only**: the tag-page template and Dataview check are project-only concerns (they require a vault).
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start). If the tag-page template was **installed** or **updated**, mention that the consumer is expected to customize it and that `/lazy-obsidian.install` will prompt on future drift. For Obsidian vault setup itself, tell them to run `lazy-obsidian.config` next.
