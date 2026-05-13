---
kind: sequence
purpose: Time-ordered interactions between two or more participants (services, components, actors).
---
# Sequence diagram — canonical exemplar (mermaid)

Used for `kind: sequence`, `format: mermaid`. Skip (return `skipped-below-threshold`) if the request has fewer than 2 distinct participants. Split (return `split-into-N`) when participants > 6 OR messages > 15.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.sequence` from `styles-<scheme>.json` verbatim. Templates carry no init literals. Sequence threads its palette through `themeVariables` (baked into the scheme) because `sequenceDiagram` ignores `classDef` and per-participant `style`.
- Declare every participant up front with `participant <id> as <human-readable label>`.
- Participant IDs are camelCase derived from the request (`browser`, `apiServer`, `db`).
- Every arrow has a label naming the message — never an empty arrow.
- Use `->>` for synchronous calls, `-->>` for responses, `--)` for fire-and-forget, `Note over X,Y:` for state.
- Group related steps with `alt` / `else` / `end` for branches and `loop` for retries — branch labels are concrete (`alt 2xx response` not `alt success`).

## Roles

- `entry` — actor plates (the participant header bar at the top of each lifeline).
- `guard` — `Note over` plates (in-line state annotations).
- `action` — `alt`/`else`/`loop` label-box plates and signal lines.

## Color binding

Mechanism: fuller-init `themeVariables`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.sequence`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

- `primaryColor`        ← `entry.fill`
- `primaryBorderColor`  ← `entry.stroke`
- `primaryTextColor`    ← `textOnPlate`
- `lineColor`           ← `action.stroke`
- `actorBkg`            ← `entry.fill`
- `actorBorder`         ← `entry.stroke`
- `actorTextColor`      ← `textOnPlate`
- `actorLineColor`      ← `entry.stroke`
- `signalColor`         ← `action.stroke`
- `signalTextColor`     ← `textOnCanvas`
- `noteBkgColor`        ← `guard.fill`
- `noteBorderColor`     ← `guard.stroke`
- `noteTextColor`       ← `textOnPlate`
- `labelBoxBkgColor`    ← `guard.fill`
- `labelBoxBorderColor` ← `guard.stroke`
- `labelTextColor`      ← `textOnPlate`
- `loopTextColor`       ← `loopText`

Note: regular signal lines/arrows use `action.stroke` (green family); the alt/loop/opt cycle frame, label tag, and condition text use `guard` (amber family) so cycles read as visually distinct from regular signals.

## Layout

Layout config is baked into the scheme's `blocks.init.sequence`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
sequenceDiagram
  participant browser as Browser
  participant apiServer as API Server
  participant db as Database

  browser->>apiServer: GET /cards/{id}
  apiServer->>db: SELECT card WHERE id = ?
  alt card found
    db-->>apiServer: card row
    apiServer-->>browser: 200 OK + card JSON
  else not found
    db-->>apiServer: empty result
    apiServer-->>browser: 404 Not Found
  end
```
