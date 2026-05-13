---
kind: flow
purpose: Decision-bearing flowchart rendered as ASCII art — for terminals, plain-text logs, and renderers that don't support mermaid.
---
# Flow diagram — canonical exemplar (ASCII)

Used for `kind: flow`, `format: ascii`. ASCII flow is for environments where mermaid won't render: PR comments on platforms without diagram support, terminal output, plain-text logs. Density bounds match mermaid (`flow` skip <2 decisions OR <4 nodes; split >12 nodes OR >5 decisions).

## Idioms

- Box every node: `+--------+` borders, label inside (`| User submits form |`).
- camelCase node IDs are used as anchor lines (e.g. `# userSubmitsForm:` above the box) only when boxes are referenced by other lines; otherwise the box label suffices.
- Connectors are arrows on their own line: `-- click submit -->`. Every connector has an inline verb.
- Decision points are diamond-style boxes (`<...>` left/right edges, `+---+` top/bottom): `<Input valid?>`. Two outgoing edges, each labelled.
- No box-drawing Unicode (`─│┌`); ASCII only — boxes use `+`, `-`, `|`. Some renderers strip Unicode; ASCII guarantees fidelity.
- Layout is left-to-right by default, top-to-bottom only for genuinely vertical flows.

## Exemplar

```text

  +-------------------+     -- click submit -->     +------------------+
  | User submits form | --------------------------> | <Input valid?>   |
  +-------------------+                             +--------+---------+
                                                    |        |
                                               yes  |        | no
                                                    v        v
                                      +------------------+  +---------------------+
                                      | Persist record   |  | Render field errors |
                                      +--------+---------+  +---------------------+
                                       |       |
                                    ok |       | server error
                       ________________|       |___________________________
                       |                                                   |
                       v                                                   v
              +---------------------+                         +---------------------+
              | Show success toast  |                         | Render field errors |
              +---------------------+                         +---------------------+
```
