---
kind: controls-scheme
purpose: Design-system control inventory in ASCII — control families with the controls in each, for terminals and plain-text renderers.
status: WIP — v1.5 foundation per `lazy-obsidian.diagram-design.md` §5. Refine after 3+ real authoring rounds.
---
# Controls-scheme diagram — canonical exemplar (ASCII) — WIP

Used for `kind: controls-scheme`, `format: ascii`. The slot is reserved in v1; idioms are tentative. Caller-passed `kind: controls-scheme` produces the placeholder below.

## Idioms (WIP)

- Outer wrapper box (`+--+` borders) contains all control families — represents the screen/canvas surface.
- Each control family is a sub-box with the family name as the title row; controls appear inside as visual samples (not bullet lists). Layout in a 2×2 grid where space allows.
- Control samples render the actual chrome: `[ Primary button ]`, `[ Text input ______ ]`, `[Tab 1][Tab 2][Tab 3]`, `[! Toast message x]`, `( Spinner ... )`. The shape conveys the kind.
- Family label and control labels are sentence case. No edges (inventory only).
- Density bound: ≤16 controls per fence; skip if <3 control families (per drawer agent's § Density check).
- ASCII only — `+`, `-`, `|`, `[`, `]`, `(`, `)`, `<`, `>`. No box-drawing Unicode.
- Lock criterion: 3+ real-world controls-scheme diagrams authored across vaults.

## Exemplar — refine in v1.5

```text
+------------------------------------------------------------------+
|                                                                  |
|  +------------------------+  +--------------------------------+  |
|  | Buttons                |  | Inputs                         |  |
|  |                        |  |                                |  |
|  |  [ Primary button   ]  |  |  [ Text input       ______  ]  |  |
|  |  [ Secondary button ]  |  |  [ Multi-line text    [___] ]  |  |
|  |  [ Icon button  [+] ]  |  |  [ Dropdown              v  ]  |  |
|  |                        |  |                                |  |
|  +------------------------+  +--------------------------------+  |
|                                                                  |
|  +------------------------+  +--------------------------------+  |
|  | Navigation             |  | Status                         |  |
|  |                        |  |                                |  |
|  |  [Tab 1][Tab 2][Tab 3] |  |  [! Toast message          x]  |  |
|  |  Home > Section > Page |  |  [ Badge ]                     |  |
|  |  < Back link           |  |  ( Spinner ... )               |  |
|  |                        |  |                                |  |
|  +------------------------+  +--------------------------------+  |
|                                                                  |
+------------------------------------------------------------------+
```
