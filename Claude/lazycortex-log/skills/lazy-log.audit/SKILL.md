---
name: lazy-log.audit
description: "Verify that every project skill, agent, and command has proper logging instructions (has a ## Logging section, references git_sha in frontmatter, uses the correct log path). Reports gaps and offers fixes. Read-first — never modifies files without confirmation."
allowed-tools: Read, Glob, Grep, Bash(mkdir -p *), Bash(date *)
---

# Logging Audit

Verify that logging conventions are followed across all project skill/agent/command definitions.

**Read-first.** Collect all findings, present a report, then ask which to fix.

## Scope

Check every file matching:
- `.claude/skills/*/SKILL.md` (project skills)
- `.claude/agents/*.md` (project agents)
- `.claude/commands/*.md` (project commands)

Do NOT check plugin-shipped skills (they live under `~/.claude/plugins/`) — those are out of scope for the user to fix.

## Checks

For each file, classify findings as `[PASS]`, `[WARN]`, or `[FAIL]`.

### 1. Logging section present

- `[FAIL]` if the file has no `## Logging` section (or equivalent heading mentioning logs)
- `[WARN]` if the `## Logging` section is shorter than 3 lines (probably incomplete)

### 2. Log path format

- `[FAIL]` if the file references a log path outside `./.logs/claude/<name>/` (e.g., uses `~/.claude/...` or a hardcoded project path)
- `[WARN]` if the log path uses a timestamp format other than `YYYY-MM-DD_HH-MM-SS`
- `[WARN]` if the log path uses UTC inconsistently (should always be UTC)

### 3. Git reference

- `[FAIL]` if the logging instructions do not mention `git_sha` or `git rev-parse HEAD` anywhere
- `[WARN]` if only `git_sha` is mentioned but not `git_branch` (both should be in frontmatter)

### 4. Separate mkdir + Write

- `[WARN]` if the logging instructions suggest chaining with `&&` or using `cat > file <<'EOF'`
- `[PASS]` if the instructions explicitly call out "two separate steps: `Bash(mkdir -p ...)` then `Write`"

### 5. Consistent with the installed rule

Read `.claude/rules/lazy-log.logging.md` (if present) and check that each skill/agent/command's `## Logging` section doesn't contradict it. Specifically:
- Same path format
- Same frontmatter fields (git_sha, git_branch, date, input)

If `.claude/rules/lazy-log.logging.md` is missing:
- `[WARN]` Tell the user to run `/lazy-log.install` first — the central rule file isn't installed yet.

## Output

```markdown
## lazy-log.audit -- Logging Audit

### Summary
- Files checked: N
- PASS: N | WARN: N | FAIL: N

### Findings

#### [FAIL] skills/example.skill/SKILL.md — missing ## Logging section
No logging instructions found. Add a `## Logging` section that logs to
`./.logs/claude/example.skill/YYYY-MM-DD_HH-MM-SS.md` with git_sha frontmatter.

#### [WARN] agents/example.agent.md — log path missing UTC instruction
Found: `date +%Y-%m-%d_%H-%M-%S`
Expected: `date -u +%Y-%m-%d_%H-%M-%S`

(... one section per finding, FAIL first, then WARN ...)

### Fixes available

- [ ] Fix 1: <description> (can auto-apply)
- [ ] Fix 2: <description> (needs manual review)
```

Ask which fixes to apply. Never auto-fix without confirmation.

## Logging

Log to `./.logs/claude/lazy-log.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
