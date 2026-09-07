---
description: "<trigger FIRST — `Run when the operator asks to <verb>` (name the request shapes they actually type, not the verb the filename already carries) — then mechanism only if a sibling command's trigger overlaps>"
---
# `/<namespace>.<name>`

<One paragraph: what the command does, when to run it, prerequisites.>

## Execution discipline (MANDATORY — read before any action)

This command has <N> ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — <name>`
   - `Phase 2 — <name>`
   - `Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a one-word outcome for it". No-ops count only if they emit an explicit outcome (`audited`, `built`, `presented`, `dispatched`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
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

- `description:` opens with WHEN to run the command, per `lazy-core.skill-writing § 8` — it is the
  routing table, and a command the router cannot select never fires (WARN). Shapes and worked
  rewrites: `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md`.

  § 11 A step that asks via `AskUserQuestion` is written as a context block followed by the call
      (WARN when missing). Ask only for genuine project config nothing can derive — not a value
      already in settings, not a path a convention fixes, not what another plugin seeds; a step
      that need not ask carries no block at all. Shape, printed to the operator before the call:
        Context (print before asking):
        - Where: /<skill> · Step <N> — <title>; target <path or scope>
        - Found: <what the read-first probe returned>
        - Why asking: <the one reason the skill cannot decide alone>
        - Answers: `<label>` — <effect now / later>; `<label>` — <…>
        AskUserQuestion: header "<label>", question "<self-contained, names the target>", options with descriptions.
- Filename: `<namespace>.<name>.md` under `.claude/commands/` or `<plugin>/commands/`.

- Logging: only if your project has a logging contract installed (e.g. `lazy-log.logging` from
  `lazycortex-core`). If so, add a `## Log the run` step pointing at
  `./.logs/claude/<namespace.name>/<UTC-timestamp>.md` with the contract's required frontmatter.
  If no logging plugin is installed, omit the step.
-->
