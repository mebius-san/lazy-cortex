---
tags:
  - {{product_tag}}
  - spec/draft
product: {{product}}
spec_role: test-plan
spec_doc_type: system-test-plan
wiki_pinned_topics:
  - wiki/doc-kind/test-plan
  - wiki/product/{{product}}
spec_stage: draft
spec_source_requests: []
spec_source_docs: []
---
# {{product}} — test-plan
<!-- The standing instructions for testing the product: the mechanisms the repository ships, the environment a run needs, what counts as a smoke test and what the regression covers. It is read first by every release's tester and holds what does not change from release to release. The test cases of one asset live in that asset's test-plan, and the plan of one run lives in the release's test-plan. -->

## Terms
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The terms this document uses, with their meaning. One line per term, alphabetical; a term the repository's dictionary already defines carries that definition verbatim, and a term this document introduces is defined here first. A term the document does not use does not belong here. -->

## Mechanisms
<!-- The testing mechanisms this repository actually ships: runners, fixtures, harnesses, CI targets. One bullet per mechanism, verified present before it is named. A mechanism the repository does not ship does not belong here. -->

## Environment
<!-- Where a test run happens: the staging target when the product has one, otherwise how a local instance is brought up, and what it needs to be seeded with. One bullet per environment or step, in the order a tester performs them. The command of a deploy target lives in the product's settings, never here. -->

## Smoke
<!-- The checks that prove the product is up at all after a deploy, before any deeper test runs. One bullet per check with its expected outcome. A check that exercises one asset's behaviour lives in that asset's test-plan. -->

## Regression
<!-- The suites and checks every release runs regardless of what its delta touched. One bullet per suite or check with the command or route that runs it. The tests of the delta itself live in the release's test-plan. -->

## Exit criteria
<!-- The conditions under which any release's test run counts as complete. One bullet per condition, checkable from the release's test-report. A condition specific to one release lives in that release's test-plan. -->

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
