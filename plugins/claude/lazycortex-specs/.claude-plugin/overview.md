## Why this plugin

`lazycortex-specs` keeps a product's specifications next to its code as ordinary Markdown notes in an Obsidian-friendly vault, and gives Claude Code the skills to author and maintain that structure so you don't carry it in your head. A product is registered once in `lazy.settings.json[products]`; its work is organised into assets — built-in `feature` / `change` / `bug` / `content` / `research` plus any operator-defined categories (characters, scenes, …) you declare. Every asset is design-only: its note carries `spec_design_done`, closed by the approval of its start document, and `spec_released`, closed by the release that ships it (a `research` asset's by the approval of its report). Only a `release` walks the five flat, linear readiness gates (`spec_design_done` … `spec_released`), and the plugin keeps the spec aligned with the product's code in the same repository, links sections to the code files they describe, and audits for drift.

The plugin manages *structure* and *lifecycle*, not the prose — authoring stays with the operator (and, optionally, the `lazycortex-review` cycle).

## Who it's for

- **Teams who write specs and design docs alongside code** in the same repo and want skills that understand spec conventions, gate state, and source links.
- **Non-software products** (games, books, courses) that model their work as asset types of their own under the same gate-and-review machinery.

## Blocks

- **authoring** — Create and populate spec assets of any asset type. Members: lazy-spec.create-asset, lazy-spec.create-feature, lazy-spec.create-change, lazy-spec.create-bug, lazy-spec.add-asset-type, lazy-spec.create-from-code, lazy-spec.create-request, lazy-spec.record-decision.
- **gates** — Drive an asset's readiness gates and per-file stages, and settle the conflicts the coherence check finds between approved documents. Members: lazy-spec.flip-gate, lazy-spec.gate-tick, lazy-spec.set-stage, spec.coherence-checker.
- **code-sync** — Keep specs aligned with the product's code across commits. Members: lazy-spec.sync-with-code, lazy-spec.coverage.
- **upstream** — Mirror external design sources, route their changes through the request pipeline, and keep a spec doc's visible source list matching its frontmatter. Members: lazy-spec.upstream-run, lazy-spec.refresh-sources.
- **source-links** — Resolve dependencies and build root links to the product's code files. Members: lazy-spec.resolve-dependency, lazy-spec.source-url.
- **requests** — Ingest free-form requests and route them into the spec tree. Members: lazy-spec.catalog-coordinator, lazy-spec.request-classify, lazy-spec.request-find-candidates.
- **install-and-audit** — Bootstrap, configure a product, and audit a spec in this repo. Members: lazy-spec.install, lazy-spec.product-config, lazy-spec.audit, lazy-spec.help.
- **research** — Bounded lookups over the spec tree for agents and operators, without loading whole documents. Members: lazy-spec.lookup.

## Walkthroughs

- **new-product-from-code** — Register a product and generate its spec from an existing codebase. Path: lazy-spec.product-config → lazy-spec.create-from-code → lazy-spec.create-feature.
- **asset-to-release** — Take one asset from creation through its gates to release. Path: lazy-spec.create-asset → lazy-spec.set-stage → lazy-spec.flip-gate → lazy-spec.sync-with-code.

## Requirements

- **Claude Code** with plugin support.
- **lazycortex-core** — provides the `products` / `spec` settings sections, the `settings-get` / `settings-set` CLI, and the runtime daemon that drives the `lazy-spec.gate-tick` md-scan routine.
- **lazycortex-review** (v4) — the shared behavior-keyed review classes that `lazy-spec.install` seeds once per vault (one class per doc-kind, right-anchored wildcard globs spanning every product and asset type); a product-specific reviewer is a `<kind>@<key>` class added through `/lazy-review.configure`.
- **lazycortex-diagram** — draws the behavioral / architecture diagrams that creation skills request.
- **lazycortex-experts** *(optional)* — supplies the designer / developer / tester personas wired into review classes.

## Quick start

1. `/lazy-spec.install` — create consumer dirs, register the gate-tick routine, optionally seed the repo's default language.
2. `/lazy-spec.product-config` — register your first product (path, source paths, icon) in `lazy.settings.json[products]`.
3. `/lazy-spec.create-feature <product> <slug>` — scaffold your first asset, then let the gates and review cycle carry it forward.
