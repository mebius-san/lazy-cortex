## Why this plugin

`lazycortex-specs` keeps a product's specifications next to its code as ordinary Markdown notes in an Obsidian-friendly vault, and gives Claude Code the skills to author and maintain that structure so you don't carry it in your head. A product is registered once in `lazy.settings.json[products]`; its work is organised into assets — built-in `feature` / `change` / `bug` plus any operator-defined categories (characters, scenes, …) you declare. Each asset advances through five flat, linear readiness gates (`spec_design_done` … `spec_released`), and the plugin keeps the spec aligned with the source repo, links sections to specific branches, and audits for drift.

The plugin manages *structure* and *lifecycle*, not the prose — authoring stays with the operator (and, optionally, the `lazycortex-review` cycle).

## Who it's for

- **Teams who write specs and design docs alongside code** in the same repo and want skills that understand spec conventions, gate state, and source links.
- **Non-software products** (games, books, courses) that model their work as operator-defined asset categories under the same gate-and-review machinery.

## Blocks

- **authoring** — Create and populate spec assets of any category. Members: spec.create-asset, spec.create-feature, spec.create-change, spec.create-bug, spec.add-asset-category, spec.create-from-code, spec.create-request.
- **gates** — Drive an asset's readiness gates and per-file stages. Members: spec.flip-gate, spec.gate-tick, spec.set-stage.
- **code-sync** — Keep specs aligned with the source repo across commits and branch merges. Members: spec.sync-with-code, spec.finalize-branch.
- **source-links** — Resolve repos, dependencies, and forge-correct source URLs. Members: spec.resolve-repo, spec.resolve-dependency, spec.source-url.
- **requests** — Ingest free-form requests and route them into the spec tree. Members: spec.request-router, spec.request-classify, spec.request-find-candidates, spec.request-attach, spec.request-spawn.
- **install-and-audit** — Bootstrap, configure a product, and audit a spec in this repo. Members: spec.install, spec.product-config, spec.doctor, spec.help.

## Walkthroughs

- **new-product-from-code** — Register a product and generate its spec from an existing codebase. Path: spec.product-config → spec.create-from-code → spec.create-feature.
- **asset-to-release** — Take one asset from creation through its gates to release. Path: spec.create-asset → spec.set-stage → spec.flip-gate → spec.sync-with-code → spec.finalize-branch.

## Requirements

- **Claude Code** with plugin support.
- **lazycortex-core** — provides the `products` / `spec` settings sections, the `settings-get` / `settings-set` CLI, and the runtime daemon that drives the `spec.gate-tick` md-scan routine.
- **lazycortex-review** (v4) — the shared behavior-keyed review classes that `spec.product-config` generates once per vault (one class per doc-kind, right-anchored wildcard globs spanning every product and asset category; a product with divergent experts gets a per-product override).
- **lazycortex-diagram** — draws the behavioral / architecture diagrams that creation skills request.
- **lazycortex-experts** *(optional)* — supplies the designer / developer / tester personas wired into review classes.

## Quick start

1. `/spec.install` — create consumer dirs, register the gate-tick routine, optionally seed the repo's default language.
2. `/spec.product-config` — register your first product (path, source repo, icon, review experts) in `lazy.settings.json[products]`.
3. `/spec.create-feature <product> <slug>` — scaffold your first asset, then let the gates and review cycle carry it forward.
