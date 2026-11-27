---
tags:
  - {{product_tag}}
  - spec/empty
spec_role: test-plan
spec_doc_type: test-plan
wiki_pinned_topics:
  - wiki/doc-kind/test-plan
  - wiki/product/{{product}}
  - wiki/category/{{category}}
spec_stage: empty
spec_source_requests: []
spec_source_docs: []
---
# {{slug}} — test-plan
<!-- How the deployed release is accepted: what is under test, the mechanisms the repository ships for testing a running product, the criteria for finishing, and the tests themselves. It is composed from the product's standing test-plan, the test cases of every asset the release carries, and the product's regression, in that order. The unit tests of the code live in the build and its code-report, and what the run returned lives in the test-report. -->

## Scope
<!-- What is under test and what is deliberately left out of this run. One bullet per item in and per item out. What proves the run complete lives in Exit criteria. -->

## Inputs
<!-- The documents this run's tests are drawn from: the product's standing test-plan and the test-plan of every asset in the release's `spec_includes`. One wikilink per document, product first. What those documents say is not repeated here. -->

## Mechanisms
<!-- The mechanisms this repository actually ships for testing the deployed product: runners, fixtures, harnesses and CI targets that exercise a running instance. One bullet per mechanism, verified present before the tests below were written. A mechanism the repository does not ship does not belong here, and neither does the unit-test runner, which belongs to the build. -->

## Preconditions
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The state the test item and its environment must be in before any test runs. One bullet per condition. A condition specific to one test lives in that test's block. -->

## Exit criteria
<!-- The conditions under which the run counts as complete. One bullet per condition, checkable from the report. What is in or out of the run lives in Scope. -->

## Tests
<!-- The test cases run against the deployed product, in three shapes: one procedure with its expected outcome, one procedure over many inputs, and a checklist over one area. One block per test in the shapes below, with type, risk and priority; tests that rely on the state an earlier test leaves form a chain in an order that runs as written, and tests that cannot join one chain form separate chains, each opening with explicit steps that bring the system into the state it needs. The mechanisms the tests use live in Mechanisms, and a unit test, a test run entirely on stubs or a check that reads the sources belongs to the build, never here. -->

### _Test name_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Preconditions**: _only when they differ from the common ones._
- **State in**: _the state this test needs from an earlier test of its chain; only in a chain._
- **State out**: _the state this test leaves for a later test of its chain; only in a chain._
- **Priority**: high | medium | low

#### Steps

1. _Concrete command or action._
2. _Next._

#### Expected
<!-- The observable outcome that counts as pass. One or two sentences. The actions producing it live in Steps. -->

### _Test name — one procedure over many inputs_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Priority**: high | medium | low

#### Steps

1. _The procedure, applied to each case below._

#### Cases

- _Case name_ — input: _…_ — expected: _…_ — priority: _…_
- _Case name_ — input: _…_ — expected: _…_ — priority: _…_

### _Test name — checklist over one area_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Priority**: high | medium | low

#### Checks

- _One independent check, phrased so that the expected outcome is part of the statement._
- _Another one. No shared procedure and no steps — a check that needs steps is a block of its own._

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
