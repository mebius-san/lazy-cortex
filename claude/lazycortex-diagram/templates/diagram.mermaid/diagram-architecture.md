---
kind: architecture
purpose: System components and the wires between them — services, layers, stores — grouped by subgraph (one subgraph per layer).
---
# Architecture diagram — canonical exemplar (mermaid)

Used for `kind: architecture`, `format: mermaid`. Mermaid `flowchart` with `subgraph` blocks per layer (frontend, backend, data, integrations). Use `c4-context` / `c4-container` only if the host project explicitly opts into C4 vocabulary; default architectural drawings stay in this kind.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.architecture` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- One `subgraph <id> [<Display name>]` per layer. Component nodes inside use camelCase IDs and a human label in `[Display name]` brackets.
- Every `-->` carries `|<verb phrase>|` (per drawer agent sanity check 4 — every-edge-labelled). Cross-layer wires read as the action: `|writes audit event|`, `|requests token|`.
- No `click` handlers, no external links, no `linkStyle`.
- Density bound: ≤12 nodes per fence; skip if <3 distinct components (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by layer.

## Roles

- `entry` — frontend / UI components (the user-facing entry points to the system).
- `action` — application-tier services (work-doing components).
- `service` — external dependencies (third-party gateways, integrations).
- `store` — data stores (databases, caches, persisted artifacts).
- `ref` — cross-fence references (dashed link to a component defined in another diagram).

## Color binding

Mechanism: `classDef` + `class`. Drawer emits one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` per role used, plus `class <id> <role>` per node. The `ref` role uses `stroke` + `stroke-dasharray:5 5` only (no fill, dashed boundary per `ref.dashed: true`). The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.architecture`; this template never carries literal style values.

- `classDef entry`   ← `entry.fill`, `entry.stroke`, `textOnPlate`
- `classDef action`  ← `action.fill`, `action.stroke`, `textOnPlate`
- `classDef service` ← `service.fill`, `service.stroke`, `textOnPlate`
- `classDef store`   ← `store.fill`, `store.stroke`, `textOnPlate`
- `classDef ref`     ← `ref.stroke`, `textOnPlate`, `stroke-dasharray:5 5` (dashed, no fill)

## Layout

Layout config is baked into the scheme's `blocks.init.architecture`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
flowchart LR
  subgraph frontend [Frontend]
    webApp[Web app]
    mobileApp[Mobile app]
  end

  subgraph backend [Backend]
    apiServer[API server]
    cardService[Card service]
    authService[Auth service]
  end

  subgraph data [Data]
    cardDb[(Card DB)]
    cache[(Redis cache)]
  end

  subgraph integrations [Integrations]
    emailGateway[/Email gateway/]
    auditStream[/Audit stream/]
  end

  webApp -->|fetches data| apiServer
  mobileApp -->|fetches data| apiServer
  apiServer -->|delegates card ops| cardService
  apiServer -->|validates token| authService
  cardService -->|reads/writes| cardDb
  cardService -->|reads cached card| cache
  cardService -->|sends share notice| emailGateway
  cardService -->|emits CardCreated| auditStream
```
