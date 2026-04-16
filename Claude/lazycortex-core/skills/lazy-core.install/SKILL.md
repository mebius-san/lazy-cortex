---
name: lazy-core.install
description: "Bootstrap the lazycortex-core plugin for the current project (or globally). Copies the hygiene and security rule templates into the rules directory. Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(test *), Bash(date *)
---

# Install lazycortex-core

Bootstrap the plugin in the right scope: copy the hygiene and security rule templates into the target `rules/` directory.

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

Plugin source: `<installPath>/rules/<file>` where `<installPath>` is the `installPath` field from `installed_plugins.json`. The plugin ships two rule files:
- `rules/lazy-core.hygiene.md`
- `rules/lazy-guard.security.md`

Target paths by scope:

| Scope | Rule destinations |
|---|---|
| `user` | `~/.claude/rules/lazy-core.hygiene.md`, `~/.claude/rules/lazy-guard.security.md` |
| `project` | `<repo-root>/.claude/rules/lazy-core.hygiene.md`, `<repo-root>/.claude/rules/lazy-guard.security.md` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

## Step 3: Copy rule templates

For each of the two rule files:

- Ensure destination directory exists with `mkdir -p`
- Copy `<installPath>/rules/<file>` to the target path
- If the target already exists and has identical content, skip silently
- If the target exists but differs, show a diff and ask whether to overwrite

## Step 4: Verify

For each installed rule file:

- Read it back and confirm its `---` frontmatter parses
- Confirm the file is under 3 KB (per the `lazy-core.doctor` rule-size threshold)

Report to the user:
- Scope detected (user vs project)
- For each rule: installed at `<path>` (or "already up-to-date")

## Step 5: Log the run

Log to `./.logs/claude/lazy-core.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Next steps shown to user**: remind the user to restart Claude Code if any rule file was just created (rules are loaded on session start).
