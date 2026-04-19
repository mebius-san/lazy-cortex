---
name: lazy-core.doctor
description: "Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(wc *), Bash(mkdir -p *), Bash(python3 *)
---

# Project Health Check

Coordinator skill. Dispatches three **Explore** subagents in parallel to scan the project, merges their reports, presents a unified report, then applies user-confirmed fixes.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern. Severity vocabulary: `PASS` / `WARN` / `FAIL`.

**CRITICAL PATH RULE** (applies to every dispatched agent): `~/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `~/.claude/`. Only project-root paths may use `wc -c`. For `~/.claude/` file sizes, estimate as `lines × 45 bytes`.

**Read-first**: collect all findings before any fix. Never fix silently.

## Phase 1 — Dispatch parallel scans

Dispatch these three Explore agents **in a single message with three Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each prompt ends with the structured report contract from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` and a "Report under 400 words" budget.

### Agent A — artifact integrity

Scope: rules / agents / skills / commands files, their frontmatter, namespace format, hook scripts, gitignore coverage, cross-references, and `~/.claude/plugins/installed_plugins.json` (read-only).

Checks the agent performs:

- **Rules files** (`.claude/rules/*.md`, `~/.claude/rules/*.md`):
  - `[FAIL]` rules file > 3 KB
  - `[WARN]` mentions an agent that doesn't exist in `.claude/agents/`
  - `[FAIL]` contains code blocks > 10 lines
  - `[WARN]` no `## Meta-rule` section explaining rules-vs-reference split, when any of:
    - file size > 2 KB (approaching the 3 KB FAIL threshold — a future split is likely), OR
    - a paired config agent exists (e.g. `.claude/agents/<namespace>.config.md` for `<namespace>.rules.md`), OR
    - file has ≥ 3 `##` subsections AND contains at least one fenced code block or Markdown table
    Pure-constraint rules (short, no code blocks/tables, no paired agent) are exempt.
  - `[WARN]` no YAML frontmatter (need `description`, optional `paths` glob)
  - `[FAIL]` filename lacks dot separator (must be `namespace.name.md`)
- **Agents** (`.claude/agents/*.md`):
  - `[FAIL]` missing / malformed frontmatter (`name`, `description`, `tools`)
  - `[WARN]` references a missing rules file
  - `[WARN]` missing `model` field
  - `[FAIL]` agent definition > 20 KB
  - `[WARN]` "Mandatory first step: read rules" but referenced rules file is empty / missing
- **Skills + commands** (`.claude/skills/*/SKILL.md`, `~/.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `~/.claude/commands/*.md`):
  - `[FAIL]` SKILL.md missing frontmatter (`name`, `description`)
  - `[WARN]` skill name in frontmatter doesn't match directory name
  - `[WARN]` skill references tools / agents that don't exist
  - `[WARN]` command file empty or < 50 bytes
- **Namespace** (skills / commands / agents / hooks / rules, skip `@`-prefixed external plugins):
  - `[FAIL]` name lacks dot separator
  - `[WARN]` namespace inconsistent with item's domain
- **Hook-language gitignore coverage**: if project has `*.py`, `.gitignore` must cover `__pycache__/` and `*.py[cod]`; `*.rb` → `*.rbc`; `*.js`/`*.ts`/`package.json` → `node_modules/`. `[WARN]` when missing, only for languages actually used.
- **Cross-reference integrity**:
  - `[WARN]` agent referenced in CLAUDE.md but file missing
  - `[WARN]` command listed in CLAUDE.md but file missing
  - `[WARN]` rules reference removed sections / features
  - `[FAIL]` `.claude/` contains files outside known patterns (`agents/*.md`, `rules/*.md`, `skills/*/SKILL.md`, `commands/*.md`, `settings*.json`)
- **Plugin dependencies** (read `~/.claude/plugins/installed_plugins.json`):
  - Build the installed-plugin set by stripping the `@<marketplace>` suffix from each top-level key, keeping only entries whose scope applies to this project (same filter the Phase 3 availability probes use: `scope: "user"`, or `scope: "project"` with `projectPath` matching the current repo).
  - For each installed plugin, read `<installPath>/.claude-plugin/plugin.json` and collect its `dependencies` array (default empty if absent).
  - `[WARN]` for each `<dep>` in that array where `<dep>` is not present in the installed-plugin set. Finding: `plugin <name> requires <dep> but <dep> is not installed — install it via its marketplace entry or remove the dependency`.
- **Plugin rule sync** (same installed-plugin set as above) — for each installed plugin that ships a `rules/` directory:
  - Glob `<installPath>/rules/*.md` → source-rule set; empty set → skip this plugin.
  - Compute the plugin's owned namespaces: the set of leading dot-segments from source-rule filenames (e.g. `lazy-log.logging.md` → `lazy-log`). One plugin may own multiple namespaces (e.g. `lazycortex-core` ships `lazy-core.*` and `lazy-guard.*`).
  - **Drift**: for each source rule whose filename also exists at `.claude/rules/<filename>` (or `~/.claude/rules/<filename>` for user-scoped installs), compare contents. If bytes differ → `[WARN] rule <filename> drifted from <plugin> source — run /<namespace>.install to reconcile (per-rule overwrite/keep-local/merge prompt)`.
  - **Orphan**: any file in target rules dir whose filename matches one of the plugin's owned namespaces but is NOT in the source-rule set → `[WARN] rule <filename> is an orphan from <plugin> (removed between versions) — run /<namespace>.install to offer deletion`.
  - Missing rules (in source but not in target) are NOT a finding — users deliberately skip rules at install time via the per-rule `AskUserQuestion` prompt.

Agent must not propose fixes beyond one-line hints — coordinator owns fixes.

### Agent B — config + memory

Scope: settings files, memory index, CLAUDE.md files, hook registration, MCP server enablement.

Checks the agent performs:

- **Settings consistency** — read all four:
  ```
  ~/.claude/settings.json          ~/.claude/settings.local.json
  .claude/settings.json            .claude/settings.local.json
  ```
  - `[FAIL]` any file is not valid JSON
  - `[FAIL]` project-specific permissions (service CLIs, `additionalDirectories`, service MCP servers, domain-specific WebFetch) in global `settings.json` instead of project `settings.local.json`
  - `[WARN]` global `settings.local.json` non-empty
  - `[WARN]` duplicate permission entries across global + project files
  - `[WARN]` project `settings.json` (tracked) contains machine-specific paths
- **Memory consistency** — locate project memory dir under `~/.claude/projects/*/memory/` matching the current project path:
  - `[FAIL]` `MEMORY.md` references a missing file
  - `[WARN]` memory `.md` exists but is not indexed in `MEMORY.md`
  - `[WARN]` `MEMORY.md` > 5 KB
  - `[WARN]` any memory file missing frontmatter (`name`, `description`, `type`)
  - `[WARN]` memory `type` not one of: `user`, `feedback`, `project`, `reference`
- **CLAUDE.md files**:
  - `[WARN]` project `CLAUDE.md` missing
  - `[WARN]` project `CLAUDE.md` references paths that don't exist
  - `[WARN]` project `CLAUDE.md` > 10 KB
  - `[WARN]` global `CLAUDE.md` contains project-specific instructions
- **Hooks** (registered in global `settings.json` under `hooks.*`):
  - `[FAIL]` hook command references a missing script
  - `[WARN]` hook script imports modules outside stdlib
  - `[WARN]` hook timeout > 10s
  - `[WARN]` hook scripts contain hardcoded project paths without sidecar configs
- **MCP server configuration** — check `~/.claude/settings.json`, `~/.claude/settings.local.json`, project `.claude/settings.json`, `~/.mcp.json`, `.mcp.json`:
  - Determine mode first: Mode A (`enableAllProjectMcpServers: true`) or Mode B (explicit `enabledMcpjsonServers`).
  - `[FAIL]` any `.mcp.json` malformed
  - Mode A only: suppress "declared but not enabled" warnings.
  - Mode B only: `[WARN]` server in project `.mcp.json` but absent from any `enabledMcpjsonServers`; `[WARN]` non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere
  - Always: `[WARN]` name in `enabledMcpjsonServers` but not defined in project `.mcp.json` or `~/.mcp.json`
- **MCP permissions completeness** — for every *enabled* MCP server, verify every tool it exposes is registered (in `permissions.allow` OR `permissions.ask`) in the correct settings file, and that destructive tools landed in `ask` rather than `allow`:
  - Enumerate runtime tools by listing every tool name visible in your own tool list whose name matches `mcp__<server>__<tool>`, grouped by `<server>`. Do NOT invent names — only use names literally present. Claude Code matches exact strings in both `allow` and `ask`; no wildcards.
  - A server counts as *enabled* iff it's defined in `~/.mcp.json` or `./.mcp.json` AND (Mode A, OR listed in `enabledMcpjsonServers` in either `./.claude/settings.json` or `./.claude/settings.local.json`). Skip servers that are defined-but-disabled, and skip servers that produced zero runtime tools (the server isn't loaded — a restart issue, not a permissions issue).
  - Resolve the target settings file per server using the routing table from `lazy-guard.allow-mcp` (SKILL.md Phase 4):
    - Global-defined server → `~/.claude/settings.json`
    - Project-defined server enabled via project `.claude/settings.json` (Mode A or Mode B) → `./.claude/settings.json`
    - Project-defined server enabled only via `./.claude/settings.local.json` → `./.claude/settings.local.json`
  - Classify each runtime tool as `read` (should live in `allow`) or `write` (should live in `ask`) using the same heuristic as `lazy-guard.allow-mcp` Phase 3: read verbs (get/list/search/query/recall/reflect/resolve/diff/status/show/log-as-read/fetch/refresh/audit) → `allow`; anything mutating (add/create/update/delete/remove/clear/write/commit/reset/push/force/retain/sync/set/cancel/checkout/merge/stash/rebase/restore/revert) → `ask`; default when uncertain → `ask`.
  - Two comparisons per server:
    1. `missing = runtime_tools \ (permissions.allow ∪ permissions.ask)` → `[WARN] MCP tools not registered: <server> (<N> missing) | <target>`; `detail:` list missing tool names, noting each tool's expected bucket in parens (e.g. `git_commit (ask)`, `git_status (allow)`); `fix: run lazy-guard.allow-mcp <server>`.
    2. `misclassified = { t ∈ permissions.allow : t matches mcp__<server>__* AND classifier(t) == "write" }` → `[WARN] Destructive MCP tools in allow list: <server> (<N> entries) | <target>`; `detail:` list the mis-placed tool names (`should be in permissions.ask — they mutate state and must prompt each time`); `fix: run lazy-guard.allow-mcp <server>` — allow-mcp's Phase 5 reconcile step will move them from `allow` to `ask`.
  - Emit at most two findings per server (one per check). Do NOT emit per-tool findings — grouped lines keep the report scannable.

### Agent C — path hygiene

Scope: every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`), grepping for hardcoded paths.

Checks the agent performs:

- `[FAIL]` file contains `/Users/` or `/home/` (hardcoded absolute user path)
- `[FAIL]` file contains `<project>/` prefix (use relative paths instead)
- `[WARN]` file contains `~/Dropbox/` or other user-specific home subdirectories
- `[WARN]` file references `~/.claude/` for something that is actually project-local

Allowed `~/.claude/` references (agent must exclude these from WARN):
- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json` / `~/.claude/settings.local.json`
- `~/.claude/rules/*.md`
- `~/.claude/skills/*/SKILL.md`
- `~/.claude/commands/*.md`
- `~/.claude/projects/*/memory/`
- `~/.mcp.json`

## Phase 2 — Collect + merge

Parse each returned block by splitting on `## scan:` headings. Deduplicate findings when two agents report the same `<path>:<line>` + title (happens rarely; A vs B overlap is minimal). Sum the three `### summary` blocks into overall `PASS / WARN / FAIL` counts.

## Phase 3 — Delegated audits (inline, not dispatched)

Doctor delegates to sibling audit skills for scope-specific checks rather than replicating their logic. Each sub-check verifies the sibling skill is reachable, then checks its run condition, and silently skips if either fails. Doctor never warns about missing sibling plugins.

Each delegation follows four steps:

1. **Availability probe** — is the sibling skill reachable?
2. **Run condition** — is the opt-in gate satisfied?
3. **On skip** — if either fails, skip silently; no entry in the report.
4. **On invoke** — fold the sibling's summary into a named subsection; direct the user to run the sibling for interactive fixes. Do NOT re-run its fix flow.

**11a. Public-repo guard** → `lazy-guard.check-public`
- *Availability*: `lazycortex-core` appears in `~/.claude/plugins/installed_plugins.json` for a scope applying to this project.
- *Run condition*: `.guard-waivers.json` exists at the repo root.
- *On invoke*: fold guard's summary (category × severity counts, waivered count) and FAIL/WARN findings into a **Guard** subsection.

**11b. Logging coverage** → `lazy-log.audit`
- *Availability*: `lazycortex-log` appears in `~/.claude/plugins/installed_plugins.json` for a scope applying to this project.
- *Run condition*: same as availability — plugin installation is the opt-in.
- *On invoke*: fold audit findings into a **Logging** subsection.

## Phase 4 — Present + fix

Render in the existing format:

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

(... one section per issue, followed by Guard and Logging subsections if delegated audits ran ...)

### Fixes available
- [ ] Fix 1: <description> (auto-fixable)
- [ ] Fix 2: <description> (auto-fixable)
- [ ] Fix 3: <description> (needs manual review)

Apply all auto-fixable? [y/N]
```

After the report, ask the user which fixes to apply. Apply only confirmed fixes. Fixes available in-coordinator:

- Rules oversized → suggest running `/lazy-core.optimize`; don't auto-slim here.
- Rule drift / orphans → direct the user to run the owning plugin's install skill (`/<namespace>.install`, e.g. `/lazy-log.install` for `lazy-log.*` rules). Do NOT auto-overwrite here — the install skill's per-rule `AskUserQuestion` is the sanctioned reconciliation flow.
- Missing rules frontmatter → add `---\ndescription: ...\npaths: [...]\n---` (use `paths` for scoped rules, omit for global rules).
- Memory index: add missing entries, remove broken links; flag stale for review.
- Settings leakage: offer to move entries between files (respect the split in `rules/lazy-core.hygiene.md`).
- Gitignore coverage: append missing patterns under a dedicated language section.
- Path hygiene: replace hardcoded paths with relative equivalents; show diff before applying.
- MCP enablement: either set `enableAllProjectMcpServers: true` in global settings or add `enabledMcpjsonServers` to project settings; remove stale entries.
- MCP tools not whitelisted: invoke `lazy-guard.allow-mcp <server>` for each confirmed finding — do NOT write `permissions.allow` directly from doctor. `allow-mcp` owns scope-routing, dedup, and cross-scope cleanup; reusing it keeps both skills consistent.
- Agents / skills / CLAUDE.md / hook scripts — report only, never auto-edit.
- Plugin dependency warnings — report only; fixing requires enabling the missing plugin in `settings.json` (user's decision) or editing the declaring plugin's manifest.

For any finding surfaced by a delegated audit (Guard / Logging), direct the user to run that sibling skill for fixes. Doctor never auto-fixes issues owned by sibling audits.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
