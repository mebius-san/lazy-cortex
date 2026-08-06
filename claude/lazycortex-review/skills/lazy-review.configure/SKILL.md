---
name: lazy-review.configure
description: "Run when the operator wants a new kind of document to go through review, wants to change which paths a review class matches, or wants to reassign who writes / validates / closes out / narrates it. Wizard over `review.classes` in `.claude/lazy.settings.json`, one question per turn via AskUserQuestion; read-first, so an already-configured class is re-validated without a single prompt. Requires `/lazy-review.install` to have run."
allowed-tools: Read, Edit, Write, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
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

If `review.classes` already holds a class whose paths the operator means to extend, reuse its `paths` silently (read-first). Otherwise `AskUserQuestion`: *"What glob(s) does this class match?"* — operator types a comma-separated list (e.g. `requests/*.md, docs/specs/*.md`). Split on commas and trim.

Outcome: `collected` (asked) or `read-from-record` (reused a persisted class's paths).

## Phase 3 — Collect writer groups

Pipeline phases (main writers and the historian) and section writers are collected separately. Each question block is its own `AskUserQuestion` call, and each is skipped when the value is already present in the in-memory settings (read-first).

### 3a — Main writers

If `experts.main` is already populated — reuse it silently (read-first). Otherwise `AskUserQuestion` (multi-select over the expert registry in the root `experts:` catalog; preserve order): *"Who are the document's main writers (several allowed; they run as a chain)?"*

Add to the in-memory settings: `experts.main = [{"name": ..., "repo": ".", "role": "main"}]` (one object per selected expert profile; `role` is a free-form string the agent receives in `request.json.role`).

### 3b — Historian

If `experts.history` is already recorded — reuse it silently (read-first). Otherwise `AskUserQuestion` (single-select over the registry; default `review.historian`): *"Who is the historian (writes the # History section)?"*

Add: `experts.history = {"name": ...}`.

### 3c — Sections (loop)

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

## Phase 4 — Pick edit_marker_style

If `review.edit_marker_style` is already recorded — reuse it silently (read-first). Otherwise `AskUserQuestion`: four options — `simple`, `diff`, `criticmarkup`, `html`. Write the chosen value into `review.edit_marker_style`.

Outcome: `picked` (asked) or `read-from-record` (reused the persisted style).

## Phase 5 — Write back + run /lazy-review.audit

Serialize the updated settings via `Write` to `.claude/lazy.settings.json`. Then normalize the `lazy-review.scan` routine — but only when the routine is present. The daemon-gated routine may be absent (a daemon-disabled project, per `/lazy-review.install` Step 2 outcome `skipped-daemon-disabled`); if `routines["lazy-review.scan"]` is missing, skip this normalization silently — there is no scan loop to feed. When present: (1) coarsen each of this class's `paths` globs — take the longest leading wildcard-free directory prefix; if the remaining tail is exactly `*.md`, keep the glob as-is; otherwise emit `<prefix>/**/*.md` (a literal file path coarsens via its parent dir; no literal prefix → `**/*.md`) — and union the coarse masks into the routine's `paths`. The emitted `**` mask is matched anchored at the repo root, so coarsen the REPO-ROOT-RELATIVE form of the glob — if this class's `paths` globs are relative to a content root (e.g. spec-plugin classes are relative to `spec.vault_root`), prepend that root before taking the prefix; a mask without its content-root prefix matches nothing; (2) dedupe and drop any mask subsumed by a broader one (`<p>/**/*.md` covers every mask whose prefix sits under `<p>` and every legacy filename-suffixed mask under `<p>` — remove those); (3) inside `filter.frontmatter` set `review_active` to `{"in": [true], "not_in": []}` (drop the legacy `null` leg — only opted-in files spawn a per-file dispatch; opt-in stamps `review_active: true` atomically and non-active files are no-op skips); (4) set `interval_sec` to `60` when it still carries the legacy `5` (coarse scans run at minute cadence; an operator-chosen value other than 5 stays untouched). Class `paths` stay precise: they are the dispatch-time routing that the coarse sieve deliberately delegates to. This rewrite is idempotent — re-running it on an already-normalized routine changes nothing. Then invoke `/lazy-review.audit` and surface its findings.

Outcome: `written`.

## Report

One line per task with its outcome word, followed by `configured: <paths>; experts={main: <count>, history: <count>, validation: <count>, terminal: <count>}; style=<style>; audit=<level>`.

## Failure modes

- **Phase 1 aborts on missing settings** — operator hasn't installed → run `/lazy-review.install` first, then re-run.
- **section-id fails validation loop** — operator keeps entering a string that doesn't match `^[a-z][a-z0-9_-]*$` or collides with an existing id → wizard re-asks until a valid unique id is provided.
- **Phase 5 audit reports FAIL** — wizard wrote inconsistent state (e.g. section-id in `validation` or `terminal` not matching the allowed alphabet, or expert name missing from top-level experts dict) → re-enter the wizard and complete the missing pieces.
