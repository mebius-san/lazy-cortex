---
name: lazy-obsidian.install
description: "Bootstrap the lazycortex-obsidian plugin for the current project (or globally). Syncs rule templates shipped by the plugin (currently none) and cleans up orphaned rules from previous versions. Idempotent — safe to re-run. Detects install scope automatically. Does not mutate any Obsidian vault — that's `lazy-obsidian.config`."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *)
---

# Install lazycortex-obsidian

Bootstrap the plugin in the right scope: sync rule templates shipped by the plugin into the matching rules directory, and offer to delete orphans (rules the plugin dropped between versions). Vault configuration lives in the separate `lazy-obsidian.config` skill — this skill only handles rule templates.

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

## Step 4: Verify

- Read back each installed rule file and confirm its `---` frontmatter parses.
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**created**, **updated**, **unchanged**, or **kept-local**) and target `<path>`

## Step 5: Log the run

Log to `./.logs/claude/lazy-obsidian.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start). For Obsidian vault setup itself, tell them to run `lazy-obsidian.config` next.
