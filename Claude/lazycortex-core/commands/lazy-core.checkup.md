---
description: One entry point that runs every read-only audit/doctor in this repo (consumer + author trios), merges findings into a per-plugin table, then prompts once for which mutating fix-flow to run. Read-only by default.
---
# `/lazy-core.checkup`

Single entry point that runs every read-only health check this repo ships, merges all findings into one per-plugin table, then prompts the user once for which mutating fix-flow(s) to run.

This is pure orchestration — it does **not** re-implement scan logic. It calls existing skills via the `Skill` tool (and the `pub.status` agent via the `Agent` tool), captures their merged-findings blocks, reformats, and asks. Mutating flows (`lazy-core.optimize`, `tool.optimize`, doctors' interactive fix loops, `pub.status`) only run after explicit user choice in Phase 4.

Author-side artifacts (`tool.*` skills under `.claude/skills/`, `pub.status` agent under `.claude/agents/`) live in the LazyCortex authoring repo and are not always present. Probe each with `Glob` before invoking; if absent, skip and emit an `INFO` row noting unavailability.

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

For both doctor invocations, pass this hint in the Skill invocation: *"Operate in report-only mode: complete all phases up to but not including the interactive Fix phase. Emit only the merged-findings block. The /lazy-core.checkup coordinator owns the unified table and fix prompt — do not enter your own per-finding fix/waive loop."*

1. `Skill(skill: "lazy-core.audit")` — always available (sibling skill in the same plugin).
2. `Skill(skill: "lazy-core.doctor", args: "report-only")` — always available; in this repo it auto-detects local-tool mode and expands content checks to `claude/**`.
3. `tool.audit` — **probe first** with `Glob(".claude/skills/tool.audit/SKILL.md")`. If a match is returned, `Skill(skill: "tool.audit")`. If no match, emit one finding row in the table with `INFO | tool.audit | (n/a) | author-side skill not installed | install LazyCortex authoring kit if you author plugins`.
4. `tool.doctor` — same probe pattern; pass the report-only hint.

Outcome word: `audited`.

## Phase 2 — Build unified table

Group every captured finding by `plugin_owner` (already tagged by upstream skills; `tool.*` outputs are implicitly per-plugin and group by their plugin argument).

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

Call `AskUserQuestion` with `multiSelect: true`, header `Fix-flows`, and these options (suppress any whose underlying skill failed the Phase 1 probe):

1. `Run lazy-core.optimize` — consumer-config rewrites
2. `Run tool.optimize` — plugin-source rewrites
3. `Run lazy-core.doctor fix loop` — interactive per-finding fix/waive over consumer config
4. `Run tool.doctor fix loop` — interactive per-finding fix/waive over plugin sources
5. `Run pub.status` — refresh per-plugin pending-changes folder notes + iconize colors
6. `Nothing — done`

If the user picks `Nothing — done` (or selects nothing else), proceed directly to the log step. Otherwise, invoke each chosen item in the order listed above — skills via `Skill(skill: "<name>")`, and `pub.status` via `Agent(subagent_type: "pub.status", prompt: "refresh per-plugin folder notes + iconize colors")`. Items run sequentially in the main agent — let each finish before invoking the next.

Outcome word: `dispatched` (or `skipped-per-user-choice` if user picked Nothing).

## Report

Emit exactly one line per task in the canonical list, each tagged with the outcome word produced by that step. A missing line is a bug — do not render with gaps.

Example shape:

```
- Phase 1 — Read-only audit pass: audited (4 skills, 1 skipped-as-absent)
- Phase 2 — Build unified table: built (5 sections, 23 findings)
- Phase 3 — Present table: presented
- Phase 4 — Prompt next action: dispatched (lazy-core.optimize, pub.status)
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
