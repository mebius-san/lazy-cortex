---
name: lazy-expert.cancel-job
description: Cancel an expert job by removing its directory. Confirms via AskUserQuestion for non-done jobs. Wraps expert_runtime.cancel_job.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion
---
# Expert Cancel Job

Cancel an expert job by removing its job directory. For `done` jobs, asks for confirmation. For `pending` jobs (READY marker present), warns the daemon may be processing and confirms before deletion.

Future hardening note: a `.claude_pid` lockfile will eventually distinguish "pending-not-started" from "pending-in-flight". For now, all pending jobs require confirmation regardless.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Classify job`
   - `Step 3 — Confirm cancellation`
   - `Step 4 — Cancel job`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs from the caller:
- `expert_name` (string) — the expert key.
- `job_id` (string) — the job identifier.

Both must be non-empty strings. If either is absent → abort: "`<field>` is required."

Outcome: `validated` or `aborted`.

## Step 2 — Classify job

Determine job state by checking the job directory:

```
Bash(test -d .claude/experts/.jobs/<expert_name>/<job_id> && echo exists || echo missing)
Bash(test -f .claude/experts/.jobs/<expert_name>/<job_id>/DONE && echo done || echo pending)
```

Classify as:
- `missing` — job directory does not exist → report and exit. Outcome: `missing`.
- `done` — DONE marker present.
- `pending` — directory exists but no DONE marker (READY marker present).

Outcome: `classified`.

## Step 3 — Confirm cancellation

For `missing`: print "Job `<job_id>` not found for expert `<expert_name>`." and exit with outcome `absent`.

For `pending`: call `AskUserQuestion`: "Job `<job_id>` is pending — the runtime daemon may be processing it. Cancel anyway?" (Yes/No). If No → exit with outcome `user-aborted`.

For `done`: call `AskUserQuestion`: "Job `<job_id>` is already done. Remove it anyway?" (Yes/No). If No → exit with outcome `user-aborted`.

Outcome: `confirmed`, `user-aborted`, or `absent`.

## Step 4 — Cancel job

On confirmation, shell out to `expert_runtime.cancel_job`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from expert_runtime import cancel_job
cancel_job(Path('.'), '<expert_name>', '<job_id>')
print('cancelled')
")
```

Print: "Job `<job_id>` cancelled."

Outcome: `cancelled` or `error`.

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-expert.cancel-job)
```

Then `Write` to `.logs/claude/lazy-expert.cancel-job/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "expert_name=<expert_name> job_id=<job_id>"
---
```

`# lazy-expert.cancel-job`

`## Actions`
- Validated inputs
- Classified job as <status>
- Confirmation: <confirmed|user-aborted|absent>
- Cancellation: <cancelled|skipped>

`## Result`
`<success|aborted>` — job_id=`<job_id>`, outcome=`<outcome>`.

## Failure modes

- **"expert_name is required"** (or `job_id`) — required argument missing → supply both.
- **"Job not found"** — job directory absent; job was never dispatched or already cancelled → verify job_id and expert_name.
- **User aborts confirmation** — user chose No → no files deleted; job remains in current state.
- **Python `ModuleNotFoundError`** — plugin not installed → run `/lazy-core.install`.
