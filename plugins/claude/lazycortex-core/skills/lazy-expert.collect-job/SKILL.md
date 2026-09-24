---
name: lazy-expert.collect-job
description: "Run when the operator asks for the result of an expert job already dispatched, naming the expert and job_id. Reports pending / done / deferred / failed and, when the job finished, the result file paths to read."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date -u *), Write, AskUserQuestion, Agent
---
# Expert Collect Job

Poll a named expert's job for its result. Returns `{status, response}` where `status` is `pending`, `done`, or `failed`. When `done`, prints the `result` file paths from `response.json` so the caller can `Read` them.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Collect job`
   - `Step 3 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs from the caller:
- `expert_name` (string) — the expert key.
- `job_id` (string) — the job identifier returned by `/lazy-expert.dispatch-job`.

Both must be non-empty strings. If either is absent → abort with: "`<field>` is required."

Outcome: `validated` or `aborted`.

## Step 2 — Collect job

Run the core `collect-job` verb with the request on stdin:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" collect-job <<'EOF'
{"expert": "<expert_name>", "job_id": "<job_id>"}
EOF
)
```

Capture and parse the JSON output: `{status, response?}` (`{"error": "…"}` with exit 1 when the request is malformed or the read fails).

- `status == "pending"` — job is queued; DONE marker not yet written.
- `status == "done"` — DONE marker present and `response.outcome != "error"`.
- `status == "failed"` — DONE marker present and `response.outcome == "error"`.
- `status == "missing"` — job directory does not exist.

Outcome: `collected`.

## Step 3 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print status summary:

```
status: <status>
```

If `status == "done"` and `response.result[]` is non-empty, list the result file paths:

```
result files (Read these to retrieve output):
  - <path>
  - <path>
```

If `status == "failed"`, print `response.error` (or `response.message`) if present.

If `status == "missing"`, print: "Job `<job_id>` not found for expert `<expert_name>`. Check the job_id or expert_name."

## Failure modes

- **"job_id is required"** — caller omitted the job_id argument → supply the job_id returned by `/lazy-expert.dispatch-job`.
- **status == "missing"** — the job directory was never created or was already cancelled → verify the job_id and expert_name are correct; re-dispatch if needed.
- **Malformed response.json** — `collect-job` reads `response.json` and prints `{"error": "collect failed: …"}` if the expert wrote invalid JSON → inspect the file at `.experts/.jobs/<expert>/<job_id>/response.json` directly.
- **Python `ModuleNotFoundError`** — plugin not installed or `${CLAUDE_PLUGIN_ROOT}` not set → run `/lazy-core.install`.
