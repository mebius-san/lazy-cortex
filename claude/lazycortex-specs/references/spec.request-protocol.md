---
name: spec.request-protocol
version: 1
description: Format contract for request files in requests/ — frontmatter shape across the request lifecycle, the status mirror tag, and the terminal status callout.
---
# Request file format

Contract for files in `<vault-root>/requests/`. The `spec.request-open` and `spec.request-apply` md-scan command-routines (deterministic Python primitives) together with the `spec.request-router` review-loop routing specialist (LLM expert) are the sole writers of frontmatter and the terminal status callout. The four `spec.request-*` primitive skills implement the mechanical pieces; `spec.create-request` writes the body-only initial file. `spec.doctor` reads this reference to validate request-file structure.

## Location

Vault-wide inbox: all request files live at `<vault-root>/requests/*.md`. Per-product `<product>/requests/` subfolders are NOT used — a request may target multiple products and per-product placement would require duplication. The `request/<status>` mirror tag (see "Status mirror tag" below) distinguishes active inbox from terminal records without filesystem moves; the file lives in `requests/` for its entire lifecycle.

## Frontmatter

### After `spec.request-open` touches the file (initial)

```yaml
---
spec_role: request                  # static; identifies file kind
request_status: draft               # draft | accepted | rejected
request_class: unknown              # feature | change | bug | task | spec | plan | feedback | unknown
tags:
  - request/draft                   # mirror of request_status (see "Status mirror tag")
---
```

### Inside review (before finalize)

The initial shape plus review-loop reserved keys managed by the dispatcher (`review_active`, `review_round`, `review_approved`, plus dispatcher-optional fields the consumer routine declares). These keys are dispatcher-owned — request-handling skills and any other authoring agent MUST NOT mutate them; overlays touching them are dropped on collect by the dispatcher.

### Post-finalize, pre-apply (apply-gate window)

Finalize strips all transient `review_*` keys and stamps a single terminal discriminator (`review_result: approved | approved-with-concerns`). The file still carries `request_status: draft` — it is waiting for the apply-gate `spec.request-apply` md-scan command-routine (the Python worker at `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) to fire:

```yaml
---
spec_role: request
request_status: draft               # still draft; apply-gate flips it next
request_class: unknown              # still unknown — router does not write frontmatter
review_result: approved             # or approved-with-concerns
tags:
  - request/draft
---
```

The `spec.request-apply` routine matches exactly this shape via `filter: { frontmatter: { request_status: { in: [draft] }, review_result: { in: [approved, approved-with-concerns] } } }`. Until apply fires, no other routine sees this file as actionable (the `spec.request-open` routine excludes it via `review_result: [null]`).

### Terminal (post-apply)

```yaml
---
spec_role: request
request_status: accepted            # or rejected
request_class: change               # resolved by apply from the routing prose verbatim
review_result: approved             # preserved as durable record
tags:
  - request/accepted                # mirror updates in lock-step with request_status
---
```

The body retains the original human-authored content as audit trail. A status callout above the title carries each target wikilink (written by the apply worker at `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`); the routing scaffold is stripped — no `# Routing` section, no separate back-link list. The `# History` section (review-loop chronicle) survives.

The `spec.request-open` routine populates only the minimal frontmatter on first touch — `spec_role`, `request_status: draft`, `request_class: unknown`, `tags: [request/draft]`. The class stays `unknown` throughout the review loop; the apply worker overwrites it post-finalize when it stamps the terminal markers, reading the class verbatim from the verdict the router settled into its terminal section prose (see `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`).

## Status mirror tag

`request_status: <value>` ⇒ `tags: [..., request/<value>, ...]`.

Same convention as `spec_stage` (see `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md` → "Status mirror tag"). Hierarchical Obsidian tags — searchable both by parent (`#request` matches all) and by leaf (`#request/accepted` matches only accepted).

Lock-step rules:

- The request-handling subsystem (`spec.request-open` + `spec.request-apply` md-scan command-routines) is the only writer of both `request_status:` and the `request/<value>` tag.
- Every status transition rewrites both fields in one edit. Defensive sweep on rewrite: strip every prior `request/*` tag entry first, then append the new one.
- Other tags (topic, user-applied) are preserved untouched.
- `spec.doctor` validates that the tag matches the field; mismatch is a finding.

The tag enables Obsidian queries without parsing frontmatter values: `#request/draft` for the active inbox, `#request/accepted` for processed (attached and/or spawned), `#request/rejected` for refused intake.

## Body distribution rules

When the expert spawns or attaches an entity, the request body is **distributed across the entity's docs by content type** — never copied wholesale into a single dump. The folder-note's `## Source requests` block holds only the wikilink to the request file, never the body.

The expert applies a two-tier detection priority (plus a fallback):

### Tier 1 — whole-doc match (top priority)

If the entire body is recognizably one document type, the whole body goes into the corresponding doc as a `draft` and the title is normalised (type-suffix stripped). Detection signals:

- **Title-suffix hint**: `# CSV export — design`, `# Foo plan`, `# Bar tech`, `# Baz bug`, `# Qux spec`
- **Title-prefix hint**: `# Design: ...`, `# Plan: ...`, `# Tech: ...`, `# Bug: ...`, `# Spec: ...`
- **Frontmatter hint**: `title: ... — design` or explicit `role:` already present
- **Structural match**: body matches a known template skeleton (e.g. a plan-skeleton has a fixed `## Phases` / `## Tasks` shape — recognisable as a plan)
- **LLM judgment**: in the absence of explicit signals, the expert evaluates whether the body reads as a complete design / plan / tech / bug / spec doc

When tier 1 matches, no section split happens. The body is the doc.

### Tier 2 — section-based split (when tier 1 doesn't match)

The expert scans body for known section headers (case-insensitive, fuzzy) and routes each section to its target doc:

| Body section header | Destination |
|---|---|
| `## Design` / `## Behavior` / `## What it should do` | `design.md` |
| `## Plan` / `## Implementation` / `## Steps` / `## Tasks` | `plan.md` |
| `## Repro` / `## Reproduction` / `## Observed` / `## Expected` | `bug.md` (only for bug-class) |
| Any other named section or unstructured prose between sections | `design.md` (or `bug.md` for bugs) — fallback |

Each extracted block becomes the initial body of the target doc with `spec_stage: draft`. Empty target docs stay at `spec_stage: empty`.

### Tier 3 — fallback (no structure detected)

Unstructured prose (no recognised sections, no whole-doc signals) goes wholesale into `design.md` (or `bug.md` for bugs) as the initial draft. Other docs stay empty.

### Per-class entity-doc applicability

Not every class spawns/attaches the same set of docs. The detection map above is filtered by the target entity's allowed docs:

| Target entity kind | Has design.md | Has plan.md | Has bug.md |
|---|---|---|---|
| feature | yes | yes | no |
| change | yes | yes | no |
| bug | no | yes | yes |

Assets carry no per-asset `tech.md` — feature/change are `design.md` + `plan.md`, bug is `bug.md` + `plan.md`. Product-level architecture lives in `docs/tech.md`, which is not a request-distribution target.

If a body section maps to a doc the target doesn't have, the content falls back to the target's WTR doc (`design.md` for feature/change, `bug.md` for bug). E.g. a `## Design` section on a bug-class request goes into `bug.md` rather than being lost.

### Attribution — `# Sources` body section + `spec_source_requests` frontmatter

`spec.request-attach` distributes prose flat (no inline attribution H2) and records the contributing request in two synchronized places:

- **Frontmatter** — appends the request wikilink to the doc's `spec_source_requests` list (source of truth).
- **Body** — re-projects the `## Requests` H2 sub-section inside the `# Sources` H1 container at the end of body. The sub-section is rewritten between its `<!-- auto:spec-requests:start --> / :end -->` markers; container, owner tag (`#protected/spec/sources`), and any other sub-sections are left untouched.

Re-running attach on the same (request → doc) pair is a no-op (dedupe on wikilink uniqueness in the frontmatter list). Multi-request overlap in body prose is appended sequentially; merging is the entity-designer's job in the entity's own review cycle, not the attach skill's job. Per-line provenance in body prose is intentionally not preserved.

The full attribution contract — frontmatter source-of-truth, body projection, H1 container shape, per-sub-section HTML markers, lifecycle, doctor checks, extensibility for additional source kinds — lives in [source-attribution](./spec.sources-protocol.md). A reference Python implementation of the marker manipulation primitives lives at `claude/lazycortex-specs/bin/spec_markers.py` (file is named `spec_markers.py` rather than `markers.py` to avoid a mypy duplicate-module conflict with lazycortex-wiki/bin/markers.py; the exposed class is `Markers`).

## Class taxonomy

`request_class` is an **open set**. It splits into two groups:

### 1. Closed meta classes (plugin-fixed, describe the shape / intent of the request)

| Class      | Meaning                                                                                                                             | Attach to                                  | Spawn                                   |
|------------|-------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------|-----------------------------------------|
| `task`     | Single discrete action without broader design intent ("rename foo", "add endpoint").                                                | any asset category                         | —                                       |
| `spec`     | Body already looks like a finished design doc.                                                                                       | feature / any operator-defined category    | feature / any operator-defined category |
| `plan`     | Body is an implementation plan (`## Phases` / `## Tasks`, `superpowers:writing-plans` shape).                                         | feature / change / any operator-defined    | feature / change / any operator-defined |
| `feedback` | Opinion / observation without a concrete ask.                                                                                       | any existing entity                        | —                                       |
| `unknown`  | Classifier could not decide.                                                                                                         | —                                          | — (specialist asks via clarifying callout to disambiguate) |

### 2. Asset categories (open set: built-in plus operator-defined)

Built-in: `feature`, `change`, `bug`. Operator-defined: any keys from `products[<key>].asset_categories` in `lazy.settings.json` (typical examples for non-software products — `characters`, `scenes`, `chapters`). Each value names a same-name folder under the product the request attaches to or spawns into.

| Class                                          | Meaning                                                                                | Attach / Spawn                       |
|------------------------------------------------|---------------------------------------------------------------------------------------|--------------------------------------|
| `feature`                                      | Desired NEW behaviour at the product level.                                            | `features` folder                    |
| `change`                                       | Modification to existing behaviour; the body names what to change.                     | `changes` folder                     |
| `bug`                                          | Defect: reproduction steps, observed-vs-expected, stack trace.                         | `bugs` folder                        |
| *operator-defined* (`characters`, `scenes`, …) | A content entity from a category declared by the operator on this product.             | same-name folder under the product   |

Bug-class requests can attach only to existing `bug` entities (not to features); the bug describes the problem and gets its own lifecycle.

A `plan`-class request that names no existing feature / change can spawn one — the body becomes the new entity's `plan.md` content, and any design content in the body lands in `design.md`. The new entity still goes through its own review cycle to validate the spec.

The full valid set is resolved **dynamically** by `spec.request-classify`: the closed meta group (fixed) plus the asset categories of the target product (or the union across every configured product when the request is not yet pinned to one). When the operator registers a new operator-defined category via `spec.add-asset-category`, the classifier sees it on the next dispatch — no rubric update needed.

## Lifecycle invariants

The request walks three stages: the `spec.request-open` routine opens it (naked → draft frontmatter), the review loop runs (operator clarifies via review-cycle, `spec.request-router` settles class + routing into its terminal section), the `spec.request-apply` worker applies it post-finalize — see `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py` for the apply implementation (self-contained Python primitive: input shape, completion sequence, terminal markers, side-effect bounds all live in the script body).

- A request file is created body-only (`spec.create-request` writes no frontmatter; `spec.request-open` adds minimal frontmatter on first scan).
- The request-handling subsystem is the SOLE writer of `spec_role`, `request_status`, `request_class`, and the `request/<value>` tag. Other skills / agents / humans MUST NOT mutate these. `spec.request-open` writes the minimal set at open; the `spec.request-apply` worker writes the terminal set (including `request_class`) at apply. The review-loop routing specialist (`spec.request-router`) writes only its own section body and never touches frontmatter.
- `request_status` transitions: `draft → accepted` OR `draft → rejected`. Both terminal — a request file in any terminal status is an audit record; there is no path back without manual operator intervention.
- `source_requests` on every spawned / attached folder-note resolves to an existing request file. Forward-only link — the reverse direction (request → spawned entities) lives in the terminal status callout body, not as a separate body section.
- The request file stays in `<vault-root>/requests/` for its entire lifetime. Never moved.
- The `spec.request-open` md-scan routine uses the composite filter `review_active: {in: [null], not_in: []} + review_result: {in: [null], not_in: []}` to match files that have not yet entered the review loop; the `spec.request-apply` routine uses `request_status: {in: ["draft"], not_in: []} + review_result: {in: ["approved", "approved-with-concerns"], not_in: []}` to match post-finalize files ready for apply. Terminal-state files (`request_status` ∈ `accepted | rejected`) are silent — no filter matches them.
