---
kind: layout
purpose: Schematic UI layout — named regions and their adjacency. Not pixel-accurate.
---
# Layout diagram — canonical exemplar (mermaid)

Used for `kind: layout`, `format: mermaid`. Mermaid's `block-beta` syntax is intentionally schematic — it documents which regions exist and how they sit relative to each other, NOT pixel sizes or styling. Skip if fewer than 2 regions. No upper split bound — layout density is the layout itself.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.layout` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Region IDs are camelCase derived from the request's UI vocabulary (`header`, `sidebar`, `mainContent`, `footer`, `actionBar`). Terminology must match what the host section calls these regions.
- Every region has a label in `["..."]` — the label is what the user sees; the ID is what other prose references.
- Use `columns N` to declare the grid width and `space:N` to leave gaps. Spans via `block:<id>:<cells>` when a region needs to occupy multiple columns/rows.
- Annotate non-obvious regions with a `%% <id>: <one-line purpose>` comment line above the block declaration when their role isn't clear from the label.

## Roles

Mermaid v11+ `block-beta` honours `classDef` + `class`. We use the canonical role vocabulary to distinguish chrome regions from content from navigation.

- `entry` — chrome regions: header, footer, actionBar (the persistent frame).
- `action` — primary content regions: mainContent, body, primary card-detail blocks.
- `sub` — auxiliary regions: sidebar, aside, navigation panels, related-content rails.

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per region. Drawer assigns roles by matching region IDs / labels to the role descriptions above; if a region's role is genuinely ambiguous, default to `action`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.layout`; this template never carries literal style values.

- `classDef entry`  ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef action` ← `action.fill`, `action.stroke`, `textOnPlate`
- `classDef sub`    ← `sub.fill`, `sub.stroke`, `textOnPlate`

## Layout

Layout config is baked into the scheme's `blocks.init.layout`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
block-beta
  columns 3
  header["Header (logo, search, user menu)"]:3
  sidebar["Sidebar (filters)"] mainContent["Card detail (image, title, description)"] aside["Aside (related cards)"]
  actionBar["Action bar (edit, delete, share)"]:3
  footer["Footer (legal, version)"]:3
```
