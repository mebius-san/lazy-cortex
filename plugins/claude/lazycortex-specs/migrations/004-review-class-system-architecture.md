---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-review-class, --check]}
writes:
  - ".claude/lazy.settings.json"
---
## Why

An earlier release seeded the product-root `architecture.md` under a review class named `architecture`; the class is now `system-architecture`. A consumer whose settings still hold the old entry keeps reviewing that document under a class name the plugin no longer seeds or refers to.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-review-class --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-review-class --check --cwd "<repo-root>"` exits 1: the settings hold no `architecture` review class; it was renamed to `system-architecture`, or dropped where `system-architecture` already existed.
