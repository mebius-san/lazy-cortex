---
since: 16.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-legacy-gates, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

Earlier releases hung launch rows in the `# Gates` section of spec notes that the plugin no longer declares: `Start implementation (<tool>)` for any tool, `Start testing`, `Start coding`, `Start data entry` and `Start documentation`; `Revise design` in the grouped shape, which the `migrate-notes` step only took down in the old one-row-per-block shape; and, on an asset note other than a release, a per-tool `Write <tool>-plan` row (any plan but the asset's own `Write test-plan`), `Write architecture` and `Publish`. No step removed them. Nothing reads such a row any more, yet the layout keeps a ticked one ticked for good, and the tick check raises an extra `tick-pending` wake behind every real wake of its asset; on a research note a leftover `Start implementation (research)` row hangs beside the current `Start research`. Research notes also still carried the middle rungs of the release ladder — `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_built` and their `*_at` stamps — although a research asset carries only `spec_design_done` and `spec_released`, and `flip-gate` lets only a release open the middle rungs. The step drops those rows, ticked or not, from the status and level notes, together with a gate callout or a group sub-heading they leave empty, and drops those keys from research status notes. A leftover row is never renamed into a current one, because an old tick would then launch work nobody asked for now; the coordinator hangs the current rows itself on the asset's next wake.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-legacy-gates --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-legacy-gates --check --cwd "<repo-root>"` exits 1: no status, product or catalog note under the spec content root still carries a retired launch row in its `# Gates` section, and no research status note carries `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_built` or one of their `*_at` stamps.
- Rows inside a code fence and rows outside `# Gates` are left as written, and every current row — `Start research`, `Start release`, `Revise architecture`, a release note's `Write code-plan`, `Build`, `Write test-plan`, `Test`, `Rebuild` and `Publish`, a product note's `Write architecture`, every `Write <doc>` row of an asset's own documents and every `Review <doc>` row — keeps its line and its tick.
- This step does not rewrite `spec_state` or the `# Status brief` prose. The migration commit carries `Lazy-Watch: skip` and wakes no coordinator, so an asset whose leftover row was dropped keeps its old `spec_state` and brief until its next wake.
