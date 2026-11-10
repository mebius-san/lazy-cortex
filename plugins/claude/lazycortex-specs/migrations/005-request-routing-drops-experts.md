---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-requests, --check]}
writes:
  - "{spec_root}/requests/*.md"
---
## Why

A `spawn-product` decision line in a spec request once named the role experts of the product it registers, in an `experts=` field. That field was retired, and an open request whose decision line still carries it fails its apply transition. Closed requests are history and stay as they are.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-requests --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-requests --check --cwd "<repo-root>"` exits 1: no open request still carries `experts=` on a `spawn-product` line.
