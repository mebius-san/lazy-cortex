---
name: lazy-log.audit
description: "Verify that the project's logging rule is installed and coherent. The rule itself is the single source of truth — individual skills/agents/commands do NOT need per-file ## Logging sections. Reports gaps and offers fixes. Read-first — never modifies files without confirmation."
allowed-tools: Read, Glob, Grep, Bash(mkdir -p *), Bash(date *)
---
# Logging Audit

Coordinator skill. Checks the rule file inline, then dispatches three **Explore** subagents in parallel to cross-check optional per-file `## Logging` sections across skills / agents / commands.

Resolve the `lazycortex-core` install path from `~/.claude/plugins/installed_plugins.json` entry `lazycortex-core@lazycortex` and Read `<installPath>/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern. Severity vocabulary: `PASS` / `WARN` / `FAIL`.

The rule (`.claude/rules/lazy-log.logging.md`) loads unconditionally at startup, so every artifact already inherits its instructions — per-file `## Logging` sections are optional restatements, not a requirement.

**Read-first.** Collect all findings, present a report, then ask which to fix.

## Phase 1 — Inline rule checks (main session)

Neither step dispatches; both operate on a single file.

### 1a. Rule file installed

- `[FAIL]` if `.claude/rules/lazy-log.logging.md` is missing — tell the user to run `/lazy-log.install`.
- `[WARN]` if the rule file has no YAML frontmatter with a `description`.

### 1b. Rule content integrity

Read `.claude/rules/lazy-log.logging.md`:

- `[FAIL]` if the rule does not specify a log path under `./.logs/claude/<name>/`.
- `[FAIL]` if the rule does not mention `git_sha` or `git rev-parse HEAD`.
- `[WARN]` if the rule does not mention `git_branch` (both belong in frontmatter).
- `[WARN]` if the rule does not mention UTC timestamps (`date -u`).
- `[WARN]` if the rule does not call out "two separate steps: `Bash(mkdir -p ...)` then `Write`".

If Phase 1a reports `[FAIL]` (rule missing), skip Phase 2 and jump to output.

## Phase 2 — Dispatch parallel cross-checks

Dispatch three Explore agents **in a single message with three Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each agent targets one artifact type and cross-checks any `## Logging` sections against the rule. Each returns the structured report contract from `lazycortex-core`'s `references/lazy-core.parallel-scan.md`. Budget: "Report under 250 words".

**Shared cross-check rules** (give to every agent):

- Missing `## Logging` sections are **not** a finding — the rule covers them.
- Do NOT check plugin-shipped skills (those under `~/.claude/plugins/`) — out of scope.
- For each artifact that *does* include a `## Logging` section:
  - `[WARN]` if the section references a log path outside `./.logs/claude/<name>/` (e.g., `~/.claude/...` or a hardcoded project path).
  - `[WARN]` if it uses a timestamp format other than `YYYY-MM-DD_HH-MM-SS`.
  - `[WARN]` if it suggests chaining with `&&` or using `cat > file <<'EOF'`.

### Agent A — skills

Scope: `.claude/skills/*/SKILL.md`. Glob the list, then `grep -n '## Logging'` to find sections to inspect. Report one finding per violation.

### Agent B — agents

Scope: `.claude/agents/*.md`. Same pattern — Glob + grep for `## Logging` and apply the shared cross-check rules.

### Agent C — commands

Scope: `.claude/commands/*.md`. Same pattern.

## Phase 3 — Present + fix

Parse the three returned blocks, merge with Phase 1 findings, and render:

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
