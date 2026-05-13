---
kind: tree
purpose: Hierarchical taxonomy in ASCII — root with descending category levels for terminals and plain-text renderers.
---
# Tree diagram — canonical exemplar (ASCII)

Used for `kind: tree`, `format: ascii`. Use when the renderer can't show mermaid `flowchart TD`. Distinct from `fs-tree`: `tree` is taxonomy (no trailing `/`, no file/dir distinction), `fs-tree` is a literal filesystem layout.

## Idioms

- Box-drawing Unicode characters (`├──`, `└──`, `│`) — the same set used by `fs-tree`. ASCII-only fallback (`+--`, `|`) is acceptable in renderers that strip Unicode, but Unicode is preferred.
- Indent step is 4 columns. Sibling lines under a parent use `├──` for non-last entries, `└──` for the last.
- No trailing `/` (taxonomy nodes are not directories). No annotations after the entry — taxonomy labels carry their own meaning.
- Order: alphabetical within a level. Don't sort by frequency or importance — that's not what taxonomies are.
- Density bound: ≤15 nodes per fence; skip if <3 levels OR <4 leaves (per drawer agent's § Density check). Past the bound, return `split-into-N` and slice by top-level branch.

## Exemplar

```text
Card
├── Content card
│   ├── Article
│   ├── Media
│   └── Note
├── Reference card
│   ├── Citation
│   └── Link
└── Task card
    ├── Milestone
    └── To-do
```
