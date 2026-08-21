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

_Code-structure design — populated once the feature's `design.md` is approved, for any feature whose work involves code. Module boundaries, dependency direction, public contract versus internals, data migration, and the cost to existing callers. Not behavior — `design.md` already settled WHAT the feature does; this doc settles the SHAPE of the code that does it._

## Overview
_What part of the codebase this touches and why an architecture step is warranted here._

## Module boundaries
_Which modules/components own which responsibility; public contract versus internals; dependency direction between them._

## Data & contracts
_Data shapes, schemas, and interfaces the feature introduces or changes — the seams other code will call across._

## Dependencies & children
_External dependencies this design pulls in; any sub-feature this decomposes into, proposed via the `[!asset-proposal]` callout rather than created directly._

## Migration & cost
_Data or schema migration this introduces; the cost to existing callers — what breaks, what must be updated alongside this feature._

# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
<!-- auto:spec-requests:end -->

## Docs
<!-- auto:spec-docs:start -->
<!-- auto:spec-docs:end -->
