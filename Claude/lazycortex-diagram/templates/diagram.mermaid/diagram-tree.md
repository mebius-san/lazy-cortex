---
kind: tree
purpose: Hierarchical taxonomy — a single root with descending levels of categories or types. No cross-links, no edge labels.
---
# Tree diagram — canonical exemplar (mermaid)

Used for `kind: tree`, `format: mermaid`. Mermaid `flowchart TD` (top-down). Use `mindmap` if the host prose is brainstorm-shaped (free-form association); use `tree` when the prose is a strict taxonomy.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.tree` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- One root node, descending levels via `-->` (no labels — taxonomic edges have no verb to carry; the every-edge-labelled sanity check is satisfied implicitly because trees have no labelled edges).
- Node IDs are camelCase, label in `[Display name]` brackets.
- Layout direction is `TD` (top-down) by default; `LR` only for genuinely wide-but-shallow taxonomies.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤15 nodes per fence; skip if <3 levels OR <4 leaves (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by top-level branch.

## Roles

- `entry` — the root taxonomy node.
- `sub` — intermediate category nodes (one or more levels of internal branches).
- `leaf` — terminal nodes (taxonomic leaves with no children).

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per node. Every node carries a class — root, internal branches, and leaves. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.tree`; this template never carries literal style values.

- `classDef entry` ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef sub`   ← `sub.fill`, `sub.stroke`, `textOnPlate`
- `classDef leaf`  ← `action.fill`, `action.stroke`, `textOnPlate`

## Layout

Layout config is baked into the scheme's `blocks.init.tree`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
flowchart TD
  card[Card]

  card --> contentCard[Content card]
  card --> referenceCard[Reference card]
  card --> taskCard[Task card]

  contentCard --> noteCard[Note]
  contentCard --> articleCard[Article]
  contentCard --> mediaCard[Media]

  referenceCard --> linkCard[Link]
  referenceCard --> citationCard[Citation]

  taskCard --> todoCard[To-do]
  taskCard --> milestoneCard[Milestone]
```
