---
since: 14.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-plan-context, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
---
## Why

The build no longer reads who makes what from the asset or its type. The product's specialists are computed per product by `resolve-product`: the coordinator hands them to the release implementer on every `Build`, and the review plugin hands them to the planner as a context file, `specialists.json`, through the `context_from_verbs` field of the `code-plan` review class, which runs `resolve-product specialists-by-path` on the plan. Install seeds that field on a new `code-plan` class only; a consumer whose settings already hold the class keeps it without the field, so the planner writes `code-plan.md` with no specialist list and names no specialist on a task whose material code does not make. The same holds for a `code-plan` class an operator keeps in the gitignored local overlay `.claude/lazy.settings.local.json`; the step migrates the overlay's `review.classes` as well, reading and writing each file alone, never as the merged view, and never creating an overlay that does not exist.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-plan-context --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-plan-context --check --cwd "<repo-root>"` exits 1: in both `.claude/lazy.settings.json` and `.claude/lazy.settings.local.json`, the shared `code-plan` class and every product-scoped `code-plan@<key>` class carries a `context_from_verbs` field; a field the operator already set, an empty list included, is left as written.
- The JSON answer of step 2 reports the tracked file in `action` and `classes`, and the local overlay in `local_action` and `local_classes`.
