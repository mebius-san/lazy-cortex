# Markdown style

Reference key: `lazycortex-core:lazy-core.markdown-style`.

Conventions for any markdown content an expert produces — when it edits a target file, writes a new authored doc, or composes a callout. Protocols whose payload or output is markdown link to this reference so their experts pick up the same style without each protocol restating the rules.

This reference is not auto-injected into every expert. Only experts whose declared protocol references it see it.

## Callouts

Obsidian callouts have a fixed shape:

```
> [!type] Single-line title
> Body line one.
> Body line two if needed.
```

- The first line is ONLY `> [!type] <title>`. Nothing else on it.
- The title is one line. Never wrap a title across two `>`-prefixed lines — the renderer treats the first `>` line as the title and a wrapped continuation renders inconsistently across viewers.
- Body prose goes on subsequent `>`-prefixed lines, one paragraph per `>`-line.
- Blank line above and below the whole callout block.

Wrong:

```
> [!info] Multi-select. Tick all targets that apply. If empty at
> finalize, the request is rejected.
```

Right:

```
> [!info] Multi-select
> Tick all targets that apply. If empty at finalize, the request is rejected.
```

## Hard-wraps in prose

Do not hard-wrap paragraph prose at any character width. One paragraph is one line. Obsidian (and every common markdown renderer) soft-wraps by viewport. Hard-wraps inside paragraphs do nothing useful and pollute diffs.

This applies to:
- Authored doc bodies (design.md, plan.md, tech.md, bug.md, request files, …).
- History entries.
- Callout bodies.
- Any other markdown prose the expert writes.

Lists, code blocks, frontmatter, and headings follow normal markdown rules (line breaks are syntactically meaningful there).

## Headings

- The doc's H1 is its title — at most one per file, at the top of the body (after frontmatter).
- Section headings use H2 (`##`); sub-sections H3; nesting deeper than H3 is allowed when the parent section's structure demands it.
- No trailing punctuation on headings.

## Links

Wikilinks (`[[target|display]]`) for vault-internal references — they survive moves. Regular markdown links (`[text](url)`) for external URLs.
