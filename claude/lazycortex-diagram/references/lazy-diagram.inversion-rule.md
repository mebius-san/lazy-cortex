---
description: Authoritative source for clause-8 inversion checking — surfaces, source-hex requirements, and how the active scheme's `blocks.init.<kind>` resolves to render-correct colours under Obsidian's dark-theme `invert + hue-rotate` filter.
---
# Inversion rule (Obsidian dark theme)

Authoritative source for clause-8 inversion checking. Templates' `## Color binding` mappings + the rendered fence's `themeVariables` (resolved from the active scheme's `blocks.init.<kind>`) must agree with this rule.

## The rule

Obsidian core's `app.css` applies `filter: invert(100%) hue-rotate(180deg) saturate(1.25)` to `.theme-dark .mermaid > svg` — a whole-SVG raster filter applied *after* render, and it fires in **dark mode only**. This is the only mode-aware colouring mechanism in play: it is not the `img[src$="#invert"]` rule (that targets `<img>` elements, irrelevant to rendered mermaid SVGs), and it is not specific to any one Obsidian theme — any theme that leaves Obsidian in dark mode gets it, because it lives in core CSS, not a theme stylesheet. Obsidian calls `mermaid.initialize` with no `theme` key, so mermaid always renders its stock `theme:"default"`; neither Obsidian nor any theme colours mermaid nodes via CSS variables.

In light mode there is no filter at all — source colours render literally. In dark mode, every source colour is inverted before display: `#000` → renders white, `#fff` → renders black, dark blue → renders light cream, etc. The scheme is authored so that a single source colour reads correctly in **both** modes at once: literally in light mode, inverted in dark mode. That is only possible for neutral-gray text (`R=G=B`, where hue-rotate is a no-op and invert is a clean lightness flip) — which is why every inversion-aware text binding in this doc is `#fff` or `#000`, never a hue.

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
| `attributeBackgroundColorOdd` (DEAD — replaced by `rowOdd` since mermaid 11.5's unified ER renderer; do not bind) | `plate-fill` |
| `attributeBackgroundColorEven` (DEAD — replaced by `rowEven` since mermaid 11.5's unified ER renderer; do not bind) | `plate-fill` |
| `rowOdd`                        | `plate-fill`         |
| `rowEven`                       | `plate-fill`         |
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
| `fillType0..3` (DEAD for `journey` — that kind no longer sets `themeVariables` at all; colour comes from `themeCSS` `rect.section-type-N`/`rect.task-type-N`, see the journey template's `## Color binding`) | `plate-fill` |
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
| `erd` | `textColor` / `nodeTextColor` | `text-on-canvas` | **`text-on-plate`** (`#fff`) | mermaid's unified ER renderer (11.5+) binds both keys to text that sits on the entity plate (title and attribute rows), not the canvas. Source `#fff` renders BLACK on the plate, matching every other kind's text-on-plate convention. The canonical table maps `textColor` to `text-on-canvas` because most kinds use it as the generic canvas-text fallback; erd is the exception. |

Two former rows in this table — `erd`'s `themeCSS` `text.entityLabel` override and `text.relationshipLabel` override, and `journey`'s `sectionColours[*]` config array and `themeCSS` `.label` override — documented workarounds for mechanisms that mermaid 11.13 no longer has:

- `erd`'s relationship-label plate is now styled through the generic `.edgeLabel rect,.edgeLabel .labelBkg` / `.edgeLabel,.edgeLabel .label *,.edgeLabel text` selectors the unified renderer shares with other diagram kinds — the standard `edge-label-bg` (`#fff`) + `text-on-canvas` (`#000`) pairing from the canonical table above, no exception needed. See `diagram-erd.md`'s `## Color binding`.
- `journey` no longer renders task/section labels through `<foreignObject>` at all (see § foreignObject inversion exception below) — the scheme forces `journey.textPlacement:'old'`, so labels are plain SVG `<text>` on a role-coloured plate, the standard `text-on-plate` (`#fff`) convention. `sectionColours` and every other array-typed journey config key are unused. See `diagram-journey.md`'s `## Color binding`.

When a kind's template documents an empirical exception in its `## Color binding` section, the template overrides the canonical table for that key on that kind only. Clause-8 validators must consult the kind's template before flagging a "violation".

## Inline-fill caveats

A handful of mermaid kinds bypass themeVariables entirely by emitting per-element inline `fill` / `style` attributes. These cannot be themed via `themeVariables`; they require either a `themeCSS` override (with `!important`, to beat the inline attribute's specificity) or a kind-specific config block inside the init directive. No currently-shipped kind hits this — `journey` used to (task-label fill via the array-typed `sectionColours` config field), until the scheme switched it to `journey.textPlacement:'old'`, which renders labels as plain SVG `<text>` styled by `themeCSS` instead of inline-attributed `<div>`/`<text>` content.

When you discover a new inline-fill case while authoring a kind's template, append it here AND document the binding in that kind's `## Color binding` section.

## foreignObject inversion exception

Some mermaid kinds can emit text via SVG `<foreignObject>` containing HTML elements (`<div>`, `<span>`) instead of native SVG `<text>`. **HTML content inside `<foreignObject>` does NOT invert under Obsidian's dark-mode-only `filter: invert(100%) hue-rotate(180deg) saturate(1.25)`** the way SVG children do — the source color is the rendered color (no flip). This is the opposite of the canonical inversion rule. When picking a `themeCSS` color that targets foreignObject-rendered text, use the **straight visual hex** (white = `#fff`, black = `#000`), not the inverted source.

**No currently-shipped kind hits this.** `journey` used to: mermaid's default `textPlacement:"fo"` renders both section headers and task labels as `<div>` content inside `<foreignObject>`, and since section bands DO invert (native SVG `rect`) while `fo`-placed label text does NOT, a single source colour for the label text could never read correctly in both themes at once. Rather than author two source colours for two rendering paths, the scheme sidesteps the whole exception: it forces `journey.textPlacement:'old'`, which switches label rendering to plain SVG `<text>` — a path that DOES invert normally, so the ordinary text-on-plate convention applies with no exception needed. See `diagram-journey.md`'s `## Color binding`.

Detection: run `grep -oE 'textPlacement[^,}]{0,30}' /path/to/mermaid.min.js` against the bundled mermaid (extract `obsidian.asar` first). If a kind's renderer defaults to `textPlacement:"fo"` (or otherwise emits `<foreignObject>`) and the scheme has no scalar override forcing it to a native-SVG placement, this exception applies to any `themeCSS` rule that targets HTML elements inside it.

When you discover a new kind that renders text via foreignObject with no override available, document its empirical-surface exception in the table above AND extend this section with the kind name.

## Obsidian sanitizer constraint (verified)

This is **mermaid's own** `sanitizeDirective` function, not something Obsidian layers on top — it runs inside mermaid itself whenever a `%%{init: ...}%%` directive is parsed, on every host that embeds stock mermaid (Obsidian included, since Obsidian calls `mermaid.initialize` with no custom `theme` and ships mermaid's bundled code unmodified). It walks an allowlist built by `keyify` over mermaid's *defaults*. Verified directly from the bundled bytes at `/Applications/Obsidian.app/Contents/Resources/obsidian.asar` → `lib/mermaid.min.js` (this is mermaid's shipped code as bundled by Obsidian, not an Obsidian-authored wrapper):

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

Consequences for any mermaid template, in Obsidian or anywhere else stock mermaid renders a directive:

- **Array-typed init keys are silently dropped, everywhere mermaid parses a directive.** `keyify` explicitly skips arrays (`Array.isArray(t[n])?r:…`) when building the allowlist, so `journey.sectionColours`, `journey.sectionFills`, `journey.actorColours` never take effect through this init path — not just inside Obsidian. This is mermaid's own sanitizer, so a host honouring "the full init schema" for arrays would have to bypass mermaid's directive parsing entirely (e.g. calling `mermaid.initialize` directly with a config object, which most embedding hosts — Obsidian included — do not do for user-authored fences). Do not rely on config arrays for custom colour on any host that renders a `%%{init: ...}%%` directive; `themeCSS` is the only reliable channel.
- **Non-default themeVariable keys are dropped.** Only keys present in mermaid's default theme block survive. `actor0..5`, `fillType0..7`, `mainBkg`, `nodeBorder`, `faceColor`, `lineColor`, `textColor` are all defaults — those work. Made-up keys do not.
- **`themeCSS` is the escape hatch.** Plus `fontFamily` / `altFontFamily`. These three are explicitly whitelisted as raw-string passthroughs (with a CSS sanitization pass via `tbe`). Use `themeCSS` to override mermaid's hardcoded class CSS rules (e.g. `.label text { fill: #333 }`) when no themeVariable controls the surface.
- **Use `!important` inside `themeCSS`.** CSS specificity alone won't beat inline `fill`/`style` attributes that some mermaid renderers write onto SVG elements. `!important` does — it elevates the rule above inline attribute precedence.
