---
name: <namespace.name>
description: <one-line dispatch context — when to invoke this skill>
allowed-tools: Read, Glob, Grep
---
# <Skill Title>

<One paragraph: what the skill does, when to invoke it, prerequisites.>

## Execution discipline (MANDATORY — read before any action)

This skill has <N> ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — <name>`
   - `Phase 2 — <name>`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — <name>

<Bite-sized actionable steps. Each step ends with a one-word outcome.>

## Phase 2 — <name>

<…>

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

<!--
Authoring notes (delete before saving):

- Conform to `lazy-core.skill-writing`:
  § 1 Execution-Discipline preamble (above) is MANDATORY for multi-phase skills.
    Single-response / static skills opt out via `execution-discipline-waiver: "<reason>"` in frontmatter.
  § 2 No "Optional" in any phase/step heading (FAIL).
  § 3 One-word outcome per step (`installed`, `unchanged`, `skipped-per-user-choice`, …).
  § 4 No narrative padding (`v1.2.3`, "we got burned", incident post-mortems → WARN).
- Filename: `<namespace.name>/SKILL.md`.
- Logging: only if your project has a logging contract installed (e.g. `lazy-log.logging` from
  `lazycortex-log`). If so, add a `## Logging` section pointing at
  `./.logs/claude/<namespace.name>/<UTC-timestamp>.md` with the contract's required frontmatter
  (typically `git_sha`, `git_branch`, `date`, `input`). Use `Bash(mkdir -p ...)` then the `Write`
  tool — never chain. If no logging plugin is installed, omit the section.
-->
