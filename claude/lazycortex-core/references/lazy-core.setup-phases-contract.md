---
description: Contract for the `lazy_setup_phase:` frontmatter key — allowed values, ordering inside `lazy-core.setup`, the companion `requires_live_session:` key, the chained-from-inside-another-install anti-pattern, and the canonical resolution of a repo's enabled plugin set.
---
# `lazy_setup_phase` frontmatter contract

Skills opt into the `lazy-core.setup` meta-installer by declaring `lazy_setup_phase:` in their `SKILL.md` frontmatter. The meta-installer discovers participating skills dynamically — no central registry to edit.

## Allowed values

- `pre-install` — runs before any plugin templates land. Reserved for future use.
- `per-plugin` — implicit for any skill whose directory matches `*.install`. Declaring this key on a `*.install` skill is unnecessary; declaring it on a non-install skill forces it to run alongside installers.
- `post-install` — cross-cutters that depend on plugin templates already being in place (e.g. permission registrars, model-tier wizards).

Any other value is a `WARN` finding from `lazy-core.audit`.

## Ordering inside `lazy-core.setup`

1. All `pre-install` skills, alphabetical.
2. All `per-plugin` skills (any directory matching `*.install`), with `lazy-core.install` first, then alphabetical.
3. All `post-install` skills, alphabetical.

## Resolving a repo's enabled plugin set

The plugins "enabled in a repo" are the union of the `enabledPlugins` maps in `<repo>/.claude/settings.json` and `<repo>/.claude/settings.local.json` — every key whose value is `true`. Each key has the form `<plugin>@<marketplace>`; strip the `@<marketplace>` suffix to get the plugin name.

This union is the **only** authority for which install chains apply to a repo. The machine-wide registry `~/.claude/plugins/installed_plugins.json` is a union of every project's plugins on the host (entries carry `scope: project` + `projectPath`) and MUST NOT be read as an enablement signal — it is consulted solely to resolve a plugin's `installPath` (any entry for that plugin will do; the cache path is per-plugin-version, not per-project).

A plugin enabled in the repo but absent from the machine registry/cache is reported as `skipped: plugin not installed on this machine`, never a hard failure.

The interactive `lazy-core.setup` runs inside the project's own session, where the enabled set is naturally the project's. The cross-repo agents `lazy-core.autosetup` and `lazy-core.autocheckup` have no such session context — they resolve the enabled set explicitly against `repo=` per this section, so a dispatching session's machine-wide view never leaks foreign install chains into the target repo.

## Companion key: `requires_live_session`

A participating skill whose execution depends on live-session resources that exist only in an interactive Claude Code session (e.g. loaded `mcp__<server>__*` tools) declares:

```yaml
requires_live_session: true
```

- **Interactive `lazy-core.setup`** ignores the key — the skill runs normally in its phase.
- **Non-interactive executors** (`lazy-core.autosetup`) exclude the skill at discovery and report its line as `skipped: live-session-only` — never `failed`, never `needs-interactive`. A headless subagent structurally cannot satisfy the dependency, so executing (or retrying) it is pure noise.

Concrete example: `lazy-guard.allow-mcp` enumerates live `mcp__*` tool schemas in its classify phase; subagents have no MCP tools, so it carries the key.

## Anti-pattern: chained-from-inside-another-install

If skill A is already invoked from inside skill B's install flow, A MUST NOT also carry `lazy_setup_phase:`. Double-running re-prompts the user and breaks idempotence.

Concrete example: `lazy-obsidian.iconize-install` is chained from `lazy-obsidian.install`. It does not carry the frontmatter key.

## How to opt in

Add a single line to the skill's frontmatter:

```yaml
lazy_setup_phase: post-install
```

That is the only edit needed; `lazy-core.setup` discovers and orders the skill on its next run.

## Enforcement

`lazy-core.audit` Agent B greps every `SKILL.md` for the `lazy_setup_phase:` key and emits `WARN` when the value is outside `{pre-install, per-plugin, post-install}`. There is no `FAIL` severity here — the meta-installer treats unknown values as opt-out, but flags them for author attention.
