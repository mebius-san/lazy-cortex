---
since: 10.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-notes, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

Several keys and rows a spec note carried were retired. The middle rungs of the asset ladder (`spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and their `*_at` stamps) are gone from every asset type but a release and a research asset; the asset dependency list `spec_depends_on` and its `spec_state: blocked` state are gone; a level note no longer keeps `spec_coordinator_child_wake_state`, and its `# Gates` section no longer has a `Revise design` row. A note that still carries them shows gates and rows the plugin no longer reads or updates, and an asset left at `blocked` stays there, since nothing clears that state any more.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-notes --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-notes --check --cwd "<repo-root>"` exits 1: no status or level note under the spec catalog still carries a retired key, a `blocked` state or a `Revise design` row.
