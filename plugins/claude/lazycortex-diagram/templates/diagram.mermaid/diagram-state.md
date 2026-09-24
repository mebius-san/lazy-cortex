---
kind: state
purpose: State machine for objects with explicit lifecycle (drafts, orders, sessions, releases).
---
# State diagram — canonical exemplar (mermaid)

Used for `kind: state`, `format: mermaid`. Use `stateDiagram-v2` — the v1 syntax is deprecated. Skip if the request mentions no transitions. Split when more than 8 distinct states — pick a natural sub-machine (e.g. happy path vs. cancellation overlay) and emit each in its own H3-anchored fence.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.state` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- State names are camelCase, mirroring whatever lifecycle terms the host section uses (`draft`, `inReview`, `published`, `cancelled`). Terminology parity is required.
- Every transition carries a `: <event>` label naming the trigger (`draft --> inReview : submit`). Unlabelled transitions are forbidden.
- Use `[*]` for the implicit start and end pseudo-states; declare them explicitly with at least one entry/exit transition each.
- Composite states (`state outerState { ... }`) only when the inner machine genuinely matters; otherwise flatten.

## Roles

- `entry` — initial state right after `[*]` (the lifecycle entry-point state).
- `guard` — review / hold states (the request is waiting on a decision).
- `action` — work-in-progress states (the system is doing something on behalf of the entity).
- `success` — terminal happy-state (e.g. `published`, `delivered`).
- `error` — terminal failure / cancellation state (e.g. `cancelled`, `rejected`).

## Color binding

Mechanism: per-element `style <id> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` directive. Mermaid `stateDiagram-v2` ignores `classDef`+`class`; styling is per-state inline. Drawer emits one `style` line per state that has a role assignment, mapping the state's role to its hex tuple from the scheme. The init directive (state-specific theme keys — `transitionColor`/`transitionLabelColor`/`labelBackgroundColor`/`edgeLabelBackground`/`stateLabelColor` — themeCSS edge-label transparency override, and `'state':{...}` layout block) comes verbatim from the scheme's `blocks.init.state`; this template never carries literal style values.

- per-state role assignment is decided at compose time from the request's lifecycle vocabulary.
- `textOnPlate` colour applies to every styled state.
- success/error states append `stroke-width:<role.strokeWidth>` per the scheme.

## Layout

Layout config is baked into the scheme's `blocks.init.state`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
stateDiagram-v2
  [*] --> draft
  draft --> inReview : submit
  inReview --> draft : reject with notes
  inReview --> published : approve
  published --> [*]

  draft --> cancelled : cancel
  inReview --> cancelled : cancel
  cancelled --> [*]
```
