---
name: lazy-spec.tool-research-playbook
description: Tool playbook for the `research` tool — the research report written straight from the approved research design, with no plan of its own; the report is the deliverable, a stage-bearing document rather than a journal.
---
# The `research` tool — playbook

The tool is declared in the shipped tool registry as `research`, carrying `playbook: lazy-spec.tool-research-playbook` and `report_doc: research-report`. There is no `plan_doc` key in the declaration — that is a property of the tool, not an omission. Everything below is the law of THIS tool and nothing else.

## What the tool delivers

The deliverable of `research` is **the research report itself** — `research.md`, `spec_doc_type: research-report`, role `research`, in the asset's folder. Unlike the journals of `code`, `data`, `test` and `docs`, this report is not a log of work done elsewhere: it is the answer to the research design's question, and it is content of the catalog. It carries a stage, it is reviewed and approved like any authored document, it enters the wiki once approved, and it is never listed among the wiki's excluded journals.

`research` is a non-test tool: its contribution counts toward `spec_develop_done`, never toward `spec_tests_passing`.

## The plan

**This tool has no plan.** The approved research design already states the question, the scope and the approach; a separate approvable plan would only add a round of acceptance. From this tool's side `spec_plan_done` always reads ready, by absence.

## The implementation checkbox

The label is `Start implementation (research)`. The bare label `Start implementation` is permitted and means the same thing when `research` is the asset's only non-test tool — the usual case.

**When it appears.** The checkbox hangs as soon as `spec_plan_done` is closed — this tool waits on no plan of its own. The shared dependency rule still applies: every dependency named in `spec_depends_on` must have closed its own `spec_develop_done`. A halted asset never gets the checkbox at all. The tool's contribution must not be counted toward the gate — an accepted report hangs no checkbox until the source-staleness rule turns the gate back off.

**What a tick dispatches.** The role is the researcher; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `research-report` class. The job's source is the **asset's approved research design** (`design.md` typed `research-design`). Context is the product's guidelines for the role and its wildcard guidelines; a declared path that does not resolve to a file becomes a warning line in the asset's history, never a silent drop. Result is `research.md`, a document of type `research-report`, seeded from its template if absent and written in place; the job commits it on its job-scoped branch.

One active job per asset at a time.

## What "done" means

The `research` tool's contribution is closed when its `research.md` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). A report written but never presented for acceptance closes nothing.

`spec_develop_done` is an AND across every non-test tool of the asset. An accepted `research.md` closes exactly one term; with `docs` bought alongside, the gate waits for its report too.

## Staleness

The source of this tool's report is `design.md` (typed `research-design`). When the research design is re-approved after `research.md` was accepted, the report returns to `draft`, `spec_develop_done` turns off and `Start implementation (research)` hangs again; the tick continues the same expert against the re-approved design, and the previously approved answer is superseded, not cited.

## The acceptance cycle

Review of `research.md` is acceptance of **the answer**: is the question answered, is every finding sourced, does the conclusion rule on the hypothesis, do the options score against the design's criteria.

- A reviewer's comment means "research further and rewrite": the researcher walks the missing route, fixes the finding, rewrites the section. The report is a stage-bearing document, not a journal — it is edited in place, never appended to.
- A finding that contradicts the research design (the question was two questions, the scope excluded the decisive route) is not fixed in the report: it is raised as a `[!question]` on the design, and the design goes back through its own review.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`.
- Until the report is accepted the tool's contribution is not counted, however many findings are already written.
- Once approved the report is immutable: a wrong conclusion is answered by a new research asset citing this one.
