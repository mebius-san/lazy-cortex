---
tags:
  - {{product_tag}}
  - spec/draft
spec_role: research
spec_doc_type: research-report
wiki_pinned_topics:
  - wiki/doc-kind/research
  - wiki/product/{{product}}
  - wiki/category/{{category}}
spec_stage: draft
spec_source_requests: []
spec_source_docs: []
---
# {{slug}} — research
<!-- The answer to the sibling research design: the conclusion per question first, then the findings it rests on, the options compared, the routes walked, and the sources. It is written by the researcher for the reader who makes the decision, and once approved it is immutable; a wrong conclusion is answered by a new research asset citing this one. A gap in the design is raised there as a `[!question]` callout, never filled in here, and the record of the walk itself belongs in no section of the report. -->

## Conclusion
<!-- The answer to every question of the design. One paragraph per question, in the design's order: the answer in its first sentence, then the verdict on its hypothesis stated outright, then the recommendation, what it rests on, the confidence, and the conditions under which the answer would change. The evidence lives in Findings. -->

## Findings
<!-- The facts the conclusion rests on, grouped by the subject they describe. One bullet per finding, each with its source: a repo-relative path, a wiki node, or a URL, with fact and interpretation in separate sentences. A finding without a source, a finding no conclusion uses, and the record of the walk (counts of pages viewed, failed or empty fetches, runs that turned up nothing new) do not belong here. -->

## Options
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The alternatives compared, when a question is a choice. One subsection per option: how it scores against each criterion of the design. The verdict lives in Conclusion. -->

## Method
<!-- The routes walked: spec tree, code, structure map, wiki, external sources. One short list with one bullet per route, in the order walked, internal routes before the internet. What each route yielded lives in Findings, and the record of the walk itself stays out of the report. -->

## Sources
<!-- Every source the findings cite, once. One bullet per source: internal paths via `lazy-spec.source-url`, external URLs verbatim. This is the only authored spec document where an external URL is permitted, here and beside the finding that uses it. -->

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
