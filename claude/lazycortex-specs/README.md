---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-specs

Specification and design skills for Claude Code

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
- **install-and-audit** — Bootstrap, configure a product, pull cross-repo design handoffs, and audit a spec in this repo. Members: spec.install, spec.product-config, spec.import, spec.doctor, spec.help.

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

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)
- [`lazycortex-diagram`](../lazycortex-diagram/) — Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.

## Skills

| Skill | Description |
|---|---|
| `spec.add-asset-category` | Use when a product must grow a new asset kind beyond the built-in feature / change / bug set — characters, scenes, chapters, endpoints, whatever the operator names — or when `spec.request-classify` has no category to route a request into. Writes the category block into `products[<key>].asset_categories.<name>` and scaffolds its folder plus operator-zone folder-note; review coverage is automatic, so it never touches `review.classes`. |
| `spec.create-asset` | Use when the user asks to add a new feature, change, bug — or any operator-defined asset category such as characters / scenes / chapters — to a product that already has a spec. The built-in `spec.create-feature` / `spec.create-change` / `spec.create-bug` skills only pin the category and delegate here; invoke this one directly for every other category. |
| `spec.create-bug` | Use when filing a bug against a product spec. Built-in wrapper: pins `<category>` to `bug` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. The bug layout is `bug.md` + `plan.md` (NO `design.md`). |
| `spec.create-change` | Use when requesting a change to an existing product spec — the atomic modification unit, peer to a feature. Built-in wrapper: pins `<category>` to `change` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. |
| `spec.create-feature` | Use when adding a new feature to a product that already has a spec. Built-in wrapper: pins `<category>` to `feature` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. |
| `spec.create-from-code` | Use when generating a specification FROM an existing codebase for an already-registered, code-bound product — fans heavy source scanning out to parallel Explore agents, then writes a behavior-only product design doc and a code-grounded product tech doc with source URLs. Product mode documents the product itself; feature mode delegates one feature-candidate to spec.create-asset. Requires the product to be registered with a `source` binding via /spec.product-config first. |
| `spec.create-request` | Use when the user has a raw idea, complaint, or ask they want written down into the vault's `requests/` inbox rather than acted on now — 'note this down', 'file a request for X', 'I want this somewhere so it does not get lost'. Runs a 3-5 question wizard first, then writes a body-only file; the request-handling routines add frontmatter and route it from there. |
| `spec.doctor` | Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or inconsistencies with the actual source code — audits a product's folder tree, status folder-notes (flat gate booleans), per-file stages, source links, and wikilinks, then reports issues grouped by severity and offers targeted fixes. Read-only by default; pass `--apply` to write fixes. |
| `spec.finalize-branch` | Use after merging or deleting a source-repo branch to rebase any specs pinned to that branch back to the repo's default branch — walks every `spec_source_branches` frontmatter entry in the vault, applies the shared Pin Reconciliation primitive, refuses to rewrite unmerged pins, and proposes `spec_released` for assets whose pinned docs covered the now-merged branch. |
| `spec.flip-gate` | Run when the operator declares an asset's progression gate reached or wants one walked back — 'design is approved', 'tests pass now', 'this is released', 'un-flip spec_released'. Interactive by default (one confirm question); non-interactive callers such as the `spec.gate-tick` worker pass `--auto`. |
| `spec.gate-tick` | Dispatched per status folder-note by the daemon's `spec.gate-tick` md-scan routine to advance one asset a single notch; not for direct use — it is a pure script and makes no Claude calls. Read it when asked why an asset auto-advanced, or where a `[!ready]` (or withdrawn-readiness) callout in its `## Gates` section came from. |
| `spec.import` | Run when the operator asks to pull specs from another repo, refresh handed-off assets, or check what an import brought in — and right after adding an entry to the spec settings' `imports[]` array. The `spec.import-pull` daemon routine drives the same primitive on a cadence; invoke this to force a run now and get the summary table. |
| `spec.install` | Run when the operator asks to set up the spec system in a repo, after enabling or updating lazycortex-specs, or when spec skills misbehave because the `spec` settings section, the per-category template-override dirs, the `spec.gate-tick` routine, or the request-handler runtime are missing. Also the place the first product gets registered. Idempotent — safe to re-run. |
| `spec.product-config` | Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the on-disk folder tree + operator-zone folder-notes with iconize icons, generates or reuses the shared vault-wide behavior-keyed review classes (one per doc-kind, right-anchored wildcard globs spanning every product and asset category; a product with divergent experts gets a per-product override), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_categories. |
| `spec.refresh-sources` | Use after hand-editing a spec doc's `spec_source_docs` / `spec_source_requests` frontmatter, or whenever its body `# Sources` bullets no longer match that frontmatter. Re-projects the `## Docs` / `## Requests` lists (keeping operator glosses on existing wikilinks), then regenerates the `# Summary` précis for the asset note and its category / product-root containers and refreshes their stats. One file per call — callers loop. |
| `spec.request-attach` | Dispatched by the `spec.request-apply` worker when a request's routing resolves to an attach target, and by `spec.request-spawn` right after it scaffolds a new entity; not for direct use. The only primitive that crosses from a request file into an existing feature / change / bug — it distributes the body, records attribution, and opens a review cycle on every doc it populated. |
| `spec.request-classify` | Dispatched by the `spec.request-router` agent during a request's review loop to label one body with a `request_class` token; not for direct use. Resolves the legal class set from `lazy.settings.json` on every dispatch, so a category added via `spec.add-asset-category` is recognised on the next run without a rubric edit. |
| `spec.request-find-candidates` | Dispatched by the `spec.request-router` agent, after `spec.request-classify` has settled the class, to find the existing features / changes / bugs a request could attach to; not for direct use. Read-only — returns a ranked list with rationale that the router turns into its attach-vs-spawn decision. |
| `spec.request-spawn` | Dispatched by the `spec.request-apply` worker when a request's routing decision names a spawn target rather than an existing entity; not for direct use. Scaffolds the new feature / change / bug, then hands the folder-note to `spec.request-attach` to fill it from the request body. |
| `spec.resolve-dependency` | Dispatched by `/spec.product-config` when it classifies or links one entry of a product's `dependencies[]` array; not for direct use. Returns `{kind, spec_link, dev_link, local_spec_path?}` for a single entry — never follows the links, never writes, never asks the user. |
| `spec.resolve-repo` | Dispatched by `spec.source-url` and by any `spec.*` skill that must turn a repo key from `lazy.settings.json[repos]` into a checkout path, branch, and forge — `spec.create-from-code`, `spec.sync-with-code`, `spec.doctor`, `spec.product-config`, `spec.finalize-branch`. Not for direct use: callers never inspect git remotes themselves, they call this once per repo per run and cache the record. |
| `spec.set-stage` | Use when one authored spec doc (design / tech / plan / bug) changes stage — a draft is approved, a plan is rejected, an asset is cancelled. Every `spec.*` skill that moves a per-file `spec_stage` delegates here instead of editing frontmatter, so the `spec/<stage>` mirror tag and the folder-note `# History` line never drift. |
| `spec.source-url` | Dispatched by every `spec.*` skill and generator agent that emits a link to a file or directory in a source repo — `spec.create-from-code`, `spec.sync-with-code`, `spec.doctor`, `spec.product-config`, `spec.finalize-branch`. Not for direct use except when a human is debugging a wrong URL. Nobody inlines a forge path scheme (GitHub `/blob/`, GitLab `/-/blob/`, Bitbucket `/src/`) anywhere else. |
| `spec.sync-with-code` | Use when source code has changed since the last spec sync — compares a registered code-bound product's source commits against the last synced commit, updates the product tech doc, surfaces behavior changes for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections from the code state. No-ops on a design-only product. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [authoring](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/authoring.md) — Create spec assets of any category — features, changes, bugs, and operator-defined kinds — and capture raw ideas into the requests inbox.
- [code-sync](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/code-sync.md) — Keep a product spec aligned with its source repo — pull in-flight code changes into the tech doc and rebase branch pins after a merge.
- [gates](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/gates.md) — Drive an asset's readiness gates and per-file doc stages from creation through release using a two-layer progression model.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/install-and-audit.md) — Bootstrap the plugin, register products, pull cross-repo design handoffs, audit spec health, and discover skills.
- [requests](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/requests.md) — Ingest free-form requests and route them into the right place in the spec tree — classify, find candidates, then attach or spawn.
- [source-links](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/source-links.md) — Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through all five readiness gates to a confirmed release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to an existing codebase, generate its design and tech docs from source, then scaffold the first feature.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/faq.md) — Answers to common questions about products, assets, gates, code sync, releases, requests, cross-repo imports, and source links in lazycortex-specs.

(`mebius-san` resolves from `.guard-waivers.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `spec.request-router` | Dispatched by the request review loop once the operator has approved a request body, to decide where that request should go; not for direct use. Classifies it (via spec.request-classify), names attach candidates (via spec.request-find-candidates), and surfaces the routing decision for the operator to confirm — it never carries the routing out, that is spec.request-apply once the review closes. Reads the vault read-only and writes only inside its own section, never the document frontmatter. |

## Commands

| Command | Description |
|---|---|
| `spec.help` | Show lazycortex-specs purpose and a one-line summary of each skill it ships |

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
/spec.add-asset-category
/spec.create-asset
/spec.create-bug
/spec.create-change
/spec.create-feature
/spec.create-from-code
/spec.create-request
/spec.doctor
/spec.finalize-branch
/spec.flip-gate
/spec.gate-tick
/spec.import
/spec.install
/spec.product-config
/spec.refresh-sources
/spec.request-attach
/spec.request-classify
/spec.request-find-candidates
/spec.request-spawn
/spec.resolve-dependency
/spec.resolve-repo
/spec.set-stage
/spec.source-url
/spec.sync-with-code
```
