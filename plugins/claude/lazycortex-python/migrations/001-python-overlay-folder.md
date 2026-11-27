---
since: 5.0.0
supersedes: []
applies_when:
  - {path_exists: "docs/guidelines/*ing_guidelines.md"}
writes:
  - "docs/guidelines/**"
---
## Why

The Python overlays moved from `docs/guidelines/<topic>_guidelines.md` to `docs/guidelines/python/<topic>_guidelines.md`, for the topics `coding`, `documenting`, `testing` and `checking`. The old name carried no language, so a second language plugin scaffolding the same names would share one file with Python. The writer agents, the rules, `/lazy-python.audit` check 7, the `chk-py review` overlay layer and the `provides_guidelines` canon now read only `docs/guidelines/python/`. A consumer that installed the old version keeps its overlays at the old path: no reader sees them any more, and the next `/lazy-python.install` scaffolds empty stubs at the new path beside them.

Each step moves one old overlay into `docs/guidelines/python/` when the new path does not exist yet. When both exist, the step leaves both in place and its receipt reports `kept-both` with the pair, because it cannot tell which one the operator means to keep. A step whose old overlay is absent reports `absent` and changes nothing. `docs/guidelines/domain-groups.md` and every other language-neutral guide stay where they are.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> move-file --src "<repo-root>/docs/guidelines/coding_guidelines.md" --dst "<repo-root>/docs/guidelines/python/coding_guidelines.md"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> move-file --src "<repo-root>/docs/guidelines/documenting_guidelines.md" --dst "<repo-root>/docs/guidelines/python/documenting_guidelines.md"`
3. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> move-file --src "<repo-root>/docs/guidelines/testing_guidelines.md" --dst "<repo-root>/docs/guidelines/python/testing_guidelines.md"`
4. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> move-file --src "<repo-root>/docs/guidelines/checking_guidelines.md" --dst "<repo-root>/docs/guidelines/python/checking_guidelines.md"`

## Done when

- For each topic `coding`, `documenting`, `testing`, `checking`: `<repo-root>/docs/guidelines/<topic>_guidelines.md` is absent, or it is present together with `<repo-root>/docs/guidelines/python/<topic>_guidelines.md` and its step's receipt reported `kept-both`, the pair named for the operator to settle.
- Every receipt's `state` is `moved`, `kept-both` or `absent`; none is `failed`.
