---
name: lazy-spec.tool-data-playbook
description: Tool playbook for the `data` tool — entity data files written to the project's schemas straight from the design document, with no plan of its own, reported in `data-report`.
---
# The `data` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.data`, carrying `playbook: lazy-spec.tool-data-playbook` and `report_doc: data-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `data` is **entity data files written to the project's schemas**. A race, a skill, an item, a table, a preset: a file in the format and the place the project's schema defines for that entity. The `data-report` document is the journal of what was written and against which decisions, never the deliverable itself.

`data` is a non-test tool: its contribution counts toward `spec_develop_done`, never toward `spec_tests_passing`.

## The plan

**This tool has no plan.** The declaration carries no `plan_doc`, and that is a definite "no", not a "not set up yet": data work is planned by the design — an approved design document already describes the entity in enough detail to write it, and an intermediate document between design and data would add nothing.

The practical consequence: from this tool's side `spec_plan_done` always reads ready, by absence. There is nothing to wait for and nothing to approve; the gate is held only by the asset's other tools, if theirs have plans.

## The implementation checkbox

The label is `Start implementation (data)`. The bare label `Start implementation` is permitted and means the same thing when `data` is the asset's only non-test tool — the typical shape of an asset that is one design plus the data written from it.

**When it appears.** The checkbox hangs as soon as `spec_plan_done` is closed — this tool waits on no plan of its own. The shared dependency rule still applies: every dependency named in `spec_depends_on` must have closed its own `spec_develop_done`. A halted asset never gets the checkbox at all.

**What a tick dispatches.** The role is the data writer; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `data-report` class. The job's source is the **asset's design document**: it IS the specification of the entity being written. Context is the product's guidelines for the role and its wildcard guidelines, plus the decision registries (product-level and asset-level) so the data does not drift from a choice already on record; a declared path that does not resolve to a file becomes a warning line in the asset's history, never a silent drop. Result is a document of type `data-report`.

**The project's validators are part of the job's work.** Schemas, linters, and data loaders are run through the **product repository's own runner** before the job reports: a red validator is unfinished work, not a finding for review. What goes into the report is the fact of the run and its outcome.

One active job per asset at a time.

## What "done" means

The `data` tool's contribution is closed when its `data-report` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). A green validator does not close the contribution on its own: it is a precondition of the report, not a substitute for acceptance.

`spec_develop_done` is an AND across every non-test tool of the asset. An accepted `data-report` closes exactly one term; with `code` or `docs` declared alongside, the gate waits for their reports too.

## The acceptance cycle

Review of a `data-report` is acceptance of the **data work**, not copy-editing of the report's text.

- A reviewer's comment means "redo what was written": go back into the data files, fix the values, re-run the validators, extend the report.
- One case is typical enough to name: data diverging from the approved design. The divergence is fixed by **work** — the data is brought to the design. Disagreement with the design itself goes back into the design through the design's own review, never silently into the data.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`.
- The report is append-only: iterations are appended, earlier ones are never rewritten.
- Until the report is accepted the tool's contribution is not counted, however many files already sit in the repository.
