---
name: lazy-review.install
description: "Per-repo bootstrap for lazycortex-review. Seeds lazy.settings.json with review.classes / experts / routines defaults, creates .experts/.jobs/ and .logs/lazy-review/runs/ directories. Idempotent — re-runnable without overwriting existing config."
allowed-tools: Read, AskUserQuestion, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
lazy_setup_phase: install
---
# lazy-review.install

Per-repo bootstrap: gets a clean checkout to the point where the daemon can start ticking. The bin script does the actual mutation; this skill is the operator-facing pipeline that runs it, points at `/lazy-review.configure` for class wiring, and prints the optional `.gitignore` entries the operator may want to add by hand (the skill never touches `.gitignore` without explicit permission).

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Bootstrap settings + dirs`
   - `Phase 2 — Surface gitignore suggestions`
   - `Phase 3 — Point user at /lazy-review.configure`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Each step emits a one-word outcome (`installed` / `already-installed` / `surfaced` / `pointed` / `report-emitted`).
3. **Do not reach the Report step until every prior task is `completed`.**

## Phase 1 — Bootstrap settings + dirs

Run `python3 claude/lazycortex-review/bin/install.py --cwd .`. The script:

- Creates `.claude/lazy.settings.json` if missing (or merges the defaults in for absent keys only).
- Creates `.experts/.jobs/` and `.logs/lazy-review/runs/` if missing.
- Prints a JSON report of what changed.

Outcome: `installed` (anything was created or merged) or `already-installed` (no-op).

## Phase 2 — Surface gitignore suggestions

The runtime writes operator-private state into the repo: the whole `.experts/` tree (job queue, cross-repo trackers, subprocess locks) and tick logs under `.logs/lazy-review/`. Operators typically want both gitignored. This skill MUST NOT write to `.gitignore` itself — instead, print the recommended lines and tell the operator to add them by hand:

```
.experts/
.logs/lazy-review/
```

Outcome: `surfaced`.

## Phase 3 — Point user at /lazy-review.configure

Tell the operator: *"Settings scaffolded with empty `review.classes` — run `/lazy-review.configure` to register your first class."*

Outcome: `pointed`.

## Report

One line per task in the canonical list with its outcome word.

## Failure modes

- **Phase 1 fails with permission error on `.claude/lazy.settings.json`** — operator's shell user can't write there → fix file ownership, re-run.
- **JSON parse error on existing settings** — operator's `.claude/lazy.settings.json` is hand-edited and malformed → fix the JSON manually, re-run.
