---
name: lazy-spec.tool-docs-playbook
description: Tool playbook for the `docs` tool — user-facing product documentation written straight from the design document, with no plan of its own, reported in `docs-report`.
---
# The `docs` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.docs`, carrying `playbook: lazy-spec.tool-docs-playbook` and `report_doc: docs-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `docs` is **the product's user-facing documentation**: the text a consumer of the product reads, in whatever place and format that product's documentation lives. It is not the asset's spec documents (`design`, plans, reports) — those are written by other jobs, under other rules, in the spec catalog; the `docs` tool writes outward, for the user. The `docs-report` document is the journal of what was written and where, never the deliverable itself.

`docs` is a non-test tool: its contribution counts toward `spec_develop_done`, never toward `spec_tests_passing`.

## The plan

**This tool has no plan.** The declaration carries no `plan_doc`, and that is a definite "no": an approved design document already states what the user got, and planning the shape of a user-facing text in a separate approvable document would only add a round of acceptance.

The practical consequence: from this tool's side `spec_plan_done` always reads ready, by absence. The gate is held only by the asset's other tools, if theirs have plans.

## The implementation checkbox

The label is `Start implementation (docs)`. The bare label `Start implementation` is permitted and means the same thing when `docs` is the asset's only non-test tool — an asset that changes nothing but the documentation.

**When it appears.** The checkbox hangs as soon as `spec_plan_done` is closed — this tool waits on no plan of its own. The shared dependency rule still applies: every dependency named in `spec_depends_on` must have closed its own `spec_develop_done`. A halted asset never gets the checkbox at all.

**What a tick dispatches.** The role is the documentation writer; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `docs-report` class. The job's source is the **asset's design document**. Context is the product's guidelines for the role and its wildcard guidelines — first of all the rules for the tone and shape of user-facing documentation; a declared path that does not resolve to a file becomes a warning line in the asset's history, never a silent drop. Result is a document of type `docs-report`.

One active job per asset at a time.

## What "done" means

The `docs` tool's contribution is closed when its `docs-report` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). Text that is written but never presented for acceptance closes nothing.

`spec_develop_done` is an AND across every non-test tool of the asset. An accepted `docs-report` closes exactly one term; with `code` or `data` declared alongside, the gate waits for their reports too.

## The acceptance cycle

Review of a `docs-report` is acceptance of the **documentation that was written**, not copy-editing of the report's text.

- A reviewer's comment means "rewrite what was written": go back into the product's documentation, fix it, extend the report.
- Documentation diverging from the approved design is fixed by work — the text is brought to the design. Disagreement with the design itself goes back into the design through the design's own review, never silently rewritten in the documentation.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`.
- The report is append-only: iterations are appended, earlier ones are never rewritten.
- Until the report is accepted the tool's contribution is not counted, however many pages are already written.
