---
since: 11.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-source-links, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

The earlier source-link step recognized the repository's own forge only when its remote was a URL or `user@host:owner/repo`. A repository whose remote names an ssh config alias, such as `<alias>:owner/repo.git`, was skipped: the alias was not read as a host, and even read, it never equalled the forge host its links carry. The verb now resolves the alias through the ssh config, so the forge links such a repository still holds into its own code become root links `[<name>](/<path>)` like everywhere else.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-source-links --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-source-links --check --cwd "<repo-root>"` exits 1: no document under the spec catalog still links a file of this repository through the forge, or carries `spec_source_branches`.
