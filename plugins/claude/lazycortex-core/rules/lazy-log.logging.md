---
description: Run-log format for the skills, agents, and commands that opt into logging.
always_loaded: "the opt-in key and the log format must be known on any turn that runs a logging artifact"
---
# Run Logging

A skill, agent, or command writes a run log only when its frontmatter declares `logging: true`. Everything else writes no log and carries no logging section. An artifact opts in when something reads its log mechanically — a caller that verifies the run against it — never for history alone; git and `.logs/commits.jsonl` hold the history.

An opted-in artifact logs each run to `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` in the current working repository — plugin-shipped artifacts log in whichever repo is the cwd.

- `<name>` is the artifact's filename stem (`<skill>` from `<skill>/SKILL.md`, `<name>` from `<name>.md`) — never a phase, task, or dispatch description.
- Timestamp uses UTC: `date -u +%Y-%m-%d_%H-%M-%S`.
- Create the directory with `Bash(mkdir -p ...)`, then write with the `Write` tool, as two separate steps — never chained with `&&`, never `cat > file <<'EOF'`.

## Log format

Frontmatter (YAML, all required):

- `git_sha` — `git rev-parse HEAD`, or `no-git`
- `git_branch` — `git rev-parse --abbrev-ref HEAD`, or `no-git`
- `date` — `YYYY-MM-DD HH:MM:SS UTC`
- `input` — arguments passed, or `none`

Body: `# <name>` heading, then `## Actions` (bullet list of actions, files modified, decisions) and `## Result` (success/failure + summary).

## Validation

`lazy-core.audit` reads the key: only the literal `true` opts in; any other value is a `FAIL`. Subagents dispatched by a coordinator never log on their own — the coordinator owns whatever log its own key calls for.
