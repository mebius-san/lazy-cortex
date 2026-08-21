---
description: Project hygiene constraints checked by lazy-core.audit, lazy-core.doctor, and lazy-core.optimize — scope, naming, settings split, MCP scope, and path hygiene.
always_loaded: constrains main agent on every artifact create/edit
---
# Project Hygiene

## Scope: project-local by default

- Create skills, agents, hooks, rules, and other artifacts at the project level (`.claude/`), never under `~/.claude/` without an explicit request.
- Never modify global `~/.claude/` config without the user's explicit command; only truly cross-project artifacts belong globally — even then, ask first.

## Naming: dot-namespaces for all artifacts

- Every custom skill, command, agent, hook, and rule uses `namespace.name` (`lazy-core.audit`, `lazy-log.logging`) — never flat names — in both file and directory names.
- A plugin's namespace is `lazy-<short name>` (`lazy-core`, `lazy-wiki`, `lazy-python`, `lazy-obsidian`, …) plus core's sub-namespaces (`lazy-log`, `lazy-memory`, `lazy-runtime`, `lazy-guard`, `lazy-repo`, `lazy-routine`, `lazy-expert`).
- An artifact a repo authors for itself takes a namespace of its own naming what it is for, never `lazy-` — that prefix marks a marketplace surface. The dot form stays mandatory either way.

### Runtime-registry keys

Two kinds of key live in `lazy.settings.json` rather than on disk, and they follow different rules on purpose:

- **Routine names carry the plugin namespace, exactly like artifacts** — `<plugin>.<verb>` (`lazy-wiki.scan`, `lazy-spec.gate-tick`); a scope-bound routine may add a third segment (`lazy-wiki.mirror-sync.<scope-id>`). A routine's `command:` resolves to its plugin's binary, so that namespace is the right one.
- **Expert keys do NOT** — they stay `<domain>.<role>` (`wiki.curator`, `spec.coordinator`, `claude-plugin.designer`). An expert key names a composition of role and domain, not an artifact any plugin ships, and is often served by another plugin's agent; a `lazy-` prefix would claim ownership the key does not have.
- **Hook short names** (the labels in `LAZYCORTEX_HOOKS_ALLOW_LIST`, a routine's `hooks_enabled`, `hooks.disabled`) follow the routine rule; the canonical name is the hook file's stem, which already carries the namespace.

The split is deliberate: never "fix" an expert key into a plugin namespace, never leave a new routine or hook name outside one. An expert served by agent `lazy-<ns>.<role>` gets key `<ns>.<role>`; only the entry's `agent` field names the artifact. A pre-clause name is a finding in either direction — `lazy-core.audit` reports it; `lazy-core.doctor` / `lazy-core.autosetup` canonicalise what they safely can, moving an expert key together with its derived `git_author` and every `routines[<name>].expert` pointer. Nothing migrates a consumer's settings by force.

## Settings split strategy

Applies at both scopes (`~/.claude/`, project `.claude/`).

- **`settings.json`** (tracked): enablement only — `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, non-secret `env`, `model`, `statusLine`, marketplace registrations.
- **`settings.local.json`** (gitignored): `permissions` (`allow`/`ask`/`deny`/`defaultMode`), `additionalDirectories`, machine-specific `env`, personal permission choices.
- **Per-tool permissions never belong in tracked `settings.json`** at either scope — permission posture is personal.
- **Prefer project-level over global** for any permission specific to one project.

## MCP servers

- Never add, remove, or modify MCP server configurations (`~/.mcp.json`, project `.mcp.json`, `enabledMcpjsonServers`) without the user's explicit permission — always ask first.
- MCP servers belong at the narrowest scope: project `.mcp.json` unless truly universal (context7, brave-search).

## Path hygiene (for tracked config files)

- No hardcoded absolute paths (`/Users/…`, `/home/…`) or `<project>/` prefixes in tracked `.claude/` files — prefer `$HOME`, `~`, `$XDG_*`, templating vars, or relative `.claude/…` paths.
- Don't use `~/.claude/` for project-local items — use relative `.claude/`.

## Dynamic content in agents/skills

- **Never hardcode dynamic content.** Filenames, folder trees, and enumerations derived from live source data must not appear as concrete names — use patterns (`<group-key>-paths.md`); only truly static names are allowed.
- **Agents discover dynamically** — they scan source at runtime following naming conventions; no pre-built list of outputs.
