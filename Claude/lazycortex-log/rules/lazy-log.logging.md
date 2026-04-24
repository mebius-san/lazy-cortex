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

## Distill after commits (automatic via Stop hook)

The `lazycortex-log` plugin ships a Stop hook (`lazy-log.distill-trigger`) that fires at session end. It checks `.logs/commits.jsonl` against the `last-distilled-sha` marker in `docs/changelog.md`; when commits are pending, it asks Claude to run `Agent(subagent_type: "lazycortex-log:lazy-log.distill", ...)` before ending the turn. You do not need to trigger distill manually.

If the hook fires and you are in the middle of a task, run distill and then resume.

**Hard skip override**: only when the user explicitly says "don't distill" / "skip the changelog" in the current turn.

`stop_hook_active` prevents re-entry loops. The model is read from `.claude/lazy.settings.json` (`agent_models["lazycortex-log:lazy-log.distill"]`, default `haiku`), optionally capped by `LAZY_AGENT_MODEL_FLOOR`.

## Recall, timeline, summary

For historical questions ("why was X changed?", "when did we change Y?"), use one of:

- `Agent(subagent_type: "lazycortex-log:lazy-log.recall", prompt: "<query>")` — searches across `docs/changelog.md`, `.logs/claude/**/*.md`, `.logs/commits.jsonl`, git log, and memory.
- `Agent(subagent_type: "lazycortex-log:lazy-log.timeline", prompt: "<date range or topic>")` — chronological view of a date range or topic.
- `Agent(subagent_type: "lazycortex-log:lazy-log.summary", prompt: "<topic>")` — synthesized multi-source summary.

Don't skim these files manually — `lazy-log.recall` is tuned to rank relevance and return git SHAs for follow-up `git show <sha>`.
