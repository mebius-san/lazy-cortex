---
name: lazy-obsidian.iconize-config
description: "Use when the iconize resolver misses a value — a role, step, or request status with no icon — or when the operator wants to change or drop one. Wizard over the vault's local `.claude/iconize/obsidian-icon-map.json`; the canonical way to seed a registry entry instead of hand-editing that JSON. Requires `lazy-obsidian.iconize-install` to have run first."
allowed-tools: Read, Write, Edit, Bash(mkdir -p *), Bash(git rev-parse*), Bash(date *), AskUserQuestion, Agent
argument-hint: "[registry-name] — e.g. roles | steps | requests.classification | requests.status_color"
---
# Configure iconize-sync icon-map

Reads the vault's local `.claude/iconize/obsidian-icon-map.json` and walks the user through adding / editing / removing registry entries via wizard-style prompts.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate icon-map`
   - `Step 2 — Pick registry`
   - `Step 3 — Pick action`
   - `Step 4 — Apply action (add / edit / remove)`
   - `Step 5 — Write back`
   - `Step 6 — Loop or exit / Report`
   - `Step 7 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Prerequisite

Run `lazy-obsidian.iconize-install` first. This skill only runs against an existing local icon-map.

## Step 1 — Locate icon-map

```
<repo-root>/.claude/iconize/obsidian-icon-map.json
```

Abort with a helpful message if missing.

## Step 2 — Pick registry (one AskUserQuestion)

Enumerate top-level registry names present in `registries` (plus allow nested dotted paths like `requests.classification`).

```
Context (print before asking):
- Where: /lazy-obsidian.iconize-config · Step 2 — Pick registry; target <repo-root>/.claude/iconize/obsidian-icon-map.json
- Found: registries on record: <path (N keys)> per registry, or none
- Why asking: which registry to edit is the operator's intent
- Answers: `<registry path>` — opens it for Step 3, nothing written; `add new registry` — asks for a name, then Step 3 with an empty registry; `exit` — stop and Report
AskUserQuestion: header "Registry", question "Which registry in <repo-root>/.claude/iconize/obsidian-icon-map.json do you want to edit?", options: one per registry path (description `<N> keys`), `add new registry`, `exit`.
```

If "add new registry":

```
Context (print before asking):
- Where: Step 2 — new registry name; same icon-map
- Found: registry paths already on record: <list>
- Why asking: the name is what matchers and the resolver address the registry by
- Answers: free text — a new empty registry under `registries.<name>` (a dotted name nests), written in Step 5; a name already on record re-asks
AskUserQuestion: header "New registry", question "Name for the new registry in obsidian-icon-map.json (top-level like `roles`, or dotted like `requests.classification`)?", free text via an "Other" answer.
```

Then branch to Step 3 with an empty registry.

## Step 3 — Pick action (one AskUserQuestion)

```
Context (print before asking):
- Where: Step 3 — Pick action; target registry `<registry path>` in obsidian-icon-map.json
- Found: <N> keys on record: <keys, or empty>
- Why asking: add / edit / remove is the operator's intent
- Answers: `add` — Step 4a, a new key; `edit` — Step 4b, change an existing key's icon; `remove` — Step 4c, drop a key after confirmation; `back` — return to Step 2; nothing written until Step 5
AskUserQuestion: header "Action", question "What do you want to do in registry `<registry path>`?", options `add`, `edit`, `remove`, `back` with those descriptions.
```

## Step 4 — Apply action (add / edit / remove)

### Step 4a — Add

One `AskUserQuestion` per field:
1. Key name:

   ```
   Context (print before asking):
   - Where: Step 4a — Add, key name; target `registries.<registry path>`
   - Found: keys on record: <list, or empty>
   - Why asking: the key is the frontmatter value the resolver matches
   - Answers: free text — becomes the new key; a key already on record re-asks; written in Step 5
   AskUserQuestion: header "Key name", question "New key for registry `<registry path>` (the value the resolver matches, e.g. `blocker`)?", free text via an "Other" answer.
   ```
2. `iconName`:

   ```
   Context (print before asking):
   - Where: Step 4a — Add, `iconName`; target `registries.<registry path>.<key>`
   - Found: key `<key>` accepted; no icon yet
   - Why asking: the icon is content only the operator can pick
   - Answers: free text — Lucide PascalCase with `Li` prefix, or an emoji; validated by the worker, a rejected value re-asks; written in Step 5
   AskUserQuestion: header "Icon", question "Icon for `<registry path>.<key>` (Lucide PascalCase with `Li` prefix, or an emoji)?", free text via an "Other" answer.
   ```
3. `iconColor`:

   ```
   Context (print before asking):
   - Where: Step 4a — Add, `iconColor`; target `registries.<registry path>.<key>`
   - Found: icon `<iconName>` accepted
   - Why asking: colour is optional content
   - Answers: `none` — monochrome, no `iconColor` key written; free text — a colour value, validated by the worker; written in Step 5
   AskUserQuestion: header "Icon colour", question "Colour for `<registry path>.<key>`, or `none` for monochrome?", options `none` — "monochrome; no iconColor key", plus free text via an "Other" answer.
   ```

Validate with the worker's validators (shell out to `python3 ${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py --validate-entry ...` — see Task 11b below for this helper flag).

### Step 4b — Edit

```
Context (print before asking):
- Where: Step 4b — Edit, pick key; target `registries.<registry path>`
- Found: keys on record: <key → iconName / iconColor> per key
- Why asking: which entry to change is the operator's intent
- Answers: `<key>` — its `iconName` / `iconColor` are re-collected per Step 4a (fields 2–3); written in Step 5
AskUserQuestion: header "Edit key", question "Which key in registry `<registry path>` do you want to edit?", options: one per key, description = its current `iconName` / `iconColor`.
```

Then edit iconName/iconColor per Step 4a.

### Step 4c — Remove

```
Context (print before asking):
- Where: Step 4c — Remove, pick key; target `registries.<registry path>`
- Found: keys on record: <key → iconName / iconColor> per key
- Why asking: which entry to drop is the operator's intent
- Answers: `<key>` — selected for removal; nothing written until confirmed below
AskUserQuestion: header "Remove key", question "Which key in registry `<registry path>` do you want to remove?", options: one per key, description = its current `iconName` / `iconColor`.
```

Confirm via a second `AskUserQuestion`:

```
Context (print before asking):
- Where: Step 4c — Remove, confirm; target `registries.<registry path>.<key>`
- Found: `<key>` → `<iconName>` / `<iconColor>`
- Why asking: removal is destructive — the resolver has no icon for that value from the next reconcile on
- Answers: `confirm-remove` — entry deleted in Step 5; `cancel` — nothing changes, back to Step 3
AskUserQuestion: header "Confirm removal", question "Remove `<key>` from registry `<registry path>` in obsidian-icon-map.json?", options `confirm-remove` — "delete the entry", `cancel` — "keep it".
```

## Step 5 — Write back

Rewrite `obsidian-icon-map.json` with `json.dumps(..., indent=2, ensure_ascii=False) + "\n"`. Preserve any top-level keys the skill didn't touch (`matchers`, `version`, `stage_colors`).

## Step 6 — Loop or exit / Report

```
Context (print before asking):
- Where: Step 6 — Loop or exit; target obsidian-icon-map.json
- Found: this run so far: <added / edited / removed entries>, written in Step 5
- Why asking: whether there is more to change is the operator's intent
- Answers: `continue` — back to Step 2; `exit` — Report, then Step 7
AskUserQuestion: header "More changes?", question "Change another entry in obsidian-icon-map.json, or exit?", options `continue` — "pick another registry", `exit` — "print the report and log the run".
```

On exit, print one report line per task in the canonical list above, each with an outcome word (e.g. `located`, `picked`, `added`, `edited`, `removed`, `written`, `exited`).

## Step 7 — Log the run

`./.logs/claude/lazy-obsidian.iconize-config/YYYY-MM-DD_HH-MM-SS.md`. Record every mutation (before/after diff per entry) in the **Actions** section.

## Wizard discipline

One `AskUserQuestion` per decision. Never bundle multiple fields into a single prompt. Validate inputs before persisting.

## Failure modes

- **`/lazy-obsidian.iconize-config` aborts: icon-map not found** — `.claude/iconize/obsidian-icon-map.json` is missing → run `/lazy-obsidian.iconize-install` first to scaffold the icon-map, then re-run.

## Notes

- This skill only touches registries. To change matcher logic, edit `obsidian-icon-map.json` by hand — matchers are structural and benefit from seeing the whole file at once.
- After any registry change, remind the user to run `lazy-obsidian.iconize-sync reconcile` so `data.json` picks up the new entries.
