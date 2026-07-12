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
- **install-and-audit** — Bootstrap, configure a product, and audit a spec in this repo. Members: spec.install, spec.product-config, spec.doctor, spec.help.

## Walkthroughs

- **new-product-from-code** — Register a product and generate its spec from an existing codebase. Path: spec.product-config → spec.create-from-code → spec.create-feature.
- **asset-to-release** — Take one asset from creation through its gates to release. Path: spec.create-asset → spec.set-stage → spec.flip-gate → spec.sync-with-code → spec.finalize-branch.

## Requirements

- **Claude Code** with plugin support.
- **lazycortex-core** — provides the `products` / `spec` settings sections, the `settings-get` / `settings-set` CLI, and the runtime daemon that drives the `spec.gate-tick` md-scan routine.
- **lazycortex-review** (v4) — the behavior-keyed review classes that `spec.product-config` generates per product (one class per doc-kind, wildcard globs spanning every asset category).
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
| `spec.add-asset-category` | Register a new operator-defined asset category on a product — writes the category block (`icon`, optional `color`) into `products[<key>].asset_categories.<name>` and scaffolds the category folder + operator-zone folder-note (carrying the managed `iconize_icon`/`iconize_color` and an operator-authored `description`). The category's docs are covered automatically by the product's behavior-keyed review classes (wildcard globs) — this skill never touches `review.classes`. Invoke when an operator wants a product to grow a new asset kind (characters / scenes / chapters / …) beyond the built-in feature / change / bug set. |
| `spec.create-asset` | Universal asset-creation skill — scaffolds one asset folder (`<spec_path>/<category>/<slug>/`) under a registered product for any asset category (built-in feature / change / bug, or an operator-defined category from the product's `asset_categories`), asks category-scaled clarifying questions, authors the docs in the product's language, and draws the primary behavioral diagram(s). The three built-in `spec.create-feature` / `spec.create-change` / `spec.create-bug` skills are thin wrappers that pin `<category>` and delegate here. |
| `spec.create-bug` | Built-in wrapper over `spec.create-asset` — pins `<category>` to `bug` and delegates. Use when filing a bug against a product spec; all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. The bug layout is `bug.md` + `plan.md` (NO `design.md`). |
| `spec.create-change` | Built-in wrapper over `spec.create-asset` — pins `<category>` to `change` and delegates. Use when requesting a change to an existing product spec; all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. A "change" is the atomic modification unit, peer to a feature. |
| `spec.create-feature` | Built-in wrapper over `spec.create-asset` — pins `<category>` to `feature` and delegates. Use when adding a new feature to a product that already has a spec; all clarification, scaffolding, prose, and diagrams are owned by `spec.create-asset`. |
| `spec.create-from-code` | Use when generating a specification FROM an existing codebase for an already-registered, code-bound product — fans heavy source scanning out to parallel Explore agents, then writes a behavior-only product design doc and a code-grounded product tech doc with source URLs. Product mode documents the product itself; feature mode delegates one feature-candidate to spec.create-asset. Requires the product to be registered with a `source` binding via /spec.product-config first. |
| `spec.create-request` | Capture a raw user idea into the vault-wide requests/ inbox as a body-only markdown file. Asks 3-5 wizard questions to clarify before writing. Frontmatter (spec_role, request_status, request_class, status-mirror tags) is added by the spec.request-open routine on the next md-scan tick — this skill writes the body only. |
| `spec.doctor` | Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or inconsistencies with the actual source code — audits a product's folder tree, status folder-notes (flat gate booleans), per-file stages, source links, and wikilinks, then reports issues grouped by severity and offers targeted fixes. Read-only by default; pass `--apply` to write fixes. |
| `spec.finalize-branch` | Use after merging or deleting a source-repo branch to rebase any specs pinned to that branch back to the repo's default branch — walks every `spec_source_branches` frontmatter entry in the vault, applies the shared Pin Reconciliation primitive, refuses to rewrite unmerged pins, and proposes `spec_released` for assets whose pinned docs covered the now-merged branch. |
| `spec.flip-gate` | Flip one asset progression gate (spec_design_done / spec_plan_done / spec_develop_done / spec_tests_passing / spec_released) true→false or back, by subprocessing the flip-gate primitive. Confirms the flip with one wizard question unless invoked --auto. |
| `spec.gate-tick` | Script-only md-scan worker that advances one asset's gates per tick — auto-flips the next derived gate, drops a readiness callout for the next human-signal gate, or withdraws a stale readiness callout. Dispatched per-file by the daemon; performs no Claude calls. |
| `spec.install` | Bootstrap the lazycortex-specs plugin for the current project (or globally). Ensures the per-category template-override dirs exist (`.claude/templates/spec.feature/`, `spec.change/`, `spec.bug/`, `spec.product/`, `spec.request/`), reads-or-seeds the repo default language into the plugin-owned `spec` settings section, registers the `spec.gate-tick` md-scan routine so the daemon advances asset gates, wires the request-handler runtime (md-scan routines + experts + review class) at project scope, and offers to register the first product via `spec.product-config`. Daemon-routine registrations honor the tracked `daemon.enabled` gate; install scope is derived; file writes follow the absent/merge/conflict policy. Idempotent — safe to re-run. |
| `spec.product-config` | Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the on-disk folder tree + operator-zone folder-notes with iconize icons, generates the built-in behavior-keyed review classes (one per doc-kind, wildcard globs spanning all asset categories), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_categories. |
| `spec.refresh-sources` | Re-project a spec doc's body `# Sources` sub-sections from frontmatter — `## Requests` from `spec_source_requests`, `## Docs` from `spec_source_docs` — preserving any operator-authored glosses on existing wikilink lines (matched by wikilink target). Then regenerates the `# Summary` précis for the asset note and affected container notes (category, product root), and refreshes container stats. Use after manually editing a doc's `spec_source_docs` / `spec_source_requests` frontmatter to bring the body back in sync. |
| `spec.request-attach` | Attach a request to an existing entity. Distributes the request body across the entity's docs by content type (whole-doc match → section-split → fallback per spec.request-protocol.md), maintains a `# Sources` H1 attribution section in every populated doc, appends a wikilink-only entry to the folder-note's ## Source requests, opens a fresh review cycle on every populated doc via lazy-review.start. Idempotent on re-invocation. |
| `spec.request-classify` | Classify a request file's body into a request_class token. The valid set is an OPEN set — closed meta classes (task \| spec \| plan \| feedback \| unknown) plus asset categories (built-in feature \| change \| bug, plus any operator-defined keys from products[<key>].asset_categories such as characters / scenes / chapters). The skill resolves the asset-category half dynamically from lazy.settings.json on every dispatch — a category registered via spec.add-asset-category is recognised on the next run without a rubric update. Output is a single lowercase token. |
| `spec.request-find-candidates` | Search the vault for existing entities (features/changes/bugs) that might be the attach target for a given request body + class. Returns a ranked list with similarity rationale. Reads folder-notes and authored docs; never writes. |
| `spec.request-spawn` | Spawn a new feature/change/bug entity from a request, then delegate to spec.request-attach to populate it from the request body. Calls the deterministic `lazycortex-specs scaffold-asset` primitive for the empty-scaffold step, then invokes `spec.request-attach` on the freshly-created folder-note. |
| `spec.resolve-dependency` | Use to resolve a product dependency entry to concrete links (spec wikilink, dev GitHub URL) and optional local spec path. Reads a product's `dependencies` from `lazy.settings.json[products]` and returns a structured record. Called by callers that need to classify or link a dep entry (e.g., `spec.product-config` import classification). |
| `spec.resolve-repo` | Use to resolve a repo key (e.g., `backend`, `shared`) to its runtime metadata by reading the cross-plugin `lazy.settings.json[repos]` section and inspecting the local checkout's git remote. Returns `{local_path, branch, remote_url, host, owner, repo, forge, base_url}`. The forge type is derived from the remote's hostname via the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`; an explicit `forge:` override in the repo record is honored for self-hosted instances. |
| `spec.set-stage` | Use to change the per-file `spec_stage` of an authored spec doc (design/tech/plan/bug). Accepts a stage from the closed set `empty \| draft \| approved \| rejected \| cancelled`, rewrites `spec_stage` in frontmatter, mirrors the `spec/<stage>` tag, and appends a transition line to the nearest folder-note's `# History`. Every per-file stage change in the system goes through this primitive. |
| `spec.source-url` | Use to build a single forge-correct source URL for a file in a source repo. Takes `(repo_key, path, kind="blob", branch=None)` and returns the URL using the forge's path scheme from the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. All `spec.*` skills and generator agents MUST go through this primitive — never inline `<base>/blob/<branch>/<path>` or other forge-specific path schemes. |
| `spec.sync-with-code` | Use when source code has changed since the last spec sync — compares a registered code-bound product's source commits against the last synced commit, updates the product tech doc, surfaces behavior changes for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections from the code state. No-ops on a design-only product. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [authoring](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/authoring.md) — Create spec assets of any category — features, changes, bugs, and operator-defined kinds — and capture raw ideas into the requests inbox.
- [code-sync](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/code-sync.md) — Keep a product spec aligned with its source repo — pull in-flight code changes into the tech doc and rebase branch pins after a merge.
- [gates](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/gates.md) — Drive an asset's readiness gates and per-file doc stages from creation through release using a two-layer progression model.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/install-and-audit.md) — Bootstrap the plugin, register products, audit spec health, and discover all available skills — the starting point before any authoring work begins.
- [requests](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/requests.md) — Ingest free-form requests and route them into the right place in the spec tree — classify, find candidates, then attach or spawn.
- [source-links](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/source-links.md) — Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through all five readiness gates to a confirmed release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to an existing codebase, generate its design and tech docs from source, then scaffold the first feature.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/faq.md) — Answers to common questions about products, gates, assets, requests, code sync, source links, and the request pipeline in lazycortex-specs.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-specs/help/`.

## Agents

| Agent | Description |
|---|---|
| `spec.request-router` | Routing specialist for request files in review. Fires after the operator has approved a request body. Classifies the request (via spec.request-classify), names candidate targets to attach to (via spec.request-find-candidates), and surfaces the routing decision for the operator to confirm. Reads the vault read-only; writes only inside its own section, never the document frontmatter. Never carries out the routing — that is spec.request-apply, once the review closes. |

## Commands

| Command | Description |
|---|---|
| `spec.help` | Show lazycortex-specs purpose and a one-line summary of each skill it ships |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-specs@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-specs:<skill.name>`.

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
