---
name: lazy-memory.index
description: Operator / audit-side rebuild of `.memory/.tags/` and every `.memory/<expert>/.tags/` from current notes' frontmatter. Recovery tool — `lazy-memory.write` keeps tag files in sync atomically; this skill exists for hand-edited memory trees and drift recovery.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write
---
# Memory reindex

Walk every expert in `.memory/`, recompute the topic set each carries from note frontmatter, and regenerate the local + global `.tags/` tree. Stale tag files (no backing note) are removed.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Verify .memory/ exists`
   - `Step 2 — Rebuild tag index via worker`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.**

## Step 1 — Verify .memory/ exists

```
Bash(test -d .memory && echo present || echo absent)
```

If `absent`, state outcome `absent` and skip Step 2 (Report still runs).

## Step 2 — Rebuild tag index via worker

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-memory.index/bin/reindex.py --repo .)
```

Parse the JSON summary `{experts, notes, tags}`.

Outcome: `rebuilt` (summary present) or `error` (worker exited non-zero).

## Step 3 — Report

One line per task. Print to the caller:

```
experts: <N>
notes:   <N>
tags:    <N>
```

## Step 4 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-memory.index)
```

Write to `.logs/claude/lazy-memory.index/<UTC-timestamp>.md` per the logging rule.

## Failure modes

- **"`.memory/` not present"** — the memory subsystem has not been initialized in this repo. Run `/lazy-core.install` to bootstrap the directory.
- **Worker fails with import error** — `${CLAUDE_PLUGIN_ROOT}/bin/memory_runtime.py` is missing → reinstall `lazycortex-core` via `/plugin update`.
