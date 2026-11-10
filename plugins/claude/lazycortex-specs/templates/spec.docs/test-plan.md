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
<!-- The test cases that prove this asset does what its design says. It is written against the sibling design and read by the tester of every release that carries the asset, who folds the cases into the release's own test-plan. The mechanisms, the environment and the exit criteria of a run live in the product's test-plan, and what a run returned lives in the release's test-report. -->

## Scope
<!-- What the cases below cover and what they deliberately leave out. One bullet per item in and per item out. How a run is set up and when it counts as complete lives in the product's test-plan. -->

## Tests
<!-- The test cases, in three shapes: one procedure with its expected outcome, one procedure over many inputs, and a checklist over one area. One block per test in the shapes below, with type, risk and priority. The mechanisms the tests use live in the product's test-plan. -->

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
