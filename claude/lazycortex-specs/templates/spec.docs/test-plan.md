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
_What is under test, and what is deliberately left out of this run._

## Mechanisms
_The testing mechanisms this repository actually ships — runners, fixtures, harnesses, CI targets — verified present before the tests below were written._

## Preconditions
_Environment, data, and state every test below assumes, and how to restore it afterwards. A test that needs something different says so in its own block._

## Exit criteria
_When the run counts as finished: which priorities must have been executed, what may still be open, what blocks the verdict._

## Tests
_One `###` block per test, executable by someone who did not write it. Three forms below — keep the ones that fit, delete the rest. One procedure with one outcome takes the first form. The same procedure over different inputs takes the second: the steps are written once and each input is a line under `Cases`. A set of independent checks sharing only their area and type takes the third. A check that needs steps of its own is a block of its own._

### _Test name_
- **Type**: _one of the tester's test types._
- **Risk**: _what breaking here would mean._
- **Preconditions**: _only when they differ from the common ones._
- **Priority**: high | medium | low

#### Steps

1. _Concrete command or action._
2. _Next._

#### Expected

_The observable outcome that counts as pass._

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
