---
name: lazy-core.doctor
description: "Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(wc *), Bash(mkdir -p *), Bash(python3 *)
---

# Project Health Check

Systematically verify consistency of all Claude Code configuration in the current project. Report every issue found, then offer fixes. For scope-specific checks (public-repo guard, logging coverage), delegate to sibling audit skills — see check 11.

**CRITICAL PATH RULE**: `~/.claude/` is protected from Bash access (Claude Code's own config dir). Use ONLY Glob and Read tools for any path under `~/.claude/`. Use `wc -c` via Bash ONLY for paths under the project root (e.g., `.claude/`). To measure `~/.claude/` file sizes, use Read and estimate: **size ~ lines x 45 bytes**.

**This is a read-first skill.** Collect all issues before proposing any changes. Never fix silently — always show what's wrong and what the fix would be, then ask before applying.

## Checks

Run every check below. Track issues as: `[PASS]`, `[WARN]`, or `[FAIL]`.

### 1. Rules files

For each `.claude/rules/*.md` (project) and `~/.claude/rules/*.md` (global):

- `[FAIL]` if any rules file > 3 KB — should contain only short constraints, not reference material
- `[WARN]` if a rules file mentions an agent but no matching agent file exists in `.claude/agents/`
- `[FAIL]` if a rules file contains code blocks > 10 lines — that's reference material, belongs in agent
- `[WARN]` if a rules file has no meta-rule section explaining where new rules vs reference go
- `[WARN]` if a rules file has no YAML frontmatter — rules should have frontmatter with at least a `description` field; domain-specific rules should also have a `paths` glob so they load on-demand instead of at startup (e.g., `paths: ["dotfiles/Docker/n8n/**"]`)
- `[FAIL]` if the rules filename has no dot separator — must use `namespace.name.md` format (e.g., `lazy-log.logging.md`, not `logging.md`)

**Fix**: offer to run `lazy-core.optimize` to slim oversized rules. For missing frontmatter, add `---\ndescription: ...\npaths: [...]\n---` — use `paths` for rules scoped to specific files, omit `paths` for rules that apply globally.

### 2. Agent definitions

For each `.claude/agents/*.md`:

- `[FAIL]` if frontmatter is missing or malformed (needs `name`, `description`, `tools`)
- `[WARN]` if agent references a rules file that doesn't exist
- `[WARN]` if agent's `model` field is missing (will default to parent model)
- `[FAIL]` if agent definition > 20 KB — may need splitting or trimming
- `[WARN]` if agent has a "Mandatory first step: read rules" but the referenced rules file is empty or missing

**Fix**: report which fields to add/fix. Don't auto-edit agent definitions.

### 3. Skills and commands

For each `.claude/skills/*/SKILL.md` (project) and `~/.claude/skills/*/SKILL.md` (global):

- `[FAIL]` if SKILL.md is missing frontmatter (`name`, `description`)
- `[WARN]` if skill name in frontmatter doesn't match directory name
- `[WARN]` if skill references tools or agents that don't exist

For each `.claude/commands/*.md` (project) and `~/.claude/commands/*.md` (global):

- `[WARN]` if command file is empty or < 50 bytes

**Namespace check** for all custom skills, commands, agents, hooks, and rules (skip external plugins with `@`):

- `[FAIL]` if skill/command/agent/hook/rule name has no dot separator — must use `namespace.name` format (e.g., `config.sync` not `config-sync`; `lazy-log.logging.md` not `logging.md`)
- `[WARN]` if namespace is inconsistent with the item's domain (e.g., a deploy skill in `config.*`)
- Scope: `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/hooks/*`, `.claude/rules/*.md`, and their `~/.claude/...` equivalents

**Fix**: report issues. Don't auto-edit skills.

### 4. Settings consistency

Read all four settings files:
```
~/.claude/settings.json              (global tracked)
~/.claude/settings.local.json        (global local)
.claude/settings.json                (project tracked)
.claude/settings.local.json          (project local)
```

- `[FAIL]` if any file is not valid JSON
- `[FAIL]` if project-specific permissions (service CLIs, additionalDirectories, service MCP servers, domain-specific WebFetch) are in global `settings.json` instead of project `settings.local.json`
- `[WARN]` if global `settings.local.json` is non-empty (should be empty per lazy-guard.settings hook)
- `[WARN]` if duplicate permission entries exist across global and project files
- `[WARN]` if project `settings.json` (tracked) contains machine-specific paths

MCP server checks live in section 10 below, not here.

**Fix**: offer to move entries between files (respecting the split strategy from CLAUDE.md).

### 5. Memory consistency

Find the project memory directory at `~/.claude/projects/*/memory/` (match current project path).

- `[FAIL]` if `MEMORY.md` references a file that doesn't exist
- `[WARN]` if a memory `.md` file exists but isn't listed in `MEMORY.md`
- `[WARN]` if `MEMORY.md` > 5 KB (index is getting large, consider consolidation)
- `[WARN]` if any memory file has no frontmatter (`name`, `description`, `type`)
- `[WARN]` if memory file's `type` is not one of: `user`, `feedback`, `project`, `reference`

**Fix**: add missing index entries, remove broken links, flag stale memories for review.

### 6. CLAUDE.md files

- `[WARN]` if project `CLAUDE.md` is missing
- `[WARN]` if project `CLAUDE.md` references files/paths that don't exist in the repo
- `[WARN]` if project `CLAUDE.md` > 10 KB (consider splitting into rules/agents)
- `[WARN]` if global `CLAUDE.md` contains project-specific instructions (references to specific services, paths within a single project)

**Fix**: flag sections that might belong elsewhere. Don't auto-edit CLAUDE.md.

### 7. Hooks

For each hook registered in global `settings.json` under `hooks.*`:

- `[FAIL]` if the hook command references a script that doesn't exist
- `[WARN]` if a hook script imports modules that aren't in stdlib
- `[WARN]` if hook timeout is > 10s (may slow down interactions)
- `[WARN]` if hook scripts contain hardcoded project paths without sidecar configs

**Fix**: report missing scripts. For hardcoded paths, suggest sidecar extraction.

### 7b. Hook-language gitignore coverage

Hook scripts are commonly written in Python (and occasionally other compiled-on-import languages), which leave bytecode caches next to the source. These must be gitignored or they leak into commits.

Detect the languages actually used by scanning hook scripts and any other tracked executables under the project:

- If **any `*.py` file** exists anywhere in the project, `.gitignore` must cover `__pycache__/` and `*.py[cod]` (and ideally `*$py.class`). `[WARN]` if missing.
- If **any `*.rb`** exists, `.gitignore` should include `*.rbc`. `[WARN]` if missing.
- If **any Node-based hook** (`*.js`/`*.ts` or a `package.json`) exists, `.gitignore` should include `node_modules/`. `[WARN]` if missing.

Only emit a warning for a language that is actually in use — don't push boilerplate.

**Fix**: append the missing patterns to `.gitignore` under a dedicated language section.

### 8. Cross-reference integrity

- `[WARN]` if an agent is referenced in CLAUDE.md but the agent file doesn't exist
- `[WARN]` if a command is listed in CLAUDE.md but the command file doesn't exist
- `[WARN]` if rules reference sections/features that have been removed from the project
- `[FAIL]` if `.claude/` contains files not matching known patterns (agents/*.md, rules/*.md, skills/*/SKILL.md, commands/*.md, settings*.json)

**Fix**: report unexpected files. Don't auto-delete.

### 9. Path hygiene

For every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`), grep for hardcoded paths:

- `[FAIL]` if file contains `/Users/` or `/home/` — hardcoded absolute user paths break on other machines
- `[FAIL]` if file contains `<project>/` prefix — use relative paths (`.claude/...`, `CLAUDE.md`) instead
- `[WARN]` if file contains `~/Dropbox/` or other user-specific home subdirectories — these won't exist for coworkers
- `[WARN]` if file references `~/.claude/` for something that is actually project-local (e.g., project settings, project agents) — use relative `.claude/` instead

Allowed `~/.claude/` references (these are genuinely global per-user):
- `~/.claude/CLAUDE.md` (global instructions)
- `~/.claude/settings.json` / `~/.claude/settings.local.json` (global settings)
- `~/.claude/rules/*.md` (global rules)
- `~/.claude/skills/*/SKILL.md` (global skills)
- `~/.claude/commands/*.md` (global commands)
- `~/.claude/projects/*/memory/` (memory storage)
- `~/.mcp.json` (global MCP config)

**Fix**: replace hardcoded paths with relative equivalents. Show diff before applying.

### 10. MCP server configuration

Check global `~/.claude/settings.json` and project `.claude/settings.json`:

Either enablement mode is valid: global `"enableAllProjectMcpServers": true` (auto-enable every project-defined server) OR explicit `enabledMcpjsonServers` arrays in the project's `settings.json` / `settings.local.json`. Don't flag one in favor of the other.

**First, determine the enablement mode** by reading `~/.claude/settings.json` and `~/.claude/settings.local.json`:

- **Mode A — `enableAllProjectMcpServers: true`**: every server in the project's `.mcp.json` is implicitly enabled. The `enabledMcpjsonServers` arrays are irrelevant in this mode.
- **Mode B — `enableAllProjectMcpServers: false` or missing**: a server is enabled only if its name appears in `enabledMcpjsonServers` of project `.claude/settings.json` or `.claude/settings.local.json`.

Global servers in `~/.mcp.json` are always available regardless of mode.

Checks:

- `[FAIL]` if `.mcp.json` or `~/.mcp.json` contains malformed JSON
- **In Mode A only**: suppress all "declared but not enabled" warnings — every project `.mcp.json` entry is auto-enabled, so there is nothing to warn about. Do NOT emit a warning like "server X defined in .mcp.json but not in enabledMcpjsonServers" when `enableAllProjectMcpServers: true`.
- **In Mode B only**: `[WARN]` if a server is defined in project `.mcp.json` but its name is absent from `enabledMcpjsonServers` in both project settings files (declared but unused).
- **In Mode B only**: `[WARN]` if no `enabledMcpjsonServers` array exists anywhere in project settings AND the project has a non-empty `.mcp.json` — config must pick one of the two modes.
- Always: `[WARN]` if a server name appears in `enabledMcpjsonServers` but is not defined in project `.mcp.json` or `~/.mcp.json` (stale reference).

**Fix**: either set `enableAllProjectMcpServers: true` in global settings (broad, covers every project automatically) or add an `enabledMcpjsonServers` array to the project's `settings.json` / `settings.local.json` listing the server names you want. Remove stale names from `enabledMcpjsonServers` when the corresponding `.mcp.json` entry is gone.

### 11. Delegated audits

Doctor delegates to sibling audit skills for scope-specific checks rather than replicating their logic. **Each delegation must first verify the sibling skill is reachable, then check its run condition, and silently skip if either fails.** Doctor never warns about missing sibling plugins — it is not doctor's job to prescribe what a user should install.

Each sub-check follows the same four-part structure:

1. **Availability probe** — is the sibling skill reachable?
2. **Run condition** — is the opt-in gate for this check satisfied?
3. **On skip** — if either (1) or (2) fails, skip silently with no entry in the report.
4. **On invoke** — fold the sibling's summary into a named subsection, and direct the user to run the sibling directly for interactive fixes.

**11a. Public-repo guard** → `lazy-guard.check-public`

1. *Availability*: `lazy-guard.check-public` is reachable. It ships in the same plugin as doctor (`lazycortex-core`), but still verify — the plugin could be partially disabled at scope. Probe by confirming `lazycortex-core` appears in `~/.claude/plugins/installed_plugins.json` for a scope that applies to this project.
2. *Run condition*: `.guard-waivers.json` exists at the repo root (the same file the pre-commit hook uses as its opt-in signal).
3. *On skip*: no entry in the report.
4. *On invoke*: fold the guard's summary (category × severity counts, waivered count) and any FAIL/WARN findings into a **Guard** subsection. Do NOT re-run its interactive fix flow — direct the user to run `/lazy-guard.check-public` for fixes.

**11b. Logging coverage** → `lazy-log.audit`

1. *Availability*: `lazycortex-log` appears in `~/.claude/plugins/installed_plugins.json` for a scope that applies to this project (user scope, or project scope matching the current repo).
2. *Run condition*: same as availability for this sub-check — installation of the `lazycortex-log` plugin is the user's opt-in to its logging rules and audit.
3. *On skip*: no entry in the report.
4. *On invoke*: fold the audit's findings into a **Logging** subsection. Direct the user to run `/lazy-log.audit` for detail and fixes.

**Fix**: for any finding surfaced by a delegated skill, re-run that skill directly to access its fix flow. Doctor never auto-fixes issues owned by sibling audits.

## Output format

```markdown
## lazy-core.doctor -- Health Report

### Summary
- Checks run: N
- PASS: N | WARN: N | FAIL: N

### Issues

#### [FAIL] Rules: openclaw.md is 25 KB (limit: 3 KB)
Reference material should be in .claude/agents/openclaw-config.md.
**Fix**: Run `/lazy-core.optimize` to slim rules files.

#### [WARN] Memory: feedback_old_thing.md not in MEMORY.md index
File exists but has no index entry.
**Fix**: Add `- [old-thing](feedback_old_thing.md) — <description>` to MEMORY.md

(... one section per issue ...)

### Fixes available
- [ ] Fix 1: <description> (auto-fixable)
- [ ] Fix 2: <description> (auto-fixable)
- [ ] Fix 3: <description> (needs manual review)

Apply all auto-fixable? [y/N]
```

After showing the report, ask the user which fixes to apply. Apply only what's confirmed.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
