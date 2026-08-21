---
tags:
  - {{product_tag}}
spec_role: test-report
spec_doc_type: test-report
wiki_pinned_topics:
  - wiki/doc-kind/test-report
  - wiki/product/{{product}}
  - wiki/category/{{category}}
---
# {{slug}} — test-report

_Append-only working journal, written during execution — never after the fact._

## Verdict
_What is proven to work, what is not, and what was left unexercised._

## Defects
_What broke, with the verbatim decisive output and the shortest steps to reproduce it._

## Open questions
_Questions against the plan or the spec that only the operator can answer, still unanswered._

## Unresolved problems
_What obstructed the run and was not solved — an environment that could not be reached, a step nothing could execute, a case that stayed flaky without explanation. Problems of the run, not defects of the product._

## Decisions taken alone
_Departures from the plan made without the operator — substituted data, a skipped step, a chosen environment — and the grounds for each._

## Log
_One entry per test of the plan, in its order and under its name: actual result against expected. A block carrying a `Cases` list gets one entry naming the cases that failed, not one entry per case. A test that could not run is recorded as blocked, with the reason._
