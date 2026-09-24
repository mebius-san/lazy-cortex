---
tags:
  - {{product_tag}}
  - spec/empty
spec_role: architecture
spec_doc_type: architecture
wiki_pinned_topics:
  - wiki/doc-kind/architecture
  - wiki/product/{{product}}
  - wiki/category/{{category}}
spec_stage: empty
spec_source_requests: []
spec_source_docs: []
---
# {{slug}} — architecture
<!-- The shape of the code that does what the sibling design settled: module boundaries, dependency direction, public contract versus internals, data migration, and the cost to existing callers. It is written once the design is approved, for an asset whose work involves code. What the asset does lives in the design, never here. -->

## Overview
<!-- What part of the codebase this touches and why an architecture step is warranted. A few sentences of prose. What the asset does lives in the sibling design. -->

## Terms
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The terms this document uses, with their meaning. One line per term, alphabetical; a term the repository's dictionary already defines carries that definition verbatim, and a term this document introduces is defined here first. A term the document does not use does not belong here. -->

## Module boundaries
<!-- The static decomposition of the code: which modules or components own which responsibility, and the dependency direction between them. One bullet per module: its responsibility, its public contract, and what stays internal. The data crossing those boundaries lives in Data & contracts. -->

## Data & contracts
<!-- The data shapes, schemas and interfaces the asset introduces or changes, the seams other code will call across. One bullet per shape or interface. Which module owns it lives in Module boundaries. -->

## Dependencies & children
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The external dependencies this design pulls in, and any child asset this one decomposes into. One bullet per dependency or child; a child is proposed via the `[!asset-proposal]` callout, never created directly. The cost of changing existing callers lives in Migration & cost. -->

## Migration & cost
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The data or schema migration this introduces and the cost to existing callers. One bullet per migration or breaking point: what breaks, and what must be updated alongside this asset. A new dependency lives in Dependencies & children. -->

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
