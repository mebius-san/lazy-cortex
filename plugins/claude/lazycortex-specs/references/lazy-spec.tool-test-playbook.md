---
name: lazy-spec.tool-test-playbook
description: Tool playbook for the `test` tool — tests and their run against a release, planned in the release's opt-in composed `test-plan`, launched by the operator's `Test` tick on the release note once the release's `spec_develop_done` closes and its `staging` deploy succeeds, and closing `spec_tests_passing` with a green accepted `test-report`.
---
# The `test` tool — playbook

The tool is declared in the product's config as `products[<key>].tool_types.test`, carrying `playbook: lazy-spec.tool-test-playbook`, `report_doc: test-report`, `plan_doc: test-plan`. Everything below is the law of THIS tool and nothing else.

`test` is the one tool whose work does **not** go into `spec_develop_done`. It owns the release's `spec_tests_passing` in full: no other tool contributes to that gate, and every release carries the tool — the release type declares it among its default tools, so a release never reads ready by the tool's absence. The one way past it is an explicit waiver, below. An asset note carries neither gate — testing is the release's business.

**The test waiver.** Every release is tested by default. A product may waive testing, as it may waive any other step, with a line in its `# Coordinator rules`. Then neither `Write test-plan` nor `Test` hangs on the release note, no tester job is dispatched, and the release's `spec_tests_passing` closes together with `spec_develop_done`. A declared `staging` deploy still runs, and `Publish` hangs only once the staging deploy of the current build has succeeded; a failed one hangs `Rebuild` instead (`lazy-spec.release-playbook.md`, "Staging and tests").

## What the tool delivers

The deliverable of `test` is **tests and their run**: tests written (or extended) in the product repository, plus a recorded green run through the repository's own runner against the deployed release — on `staging`, or on a local instance the tester brings up itself. Not an opinion on quality and not a code review — verification by execution. Not unit tests either: those belong to the `code` tool, written and run by the implementer inside the build (`lazy-spec.tool-code-playbook.md`), and neither this tool's plan nor its report covers them. The `test-report` document is the journal of what was run and with what outcome, never the deliverable itself.

## The plan

This tool has a plan: `plan_doc: test-plan`. It is the **release's** plan, `test-plan.md` in the release folder — a composed document, not the test cases of one asset.

- **Who writes it.** A job in the `tester` role; the expert is the main writer of the `test-plan` review class. The tester assembles it from three sources: the product's root `test-plan.md` (doc type `system-test-plan`, the standing test instructions), the included assets' own `test-plan.md` files, which hold their test cases, and the regression. Context is the product's `guidelines` for that role plus its wildcard guidelines. Result is a document of type `test-plan`.
- **Opt-in semantics.** A declared `plan_doc` means "a plan is available", not "a plan is mandatory". A release may be tested with no composed `test-plan` at all — the test job then reads the included assets' start documents and their test cases, with the root plan in its context (What is dispatched, below). An absent plan is a normal state, not a finding.
- **A cancelled plan counts as absent.** From this tool's side the release plan stops holding `Test` and `spec_tests_passing` when `test-plan` is absent, `cancelled` or `approved`. A cancelled plan waives the plan, never the testing: the tester works without a release plan, as when none exists, and `spec_tests_passing` still waits for a green accepted report of the current build. Nor does it close planning: `Write test-plan` hangs over a cancelled plan as over an absent one, and its tick seeds a fresh plan that replaces the cancelled file (When it starts, below). This is where `test` parts ways with the non-test tools' plans, where `cancelled` settles the plan and nothing else is owed.

## The test run inside a release

**No `Start testing` row hangs on any asset note.** Testing is a stage of the release, started by the operator's `Test` tick on the release note; the release coordinator never dispatches the tester without it.

**When it starts.** The `Test` row hangs on the release note once the release's `spec_develop_done` is closed — the build's `code-report.md` has been accepted — and the tool's plan no longer holds it (absent, `cancelled`, or `approved`; a present plan not yet approved keeps the row down, and the release's `# Status brief` says so), and the tester is dispatched on the operator's tick of that row. When the product declares a `staging` environment the release is deployed to it automatically first, and the row hangs only after that deploy of the current build succeeded; a failed deploy is journaled, the row does not hang, and the failed deploy hangs `Rebuild`. The deploy runs once per build number, the tester at most once per build number (`lazy-spec.release-playbook.md`, "Staging and tests"); a test-only `Rebuild` re-runs the staging deploy and hangs `Test` again for the new build number, and dispatches no tester itself. The `Write test-plan` row hangs from the moment the release is open until the `Test` job of the current build is dispatched, while the release has no `test-plan.md`, or has one at `cancelled`, and testing is not waived; after a `Rebuild` it hangs again for each new build, until that build's `Test` is dispatched. Its tick over a `cancelled` plan seeds a fresh plan that replaces the cancelled file (`seed-doc … --doc test-plan.md:test-plan --replace-cancelled`); until that new plan is written the cancelled one still counts as absent, and `Test` may run without one. The `test` tool never runs before the build is accepted.

**What is dispatched.** The role is `tester`; the expert is resolved mechanically as the main writer of the review class named after the tool's `report_doc` — the `test-report` class. The job's source is the release's `test-plan.md` when it exists and is not `cancelled`, else the included assets' start documents and their test cases — a cancelled plan not yet replaced by a fresh one is never the source. Context is the product's root `test-plan.md`, the included assets' folders, the product's guidelines for the tester's role and its wildcard guidelines, the `staging` address when the target declares one, and the release's `test-report.md` when it exists: the job returns the whole journal, every earlier entry intact plus its new `#### build <k>` entry. A member of `spec_includes` cancelled since it was included is left out of both lists (`lazy-spec.release-playbook.md`, "Staging and tests", step 2). Result is the release's `test-report.md`. The run has its own branch per build, `spec/<product>/releases/<n>/test-<k>`, and every continuation of the run reuses it; a continuation writes `spec_test_job` on the release note, never `spec_test_dispatched_at` (below).

**Where it runs.** The tester tests the product against `staging` when the product declares one, or against a local instance it brings up inside its own job when it does not. The run goes through the **product repository's own runner**; a red run is an outcome the job is obliged to record in the report, never a reason to stop quietly.

Each tester run opens a `#### build <k>` entry in `test-report.md`, `<k>` the `spec_build` value its dispatch names — the entry `spec_tests_passing` reads. One active job per release at a time: every `Test` dispatch, and every continuation of the run, is followed at once by `mark-job` with the label `Test`. A `Test` dispatch writes `spec_test_job` and `spec_test_dispatched_at` on the release note; a continuation writes `spec_test_job` alone, never `spec_test_dispatched_at`, so the moment keeps naming the run's own dispatch.

## What "done" means

`spec_tests_passing` closes when `test-report` is **accepted by review** — `review_result` reads `approved` or `approved-with-concerns` and `review_active` is not `true` — while it holds the `#### build <k>` entry of the current build, AND that entry is **green**. The journal carries no stage, so the verdict is never compared with `spec_test_dispatched_at`: `lazy-review.submit` clears an older verdict, and a verdict present after the run's report was submitted belongs to that run; the coordinator flips it with `flip-gate --auto` (`lazy-spec.release-playbook.md`, "Staging and tests"). Both conditions are required, and nothing else substitutes for either:

- an accepted but red report does not close the gate — it honestly records that tests do not pass, and hangs `Rebuild` on the release note, whose tick starts the implementer's next build;
- a green but unaccepted report does not close the gate — acceptance has not happened yet.

The `test` tool does not contribute to `spec_develop_done` at all: that gate closes on the accepted `code-report.md`, and `test` is neither a term of it nor a condition on it.

## Staleness

The source of this tool's report is `test-plan.md` of the release. A plan re-approved after `test-report.md` was accepted moves nothing by itself: the report keeps its stage-less journal form and the release's gates stay as they are; the next run continues the same expert against the re-approved plan, who opens the next `#### build <k>` entry in the journal and re-submits it.

Changes from below reach the plan through `Rebuild` (`lazy-spec.release-playbook.md`): re-approved test cases of an included feature — its own `test-plan.md` — hang the row, and its tick returns the release's `test-plan.md` to `draft` and turns `spec_tests_passing` and `spec_built` off. A re-approved design reaches further: the tick returns both release plans to `draft` and turns `spec_develop_done`, `spec_tests_passing` and `spec_built` off together.

## The acceptance cycle

Review of a `test-report` is acceptance of the **verification**, not copy-editing of the report's text.

- A reviewer's comment means "verify again": extend or fix the tests, re-run them, extend the report. Rewriting the report's conclusions without a new run is a way around the cycle, not through it.
- A redo runs as a **continuation to the same expert** — same job expert, same `branch`, with `test-report.md` named in its `context`.
- The report is append-only: every run iteration is appended, earlier ones are never rewritten — the history of red runs is precisely what the report exists to keep.
- A red run caused by a defect in code, data or documentation is fixed by the release implementer in the next build, which the `Rebuild` tick starts: the `test` tool presents the failure, it does not repair another tool's work.
