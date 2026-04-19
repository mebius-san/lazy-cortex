---
name: lazy-core.doctor
description: "Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, checks that installed plugins are at the latest marketplace version, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(wc *), Bash(mkdir -p *), Bash(python3 *)
---

# Project Health Check

Coordinator skill. Dispatches three **Explore** subagents in parallel to scan the project, merges their reports, presents a unified report, then applies user-confirmed fixes.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern. Severity vocabulary: `PASS` / `WARN` / `FAIL`, plus `INFO` (reserved for Phase 2.5 transient status lines — e.g. "marketplace unreachable, used cached manifest" — that don't require a user fix).

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
  - `[WARN]` global `settings.local.json` non-empty (except entries added via `lazy-guard.allow-mcp` with the user's explicit global-scope choice)
  - `[WARN]` duplicate permission entries across global + project files
  - `[WARN]` project `settings.json` (tracked) contains machine-specific paths
- **Permissions leakage into tracked `settings.json`** (both `~/.claude/settings.json` and `./.claude/settings.json`):
  - Per-tool permission entries are personal and should live in the paired `settings.local.json` (gitignored), not in tracked `settings.json` where they ship to every teammate who clones the repo / dotfiles.
  - `[WARN]` tracked file has a `permissions.allow` or `permissions.ask` array containing any entry. Finding: `tracked settings file owns per-tool permissions — these leak to teammates | <path>`; `detail:` count of entries in each list; `fix: migrate permissions.* block to <paired settings.local.json>` (coordinator-owned fix — see Phase 4).
  - Tracked `settings.json` may still own `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, `env` (non-secret), and similar enablement flags that teammates legitimately share. Only `permissions.*` is flagged.
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
- **MCP permissions hygiene** — for every *enabled* MCP server, verify that (a) destructive tools aren't sitting in `allow`, and (b) medium-risk tools haven't been pinned into either list. The doctor **does not** flag "missing" tools — `skip` is a valid classification and per-call prompting is the intended fallback. Completeness is `lazy-guard.allow-mcp`'s job when the user invokes it; here we only catch *wrong-bucket* entries.
  - Enumerate runtime tools by listing every tool name visible in your own tool list whose name matches `mcp__<server>__<tool>`, grouped by `<server>`. Do NOT invent names — only use names literally present. Claude Code matches exact strings in both `allow` and `ask`; no wildcards.
  - A server counts as *enabled* iff it's defined in `~/.mcp.json` or `./.mcp.json` AND (Mode A, OR listed in `enabledMcpjsonServers` in either `./.claude/settings.json` or `./.claude/settings.local.json`). Skip servers that are defined-but-disabled, and skip servers that produced zero runtime tools (the server isn't loaded — a restart issue, not a permissions issue).
  - Resolve the target settings file per server using the routing rule from `lazy-guard.allow-mcp` Phase 4: default target is **`settings.local.json`** at the scope matching the server definition (global servers → `~/.claude/settings.local.json` if the user registered globally; else `./.claude/settings.local.json`). Doctor checks both the target and the paired tracked `settings.json` (for leakage).
  - Classify each runtime tool using the 3-bucket classifier from `lazy-guard.allow-mcp` Phase 3:
    - **`allow`** — read verbs (get/list/search/query/recall/reflect/resolve/diff/status/show/log-as-read/fetch/refresh/audit) AND low-risk writes the user already trusts (`git_add`, `git_create_branch`, `retain`, `sync_retain`, `create_directive`, `create_mental_model`, `update_bank`, `update_mental_model`).
    - **`ask`** — irreversible destruction: `delete_*`, `remove_*`, `clear_*`, `reset*`, `checkout*`, `restore*`, `revert*`, force-pushes, bulk destructive ops.
    - **`skip`** — medium-risk verbs that should *not* be in either list: `commit*`, `cancel_*`, and anything ambiguous. Skipped tools trigger Claude Code's per-call prompt.
  - Three comparisons per server (on the target `settings.local.json`):
    1. `misclassified_destructive = { t ∈ permissions.allow : t matches mcp__<server>__* AND classifier(t) == "ask" }` → `[WARN] Destructive MCP tools in allow list: <server> (<N> entries) | <target>`; `detail:` list the mis-placed tool names (`should be in permissions.ask — they cause irreversible loss and must prompt each time`); `fix: run lazy-guard.allow-mcp <server>` — allow-mcp will move them.
    2. `pinned_medium_risk = { t : t matches mcp__<server>__* AND classifier(t) == "skip" AND t ∈ (permissions.allow ∪ permissions.ask) }` → `[WARN] Medium-risk MCP tools pinned into allow/ask: <server> (<N> entries) | <target>`; `detail:` list tool names and which list they're in (`medium-risk — should be skipped from both lists so Claude Code prompts per call`); `fix: run lazy-guard.allow-mcp <server>` — it will remove them.
    3. `leaked_into_tracked = { t ∈ (tracked.permissions.allow ∪ tracked.permissions.ask) : t matches mcp__<server>__* }` → covered by the "Permissions leakage into tracked `settings.json`" check above; cross-reference but don't double-emit.
  - Emit at most two findings per server (misclassified + pinned). Do NOT emit per-tool findings — grouped lines keep the report scannable.

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

## Phase 2.5 — Plugin version currency

Coordinator-owned inline check (not an Explore agent — it performs a `git fetch`, which violates the parallel-scan read-only contract). Runs in the main session after the merge above and before delegated audits.

Steps:

1. **Collect installed plugins.** Read `~/.claude/plugins/installed_plugins.json`. Keep only entries whose scope applies to this project: `scope: "user"`, OR `scope: "project"` with `projectPath` equal to the current repo path. Same filter Agent A already uses.
2. **Group by marketplace.** Strip the `@<marketplace>` suffix from each top-level key → `{ marketplace → [plugin entries] }`.
3. **Refresh each referenced marketplace (live).** Read `~/.claude/plugins/known_marketplaces.json` to resolve each marketplace's `source` and `installLocation`. For each:
   - If `source.source == "github"`: run `git -C <installLocation> fetch --quiet origin` with a **5-second timeout** (`timeout 5 git ...` on Linux, `gtimeout` or `perl -e 'alarm 5; exec @ARGV'` fallbacks on macOS). Then read the latest manifest via `git show origin/HEAD:.claude-plugin/marketplace.json`. Non-destructive — working tree untouched, only remote-tracking refs advance.
   - On fetch timeout, fetch failure, or parse failure: fall back to the on-disk `<installLocation>/.claude-plugin/marketplace.json` and emit one `[INFO]` line (see schema).
   - Non-github sources (none today): read the cached manifest directly and treat as fallback.
4. **Parse remote manifests.** Extract `plugins[].name` and `plugins[].version` from each refreshed `marketplace.json`.
5. **Compare.** For each installed plugin, look up the marketplace entry by name and compare version strings with plain equality — no semver parsing. A genuine downgrade (marketplace moved backwards) is still surfaced; acceptable.
6. **Emit findings** into the merged list rendered by Phase 4.

Finding schema:

- Outdated plugin:
  `[WARN] plugin <name>@<mp> is outdated (<installed> → <latest>) | installed_plugins.json`
  `detail: scope=<user|project> | path=<installPath>`
  `fix: run `/plugin update <name>` or `/plugin install <name>@<mp>` to upgrade`
- Unrecorded installed version (installed_plugins.json has `version: "unknown"`):
  `[WARN] plugin <name>@<mp> has unrecorded version (installed_plugins.json shows "unknown") | installed_plugins.json`
  `detail: latest in marketplace: <latest>`
  `fix: reinstall via `/plugin install <name>@<mp>` so the version is recorded`
- Marketplace cache fallback (one per unreachable marketplace):
  `[INFO] marketplace <mp> unreachable — using cached manifest (last updated <lastUpdated>)`

Worst-case latency: 5 s × number of referenced marketplaces (sequential today; parallelize if it bites).

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
- Permissions leakage into tracked `settings.json`: offer an in-place migration — move the entire `permissions.*` block (both `allow` and `ask` arrays) from tracked `settings.json` to the paired `settings.local.json`. Merge with any existing entries there, preserving order and deduplicating. Leave `enabledPlugins`, `hooks`, `env`, `enabledMcpjsonServers`, and similar enablement flags in the tracked file untouched. Show the diff before writing; apply only on explicit user confirmation.
- Gitignore coverage: append missing patterns under a dedicated language section.
- Path hygiene: replace hardcoded paths with relative equivalents; show diff before applying.
- MCP enablement: either set `enableAllProjectMcpServers: true` in global settings or add `enabledMcpjsonServers` to project settings; remove stale entries.
- MCP tools not whitelisted: invoke `lazy-guard.allow-mcp <server>` for each confirmed finding — do NOT write `permissions.allow` directly from doctor. `allow-mcp` owns scope-routing, dedup, and cross-scope cleanup; reusing it keeps both skills consistent.
- Agents / skills / CLAUDE.md / hook scripts — report only, never auto-edit.
- Plugin dependency warnings — report only; fixing requires enabling the missing plugin in `settings.json` (user's decision) or editing the declaring plugin's manifest.
- Plugin outdated / unrecorded version (Phase 2.5) — report only; direct the user to run `/plugin update <name>` or reinstall. Doctor never shells out to `claude plugin update`.

For any finding surfaced by a delegated audit (Guard / Logging), direct the user to run that sibling skill for fixes. Doctor never auto-fixes issues owned by sibling audits.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
