---
description: Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene.
---

# Project Hygiene

## Scope: project-local by default

- **Create skills, agents, hooks, rules, and other artifacts at the project level** (`.claude/` in the repo), never under `~/.claude/` without an explicit request.
- **Never modify the global `~/.claude/` config** (create/modify/delete skills, agents, hooks, rules, scripts, or settings) without the user's explicit command.
- Only truly cross-project artifacts belong globally — and even then, ask first.

## Naming: dot-namespaces for all artifacts

- **All custom skills, commands, agents, hooks, and rules must use `namespace.name`.** Examples: `lazy-core.audit`, `lazy-core.doctor`, `lazy-guard.check-public`, `lazy-log.logging`.
- Never create flat names like `config-sync` or `logging` — always `namespace.name`.
- Applies to file names and directory names: rule files (`lazy-log.logging.md`, not `logging.md`), skill directories (`lazy-core.audit/`, not `audit/`), hook filenames, command filenames, and agent filenames.

## Settings split strategy

Applies at **both scopes** — `~/.claude/` and project `.claude/`. The split is the same: tracked `settings.json` owns enablement flags, gitignored `settings.local.json` owns per-tool permissions.

- **`settings.json`** (git-tracked, shared via the repo or dotfiles): enablement and shared configuration only — `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, non-secret `env` vars, `model`, `statusLine`, marketplace registrations. Anything every contributor / every machine needs identically.
- **`settings.local.json`** (gitignored, per-user + per-machine): the entire `permissions` block (`allow` / `ask` / `deny` / `defaultMode`), plus machine-specific paths (`additionalDirectories`, `PUBLIC_REPO` and similar env values), plus any permission choices that are personal preferences rather than project requirements.
- **Per-tool permissions never belong in tracked `settings.json`** — not at the project scope and not at the global scope. Permission choices are personal. A teammate (or your future self on a different machine) may have a different risk posture. Put them in the paired `settings.local.json`.
- **Prefer project-level over global.** A permission specific to one project goes in that project's `.claude/settings.local.json`, not `~/.claude/settings.local.json`. The global `settings.local.json` should only hold permissions that genuinely apply to every project on this machine.
- **Machine-specific paths also live in `settings.local.json`.** Public-repo mirror paths, Docker socket paths, local service paths, and any value that varies by machine goes in the local file (`additionalDirectories`, `env`, etc.). Never in tracked `settings.json`.

## MCP servers

- **Never add, remove, or modify MCP server configurations** (in `~/.mcp.json`, project `.mcp.json`, or `settings.json` `enabledMcpjsonServers`) without the user's explicit permission. Always ask first.
- **MCP servers belong at the narrowest scope.** A server used by one project goes in that project's `.mcp.json`, not the global `~/.mcp.json`. Only truly universal servers (context7, brave-search) belong globally.

## Path hygiene (for tracked config files)

- **Never hardcode paths that can be derived.** Prefer `$HOME`, `~`, `$XDG_*`, or templating variables from your config system. Hardcode only when truly unavoidable and the value is the same on every machine.
- Do not write `/Users/…` or `/home/…` absolute paths into tracked `.claude/` files.
- Do not write `<project>/` prefixes — use relative paths (`.claude/…`, `CLAUDE.md`).
- Do not use `~/.claude/` for project-local items (project settings, project agents, project rules) — use relative `.claude/` instead.

## Meta-rule

All constraints. New constraints → this file; procedures → the relevant `lazy-core.*` / `lazy-guard.*` skill.
