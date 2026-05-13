---
kind: decision-tree
purpose: Pure decision branches in ASCII — every non-leaf is a question (diamond), every leaf is an outcome. No mixed nodes.
---
# Decision-tree diagram — canonical exemplar (ASCII)

Used for `kind: decision-tree`, `format: ascii`. Use when the renderer can't show mermaid `flowchart TD`. Distinct from `flow` (mixed action/decision); `decision-tree` is strict pure branching.

## Idioms

- Every non-leaf node is a diamond-shaped box (`<Question?>` left/right edges, `+---+` top/bottom). Leaves are plain rectangles (`+--+` borders).
- Every connector carries an inline answer label (`yes` / `no` / short phrase) — per drawer agent sanity check 3.
- Layout is top-down by default; left-to-right only for very wide trees.
- ASCII only — `+`, `-`, `|`, `>`, `<`, `v`. No box-drawing Unicode.
- Density bound: ≤12 nodes per fence; skip if <2 branches (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by top-level decision.

## Exemplar

```text

  +---------------------+
  | Owner configures    |
  | card share          |
  +----------+----------+
             |
   -- set visibility? -->
             |
             v
  +--------------------+
  | <Make card public?> |
  +--------+-----------+
           |           |
        No |           | Yes
           v           v
  +------------------+ +------------------------------+
  | <Viewer list     | | Public link (no auth needed) |
  |  provided?>      | +------------------------------+
  +-----+------+-----+
        |      |
     No |      | Yes
        |      v
        |  +------------------+
        |  | <Set expiry?>    |
        |  +-------+----------+
        |          |       |
        |       No |       | Yes
        |          v       v
        |  +--------------------+  +-------------------------------+
        |  | Private link       |  | Private link                  |
        |  | with viewers       |  | with viewers + expiry         |
        |  +--------------------+  +-------------------------------+
        |
        v
  +---------------------------+
  | Private link, no viewers  |
  +---------------------------+
```
