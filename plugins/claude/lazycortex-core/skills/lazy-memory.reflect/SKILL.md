---
name: lazy-memory.reflect
description: "Run when the operator asks an expert to consolidate what it has learned — fold its recent run logs into its memory notes. Dispatches one `kind=reflect` job for that expert; refuses an expert that is not persona-marked (run `/lazy-memory.mark-persona` first)."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, Agent
---
# Memory reflect

Dispatch a `kind=reflect` job to one expert. The expert receives recent run logs and current memory as input, applies its memory aspect's obligations, and returns `outcome=edited` (notes changed) or `outcome=empty` (nothing to consolidate).

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Confirm expert is persona-marked`
   - `Step 3 — Dispatch reflect job`
   - `Step 4 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.**
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.**

## Step 1 — Validate inputs

Required input:
- `expert` (string) — a key in `.claude/lazy.settings.json[experts]`.

Optional input:
- `days` (int, default 30) — how far back to pull `.logs/claude/<expert>/*.md` files into `source[]`.

Outcome: `validated` or `aborted`.

## Step 2 — Confirm expert is persona-marked

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get experts --key '<expert>/aspects')
```

If the printed list does not contain `lazycortex-core:lazy-memory.persona-aspect` (or the output is `null` — no entry, or no aspects), abort: "`<expert>` is not marked persona; run `/lazy-memory.mark-persona <expert>`."

Outcome: `persona-confirmed` or `aborted-not-persona`.

## Step 3 — Dispatch reflect job

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" memory-reflect '<expert>' --days <days>)
```

The verb collects the source list itself — run logs under `.logs/claude/<expert>/` newer than `days` plus every note under `.memory/<expert>/` — builds the `kind=reflect` payload, re-checks the persona aspect (`not-persona` with exit 1 if it is missing) and dispatches with no protocols, since the aspect itself carries the obligations.

Parse `{job_id, queue_path}` (`{"error": "…"}` with exit 1 when the expert's configuration refuses the dispatch).

Outcome: `dispatched` or `error`.

## Step 4 — Report

One line per task. Print:

```
expert:    <expert>
job_id:    <job_id>
queue_path: <queue_path>
```

## Failure modes

- **"`<expert>` is not marked persona"** — opt the expert in via `/lazy-memory.mark-persona <expert>` and re-run.
- **`<expert>` not in `lazy.settings.json[experts]`** — the expert is unknown; verify the name or register via `/lazy-core.install`.
- **No source files found** — the expert has no recent run logs and no existing memory notes. The reflect job will be a no-op; consider skipping until the expert has run jobs to consolidate.
