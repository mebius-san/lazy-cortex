---
description: "Run when the operator asks for one pass over everything — 'check my whole config', 'run all the audits', 'is anything broken across the lazycortex plugins' — and wants to be asked at the end what to fix. Runs every read-only audit and doctor this plugin orchestrates, merges them into one per-plugin table, then prompts once for a mutating fix-flow — but only when some finding is actually resolvable; the sibling `/lazy-core.audit` only measures context weight and authoring compliance and never fixes, and `/lazy-core.doctor` is its own cross-artifact scan with a per-finding fix loop."
---
# `/lazy-core.checkup`

Single entry point that runs every read-only health check this plugin orchestrates against consumer config, merges all findings into one per-plugin table, then prompts the user once for which mutating fix-flow(s) to run. The prompt is skipped when no finding carries a resolution a fix-flow could act on.

This is pure orchestration — it does **not** re-implement scan logic. It calls existing skills via the `Skill` tool, captures their merged-findings blocks, reformats, and asks. Mutating flows (`lazy-core.slim-context`, the doctor's interactive fix loop) only run after explicit user choice in Phase 4.

## Execution discipline (MANDATORY — read before any action)

This command has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Read-only audit pass`
   - `Phase 2 — Build unified table`
   - `Phase 3 — Present table`
   - `Phase 3.5 — Decide whether anything is fixable`
   - `Phase 4 — Prompt next action`
   - `Report`
   - `Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `audited`, `built`, `presented`, `dispatched`, `skipped-per-user-choice`, `logged`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Read-only audit pass

Invoke each of the following via the `Skill` tool, in order. Capture the merged-findings block from each invocation's output.

For the doctor invocation, pass this hint in the Skill invocation: *"Operate in report-only mode: complete all phases up to but not including the interactive Fix phase. Emit only the merged-findings block. The /lazy-core.checkup coordinator owns the unified table and fix prompt — do not enter your own per-finding fix/waive loop."*

1. `Skill(skill: "lazy-core.audit")` — sibling skill in this plugin.
2. `Skill(skill: "lazy-core.doctor", args: "report-only")` — sibling skill in this plugin; delegates to other installed plugins' audits per its own Phase 3.

Outcome word: `audited`.

## Phase 2 — Build unified table

Group every captured finding by `plugin_owner` (already tagged by upstream skills).

Every finding also carries a `resolution` value, set by the check that raised it: `mechanical` (the change follows unambiguously from what was read), `selective` (the operator must choose between defensible changes) or `report-only` (no change is expected). Render it in the `Resolution` column verbatim. A finding arriving without the field counts as `report-only` — an unclassified finding must never be the reason this run asks to mutate anything.

Discover plugin sections dynamically: `Glob("plugins/claude/*/.claude-plugin/plugin.json")`. The repo-level section comes first; per-plugin sections follow in alphabetical order.

For each section, render this table:

```
| Severity | Resolution | Source skill | Path | Problem | Suggested fix |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |
```

Sort rows within a section: `FAIL` first, then `WARN`, then `INFO`. Within a severity, group by source skill.

If a section has zero findings, emit `_No findings._` under the heading instead of an empty table.

Outcome word: `built`.

## Phase 3 — Present table

Render the markdown to the user verbatim. Do not summarize, do not annotate, do not add commentary above or below the table. The user reads the table; the next phase asks what to do about it.

Outcome word: `presented`.

## Phase 3.5 — Decide whether anything is fixable

Count the `resolution` values across every finding in the Phase 2 table.

- **No finding is `mechanical` or `selective`** — there is nothing a fix-flow could act on. Skip Phase 4 entirely, report the table as the run's whole outcome, and mark Phase 4 `completed` with outcome `skipped-nothing-to-fix`.
- **At least one is `mechanical` or `selective`** — continue to Phase 4.

The branch is read off the findings themselves, never off a judgment about how serious they look. A run over a clean-enough repo must not ask the operator a question with no answer worth giving.

Outcome word: `fixable` or `nothing-to-fix`.

## Phase 4 — Prompt next action

**Collect the fix-flow set first — it is open, not hardcoded.** Two flows are this plugin's own; the rest are published by whatever else is installed.

Enumerate the installed plugins the same way Phase 2 does, and read `provides_fix_flows` from each manifest at `<installPath>/.claude-plugin/plugin.json` (the dev-vault source at `plugins/claude/<plugin>/.claude-plugin/plugin.json` when this repo ships the plugin). Each entry is an object with `skill` (the skill to invoke) and `label` (the one-line option text). A plugin without the key publishes no fix-flow, which is a valid answer and not a finding.

A hardcoded list here would name only the flows that existed when someone last edited this step, so a flow added since would never reach the operator. `lazy-core.hygiene` § Dynamic content forbids that; the manifest is the machine-readable source it requires.

```
Context (print before asking):
- Where: /lazy-core.checkup · Phase 4 — Prompt next action; target consumer config of `<repo>`
- Found: the Phase 3 table — <n> findings (<f> FAIL, <w> WARN, <i> INFO) across <s> sections, of which <m> are mechanically or selectively resolvable
- Why asking: every fix-flow mutates consumer config; the read-only pass never does, so the operator picks what runs
- Answers: `Run lazy-core.slim-context` — consumer-config rewrites now, under that skill's own confirmations; `Run lazy-core.doctor fix loop` — interactive per-finding fix/waive over consumer config; one option per published fix-flow, carrying its own `label`; `Nothing — done` — no mutation, straight to the log. Nothing persisted by this command; asked every run
AskUserQuestion: multiSelect true, header "Fix-flows", question "Which fix-flows should run now against the consumer config of `<repo>`, given the <n> findings above?", options as listed with the descriptions above.
```

Options, in dispatch order:

1. `Run lazy-core.slim-context` — consumer-config rewrites
2. `Run lazy-core.doctor fix loop` — interactive per-finding fix/waive over consumer config
3. One option per collected `provides_fix_flows` entry, ordered by plugin name, labelled with the entry's `label`
4. `Nothing — done`

If the user picks `Nothing — done` (or selects nothing else), proceed directly to the log step. Otherwise, invoke each chosen item in the order listed above via `Skill(skill: "<name>")`. Items run sequentially in the main agent — let each finish before invoking the next.

A published flow's behaviour belongs to the plugin that published it. This command lists it and invokes it; it never re-implements its steps, adds its own confirmations, or re-runs it on failure.

Outcome word: `dispatched` (or `skipped-per-user-choice` if user picked Nothing, or `skipped-nothing-to-fix` when Phase 3.5 stopped the run).

## Report

Emit exactly one line per task in the canonical list, each tagged with the outcome word produced by that step. A missing line is a bug — do not render with gaps.

Example shape:

```
- Phase 1 — Read-only audit pass: audited (2 skills)
- Phase 2 — Build unified table: built (5 sections, 23 findings)
- Phase 3 — Present table: presented
- Phase 3.5 — Decide whether anything is fixable: fixable (4 of 23 resolvable)
- Phase 4 — Prompt next action: dispatched (lazy-core.slim-context)
- Report: reported
- Log the run: logged (./.logs/claude/lazy-core.checkup/2026-04-26_HH-MM-SS.md)
```

Outcome word: `reported`.

## Log the run

Per `lazy-log.logging`:

1. `Bash(mkdir -p ./.logs/claude/lazy-core.checkup)` — separate step from the Write.
2. `Write` to `./.logs/claude/lazy-core.checkup/<UTC-ts>.md` where the timestamp is `date -u +%Y-%m-%d_%H-%M-%S`.
3. Frontmatter: `git_sha` (from `git rev-parse HEAD` or `no-git`), `git_branch`, `date`, `input` (the user's raw command args or `none`).
4. Body: `# lazy-core.checkup` heading, `## Actions` listing each Phase outcome word, the Phase 3.5 resolution counts, and the Phase 4 user choices, `## Result` with success/failure summary.

Outcome word: `logged`.
