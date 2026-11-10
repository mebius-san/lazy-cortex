---
name: lazy-spec.refresh-sources
description: "Use after hand-editing a spec doc's `spec_source_docs` / `spec_source_requests` frontmatter, or whenever its body `# Sources` bullets no longer match that frontmatter. Re-projects the `## Docs` / `## Requests` lists, keeping operator glosses on existing wikilinks. Touches nothing outside the doc's `# Sources` container. One file per call — callers loop."
execution-discipline-waiver: "Single-purpose projection primitive — wraps the source-attribution reference; no multi-phase orchestration where step-skip can hide."
---
# Refresh Sources

Primitive skill that re-projects a doc's body `# Sources` sub-sections from its frontmatter source-of-truth keys. The operator edits `spec_source_docs:` / `spec_source_requests:` in frontmatter; this skill brings the human-readable `## Docs` / `## Requests` bullet lists back in sync without disturbing anything else. It writes inside that one container and nowhere else — the `# Summary` section of a note belongs to the coordinator that owns the note, and its stats region to the stats CLI.

The body shape (the `# Sources` H1 container, the `#protected/spec/sources` owner tag, the `## Requests` / `## Docs` sub-sections, their `<!-- auto:spec-<kind>:start --> / :end -->` marker pairs, the bullet format per kind, and the gloss-preservation rule) is owned by `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`. This skill never restates that format — follow the reference exactly.

## Input

Signature: `lazy-spec.refresh-sources <file-path>`.

1. **File path** — absolute or vault-relative path to a single stage-bearing authored spec doc (`design.md`, `code-plan.md`, `test-plan.md`, `bug.md`, or the product-level `tech.md`). One file only — callers loop over files themselves. The folder-note (status file) and the report journals (`code-report.md` / `test-report.md`) carry no `spec_source_docs` and are rejected.

## Process

Run the projection verb on the one file:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" refresh-sources <file-path>
```

The verb reads `spec_source_requests` and `spec_source_docs`, rewrites only the bytes between each kind's marker pair (creating the `# Sources` container with both sub-sections when it is absent), keeps every operator gloss and first-appearance date, and prints one JSON line: `{"doc", "docs", "requests", "touched_paths"}`. Exit 1 prints `{"status": "refused", "reason", "doc"}` — report the reason as it stands and stop.

## Output

- The doc's path (`doc`).
- Per sub-section: the projected bullet count, or `unchanged` when the projection matched the existing bytes (`requests`, `docs`).
- `touched_paths` — the doc when a byte changed, empty otherwise; nothing else is read or written by this skill.

## Failure modes

- **`/lazy-spec.refresh-sources` reports `reason: folder-note`** — the target is a status or level note → run it on one of that folder's authored docs instead.
- **`/lazy-spec.refresh-sources` reports `reason: no-source-docs`** — the target's type is undeclared or carries no `stages` → run it on a stage-bearing authored doc (`design` / `code-plan` / `test-plan` / `bug` / `tech`) instead.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop themselves.
- **Frontmatter is the source of truth** — body is a projection of it; never write frontmatter from the body.
- **Glosses survive re-projection** — operator-edited displays on `## Docs` / `## Requests` bullets are preserved by matching the wikilink target; only the display right of the `|` is operator-owned.
- **Marker-scoped rewrites only** — touch only the bytes between each kind's `<!-- auto:spec-<kind>:start --> / :end -->` pair. Nothing outside the `# Sources` container is this skill's to write.
- **Never reach into another owner's section** — the `# Summary` section belongs to the note's coordinator and its stats region to the stats CLI; `#protected/spec/{gates,history}` belong to their own writers.
- **Idempotent** — re-running on a doc already in sync is a no-op: the projection matches the existing bytes and nothing is written.
