---
name: lazy-review.audit
description: "Read-only validation of lazy-review configuration in .claude/lazy.settings.json — checks schema, expert references, git_author completeness, and edit_marker_style. Returns PASS/WARN/FAIL plus per-finding detail."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
---
# lazy-review.audit

Read-only validation of the consumer's settings. Never writes anything; never asks questions.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Run audit script`
   - `Phase 2 — Render findings`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `audited` / `rendered` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Phase 1 — Run audit script

`python3 claude/lazycortex-review/bin/audit.py --settings .claude/lazy.settings.json`. The script prints a JSON record `{level: PASS|WARN|FAIL, findings: [{severity, check, message}, ...]}` and exits 0/1/2 respectively.

Outcome: `audited`.

## Phase 2 — Render findings

If the report has findings, print one bullet per finding grouped by severity (FAIL first, then WARN, then PASS). If there are none, print `audit: PASS (no issues)`.

Outcome: `rendered`.

## Report

One line per task with its outcome word, followed by the summary line `audit: <LEVEL> (<N> findings)`.

## Failure modes

- **Phase 1 reports `settings_present FAIL`** — operator hasn't run `/lazy-review.install` → run install first, then re-run audit.
- **Phase 1 reports `expert_<name>_missing FAIL`** — a class references an expert name that isn't in the top-level `experts` dict → run `/lazy-review.configure` to register the expert, or remove the class member.
