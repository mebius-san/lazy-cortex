---
name: lazy-review.configure
description: "Run when the operator wants a new kind of document to go through review, wants to change which paths a review class matches, or wants to reassign who writes / validates / closes out / narrates it. Wizard over `review.classes` in `.claude/lazy.settings.json`, one question per turn via AskUserQuestion; read-first, so an already-configured class is re-validated without a single prompt. Requires `/lazy-review.install` to have run."
allowed-tools: Read, Edit, Write, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Agent
---
# lazy-review.configure

Interactive wizard. Adds (or appends to) `review.classes` in `.claude/lazy.settings.json` for the consumer's first or next document class — globs, writer groups, sections, marker style — all of which are genuine project config that cannot be derived. The wizard is **read-first**: every value already persisted in the settings file is honoured silently and the matching question is skipped; only values with nothing on record are asked. Calls the configure pipeline one question at a time via `AskUserQuestion`.

Prerequisite: `/lazy-review.install` has run (the settings file exists).

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Verify install + load settings`
   - `Phase 2 — Collect class paths`
   - `Phase 3 — Collect writer groups`
   - `Phase 4 — Pick edit_marker_style`
   - `Phase 5 — Write back + run /lazy-review.audit`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `verified` / `collected` / `read-from-record` / `picked` / `written` / `audited` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Read-first principle (applies to every question below)

Every collecting phase first inspects the in-memory settings loaded in Phase 1. If the value the phase would ask for is **already persisted**, skip the `AskUserQuestion` and reuse the recorded value silently — state `read-from-record`. Ask **only** when nothing is on record. This makes the wizard idempotent and quiet on re-run: a fully-configured class is re-validated and re-audited without a single prompt. The questions below collect genuine project config (which globs enter the review loop, which experts play which role, where sections sit, which marker style) — none of it is derivable, so the wizard keeps every question, but each is gated on the absence of a persisted answer.

## Phase 1 — Verify install + load settings

`Read` `.claude/lazy.settings.json`. If absent, abort with the message *"run `/lazy-review.install` first"* and stop. Otherwise hold the parsed object in memory for the wizard.

Outcome: `verified`.

## Phase 2 — Collect class paths

Every class entry carries a `class` identity token — a short unique slug (`design`, `request`, `meeting-notes`) tooling addresses the entry by; globs stay routing-only. Read-first: an entry the operator means to extend is found by its token. For a new class, derive the token from the document kind and confirm it in the same question as the globs; refuse a token another entry already carries.

If `review.classes` already holds the class (matched by token), reuse its `paths` silently (read-first). Otherwise `AskUserQuestion`: *"What glob(s) does this class match, and what identity token names it?"* — operator types a comma-separated glob list (e.g. `requests/*.md, docs/specs/*.md`) and a slug. Split globs on commas and trim.

Outcome: `collected` (asked) or `read-from-record` (reused a persisted class's paths).

## Phase 3 — Collect writer groups

Main writers and section writers are collected separately. Each question block is its own `AskUserQuestion` call, and each is skipped when the value is already present in the in-memory settings (read-first). This phase is the authoritative source of each writer's `role` value — the free-form string `lazy-review.doc-review-protocol` transports verbatim into `request.json.role` without assigning it semantics of its own.

### 3a — Main writers

If `experts.main` is already populated — reuse it silently (read-first). Otherwise `AskUserQuestion` (multi-select over the expert registry in the root `experts:` catalog; preserve order): *"Who are the document's main writers (several allowed; they run as a chain)?"*

Add to the in-memory settings: `experts.main = [{"name": ..., "repo": ".", "role": "main"}]` (one object per selected expert profile; `role` is a free-form string the agent receives in `request.json.role`).

### 3b — Sections (loop)

If section writers (`experts.validation` / `experts.terminal`) are already recorded for this class — reuse them silently and skip the loop (read-first). Otherwise loop over sections — every iteration strictly through separate `AskUserQuestion` calls:

1. `AskUserQuestion`: *"Add another section?"* Options: "Add", "Done".
2. On "Done" — exit the loop.
3. On "Add":
   a. `AskUserQuestion`: *"Which type is this section?"* Options:
      - **`validation`** — post-approve check; a section with content blocks finalize (revert-to-main); erased at finalization.
      - **`terminal`** — post-approve operator choice; does not block finalize; survives finalization.
   b. `AskUserQuestion` (free text): *"Enter the section-id (stable identifier, format `^[a-z][a-z0-9_-]*$`, e.g. `final_check` or `routing`)"*. Validate in place against `^[a-z][a-z0-9_-]*$`; re-ask on a mismatch. Check section-id uniqueness within the class (across both umbrellas — `validation` and `terminal`); re-ask on a duplicate.
   c. `AskUserQuestion` (free text): *"H1 heading for this section (any string, e.g. `Final check` or `Routing`)"*.
   d. `AskUserQuestion`: *"Where does the section sit relative to the operator's free body?"* Options:
      - **`top`** — the section renders ABOVE the free body (after the banner/status).
      - **`bottom`** — the section renders BELOW the free body (before `# History`).
   e. `AskUserQuestion` (single-select over the registry): *"Who writes into this section?"*
   f. Add to the in-memory settings: `experts.<umbrella>.<section-id> = {"name": ..., "repo": ".", "role": <umbrella>, "section": <heading from step c>, "position": <top|bottom>}` (`role` defaults to the umbrella name — `validation` or `terminal`; operators running specialized persona routing may replace it with any other string — the agent receives it in `request.json.role`).
4. Goto 1.

Outcome: `collected` (asked) or `read-from-record` (every writer group reused from a persisted class).

### Class-level `protocols` (not asked, preserved)

A class entry may carry an optional `protocols` list — plugin-namespaced reference ids (e.g. `lazycortex-specs:lazy-spec.expert-signals-protocol`) the review coordinator folds into every writer dispatch for documents of that class, on top of the doc-review protocol and the `review.protocols` section-level defaults. The wizard never asks for it: the list is seeded by the plugin that owns the document kind (its install skill), and read-first preserves whatever is on record.

## Phase 4 — Pick edit_marker_style

If `review.edit_marker_style` is already recorded — reuse it silently (read-first). Otherwise `AskUserQuestion`: four options — `simple`, `diff`, `criticmarkup`, `html`. Write the chosen value into `review.edit_marker_style`.

Outcome: `picked` (asked) or `read-from-record` (reused the persisted style).

## Phase 5 — Write back + run /lazy-review.audit

Serialize the updated settings via `Write` to `.claude/lazy.settings.json`. Then widen the coordinator's watch scope so this class's documents actually reach it — but only when `routines["lazy-review.coordinator-watch"]` is present. The daemon-gated routine may be absent (a daemon-disabled project, per `/lazy-review.install` Step 2 outcome `skipped-daemon-disabled`); if it is missing, skip this normalization silently — there is no watch to feed.

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
