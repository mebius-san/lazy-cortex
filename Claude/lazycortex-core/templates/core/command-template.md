---
description: <one-line dispatch context — what this command does and when to run it>
---
# `/<namespace>.<name>`

<One paragraph: what the command does, when to run it, prerequisites.>

## Execution discipline (MANDATORY — read before any action)

This command has <N> ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — <name>`
   - `Phase 2 — <name>`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a one-word outcome for it". No-ops count only if they emit an explicit outcome (`audited`, `built`, `presented`, `dispatched`, `skipped-per-user-choice`, …).
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

- Conform to `lazy-core.skill-writing` (commands share the skill/command authoring contract):
  § 1 Execution-Discipline preamble (above) is MANDATORY for multi-phase commands.
      Verbatim-output / help-style commands opt out via
        execution-discipline-waiver: "<concrete reason — e.g. 'static help text — no executable steps'>"
      in the frontmatter; the body then becomes just the literal output (see alternative shape below).
  § 2 No "Optional" in any phase/step heading (FAIL).
  § 3 One-word outcome per step.
  § 4 No narrative padding (`v1.2.3`, "we got burned", incident post-mortems → WARN).

- Alternative shape — verbatim-output / help-style command:

    ---
    description: <one-line>
    execution-discipline-waiver: "static help text — no executable steps"
    ---
    Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

    ---

    <help block — purpose statement + one-line bullet per shipped artifact>

  Plugin help commands (`<namespace>.help`) are a specific contract — see `lazy-core.skill-writing § 7`.

- Filename: `<namespace>.<name>.md` under `.claude/commands/` or `<plugin>/commands/`.

- Logging: only if your project has a logging contract installed (e.g. `lazy-log.logging` from
  `lazycortex-log`). If so, add a `## Log the run` step pointing at
  `./.logs/claude/<namespace.name>/<UTC-timestamp>.md` with the contract's required frontmatter.
  If no logging plugin is installed, omit the step.
-->
