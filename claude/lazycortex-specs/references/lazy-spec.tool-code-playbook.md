---
name: lazy-spec.tool-code-playbook
description: Tool playbook for the `code` tool — code in the product repository, written from an opt-in `code-plan` and reported in `code-report`, closing that tool's share of `spec_develop_done`.
---
# The `code` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.code`, carrying `playbook: lazy-spec.tool-code-playbook`, `report_doc: code-report`, `plan_doc: code-plan`. Everything below is the law of THIS tool and nothing else: the asset's other tools live by their own playbooks, and their contributions are summed into the shared gate.

## What the tool delivers

The deliverable of `code` is **working code in the product repository**. Not a description of code, not a plan for code, not a report about code: changed and added sources that pass the repository's own checkers and runners. The `code-report` document is the journal of what was done to the code, never the deliverable itself — it only presents the work for acceptance.

`code` is a non-test tool: its contribution counts toward `spec_develop_done`, never toward `spec_tests_passing`.

## The plan

This tool has a plan: `plan_doc: code-plan`.

- **Who writes it.** A job in the `planner` role; the expert is the main writer of the `code-plan` review class. Source is the asset's `design`, plus `architecture` when the asset has one; context is the product's `guidelines` for that role plus its wildcard guidelines. Result is a document of type `code-plan`.
- **Opt-in semantics.** A declared `plan_doc` means "a plan is available for this tool", not "a plan must exist". An asset may reach implementation with no `code-plan` at all — implementation then reads `design` (and `architecture`, if present) directly. An absent plan is a normal state, not a finding.
- **How the plan stops holding `spec_plan_done`.** From this tool's side the gate reads ready when `code-plan` is absent, OR its `spec_stage` is `approved`, OR its `spec_stage` is `cancelled`. A cancelled plan is a legitimate "there is nothing here to plan" — it does not block the start of work.

## The implementation checkbox

The label is `Start implementation (code)`. The bare label `Start implementation` is permitted and means exactly the same thing when the asset has exactly one non-test tool: the parameter exists only to tell several implementation checkboxes on one asset apart.

**When it appears.** The checkbox hangs once `spec_plan_done` is closed, the tool's own plan no longer holds the gate (above), and every dependency named in `spec_depends_on` has closed its own `spec_develop_done` — bottom-up, dependency before dependent. A halted asset never gets the checkbox at all, and one already hung comes down.

**What a tick dispatches.** The role is `developer`; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `code-report` class. The job's source is `code-plan`, or the asset's `design` when no plan exists. Context is `design` (when it did not itself take the source slot) plus the product's guidelines for the role and its wildcard guidelines; a declared path that does not resolve to a file becomes a warning line in the asset's history, never a silent drop. Result is a document of type `code-report`, which the job writes itself.

One active job per asset at a time: while the previous one has not reported, a second tick of the same checkbox dispatches nothing.

## What "done" means

The `code` tool's contribution is closed when its `code-report` is **accepted by review** — it has reached `approved` (approved-with-concerns counts as accepted). Not "the job returned DONE", not "the code is committed": a job's terminal marker only opens review on the fresh report, and it is the accepted report that closes the contribution.

`spec_develop_done` is an AND across every non-test tool of the asset. An accepted `code-report` closes exactly one term of that AND; if the asset also declares, say, `data` or `docs`, the gate waits for their reports too.

## The acceptance cycle

Review of a `code-report` is acceptance of the **work**, not copy-editing of a text.

- A reviewer's comment on the report means "redo what was done": go back into the code, fix it, extend the report. Rewording the report without touching the code is a way around the cycle, not through it.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch` — so the work builds on top of what is already there instead of restarting on a clean slate.
- The report is append-only: each iteration is appended, earlier ones are never rewritten — review must see the history of redos.
- Until the report is accepted the tool's contribution is not counted, and `spec_develop_done` stays shut no matter how much code already sits in the repository.
