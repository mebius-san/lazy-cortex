---
name: lazy-memory.mark-persona
description: "Run when the operator asks to give an expert memory (let it keep notes between jobs), or when an audit reports that `.memory/<expert>/` exists but the expert is not marked persona. Appends the persona aspect to that one expert; idempotent."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion, Agent
---
# Mark expert as persona

Opt one expert into the memory subsystem. After running this skill, the expert may write under `.memory/<self>/` via `lazy-memory.write`, must consult `.memory/<self>/.tags/*.md` before primary work, and must handle `kind=reflect` jobs per `lazy-memory.persona-aspect.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Read expert entry`
   - `Step 3 — Append persona aspect`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.**
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.**

## Step 1 — Validate inputs

Required input from the caller:
- `expert` (string) — must be a key in `.claude/lazy.settings.json[experts]` (excluding `_version`).

`_version` is the section's reserved key, not an expert — treat it as absent without running the call. Otherwise:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get experts --key '<expert>')
```

If output is `null`, abort: "`<expert>` is not registered in `lazy.settings.json[experts]`."

Outcome: `validated` or `aborted-unknown-expert`.

## Step 2 — Read expert entry

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get experts --key '<expert>/aspects')
```

Parse the JSON list (`null` means the entry carries no `aspects` yet — treat it as `[]`). If `lazycortex-core:lazy-memory.persona-aspect` is already in it, state outcome `already-marked` and skip Step 3 (Report still runs).

Outcome: `read` or `already-marked`.

## Step 3 — Append persona aspect

Append `lazycortex-core:lazy-memory.persona-aspect` to the list read in Step 2 and write the whole list back:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set experts --key '<expert>/aspects' --value '<aspects-json-list>')
```

It prints `{"status": "written", …}`; `{"error": "…"}` with exit 1 means nothing was written.

Outcome: `marked`.

## Step 4 — Report

One line per task. Print to the caller:

```
expert:        <name>
aspects_after: <comma list>
```

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-memory.mark-persona)
```

Write to `.logs/claude/lazy-memory.mark-persona/<UTC-timestamp>.md` per the logging rule.

## Failure modes

- **"`<expert>` is not registered in `lazy.settings.json[experts]`"** — typo or the expert was never registered. Verify the name and re-run, or register the expert via `/lazy-core.install` first.
