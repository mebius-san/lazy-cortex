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
<!-- How the asset is accepted: what is under test, the mechanisms the repository ships, the criteria for finishing, and the tests themselves. It is written against the sibling design. What the run returned lives in the test-report. -->

## Scope
<!-- What is under test and what is deliberately left out of this run. One bullet per item in and per item out. What proves the run complete lives in Exit criteria. -->

## Mechanisms
<!-- The testing mechanisms this repository actually ships: runners, fixtures, harnesses, CI targets. One bullet per mechanism, verified present before the tests below were written. A mechanism the repository does not ship does not belong here. -->

## Preconditions
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The state the test item and its environment must be in before any test runs. One bullet per condition. A condition specific to one test lives in that test's block. -->

## Exit criteria
<!-- The conditions under which the run counts as complete. One bullet per condition, checkable from the report. What is in or out of the run lives in Scope. -->

## Tests
<!-- The test cases, in three shapes: one procedure with its expected outcome, one procedure over many inputs, and a checklist over one area. One block per test in the shapes below, with type, risk and priority. The mechanisms the tests use live in Mechanisms. -->

### _Test name_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Preconditions**: _only when they differ from the common ones._
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
