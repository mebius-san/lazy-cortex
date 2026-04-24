---
name: lazy-log.timeline
description: "Generate a chronological timeline view of all changes matching a date range or topic. Combines changelog entries, commits, and AI run logs. Use when the user wants a 'what happened when' view."
tools: Read, Glob, Grep, Bash
model: inherit
---
# Change Timeline

Produce a chronological (oldest → newest, or newest → oldest on request) timeline of changes matching a filter.

## Execution discipline (MANDATORY — read before any action)

This agent has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Parse input`
   - `Step 2 — Collect entries`
   - `Step 3 — Deduplicate by SHA`
   - `Step 4 — Sort`
   - `Step 5 — Format`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

One of:
- A date range: "last week", "since 2026-04-01", "between 2026-03-01 and 2026-03-31"
- A topic: "the lazycortex-log plugin", "auth flow"
- Both combined: "hooks, last 2 weeks"

If no input is given, default to "everything in the last 7 days".

## Sources

1. `./docs/changelog.md`
2. `.logs/claude/**/*.md` (frontmatter `date` and `git_sha`)
3. `.logs/commits.jsonl` (raw commits)
4. `git log --all --since "<start>" --until "<end>" --format="%H%x00%cI%x00%s"` for dates outside the log files

## Process

1. **Parse input** into `{start_date, end_date, topic_keywords}`.
   - Relative dates ("last week") → compute absolute using `date -u +%Y-%m-%d` and offset.
   - Missing dates → use broad defaults but mention them in the output.

2. **Collect entries** from each source within the date range.
   - If `topic_keywords` given, filter to entries whose subject, files, or description matches any keyword (case-insensitive).

3. **Deduplicate by SHA** (same commit might appear in multiple sources — merge into one timeline entry).

4. **Sort** by date (default: newest first).

5. **Format**

```markdown
## lazy-log.timeline: <date range> [topic: <topic>]

### 2026-04-17

- `a2739ff` 14:30 — Added lazycortex-log plugin with commit recorder and recall agent
- `78e1cca` 09:15 — Fixed settings guardian hook deny protocol

### 2026-04-16

- `8ab5c73` 22:10 — Migrated cortex skills to lazycortex-core plugin
- `f2283b0` 18:45 — (internal) Renamed several skills

### 2026-04-15

(... etc ...)

### Coverage

- Date range: 2026-04-10 → 2026-04-17 (8 days)
- Sources searched: changelog, run logs, raw commits, git log
- Total entries: 14 (deduplicated from 23 raw matches)
```

## Guidelines

- **Don't editorialize** — timeline entries are short factual references. Users who want more detail invoke `lazy-log.recall <sha>` or `git show <sha>`.
- **Group by day** — don't group by week or month unless the range is very long (> 90 days).
- **Include times** when available — from commit `date` field or run log frontmatter.
- **Mark (internal)** prefix on commits that are chore/refactor/formatting so user can skim past them.

## Logging

Log to `./.logs/claude/lazy-log.timeline/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).
Use `Bash(mkdir -p ...)` then `Write` tool (never chain).
