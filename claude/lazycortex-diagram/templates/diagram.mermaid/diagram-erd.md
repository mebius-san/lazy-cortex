---
kind: erd
purpose: Entity-relationship diagram for data structures, persisted records, and their relations.
---
# ER diagram — canonical exemplar (mermaid)

Used for `kind: erd`, `format: mermaid`. Skip if fewer than 2 entities. Split when more than 8 entities — pick a natural cut (e.g. user-side vs. content-side) and emit each in its own H3-anchored fence.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.erd` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Entity names are PascalCase singular (`User`, `Card`, `Round`) — match the prose terms in the host section exactly.
- Every relation declares cardinality on both sides using mermaid's `||--o{` family. The relation label names the relationship verb (`User ||--o{ Card : "owns"`).
- Inside an entity, list only the fields the request actually references — not the full schema. Each field has a type and a name; PK/FK markers via `PK` / `FK` after the name.
- PascalCase entity names + labelled relations + terminology parity carry the full meaning.

## Roles

`erDiagram` does not honour per-entity colour, but its global theme keys can be mapped to scheme roles so the whole diagram lands on the canonical palette instead of mermaid's default greys.

## Color binding

Mechanism: fuller-init `themeVariables`, plus a `themeCSS` string for the one surface `themeVariables` can't reach (the relationship-label plate). The init directive (theme keys, `er:{}` config, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.erd`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

Verified against mermaid 11.13.0 as bundled in Obsidian 1.13.7. Mermaid's ER module was rewritten into a unified renderer in mermaid 11.5 — the keys below are that renderer's, not the pre-11.5 one:

- `mainBkg`        ← `entry.fill`   (entity box fill — THE CARDS)
- `nodeBorder`      ← `entry.stroke` (entity box border)
- `lineColor`       ← `lineOnCanvas` (relationship lines + markers)
- `textColor`       ← `textOnPlate`  (entity title text — source renders BLACK on the plate, matching every other kind's text-on-plate convention)
- `nodeTextColor`   ← `textOnPlate`  (attribute row text — same convention as the title)
- `rowOdd`          ← `entry.fill`   (attribute row alternation — odd rows match the entity main background)
- `rowEven`         ← a lightened sibling of `entry.fill`, baked into `blocks.init.erd` (attribute row alternation — even rows sit one step lighter than `rowOdd` so the banding reads while staying in the entity plate's own hue family; not a `roles{}` token, because no role names a within-plate alternation shade)

`rowOdd`/`rowEven` are the current attribute-row-alternation keys. **`attributeBackgroundColorOdd`/`attributeBackgroundColorEven` are DEAD since mermaid 11.5's unified ER renderer — do not bind them.**

`themeCSS` rule baked into `blocks.init.erd` (the one surface `themeVariables` can't reach — the unified renderer draws the relationship label through the generic `.edgeLabel` wrapper it shares with other diagram kinds, not a bespoke `.relationshipLabel`/`.relationshipLabelBox` class, so there is no themeVariable that targets it):

- `.edgeLabel rect,.edgeLabel .labelBkg{fill:...}` ← `edgeLabelBg` (relationship-label plate)
- `.edgeLabel,.edgeLabel .label,.edgeLabel .label *,.edgeLabel text{color:...}` ← `textOnCanvas` (relationship-label text)

This is the standard `edge-label-bg` + `text-on-canvas` pairing documented in `lazy-diagram.inversion-rule.md` — white plate / black text as source. Light mode renders it literally (black text on a white plate); the dark-mode-only whole-SVG filter flips it to white text on a black plate. No erd-specific inversion exception applies to this surface any more.

Caveats:

- `classDef` and per-element `style` directives are silently ignored by mermaid's `erDiagram` — do NOT emit them. The fuller-init `themeVariables` block + `themeCSS` is the only working surface.
- `tertiaryColor` and `edgeLabelBackground` are not part of this scheme's `blocks.init.erd` — the relationship-label plate is `themeCSS`-driven now, not `themeVariables`-driven. Do not reintroduce a binding to either key.

## Layout

Layout config is baked into the scheme's `blocks.init.erd`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
erDiagram
  User ||--o{ Card : "owns"
  Round ||--o{ Card : "contains"
  User {
    string id PK
    string handle
  }
  Card {
    string id PK
    string ownerId FK
    string roundId FK
    string status
  }
  Round {
    string id PK
    timestamp startedAt
    timestamp endedAt
  }
```
