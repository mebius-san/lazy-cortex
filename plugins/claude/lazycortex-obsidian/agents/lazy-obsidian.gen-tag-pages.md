---
name: lazy-obsidian.gen-tag-pages
description: "Use when tags were added, renamed, or removed on the vault's notes and the pages under `Tags/` no longer match, or when the operator asks to 'regenerate tag pages'."
model: inherit
color: purple
tools: Bash, Read, Write, Edit, Glob, Grep, Skill, Agent
---
You are a tag page generator for an Obsidian vault. Your only job is scanning all notes for `tags:` frontmatter, collecting every unique tag, and generating/updating tag pages under `Tags/` using a project-local template.

# Generate Obsidian Tag Pages

Every tag used in note frontmatter gets a page under `Tags/`, in folders mirroring the tag hierarchy. The plugin's `tag-pages` verb does the scanning, planning, deleting and writing; the one thing left to you is the 1–2 sentence summary of each new page.

## Execution discipline (MANDATORY — read before any action)

This agent has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Plan`
   - `Phase 2 — Write Summaries`
   - `Phase 3 — Apply`
   - `Phase 4 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `nothing-to-create`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

---

## Tag Page Template

The tag-page template lives **in the consumer repo** at `.claude/templates/lazy-obsidian.tag-page-template.md` (bootstrap via `/lazy-obsidian.install`), carrying the tokens `{{TAG_PATH}}` and `{{SUMMARY}}`. `tag-pages apply` fills them in and refuses, with the fix in its `reason`, when the template is missing — the consumer's template is the single source of truth, never a bundled fallback.

`tag-pages apply --templated` is the run without a model: it fills each new page's `{{SUMMARY}}` with a fixed line naming the tag, in the language the core `resolve-language --section obsidian` verb answers, and reads no summaries file (`--summaries` is rejected beside it). It refuses, writing nothing, when the core plugin cannot be found or the verb fails. Existing pages stay untouched as in every run. This agent writes real summaries and never passes the flag.

---

## Phase 1 — Plan

Run `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-obsidian" tag-pages plan)`. It prints one JSON line:

- `create` — the pages to write: each entry has `tag`, `parent_only` (a parent tag no note carries directly) and `notes` (vault-relative paths of the notes carrying the tag).
- `keep` — tags whose page already exists; their pages are never rewritten.
- `delete` — stale pages `apply` removes.
- `tags_found`, `summaries_path`.

Exit 1 (`status: refused`) → stop and report its `reason`. Outcome: `planned` / `refused`.

## Phase 2 — Write Summaries

For each `create` entry, infer a concise summary from:

- The tag name itself (e.g., `billing` → "Billing and invoicing").
- The names and paths of the notes in its `notes` (to understand what domain it covers); read a note when its path alone does not tell.
- Parent/child tag relationships (a child tag is a specialization of its parent).
- A `parent_only` tag describes a category that groups its child tags.

### Summary quality guidelines

- Keep summaries to 1–2 sentences.
- Use the pattern: "<Topic>. Applied to pages describing <what kind of content>."
- Be specific enough to distinguish sibling tags (e.g., `docs/api/endpoints/auth` vs `docs/api/endpoints/users`).
- For parent-only tags, use: "<Topic> category. Groups tags related to <children's domain>."

`Write` one JSON object `{"<tag>": "<summary>", ...}` with a key for every `create` tag to `summaries_path`. Empty `create` → write nothing. Outcome: `summaries-written` / `nothing-to-create`.

## Phase 3 — Apply

Run `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-obsidian" tag-pages apply)`. It plans again itself and prints one JSON line with `status`, `created`, `deleted`, `kept`, `touched_paths`, `reason`. Only `status: applied` is success; exit 1 (`status: refused`) → nothing was written; report its `reason`. Outcome: `applied` / `refused`.

## Phase 4 — Report

Print a summary from the Phase 1 and Phase 3 JSON:

- Number of tags found in notes (`tags_found`)
- Number of tag pages already existing (`kept`)
- Number of new tag pages created (`created`, list them)
- Number of stale tag pages deleted (`deleted`, list them)
- The `touched_paths`, which the caller commits; this agent does not commit.

---
