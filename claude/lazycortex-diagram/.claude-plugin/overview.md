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
