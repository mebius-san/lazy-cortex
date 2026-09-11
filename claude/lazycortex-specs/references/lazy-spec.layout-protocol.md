---
name: lazy-spec.layout-protocol
version: 5
description: Physical disk layout for spec assets — folder kinds, the open asset-type set, folder-notes, template storage and its five-layer resolution, the sibling topology an author-doc sees, and the canonical writer of every managed key and section.
---
# Layout protocol — folder structure, asset types, templates, sibling topology

Physical disk layout: where every kind of folder and file sits, which asset types may exist and how they are declared, where doc templates come from and in what order they resolve, the relative paths an author-doc's siblings are found at, and who is allowed to write each managed key and body section.

Two neighbours carry what this contract used to hold inline, split out at 75 KB and each keeping its original Part numbers (Parts 2–3, and Parts 4–4b respectively) so existing `Part N` citations still resolve: what a document IS — its type, its role, its filename, its header, its link form — is the [file-roles protocol](./lazy-spec.file-roles-protocol.md); what an asset's status folder-note and a level note look like inside is the [status-note protocol](./lazy-spec.status-note-protocol.md). The three stay inseparable in practice (a doc's path determines its role determines its allowed content determines its body header), and the stubs below point each moved Part at its new home. The abstraction height each design level holds — what the content may elaborate and what it delegates down — is the [doc-height protocol](./lazy-spec.doc-height-protocol.md)'s contract, delivered to review experts through the class's `protocols` list.

## Part 1 — Folder structure

### Folder kinds

**Spec content-root.** All spec content lives under `<settings-dir>/<spec.vault_root>` (default `specs`), where `<settings-dir>` is the directory that holds `.claude/lazy.settings.json` (the repo root) — except the `upstream/` mirror tree (see "Upstream unit notes" below), which sits directly at `<settings-dir>` since it is not yet vault content. The operator's top-level folders, the content-root `requests/` inbox, and the **project-wide level docs** — a loose `vision.md` + `design.md` + `tech.md` describing the whole project above every product, typed `system-vision` / `system-design` / `system-tech` — are direct children of the content-root. No config key declares them. `vision.md` is the **vault spec** and the ONLY mandatory level doc: `/lazy-spec.install` seeds its draft, and `lazy-spec.product-config` refuses to register the first product while it is absent (a pre-existing `design.md` without a vision is accepted as a legal pre-vision state) — the split into products is a consequence of the repo-wide spec. `design.md` and `tech.md` stay optional: their existence is their declaration. The reading chain per level is vision, then opt-in use-cases, then design, then tech — the direction of reading and sourcing (a design's `spec_source_docs` names the sibling vision), enforced at the level-doc scale by operator discipline alone. Vault-relative paths (`spec_path`, wikilinks, tags) are relative to this content-root, not to `<settings-dir>`. See [config](./lazy-spec.config-protocol.md) for the `spec.vault_root` setting.

Two kinds of folders exist under the content-root:

1. **Organizational folders** — everything above a product folder. Their names, nesting, and depth are the operator's own: the plugin dictates no form and derives no meaning from a path segment — a product's identity lives in its `products[<key>]` record and its files' frontmatter, never in where it sits. A product folder may also sit directly at the content-root, with no organizational folders above it.
2. **Product folders** — the folder a registered product's `spec_path` points at (lowercase-with-hyphens recommended for the folder name). A product folder owns the category subdirectories below; the only loose files at the product folder level are the product folder-note (see "Folder-notes" below), the product-level docs `vision.md` + `design.md` + `tech.md`, and the opt-in `use-cases.md` + `decisions.md`:
   - `vision.md` + `design.md` + `tech.md` — the product-level docs, loose at the product root (NOT in a subfolder), typed `system-vision` / `system-design` / `system-tech` (`spec_role` stays `vision` / `design` / `tech`). `vision.md` is seeded by `lazy-spec.product-config` create mode — the seeding is its whole obligation; a pre-existing product with `design.md` and no vision is a legal pre-vision state. `design.md` and `tech.md` stay optional. There is no per-product `docs/` or `spec/` subfolder — the system itself is called "spec", so product-level reference material sits directly at the product root alongside the folder-note. Because the folder-note basename is `<product>.md`, a product slug of `design` or `tech` would collide with these docs and is therefore forbidden (see [file-roles](./lazy-spec.file-roles-protocol.md) Part 3 naming).
   - `decisions.md` — the product-level decisions registry, loose at the product root. Opt-in and lazily created: it exists only once the `decide` primitive writes a product-level record into it. Its absence is never a defect. No `spec_stage`, no review — see [file-roles](./lazy-spec.file-roles-protocol.md) Part 2.
   - `use-cases.md` — the product-level use cases, loose at the product root: the product's actors and cross-feature scenarios. Opt-in, authored by the operator (no checkbox exists above the asset level); absence is never a defect. Stage-bearing and reviewed like its asset-level sibling — the same `use-cases` review class covers it.
   - **group folders** — one per asset type whose assets exist, named by the type's `default_path`: the shipped `features/` / `changes/` / `bugs/` and every operator-declared type's folder (e.g. `characters/`, `scenes/`) follow ONE rule. The folder is a place, not a fact: an asset's kind is the `spec_asset_type` key on its own status folder-note, and the folder is created lazily by the first `scaffold-asset` call that lands an asset in it — nothing pre-creates an empty group folder, and a product using no changes has no `changes/`. On that first landing the scaffold also seeds the group folder-note `<folder>/<folder>.md` when none exists: an operator-zone note (protected `# Summary` skeleton plus an empty protected `# Coordinator rules` section — the group-scoped rules layer of `lazy-spec.coordination-playbook.md` § 2 — `iconize_icon` from the type's declaration and no `iconize_color` at all — an ordinary container is colourless per [config](./lazy-spec.config-protocol.md) § Container colour, NO `spec_role`) whose body below the skeleton is the operator's; an already-present note is never touched, and an asset scaffolded inside another asset's folder seeds nothing (the enclosing folder's own status note is its folder-note). A bug folder carries `bug.md` (the report: summary, repro steps, observed vs expected) plus the opt-in `code-plan.md` / `code-report.md` / `test-plan.md` / `test-report.md` quartet; it has NO `design.md`, NO `tech.md`, and NO `architecture.md` — a bug fix is never judged code-bearing enough to need one (`lazy-spec.coordination-playbook.md` Chapter 3).

**The request inbox is NOT a product category.** A single `requests/` folder at the **content-root** (a direct child of the content-root, never under a product `spec_path`) holds all free-form intake for the whole vault — one `<slug>.md` per request. A request may target multiple products, so per-product placement would force duplication; classification routes it to the right product/entity. Full lifecycle + frontmatter contract live in [request-format](./lazy-spec.request-protocol.md).

There is **no `backlog/` folder** (removed), **no `human-tasks.md` loose file** (removed — there is no plugin-managed human-attention dashboard; container index dataview is operator-zone), and **no `changelog.md` loose file** (removed — history is recorded per-doc via `# History` H1 sections written by lazy-review.coordinator, and per-asset via the status folder-note's `# History` H1 section written by `lazy-spec.flip-gate` / `lazy-spec.set-stage`. There is no separate product-wide changelog).

**A product folder MUST NOT contain another product folder.** Group related sibling products under a shared organizational parent folder instead.

### Asset types — shipped + operator-defined

Asset types are an **open set**, declared rather than enumerated. Two layers declare:

- **Shipped**: the plugin, in `references/lazy-spec.asset-types.json` — five spawnable types, `feature`, `change`, `bug`, `content`, `research`, with default paths `features/` / `changes/` / `bugs/` / `content/` / `research/`. The same file also carries the `catalog` and `product` level entries: they have no `default_path`, nothing spawns into them, and they exist only to give a level note its icon and its playbook.
- **Operator-defined**: a product, under `products[<key>].asset_types` in `.claude/lazy.settings.json` — merged over the shipped set key-by-key, so a product may replace one field of a shipped type without restating the rest.

A declaration carries `{ icon, color?, playbook, alias_of?, default_path?, start_doc, default_tools?, vision? }`. `vision` is the asset-level vision contract — `mandatory` (the coordinator seeds and starts `vision.md` itself on a fresh asset, before the start document), `opt-in` (a `Write vision` launch checkbox), or `none` (the doc is illegal on the type); shipped defaults: `feature` mandatory, `change` opt-in, `bug` none, `content` and `research` opt-in; an undeclared field reads as `opt-in`. `start_doc` is the `"<file>:<doc_type>"` token naming the one document a fresh asset of the type is seeded with; `playbook` is the reference `spec.coordinator` loads on every wake of an asset of the type; `alias_of` names a base type whose playbook this one borrows when it declares none of its own — the folder, icon, colour, start document and tools stay the alias's own, and aliases never chain.

A type declared via `/lazy-spec.add-asset-type` is recognised by `lazy-spec.create-asset`, `lazy-spec.request-classify`, the coordinator, and the review daemon on their next run without a rubric or code edit. The skill writes the declaration and nothing else: **no folder is created on disk**, no folder-note is rendered, and no templates are seeded — the type's folder appears the first time an asset of it is scaffolded, and the operator-zone folder-note is theirs to author. Its design / code-plan / test-plan docs are covered by the shared behavior-keyed review classes (right-anchored `*/design.md` / `*/code-plan.md` / `*/test-plan.md` globs) — no per-type class is created.

An asset folder is `<spec_path>/<folder>/<slug>/`, where `<folder>` is the type's `default_path` unless the caller named another location. Assets may nest: an asset's boundary is the folder whose folder-note carries `spec_role: status`, so a folder sitting inside another asset's folder is its own asset all the same. It holds:

- the status folder-note `<slug>.md` (`spec_role: status`, flat gates, `spec_asset_type` — see [status-note](./lazy-spec.status-note-protocol.md) Part 4 and [lifecycle](./lazy-spec.lifecycle-protocol.md));
- the document named by the type's `start_doc` — `design.md` for the shipped `feature` / `change` / `content` types and for `research` (typed `research-design` there), `bug.md` for `bug`. There is no default layout: a type with no `start_doc` cannot be scaffolded at all;
- optionally `architecture.md` — feature/change layout only, NEVER on a bug; opt-in on disk the same way as `code-plan.md` / `test-plan.md`, but its existence tracks a coordinator judgment (code-bearing asset) rather than free operator choice — see [coordination-playbook](./lazy-spec.coordination-playbook.md) Chapter 3 and Chapter 8;
- `vision.md` per the asset type's `vision` contract — mandatory on a feature (the coordinator seeds and starts it before `design.md`; the `Write design` row waits for its approve), opt-in on a change, on `content`, and on `research` (`Write vision` checkbox, window closes with `spec_design_done`), never on a bug;
- optionally `use-cases.md` and/or `ui-design.md` — feature/change layout only, NEVER on a bug; opt-in the same way as `code-plan.md` / `test-plan.md`, each created only once its launch checkbox is ticked or the product or asset declares it mandatory — see the [feature](./lazy-spec.feature-playbook.md) and [change](./lazy-spec.change-playbook.md) playbooks;
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
│   ├── vision.md
│   ├── use-cases.md
│   ├── design.md
│   ├── ui-design.md
│   ├── architecture.md
│   ├── code-plan.md
│   ├── test-plan.md
│   ├── code-report.md
│   ├── test-report.md
│   ├── bug.md
│   ├── research-design.md                       ← research asset start doc: <slug>/design.md typed research-design
│   ├── research.md                              ← the research tool's report, typed research-report
│   ├── system-vision.md                         ← product-level <product>/vision.md
│   ├── system-design.md                         ← product-level <product>/design.md
│   ├── system-tech.md                           ← product-level <product>/tech.md
│   ├── vault-vision.md                          ← content-root vision.md
│   ├── vault-design.md                          ← content-root design.md
│   └── vault-tech.md                            ← content-root tech.md
├── spec.product/                                ← product-level docs (at the product root) + the level folder-note
│   ├── design.md                                ← specialisation: <product>/design.md diverges from the base
│   ├── level-note.md                            ← <product>.md level folder-note; `catalog-note backfill` renders it, at a product root and at the catalog root alike
│   └── group-note.md                            ← group folder-note skeleton (product is the "group" of its asset types)
├── spec.feature/                                ← shipped feature type — no doc specialisations, rides the base
│   ├── asset-note.md                            ← <slug>/<slug>.md asset status folder-note (gates + # History)
│   └── group-note.md                            ← features/features.md type folder-note (operator-zone)
├── spec.change/                                 ← shipped change type
│   ├── design.md                                ← specialisation
│   ├── architecture.md                          ← specialisation
│   ├── code-plan.md                             ← specialisation
│   ├── asset-note.md
│   └── group-note.md                            ← changes/changes.md type folder-note
├── spec.bug/                                    ← shipped bug type (its `start_doc` seeds `bug.md`, not `design.md`)
│   ├── code-plan.md                             ← specialisation
│   ├── asset-note.md
│   └── group-note.md                            ← bugs/bugs.md type folder-note
├── spec.request/                                ← content-root intake inbox (the request file itself has no template — `lazy-spec.create-request` writes its body inline)
│   └── group-note.md                            ← <content-root>/requests/requests.md inbox folder-note
└── spec.asset/                                  ← TYPE-AGNOSTIC BASE: what a type with no folder of its own falls back on
    ├── asset-note.md                            ← <slug>/<slug>.md asset status folder-note (gates + # History)
    └── group-note.md                            ← <folder>/<folder>.md type folder-note (operator-zone)
```

Naming convention inside an asset-type template folder:

- **`group-note.md`** — the folder-note for the type's COLLECTION folder (the `<folder>/` itself, e.g. `features/features.md`). Operator-zone — plugin writes only the managed `iconize_*` keys.
- **`asset-note.md`** — the folder-note for each individual ASSET folder (`<slug>/<slug>.md`). Carries `spec_role: status`, gates, `# Gates`, `# History`. Plugin-managed.
- **`level-note.md`** (`spec.product/` only) — the folder-note for a LEVEL: a product root (`<product>.md`) or the catalog root. Carries `spec_role: product` / `catalog`, the four level gates, `# Gates`, `# Status brief`, `# History`. Plugin-managed, and never instantiated by a scaffold — the `catalog-note backfill` verb owns it ([status-note](./lazy-spec.status-note-protocol.md) Part 4b).
- The named docs (`design.md`, `bug.md`, `tech.md`, `code-plan.md`, `test-plan.md`, `code-report.md`, `test-report.md`) — authored content the operator + lazy-review experts fill in.

**An operator-defined type ships no template folder, and none is seeded for it.** `/lazy-spec.add-asset-type` writes the type's declaration and stops — it copies no files into `.claude/templates/spec.<name>/`. A type with no folder of its own resolves every document from the plugin's linear base (`spec.docs/`) and its status folder-note from the type-agnostic base (`spec.asset/`), which is why a type needs no template to be scaffoldable. An operator who wants a specialisation creates `.claude/templates/spec.<name>/` by hand and drops in the files to override — the resolver picks them up on the next scaffold, with no registration step.

Diagram exemplars are owned by the `lazycortex-diagram:lazy-diagram.draw` engine (shipped by the lazycortex-diagram plugin), and this template tree has no say in them. There is **no per-product diagram-exemplar override**: the drawer's input list carries no override key, and its mermaid writer resolves each kind's exemplar from the diagram plugin's own template directory. A product that needs a different diagram house style changes the exemplar the diagram plugin ships; nothing under `.claude/templates/` is consulted for it.

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
    ├── vision.md                            ← mandatory vault spec — project-wide vision (system-vision), seeded by /lazy-spec.install
    ├── design.md                            ← optional — project-wide design (system-design)
    ├── tech.md                              ← optional — project-wide tech (system-tech), loose at the content-root
    ├── decisions.md                         ← opt-in — project-level decisions registry, lazily created
    ├── use-cases.md                         ← opt-in — project-level use cases, absence is never a defect
    ├── <operator folders…>/                 ← free-form organizational nesting, operator's own (any depth, or none)
    │   └── …/
    │       └── <product>/                   ← product folder (root of the product's spec_path)
    │           ├── <product>.md             ← product folder-note (operator-zone; managed iconize_icon)
    │           ├── vision.md                ← product-level vision (seeded at product creation)
    │           ├── design.md                ← product-level design (loose at product root)
    │           ├── tech.md                  ← product-level tech (loose at product root)
    │           ├── decisions.md              ← opt-in — product-level decisions registry, lazily created
    │           ├── use-cases.md              ← opt-in — product-level use cases, absence is never a defect
    │           ├── features/
    │           │   ├── features.md          ← category folder-note (operator-zone; managed iconize_icon)
    │           │   └── <slug>/              ← feature asset folder
    │           │       ├── <slug>.md        ← status folder-note (spec_role: status, flat gates)
    │           │       ├── vision.md        ← mandatory on a feature — seeded by the coordinator before design
    │           │       ├── use-cases.md     ← opt-in — present only when authored
    │           │       ├── design.md
    │           │       ├── architecture.md  ← opt-in — present once the asset is judged code-bearing
    │           │       ├── ui-design.md     ← opt-in — present only when authored
    │           │       ├── code-plan.md      ← opt-in — present only when authored
    │           │       ├── code-report.md    ← opt-in — present only when authored
    │           │       ├── test-plan.md     ← opt-in — present only when authored
    │           │       ├── test-report.md   ← opt-in — present only when authored
    │           │       └── decisions.md     ← opt-in — asset-level decisions registry, lazily created
    │           ├── changes/
    │           │   ├── changes.md           ← category folder-note (operator-zone)
    │           │   └── <slug>/              ← change asset folder
    │           │       ├── <slug>.md        ← status folder-note
    │           │       ├── vision.md        ← opt-in on a change — Write vision checkbox
    │           │       ├── use-cases.md     ← opt-in
    │           │       ├── design.md
    │           │       ├── architecture.md  ← opt-in — present once the asset is judged code-bearing
    │           │       ├── ui-design.md     ← opt-in
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

An asset folder of any category may additionally hold **attachments** — files an expert created beside the document it was writing (a mockup, a diagram, a data file, an extra prose chapter). They are not drawn in the tree above because they carry no fixed names, and they sit **flat in the asset folder**, beside the documents. There is no attachments subfolder, and no other legal location. See [file-roles](./lazy-spec.file-roles-protocol.md) Part 2 § Attachments for what an attachment is and which keys it carries.

## Part 2 — File roles

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md`** for what a document IS: the open `spec_doc_type` set and its two declaring layers, the closed sixteen-value `spec_role` set with its per-role content and stage rules, the path constraints each role is legal under, the removed roles, the operator-zone folder-notes that carry no role at all, and the three file kinds that live outside the closed set — request files, upstream unit notes, and attachments with their `spec_owner_doc` / `spec_doc_type` pair. That file keeps this Part's number.

## Part 3 — File naming, header section, wikilinks

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md`** for role-only filenames and their four exceptions, the reserved product slugs, the frontmatter-field table every authored doc is written against, the mandatory `# <Title> — <role>` body header, and the path-qualified wikilink form bare links are forbidden in favour of. That file keeps this Part's number.

## Part 4 — Status file (folder-note) shape

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.status-note-protocol.md`** for the asset status folder-note: its flat-gate frontmatter schema, the seven protected H1 sections in order with their `#protected/spec/<region>` owner tags, the launch-checkbox and `# Attachments` line shapes, and the shared-primitive pointers (`lazy-spec.flip-gate`, `lazy-spec.gate-tick`, `lazy-spec.set-stage`, the source-resolution trio). That file keeps this Part's number.

## Part 4b — Level note (product root and catalog root) shape

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.status-note-protocol.md`** for the two LEVEL notes: the `catalog-note backfill` verb that brings both to schema, the four-gate frontmatter, and the seven-section body whose required roster is stricter than a status note's. That file keeps this Part's number.

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
| Project-level `decisions.md` (opt-in — may not exist) | `<content-root>/decisions.md` — resolve from the vault root, not by relative hops |

When an agent works over a specific author-doc, the canonical references it needs are usually already listed in that doc's `spec_source_docs` frontmatter — resolving those wikilinks is preferred over reasoning about paths from first principles (the dispatcher materialises the resolved files into the agent's `context/` payload). See [sources](./lazy-spec.sources-protocol.md) Part 1.

## Part 6 — Canonical writer per artifact (sanity check)

Every plugin-managed frontmatter key and body section has exactly one writer. Any other agent / skill / human writing to a key or section it does not own is a contract violation; `lazy-spec.audit` and `lazy-core.audit` flag this.

| Artifact | Canonical writer |
|----------|------------------|
| `spec_stage` on any author-doc | `lazy-spec.set-stage` (single writer; field changes only through it) |
| `spec_stage` on a markdown attachment | `lazy-spec.set-stage`'s owner cascade, plus `spec.coordinator` reconciliation (catch-up after the attachment's own review, and stamping a newborn attachment) — never the creating expert, never a direct `set-stage` call |
| `spec_*_done` gates on a status folder-note | `lazy-spec.flip-gate` (invoked by `spec.coordinator` — with `--auto` for the two derived gates, per `lazy-spec.coordination-playbook.md` Chapter 3) |
| `spec_source_requests` frontmatter + body `## Requests` sub-section | `lazy-spec.request-apply` |
| `spec_source_docs` frontmatter + body `## Docs` sub-section | `lazy-spec.create-asset` (initial scaffold) / `lazy-spec.refresh-sources` (resync) |
| `iconize_*` on a folder-note | `lazy-spec.create-asset` (asset status), `lazy-spec.product-config` (product / asset-type folder-notes) |
| Body prose of an author-doc | the operator + lazy-review experts (`main` writer, `validation` writers, `terminal` writer per the doc's review-class) — exception: removing a tagged `[!decision]` callout from the body and inserting its registry link in its place is the `promote` operation of the `decide` primitive, regardless of which caller invokes it (`lazy-spec.set-stage`'s approval transition, `/lazy-spec.record-decision promote`, or the coordinator) |
| `# History` H1 section in an author-doc inside a review cycle | `lazy-review.coordinator` |
| `# Sources` H1 section + the `#protected/spec/sources` owner tag | specs writers (`lazy-spec.request-apply`, `lazy-spec.create-asset`, `lazy-spec.refresh-sources`) — never lazy-review, never operator-bypass |
| `decisions.md` body — all four operations (`add`, `supersede`, `obsolete`, `promote`) | the `decide` primitive (sole writer), except the `#protected/wiki/see-also` H1 section, which is owned by `lazycortex-wiki` per its `#protected/<owner>/<region>` tag |
| `# Attachments` H1 section + the `#protected/spec/attachments` owner tag | `spec.coordinator`'s own pen — written directly, never through a verb |
| `spec_owner_doc` / `spec_doc_type` on an attachment | the expert that creates the file, at creation time — never derived or backfilled by another writer |
| Body of an attachment | the job whose own result document is the attachment's `spec_owner_doc` — every other role reads it and leaves it alone |
| `wiki_pinned_topics` frontmatter | the file-creation sites that render it into a template (`scaffold_asset.py`, `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`), the `decide` primitive (on `decisions.md` at creation), and the `pins` verb (backfill on existing files) |

Any attempt by an expert or agent to write into a frontmatter key or body section not owned by it per this table is a contract violation.
