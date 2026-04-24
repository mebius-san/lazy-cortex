---
name: lazy-obsidian.iconize-config
description: "Interactively add, edit, or remove registry entries in the local `.claude/obsidian-iconize/icon-map.json` (roles, steps, requests, or any custom registry). Re-runnable. Writes back JSON with stable formatting. Use when the resolver misses a role/step/etc. — this skill is the canonical way to seed the missing registry entry without hand-editing."
allowed-tools: Read, Write, Edit, Bash(mkdir -p *), Bash(git rev-parse*), Bash(date *), AskUserQuestion
argument-hint: "[registry-name] — e.g. roles | steps | requests.classification | requests.status_color"
---
# Configure iconize-sync icon-map

Reads the vault's local `.claude/obsidian-iconize/icon-map.json` and walks the
user through adding / editing / removing registry entries via wizard-style
prompts.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate icon-map`
   - `Step 2 — Pick registry`
   - `Step 3 — Pick action`
   - `Step 4 — Apply action (add / edit / remove)`
   - `Step 5 — Write back`
   - `Step 6 — Loop or exit / Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Prerequisite

Run `lazy-obsidian.iconize-install` first. This skill only runs against an
existing local icon-map.

## Step 1 — Locate icon-map

```
<repo-root>/.claude/obsidian-iconize/icon-map.json
```

Abort with a helpful message if missing.

## Step 2 — Pick registry (one AskUserQuestion)

Enumerate top-level registry names present in `registries` (plus allow
nested dotted paths like `requests.classification`). Ask the user which to
edit. Options: each registry path + "add new registry" + "exit".

If "add new registry" → ask for registry name (free-text via `AskUserQuestion`
with an "Other" answer), then branch to Step 3 with an empty registry.

## Step 3 — Pick action (one AskUserQuestion)

Options: **add** / **edit** / **remove** / **back**.

## Step 4 — Apply action (add / edit / remove)

### Step 4a — Add

One `AskUserQuestion` per field:
1. Key name (the new registry key — e.g. "blocker").
2. `iconName` (Lucide PascalCase with `Li` prefix, or emoji).
3. `iconColor` (optional — user can pick "none" for monochrome).

Validate with the worker's validators (shell out to
`python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py --validate-entry ...` —
see Task 11b below for this helper flag).

### Step 4b — Edit

List existing keys as options. Pick one. Then edit iconName/iconColor
per Step 4a.

### Step 4c — Remove

List existing keys as options. Pick one. Confirm via a second
`AskUserQuestion` (**confirm-remove** / **cancel**).

## Step 5 — Write back

Rewrite `icon-map.json` with `json.dumps(..., indent=2, ensure_ascii=False) + "\n"`.
Preserve any top-level keys the skill didn't touch (`matchers`, `version`,
`stage_colors`).

## Step 6 — Loop or exit / Report

One `AskUserQuestion`: **continue** / **exit**. Continue returns to Step 2.

On exit, print one report line per task in the canonical list above, each
with an outcome word (e.g. `located`, `picked`, `added`, `edited`, `removed`,
`written`, `exited`).

## Step 7 — Log the run

`./.logs/claude/lazy-obsidian.iconize-config/YYYY-MM-DD_HH-MM-SS.md`.
Record every mutation (before/after diff per entry) in the **Actions**
section.

## Wizard discipline

One `AskUserQuestion` per decision. Never bundle multiple fields into a
single prompt. Validate inputs before persisting.

## Notes

- This skill only touches registries. To change matcher logic, edit
  `icon-map.json` by hand — matchers are structural and benefit from seeing
  the whole file at once.
- After any registry change, remind the user to run
  `lazy-obsidian.iconize-sync reconcile` so `data.json` picks up the new
  entries.
