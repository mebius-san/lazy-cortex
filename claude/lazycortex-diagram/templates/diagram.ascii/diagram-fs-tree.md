---
kind: fs-tree
purpose: Filesystem tree — directory and file structure rendered as ASCII.
---
# fs-tree diagram — canonical exemplar (ASCII)

Used for `kind: fs-tree`, `format: ascii`. The default and only format for filesystem trees — there's no mermaid equivalent worth having (`mindmap` is a misfit). Skip if fewer than 2 entries. Split when more than 40 entries (split by sub-tree under H3 anchors).

## Idioms

- Use box-drawing Unicode characters (`├──`, `└──`, `│`) — these are universally supported by terminals, GitHub, and Obsidian, and produce the cleanest tree. The "ASCII" name is historical; the drawer agent's `## Output` notes explicitly permit Unicode for tree characters.
- Trailing `/` on directory entries (`src/`, `docs/`); no trailing `/` on files.
- Annotations use ` ← <one-line note>` after the entry, only when the entry's purpose isn't obvious from its name.
- Indent step is 4 columns.
- Order: directories before files within a level; alphabetical within each group.
- Sibling lines under a parent use `├──` for non-last entries, `└──` for the last.

## Exemplar

```text
claude/lazycortex-diagram/
├── .claude-plugin/
│   ├── overview.md
│   └── plugin.json
├── agents/
│   ├── lazy-diagram.draw-ascii.md
│   └── lazy-diagram.draw-mermaid.md
├── rules/
│   └── lazy-diagram.authoring.md          ← nine-clause contract
├── skills/
│   ├── lazy-diagram.audit/
│   ├── lazy-diagram.draw/
│   ├── lazy-diagram.fix/
│   └── lazy-diagram.install/
├── templates/
│   ├── diagram.ascii/
│   └── diagram.mermaid/
├── tests/
│   └── diagram/                           ← shipped fixtures: request + expected
└── README.md
```
