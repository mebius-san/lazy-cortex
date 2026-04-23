---
name: lazy-core.audit
description: "Quick read-only audit of what gets loaded into conversation context at startup. Shows sizes, loading behavior, and optimization opportunities. No changes made."
allowed-tools: Read, Glob, Grep, Bash(wc *)
---
# Context Audit

Coordinator skill. Dispatches two **Explore** subagents in parallel to measure context weight and hygiene, then renders the tables. Read-only — no changes made.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern.

**CRITICAL PATH RULE** (applies to every dispatched agent): `~/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `~/.claude/`. `wc -c` via Bash is allowed ONLY for paths under the project root.

**Size estimation**: for Read-measured files use `size ~ lines × 45 bytes`; for `wc -c` use exact bytes.

## Phase 1 — Dispatch parallel scans

Dispatch these two Explore agents **in a single message with two Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each returns the structured report from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. Budget: "Report under 350 words".

Severity vocabulary for this skill: `INFO` (measurement row) / `WARN` (recommendation). No `FAIL`.

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

**Naming hygiene** — for `.claude/skills/*/`, `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/hooks/*`, `.claude/rules/*.md`: filename (or directory name for skills) must use dot-namespace (`namespace.name`). `[WARN]` for anything missing a dot (e.g., `logging.md` → `<namespace>.logging.md`).

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

### Recommendations

- Rules file > 3 KB → flag for slimming (run `/lazy-core.optimize`).
- Memory index > 5 KB → suggest consolidation.
- Hardcoded paths found → run `/lazy-core.doctor` for details.
- Note: system prompt, skill registry, MCP instructions, deferred tool list are injected by Claude Code and cannot be reduced by the user.
