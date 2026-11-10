---
name: lazy-spec.tool-research-playbook
description: Tool playbook for the `research` tool — the research report written inside the review loop straight from the approved research design, with no plan and no implementation job; the report is the deliverable, a stage-bearing document rather than a journal, and its approval closes the asset's `spec_released`.
---
# The `research` tool — playbook

The tool is declared in the shipped tool registry as `research`, carrying `playbook: lazy-spec.tool-research-playbook` and `report_doc: research-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `research` is **the research report itself** — `research.md`, `spec_doc_type: research-report`, role `research`, in the asset's folder. Unlike the journals of `code`, `data`, `test` and `docs`, this report is not a log of work done elsewhere: it is the answer to the research design's questions, and it is content of the catalog. It carries a stage, it is reviewed and approved like any authored document, it enters the wiki once approved, and it is never listed among the wiki's excluded journals.

`research` is the one tool with no implementation. A research asset never enters a release: nothing of it counts toward a release's `spec_develop_done` or `spec_tests_passing`, and the asset's own ladder closes on the report itself.

## The plan

**This tool has no plan.** The approved research design already states the questions, the scope and the approach; a separate approvable plan would only add a round of acceptance. There is no gate an absent plan would hold: the research asset's ladder runs from the approval of its design straight into the review of its report.

## How the report is written

**There is no implementation job.** `Start research` is a writer-launch row the research TYPE playbook hangs on the asset note once `design.md` is approved — not a checkbox of this tool. A tick seeds `research.md` from its template (`research.md:research-report`) and opens review on it in the seed-then-start flow: the document enters the loop at the writer round, with the researcher — the main writer of the `research-report` class, resolved mechanically from the tool's `report_doc` — as the round's writer. The researcher writes the report inside the review loop, in place; no bundle is dispatched, no job result is collected, no `land-result` step exists for it.

**What reaches the researcher.** The **asset's approved research design** (`design.md` typed `research-design`) is the document the report answers, and the product's guidelines for the role plus its wildcard guidelines frame the work; both reach the researcher through the review's own context, the same way every writer round receives its material. A declared path that does not resolve to a file becomes a warning line in the asset's history, never a silent drop.

## What "done" means

The research asset is done when `research.md` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). A report written but never presented for acceptance closes nothing.

The approval of `research.md` closes the research asset's `spec_released` directly: an asset note carries no `spec_develop_done`, and the approved report is the asset's release.

## Staleness

The source of this tool's report is `design.md` (typed `research-design`). A research design re-approved after `research.md` was accepted reopens nothing: the report stays `approved` and `spec_released` stays on, and a changed question is answered by a new research asset. Contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19).

## The acceptance cycle

Review of `research.md` is acceptance of **the answer**: is every question answered, is every finding sourced, does the conclusion rule on each hypothesis, do the options score against the design's criteria.

- A reviewer's comment means "research further and rewrite": the researcher walks the missing route, fixes the finding, rewrites the section. The report is a stage-bearing document, not a journal — it is edited in place, never appended to.
- A finding that contradicts the research design (the question was two questions, the scope excluded the decisive route) is not fixed in the report: it is raised as a `[!question]` on the design, and the design goes back through its own review.
- A redo is the **review loop's own continuation** — the next writer round goes to the same researcher, on the same document; there is no job branch and no `result/` to carry the report through.
- Until the report is accepted the asset's `spec_released` stays shut, however many findings are already written.
- Once approved the report is immutable: a wrong conclusion is answered by a new research asset citing this one.
