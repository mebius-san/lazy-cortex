---
name: lazy-core.optimize
description: "Optimize Claude Code context loading for the current project. Slims oversized rules files by moving reference material to agent definitions, audits global settings for project-specific leakage and moves entries to local settings. Run when startup feels slow or after adding new rules/agents."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(mkdir -p *)
---

# Context Optimization

Reduce startup context weight and fix settings layer violations for the current project.

## Phase 1: Audit context weight

Measure everything that loads at conversation start.

### 1a. Always-loaded context budget

Measure byte sizes of everything Claude Code loads into every session's context on every turn:

- `~/.claude/CLAUDE.md` (global instructions)
- `<project>/.claude/CLAUDE.md` (project instructions) — also `CLAUDE.md` at repo root if present
- Every `~/.claude/rules/*.md` **without** a `paths:` key in YAML frontmatter (scoped rules only load when files matching their glob are touched, so they don't count)
- Every `<project>/.claude/rules/*.md` **without** a `paths:` key
- `~/.claude/projects/<project-key>/memory/MEMORY.md` (memory index — auto-loaded)

Thresholds (mirror `lazy-core.doctor`): total > 20 KB → WARN, > 40 KB → FAIL. This is the real token budget — each turn pays this cost.

### 1b. On-demand files (no startup cost)

Count and total sizes of:
- `.claude/agents/*.md`
- `.claude/skills/*/SKILL.md`
- `.claude/commands/*.md`
- `~/.claude/commands/*.md` (global commands)
- `~/.claude/skills/*/SKILL.md` (global skills)
- Individual memory files (everything in memory dir except MEMORY.md)

### 1c. Report

Show two tables (always-loaded sorted by size desc, on-demand sorted by size desc) with file path, size, and count. Show totals for each category.

## Phase 2: Fix oversized rules files

For each rules file **over 3 KB**:

1. Read the rules file and identify its corresponding agent(s):
   - Check if the rules file mentions an agent file path
   - Check `.claude/agents/` for agents that reference this rules file
   - If no matching agent exists, flag it (the content has nowhere to go)

2. Classify every section as **constraint** or **reference**:
   - **Constraint**: prohibitions, "never do X", "always do Y", one-liner facts needed by every conversation
   - **Reference**: layouts, tables, API details, code examples, procedures, migration history, version tables

3. Show the classification to the user and ask for confirmation before proceeding.

4. Rewrite:
   - Rules file: keep only constraints as a bullet list (target < 2 KB)
   - Agent file: absorb all reference sections, organized under `## Reference: <topic>` headers

5. After rewriting, re-measure and show the before/after comparison.

## Phase 2.5: LLM-readability audit

Every file under this phase's scope is authored for the LLM, not humans. Detect constructs that look clear on a page but hurt LLM comprehension — decision-logic tables, narrative preamble, cross-references without anchors, decorative markers, and long prose where bullets would serialize better. Rewrites require per-finding user confirmation.

### 2.5a. Scope

Scan every LLM-consumed artifact file:

- `.claude/rules/*.md`, `~/.claude/rules/*.md`
- `.claude/skills/*/SKILL.md`, `~/.claude/skills/*/SKILL.md`
- `.claude/agents/*.md`, `~/.claude/agents/*.md`
- `.claude/commands/*.md`, `~/.claude/commands/*.md`
- `.claude/skills/*/references/*.md`, `~/.claude/skills/*/references/*.md`

**Excluded:** `README*.md`, `CHANGELOG.md`, `docs/**`, `CLAUDE.md` at any scope, and any non-`.md` file.

### 2.5b. Dispatch parallel scan

Dispatch up to 5 Explore subagents in parallel — one per file-group (rules / skills / agents / commands / references) — in a single message with N Agent tool calls. Each uses `subagent_type: "Explore"`, `mode: "dontAsk"`. The prompt passes the scope glob list and the pattern catalog (2.5c). Budget: "Report under 600 words". If a group has zero files, skip its dispatch.

Each agent returns a finding list with this shape per entry:

```
- file: <project-relative path>
  line_start: <int>
  line_end: <int>
  pattern: P1 | P2 | P3 | P4 | P5 | P6
  original: <verbatim snippet, ≤400 chars; elide with "…" if longer>
  rewrite_class: <short label, e.g. "table→numbered-cases">
  reason: <one-line rationale>
```

### 2.5c. Pattern catalog

Agents flag a finding for each occurrence of any of:

- **P1 — Decision-logic table.** Markdown table with ≥2 rows where at least one column contains conditional verbs (`if`, `when`, `unless`, `else`, `otherwise`, `except when`), imperatives (`must`, `should`, `do not`, `always`, `never`), or action verb-phrases. `rewrite_class: "table→numbered-cases"`.
- **P2 — Abstract-header lookup table.** Column headers are abstract (e.g. `Stage | Inputs | Outputs | Rule`, `Step | Trigger | Action`) AND cells contain verb phrases requiring the reader to cross-reference headers to recover meaning. `rewrite_class: "table→named-entries"`.
- **P3 — Narrative preamble.** The first non-frontmatter, non-heading paragraph contains no constraint, no instruction, and no behavior-changing fact. Markers: `"This skill..."`, `"Welcome to..."`, `"This guide walks you through..."`, `"The purpose of this document is..."`. `rewrite_class: "delete-or-fold-to-description"`.
- **P4 — Restated cross-reference without anchor.** Phrases like `"as mentioned above"`, `"see the section below"`, `"the previous section"` without a concrete section name, heading anchor, or file path. `rewrite_class: "inline-or-anchor"`.
- **P5 — Decorative markers without semantic content.** Emoji/symbol prefixes (`✅`, `❌`, `🔴`, `⚠️`, `→`) used as visual bullets where semantics are already carried by surrounding text. `rewrite_class: "strip-decoration"`.
- **P6 — Long explanatory paragraph.** A paragraph >3 sentences where each sentence introduces an independent fact (detectable by "First… Second… Finally…" patterns or conjunction density without topic continuity). `rewrite_class: "prose→bullets"`.

**Must NOT flag (preserve):**

- Key→value lookup tables with ≤5 rows where both columns are concrete nouns (no verbs).
- Ordinal/step tables where one column is a step number, phase index, or sequence position.
- Self-contained paired tables where every row is one independent fact (canonical example: `Thought | Reality` in `superpowers:using-superpowers`).
- YAML frontmatter, code blocks, DOT/graphviz diagrams, ASCII art.
- Tables under `## Reference:` headings in agent definitions.

### 2.5d. Merge, classify, waiver reconciliation

Coordinator deduplicates findings by `(file, line_start, pattern)` and groups by file. For every finding, assign:

- `check_id`: `llm-readability.<pattern-slug>` — one of `decision-table`, `abstract-header-table`, `narrative-preamble`, `restated-cross-ref`, `decorative-marker`, `long-prose`.
- `scope`: `project` (path inside the repo) or `personal` (path under `~/.claude/**`).
- `fingerprint`: `(check_id, normalized_path, detail_hash)` where `detail_hash` is the first 8 hex chars of `sha256(normalized_original)` — whitespace collapsed, line numbers stripped.

Load waivers from both stores (same format as `lazy-core.doctor` Phase 2.7b):

- `~/.claude/projects/<slug>/memory/doctor.waivers/*.md` (project)
- `~/.claude/memory/doctor.waivers/*.md` (personal)

For each finding whose fingerprint matches a waiver's `check_id + normalized_path + detail_hash`, move it to a `waived_findings` list. Render waived count in the summary header, same as doctor.

### 2.5e. Present and resolve

Render a summary block:

```
## Phase 2.5 — LLM-readability audit

- Files scanned: N (rules=A, skills=B, agents=C, commands=D, references=E)
- Findings: M across K files
- By pattern: P1=x, P2=x, P3=x, P4=x, P5=x, P6=x
- Waived: W
```

Then, per non-waived finding, render:

```
#### [P1] decision-logic table in <file>:<line_start>–<line_end>
<reason>
--- original ---
<snippet>
--- proposed rewrite class ---
<rewrite_class>
```

`AskUserQuestion` with three options:

- **Apply rewrite** *(default-recommended for clear cases)* — coordinator generates the rewritten snippet, shows the diff via a second `AskUserQuestion` ("Apply this diff? / Edit further / Cancel"), and on confirmation writes via the Edit tool.
- **Skip for now** — no action; finding reappears next run.
- **Waive permanently** — opens the permanence confirmation sub-prompt (same wording as doctor Phase 4a), then writes a waiver file via `Bash(mkdir -p <doctor.waivers-dir>)` followed by the `Write` tool (never chained). File path: `<doctor.waivers-dir>/llm-readability.<pattern-slug>__<detail_hash>.md`. Frontmatter shape matches the template in `lazy-core.doctor` Phase 2.7d.

**Rewrites are generated by the main coordinator, not the scan agent.** Scan agents identify constructs; the coordinator synthesizes the rewrite so the user can review the diff in the same turn.

### 2.5f. Summary row

Append one row to the final Optimization Results table (Phase 6 Output):

```
| LLM-readability rewrites | - | N | applied: A, skipped: S, waived: W |
```

## Phase 3: Audit global settings for project leakage

Read these files:
```
~/.claude/settings.json           (global tracked — enablement only)
~/.claude/settings.local.json     (global local — owns global permissions)
.claude/settings.json             (project tracked — enablement only)
.claude/settings.local.json       (project local — owns project permissions)
```

For every entry in global `settings.json`, classify as:

**GLOBAL** (belongs in global):
- Model, effort level, plugins, env vars
- Universal safety deny rules (rm -rf, sudo, git push --force)
- Universal allow rules (Read, Grep, Glob, basic Bash)
- Hooks that are project-agnostic (lazy-guard.settings, notification)
- Status line configuration

**PROJECT-SPECIFIC** (should be in project settings):
- Service-specific permissions (ssh, chezmoi, docker, openclaw, vpn, etc.)
- `additionalDirectories` entries
- Service-specific MCP servers (n8n-mcp)
- Domain-specific WebFetch permissions
- Service-specific Skill permissions
- Path-specific Read/Write/Edit permissions referencing project directories

For each item classified as PROJECT-SPECIFIC, check if it already exists in the project's `settings.local.json`. If not, flag it for migration.

## Phase 4: Fix settings leakage

For each PROJECT-SPECIFIC entry found in global settings:

1. Add it to `.claude/settings.local.json` (merge into existing arrays, don't duplicate)
2. Remove it from `~/.claude/settings.json`
3. Validate both files parse as JSON after each edit

After all moves, show a summary: N entries moved, from which global section to which project file.

## Phase 5: Memory index health

Check the memory index at `~/.claude/projects/<project-key>/memory/MEMORY.md`:

1. **Oversized index**: if > 5 KB, suggest consolidating related entries
2. **Orphaned files**: memory files that exist but aren't in the index
3. **Broken links**: index entries pointing to files that don't exist
4. **Stale entries**: entries about features/state that can be verified against current code (flag for manual review, don't auto-delete)

Report findings. Fix orphaned/broken links automatically, flag stale for user review.

## Phase 6: Heavy-scan delegation audit

Find skills that should be refactored to the coordinator-plus-parallel-Explore-agents pattern described in `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. This phase only reports — it never rewrites skills, because coordinator logic is skill-specific.

### Scan scope

- `.claude/skills/*/SKILL.md` (project)
- `~/.claude/skills/*/SKILL.md` (global)
- `Claude/*/skills/*/SKILL.md` (plugin sources, if this repo has a `Claude/` tree)

### Heuristics (all four must hit for a candidate)

For each SKILL.md, Read the body (not the frontmatter) and test:

1. **Size**: > 120 lines **or** > 5 KB.
2. **Multiple independent scan blocks**: ≥ 3 distinct scan-like blocks in the body. Count as a scan block any of:
   - Numbered check heading (`### N.`, `### Na.`)
   - Heading like `Check N:` or `Phase N:` where each phase reads a distinct file set
   - Directive block mentioning a Glob / Grep pattern or a Read of a different file tree than the previous block
3. **No existing parallel dispatch**: body does NOT contain any of — `subagent_type: "Explore"`, `subagent_type: "general-purpose"`, `in parallel`, `dispatching-parallel-agents`, `references/lazy-core.parallel-scan.md`, `rules/lazy-core.parallel-scan.md`, "multiple Agent tool calls".
4. **Read-heavy before interaction**: the first user prompt (search for `AskUserQuestion`, "ask the user", "confirm", "fix which", `[y/N]`) appears after more than half the scan blocks in (2).

If a skill hits all four, it is a candidate.

### Suggested split (per candidate)

Group the skill's scan blocks by the top-level file tree they read:
- `rules/`, `agents/`, `skills/`, `commands/` → "artifact" group
- `settings*.json`, `memory/` → "config+memory" group
- content greps across project files → "hygiene" group
- other distinctive buckets (e.g., security-pattern categories) → one group per category

Cap at **4 agents** per skill to keep dispatch cheap and report merging tractable. If natural grouping produces more, combine the smallest.

### Output

Emit one section per positive finding plus a summary table:

```markdown
## Phase 6: Heavy-scan delegation candidates

| Skill | Size | Scan blocks | Suggested split |
|---|---|---|---|
| <skill-name> | N lines / M KB | K | <short split description> |

Each candidate above does K independent scans before any user interaction.
Refactor to spawn Explore agents in parallel and have the skill itself
act as coordinator. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`.
```

If no candidates found, render "No heavy-scan delegation candidates found." and continue.

## Output

End with a summary:

```
## Optimization Results

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Rules (always-loaded) | X KB | Y KB | -Z% |
| Settings entries moved | - | N | global -> project |
| Memory issues fixed | - | N | orphaned/broken |
| Delegation candidates | - | N | heavy skills to refactor |
| LLM-readability rewrites | - | N | applied / skipped / waived |
```

## Logging

Log to `./.logs/claude/lazy-core.optimize/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).

The log's `## Actions` section must include an `## llm-readability audit` subsection when Phase 2.5 ran:

- Files scanned (count per group).
- Findings (count per pattern).
- Waived (count, per `check_id`).
- One line per finding decision: `<file>:<line_start> <pattern> → apply | skip | waive`.
- One line per newly written waiver: `waiver written: llm-readability.<pattern-slug> | <normalized_path>`.
