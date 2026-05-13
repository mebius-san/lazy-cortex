---
kind: flow
purpose: Decision-bearing flowchart for user flows, validation flows, and request flows.
---
# Flow diagram — canonical exemplar (mermaid)

Used for `kind: flow`, `format: mermaid`. Default orientation `flowchart LR` (left-to-right) — Obsidian's reading column is wider than tall, and LR keeps the rendered diagram inside one screen at typical zoom. Use `TD` only when the flow is genuinely vertical (deep validation chain, no parallel branches).

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.flow` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Descriptive camelCase node IDs derived from the request's domain terms (e.g. `userOpensCard`, never single letters).
- Every edge carries a `|verb|` label. Unlabelled edges are forbidden.
- Conditional branches use `{...}` decision shapes with at least two outgoing edges. Each outgoing edge is named (`yes`/`no`, `valid`/`invalid`, the actual subcommand chosen, etc.).
- Terminal outcome nodes use the same camelCase scheme; the outcome word ("Done", "Fail") is part of the label, not implied by colour.
- No `click` handlers, no external links, no `linkStyle`.
- Respect the split bound from the drawer agent's § Density check: past 12 nodes or 5 decision points return `split-into-N`.

## Roles

- `entry` — the user-action start node (e.g. "User submits form").
- `guard` — decision diamonds (e.g. "Input valid?").
- `action` — work being performed (e.g. "Persist record").
- `success` — terminal happy-path outcome (e.g. "Show success toast").
- `error` — terminal failure outcome (e.g. "Render field errors").

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per node, with `stroke-width:<role.strokeWidth>` appended where the scheme provides it. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.flow`; this template never carries literal style values.

- `classDef entry`   ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef guard`   ← `guard.fill`, `guard.stroke`, `textOnPlate`
- `classDef action`  ← `action.fill`, `action.stroke`, `textOnPlate`
- `classDef success` ← `success.fill`, `success.stroke`, `textOnPlate`, `success.strokeWidth`
- `classDef error`   ← `error.fill`, `error.stroke`, `textOnPlate`, `error.strokeWidth`

## Layout

Layout config is baked into the scheme's `blocks.init.flow`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
flowchart LR
  userSubmitsForm[User submits form]
  validateInput{Input valid?}
  persistRecord[Persist record]
  showSuccess[Show success toast]
  showFieldErrors[Render field errors]

  userSubmitsForm -->|click submit| validateInput
  validateInput -->|valid| persistRecord
  validateInput -->|invalid| showFieldErrors
  persistRecord -->|ok| showSuccess
  persistRecord -->|server error| showFieldErrors
```
