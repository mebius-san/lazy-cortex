---
name: lazy-spec.decide
description: "Use when the operator wants to record, supersede, obsolete, or promote an entry in the spec catalog's decisions registry — 'log this decision', 'mark D-007 superseded', 'D-012 is obsolete now', 'pull the decision blocks out of design.md'. Interactive wrapper over the `decide` CLI primitive; never edits a `decisions.md` file by hand."
allowed-tools: Read, Glob, Bash(lazycortex-specs *), Bash(git add -N *), Bash(git commit *), Bash(git status*), Bash(mkdir -p *), AskUserQuestion, Agent, TaskCreate, TaskUpdate, TaskList, TaskGet
---
# Decide

Interactive wrapper over the four `decide` operations — `add`, `supersede`, `obsolete`, `promote`. All writes go through `Bash(lazycortex-specs decide ...)`; this skill NEVER edits a `decisions.md` file, or a living doc's `[!decision]` blocks, by hand. Before recording a new decision, hold the operator to the weight test in `${CLAUDE_PLUGIN_ROOT}/rules/spec.decisions.md` — a real fork, expensive to reverse, unrecoverable from the artifact.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Choose the operation`
   - `Step 2 — Resolve the target`
   - `Step 3 — Collect the record fields`
   - `Step 4 — Run the primitive`
   - `Step 5 — Commit the touched paths`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`refused`, `duplicate`, `noop`, `no-commit`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per step above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Choose the operation

Ask via `AskUserQuestion`, one question, four options:

- `add` — a new entry in an asset's or product's `decisions.md`.
- `supersede <id>` — a new entry that also marks an older one `superseded-by`.
- `obsolete <id>` — marks an existing entry `obsolete — <reason>`.
- `promote <living-doc>` — transfers decision blocks out of a `design.md` / `bug.md` / `tech.md` / `architecture.md` body into its sibling registry.

## Step 2 — Resolve the target

- **`add` / `supersede` / `obsolete`** — resolve the `decisions.md` file this call targets: a status folder-note path, an asset directory, a product root, or a product key plus category/slug, the same way `lazy-spec.flip-gate` resolves an asset. Build `<decisions.md>` = `<asset_dir>/decisions.md` (asset-level) or `<spec_path>/decisions.md` (product-level). The file need not exist yet — the first record lazily creates it. If the input is ambiguous, prompt via `AskUserQuestion` with the candidate paths.
- **`promote`** — resolve the **living document** path directly. Do NOT pre-filter by role or by the owning asset's cancelled/halted/released flags — the primitive is the sole judge; a plan, a report, or a halted/cancelled/released asset's doc produces a `refused` result, surfaced verbatim in Step 4. Never work around a refusal.

## Step 3 — Collect the record fields

- **`add`** — thesis (one line), `--why`, `--rejected`, optional `--origin` (a qualified wikilink to a source doc; default `—` for a manual entry with none).
- **`supersede`** — the old id (`D-NNN`, named directly by the operator), then the same thesis / `--why` / `--rejected` / optional `--origin` as `add`.
- **`obsolete`** — the record id (`D-NNN`) and a reason string.
- **`promote`** — nothing further; the doc path from Step 2 is the only input.

Before collecting an `add` or `supersede` thesis, restate the three-test weight bar from `spec.decisions.md` in one line and ask the operator to confirm a genuine fork exists — a foregone conclusion is not worth a record.

## Step 4 — Run the primitive

Subprocess the matching call, quoting every free-text argument:

- `Bash(lazycortex-specs decide add <decisions.md> "<thesis>" --why "<why>" --rejected "<rejected>" [--origin "<origin>"])`
- `Bash(lazycortex-specs decide supersede <decisions.md> <old-id> "<thesis>" --why "<why>" --rejected "<rejected>" [--origin "<origin>"])`
- `Bash(lazycortex-specs decide obsolete <decisions.md> <id> "<reason>")`
- `Bash(lazycortex-specs decide promote <living-doc>)`

Parse the single-line JSON printed on stdout.

- **`refused`** — stop here. Do not commit, do not retry, do not work around it. Report the primitive's `reason` field verbatim — this is how a `promote` call on a non-living doc, or on a cancelled/halted/released asset, surfaces to the operator.
- **`duplicate`** (from `add`, including the write-through inside `supersede`) — nothing was written; report the existing id.
- **`noop`** (from `promote`, no decision blocks found in the doc) — nothing was written.
- **`added` / `superseded` / `obsoleted` / `promoted`** — continue to Step 5.

## Step 5 — Commit the touched paths

The primitive never commits — it only writes files and, for `promote`, returns `touched_paths`. Skip this step entirely on `refused` / `duplicate` / `noop` (outcome `no-commit`).

- **`add` / `supersede` / `obsolete`** — the touched path is the `<decisions.md>` argument from Step 2. `Bash(git add -N <path>)` when the file did not exist before this run (lazy creation), then `Bash(git commit -m "<message>" -- <path>)`.
- **`promote`** — the touched paths are exactly `result["touched_paths"]` (the doc, its sibling registry, and — on a `**Supersedes.**` line — the superseded record's own registry file, which may be the product's rather than the asset's). `git add -N` any of them that did not exist before this run, then commit all of them together in one call.

Commit message: `docs(spec-decisions): <op> <id-or-doc-stem>` — deterministic, names the operation and its target.

## Step 6 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.decide/YYYY-MM-DD_HH-MM-SS.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`), a short `## Actions` bullet list (operation, target, primitive result), and a `## Result` line.

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-spec.decide)` then the `Write` tool. Never chain with `&&`.

## Report

One line per step above, plus: operation, target path(s), primitive outcome, id(s) touched, commit sha or the reason nothing was committed.

## Failure modes

- **`lazy-spec.decide` reports `refused: no such record: D-NNN`** — the id given to `supersede` or `obsolete` doesn't exist in that file → re-check the id against the file's own `## D-NNN` headings.
- **`lazy-spec.decide` reports `refused: no such doc`** — the living-doc path passed to `promote` doesn't exist → check the path.
- **`lazy-spec.decide` reports `refused: spec_role '<x>' is not a living doc`** — `promote` only reads from `design` / `bug` / `tech` / `architecture`; a plan never promotes (plans decompose already-accepted decisions, not source them) and a report never promotes (it carries only decision-candidates) → the fix is a decision statement in the correct living doc, followed by its own approve/promote, never a forced promote on the plan or report.
- **`lazy-spec.decide` reports `refused: asset flag spec_cancelled/spec_halted/spec_released is true`** — the owning asset is cancelled, halted, or released; `promote` refuses unconditionally in all three states → clear the flag (or, for a halted asset, un-halt it) and re-run `promote`, or leave the block in place — nothing forces the transfer.
- **`lazy-spec.decide` reports `duplicate: D-NNN`** — an existing record already carries the same normalized thesis and body; nothing new was written, not an error.
