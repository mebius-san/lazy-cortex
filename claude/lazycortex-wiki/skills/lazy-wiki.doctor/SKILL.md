---
name: lazy-wiki.doctor
description: "Audit a wiki scope's integrity: orphan topics, broken See-also links and repo keys, index desync, missing summaries, stale glosses, unknown axes, duplicate branches, broken code <wiki> blocks, and scope overlaps. Read-only by default; applies fixable repairs only after the operator confirms."
allowed-tools: Read, Bash(lazycortex-wiki doctor *), Bash(date -u *), Bash(git rev-parse *), Bash(mkdir -p *)
---
# lazy-wiki.doctor

Run the integrity audit over one wiki scope (or every configured scope), present the findings grouped by severity, and — only after the operator confirms — apply the fixable repairs. Fixable repairs are: rebuild the topic index (orphan-topic, index-desync), drop broken See-also lines (broken-see-also), and refresh stale glosses (stale-gloss). All other findings are report-only.

Invocation: `/wiki.doctor [<scope-id>]`

Prerequisites: `/wiki.install` has run and at least one scope is configured in `.claude/lazy.settings.json[wiki.scopes]`.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Run the audit`
   - `Phase 2 — Present findings`
   - `Phase 3 — Confirm and apply fixes`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Log step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Run the audit

Run the read-only audit first — never pass `--apply` in this phase.

`Bash(lazycortex-wiki doctor <scope-id>)` when the operator named a scope, or `Bash(lazycortex-wiki doctor)` to audit every configured scope.

The command prints findings grouped per scope and severity (`FAIL` / `WARN` / `INFO`), tags each fixable finding `(fixable)`, and ends with a grand-total count. It exits 0 when the audit ran; a non-zero exit means the named scope id is unknown or no scopes are configured — surface that message to the operator and stop (do not proceed to later phases).

Outcome: `audited`.

## Phase 2 — Present findings

Summarise the captured output for the operator: the per-scope counts by severity, and a short list of the concrete findings (check name, node path, message). Call out which findings are fixable (`orphan-topic`, `index-desync`, `broken-see-also`, `stale-gloss`) versus report-only (`broken-repo-key`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`).

If the audit found zero findings, report "scope clean" and skip to the Log step (mark Phase 3 `skipped` with outcome `skipped-per-user-choice`).

Outcome: `presented`.

## Phase 3 — Confirm and apply fixes

If there are no fixable findings, skip with outcome `skipped-per-user-choice`.

Otherwise ask the operator via `AskUserQuestion` whether to apply the fixable repairs. State exactly what `--apply` will do: rebuild the topic index, drop the broken See-also lines, and refresh stale glosses — these write tracked files. Offer at minimum: apply fixes, leave read-only.

- **Operator declines** → outcome `skipped-per-user-choice`. Do not run `--apply`.
- **Operator confirms** → run `Bash(lazycortex-wiki doctor <scope-id> --apply)` (same scope argument as Phase 1, add `--apply`). The command reports each fix as `(fixed)`. Report what was applied. Outcome `applied`.

Outcome: `applied` or `skipped-per-user-choice`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.doctor/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.doctor)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.doctor/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<scope-id or 'all scopes'>"
---
# lazy-wiki.doctor

## Actions
- <bullet per step with outcome>

## Result
<success/failure + one-sentence summary of finding counts and any fixes applied>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/wiki.doctor` reports "unknown scope '<id>'"** — the scope id is not in `lazy.settings.json[wiki.scopes]` → run `/wiki.configure` to create it, or re-invoke with a known id.
- **`/wiki.doctor` reports "no wiki scopes configured"** — no scopes exist yet → run `/wiki.install` then `/wiki.configure` first.
