---
name: lazy-obsidian.iconize-configure
description: "Interactively add, edit, or remove registry entries in the local `.claude/obsidian-iconize/icon-map.json` (roles, steps, requests, or any custom registry). Re-runnable. Writes back JSON with stable formatting. Use when the resolver misses a role/step/etc. — this skill is the canonical way to seed the missing registry entry without hand-editing."
allowed-tools: Read, Write, Edit, Bash(mkdir -p *), Bash(git rev-parse*), Bash(date *), AskUserQuestion
argument-hint: "[registry-name] — e.g. roles | steps | requests.classification | requests.status_color"
---

# Configure iconize-sync icon-map

Reads the vault's local `.claude/obsidian-iconize/icon-map.json` and walks the
user through adding / editing / removing registry entries via wizard-style
prompts.

## Prerequisite

Run `lazy-obsidian.iconize-install` first. This skill only runs against an
existing local icon-map.

## Flow

### Step 1 — Locate icon-map

```
<repo-root>/.claude/obsidian-iconize/icon-map.json
```

Abort with a helpful message if missing.

### Step 2 — Pick registry (one AskUserQuestion)

Enumerate top-level registry names present in `registries` (plus allow
nested dotted paths like `requests.classification`). Ask the user which to
edit. Options: each registry path + "add new registry" + "exit".

If "add new registry" → ask for registry name (free-text via `AskUserQuestion`
with an "Other" answer), then branch to Step 3 with an empty registry.

### Step 3 — Pick action (one AskUserQuestion)

Options: **add** / **edit** / **remove** / **back**.

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

### Step 5 — Write back

Rewrite `icon-map.json` with `json.dumps(..., indent=2, ensure_ascii=False) + "\n"`.
Preserve any top-level keys the skill didn't touch (`matchers`, `version`,
`stage_colors`).

### Step 6 — Loop or exit

One `AskUserQuestion`: **continue** / **exit**. Continue returns to Step 2.

### Step 7 — Log the run

`./.logs/claude/lazy-obsidian.iconize-configure/YYYY-MM-DD_HH-MM-SS.md`.
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
