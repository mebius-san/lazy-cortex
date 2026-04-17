---
name: lazy-core.optimize
description: "Optimize Claude Code context loading for the current project. Slims oversized rules files by moving reference material to agent definitions, audits global settings for project-specific leakage and moves entries to local settings. Run when startup feels slow or after adding new rules/agents."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(mkdir -p *)
---

# Context Optimization

Reduce startup context weight and fix settings layer violations for the current project.

## Phase 1: Audit context weight

Measure everything that loads at conversation start.

### 1a. Always-loaded files

Measure byte sizes of:

```
~/.claude/CLAUDE.md                          (global instructions)
CLAUDE.md                                    (project instructions)
~/.claude/rules/*.md                         (global rules — resolve symlinks)
.claude/rules/*.md                           (project rules)
~/.claude/projects/<project-key>/memory/MEMORY.md  (memory index)
```

Also check for additional CLAUDE.md files in subdirectories and any global rules files outside the symlinked directory.

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
   - Update meta-rules in both files to clarify: constraints -> rules, reference -> agent

5. After rewriting, re-measure and show the before/after comparison.

## Phase 3: Audit global settings for project leakage

Read these files:
```
~/.claude/settings.json           (global)
~/.claude/settings.local.json     (global local — should be empty or near-empty)
.claude/settings.json             (project tracked)
.claude/settings.local.json       (project local)
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

**Important**: The global `settings.local.json` may have a guardian hook preventing writes. Check for `lazy-guard.settings` hook and respect its constraints.

After all moves, show a summary: N entries moved, from which global section to which project file.

## Phase 5: Memory index health

Check the memory index at `~/.claude/projects/<project-key>/memory/MEMORY.md`:

1. **Oversized index**: if > 5 KB, suggest consolidating related entries
2. **Orphaned files**: memory files that exist but aren't in the index
3. **Broken links**: index entries pointing to files that don't exist
4. **Stale entries**: entries about features/state that can be verified against current code (flag for manual review, don't auto-delete)

Report findings. Fix orphaned/broken links automatically, flag stale for user review.

## Phase 6: Heavy-scan delegation audit

Find skills that should be refactored to the coordinator-plus-parallel-Explore-agents pattern described in `rules/lazy-core.parallel-scan.md`. This phase only reports — it never rewrites skills, because coordinator logic is skill-specific.

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
3. **No existing parallel dispatch**: body does NOT contain any of — `subagent_type: "Explore"`, `subagent_type: "general-purpose"`, `in parallel`, `dispatching-parallel-agents`, `rules/lazy-core.parallel-scan.md`, "multiple Agent tool calls".
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
act as coordinator. See rules/lazy-core.parallel-scan.md.
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
```

## Logging

Log to `./.logs/claude/lazy-core.optimize/YYYY-MM-DD_HH-MM-SS.md`.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
