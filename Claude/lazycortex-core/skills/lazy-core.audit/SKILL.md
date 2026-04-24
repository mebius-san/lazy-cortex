---
name: lazy-core.audit
description: "Quick read-only audit of what gets loaded into conversation context at startup plus skill-writing, agent-writing, and rule-writing compliance. Shows sizes, loading behavior, optimization opportunities, Execution-Discipline preamble presence, no-Optional headings, narrative-padding heuristics, and rule-file frontmatter/size/code-block/scope enforcement. No changes made."
allowed-tools: Read, Glob, Grep, Bash(wc *)
---
# Context Audit

Coordinator skill. Dispatches two **Explore** subagents in parallel to measure context weight and hygiene, then renders the tables. Read-only — no changes made.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern.

**CRITICAL PATH RULE** (applies to every dispatched agent): `~/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `~/.claude/`. `wc -c` via Bash is allowed ONLY for paths under the project root.

**Size estimation**: for Read-measured files use `size ~ lines × 45 bytes`; for `wc -c` use exact bytes.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Dispatch parallel scans`
   - `Phase 2 — Render (Report)`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Dispatch parallel scans

Dispatch these two Explore agents **in a single message with two Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each returns the structured report from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. Budget: "Report under 350 words".

Severity vocabulary for this skill: `INFO` (measurement row or visible waiver) / `WARN` (recommendation or heuristic flag) / `FAIL` (structural violation — Agent B compliance checks across skill-writing, agent-writing, and rule-writing: missing preamble, invalid waiver, "Optional" heading, missing rule frontmatter or scope, oversize rule, code block > 10 lines, `AskUserQuestion` inside agent body).

### Agent A — always-loaded context

Measure everything that loads at conversation start. Include these sources as one `[INFO]` finding per source, sorted by size desc:

- **Global CLAUDE.md** (`~/.claude/CLAUDE.md`) — Read, estimate size.
- **Project CLAUDE.md** (`CLAUDE.md`) — Read, estimate size.
- **Global rules** (`~/.claude/rules/*.md`) — Glob + Read. If the directory is a symlink, resolve and follow it. Only rules **without** a `paths` frontmatter field count as always-loaded; rules with `paths` are on-demand and belong to Agent B.
- **Project rules** (`.claude/rules/*.md`) — `wc -c` via Bash. Same `paths` filtering rule.
- **Memory index** (`~/.claude/projects/*/memory/MEMORY.md`) — Read, estimate size.

Also emit `[WARN]` findings for:

- Any rules file > 3 KB (suggest `/lazy-core.optimize`).
- `MEMORY.md` > 5 KB (suggest consolidation).

Include a `total_kb` line in the summary block.

### Agent B — on-demand assets, MCP, path + naming hygiene

Scope covers everything not loaded at startup, plus hygiene grep work.

**On-demand sizing** (one `[INFO]` per source):

- Agents (`.claude/agents/*.md`) — `wc -c` via Bash.
- Project commands (`.claude/commands/*.md`) — `wc -c` via Bash.
- Global commands (`~/.claude/commands/*.md`) — Glob + Read.
- Project skills (`.claude/skills/*/SKILL.md`) — `wc -c` via Bash.
- Global skills (`~/.claude/skills/*/SKILL.md`) — Glob + Read.
- Memory files (individual `~/.claude/projects/*/memory/*.md` except `MEMORY.md`) — Glob to count.
- On-demand rules (rules files with a `paths` frontmatter field).

Include a `total_kb` line for on-demand sources in the summary block.

**MCP enablement** — read `~/.mcp.json`, `.mcp.json`, `~/.claude/settings.json`, `~/.claude/settings.local.json`, `.claude/settings.json`, `.claude/settings.local.json`. Determine mode:

- Mode A: global `enableAllProjectMcpServers: true` → every project `.mcp.json` entry is implicitly enabled; suppress "declared but unused" warnings.
- Mode B: `enableAllProjectMcpServers` false or missing → server enabled only if its name appears in `enabledMcpjsonServers` of project settings.

Emit one `[INFO]` per enabled server. Emit `[WARN]`:

- Mode B only: server in project `.mcp.json` not enabled under any rule above.
- Mode B only: non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere.
- Always: name in `enabledMcpjsonServers` with no definition in `.mcp.json` or `~/.mcp.json`.

**Path hygiene** — grep every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`) and emit `[WARN]` for:

- `/Users/` or `/home/` — hardcoded absolute paths.
- `<project>/` prefix — should be relative.
- `~/Dropbox/` or other user-specific home subdirectories.
- `~/.claude/` used for items that are actually project-local (project agents / rules / settings) instead of relative `.claude/`.

**Exclusions** (suppress the match — do not emit a WARN if any gate matches):

- **Inside backticks on the line** — `` `~/Dropbox/` ``, `` `/Users/foo` ``, etc. Backticked strings are code/pattern literals, not operational paths the file uses at runtime.
- **Inside a fenced code block** (between ` ``` ` fences) where the line or the block's preceding prose contains `e.g.` — illustrative examples in documentation, not operational config.
- **Any line containing `e.g.`** — the author has explicitly marked the path as an example.

Emit WARN only when the match survives all three gates.

**Naming hygiene** — for `.claude/skills/*/`, `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/hooks/*`, `.claude/rules/*.md`: filename (or directory name for skills) must use dot-namespace (`namespace.name`). `[WARN]` for anything missing a dot (e.g., `logging.md` → `<namespace>.logging.md`).

**Skill-writing compliance** — see `lazy-core.skill-writing` (plugin) / `.claude/rules/dev.skill-writing.md` (local pointer). File set: `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md` (commands exempt from the preamble check). Three checks:

1. **Preamble present** — grep each file for `^## Execution discipline (MANDATORY`. Absent AND no `execution-discipline-waiver:` in frontmatter → `[FAIL]`. Frontmatter carries a non-empty `execution-discipline-waiver: "<reason>"` string → `[INFO]` with the waiver reason (visible, not silent). Frontmatter carries `execution-discipline-waiver: true` / `yes` / `""` → `[FAIL]` (invalid waiver).
2. **No "Optional" in phase/step headings** — grep for `^##+ .*[Pp]hase.*[Oo]ptional`, `^##+ .*[Ss]tep.*[Oo]ptional`, and any `^### .*[Oo]ptional`. Match → `[FAIL]`.
3. **Narrative padding (heuristic)** — grep the body (exclude frontmatter) for the denylist: `\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`, `user had to patch`. Match → `[WARN]` with the offending line. Final decision is the author's — heuristic, not structural.

**Agent-writing compliance** — see `lazy-core.agent-writing` (plugin) / `.claude/rules/dev.agent-writing.md` (local pointer). File set: `.claude/agents/*.md`, `claude/*/agents/*.md`. Checks:

1. **Frontmatter complete** — `name`, `description`, `tools` all present. Missing any → `[FAIL]`.
2. **Preamble present** (for multi-phase agents) — same check as skill-writing §1. Agents with `## Phase N` or `## Process` sections must carry the preamble OR a valid `execution-discipline-waiver:` string. Same FAIL/INFO vocabulary.
3. **No `AskUserQuestion` in agent body** — grep for `AskUserQuestion` outside fenced code/frontmatter. Match → `[FAIL]` (agents have no user channel).
4. **Tool allowlist hygiene** — `tools: ["*"]` → `[WARN]` (unless a justification comment on the same line).
5. **No "Optional" in phase/step headings** — same as skill-writing §2 → `[FAIL]`.
6. **Narrative padding (heuristic)** — same denylist as skill-writing §3 → `[WARN]`.

**Model routing** — read both `./.claude/lazy.settings.json` (project scope) AND `~/.claude/lazy.settings.json` (user scope); missing files are silent no-op, not a finding. Build a merged-with-provenance view of `agent_models`:

1. **Files present** — emit `[INFO]` per scope: `lazy.settings.json scope=project path=<path>` or `lazy.settings.json scope=project (missing)`; same for `global`.
2. **No config anywhere** — if BOTH scopes are missing, emit `[WARN] no lazy.settings.json found (project: <path>, global: <path>) — agent routing disabled. Run /lazy-core.optimize to create and fill.` Skip the remaining checks (merged view / orphans / gaps / invalid values) since there is nothing to validate.
3. **Merged entries** — for every dispatch-string key across both scopes, emit one `[INFO]`: `agent_models <group>.<key> = <value> (<provenance>)`. Provenance is `project`, `global`, or `project, overrides global=<other>` when both scopes carry the same key with different values. Group entries together in the report render by their top-level group name.
4. **Orphans** — any key in either scope that does NOT resolve to a discovered agent (see Agent discovery below). Finding: `[WARN] orphan agent_models entry: <group>.<key> (<scope>)`.
5. **Gaps** — discovered agents with no entry in any scope (exclude agents explicitly set to `"inherit"` in either scope — those are explicit decisions, not gaps). Finding: `[INFO] no agent_models entry for <dispatch-string> (from <source>) — run /lazy-core.optimize to fill`.
6. **Invalid values** — any value not in `{"haiku", "sonnet", "opus", "inherit"}`. Finding: `[WARN] invalid value <x> for <group>.<key> (<scope>)`.
7. **Env-var status** — emit `[INFO]` with `LAZY_AGENT_MODEL_FLOOR=<value>` and a tier-order note (`haiku < sonnet < opus`), else `LAZY_AGENT_MODEL_FLOOR=(unset)`.

**Agent discovery (shared helper — used by audit, optimize, doctor)**. Deduped by full dispatch string:

1. **Built-ins** — hardcoded list: `Explore`, `Plan`, `general-purpose`, `statusline-setup`. Group: `_builtin`. Dispatch string: bare name.
2. **User-authored, global** — `~/.claude/agents/*.md`. Group: `_user`. Dispatch string: bare filename stem.
3. **User-authored, project** — `./.claude/agents/*.md`. Group: `_project`. Dispatch string: bare filename stem. (Project entries shadow global entries of the same stem — both still listed separately with provenance.)
4. **Plugin-shipped** — `~/.claude/plugins/cache/**/agents/*.md`. Extract plugin name from path (`~/.claude/plugins/cache/<marketplace>/<plugin-name>/<version>/agents/<agent>.md` → plugin = `<plugin-name>`). Group: **domain** derived from plugin name via the domain-extraction rule (first `-`-delimited segment, or full name if no `-`). Dispatch string: `<plugin-name>:<stem>`.

**Rule-writing compliance** — see `lazy-core.rule-writing` (plugin) / `.claude/rules/dev.rule-writing.md` (local pointer). File set: `.claude/rules/*.md`, `~/.claude/rules/*.md`, `claude/*/rules/*.md`. Checks:

1. **Frontmatter present** — YAML frontmatter with at minimum `description:`. Absent → `[FAIL]`.
2. **Scope or waiver** — frontmatter must carry EITHER `paths: ["<glob>", ...]` OR `always_loaded: "<reason>"`. Neither present → `[FAIL]`. `always_loaded: true` / `always_loaded: ""` → `[FAIL]` (invalid waiver).
3. **Size budget** — `always_loaded:` rule > 3 KB → `[FAIL]`. `paths:`-scoped rule > 10 KB → `[WARN]`. `paths:`-scoped rule > 25 KB → `[FAIL]`.
4. **Code-block size** — any fenced code block > 10 lines → `[FAIL]`.
5. **Dot-namespace filename** — filename without dot separator → `[WARN]`.
6. **Broken artifact reference** — slash-commands, subagent-types, rule filenames, `references/…` paths, hook paths, `skills/<name>/SKILL.md` paths that don't resolve on disk → `[WARN]`. Markdown section headings (`## Phase 2.5`) are NOT checked.
7. **Narrative padding (heuristic)** — same denylist as skill-writing §3 → `[WARN]`.

## Phase 2 — Render

Parse both returned blocks. Produce:

### Always loaded (startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent A `[INFO]` finding, sorted by size descending) |

**Total always-loaded**: ~X KB

### On-demand (no startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent B on-demand `[INFO]` finding, sorted by size descending) |

**Total on-demand**: ~X KB

### MCP servers

List enabled servers and the mode in effect. Flag any WARN findings from Agent B's MCP section.

### Path hygiene

One line per Agent B path-hygiene `[WARN]`.

### Naming hygiene

One line per Agent B naming `[WARN]`.

### Skill-writing compliance

- **Missing Execution-Discipline preamble** (FAIL) — one line per finding (skills only).
- **"Optional" in phase/step heading** (FAIL) — one line per match.
- **Waivered files** (INFO) — one line per file with `execution-discipline-waiver: "<reason>"`.
- **Narrative-padding heuristic** (WARN) — one line per match with the offending line.

### Agent-writing compliance

- **Frontmatter incomplete** (FAIL) — one line per agent missing `name`/`description`/`tools`.
- **Missing preamble** (FAIL) — multi-phase agents without preamble and without valid waiver.
- **`AskUserQuestion` in agent body** (FAIL) — one line per match.
- **`tools: ["*"]` without justification** (WARN) — one line per match.
- **"Optional" in heading** (FAIL) — one line per match.
- **Narrative-padding heuristic** (WARN) — one line per match.

### Model routing

Render the merged-with-provenance view grouped by top-level group name:

```
[_builtin]
  <dispatch-string>                        <value>    (<provenance>)

[_user]
  <dispatch-string>                        <value>    (<provenance>)

[_project]
  <dispatch-string>                        <value>    (<provenance>)

[<domain>]
  <dispatch-string>                        <value>    (<provenance>)
```

One line per entry. Below the table:

- **Orphans** (WARN) — one line per `orphan agent_models entry` finding.
- **Gaps** (INFO) — one line per `no agent_models entry for ...` finding.
- **Invalid values** (WARN) — one line per invalid-value finding.
- **Env-var** (INFO) — `LAZY_AGENT_MODEL_FLOOR=<value>` with tier-order note, or `(unset)`.

### Rule-writing compliance

- **Missing frontmatter** (FAIL) — one line per rule without YAML frontmatter.
- **Missing scope or waiver** (FAIL) — neither `paths:` nor `always_loaded:`, or invalid `always_loaded` (true/empty).
- **Size over budget** (FAIL / WARN) — `always_loaded:` > 3 KB; `paths:` > 10 KB (WARN) or > 25 KB (FAIL).
- **Code block > 10 lines** (FAIL) — one line per match.
- **Filename lacks dot separator** (WARN) — one line per match.
- **Broken artifact reference** (WARN) — one line per unresolved reference.
- **Narrative-padding heuristic** (WARN) — one line per match.

### Recommendations

- Memory index > 5 KB → suggest consolidation.
- Hardcoded paths found → run `/lazy-core.doctor` for details.
- Missing Execution-Discipline preamble → add per `lazy-core.skill-writing § 1` (or `lazy-core.agent-writing § 4`), or declare `execution-discipline-waiver: "<reason>"` in frontmatter with a concrete justification.
- Rule missing scope or waiver → add `paths: ["<glob>"]` (preferred) or `always_loaded: "<reason>"` per `lazy-core.rule-writing § 1`.
- Rule over size budget → move long guidance to `<plugin>/skills/<skill>/references/*.md` per `lazy-core.rule-writing § 2`.
- "Optional" in phase/step heading → rename the heading; the user's accept/decline choice belongs inside an `AskUserQuestion`, not at the heading level.
- Narrative-padding match → review and drop the passage if its removal leaves executable behavior unchanged.
- Note: system prompt, skill registry, MCP instructions, deferred tool list are injected by Claude Code and cannot be reduced by the user.
