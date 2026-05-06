---
kind: timeline
purpose: Time-axis narrative — events anchored to dates or periods, grouped by epoch, with optional sub-events per anchor.
---
# Timeline — canonical exemplar (mermaid)

Used for `kind: timeline`, `format: mermaid`. Use for *historical* narrative (release history, milestone retrospective) where there is no concept of dependencies between events. Use `gantt` instead when durations and dependencies matter.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.timeline` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Each anchor line: `<period> : <event>` — period is whatever resolution the narrative needs (`2024 Q1`, `Jan 2025`, `Day 0`). Sub-events of the same anchor follow on indented `: <event>` lines (continuation form).
- Keep period labels homogeneous across the diagram (don't mix quarters and exact dates in the same fence).
- No arrows, so the every-edge-labelled sanity check is trivially satisfied. Each event line carries an inline description.
- Density bound: keep to ≤8 anchors and ≤16 events. Past that, return `split-into-N` and slice by year or epoch.

## Roles

Mermaid `timeline` honours `cScale0..cScale11` for alternating-anchor stripes. The canonical scheme roles map onto the first 8 indices so anchors land on the project palette instead of mermaid's neon defaults.

## Color binding

Mechanism: fuller-init `themeVariables`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.timeline`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

- `cScale0` ← `entry.fill`
- `cScale1` ← `action.fill`
- `cScale2` ← `guard.fill`
- `cScale3` ← `sub.fill`
- `cScale4` ← `service.fill`
- `cScale5` ← `store.fill`
- `cScale6` ← `success.fill`
- `cScale7` ← `error.fill`
- `cScaleLabel0..7` ← `textOnPlate`
- `lineColor`    ← `lineOnCanvas`
- `textColor`    ← `textOnCanvas`     (title and any non-cScale text sits on canvas — source renders white after inversion. Section event text is controlled per-section by `cScaleLabel{i}` above.)

## Layout

Layout config is baked into the scheme's `blocks.init.timeline`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
timeline
  2024 Q1 : v1 alpha — internal preview
         : private beta with five teams
  2024 Q4 : v1.0 launch — public availability
  2025 Q2 : v1.5 — share links and audit log
  2025 Q4 : v1.8 — mobile companion app
  2026 Q2 : v2 plan freeze
```
