---
name: lazy-expert.cancel-job
description: "Run when the operator wants an expert job stopped — wrong expert, changed requirements, a moved source file, or a job that should not finish. Confirms, kills the executor, and marks the bundle CANCELLED; the job directory stays on disk for forensics and the dedup key is released so the same work can be re-dispatched."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion
---
# Expert Cancel Job

Cancel an expert job. Cancellation stops the running executor (SIGTERM → grace → SIGKILL on its process groups), removes the `READY` marker, and places a `CANCELLED` marker. The bundle directory (request, response, transcript, result) stays on disk for post-mortem and ages out via the failed-job cleanup window; the dedup key is released, so a fresh dispatch with the same key creates a new job. Nothing is deleted. Confirmation is required for every live job.

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
Bash(test -d .experts/.jobs/<expert_name>/<job_id> && echo exists || echo missing)
Bash(test -f .experts/.jobs/<expert_name>/<job_id>/CANCELLED && echo cancelled || true)
Bash(test -f .experts/.jobs/<expert_name>/<job_id>/DONE && echo done || echo pending)
```

Classify as:
- `missing` — job directory does not exist → report and exit. Outcome: `missing`.
- `cancelled` — CANCELLED marker already present → already cancelled, nothing to do. Outcome: `already-cancelled`.
- `done` — DONE marker present.
- `pending` — directory exists, no DONE marker (queued or running; a PID marker means the daemon claimed it).

Outcome: `classified`.

## Step 3 — Confirm cancellation

For `missing`: print "Job `<job_id>` not found for expert `<expert_name>`." and exit with outcome `absent`.

For `already-cancelled`: print "Job `<job_id>` is already cancelled; bundle kept at `.experts/.jobs/<expert_name>/<job_id>/`." and exit with outcome `already-cancelled`.

For `pending`: call `AskUserQuestion`: "Job `<job_id>` is pending — if the daemon is executing it, its executor process will be stopped immediately. Cancel?" (Yes/No). If No → exit with outcome `user-aborted`.

For `done`: call `AskUserQuestion`: "Job `<job_id>` is already done. Mark it cancelled anyway? (The bundle stays on disk either way.)" (Yes/No). If No → exit with outcome `user-aborted`.

Outcome: `confirmed`, `user-aborted`, `already-cancelled`, or `absent`.

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

Print: "Job `<job_id>` cancelled — executor stopped, bundle kept at `.experts/.jobs/<expert_name>/<job_id>/` with a CANCELLED marker."

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
- Confirmation: <confirmed|user-aborted|already-cancelled|absent>
- Cancellation: <cancelled|skipped>

`## Result` `<success|aborted>` — job_id=`<job_id>`, outcome=`<outcome>`.

## Failure modes

- **"expert_name is required"** (or `job_id`) — required argument missing → supply both.
- **"Job not found"** — job directory absent; job was never dispatched or its bundle already aged out → verify job_id and expert_name via `/lazy-expert.list-jobs`.
- **User aborts confirmation** — user chose No → nothing signalled, no markers changed; job remains in its current state.
- **Python `ModuleNotFoundError`** — plugin not installed → run `/lazy-core.install`.
