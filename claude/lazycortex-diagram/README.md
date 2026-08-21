---
iconize_icon: LiInfo
iconize_color: "#93c5fd"
---
# lazycortex-diagram

Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.

## Why this plugin

Mermaid and ASCII diagrams in long-running docs drift from house style as palettes, init directives, and per-kind conventions evolve. Each one-off diagram becomes a tiny exception that nobody owns. lazycortex-diagram centralises diagram production behind a single dispatcher that picks the right kind and format for the request, hands it to a per-format writer agent, and renders against shipped templates and named style schemes. New diagrams stay current; old fences can be re-conformed in place.

## Who it's for

- Authors of Markdown documentation (architecture notes, runbooks, ADRs) who want consistent, theme-correct mermaid and ASCII diagrams without hand-tweaking each fence.
- Plugin authors who want to ship style-aware diagrams whose palette, init directive, and density bounds are governed by a contract instead of memory.

## Blocks

- **install-and-audit** — Bootstrap lazycortex-diagram in your project. Covers what `/lazy-diagram.install` drops (the authoring rule, templates under `templates/diagram.<format>/`, style schemes, agent-model tier seeds for the per-format writer agents). lazycortex-diagram has no user-facing audit — for health verification use `/lazy-core.doctor`. Members: lazy-diagram.install.
- **drawing** — Insert and refresh diagrams in Markdown documentation against shipped templates and named style schemes. Members: lazy-diagram.draw, lazy-diagram.fix, lazy-diagram.draw-mermaid, lazy-diagram.draw-ascii.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the install skill, doctor checks, and parallel-scan reference used by `lazy-diagram.audit`.

## Quick start

1. Install the marketplace and enable the plugin (`/plugin install lazycortex-diagram@lazycortex`).
2. Run `/lazy-diagram.install` to wire local config.
3. Insert a new diagram: `/lazy-diagram.draw target_file=<abs path> anchor_section="## <H2>" request="<one-line description>"`. The skill picks `(kind, format)`, dispatches the per-format writer agent, and writes a fence under the heading.
4. Re-conform an existing diagram: `/lazy-diagram.fix target_file=<abs path> anchor_section="## <H2>"`. The skill infers `(kind, format)` from the fence and rewrites it against the current scheme.
5. To embed diagram seams inside another skill, follow the `Caller contract` in `skills/lazy-diagram.draw/SKILL.md` (numbered substep, per-seam TaskCreate, Verify section).

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-diagram.audit` | Run when the operator asks to audit the lazycortex-diagram plugin itself — after authoring or editing a template under `templates/diagram.*/` or a `styles-*.json` scheme, or when drawn diagrams come out with unbound roles, a missing init block, or an exemplar that no longer matches the authoring rule. Delegated from `lazy-core.doctor` Phase 3. Audits the plugin's own shipped templates and schemes, never a diagram in your docs — a stale fence in a document is `/lazy-diagram.fix`. |
| `lazy-diagram.draw` | Use when a NEW diagram should land under a named heading in a markdown file — an authoring skill reaching a declared draw seam, or a direct request to draw a flow / sequence / state / architecture / layout picture of something. Picks (kind, format) from the free-form request, dispatches the per-format drawer agent, and writes one fenced diagram. For re-conforming a fence that already exists, see `/lazy-diagram.fix`. |
| `lazy-diagram.fix` | Use when a diagram fence that already exists has drifted from the current contract — hardcoded palette, missing theme directive, node labels that no longer match the prose around them — or when `/lazy-diagram.audit` offers to repair an offending file. Infers (kind, format) from the fence's syntax marker, re-renders it against the host section's prose, and replaces it in place. For inserting a NEW fence under a heading, see `/lazy-diagram.draw`. |
| `lazy-diagram.install` | Run when the operator asks to set up diagram drawing in a repo, and again after a plugin update so new artifacts land. Also the answer when `/lazy-diagram.draw` or `/lazy-diagram.fix` misbehaves because the `lazy-diagram.authoring` rule is missing from the rules directory or the drawer agents have no model tier assigned. Idempotent and quiet on re-run; install scope is detected, not asked. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [drawing](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/drawing.md) — Insert new diagrams and refresh existing ones — dispatcher picks kind and format from your prose, writer agents render against shipped templates and style schemes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/install-and-audit.md) — Bootstrap lazycortex-diagram in your project — sync the authoring rule, seed agent-model tiers, and clean up orphans.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/troubleshooting.md) — Common failure modes across lazycortex-diagram skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/faq.md) — Answers to common questions about kind/format selection, scheme palettes, draw vs fix, ASCII vs mermaid, density bounds, split behaviour, direct agent invocation, and install.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-diagram.draw-ascii` | Dispatched by /lazy-diagram.draw or /lazy-diagram.fix once kind and format are settled; dispatch it directly only when you have ALREADY chosen format=ascii and kind=<one of: flow, fs-tree, layout> — it never infers either. Single-pass writer: its whole response is the ASCII diagram body, without the surrounding triple-backticks. |
| `lazy-diagram.draw-mermaid` | Dispatched by /lazy-diagram.draw or /lazy-diagram.fix once kind and format are settled; dispatch it directly only when you have ALREADY chosen format=mermaid and kind=<one of: flow, sequence, state, erd, class, architecture, layout, nav, tree, controls-scheme, decision-tree, screen-scheme, journey, mindmap, gantt, timeline> — it never infers either. Single-pass writer: its whole response is the mermaid fence body, without the surrounding triple-backticks. |

## Commands

| Command | Description |
|---|---|
| `lazy-diagram.help` | Run when the operator asks what lazycortex-diagram can do, which verb draws a new picture versus repairing an existing fence, or what kinds and formats are on offer — lists the diagram engine's surface: draw / fix / audit / install, the mermaid and ASCII drawer agents, and the authoring rule governing templates and style schemes. |

## Rules

| Rule | Description |
|---|---|
| `lazy-diagram.authoring.md` | Authoring contract — closure relationship between diagram templates, style files, and emitted fences. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-diagram@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-diagram:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-diagram.audit
/lazy-diagram.draw
/lazy-diagram.fix
/lazy-diagram.install
```
