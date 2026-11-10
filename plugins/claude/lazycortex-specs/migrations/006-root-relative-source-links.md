---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-source-links, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

An earlier release linked a spec document to the product's code through the forge's web view, and could pin those links to a branch with a `spec_source_branches` frontmatter key. The code now lives in the catalog's own repository and is linked by root links `[<name>](/<path>)`; the branch key is retired. A document keeping the old forge links points at a web page instead of the file in the same repository, and keeps a key the plugin no longer reads.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-source-links --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-source-links --check --cwd "<repo-root>"` exits 1: no document under the spec catalog still links a file of this repository through the forge, or carries `spec_source_branches`.
