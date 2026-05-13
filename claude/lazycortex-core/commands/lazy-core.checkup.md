---
description: One entry point that runs every read-only audit/doctor this plugin orchestrates against consumer config, merges findings into a per-plugin table, then prompts once for which mutating fix-flow to run. Read-only by default.
---
# `/lazy-core.checkup`

Single entry point that runs every read-only health check this plugin orchestrates against consumer config, merges all findings into one per-plugin table, then prompts the user once for which mutating fix-flow(s) to run.

This is pure orchestration — it does **not** re-implement scan logic. It calls existing skills via the `Skill` tool, captures their merged-findings blocks, reformats, and asks. Mutating flows (`lazy-core.optimize`, the doctor's interactive fix loop) only run after explicit user choice in Phase 4.

## Execution discipline (MANDATORY — read before any action)

This command has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Read-only audit pass`
   - `Phase 2 — Build unified table`
   - `Phase 3 — Present table`
   - `Phase 4 — Prompt next action`
   - `Report`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `audited`, `built`, `presented`, `dispatched`, `skipped-per-user-choice`, `logged`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Read-only audit pass

Invoke each of the following via the `Skill` tool, in order. Capture the merged-findings block from each invocation's output.

For the doctor invocation, pass this hint in the Skill invocation: *"Operate in report-only mode: complete all phases up to but not including the interactive Fix phase. Emit only the merged-findings block. The /lazy-core.checkup coordinator owns the unified table and fix prompt — do not enter your own per-finding fix/waive loop."*

1. `Skill(skill: "lazy-core.audit")` — sibling skill in this plugin.
2. `Skill(skill: "lazy-core.doctor", args: "report-only")` — sibling skill in this plugin; delegates to other installed plugins' audits per its own Phase 3.

Outcome word: `audited`.

## Phase 2 — Build unified table

Group every captured finding by `plugin_owner` (already tagged by upstream skills).

Discover plugin sections dynamically: `Glob("claude/*/.claude-plugin/plugin.json")`. The repo-level section comes first; per-plugin sections follow in alphabetical order.

For each section, render this table:

```
| Severity | Source skill | Path | Problem | Suggested fix |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |
```

Sort rows within a section: `FAIL` first, then `WARN`, then `INFO`. Within a severity, group by source skill.

If a section has zero findings, emit `_No findings._` under the heading instead of an empty table.

Outcome word: `built`.

## Phase 3 — Present table

Render the markdown to the user verbatim. Do not summarize, do not annotate, do not add commentary above or below the table. The user reads the table; the next phase asks what to do about it.

Outcome word: `presented`.

## Phase 4 — Prompt next action

Call `AskUserQuestion` with `multiSelect: true`, header `Fix-flows`, and these options:

1. `Run lazy-core.optimize` — consumer-config rewrites
2. `Run lazy-core.doctor fix loop` — interactive per-finding fix/waive over consumer config
3. `Nothing — done`

If the user picks `Nothing — done` (or selects nothing else), proceed directly to the log step. Otherwise, invoke each chosen item in the order listed above via `Skill(skill: "<name>")`. Items run sequentially in the main agent — let each finish before invoking the next.

Outcome word: `dispatched` (or `skipped-per-user-choice` if user picked Nothing).

## Report

Emit exactly one line per task in the canonical list, each tagged with the outcome word produced by that step. A missing line is a bug — do not render with gaps.

Example shape:

```
- Phase 1 — Read-only audit pass: audited (2 skills)
- Phase 2 — Build unified table: built (5 sections, 23 findings)
- Phase 3 — Present table: presented
- Phase 4 — Prompt next action: dispatched (lazy-core.optimize)
- Report: reported
- Log the run: logged (./.logs/claude/lazy-core.checkup/2026-04-26_HH-MM-SS.md)
```

Outcome word: `reported`.

## Log the run

Per `lazy-log.logging`:

1. `Bash(mkdir -p ./.logs/claude/lazy-core.checkup)` — separate step from the Write.
2. `Write` to `./.logs/claude/lazy-core.checkup/<UTC-ts>.md` where the timestamp is `date -u +%Y-%m-%d_%H-%M-%S`.
3. Frontmatter: `git_sha` (from `git rev-parse HEAD` or `no-git`), `git_branch`, `date`, `input` (the user's raw command args or `none`).
4. Body: `# lazy-core.checkup` heading, `## Actions` listing each Phase outcome word + the Phase 4 user choices, `## Result` with success/failure summary.

Outcome word: `logged`.
