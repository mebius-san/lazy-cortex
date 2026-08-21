---
name: lazy-core.doctor
description: "Run when the operator asks whether the project config is healthy, or when something feels off — a rule or skill is not firing, plugins may be behind the marketplace, settings / agents / memory / hooks / CLAUDE.md have drifted apart. Merges its own cross-artifact scan with the installed plugins' audits, applies the repairs that follow mechanically from what it read, and asks per finding about the rest; the sibling `/lazy-core.audit` only measures context weight and authoring compliance and never fixes."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(wc *), Bash(mkdir -p *), Bash(python3 *), Bash(claude plugin update *), mcp__*__recall, mcp__*__retain, Agent
---
# Project Health Check

Coordinator skill. Dispatches three **Explore** subagents in parallel to scan the project, merges their reports, presents a unified report, applies the repairs a finding fully determines, and asks about the ones that encode a decision.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern. Severity vocabulary: `PASS` / `WARN` / `FAIL`, plus `INFO` (reserved for Phase 2.5 transient status lines — e.g. "marketplace unreachable, used cached manifest" — that don't require a user fix).

**CRITICAL PATH RULE** (applies to every dispatched agent): `$HOME/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `$HOME/.claude/`. Only project-root paths may use `wc -c`. For `$HOME/.claude/` file sizes, estimate as `lines × 45 bytes`.

**Path expansion** (mandatory): Glob and Read do **not** shell-expand `~` or `$HOME`. Before any Glob/Read targeting a home-relative path, run `Bash(echo $HOME)` once and substitute the result (or read the absolute home path from the session env block). A literal `~/.claude/rules/*.md` or `$HOME/.claude/rules/*.md` passed to Glob will match nothing and silently report "empty".

**Read-first**: collect all findings before any fix. Never fix silently.

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 0 — Mode detection`
   - `Phase 1 — Dispatch parallel scans`
   - `Phase 2 — Collect + merge`
   - `Phase 2.5 — Plugin version currency`
   - `Phase 2.55 — Naming-canon drift in consumer state`
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

  3. **Migrating helper read (project scope only)** — for the project file, call `load_section` to obtain the migrated section dict and trigger on-disk migration if the file is still in the old format: ``` Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c " from lazy_settings import load_section from pathlib import Path import json proj = load_section(Path('.claude/lazy.settings.json'), 'agent_models') print(json.dumps(proj)) ") ``` Do NOT add a manual file-existence guard — `load_section` returns a stub with `_version` intact when the file is absent.

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

- **Settings consistency** — read all four: ``` ~/.claude/settings.json          ~/.claude/settings.local.json .claude/settings.json            .claude/settings.local.json ```
  - `[FAIL]` any file is not valid JSON
  - `[FAIL]` project-specific permissions (service CLIs, `additionalDirectories`, service MCP servers, domain-specific WebFetch) in global `settings.json` instead of project `settings.local.json`
  - `[WARN]` duplicate permission entries across global + project files
  - `[WARN]` project `settings.json` (tracked) contains machine-specific paths
- **Permissions leakage into tracked `settings.json`** (both `$HOME/.claude/settings.json` and `./.claude/settings.json`):
  - Per-tool permission entries are personal and should live in the paired `settings.local.json` (gitignored), not in tracked `settings.json` where they ship to every teammate who clones the repo / dotfiles.
  - `[WARN]` tracked file has a `permissions.allow` or `permissions.ask` array containing any entry. Finding: `tracked settings file owns per-tool permissions — these leak to teammates | <path>`; `detail:` count of entries in each list; `fix: migrate permissions.* block to <paired settings.local.json>` (coordinator-owned fix — see Phase 4).
  - Tracked `settings.json` may still own `enabledPlugins`, `enabledMcpjsonServers`, `enableAllProjectMcpServers`, `hooks`, `env` (non-secret), and similar enablement flags that teammates legitimately share. Only `permissions.*` is flagged.
- **Plugin marketplace declaration** (project `./.claude/settings.json` + `./.claude/settings.local.json`):
  - A `enabledPlugins` key has the form `<plugin>@<marketplace>`. The entry only resolves where `<marketplace>` is known — declared in the same settings scope under `extraKnownMarketplaces`, or registered globally on that machine. A project file that enables a plugin without declaring its marketplace works only for the operator who happens to have it globally; on a fresh clone or another machine the plugin is silently never loaded.
  - Union the marketplaces declared under `extraKnownMarketplaces` in both project files → `declared`. For every `<plugin>@<marketplace>` with value `true` in either project file where `<marketplace>` ∉ `declared`:
    - `[WARN]` Finding: `<plugin>@<marketplace> enabled but marketplace not declared in project settings — resolves only where <marketplace> is registered globally | <path>`.
    - Resolve the marketplace source, in order: `$HOME/.claude/settings.json` `extraKnownMarketplaces.<marketplace>`, then `$HOME/.claude/plugins/known_marketplaces.json` `<marketplace>` (Read only — CRITICAL PATH RULE). Record the resolved block in the finding's `detail:` when found; `fix: add <marketplace> to extraKnownMarketplaces in <path>` (coordinator-owned fix — see Phase 4).
    - Unresolvable at both sources → keep the WARN, mark `detail: source unknown` — the operator must supply the marketplace source (report-only).
  - The mirror direction (a declared marketplace no enabled plugin references) is NOT a finding — operators pre-declare marketplaces ahead of enabling their plugins.
- **Routine registry conformance** (project `.claude/lazy.settings.json` + its `.local.json` overlay) — every entry under `routines` is validated against its own type schema. A broken entry is invisible until the daemon reads it: it is then dropped, halts the daemon with `routine_config_invalid`, and stops every other routine of the repo until the settings are edited. Entries written by hand, seeded by a plugin's install skill, or left behind by a schema change are exactly the ones no write-time validator ever saw.
  - Run the validator over the merged view — never re-implement the schema here; the checker is the same function the daemon and `/lazy-routine.register` call. Each printed line is one broken entry, tab-separated as `<name>\t<schema error>`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_section
from routine_types import RoutineConfigError, validate_routine_entry
routines = load_section(Path('.claude/lazy.settings.json'), 'routines')
routines.pop('_version', None)
for name, cfg in routines.items():
    if not isinstance(cfg, dict):
        print(f'{name}\tnot an object')
        continue
    try:
        validate_routine_entry(name, cfg)
    except RoutineConfigError as e:
        print(f'{name}\t{e}')
")
```

  - `[FAIL]` one finding per printed line — `routine <name> does not conform to its type schema — daemon halts on read | .claude/lazy.settings.json`; `detail:` the validator's message verbatim, never paraphrased (it names the exact field).
  - **Report-only, no fix.** An unknown field can be a typo, a leftover of an older schema, or an intent the schema has not grown yet; a missing required field can mean the entry was meant to be a different type entirely. The operator decides. Offer the two routes in the finding's `fix:` line — hand-edit the entry, or re-register it via `/lazy-routine.register --force` — and never rewrite the entry from the doctor.
  - A non-dict value under `routines` (other than `_version`) is the same `[FAIL]`, phrased `routine <name> is not an object`.
  - No entries, or no settings file → no finding. An empty registry is a legitimate state.
- **Mandatory routine protocols** — protocols are routine-side: whatever a routine declares reaches every job it dispatches, and a job whose expert writes markdown into the vault without `lazy-core.markdown-style` produces prose in the wrong shape with nothing to catch it. A plugin's install seeds the protocol; an operator who hand-edits the routine, or a settings file restored from before the plugin shipped the seed, silently loses it.
  - The routines whose jobs write markdown, and the protocol each must carry:

| Routine | Mandatory protocol |
|---|---|
| `lazy-spec.coordinator-watch` | `lazycortex-core:lazy-core.markdown-style` |
| `lazy-wiki.scan` | `lazycortex-core:lazy-core.markdown-style` |
| `lazy-wiki.relink-weekly` | `lazycortex-core:lazy-core.markdown-style` |
| `lazy-review.scan` | `lazycortex-core:lazy-core.markdown-style` |

  - Check only the routines the merged registry actually contains — an absent routine means the plugin is not installed here and is never a finding. Read each one's `protocols` list (or the singular `protocol`); a missing entry is `[WARN] routine <name> is missing its mandatory protocol <id> — its jobs write markdown with no style contract | .claude/lazy.settings.json`.
  - **Coordinator-owned fix**, mechanically derivable: `Bash(lazycortex-core add-protocols --routine <name> --ids <id>)`. The union only appends, so an operator's own additions survive.
  - Optional protocols are never checked here and never offered — attaching them is the operator's call through `/lazy-routine.offer-protocols`.
  - The table is the mandatory set the shipped installs seed; a plugin that adds a markdown-writing routine adds its row in the same change.
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
  - Every always-loaded rule file under `$HOME/.claude/rules/*.md` — i.e., frontmatter declares `always_loaded:` (the canonical waiver per `lazy-core.rule-writing § 1`). Rules with `paths:` instead are loaded only when files under their glob are touched, so they don't count toward this budget.
  - Every always-loaded rule file under `<project>/.claude/rules/*.md`
  Thresholds: `[WARN]` total > 20 KB, `[FAIL]` total > 40 KB. This is the real token budget — individual per-file limits are a crude proxy; the sum is what hits every turn. Finding must list per-file breakdown (largest first) so the user knows what to cut.

  **Phrase the finding correctly.** This is a *budget* check, not a frontmatter-shape check. Always-loaded rules with a valid `always_loaded:` waiver are correctly authored; they only matter here because they contribute bytes. Do NOT emit findings reading "rule lacks `paths:` restriction" — that wording falsely implies the rule is misshaped. If a rule lacks BOTH `paths:` AND `always_loaded:`, that's a separate FAIL caught by `lazy-core.rule-writing` Check 2 and surfaced via `lazy-core.audit`, not this budget check.
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

- **`check_id`** — a stable slug of the form `<area>.<rule>` that identifies the check the finding came from (e.g. `rules.broken-artifact-reference`, `rules.oversize`, `rules.unscoped-no-waiver`, `agents.filename-no-dot`, `agents.frontmatter-malformed`, `skills.name-dir-mismatch`, `commands.filename-no-dot`, `settings.tracked-owns-permissions`, `memory.not-indexed`, `memory.oversize`, `claude-md.path-missing`, `budget.always-loaded-warn`, `budget.always-loaded-fail`, `hooks.import-undeclared`, `mcp.entry-wildcard`, `mcp.destructive-in-allow`, `paths.user-home-abs`, `paths.user-home-subdir`, `paths.project-prefix`, `paths.claude-home-for-local`, `runtime.external-dir-broken`, `runtime.inbox-collision`). The coordinator maintains an explicit title→slug table; new titles must be added to the table with their slug before shipping.
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

- Outdated plugin: `[WARN] plugin <name>@<mp> is outdated (<installed> → <latest>) | installed_plugins.json` `detail: scope=<user|project> | path=<installPath>` `fix: `claude plugin update <name>` (auto-applied in Phase 4; takes effect after a session restart)`
- Marketplace cache fallback (one per unreachable marketplace): `[INFO] marketplace <mp> unreachable — using cached manifest (last updated <lastUpdated>)`

Worst-case latency: 5 s × number of referenced marketplaces (sequential today; parallelize if it bites).

## Phase 2.55 — Naming-canon drift in consumer state

Coordinator-owned inline check. `lazy-core.hygiene` § Naming puts routine names and hook short names in the owning plugin's namespace; consumer state written before a plugin adopted that canon still carries the pre-namespace form. Nothing migrates by force — this phase names the drift and offers the rename, per plugin, in Phase 4. Doubt reads as not-a-problem: a name, key, or identity this phase cannot prove drifted stays unreported — a wrong rename is worse than a stale one.

Scan four surfaces of the merged `lazy.settings.json`:

1. **Routine keys** — a `routines[<name>]` whose first dot-segment is not a `lazy-*` namespace, while the plugin its `command[0]` (or `expert`) resolves to owns a `lazy-*` one. The canonical key is that plugin's namespace plus the existing verb and scope segments.
1a. **Expert keys — the same canon read backwards.** An `experts[<key>]` whose first dot-segment IS a `lazy-*` namespace drifted the other way: § Naming keeps an expert key at `<domain>.<role>`, because it names a role in a domain rather than a file any plugin ships. The canonical key is the existing one with the leading `lazy-` stripped (`lazy-review.coordinator` → `review.coordinator`). Rename only when the entry's `agent` resolves to an installed plugin and the stripped key is free; a `lazy-*` key nothing serves is unresolvable, not drifted. Three things move as one unit or the dispatch breaks: the key, the `git_author` derived from it (only when its email is still `<old key>@bot.invalid` — a customised identity is the operator's), and every `routines[<name>].expert` naming it. The routine's own key is NOT touched — it is on the other side of the split and already canonical.
2. **Hook short names** — entries in a routine's `hooks_enabled` or in `hooks.disabled` that are not a shipped hook's canonical name (the stem of its file under `<plugin>/hooks/`).
3. **Seeded consumer files** — a file under `.claude/templates/` whose name matches a shipped template's pre-namespace form while the plugin now seeds it namespaced. The seeding install step only ever writes the canonical name; moving a consumer's customised copy is this phase's job, not the installer's, so one place owns every such rename rather than seven install skills each carrying their own.

Emit one finding per drifted name. The fix is a rename in place — the settings key, or `mv` for a file — never a delete and never a fresh default written beside the old copy: the consumer's own content moves to the canonical name. A routine rename also carries its `last_run` entry in the daemon state, so the routine does not read as never-run and fire an unscheduled pass.

Finding schema:

- `[WARN] <kind> `<current>` is outside the naming canon (→ `<canonical>`) | <where>` `detail: <plugin> owns the `lazy-*` namespace for this key` `fix: rename in place (auto-applied in Phase 4)`
- Expert key (surface 1a, reverse direction): `[WARN] expert key `<current>` carries a plugin namespace (→ `<canonical>`) | lazy.settings.json` `detail: an expert key is `<domain>.<role>`; `<plugin>:<agent>` stays the artifact reference` `fix: rename key + derived git_author + every routines[].expert naming it (auto-applied in Phase 4)`

Silent when nothing drifted. A name whose owning plugin cannot be resolved is left alone — an unresolvable owner is not evidence of drift.

**Dead settings keys (same pass, same finding style).** Keys of retired features are dead config — the precedent is the `agent_models` prune of deleted agents. Scan the merged `lazy.settings.json` for: `isolate` or `allow_merge` inside any `routines[<name>]` block, and `daemon.git.max_concurrent_tasks` (all retired with the routine-side worktree path; the runtime ignores them with a stderr warning). Emit one finding per occurrence:

- `[WARN] dead key `<key>` in `<where>` — retired with the routine-side worktree path` `fix: delete the key (offered in Phase 4)`

The fix deletes the key only, never the enclosing routine or git block. Silent when none present.

**Bot-identity domain canon (same pass, same finding style).** Every automatic git identity uses the `@bot.invalid` domain (RFC 2606 — undeliverable by construction, and recognised as-is by every consumer that classifies commits by the `@bot.` substring). Scan the merged `lazy.settings.json` for any `experts[<name>].git_author.email` or `routines[<name>].git_author.email` that does not end in `@bot.invalid`. Emit one finding per occurrence:

- `[WARN] bot identity `<email>` in `<where>` is off the `@bot.invalid` canon` `detail: loop-detect and coordinator operator-vs-bot checks key on the canonical domain` `fix: rewrite the domain, keeping the local part (offered in Phase 4)`

Silent when every identity is canonical or no `git_author` blocks exist.

**Sanitizer-routine registration (same pass, same finding style).** The state sanitizers only run when their routines are registered, and an install that predates them leaves a daemon-enabled repo silently unsanitized. When the merged settings carry `daemon.enabled: true`, check per enabled plugin (enabled-set per `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md`):

- `lazycortex-core` → `routines["lazy-core.autocheckup"]` present.
- `lazycortex-review` (with a `review` settings section) → `routines["lazy-review.sanitize"]` present.
- `lazycortex-wiki` (with a non-empty `wiki.scopes`) → `routines["lazy-wiki.doctor-apply"]` present.

Emit one finding per missing routine:

- `[WARN] sanitizer routine `<name>` is not registered while the daemon is enabled | lazy.settings.json` `fix: re-run /<owning-namespace>.install (offered in Phase 4)`

Silent when the daemon is disabled, the owning plugin is disabled or unconfigured, or every routine is present.

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
- *Run condition*: `.guard-public.json` exists at the repo root.
- *On invoke*: fold guard's summary (category × severity counts, waivered count) and FAIL/WARN findings into a **Guard** subsection.

**11b. Logging coverage** — inline, via `lazy-core.audit` Phase 1 checks
- *Availability*: `lazycortex-core` meets the canonical signal set above.
- *Run condition*: always — the logging compliance checks live in `lazy-core.audit` Phase 1 and apply whenever the plugin is enabled.
- *On invoke*: run the L1–L4 logging compliance checks from `lazy-core.audit` Phase 1 inline (do NOT dispatch a separate skill — execute the same logic described there). Fold findings into a **Logging** subsection.

**11c. Diagram coverage** → `lazy-diagram.audit`
- *Availability*: `lazycortex-diagram` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Diagram** subsection.

**11d. Observe coverage** → `lazy-observe.audit`
- *Availability*: `lazycortex-observe` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into an **Observe** subsection.

**11e. Review coverage** → `lazy-review.audit`
- *Availability*: `lazycortex-review` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Review** subsection.

**11f. Expert runtime** — inline, via `lazy-core.audit` Agent D findings
- *Availability*: always (expert-runtime checks are part of `lazycortex-core` itself — no separate plugin probe needed).
- *Run condition*: `.claude/lazy.settings.json` contains a non-empty `experts` section, a `lazy-core.runtime` section, **or a non-empty `external_dirs.paths` list**. Skip if none is present (no expert runtime configured — silent skip, no report entry). Test the `paths` list, never the section: a settings migration stamps a `{"_version": 1}` stub for every known section into every repo, so "non-empty section" would match everywhere and defeat the skip.
- *On invoke*: run the Agent D sub-checks from `lazy-core.audit` inline (do NOT dispatch a separate skill — just execute the same D1–D15 logic described in `lazy-core.audit`'s Agent D section). Fold findings into a **Loop runtime** subsection. Retain all D-findings for Phase 4 fix-offer matching (see "Loop runtime fix offers" in Phase 4).

**11g. Obsidian coverage** → `lazy-obsidian.audit`
- *Availability*: `lazycortex-obsidian` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into an **Obsidian** subsection.

**11h. Python coverage** → `lazy-python.audit`
- *Availability*: `lazycortex-python` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in.
- *On invoke*: fold audit findings into a **Python** subsection.

**11i. Description triggers** — inline, via `lazy-core.audit` skill-writing check 5 + agent-writing check 2
- *Availability*: always — the contract lives in `lazycortex-core` itself.
- *Run condition*: at least one file in `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md`, `.claude/agents/*.md`, `claude/*/agents/*.md`, `.claude/commands/*.md`, or `claude/*/commands/*.md`. No local skills, agents, or commands → silent skip.
- *On invoke*: `Read` `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md`, then judge every one of those files' `description:` against it inline (do NOT dispatch a separate skill). One `[WARN]` per mechanism-only description, `[FAIL]` per missing one; fold into a **Description triggers** subsection. A description that will not fire is invisible to the router, so the count matters as much as the individual lines — lead the subsection with `<n> of <total> descriptions carry no trigger`.

**11j. `Agent`-tool presence** — inline, via `lazy-core.audit` skill-writing check 6 + agent-writing check 5
- *Availability*: always — the contract lives in `lazycortex-core` itself.
- *Run condition*: at least one file in `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md`, `.claude/agents/*.md`, or `claude/*/agents/*.md`. No local skills or agents → silent skip.
- *On invoke*: for each agent file, grep `^tools:` and flag `[WARN]` when present but missing `Agent`; for each skill file, grep `^allowed-tools:` and flag `[WARN]` the same way (a skill with no `allowed-tools:` field is out of scope — it inherits the caller's tools). Never flag `Agent`'s presence. Fold into an **Agent-tool coverage** subsection.

**11k. Research-marker semantics** — inline, via `lazy-core.audit` skill-writing check 7
- *Availability*: always — the contract lives in `lazycortex-core` itself.
- *Run condition*: at least one file in `.claude/skills/*/SKILL.md` or `claude/*/skills/*/SKILL.md`. No local skills → silent skip.
- *On invoke*: judge each skill's description/body against the research-marker convention per `lazy-core.skill-writing § 10` (do NOT dispatch a separate skill); flag `[WARN]` per missing-marker or marker-without-query-contract finding. Fold into a **Research markers** subsection.

**11l. Specs plugin coverage** → `lazy-spec.audit`
- *Availability*: `lazycortex-specs` meets the canonical signal set above.
- *Run condition*: same as availability — plugin installation / enablement is the opt-in; no further gate.
- *On invoke*: fold audit findings into a **Specs** subsection.

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

### Applied (<N>)
- <check_id> | <path> — <what changed, one line>
(omit the whole section when N == 0)

### Fixes available
- [ ] Fix 1: <description>
- [ ] Fix 2: <description>

Apply? [y/N]
```

Fixes split into two classes, marked per bullet below:

- **(auto)** — the correct result follows from what the check already read; there is no second defensible answer. Doctor writes it during the run and records one line under `### Applied`. No prompt, no diff preview. The write is small, in-file, and recoverable from git.
- **(ask)** — the fix encodes a decision the checks cannot derive (a rule's audience, whether a plugin should be enabled), or it deletes something. Doctor proposes and waits.

After the report, ask the user which of the **(ask)** fixes to apply, and apply only those. Then enter the **per-WARN waive loop** described in 4a below. Fixes available in-coordinator:

- Rules oversized (ask) → suggest running `/lazy-core.optimize`; don't auto-slim here.
- Rule drift on an install-managed rule (auto) → restore the file from the owning plugin's shipped source. A plugin rule is not an editing surface: a project that needs different behaviour writes its own rule alongside it, so a divergence from the plugin source is stale content rather than a deliberate override, and preserving it means the consumer silently runs on a rule the plugin no longer ships. Identify install-managed status from the owning install skill's registry (`lazy-log.*` rules are owned by `/lazy-core.install`), never from the filename. Report which rules were restored so an operator who did mean to edit one sees it immediately.
- Orphan rule — a `.claude/rules/*.md` no installed plugin claims (ask) → report; deleting a file whose owner is simply not installed right now is not doctor's call.
- Missing rules frontmatter (mixed) → `description:` is derived from the rule body and written (auto). The scope key (`paths:` vs `always_loaded:`) is a separate decision — see the next bullet.
- Rule lacks scope AND waiver (ask) → ask the user, per rule, whether the rule is legitimately always-loaded. If yes, add `always_loaded: <reason>` (reason must be substantive — one line explaining *why* every turn needs it, not `true`). If no, add a `paths:` block-list narrowing it to the folders where it applies. Show the proposed frontmatter diff before writing. Never auto-pick a scope — only the user knows the rule's true audience.
- Inline-array `paths:` shape (FAIL from `lazy-core.audit` rule-writing check 3) (auto) → in-place migration to canonical YAML block-list. Parse the existing `paths: ["a", "b", ...]` line, preserve all globs verbatim (including quote style), rewrite as a key on its own line followed by one `  - "<glob>"` per array element. No glob is added, dropped, or reworded, so the rule's scope is byte-equivalent before and after.
- Authoring rule without template reference (WARN from `lazy-core.audit` rule-writing check 9) (auto) → two-step scaffold. (1) Derive `<artifact-type>` from the rule filename (`*.writing.md` → strip `-writing`/`.writing` and pluralize as needed; e.g. `lazy-core.skill-writing.md` → `skill`), copy the matching base template (`<plugin>/templates/core/{rule,skill,agent}-template.md`) to `<plugin>/templates/<group>/<derived-name>-template.md`, with `<group>` = the plugin's primary namespace (`core` for `lazycortex-core`). (2) Prepend `**Template:** ${CLAUDE_PLUGIN_ROOT}/templates/<group>/<derived-name>-template.md — start here when creating a new <artifact-type>.` immediately after the rule's H1 + orientation paragraph, before the first `## ` section. Per `lazy-core.scaffold`. Both the derived name and the group follow from names already on disk; a maintainer who wants a different group renames the file afterwards.
- `description:` without a trigger — WARN (mechanism-only) or FAIL (absent) from Phase 3 § 11i (auto) → rewrite the line. `Read` `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md` and the artifact's own body, then grep the artifact's name across `.claude/` and `claude/` before claiming a caller trigger — the trigger states what the file does and who invokes it, and both are already written in the body and the call sites. `Edit` that one frontmatter line and nothing else — not the body, not another key — and record old and new under `### Applied` so a wrong trigger is one line to spot and revert. The single exception is an artifact with no substantive body to read from (an empty or stub file): nothing to derive, so it stays a report.
- Missing mandatory routine protocol (auto): `Bash(lazycortex-core add-protocols --routine <name> --ids <id>)` per finding. The routine and the protocol both come from the check's own table, and the union only appends — nothing the operator attached is touched.
- Memory index (auto): add missing entries, remove broken links; flag stale for review.
- Settings leakage (auto): move each misplaced key to the file the split in `rules/lazy-core.hygiene.md` assigns it.
- Permissions leakage into tracked `settings.json` (auto): move the entire `permissions.*` block (both `allow` and `ask` arrays) from tracked `settings.json` to the paired `settings.local.json`. Merge with any existing entries there, preserving order and deduplicating. Leave `enabledPlugins`, `hooks`, `env`, `enabledMcpjsonServers`, and similar enablement flags in the tracked file untouched. The destination is fixed by the hygiene split, and the permission set itself is unchanged by the move.
- Undeclared plugin marketplace (auto, only when the source resolved): add `<marketplace>` to `extraKnownMarketplaces` in the settings file that enables the plugin, copying the resolved block verbatim (`source`, plus `autoUpdate` when present — never `installLocation` / `lastUpdated` from `known_marketplaces.json`). Purely additive; touches nothing else in the file. When the source did not resolve, report only — inventing a marketplace source is the operator's call.
- Gitignore coverage (auto): append missing patterns under a dedicated language section.
- Path hygiene (auto): replace hardcoded paths with their relative or `$HOME`-anchored equivalents.
- Stale `enabledMcpjsonServers` entry naming a server no `.mcp.json` defines (auto): remove it.
- MCP enablement (ask): either set `enableAllProjectMcpServers: true` in global settings or add `enabledMcpjsonServers` to project settings — which servers this project trusts is the operator's call.
- MCP tools not whitelisted (ask): invoke `lazy-guard.allow-mcp <server>` for each confirmed finding — do NOT write `permissions.allow` directly from doctor. `allow-mcp` owns scope-routing, dedup, and cross-scope cleanup; reusing it keeps both skills consistent.
- Agents / skills / CLAUDE.md / hook scripts — report only, never auto-edit. The one carve-out is the `description:` frontmatter line, via the rewrite above; every other byte of a skill or agent stays report-only.
- Plugin dependency warnings (ask) — report only; fixing requires enabling the missing plugin in `settings.json` (user's decision) or editing the declaring plugin's manifest.
- Plugin outdated (Phase 2.5) (auto) → run `Bash(claude plugin update <name>)` and record the version delta under `### Applied`. The update itself is mechanical — the marketplace decides the target version, not doctor. What doctor cannot finish is the tail: the CLI applies the new files only after a session restart, and a MINOR bump means `/<namespace>.install` has to run against those new files, i.e. after the restart. So every applied update also emits a report line naming both follow-ups. In release mode, Phase 2.6 suppresses content findings on this plugin's owned rules — the suppression counter is surfaced so the user knows to re-run after upgrading.

### Loop runtime fix offers

These seven fix offers are conditional on findings from Phase 3 § 11f. Each is offered via `AskUserQuestion` only when the corresponding finding is present in the Loop runtime subsection.

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

`AskUserQuestion`: "Found <N> orphan job director(y/ies) under `.jobs/` for experts no longer in `lazy.settings.json[experts]`. Delete them?"

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

`AskUserQuestion`: "Routine `<name>` references plugin bin path `<path>` which does not exist. The plugin may not be installed. Unregister the routine from `routines`?"

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

**Fix L4 — External directory broken** (trigger: D11 FAIL, status `missing` / `dangling` / `wrong_target`)

`AskUserQuestion`: "<N> declared external director(y/ies) do not resolve in this checkout (<comma-joined paths>). Re-link them from `external_dirs.root`?"

Options: `Re-link`, `Skip`.

On Re-link:
```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from external_dirs import apply
from pathlib import Path
for r in apply(Path('.')):
  print(f\"{r['path']}: {r['action']}\")
")
```
Report one line per path. `not_a_symlink` and `source_missing` rows are never offered here — real content and an absent source are reported only.

**Fix L5 — Shared inbox** (trigger: D12 FAIL `inbox_collision`)

Report only, no fix offer: print the conflicting `other_repo` and state that one of the two projects must stop naming a checkout on this host in its `daemon.run_here`. Doctor does not choose which checkout drives a shared inbox.

**Fix L6 — `daemon.git` unconfigured** (trigger: D3 FAIL "daemon.enabled is true but daemon.git is null" or "daemon.git missing required field base_branch")

`AskUserQuestion`: "The daemon is enabled but `daemon.git` carries no `base_branch`, so it rides no branch and never syncs with origin — routine commits stay in this checkout. Derive the block from this checkout?"

Options: `Derive`, `Skip`.

The derived values are shown in the question description before the write: `base_branch` = the current branch, `remote_sync` = `pull_push` when an `origin` remote exists (omitted otherwise).

On Derive:
```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_install_phases import bootstrap_daemon_git
from pathlib import Path
print(bootstrap_daemon_git(Path('.')))
")
```
Report the receipt verbatim: `seeded`, `kept-local`, or `skipped-no-branch`. `kept-local` here means the block acquired content between the scan and the fix — re-run the audit rather than writing again.

**Fix L7 — Sandbox scope misses a resolved location** (trigger: D13 FAIL / WARN)

`AskUserQuestion`: "The expert-spawn sandbox does not cover <N> location(s) its own allowlist resolves to (<comma-joined paths>). Confined spawns fail every write there with `Operation not permitted`. Record them?"

Options: `Record`, `Skip`.

On Record:
```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from sandbox_scope import sync
from pathlib import Path
r = sync(Path('.'))
print(f\"changed={r['changed']} added_write={r['added_write']}\")
")
```
Report the receipt verbatim. The file is gitignored daemon state, so there is nothing to commit. The sync appends only what is missing and never drops a recorded entry.

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
- **Phase 3 § 11f skipped unexpectedly** — none of an `experts` section, a `lazy-core.runtime` section, or a non-empty `external_dirs.paths` list was found in `lazy.settings.json`. If expert runtime is configured but the file is in a non-standard location, run `/lazy-core.audit` directly to surface Agent D findings without the skip guard.

## Logging

Log to `./.logs/claude/lazy-core.doctor/YYYY-MM-DD_HH-MM-SS.md`. Use `Bash(mkdir -p ...)` then `Write` tool (never chain).

The `## Actions` section must include, in addition to the usual run details:

- **Backend discovery** — one line per scope recording which backends were reachable (e.g. `backend discovery (project): file=ok, mcp=<discovered server name or 'none'>`).
- **Waiver recall counts** — per backend / per scope (`recall: file=<N>, mcp=<N>`), plus an `INFO` line for any fingerprint held by both backends (`both-backends: <fingerprint> (file wins)`).
- **Suppressed findings** — one line per finding dropped by Phase 2.7: `waived finding suppressed: <check_id> | <normalized_path>`.
- **Newly written waivers** — one line per write: `waiver written: <check_id> | <normalized_path> → <backend>:<location>`.
- **Waive-option downgrades** — one line per finding where every backend for the resolved scope failed and the option was gracefully downgraded to Skip: `waive unreachable: <check_id> | <normalized_path> — all backends failed, treated as skip`.
