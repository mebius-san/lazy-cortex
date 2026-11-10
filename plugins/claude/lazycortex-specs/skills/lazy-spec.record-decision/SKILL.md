---
name: lazy-spec.record-decision
description: "Use when the operator wants to record, supersede, obsolete, or promote an entry in the spec catalog's decisions registry — 'log this decision', 'mark D-007 superseded', 'D-012 is obsolete now', 'pull the decision blocks out of design.md'. Interactive wrapper over the `decide` CLI primitive; never edits a `decisions.md` file by hand."
allowed-tools: Read, Glob, Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(git status*), Bash(mkdir -p *), AskUserQuestion, Agent
---
# Record Decision

Interactive wrapper over the four `decide` operations — `add`, `supersede`, `obsolete`, `promote`. All writes go through `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide ...)`; this skill NEVER edits a `decisions.md` file, or a living doc's `[!decision]` blocks, by hand. Before recording a new decision, hold the operator to the weight test in `${CLAUDE_PLUGIN_ROOT}/rules/lazy-spec.decisions.md` — a real fork, expensive to reverse, unrecoverable from the artifact.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Choose the operation`
   - `Step 2 — Resolve the target`
   - `Step 3 — Collect the record fields`
   - `Step 4 — Run the primitive`
   - `Step 5 — Commit the touched paths`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`refused`, `duplicate`, `noop`, `no-commit`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per step above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Choose the operation

Ask via `AskUserQuestion`, one question, four options:

```
Context (print before asking):
- Where: /lazy-spec.record-decision · Step 1 — Choose the operation; target the decisions registry of <the asset | product | project the invocation named, or "not named yet">
- Found: <the target path or D-NNN id the invocation carried, or "no target named yet">
- Why asking: the four `decide` operations write different things and the invocation did not name one
- Answers: one of the four below — Step 2 then resolves its target; nothing is written until Step 4 runs the primitive
AskUserQuestion: header "Operation", question "Which decisions-registry operation should run<, for <target>>?", options `add` / `supersede <id>` / `obsolete <id>` / `promote <living-doc>` with the descriptions below.
```

- `add` — a new entry in an asset's, product's, or the project's `decisions.md`.
- `supersede <id>` — a new entry that also marks an older one `superseded-by`.
- `obsolete <id>` — marks an existing entry `obsolete — <reason>`.
- `promote <living-doc>` — transfers decision blocks out of a `vision.md` / `design.md` / `bug.md` / `tech.md` / `architecture.md` body into its sibling registry.

## Step 2 — Resolve the target

- **`add` / `supersede` / `obsolete`** — resolve the `decisions.md` file this call targets: a status folder-note path, an asset directory, a product root, a product key plus the asset's product-relative path (the same way `lazy-spec.flip-gate` resolves an asset), or the spec content-root for a project-wide decision. Resolution order mirrors the placement ladder: asset → product → project. Build `<decisions.md>` = `<asset_dir>/decisions.md` (asset-level), `<spec_path>/decisions.md` (product-level), or `<content-root>/decisions.md` (project-level — a decision about the system pair or a cross-product concern). The file need not exist yet — the first record lazily creates it. If the input is ambiguous, prompt via `AskUserQuestion` with the candidate paths — context first: where (`/lazy-spec.record-decision · Step 2 — Resolve the target`), found (the candidate `decisions.md` paths the input matched, each with its level: asset / product / project), why asking (the placement ladder resolves the input to several files), answers (one option per candidate path — the record lands in that file, created lazily if absent; never re-asked); header "Target registry", question "Which decisions.md should `<op>` write to for input `<input>`?".
- **`promote`** — resolve the **living document** path directly. Do NOT pre-filter by role or by the owning asset's cancelled/halted/released flags — the primitive is the sole judge; a plan, a report, or a halted/cancelled/released asset's doc produces a `refused` result, surfaced verbatim in Step 4. Never work around a refusal.

## Step 3 — Collect the record fields

**Language first.** Before collecting any free text, run `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" resolve-language <decisions.md relpath>)` and write the thesis and the justification text in the code it returns — the operator's own words are kept verbatim in whatever language they typed them. Record ids, origins, and wikilink targets are never translated.

- **`add`** — thesis (one line), justification (plain prose stating why the decision holds; no `Why` / `Rejected` labels, no list of alternatives), optional `--origin` (a qualified wikilink to a source doc; default `—` for a manual entry with none).
- **`supersede`** — the old id (`D-NNN`, named directly by the operator), then the same thesis / justification / optional `--origin` as `add`.
- **`obsolete`** — the record id (`D-NNN`) and a reason string.
- **`promote`** — nothing further; the doc path from Step 2 is the only input.

Before collecting an `add` or `supersede` thesis, restate the three-test weight bar from `lazy-spec.decisions.md` in one line and ask the operator to confirm a genuine fork exists — a foregone conclusion is not worth a record. Context first: where (`/lazy-spec.record-decision · Step 3 — Collect the record fields`, target `<decisions.md>`), found (the thesis as stated so far), why asking (only the operator knows whether a real alternative existed and reversal is expensive), answers (`yes, a real fork` — continue collecting the justification; `no` — stop, nothing written); header "Weight test", question "Is `<thesis>` a genuine fork — a real alternative existed, reversal is expensive, the why is unrecoverable from the artifact?".

## Step 4 — Run the primitive

Subprocess the matching call with `--commit`, quoting every free-text argument:

- `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide add <decisions.md> "<thesis>" "<justification>" [--origin "<origin>"] --commit)`
- `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide supersede <decisions.md> <old-id> "<thesis>" "<justification>" [--origin "<origin>"] --commit)`
- `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide obsolete <decisions.md> <id> "<reason>" --commit)`
- `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide promote <living-doc> --commit)`

Parse the single-line JSON printed on stdout.

- **`refused`** — stop here. Do not commit, do not retry, do not work around it. Report the primitive's `reason` field verbatim — this is how a `promote` call on a non-living doc, or on a cancelled/halted/released asset, surfaces to the operator.
- **`duplicate`** (from `add`, including the write-through inside `supersede`) — nothing was written; report the existing id.
- **`noop`** (from `promote`, no decision blocks found in the doc) — nothing was written.
- **`added` / `superseded` / `obsoleted` / `promoted`** — continue to Step 5.

## Step 5 — Commit the touched paths

`--commit` makes the primitive commit what it wrote, in the same call; this step only reads the result. On `refused` / `duplicate` / `noop` nothing was written and the result carries no `commit` field (outcome `no-commit`). On `added` / `superseded` / `obsoleted` / `promoted` read `result["commit"]`: `status: committed` with its `sha` (outcome `committed`), or `status: nothing-to-commit` (outcome `no-commit`). The commit carries the `<decisions.md>` file for `add` / `supersede` / `obsolete` and exactly `result["touched_paths"]` for `promote`, under the subject the `decide` verb composes (`${CLAUDE_PLUGIN_ROOT}/bin/spec_decisions.py` owns it).

## Report

One line per step above, plus: operation, target path(s), primitive outcome, id(s) touched, commit sha or the reason nothing was committed.

## Failure modes

- **`lazy-spec.record-decision` reports `status: refused`, `reason: no such record: D-NNN`** — the id given to `supersede` or `obsolete` is not in that file → re-check the id against the file's own `## D-NNN` headings.
- **`lazy-spec.record-decision` reports `status: refused`, `reason: no such doc: <path>`** — the living-doc path passed to `promote` does not exist → check the path.
- **`lazy-spec.record-decision` reports `status: refused`, `reason: spec_role '<x>' is not a living doc (…)`** — the document passed to `promote` is a plan or a report → write the decision statement in the living doc the reason lists, approve it, and promote that one.
- **`lazy-spec.record-decision` reports `status: refused`, `reason: asset flag <flag> is true`** — the owning asset is cancelled, halted, or released → clear the flag (or un-halt the asset) and re-run `promote`, or leave the block in place.
- **`lazy-spec.record-decision` reports `status: duplicate`** — an existing record already carries the same thesis and body; nothing was written, not an error.
