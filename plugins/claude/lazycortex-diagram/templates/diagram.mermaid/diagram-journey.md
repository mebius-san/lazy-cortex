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

Mermaid's `journey` renderer (mermaid 11.13, as bundled in Obsidian 1.13.7) draws section bands and task bars as SVG `rect` elements classed `section-type-N` / `task-type-N`, where `N` is the section's 0-based first-appearance order in the source — a task's `task-type-N` always equals its parent section's index. We map the four available slots (`N=0..3`) to four canonical roles, matching this kind's 4-section density bound (see § Idioms).

- `entry` — section/task-type `0` (first section in source order).
- `guard` — section/task-type `1`.
- `action` — section/task-type `2`.
- `sub` — section/task-type `3` (fourth section, if the fence uses one).

## Color binding

Mechanism: a `journey:{textPlacement:'old'}` config scalar plus a `themeCSS` string. The init directive (journey config, themeCSS) comes verbatim from the scheme's `blocks.init.journey`; this template never carries literal style values.

Mermaid's journey renderer defaults to `textPlacement:"fo"`, which renders both section headers and task labels as HTML `<div>` content inside an SVG `<foreignObject>`. HTML content inside `<foreignObject>` does not participate in Obsidian's dark-mode-only `invert(100%) hue-rotate(180deg)` filter the way SVG children do, so a single source colour cannot read correctly in both themes at once — the plate and the label text would need opposite compensation depending on which path rendered them. The scheme sidesteps this instead of working around it per-surface: it forces `journey.textPlacement:'old'`, a scalar (so it survives mermaid's directive sanitizer inside Obsidian, unlike an array), which switches label rendering to plain SVG `<text class="journey-section section-type-N">` / `<text class="task">` elements. Those DO invert under the filter, so the usual dark-plate-plus-`textOnPlate`-text authoring convention applies uniformly, with one rendering path instead of two.

- `rect.section-type-0` / `rect.task-type-0` ← `entry.fill`
- `rect.section-type-1` / `rect.task-type-1` ← `guard.fill`
- `rect.section-type-2` / `rect.task-type-2` ← `action.fill`
- `rect.section-type-3` / `rect.task-type-3` ← `sub.fill`
- `text.journey-section,text.task` ← `textOnPlate` (header and task labels both now sit on a role-coloured plate, so one binding covers both)

The scheme no longer sets `fillType0..3` (`themeVariables`), nor the `sectionFills`/`sectionColours`/`actorColours` config arrays — those surfaces are gone from `blocks.init.journey`; do not reintroduce bindings to them. Those three keys were array-typed, and per `lazy-diagram.inversion-rule.md` § Obsidian sanitizer constraint, mermaid's own directive sanitizer drops every array-typed init key regardless of host — so they never worked reliably inside Obsidian even before this fix. Actor swatches, the score-face colour, and the task-bar/axis theming this kind's mermaid module also exposes are not bound by this scheme — the four section/task-type rules above are the only styling surface this template targets.

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
