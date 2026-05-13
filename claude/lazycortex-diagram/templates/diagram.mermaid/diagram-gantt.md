---
kind: gantt
purpose: Time-bound schedule of tasks across phases — milestones, dependencies, durations.
---
# Gantt chart — canonical exemplar (mermaid)

Used for `kind: gantt`, `format: mermaid`. Use for genuinely time-anchored work (release plan, migration cutover) — not for abstract "ordered tasks" (use `flow` or a markdown checklist instead).

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.gantt` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- `dateFormat` and `axisFormat` declared once at the top. Default to ISO `YYYY-MM-DD` for input; choose an `axisFormat` that keeps labels readable for the schedule's length.
- Group tasks under `section <name>` headings — every task lives inside a section. Sections are the only grouping mechanism gantt offers; use them.
- Each task line: `  <descriptive label> :<id>, <start>, <duration>` — the id is camelCase, the start is either an absolute date or `after <otherId>`, the duration is `<n>d`/`<n>w`. Dependencies live in `after`, not in arrows.
- No edges, so the every-edge-labelled sanity check is trivially satisfied. Each task line implicitly carries a label (the description before the colon).
- Density bound: keep to ≤4 sections and ≤20 tasks. Past that, return `split-into-N` and slice by milestone.

## Roles

Mermaid `gantt` ignores `classDef` and per-task `style`, but accepts a rich set of palette theme keys that drive section shading, task bars, and milestone markers. The canonical scheme roles map cleanly onto those keys.

## Color binding

Mechanism: fuller-init `themeVariables`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.gantt`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

- `sectionBkgColor` ← `entry.fill`
- `altSectionBkgColor` ← `sub.fill`
- `taskBkgColor` ← `action.fill`
- `taskBorderColor` ← `action.stroke`
- `taskTextColor` ← `textOnPlate`
- `taskTextOutsideColor` ← `textOnCanvas`
- `doneTaskBkgColor` ← `success.fill`
- `doneTaskBorderColor` ← `success.stroke`
- `critBkgColor` ← `error.fill`
- `critBorderColor` ← `error.stroke`
- `activeTaskBkgColor` ← `guard.fill`
- `activeTaskBorderColor` ← `guard.stroke`
- `gridColor` ← `sub.stroke`
- `todayLineColor` ← `guard.stroke`
- `textColor` ← `textOnCanvas` (axis labels sit on canvas — source renders white after inversion)

## Layout

Layout config is baked into the scheme's `blocks.init.gantt`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
gantt
  dateFormat YYYY-MM-DD
  axisFormat %b %d

  section Design
  spec drafting :specDrafting, 2026-05-01, 14d
  design review :designReview, after specDrafting, 5d

  section Build
  api implementation :apiImpl, after designReview, 21d
  ui implementation :uiImpl, after designReview, 28d

  section Ship
  staging soak :stagingSoak, after apiImpl, 7d
  launch :launch, after stagingSoak, 1d

  section Post-launch
  metrics review :metricsReview, after launch, 7d
```
