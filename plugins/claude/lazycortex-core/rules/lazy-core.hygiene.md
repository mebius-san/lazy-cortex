---
description: Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.slim-context — scope, naming, settings split, MCP scope, and path hygiene.
always_loaded: constrains main agent on every artifact create/edit
---
# Project Hygiene

## Scope: project-local by default

- Create artifacts at the project level (`.claude/`), never under `~/.claude/` without an explicit request.
- Never modify global `~/.claude/` config without the user's explicit command; only truly cross-project artifacts belong globally — even then, ask first.

## Naming: dot-namespaces for all artifacts

- Every custom skill, command, agent, hook, and rule uses `namespace.name` (`lazy-core.audit`), never a flat name, in both file and directory names.
- A plugin's namespace is `lazy-<short name>` plus core's sub-namespaces (`lazy-log`, `lazy-memory`, `lazy-runtime`, `lazy-guard`, `lazy-repo`, `lazy-routine`, `lazy-expert`).
- An artifact a repo authors for itself takes a namespace of its own naming what it is for, never `lazy-` — that prefix marks a marketplace surface.

### Runtime-registry keys

Two kinds of key live in `lazy.settings.json`, under different rules on purpose:

- **Routine names carry the plugin namespace**: `<plugin>.<verb>` (`lazy-wiki.scan`), optionally a third scope segment (`lazy-wiki.mirror-sync.<scope-id>`). Hook short names (`hooks_enabled`, `hooks.disabled`) follow the same rule.
- **Expert keys do NOT**: they stay `<domain>.<role>` (`wiki.curator`); only the entry's `agent` field names the artifact (agent `lazy-<ns>.<role>` → key `<ns>.<role>`).

Never "fix" an expert key into a plugin namespace, never leave a new routine or hook name outside one; `lazy-core.audit` reports either.

## Settings split strategy

At both scopes (`~/.claude/`, project `.claude/`):

- **`settings.json`** (tracked): enablement only — `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, non-secret `env`, `model`, `statusLine`, marketplace registrations.
- **`settings.local.json`** (gitignored): `permissions`, `additionalDirectories`, machine-specific `env`. Per-tool permissions never go in tracked `settings.json`; prefer project-level over global.

## MCP servers

- Never add, remove, or modify MCP server configurations (`~/.mcp.json`, project `.mcp.json`, `enabledMcpjsonServers`) without the user's explicit permission — always ask first.
- MCP servers belong at the narrowest scope: project `.mcp.json` unless truly universal.

## Path hygiene (for tracked config files)

- No hardcoded absolute paths (`/Users/…`, `/home/…`) or `<project>/` prefixes in tracked `.claude/` files — prefer `$HOME`, `~`, `$XDG_*`, or relative `.claude/…` paths. Never `~/.claude/` for project-local items.

## Dynamic content in agents/skills

- **Never hardcode dynamic content.** Filenames, folder trees, and enumerations derived from live source data must not appear as concrete names — use patterns (`<group-key>-paths.md`); agents discover them by scanning source at runtime.
