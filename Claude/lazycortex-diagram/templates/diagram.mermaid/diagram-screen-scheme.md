---
kind: screen-scheme
purpose: Wireframe-ish screen schematic — header/content/action rows with named regions and (optionally) nested controls inside each region.
---
# Screen-scheme diagram — canonical exemplar (mermaid)

Used for `kind: screen-scheme`, `format: mermaid`. Mermaid `block-beta` with nested blocks. Use `layout` when the prose names abstract page regions (no controls); use `screen-scheme` when the prose names specific UI elements within those regions.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.screen-scheme` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Three-row scaffold by convention: header row, content row, action row. Rows are declared via `block` blocks; nested controls inside a region are also `block`s.
- Region/control IDs are camelCase; the human label sits in `:` quotes after the id (`headerBar["Header bar"]` in `block-beta`).
- No edges, so the every-edge-labelled sanity check is trivially satisfied (each block carries its own inline label).
- A `columns` declaration per row tunes how the regions are packed.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤8 regions per fence; skip if <2 named regions (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by row.

## Roles

Mermaid v11+ `block-beta` honours `classDef` + `class`. We use the canonical role vocabulary to distinguish chrome regions from content from auxiliary panels and individual controls.

- `entry` — chrome regions that frame the screen: header bar, footer, persistent action bar.
- `action` — individual controls / content cells inside content blocks: card image, title, description, primary buttons.
- `sub` — region-grouping containers: sidebar, aside, content-row container blocks.

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per region. Drawer assigns roles by matching region IDs / labels to the role descriptions above; if a region's role is genuinely ambiguous, default to `action`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.screen-scheme`; this template never carries literal style values.

- `classDef entry`  ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef action` ← `action.fill`, `action.stroke`, `textOnPlate`
- `classDef sub`    ← `sub.fill`, `sub.stroke`, `textOnPlate`

## Layout

Layout config is baked into the scheme's `blocks.init.screen-scheme`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
block-beta
  columns 3
  header["Header (logo, search, user menu)"]:3
  block:contentRow:3
    columns 3
    sidebar["Sidebar (filters)"]
    block:cardDetail:1
      columns 1
      cardImage["Card image"]
      cardTitle["Card title"]
      cardDescription["Description"]
    end
    aside["Aside (related cards)"]
  end
  actionBar["Action bar (edit, delete, share)"]:3
```
