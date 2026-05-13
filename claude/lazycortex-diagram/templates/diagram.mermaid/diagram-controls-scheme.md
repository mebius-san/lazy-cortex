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
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤16 controls per fence; skip if <3 control families (per drawer agent's § Density check).
- Lock criterion: 3+ real-world controls-scheme diagrams authored across vaults; remove the WIP marker once the contract feels stable.

## Roles

- `guard` — control-family group blocks (`buttons`, `inputs`, `navigation`, `status`, etc.). Amber plate keeps the group frame visually distinct from the green action plates inside it.
- `action` — individual control variants inside a family.

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used. `block-beta` honours classDef on inner blocks; outer family blocks get `class <id> guard`, controls get `class <id> action`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.controls-scheme`; this template never carries literal style values.

- `classDef guard`  ← `guard.fill`, `guard.stroke`, `textOnPlate`
- `classDef action` ← `action.fill`, `action.stroke`, `textOnPlate`

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
