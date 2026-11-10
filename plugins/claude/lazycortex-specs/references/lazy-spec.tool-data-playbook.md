---
name: lazy-spec.tool-data-playbook
description: Tool playbook for the `data` tool — entity data files written to the project's schemas straight from the asset's design document, with no plan of its own, by a child agent the release implementer delegates to and journals in the release's `code-report`.
---
# The `data` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.data`, carrying `playbook: lazy-spec.tool-data-playbook` and `report_doc: data-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `data` is **entity data files written to the project's schemas**. A catalog entry, a pricing rule table, a document template, a configuration preset: a file in the format and the place the project's schema defines for that entity. The journal of what was written and against which decisions is the release's `code-report`, kept by the implementer — never the deliverable itself. The `report_doc: data-report` declaration survives for one purpose: it names the review class whose main writer is this tool's expert.

The design states decisions, never values. The tool chooses every concrete value itself so that the data expresses those decisions, and the reason for a value lives in the data — in the schema's own comment field where it has one — never back in the design.

**Where the data's schema comes from is the project's business.** It may be a document, a schema file, or the output of a project utility; the product declares how to reach it in `products[<key>].asset_types.content.guidelines` (`lazy-spec.config-protocol.md`), the one declaration the content designer and the data writer both read. A product that declares none leaves the tool without a schema to write against, and the job stops and says so rather than inferring the format from existing data.

`data` is a non-test tool: its work counts toward the release's `spec_develop_done`, never toward `spec_tests_passing`. An asset note carries neither gate — implementation is the release's business, and the asset's own ladder ends at the approval of its start document.

## The plan

**This tool has no plan.** The declaration carries no `plan_doc`, and that is a definite "no", not a "not set up yet": data work is planned by the design — an approved design document already describes the entity in enough detail to write it, and an intermediate document between design and data would add nothing.

The practical consequence: from this tool's side the release's `spec_plan_done` always reads ready, by absence. There is nothing to wait for and nothing to approve; the gate is held only by the build's architecture step and the release's `code-plan.md`, when the release has one (`lazy-spec.release-playbook.md`, "The gates of the build"); the release's `test-plan.md` is written after the build and holds `spec_tests_passing`, never this gate.

## The work inside a release build

**There is no `Start data entry` row anywhere** — not on an asset note, not on the release note. Data is written inside a release build, as part of the one implementation job the release coordinator dispatches to the product's release implementer (`resolve-product release-implementer`, `lazy-spec.release-playbook.md`).

**The implementer delegates, it does not write.** For every included asset whose `spec_tools` declares `data`, the implementer MUST launch a child agent with this tool's expert — resolved mechanically, as before, as the main writer of the review class named after the tool's `report_doc`, the `data-report` class. It hands the child the **asset's design document**, which IS the specification of the entity being written, together with the tool's guidelines: the product's guidelines for the role, the content type's own guidelines — the schema the data is written against — and the wildcard guidelines, plus the decision registries (product-level and asset-level) so the data does not drift from a choice already on record. A declared path that does not resolve to a file becomes a warning line in the release's history, never a silent drop. The implementer never writes the data itself.

**The project's validators are part of that work.** Schemas, linters, and data loaders are run through the **product repository's own runner** before the child reports back: a red validator is unfinished work, not a finding for review. What reaches the journal is the fact of the run and its outcome.

**The journal is the release's `code-report.md`.** The implementer records the delegated data work there, under the build's `#### build <n>` entry; a release carries no `data-report.md`.

## What "done" means

The `data` work is closed together with everything else in the build: when the release's `code-report.md` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). A green validator does not close anything on its own: it is a precondition of the journal entry, not a substitute for acceptance.

There is no separate term for `data` in the release's `spec_develop_done`: the one accepted `code-report.md` closes the gate for every non-test tool of every included asset at once.

## Staleness

The source of this tool's work is the asset's `design.md`. When the design is re-approved after the build that wrote the data, `Rebuild` hangs on the release note, and its tick returns both release plans to `draft` and turns `spec_develop_done`, `spec_tests_passing` and `spec_built` off. The next build delegates the asset to this tool's expert again against the re-approved design; the journal keeps its stage-less, append-only form, and the implementer records the redo in the next `#### build <n>` entry.

## The acceptance cycle

Review of the release's `code-report.md` is acceptance of the **work**, the data work included — not copy-editing of the report's text.

- A reviewer's comment on the data means "redo what was written": go back into the data files, fix the values, re-run the validators, extend the journal.
- One case is typical enough to name: data failing a decision of the approved design. The failure is fixed by **work** — the data is brought to express the design. Disagreement with the design itself goes back into the design through the design's own review, never silently into the data.
- A redo runs as a **continuation to the same expert** — the same implementer, on the release's job `branch` — and the implementer routes the comment back to the same child expert; it does not fix the data by hand.
- The report is append-only: iterations are appended, earlier ones are never rewritten.
- Until the report is accepted the release's `spec_develop_done` stays shut, however many files already sit in the repository.
