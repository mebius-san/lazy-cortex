---
name: spec.import
description: Pull-based cross-repo design handoff — fetch every configured `spec.imports[]` entry, land each `handoff` product's approved assets read-only (`spec_imported: true`), auto-register missing products, and report the run as a summary table. Non-interactive; the manual counterpart to the `spec.import-pull` daemon routine, both driving the same primitive.
---
# Import Specs

Pull one or more spec-repos configured under the `spec` settings section's `imports` array, land each qualifying asset's approved authored docs into this repo, and report the outcome. This skill is the operator-invoked entry point; `/spec.install` Step 6.6 registers a `spec.import-pull` schedule routine that calls the same underlying primitive (`lazycortex-specs import-specs`) on a cadence — running this skill by hand and waiting for the routine produce identical results.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical list:
   - `Step 1 — Run the importer`
   - `Step 2 — Render the summary table`
   - `Step 3 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.**
3. **Do not finalise until `TaskList` shows every prior task `completed`.**

## Step 1 — Run the importer

Run `Bash(lazycortex-specs import-specs)`. It prints exactly one JSON object to stdout — `{"imported": <n>, "unchanged": <n>, "drift": <n>, "skipped": <n>, "drift_assets": [<entries>], "auto_registered": [<product-keys>], "errors": [{"git_url": <url>, "error": <message>}]}` — and always exits `0` (drift, skips, and per-entry errors are report outcomes, never a process failure — one bad `spec.imports[]` entry does not abort the rest). Parse the JSON.

Outcome: `ran:<imported>/<unchanged>/<drift>/<skipped>`.

## Step 2 — Render the summary table

Render the parsed counts:

| Outcome | Count |
|---|---|
| Imported | `<imported>` |
| Unchanged | `<unchanged>` |
| Drift | `<drift>` |
| Skipped | `<skipped>` |
| Auto-registered | `<len(auto_registered)>` |

- When `drift > 0`, list every entry from `drift_assets` (`<product-key>/<category>/<slug>`, one per line) below the table. Drift means the upstream doc changed after the original handoff; the importer never overwrites the already-landed copy, so these need an operator decision.
- When `skipped > 0`, add the hint: an operator-defined asset category with no matching templates in this repo was skipped for at least one asset — run `/spec.add-asset-category` here to add the missing category's templates, then re-run `/spec.import`.
- When `auto_registered` is non-empty, list the product keys it registered. Each is a bare product record (`spec_path` mirrored from upstream; `handoff`, `source`, and `dependencies` stripped, per `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` Part 4) — the operator completes the tree (folder-notes, icons) via `/spec.product-config` edit mode when desired.
- When `errors` is non-empty, list each `{git_url, error}` pair below the table. That entry's assets did not land this run; the other entries still landed normally.

Outcome: `rendered`.

## Step 3 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.import/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.import)`, then `Write` the file — never chain with `&&`. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input: none`. Body: `# spec.import` heading, `## Actions` (the parsed counts), `## Result` (the rendered table, plus any drift/skip hints).

Outcome: `logged`.

## Failure modes

- **Every count is `0`** — no `spec.imports[]` entries are configured, or the configured spec-repo(s) have no `handoff` products → configure `spec.imports` (see `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`), or check that the upstream repo's `products[<key>].handoff` records exist.
- **The same asset keeps reporting drift on every run** — the upstream doc changed after the original handoff; the importer refuses to overwrite the locally-landed copy on principle (design is frozen at handoff). Resolve by hand — compare the two copies and decide whether to adopt the upstream change.
- **An entry shows up in `errors`** — that entry's `git_url` was unreachable, its ref/branch didn't resolve, or its `lazy.settings.json` was malformed; the message is the underlying exception, truncated. The rest of the configured entries still ran normally this pass. Fix the entry (correct URL, correct `ref`, or ask the spec-repo operator to repair its settings) and re-run.

## Key Rules

- **Non-interactive.** No `AskUserQuestion` anywhere — the primitive is shared with the unattended `spec.import-pull` daemon routine, so the manual path behaves identically without operator input.
- **Reports, never configures.** This skill only invokes the importer and renders its result; adding or editing `spec.imports[]` entries is `/spec.product-config` or a direct edit of the `spec` settings section.
- **Idempotent.** Re-running with nothing changed upstream reports `unchanged` for every previously-imported asset; the exit code is always `0`.
