---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, pins, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

A spec document's product tag moved under the product namespace: it is now `product/<spec_path>`, the product's whole tree path, where an earlier release wrote the bare last segment of that path or `product/<leaf>`. Documents written before the change keep the old tag, so tag views and queries that group a product's documents by the current form miss them, and a document relocated into a nested product still carries the enclosing product's tag and `wiki/product/` pin. The same pass adds the `wiki_pinned_topics` block to every role-bearing document that lacks one.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> pins --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> pins --check --cwd "<repo-root>"` exits 1: no document under the spec catalog still needs its product tag, product pin or `wiki_pinned_topics` block rewritten.
