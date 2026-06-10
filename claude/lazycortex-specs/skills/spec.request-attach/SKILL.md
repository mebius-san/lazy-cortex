---
name: spec.request-attach
description: Attach a request to an existing entity. Distributes the request body across the entity's docs by content type (whole-doc match → section-split → fallback per spec.request-protocol.md), maintains a `# Sources` H1 attribution section in every populated doc, appends a wikilink-only entry to the folder-note's ## Source requests, opens a fresh review cycle on every populated doc via lazy-review.start. Idempotent on re-invocation.
execution-discipline-waiver: "Single-purpose primitive — distribute body to one target entity; idempotent on the request side."
---
# Attach a request to an existing entity

Append a request's content to an existing feature, change, or bug. The body is distributed across the entity's docs per the rules in `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md` → "Body distribution rules"; the folder-note gets only a wikilink in `## Source requests`.

This is the only primitive that crosses the boundary between a request file and a target entity. `spec.request-spawn` delegates to this skill after scaffolding an empty entity.

## Input

- **`request_path`** — absolute or vault-relative path to the request file
- **`target_folder_note_path`** — absolute or vault-relative path to the entity's folder-note. Per the canonical convention (`${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`) the folder-note's filename matches the parent folder, e.g. `<product>/{features,changes,bugs}/<slug>/<slug>.md`.

## Process

### 1. Read the request body

Strip frontmatter from the request file. Keep title (H1) + remainder of body. Skip the request's own `# Routing` block (routing specialist's working area — stripped by `spec.request-apply` after parsing the resolved prose).

### 2. Determine the target entity kind

Read the target folder-note's frontmatter. Verify `role: status`. Infer kind from the folder-note's path:

- `<product>/features/<slug>/<slug>.md` ⇒ `feature`
- `<product>/changes/<slug>/<slug>.md` ⇒ `change`
- `<product>/bugs/<slug>/<slug>.md` ⇒ `bug`

Per the per-class entity-doc applicability table in `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md`, the allowed authored docs for this entity are:

- feature / change → `design.md`, `plan.md`
- bug → `bug.md`, `plan.md`

### 3. Distribute body content (two-tier detection)

Apply the body distribution rules from `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md` → "Body distribution rules":

1. **Tier 1 (whole-doc match)** — title-suffix hint (`— design`, `plan`, `tech`, `bug`, `spec`), structural match (e.g. superpowers plan skeleton), or LLM judgment that the body IS one doc type ⇒ paste whole body into the matching target doc; strip the type-suffix from the H1.
2. **Tier 2 (section-split)** — recognised section headers route per the body-distribution map in the reference. Sections that target a doc the entity doesn't have fall back to the entity's WTR doc (`design.md` for feature/change, `bug.md` for bug).
3. **Tier 3 (fallback)** — no structure ⇒ whole body into the WTR doc (`design.md` for feature/change, `bug.md` for bug) as the initial draft.

### 4. Apply the distribution to each target doc

For each target doc that received content from step 3:

- **If currently `spec_stage: empty`** — replace the doc body with the extracted content; call `spec.set-stage <doc> draft` (which also rewrites the `spec/<value>` mirror tag).
- **If currently `spec_stage: draft`** — append the new content **flat** to the end of the doc body. No `## From [[…]] — <date>` H2 wrap — distributed prose lives directly under its named section (`## Premise`, `## Stated goal`, etc.) where the body-distribution rules placed it; attribution is recorded once per request in the `# Sources` section (step 4b) instead of repeated as an H2 wrapper. Stage stays `draft`.
- **If currently `spec_stage: approved`** — the doc is a frozen accepted artifact, so plain append would silently mutate it. Instead: insert the new content **as diff blocks** under its target sections (using the same diff-rendering conventions lazy-review's writer round emits — additions marked, no in-place rewriting of accepted prose), then call `spec.set-stage <doc> draft`, then invoke `Skill(skill: "lazycortex-review:lazy-review.submit", args: "<doc>")` to open the review loop directly on the reviewer round (the writer-round diffs are already in the file). The next review cycle accepts or rejects the request's contribution as an explicit delta against the previously-approved body.
- **If currently `spec_stage: rejected` or `cancelled`** — refuse the attach. These are terminal stages for the target doc — the operator declared the doc unworkable or abandoned. Surface a refusal naming the target, its stage, and that the operator must first revive the doc (`spec.set-stage <doc> draft`) before this request can attach to it. The request file is left untouched; its `request_status` stays at the pre-attach value so the operator can retry the attach after reviving the target. Do NOT silently flip the doc's stage on behalf of the operator.

Distinct contributions from multiple requests that land in the same section (`## Premise` from request X plus `## Premise` from request Y) are appended sequentially as flat prose — merging overlap is the entity-designer's job in the entity's own review cycle, not the attach skill's job. Per-line provenance is intentionally not preserved in body prose; provenance lives in `# Sources` at the request-grain.

### 4b. Update `spec_source_requests` frontmatter and re-project the `## Requests` body sub-section

For each doc that received content in step 4:

**a. Frontmatter (source of truth).** Append the request's wikilink to the doc's `spec_source_requests` list, dedupe on wikilink (not on date). The list keeps insertion order — first wikilink stays first. When `spec_source_requests` is absent (older doc predating this convention), create the key with the new wikilink as the only entry.

**b. Body projection — re-project the `## Requests` H2 sub-section** inside the `# Sources` H1 container at the end of body. The full contract (container shape, per-kind markers, lifecycle, doctor checks) lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. Canonical shape:

```markdown
# Sources
#protected/spec/sources

## Requests
<!-- auto:spec-requests:start -->
- [[<request-wikilink>|<display>]] — <YYYY-MM-DD>
<!-- auto:spec-requests:end -->
```

Three nested levels, each owned by a different writer:

- **H1 `# Sources` + owner tag `#protected/spec/sources`** — section container, owned by specs as a whole (no managed inner bytes at this level). The H1 + tag pair signals lazy-review.finalize to preserve the section byte-for-byte.
- **H2 `## Requests`** — request-kind sub-section. The sub-section heading itself is operator-territory (preserved across rewrites); specs only manages the bytes between the per-kind markers below.
- **Per-kind HTML markers `<!-- auto:spec-requests:start --> / :end -->`** — narrow rewrite boundary for THIS sub-section only. Specs owns only the bullet list between this marker pair. Other H2 sub-sections under the same `# Sources` container (e.g. `## External links` operator-authored, or a future auto-managed `## RFCs` with its own `<!-- auto:spec-rfcs:* -->` marker pair) coexist freely and are NEVER touched by this writer.

Apply the projection mechanically: the bullet list between the request-markers is `[ - [[<wikilink>|<display>]] — <YYYY-MM-DD> ]` joined by newlines, one per entry in `spec_source_requests`, in the frontmatter's order. Dates: when adding a new wikilink, use today's UTC date (`YYYY-MM-DD`); existing entries keep their original date.

On every attach:

- **`# Sources` container absent** — create the container (`# Sources` heading + `#protected/spec/sources` tag + blank line), then the `## Requests` sub-section with its marker pair and the single new bullet.
- **`# Sources` present but `## Requests` absent** — append the `## Requests` sub-section (heading + marker pair + bullet) inside the container, BELOW the protected tag and ABOVE any operator-authored content under the container.
- **`# Sources` and `## Requests` both present, request not yet in `spec_source_requests`** — append the wikilink to the frontmatter list and re-write the bullet list between the existing request-kind markers (full projection from the updated list). Preserve every other byte in the doc.
- **Request already in `spec_source_requests`** — no-op (the frontmatter check is the dedupe anchor; body projection is already in sync). This is the attach-skill's idempotence.

The frontmatter list is the dedupe anchor; the body projection always follows it. Re-running the skill on the same (request → doc) pair short-circuits at the frontmatter check, before any body work happens.

### 5. Folder-note `## Source requests` — append wikilink only

Append one line to the folder-note's `## Source requests` section (create the section if missing):

```markdown
- [[<request-wikilink>|<display>]] — <YYYY-MM-DD>
```

The display name in the wikilink follows `<product> request: <slug>` or just the request title — caller's choice. Body of request NEVER goes here.

Idempotent: re-running with the same request → target leaves the existing line in place (dedupe on wikilink).

### 6. Open a review cycle on every populated doc

For each doc that received content in step 4 — invoke the review-loop start verb on the doc (cross-plugin call). When the doc is already in review, the verb is a no-op.

The folder-note is NOT opened into review by this skill — only the authored docs that received content. The folder-note serves as a status anchor; its review state is governed by `spec.step-forward`.

The request body itself is NOT mutated by this skill. The request's `request_status` and `request/<value>` tag are set later by `spec.request-apply` once every attach / spawn for the request resolves; the reverse link from request → spawned entities is carried in the apply's terminal status callout body (not a separate body section).

## Idempotence

Re-running the skill on the same request → target pair is a no-op:

- The wikilink-uniqueness check in the `# Sources` bullet list dedupes content appends (skip body distribution entirely when the request's wikilink is already listed).
- The `## Source requests` line in the folder-note dedupes on the wikilink.
- The review-loop start verb is itself idempotent.

## Commit-message discipline

When the caller commits the changes this skill produced, the commit subject and body MUST describe the literal staged diff — not the operation's generic template. Forbidden words unless prior state with the matching shape was directly observed: `re-` (re-attach, re-add, re-distribute), `revised`, `restored`, `restores missing`, `again`, `previously`, `updated body`. These narrative words imply prior history the current diff does not show. Subject pattern: `spec.request-attach: <verb> <what> on <target>`; verbs are `add` (first-time content), `append` (subsequent content into existing sections), `link` (wikilink-only into folder-note or `# Sources` bullet). Avoid `update / updated body` — say which doc and what kind of change (`add design.md draft`, `append plan.md prose + Sources bullet`, `link folder-note ## Source requests`).

## Failure modes

- **`request_path` does not exist** — abort with a clear error.
- **`target_folder_note_path` does not point at a `role: status` file** — abort. Caller passed wrong path.
- **Target entity is `cancelled: true`** — abort. Cannot attach to a cancelled entity. Caller should pick a different target or spawn a new one.

## Run logging

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.request-attach/YYYY-MM-DD_HH-MM-SS.md` listing inputs, the per-doc distribution decisions, and the resulting stage transitions.
