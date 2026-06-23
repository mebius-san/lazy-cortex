---
iconize_icon: LiInfo
iconize_color: "#fca5a5"
---
# lazycortex-specs

Specification and design skills for Claude Code

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
- **lazycortex-review** (v4) — the review classes that `spec.product-config` and `spec.add-asset-category` generate for each authored-doc type.
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

## Skills

| Skill | Description |
|---|---|
| `spec.add-asset-category` | Register a new operator-defined asset category on a product with icon and review classes. |
| `spec.create-asset` | Universal asset-creation skill — scaffolds one asset folder for any category with authored docs and behavioral diagrams. |
| `spec.create-bug` | Built-in wrapper over `spec.create-asset` — pins category to bug and delegates. |
| `spec.create-change` | Built-in wrapper over `spec.create-asset` — pins category to change and delegates. |
| `spec.create-feature` | Built-in wrapper over `spec.create-asset` — pins category to feature and delegates. |
| `spec.create-from-code` | Generate product or feature-level spec from an existing codebase via parallel Explore agents. |
| `spec.create-request` | Capture a raw user idea into the vault-wide requests/ inbox as a body-only markdown file. |
| `spec.doctor` | Audit a product spec for staleness, broken links, missing sections, role/gate/stage inconsistencies. |
| `spec.finalize-branch` | Rebase any specs pinned to a branch back to the repo's default branch after merge or deletion. |
| `spec.flip-gate` | Flip one asset progression gate true/false by subprocessing the flip-gate primitive. |
| `spec.gate-tick` | Script-only md-scan worker that advances one asset's gates per tick — auto-flips derived gates or drops readiness callouts. |
| `spec.install` | Bootstrap the lazycortex-specs plugin — ensures template dirs exist, seeds language config, registers spec.gate-tick routine. |
| `spec.product-config` | Create or edit a product registration — writes to lazy.settings.json[products], scaffolds folder tree and review classes. |
| `spec.refresh-sources` | Re-project a spec doc's body Sources sub-sections from frontmatter, preserving operator-authored glosses. |
| `spec.request-attach` | Attach a request to an existing entity and distribute body across entity's docs. |
| `spec.request-classify` | Classify a request file's body into a request_class token from closed meta classes plus asset categories. |
| `spec.request-find-candidates` | Search the vault for existing entities that might be the attach target for a given request. |
| `spec.request-spawn` | Spawn a new feature/change/bug entity from a request, then delegate to spec.request-attach. |
| `spec.resolve-dependency` | Resolve a product dependency entry to concrete links and optional local spec path. |
| `spec.resolve-repo` | Resolve a repo key to runtime metadata by reading lazy.settings.json[repos] and inspecting git remote. |
| `spec.set-stage` | Change the per-file spec_stage of an authored spec doc and mirror the spec/<stage> tag. |
| `spec.source-url` | Build a single forge-correct source URL for a file in a source repo. |
| `spec.sync-with-code` | Compare source commits against last synced commit and propagate relevant changes into product spec. |

## Agents

| Agent | Description |
|---|---|
| `spec.request-router` | Review-loop specialist — classifies request, finds candidates, writes Routing section surfacing decision for operator confirmation. |

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
