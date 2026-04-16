---
name: lazy-core.audit
description: "Quick read-only audit of what gets loaded into conversation context at startup. Shows sizes, loading behavior, and optimization opportunities. No changes made."
allowed-tools: Read, Glob, Grep, Bash(wc *)
---

# Context Audit

Read-only audit of context loading for the current project. Do NOT make any changes.

**CRITICAL PATH RULE**: `~/.claude/` is protected from Bash access (Claude Code's own config dir). Use ONLY Glob and Read tools for any path under `~/.claude/`. Use `wc -c` via Bash ONLY for paths under the project root (e.g., `.claude/`).

## Steps

### 1. Always-loaded files

**Global CLAUDE.md** (`~/.claude/CLAUDE.md`): Use Read tool, note last line number.

**Project CLAUDE.md** (`CLAUDE.md`): Use Read tool, note last line number.

**Global rules** (`~/.claude/rules/*.md`): Use Glob to find files, Read each one, note line counts. If the directory is a symlink, resolve and follow it.

**Project rules** (`.claude/rules/*.md`): Use `wc -c` via Bash (project path, safe). Check frontmatter: rules with `paths` are on-demand (don't count toward startup cost), rules without `paths` are always-loaded.

**Memory index** (`~/.claude/projects/*/memory/MEMORY.md`): Use Read tool, note last line number.

### 2. On-demand files

**Agents** (`.claude/agents/*.md`): Use `wc -c` via Bash (project path).

**Project commands** (`.claude/commands/*.md`): Use `wc -c` via Bash (project path).

**Global commands** (`~/.claude/commands/*.md`): Use Glob to find, Read to count lines.

**Project skills** (`.claude/skills/*/SKILL.md`): Use `wc -c` via Bash (project path).

**Global skills** (`~/.claude/skills/*/SKILL.md`): Use Glob to find, Read to count lines.

**Memory files** (individual `~/.claude/projects/*/memory/*.md` except MEMORY.md): Use Glob to count files.

### 3. MCP servers

List from system context (no tools needed).

Check MCP enablement:
- Global `~/.claude/settings.json` should have `"enableAllProjectMcpServers": false` (flag if `true`)
- Project `.claude/settings.json` should have `enabledMcpjsonServers` listing each enabled server
- Cross-reference: compare servers in `.mcp.json` vs `enabledMcpjsonServers` — flag any declared but not enabled

## Size estimation

For files measured via Read (line count only): **size ~ lines x 45 bytes**.
For files measured via `wc -c`: exact bytes.

## Output

### Always loaded (startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per source, sorted by size descending) |

**Total always-loaded**: ~X KB

### On-demand (no startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per source, sorted by size descending) |

**Total on-demand**: ~X KB

### Path hygiene

Grep all project-level config files (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`) for hardcoded paths. Flag:

- `/Users/` or `/home/` — hardcoded absolute paths
- `<project>/` prefix — should be relative
- `~/Dropbox/` or other user-specific home subdirectories
- `~/.claude/` used for project-local items (agents, project settings, project rules) instead of relative `.claude/`

### Recommendations

- Rules file > 3 KB -> flag for slimming (run `/lazy-core.optimize`)
- Memory index > 5 KB -> suggest consolidation
- Hardcoded paths found -> flag for replacement with relative equivalents (run `/lazy-core.doctor` for details)
- Note: system prompt, skill registry, MCP instructions, deferred tool list are injected by Claude Code and cannot be reduced by the user.
