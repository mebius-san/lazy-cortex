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
- **Every declared ID carries a `class` line — the container blocks included.** For leaf regions the scheme's `.node rect{...!important}` rule paints every node, classed or not, with the `sub` role's plate, so a class-less leaf never renders bare — it just collapses into the `sub` look instead of its intended role. For *container* blocks (`block:<id> … end`) there is no such catch-all: mermaid renders them as `.cluster` elements, and the scheme carries exactly one `.cluster.composite{...!important}` rule and no bare `.cluster{...}` fallback — a container left without `class <id> composite` renders with mermaid's own unstyled cluster look, genuinely illegible next to its coloured neighbours. Coverage is per-ID and total, not per-role.
- A `columns` declaration per row tunes how the regions are packed.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤8 regions per fence; skip if <2 named regions (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by row.

## Roles

`block-beta` accepts `classDef` + `class` syntactically, but in mermaid 11.13 the block renderer never lets a node's `classDef` fill/stroke win the rendered colour — that comes from the scheme's `themeCSS` instead, keyed off the class name the fence assigns. We still use the canonical role vocabulary to distinguish chrome regions from content from auxiliary panels and individual controls.

- `entry` — chrome regions that frame the screen: header bar, footer, persistent action bar.
- `action` — individual controls / content cells inside content blocks: card image, title, description, primary buttons.
- `sub` — auxiliary *leaf* regions: sidebar, aside, and other standalone panels that are not their own `block:<id> … end` container.
- `composite` — structural literal (not a palette role) for region-*grouping* containers opened with `block:<id> … end` — the content-row wrapper, a nested card-detail group. Mermaid renders these as `.cluster` elements, which never carry a per-instance role class the way leaf `.node` elements do, so they share one reserved class instead of `entry`/`action`/`sub`.

## Color binding

Mechanism: `themeCSS` selectors baked into the scheme's `blocks.init.screen-scheme`, not `classDef` fill/stroke. In mermaid 11.13, `classDef`/`class` never reach block-diagram nodes' rendered colour — the block renderer uses the legacy dagre-wrapper, and a leaf node's `classDef` CSS loses the specificity fight against the renderer's own styling. Colour is delivered instead via `themeCSS`: `.node rect` sets the default plate for leaf regions (used by any node without an explicit role override — this is where the `sub` role's colours land), `.node.<role> rect{fill:...;stroke:...}` overrides per role, `.node .label,.node .label *{color:...}` forces label text to `textOnPlate`, and `.cluster.composite{fill:...;stroke:...}` colours the region-grouping *container* blocks — a surface `.node.<role>` cannot reach, because composite containers never carry the role class the way leaf nodes do.

The drawer still emits `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used (plus `classDef composite fill:<sub.fill>,stroke:<sub.stroke>` for the reserved literal), and `class <id> <role-or-composite>` per region/container — this is what carries the ROLE ASSIGNMENT the `themeCSS` selectors key off: `class <id> entry|action` puts that role on a leaf node's DOM class list, matched by `.node.<role> rect`; `class <id> composite` puts the reserved literal on a container's DOM class list, matched by `.cluster.composite`. The `classDef` lines' own fill/stroke values are cosmetically inert (the `themeCSS` `!important` rules win) but stay for mermaid syntax validity and to keep the fence self-documenting. Drawer assigns roles by matching region IDs / labels to the role descriptions above; if a leaf region's role is genuinely ambiguous, default to `action`. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.screen-scheme`; this template never carries literal style values.

- `.node.entry rect`  ← `entry.fill`, `entry.stroke` (label text ← `textOnPlate`)
- `.node.action rect` ← `action.fill`, `action.stroke` (label text ← `textOnPlate`)
- `.node rect` (default plate — also what a `sub`-classed leaf renders as; no dedicated `.node.sub` override exists because `sub` IS the default) ← `sub.fill`, `sub.stroke` (label text ← `textOnPlate`)
- `.cluster.composite` (container blocks: `contentRow`, `cardDetail`, …) ← `sub.fill`, `sub.stroke` — same palette as the leaf default, so grouping containers read as one visual family with unstyled leaves

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
