---
name: lazy-core.doctor
description: "Health check for Claude Code project configuration. Verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, checks that installed plugins are at the latest marketplace version, and delegates to sibling audit skills (lazy-guard.check-public, lazy-log.audit) when they apply. Reports issues and offers targeted fixes. Run periodically or when something feels off."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(wc *), Bash(mkdir -p *), Bash(python3 *), mcp__*__recall, mcp__*__retain
---
# Project Health Check

Coordinator skill. Dispatches three **Explore** subagents in parallel to scan the project, merges their reports, presents a unified report, then applies user-confirmed fixes.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern. Severity vocabulary: `PASS` / `WARN` / `FAIL`, plus `INFO` (reserved for Phase 2.5 transient status lines — e.g. "marketplace unreachable, used cached manifest" — that don't require a user fix).

**CRITICAL PATH RULE** (applies to every dispatched agent): `$HOME/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `$HOME/.claude/`. Only project-root paths may use `wc -c`. For `$HOME/.claude/` file sizes, estimate as `lines × 45 bytes`.

**Path expansion** (mandatory): Glob and Read do **not** shell-expand `~` or `$HOME`. Before any Glob/Read targeting a home-relative path, run `Bash(echo $HOME)` once and substitute the result (or read the absolute home path from the session env block). A literal `~/.claude/rules/*.md` or `$HOME/.claude/rules/*.md` passed to Glob will match nothing and silently report "empty".

**Read-first**: collect all findings before any fix. Never fix silently.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 0 — Mode detection`
   - `Phase 1 — Dispatch parallel scans`
   - `Phase 2 — Collect + merge`
   - `Phase 2.5 — Plugin version currency`
   - `Phase 2.6 — Release-mode outdated-plugin suppression`
   - `Phase 2.7 — Waiver reconciliation`
   - `Phase 3 — Delegated audits`
   - `Phase 4 — Present + fix + waive (Report)`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 0 — Mode detection

Detect mode at the start of the run; pass the result to every dispatched agent and to Phase 2.6.

- **Local tool mode** — this repo *authors* plugins. Detected by `Glob("claude/**/.claude-plugin/plugin.json")` returning any match. Every content check also applies to plugin sources under `claude/**` (see per-agent scope expansions below). Outdated-plugin suppression (Phase 2.6) is **disabled** — the sources are authored here, so full integrity is required regardless of installed-plugin currency.
- **Release mode** (default) — this repo *consumes* installed plugins. Plugin-owned rule files in `.claude/rules/` and `$HOME/.claude/rules/` are synced copies; if the owning plugin is outdated (per Phase 2.5), content-level findings on those files are suppressed by Phase 2.6 and only the version-outdated WARN is surfaced (upgrading will overwrite the stale content).

The per-plugin "owned namespaces" set computed by Agent A's Plugin rule sync check is the key used to decide plugin ownership of any given rule filename.

## Phase 1 — Dispatch parallel scans

Dispatch these three Explore agents **in a single message with three Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each prompt ends with the structured report contract from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` and a "Report under 400 words" budget.

### Agent A — artifact integrity

Scope: rules / agents / skills / commands files, their frontmatter, namespace format, hook scripts, gitignore coverage, cross-references, and `$HOME/.claude/plugins/installed_plugins.json` (read-only).

**Local tool mode scope expansion**: when the coordinator reports local tool mode, also apply every rules / agents / skills / commands / hooks check below to the plugin sources at:

- `claude/**/rules/*.md`
- `claude/**/skills/*/SKILL.md`
- `claude/**/agents/*.md`
- `claude/**/commands/*.md`
- `claude/**/hooks/**`

Findings from plugin sources must carry a `source: plugin` marker so Phase 2.6 can distinguish them from release-mode sync'd copies.

**Plugin-ownership tagging (both modes)**: when emitting any finding on a file under `.claude/rules/` or `$HOME/.claude/rules/`, record `plugin_owner: <name>` if the filename's leading dot-segment matches an installed plugin's owned namespace (see Plugin rule sync check). Leave the field absent for user-authored rules. Phase 2.6 uses this to suppress release-mode findings on outdated plugins.

Checks the agent performs:

- **Rules files** (`.claude/rules/*.md`, `$HOME/.claude/rules/*.md`): contract defined by `lazy-core.rule-writing`. Agent runs the checks enumerated there — mandatory frontmatter (`description` + `paths:` scope OR `always_loaded:` waiver), size budget (3 KB for `always_loaded:`, 10 KB WARN / 25 KB FAIL for `paths:`-scoped), no code blocks > 10 lines, dot-namespace filename, broken-artifact-reference scan, narrative-padding heuristic. Severities as defined in that rule. `lazy-core.rule-writing` auto-loads on this scan because the rule's `paths:` glob matches `.claude/rules/**`.
- **Agents** (`.claude/agents/*.md`):
  - `[FAIL]` missing / malformed frontmatter (`name`, `description`, `tools`)
  - `[WARN]` references a missing rules file
  - `[FAIL]` agent definition > 20 KB
- **Skills + commands** (`.claude/skills/*/SKILL.md`, `$HOME/.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `$HOME/.claude/commands/*.md`):
  - `[FAIL]` SKILL.md missing frontmatter (`name`, `description`)
  - `[WARN]` skill name in frontmatter doesn't match directory name
  - `[WARN]` skill references tools / agents that don't exist
  - `[WARN]` command file empty or < 50 bytes
- **Namespace** (skills / commands / agents / hooks / rules, skip `@`-prefixed external plugins):
  - `[WARN]` name lacks dot separator
- **Hook-language gitignore coverage**: if project has `*.py`, `.gitignore` must cover `__pycache__/` and `*.py[cod]`; `*.rb` → `*.rbc`; `*.js`/`*.ts`/`package.json` → `node_modules/`. `[WARN]` when missing, only for languages actually used.
- **Cross-reference integrity**:
  - `[WARN]` agent referenced in CLAUDE.md but file missing
  - `[WARN]` command listed in CLAUDE.md but file missing
- **Plugin dependencies** (read `$HOME/.claude/plugins/installed_plugins.json`):
  - Build the installed-plugin set by stripping the `@<marketplace>` suffix from each top-level key, keeping only entries whose scope applies to this project (same filter the Phase 3 availability probes use: `scope: "user"`, or `scope: "project"` with `projectPath` matching the current repo).
  - For each installed plugin, read `<installPath>/.claude-plugin/plugin.json` and collect its `dependencies` array (default empty if absent).
  - `[WARN]` for each `<dep>` in that array where `<dep>` is not present in the installed-plugin set. Finding: `plugin <name> requires <dep> but <dep> is not installed — install it via its marketplace entry or remove the dependency`.
- **Plugin rule sync** (same installed-plugin set as above) — for each installed plugin that ships a `rules/` directory:
  - Glob `<installPath>/rules/*.md` → source-rule set; empty set → skip this plugin.
  - Compute the plugin's owned namespaces: the set of leading dot-segments from source-rule filenames (e.g. `lazy-log.logging.md` → `lazy-log`). One plugin may own multiple namespaces (e.g. `lazycortex-core` ships `lazy-core.*` and `lazy-guard.*`).
  - **Drift**: for each source rule whose filename also exists at `.claude/rules/<filename>` (or `$HOME/.claude/rules/<filename>` for user-scoped installs), compare contents. If bytes differ → `[WARN] rule <filename> drifted from <plugin> source — run /<namespace>.install to reconcile (per-rule overwrite/keep-local/merge prompt)`.
  - **Orphan**: any file in target rules dir whose filename matches one of the plugin's owned namespaces but is NOT in the source-rule set → `[WARN] rule <filename> is an orphan from <plugin> (removed between versions) — run /<namespace>.install to offer deletion`.
  - Missing rules (in source but not in target) are NOT a finding — users deliberately skip rules at install time via the per-rule `AskUserQuestion` prompt.
- **`lazy.settings.json` validation** — process each scope (project + global) in the following order. The raw Read MUST come before the migrating helper call so that the root-`version` check sees the file before migration removes that key.

  **For each scope (project path `.claude/lazy.settings.json`, global path `$HOME/.claude/lazy.settings.json`):**

  1. **Raw Read first** — Read the file directly (no helper, no Bash for the global path — the CRITICAL PATH RULE applies). For the global path, resolve `$HOME` via `Bash(echo $HOME)` first, then use `Read` with the absolute path.
     - If the file is absent: emit `[INFO] lazy.settings.json absent at <path>` and skip all remaining checks for this scope.
     - If present: parse the raw JSON in memory for the checks below.

  2. **Root `version` check (raw JSON)** — using the raw JSON parsed in step 1, check whether the top-level object contains a `"version"` key. If present, emit: `[WARN] <path> has root 'version' key — auto-migration to per-section _version not yet run. Trigger migration by running any lazy-core skill (e.g., /lazy-core.audit) so that load_section rewrites the file.` Why this must use the raw JSON: `load_section` runs `migrate_root_version_to_section_version` on every call, rewriting the file in place and removing the root `version` key before this check could see it.

  3. **Migrating helper read (project scope only)** — for the project file, call `load_section` to obtain the migrated section dict and trigger on-disk migration if the file is still in the old format:
     ```
     Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
     from lazy_settings import load_section
     from pathlib import Path
     import json
     proj = load_section(Path('.claude/lazy.settings.json'), 'agent_models')
     print(json.dumps(proj))
     ")
     ```
     Do NOT add a manual file-existence guard — `load_section` returns a stub with `_version` intact when the file is absent.

     For the **global scope**, do NOT call `load_section` via Bash (CRITICAL PATH RULE forbids Bash under `$HOME/.claude/`). Instead, pluck the `agent_models` value directly from the raw JSON parsed in step 1: `raw.get("agent_models", {})`. If `agent_models` is missing from the raw JSON treat it as an empty dict (no gap findings for the global scope).

  4. **Absent-at-both-scopes check** — after processing both scopes, if BOTH files were absent (both step-1 Reads returned no file): emit `[WARN] no lazy.settings.json found at either scope — agent routing disabled. Run /lazy-core.optimize to create and fill.` and skip the remaining schema checks.

  5. **Schema checks** — for each present file, inspect the `agent_models` section dict obtained in step 3:
     - `[FAIL]` `agent_models` is not a dict (load returned a non-dict value).
     - `[WARN]` any value under `agent_models` that is a dict but has unexpected shape — finding: `malformed group <name> in <path>`. Skip any top-level key whose value is not a dict (e.g. `_version: int`) — only group sub-dicts carry dispatch mappings. Filter by shape, not by name, because `_user` / `_project` / `_builtin` are legitimate group-name keys that share the underscore prefix.
     - `[WARN]` unexpected reserved group — any group whose name starts with `_` and is NOT one of `_builtin`, `_user`, `_project`. Finding: `unknown reserved group <name> in <path> — reserved prefix`.
     - `[WARN]` cross-group duplicate keys — same dispatch string appearing in more than one group. Finding: `duplicate key <dispatch> in groups <a>, <b> (<path>) — router last-wins is non-deterministic`.
     - `[WARN]` invalid value — any value not in `{"haiku", "sonnet", "opus", "default"}`. Finding: `invalid value <x> for <group>.<key> in <path>`.
     - `[WARN]` orphan — dispatch string in any group that does NOT resolve to any discovered agent (see Agent discovery under `lazy-core.audit` / `lazy-core.optimize`). Finding: `orphan agent_models entry: <group>.<key> (<path>)`.
     - `[INFO]` gap — discovered agent with no entry in any group (except those explicitly set to `"default"`, which are NOT gaps). Finding: `no agent_models entry for <dispatch-string> — run /lazy-core.optimize to fill`.
     - `[INFO]` env-var status — current `LAZY_AGENT_MODEL_FLOOR` value if set, plus tier-order note `haiku < sonnet < opus`.
  All non-blocking.

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
- **Permissions leakage into tracked `settings.json`** (both `$HOME/.claude/settings.json` and `./.claude/settings.json`):
  - Per-tool permission entries are personal and should live in the paired `settings.local.json` (gitignored), not in tracked `settings.json` where they ship to every teammate who clones the repo / dotfiles.
  - `[WARN]` tracked file has a `permissions.allow` or `permissions.ask` array containing any entry. Finding: `tracked settings file owns per-tool permissions — these leak to teammates | <path>`; `detail:` count of entries in each list; `fix: migrate permissions.* block to <paired settings.local.json>` (coordinator-owned fix — see Phase 4).
  - Tracked `settings.json` may still own `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, `env` (non-secret), and similar enablement flags that teammates legitimately share. Only `permissions.*` is flagged.
- **Memory consistency** — locate project memory dir under `$HOME/.claude/projects/*/memory/` matching the current project path:
  - `[FAIL]` `MEMORY.md` references a missing file
  - `[WARN]` memory `.md` exists but is not indexed in `MEMORY.md`
  - `[WARN]` `MEMORY.md` > 5 KB
  - `[WARN]` any memory file missing frontmatter (`name`, `description`, `type`)
  - `[WARN]` memory `type` not one of: `user`, `feedback`, `project`, `reference`
  - **Exempt from these checks**: any file under `doctor.waivers/` (both project `$HOME/.claude/projects/<slug>/memory/doctor.waivers/` and personal `$HOME/.claude/memory/doctor.waivers/`). Waivers are doctor-internal memory entries intentionally kept out of `MEMORY.md` to avoid always-loaded-context bloat; they carry their own frontmatter shape (see Phase 2.7d).
- **CLAUDE.md files**:
  - `[WARN]` project `CLAUDE.md` references paths that don't exist
  - `[WARN]` project `CLAUDE.md` > 10 KB
  - `[WARN]` global `CLAUDE.md` contains project-specific instructions
- **Always-loaded context budget** — sum the byte size of everything Claude Code auto-loads into every session's context on every turn:
  - `$HOME/.claude/CLAUDE.md`
  - `<project>/.claude/CLAUDE.md`
  - Every `$HOME/.claude/rules/*.md` **without** a `paths:` key in YAML frontmatter (scoped rules only load when files under their glob are touched, so they don't count toward the always-loaded budget)
  - Every `<project>/.claude/rules/*.md` **without** a `paths:` key in YAML frontmatter
  Thresholds: `[WARN]` total > 20 KB, `[FAIL]` total > 40 KB. This is the real token budget — individual per-file limits are a crude proxy; the sum is what hits every turn. Finding must list per-file breakdown (largest first) so the user knows what to cut.
- **Hooks** (registered in global `settings.json` under `hooks.*`):
  - `[FAIL]` hook command references a missing script
  - `[WARN]` hook script imports a module that is **not stdlib AND not declared in a project dependency manifest** (`requirements.txt`, `pyproject.toml`, `package.json`, `Gemfile`, `Cargo.toml` — match by interpreter). Declared third-party deps are fine; undeclared ones create install risk for teammates and slow every hook invocation.
  - `[WARN]` hook timeout > 10s
  - `[WARN]` hook scripts contain hardcoded project paths without sidecar configs
- **MCP server configuration** — check `$HOME/.claude/settings.json`, `$HOME/.claude/settings.local.json`, project `.claude/settings.json`, `$HOME/.mcp.json`, `.mcp.json`:
  - Determine mode first: Mode A (`enableAllProjectMcpServers: true`) or Mode B (explicit `enabledMcpjsonServers`).
  - `[FAIL]` any `.mcp.json` malformed
  - Mode A only: suppress "declared but not enabled" warnings.
  - Mode B only: `[WARN]` server in project `.mcp.json` but absent from any `enabledMcpjsonServers`; `[WARN]` non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere
  - Always: `[WARN]` name in `enabledMcpjsonServers` but not defined in project `.mcp.json` or `$HOME/.mcp.json`
- **MCP permission wildcard detection** — Claude Code matches `permissions.allow` / `permissions.ask` / `permissions.deny` entries as **exact strings**. Wildcards (`*`, `?`) and brace expansions (`{foo,bar}`) in MCP permission entries are silently no-ops: the entry never matches any real tool call, so the "allow" or "ask" never takes effect and every invocation falls through to the default per-call prompt. Scan every permissions file (all four settings files listed above) and flag:
  - `[WARN]` MCP permission entry contains a wildcard — `entry matches /^mcp__/ AND entry contains any of: *, ?, {`. Finding: `MCP permission entry will never match — wildcards/braces are not expanded | <path>`; `detail:` quote the offending entry (e.g. `mcp__github__*`) and the owning list (`allow` / `ask` / `deny`); `fix: enumerate the exact mcp__<server>__<tool> names via lazy-guard.allow-mcp <server>` — that skill reads the runtime tool list and writes concrete entries.
  - A leading `^mcp__` guard on the regex avoids flagging non-MCP entries like `Bash(git push *)` or `Read(~/.claude/**)` which legitimately use Claude Code's own glob matcher. Only `mcp__*` entries are affected by this restriction.
- **MCP permissions hygiene** — for every *enabled* MCP server, verify that destructive tools aren't sitting in `allow`. The doctor **does not** flag "missing" tools — `skip` is a valid classification and per-call prompting is the intended fallback. The doctor also **does not** flag medium-risk (`skip`-classified) tools that the user pinned into `allow` or `ask` — that's a deliberate user decision, not a hygiene issue. Completeness and bucket re-shuffling are `lazy-guard.allow-mcp`'s job when the user invokes it; here we only catch truly destructive entries sitting in `allow` where they bypass confirmation.
  - Enumerate runtime tools by listing every tool name visible in your own tool list whose name matches `mcp__<server>__<tool>`, grouped by `<server>`. Do NOT invent names — only use names literally present. Claude Code matches exact strings in both `allow` and `ask`; no wildcards.
  - A server counts as *enabled* iff it's defined in `$HOME/.mcp.json` or `./.mcp.json` AND (Mode A, OR listed in `enabledMcpjsonServers` in either `./.claude/settings.json` or `./.claude/settings.local.json`). Skip servers that are defined-but-disabled, and skip servers that produced zero runtime tools (the server isn't loaded — a restart issue, not a permissions issue).
  - Resolve the target settings file per server using the routing rule from `lazy-guard.allow-mcp` Phase 4: default target is **`settings.local.json`** at the scope matching the server definition (global servers → `$HOME/.claude/settings.local.json` if the user registered globally; else `./.claude/settings.local.json`). Doctor checks both the target and the paired tracked `settings.json` (for leakage).
  - Classify each runtime tool using the 3-bucket classifier from `lazy-guard.allow-mcp` Phase 3:
    - **`allow`** — read verbs (get/list/search/query/recall/reflect/resolve/diff/status/show/log-as-read/fetch/refresh/audit) AND low-risk writes the user already trusts (`git_add`, `git_create_branch`, `retain`, `sync_retain`, `create_directive`, `create_mental_model`, `update_bank`, `update_mental_model`).
    - **`ask`** — irreversible destruction: `delete_*`, `remove_*`, `clear_*`, `reset*`, `checkout*`, `restore*`, `revert*`, force-pushes, bulk destructive ops.
    - **`skip`** — medium-risk verbs that should *not* be in either list: `commit*`, `cancel_*`, and anything ambiguous. Skipped tools trigger Claude Code's per-call prompt.
    - **Strict-match guard.** The `ask` bucket matches **only** the patterns above — do not extend by analogy. Tools whose names contain `commit`, `add`, `merge`, `pull`, or `push` (non-force) are **never** `ask`; `commit*` is `skip` and the rest are `allow`. A finding that classifies `mcp__git__git_commit` (or any other `commit*` tool) as `ask` is a bug — re-check the patterns before emitting.
  - Two comparisons per server (on the target `settings.local.json`):
    1. `misclassified_destructive = { t ∈ permissions.allow : t matches mcp__<server>__* AND classifier(t) == "ask" }` → `[WARN] Destructive MCP tools in allow list: <server> (<N> entries) | <target>`; `detail:` list the mis-placed tool names (`should be in permissions.ask — they cause irreversible loss and must prompt each time`); `fix: run lazy-guard.allow-mcp <server>` — allow-mcp will move them.
    2. `leaked_into_tracked = { t ∈ (tracked.permissions.allow ∪ tracked.permissions.ask) : t matches mcp__<server>__* }` → covered by the "Permissions leakage into tracked `settings.json`" check above; cross-reference but don't double-emit.
  - Emit at most one finding per server (misclassified). Do NOT emit per-tool findings — grouped lines keep the report scannable. Medium-risk (`skip`-classified) tools pinned to `allow` or `ask` are a user decision and never a finding.

### Agent C — path hygiene

Scope: every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`), grepping for hardcoded paths.

**Local tool mode scope expansion**: when the coordinator reports local tool mode, also grep for the same hardcoded-path patterns across `claude/**/rules/*.md`, `claude/**/skills/*/SKILL.md`, `claude/**/agents/*.md`, `claude/**/commands/*.md`, and `claude/**/hooks/**`. Self-referential documentation of the path-hygiene rule itself (files whose purpose is to describe the bad patterns — e.g. `lazy-core.hygiene.md`, `lazy-guard.security.md`, `lazy-core.doctor/SKILL.md`, `lazy-guard.check-public/SKILL.md`) must be excluded via the `source: doc-of-rule` marker to avoid false positives.

Checks the agent performs:

- `[FAIL]` file contains `/Users/` or `/home/` (hardcoded absolute user path)
- `[FAIL]` file contains `<project>/` prefix (use relative paths instead)
- `[WARN]` file contains `~/Dropbox/` or other user-specific home subdirectories
- `[WARN]` file references `$HOME/.claude/` for something that is actually project-local

Allowed `$HOME/.claude/` references (agent must exclude these from WARN):
- `$HOME/.claude/CLAUDE.md`
- `$HOME/.claude/settings.json` / `$HOME/.claude/settings.local.json`
- `$HOME/.claude/rules/*.md`
- `$HOME/.claude/skills/*/SKILL.md`
- `$HOME/.claude/commands/*.md`
- `$HOME/.claude/projects/*/memory/`
- `$HOME/.mcp.json`

## Phase 2 — Collect + merge

Parse each returned block by splitting on `## scan:` headings. Deduplicate findings when two agents report the same `<path>:<line>` + title (happens rarely; A vs B overlap is minimal). Sum the three `### summary` blocks into overall `PASS / WARN / FAIL` counts.

### 2a. Coordinator-assigned fields (enable waiver matching)

For every finding after merge, the coordinator attaches three internal fields. Agents don't emit them — the coordinator derives them from the finding's title + path. These fields never appear in the printed report; they're used only by Phase 2.7 and the logs.

- **`check_id`** — a stable slug of the form `<area>.<rule>` that identifies the check the finding came from (e.g. `rules.broken-artifact-reference`, `rules.oversize`, `rules.unscoped-no-waiver`, `agents.filename-no-dot`, `agents.frontmatter-malformed`, `skills.name-dir-mismatch`, `commands.filename-no-dot`, `settings.tracked-owns-permissions`, `memory.not-indexed`, `memory.oversize`, `claude-md.path-missing`, `budget.always-loaded-warn`, `budget.always-loaded-fail`, `hooks.import-undeclared`, `mcp.entry-wildcard`, `mcp.destructive-in-allow`, `paths.user-home-abs`, `paths.user-home-subdir`, `paths.project-prefix`, `paths.claude-home-for-local`). The coordinator maintains an explicit title→slug table; new titles must be added to the table with their slug before shipping.
- **`scope`** — one of `project` / `personal` / `ambiguous`. Derived from the finding's primary path:
  - path inside the repo (no leading `~`, no `/Users/…`) → `project`
  - path under `$HOME/.claude/**` or `$HOME/.mcp.json` → `personal`
  - plugin-outdated WARN → `personal` (version applies machine-wide)
  - path spans both scopes (e.g. a hook file at global scope referencing a project path) → `ambiguous`
  - findings with no path (e.g. `budget.always-loaded-warn`) default to `project` if the sum was computed primarily from project files, else `personal`
- **`fingerprint`** — the tuple `(check_id, normalized_path, detail_hash)` used by Phase 2.7 to match findings against stored waivers:
  - `normalized_path` — project-relative (`./.claude/rules/foo.md`), `~`-prefixed (`$HOME/.claude/CLAUDE.md`), or `*` for findings with no path.
  - `detail_hash` — first 8 hex chars of sha256 of a normalized detail string (drop whitespace, drop byte counts, keep the referenced symbol / path / tool name). Specific enough that "missing agent X" is waived independently of "missing agent Y"; stable enough that whitespace edits don't re-surface the same finding.

## Phase 2.5 — Plugin version currency

Coordinator-owned inline check (not an Explore agent — it performs a `git fetch`, which violates the parallel-scan read-only contract). Runs in the main session after the merge above and before delegated audits.

Steps:

1. **Collect installed plugins.** Read `$HOME/.claude/plugins/installed_plugins.json`. Keep only entries whose scope applies to this project: `scope: "user"`, OR `scope: "project"` with `projectPath` equal to the current repo path. Same filter Agent A already uses.
2. **Group by marketplace.** Strip the `@<marketplace>` suffix from each top-level key → `{ marketplace → [plugin entries] }`.
3. **Refresh each referenced marketplace (live).** Read `$HOME/.claude/plugins/known_marketplaces.json` to resolve each marketplace's `source` and `installLocation`. For each:
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

- For any finding whose `path` starts with `.claude/rules/` or `$HOME/.claude/rules/` AND whose `plugin_owner` field (set by Agent A) is in `outdated_plugins`, **drop the finding from the merged list** and increment a `suppressed_by_outdated_plugin` counter keyed by plugin.
- Findings with no `plugin_owner` (user-authored rules) are never suppressed.
- Findings from Agent A Plugin rule sync (drift / orphan) are never suppressed — drift is exactly what an upgrade resolves, and the finding itself is the pointer.
- Findings from any other agent / scope (Agent B, Agent C, cross-reference integrity, etc.) are never suppressed.

For each plugin with a non-zero `suppressed_by_outdated_plugin` counter, emit one summary line alongside the existing version WARN:

`[INFO] <N> content findings on <plugin>-owned rules suppressed — upgrade via `/plugin update <name>` to re-validate.`

This keeps the user focused on the root cause (stale install) instead of chasing content issues that the upgrade will overwrite. Re-run the doctor after upgrading to surface any remaining issues.

## Phase 2.7 — Waiver reconciliation

Suppress `WARN` findings the user has previously waived. `FAIL` findings are **never** checked against the waiver set — a stale waiver must not mask broken state.

### 2.7a. Discover memory backends (once per run, cached for Phase 4)

The coordinator supports two backend shapes. It never names a specific MCP server; it probes for whatever is available and uses the first reachable option per scope.

1. **File-based store (preferred — always accessible, no MCP required).**
   - Project-scoped waivers live under `$HOME/.claude/projects/<slug>/memory/doctor.waivers/`.
   - Personal-scoped waivers live under `$HOME/.claude/memory/doctor.waivers/`.
   - `<slug>` is the project memory slug Claude Code already writes to at session start (same directory that owns the project's `MEMORY.md` — the existing Phase 1 memory checks already operate on it). Resolve `<slug>` from the running session's own auto-memory path; never construct it from the current `pwd`.
   - A missing directory is a silent zero-match, not an error.

2. **MCP-backed memory (opt-in fallback only).**
   - Probe the runtime tool list for any tool name matching both `mcp__<server>__retain` AND `mcp__<server>__recall` for the same `<server>`. If any such pair exists, mark MCP available.
   - The coordinator never writes the matched server name into the skill text — it uses whichever tool name is present at runtime. One or multiple servers are fine.

3. **If neither backend is reachable** for a given scope, Phase 4 downgrades the "Waive permanently" option to "Skip for now" with a visible warning and writes nothing.

### 2.7b. Load waivers

1. **File-based** — `Glob` both scoped `doctor.waivers/` directories. `Read` each match; parse its YAML frontmatter into a waiver record (see §2.7d).
2. **MCP (only if discovered)** — call the discovered `recall`-shaped tool with `tags: ["doctor-waiver"]`. A tool error is a soft-fail: log it, continue with only file-based waivers.
3. Build `waiver_set = { fingerprint → {reason, date, scope, backend, location} }`. If the same fingerprint exists in both file and MCP backends, the **file entry wins** and an `INFO` note is appended to the run log so the user notices the drift. No automatic cleanup.

### 2.7c. Suppress matching findings

For every `WARN` finding in the merged list:

- Compute its `fingerprint` (see Phase 2a).
- If `fingerprint` is in `waiver_set`, move the finding from the merged list to a separate `waived_findings` list. Phase 4 renders `waived_findings` under a collapsed "Waived (N)" section.
- `FAIL` findings are left untouched regardless of any matching waiver.

### 2.7d. Waiver record shape (backend-agnostic)

A waiver carries these fields regardless of where it's stored:

- `check_id` — stable check slug (Phase 2a table).
- `normalized_path` — project-relative, `~`-prefixed, or `*`.
- `detail_hash` — 8-hex fingerprint of the normalized detail.
- `reason` — one-line free-text; defaults to the finding's own message + `accepted permanently on <YYYY-MM-DD>`.

**File-based encoding** — `<doctor.waivers-dir>/<fingerprint>.md` where `<fingerprint>` is `<check_id>__<detail_hash>` (path-safe). Frontmatter mirrors the shape the doctor already validates for memory entries (so this dir doesn't itself trip a memory-index WARN):

```
---
name: doctor waiver: <check_id>
description: <finding title — short>
type: reference
tags: [doctor-waiver, severity:warn, check:<check_id>, scope:<scope>]
check_id: <check_id>
normalized_path: <normalized_path>
detail_hash: <detail_hash>
scope: <project|personal>
added: <YYYY-MM-DD>
---

<reason>
```

Do **not** link the waiver file from `MEMORY.md` — waivers are doctor-internal and must not enter always-loaded context. (Phase 1's `memory.not-indexed` WARN does not fire for entries inside `doctor.waivers/` — add an exemption in Agent A's memory check so this dir is excluded.)

**MCP encoding** — invoke the discovered `retain`-shaped tool with:
- `content`: `"Doctor waiver: <finding title — short> | <normalized_path>. Accepted permanently on <YYYY-MM-DD>."`
- `tags`: `["doctor-waiver", "severity:warn", "check:<check_id>", "scope:<scope>"]`
- `context`: object carrying `check_id`, `normalized_path`, `detail_hash`, `reason`, `added`.

## Phase 3 — Delegated audits (inline, not dispatched)

Doctor delegates to sibling audit skills for scope-specific checks rather than replicating their logic. Each sub-check verifies the sibling skill is reachable, then checks its run condition, and silently skips if either fails. Doctor never warns about missing sibling plugins.

Each delegation follows four steps:

1. **Availability probe** — is the sibling skill reachable?
2. **Run condition** — is the opt-in gate satisfied?
3. **On skip** — if either fails, skip silently; no entry in the report.
4. **On invoke** — fold the sibling's summary into a named subsection; direct the user to run the sibling for interactive fixes. Do NOT re-run its fix flow.

**Availability probe — canonical signal set.** A sibling plugin counts as available if **any** of these signals is true (not just the first):

1. `$HOME/.claude/plugins/installed_plugins.json` contains a top-level entry `<plugin>@<marketplace>` whose scope applies to this project (`scope: "user"`, or `scope: "project"` with `projectPath` matching the current repo).
2. **Local tool mode** — `claude/<plugin>/.claude-plugin/plugin.json` exists in the current repo (the plugin is authored here; all its skills are reachable via the local path).
3. **Enabled via settings** — `enabledPlugins["<plugin>@<marketplace>"] === true` in any of `$HOME/.claude/settings.json`, `$HOME/.claude/settings.local.json`, `./.claude/settings.json`, `./.claude/settings.local.json`. This catches the case where the user enabled the plugin via `/plugin install` flow that wrote to settings but where `installed_plugins.json` lacks a matching `projectPath` record (common when multiple machines / Dropbox-synced project paths diverge).

Any one signal is sufficient — doctor should not skip a delegated audit just because one signal is absent. If none are true, skip silently.

**11a. Public-repo guard** → `lazy-guard.check-public`
- *Availability*: `lazycortex-core` meets the canonical signal set above.
- *Run condition*: `.guard-waivers.json` exists at the repo root.
- *On invoke*: fold guard's summary (category × severity counts, waivered count) and FAIL/WARN findings into a **Guard** subsection.

**11b. Logging coverage** → `lazy-log.audit`
- *Availability*: `lazycortex-log` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Logging** subsection.

**11c. Diagram coverage** → `lazy-diagram.audit`
- *Availability*: `lazycortex-diagram` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Diagram** subsection.

**11d. Review coverage** → `lazy-review.audit`
- *Availability*: `lazycortex-review` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Review** subsection.

**11e. Expert runtime** — inline, via `lazy-core.audit` Agent D findings
- *Availability*: always (expert-runtime checks are part of `lazycortex-core` itself — no separate plugin probe needed).
- *Run condition*: `experts.settings.json` exists at the repo root OR `lazy.settings.json` contains a `lazy-core.runtime` section. Skip if neither is present (no expert runtime configured — silent skip, no report entry).
- *On invoke*: run the Agent D sub-checks from `lazy-core.audit` inline (do NOT dispatch a separate skill — just execute the same D1–D10 logic described in `lazy-core.audit`'s Agent D section). Fold findings into a **Loop runtime** subsection. Retain all D-findings for Phase 4 fix-offer matching (see "Loop runtime fix offers" in Phase 4).

## Phase 4 — Present + fix + waive

Render in the existing format, with a new "Waived" tail section covering findings Phase 2.7 suppressed:

```markdown
## lazy-core.doctor -- Health Report

### Summary
- Checks run: N
- PASS: N | WARN: N | FAIL: N | Waived: N

### Issues

#### [FAIL] Rules: openclaw.md is 25 KB (limit: 3 KB)
Reference material should be in .claude/agents/openclaw-config.md.
**Fix**: Run `/lazy-core.optimize` to slim rules files.

#### [WARN] Memory: feedback_old_thing.md not in MEMORY.md index
File exists but has no index entry.
**Fix**: Add `- [old-thing](feedback_old_thing.md) — <description>` to MEMORY.md

(... one section per issue, followed by Guard and Logging subsections if delegated audits ran ...)

### Waived (<N>)
- <check_id> | <normalized_path> — waived <YYYY-MM-DD>, backend=<file|mcp>, location=<abs path or mcp memory-id>, reason="<reason>"
(omit the whole section when N == 0)

### Fixes available
- [ ] Fix 1: <description> (auto-fixable)
- [ ] Fix 2: <description> (auto-fixable)
- [ ] Fix 3: <description> (needs manual review)

Apply all auto-fixable? [y/N]
```

After the report, ask the user which fixes to apply. Apply only confirmed fixes. Then enter the **per-WARN waive loop** described in 4a below. Fixes available in-coordinator:

- Rules oversized → suggest running `/lazy-core.optimize`; don't auto-slim here.
- Rule drift / orphans → direct the user to run the owning plugin's install skill (`/<namespace>.install`, e.g. `/lazy-log.install` for `lazy-log.*` rules). Do NOT auto-overwrite here — the install skill's per-rule `AskUserQuestion` is the sanctioned reconciliation flow.
- Missing rules frontmatter → add `---\ndescription: ...\npaths:\n  - "<glob>"\n---` (YAML block-list per Claude Code docs) for scoped rules, or `---\ndescription: ...\nalways_loaded: <one-line reason>\n---` for rules that must load every turn.
- Rule lacks scope AND waiver → ask the user, per rule, whether the rule is legitimately always-loaded. If yes, add `always_loaded: <reason>` (reason must be substantive — one line explaining *why* every turn needs it, not `true`). If no, add a `paths:` block-list narrowing it to the folders where it applies. Show the proposed frontmatter diff before writing. Never auto-pick a scope — only the user knows the rule's true audience.
- Inline-array `paths:` shape (FAIL from `lazy-core.audit` rule-writing check 3) → in-place migration to canonical YAML block-list. Parse the existing `paths: ["a", "b", ...]` line, preserve all globs verbatim (including quote style), rewrite as a key on its own line followed by one `  - "<glob>"` per array element. The conversion is mechanical (no semantic change) but always show the diff before writing — the rule file is loaded into context for whoever's editing files in its scope, so even a YAML-shape change deserves explicit user confirmation. Apply per-rule via `AskUserQuestion`; batch only on explicit "apply all" from the user.
- Authoring rule without template reference (WARN from `lazy-core.audit` rule-writing check 9) → ask the user, per finding, whether to scaffold a template. Two-step fix: (1) derive `<artifact-type>` from the rule filename (`*.writing.md` → strip `-writing`/`.writing` and pluralize as needed; e.g. `dev.skill-writing.md` → `skill`), copy the matching base template (`<plugin>/templates/core/{rule,skill,agent}-template.md`) to `<plugin>/templates/<group>/<derived-name>-template.md` — default `<group>` to the plugin's primary namespace (`core` for `lazycortex-core`); ask the user if they prefer a different group name. (2) Prepend `**Template:** ${CLAUDE_PLUGIN_ROOT}/templates/<group>/<derived-name>-template.md — start here when creating a new <artifact-type>.` immediately after the rule's H1 + orientation paragraph, before the first `## ` section. Show the full diff (new template file + rule edit) before writing; apply only on explicit user confirmation. Per `lazy-core.scaffold`.
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

### Loop runtime fix offers

These three fix offers are conditional on findings from Phase 3 § 11e. Each is offered via `AskUserQuestion` only when the corresponding finding is present in the Loop runtime subsection.

**Fix L1 — Daemon stalled** (trigger: D10 WARN "runtime daemon appears stale")

`AskUserQuestion`: "Daemon is stalled — no log activity in the last <N>s (last seen: <timestamp or 'never'>). Restart the runtime daemon?"

Options: `Restart via supervisor`, `Skip`.

On Restart:
1. Detect OS: `Bash(uname -s)` → `Darwin` or `Linux`.
2. Derive the service label: `com.lazycortex.runtime.<repo-name>` where `<repo-name>` is `Bash(basename $(pwd))`.
3. macOS: `Bash(launchctl kickstart -k gui/$UID/com.lazycortex.runtime.<repo-name> 2>&1)`.
4. Linux: `Bash(systemctl --user restart lazy-core-runtime.service 2>&1)`.
5. Verify: re-run the D10 liveness check (pgrep + launchctl/systemctl) immediately after. Report `restarted` (liveness confirmed) or `restart-attempted` (supervisor command ran but liveness probe still failing — user may need to reload the service definition first).

**Fix L2 — Stale orphan jobs** (trigger: D8 WARN "orphan job directory")

`AskUserQuestion`: "Found <N> orphan job director(y/ies) under `.jobs/` for experts no longer in `experts.settings.json`. Delete them?"

Options: `Delete all`, `Keep`.

On Delete: for each orphan job dir identified in D8, run:
```
Bash(python3 -c "
import shutil, sys
shutil.rmtree(sys.argv[1])
print('deleted')
" '.jobs/<expert>')
```
Report one line per deleted directory: `deleted: .jobs/<expert>/`.

**Fix L3 — Routine command unresolvable** (trigger: D7 FAIL "routine <name> command path does not exist")

`AskUserQuestion`: "Routine `<name>` references plugin bin path `<path>` which does not exist. The plugin may not be installed. Unregister the routine from `lazy-core.runtime.routines`?"

Options: `Unregister`, `Keep — I'll fix the plugin install`.

On Unregister:
```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from expert_runtime import unregister_routine
from pathlib import Path
unregister_routine(Path('.'), sys.argv[1])
print('unregistered')
import sys
" '<name>')
```
Report: `unregistered routine: <name>`. If `unregister_routine` raises (e.g. settings file not writable), surface the exception text as a FAIL finding and skip the write.

Offer Fix L3 per-routine when multiple routines are unresolvable — one `AskUserQuestion` per routine. Do not batch them silently.

For any finding surfaced by a delegated audit (Guard / Logging), direct the user to run that sibling skill for fixes. Doctor never auto-fixes issues owned by sibling audits.

### 4a. Per-WARN waive loop

After the fix batch is applied (or declined), iterate the remaining `WARN` findings — i.e. every WARN that was not auto-fixed and not already suppressed by Phase 2.7. `FAIL` findings are **never** offered a waive option.

For each remaining WARN, `AskUserQuestion` with two options:

- **Skip for now** *(default-recommended — safest)* — no persistent effect; the finding will reappear on the next doctor run.
- **Waive permanently** — opens the permanence confirmation sub-prompt.

If the user picks **Waive permanently**, a second `AskUserQuestion`:

> This will write a permanent waiver to `<resolved backend + location>`. Future doctor runs will suppress this finding. **This is not a temporary skip — the waiver persists across sessions.** Confirm?
>
> - **Confirm permanent waiver** — writes to the resolved backend.
> - **Cancel — treat as a skip** — no write; finding reappears next run.

If the finding's `scope` is `ambiguous`, insert a **storage-choice** question between the permanence confirmation and the write:

- **Save under this project** *(default-recommended — smaller blast radius, easy to revert by deleting the file)* — project scope.
- **Save for all projects on this machine** — personal scope.

On confirmation, resolve the backend via the Phase 2.7a priority ladder using the finding's `scope`:

- **File-based (preferred)** — `Bash(mkdir -p <doctor.waivers-dir>)` in one step, then the `Write` tool in a separate step (never chained; per `lazy-log.logging`) to create `<doctor.waivers-dir>/<check_id>__<detail_hash>.md` with the frontmatter from Phase 2.7d.
- **MCP fallback (only if discovered and the user opted in)** — call the discovered `retain`-shaped tool with the payload from Phase 2.7d. The skill reads the discovered tool name from the runtime tool list — no specific server name is written here.

**Reachability fallback.** If the preferred backend write fails (filesystem error, permission denied, MCP tool error), retry via the next backend in the Phase 2.7a ladder and append a one-line note to the report: `note: <X> unreachable, waiver saved to <Y>`. If every backend for the resolved scope fails, downgrade the "Waive permanently" option to "Skip for now" with a visible warning and write nothing.

**No free-text reason is solicited by default.** The waiver stores the finding's own short title + date, which is enough for future recall to explain itself. If the user wants to record a reason, they can supply it via the `AskUserQuestion` "Other" field on the permanence prompt — whatever they type becomes the `reason` field.

**Un-waiving is out of scope for this skill.** To remove a waiver the user deletes the file (for file-based) or deletes the memory entry via their existing memory tooling (for MCP-backed). On the next doctor run, the finding reappears in the main WARN list.

## Failure modes

- **Fix L1 "launchctl kickstart" fails with "No such process"** — the service plist hasn't been loaded yet (first-time use after install). The user must first run `launchctl load ~/Library/LaunchAgents/com.lazycortex.runtime.<repo-name>.plist` before kickstart can restart it → direct the user to run `/lazy-core.install` to (re-)register the supervisor plist.
- **Fix L1 "systemctl --user restart" fails with "Unit not found"** — the systemd user unit hasn't been installed yet → direct the user to run `/lazy-core.install` to install the unit file and `systemctl --user daemon-reload`.
- **Fix L1 liveness probe still stale after restart** — the daemon started but hasn't written a JSONL log line yet (can take up to one polling interval). Wait `polling_interval_sec` seconds, then re-run `/lazy-core.doctor` to confirm.
- **Fix L2 fails with "Permission denied" on rmtree** — the job directory has restricted permissions (e.g. created by a different user or process). Doctor surfaces the error; the user must remove the directory manually.
- **Fix L3 "unregister_routine" raises "settings file not writable"** — `.claude/lazy.settings.json` is read-only or the process lacks write permission → fix file permissions, then re-run `/lazy-core.doctor`.
- **Fix L3 offered but routine reappears on next doctor run** — the settings write completed but the installed plugin's default-routines bootstrap re-added the entry. Re-run `/lazy-core.install` with the `skip expert-pump routine` option, or add the routine to a local exclusion list in `lazy.settings.json`.
- **Phase 3 § 11e skipped unexpectedly** — neither `experts.settings.json` nor a `lazy-core.runtime` section in `lazy.settings.json` was found. If expert runtime is configured but the files are in a non-standard location, run `/lazy-core.audit` directly to surface Agent D findings without the skip guard.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).

The `## Actions` section must include, in addition to the usual run details:

- **Backend discovery** — one line per scope recording which backends were reachable (e.g. `backend discovery (project): file=ok, mcp=<discovered server name or 'none'>`).
- **Waiver recall counts** — per backend / per scope (`recall: file=<N>, mcp=<N>`), plus an `INFO` line for any fingerprint held by both backends (`both-backends: <fingerprint> (file wins)`).
- **Suppressed findings** — one line per finding dropped by Phase 2.7: `waived finding suppressed: <check_id> | <normalized_path>`.
- **Newly written waivers** — one line per write: `waiver written: <check_id> | <normalized_path> → <backend>:<location>`.
- **Waive-option downgrades** — one line per finding where every backend for the resolved scope failed and the option was gracefully downgraded to Skip: `waive unreachable: <check_id> | <normalized_path> — all backends failed, treated as skip`.
