---
name: lazy-spec.tool-test-playbook
description: Tool playbook for the `test` tool — tests and their run against a release, planned in the release's opt-in composed `test-plan`, launched once the release's `spec_develop_done` closes and its `staging` deploy succeeds, and closing `spec_tests_passing` with a green accepted `test-report`.
---
# The `test` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.test`, carrying `playbook: lazy-spec.tool-test-playbook`, `report_doc: test-report`, `plan_doc: test-plan`. Everything below is the law of THIS tool and nothing else.

`test` is the one tool whose work does **not** go into `spec_develop_done`. It owns the release's `spec_tests_passing` in full: no other tool contributes to that gate, and every release carries the tool — the release type declares it among its default tools, so a release never reads ready by the tool's absence. The one way past it is an explicit waiver, below. An asset note carries neither gate — testing is the release's business.

**The test waiver.** Every release is tested by default. A product may waive testing, as it may waive any other step, with a line in its `# Coordinator rules`. Then no tester job is dispatched, and the release's `spec_tests_passing` closes together with `spec_develop_done`. A declared `staging` deploy still runs, and `Publish` hangs after it.

## What the tool delivers

The deliverable of `test` is **tests and their run**: tests written (or extended) in the product repository, plus a recorded green run through the repository's own runner against the deployed release — on `staging`, or on a local instance the tester brings up itself. Not an opinion on quality and not a code review — verification by execution. Not unit tests either: those belong to the `code` tool, written and run by the implementer inside the build (`lazy-spec.tool-code-playbook.md`), and neither this tool's plan nor its report covers them. The `test-report` document is the journal of what was run and with what outcome, never the deliverable itself.

## The plan

This tool has a plan: `plan_doc: test-plan`. It is the **release's** plan, `test-plan.md` in the release folder — a composed document, not the test cases of one asset.

- **Who writes it.** A job in the `tester` role; the expert is the main writer of the `test-plan` review class. The tester assembles it from three sources: the product's root `test-plan.md` (doc type `system-test-plan`, the standing test instructions), the included assets' own `test-plan.md` files, which hold their test cases, and the regression. Context is the product's `guidelines` for that role plus its wildcard guidelines. Result is a document of type `test-plan`.
- **Opt-in semantics.** A declared `plan_doc` means "a plan is available", not "a plan is mandatory". A release may be tested with no composed `test-plan` at all — the test job then reads the root plan and the assets' test cases directly. An absent plan is a normal state, not a finding.
- **The waive asymmetry is deliberate.** From this tool's side `spec_tests_passing` reads ready when `test-plan` is absent OR its `spec_stage` is `approved`. `cancelled` does **not** waive here: a cancelled test plan does not certify that tests pass, so it cannot stand in for a green report. This is exactly where `test` parts ways with the non-test tools' plans, where `cancelled` is a legitimate answer.

## The test run inside a release

**No `Start testing` row hangs on any asset note.** Testing is a stage of the release, and the release coordinator dispatches it without a tick.

**When it starts.** The tester is dispatched once the release's `spec_develop_done` is closed — the build's `code-report.md` has been accepted — and the tool's plan no longer holds the gate (absent, or `approved`). When the product declares a `staging` environment the release is deployed to it automatically first; a failed deploy is journaled and tests do not start. The `test` tool never runs before the build is accepted.

**What is dispatched.** The role is `tester`; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `test-report` class. The job's source is the release's `test-plan.md`, or the root plan and the included assets' test cases when no composed plan exists. Context is the product's guidelines for the role and its wildcard guidelines. Result is the release's `test-report.md`.

**Where it runs.** The tester tests the product against `staging` when the product declares one, or against a local instance it brings up inside its own job when it does not. The run goes through the **product repository's own runner**; a red run is an outcome the job is obliged to record in the report, never a reason to stop quietly.

Each tester run opens a `#### build <n>` entry in `test-report.md`, numbered from 1 within the release. One active job per release at a time.

## What "done" means

`spec_tests_passing` closes when the `test-report` is **green AND accepted by review** (`approved`; approved-with-concerns counts as accepted). Both conditions are required, and nothing else substitutes for either:

- an accepted but red report does not close the gate — it honestly records that tests do not pass, and returns the work to the release implementer for the next build;
- a green but unaccepted report does not close the gate — acceptance has not happened yet.

The `test` tool does not contribute to `spec_develop_done` at all: that gate closes on the accepted `code-report.md`, and `test` is neither a term of it nor a condition on it.

## Staleness

The source of this tool's report is `test-plan.md` of the release. A plan re-approved after `test-report.md` was accepted moves nothing by itself: the report keeps its stage-less journal form and the release's gates stay as they are; the next run continues the same expert against the re-approved plan, who opens the next `#### build <n>` entry in the journal and re-submits it.

Changes from below reach the plan through `Rebuild` (`lazy-spec.release-playbook.md`): re-approved test cases of an included feature — its own `test-plan.md` — hang the row, and its tick returns the release's `test-plan.md` to `draft` and turns `spec_tests_passing` off. A re-approved design reaches further: the tick returns both release plans to `draft` and turns `spec_develop_done`, `spec_tests_passing` and `spec_built` off together.

## The acceptance cycle

Review of a `test-report` is acceptance of the **verification**, not copy-editing of the report's text.

- A reviewer's comment means "verify again": extend or fix the tests, re-run them, extend the report. Rewriting the report's conclusions without a new run is a way around the cycle, not through it.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`.
- The report is append-only: every run iteration is appended, earlier ones are never rewritten — the history of red runs is precisely what the report exists to keep.
- A red run caused by a defect in code, data or documentation is fixed by the release implementer in the next build: the `test` tool presents the failure, it does not repair another tool's work.
