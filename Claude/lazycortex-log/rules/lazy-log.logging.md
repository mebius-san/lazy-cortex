---
description: Logging conventions for skills, agents, and commands. Also guides when to run lazy-log.distill after commits.
---

# Run Logging (MANDATORY)

Every skill, agent, and command **must** log each run to `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` in the current working repository.

- `<name>` is the skill/agent/command name (e.g., `lazy-core.audit`, `config.add-project`)
- Timestamp uses UTC: `date -u +%Y-%m-%d_%H-%M-%S`
- Create directories with `mkdir -p` (project-relative, never under `~/.claude/`)
- Writing logs must never prompt for permission. Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`
- This applies to all skills/agents/commands, including globals and plugin-shipped ones — they always log in whichever repo is the current working directory

## Log format

```markdown
---
git_sha: <output of `git rev-parse HEAD`, or "no-git" if not in a git repo>
git_branch: <output of `git rev-parse --abbrev-ref HEAD`, or "no-git">
date: YYYY-MM-DD HH:MM:SS UTC
input: <arguments or "none">
---

# <name>

## Actions

<bullet list of actions taken, files modified, decisions made>

## Result

<success/failure, summary of outcome>
```

The `git_sha` in frontmatter is the critical bridge from "the AI did Y" back to the actual commit that made the change. Always include it.

## Distill after commits

After making one or more git commits, **consider** invoking the `lazy-log.distill` agent to update `./docs/changelog.md` with a short functional description of what changed.

**Skip distill when:**
- The commit is trivial (typo fix, formatting, whitespace, dependency bump)
- You've already distilled in this session and only minor follow-up commits happened since
- The user explicitly says they don't need the changelog updated

**Default to distill when:**
- A logical unit of work is complete (feature, bugfix, refactor)
- Multiple related commits have accumulated since the last distill
- The user is about to push or wrap up for the day

This is guidance, not a hard rule — use judgment. When in doubt, mention it and let the user decide.

## Recall, timeline, summary

When the user asks "why was X changed?", "when did we change Y?", or similar historical questions:

1. Invoke `lazy-log.recall "<query>"` to search across `docs/changelog.md`, `.logs/claude/**/*.md`, `.logs/commits.jsonl`, git log, and memory
2. For chronological views of a date range or topic, invoke `lazy-log.timeline`
3. For a synthesized multi-source summary of a topic, invoke `lazy-log.summary`

Don't skim these files manually — the recall agent is tuned to rank relevance and return git SHAs for follow-up `git show <sha>`.
