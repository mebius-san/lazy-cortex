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
<!-- The working journal of one test run: the verdict against the plan's exit criteria, the defects found, what stayed open, and the log of every step. It is append-only and written during execution, never after the fact. What was to be tested lives in the sibling test-plan. -->

## Verdict
<!-- The evaluation of the run against the plan's exit criteria. One line per criterion: met or not, with the evidence. The defects behind an unmet criterion live in Defects. -->

## Defects
<!-- The defects the run found. One bullet per defect: the occurrence, its nature, and its status. A problem of the run itself, not of the product, lives in Unresolved problems. -->

## Open questions
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The questions against the plan or the spec that only the operator can answer and that are still unanswered. One bullet per question, naming the test it blocks. A departure already made lives in Decisions taken alone. -->

## Unresolved problems
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. What obstructed the run and was not solved: an environment that could not be reached, a step nothing could execute, a case that stayed flaky without explanation. One bullet per problem: what obstructed, and what was tried. A defect of the product lives in Defects. -->

## Decisions taken alone
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The departures from the plan made without the operator: substituted data, a skipped step, a chosen environment. One bullet per departure, with the grounds. A question left for the operator lives in Open questions. -->

## Log
<!-- The chronological record of the run. One entry per test executed, in order: what was run and what it returned. The evaluation of the whole lives in Verdict. -->
