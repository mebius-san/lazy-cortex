---
kind: class
purpose: Class/interface relationships for OOP-shaped designs — inheritance, composition, key methods.
---
# Class diagram — canonical exemplar (mermaid)

Used for `kind: class`, `format: mermaid`. Skip if a single class — prose wins. Past 6 classes the upper bound is advisory: keep one fence with subgraph-style grouping when the classes form one tightly-coupled hierarchy; split into N H3-anchored fences when they cluster into independent groups.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.class` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Class names match the prose exactly (PascalCase). Do not abbreviate or pluralize.
- Show only the methods/fields that are referenced in the host section's prose; never dump the full surface.
- Use mermaid's relation arrows: `<|--` (inheritance), `*--` (composition), `o--` (aggregation), `..>` (dependency). Every relation has a label.

## Roles

- `entry` — interface / abstract contract classes (the type other classes implement against).
- `action` — every other concrete class (implementers AND collaborators reached via `..>`/`*--`/`o--`).

## Color binding

Mechanism: per-element `style <id> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>` directive. Mermaid `classDiagram` ignores `classDef`+`class`; styling is per-class inline. Drawer emits one `style` line per class, mapping its role to the hex tuple from the scheme. The init directive (theme keys, themeCSS, layout block — including the class-specific edge-label transparency override that compensates for mermaid's class module wiring `.labelBkg`/`.edgeLabel .label span`/`.edgeLabel .label rect` to `mainBkg` with no built-in `opacity:0.5`) comes verbatim from the scheme's `blocks.init.class`; this template never carries literal style values.

- Role assignment: any class declared with `<<interface>>` or `<<abstract>>` stereotype, OR sitting at the contract end of `<|--`/`<|..` → `entry`. Every other class on the diagram → `action`. No class is left unstyled.
- `textOnPlate` colour applies to every styled class.

## Layout

Layout config is baked into the scheme's `blocks.init.class`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
classDiagram
  class CardValidator {
    <<interface>>
    +validate(card) Result
  }
  class ServerValidator {
    +validate(card) Result
    -callApi(card)
  }
  class LocalValidator {
    +validate(card) Result
    -checkSchema(card)
  }
  class ApiClient {
    +post(url, body)
  }
  CardValidator <|.. ServerValidator : implements
  CardValidator <|.. LocalValidator : implements
  ServerValidator ..> ApiClient : uses
```
