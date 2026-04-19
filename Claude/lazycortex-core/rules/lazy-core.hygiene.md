---
description: Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene.
always_loaded: constrains main agent on every artifact create/edit
---

# Project Hygiene

## Scope: project-local by default

- Create skills, agents, hooks, rules, and other artifacts at the project level (`.claude/`), never under `~/.claude/` without an explicit request.
- Never modify global `~/.claude/` config without the user's explicit command.
- Only truly cross-project artifacts belong globally — even then, ask first.

## Naming: dot-namespaces for all artifacts

- All custom skills, commands, agents, hooks, and rules use `namespace.name` (e.g. `lazy-core.audit`, `lazy-log.logging`). Never flat names like `logging` or `config-sync`.
- Applies to both file names and directory names.

## Settings split strategy

Applies at **both scopes** — `~/.claude/` and project `.claude/`. Tracked `settings.json` owns enablement; gitignored `settings.local.json` owns permissions and machine-specific values.

- **`settings.json`** (tracked): enablement only — `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, non-secret `env`, `model`, `statusLine`, marketplace registrations. What every contributor/machine needs identically.
- **`settings.local.json`** (gitignored): entire `permissions` block (`allow`/`ask`/`deny`/`defaultMode`), `additionalDirectories`, machine-specific `env` (public-repo mirror paths, Docker sockets, etc.), and personal permission choices.
- **Per-tool permissions never belong in tracked `settings.json`** — at either scope. Permission posture is personal.
- **Prefer project-level over global.** A permission specific to one project goes in that project's `.claude/settings.local.json`, not `~/.claude/settings.local.json`.

## MCP servers

- Never add, remove, or modify MCP server configurations (`~/.mcp.json`, project `.mcp.json`, `settings.json` `enabledMcpjsonServers`) without the user's explicit permission. Always ask first.
- MCP servers belong at the narrowest scope — project `.mcp.json` unless truly universal (context7, brave-search).

## Path hygiene (for tracked config files)

- Never hardcode paths that can be derived. Prefer `$HOME`, `~`, `$XDG_*`, or templating variables. Hardcode only when unavoidable and identical on every machine.
- No `/Users/…` or `/home/…` absolute paths in tracked `.claude/` files.
- No `<project>/` prefixes — use relative paths (`.claude/…`).
- Don't use `~/.claude/` for project-local items — use relative `.claude/`.

## Dynamic content in agents/skills

- **Never hardcode dynamic content.** Filenames, folder trees, and enumerations derived from live source data must not appear as concrete names — use patterns (e.g. `<group-key>-paths.md`). Only truly static names are allowed.
- **Agents discover dynamically.** They scan source at runtime, following naming conventions — no pre-built list of outputs.
