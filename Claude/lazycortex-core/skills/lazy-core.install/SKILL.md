---
name: lazy-core.install
description: "Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory. Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(test *), Bash(date *)
---

# Install lazycortex-core

Bootstrap the plugin in the right scope: copy every rule template shipped by the plugin into the target `rules/` directory.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json` and find the entry for `lazycortex-core@lazycortex`. The `scope` field is either:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled in a project's `.claude/settings.json`

If the plugin has entries at both scopes, ask the user which to target. Default: `project`.

If no entry is found, the plugin isn't actually installed — abort and tell the user to enable it first in their `settings.json`:
```json
"enabledPlugins": { "lazycortex-core@lazycortex": true }
```

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json`.

For each source file `<installPath>/rules/<name>.md`, the target is:

| Scope | Rule destination |
|---|---|
| `user` | `~/.claude/rules/<name>.md` |
| `project` | `<repo-root>/.claude/rules/<name>.md` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-core@lazycortex` first.

## Step 3: Sync rule templates

For each rule file discovered in Step 2:

1. Ensure destination directory exists with `mkdir -p`.
2. Determine state by comparing source and target **byte-for-byte** (read both files and compare content exactly):
   - **Target missing** → copy source → target. Record state: **created**.
   - **Target exists, byte-identical to source** → skip. Record state: **unchanged**.
   - **Target exists, differs from source** → show a unified diff and ask the user whether to overwrite.
     - Accept → overwrite with source. Record state: **updated**.
     - Decline → leave target untouched. Record state: **kept-local**.

## Step 4: Verify

For each installed rule file:

- Read it back and confirm its `---` frontmatter parses
- Confirm the file is under 3 KB (per the `lazy-core.doctor` rule-size threshold)

Report to the user:
- Scope detected (user vs project)
- Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
- For each rule: state (**created**, **updated**, **unchanged**, or **kept-local**) and target `<path>`

## Step 5: Log the run

Log to `./.logs/claude/lazy-core.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start).
