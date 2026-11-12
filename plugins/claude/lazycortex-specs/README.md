# lazycortex-specs

Specification and design skills for Claude Code

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

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)
- [`lazycortex-diagram`](../lazycortex-diagram/) — Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.
- [`lazycortex-review`](../lazycortex-review/) — Coordinator-driven markdown document review loop: a closed set of Python primitive verbs (parse-note / set-key / paint-banner / collect-job), an LLM coordinator that owns every decision from a prose playbook, and a git-watch wake plus an interval postman that carry commits and finished expert jobs back into the loop.

## Skills

| Skill | Description |
|---|---|
| `lazy-spec.add-asset-type` | Use when a product must grow a new kind of asset beyond the shipped feature / change / bug / content / research / release set — characters, scenes, chapters, endpoints, whatever the operator names — or when `lazy-spec.request-classify` has no type to route a request into. |
| `lazy-spec.audit` | Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or drift from the source code — 'audit this spec', 'is the spec tree healthy'. Read-only: it reports findings with the repair route and writes nothing; /lazy-spec.coverage finds uncovered code instead. |
| `lazy-spec.coverage` | Run when the operator asks to find capabilities the code already has that the product's spec tree does not cover yet — 'what's missing from the specs', 'gap-scan this product against its code'. A whole-product sweep, not a bounded lookup (/lazy-spec.lookup) and not a spec-health check (/lazy-spec.audit). |
| `lazy-spec.create-asset` | Use when the user asks to add a new feature, change, bug — or any operator-declared asset type such as characters / scenes / chapters — to a product that already has a spec. The built-in `lazy-spec.create-feature` / `lazy-spec.create-change` / `lazy-spec.create-bug` skills only pin the type and delegate here; invoke this one directly for every other type. |
| `lazy-spec.create-bug` | Use when filing a bug against a product spec. Built-in wrapper: pins `<asset-type>` to `bug` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. Which document the asset starts from is declared by the type declaration (`asset_types.bug.start_doc`) and read by the delegate, never by this wrapper. |
| `lazy-spec.create-change` | Use when requesting a change to an existing product spec — the atomic modification unit, peer to a feature. Built-in wrapper: pins `<asset-type>` to `change` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. |
| `lazy-spec.create-feature` | Use when adding a new feature to a product that already has a spec. Built-in wrapper: pins `<asset-type>` to `feature` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. |
| `lazy-spec.create-from-code` | Use when the operator asks to write a spec FROM existing code — 'spec this codebase', 'document this product from its source', 'spec this feature from the code' — for a product already registered with a `source` binding via /lazy-spec.product-config. Pick it over /lazy-spec.sync-with-code when no spec exists yet; sync updates one that does. |
| `lazy-spec.create-request` | Use when the user has a raw idea, complaint, or ask they want written down into the vault's `requests/` inbox rather than acted on now — 'note this down', 'file a request for X', 'I want this somewhere so it does not get lost'. Runs a 3-5 question wizard first, then writes a body-only file; the request-handling routines add frontmatter and route it from there. |
| `lazy-spec.drive` | Use when the operator wants to drive one spec asset through its ladder by hand, in one session, with no runtime daemon acting on this checkout — `/lazy-spec.drive <asset-note-path>`. It performs each gesture only on the operator's word, never as its own decision, and refuses to start while a live daemon could act on the same checkout. |
| `lazy-spec.flip-gate` | Run when the operator declares an asset's progression gate reached or wants one walked back — 'design is approved', 'tests pass now', 'this is released', 'un-flip spec_released'. Interactive by default (one confirm question); non-interactive callers such as `spec.coordinator` pass `--auto`. |
| `lazy-spec.gate-tick` | Dispatched per status folder-note by the daemon's `lazy-spec.gate-tick` md-scan routine; not for direct use. |
| `lazy-spec.install` | Run when the operator asks to set up the spec system in a repo, after enabling or updating lazycortex-specs, or when spec skills misbehave because the `spec` settings section, the `lazy-spec.gate-tick` routine, or the vault spec (`vision.md`) is missing. Products are registered separately by /lazy-spec.product-config. |
| `lazy-spec.lookup` | Use when an agent doing research over the spec tree, or the operator asking where something lives in specs or what depends on it, needs a bounded slice around a product or asset — a question or token plus an optional anchor, returning matching paths with short excerpts, never whole documents. |
| `lazy-spec.product-config` | Use when the operator asks to create a new product in the spec system or edit an existing product's registration — 'add a product', 'register this repo as a product', 'add source to this design-only product', 'change its dependencies, language or icon'. Products are registered here, never by /lazy-spec.install. |
| `lazy-spec.record-decision` | Use when the operator wants to record, supersede, obsolete, or promote an entry in the spec catalog's decisions registry — 'log this decision', 'mark D-007 superseded', 'D-012 is obsolete now', 'pull the decision blocks out of design.md'. Interactive wrapper over the `decide` CLI primitive; never edits a `decisions.md` file by hand. |
| `lazy-spec.refresh-sources` | Use after hand-editing a spec doc's `spec_source_docs` / `spec_source_requests` frontmatter, or whenever its body `# Sources` bullets no longer match that frontmatter. Re-projects the `## Docs` / `## Requests` lists, keeping operator glosses on existing wikilinks. Touches nothing outside the doc's `# Sources` container. One file per call — callers loop. |
| `lazy-spec.request-classify` | Dispatched by the `spec.catalog-coordinator` agent in routing mode to label a request with a `request_class`; not for direct use. |
| `lazy-spec.request-find-candidates` | Dispatched by the `spec.catalog-coordinator` agent in routing mode to find assets a request could attach to; not for direct use. |
| `lazy-spec.resolve-dependency` | Dispatched by /lazy-spec.product-config to classify or link one `dependencies[]` entry; not for direct use. |
| `lazy-spec.set-stage` | Use when one authored spec doc changes stage — a draft is approved, a plan is rejected, an asset is cancelled. Accepts any document whose `spec_doc_type` is declared with `stages: true`, never a filename or a path. Every `spec.*` skill that moves a per-file `spec_stage` delegates here instead of editing frontmatter, so the `spec/<stage>` mirror tag and the `spec_approved_at` stamp never drift. |
| `lazy-spec.source-url` | Dispatched by every `spec.*` skill and agent that emits a link to a file of the product's code; not for direct use. |
| `lazy-spec.sync-with-code` | Use when source code has changed and the spec tree should match it again — 'sync the specs with the code', 'the code moved on, update the spec' — for the whole tree, one code-bound product, or one asset. Every edit stays uncommitted until the operator reads the diff and says yes. Pick /lazy-spec.create-from-code instead when no spec exists yet. |
| `lazy-spec.upstream-run` | Run when the operator asks to fetch upstream sources now, check what changed in a configured `spec.upstream` source, or force a mirror/detect pass without waiting for the next `lazy-spec.upstream-tick` schedule tick. Manual, no-daemon counterpart of that routine — same underlying primitive, same result. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through its approved design to its publication in a product release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to existing code, generate vision/design/tech docs from source, then gap-scan for anything missed.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-specs/help/faq.md) — FAQ on products, nested products, assets, vision/design docs, gates, requests, decisions, coverage gaps, and spec lookups.

## Agents

| Agent | Description |
|---|---|
| `lazy-spec.catalog-coordinator` | Dispatched by the runtime on a wake against a catalog-root or product level note, or by /lazy-spec.drive; not for direct use. |
| `lazy-spec.coherence-checker` | Dispatched by the spec coordinators through `coherence-dispatch` after a spec document is approved; not for direct use. |
| `lazy-spec.coordinator` | Dispatched by the runtime on a wake against an asset's status folder-note, or by /lazy-spec.drive; not for direct use. |

## Commands

| Command | Description |
|---|---|
| `lazy-spec.help` | Run when the operator asks what lazycortex-specs can do, which verb creates or advances a spec, or how the readiness gates work — lists the spec-vault surface grouped by phase: product bootstrap, asset authoring, gates and per-doc stages, request intake and routing, code sync and doctor, plus the resolver primitives other skills call. |

## Rules

| Rule | Description |
|---|---|
| `lazy-spec.decisions.md` | Four duties for anyone editing a spec-catalog document — read the accumulated decisions before the first edit, reserve a decision statement for a genuine fork, raise a decision candidate only for a product fork taken mid-job, and ask the operator only for a contradiction, an unclear purpose, or a product fork no approved document answers. Owns the weight test that keeps the decisions registry from filling with restated conclusions and the review loop from filling with questions. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-specs@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-specs:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-spec.add-asset-type
/lazy-spec.audit
/lazy-spec.coverage
/lazy-spec.create-asset
/lazy-spec.create-bug
/lazy-spec.create-change
/lazy-spec.create-feature
/lazy-spec.create-from-code
/lazy-spec.create-request
/lazy-spec.drive
/lazy-spec.flip-gate
/lazy-spec.gate-tick
/lazy-spec.install
/lazy-spec.lookup
/lazy-spec.product-config
/lazy-spec.record-decision
/lazy-spec.refresh-sources
/lazy-spec.request-classify
/lazy-spec.request-find-candidates
/lazy-spec.resolve-dependency
/lazy-spec.set-stage
/lazy-spec.source-url
/lazy-spec.sync-with-code
/lazy-spec.upstream-run
```
