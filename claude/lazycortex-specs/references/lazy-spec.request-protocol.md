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

The request body is **never copied into an entity's docs, whole or in sections** — and nothing is seeded in its place. What lands on a target at apply time is attribution only: the folder-note's `## Source requests` bullet, plus the `spec_source_requests` frontmatter link on an attach target's primary doc; the full request stays exactly one file — the request itself — and reaches the entity's own main writer through that doc's own review job context, not through a document-assembly step. Five points define the whole model:

1. **The coordinator routes, it does not describe or distribute.** `spec.coordinator`, in its routing mode, writes only verbs and structural fields into the structured routing-decision block — kind, slug, `product=`, `path=`, `tools=`, `targets=`, `drop=`. It never splits the request body into sections, copies prose into a target doc, or writes a per-target description for anyone to seed — writers read the request itself, never a re-telling.
2. **The worker attributes, it never seeds prose.** `lazy-spec.request-apply` (the deterministic Python primitive, `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) records where the request landed and nothing more:
   - **Spawn target** — the asset folder and its status folder-note alone are scaffolded (plus the group note when missing); no authored documents are created and no review opens. The folder-note gets its `## Source requests` bullet; per-document attribution arrives later, when the coordinator's launch checkboxes create each doc via the `lazycortex-specs seed-doc <product> <folder-note-path> --doc <name>:<type>` primitive — one doc from the type's template chain, at stage `empty`, with the folder-note's `spec_source_requests` copied into the doc's frontmatter.
   - **Attach target** — attribution is the whole delta: `ensure_source_request` stamps `spec_source_requests` (plus the `## Requests` body projection) on the target's **primary doc** — the entity's main authored doc (`design.md` for feature/change, `bug.md` for bug; see "Primary doc" below) — the folder-note gets its `## Source requests` bullet, and the primary doc re-enters review via `start` (or `submit` after a pre-launch ladder rollback). No callout, no delta text — the existing doc content is never rewritten or extended.
3. **The doc's own main writer builds the real text, from the source, in its own review job.** The primary doc enters (or re-enters) review exactly as any other doc does. When that review job dispatches its class's main writer, the writer's job context is not limited to guideline files — `context_from_frontmatter` (a class-config key consumed by the `lazycortex-review` dispatcher, wired for the `design` and `bug` classes) resolves every wikilink in the doc's own `spec_source_requests` frontmatter list to a file and folds it into the job's `context/`. The main writer reads the linked request file(s) directly and builds the doc's real prose from that first-hand source — there is no seeded pointer or description to start from; the request itself is the material. **A request whose body names an upstream unit** (`- Unit: \`upstream/<repo-key>/<mount>/<unit-path>\``, `lazy-spec.upstream-tick`'s own Phase C shape) does not leave the writer to infer the unit's material from that line alone — the request body carries its own `## Material` section (`upstream_tick.py`'s `_render_request_body`), a concrete Read instruction naming the unit's `source/` (current upstream state) and `processed/` (last processed snapshot) paths verbatim. That section is the deterministic hook: the request travels to the writer whole (point 2's own contract), so the instruction sitting in the body the writer already reads is what closes the chain, not an assumption that the writer will follow the `- Note:` link and guess the directory layout on its own.
4. **Attribution is what makes step 3 possible.** The `spec_source_requests` frontmatter list (per "Attribution" below) is not just an audit trail — it is the literal input `context_from_frontmatter` reads to decide which files join the writer's context. An unresolvable entry (a wikilink that no longer points at a file) becomes a warning in the job's result, never a silent drop.
5. **This applies uniformly to spawn and attach; there is no separate distribution model for either.** Both paths land the same folder-note `## Source requests` bullet at apply time; what differs is only when the per-document `spec_source_requests` stamp arrives — an attach stamps its existing primary doc directly (`ensure_source_request`), a spawn's documents each inherit the folder-note's list at their own `seed-doc` creation (a spawn scaffolds only the empty folder + note first, via the `scaffold-asset` CLI primitive).

### Routing-block grammar

The router's structured `<!-- routing-decision ... -->` comment (inside the request's `# Routing` section) carries one decision per line:

```
spawn <kind> <slug> [product=<key>] [targets=<category>/<slug>[,<category>/<slug>...]]
spawn-product key=<key> path=<spec_path> [experts=<role>:<name>[,...]] :: <description>
attach <repo-relative-folder-note-path | level-doc-path>
reference <repo-relative-folder-note-path>
```

- **`spawn-product key=<key> path=<spec_path> :: <description>`** — registers a new product. Both fields are required and so is the `:: <description>` (one or two sentences naming what the product is) — this is the one line of the grammar where the description is read rather than ignored, since no target document exists yet to carry the intent. The optional `experts=<role>:<name>[,...]` field names the product's role experts and is never guessed: the candidates are settled by a `[!question]` callout during the request's own review, so the line apply reads carries an already-decided set; absent the field, apply wires no role experts. Apply writes `products[<key>]` with the given `spec_path` and no `source` block (a request only ever spawns a design-only product; a code binding is added later through `/lazy-spec.product-config` in edit mode), scaffolds the folder and its `spec_role: product` level note, seeds `vision.md` at stage `empty` with the request attributed onto it, and opens that document's review. An unregistered `key` whose `path` already exists is a hard apply-time refusal, never a silent merge. The line carries no precondition of its own — a request may spawn a product at any time, whatever state the catalog root's own ladder is in (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 10).
- **`attach` also accepts a level document.** Besides an asset's folder-note, an `attach` line may name a system document loose at a product root or at the content root (`vision.md` / `design.md` / `ui-design.md` / `tech.md`). Apply stamps `spec_source_requests` onto that document directly and reopens its review — a level note carries no `## Source requests` section, so there is no intermediate stamp on the note and no status folder-note is looked for.
- **No `:: <description>` on any other line, no `docs=`.** An older request may carry a trailing `:: <description>` on a `spawn` / `attach` / `reference` line, or a `docs=<name>:<type>[,…]` field on a spawn line — both are tolerated at parse time and ignored: nothing is seeded from either, and a spawn line names no documents (documents come later, from the coordinator's launch checkboxes, per point 2 above). Writers read the request itself, never a re-telling.
- **`product=<key>`** — recognised on any spawn line, in either order relative to `targets=`. Names the product this one target spawns into, so a single request can fan out across several products in one apply run (a design that decomposes into work for more than one product's own spec tree). Absent, the apply worker falls back to its own single-product default (the first product key registered, alphabetically) — correct on a single-product vault, a silent wrong guess on a multi-product one, so `lazy-spec.coordination-playbook.md` Chapter 7 requires the router to state it explicitly once more than one product is registered. An unregistered `product=` value is a hard apply-time failure, never a silent fallback.
- **`targets=<category>/<slug>[,...]`** — recognised only on a `change`-kind spawn line. Names the existing assets the new change asset's design cascades into once its own design is approved (see `lazy-spec.lifecycle-protocol.md` → Change cascade). Ignored (treated as absent) on every other kind/verb. Each token is validated against the product's asset tree at apply time; an unresolvable token is excluded from what gets written to `spec_targets` and surfaces as a warning in the apply run's JSON summary (stdout) — never a silent drop and never a hard failure of the whole apply pass. It does not become a `# History` line — the doc's `# History` is a different mechanism (the review-loop chronicle).
- **`reference <path>`** — names an existing asset the router judges already implements the request (`lazy-spec.coordination-playbook.md` Chapter 7). Applying it writes `spec_targets` onto the REQUEST's own frontmatter (reusing the same list-typed key `targets=` writes onto a change's folder-note — one mechanism, not two) and touches nothing else — the target record holds only the wikilink, never the body: no scaffold, no doc seed, no `spec_source_requests` attribution, no review opened on the referenced asset. A request whose routing decision is entirely `reference` lines is still a full accept, not a rejection.
- Multiple `spawn` / `spawn-product` / `attach` / `reference` lines are allowed in one block (a request may fan out to several targets). Dedup is per `(kind, slug)` for spawn, per `key` for spawn-product, and per path for attach / reference (each its own set) — first occurrence wins.
- A line without a recognised `spawn` / `spawn-product` / `attach` / `reference` verb, or a blank line, is silently skipped — the router may mix structured decisions with operator-readable notes in the same block.

### Primary doc

"Primary doc" names the one authored doc every entity kind treats as its main target for request attribution: `design.md` for `feature` / `change`, `bug.md` for `bug`. It replaces the older informal abbreviation this contract used before attribution replaced whole-body distribution — that older term is gone from code and docs alike; use "primary doc" (English) / «основной док» (Russian prose).

### Per-class entity-doc applicability

Not every class spawns/attaches the same set of docs:

| Target entity kind | Has design.md | Has code-plan.md / test-plan.md (opt-in) | Has bug.md |
|---|---|---|---|
| feature | yes | yes | no |
| change | yes | yes | no |
| bug | no | yes | yes |

Assets carry no per-asset `tech.md` — feature/change are `design.md` plus the opt-in `code-plan.md` / `test-plan.md`, bug is `bug.md` plus the same opt-in pair. Product-level architecture lives in `tech.md` at the product root, which is never a request-distribution target. No document — primary doc or opt-in sibling — is ever created from a request directly: every authored doc is created by the coordinator's launch checkboxes via `seed-doc`, following the launch-checkbox ladder (`lazy-spec.lifecycle-protocol.md` Part 3), never by request distribution. A request's attribution lands on the primary doc — at attach time when the doc exists, at the doc's own `seed-doc` creation on a spawned asset.

### Attribution — `# Sources` body section + `spec_source_requests` frontmatter

`lazy-spec.request-apply` records the contributing request in two synchronized places on an attach target's primary doc (`ensure_source_request`); on a spawned asset, each document instead inherits the folder-note's `spec_source_requests` list into its frontmatter at its own `seed-doc` creation. The two places:

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

Spawn is not a fixed word list: `apply_request.py` validates a spawn line's asset type against the shipped declarations plus whatever every registered product declares, so an operator's own type is spawnable without touching the worker. The spawn line carries the decisions the worker never guesses — optional `path=` (else the type's `default_path`) and `tools=`. It names no documents: a spawn scaffolds only the folder and its status folder-note, and every doc is created later by the coordinator's launch checkboxes via `seed-doc` (a legacy `docs=` field is tolerated and ignored).

### 2. Asset types (open set: shipped plus operator-defined)

Shipped: the types declared in `references/lazy-spec.asset-types.json` — `feature`, `change`, `bug`, `content`, `research`. Operator-defined: any keys from `products[<key>].asset_types` in `lazy.settings.json` (typical examples for non-software products — `characters`, `scenes`, `chapters`), merged over the shipped set key-by-key. A type's folder is its `default_path`, not its name, and it is a place rather than a fact — the asset's kind is the `spec_asset_type` key on its status folder-note.

| Class                                          | Meaning                                                                                | Attach                                                                  | Spawn                                                                                                              |
|------------------------------------------------|-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `feature`                                      | Desired NEW behaviour at the product level.                                            | `features` folder                                                         | `features` folder                                                                                                     |
| `change`                                       | Modification to existing behaviour; the body names what to change.                     | `changes` folder                                                          | `changes` folder                                                                                                      |
| `bug`                                          | Defect: reproduction steps, observed-vs-expected, stack trace.                         | `bugs` folder                                                             | `bugs` folder                                                                                                         |
| *operator-defined* (`characters`, `scenes`, …) | An asset of a type declared by the operator on this product.                           | works today, via an explicit `[[path]]` wikilink to the existing asset    | supported — the worker validates the kind against the product's declared types and scaffolds into the type's folder |

Bug-class requests can attach only to existing `bug` entities (not to features); the bug describes the problem and gets its own lifecycle.

A `plan`-class request that names no existing feature / change can spawn one — same attribution model as every other spawn (§ above): the new entity starts as a folder and folder-note alone, its primary doc (`design.md`) and any `code-plan.md` / `test-plan.md` siblings arriving only via the launch checkboxes, and the request body itself is never copied into any doc. The new entity still goes through its own review cycle to validate the spec.

The full valid set is resolved **dynamically** by `lazy-spec.request-classify`: the closed meta group (fixed) plus the asset types visible on the target product (or the union across every configured product when the request is not yet pinned to one). When the operator declares a new asset type via `lazy-spec.add-asset-type`, the classifier sees it on the next dispatch — no rubric update needed.

## Lifecycle invariants

The request walks three stages: the `lazy-spec.request-open` routine opens it (naked → draft frontmatter), the review loop runs (operator clarifies via review-cycle, `spec.coordinator` settles class + routing into its terminal section in its routing mode), the `lazy-spec.request-apply` worker applies it post-finalize — see `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py` for the apply implementation (self-contained Python primitive: input shape, completion sequence, terminal markers, side-effect bounds all live in the script body).

- A request file is created body-only (`lazy-spec.create-request` writes no frontmatter; `lazy-spec.request-open` adds minimal frontmatter on first scan).
- The request-handling subsystem is the SOLE writer of `spec_role`, `request_status`, `request_class`, and the `request/<value>` tag. Other skills / agents / humans MUST NOT mutate these. `lazy-spec.request-open` writes the minimal set at open; the `lazy-spec.request-apply` worker writes the terminal set (including `request_class`) at apply. The review-loop routing specialist (`spec.coordinator`, in its routing mode) writes only its own section body and never touches frontmatter.
- `request_status` transitions: `draft → accepted` OR `draft → rejected`. Both terminal — a request file in any terminal status is an audit record; there is no path back without manual operator intervention.
- `source_requests` on every spawned / attached folder-note resolves to an existing request file. Forward-only link — the reverse direction (request → spawned entities) lives in the terminal status callout body, not as a separate body section.
- The request file stays in `<content-root>/requests/` for its entire lifetime. Never moved.
- The `lazy-spec.request-open` md-scan routine uses the composite filter `review_active: {in: [null], not_in: []} + review_result: {in: [null], not_in: []}` to match files that have not yet entered the review loop; the `lazy-spec.request-apply` routine uses `request_status: {in: ["draft"], not_in: []} + review_result: {in: ["approved", "approved-with-concerns"], not_in: []}` to match post-finalize files ready for apply. Terminal-state files (`request_status` ∈ `accepted | rejected`) are silent — no filter matches them.
