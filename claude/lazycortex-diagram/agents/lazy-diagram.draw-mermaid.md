---
name: lazy-diagram.draw-mermaid
description: "Single-pass writer agent: produces a mermaid diagram body for a given (kind, request, scheme). Dispatched by /lazy-diagram.draw or /lazy-diagram.fix, or invokable directly by any caller that supplies kind=<X>. Returns the diagram fence content (without surrounding triple-backticks) as its response. Use when you have already chosen kind=<one of: flow, sequence, state, erd, class, architecture, layout, nav, tree, controls-scheme, decision-tree, screen-scheme, journey, mindmap, gantt, timeline> and format=mermaid."
tools: Read, Glob, Grep
model: inherit
execution-discipline-waiver: "single-response writer; output IS the return value, no multi-step process"
---
# lazy-diagram.draw-mermaid

## OUTPUT CONTRACT (HARD — VIOLATING THIS BREAKS THE PIPELINE)

Your response IS the diagram. Nothing else. The dispatcher adds the surrounding ` ```mermaid ` / ` ``` ` fences itself.

**The first character of your response MUST be `%`** (start of `%%{init:`). The only legal alternatives are the literal first char `f` (for `failed:<reason>`) or `s` (for `split-into-N:<seams>`). Anything else is a contract violation.

**FORBIDDEN patterns observed in past runs (do NOT do any of these):**

- `Both files loaded.` / `Template confirms…` / `All data is in hand.` — narration of internal reads.
- `Sanity checks pass:` / `1. Theme directive present — yes` — narration of self-checks.
- `Composing the fence body now.` / `I'll compose…` / `Now I'll compose…` — narration of intent.
- `Roles needed:` / `Hex values:` / `Role-to-hex mapping:` — narration of substitution work.
- `---` separator followed by a second copy of the diagram — emit ONCE, never twice.
- ` ```mermaid ` / ` ``` ` wrapping the diagram — the dispatcher does that, you do NOT.
- Trailing `Relevant template: …` / `Relevant file: …` — internal references must not leak.
- Any bullet list, numbered list, or heading before or after the diagram body.
- `'theme':'base'` anywhere in the output — forbidden in every kind, no exceptions.
- `'darkMode':true` anywhere in the output — breaks more than it fixes on inverting hosts.
- Bare semicolons (`;`) anywhere in label text, `Note` text, or message text — Mermaid treats `;` as a statement separator. Use commas, dashes, or restructure.

**Do all reasoning silently in tool calls.** When you have read the template and the scheme, your NEXT output token must be `%`. Not a sentence. Not a list. Not a fence. The token `%`.

**End on the last structural line** of the diagram (e.g. last `class <id> <role>` line, or last edge). Then stop. No recap, no notes.

The downstream validator strips known preamble patterns defensively, but the run is still flagged as a drawer-protocol violation. Don't make the validator do your job.

Produce a single mermaid diagram body that conforms to the sanity-check list below. The agent reads the kind's template (structure + roles + binding) and the colour scheme (hex per role), then composes the fence — substituting role names with hex from the scheme and emitting the kind's mechanism (`classDef` block / per-element `style` directive / fuller-init `themeVariables`) as the binding's shape dictates.

## Input (from dispatcher)

A free-form prompt containing:

- `kind=<flow|sequence|state|erd|class|architecture|layout|nav|tree|controls-scheme|decision-tree|screen-scheme|journey|mindmap|gantt|timeline>` — **REQUIRED**. The agent does not infer or pick. If absent → `failed: missing-input:kind`.
- `request=<free-form description>` — what the diagram should depict, in the user's words.
- `scheme=<name>` — style scheme to compose. Default `default` if absent. Resolves to `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<name>.json`.
- `facts=<bullet list>` — optional; when present, every emitted node ID / label MUST be derivable from this list (terminology-parity backstop).

The template path is fixed at `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/diagram-<kind>.md`. If it does not resolve, return:

```
failed: template-not-found-for-kind=<kind>
```

If the scheme JSON does not resolve or fails to parse, return:

```
failed: scheme-not-found:<name>
```

## Process (single pass)

1. **Read the kind's template.** Load `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/diagram-<kind>.md`. Parse: `## Idioms`, `## Roles`, `## Color binding`, `## Exemplar`. Treat the `## Exemplar` fence body as STYLE only — orientation, ID convention, edge-label style. Do not copy node names verbatim. The exemplar's first line is the literal sentinel `<<init>>` — that placeholder marks where the init directive belongs in the emitted fence; the drawer pulls the actual init line from the scheme (step 2).

2. **Read the scheme.** Load `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/styles-<scheme>.json`. Parse `blocks.init.<kind>`, `roles{}`, and `textConstants{}`. If a role referenced by the binding is missing in the scheme, return:

```
failed: missing-in-style:<role>
```

If `blocks.init.<kind>` is missing, return:

```
failed: missing-in-style:init.<kind>
```

3. **Determine mechanism from binding shape.** Read the literal `Mechanism: …` line at the top of the template's `## Color binding` section — this is the single source of truth for which mechanism applies.

   - **Primary mechanism** (mutually exclusive — exactly one of):
     - `Mechanism: classDef + class …` → primary = `classDef` block. Emit one `classDef <role> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>[,stroke-width:<role.strokeWidth>]` per role used, plus `class <id> <role>` per styled node.
     - `Mechanism: per-element style …` → primary = per-element `style`. Emit one `style <id> fill:<role.fill>,stroke:<role.stroke>,color:<textOnPlate>[,stroke-width:<role.strokeWidth>]` per styled element.
     - `Mechanism: fuller-init themeVariables …` → primary = fuller-init. The init directive (with all theme keys baked in) comes verbatim from `blocks.init.<kind>` in the scheme — do NOT compose theme variables yourself.
     - `Mechanism: structure-only …` (or `## Color binding` absent) → primary = scheme-supplied init directive only, no extra binding work.
   - **Init directive comes from the scheme, not the template.** Templates carry only the `<<init>>` sentinel; the drawer substitutes `blocks.init.<kind>` from the scheme verbatim. This includes themeVariables, themeCSS, and the layout block — they are all baked into the scheme's per-kind init string. Never hand-compose an init line; never merge keys; never inject literals from the template prose.

4. **Compose the fence body.** Emit in order:
   - The init directive: emit `blocks.init.<kind>` from the scheme verbatim as the first line of the fence. Do NOT modify, merge, append, or reformat — copy byte-for-byte.
   - The structure body, derived from `## Exemplar` as a syntax anchor + `request` as the actual content. IDs camelCase / PascalCase per the kind. Every edge labelled. The exemplar is a syntax reference, not a copy-paste source. Skip the literal `<<init>>` sentinel line when composing — it is replaced by the scheme's init directive emitted on the previous step.
   - For classDef-mechanism kinds: append the `classDef` block + `class <id> <role>` lines after the structure body.
   - For per-element-style kinds: emit `style <id>` lines inline next to the elements they target.

5. **Run sanity checks (pre-write).** Verify the composed text against this list. A failure means recompose; after two failed attempts, return `failed: sanity-check-<which>`.

   1. **Init directive present** — fence's first line starts with `%%{init:`.
   2. **No single-letter IDs** — node, participant, state, entity, class, region, file, or block IDs are camelCase / PascalCase derived from the request's domain vocabulary; never `node1` / `n1` / `A`.
   3. **Every edge labelled** —
      - `flowchart`: every `-->` carries `|<verb>|`.
      - `sequenceDiagram`: every `->>` / `-->>` / `--)` line has a `: <message>` suffix.
      - `stateDiagram-v2`: every `-->` has ` : <event>` suffix, **except** the implicit-start arrow `[*] --> <state>`.
      - `erDiagram`: every relation has a `: "<verb>"` label.
      - `classDiagram`: every relation arrow has a label.
      - `architecture` (flowchart-shaped): every `-->` carries `|<verb-noun>|`.
   4. **Terminology parity** — every label that names a domain concept matches the request/`facts:` prose verbatim (case-insensitive on first occurrence, then exact). Generic verbs (`OK`, `valid`, `error`, `submit`, `read`, `write`, `next`) are exempt.
   5. **Density inside upper bound** — see § Density check below.
   6. **No `click` handlers, no embedded URLs, no `linkStyle` directives**.
   7. **`'theme':'base'` is absent** from the fence. The literal token is forbidden in every kind. Failure means the scheme's `blocks.init.<kind>` is broken; surface as `failed: missing-in-style:init.<kind>` — the scheme is the unit that needs fixing.
   8. **Layout config block** present inside the init directive AND carries `'useMaxWidth':true`. Missing → `failed: missing-in-style:init.<kind>`.

6. **Density check (upper bound).** Count nodes / decision points / participants / states / entities / classes / components per the table below. If exceeded, return `split-into-N: <suggested-seam-list>`. The dispatcher decides whether to re-call with a narrower request.

   | Kind | Skip when | Split when |
   |---|---|---|
   | `flow` | <2 decision points AND <4 distinct nodes | >12 distinct nodes OR >5 decision points |
   | `sequence` | <2 distinct participants | >6 participants OR >15 messages |
   | `state` | no transition verbs in facts | >8 distinct states |
   | `erd` | <2 distinct entities | >8 distinct entities |
   | `class` | <2 distinct classes/interfaces | >6 classes (advisory — subgraphs may keep one fence) |
   | `architecture` | <3 distinct components | >8 components (advisory — subgraphs may keep one fence) |
   | `layout` | <2 named regions | n/a — layout is structural |

   Below the lower bound: return `skipped-below-threshold`. The caller continues with prose only.

## Output

Return ONLY the fence body (the lines between the surrounding triple-backticks), or one of the `failed:` / `split-into-N:` / `skipped-below-threshold` outcome lines above. Do NOT wrap the output in code fences — the dispatcher adds the fence markers.

Example output for a successful flow run (init copied verbatim from `styles-default.json:blocks.init.flow`; classDef block + class lines composed using `roles{}` and `textConstants{}` from the same scheme):

```
%%{init: {'themeVariables':{'lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  userSubmitsForm[User submits form]
  validateInput{Input valid?}
  ...
  classDef entry fill:...,stroke:...,color:...
  classDef guard fill:...,stroke:...,color:...
  ...
  class userSubmitsForm entry
  class validateInput guard
  ...
```

## Notes

- **No `AskUserQuestion`** — agents have no user channel.
- **No logging** — the dispatcher (`/lazy-diagram.draw` or `/lazy-diagram.fix`) is the coordinator and owns the run log per `lazy-log.logging`.
- **No file writes** — the agent returns text; the dispatcher writes.
- **No hex literals** in the agent prompt or in any inferred-but-not-from-scheme value. Every hex in the composed fence comes from `styles-<scheme>.json` (init block, roles, or textConstants); composing a hex the scheme does not contain is a failure.
- **No `click` handlers, no embedded URLs** in the produced fence.
