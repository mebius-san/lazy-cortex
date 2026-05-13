---
kind: journey
purpose: User journey — sequence of journey steps in named phases, each rated for satisfaction and tagged with the actors involved.
---
# User-journey diagram — canonical exemplar (mermaid)

Used for `kind: journey`, `format: mermaid`. Use when the host section is talking about *experience* (how it feels, where friction sits) — not the technical request flow (use `sequence`) and not the decision tree (use `flow`).

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.journey` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Group steps under `section <Phase name>` lines — every step belongs to a phase.
- Step syntax: `<step description>: <score>: <actorList>`. Score is 1–5 (1 = pain, 5 = delight). Actors are comma-separated, named after the participants in the host prose (camelCase or natural display names).
- No arrows, so the every-edge-labelled sanity check is trivially satisfied. Each step line carries an inline description (its own label).
- Density bound: keep to ≤4 sections and ≤12 steps. Past that, return `split-into-N` and slice by phase.

## Roles

Mermaid `journey` reads keys from three distinct surfaces — themeVariables, a `journey:` config block, AND `themeCSS` (raw CSS injection). Verified against mermaid source (`packages/mermaid/src/diagrams/user-journey/styles.js`, `journeyRenderer.ts` lines 226, 259-269, `schemas/config.schema.yaml`) AND Obsidian's bundled mermaid bytes (`/Applications/Obsidian.app/Contents/Resources/obsidian.asar` → `lib/mermaid.min.js`).

**Obsidian sanitizer constraint (verified, not guessed):** Obsidian wraps mermaid behind a sanitizer that walks an allowlist built by `keyify` over mermaid's *defaults*. The keyifier explicitly skips arrays (`Array.isArray(t[n])?r:…`), so every array-typed init key is silently dropped — including `journey.sectionColours`, `journey.sectionFills`, `journey.actorColours`. Non-default scalar keys (e.g. `actor6..7` if they don't exist in the schema's default block) are also dropped by the allowlist filter. **Only `themeCSS` (plus `fontFamily` / `altFontFamily`) survives sanitization for arbitrary-content keys** — these three are explicitly whitelisted as raw CSS / string passthroughs.

themeVariables (CSS-level — apply in standalone mermaid AND Obsidian):

- `fillType0..fillType7` — section background bands (cycle by section index). Mermaid defaults, allowlisted.
- `mainBkg` / `nodeBorder` — task-bar background and border. Mermaid defaults, allowlisted.
- `faceColor` — the score-emoji circle background (one colour for all scores; mouth is hardcoded `#666` in mermaid, not themable). Mermaid default, allowlisted.
- `lineColor` / `textColor` — axis/connectors and outside-card text fallback. Mermaid defaults, allowlisted.
- `actor0..actor5` — per-actor swatch in the legend strip. Mermaid defaults, allowlisted (sequence + journey share these keys).

`journey` config (NOT themeVariables — set inside `'journey':{...}`). Documented for cross-platform completeness; **all three array keys below are dropped by Obsidian's sanitizer** so they have no effect inside Obsidian, but they take effect in standalone mermaid renderers (CLI, mermaid-live, GitHub):

- `sectionColours` (array) — task-label text fill via inline `fill="<colour>"` attribute. Source: `journeyRenderer.ts:259-269` + `task.colour` assignment + `svgDraw.js` byTspan emit. Inline attribute beats every CSS rule. Mermaid default `['#fff']`.
- `sectionFills` (array) — section-band fills, parallel surface to `fillType0..7`.
- `actorColours` (array) — actor legend circle fills, parallel surface to `actor0..5`.

`themeCSS` (raw CSS injected into the rendered SVG — survives Obsidian's sanitizer):

- The **only** way to force in-card label color inside Obsidian. Two rendering paths to cover:
  - **Primary path: `<div class="label">` inside `<foreignObject>`** — mermaid 11.4.1's journey defaults `textPlacement:"fo"` (verified: `grep textPlacement` in bundled `mermaid.min.js` returns `textPlacement:"fo"`). The byFo strategy emits `<switch><foreignObject>...<div class="label">{text}</div></foreignObject><text class="task">{text}</text></switch>`. Modern browsers (including Obsidian's Electron Chrome) render the foreignObject content; the SVG `<text>` is the legacy fallback. So **selector `.label` is what actually paints**, not `text.task`.
  - **Fallback path: `<text class="task">`** — emitted by byTspan and used as the `<switch>` fallback. Targeted for cross-platform completeness (older renderers, headless export tools).
- Mermaid's CSS template `.label text { fill: #333 }` rule is **dead** in current journey output — task labels are not nested as `<text>` inside an element with class `label`. The rule survives in the template for legacy reasons.

Score *gradient* (1=pain → 5=delight) is **not themable** — mermaid uses one `faceColor` for every score circle and varies only the mouth curve. Pick a `faceColor` that reads on top of the section bands.

## Color binding

Mechanism: fuller-init `themeVariables` (allowlisted) PLUS a `journey:{}` config block (cross-platform mirror — silently dropped inside Obsidian) PLUS a `themeCSS` string (raw CSS that survives every sanitizer). The init directive (theme keys, themeCSS, journey config block including arrays) comes verbatim from the scheme's `blocks.init.journey`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid surfaces for documentation purposes — the scheme bakes the resolved values into the init string.

themeVariables bindings:

- `fillType0` ← `entry.fill`        (section 1 band)
- `fillType1` ← `guard.fill`        (section 2 band)
- `fillType2` ← `action.fill`       (section 3 band)
- `fillType3` ← `sub.fill`          (section 4 band if needed)
- `mainBkg` ← `entry.fill`          (task-bar fill)
- `nodeBorder` ← `entry.stroke`     (task-bar border)
- `faceColor` ← `guard.stroke`      (warm amber on dark sections; readable face circle)
- `actor0` ← `entry.stroke`   (blue source — first actor)
- `actor1` ← `guard.stroke`   (orange source — second actor; warm/cool contrast against actor0 so Owner vs System are visually distinct after inversion. action.stroke and service.stroke are too close in inverted hue to entry.stroke — verified visually in Obsidian dark.)
- `actor2` ← `error.stroke`   (red source — third actor; another warm hue, distinct from blue + orange)
- `lineColor` ← `lineOnCanvas`      (axis & connectors run across canvas; source inverts to white in render)
- `textColor` ← `textOnCanvas`      (outside-card text — section/legend labels)

journey config bindings (cross-platform — Obsidian drops these but they work in mermaid CLI / mermaid-live / GitHub):

- `sectionColours` ← single-element array carrying source `textOnCanvas` — task-label text fill renders white after inversion. Mermaid default would render BLACK on the dark plate.
- `sectionFills` ← `[entry.fill, guard.fill, action.fill, sub.fill]` (mirror of fillType0..3 — same role, different consumer)
- `actorColours` ← `[entry.stroke, guard.stroke, error.stroke]` (mirror of actor0..2 — blue/orange/red triplet)

themeCSS binding (the **only** in-card text override that survives Obsidian's sanitizer) — two-rule string covering both rendering paths, **with opposite source colors** because the two paths invert differently:

- `.label{color:...}` — paints the `<div class="label">` inside `<foreignObject>`. This is the path Obsidian actually renders (mermaid journey defaults `textPlacement:"fo"`, byFo strategy). `color` (not `fill`) is the right property because it's an HTML element, not SVG. **Source uses on-plate value straight** — HTML content inside `<foreignObject>` is empirically NOT subject to the SVG's `filter: invert(100%) hue-rotate(180deg)`, so the source color is the rendered color (no inversion compensation needed). Verified by user visual test in Obsidian dark.
- `text.task{fill:...}` — paints the SVG `<text class="task">` fallback inside the `<switch>`. Used by older renderers without foreignObject support and by headless export tools. Verified from bundled bytes: `journeyRenderer` calls `drawTask` with `f={class:"task"}`; byTspan does `b.attr("fill", colour).style(...)` then `_setTextAttrs(b, f)` which applies `class="task"`. Source uses on-canvas value because SVG children DO invert.
- The `!important` on both rules is required because mermaid writes inline attributes/styles that would otherwise win specificity. **Selector `.label text` does NOT match** — task labels are not nested as `<text>` inside any element with class `label` (legacy CSS template rule that's dead in current journey output).

## Layout

Layout config is baked into the scheme's `blocks.init.journey`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
journey
  section Discover
    Open card detail: 5: Owner
    Tap share button: 4: Owner
  section Configure
    Set link visibility: 3: Owner
    Add viewer emails: 2: Owner, System
  section Confirm
    Review summary: 4: Owner
    Submit and copy link: 5: Owner, System
```
