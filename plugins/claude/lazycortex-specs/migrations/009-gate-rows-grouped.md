---
since: 11.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-gate-rows, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

An earlier release wrote every launch row in the `# Gates` section of a spec folder note as a `[!gate]` callout of its own: the label in the title, the same label on the checkbox line, and a hint under each checkbox. The `review-rows` verb now writes one `[!gate]` callout per row verb inside each layout group, titled by the verb, holding the checkboxes of every row of that verb and one shared footer line. The verb reads both shapes, but a note left in the old shape is folded only on its next wake, so until then it shows one block per row beside notes in the grouped shape.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-gate-rows --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-gate-rows --check --cwd "<repo-root>"` exits 1: no status, product or catalog note under the spec content root still carries a `# Gates` section outside the grouped shape.
