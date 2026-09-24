---
name: lazy-expert.cancel-job
description: "Run when the operator wants an expert job stopped — wrong expert, changed requirements, a moved source file, or a job that should not finish. Confirms, kills the executor, and marks the bundle CANCELLED; the job directory stays on disk for forensics and the dedup key is released so the same work can be re-dispatched."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion, Agent
---
# Expert Cancel Job

Cancel an expert job. Cancellation stops the running executor (SIGTERM → grace → SIGKILL on its process groups), removes the `READY` marker, and places a `CANCELLED` marker. The bundle directory (request, response, transcript, result) stays on disk for post-mortem and ages out via the failed-job cleanup window; the dedup key is released, so a fresh dispatch with the same key creates a new job. Nothing is deleted. Confirmation is required for every live job.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Classify job`
   - `Step 3 — Confirm cancellation`
   - `Step 4 — Cancel job`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
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

For `pending`, ask:

```
Context (print before asking):
- Where: /lazy-expert.cancel-job · Step 3 — Confirm cancellation; target `.experts/.jobs/<expert_name>/<job_id>/`
- Found: directory exists, no DONE marker; <PID marker present — the daemon has claimed it | no PID marker — still queued>
- Why asking: cancelling kills a live executor (SIGTERM → SIGKILL) and releases the dedup key — not reversible
- Answers: `Yes` — executor stopped now, READY removed, CANCELLED placed; bundle stays on disk, a same-key dispatch creates a new job; `No` — nothing signalled, no markers changed, outcome `user-aborted`
AskUserQuestion: header "Cancel job", question "Cancel pending job `<job_id>` of expert `<expert_name>`? If the daemon is executing it, its executor process is stopped immediately.", options `Yes` / `No` with the descriptions above.
```

If No → exit with outcome `user-aborted`.

For `done`, ask:

```
Context (print before asking):
- Where: /lazy-expert.cancel-job · Step 3 — Confirm cancellation; target `.experts/.jobs/<expert_name>/<job_id>/`
- Found: DONE marker present — the job already finished
- Why asking: marking a finished job cancelled releases its dedup key so the same work can be re-dispatched; whether the finished result should stand is the operator's call
- Answers: `Yes` — CANCELLED placed on the finished bundle, nothing to kill, bundle stays on disk; `No` — job stays done, outcome `user-aborted`
AskUserQuestion: header "Cancel done job", question "Job `<job_id>` of expert `<expert_name>` is already done — mark it cancelled anyway? The bundle stays on disk either way.", options `Yes` / `No` with the descriptions above.
```

If No → exit with outcome `user-aborted`.

Outcome: `confirmed`, `user-aborted`, `already-cancelled`, or `absent`.

## Step 4 — Cancel job

On confirmation, run the core `cancel-job` verb with the request on stdin:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" cancel-job <<'EOF'
{"expert": "<expert_name>", "job_id": "<job_id>"}
EOF
)
```

It prints `{"cancelled": true, "job_id": "<job_id>"}` on success; `{"cancelled": false, "job_id": "<job_id>"}` means the bundle was already terminal (done, failed, deferred, dead, cancelled) or absent and was left untouched; `{"error": "…"}` with exit 1 is a failed cancel.

Print: "Job `<job_id>` cancelled — executor stopped, bundle kept at `.experts/.jobs/<expert_name>/<job_id>/` with a CANCELLED marker."

Outcome: `cancelled` or `error`.

## Failure modes

- **"expert_name is required"** (or `job_id`) — required argument missing → supply both.
- **"Job not found"** — job directory absent; job was never dispatched or its bundle already aged out → verify job_id and expert_name via `/lazy-expert.list-jobs`.
- **User aborts confirmation** — user chose No → nothing signalled, no markers changed; job remains in its current state.
- **`{"cancelled": false, …}` on a job Step 2 classified as `done`** — the verb refuses to re-mark a terminal bundle; the DONE marker stands and the dedup key is not released → nothing to do, report the job as already finished.
- **Python `ModuleNotFoundError`** — plugin not installed → run `/lazy-core.install`.
