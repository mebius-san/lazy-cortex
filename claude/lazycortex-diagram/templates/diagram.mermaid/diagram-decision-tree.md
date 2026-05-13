---
kind: decision-tree
purpose: Pure decision branches — every node is a yes/no (or n-way) question, every leaf is an outcome. No mixed action/decision nodes.
---
# Decision-tree diagram — canonical exemplar (mermaid)

Used for `kind: decision-tree`, `format: mermaid`. Mermaid `flowchart TD` (top-down). All non-leaf nodes are diamond-shaped (`{Question?}`); leaves are rectangles. Use `flow` if the diagram mixes actions and decisions; `decision-tree` is the strict pure-branching variant.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.decision-tree` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Every non-leaf node uses the diamond form `{Question?}` — never `[box]` for questions. Leaves use `[Outcome]`.
- Every `-->` carries `|<answer>|` (per drawer agent sanity check 4) — typically `|yes|` / `|no|` for binary, or `|short answer phrase|` for n-way.
- Layout direction `TD` (top-down) by default; `LR` only when the tree is genuinely wide.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤12 nodes per fence; skip if <2 branches (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by top-level decision.

## Roles

- `guard` — decision diamond nodes (`{Question?}`).
- `success` — terminal positive-outcome leaf nodes.
- `error` — terminal negative-outcome leaf nodes (when the host prose distinguishes positive vs negative outcomes; otherwise omit and use only `success`).

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per node, with `stroke-width:<role.strokeWidth>` appended where the scheme provides it. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.decision-tree`; this template never carries literal style values.

- `classDef guard`   ← `guard.fill`, `guard.stroke`, `textOnPlate`
- `classDef success` ← `success.fill`, `success.stroke`, `textOnPlate`, `success.strokeWidth`
- `classDef error`   ← `error.fill`, `error.stroke`, `textOnPlate`, `error.strokeWidth`

## Layout

Layout config is baked into the scheme's `blocks.init.decision-tree`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
flowchart TD
  isPublic{Make card public?}
  hasViewers{Viewer list provided?}
  needsExpiry{Set expiry?}

  publicLink[Outcome: public link]
  privateLink[Outcome: private link, no viewers]
  privateLinkViewers[Outcome: private link with viewer list]
  privateLinkExpiry[Outcome: private link with viewers and expiry]

  isPublic -->|yes| publicLink
  isPublic -->|no| hasViewers
  hasViewers -->|no| privateLink
  hasViewers -->|yes| needsExpiry
  needsExpiry -->|no| privateLinkViewers
  needsExpiry -->|yes| privateLinkExpiry
```
