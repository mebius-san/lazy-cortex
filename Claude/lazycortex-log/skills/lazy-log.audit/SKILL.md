---
name: lazy-log.audit
description: "Verify that the project's logging rule is installed and coherent. The rule itself is the single source of truth — individual skills/agents/commands do NOT need per-file ## Logging sections. Reports gaps and offers fixes. Read-first — never modifies files without confirmation."
allowed-tools: Read, Glob, Grep, Bash(mkdir -p *), Bash(date *)
---

# Logging Audit

Verify that the project's logging rule (`.claude/rules/lazy-log.logging.md`) is installed and internally coherent. The rule loads unconditionally at startup, so every skill/agent/command already inherits its instructions — per-file `## Logging` sections are optional restatements, not a requirement.

**Read-first.** Collect all findings, present a report, then ask which to fix.

## Scope

Primary target:
- `.claude/rules/lazy-log.logging.md` — the rule is the single source of truth

Secondary (only if per-file `## Logging` sections exist, verify they don't contradict the rule):
- `.claude/skills/*/SKILL.md`
- `.claude/agents/*.md`
- `.claude/commands/*.md`

Do NOT flag files that lack a `## Logging` section. The rule covers them.

Do NOT check plugin-shipped skills (they live under `~/.claude/plugins/`) — those are out of scope for the user to fix.

## Checks

Classify findings as `[PASS]`, `[WARN]`, or `[FAIL]`.

### 1. Rule file installed

- `[FAIL]` if `.claude/rules/lazy-log.logging.md` is missing — tell the user to run `/lazy-log.install`
- `[WARN]` if the rule file has no YAML frontmatter with a `description`

### 2. Rule content integrity

Read `.claude/rules/lazy-log.logging.md` and verify it covers the core requirements:

- `[FAIL]` if the rule does not specify a log path under `./.logs/claude/<name>/`
- `[FAIL]` if the rule does not mention `git_sha` or `git rev-parse HEAD`
- `[WARN]` if the rule does not mention `git_branch` (both should be in frontmatter)
- `[WARN]` if the rule does not mention UTC timestamps (`date -u`)
- `[WARN]` if the rule does not call out "two separate steps: `Bash(mkdir -p ...)` then `Write`"

### 3. Per-file sections (only if present) don't contradict the rule

For each skill/agent/command that *does* happen to include a `## Logging` section, cross-check against the installed rule:

- `[WARN]` if the per-file section references a log path outside `./.logs/claude/<name>/` (e.g., uses `~/.claude/...` or a hardcoded project path)
- `[WARN]` if the per-file section uses a timestamp format other than `YYYY-MM-DD_HH-MM-SS`
- `[WARN]` if the per-file section suggests chaining with `&&` or using `cat > file <<'EOF'`

Missing `## Logging` sections are **not** a finding — the rule covers them.

## Output

```markdown
## lazy-log.audit -- Logging Audit

### Summary
- Rule file: installed | missing
- Files cross-checked: N (those with optional per-file sections)
- PASS: N | WARN: N | FAIL: N

### Findings

#### [FAIL] .claude/rules/lazy-log.logging.md missing
Run `/lazy-log.install` to install the rule template.

#### [WARN] agents/example.agent.md — per-file log path disagrees with rule
Found: `~/.claude/logs/...`
Rule says: `./.logs/claude/<name>/...`

(... one section per finding, FAIL first, then WARN ...)

### Fixes available

- [ ] Fix 1: <description> (can auto-apply)
- [ ] Fix 2: <description> (needs manual review)
```

Ask which fixes to apply. Never auto-fix without confirmation.

## Logging

Log to `./.logs/claude/lazy-log.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule.
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
