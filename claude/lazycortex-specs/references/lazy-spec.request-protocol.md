---
name: lazy-spec.request-protocol
version: 1
description: Format contract for request files in requests/ — frontmatter shape across the request lifecycle, the status mirror tag, and the terminal status callout.
---
# Request file format

Contract for files in `<vault-root>/requests/`. The `lazy-spec.request-open` and `lazy-spec.request-apply` md-scan command-routines (deterministic Python primitives) together with `spec.coordinator`, running in its routing mode as the review-loop routing specialist (`lazy-spec.coordination-playbook.md` Chapter 7), are the sole writers of frontmatter and the terminal status callout. `lazy-spec.request-apply` (`${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) is the single primitive that enacts a routing decision — attaching to an existing entity or scaffolding a new one are both branches inside it, not separate dispatched skills. `lazy-spec.request-classify` and `lazy-spec.request-find-candidates` remain standalone read-only primitives the coordinator composes in this mode. `lazy-spec.create-request` writes the body-only initial file. `lazy-spec.doctor` reads this reference to validate request-file structure.

## Location

Vault-wide inbox: all request files live at `<content-root>/requests/*.md`, where `<content-root>` is `<settings-dir>/<spec.vault_root>` (default `<settings-dir>/specs`). Per-product `<product>/requests/` subfolders are NOT used — a request may target multiple products and per-product placement would require duplication. The `request/<status>` mirror tag (see "Status mirror tag" below) distinguishes active inbox from terminal records without filesystem moves; the file lives in `requests/` for its entire lifecycle.

The inbox folder-note `requests/requests.md` is always present and committed — `lazy-spec.install` seeds it and the install contract keeps it tracked — so `requests/` is a tracked directory even when no request files have been created yet.

## Frontmatter

### After `lazy-spec.request-open` touches the file (initial)

```yaml
---
spec_role: request                  # static; identifies file kind
request_status: draft               # draft | accepted | rejected
request_class: unknown              # feature | change | bug | task | spec | plan | feedback | unknown
review_active: true                 # review loop opens immediately on first touch
review_round: 1
review_approved: false
tags:
  - request/draft                   # mirror of request_status (see "Status mirror tag")
---
```

The file also gets a `> [!hint] Waiting …` banner above the body in the same write — the review loop is live from first touch, not a later transition.

### Inside review (before finalize)

The initial shape plus review-loop reserved keys managed by the dispatcher (`review_active`, `review_round`, `review_approved`, plus dispatcher-optional fields the consumer routine declares). These keys are dispatcher-owned — request-handling skills and any other authoring agent MUST NOT mutate them; overlays touching them are dropped on collect by the dispatcher.

### Post-finalize, pre-apply (apply-gate window)

Finalize strips all transient `review_*` keys and stamps a single terminal discriminator (`review_result: approved | approved-with-concerns`). The file still carries `request_status: draft` — it is waiting for the apply-gate `lazy-spec.request-apply` md-scan command-routine (the Python worker at `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) to fire:

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

The `lazy-spec.request-apply` routine matches exactly this shape via `filter: { frontmatter: { request_status: { in: [draft] }, review_result: { in: [approved, approved-with-concerns] } } }`. Until apply fires, no other routine sees this file as actionable (the `lazy-spec.request-open` routine excludes it via `review_result: [null]`).

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

The `lazy-spec.request-open` routine populates the full first-touch frontmatter in one write — `spec_role`, `request_status: draft`, `request_class: unknown`, `review_active: true`, `review_round: 1`, `review_approved: false`, `tags: [request/draft]` — plus the Waiting banner above the body. The class stays `unknown` throughout the review loop; the apply worker overwrites it post-finalize when it stamps the terminal markers, reading the class verbatim from the verdict the router settled into its terminal section prose (see `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`).

## Status mirror tag

`request_status: <value>` ⇒ `tags: [..., request/<value>, ...]`.

Same convention as `spec_stage` (see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md` → "Status mirror tag"). Hierarchical Obsidian tags — searchable both by parent (`#request` matches all) and by leaf (`#request/accepted` matches only accepted).

Lock-step rules:

- The request-handling subsystem (`lazy-spec.request-open` + `lazy-spec.request-apply` md-scan command-routines) is the only writer of both `request_status:` and the `request/<value>` tag.
- Every status transition rewrites both fields in one edit. Defensive sweep on rewrite: strip every prior `request/*` tag entry first, then append the new one.
- Other tags (topic, user-applied) are preserved untouched.
- `lazy-spec.doctor` validates that the tag matches the field; mismatch is a finding.

The tag enables Obsidian queries without parsing frontmatter values: `#request/draft` for the active inbox, `#request/accepted` for processed (attached and/or spawned), `#request/rejected` for refused intake.

## Body distribution rules

The request body is **never copied into an entity's docs, whole or in sections**. What lands on the target entity's primary doc is a short per-target description the routing specialist (`spec.coordinator`, in its routing mode) writes; the full request stays exactly one file — the request itself — and reaches the entity's own main writer through that doc's own review job context, not through a document-assembly step. Five points define the whole model:

1. **The coordinator describes, it does not distribute.** `spec.coordinator`, in its routing mode, writes one short per-target description (a sentence or two — what the target is, what changes) into the structured routing-decision block for every spawn/attach/`reference` target it names. It never splits the request body into sections or copies prose into a target doc — describing the target is the entirety of its contribution to doc content.
2. **The worker seeds the description, never the body.** `lazy-spec.request-apply` (the deterministic Python primitive, `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) reads the coordinator's per-target description and seeds it onto the target's **primary doc** — the entity's main authored doc (`design.md` for feature/change, `bug.md` for bug; see "Primary doc" below):
   - **Spawn target** — the description becomes the primary doc's initial content, spliced in before any `# Sources` section, at whatever `spec_stage` the scaffold left the doc (`draft`).
   - **Attach target** — the description becomes an attention-block delta, `> [!attention] change requested: <description>`, spliced in the same way. The existing doc content is never rewritten or replaced.
   - **Empty description** (the coordinator left none, or no structured routing-decision block was present) — the fallback one-line seed `Request routed here — see linked request` is used instead of a silent empty splice. A target always gets SOME visible marker that a request landed on it.
3. **The doc's own main writer builds the real text, from the source, in its own review job.** The primary doc enters (or re-enters) review exactly as any other doc does. When that review job dispatches its class's main writer, the writer's job context is not limited to guideline files — `context_from_frontmatter` (a class-config key consumed by the `lazycortex-review` dispatcher, wired for the `design` and `bug` classes) resolves every wikilink in the doc's own `spec_source_requests` frontmatter list to a file and folds it into the job's `context/`. The main writer reads the linked request file(s) directly and builds the doc's real prose from that first-hand source — the seeded description is a pointer for the writer to start from, not a substitute for reading the request. **A request whose body names an upstream unit** (`- Unit: \`upstream/<repo-key>/<mount>/<unit-path>\``, `lazy-spec.upstream-tick`'s own Phase C shape) does not leave the writer to infer the unit's material from that line alone — the request body carries its own `## Material` section (`upstream_tick.py`'s `_render_request_body`), a concrete Read instruction naming the unit's `source/` (current upstream state) and `processed/` (last processed snapshot) paths verbatim. That section is the deterministic hook: the request travels to the writer whole (point 2's own contract), so the instruction sitting in the body the writer already reads is what closes the chain, not an assumption that the writer will follow the `- Note:` link and guess the directory layout on its own.
4. **Attribution is what makes step 3 possible.** The `spec_source_requests` frontmatter list (populated on every seed, per "Attribution" below) is not just an audit trail — it is the literal input `context_from_frontmatter` reads to decide which files join the writer's context. An unresolvable entry (a wikilink that no longer points at a file) becomes a warning in the job's result, never a silent drop.
5. **This applies uniformly to spawn and attach; there is no separate distribution model for either.** Both paths go through the same `_attach_to_folder_note` seed step inside `lazy-spec.request-apply` — a spawn scaffolds an empty entity first (via the `scaffold-asset` CLI primitive) and then runs the identical seed-and-attribute step an attach target runs directly.

### Routing-block grammar

The router's structured `<!-- routing-decision ... -->` comment (inside the request's `# Routing` section) carries one decision per line:

```
spawn <kind> <slug> [product=<key>] [targets=<category>/<slug>[,<category>/<slug>...]] [:: <description>]
attach <repo-relative-folder-note-path> [:: <description>]
reference <repo-relative-folder-note-path> [:: <description>]
```

- **`:: <description>`** — everything after the first `::` on the line is the router's free-text per-target description (point 1 above). A line without `::` is legacy-valid; its description resolves to empty (triggers the fallback seed in point 2).
- **`product=<key>`** — recognised on any spawn line, in either order relative to `targets=`. Names the product this one target spawns into, so a single request can fan out across several products in one apply run (a design that decomposes into work for more than one product's own spec tree). Absent, the apply worker falls back to its own single-product default (the first product key registered, alphabetically) — correct on a single-product vault, a silent wrong guess on a multi-product one, so `lazy-spec.coordination-playbook.md` Chapter 7 requires the router to state it explicitly once more than one product is registered. An unregistered `product=` value is a hard apply-time failure, never a silent fallback.
- **`targets=<category>/<slug>[,...]`** — recognised only on a `change`-kind spawn line. Names the existing assets the new change asset's design cascades into once its own design is approved (see `lazy-spec.lifecycle-protocol.md` → Change cascade). Ignored (treated as absent) on every other kind/verb. Each token is validated against the product's asset tree at apply time; an unresolvable token is excluded from what gets written to `spec_targets` and surfaces as a warning in the apply run's JSON summary (stdout) — never a silent drop and never a hard failure of the whole apply pass. It does not become a `# History` line — the doc's `# History` is a different mechanism (the review-loop chronicle).
- **`reference <path>`** — names an existing asset the router judges already implements the request (`lazy-spec.coordination-playbook.md` Chapter 7). Applying it writes `spec_targets` onto the REQUEST's own frontmatter (reusing the same list-typed key `targets=` writes onto a change's folder-note — one mechanism, not two) and touches nothing else: no scaffold, no doc seed, no `spec_source_requests` attribution, no review opened on the referenced asset. A request whose routing decision is entirely `reference` lines is still a full accept, not a rejection.
- Multiple `spawn` / `attach` / `reference` lines are allowed in one block (a request may fan out to several targets). Dedup is per `(kind, slug)` for spawn and per path for attach / reference (each its own set) — first occurrence wins.
- A line without a recognised `spawn` / `attach` / `reference` verb, or a blank line, is silently skipped — the router may mix structured decisions with operator-readable notes in the same block.

### Primary doc

"Primary doc" names the one authored doc every entity kind treats as its main write target for a request-seeded description: `design.md` for `feature` / `change`, `bug.md` for `bug`. It replaces the older informal abbreviation this contract used before the description-seed model replaced whole-body distribution — that older term is gone from code and docs alike; use "primary doc" (English) / «основной док» (Russian prose).

### Per-class entity-doc applicability

Not every class spawns/attaches the same set of docs:

| Target entity kind | Has design.md | Has code-plan.md / test-plan.md (opt-in) | Has bug.md |
|---|---|---|---|
| feature | yes | yes | no |
| change | yes | yes | no |
| bug | no | yes | yes |

Assets carry no per-asset `tech.md` — feature/change are `design.md` plus the opt-in `code-plan.md` / `test-plan.md`, bug is `bug.md` plus the same opt-in pair. Product-level architecture lives in `tech.md` at the product root, which is never a request-distribution target. The opt-in `code-plan.md` / `test-plan.md` siblings are never seeded from a request directly — a request's description always lands on the primary doc; any code-plan / test-plan work follows from the primary doc's own review and the launch-checkbox ladder (`lazy-spec.lifecycle-protocol.md` Part 3), not from request distribution.

### Attribution — `# Sources` body section + `spec_source_requests` frontmatter

`lazy-spec.request-apply` records the contributing request in two synchronized places on every doc it seeds:

- **Frontmatter** — appends the request wikilink to the doc's `spec_source_requests` list (source of truth, and the literal input `context_from_frontmatter` reads per point 4 above).
- **Body** — re-projects the `## Requests` H2 sub-section inside the `# Sources` H1 container at the end of body. The sub-section is rewritten between its `<!-- auto:spec-requests:start --> / :end -->` markers; container, owner tag (`#protected/spec/sources`), and any other sub-sections are left untouched.

Re-running apply on the same (request → doc) pair is a no-op (dedupe on wikilink uniqueness in the frontmatter list). Multi-request overlap on the same primary doc is attributed sequentially — each request's wikilink joins the list, each contributes its own row to the `## Requests` projection — and it is the doc's own main writer, reading every linked request from `context/` on its next review round, who reconciles overlapping asks into one coherent doc. Per-line provenance in body prose is intentionally not preserved; provenance lives in `# Sources` at the request-grain.

The full attribution contract — frontmatter source-of-truth, body projection, H1 container shape, per-sub-section HTML markers, lifecycle, doctor checks, extensibility for additional source kinds — lives in [source-attribution](./lazy-spec.sources-protocol.md). A reference Python implementation of the marker manipulation primitives lives at `claude/lazycortex-specs/bin/spec_markers.py` (file is named `spec_markers.py` rather than `markers.py` to avoid a mypy duplicate-module conflict with lazycortex-wiki/bin/markers.py; the exposed class is `Markers`).

## Class taxonomy

`request_class` is an **open set**. It splits into two groups:

### 1. Closed meta classes (plugin-fixed, describe the shape / intent of the request)

| Class      | Meaning                                                                                                                             | Attach to                                  | Spawn                                   |
|------------|-------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------|-----------------------------------------|
| `task`     | Single discrete action without broader design intent ("rename foo", "add endpoint").                                                | any asset type                             | —                                       |
| `spec`     | Body already looks like a finished design doc.                                                                                       | feature / any operator-defined type        | any declared asset type                 |
| `plan`     | Body is an implementation plan (`## Phases` / `## Tasks`, `superpowers:writing-plans` shape).                                         | feature / change / any operator-defined    | any declared asset type                 |
| `feedback` | Opinion / observation without a concrete ask.                                                                                       | any existing entity                        | —                                       |
| `unknown`  | Classifier could not decide.                                                                                                         | —                                          | — (specialist asks via clarifying callout to disambiguate) |

Spawn is not a fixed word list: `apply_request.py` validates a spawn line's asset type against the shipped declarations plus whatever every registered product declares, so an operator's own type is spawnable without touching the worker. The spawn line carries the decisions the worker never guesses — `docs=<name>:<type>[,…]` (mandatory: the scaffolder has no default layout), optional `path=` (else the type's `default_path`) and `tools=`.

### 2. Asset types (open set: shipped plus operator-defined)

Shipped: the types declared in `references/lazy-spec.asset-types.json` — `feature`, `change`, `bug`, `content`, `research`. Operator-defined: any keys from `products[<key>].asset_types` in `lazy.settings.json` (typical examples for non-software products — `characters`, `scenes`, `chapters`), merged over the shipped set key-by-key. A type's folder is its `default_path`, not its name, and it is a place rather than a fact — the asset's kind is the `spec_asset_type` key on its status folder-note.

| Class                                          | Meaning                                                                                | Attach                                                                  | Spawn                                                                                                              |
|------------------------------------------------|-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `feature`                                      | Desired NEW behaviour at the product level.                                            | `features` folder                                                         | `features` folder                                                                                                     |
| `change`                                       | Modification to existing behaviour; the body names what to change.                     | `changes` folder                                                          | `changes` folder                                                                                                      |
| `bug`                                          | Defect: reproduction steps, observed-vs-expected, stack trace.                         | `bugs` folder                                                             | `bugs` folder                                                                                                         |
| *operator-defined* (`characters`, `scenes`, …) | An asset of a type declared by the operator on this product.                           | works today, via an explicit `[[path]]` wikilink to the existing asset    | supported — the worker validates the kind against the product's declared types and scaffolds into the type's folder |

Bug-class requests can attach only to existing `bug` entities (not to features); the bug describes the problem and gets its own lifecycle.

A `plan`-class request that names no existing feature / change can spawn one — same description-seeding model as every other spawn (§ above): the router's per-target description seeds the new entity's primary doc (`design.md`) as draft content, never the `code-plan.md` / `test-plan.md` siblings, and the request body itself is never copied into any sibling doc. The new entity still goes through its own review cycle to validate the spec.

The full valid set is resolved **dynamically** by `lazy-spec.request-classify`: the closed meta group (fixed) plus the asset types visible on the target product (or the union across every configured product when the request is not yet pinned to one). When the operator declares a new asset type via `lazy-spec.add-asset-type`, the classifier sees it on the next dispatch — no rubric update needed.

## Lifecycle invariants

The request walks three stages: the `lazy-spec.request-open` routine opens it (naked → draft frontmatter), the review loop runs (operator clarifies via review-cycle, `spec.coordinator` settles class + routing into its terminal section in its routing mode), the `lazy-spec.request-apply` worker applies it post-finalize — see `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py` for the apply implementation (self-contained Python primitive: input shape, completion sequence, terminal markers, side-effect bounds all live in the script body).

- A request file is created body-only (`lazy-spec.create-request` writes no frontmatter; `lazy-spec.request-open` adds minimal frontmatter on first scan).
- The request-handling subsystem is the SOLE writer of `spec_role`, `request_status`, `request_class`, and the `request/<value>` tag. Other skills / agents / humans MUST NOT mutate these. `lazy-spec.request-open` writes the minimal set at open; the `lazy-spec.request-apply` worker writes the terminal set (including `request_class`) at apply. The review-loop routing specialist (`spec.coordinator`, in its routing mode) writes only its own section body and never touches frontmatter.
- `request_status` transitions: `draft → accepted` OR `draft → rejected`. Both terminal — a request file in any terminal status is an audit record; there is no path back without manual operator intervention.
- `source_requests` on every spawned / attached folder-note resolves to an existing request file. Forward-only link — the reverse direction (request → spawned entities) lives in the terminal status callout body, not as a separate body section.
- The request file stays in `<content-root>/requests/` for its entire lifetime. Never moved.
- The `lazy-spec.request-open` md-scan routine uses the composite filter `review_active: {in: [null], not_in: []} + review_result: {in: [null], not_in: []}` to match files that have not yet entered the review loop; the `lazy-spec.request-apply` routine uses `request_status: {in: ["draft"], not_in: []} + review_result: {in: ["approved", "approved-with-concerns"], not_in: []}` to match post-finalize files ready for apply. Terminal-state files (`request_status` ∈ `accepted | rejected`) are silent — no filter matches them.
