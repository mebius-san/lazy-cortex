---
since: 14.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-spec-tools, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
  - "{spec_root}/**/*.md"
---
## Why

Nothing on an asset or on an asset type says who builds it any more: the release implementer builds the whole product and orders material that code does not make from the product's specialists. The tool layer is gone with it. The `spec_tools` key is gone from status folder-notes: `note-set-key` refuses it and `note-check` reports a leftover as `unknown-key`. The coordinator no longer asks the operator for an asset's tool set, so a tool-set `[!question]` an earlier release left in `# Status brief` waits for an answer nothing reads and keeps the asset in `waits-operator`. The asset-type settings `default_tools` and `tools` are no longer read, and a product's own `tool_types` declarations have no reader either; the step leaves them in place and names them, because what they meant is the operator's to carry over. The `data-report` and `docs-report` document types and their review classes are no longer shipped or seeded: a class with no document of its type left in the repository has nothing to review and is dropped, while a class whose documents still exist stays, so those documents keep their reviewer until the operator decides what becomes of them. An operator may keep `products` and `review` entries in the gitignored local overlay `.claude/lazy.settings.local.json`; the settings part of the step applies to the overlay as well, with the same rule for a report class, while the notes are files and are walked once. Each settings file is read and written alone, never as the merged view, and an overlay that does not exist is never created.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-spec-tools --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-spec-tools --check --cwd "<repo-root>"` exits 1: no status folder-note under the spec content root carries `spec_tools`, no `# Status brief` holds a tool-set question, and in neither `.claude/lazy.settings.json` nor `.claude/lazy.settings.local.json` does a `products.<key>.asset_types.<type>` entry carry `default_tools` or `tools`, or a bare `data-report` or `docs-report` review class remain whose document type no document under the spec content root carries.
- The JSON answer of step 2 lists in `classes_kept` each `data-report` or `docs-report` class left in place with the documents that hold it, in `classes_scoped` each product-scoped `<kind>@<key>` class of those two kinds left as the operator wired it, and in `tool_types_found` each `products.<key>.tool_types.<name>` declaration for the operator to settle; none of the three counts as pending work. The settings keys `fields_dropped`, `classes_dropped`, `classes_kept`, `classes_scoped` and `tool_types_found` report the tracked file; their `local_` twins report the local overlay the same way.
- This step does not rewrite `spec_state` or the `# Status brief` prose. The migration commit carries `Lazy-Watch: skip` and wakes no coordinator, so an asset whose question was cut keeps its old `spec_state` until its next wake. A ticked option in a cut question is dropped with it, because nothing reads that answer any more.
