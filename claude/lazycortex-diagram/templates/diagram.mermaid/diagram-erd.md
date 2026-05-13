---
kind: erd
purpose: Entity-relationship diagram for data structures, persisted records, and their relations.
---
# ER diagram — canonical exemplar (mermaid)

Used for `kind: erd`, `format: mermaid`. Skip if fewer than 2 entities. Split when more than 8 entities — pick a natural cut (e.g. user-side vs. content-side) and emit each in its own H3-anchored fence.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.erd` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Entity names are PascalCase singular (`User`, `Card`, `Round`) — match the prose terms in the host section exactly.
- Every relation declares cardinality on both sides using mermaid's `||--o{` family. The relation label names the relationship verb (`User ||--o{ Card : "owns"`).
- Inside an entity, list only the fields the request actually references — not the full schema. Each field has a type and a name; PK/FK markers via `PK` / `FK` after the name.
- PascalCase entity names + labelled relations + terminology parity carry the full meaning.

## Roles

`erDiagram` does not honour per-entity colour, but its global theme keys can be mapped to scheme roles so the whole diagram lands on the canonical palette instead of mermaid's default greys.

## Color binding

Mechanism: fuller-init `themeVariables`. The init directive (theme keys, themeCSS, layout block) comes verbatim from the scheme's `blocks.init.erd`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

Per mermaid's `packages/mermaid/src/diagrams/er/styles.ts` (verified against the bundled mermaid 11.4.1 in Obsidian 1.12.7), the keys that actually drive erd rendering are listed below. `primaryColor`/`primaryBorderColor`/`primaryTextColor` are NOT read directly by the er module — they only cascade into `mainBkg`/`nodeBorder` under `'theme':'base'` (which we forbid). `nodeTextColor` is **not consumed by the er module at all** in current mermaid — it appears only on a generic `.label` selector that does not match erd's `<text class="er entityLabel">` elements. The scheme binds the actual keys.

- `mainBkg`                       ← `entry.fill`        (entity box fill — THE CARDS)
- `nodeBorder`                    ← `entry.stroke`      (entity box border)
- `tertiaryColor`                 ← `edgeLabelBg`       (relationship label box fill — source renders black plate after inversion)
- `lineColor`                     ← `lineOnCanvas`      (relationship lines + markers)
- `textColor`                     ← `textOnPlate`       (entity title text via `.entityTitleText{fill:textColor}` — source renders BLACK on the plate, matching all other kinds' text-on-plate convention)
- `edgeLabelBackground`           ← `edgeLabelBg`       (edge label background plate — source renders BLACK at 50% alpha after inversion)
- `attributeBackgroundColorOdd`   ← `entry.fill`        (attribute row alternation — odd rows match the entity main background)
- `attributeBackgroundColorEven`  ← `sub.fill`          (attribute row alternation — even rows take the `sub` palette; using `entry.fill` lookalikes produces near-invisible alternation, so use a visibly distinct scheme role)

`themeCSS` rules baked into `blocks.init.erd` (Obsidian-only escape hatch — concatenated single string with all rules):

- `text.entityLabel{fill:...}` — attribute row text + entity-name title. Mermaid's er styles.ts emits NO CSS rule for `.entityLabel`, so the SVG default fill wins. The override forces text-on-plate so it renders BLACK on the entity plate after inversion. Selector targets `<text class="er entityLabel">` (used by both the entity title and every attribute-row text emitted in the er renderer); `!important` is required because mermaid's class-attribute precedence beats unflagged user CSS.
- `text.entityLabel:not([id*=-attr-]){font-weight:bold;font-size:...}` — entity-name title only (the header at the top of each card). Verified against `erRenderer.js` (mermaid develop, equivalent to 11.x): the entity title is created with `id="text-<entityId>"` (line 318: `const textId = 'text-' + entityId`). **Attribute texts inherit that prefix** — line 72: `attrPrefix = "${entityTextNode.node().id}-attr-${attrNum}"` — so attribute ids end up as `text-<entityId>-attr-N-{type,name,key,comment}`. ALL entityLabel ids start with `text-`, so a `[id^=text-]` selector matches everything (title + attributes) and was the previous bug. The reliable distinguisher is the `-attr-` infix: title ids never contain it, attribute ids always do. `:not([id*=-attr-])` is title-only. **Selector values are unquoted on purpose** — the whole init directive is a single-quoted string in the `%%{init: ...}%%` line; embedding double-quotes inside breaks mermaid's init parser, which silently drops the entire `themeVariables`/`themeCSS` block and falls back to defaults. CSS allows unquoted attribute values when they're valid `<ident-token>`s, and `-attr-` is one (`-` + ident-start `a` + ident chars `ttr-`, per CSS Syntax Module L3). Two effects: (a) `font-weight:bold` mirrors the class-diagram convention (`.classTitle{font-weight:bolder}` is mermaid's built-in for class titles); (b) shrunken `font-size` matches attribute-row size (mermaid's er renderer renders attributes at `conf.fontSize * 0.85`). The shrunk-+-bold combination produces title/row visual parity, like the class diagram. **If the scheme changes `er.fontSize`, the title font-size in the same scheme block must follow `er.fontSize * 0.85`** — both literals live in `blocks.init.erd`.
- `text.relationshipLabel{fill:...}` — relationship label text on the arrow plates ("owns", "contains", etc.). Mermaid's er styles.ts emits a `.relationshipLabelBox{fill:tertiaryColor}` rule for the plate but **no fill rule for `.relationshipLabel` itself**. The text's actual rendered color depends on whatever generic mermaid CSS happens to inherit (typically near-black, which inverts to near-white but blends into the 0.7-opacity plate). Source value renders WHITE on the BLACK plate after inversion. Distinct from `text.entityLabel` because the surfaces differ: entity text on coloured plates → renders black; relationship text on black plate → renders white.
- `.relationshipLabelBox{opacity:0.5}` — relationship-label plate opacity. Mermaid's default is `opacity:0.7`, which fully obscures the line passing under the label. Dropped to 50% so the line is visible through the plate while the white label text remains legible against the half-transparent black plate.

Caveats (verified against mermaid GitHub issue #2673 and Obsidian forum #67557):

- `classDef` and per-element `style` directives are silently ignored by mermaid's `erDiagram` — do NOT emit them. The fuller-init `themeVariables` block + `themeCSS` is the only working surface.
- `attributeBackgroundColorOdd/Even` had a hardcoded-fill bug in older Obsidian (fixed in Obsidian 1.8). On older Obsidian versions, attribute row backgrounds may render with mermaid's defaults regardless of these keys. The vault's `cssclasses` snippet path is the per-vault workaround when needed; we do not ship CSS.
- `erEdgeLabelBackground` and `nodeTextColor` are NOT consumed by the er module in mermaid 11.4.1 — do NOT emit them. They were tried in earlier iterations and verified to have no rendering effect.

## Layout

Layout config is baked into the scheme's `blocks.init.erd`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
erDiagram
  User ||--o{ Card : "owns"
  Round ||--o{ Card : "contains"
  User {
    string id PK
    string handle
  }
  Card {
    string id PK
    string ownerId FK
    string roundId FK
    string status
  }
  Round {
    string id PK
    timestamp startedAt
    timestamp endedAt
  }
```
