---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-upstream-history, --check]}
writes:
  - "upstream/**/*.md"
---
## Why

An earlier release wrote the `# History` section of an upstream unit note as a flat list, newest line first, each line carrying its own date. Every history section is now grouped under one `#### <date>` heading per day, oldest day first, and the journal writer appends new lines to that layout only. A unit note left in the old format mixes the two layouts as soon as the next line lands.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-upstream-history --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-upstream-history --check --cwd "<repo-root>"` exits 1: no upstream unit note under `upstream/` still keeps a `# History` line in the old flat format.
