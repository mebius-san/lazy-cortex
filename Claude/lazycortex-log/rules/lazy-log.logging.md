---
description: Logging conventions for skills, agents, and commands.
always_loaded: every skill/agent/command must log on every run
---
# Run Logging (MANDATORY)

Every skill, agent, and command **must** log each run to `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` in the current working repository.

- `<name>` is the skill/agent/command name (e.g., `lazy-core.audit`, `config.add-project`)
- Timestamp uses UTC: `date -u +%Y-%m-%d_%H-%M-%S`
- Create directories with `mkdir -p` (project-relative, never under `~/.claude/`)
- Writing logs must never prompt for permission. Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`
- This applies to all skills/agents/commands, including globals and plugin-shipped ones — they always log in whichever repo is the current working directory

## Log format

File path: `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md`

Frontmatter (YAML, all required):

- `git_sha` — `git rev-parse HEAD`, or `no-git`
- `git_branch` — `git rev-parse --abbrev-ref HEAD`, or `no-git`
- `date` — `YYYY-MM-DD HH:MM:SS UTC`
- `input` — arguments passed, or `none`

Body: `# <name>` heading, then `## Actions` (bullet list of actions, files modified, decisions) and `## Result` (success/failure + summary).

Always include `git_sha` — it bridges "the AI did Y" back to the actual commit.

## Distill cadence (qualitative + 4h throttle)

Decide whether to invoke
`Agent(subagent_type: "lazycortex-log:lazy-log.distill", prompt: "distill pending commits")`
on the **current turn**. Walk these gates in order; stop at the first match:

1. **No commit landed in this turn → HARD SKIP.** "Commit landed this turn" means a `git commit` ran in *this* assistant turn — not earlier in the session, not pending in `.logs/commits.jsonl`. Questions, plans, edits without commits, and read-only turns never trigger distill, even if undistilled commits exist from earlier turns. They wait for the next turn that itself produces a commit.
2. **User said "don't distill" this turn → HARD SKIP.**
3. **User explicitly asked to distill / catch up → RUN** (bypasses throttle and qualitative gate).
4. **`mtime(./.logs/changelog.md)` is younger than 4 hours → SKIP.** The 4h floor is a ceiling, not a target — even on big changes, don't run more often.
5. **The just-landed commit isn't meaningful enough to narrate → SKIP** (Claude judges qualitatively: notable feature, fix, or refactor = yes; mechanical state-refresh, README rerender, version bump = no).
6. **Otherwise → RUN.**

Pending commits accumulate in `.logs/commits.jsonl`; the next eligible turn catches up.

## Recall, timeline, summary

For historical questions ("why was X changed?", "when did we change Y?"), use one of:

- `Agent(subagent_type: "lazycortex-log:lazy-log.recall", prompt: "<query>")` — searches across `.logs/changelog.md`, `.logs/claude/**/*.md`, `.logs/commits.jsonl`, git log, and memory.
- `Agent(subagent_type: "lazycortex-log:lazy-log.timeline", prompt: "<date range or topic>")` — chronological view of a date range or topic.
- `Agent(subagent_type: "lazycortex-log:lazy-log.summary", prompt: "<topic>")` — synthesized multi-source summary.

Don't skim these files manually — `lazy-log.recall` is tuned to rank relevance and return git SHAs for follow-up `git show <sha>`.
