---
name: lazy-wiki.configure
description: "Wizard to create or edit a wiki scope in .claude/lazy.settings.json — collects id, path globs, optional exclude_paths, tag_axes, and topics_index. Strict one-question-per-turn via AskUserQuestion."
allowed-tools: Read, Edit, Write, AskUserQuestion, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*)
---
# lazy-wiki.configure

Interactive wizard. Creates or edits a scope entry in `lazy.settings.json[wiki.scopes]` for the current repo. Each field is collected one question at a time via `AskUserQuestion`. This wizard only collects **genuine project config that cannot be derived** — the topics-index path, scope globs, exclude globs, classification axes, and review-skip filter. There is no install-scope question (the wizard always edits the current repo's `lazy.settings.json`) and no environment probe.

**Read-first.** Re-running for an existing scope `id` enters edit mode: each persisted value is read from `lazy.settings.json` first and shown as the current value; pressing Enter keeps it untouched. A field is re-asked only to let the operator change it — never to re-collect a value already on record.

Prerequisite: `/wiki.install` has run (the `wiki` settings section exists).

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Verify install + load settings`
   - `Phase 2 — Collect scope id`
   - `Phase 3 — Collect paths globs`
   - `Phase 4 — Collect exclude_paths`
   - `Phase 5 — Collect tag_axes`
   - `Phase 6 — Collect topics_index`
   - `Phase 7 — Collect filter`
   - `Phase 8 — Write back + log`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `verified` / `collected` / `skipped-per-user-choice` / `written` / `logged` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Verify install + load settings

Run `Bash(git rev-parse --show-toplevel)` to get `<repo-root>`. `Read` `<repo-root>/.claude/lazy.settings.json`. If the file is absent, abort: *"Run `/wiki.install` first."* If the file exists but has no `wiki` key, abort: *"Run `/wiki.install` first — the `wiki` section is missing."* Hold the parsed object in memory.

Outcome: `verified`.

## Phase 2 — Collect scope id

`AskUserQuestion`: *"Scope id (alphanumeric + hyphens/underscores, e.g. `docs` or `codebase`)?"*

Validate: must match `^[a-z][a-z0-9_-]*$`. Re-ask until valid.

If an entry already exists at `wiki.scopes[<id>]`, inform the user: *"Scope `<id>` already exists — entering edit mode. Existing values will be shown; press Enter to keep them."* Hold edit-mode flag.

Outcome: `collected`.

## Phase 3 — Collect paths globs

`AskUserQuestion`:
- New mode: *"Path glob(s) that define this scope — comma-separated (e.g. `docs/**/*.md, src/**/*.py`):"*
- Edit mode: *"Path glob(s) for scope `<id>` (current: `<current paths joined>`; comma-separated, Enter to keep):"*

Split on commas, trim whitespace, discard empty entries. Must have at least one entry; re-ask if empty. Hold as an array.

Outcome: `collected`.

## Phase 4 — Collect exclude_paths

`AskUserQuestion`:
- New mode: *"Exclude glob(s) to omit from the scope — comma-separated, or leave blank for none (e.g. `**/.obsidian/**, **/node_modules/**`):"*
- Edit mode: *"Exclude glob(s) for scope `<id>` (current: `<current exclude_paths joined or "none">`; comma-separated, blank to clear, Enter to keep):"*

Split on commas, trim, discard empty entries. Empty input means no `exclude_paths` key (or clear existing). Hold as an array (may be empty).

Outcome: `collected`.

## Phase 5 — Collect tag_axes

`AskUserQuestion`:
- New mode: *"Tag axes — the closed set of coordinate dimensions for topic classification — comma-separated (e.g. `domain, kind, layer`). An empty list disables topic classification:"*
- Edit mode: *"Tag axes for scope `<id>` (current: `<current tag_axes joined or "none">`; comma-separated, blank to clear, Enter to keep):"*

Split on commas, trim, discard empty entries. Lowercase-normalise each axis slug. Empty input is allowed (means `[]`). Hold as an array.

Outcome: `collected`.

## Phase 6 — Collect topics_index

`AskUserQuestion`:
- New mode: *"Path to the scope's `topics.md` index file, relative to the repo root (e.g. `wiki/docs-topics.md`):"*
- Edit mode: *"Topics index path for scope `<id>` (current: `<current topics_index>`; Enter to keep):"*

Trim whitespace. Must be non-empty; re-ask if blank. The file need not exist yet — it is created on first full scan.

Outcome: `collected`.

## Phase 7 — Collect filter

The per-scope `filter` excludes a node from the wiki on the fly by its frontmatter (the node is not curated, not indexed, not linked while it matches). The common case is standing down on documents currently under review.

`AskUserQuestion`:
- New mode: *"Skip documents that are currently in review? While `review_active: true` (set by lazycortex-review) is present, the document is left out of the wiki and re-enters when review closes. (yes / no)"*
- Edit mode: *"Review-skip filter for scope `<id>` (current: `<"on" when filter.frontmatter.review_active present, else "off">`; yes keeps it on, no clears it):"*

- **yes** → hold the filter object `{ "frontmatter": { "review_active": { "not_in": [true] } } }`.
- **no** → hold no filter (clears any existing one in edit mode).

Default: **yes**. Richer predicates (other frontmatter keys, `in` allow-lists, `folder_note`) follow the same schema as a routine's `filter` block and are hand-editable in `lazy.settings.json` — this wizard only collects the review-skip default.

Outcome: `collected`.

## Phase 8 — Write back + log

Build the scope object:

```json
{
  "paths": ["<...>"],
  "tag_axes": ["<...>"],
  "topics_index": "<path>"
}
```

Add `"exclude_paths"` only if the collected array is non-empty. Add `"filter"` only when Phase 7 held a filter object (review-skip chosen).

Write the updated settings back: set `lazy.settings.json[wiki.scopes][<id>]` to the constructed object. Preserve all other keys. Use `Write` to the target file.

Then log to `./.logs/claude/lazy-wiki.configure/<UTC-timestamp>.md` — two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-wiki.configure)` then `Write` tool. Log frontmatter: `git_sha` (`Bash(git rev-parse HEAD)`), `git_branch` (`Bash(git rev-parse --abbrev-ref HEAD)`), `date` (UTC), `input: "scope_id=<id>"`.

Outcome: `written` and `logged`.

## Report

One line per task in the canonical list, with its outcome word. Summary line: `scope <id> <created|updated>: paths=<count>, tag_axes=[<axes>], topics_index=<path>, filter=<on|off>`.

## Failure modes

- **Phase 1 aborts: "run /wiki.install first"** — `lazy.settings.json` is absent or missing the `wiki` key → run `/wiki.install` then re-run this wizard.
- **Phase 2 re-asks on invalid id** — id doesn't match `^[a-z][a-z0-9_-]*$` → enter a valid slug (lowercase letters, digits, hyphens, underscores; must start with a letter).
- **Phase 3 re-asks on empty paths** — at least one path glob is required; blank input is not accepted.
- **Phase 6 re-asks on blank topics_index** — a relative file path is required (the file need not exist yet).
