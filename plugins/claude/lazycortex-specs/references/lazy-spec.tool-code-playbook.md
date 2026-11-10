---
name: lazy-spec.tool-code-playbook
description: Tool playbook for the `code` tool — code in the product repository, written inside a release build from the release's opt-in `code-plan` and journaled in the release's `code-report`, whose acceptance closes the release's `spec_develop_done`.
---
# The `code` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.code`, carrying `playbook: lazy-spec.tool-code-playbook`, `report_doc: code-report`, `plan_doc: code-plan`. Everything below is the law of THIS tool and nothing else: an asset's other tools live by their own playbooks, and the release's implementer assembles their work into one result.

## What the tool delivers

The deliverable of `code` is **working code in the product repository**. Not a description of code, not a plan for code, not a report about code: changed and added sources that pass the repository's own checkers and runners. The `code-report` document is the journal of what was done to the code, never the deliverable itself — it only presents the work for acceptance.

`code` is a non-test tool: its work counts toward the release's `spec_develop_done`, never toward `spec_tests_passing`. An asset note carries neither gate — implementation is the release's business, and the asset's own ladder ends at the approval of its start document.

## The plan

This tool has a plan: `plan_doc: code-plan`. It is the **release's** plan, `code-plan.md` in the release folder, never a document of an asset.

- **Who writes it.** A job in the `planner` role; the expert is the main writer of the `code-plan` review class. Source is the start document of every asset the release includes (the notes `spec_includes` links to), plus the product's root `architecture.md` as the architect left it for this build; context is the product's `guidelines` for that role plus its wildcard guidelines. Result is a document of type `code-plan`.
- **Opt-in semantics.** A declared `plan_doc` means "a plan is available for this tool", not "a plan must exist". A release may reach its build with no `code-plan` at all — the implementer then reads the included assets' designs and `architecture.md` directly. An absent plan is a normal state, not a finding.
- **How the plan stops holding the release's `spec_plan_done`.** From this tool's side the gate reads ready when `code-plan` is absent, OR its `spec_stage` is `approved`, OR its `spec_stage` is `cancelled`. A cancelled plan is a legitimate "there is nothing here to plan" — it does not block the start of the build.

## The work inside a release build

**No `Start coding` row hangs on any asset note.** Code is written only inside a build of a release: the operator ticks `Start release` on the product note, the product coordinator creates the release from the delta, and the release coordinator runs the build. `Rebuild` on the release note starts the next build of the same folder once new approvals have been pulled in.

**The build is two jobs in sequence.** First the architect revises the product's root `architecture.md` against the delta's designs — an unchanged document means "the structure does not change" and the build goes on; a changed one lands in place and passes review before anything is written. Then **one implementation job** runs, led by the product's release implementer (`resolve-product release-implementer`, `lazy-spec.release-playbook.md`). Its source is the release's `code-plan.md`, or the included assets' designs when no plan exists; context is `architecture.md`, the designs (when they did not themselves take the source slot), and the product's guidelines for the role plus its wildcard guidelines. A declared path that does not resolve to a file becomes a warning line in the release's history, never a silent drop. Result is the release's `code-report.md`, which the job writes itself.

**What the implementer does with the tools.** It reads every included asset's `spec_tools`. Its own tool's work — the code — it does itself. For every foreign tool an asset declares (`data`, `docs`, an operator-defined tool) it MUST launch a child agent with that tool's expert, resolved as before from the review class of the tool's `report_doc`, handing it the asset's design and the tool's guidelines; the implementer never writes that content itself. It alone answers for the assembled result, for the consistency of the whole product — not only the delta — and for `code-report.md`, into which it journals the delegated agents' work: a release carries no `data-report.md` and no `docs-report.md`.

**Builds are incremental.** Inside an open release the implementer does only what changed since the previous build; the list arrives in the job context, and the earlier builds are in `code-report.md`. Each implementer run opens a `#### build <n>` entry in the journal, numbered from 1 within the release.

One job per build: while the implementation job has not reported, the release coordinator dispatches nothing else for it.

## What "done" means

The release's `spec_develop_done` closes when its `code-report.md` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). Not "the job returned DONE", not "the code is committed": a job's terminal marker only opens review on the fresh report, and it is the accepted report that closes the gate.

That one report covers every non-test tool of every included asset: the delegated `data` and `docs` work is journaled inside it, so there is no second report for the gate to wait on.

## Staleness

The source of this tool's report is `code-plan.md` of the release. A plan re-approved after `code-report.md` was accepted moves nothing by itself: the report keeps its stage-less journal form and the release's gates stay as they are; the next build continues the implementer against the re-approved plan, who opens the next `#### build <n>` entry in the journal and re-submits it.

A re-approved design of an included asset hangs `Rebuild`, and its tick rolls the build back: both release plans return to `draft`, and `spec_develop_done`, `spec_tests_passing` and `spec_built` turn off (`lazy-spec.release-playbook.md`, "Rebuild").

## The acceptance cycle

Review of a `code-report` is acceptance of the **work**, not copy-editing of a text.

- A reviewer's comment on the report means "redo what was done": go back into the code, fix it, extend the report. Rewording the report without touching the code is a way around the cycle, not through it.
- A redo runs as a **continuation to the same expert** — the same implementer, on the release's job `branch` — so the work builds on top of what is already there instead of restarting on a clean slate. A comment on delegated work goes back to the same child expert through the implementer, never into the implementer's own hands.
- The report is append-only: each iteration is appended, earlier ones are never rewritten — review must see the history of redos.
- Until the report is accepted the release's `spec_develop_done` stays shut no matter how much code already sits in the repository.
