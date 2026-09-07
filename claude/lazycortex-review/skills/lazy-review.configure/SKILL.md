---
name: lazy-review.configure
description: "Run when the operator wants a new kind of document to go through review, wants to change which paths a review class matches, or wants to reassign who writes / validates / closes out / narrates it. Wizard over `review.classes` in `.claude/lazy.settings.json`, one question per turn via AskUserQuestion; read-first, so an already-configured class is re-validated without a single prompt. Requires `/lazy-review.install` to have run."
allowed-tools: Read, Edit, Write, AskUserQuestion, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Agent
---
# lazy-review.configure

Interactive wizard. Adds (or appends to) `review.classes` in `.claude/lazy.settings.json` for the consumer's first or next document class — globs, writer groups, sections, marker style — all of which are genuine project config that cannot be derived. The wizard is **read-first**: every value already persisted in the settings file is honoured silently and the matching question is skipped; only values with nothing on record are asked. Calls the configure pipeline one question at a time via `AskUserQuestion`.

Prerequisite: `/lazy-review.install` has run (the settings file exists).

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Verify install + load settings`
   - `Phase 2 — Collect class paths`
   - `Phase 3 — Collect writer groups`
   - `Phase 4 — Pick edit_marker_style`
   - `Phase 5 — Write back + run /lazy-review.audit`
   - `Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** Outcomes: `verified` / `collected` / `read-from-record` / `picked` / `written` / `audited` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Read-first principle (applies to every question below)

Every collecting phase first inspects the in-memory settings loaded in Phase 1. If the value the phase would ask for is **already persisted**, skip the `AskUserQuestion` and reuse the recorded value silently — state `read-from-record`. Ask **only** when nothing is on record. This makes the wizard idempotent and quiet on re-run: a fully-configured class is re-validated and re-audited without a single prompt. The questions below collect genuine project config (which globs enter the review loop, which experts play which role, where sections sit, which marker style) — none of it is derivable, so the wizard keeps every question, but each is gated on the absence of a persisted answer.

## Phase 1 — Verify install + load settings

`Read` `.claude/lazy.settings.json`. If absent, abort with the message *"run `/lazy-review.install` first"* and stop. Otherwise hold the parsed object in memory for the wizard.

Outcome: `verified`.

## Phase 2 — Collect class paths

Every class entry carries a `class` identity token — a short unique slug (`design`, `request`, `meeting-notes`) tooling addresses the entry by; globs stay routing-only. Read-first: an entry the operator means to extend is found by its token. For a new class, derive the token from the document kind and confirm it in the same question as the globs; refuse a token another entry already carries.

If `review.classes` already holds the class (matched by token), reuse its `paths` silently (read-first). Otherwise:

```
Context (print before asking):
- Where: /lazy-review.configure · Phase 2 — Collect class paths; target `.claude/lazy.settings.json[review.classes]` in <repo-root>
- Found: no class entry for `<token>`; tokens already on record: <list, or none>
- Why asking: which globs enter the review loop, and the slug tooling addresses the class by, are project config nothing can derive
- Answers: free text `<globs>, <token>` — globs split on commas and trimmed into `paths`, slug into `class`; persisted in Phase 5; never re-asked while the entry exists; a token already on record re-asks
AskUserQuestion: header "Class paths", question "Which glob(s) does the new review class in <repo-root> match (comma-separated, e.g. `requests/*.md, docs/specs/*.md`), and what identity token names it (e.g. `design`)?", free text via an "Other" answer.
```

Outcome: `collected` (asked) or `read-from-record` (reused a persisted class's paths).

## Phase 3 — Collect writer groups

Main writers and section writers are collected separately. Each question block is its own `AskUserQuestion` call, and each is skipped when the value is already present in the in-memory settings (read-first). This phase is the authoritative source of each writer's `role` value — the free-form string `lazy-review.doc-review-protocol` transports verbatim into `request.json.role` without assigning it semantics of its own.

### 3a — Main writers

If `experts.main` is already populated — reuse it silently (read-first). Otherwise:

```
Context (print before asking):
- Where: Phase 3a — Main writers; target `review.classes[<token>].experts.main`
- Found: `experts.main` absent for `<token>`; registry experts in the root `experts:` catalog: <names>
- Why asking: which experts author this document kind is project config
- Answers: each selected expert — appended in selection order as `{"name", "repo": ".", "role": "main"}`; persisted in Phase 5; never re-asked while populated
AskUserQuestion: header "Main writers", question "Which registered experts are the main writers of `<token>` documents (several allowed; they run as a chain, in the order picked)?", multi-select over the registry, each option's description from the catalog entry.
```

Add to the in-memory settings: `experts.main = [{"name": ..., "repo": ".", "role": "main"}]` (one object per selected expert profile; `role` is a free-form string the agent receives in `request.json.role`).

### 3b — Sections (loop)

If section writers (`experts.validation` / `experts.terminal`) are already recorded for this class — reuse them silently and skip the loop (read-first). Otherwise loop over sections — every iteration strictly through separate `AskUserQuestion` calls:

1. Ask whether to add a section:

   ```
   Context (print before asking):
   - Where: Phase 3b — Sections; target `review.classes[<token>].experts.validation` / `.terminal`
   - Found: sections collected so far this run: <section-ids, or none>
   - Why asking: how many post-approve sections the class carries is project config
   - Answers: `Add` — collect one more section (steps a–f), nothing written yet; `Done` — exit the loop; all sections are persisted in Phase 5; re-asked after every added section
   AskUserQuestion: header "Sections", question "Add another post-approve section to the `<token>` class?", options `Add` — "define one more validation or terminal section", `Done` — "no more sections".
   ```
2. On "Done" — exit the loop.
3. On "Add":
   a. Section type:

      ```
      Context (print before asking):
      - Where: Phase 3b — section type; target `experts.<umbrella>` of `<token>`
      - Found: section <n> of this class; umbrellas already in use: <validation / terminal / none>
      - Why asking: whether the section blocks finalization is a class-design decision
      - Answers: `validation` — stored under `experts.validation`; `terminal` — stored under `experts.terminal`; persisted in Phase 5; never re-asked for this section
      AskUserQuestion: header "Section type", question "Is the new section on the `<token>` class a `validation` or a `terminal` section?", options:
      - `validation` — post-approve check; a section with content blocks finalize (revert-to-main); erased at finalization.
      - `terminal` — post-approve operator choice; does not block finalize; survives finalization.
      ```
   b. Section-id. Validate in place against `^[a-z][a-z0-9_-]*$`; re-ask on a mismatch. Check section-id uniqueness within the class (across both umbrellas — `validation` and `terminal`); re-ask on a duplicate.

      ```
      Context (print before asking):
      - Where: Phase 3b — section-id; target `experts.<umbrella>.<section-id>`
      - Found: ids already taken on `<token>` (both umbrellas): <list, or none>
      - Why asking: the stable identifier tooling addresses the section by cannot be derived
      - Answers: free text — becomes the key under `experts.<umbrella>`; a mismatch or duplicate re-asks; persisted in Phase 5
      AskUserQuestion: header "Section id", question "Section-id for the new `<umbrella>` section on `<token>` (stable identifier, format `^[a-z][a-z0-9_-]*$`, e.g. `final_check` or `routing`)?", free text via an "Other" answer.
      ```
   c. H1 heading:

      ```
      Context (print before asking):
      - Where: Phase 3b — heading; target `experts.<umbrella>.<section-id>.section`
      - Found: section-id `<section-id>` accepted; no heading on record
      - Why asking: the heading is the rendered title of the section in every `<token>` document
      - Answers: free text, any string — stored verbatim as `section`; persisted in Phase 5
      AskUserQuestion: header "Section heading", question "H1 heading for section `<section-id>` of the `<token>` class (any string, e.g. `Final check` or `Routing`)?", free text via an "Other" answer.
      ```
   d. Position:

      ```
      Context (print before asking):
      - Where: Phase 3b — position; target `experts.<umbrella>.<section-id>.position`
      - Found: heading `<heading>` recorded; no position on record
      - Why asking: where the section renders relative to the operator's free body is layout the class owns
      - Answers: `top` — `position: top`; `bottom` — `position: bottom`; persisted in Phase 5
      AskUserQuestion: header "Section position", question "Where does section `<section-id>` (`<heading>`) sit relative to the operator's free body in `<token>` documents?", options:
      - `top` — the section renders ABOVE the free body (after the banner/status).
      - `bottom` — the section renders BELOW the free body (before `# History`).
      ```
   e. Writer:

      ```
      Context (print before asking):
      - Where: Phase 3b — section writer; target `experts.<umbrella>.<section-id>.name`
      - Found: registry experts: <names>; main writers of `<token>`: <names>
      - Why asking: which expert owns this section is project config
      - Answers: the selected expert — stored as `name` with `repo: "."` and `role: <umbrella>`; persisted in Phase 5; never re-asked for this section
      AskUserQuestion: header "Section writer", question "Which registered expert writes into section `<section-id>` (`<heading>`) of the `<token>` class?", single-select over the registry, each option's description from the catalog entry.
      ```
   f. Add to the in-memory settings: `experts.<umbrella>.<section-id> = {"name": ..., "repo": ".", "role": <umbrella>, "section": <heading from step c>, "position": <top|bottom>}` (`role` defaults to the umbrella name — `validation` or `terminal`; operators running specialized persona routing may replace it with any other string — the agent receives it in `request.json.role`).
4. Goto 1.

Outcome: `collected` (asked) or `read-from-record` (every writer group reused from a persisted class).

### Class-level `protocols` (not asked, preserved)

A class entry may carry an optional `protocols` list — plugin-namespaced reference ids (e.g. `lazycortex-specs:lazy-spec.expert-signals-protocol`) the review coordinator folds into every writer dispatch for documents of that class, on top of the doc-review protocol and the `review.protocols` section-level defaults. The wizard never asks for it: the list is seeded by the plugin that owns the document kind (its install skill), and read-first preserves whatever is on record.

## Phase 4 — Pick edit_marker_style

If `review.edit_marker_style` is already recorded — reuse it silently (read-first). Otherwise:

```
Context (print before asking):
- Where: /lazy-review.configure · Phase 4 — Pick edit_marker_style; target `.claude/lazy.settings.json[review.edit_marker_style]` in <repo-root>
- Found: `review.edit_marker_style` absent
- Why asking: how main writers mark prose edits inside reviewed documents is a vault-wide operator preference
- Answers: the chosen name is written to `review.edit_marker_style` in Phase 5, applies to every class, and is pinned per document at review entry; never re-asked while set
AskUserQuestion: header "Edit markers", question "Which edit-marker style should expert edits use in reviewed documents of <repo-root>?", options:
- `simple` — inline `~~del~~`, `==add==`, `%%note%%`.
- `diff` — every mutation inside a fenced diff block with `-` / `+` line prefixes.
- `criticmarkup` — inline `{++add++}`, `{--del--}`, `{~~old~>new~~}`, `{>>note<<}`.
- `html` — inline `<ins>`, `<del>`, `<mark>`, `<!-- note -->`.
```

Write the chosen value into `review.edit_marker_style`.

Outcome: `picked` (asked) or `read-from-record` (reused the persisted style).

## Phase 5 — Write back + run /lazy-review.audit

Serialize the updated settings via `Write` to `.claude/lazy.settings.json`. Then widen the coordinator's watch scope so this class's documents actually reach it — but only when `routines["lazy-review.coordinator-watch"]` is present. The routine may be absent on a repo where `/lazy-review.install` has not run yet; if it is missing, skip this normalization silently — there is no watch to feed.

The watch carries **one** pathspec, not a list — core's git-watch takes a single `path_filter` — so the scope is one directory root that must contain every class:

1. Take each of this class's `paths` globs in its REPO-ROOT-RELATIVE form (a glob relative to a content root, e.g. a spec-plugin class relative to `spec.vault_root`, gets that root prepended first — without it the pathspec matches nothing) and reduce it to its longest leading wildcard-free directory prefix. A literal file path reduces to its parent dir; a glob whose first component already wildcards reduces to nothing.
2. The new `review.watch_root` is the common directory of those prefixes and the current `review.watch_root`. Any prefix reducing to nothing, or roots sharing no common directory, makes it `.` (the whole repo).
3. Write `routines["lazy-review.coordinator-watch"].path_filter` as `:(glob)<watch_root>/**/*.md`, collapsing to `:(glob)**/*.md` when the root is `.`.

Class `paths` stay precise — they are the dispatch-time routing the broad watch deliberately delegates to, and the routine's `review_active` frontmatter filter is what keeps the broad pathspec cheap. Widening is monotonic and idempotent: a root already covering the class changes nothing, and the scope is never narrowed (that would silently drop a class configured earlier). Then invoke `/lazy-review.audit` and surface its findings.

Outcome: `written`.

## Report

One line per task with its outcome word, followed by `configured: <paths>; experts={main: <count>, validation: <count>, terminal: <count>}; style=<style>; watch_root=<root>; audit=<level>`.

## Failure modes

- **Phase 1 aborts on missing settings** — operator hasn't installed → run `/lazy-review.install` first, then re-run.
- **section-id fails validation loop** — operator keeps entering a string that doesn't match `^[a-z][a-z0-9_-]*$` or collides with an existing id → wizard re-asks until a valid unique id is provided.
- **Phase 5 audit reports FAIL** — wizard wrote inconsistent state (e.g. section-id in `validation` or `terminal` not matching the allowed alphabet, or expert name missing from top-level experts dict) → re-enter the wizard and complete the missing pieces.
