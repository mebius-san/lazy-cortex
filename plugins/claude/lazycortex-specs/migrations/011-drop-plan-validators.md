---
since: 13.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-plan-validators, --check]}
writes:
  - ".claude/lazy.settings.json"
---
## Why

An earlier release seeded validators on the review classes of the plan documents: `tester_review` and `architect_review` on `code-plan`, `developer_review` on `test-plan` and `system-test-plan`. The plan classes now carry no validators: a release's test plan is not written from its code plan, and the developer does not work from a test plan, so neither validator had a document of its own to judge the plan for. A consumer whose settings still hold those blocks keeps dispatching validators the plugin no longer seeds or describes.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-plan-validators --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-plan-validators --check --cwd "<repo-root>"` exits 1: none of the `code-plan`, `test-plan` and `system-test-plan` review classes carries an `experts.validation` block; a product-scoped `<kind>@<key>` class is left as the operator wired it.
