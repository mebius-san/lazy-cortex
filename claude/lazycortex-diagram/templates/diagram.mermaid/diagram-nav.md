---
kind: nav
purpose: Navigation / sitemap — destinations the user can reach and the links between them, with link labels naming the navigation action.
---
# Nav diagram — canonical exemplar (mermaid)

Used for `kind: nav`, `format: mermaid`. Mermaid `flowchart`, with nodes representing destinations (pages, screens, modals) and edges representing navigation actions. Use `flow` instead when the host prose is a control/decision flow rather than a sitemap.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.nav` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Nodes are destinations — camelCase IDs, human label in `[Display name]` brackets. No abstract verbs as node names.
- Every `-->` carries `|<verb phrase>|` (per drawer agent sanity check 4). Common verbs: `|click cards tab|`, `|select card|`, `|tap share|`. Do NOT wrap UI strings in double quotes inside the pipe-label — mermaid's parser rejects `"..."` mid-label. Render the visible UI string in lowercase prose, or rephrase to avoid quoting.
- Modal-style destinations get the rounded form `(Modal name)`; full pages get `[Page name]`.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤15 nodes per fence; skip if <3 destinations (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by top-level section.

## Roles

- `entry` — the home / start destination the user lands on by default.
- `sub` — modal-style destinations (rounded `(...)` form).
- `action` — regular page destinations.

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per node. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.nav`; this template never carries literal style values.

- `classDef entry`  ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef sub`    ← `sub.fill`, `sub.stroke`, `textOnPlate`
- `classDef action` ← `action.fill`, `action.stroke`, `textOnPlate`

## Layout

Layout config is baked into the scheme's `blocks.init.nav`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
flowchart LR
  home[Home dashboard]
  cardList[Cards list]
  cardDetail[Card detail]
  cardEditor[Card editor]
  shareModal(Share modal)
  settings[Settings]
  account[Account]

  home -->|click cards tab| cardList
  home -->|click settings| settings
  cardList -->|select card| cardDetail
  cardList -->|click new card| cardEditor
  cardDetail -->|click edit| cardEditor
  cardDetail -->|click share| shareModal
  shareModal -->|click send| cardDetail
  settings -->|click account| account
```
