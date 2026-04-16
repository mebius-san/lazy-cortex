---
description: Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene.
---

# Project Hygiene

Constraints below are what `lazy-core.audit`, `lazy-core.doctor`, and `lazy-core.optimize` enforce. Fix issues at their source; don't silence the checks.

## Scope: project-local by default

- **Create skills, agents, hooks, rules, and other artifacts at the project level** (`.claude/` in the repo), never under `~/.claude/` without an explicit request.
- **Never modify the global `~/.claude/` config** (create/modify/delete skills, agents, hooks, rules, scripts, or settings) without the user's explicit command.
- Only truly cross-project artifacts belong globally — and even then, ask first.

## Naming: dot-namespaces for all artifacts

- **All custom skills, commands, agents, hooks, and rules must use `namespace.name`.** Examples: `lazy-core.audit`, `lazy-core.doctor`, `lazy-guard.check-public-repo`, `lazy-log.logging`.
- Never create flat names like `config-sync` or `logging` — always `namespace.name`.
- Applies to file names and directory names: rule files (`lazy-log.logging.md`, not `logging.md`), skill directories (`lazy-core.audit/`, not `audit/`), hook filenames, command filenames, and agent filenames.

## Settings split strategy

- **`settings.json`** (git-tracked): project-inherent permissions — MCP tools, git write ops, log paths, skills. Anything a contributor needs regardless of machine.
- **`settings.local.json`** (gitignored): machine-specific permissions — personal env files, local docker paths, machine-specific CLIs, service-specific permissions tied to one setup.
- **Prefer project-level over global.** A permission specific to one project goes in that project's `.claude/settings.local.json`, not the global `~/.claude/settings.local.json`. The global file should only contain permissions that genuinely apply to every project.

## MCP servers

- **Never add, remove, or modify MCP server configurations** (in `~/.mcp.json`, project `.mcp.json`, or `settings.json` `enabledMcpjsonServers`) without the user's explicit permission. Always ask first.
- **MCP servers belong at the narrowest scope.** A server used by one project goes in that project's `.mcp.json`, not the global `~/.mcp.json`. Only truly universal servers (context7, brave-search) belong globally.

## Path hygiene (for tracked config files)

- **Never hardcode paths that can be derived.** Prefer `$HOME`, `~`, `$XDG_*`, or templating variables from your config system. Hardcode only when truly unavoidable and the value is the same on every machine.
- Do not write `/Users/…` or `/home/…` absolute paths into tracked `.claude/` files.
- Do not write `<project>/` prefixes — use relative paths (`.claude/…`, `CLAUDE.md`).
- Do not use `~/.claude/` for project-local items (project settings, project agents, project rules) — use relative `.claude/` instead.
