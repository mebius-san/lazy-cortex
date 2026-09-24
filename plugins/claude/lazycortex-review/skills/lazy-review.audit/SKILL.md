---
name: lazy-review.audit
description: "Run when the operator asks whether the review setup is sane, or when review misbehaves in a way that smells like config — a document never enters the loop, a class points at an expert that was never registered, commits land under the wrong identity. Read-only check of the `review` section in `.claude/lazy.settings.json`; reports `PASS` / `INFO` / `WARN` / `FAIL` and writes no file — fixes come from `/lazy-review.configure` or `/lazy-review.install`."
allowed-tools: Read, Write, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse *), Agent
---
# lazy-review.audit

Read-only validation of the consumer's settings. It changes no configuration, asks no questions, and writes nothing.

This skill follows the shared audit contract at `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md`: the audit only reads — it writes nothing — the severity vocabulary is `PASS` / `INFO` / `WARN` / `FAIL` and nothing else, every finding carries its own repair route in the same line, and no finding estimates what running that route would change.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Run audit script`
   - `Phase 2 — Render findings`
   - `Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** Outcomes: `audited` / `rendered` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Phase 1 — Run audit script

`"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/audit.py" --settings .claude/lazy.settings.json`. The script prints a JSON record `{level: PASS|WARN|FAIL, findings: [{severity, check, message}, ...]}` and exits 0/1/2 respectively.

Outcome: `audited`.

## Phase 2 — Render findings

If the report has findings, print one bullet per finding grouped by severity (FAIL first, then WARN, then INFO, then PASS). Each bullet carries the check name, the settings key or artifact it names, what is wrong, and the route that repairs it — all in that one line; a route shared by several findings is repeated on each of them rather than collected into a section of its own. The routes the script's checks map onto are `/lazy-review.install` (nothing configured yet), `/lazy-review.configure` (a class, an expert entry, a section writer, or the edit-marker style), and `/lazy-spec.product-config <key>` (a product-scoped class's globs) — the `## Failure modes` section below names which finding takes which. If there are none, print `audit: PASS (no issues)`.

Outcome: `rendered`.

## Report

One line per task with its outcome word, followed by the summary line `audit: <LEVEL> (<N> findings)`.

## Failure modes

- **Phase 1 reports `settings_present FAIL`** — operator hasn't run `/lazy-review.install` → run install first, then re-run audit.
- **Phase 1 reports `expert_<name>_missing FAIL`** — a class references an expert name that isn't in the top-level `experts` dict → run `/lazy-review.configure` to register the expert, or remove the class member.
- **Phase 1 reports `override_glob_depth WARN`** — a product-scoped `<type>@<key>` class carries a glob that fixes the asset depth, so an asset at the product root or nested deeper falls out of it and loses the product's own experts → re-run `/lazy-spec.product-config <key>` in edit mode to regenerate the class's globs.
