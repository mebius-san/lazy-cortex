---
name: lazy-spec.tool-test-playbook
description: Tool playbook for the `test` tool — tests and their run, planned in an opt-in `test-plan`, launched only after every non-test tool has reported, and closing `spec_tests_passing` with a green accepted `test-report`.
---
# The `test` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.test`, carrying `playbook: lazy-spec.tool-test-playbook`, `report_doc: test-report`, `plan_doc: test-plan`. Everything below is the law of THIS tool and nothing else.

`test` is the one tool whose contribution does **not** go into `spec_develop_done`. It owns `spec_tests_passing` in full: no other tool contributes to that gate, and an asset with no `test` tool leaves it ready by absence.

## What the tool delivers

The deliverable of `test` is **tests and their run**: tests written (or extended) in the product repository, plus a recorded green run through the repository's own runner. Not an opinion on quality and not a code review — verification by execution. The `test-report` document is the journal of what was run and with what outcome, never the deliverable itself.

## The plan

This tool has a plan: `plan_doc: test-plan`.

- **Who writes it.** A job in the `tester` role; the expert is the main writer of the `test-plan` review class. Source is the asset's `design`; context is the product's `guidelines` for that role plus its wildcard guidelines. Result is a document of type `test-plan`.
- **Opt-in semantics.** A declared `plan_doc` means "a plan is available", not "a plan is mandatory". An asset may be tested with no `test-plan` at all — the test job then reads `design` directly. An absent plan is a normal state, not a finding.
- **The waive asymmetry is deliberate.** From this tool's side `spec_tests_passing` reads ready when `test-plan` is absent OR its `spec_stage` is `approved`. `cancelled` does **not** waive here: a cancelled test plan does not certify that tests pass, so it cannot stand in for a green report. This is exactly where `test` parts ways with the non-test tools' plans, where `cancelled` is a legitimate answer.

## The implementation checkbox

The label is `Start testing`. It is **never parameterised**: an asset carries one `test` tool, there is nothing to tell apart, and the form `Start implementation (test)` is not used.

**When it appears.** The checkbox hangs once `spec_develop_done` is closed — that is, **every non-test tool of the asset has reported and its report has been accepted** — and the tool's plan no longer holds the gate (absent, or `approved`). The `test` tool does not start before every non-test tool's implementation is finished. A halted asset never gets the checkbox at all.

**What a tick dispatches.** The role is `tester`; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `test-report` class. The job's source is `test-plan`, or the asset's `design` when no plan exists. Context is `design` (when it did not itself take the source slot) plus the product's guidelines for the role and its wildcard guidelines. Result is a document of type `test-report`.

The run goes through the **product repository's own runner**; a red run is an outcome the job is obliged to record in the report, never a reason to stop quietly.

One active job per asset at a time.

## What "done" means

`spec_tests_passing` closes when the `test-report` is **green AND accepted by review** (`approved`; approved-with-concerns counts as accepted). Both conditions are required, and nothing else substitutes for either:

- an accepted but red report does not close the gate — it honestly records that tests do not pass, and returns the work to the implementation of the tool whose deliverable is broken;
- a green but unaccepted report does not close the gate — acceptance has not happened yet.

The `test` tool does not contribute to `spec_develop_done` at all: that gate is an AND across the non-test tools, and `test` is neither a term of it nor a condition on it.

## The acceptance cycle

Review of a `test-report` is acceptance of the **verification**, not copy-editing of the report's text.

- A reviewer's comment means "verify again": extend or fix the tests, re-run them, extend the report. Rewriting the report's conclusions without a new run is a way around the cycle, not through it.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`.
- The report is append-only: every run iteration is appended, earlier ones are never rewritten — the history of red runs is precisely what the report exists to keep.
- A red run caused by a defect in code or data is fixed in the tool whose deliverable is broken: the `test` tool presents the failure, it does not repair another tool's contribution.
