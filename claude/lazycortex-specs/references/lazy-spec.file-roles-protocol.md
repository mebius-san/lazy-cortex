---
name: lazy-spec.file-roles-protocol
version: 5
description: What a spec document IS — the open `spec_doc_type` set, the closed fifteen-value `spec_role` set and its path constraints, the non-role files (requests, upstream unit notes, attachments), role-only filenames, the mandatory body header, and the path-qualified wikilink form.
---
# File-roles protocol — document type, roles, naming, header, wikilinks

Parts 2 and 3 of the [layout protocol](./lazy-spec.layout-protocol.md), split out at 75 KB and kept under their original numbers so existing `Part N` citations still resolve. What a document IS — its declared type, its role in the closed set, the path it is legal at, the filename it must take, the header it opens with, and the link form that reaches it. Where those files SIT is the layout protocol's Part 1; what an asset's status folder-note and a level note look like inside is the [status-note protocol](./lazy-spec.status-note-protocol.md)'s Parts 4 and 4b. The abstraction height each design level holds is the [doc-height protocol](./lazy-spec.doc-height-protocol.md)'s contract.

## Part 2 — File roles

### Document type

A document's **type** is the `spec_doc_type` frontmatter key, and the set of legal values is **open**, declared rather than enumerated. Two layers declare:

- the plugin, in `references/lazy-spec.doc-types.json` — the shipped types, that file being the only count of them;
- a product, under `products[<key>].doc_types` in `.claude/lazy.settings.json` — merged over the shipped set key-by-key, so a product may flip one flag of a shipped type without restating the rest.

A declaration carries three independent boolean flags, each defaulting to `false`, plus an optional `template`:

- `stages` — the document carries `spec_stage`, and is the only kind `lazy-spec.set-stage` accepts;
- `review` — the document goes through the review loop under a class of the same name;
- `append_only` — the file is only ever appended to, never rewritten;
- `template` — filename of the type's linear template under `templates/spec.docs/`.

Validation everywhere is "a declaration for this type exists", never "this name is in the enum". `lazycortex-specs doc-type` is the one reader: `of <file>`, `resolve <type> --product <key>`, `list --product <key>`, `backfill`.

Three consequences worth stating outright:

- **The basename of an authored document carries no semantics.** `races.md` with `spec_doc_type: design` is a design document; the filename is free.
- **Two documents of the same type in one asset are legal.** Nothing keys off uniqueness of a name.
- **`spec_role` is not replaced by this.** It remains the role/placement key — the status folder-note is `spec_role: status` and has no type at all, and the pins, decisions, and path checks still read it. A document carrying both keys must have them agree; agreement is by family, not literal equality — role `vision` agrees with types `vision` AND `system-vision`, role `design` agrees with types `design` AND `system-design`, role `tech` agrees with type `system-tech`, every other shipped type agrees only with the role of its own name.

### Roles

The `spec_role` frontmatter key is a **closed set** of fifteen values: `vision`, `use-cases`, `design`, `architecture`, `ui-design`, `code-plan`, `test-plan`, `code-report`, `test-report`, `bug`, `tech`, `decisions`, `status`, `product`, `catalog`. A plugin-owned spec doc carries exactly one of these. Role determines what content is allowed.

The last three are folder-note roles rather than document roles — `status` marks an asset's folder-note, and `product` / `catalog` mark the two LEVEL notes ([status-note](./lazy-spec.status-note-protocol.md) Part 4b). None of the three carries a per-file `spec_stage`; each carries gates instead.

The last column records today's defaults only — the authority on whether a document carries `spec_stage` is the `stages` flag of its type's declaration, not this table.

| `spec_role` | Purpose | May contain source URLs? | May carry `spec_source_branches`? | Per-file `spec_stage`? (see the type's `stages` flag) |
|------|---------|--------------------------|------------------------------|-------------------|
| `vision` | Goals, value, one-screen "what this is and for whom" — sections Overview / Goals / Value Proposition / Design Concept / Risks. Goals live ONLY here; the sibling design opens with a reference to it. Three levels: content-root (`vision.md`, the mandatory vault spec, typed `system-vision`), product root (`<spec_path>/vision.md`, seeded at product creation, typed `system-vision`), and asset folders per the type's `vision` contract (typed `vision`) — never on a bug | **No** | No | **Yes** |
| `use-cases` | Opt-in requirements scenarios written before the behavior settles: actors, goals, preconditions, main and alternative flows, postconditions — WHO needs what of the system, in the actor's own language, with no system internals. Three levels: content-root (`use-cases.md` — the system's actors and cross-product scenarios), product root (`<spec_path>/use-cases.md` — cross-feature scenarios), and feature/change asset folders; never on a bug | **No** | No | **Yes** |
| `design` | Behavior, requirements, user flow — WHAT the system does (feature/change/operator-defined-asset doc) | **No** | No | **Yes** |
| `architecture` | Opt-in code-structure design: module boundaries, dependency direction, public contract versus internals, data migration, cost to existing callers — the SHAPE of the code, not the behavior. Feature/change asset-level only, never on a bug. Mandatory once the coordinator judges the asset code-bearing (`lazy-spec.coordination-playbook.md` Chapter 3/8), same as `design` is mandatory once the category needs it | **No** | No | **Yes** |
| `ui-design` | Opt-in interface design: the screens the asset introduces or changes, their per-screen states, the navigation between them, and the interaction decisions behind them — with the HTML mockups filed flat beside it as attachments. Feature/change asset-level only, never on a bug | **No** | No | **Yes** |
| `tech` | Technical specification: architecture, source file map, components, data structures, reuse notes. System-level only (`tech.md` at a product root, or loose at the content-root as the project-wide spec; type `system-tech`) — no per-asset `tech.md` | **Yes** | **Yes** | **Yes** |
| `code-plan` | Opt-in development plan: scope, sequence, implementation notes for the developer. Populated once `design.md` is approved | **Yes** | **Yes** | **Yes** |
| `test-plan` | Opt-in functional test plan: verifies behavior against the design. Populated by the tester expert from the approved design; unit tests belong to the developer, not here | **Yes** | **Yes** | **Yes** |
| `code-report` | Opt-in append-only working journal written during execution, never after the fact. Carries no `spec_source_branches` and no per-file stage — it is not reviewed or approved | No | No | **No** |
| `test-report` | Opt-in append-only working journal written during execution, never after the fact. Same no-stage, no-review contract as `code-report` | No | No | **No** |
| `bug` | Report doc for a bug: what's broken, repro steps, observed vs expected, environment, links to affected code / logs. No companion `design` or `tech` — a bug folder ships only `bug.md` plus whichever quartet members are opt-in-authored | **Yes** (only in the `## Related code / logs` section) | No | **Yes** |
| `status` | Asset folder-note: lifecycle state as flat gate booleans (`spec_design_done`…`spec_released` + `spec_cancelled`), `# Gates` callouts (H1), `# History` log (H1). See [lifecycle](./lazy-spec.lifecycle-protocol.md) | **No** | No | No — carries **gates**, not a per-file stage |
| `product` | Product-root LEVEL note (`<spec_path>/<leaf>.md`): the four level gates plus `spec_halted`, and the coordinator's own body sections. Owns the four system documents loose at that product root. See [status-note](./lazy-spec.status-note-protocol.md) Part 4b | **No** | No | No — carries **level gates** |
| `catalog` | Catalog-root LEVEL note (`<content-root>/<basename>.md`): the same four level gates and the same sections, owning the four system documents loose at the content root, plus the split into products. Exactly one per vault. See [status-note](./lazy-spec.status-note-protocol.md) Part 4b | **No** | No | No — carries **level gates** |
| `decisions` | Opt-in append-only registry of accepted decisions — project-level (`<content-root>/decisions.md`), product-level (`<spec_path>/decisions.md`), or asset-level (`<spec_path>/<category>/<slug>/decisions.md`). Never scaffolded; created lazily by the `decide` primitive on its first record. Carries no `spec_stage`, no `review_active` — it never enters review | **No** | No | No — not stage-bearing, not gated |

A file that violates its role (e.g., source URL in a `design` file) is a hard violation caught by `lazy-spec.audit`.

**Per-file stage vs gates.** A document carries a per-file `spec_stage` when its type's declaration says `stages: true`; among the shipped types that flag is set on `vision`, `system-vision`, `use-cases`, `design`, `system-design`, `bug`, `architecture`, `ui-design`, `system-tech`, `code-plan`, and `test-plan`, which therefore carry `spec_stage` (`empty | draft | approved | rejected | cancelled | deferred`; see [lifecycle](./lazy-spec.lifecycle-protocol.md) and `lazy-spec.set-stage`). `code-report` and `test-report` are authored docs too, but carry **no** `spec_stage` — they are append-only journals, never opted into review, and play no role in any gate precondition. `decisions` carries no `spec_stage` either, for the same reason — it is an append-only registry, never opted into review, and plays no role in any gate. The `status` role carries the asset's **flat gate booleans** instead (it is a folder marker, not an authored doc) — see [lifecycle](./lazy-spec.lifecycle-protocol.md).

**Path constraints.** `status` files are only permitted at an asset folder-note path (`<spec_path>/<category>/<slug>/<slug>.md`) — never at the product root. `bug` files are only permitted under `<spec_path>/bugs/<slug>/`. `architecture` and `ui-design` files are only permitted under a `features/<slug>/` or `changes/<slug>/` asset folder — NEVER under `bugs/<slug>/`; `use-cases` files are additionally permitted loose at the product root and at the content-root, and still NEVER under `bugs/<slug>/`; `vision` files follow the same three levels — asset folders per the type's `vision` contract, the product root, and the content-root — and are NEVER under `bugs/<slug>/`. `design.md`, and the opt-in `use-cases.md` / `architecture.md` / `ui-design.md` / `code-plan.md` / `code-report.md` / `test-plan.md` / `test-report.md` / `decisions.md`, live in an asset folder; the product-level `vision.md` + `design.md` + `tech.md` + opt-in `use-cases.md` + `decisions.md` are loose at the product root; the project-wide `vision.md` + `design.md` + `tech.md` + opt-in `use-cases.md` + `decisions.md` are loose at the content-root and are the ONLY spec docs legal there — an asset-typed doc at the content-root is a defect.

### Removed roles

The following roles no longer exist — do not author them, do not reference them:

- **`layout`** — there is no Excalidraw layout doc/role.
- **`human-tasks`** — there is no plugin-managed human-attention dashboard.
- **`*-index`** (`spec-index`, `features-index`, `changes-index`, `bugs-index`, `requests-index`, `backlog-index`) — container index dataview is **operator-zone**, not a plugin role. The plugin defines no `*-index` role.

### Operator-zone folder-notes carry no `spec_role`

Category and group folder-notes (`features/features.md`, `<spec_path>/<category>/<category>.md`, …) are **operator-zone** — same-name-as-folder folder-notes the plugin does not own. They carry **NO `spec_role`** key. The plugin writes only the managed `iconize_icon` / `iconize_color` keys (and reads a category folder-note's `description`); their bodies are operator-owned. See [layout](./lazy-spec.layout-protocol.md) Part 1.

Three same-name-as-folder folder-notes DO carry a `spec_role`: the asset status folder-note (`spec_role: status`), the product-root level note (`spec_role: product`), and the catalog-root level note (`spec_role: catalog`). The product root was operator-zone before the level coordinator existed; it is now a plugin-owned note whose `# Coordinator rules` and `# Summary` stay operator-authored inside a plugin-owned shape — `lazycortex-specs catalog-note backfill` is what brings an older one across, adding what it lacks and rewriting nothing.

### Request files

A request file (`<content-root>/requests/<slug>.md`) is free-form user intake captured before classification. It is governed by [request-format](./lazy-spec.request-protocol.md) (its own `request_*` frontmatter and lifecycle); it is not part of the `spec_role` closed set.

### Upstream unit notes

A unit note (`<repo-root>/upstream/<repo-key>/<mount>/<unit-path>/<unit-slug>.md`) carries `spec_role: upstream-unit` — declared the same way `request` is above: a recognised `spec_role` value living outside the closed fifteen in § Roles, with its own frontmatter and lifecycle documented in [config-protocol](./lazy-spec.config-protocol.md) Part 5, not the quartet-role table above. Unlike every other folder documented here, the `upstream/` mirror tree is a sibling of the content-root at the repository root, not a subtree of it — a mirrored external source is not vault content until Phase C's request accepts it in.

### Attachments

An **attachment** is any file in an asset folder that is neither one of the canonical authored docs nor the status folder-note — a mockup, a diagram, a stylesheet, a data file, an additional prose chapter. It is created by the expert writing the document it belongs to, directly in the worktree, and it rides on that job's own commit. Like `request` and `upstream-unit` above, it lives outside the closed fifteen `spec_role` values and carries no `spec_role` of its own.

**Placement.** Flat in the asset folder (`<spec_path>/<category>/<slug>/`), beside the documents — see [layout](./lazy-spec.layout-protocol.md) Part 1.

**Naming.** Free. Nothing keys off an attachment's basename.

**A markdown attachment carries two authored frontmatter keys**, both written by the creating expert at creation time, plus one derived key nobody authors:

| Key | Value | What it decides |
|-----|-------|-----------------|
| `spec_owner_doc` | basename of a sibling document, e.g. `design.md` | Who owns the file: only the job whose own result document is that owner may write to it. It also marks the file as not participating in the asset's gates. |
| `spec_doc_type` | a declared type name — see § Document type | What kind of document the file is: its review class and its stage rules, resolved exactly as for any other typed document. |
| `spec_stage` | mirror of the owner's `spec_stage` | Derived, never authored: an attachment has no lifecycle of its own, so its stage (and the `spec/<stage>` mirror tag) always copies the owner's. Written by `lazy-spec.set-stage`'s cascade on every owner stage change and by the coordinator's reconciliation; the one exception is an attachment in its own review (`review_active: true`), which nobody writes until the review finalizes — the coordinator re-stamps it on the wake that finalize raises. The attachment's own review verdict lives only in `review_result` and never feeds its stage. |

The authored two record different facts and are not one fact under two names. A document with a type and no owner is an ordinary asset document; a document with both is an attachment; a document with an owner and no type is a defect the coordinator escalates. `lazy-spec.set-stage` refuses an attachment as a direct target — the mirror has exactly two writers, the cascade and the coordinator.

**A non-markdown attachment carries no frontmatter at all**, so there is nowhere in the file to record who owns it. Its ownership is recorded instead by the coordinator, in the status folder-note's `# Attachments` section — see [status-note](./lazy-spec.status-note-protocol.md) Part 4.

## Part 3 — File naming, header section, wikilinks

### File naming

Filenames are **role-only** — a plugin-owned spec doc's basename is its role, nothing else — with two folder-note exceptions (status + operator folder-notes carry the parent folder's name) and the request slug exception:

| Role | Filename | Allowed under |
|------|----------|---------------|
| `vision` | `vision.md` | content-root (mandatory vault spec), product root `<spec_path>/` (seeded at product creation), or an asset folder per the type's `vision` contract — never on a bug |
| `use-cases` | `use-cases.md` | content-root, product root `<spec_path>/`, `<spec_path>/features/<slug>/`, or `<spec_path>/changes/<slug>/` — opt-in requirements-scenario doc at every level, never on a bug |
| `design` | `design.md` | content-root (project-wide, type `system-design`), product root `<spec_path>/` (product-level, type `system-design`), `<spec_path>/<category>/<slug>/` (any category except `bugs`; type `design`) |
| `architecture` | `architecture.md` | `<spec_path>/features/<slug>/` or `<spec_path>/changes/<slug>/` ONLY — opt-in code-structure doc, never on a bug |
| `ui-design` | `ui-design.md` | `<spec_path>/features/<slug>/` or `<spec_path>/changes/<slug>/` ONLY — opt-in interface doc, never on a bug |
| `tech` | `tech.md` | content-root (project-wide) or product root `<spec_path>/` — always type `system-tech` |
| `bug` | `bug.md` | `bugs/<slug>/` (bug-report doc; bugs omit design/tech/architecture) |
| `code-plan` | `code-plan.md` | `<spec_path>/<category>/<slug>/` (opt-in asset-level implementation plan) |
| `test-plan` | `test-plan.md` | `<spec_path>/<category>/<slug>/` (opt-in asset-level functional test plan) |
| `code-report` | `code-report.md` | `<spec_path>/<category>/<slug>/` (opt-in append-only execution journal) |
| `test-report` | `test-report.md` | `<spec_path>/<category>/<slug>/` (opt-in append-only execution journal) |
| `status` | `<slug>.md` (matches parent asset folder name) | `<spec_path>/<category>/<slug>/` |
| `decisions` | `decisions.md` | content-root (project-level), product root `<spec_path>/` (product-level), `<spec_path>/<category>/<slug>/` (asset-level) — opt-in, never scaffolded, lazily created by the `decide` primitive |
| operator folder-note | `<product>.md` / `<category>.md` (matches parent folder name) | product root / category folder root |
| request | `<slug>.md` | `<content-root>/requests/` (vault-wide inbox) |

- No scope suffix, no name prefix, no underscores. `design.md` is just `design.md` everywhere.
- **Exception: the `status` role uses a filename matching its parent asset folder** — `features/chapter-log/chapter-log.md`, `changes/rename-chapter-log/rename-chapter-log.md`. This is the Obsidian folder-note convention: clicking the folder opens this file, and the file itself is hidden in the file tree. An asset folder without its status folder-note has no lifecycle state — `lazy-spec.audit` flags it.
- **Exception: operator folder-notes also use the folder-note convention** — `<spec_path>/<product>.md`, `features/features.md`, `<spec_path>/<category>/<category>.md`. The filename matches the parent folder. These carry NO `spec_role` (operator-zone) and only the managed `iconize_*` keys (plus `description` on category folder-notes) — see Part 2.
- **Exception: an attachment's filename is free.** An attachment is not a role-bearing document — it carries `spec_owner_doc` and `spec_doc_type` instead of a `spec_role`, and nothing reads its basename. See Part 2 § Attachments.
- **Exception: the `request` role uses a user-controlled `<slug>.md` filename.** Requests have no per-folder identity, so the slug IS the identity. Slugs are lowercase-with-hyphens, globally unique across the content-root `requests/` inbox. See [request-format](./lazy-spec.request-protocol.md).
- Folder names carry identity: category folders and asset folders use lowercase-with-hyphens; the same is recommended for product folders (the plugin reads no meaning from folder names above `spec_path`).
- **Reserved product slugs.** A product folder MUST NOT be named `vision`, `design`, `tech`, `use-cases`, or `decisions`: its folder-note (`<product>.md`) would then collide with the product-level docs of those names that sit loose at the product root. `lazy-spec.audit` flags a product slug in this reserved set.
- Basenames intentionally collide across the vault (every feature and every change has a `design.md`). Collisions are disambiguated by path (in file references) and by the in-file header section (when reading).

### Header section (mandatory in every authored spec doc)

Because filenames are role-only, every authored spec doc carries a structured body header identifying its product / asset and role. Skills generate this header when they create a file; `lazy-spec.audit` enforces it.

**Frontmatter fields** (the keys the plugin reads / writes):

| Field | Applies to | Value |
|-------|-----------|-------|
| `tags` | every file | list of tag paths (includes the product tag + the `spec/<stage>` mirror for stage-bearing docs) |
| `spec_role` | every plugin-owned spec doc | one of the closed set of fifteen in § Roles: `vision`, `use-cases`, `design`, `architecture`, `ui-design`, `code-plan`, `test-plan`, `code-report`, `test-report`, `bug`, `tech`, `decisions`, `status`, `product`, `catalog`. Operator-zone folder-notes carry NO `spec_role` — see Part 2 |
| `spec_stage` | stage-bearing authored docs (`vision`, `system-vision`, `use-cases`, `design`, `system-design`, `architecture`, `ui-design`, `code-plan`, `test-plan`, `bug`, `system-tech`) | per-file lifecycle stage, one of `empty | draft | approved | rejected | cancelled | deferred`; mirrored to a `spec/<stage>` tag. See [lifecycle](./lazy-spec.lifecycle-protocol.md). `code-report` / `test-report` / `decisions` carry NO `spec_stage` |
| `spec_design_done` | `status` files only | bool gate — see [lifecycle](./lazy-spec.lifecycle-protocol.md) |
| `spec_plan_done` | `status` files only | bool gate |
| `spec_develop_done` | `status` files only | bool gate |
| `spec_tests_passing` | `status` files only | bool gate |
| `spec_released` | `status` files only | bool gate |
| `spec_cancelled` | `status` files only | bool — terminal overlay freezing all gates |
| `spec_source_requests` | every stage-bearing authored doc (`vision`, `system-vision`, `use-cases`, `design`, `system-design`, `architecture`, `ui-design`, `code-plan`, `test-plan`, `bug`, `system-tech`) AND `status` folder-notes | per-doc subset on authored docs / asset-wide union on the folder-note. List of path-qualified wikilinks to request files that contributed (`[]` when created directly). Forward-only; the reverse link lives in the request body. The body's `# Sources` section is a projection of this key — see [sources](./lazy-spec.sources-protocol.md) Part 1. `code-report` / `test-report` carry neither key — they are execution journals, not sourced deliverables |
| `spec_source_docs` | every stage-bearing authored doc | per-doc list of path-qualified wikilinks to companion reference documents. See [sources](./lazy-spec.sources-protocol.md) Part 1 |
| `spec_source_branches` | `system-tech`, `code-plan`, and `test-plan` only (when applicable) | per-repo branch pins — see [sources](./lazy-spec.sources-protocol.md) Part 2 |
| `iconize_icon` | every folder-note (product / category / asset status) | managed iconize identifier the plugin writes from config — see [layout](./lazy-spec.layout-protocol.md) Part 1 |
| `iconize_color` | product roots, intake shelves, and asset status folder-notes — never an ordinary group folder-note | managed iconize color the plugin writes from config — see [config](./lazy-spec.config-protocol.md) § Container colour |
| `description` | category folder-notes only | operator-authored prose explaining the category; the plugin only READS it |
| `wiki_pinned_topics` | files written by a template-rendering site (`scaffold_asset.py`, `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`), the `pins` verb, and `decisions.md` (written by the `decide` primitive at creation) | list of `wiki/<axis>/<value>` tag paths pinning the file's `doc-kind` (and, on asset-level files, `product` / `category`) axis values so the wiki curator's classification never overrides them. Wiki reads this key only — it never writes it |

Request files carry their own `request_*` frontmatter (see [request-format](./lazy-spec.request-protocol.md)), not the keys above.

**Body header**: immediately after frontmatter, every authored doc starts with:

```markdown
# <Title> — <role>
```

- `<Title>` is the display name — the product name, asset slug, or status name depending on role.
- There is NO breadcrumb line — that form is removed. Ancestry is carried by the file's path and frontmatter, not by a body line.
- Body content follows.

Example for `Server/Tester/chapter/features/chapter-log/design.md`:

```markdown
---
tags:
  - tester/chapter
  - spec/draft
spec_role: design
spec_stage: draft
spec_source_requests: []
---

# chapter-log — design

## Summary
…
```

### Wikilinks

All inter-doc references MUST use **path-qualified** wikilinks with explicit display text:

```
[[<path/relative/to/vault/root/without/.md>|<display text>]]
```

- Paths are relative to the vault root. No leading slash.
- Display text is required — it's what the reader sees.
- Bare wikilinks like `[[design]]` or `[[code-plan]]` are FORBIDDEN because role-only basenames collide by design (every feature has a `design.md`). `lazy-spec.audit` flags any bare wikilink that resolves ambiguously.

Examples:

- `[[Server/Tester/chapter/design|chapter design]]`
- `[[Server/Tester/chapter/features/chapter-log/design|chapter-log design]]`
- `[[Server/Tester/chapter/features/chapter-log/code-plan|chapter-log code-plan]]`
- `[[Server/Tester/chapter/changes/rename-chapter-log/design|rename-chapter-log design]]`

Asset folder names are NOT required to be globally unique across products — the wikilink path disambiguates them. Request slugs, by contrast, are globally unique across the single content-root `requests/` inbox.

