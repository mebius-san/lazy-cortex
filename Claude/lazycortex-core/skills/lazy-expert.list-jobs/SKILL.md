---
name: lazy-expert.list-jobs
description: List expert queue jobs, optionally filtered by expert name or status. Wraps expert_runtime.list_jobs.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Write, AskUserQuestion
logging-waiver: "read-only status query — single read, no mutation, no decision"
---
# Expert List Jobs

List all jobs in the expert queue, sorted oldest-first by age. Supports optional filters for expert name and status (`pending`, `done`, `failed`). Output is a tabular summary of `{expert, job_id, status, age_sec}`.

Note on `status="failed"` filtering: `list_jobs` in `expert_runtime` classifies jobs only as `pending` or `done` based on the DONE marker. To filter for `failed`, the skill reads each `response.json` and checks `outcome == "error"`. This adds one file-read per job when the filter is active.

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
- `status` (string) — filter to `pending`, `done`, or `failed` only.

If `status` is provided but not one of `pending`, `done`, `failed` → abort: "status must be one of: pending, done, failed. Got: `<value>`."

Outcome: `validated` or `aborted`.

## Step 2 — List jobs

Shell out to `expert_runtime.list_jobs`. When `status` is NOT `"failed"`, pass the filter directly:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys, time
from pathlib import Path
from expert_runtime import list_jobs

expert_filter = sys.argv[1] if sys.argv[1] != '' else None
status_filter = sys.argv[2] if sys.argv[2] != '' else None

# For 'failed', fetch all done jobs then filter by response.json outcome
if status_filter == 'failed':
    jobs = list_jobs(Path('.'), expert=expert_filter, status='done')
    result = []
    for j in jobs:
        resp_path = Path(j['path']) / 'response.json'
        outcome = ''
        if resp_path.exists():
            try:
                outcome = json.loads(resp_path.read_text()).get('outcome', '')
            except Exception:
                outcome = 'parse-error'
        if outcome == 'error':
            j['status'] = 'failed'
            result.append(j)
else:
    result = list_jobs(Path('.'), expert=expert_filter, status=status_filter)

# Compute age_sec using DONE.mtime for done/failed, READY.mtime for pending
now = time.time()
for j in result:
    jpath = Path(j['path'])
    marker = jpath / 'DONE' if (jpath / 'DONE').exists() else jpath / 'READY'
    j['age_sec'] = int(now - marker.stat().st_mtime) if marker.exists() else -1

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

`## Result`
`success` — listed N job(s).

## Failure modes

- **"status must be one of: pending, done, failed"** — caller passed an unsupported status value → use one of the three valid values.
- **"No jobs found"** — the jobs base directory is absent or empty → confirm that jobs have been dispatched and `.experts/.jobs/` exists.
- **`.experts/.jobs/` missing** — expert runtime not bootstrapped in this repo → run `/lazy-core.install`.
