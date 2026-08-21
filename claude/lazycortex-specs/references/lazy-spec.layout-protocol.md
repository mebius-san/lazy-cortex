---
name: lazy-spec.layout-protocol
version: 4
description: Physical disk layout for spec assets — folder kinds, the closed set of file roles, naming conventions, and the asset status folder-note body shape.
---
# Layout protocol — folder structure, file roles, naming, status-file shape

Physical disk layout, the closed set of file roles, naming conventions, and the asset status folder-note's body shape — one contract because they're inseparable in practice (a doc's path determines its role determines its allowed content determines its body header).

## Part 1 — Folder structure

### Folder kinds

**Spec content-root.** All spec content lives under `<settings-dir>/<spec.vault_root>` (default `specs`), where `<settings-dir>` is the directory that holds `.claude/lazy.settings.json` (the repo root). The operator's top-level folders, the content-root `requests/` inbox, and the optional **project-wide spec pair** — a loose `design.md` + `tech.md` describing the whole project above every product, typed `system-design` / `system-tech` — are direct children of the content-root. No config key declares the project-wide pair: the files' existence is the declaration, and their absence means the project level simply does not exist yet. Vault-relative paths (`spec_path`, wikilinks, tags) are relative to this content-root, not to `<settings-dir>`. See [config](./lazy-spec.config-protocol.md) for the `spec.vault_root` setting.

Two kinds of folders exist under the content-root:

1. **Organizational folders** — everything above a product folder. Their names, nesting, and depth are the operator's own: the plugin dictates no form and derives no meaning from a path segment — a product's identity lives in its `products[<key>]` record and its files' frontmatter, never in where it sits. A product folder may also sit directly at the content-root, with no organizational folders above it.
2. **Product folders** — the folder a registered product's `spec_path` points at (lowercase-with-hyphens recommended for the folder name). A product folder owns the category subdirectories below; the only loose files at the product folder level are the product folder-note (see "Folder-notes" below), the two product-level docs `design.md` + `tech.md`, and the opt-in `decisions.md`:
   - `design.md` + `tech.md` — the product-level docs, loose at the product root (NOT in a subfolder), typed `system-design` / `system-tech` (`spec_role` stays `design` / `tech`). There is no per-product `docs/` or `spec/` subfolder — the system itself is called "spec", so product-level reference material sits directly at the product root alongside the folder-note. Because the folder-note basename is `<product>.md`, a product slug of `design` or `tech` would collide with these docs and is therefore forbidden (see Part 3 naming).
   - `decisions.md` — the product-level decisions registry, loose at the product root. Opt-in and lazily created: it exists only once the `decide` primitive writes a product-level record into it. Its absence is never a defect. No `spec_stage`, no review — see Part 2.
   - **group folders** — one per asset type whose assets exist, named by the type's `default_path`: the shipped `features/` / `changes/` / `bugs/` and every operator-declared type's folder (e.g. `characters/`, `scenes/`) follow ONE rule. The folder is a place, not a fact: an asset's kind is the `spec_asset_type` key on its own status folder-note, and the folder is created lazily by the first `scaffold-asset` call that lands an asset in it — nothing pre-creates an empty group folder, and a product using no changes has no `changes/`. On that first landing the scaffold also seeds the group folder-note `<folder>/<folder>.md` when none exists: an operator-zone note (protected `# Summary` skeleton, `iconize_icon` from the type's declaration and no `iconize_color` at all — an ordinary container is colourless per [config](./lazy-spec.config-protocol.md) § Container colour, NO `spec_role`) whose body below the skeleton is the operator's; an already-present note is never touched, and an asset scaffolded inside another asset's folder seeds nothing (the enclosing folder's own status note is its folder-note). A bug folder carries `bug.md` (the report: summary, repro steps, observed vs expected) plus the opt-in `code-plan.md` / `code-report.md` / `test-plan.md` / `test-report.md` quartet; it has NO `design.md`, NO `tech.md`, and NO `architecture.md` — a bug fix is never judged code-bearing enough to need one (`lazy-spec.coordination-playbook.md` Chapter 3).

**The request inbox is NOT a product category.** A single `requests/` folder at the **content-root** (a direct child of the content-root, never under a product `spec_path`) holds all free-form intake for the whole vault — one `<slug>.md` per request. A request may target multiple products, so per-product placement would force duplication; classification routes it to the right product/entity. Full lifecycle + frontmatter contract live in [request-format](./lazy-spec.request-protocol.md).

There is **no `backlog/` folder** (removed), **no `human-tasks.md` loose file** (removed — there is no plugin-managed human-attention dashboard; container index dataview is operator-zone), and **no `changelog.md` loose file** (removed — history is recorded per-doc via `# History` H1 sections written by lazy-review.coordinator, and per-asset via the status folder-note's `# History` H1 section written by `lazy-spec.flip-gate` / `lazy-spec.set-stage`. There is no separate product-wide changelog).

**A product folder MUST NOT contain another product folder.** Group related sibling products under a shared organizational parent folder instead.

### Asset types — shipped + operator-defined

Asset types are an **open set**, declared rather than enumerated. Two layers declare:

- **Shipped**: the plugin, in `references/lazy-spec.asset-types.json` — `feature`, `change`, `bug`, `content`, `research`, with default paths `features/` / `changes/` / `bugs/` / `content/` / `research/`.
- **Operator-defined**: a product, under `products[<key>].asset_types` in `.claude/lazy.settings.json` — merged over the shipped set key-by-key, so a product may replace one field of a shipped type without restating the rest.

A declaration carries `{ icon, color?, playbook, alias_of?, default_path?, start_doc, default_tools? }`. `start_doc` is the `"<file>:<doc_type>"` token naming the one document a fresh asset of the type is seeded with; `playbook` is the reference `spec.coordinator` loads on every wake of an asset of the type; `alias_of` names a base type whose playbook this one borrows when it declares none of its own — the folder, icon, colour, start document and tools stay the alias's own, and aliases never chain.

A type declared via `/lazy-spec.add-asset-type` is recognised by `lazy-spec.create-asset`, `lazy-spec.request-classify`, the coordinator, and the review daemon on their next run without a rubric or code edit. The skill writes the declaration and nothing else: **no folder is created on disk**, no folder-note is rendered, and no templates are seeded — the type's folder appears the first time an asset of it is scaffolded, and the operator-zone folder-note is theirs to author. Its design / code-plan / test-plan docs are covered by the shared behavior-keyed review classes (right-anchored `*/design.md` / `*/code-plan.md` / `*/test-plan.md` globs) — no per-type class is created.

An asset folder is `<spec_path>/<folder>/<slug>/`, where `<folder>` is the type's `default_path` unless the caller named another location. Assets may nest: an asset's boundary is the folder whose folder-note carries `spec_role: status`, so a folder sitting inside another asset's folder is its own asset all the same. It holds:

- the status folder-note `<slug>.md` (`spec_role: status`, flat gates, `spec_asset_type` — see Part 4 and [lifecycle](./lazy-spec.lifecycle-protocol.md));
- the document named by the type's `start_doc` — `design.md` for the shipped `feature` / `change` / `content` / `research` types, `bug.md` for `bug`. There is no default layout: a type with no `start_doc` cannot be scaffolded at all;
- optionally `architecture.md` — feature/change layout only, NEVER on a bug; opt-in on disk the same way as `code-plan.md` / `test-plan.md`, but its existence tracks a coordinator judgment (code-bearing asset) rather than free operator choice — see [coordination-playbook](./lazy-spec.coordination-playbook.md) Chapter 3 and Chapter 8;
- optionally `code-plan.md` and/or `test-plan.md` — opt-in, scaffolded only when explicitly authored, never seeded by `lazy-spec.create-asset`;
- optionally `code-report.md` and/or `test-report.md` — opt-in append-only execution journals, carrying no `spec_stage` and no role in any gate;
- optionally `decisions.md` — opt-in append-only registry of accepted decisions for this asset, never scaffolded, created lazily by the `decide` primitive on its first record; carries no `spec_stage` and plays no role in any gate or review.

There is no per-asset `tech.md` (only the product carries `tech.md` at its root) and no `layout` doc.

### Folder-notes — at every folder

Every folder in the tree carries a folder-note (the Obsidian convention: a note whose basename matches the parent folder; clicking the folder opens it). Three flavours:

| Folder | Folder-note | Kind |
|--------|-------------|------|
| product `<spec_path>/` | `<product>.md` | operator-zone (no `spec_role`) |
| asset-type folder `<spec_path>/<folder>/` | `<folder>/<folder>.md` | operator-zone (no `spec_role`) |
| content-root request inbox `requests/` | `requests/requests.md` | operator-zone (no `spec_role`) |
| asset `<spec_path>/<folder>/<slug>/` | `<slug>.md` | status (`spec_role: status`, flat gates) |

#### Managed icon frontmatter + type description

The plugin WRITES two managed keys into folder-notes from config — `iconize_icon` and `iconize_color` (the Obsidian iconize system paints the folder from these). Every folder-note gets the icon; which of them get a colour is the three-tier container rule in [config](./lazy-spec.config-protocol.md) § Container colour — a product root takes the neutral `#64748b`, the intake shelves (request inbox, upstream notes) take the `#f0abfc` accent, and an ordinary group folder-note carries no colour key at all.

The icon values come from `products[<key>].icon` for a product folder-note, and from `asset_types[<name>].icon` for an asset-type folder-note (the shipped types carry theirs in `references/lazy-spec.asset-types.json`: `feature` → `LiRocket`, `change` → `LiRefreshCcw`, `bug` → `LiBug`, `content` → `LiShapes`, `research` → `LiFlaskConical`; the content-root request inbox folder-note defaults to `LiInbox`). For an asset status folder-note both keys come from the asset's own type declaration — `asset_types[<name>].icon` / `.color` — injected at scaffold time; that type colour reaches the asset, never the group folder named by the same type's `default_path`.

An asset-type folder-note may also carry a `description` frontmatter key — the operator's prose explanation of what the folder holds. The plugin **only READS** `description` (and the operator-owned body); it never overwrites operator text. The type's own human explanation is not this key and not any config field — it is the opening chapter of the type's playbook.

#### Operator-zone folder-note bodies

Product and asset-type folder-note **bodies are operator-zone**: the plugin does not manage them. They carry NO `spec_role`, NO `*-index` role, and NO plugin-managed dataview. The body is a single `# <name>` H1 plus operator-owned prose (a scaffold seeds a one-line HTML comment marking the body operator-owned). If an operator wants a container dashboard (a dataviewjs listing of the assets under that folder), they author it themselves — it is their content, outside the plugin's contract.

### Template storage (per-file + per-product)

Doc templates come from a **linear per-doc-type base** plus **per-asset-type specialisations**. `spec.docs/` holds one template per shipped document type and serves every asset type; a `spec.<type>/` folder carries only the structural notes that asset type owns (`asset-note.md`, `group-note.md`) plus the doc templates that genuinely diverge from the base. An asset type needs no template of its own to scaffold a document — the bases cover it — and an edit to a specialisation never affects another type:

```
.claude/templates/
├── spec.docs/                                   ← LINEAR BASE: one template per shipped doc type, serves every asset type
│   ├── design.md
│   ├── architecture.md
│   ├── code-plan.md
│   ├── test-plan.md
│   ├── code-report.md
│   ├── test-report.md
│   ├── bug.md
│   └── tech.md
├── spec.product/                                ← product-level docs (at the product root)
│   ├── design.md                                ← specialisation: <product>/design.md diverges from the base
│   └── group-note.md                            ← <product>.md operator folder-note (product is the "group" of its asset types)
├── spec.feature/                                ← shipped feature type — no doc specialisations, rides the base
│   ├── asset-note.md                            ← <slug>/<slug>.md asset status folder-note (gates + # History)
│   └── group-note.md                            ← features/features.md type folder-note (operator-zone)
├── spec.change/                                 ← shipped change type
│   ├── design.md                                ← specialisation
│   ├── architecture.md                          ← specialisation
│   ├── code-plan.md                              ← specialisation
│   ├── asset-note.md
│   └── group-note.md                            ← changes/changes.md type folder-note
├── spec.bug/                                    ← shipped bug type (its `start_doc` seeds `bug.md`, not `design.md`)
│   ├── code-plan.md                              ← specialisation
│   ├── asset-note.md
│   └── group-note.md                            ← bugs/bugs.md type folder-note
├── spec.request/                                ← content-root intake inbox
│   ├── request.md                               ← <slug>.md request file (single-file, NOT a folder-note)
│   └── group-note.md                            ← <content-root>/requests/requests.md inbox folder-note
└── spec.asset/                                  ← TYPE-AGNOSTIC BASE: what a type with no folder of its own falls back on
    └── asset-note.md                            ← <slug>/<slug>.md asset status folder-note (gates + # History)
```

Naming convention inside an asset-type template folder:

- **`group-note.md`** — the folder-note for the type's COLLECTION folder (the `<folder>/` itself, e.g. `features/features.md`). Operator-zone — plugin writes only the managed `iconize_*` keys.
- **`asset-note.md`** — the folder-note for each individual ASSET folder (`<slug>/<slug>.md`). Carries `spec_role: status`, gates, `# Gates`, `# History`. Plugin-managed.
- The named docs (`design.md`, `bug.md`, `tech.md`, `code-plan.md`, `test-plan.md`, `code-report.md`, `test-report.md`) — authored content the operator + lazy-review experts fill in.

**An operator-defined type ships no template folder, and none is seeded for it.** `/lazy-spec.add-asset-type` writes the type's declaration and stops — it copies no files into `.claude/templates/spec.<name>/`. A type with no folder of its own resolves every document from the plugin's linear base (`spec.docs/`) and its status folder-note from the type-agnostic base (`spec.asset/`), which is why a type needs no template to be scaffoldable. An operator who wants a specialisation creates `.claude/templates/spec.<name>/` by hand and drops in the files to override — the resolver picks them up on the next scaffold, with no registration step.

Diagram exemplars are owned by the `lazycortex-diagram:lazy-diagram.draw` engine (shipped by the lazycortex-diagram plugin). Per-product diagram-exemplar overrides live under whatever directory a caller passes to the drawer via `exemplar_override_dir`.

**Template resolution (5-layer fallback).** When `lazy-spec.create-asset` scaffolds an asset, it resolves each template file in this order, first hit wins:

1. **Per-product override** — `.claude/templates/spec.<type>/<compound-key>/<file>.md` (operator-authored variant for one specific product; compound-key matches the product's settings key).
2. **Consumer type baseline** — `.claude/templates/spec.<type>/<file>.md` (the type-level baseline in the consumer vault — where an operator's own specialisations live, for a shipped type and an operator-defined one alike).
3. **Plugin type baseline** — `${CLAUDE_PLUGIN_ROOT}/templates/spec.<type>/<file>.md` (the plugin-shipped per-type specialisation; exists only where a shipped type genuinely diverges from the bases). Absent for operator-defined types, and for most shipped doc templates too — layers 4 and 5 cover them.
4. **Plugin linear base** — `${CLAUDE_PLUGIN_ROOT}/templates/spec.docs/<file>.md`, one template per shipped document type. Any per-type or per-product override of the same filename still wins over it; it exists so a type needs no doc template of its own.
5. **Plugin type-agnostic base** — `${CLAUDE_PLUGIN_ROOT}/templates/spec.asset/<file>.md`, the structural notes (`asset-note.md`) that are byte-identical across types. The LAST layer.

When the type declares an `alias_of`, the base type's own three layers (1–3) are consulted after the alias's own three and before layer 4 — an alias-local template outranks every base layer, not only the layer matching its own.

There is no settings field for this — folder + file presence is the single signal at each layer.

### Generic Layout

All products follow this shape. No concrete names appear in this rule — skills discover products at runtime from the `products` section of `.claude/lazy.settings.json` (see [config](./lazy-spec.config-protocol.md) for product registration).

```
<settings-dir>/                              ← repo root (holds .claude/lazy.settings.json)
└── specs/                                   ← content-root (<spec.vault_root>, default "specs")
    ├── design.md                            ← optional — project-wide design (system-design), loose at the content-root
    ├── tech.md                              ← optional — project-wide tech (system-tech), loose at the content-root
    ├── <operator folders…>/                 ← free-form organizational nesting, operator's own (any depth, or none)
    │   └── …/
    │       └── <product>/                   ← product folder (root of the product's spec_path)
    │           ├── <product>.md             ← product folder-note (operator-zone; managed iconize_icon)
    │           ├── design.md                ← product-level design (loose at product root)
    │           ├── tech.md                  ← product-level tech (loose at product root)
    │           ├── decisions.md              ← opt-in — product-level decisions registry, lazily created
    │           ├── features/
    │           │   ├── features.md          ← category folder-note (operator-zone; managed iconize_icon)
    │           │   └── <slug>/              ← feature asset folder
    │           │       ├── <slug>.md        ← status folder-note (spec_role: status, flat gates)
    │           │       ├── design.md
    │           │       ├── code-plan.md      ← opt-in — present only when authored
    │           │       ├── code-report.md    ← opt-in — present only when authored
    │           │       ├── test-plan.md     ← opt-in — present only when authored
    │           │       ├── test-report.md   ← opt-in — present only when authored
    │           │       └── decisions.md     ← opt-in — asset-level decisions registry, lazily created
    │           ├── changes/
    │           │   ├── changes.md           ← category folder-note (operator-zone)
    │           │   └── <slug>/              ← change asset folder
    │           │       ├── <slug>.md        ← status folder-note
    │           │       ├── design.md
    │           │       ├── code-plan.md      ← opt-in
    │           │       ├── code-report.md    ← opt-in
    │           │       ├── test-plan.md     ← opt-in
    │           │       ├── test-report.md   ← opt-in
    │           │       └── decisions.md     ← opt-in — lazily created
    │           ├── bugs/
    │           │   ├── bugs.md              ← category folder-note (operator-zone)
    │           │   └── <slug>/              ← bug asset folder
    │           │       ├── <slug>.md        ← status folder-note
    │           │       ├── bug.md           ← report: summary, repro steps, observed vs expected
    │           │       ├── code-plan.md      ← opt-in fix plan (no design.md, no tech.md)
    │           │       ├── code-report.md    ← opt-in
    │           │       ├── test-plan.md     ← opt-in
    │           │       ├── test-report.md   ← opt-in
    │           │       └── decisions.md     ← opt-in — lazily created
    │           └── <folder>/                ← an asset type's folder (its `default_path` under `asset_types`)
    │               ├── <category>.md        ← category folder-note (operator-zone; description + managed iconize_icon)
    │               └── <slug>/              ← asset folder
    │                   ├── <slug>.md        ← status folder-note
    │                   ├── design.md
    │                   ├── code-plan.md      ← opt-in
    │                   ├── code-report.md    ← opt-in
    │                   ├── test-plan.md     ← opt-in
    │                   ├── test-report.md   ← opt-in
    │                   └── decisions.md     ← opt-in — lazily created
    └── requests/                            ← vault-wide free-form intake (direct child of the content-root)
        ├── requests.md                      ← inbox folder-note (operator-zone; managed iconize_icon, default LiInbox)
        └── <slug>.md                        ← request file (lifecycle in lazy-spec.request-protocol.md)
```

The request inbox is a direct child of the content-root — never inside any product or operator folder.

An asset folder of any category may additionally hold **attachments** — files an expert created beside the document it was writing (a mockup, a diagram, a data file, an extra prose chapter). They are not drawn in the tree above because they carry no fixed names, and they sit **flat in the asset folder**, beside the documents. There is no attachments subfolder, and no other legal location. See Part 2 § Attachments for what an attachment is and which keys it carries.

## Part 2 — File roles

### Document type

A document's **type** is the `spec_doc_type` frontmatter key, and the set of legal values is **open**, declared rather than enumerated. Two layers declare:

- the plugin, in `references/lazy-spec.doc-types.json` — nine shipped types;
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
- **`spec_role` is not replaced by this.** It remains the role/placement key — the status folder-note is `spec_role: status` and has no type at all, and the pins, decisions, and path checks still read it. A document carrying both keys must have them agree; agreement is by family, not literal equality — role `design` agrees with types `design` AND `system-design`, role `tech` agrees with type `system-tech`, every other shipped type agrees only with the role of its own name.

### Roles

The `spec_role` frontmatter key is a **closed set** of ten values: `design`, `architecture`, `code-plan`, `code-report`, `test-plan`, `test-report`, `bug`, `tech`, `status`, `decisions`. A plugin-owned spec doc carries exactly one of these. Role determines what content is allowed.

The last column records today's defaults only — the authority on whether a document carries `spec_stage` is the `stages` flag of its type's declaration, not this table.

| `spec_role` | Purpose | May contain source URLs? | May carry `spec_source_branches`? | Per-file `spec_stage`? (see the type's `stages` flag) |
|------|---------|--------------------------|------------------------------|-------------------|
| `design` | Behavior, requirements, user flow — WHAT the system does (feature/change/operator-defined-asset doc) | **No** | No | **Yes** |
| `architecture` | Opt-in code-structure design: module boundaries, dependency direction, public contract versus internals, data migration, cost to existing callers — the SHAPE of the code, not the behavior. Feature/change asset-level only, never on a bug. Mandatory once the coordinator judges the asset code-bearing (`lazy-spec.coordination-playbook.md` Chapter 3/8), same as `design` is mandatory once the category needs it | **No** | No | **Yes** |
| `tech` | Technical specification: architecture, source file map, components, data structures, reuse notes. System-level only (`tech.md` at a product root, or loose at the content-root as the project-wide spec; type `system-tech`) — no per-asset `tech.md` | **Yes** | **Yes** | **Yes** |
| `code-plan` | Opt-in development plan: scope, sequence, implementation notes for the developer. Populated once `design.md` is approved | **Yes** | **Yes** | **Yes** |
| `test-plan` | Opt-in functional test plan: verifies behavior against the design. Populated by the tester expert from the approved design; unit tests belong to the developer, not here | **Yes** | **Yes** | **Yes** |
| `code-report` | Opt-in append-only working journal written during execution, never after the fact. Carries no `spec_source_branches` and no per-file stage — it is not reviewed or approved | No | No | **No** |
| `test-report` | Opt-in append-only working journal written during execution, never after the fact. Same no-stage, no-review contract as `code-report` | No | No | **No** |
| `bug` | Report doc for a bug: what's broken, repro steps, observed vs expected, environment, links to affected code / logs. No companion `design` or `tech` — a bug folder ships only `bug.md` plus whichever quartet members are opt-in-authored | **Yes** (only in the `## Related code / logs` section) | No | **Yes** |
| `status` | Asset folder-note: lifecycle state as flat gate booleans (`spec_design_done`…`spec_released` + `spec_cancelled`), `# Gates` callouts (H1), `# History` log (H1). See [lifecycle](./lazy-spec.lifecycle-protocol.md) | **No** | No | No — carries **gates**, not a per-file stage |
| `decisions` | Opt-in append-only registry of accepted decisions — product-level (`<spec_path>/decisions.md`) or asset-level (`<spec_path>/<category>/<slug>/decisions.md`). Never scaffolded; created lazily by the `decide` primitive on its first record. Carries no `spec_stage`, no `review_active` — it never enters review | **No** | No | No — not stage-bearing, not gated |

A file that violates its role (e.g., source URL in a `design` file) is a hard violation caught by `lazy-spec.doctor`.

**Per-file stage vs gates.** A document carries a per-file `spec_stage` when its type's declaration says `stages: true`; among the shipped types that flag is set on `design`, `system-design`, `bug`, `architecture`, `system-tech`, `code-plan`, and `test-plan`, which therefore carry `spec_stage` (`empty | draft | approved | rejected | cancelled`; see [lifecycle](./lazy-spec.lifecycle-protocol.md) and `lazy-spec.set-stage`). `code-report` and `test-report` are authored docs too, but carry **no** `spec_stage` — they are append-only journals, never opted into review, and play no role in any gate precondition. `decisions` carries no `spec_stage` either, for the same reason — it is an append-only registry, never opted into review, and plays no role in any gate. The `status` role carries the asset's **flat gate booleans** instead (it is a folder marker, not an authored doc) — see [lifecycle](./lazy-spec.lifecycle-protocol.md).

**Path constraints.** `status` files are only permitted at an asset folder-note path (`<spec_path>/<category>/<slug>/<slug>.md`) — never at the product root. `bug` files are only permitted under `<spec_path>/bugs/<slug>/`. `architecture` files are only permitted under a `features/<slug>/` or `changes/<slug>/` asset folder — NEVER under `bugs/<slug>/`. `design.md`, and the opt-in `architecture.md` / `code-plan.md` / `code-report.md` / `test-plan.md` / `test-report.md` / `decisions.md`, live in an asset folder; the product-level `design.md` + `tech.md` + opt-in `decisions.md` are loose at the product root (`<spec_path>/design.md`, `<spec_path>/tech.md`, `<spec_path>/decisions.md`); the project-wide `design.md` + `tech.md` are loose at the content-root and are the ONLY spec docs legal there (`system-design` / `system-tech` typed — an asset-typed doc at the content-root is a defect).

### Removed roles

The following roles no longer exist — do not author them, do not reference them:

- **`layout`** — there is no Excalidraw layout doc/role.
- **`human-tasks`** — there is no plugin-managed human-attention dashboard.
- **`*-index`** (`spec-index`, `features-index`, `changes-index`, `bugs-index`, `requests-index`, `backlog-index`) — container index dataview is **operator-zone**, not a plugin role. The plugin defines no `*-index` role.

### Operator-zone folder-notes carry no `spec_role`

Product and category folder-notes (`<spec_path>/<product>.md`, `features/features.md`, `<spec_path>/<category>/<category>.md`, …) are **operator-zone** — same-name-as-folder folder-notes the plugin does not own. They carry **NO `spec_role`** key. The plugin writes only the managed `iconize_icon` / `iconize_color` keys (and reads a category folder-note's `description`); their bodies are operator-owned. See Part 1 above.

The only same-name-as-folder folder-note that DOES carry a `spec_role` is the asset status folder-note (`spec_role: status`).

### Request files

A request file (`<content-root>/requests/<slug>.md`) is free-form user intake captured before classification. It is governed by [request-format](./lazy-spec.request-protocol.md) (its own `request_*` frontmatter and lifecycle); it is not part of the `spec_role` closed set.

### Upstream unit notes

A unit note (`<content-root>/upstream/<repo-key>/<mount>/<unit-path>/<unit-slug>.md`) carries `spec_role: upstream-unit` — declared the same way `request` is above: a recognised `spec_role` value living outside the closed ten in § 216, with its own frontmatter and lifecycle documented in [config-protocol](./lazy-spec.config-protocol.md) Part 5, not the quartet-role table above.

### Attachments

An **attachment** is any file in an asset folder that is neither one of the canonical authored docs nor the status folder-note — a mockup, a diagram, a stylesheet, a data file, an additional prose chapter. It is created by the expert writing the document it belongs to, directly in the worktree, and it rides on that job's own commit. Like `request` and `upstream-unit` above, it lives outside the closed ten `spec_role` values and carries no `spec_role` of its own.

**Placement.** Flat in the asset folder (`<spec_path>/<category>/<slug>/`), beside the documents — see Part 1.

**Naming.** Free. Nothing keys off an attachment's basename.

**A markdown attachment carries two authored frontmatter keys**, both written by the creating expert at creation time, plus one derived key nobody authors:

| Key | Value | What it decides |
|-----|-------|-----------------|
| `spec_owner_doc` | basename of a sibling document, e.g. `design.md` | Who owns the file: only the job whose own result document is that owner may write to it. It also marks the file as not participating in the asset's gates. |
| `spec_doc_type` | a declared type name — see § Document type | What kind of document the file is: its review class and its stage rules, resolved exactly as for any other typed document. |
| `spec_stage` | mirror of the owner's `spec_stage` | Derived, never authored: an attachment has no lifecycle of its own, so its stage (and the `spec/<stage>` mirror tag) always copies the owner's. Written by `lazy-spec.set-stage`'s cascade on every owner stage change and by the coordinator's reconciliation; the one exception is an attachment in its own review (`review_active: true`), which nobody writes until the review finalizes — the coordinator re-stamps it on the wake that finalize raises. The attachment's own review verdict lives only in `review_result` and never feeds its stage. |

The authored two record different facts and are not one fact under two names. A document with a type and no owner is an ordinary asset document; a document with both is an attachment; a document with an owner and no type is a defect the coordinator escalates. `lazy-spec.set-stage` refuses an attachment as a direct target — the mirror has exactly two writers, the cascade and the coordinator.

**A non-markdown attachment carries no frontmatter at all**, so there is nowhere in the file to record who owns it. Its ownership is recorded instead by the coordinator, in the status folder-note's `# Attachments` section — see Part 4.

## Part 3 — File naming, header section, wikilinks

### File naming

Filenames are **role-only** — a plugin-owned spec doc's basename is its role, nothing else — with two folder-note exceptions (status + operator folder-notes carry the parent folder's name) and the request slug exception:

| Role | Filename | Allowed under |
|------|----------|---------------|
| `design` | `design.md` | content-root (project-wide, type `system-design`), product root `<spec_path>/` (product-level, type `system-design`), `<spec_path>/<category>/<slug>/` (any category except `bugs`; type `design`) |
| `architecture` | `architecture.md` | `<spec_path>/features/<slug>/` or `<spec_path>/changes/<slug>/` ONLY — opt-in code-structure doc, never on a bug |
| `tech` | `tech.md` | content-root (project-wide) or product root `<spec_path>/` — always type `system-tech` |
| `bug` | `bug.md` | `bugs/<slug>/` (bug-report doc; bugs omit design/tech/architecture) |
| `code-plan` | `code-plan.md` | `<spec_path>/<category>/<slug>/` (opt-in asset-level implementation plan) |
| `test-plan` | `test-plan.md` | `<spec_path>/<category>/<slug>/` (opt-in asset-level functional test plan) |
| `code-report` | `code-report.md` | `<spec_path>/<category>/<slug>/` (opt-in append-only execution journal) |
| `test-report` | `test-report.md` | `<spec_path>/<category>/<slug>/` (opt-in append-only execution journal) |
| `status` | `<slug>.md` (matches parent asset folder name) | `<spec_path>/<category>/<slug>/` |
| `decisions` | `decisions.md` | product root `<spec_path>/` (product-level), `<spec_path>/<category>/<slug>/` (asset-level) — opt-in, never scaffolded, lazily created by the `decide` primitive |
| operator folder-note | `<product>.md` / `<category>.md` (matches parent folder name) | product root / category folder root |
| request | `<slug>.md` | `<content-root>/requests/` (vault-wide inbox) |

- No scope suffix, no name prefix, no underscores. `design.md` is just `design.md` everywhere.
- **Exception: the `status` role uses a filename matching its parent asset folder** — `features/chapter-log/chapter-log.md`, `changes/rename-chapter-log/rename-chapter-log.md`. This is the Obsidian folder-note convention: clicking the folder opens this file, and the file itself is hidden in the file tree. An asset folder without its status folder-note has no lifecycle state — `lazy-spec.doctor` flags it.
- **Exception: operator folder-notes also use the folder-note convention** — `<spec_path>/<product>.md`, `features/features.md`, `<spec_path>/<category>/<category>.md`. The filename matches the parent folder. These carry NO `spec_role` (operator-zone) and only the managed `iconize_*` keys (plus `description` on category folder-notes) — see Part 2.
- **Exception: an attachment's filename is free.** An attachment is not a role-bearing document — it carries `spec_owner_doc` and `spec_doc_type` instead of a `spec_role`, and nothing reads its basename. See Part 2 § Attachments.
- **Exception: the `request` role uses a user-controlled `<slug>.md` filename.** Requests have no per-folder identity, so the slug IS the identity. Slugs are lowercase-with-hyphens, globally unique across the content-root `requests/` inbox. See [request-format](./lazy-spec.request-protocol.md).
- Folder names carry identity: category folders and asset folders use lowercase-with-hyphens; the same is recommended for product folders (the plugin reads no meaning from folder names above `spec_path`).
- **Reserved product slugs.** A product folder MUST NOT be named `design`, `tech`, or `decisions`: its folder-note (`<product>.md`) would then collide with the product-level `design.md` / `tech.md` / `decisions.md` that sit loose at the product root. `lazy-spec.doctor` flags a product slug in this reserved set.
- Basenames intentionally collide across the vault (every feature and every change has a `design.md`). Collisions are disambiguated by path (in file references) and by the in-file header section (when reading).

### Header section (mandatory in every authored spec doc)

Because filenames are role-only, every authored spec doc carries a structured body header identifying its product / asset and role. Skills generate this header when they create a file; `lazy-spec.doctor` enforces it.

**Frontmatter fields** (the keys the plugin reads / writes):

| Field | Applies to | Value |
|-------|-----------|-------|
| `tags` | every file | list of tag paths (includes the product tag + the `spec/<stage>` mirror for stage-bearing docs) |
| `spec_role` | every plugin-owned spec doc | one of the closed set: `design`, `architecture`, `code-plan`, `test-plan`, `code-report`, `test-report`, `bug`, `tech`, `status`, `decisions`. Operator-zone folder-notes carry NO `spec_role` — see Part 2 |
| `spec_stage` | stage-bearing authored docs (`design`, `system-design`, `architecture`, `code-plan`, `test-plan`, `bug`, `system-tech`) | per-file lifecycle stage, one of `empty | draft | approved | rejected | cancelled`; mirrored to a `spec/<stage>` tag. See [lifecycle](./lazy-spec.lifecycle-protocol.md). `code-report` / `test-report` / `decisions` carry NO `spec_stage` |
| `spec_design_done` | `status` files only | bool gate — see [lifecycle](./lazy-spec.lifecycle-protocol.md) |
| `spec_plan_done` | `status` files only | bool gate |
| `spec_develop_done` | `status` files only | bool gate |
| `spec_tests_passing` | `status` files only | bool gate |
| `spec_released` | `status` files only | bool gate |
| `spec_cancelled` | `status` files only | bool — terminal overlay freezing all gates |
| `spec_source_requests` | every stage-bearing authored doc (`design`, `system-design`, `architecture`, `code-plan`, `test-plan`, `bug`, `system-tech`) AND `status` folder-notes | per-doc subset on authored docs / asset-wide union on the folder-note. List of path-qualified wikilinks to request files that contributed (`[]` when created directly). Forward-only; the reverse link lives in the request body. The body's `# Sources` section is a projection of this key — see [sources](./lazy-spec.sources-protocol.md) Part 1. `code-report` / `test-report` carry neither key — they are execution journals, not sourced deliverables |
| `spec_source_docs` | every stage-bearing authored doc | per-doc list of path-qualified wikilinks to companion reference documents. See [sources](./lazy-spec.sources-protocol.md) Part 1 |
| `spec_source_branches` | `system-tech`, `code-plan`, and `test-plan` only (when applicable) | per-repo branch pins — see [sources](./lazy-spec.sources-protocol.md) Part 2 |
| `iconize_icon` | every folder-note (product / category / asset status) | managed iconize identifier the plugin writes from config — see Part 1 |
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
- Bare wikilinks like `[[design]]` or `[[code-plan]]` are FORBIDDEN because role-only basenames collide by design (every feature has a `design.md`). `lazy-spec.doctor` flags any bare wikilink that resolves ambiguously.

Examples:

- `[[Server/Tester/chapter/design|chapter design]]`
- `[[Server/Tester/chapter/features/chapter-log/design|chapter-log design]]`
- `[[Server/Tester/chapter/features/chapter-log/code-plan|chapter-log code-plan]]`
- `[[Server/Tester/chapter/changes/rename-chapter-log/design|rename-chapter-log design]]`

Asset folder names are NOT required to be globally unique across products — the wikilink path disambiguates them. Request slugs, by contrast, are globally unique across the single content-root `requests/` inbox.

## Part 4 — Status file (folder-note) shape

Every asset folder (`features/<feat>/`, `changes/<change-name>/`, `bugs/<bug-name>/`) MUST contain exactly one folder-note — a file whose basename matches the parent folder (e.g., `features/chapter-log/chapter-log.md`, `changes/Rename Chapter Log/Rename Chapter Log.md`, `bugs/login-accepts-empty-password/login-accepts-empty-password.md`). It carries the asset's progression in a machine-consumable form for `spec.*` skills. The folder-note is identified by `spec_role: status` in frontmatter; `lazy-spec.doctor` also enforces the basename-matches-parent invariant.

The status file owns the asset's **gates** — five flat top-level booleans plus a `spec_cancelled` overlay. There is no `gates:` dict, no `stage:`, no `awaits_human:`, and no `## Workflow` section: the gate booleans are the entire progression model. The authoritative gate semantics — the linear S0..S5 ladder, the precondition table, derived-vs-human-signal mechanics, and the single mutation channel — live in [lifecycle](./lazy-spec.lifecycle-protocol.md). This section covers only the file's frontmatter shape and body layout; it does NOT restate the gate rules.

### Status frontmatter schema

The status folder-note carries the asset's type, five flat boolean gates and one overlay flag — no nesting, no `gates:` dict. This matches the shipped template `${CLAUDE_PLUGIN_ROOT}/templates/spec.<type>/asset-note.md` (or `spec.asset/asset-note.md` for a type with no folder of its own):

```yaml
---
tags:
  - <product_tag>
  - spec/status
spec_role: status
spec_asset_type: <the asset's type>
spec_design_done: false
spec_plan_done: false
spec_develop_done: false
spec_tests_passing: false
spec_released: false
spec_cancelled: false
iconize_icon: <inherited from the asset's type declaration>
iconize_color: <inherited from the asset's type declaration>
---
```

- `spec_asset_type` is what makes the asset an asset OF a type — the folder it sits in is a place, not a fact, and everything that resolves the asset's law (the coordinator, the playbook lookup) reads this key, never the path. Written at scaffold time alongside `spec_tools`, the list of tools the asset is realised and checked with when its type declares any.
- The five gate booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) and the `spec_cancelled` overlay are the asset's whole progression state. Their ladder, preconditions, and flip rules are owned by [lifecycle](./lazy-spec.lifecycle-protocol.md).
- `iconize_icon` / `iconize_color` are managed keys, inherited from the asset's type declaration (`asset_types[<type>]`, the product's own merged over the shipped set); they paint the folder icon in the Obsidian file explorer. Not authored by hand.
- This is distinct from the per-file `spec_stage` on sibling authored docs (`design.md` / `bug.md` / `code-plan.md` / `test-plan.md`) — see [lifecycle](./lazy-spec.lifecycle-protocol.md). The folder-note carries gates, not a stage. The sibling `code-report.md` / `test-report.md` journals carry neither gates nor a stage.

### Status body format

The status folder-note body carries seven H1 sections, in order, matching the shipped `asset-note.md` template byte-for-byte. All seven are plugin-owned and protected — each seeds EMPTY (no placeholder HTML comment; prose explanations live in this doc and the playbook, not in the scaffolded note itself). There is no title H1, no `## Current`, no `## Workflow`, no `## Log`, no H2-level Gates or History.

Each protected section's **first content line** is the ownership tag `#protected/spec/<region>`. This tag tells every other plugin (reviewer, wiki, etc.) that the section is owned by the spec plugin and must be preserved byte-for-byte across any edit those plugins make to the note. Ownership by the `spec` plugin domain is not the same as a single writer — the protected-sections obligation binds every OTHER plugin to leave the section alone; within the spec domain, who actually writes each section still varies (below).

1. **`# Summary`** (protected, `#protected/spec/summary`) — a one-line précis of the asset (written by `lazy-spec.create-asset` / `lazy-spec.product-config` at scaffold time; on container notes it carries `<!-- spec:precis:* -->` and `<!-- spec:stats:* -->` markers filled by `summary_render`).
2. **`# Gates`** (protected, `#protected/spec/gates`) — the `[!gate]` callouts `bin/flip_gate.py` appends. Never any task checkboxes here.
3. **`# Attachments`** (protected, `#protected/spec/attachments`) — the coordinator's registry of the asset's non-markdown attachments, one line per file: a link to the file and the document that owns it. **The one optional section**: the shipped templates seed it, so every freshly scaffolded note carries it empty, but a note created before it existed does not have it — `note-check` reports its absence as nothing at all, and only validates the owner tag when the heading is present. A markdown attachment is never listed here; its ownership lives in its own `spec_owner_doc` frontmatter, and duplicating it would create two sources of truth that can disagree.
4. **`# Status brief`** (protected, `#protected/spec/status-brief`) — `spec.coordinator`'s own prose, rewritten (not appended) on every invocation: what's happening on the asset, why it's stalled (if it is), what happens next. Placeholder before the coordinator's first pass: `_Not yet assessed by the coordinator._`.
5. **`# Coordinator rules`** (protected, `#protected/spec/coordinator-rules`) — operator-authored, persistent constraints scoped to this asset; `spec.coordinator` reads it before every decision but never writes it. The operator writes it by hand — the protected-section contract binds every other PLUGIN to preserve it byte-for-byte, not the operator. Seeded empty.
6. **`# Coordinator commands`** (protected, `#protected/spec/coordinator-commands`) — operator-authored one-shot instructions; the coordinator, as this section's owning persona, unfolds a command into a numbered mini-plan written into this same section, locks progress marks into it while the command runs, then moves the finished block into `# History` on completion (`lazy-spec.coordination-playbook.md` Chapter 5). Seeded empty.
7. **`# History`** (protected, `#protected/spec/history`) — one line per gate or stage transition, appended chronologically. Earlier lines are never rewritten.

```markdown
# Summary
#protected/spec/summary

<one-line précis of the asset>

# Gates
#protected/spec/gates

> [!gate] spec_design_done — flipped 2026-05-01 (auto: design.md approved)

> [!gate] spec_plan_done — flipped 2026-05-02 (auto: code-plan.md approved)

# Attachments
#protected/spec/attachments

- [mockup.html](mockup.html) — design.md
- [palette.svg](palette.svg) — design.md

# Status brief
#protected/spec/status-brief

<the coordinator's current narration>

# Coordinator rules
#protected/spec/coordinator-rules

<operator-authored constraints scoped to this asset, once written>

# Coordinator commands
#protected/spec/coordinator-commands

# History
#protected/spec/history

- 2026-05-01 — lazy-spec.flip-gate · spec_design_done → true
- 2026-05-02 — lazy-spec.flip-gate · spec_plan_done → true
```

**Rules**:

- `# Gates` carries the callouts written by `bin/flip_gate.py` — there are NEVER any task checkboxes here.
  - **`[!gate]`** — appended by `flip_gate` on every flip. Format: `> [!gate] <gate> — flipped <date> (<note>)`. `<note>` is the reason text; an auto-flip (from `spec.coordinator` calling the primitive with `--auto`) prefixes it with `auto:` — e.g. `(auto: design.md approved)`, or just `(auto)` when no reason is supplied.
  - There is no `[!ready]` / `[!info]` readiness callout anymore — `bin/gate_tick.py` no longer evaluates gate readiness or drops one. Readiness reasoning now lives in `spec.coordinator`'s own narration, in `# Status brief`, per `lazy-spec.coordination-playbook.md`.
- `# Attachments` is `spec.coordinator`'s own registry, one line per non-markdown attachment in the form `- [<file>](<file>) — <owner>.md`. It stays absent or empty on an asset that has none, and a line whose file no longer exists is removed on the next reconciliation. `note-check` treats the section as optional — no finding when the heading is absent, a `missing-marker` finding when the heading is present without `#protected/spec/attachments` as its very next line.
- `# Status brief`, `# Coordinator rules`, and `# Coordinator commands` are `spec.coordinator`'s own sections to reason from (write-once-per-invocation for the brief; read-only / lock-and-clear for the other two) — see `lazy-spec.coordination-playbook.md` §§ 1, 5, 9 for the full contract. `note-check` (`bin/note_ops.py`) validates all three are present, in order, and that each carries its own protected marker as the line immediately following its heading; `lazy-spec.doctor` delegates to it rather than re-deriving the check.
- `# History` is one line per gate (or stage) transition, appended chronologically. `flip_gate` writes `- <date> — lazy-spec.flip-gate · <gate> → <true|false>`; `lazy-spec.set-stage` writes its own per-file stage-transition lines here too. Earlier lines are never rewritten.

### Shared primitives — pointers

Skills touching status files or authored-doc stages use these named primitives rather than restating the mechanics:

- **`lazy-spec.flip-gate`** (`bin/flip_gate.py`) — the only writer of gate booleans. Flips unconditionally on call (refusing only a cancelled asset), rewrites the gate in frontmatter, appends the `[!gate]` callout + a `# History` line. Deciding WHEN a gate is ready is `spec.coordinator`'s call, not this primitive's. See [lifecycle](./lazy-spec.lifecycle-protocol.md) → "The single mutation channel".
- **`lazy-spec.gate-tick`** (`bin/gate_tick.py`) — a pure poller now: clears a finished expert job's `active_job` marker in the runtime sidecar and runs a structural `note-check` on the folder-note. It no longer flips gates, evaluates readiness, or drops any callout. See [lifecycle](./lazy-spec.lifecycle-protocol.md) → "The `gate-tick` md-scan worker".
- **`lazy-spec.set-stage`** — change a per-file stage on an authored doc; see [lifecycle](./lazy-spec.lifecycle-protocol.md). Every per-file stage change in the system MUST go through this primitive.
- **`lazy-spec.resolve-dependency`** — resolve a dep entry to `{kind, spec_link, dev_link, local_spec_path?}`; see [sources](./lazy-spec.sources-protocol.md) Part 3.
- **`lazy-spec.resolve-repo`** — turn a repo-config key into `{local_path, branch, remote_url, host, owner, repo, forge, base_url}` by inspecting the local checkout's git remote and applying the known-forges table; see [sources](./lazy-spec.sources-protocol.md) Part 2.
- **`lazy-spec.source-url`** — build a forge-correct source URL for `(repo_key, path, kind, branch?)` via the known-forges table. EVERY source URL emitted by any skill or agent MUST go through this primitive; see [sources](./lazy-spec.sources-protocol.md) Part 2.

Skills MUST reference these primitive names rather than restate the mechanics.

## Part 5 — Asset sibling topology (from an author-doc's POV)

An author-document lives at `<spec_path>/<category>/<slug>/`. Wherever an agent reads or writes an author-doc, sibling and product-level docs are at predictable relative paths:

| Target | Relative path from an asset's author-doc |
|--------|-------------------------------------------|
| Sibling `design.md` (or `bug.md` for bug-category) | `./design.md` (or `./bug.md`) |
| Sibling status folder-note | `./<slug>.md` (basename = the parent folder name) |
| Sibling `code-plan.md` (opt-in — may not exist) | `./code-plan.md` |
| Sibling `test-plan.md` (opt-in — may not exist) | `./test-plan.md` |
| Sibling `code-report.md` (opt-in — may not exist) | `./code-report.md` |
| Sibling `test-report.md` (opt-in — may not exist) | `./test-report.md` |
| Sibling `decisions.md` (opt-in — may not exist) | `./decisions.md` |
| Sibling attachment (free-named — may not exist) | `./<file>` |
| Product-level `design.md` | `../../design.md` |
| Product-level `tech.md` | `../../tech.md` |
| Product-level `decisions.md` (opt-in — may not exist) | `../../decisions.md` |

When an agent works over a specific author-doc, the canonical references it needs are usually already listed in that doc's `spec_source_docs` frontmatter — resolving those wikilinks is preferred over reasoning about paths from first principles (the dispatcher materialises the resolved files into the agent's `context/` payload). See [sources](./lazy-spec.sources-protocol.md) Part 1.

## Part 6 — Canonical writer per artifact (sanity check)

Every plugin-managed frontmatter key and body section has exactly one writer. Any other agent / skill / human writing to a key or section it does not own is a contract violation; `lazy-spec.doctor` and `lazy-core.audit` flag this.

| Artifact | Canonical writer |
|----------|------------------|
| `spec_stage` on any author-doc | `lazy-spec.set-stage` (single writer; field changes only through it) |
| `spec_stage` on a markdown attachment | `lazy-spec.set-stage`'s owner cascade, plus `spec.coordinator` reconciliation (catch-up after the attachment's own review, and stamping a newborn attachment) — never the creating expert, never a direct `set-stage` call |
| `spec_*_done` gates on a status folder-note | `lazy-spec.flip-gate` (invoked by `spec.coordinator` — with `--auto` for the two derived gates, per `lazy-spec.coordination-playbook.md` Chapter 3) |
| `spec_source_requests` frontmatter + body `## Requests` sub-section | `lazy-spec.request-apply` |
| `spec_source_docs` frontmatter + body `## Docs` sub-section | `lazy-spec.create-asset` (initial scaffold) / `lazy-spec.refresh-sources` (resync) |
| `iconize_*` on a folder-note | `lazy-spec.create-asset` (asset status), `lazy-spec.product-config` (product / asset-type folder-notes) |
| Body prose of an author-doc | the operator + lazy-review experts (`main` writer, `validation` writers, `terminal` writer per the doc's review-class) — exception: removing a tagged `[!decision]` callout from the body and inserting its registry link in its place is the `promote` operation of the `decide` primitive, regardless of which caller invokes it (`lazy-spec.set-stage`'s approval transition, `/lazy-spec.decide promote`, or the coordinator) |
| `# History` H1 section in an author-doc inside a review cycle | `lazy-review.coordinator` |
| `# Sources` H1 section + the `#protected/spec/sources` owner tag | specs writers (`lazy-spec.request-apply`, `lazy-spec.create-asset`, `lazy-spec.refresh-sources`) — never lazy-review, never operator-bypass |
| `decisions.md` body — all four operations (`add`, `supersede`, `obsolete`, `promote`) | the `decide` primitive (sole writer), except the `#protected/wiki/see-also` H1 section, which is owned by `lazycortex-wiki` per its `#protected/<owner>/<region>` tag |
| `# Attachments` H1 section + the `#protected/spec/attachments` owner tag | `spec.coordinator`'s own pen — written directly, never through a verb |
| `spec_owner_doc` / `spec_doc_type` on an attachment | the expert that creates the file, at creation time — never derived or backfilled by another writer |
| Body of an attachment | the job whose own result document is the attachment's `spec_owner_doc` — every other role reads it and leaves it alone |
| `wiki_pinned_topics` frontmatter | the file-creation sites that render it into a template (`scaffold_asset.py`, `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`), the `decide` primitive (on `decisions.md` at creation), and the `pins` verb (backfill on existing files) |

Any attempt by an expert or agent to write into a frontmatter key or body section not owned by it per this table is a contract violation.
