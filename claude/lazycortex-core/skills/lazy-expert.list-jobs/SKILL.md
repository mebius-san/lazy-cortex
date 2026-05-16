---
name: lazy-expert.list-jobs
description: List expert queue jobs, optionally filtered by expert name or status. Wraps expert_runtime.list_jobs.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Write, AskUserQuestion
logging-waiver: "read-only status query — single read, no mutation, no decision"
---
# Expert List Jobs

List all jobs in the expert queue, sorted oldest-first by age. Supports optional filters for expert name and status (`queued`, `active`, `dead`, `done`, `failed`). Output is a tabular summary of `{expert, job_id, status, age_sec}`.

### Job status enum

| Filesystem signature | `status` |
|---|---|
| `READY` only (no `PID`) | `queued` |
| `READY` + `PID` (no `DEAD`, no `response.json`) | `active` |
| `DEAD` exists | `dead` |
| `DONE` + `response.json` (outcome ≠ error) | `done` |
| `DONE` + `response.json` (outcome == error) | `failed` |

Use the `--status` filter with any of these values to scope the listing.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — List jobs`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

All inputs are optional:
- `expert` (string) — filter to one expert.
- `status` (string) — filter to one of `queued`, `active`, `dead`, `done`, or `failed`.

If `status` is provided but not one of these five values → abort: "status must be one of: queued, active, dead, done, failed. Got: `<value>`."

Outcome: `validated` or `aborted`.

## Step 2 — List jobs

Shell out to `expert_runtime.list_jobs`, passing the status filter directly (all five enum values are handled natively):

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys, time
from pathlib import Path
from expert_runtime import list_jobs

expert_filter = sys.argv[1] if sys.argv[1] != '' else None
status_filter = sys.argv[2] if sys.argv[2] != '' else None

result = list_jobs(Path('.'), expert=expert_filter, status=status_filter)

# Compute age_sec using DONE/DEAD/READY mtime, oldest marker wins
now = time.time()
for j in result:
    jpath = Path(j['path'])
    for marker_name in ('DONE', 'DEAD', 'READY'):
        m = jpath / marker_name
        if m.exists():
            j['age_sec'] = int(now - m.stat().st_mtime)
            break
    else:
        j['age_sec'] = -1

print(json.dumps(result))
" '<expert>' '<status>')
```

Sort the result list by `age_sec` descending (oldest first).

Outcome: `listed` or `empty`.

## Step 3 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

If no jobs found, print: "No jobs found" (with the active filters if any) — outcome `empty`.

Otherwise print a table:

```
expert                  job_id          status   age_sec
---------               --------        ------   -------
<expert>                <job_id>        <status> <age_sec>
```

## Step 4 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-expert.list-jobs)
```

Then `Write` to `.logs/claude/lazy-expert.list-jobs/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "expert=<expert|none> status=<status|none>"
---
```

`# lazy-expert.list-jobs`

`## Actions`
- Validated filters
- Called list_jobs (N jobs returned)

`## Result` `success` — listed N job(s).

## Failure modes

- **"status must be one of: queued, active, dead, done, failed"** — caller passed an unsupported status value → use one of the five valid values.
- **"No jobs found"** — the jobs base directory is absent or empty → confirm that jobs have been dispatched and `.experts/.jobs/` exists.
- **`.experts/.jobs/` missing** — expert runtime not bootstrapped in this repo → run `/lazy-core.install`.
