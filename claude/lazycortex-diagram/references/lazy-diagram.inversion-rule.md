---
description: Authoritative source for clause-8 inversion checking — surfaces, source-hex requirements, and how the active scheme's `blocks.init.<kind>` resolves to render-correct colours under Obsidian's dark-theme `invert + hue-rotate` filter.
---
# Inversion rule (Obsidian dark theme)

Authoritative source for clause-8 inversion checking. Templates' `## Color binding` mappings + the rendered fence's `themeVariables` (resolved from the active scheme's `blocks.init.<kind>`) must agree with this rule.

## The rule

Obsidian's dark theme applies CSS `invert(1) hue-rotate(180deg)` to embedded SVG. Every source colour is therefore inverted before display: `#000` → renders white, `#fff` → renders black, dark blue → renders light cream, etc. The scheme is authored so that, *after* inversion, text remains readable on whatever surface it sits on.

## Surfaces

A "surface" is the visual layer a colour will be drawn on. Each binding in a template's `## Color binding` mapping has exactly one surface implied by the mermaid key it sets. The clause-8 validator resolves each binding through the active scheme's `roles{}` / `textConstants{}` (default scheme = `styles-default.json`) and asserts the rendered hex (as embedded in the scheme's `blocks.init.<kind>`) matches the surface's expected value.

| surface tag         | source hex (must be) | renders as              | role-field that satisfies it           |
|---------------------|----------------------|-------------------------|----------------------------------------|
| `text-on-canvas`    | `#000`               | white on dark canvas    | `textOnCanvas`                         |
| `line-on-canvas`    | `#000`               | white on dark canvas    | `lineOnCanvas`                         |
| `text-on-plate`     | `#fff`               | black on light-rendered plate | `textOnPlate`                    |
| `edge-label-bg`     | `#fff`               | black plate on canvas (paired with `text-on-canvas` text → white-on-black) | `edgeLabelBg` |
| `plate-fill`        | scheme `<role>.fill`  | inverted plate colour   | `entry.fill`, `action.fill`, etc.     |
| `plate-stroke`      | scheme `<role>.stroke`| inverted stroke colour  | `entry.stroke`, `action.stroke`, etc. |
| `accent-on-plate`   | scheme accent        | inverted accent         | e.g. `loopText`                        |

`plate-fill` / `plate-stroke` / `accent-on-plate` are *value-class* checks — the rendered hex must be one of the scheme-defined values, not an arbitrary literal. They do not have a single fixed expected hex.

`text-on-canvas`, `line-on-canvas`, `text-on-plate`, and `edge-label-bg` are *fixed-hex* checks — the rendered value must equal the scheme constant.

## Why both surfaces and the scheme?

- The **scheme constants** (`textOnCanvas=#000`, `textOnPlate=#fff`, etc.) encode the inversion-rule outcome.
- The **template bindings** map mermaid's per-kind theme keys onto those constants.
- The **fence output** must emit the resolved hex for each key.

A bug at any of those three layers is a surface violation:
- Template binds the wrong constant for a key (e.g. `textColor ← textOnPlate` when `textColor` is a canvas surface) → template-level bug.
- Drawer agent emits a literal hex that doesn't match the resolved binding → drawer-level bug.
- Scheme constant changed without updating templates → scheme drift.

Clause-8 catches all three.

## Surface assignment per mermaid key (canonical)

| mermaid key                     | surface              |
|---------------------------------|----------------------|
| `lineColor`                     | `line-on-canvas`     |
| `textColor`                     | `text-on-canvas`     |
| `edgeLabelBackground`           | `edge-label-bg`      |
| `nodeTextColor`                 | `text-on-plate`      |
| `primaryTextColor`              | `text-on-plate`      |
| `primaryColor`                  | `plate-fill`         |
| `primaryBorderColor`            | `plate-stroke`       |
| `attributeBackgroundColorOdd`   | `plate-fill`         |
| `attributeBackgroundColorEven`  | `plate-fill`         |
| `transitionColor`               | `line-on-canvas`     |
| `transitionLabelColor`          | `text-on-canvas`     |
| `labelBackgroundColor`          | `edge-label-bg`      |
| `stateLabelColor`               | `text-on-plate`      |
| `signalColor`                   | `plate-stroke`       |
| `signalTextColor`               | `text-on-canvas`     |
| `actorBkg`                      | `plate-fill`         |
| `actorBorder`                   | `plate-stroke`       |
| `actorTextColor`                | `text-on-plate`      |
| `actorLineColor`                | `plate-stroke`       |
| `noteBkgColor`                  | `plate-fill`         |
| `noteBorderColor`               | `plate-stroke`       |
| `noteTextColor`                 | `text-on-plate`      |
| `labelBoxBkgColor`              | `plate-fill`         |
| `labelBoxBorderColor`           | `plate-stroke`       |
| `labelTextColor`                | `text-on-plate`      |
| `loopTextColor`                 | `accent-on-plate`    |
| `cScale0..11`                   | `plate-fill`         |
| `cScaleLabel0..11`              | `text-on-plate`      |
| `fillType0..3`                  | `plate-fill`         |
| `mainBkg`                       | `plate-fill`         |
| `nodeBorder`                    | `plate-stroke`       |
| `faceColor`                     | `accent-on-plate`    |
| `actor0..7`                     | `plate-stroke`       |
| `sectionBkgColor`               | `plate-fill`         |
| `altSectionBkgColor`            | `plate-fill`         |
| `taskBkgColor`                  | `plate-fill`         |
| `taskBorderColor`               | `plate-stroke`       |
| `taskTextColor`                 | `text-on-plate`      |
| `taskTextOutsideColor`          | `text-on-canvas`     |
| `doneTaskBkgColor`              | `plate-fill`         |
| `doneTaskBorderColor`           | `plate-stroke`       |
| `critBkgColor`                  | `plate-fill`         |
| `critBorderColor`               | `plate-stroke`       |
| `activeTaskBkgColor`            | `plate-fill`         |
| `activeTaskBorderColor`         | `plate-stroke`       |
| `gridColor`                     | `line-on-canvas`     |
| `todayLineColor`                | `accent-on-plate`    |

This table is the law. If a template binding contradicts it, the template is wrong.

## Empirical exceptions

The table above describes the *intended* surface for each key based on what the key controls in mermaid's source. Some kinds render text inside elements that, due to mermaid's SVG group structure or class application, do NOT receive the same inversion path as ordinary plate text. In those cases the empirically-correct binding flips from `text-on-plate` to `text-on-canvas` (or vice versa).

| kind | key | canonical surface | empirical surface | reason |
|---|---|---|---|---|
| `erd` | `textColor` | `text-on-canvas` | **`text-on-plate`** (`#fff`) | mermaid's er styles.ts binds `.entityTitleText{fill:textColor}` — the entity title sits on the entity plate, not the canvas. Source `#fff` renders BLACK on the plate, matching all other kinds' text-on-plate convention. The canonical table maps `textColor` to `text-on-canvas` because most kinds use it as the generic canvas-text fallback; erd is the exception. |
| `erd` | `themeCSS` selector `text.entityLabel` | (n/a — raw CSS) | **`text-on-plate`** (`#fff`) | mermaid's er styles.ts emits no CSS rule for `.entityLabel`, so SVG default `fill` (black) wins → renders WHITE on the dark plate (illegible). The class is applied to both the entity-name title and every attribute-row text node (verified in mermaid 11.4.1 renderer). Override via `themeCSS:'text.entityLabel{fill:#fff!important}'` so source `#fff` renders BLACK on the entity plate. |
| `erd` | `themeCSS` selector `text.relationshipLabel` | (n/a — raw CSS) | **`text-on-canvas`** (`#000`) — sits on edge-label plate | mermaid's er styles.ts emits `.relationshipLabelBox{fill:tertiaryColor}` for the plate but **no fill rule for `.relationshipLabel`** itself. The text falls back to whatever generic mermaid CSS inherits (typically near-black), which inverts to near-white but blends into the 0.7-opacity plate. Override via `themeCSS:'text.relationshipLabel{fill:#000!important}'` so source `#000` renders WHITE on the black plate (`tertiaryColor:#fff` source → black). The "canonical" surface here is the relationship-label plate, which is rendered black via `tertiaryColor:#fff` — so source `#000` is correct (white text on black plate, like every other edge-label-text-on-edge-label-bg pair). |
| `journey` | `sectionColours[*]` | (n/a — not a themeVariable) | **`text-on-canvas`** (`#000`) | mermaid's journey renderer (`packages/mermaid/src/diagrams/user-journey/journeyRenderer.ts:226,259-269`) sets task-label text fill via an **inline `fill="<colour>"` attribute** assigned from `conf.sectionColours[N % length]`. Inline attribute beats every CSS theme key. Mermaid default `['#fff']` renders BLACK on the dark inverted plate inside cards. Override `sectionColours` to `['#000']` so card text renders white. This is a `journey`-scoped config field, not a themeVariable. (Note: `sectionColours` is also array-typed and gets dropped by Obsidian's sanitizer — see § Obsidian sanitizer constraint. Cross-platform parity only; in Obsidian, override task-label color via `themeCSS` instead — see § foreignObject inversion exception below.) |
| `journey` | `themeCSS` selector `.label` | (n/a — raw CSS) | **inverse of canvas text** (`#fff`) | mermaid 11.4.1 journey defaults `textPlacement:"fo"` — task labels render as `<div class="label">` **inside `<foreignObject>`**. HTML content inside `<foreignObject>` does NOT participate in the SVG's `filter: invert(100%) hue-rotate(180deg)` the way SVG children do. So the source color is the rendered color, **with no inversion compensation**. To get white-rendered card text in Obsidian dark, write `themeCSS:'.label{color:#fff!important}'` — straight, not flipped. The sibling `text.task{fill:#000!important}` rule (for the SVG `<text>` fallback inside `<switch>`) keeps the canonical inverted source `#000` because that path IS inverted. **Two paths, two source colors, opposite hexes.** Verified by user visual test in Obsidian dark. |

When a kind's template documents an empirical exception in its `## Color binding` section, the template overrides the canonical table for that key on that kind only. Clause-8 validators must consult the kind's template before flagging a "violation".

## Inline-fill caveats

A handful of mermaid kinds bypass themeVariables entirely by emitting per-element inline `fill` / `style` attributes. These cannot be themed via `themeVariables`; they require kind-specific config blocks inside the init directive. Known cases:

- `journey` — task-label text fill comes from the kind config field `sectionColours` (array). See empirical-exception row above.

When you discover a new inline-fill case while authoring a kind's template, append it here AND document the binding in that kind's `## Color binding` section.

## foreignObject inversion exception

Some mermaid kinds emit text via SVG `<foreignObject>` containing HTML elements (`<div>`, `<span>`) instead of native SVG `<text>`. **HTML content inside `<foreignObject>` does NOT invert under Obsidian's `filter: invert(100%) hue-rotate(180deg)` filter the way SVG children do** — the source color is the rendered color (no flip).

This is the opposite of the canonical inversion rule. When picking a `themeCSS` color that targets foreignObject-rendered text, use the **straight visual hex** (white = `#fff`, black = `#000`), not the inverted source.

Concrete impact:

- `journey` with `textPlacement:"fo"` (default in mermaid 11.4.1) → task labels render as `<div class="label">` inside `<foreignObject>`. To paint them white, write `themeCSS:'.label{color:#fff!important}'`.
- The same diagram's SVG `<text class="task">` fallback (inside the `<switch>`) IS inverted normally → `text.task{fill:#000!important}` to render white.

Detection: run `grep -oE 'textPlacement[^,}]{0,30}' /path/to/mermaid.min.js` against the bundled mermaid (extract `obsidian.asar` first). If the kind's renderer uses `textPlacement:"fo"` or otherwise emits `<foreignObject>`, this exception applies to any `themeCSS` rule that targets HTML elements inside it.

When you discover a new kind that renders text via foreignObject, document its empirical-surface exception in the table above AND extend this section with the kind name.

## Obsidian sanitizer constraint (verified)

Obsidian wraps mermaid behind a sanitizer that walks an allowlist built by `keyify` over mermaid's *defaults*. Verified directly from the bundled bytes at `/Applications/Obsidian.app/Contents/Resources/obsidian.asar` → `lib/mermaid.min.js`:

```javascript
Bz=o((t,e="")=>Object.keys(t).reduce((r,n)=>
  Array.isArray(t[n])?r:                          // ARRAYS SKIPPED FROM ALLOWLIST
  typeof t[n]=="object"&&t[n]!==null?[...r,e+n,...Bz(t[n],"")]:
  [...r,e+n],[]),"keyify");
Fz=new Set(Bz(Pz,""));
// sanitizeDirective:
if(!Fz.has(e)||t[e]==null){delete t[e]; continue}
// themeCSS allowed (raw passthrough):
let r=["themeCSS","fontFamily","altFontFamily"];
for(let n of r) e.includes(n) && (t[e]=tbe(t[e]))
```

Consequences for any mermaid template that targets Obsidian:

- **Array-typed init keys are silently dropped.** `journey.sectionColours`, `journey.sectionFills`, `journey.actorColours` — none take effect inside Obsidian. Keep them in the template for cross-platform parity (mermaid CLI, mermaid-live, GitHub all honour them) but never rely on them for Obsidian-readable output.
- **Non-default themeVariable keys are dropped.** Only keys present in mermaid's default theme block survive. `actor0..5`, `fillType0..7`, `mainBkg`, `nodeBorder`, `faceColor`, `lineColor`, `textColor` are all defaults — those work. Made-up keys do not.
- **`themeCSS` is the escape hatch.** Plus `fontFamily` / `altFontFamily`. These three are explicitly whitelisted as raw-string passthroughs (with a CSS sanitization pass via `tbe`). Use `themeCSS` to override mermaid's hardcoded class CSS rules (e.g. `.label text { fill: #333 }`) when no themeVariable controls the surface.
- **Use `!important` inside `themeCSS`.** CSS specificity alone won't beat inline `fill` attributes that mermaid renderers write onto SVG elements (e.g. journey task labels via `sectionColours`). `!important` does — it elevates the rule above inline attribute precedence.

Source-of-truth note: this constraint is Obsidian-specific. Standalone mermaid renderers (CLI, mermaid-live, GitHub's renderer) honour the full init schema, so cross-platform templates keep the kind-config block as a fallback.
