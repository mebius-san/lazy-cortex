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
- **No edges.** A layout states adjacency through the grid, never through arrows. A request that wants relationships between regions is not a layout — it is a `flow` or an `architecture`, and the drawer must not satisfy it by hanging `-->` off block-beta regions.
- **No composite `block:<id> … end` containers.** `layout` is a flat grid of regions; nesting controls inside a region is what `screen-scheme` is for. `block:<id>:<cells>` as a pure span declaration on a leaf region stays allowed — the forbidden shape is the one that opens its own `columns` and encloses child regions before `end`.
- **Every declared region ID carries a `class` line.** The scheme's `themeCSS` `.node rect{...!important}` rule paints every node — classed or not — with the `sub` role's plate plus white label text, so a class-less region never renders bare or illegible; but it also never differentiates from its neighbours. Skipping `class` on a region silently collapses it into the `sub` look regardless of its actual role, which reads as visually wrong next to correctly-classed `entry`/`action` neighbours. Coverage is per-ID and total, not per-role.
- Annotate non-obvious regions with a `%% <id>: <one-line purpose>` comment line above the block declaration when their role isn't clear from the label.

## Roles

`block-beta` accepts `classDef` + `class` syntactically, but in mermaid 11.13 the block renderer (the legacy dagre-wrapper) never lets a node's `classDef` fill/stroke win the rendered style — colour comes from the scheme's `themeCSS` instead, keyed off the class name the fence assigns. We still use the canonical role vocabulary to distinguish chrome regions from content from navigation; `class <id> <role>` is what actually wires a region to its colour.

- `entry` — chrome regions: header, footer, actionBar (the persistent frame).
- `action` — primary content regions: mainContent, body, primary card-detail blocks.
- `sub` — auxiliary regions: sidebar, aside, navigation panels, related-content rails.

## Color binding

Mechanism: `themeCSS` role selectors baked into the scheme's `blocks.init.layout`, not `classDef` fill/stroke. In mermaid 11.13, `classDef`/`class` never reach block-diagram nodes' rendered colour — the block renderer uses the legacy dagre-wrapper, and a leaf node's `classDef` CSS loses the specificity fight against the renderer's own styling. Colour is delivered instead via `themeCSS`: `.node rect` sets the default plate (used by any node without an explicit role override — this is where the `sub` role's colours land), `.node.<role> rect{fill:...;stroke:...}` overrides per role, and `.node .label,.node .label *{color:...}` forces label text to `textOnPlate`. A `.cluster.composite{fill:...;stroke:...}` rule is also baked into the init string for composite containers, but this kind's "no composite `block:<id> … end`" idiom means it is never exercised here — it exists for closure parity with the sibling `screen-scheme`/`controls-scheme` kinds, which share the same style-scheme shape.

The drawer still emits `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per region — this is what carries the ROLE ASSIGNMENT the `themeCSS` selectors key off: `class <id> <role>` puts `<role>` on the node's DOM class list, and `.node.<role> rect` matches exactly that. The `classDef` line's own fill/stroke values are cosmetically inert (the `themeCSS` `!important` rules win) but the line stays for mermaid syntax validity and to keep the fence self-documenting. Drawer assigns roles by matching region IDs / labels to the role descriptions above; if a region's role is genuinely ambiguous, default to `action`. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.layout`; this template never carries literal style values.

- `.node.entry rect`  ← `entry.fill`, `entry.stroke` (label text ← `textOnPlate`)
- `.node.action rect` ← `action.fill`, `action.stroke` (label text ← `textOnPlate`)
- `.node rect` (default plate — also what a `sub`-classed region renders as; no dedicated `.node.sub` override exists because `sub` IS the default) ← `sub.fill`, `sub.stroke` (label text ← `textOnPlate`)

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
