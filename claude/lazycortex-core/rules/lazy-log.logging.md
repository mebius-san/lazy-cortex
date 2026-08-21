---
description: Logging conventions for skills, agents, and commands.
always_loaded: every skill/agent/command must log on every run
---
# Run Logging (MANDATORY)

Every skill, agent, and command **must** log each run to `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` in the current working repository — including globals and plugin-shipped artifacts, which log in whichever repo is the cwd.

- `<name>` is the skill/agent/command name (e.g., `lazy-core.audit`, `config.add-project`)
- Timestamp uses UTC: `date -u +%Y-%m-%d_%H-%M-%S`
- Create directories with `mkdir -p` (project-relative, never under `~/.claude/`)
- Log writes must never prompt for permission: `Bash(mkdir -p ...)` then the `Write` tool, as two separate steps — never chained with `&&`, never `cat > file <<'EOF'`

## Log format

Frontmatter (YAML, all required):

- `git_sha` — `git rev-parse HEAD`, or `no-git`
- `git_branch` — `git rev-parse --abbrev-ref HEAD`, or `no-git`
- `date` — `YYYY-MM-DD HH:MM:SS UTC`
- `input` — arguments passed, or `none`

Body: `# <name>` heading, then `## Actions` (bullet list of actions, files modified, decisions) and `## Result` (success/failure + summary).

## Waiver

A skill, agent, or command may opt out by declaring a non-empty string in frontmatter:

    logging-waiver: "<concrete one-line reason>"

- The value must be a concrete reason. `true` / `yes` / `""` are rejected as `FAIL` by `lazy-core.audit`.
- Waivered artifacts are silently skipped — no log file written, no audit listing.
- Patterns / suggested reasons: see `${CLAUDE_PLUGIN_ROOT}/references/lazy-log.waiver-candidates.md`.

**Class-level exemption (no per-file frontmatter required):** agents dispatched by a coordinator skill via `Agent(subagent_type: ...)` and returning a structured findings block do NOT log; the coordinator owns the log.

**Log dir name MUST be the artifact's filename** (`<skill>` from `<skill>/SKILL.md`, `<name>` from `<name>.md`) — never a phase / task / dispatch description. Self-named subagent dirs (`task-N`, `expert-runtime-X`, etc.) are `lazy-core.audit` findings.

## Distill cadence

Decide whether to invoke `Agent(subagent_type: "lazycortex-core:lazy-log.distill", prompt: "distill pending commits")` on the **current turn**. Walk the gates in order; stop at the first match:

1. **No commit this turn → SKIP** (only `git commit` in *this* turn counts; not session-earlier, not `.logs/commits.jsonl`-pending).
2. **User said "don't distill" → SKIP.**
3. **User asked to distill / catch up → RUN** (bypasses throttle + qualitative gate).
4. **`mtime(./.logs/changelog.md)` < 4h → SKIP** (4h floor is a ceiling).
5. **Just-landed commit not narration-worthy → SKIP** (notable feat/fix/refactor = yes; state-refresh / README-rerender / version-bump = no).
6. **Otherwise → RUN.**

Pending commits accumulate in `.logs/commits.jsonl`; the next eligible turn catches up.
