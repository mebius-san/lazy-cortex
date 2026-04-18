---
description: Coordinator-plus-parallel-Explore pattern for heavy skills that do multiple independent scans before user interaction. Referenced by lazy-core.doctor, lazy-guard.check-public, lazy-core.audit, lazy-log.audit, and the tool.* wrappers.
---

# Parallel Scan Coordinator Pattern

Skills that do ≥ 3 independent scans before user interaction must act as thin **coordinators** that dispatch parallel **Explore** subagents.

## When this applies

All of:

- Three or more scan blocks (Glob / Grep / Read loops) that don't depend on each other.
- Heavy read work before the first `AskUserQuestion` or `[y/N]` prompt.
- Fixes that stay with the coordinator (Write / Edit permission agents shouldn't have).

Skip the pattern if a skill has one scan block or scans interleave with user prompts.

## Shape

```
SKILL.md
├── Phase 1: Dispatch N Explore agents IN PARALLEL
│       (single message, multiple Agent tool calls)
├── Phase 2: Collect + merge structured reports
├── Phase 3: Present unified report (unchanged output format)
├── Phase 4: Ask "fix which?" and apply confirmed fixes
└── Logging
```

## Dispatch rules

- Use `subagent_type: "Explore"` with `mode: "dontAsk"`. Explore is read-only, matching the scan-only constraint. Never dispatch `general-purpose` for scanning.
- Dispatch all N agents in a **single assistant message with N tool calls**. Sequential dispatch defeats the point.
- Cap at **4 agents per skill**. More than 4 makes report merging painful and latency unpredictable.
- Each agent prompt must include: narrow read-only scope (specific globs / Grep patterns / files), the structured-report contract below, and a word budget (typically "Report under 300 words").

## Structured report contract

Every Explore agent must return a block in this exact shape:

```markdown
## scan: <scan-name>

### findings
- [SEVERITY] <short title> | <path>:<optional-line>
  detail: <one line>
  fix: <short action, or "manual">

### summary
pass: <n>  warn: <n>  fail: <n>
```

`SEVERITY` vocabulary is chosen by the coordinator skill (`PASS / WARN / FAIL` for doctor-family, `OK / WARN / FAIL` for guard) and documented at the top of its SKILL.md.

## Coordinator responsibilities

- Parse each returned block; split on `## scan:` headings.
- Deduplicate findings across scans (same `<path>:<line>` + title = one).
- Apply waivers / suppressions (e.g., `.guard-waivers.json`) at the coordinator level, not inside agent prompts.
- Render the existing user-visible output format — the refactor must not change what the user sees.
- Handle all Write / Edit operations in the main session after user confirmation.
- Write the run log to `./.logs/claude/<skill-name>/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Agents are ephemeral and do not log.

## Meta-rule

All constraints. New pattern-wide rules → this file; per-skill Explore prompts and report schemas → the skill's `SKILL.md`.
