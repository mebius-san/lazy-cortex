---
description: Authoring contract — closure relationship between diagram templates, style files, and emitted fences.
paths:
  - "claude/lazycortex-diagram/templates/diagram.*/diagram-*.md"
  - "claude/lazycortex-diagram/templates/diagram.mermaid/styles-*.json"
---
# Diagram authoring contract

Three artifacts cooperate per `(kind, format)`:

- **Template** (`templates/diagram.<format>/diagram-<kind>.md`) — structure + role binding. Names roles, declares mechanism (`classDef` / per-element `style` / fuller-init / structure-only). No literal style values.
- **Style file** (`templates/diagram.mermaid/styles-<name>.json`) — literal values. Owns `roles{}`, `textConstants{}`, and `blocks.init.<kind>` (the full init line per kind).
- **Fence** (emitted by drawer agent) — composes template structure with style values into the rendered block.

## 1. Closure rule

Every field a template references in its `## Color binding` (any role name, any text-constant name) MUST resolve to a value in every shipped style file's `roles{}` or `textConstants{}`. Every kind that has a template MUST have a `blocks.init.<kind>` entry in every style file. Conversely, style files MUST NOT contain values for roles, text-constants, or kinds that no template references.

Drawer agents emit only what the closure provides — no fabricated hex, no fabricated init lines, no fabricated keys. A referenced field missing in the style file → drawer returns `failed: missing-in-style:<field>`. A style file value with no template referent → audit FAIL.

## 2. Drawing constraints live elsewhere

Per-kind drawing constraints (init directive shape, edge labelling, ID conventions, density bounds, sanity checks) are inlined in each drawer agent's `## Process (single pass)` § Sanity checks and § Density check (`agents/lazy-diagram.draw-*.md`). They are drawing concerns enforced at fence-emit time — not authoring concerns enforced at template-write time. Authors of templates and style files do not need to know the drawing constraints; the agent owns them.

Style-file authoring concerns (palette construction, contrast, inversion-aware text colour for hosts that flip brightness at render time) live in the `dev.diagram-style` skill.

## Enforcement

`lazy-diagram.audit` runs the closure rule of § 1 over the template tree and shipped style files. `lazy-core.doctor` surfaces findings.
