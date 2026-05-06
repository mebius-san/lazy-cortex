---
kind: mindmap
purpose: Hierarchical brainstorm — central topic with branches and sub-branches naming concerns, options, or open questions.
---
# Mindmap — canonical exemplar (mermaid)

Used for `kind: mindmap`, `format: mermaid`. Mindmaps are tree-shaped, not graph-shaped: every node has exactly one parent. Use a `flow` or `c4-*` instead when relationships are non-tree.

## Idioms

- First line inside the fence: literal `<<init>>` sentinel — the drawer agent substitutes it with `blocks.init.mindmap` from `styles-<scheme>.json` verbatim. Templates carry no init literals.
- Indent levels define hierarchy — two spaces per level, consistent throughout.
- The root is `root((id))` (rounded form) or `root[Label]`. Subsequent nodes use plain identifiers (camelCase) or labels in shape syntax (`[box]`, `(round)`, `((double))`, `{{hex}}`).
- No edges to label — the parent-child relationship is the only edge syntax. The every-edge-labelled sanity check is satisfied by construction (no arrows).
- Density bound: keep to 3 levels and ≤25 leaf nodes. Past that, return `split-into-N` and slice by top-level branch.

## Roles

Mermaid `mindmap` honours `cScale0..cScale11` (and matching `cScaleLabel*` for text colour). The branches rotate through the cScale palette, so we map the canonical role hexes onto the first 8 indices to land branches on the project palette instead of mermaid's neon defaults.

## Color binding

Mechanism: fuller-init `themeVariables`. The init directive (theme keys, layout block) comes verbatim from the scheme's `blocks.init.mindmap`; this template never carries literal style values. The role bindings below describe which scheme keys map to which mermaid theme keys for documentation purposes — the scheme bakes the resolved values into the init string.

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
- `textColor`    ← `textOnPlate`

## Layout

Layout config is baked into the scheme's `blocks.init.mindmap`; the drawer emits the init line verbatim and never composes a layout block from this template.

## Exemplar

```mermaid
<<init>>
mindmap
  root((cardPlatform))
    surfaces
      webApp
      mobileApp
      pluginApi
    integrations
      authProvider
      emailGateway
      analyticsPipeline
    quality
      latencyBudget
      auditCoverage
      accessibility
```
