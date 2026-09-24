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

1. **File path** — absolute or vault-relative path to a single stage-bearing authored spec doc (`design.md`, `code-plan.md`, `test-plan.md`, `bug.md`, or product/asset-level `tech.md`). One file only — callers loop over files themselves. The folder-note (status file) and the report journals (`code-report.md` / `test-report.md`) carry no `spec_source_docs` and are rejected.

## Process

### 1. Read the doc

- Read the doc's frontmatter and body.
- Capture the `spec_source_requests` list (order-preserving; `[]` when absent) and the `spec_source_docs` list (order-preserving; `[]` when absent). Frontmatter is the source of truth.
- Locate the body `# Sources` H1 container and its `## Requests` / `## Docs` sub-sections. If the `# Sources` container is absent, create it per the reference (H1 + `#protected/spec/sources` tag on the first content line + both sub-sections with their marker pairs) at the end of the body.

### 2. Re-project `## Requests`

- Rewrite only the bytes between the `<!-- auto:spec-requests:start --> / :end -->` markers, projecting one bullet per `spec_source_requests` wikilink per the reference's `## Requests` bullet format (request wikilink + the date it first appeared).
- Preserve the first-appearance date and any operator gloss on existing bullets by matching on the wikilink target (the bytes left of the `|`). A wikilink already present in the body keeps its existing date / display; a wikilink new to the frontmatter gets today's UTC date (`date -u +%Y-%m-%d`) and the default display.
- Drop bullets whose wikilink no longer appears in the frontmatter list. Dedupe on the wikilink target.

### 3. Re-project `## Docs`

- Rewrite only the bytes between the `<!-- auto:spec-docs:start --> / :end -->` markers, projecting one bullet per `spec_source_docs` wikilink per the reference's `## Docs` bullet format (wikilink only, no date).
- Preserve any operator-edited display (gloss) on existing bullets by matching on the wikilink path (the bytes left of the `|`). A wikilink new to the frontmatter gets the default display (the last path segment).
- Drop bullets whose wikilink no longer appears in the frontmatter list. Dedupe on the wikilink path.

### 4. Leave everything else untouched

- Never touch frontmatter — this primitive is body-only projection from frontmatter, never the reverse.
- Never touch the `# Sources` H1 heading text, the `#protected/spec/sources` tag, sub-section headings, the marker comments themselves, or any unmarked sub-section under `# Sources` (operator-authored kinds). Rewrite only the bytes inside each kind's marker pair.
- Never touch any content outside the `# Sources` container.

## Output

- The doc's path.
- Per sub-section: the projected bullet count (or `unchanged` when the projection matched the existing bytes byte-for-byte).
- Nothing else — no other note is read or written by this skill.

## Failure modes

- **`/lazy-spec.refresh-sources` refuses naming a non-authored doc** — the target's `spec_role` is `status` (folder-note), `code-report` / `test-report`, or otherwise not an authored doc that carries `spec_source_docs` → run on a stage-bearing authored doc (`design` / `code-plan` / `test-plan` / `bug` / `tech`) instead.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.refresh-sources/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.refresh-sources)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the file path passed). Body: `# lazy-spec.refresh-sources` heading, then `## Actions` and `## Result`.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop themselves.
- **Frontmatter is the source of truth** — body is a projection of it; never write frontmatter from the body.
- **Glosses survive re-projection** — operator-edited displays on `## Docs` / `## Requests` bullets are preserved by matching the wikilink target; only the display right of the `|` is operator-owned.
- **Marker-scoped rewrites only** — touch only the bytes between each kind's `<!-- auto:spec-<kind>:start --> / :end -->` pair. Nothing outside the `# Sources` container is this skill's to write.
- **Never reach into another owner's section** — the `# Summary` section belongs to the note's coordinator and its stats region to the stats CLI; `#protected/spec/{gates,history}` belong to their own writers.
- **Idempotent** — re-running on a doc already in sync is a no-op: the projection matches the existing bytes and nothing is written.
