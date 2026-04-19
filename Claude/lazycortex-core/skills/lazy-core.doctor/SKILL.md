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

## Phase 0 — Mode detection

Detect mode at the start of the run; pass the result to every dispatched agent and to Phase 2.6.

- **Local tool mode** — this repo *authors* plugins. Detected by `Glob("Claude/**/.claude-plugin/plugin.json")` returning any match. Every content check also applies to plugin sources under `Claude/**` (see per-agent scope expansions below). Outdated-plugin suppression (Phase 2.6) is **disabled** — the sources are authored here, so full integrity is required regardless of installed-plugin currency.
- **Release mode** (default) — this repo *consumes* installed plugins. Plugin-owned rule files in `.claude/rules/` and `~/.claude/rules/` are synced copies; if the owning plugin is outdated (per Phase 2.5), content-level findings on those files are suppressed by Phase 2.6 and only the version-outdated WARN is surfaced (upgrading will overwrite the stale content).

The per-plugin "owned namespaces" set computed by Agent A's Plugin rule sync check is the key used to decide plugin ownership of any given rule filename.

## Phase 1 — Dispatch parallel scans

Dispatch these three Explore agents **in a single message with three Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each prompt ends with the structured report contract from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` and a "Report under 400 words" budget.

### Agent A — artifact integrity

Scope: rules / agents / skills / commands files, their frontmatter, namespace format, hook scripts, gitignore coverage, cross-references, and `~/.claude/plugins/installed_plugins.json` (read-only).

**Local tool mode scope expansion**: when the coordinator reports local tool mode, also apply every rules / agents / skills / commands / hooks check below to the plugin sources at:

- `Claude/**/rules/*.md`
- `Claude/**/skills/*/SKILL.md`
- `Claude/**/agents/*.md`
- `Claude/**/commands/*.md`
- `Claude/**/hooks/**`

Findings from plugin sources must carry a `source: plugin` marker so Phase 2.6 can distinguish them from release-mode sync'd copies.

**Plugin-ownership tagging (both modes)**: when emitting any finding on a file under `.claude/rules/` or `~/.claude/rules/`, record `plugin_owner: <name>` if the filename's leading dot-segment matches an installed plugin's owned namespace (see Plugin rule sync check). Leave the field absent for user-authored rules. Phase 2.6 uses this to suppress release-mode findings on outdated plugins.

Checks the agent performs:

- **Rules files** (`.claude/rules/*.md`, `~/.claude/rules/*.md`):
  - `[FAIL]` rules file > 3 KB
  - `[WARN]` contains a **broken artifact reference** — any of the below that doesn't exist at its expected location:
    - slash-command `/name` → no matching skill/command found
    - `Agent(subagent_type: "plugin:name")` or `subagent_type: "X"` → no matching agent/skill
    - `<namespace>.<name>.md` literal filename mentioned → file not present in rules dir
    - `references/...` or `${CLAUDE_PLUGIN_ROOT}/references/...` path → file missing
    - `hooks/...` script path → file missing
    - `skills/<name>/SKILL.md` path → file missing
    Markdown section headings (`## Phase 2.5`) are NOT checked — internal document structure.
  - `[FAIL]` contains code blocks > 10 lines
  - `[WARN]` no YAML frontmatter (need at minimum `description`, plus scope or waiver — see next bullet)
  - `[WARN]` frontmatter has **neither `paths:` scope nor `always_loaded:` waiver** — every unscoped rule burns tokens on every turn for every user. A rule must either declare a folder scope (`paths: ["glob", ...]` — only loaded when matching files are touched) or carry a short `always_loaded: <one-line reason>` waiver justifying why it must be in context every turn (e.g. governs every skill, constrains the main agent, encodes a safety posture applied to every action). The value IS the waiver — empty / boolean `true` is not accepted. Finding: `rule lacks scope and waiver | <path>`; `detail: frontmatter has neither paths nor always_loaded`; `fix: add paths: ["<glob>"] if scoped, or always_loaded: <reason> if truly global`. Coordinator-owned fix.
  - `[FAIL]` filename lacks dot separator (must be `namespace.name.md`)
- **Agents** (`.claude/agents/*.md`):
  - `[FAIL]` missing / malformed frontmatter (`name`, `description`, `tools`)
  - `[WARN]` references a missing rules file
  - `[FAIL]` agent definition > 20 KB
- **Skills + commands** (`.claude/skills/*/SKILL.md`, `~/.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `~/.claude/commands/*.md`):
  - `[FAIL]` SKILL.md missing frontmatter (`name`, `description`)
  - `[WARN]` skill name in frontmatter doesn't match directory name
  - `[WARN]` skill references tools / agents that don't exist
  - `[WARN]` command file empty or < 50 bytes
- **Namespace** (skills / commands / agents / hooks / rules, skip `@`-prefixed external plugins):
  - `[FAIL]` name lacks dot separator
- **Hook-language gitignore coverage**: if project has `*.py`, `.gitignore` must cover `__pycache__/` and `*.py[cod]`; `*.rb` → `*.rbc`; `*.js`/`*.ts`/`package.json` → `node_modules/`. `[WARN]` when missing, only for languages actually used.
- **Cross-reference integrity**:
  - `[WARN]` agent referenced in CLAUDE.md but file missing
  - `[WARN]` command listed in CLAUDE.md but file missing
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
  - `[WARN]` project `CLAUDE.md` references paths that don't exist
  - `[WARN]` project `CLAUDE.md` > 10 KB
  - `[WARN]` global `CLAUDE.md` contains project-specific instructions
- **Always-loaded context budget** — sum the byte size of everything Claude Code auto-loads into every session's context on every turn:
  - `~/.claude/CLAUDE.md`
  - `<project>/.claude/CLAUDE.md`
  - Every `~/.claude/rules/*.md` **without** a `paths:` key in YAML frontmatter (scoped rules only load when files under their glob are touched, so they don't count toward the always-loaded budget)
  - Every `<project>/.claude/rules/*.md` **without** a `paths:` key in YAML frontmatter
  Thresholds: `[WARN]` total > 20 KB, `[FAIL]` total > 40 KB. This is the real token budget — individual per-file limits are a crude proxy; the sum is what hits every turn. Finding must list per-file breakdown (largest first) so the user knows what to cut.
- **Hooks** (registered in global `settings.json` under `hooks.*`):
  - `[FAIL]` hook command references a missing script
  - `[WARN]` hook script imports a module that is **not stdlib AND not declared in a project dependency manifest** (`requirements.txt`, `pyproject.toml`, `package.json`, `Gemfile`, `Cargo.toml` — match by interpreter). Declared third-party deps are fine; undeclared ones create install risk for teammates and slow every hook invocation.
  - `[WARN]` hook timeout > 10s
  - `[WARN]` hook scripts contain hardcoded project paths without sidecar configs
- **MCP server configuration** — check `~/.claude/settings.json`, `~/.claude/settings.local.json`, project `.claude/settings.json`, `~/.mcp.json`, `.mcp.json`:
  - Determine mode first: Mode A (`enableAllProjectMcpServers: true`) or Mode B (explicit `enabledMcpjsonServers`).
  - `[FAIL]` any `.mcp.json` malformed
  - Mode A only: suppress "declared but not enabled" warnings.
  - Mode B only: `[WARN]` server in project `.mcp.json` but absent from any `enabledMcpjsonServers`; `[WARN]` non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere
  - Always: `[WARN]` name in `enabledMcpjsonServers` but not defined in project `.mcp.json` or `~/.mcp.json`
- **MCP permission wildcard detection** — Claude Code matches `permissions.allow` / `permissions.ask` / `permissions.deny` entries as **exact strings**. Wildcards (`*`, `?`) and brace expansions (`{foo,bar}`) in MCP permission entries are silently no-ops: the entry never matches any real tool call, so the "allow" or "ask" never takes effect and every invocation falls through to the default per-call prompt. Scan every permissions file (all four settings files listed above) and flag:
  - `[WARN]` MCP permission entry contains a wildcard — `entry matches /^mcp__/ AND entry contains any of: *, ?, {`. Finding: `MCP permission entry will never match — wildcards/braces are not expanded | <path>`; `detail:` quote the offending entry (e.g. `mcp__github__*`) and the owning list (`allow` / `ask` / `deny`); `fix: enumerate the exact mcp__<server>__<tool> names via lazy-guard.allow-mcp <server>` — that skill reads the runtime tool list and writes concrete entries.
  - A leading `^mcp__` guard on the regex avoids flagging non-MCP entries like `Bash(git push *)` or `Read(~/.claude/**)` which legitimately use Claude Code's own glob matcher. Only `mcp__*` entries are affected by this restriction.
- **MCP permissions hygiene** — for every *enabled* MCP server, verify that destructive tools aren't sitting in `allow`. The doctor **does not** flag "missing" tools — `skip` is a valid classification and per-call prompting is the intended fallback. The doctor also **does not** flag medium-risk (`skip`-classified) tools that the user pinned into `allow` or `ask` — that's a deliberate user decision, not a hygiene issue. Completeness and bucket re-shuffling are `lazy-guard.allow-mcp`'s job when the user invokes it; here we only catch truly destructive entries sitting in `allow` where they bypass confirmation.
  - Enumerate runtime tools by listing every tool name visible in your own tool list whose name matches `mcp__<server>__<tool>`, grouped by `<server>`. Do NOT invent names — only use names literally present. Claude Code matches exact strings in both `allow` and `ask`; no wildcards.
  - A server counts as *enabled* iff it's defined in `~/.mcp.json` or `./.mcp.json` AND (Mode A, OR listed in `enabledMcpjsonServers` in either `./.claude/settings.json` or `./.claude/settings.local.json`). Skip servers that are defined-but-disabled, and skip servers that produced zero runtime tools (the server isn't loaded — a restart issue, not a permissions issue).
  - Resolve the target settings file per server using the routing rule from `lazy-guard.allow-mcp` Phase 4: default target is **`settings.local.json`** at the scope matching the server definition (global servers → `~/.claude/settings.local.json` if the user registered globally; else `./.claude/settings.local.json`). Doctor checks both the target and the paired tracked `settings.json` (for leakage).
  - Classify each runtime tool using the 3-bucket classifier from `lazy-guard.allow-mcp` Phase 3:
    - **`allow`** — read verbs (get/list/search/query/recall/reflect/resolve/diff/status/show/log-as-read/fetch/refresh/audit) AND low-risk writes the user already trusts (`git_add`, `git_create_branch`, `retain`, `sync_retain`, `create_directive`, `create_mental_model`, `update_bank`, `update_mental_model`).
    - **`ask`** — irreversible destruction: `delete_*`, `remove_*`, `clear_*`, `reset*`, `checkout*`, `restore*`, `revert*`, force-pushes, bulk destructive ops.
    - **`skip`** — medium-risk verbs that should *not* be in either list: `commit*`, `cancel_*`, and anything ambiguous. Skipped tools trigger Claude Code's per-call prompt.
  - Two comparisons per server (on the target `settings.local.json`):
    1. `misclassified_destructive = { t ∈ permissions.allow : t matches mcp__<server>__* AND classifier(t) == "ask" }` → `[WARN] Destructive MCP tools in allow list: <server> (<N> entries) | <target>`; `detail:` list the mis-placed tool names (`should be in permissions.ask — they cause irreversible loss and must prompt each time`); `fix: run lazy-guard.allow-mcp <server>` — allow-mcp will move them.
    2. `leaked_into_tracked = { t ∈ (tracked.permissions.allow ∪ tracked.permissions.ask) : t matches mcp__<server>__* }` → covered by the "Permissions leakage into tracked `settings.json`" check above; cross-reference but don't double-emit.
  - Emit at most one finding per server (misclassified). Do NOT emit per-tool findings — grouped lines keep the report scannable. Medium-risk (`skip`-classified) tools pinned to `allow` or `ask` are a user decision and never a finding.

### Agent C — path hygiene

Scope: every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`), grepping for hardcoded paths.

**Local tool mode scope expansion**: when the coordinator reports local tool mode, also grep for the same hardcoded-path patterns across `Claude/**/rules/*.md`, `Claude/**/skills/*/SKILL.md`, `Claude/**/agents/*.md`, `Claude/**/commands/*.md`, and `Claude/**/hooks/**`. Self-referential documentation of the path-hygiene rule itself (files whose purpose is to describe the bad patterns — e.g. `lazy-core.hygiene.md`, `lazy-guard.security.md`, `lazy-core.doctor/SKILL.md`, `lazy-guard.check-public/SKILL.md`) must be excluded via the `source: doc-of-rule` marker to avoid false positives.

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
4. **Parse remote manifests.** Extract `plugins[].name` and `plugins[].version` from each refreshed `marketplace.json`. A marketplace entry without a `version` field is *unversioned* — the manifest format doesn't carry versions (e.g. GCS-distributed tarballs) so currency is not decidable.
5. **Compare.** For each installed plugin, look up the marketplace entry by name. **Skip the comparison silently** (no finding of any severity) when either side lacks a comparable version:
   - Installed `version` is missing, empty, or `"unknown"` in `installed_plugins.json`.
   - Marketplace entry has no `version` field.
   Otherwise compare version strings with plain equality — no semver parsing. A genuine downgrade (marketplace moved backwards) is still surfaced; acceptable.
6. **Emit findings** into the merged list rendered by Phase 4.

Findings are emitted only for plugins where both sides carry a comparable version AND the versions differ. Unversioned plugins (either side) are not a doctor concern — reinstalling doesn't change the manifest format, so warning the user is noise.

Finding schema:

- Outdated plugin:
  `[WARN] plugin <name>@<mp> is outdated (<installed> → <latest>) | installed_plugins.json`
  `detail: scope=<user|project> | path=<installPath>`
  `fix: run `/plugin update <name>` or `/plugin install <name>@<mp>` to upgrade`
- Marketplace cache fallback (one per unreachable marketplace):
  `[INFO] marketplace <mp> unreachable — using cached manifest (last updated <lastUpdated>)`

Worst-case latency: 5 s × number of referenced marketplaces (sequential today; parallelize if it bites).

## Phase 2.6 — Release-mode outdated-plugin suppression

Runs after Phase 2.5, before delegated audits. **Skipped entirely in local tool mode** (Phase 0 disables it — plugin sources are authored here, so every check must surface).

Build the outdated set from Phase 2.5:

- `outdated_plugins = { p : Phase 2.5 emitted the "outdated" WARN for p }`

Filter the merged findings in place:

- For any finding whose `path` starts with `.claude/rules/` or `~/.claude/rules/` AND whose `plugin_owner` field (set by Agent A) is in `outdated_plugins`, **drop the finding from the merged list** and increment a `suppressed_by_outdated_plugin` counter keyed by plugin.
- Findings with no `plugin_owner` (user-authored rules) are never suppressed.
- Findings from Agent A Plugin rule sync (drift / orphan) are never suppressed — drift is exactly what an upgrade resolves, and the finding itself is the pointer.
- Findings from any other agent / scope (Agent B, Agent C, cross-reference integrity, etc.) are never suppressed.

For each plugin with a non-zero `suppressed_by_outdated_plugin` counter, emit one summary line alongside the existing version WARN:

`[INFO] <N> content findings on <plugin>-owned rules suppressed — upgrade via `/plugin update <name>` to re-validate.`

This keeps the user focused on the root cause (stale install) instead of chasing content issues that the upgrade will overwrite. Re-run the doctor after upgrading to surface any remaining issues.

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
- Missing rules frontmatter → add `---\ndescription: ...\npaths: [...]\n---` for scoped rules, or `---\ndescription: ...\nalways_loaded: <one-line reason>\n---` for rules that must load every turn.
- Rule lacks scope AND waiver → ask the user, per rule, whether the rule is legitimately always-loaded. If yes, add `always_loaded: <reason>` (reason must be substantive — one line explaining *why* every turn needs it, not `true`). If no, add `paths: ["<glob>"]` narrowing it to the folders where it applies. Show the proposed frontmatter diff before writing. Never auto-pick a scope — only the user knows the rule's true audience.
- Memory index: add missing entries, remove broken links; flag stale for review.
- Settings leakage: offer to move entries between files (respect the split in `rules/lazy-core.hygiene.md`).
- Permissions leakage into tracked `settings.json`: offer an in-place migration — move the entire `permissions.*` block (both `allow` and `ask` arrays) from tracked `settings.json` to the paired `settings.local.json`. Merge with any existing entries there, preserving order and deduplicating. Leave `enabledPlugins`, `hooks`, `env`, `enabledMcpjsonServers`, and similar enablement flags in the tracked file untouched. Show the diff before writing; apply only on explicit user confirmation.
- Gitignore coverage: append missing patterns under a dedicated language section.
- Path hygiene: replace hardcoded paths with relative equivalents; show diff before applying.
- MCP enablement: either set `enableAllProjectMcpServers: true` in global settings or add `enabledMcpjsonServers` to project settings; remove stale entries.
- MCP tools not whitelisted: invoke `lazy-guard.allow-mcp <server>` for each confirmed finding — do NOT write `permissions.allow` directly from doctor. `allow-mcp` owns scope-routing, dedup, and cross-scope cleanup; reusing it keeps both skills consistent.
- Agents / skills / CLAUDE.md / hook scripts — report only, never auto-edit.
- Plugin dependency warnings — report only; fixing requires enabling the missing plugin in `settings.json` (user's decision) or editing the declaring plugin's manifest.
- Plugin outdated / unrecorded version (Phase 2.5) — report only; direct the user to run `/plugin update <name>` or reinstall. Doctor never shells out to `claude plugin update`. In release mode, Phase 2.6 suppresses content findings on this plugin's owned rules — the suppression counter is surfaced so the user knows to re-run after upgrading.

For any finding surfaced by a delegated audit (Guard / Logging), direct the user to run that sibling skill for fixes. Doctor never auto-fixes issues owned by sibling audits.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
