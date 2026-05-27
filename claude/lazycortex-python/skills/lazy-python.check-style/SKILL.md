---
name: lazy-python.check-style
description: Six-step Python code/style review — manually-invoked workflow that reads canon + overlay, identifies modified files, runs manual inspection categories, then dispatches chk-py + tst-py to gate.
allowed-tools: Bash, Read, Edit, Glob, Grep
user-invocable: true
---
# Python check-style — six-step review

Deep style + docstring review for modified Python files in the current change set. Invoke after a meaningful edit batch and before committing — the run pairs manual inspection (categories the automated checkers cannot see) with the full `chk-py` + `tst-py` gate, and ends with a re-verify pass. Reads canonical guidelines from `${CLAUDE_PLUGIN_ROOT}/references/` and the project overlay from `${CLAUDE_PROJECT_DIR}/docs/guidelines/` on every run — neither is cached across invocations.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read guidelines`
   - `Step 2 — Identify modified files`
   - `Step 3 — Manual review`
   - `Step 4 — Automated checks`
   - `Step 5 — Fix remaining issues`
   - `Step 6 — Re-verify`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a one-word outcome for it". A no-op step counts only if it emits an explicit outcome (`manual-clean`, `chk-clean`, `no-fixes-needed`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Read guidelines

Read the canonical guidelines from the plugin (always — never skip on the assumption they are loaded):

- `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md`
- `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.documenting-guidelines.md`

Then read the project overlay if it exists (overlay overrides canon on conflict):

- `${CLAUDE_PROJECT_DIR}/docs/guidelines/coding_guidelines.md`
- `${CLAUDE_PROJECT_DIR}/docs/guidelines/documenting_guidelines.md`

Then read the project's `${CLAUDE_PROJECT_DIR}/CLAUDE.md` `## Style` section if present — this is the third overlay layer for project-wide notes that don't belong to a single topic.

Why all three layers every run: dispatched skills do not inherit the main session's loaded rules, and the canon is too long to inline into this body. Re-reading is mandatory; do not skip even when "the rules feel familiar".

Outcome: `guidelines-loaded`.

## Step 2 — Identify modified files

Enumerate Python files in the current change set:

```bash
git diff --name-only HEAD
git diff --name-only HEAD --cached
```

Union the two lists, filter to `*.py`, deduplicate. If the user passed explicit file paths to the skill, use those instead and skip the `git diff` enumeration.

If the set is empty, emit outcome `no-files-changed` and exit cleanly — there is nothing to review.

Outcome: `<N>-files-identified`.

## Step 3 — Manual review

For each modified file, walk every category below. The categories cover rules the automated checkers (Step 4) cannot fully verify; the canon for each lives in `lazy-python.coding-guidelines.md` and `lazy-python.documenting-guidelines.md`.

- **Docstring quality** — opening `"""` and closing `"""` each on their own line; `Summary` / `Scope` describe external behaviour only (no implementation details, no algorithm narration, no private-internal references); `TODO:` / `TMP:` / `DBG:` / `REF:` / `opt:` / `guard:` / `DOC(...)` markers preserved verbatim.
- **Contract consistency** — public method / property signatures match the docstring's `Args:` / `Returns:` / `Raises:` sections; type hints accurately reflect declared behaviour; no drift between what the docstring promises and what the signature accepts.
- **Guard clauses** — every guard `if` (early-return for invalid state) has a `# guard:` comment on the preceding line.
- **Method organization** — public-before-private inside each class; classmethods before instance methods; properties grouped per the canon ordering.
- **Naming** — `snake_case` for functions, methods, and variables; `_private` prefix for non-public attributes; full words (no abbreviations like `cfg`, `tmp_v`, single-letter loop vars outside short comprehensions).
- **Structural rules** — 2-space indentation; 117-char line limit; no `typing.cast()`; no bare `Any` in annotations (waiver required to exempt); `__init__` parameters with defaults are keyword-only (after `*`).
- **Comment preservation** — the special markers (`TODO:`, `TMP:`, `DBG:`, `REF:`, `opt:`, `guard:`, `DOC(...)`) are untouched anywhere they appeared before the edit. Removing or rewording any of them is an issue regardless of whether the surrounding code looks cleaner without them.

Track every violation found, by file and line. The manual pass is mandatory — do not assume Step 4 will catch these; the checkers are tuned for syntactic / type-level issues, not semantic ones.

Outcome: `<N>-issues-found-manually` or `manual-clean`.

## Step 4 — Automated checks

Run the canonical aggregator. Path: `<repo>/cli/chk-py` (wrapper installed by `/lazy-python.install`).

- **Per file**: `chk-py all <file>.py -q` for each modified file.
- **Per dir**: if more than three modified files share a directory, run `chk-py all <dir>/ -q` instead of looping per file — the aggregator deduplicates cross-file checks and is faster on a module-wide refactor.
- **Whole project**: after the per-file/per-dir sweep is clean, run `chk-py all -q` to catch cross-file regressions (broken imports, removed public APIs, dangling type references).

Always pass `-q` — without it, desktop notifications fire and per-file output overflows the context window.

Aggregate every violation reported by `pcf` / `toi` / `pch` / `mypy` / `pylint`. Group them by file for the fix pass.

Outcome: `<N>-violations-from-chk` or `chk-clean`.

## Step 5 — Fix remaining issues

For each issue identified in Step 3 or Step 4, apply a minimal targeted fix via `Edit`. One fix per violation; do not bundle unrelated changes (e.g. do not reorganise the file's imports while fixing a docstring line-length issue — the next checker pass will surface the import change as noise).

**Test-edit guard**: if a proposed fix would modify any file under `tests/**`, STOP and ask the user via `AskUserQuestion` before editing. Naming the specific test file in the question is mandatory — silently doctoring a test to keep things green hides the regression the test was meant to catch. See `.claude/CLAUDE.md` § "Test edits require explicit user permission".

If no issues were found in Steps 3 and 4, skip the fix loop and emit `no-fixes-needed`.

Outcome: `<N>-issues-fixed` or `no-fixes-needed`.

## Step 6 — Re-verify

Confirm the fixes landed cleanly:

- **Per file / per dir**: re-run `chk-py all <file>.py -q` for each fixed file, or `chk-py all <dir>/ -q` for a multi-file refactor.
- **Whole project**: re-run `chk-py all -q`.
- **Tests**: run `tst-py <module> -q` for each module the edits touched. Pass the bare module name (e.g. `core`, `rpg`), not a path and not `.py`.

If any check still reports violations, do not loop back to Step 5 silently — escalate to the user with the remaining issue list and ask how to proceed.

Outcome: `verified-clean` or `<N>-issues-remain`.

## Step 7 — Log the run

Write a run log per `lazy-log.logging`:

- Path: `./.logs/claude/lazy-python.check-style/YYYY-MM-DD_HH-MM-SS.md` (timestamp via `date -u +%Y-%m-%d_%H-%M-%S`).
- Steps: `Bash(mkdir -p ./.logs/claude/lazy-python.check-style)` then a single `Write` to the file — never chain with `&&`.
- Frontmatter: `git_sha`, `git_branch`, `date` (`YYYY-MM-DD HH:MM:SS UTC`), `input` (file list or `none`).
- Body: `# lazy-python.check-style` heading; `## Actions` with one bullet per step + its outcome word; `## Result` with the final state (`verified-clean` / `<N>-issues-remain` / `no-files-changed`).

Outcome: `logged`.

## Report

One line per task in the canonical list above, each with its outcome word. A missing line is a bug.

## Failure modes

- **Step 3 manual review finds issues but Step 4 `chk-py` reports clean** — the checkers do not enforce every canon rule (semantic docstring quality, contract consistency, comment preservation are out of their scope). The manual pass is mandatory; do not interpret a clean `chk-py` as evidence the file is review-complete.
- **Step 5 fix would modify a file under `tests/**`** — STOP and ask the user via `AskUserQuestion` naming the specific test file. Never silently retune a test to keep the suite green; the failing test is signalling a regression in the code, not in itself.
- **Step 6 re-verify still reports violations after Step 5 fixes landed** — escalate to the user with the remaining issue list rather than looping silently. A persistent violation after a targeted fix usually means the issue spans more than one file or the canon rule was misread; surfacing it is correct behaviour.
