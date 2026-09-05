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

## Scope
<!-- What is under test, and what is deliberately left out of this run. -->

## Mechanisms
<!-- The testing mechanisms this repository actually ships — runners, fixtures, harnesses, CI targets — verified present before the tests below were written. -->

## Preconditions
<!-- "Precondition: The required state of a test item and its environment prior to test case execution." — ISTQB Glossary -->

## Exit criteria
<!-- "Exit criteria: The set of conditions for officially completing a defined task." — ISTQB Glossary -->

## Tests
<!-- "Test case: A set of preconditions, inputs, actions (where applicable), expected results and postconditions, developed based on test conditions." — ISTQB Glossary -->

### _Test name_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Preconditions**: _only when they differ from the common ones._
- **Priority**: high | medium | low

#### Steps

1. _Concrete command or action._
2. _Next._

#### Expected

<!-- The observable outcome that counts as pass. -->

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
