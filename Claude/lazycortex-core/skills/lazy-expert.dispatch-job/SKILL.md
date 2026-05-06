---
name: lazy-expert.dispatch-job
description: Dispatch a job to a named expert queue. Wraps expert_runtime.dispatch_job and returns {job_id, queue_path}.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion
---
# Expert Dispatch Job

Submit a job to a named expert's queue. The skill validates the payload against the protocol contract, writes the job to `.claude/experts/.jobs/<expert_name>/`, and returns `{job_id, queue_path}` to the caller.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Verify experts directory`
   - `Step 3 — Dispatch job`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs from the caller:
- `expert_name` (string) — the key in `experts.settings.json`.
- `payload` (dict) — the request body.

Pre-flight checks:
1. `expert_name` must be a non-empty string. If absent → abort: "`expert_name` is required."
2. `payload` must be a dict containing all three standard fields: `kind`, `role`, `request`. If any field is missing → abort with: "payload missing required field(s): <list>. See `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md` for the protocol contract."

Optional payload fields: `source` (array), `context` (array), `result` (array), plus protocol-specific extras.

Outcome: `validated` or `aborted`.

## Step 2 — Verify experts directory

Check that `.claude/experts/` exists in the current repo:

```
Bash(test -d .claude/experts && echo ok || echo missing)
```

If output is `missing` → abort: "`.claude/experts/` not initialised — run `/lazy-core.install` first."

Outcome: `asserted` or `aborted`.

## Step 3 — Dispatch job

Shell out to `expert_runtime.dispatch_job` with the validated payload:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from pathlib import Path
from expert_runtime import dispatch_job
payload = json.loads(sys.argv[1])
result = dispatch_job(Path('.'), sys.argv[2], payload)
print(json.dumps(result))
" '<payload-json>' '<expert_name>')
```

Capture and parse the JSON output: `{job_id, queue_path}`.

Outcome: `dispatched` or `error`.

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print to the caller:

```
job_id:     <job_id>
queue_path: <queue_path>
```

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-expert.dispatch-job)
```

Then `Write` to `.logs/claude/lazy-expert.dispatch-job/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "expert_name=<expert_name>"
---
```

`# lazy-expert.dispatch-job`

`## Actions`
- Validated payload fields
- Verified .claude/experts/ directory
- Dispatched job to expert queue

`## Result`
`<success|failure>` — job_id=`<job_id>`, queue_path=`<queue_path>`.

## Failure modes

- **"payload missing required field(s): kind"** (or `role`, `request`) — payload does not conform to the protocol contract → add the missing fields; see `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`.
- **"`.claude/experts/` not initialised"** — the experts directory has not been bootstrapped in this repo → run `/lazy-core.install` to create the required directory layout.
- **Python `FileNotFoundError` or `ModuleNotFoundError`** — `${CLAUDE_PLUGIN_ROOT}/bin` is not on the path or `expert_runtime.py` is absent → verify the plugin is installed (`/lazy-core.install`) and `${CLAUDE_PLUGIN_ROOT}` resolves correctly.
- **Unknown expert name** — `dispatch_job` creates the job dir under the named expert key; if the name is a typo, subsequent pump runs will silently skip it → verify the expert name against `experts.settings.json`.
