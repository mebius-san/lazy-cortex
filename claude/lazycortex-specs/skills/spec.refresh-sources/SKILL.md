---
name: spec.refresh-sources
description: Re-project a spec doc's body `# Sources` sub-sections from frontmatter — `## Requests` from `spec_source_requests`, `## Docs` from `spec_source_docs` — preserving any operator-authored glosses on existing wikilink lines (matched by wikilink target). Then regenerates the `# Summary` précis for the asset note and affected container notes (category, product root), and refreshes container stats. Use after manually editing a doc's `spec_source_docs` / `spec_source_requests` frontmatter to bring the body back in sync.
execution-discipline-waiver: "Single-purpose projection primitive — wraps the source-attribution reference; no multi-phase orchestration where step-skip can hide."
---
# Refresh Sources

Primitive skill that re-projects a doc's body `# Sources` sub-sections from its frontmatter source-of-truth keys. The operator edits `spec_source_docs:` / `spec_source_requests:` in frontmatter; this skill brings the human-readable `## Docs` / `## Requests` bullet lists back in sync without disturbing anything else. After projecting sources, the skill also regenerates the `# Summary` précis for the resolved asset note and its container hierarchy (category note, product root note), and refreshes the deterministic stats for each affected container.

The body shape (the `# Sources` H1 container, the `#protected/spec/sources` owner tag, the `## Requests` / `## Docs` sub-sections, their `<!-- auto:spec-<kind>:start --> / :end -->` marker pairs, the bullet format per kind, and the gloss-preservation rule) is owned by `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. This skill never restates that format — follow the reference exactly.

## Input

Signature: `spec.refresh-sources <file-path>`.

1. **File path** — absolute or vault-relative path to a single authored spec doc (`design.md`, `plan.md`, `bug.md`, or product/asset-level `tech.md`). One file only — callers loop over files themselves. The folder-note (status file) carries no `spec_source_docs` and is rejected.

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

### 5. Refresh `# Summary` précis and container stats

Resolve the asset note, category container, and product root note using the path convention (never by `spec_role` — asset, category, and product notes carry no such roles):
- **Asset note** — the status folder-note whose basename matches the enclosing asset directory: `<category>/<slug>/<slug>.md`.
- **Category container** — `<category>/<category>.md` (e.g. `features/features.md`), resolved from the category directory that contains the asset.
- **Product root note** — `<spec_path>/<leaf>.md`, where `<leaf>` is the basename of the product's `spec_path`.

For each of the three notes (asset, category, product root) that actually exist:

- Locate the `# Summary` section. It is protected under `#protected/spec/summary`. Never write outside the `<!-- spec:precis:start --> / <!-- spec:precis:end -->` marker pair within that section. Never touch the operator-authored body below the protected region, and never touch any `#protected/spec/{gates,history}` section.
- Author one LLM-generated précis sentence that captures the meaning of the note and write it into the `<!-- spec:precis:start --> / <!-- spec:precis:end -->` region, replacing any prior précis. The précis is plain prose — no wikilinks, no markup.
- For **container notes** (category, product root) only: after writing the précis, run `Bash(lazycortex-specs render-container-stats <note-path>)` to refresh the `<!-- spec:stats:start --> / <!-- spec:stats:end -->` region with deterministic counts. Never write the stats region by hand; always delegate to the CLI. Asset notes are précis-only — do not call `render-container-stats` on them.

Scope guards:
- Skip any note in the hierarchy that does not exist on disk.
- Skip the stats refresh if `render-container-stats` is unavailable (not on PATH); log the skip in the run log.
- Never touch the `<!-- spec:stats:* -->` region directly — it is exclusively owned by the `render-container-stats` CLI.

Commit all changed notes together with the source-projection changes in one commit per the Key Rules below.

## Output

- The doc's path.
- Per sub-section: the projected bullet count (or `unchanged` when the projection matched the existing bytes byte-for-byte).
- Per affected note (asset, category, product root): précis outcome (`written` or `skipped-not-found`) and stats outcome (`refreshed`, `skipped-asset-note`, or `skipped-unavailable`).

## Failure modes

- **`/spec.refresh-sources` refuses naming a non-authored doc** — the target's `spec_role` is `status` (folder-note) or otherwise not an authored doc that carries `spec_source_docs` → run on an authored doc (`design` / `plan` / `bug` / `tech`) instead.
- **`render-container-stats` not found on PATH** — the CLI is not installed or the shell environment is missing the specs tool. Stats refresh is skipped and logged; précis is still written. Re-run `/spec.install` to restore the CLI.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.refresh-sources/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.refresh-sources)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the file path passed). Body: `# spec.refresh-sources` heading, then `## Actions` and `## Result`.

## Key Rules

- **One primitive, one file** — never accept a list of files. Callers loop themselves.
- **Frontmatter is the source of truth** — body is a projection of it; never write frontmatter from the body.
- **Glosses survive re-projection** — operator-edited displays on `## Docs` / `## Requests` bullets are preserved by matching the wikilink target; only the display right of the `|` is operator-owned.
- **Marker-scoped rewrites only** — touch only the bytes between each kind's `<!-- auto:spec-<kind>:start --> / :end -->` pair for source projection, and between `<!-- spec:precis:start --> / <!-- spec:precis:end -->` for précis; never hand-write into `<!-- spec:stats:* -->` (CLI only).
- **Never breach the protected summary zone** — write only inside `<!-- spec:precis:start --> / <!-- spec:precis:end -->`; never touch operator body below the `# Summary` section, and never touch `#protected/spec/{gates,history}` sections.
- **Commit all changes together** — source projection edits and précis/stats updates for all affected notes go in one atomic commit.
- **Idempotent** — re-running on a doc already in sync is a no-op (byte-for-byte projection match for sources; unchanged précis and stats leave no diff).
