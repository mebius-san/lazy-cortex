---
kind: controls-scheme
purpose: Design-system control inventory — every control type used in a feature, grouped by family (buttons, inputs, navigation, status). No edges, no flow — purely structural inventory.
status: WIP — v1.5 foundation per `lazy-obsidian.diagram-design.md` §5. Refine after 3+ real authoring rounds.
---
# Controls-scheme diagram — canonical exemplar (mermaid) — WIP

Used for `kind: controls-scheme`, `format: mermaid`. Mermaid `block-beta` with nested blocks. The slot is reserved in v1; the idioms below are tentative. If a caller passes `kind: controls-scheme`, the engine emits the placeholder fence below and warns (per design §5.3 — `v1.5 foundation`).

## Idioms (WIP)

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.controls-scheme` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Outer block per control family — `buttons`, `inputs`, `navigation`, `status`, etc. Inner blocks are individual control variants.
- IDs are camelCase, label in `:` quotes (`primaryButton["Primary button"]`).
- No edges (drawer's every-edge-labelled sanity check trivially satisfied — inventory diagrams have no relationships to label).
- **Every declared ID carries a `class` line — the family blocks included.** For leaf controls the scheme's `.node rect{...!important}` rule paints every node, classed or not, with the `action` role's plate, so a class-less control never renders bare — it just collapses into the `action` look instead of a possibly-intended `guard` role. For *family* blocks (`block:<id> … end`) there is no such catch-all: mermaid renders them as `.cluster` elements, and the scheme carries exactly one `.cluster.composite{...!important}` rule and no bare `.cluster{...}` fallback — a family block left without `class <id> composite` renders with mermaid's own unstyled cluster look, genuinely illegible next to its coloured control children. Coverage is per-ID and total, not per-role.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤16 controls per fence; skip if <3 control families (per drawer agent's § Density check).
- Lock criterion: 3+ real-world controls-scheme diagrams authored across vaults; remove the WIP marker once the contract feels stable.

## Roles

- `guard` — the palette used for control-family group blocks (`buttons`, `inputs`, `navigation`, `status`, etc.). Amber keeps the group frame visually distinct from the green action plates inside it. Reaches the render only through the `composite` literal below — `guard` itself is never a `class` value in this kind's fences.
- `action` — individual control variants inside a family. Also the *default* leaf palette: any unclassed control still renders action-green.
- `composite` — structural literal (not a palette role) assigned to the family group blocks. Mermaid renders `block:<id> … end` groups as `.cluster` elements, which never carry a per-instance role class the way leaf `.node` elements do, so every family group shares this one reserved class instead of `guard` directly.

## Color binding

Mechanism: `themeCSS` selectors baked into the scheme's `blocks.init.controls-scheme`, not `classDef` fill/stroke. In mermaid 11.13, `classDef`/`class` never reach block-diagram nodes' rendered colour — the block renderer uses the legacy dagre-wrapper, and a leaf node's `classDef` CSS loses the specificity fight against the renderer's own styling. Colour is delivered instead via `themeCSS`: `.node rect` sets the default plate for leaf controls (used by any node without an explicit override — this is where the `action` role's colours land), `.node.action rect` / `.node.guard rect` restate the per-role overrides explicitly, `.node .label,.node .label *{color:...}` forces label text to `textOnPlate`, and `.cluster.composite{fill:...;stroke:...}` colours the family *group* blocks amber (`guard`'s palette) — a surface `.node.guard` cannot reach, because family blocks never carry the role class the way leaf controls do.

The drawer still emits `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used (plus `classDef composite fill:<guard.fill>,stroke:<guard.stroke>` for the reserved literal), and `class <id> <role-or-composite>` per block: `class <id> action` for individual controls, `class <id> composite` for family group blocks. `class <id> composite` is what carries the ROLE ASSIGNMENT the `.cluster.composite` selector keys off — it puts the reserved literal on a family block's DOM class list, and `guard`'s palette is what that selector resolves to. The `classDef` lines' own fill/stroke values are cosmetically inert (the `themeCSS` `!important` rules win) but stay for mermaid syntax validity and to keep the fence self-documenting. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.controls-scheme`; this template never carries literal style values.

- `.node.action rect` ← `action.fill`, `action.stroke` (label text ← `textOnPlate`) — also `.node rect`'s default, so an unclassed leaf control renders identically
- `.node.guard rect` ← `guard.fill`, `guard.stroke` (label text ← `textOnPlate`) — declared for closure parity; this kind's fences reach `guard`'s palette only via `.cluster.composite`, never by classing a leaf `guard`
- `.cluster.composite` (family group blocks: `buttons`, `inputs`, `navigation`, `status`) ← `guard.fill`, `guard.stroke`

## Layout

Layout config is baked into the scheme's `blocks.init.controls-scheme`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar — refine in v1.5

```mermaid
<<init>>
block-beta
  columns 1
  block:buttons
    columns 3
    primaryButton["Primary button"]
    secondaryButton["Secondary button"]
    iconButton["Icon button"]
  end
  block:inputs
    columns 3
    textInput["Text input"]
    textArea["Multi-line text"]
    dropdown["Dropdown"]
  end
  block:navigation
    columns 3
    tabBar["Tab bar"]
    breadcrumbs["Breadcrumbs"]
    backLink["Back link"]
  end
  block:status
    columns 3
    toast["Toast"]
    badge["Badge"]
    spinner["Spinner"]
  end
```
