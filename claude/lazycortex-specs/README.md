---
iconize_icon: LiInfo
iconize_color: "#fca5a5"
---
# lazycortex-specs

Specification and design skills for Claude Code

## Why this plugin

`lazycortex-specs` keeps a product's specifications next to its code as ordinary Markdown notes in an Obsidian-friendly vault, and gives Claude Code the skills to author and maintain that structure so you don't carry it in your head. A product is registered once in `lazy.settings.json[products]`; its work is organised into assets — built-in `feature` / `change` / `bug` plus any operator-defined categories (characters, scenes, …) you declare. Each asset advances through five flat, linear readiness gates (`spec_design_done` … `spec_released`), and the plugin keeps the spec aligned with the source repo, links sections to specific branches, and audits for drift.

The plugin manages *structure* and *lifecycle*, not the prose — authoring stays with the operator (and, optionally, the `lazycortex-review` cycle).

## Who it's for

- **Teams who write specs and design docs alongside code** in the same repo and want skills that understand spec conventions, gate state, and source links.
- **Non-software products** (games, books, courses) that model their work as asset types of their own under the same gate-and-review machinery.

## Blocks

- **authoring** — Create and populate spec assets of any category. Members: lazy-spec.create-asset, lazy-spec.create-feature, lazy-spec.create-change, lazy-spec.create-bug, lazy-spec.add-asset-type, lazy-spec.create-from-code, lazy-spec.create-request, lazy-spec.decide.
- **gates** — Drive an asset's readiness gates and per-file stages. Members: lazy-spec.flip-gate, lazy-spec.gate-tick, lazy-spec.set-stage.
- **code-sync** — Keep specs aligned with the source repo across commits and branch merges. Members: lazy-spec.sync-with-code, lazy-spec.finalize-branch, lazy-spec.coverage.
- **upstream** — Mirror external design sources and route their changes through the request pipeline. Members: lazy-spec.upstream-run.
- **source-links** — Resolve repos, dependencies, and forge-correct source URLs. Members: lazy-spec.resolve-repo, lazy-spec.resolve-dependency, lazy-spec.source-url.
- **requests** — Ingest free-form requests and route them into the spec tree. Members: spec.coordinator, lazy-spec.request-classify, lazy-spec.request-find-candidates.
- **install-and-audit** — Bootstrap, configure a product, and audit a spec in this repo. Members: lazy-spec.install, lazy-spec.product-config, lazy-spec.doctor, lazy-spec.audit, lazy-spec.help.
- **research** — Bounded lookups over the spec tree for agents and operators, without loading whole documents. Members: lazy-spec.lookup.

## Walkthroughs

- **new-product-from-code** — Register a product and generate its spec from an existing codebase. Path: lazy-spec.product-config → lazy-spec.create-from-code → lazy-spec.create-feature.
- **asset-to-release** — Take one asset from creation through its gates to release. Path: lazy-spec.create-asset → lazy-spec.set-stage → lazy-spec.flip-gate → lazy-spec.sync-with-code → lazy-spec.finalize-branch.

## Requirements

- **Claude Code** with plugin support.
- **lazycortex-core** — provides the `products` / `spec` settings sections, the `settings-get` / `settings-set` CLI, and the runtime daemon that drives the `lazy-spec.gate-tick` md-scan routine.
- **lazycortex-review** (v4) — the shared behavior-keyed review classes that `lazy-spec.product-config` generates once per vault (one class per doc-kind, right-anchored wildcard globs spanning every product and asset type; a product with divergent experts gets a per-product override).
- **lazycortex-diagram** — draws the behavioral / architecture diagrams that creation skills request.
- **lazycortex-experts** *(optional)* — supplies the designer / developer / tester personas wired into review classes.

## Quick start

1. `/lazy-spec.install` — create consumer dirs, register the gate-tick routine, optionally seed the repo's default language.
2. `/lazy-spec.product-config` — register your first product (path, source repo, icon, review experts) in `lazy.settings.json[products]`.
3. `/lazy-spec.create-feature <product> <slug>` — scaffold your first asset, then let the gates and review cycle carry it forward.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)
- [`lazycortex-diagram`](../lazycortex-diagram/) — Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.
- [`lazycortex-review`](../lazycortex-review/) — Coordinator-driven markdown document review loop: a closed set of Python primitive verbs (parse-note / set-key / paint-banner / collect-job), an LLM coordinator that owns every decision from a prose playbook, and a git-watch wake plus an interval postman that carry commits and finished expert jobs back into the loop.

## Skills

| Skill | Description |
|---|---|
| `lazy-spec.add-asset-type` | Use when a product must grow a new kind of asset beyond the shipped feature / change / bug / content / research set — characters, scenes, chapters, endpoints, whatever the operator names — or when `lazy-spec.request-classify` has no type to route a request into. Writes the type declaration into `products[<key>].asset_types.<name>` and settles the playbook the coordinator will work assets of that type under; review coverage is automatic, so it never touches `review.classes`. |
| `lazy-spec.audit` | Run when the operator asks whether the lazycortex-specs plugin itself is internally consistent — the decisions-registry rule still matches what the code relies on, every CLI verb is documented, every skill and reference resolves. Read-only; findings name the fix (re-run `/lazy-spec.install`, edit the drifted file, run `/lazy-spec.doctor`) rather than applying one. |
| `lazy-spec.coverage` | Run when the operator asks to find capabilities the code already has that the product's spec tree does not cover yet — 'what's missing from the specs', 'gap-scan this product against its code'. Audits the product's structure map (`docs/structure.md`) and domain groups against its spec-asset tree, reporting uncovered capabilities with a proposed category + slug for a retro-spec. This is a whole-product audit sweep with judgment calls on every match, not a bounded lookup by query or anchor — it carries no `research: true` marker despite reading through `lazy-wiki.structure` and `lazy-wiki.domains`. |
| `lazy-spec.create-asset` | Use when the user asks to add a new feature, change, bug — or any operator-declared asset type such as characters / scenes / chapters — to a product that already has a spec. The built-in `lazy-spec.create-feature` / `lazy-spec.create-change` / `lazy-spec.create-bug` skills only pin the type and delegate here; invoke this one directly for every other type. |
| `lazy-spec.create-bug` | Use when filing a bug against a product spec. Built-in wrapper: pins the asset type to `bug` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. Which document the asset starts from is declared by the type declaration (`asset_types.bug.start_doc`) and read by the delegate, never by this wrapper. |
| `lazy-spec.create-change` | Use when requesting a change to an existing product spec — the atomic modification unit, peer to a feature. Built-in wrapper: pins `<category>` to `change` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. |
| `lazy-spec.create-feature` | Use when adding a new feature to a product that already has a spec. Built-in wrapper: pins `<category>` to `feature` and delegates — all clarification, scaffolding, prose, and diagrams are owned by `lazy-spec.create-asset`. |
| `lazy-spec.create-from-code` | Use when generating a specification FROM an existing codebase for an already-registered, code-bound product — fans heavy source scanning out to parallel Explore agents, then writes a behavior-only product design doc and a code-grounded product tech doc with source URLs. Product mode documents the product itself; feature mode delegates one feature-candidate to lazy-spec.create-asset. Requires the product to be registered with a `source` binding via /lazy-spec.product-config first. |
| `lazy-spec.create-request` | Use when the user has a raw idea, complaint, or ask they want written down into the vault's `requests/` inbox rather than acted on now — 'note this down', 'file a request for X', 'I want this somewhere so it does not get lost'. Runs a 3-5 question wizard first, then writes a body-only file; the request-handling routines add frontmatter and route it from there. |
| `lazy-spec.decide` | Use when the operator wants to record, supersede, obsolete, or promote an entry in the spec catalog's decisions registry — 'log this decision', 'mark D-007 superseded', 'D-012 is obsolete now', 'pull the decision blocks out of design.md'. Interactive wrapper over the `decide` CLI primitive; never edits a `decisions.md` file by hand. |
| `lazy-spec.doctor` | Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or inconsistencies with the actual source code — audits a product's folder tree, status folder-notes (flat gate booleans), per-file stages, source links, and wikilinks, then reports issues grouped by severity and offers targeted fixes. Read-only by default; pass `--apply` to write fixes. |
| `lazy-spec.drive` | Use when the operator wants to drive one spec asset through its ladder by hand, in a single continuous session, with no runtime daemon acting on this checkout — `/lazy-spec.drive <asset-note-path>`. Reads `lazy-spec.coordination-playbook.md`, the same law `spec.coordinator` follows under the daemon, and drives the identical ladder locally: the operator speaks a word, the skill translates it into the gesture (tick, question-answer, command) ON THE OPERATOR'S BEHALF — never its own decision — commits it, wakes the coordinator via the same CLI the daemon's git-watch routine uses, and pumps whatever expert jobs result to completion with the local manual pump. Refuses to start while a live daemon could act on the same checkout. |
| `lazy-spec.finalize-branch` | Use after merging or deleting a source-repo branch to rebase any specs pinned to that branch back to the repo's default branch — walks every `spec_source_branches` frontmatter entry in the vault, applies the shared Pin Reconciliation primitive, refuses to rewrite unmerged pins, and proposes `spec_released` for assets whose pinned docs covered the now-merged branch. |
| `lazy-spec.flip-gate` | Run when the operator declares an asset's progression gate reached or wants one walked back — 'design is approved', 'tests pass now', 'this is released', 'un-flip spec_released'. Interactive by default (one confirm question); non-interactive callers such as `spec.coordinator` pass `--auto`. |
| `lazy-spec.gate-tick` | Dispatched per status folder-note by the daemon's `lazy-spec.gate-tick` md-scan routine to poll one asset's active job and structurally check its folder-note; not for direct use — it is a pure script and makes no Claude calls. Read it when asked why an active-job marker was cleared, why an asset went `spec_halted` from a dead job, or what a `note-check` violation folded into a tick result means. For why a launch checkbox appeared, disappeared, or dispatched a job — or why a gate flipped at all — see `lazy-spec.coordination-playbook.md`; none of that is this worker's decision anymore. |
| `lazy-spec.install` | Run when the operator asks to set up the spec system in a repo, after enabling or updating lazycortex-specs, or when spec skills misbehave because the `spec` settings section, the per-category template-override dirs, the `lazy-spec.gate-tick` routine, or the request-handler runtime are missing. Also the place the first product gets registered. Idempotent — safe to re-run. |
| `lazy-spec.lookup` | Use when an agent doing research over the spec tree — an expert following its research aspect, a subagent gathering context before writing, or the operator asking where something lives in specs or what depends on it — needs a bounded slice of the spec tree around a product or asset: a question or token plus an optional product/asset anchor, returning matching paths with short excerpts, never whole documents. |
| `lazy-spec.product-config` | Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the product root with its operator-zone folder-note and iconize icon (group folders appear lazily with their first asset), generates or reuses the shared vault-wide behavior-keyed review classes (one per doc-kind, right-anchored wildcard globs spanning every product and asset type; a product with divergent experts gets a per-product override), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_types. |
| `lazy-spec.refresh-sources` | Use after hand-editing a spec doc's `spec_source_docs` / `spec_source_requests` frontmatter, or whenever its body `# Sources` bullets no longer match that frontmatter. Re-projects the `## Docs` / `## Requests` lists (keeping operator glosses on existing wikilinks), then regenerates the `# Summary` précis for the asset note and its category / product-root containers and refreshes their stats. One file per call — callers loop. |
| `lazy-spec.request-classify` | Dispatched by the `spec.coordinator` agent during a request's review loop to label one body with a `request_class` token; not for direct use. Resolves the legal class set from `lazy.settings.json` on every dispatch, so an asset type declared via `lazy-spec.add-asset-type` is recognised on the next run without a rubric edit. |
| `lazy-spec.request-find-candidates` | Dispatched by the `spec.coordinator` agent, after `lazy-spec.request-classify` has settled the class, to find the existing features / changes / bugs a request could attach to; not for direct use. Read-only — returns a ranked list with rationale that the coordinator turns into its attach-vs-spawn decision. |
| `lazy-spec.resolve-dependency` | Dispatched by `/lazy-spec.product-config` when it classifies or links one entry of a product's `dependencies[]` array; not for direct use. Returns `{kind, spec_link, dev_link, local_spec_path?}` for a single entry — never follows the links, never writes, never asks the user. |
| `lazy-spec.resolve-repo` | Dispatched by `lazy-spec.source-url` and by any `spec.*` skill that must turn a repo key from `lazy.settings.json[repos]` into a checkout path, branch, and forge — `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`, `lazy-spec.doctor`, `lazy-spec.product-config`, `lazy-spec.finalize-branch`. Not for direct use: callers never inspect git remotes themselves, they call this once per repo per run and cache the record. |
| `lazy-spec.set-stage` | Use when one authored spec doc changes stage — a draft is approved, a plan is rejected, an asset is cancelled. Accepts any document whose `spec_doc_type` is declared with `stages: true`, never a filename or a path. Every `spec.*` skill that moves a per-file `spec_stage` delegates here instead of editing frontmatter, so the `spec/<stage>` mirror tag and the folder-note `# History` line never drift. |
| `lazy-spec.source-url` | Dispatched by every `spec.*` skill and generator agent that emits a link to a file or directory in a source repo — `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`, `lazy-spec.doctor`, `lazy-spec.product-config`, `lazy-spec.finalize-branch`. Not for direct use except when a human is debugging a wrong URL. Nobody inlines a forge path scheme (GitHub `/blob/`, GitLab `/-/blob/`, Bitbucket `/src/`) anywhere else. |
| `lazy-spec.sync-with-code` | Use when source code has changed since the last spec sync — compares a registered code-bound product's source commits against the last synced commit, updates the product tech doc, surfaces behavior changes for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections from the code state. No-ops on a design-only product. Given an `<asset>` argument instead of a bare product key, runs in asset mode instead: reconciles ONE feature/change asset's design.md / architecture.md against the current code by anchor (source-links, domain-groups, structure) rather than by commit diff, and never edits spec content silently — every drift finding becomes an `[!attention]` callout, a change-asset proposal, or a gate-correction proposal. |
| `lazy-spec.upstream-run` | Run when the operator asks to fetch upstream sources now, check what changed in a configured `spec.upstream` source, or force a mirror/detect pass without waiting for the next `lazy-spec.upstream-tick` schedule tick. Manual, no-daemon counterpart of that routine — same underlying primitive, same result. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [authoring](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/authoring.md) — Create spec assets of any type — features, changes, bugs, and operator-declared kinds — record the decisions behind them, and capture raw ideas into the requests inbox.
- [code-sync](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/code-sync.md) — Keep a product spec aligned with its source repo — pull in-flight code changes into the tech doc, rebase branch pins after a merge, and gap-scan for capabilities the spec tree never documented.
- [gates](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/gates.md) — Drive an asset's readiness gates and per-file doc stages from creation through release using a two-layer progression model.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/install-and-audit.md) — Bootstrap the plugin, register products, and audit both the plugin's own sources and a product's spec health.
- [requests](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/requests.md) — Ingest free-form requests and route them into the right place in the spec tree — classify, find candidates, then let the deterministic apply worker attach, spawn, or link.
- [research](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/research.md) — Answer one question against the spec tree without loading whole documents into your context.
- [source-links](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/source-links.md) — Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
- [upstream](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/upstream.md) — Mirror external design repos into your vault and keep a spec doc's visible source list matching its frontmatter.
- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through all five readiness gates to a confirmed release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to an existing codebase, generate its design and tech docs from source, then scaffold the first feature.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/faq.md) — Answers to common questions about products, assets, gates, requests, decisions, coverage gaps, spec lookups, and the coordinator agent.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-spec.coordinator` | Dispatched on any of the coordinator's eight wake triggers: a commit not authored by a bot identity that touches an asset's folder outside an active review (the status note, a sibling doc not carrying `review_active: true`, or an attachment an expert created beside one), a launch-checkbox job finishing (raised as a `job-done` wake in the runtime sidecar, whoever authored the commit that carried it), a sibling doc's `review_result` transitioning (also regardless of the sibling commit's own author), a dependency asset's own wake reaching this asset as a one-hop reverse-edge dispatch, request routing reaching its terminal review group, a non-empty `# Coordinator commands` section, a ticked `[!question]` answer, or `lazy-spec.drive`'s no-daemon session mode — not for direct use. Owns every asset/product/category folder-note in full: reads the rule layers and every related asset in scope, decides the one mode this wake calls for, acts only through the closed primitive-verb set, and rewrites `# Status brief` to match. |

## Commands

| Command | Description |
|---|---|
| `lazy-spec.help` | Run when the operator asks what lazycortex-specs can do, which verb creates or advances a spec, or how the readiness gates work — lists the spec-vault surface grouped by phase: product bootstrap, asset authoring, gates and per-doc stages, request intake and routing, code sync and doctor, plus the resolver primitives other skills call. |

## Rules

| Rule | Description |
|---|---|
| `spec.decisions.md` | Two duties for anyone editing a spec-catalog document — read the accumulated decisions before the first edit, and reserve a decision statement for a genuine fork. Owns the weight test that keeps the decisions registry from filling with restated conclusions. |

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
/lazy-spec.decide
/lazy-spec.doctor
/lazy-spec.drive
/lazy-spec.finalize-branch
/lazy-spec.flip-gate
/lazy-spec.gate-tick
/lazy-spec.install
/lazy-spec.lookup
/lazy-spec.product-config
/lazy-spec.refresh-sources
/lazy-spec.request-classify
/lazy-spec.request-find-candidates
/lazy-spec.resolve-dependency
/lazy-spec.resolve-repo
/lazy-spec.set-stage
/lazy-spec.source-url
/lazy-spec.sync-with-code
/lazy-spec.upstream-run
```
