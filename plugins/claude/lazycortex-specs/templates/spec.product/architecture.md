---
tags:
  - {{product_tag}}
  - spec/draft
product: {{product}}
spec_role: architecture
spec_doc_type: system-architecture
wiki_pinned_topics:
  - wiki/doc-kind/architecture
  - wiki/product/{{product}}
spec_stage: draft
spec_source_requests: []
spec_source_docs: []
---
# {{product}} — architecture
<!-- The shape of the product's code: module boundaries, dependency direction, public contracts versus internals, and the cost of changing existing callers. It is the standing document every release's plan is written against, kept current with the approved designs before a release starts. What the product does lives in the sibling design, and the technologies it is built with live in the sibling tech. -->

## Overview
<!-- The parts of the codebase the product owns and the shape they form together. A few sentences of prose. What the product does lives in the sibling design. -->

## Terms
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The terms this document uses, with their meaning. One line per term, alphabetical; a term the repository's dictionary already defines carries that definition verbatim, and a term this document introduces is defined here first. A term the document does not use does not belong here. -->

## Module boundaries
<!-- The static decomposition of the code: which modules or components own which responsibility, and the dependency direction between them. One bullet per module: its responsibility, its public contract, what stays internal, and where its unit tests sit and the seam they reach it through. The data crossing those boundaries lives in Data & contracts. -->

## Data & contracts
<!-- The data shapes, schemas and interfaces the product exposes between its modules and to the outside, the seams other code calls across. One bullet per shape or interface. Which module owns it lives in Module boundaries. -->

## Dependencies
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The external dependencies the code relies on and the boundary each one is kept behind. One bullet per dependency. The cost of changing existing callers lives in Migration & cost. -->

## Migration & cost
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The migrations the current structure still owes and the cost a change of structure imposes on existing callers. One bullet per migration or breaking point: what breaks, and what must move with it. A new dependency lives in Dependencies. -->

## Proposed assets
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The assets the product is missing, found while writing or revising this document. One `[!asset-proposal]` callout per asset; once this document is approved the coordinator materializes each one, and the new asset enters a release like any other, once its own start document is approved. An existing asset merely worth mentioning is prose in the section it concerns, never a proposal. -->

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
