---
name: lazy-spec.tool-docs-playbook
description: Tool playbook for the `docs` tool — user-facing product documentation written straight from the asset's design document, with no plan of its own, by a child agent the release implementer delegates to and journals in the release's `code-report`.
---
# The `docs` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.docs`, carrying `playbook: lazy-spec.tool-docs-playbook` and `report_doc: docs-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `docs` is **the product's user-facing documentation**: the text a consumer of the product reads, in whatever place and format that product's documentation lives. It is not the asset's spec documents (`design`, plans, reports) — those are written by other jobs, under other rules, in the spec catalog; the `docs` tool writes outward, for the user. The journal of what was written and where is the release's `code-report`, kept by the implementer — never the deliverable itself. The `report_doc: docs-report` declaration survives for one purpose: it names the review class whose main writer is this tool's expert.

`docs` is a non-test tool: its work counts toward the release's `spec_develop_done`, never toward `spec_tests_passing`. An asset note carries neither gate — implementation is the release's business, and the asset's own ladder ends at the approval of its start document.

## The plan

**This tool has no plan.** The declaration carries no `plan_doc`, and that is a definite "no": an approved design document already states what the user got, and planning the shape of a user-facing text in a separate approvable document would only add a round of acceptance.

The practical consequence: from this tool's side the release's `spec_plan_done` always reads ready, by absence. The gate is held only by the release's code plan, until it is settled — `code-plan.md` `approved` or `cancelled`, or the code plan waived in the owner's `# Coordinator rules` (`lazy-spec.release-playbook.md`, "The gates of the build"); the release's `test-plan.md` is written after the build and holds `spec_tests_passing`, never this gate.

## The work inside a release build

**There is no `Start documentation` row anywhere** — not on an asset note, not on the release note. Documentation is written inside a release build, as part of the one implementation job the release coordinator dispatches to the product's release implementer (`resolve-product release-implementer`, `lazy-spec.release-playbook.md`).

**The implementer delegates, it does not write.** For every included asset whose `spec_tools` declares `docs`, the implementer MUST launch a child agent with this tool's expert — resolved mechanically, as before, as the main writer of the review class named after the tool's `report_doc`, the `docs-report` class. It hands the child the **asset's design document** together with the tool's guidelines: the product's guidelines for the role and its wildcard guidelines — first of all the rules for the tone and shape of user-facing documentation. A declared path that does not resolve to a file becomes a warning line in the release's history, never a silent drop. The implementer never writes the documentation itself.

**The journal is the release's `code-report.md`.** The implementer records the delegated documentation work there, under the build's `#### build <n>` entry; a release carries no `docs-report.md`.

## What "done" means

The `docs` work is closed together with everything else in the build: when the release's `code-report.md` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). Text that is written but never presented for acceptance closes nothing.

There is no separate term for `docs` in the release's `spec_develop_done`: the one accepted `code-report.md` closes the gate for every non-test tool of every included asset at once.

## Staleness

The source of this tool's work is the asset's `design.md`. When the design is re-approved after the build that wrote the documentation, `Rebuild` hangs on the release note, and its tick returns both release plans to `draft` and turns `spec_develop_done`, `spec_tests_passing` and `spec_built` off. The next build delegates the asset to this tool's expert again against the re-approved design; the journal keeps its stage-less, append-only form, and the implementer records the redo in the next `#### build <n>` entry.

## The acceptance cycle

Review of the release's `code-report.md` is acceptance of the **work**, the documentation included — not copy-editing of the report's text.

- A reviewer's comment on the documentation means "rewrite what was written": go back into the product's documentation, fix it, extend the journal.
- Documentation diverging from the approved design is fixed by work — the text is brought to the design. Disagreement with the design itself goes back into the design through the design's own review, never silently rewritten in the documentation.
- A redo runs as a **continuation to the same expert** — the same implementer, on the release's job `branch` — and the implementer routes the comment back to the same child expert; it does not rewrite the documentation by hand.
- The report is append-only: iterations are appended, earlier ones are never rewritten.
- Until the report is accepted the release's `spec_develop_done` stays shut, however many pages are already written.
