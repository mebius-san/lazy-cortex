---
kind: layout
purpose: Schematic UI layout in ASCII — named regions and their adjacency for plain-text rendering.
---
# Layout diagram — canonical exemplar (ASCII)

Used for `kind: layout`, `format: ascii`. ASCII layout is the right pick when the renderer can't show `block-beta` (PR comments, terminal output) or when the schematic is so simple it doesn't need a mermaid round-trip. Skip if fewer than 2 regions. No upper split bound.

## Idioms

- Box every region with `+----+` borders.
- Region label inside the box, in human-readable form (`| Sidebar (filters) |`); region ID is reflected in a `# id:` comment line above the box only when other prose references it by ID.
- Adjacent regions share borders where physically adjacent in the layout.
- Nested content blocks (image, title/description, repeated cards) are drawn as inner `+----+` boxes inside their parent region — gives the schematic actual visual structure rather than a single flat label.
- Action-bar / button-strip regions render the controls inline as `[ Edit ]  [ Delete ]  [ Share ]`; footer corners can carry trailing metadata (`(c) legal notice` left, `v1.0.0` right).
- No box-drawing Unicode — ASCII only (`+`, `-`, `|`, `[`, `]`).
- Use blank space inside boxes to suggest relative size; do not attempt pixel-fidelity.

## Exemplar

```text
+--------------------------------------------------------------+
| Header (logo, search, user menu)                             |
+----------------+-----------------------------+---------------+
| Sidebar        | Card detail                 | Aside         |
| (filters)      |                             | (related)     |
|                | +------------------------+  |               |
|                | | Image                  |  |               |
|                | +------------------------+  |               |
|                | | Title                  |  | +-----------+ |
|                | | Description            |  | | Card      | |
|                | |                        |  | +-----------+ |
|                | |                        |  | | Card      | |
|                | |                        |  | +-----------+ |
|                | |                        |  | | Card      | |
|                | +------------------------+  | +-----------+ |
+----------------+-----------------------------+---------------+
| Action bar  [ Edit ]  [ Delete ]  [ Share ]                  |
+--------------------------------------------------------------+
| Footer  (c) legal notice                        v1.0.0       |
+--------------------------------------------------------------+
```
