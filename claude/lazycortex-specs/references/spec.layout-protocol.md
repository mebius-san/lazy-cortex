---
name: spec.layout-protocol
version: 2
description: Physical disk layout for spec assets — folder kinds, the closed set of file roles, naming conventions, and the asset status folder-note body shape.
---
# Layout protocol — folder structure, file roles, naming, status-file shape

Physical disk layout, the closed set of file roles, naming conventions, and the asset status folder-note's body shape — one contract because they're inseparable in practice (a doc's path determines its role determines its allowed content determines its body header).

## Part 1 — Folder structure

### Folder kinds

**Spec content-root.** All spec content lives under `<settings-dir>/<spec.vault_root>` (default `specs`), where `<settings-dir>` is the directory that holds `.claude/lazy.settings.json` (the repo root). Subsystem folders and the content-root `requests/` inbox are direct children of the content-root. Vault-relative paths (`spec_path`, wikilinks, tags) are relative to this content-root, not to `<settings-dir>`. See [config](./spec.config-protocol.md) for the `spec.vault_root` setting.

Three kinds of folders exist under the content-root:

1. **Subsystem folders** — top-level, named for the subsystem using TitleCase. They contain namespace folders and/or product folders directly.
2. **Namespace folders** — optional grouping folders using TitleCase, used to collect related products under a common label. A namespace folder contains ONLY product folders. It is purely organizational.
3. **Product folders** — leaf folders using lowercase-with-hyphens. A product folder owns the category subdirectories below; the only loose files at the product folder level are the product folder-note (see "Folder-notes" below) and the two product-level docs `design.md` + `tech.md`:
   - `design.md` + `tech.md` — the product-level docs, loose at the product root (NOT in a subfolder). There is no per-product `docs/` or `spec/` subfolder — the system itself is called "spec", so product-level reference material sits directly at the product root alongside the folder-note. Because the folder-note basename is `<product>.md`, a product slug of `design` or `tech` would collide with these docs and is therefore forbidden (see Part 3 naming).
   - `features/` — feature asset folders (one per feature). Required directory even if empty.
   - `changes/` — change asset folders (one per change — the atomic modification unit; see Part 2 and `spec.create-change`). Required directory even if empty.
   - `bugs/` — bug asset folders (one per bug — see Part 2 and `spec.create-bug`). Required directory even if empty. A bug folder carries `bug.md` (the report: summary, repro steps, observed vs expected) plus `plan.md`; it has NO `design.md` and NO `tech.md`.
   - **operator-defined category folders** — one per operator-defined asset category declared in `products[<key>].asset_categories` (e.g. `characters/`, `scenes/`, `chapters/`). Each holds asset folders mirroring `features/`.

**The request inbox is NOT a product category.** A single `requests/` folder at the **content-root** (a sibling of the subsystem folders, never under a product `spec_path`) holds all free-form intake for the whole vault — one `<slug>.md` per request. A request may target multiple products, so per-product placement would force duplication; classification routes it to the right product/entity. Full lifecycle + frontmatter contract live in [request-format](./spec.request-protocol.md).

There is **no `backlog/` folder** (removed), **no `human-tasks.md` loose file** (removed — there is no plugin-managed human-attention dashboard; container index dataview is operator-zone), and **no `changelog.md` loose file** (removed — history is recorded per-doc via `# History` H1 sections written by lazy-review.historian, and per-asset via the status folder-note's `# History` H1 section written by `spec.flip-gate` / `spec.set-stage`. There is no separate product-wide changelog).

**A product folder MUST NOT contain another product folder.** Use a namespace folder to group related sibling products under a common label.

### Asset categories — built-in + operator-defined

Asset categories are an **open set**:

- **Built-in**: `feature` / `change` / `bug`, with folders `features/` / `changes/` / `bugs/`. Always present.
- **Operator-defined**: any key declared in `products[<key>].asset_categories` (config block carrying `{ icon, color? }`). A category registered via `/spec.add-asset-category` is recognised by `spec.create-asset`, `spec.request-classify`, and the review daemon on their next run without a rubric or code edit. Each operator-defined category gets its own folder `<spec_path>/<name>/`, its operator-zone folder-note, and a default design + plan review-class pair.

An asset folder (under any category) is `<spec_path>/<category>/<slug>/` and holds:

- the status folder-note `<slug>.md` (`spec_role: status`, flat gates — see Part 4 and [lifecycle](./spec.lifecycle-protocol.md));
- `design.md` + `plan.md` (default layout: `feature` / `change` / any operator-defined category), OR `bug.md` + `plan.md` (bug layout — NO `design.md`).

There is no per-asset `tech.md` (only the product carries `tech.md` at its root) and no `layout` doc.

### Folder-notes — at every folder

Every folder in the tree carries a folder-note (the Obsidian convention: a note whose basename matches the parent folder; clicking the folder opens it). Three flavours:

| Folder | Folder-note | Kind |
|--------|-------------|------|
| product `<spec_path>/` | `<product>.md` | operator-zone (no `spec_role`) |
| built-in category `features/` / `changes/` / `bugs/` | `features/features.md`, … | operator-zone (no `spec_role`) |
| operator-defined category `<spec_path>/<name>/` | `<name>/<name>.md` | operator-zone (no `spec_role`) |
| content-root request inbox `requests/` | `requests/requests.md` | operator-zone (no `spec_role`) |
| asset `<spec_path>/<category>/<slug>/` | `<slug>.md` | status (`spec_role: status`, flat gates) |

#### Managed icon frontmatter + category description

The plugin WRITES two managed keys into every folder-note from config — `iconize_icon` and `iconize_color` (the Obsidian iconize system paints the folder from these). For a product folder-note the values come from `products[<key>].icon`; for a category folder-note from `asset_categories[<name>].icon` / `.color` (built-in categories fall back to defaults: `feature` → `LiRocket`, `change` → `LiRefreshCcw`, `bug` → `LiBug`; the content-root request inbox folder-note defaults to `LiInbox`). For an asset status folder-note they come from the asset's category icon, injected at scaffold time.

A category folder-note also carries a `description` frontmatter key — the operator's prose explanation of what the category holds. The plugin **only READS** `description` (and the operator-owned body); it never overwrites operator text.

#### Operator-zone folder-note bodies

Product and category folder-note **bodies are operator-zone**: the plugin does not manage them. They carry NO `spec_role`, NO `*-index` role, and NO plugin-managed dataview. The body is a single `# <name>` H1 plus operator-owned prose (a scaffold seeds a one-line HTML comment marking the body operator-owned). If an operator wants a container dashboard (a dataviewjs listing of the assets under that folder), they author it themselves — it is their content, outside the plugin's contract.

### Template storage (per-file + per-product)

Spec-system doc templates are organised **per asset category**: one folder per category under `.claude/templates/`, with the per-category set of templates that category uses. The single shared `spec.docs/default/` of an older revision is gone — each category owns its own templates so an edit (or a per-product override) of one category never silently affects another:

```
.claude/templates/
├── spec.product/                                ← product-level docs (at the product root)
│   ├── design.md                                ← <product>/design.md
│   ├── tech.md                                  ← <product>/tech.md
│   └── group-note.md                            ← <product>.md operator folder-note (product is the "group" of its asset categories)
├── spec.feature/                                ← built-in feature category
│   ├── design.md                                ← <slug>/design.md
│   ├── plan.md                                  ← <slug>/plan.md
│   ├── asset-note.md                            ← <slug>/<slug>.md asset status folder-note (gates + # History)
│   └── group-note.md                            ← features/features.md category folder-note (operator-zone)
├── spec.change/                                 ← built-in change category
│   ├── design.md
│   ├── plan.md
│   ├── asset-note.md
│   └── group-note.md                            ← changes/changes.md category folder-note
├── spec.bug/                                    ← built-in bug category (bug.md replaces design.md)
│   ├── bug.md                                   ← <slug>/bug.md
│   ├── plan.md
│   ├── asset-note.md
│   └── group-note.md                            ← bugs/bugs.md category folder-note
├── spec.request/                                ← content-root intake inbox
│   ├── request.md                               ← <slug>.md request file (single-file, NOT a folder-note)
│   └── group-note.md                            ← <content-root>/requests/requests.md inbox folder-note
├── spec._content/                               ← BASELINE for operator-defined categories (plugin-shipped, never used directly)
│   ├── design.md                                ← content-flavored design template (Summary / Attributes / Relations / Notes)
│   ├── plan.md                                  ← content-flavored plan template
│   ├── asset-note.md                            ← identical to feature/change/bug asset-note (flat gates)
│   └── group-note.md                            ← group-note with {{name}} / {{description}} placeholders
└── spec.<operator-category>/                    ← one folder per operator-defined category, seeded by /spec.add-asset-category from spec._content/ INTO `.claude/templates/spec.<name>/`
    ├── design.md
    ├── plan.md
    ├── asset-note.md
    └── group-note.md                            ← <category>/<category>.md category folder-note (basename matches parent folder)
```

The leading-underscore folder `spec._content/` is **plugin-shipped baseline only** — it is never the resolution target of `spec.create-asset` at runtime (category names can't start with `_`, per `^[a-z][a-z0-9-]*$`). It exists so `/spec.add-asset-category` has a single source to copy from when seeding a new operator-defined category's local templates. If you want a different baseline (e.g. a software-engineering operator category that mirrors feature/change shape rather than content-asset shape), copy from `spec.feature/` by hand into `.claude/templates/spec.<name>/` after running add-asset-category, or extend add-asset-category to take a `--from <baseline>` flag (not implemented today).

Naming convention inside a category template folder:

- **`group-note.md`** — the folder-note for the category's COLLECTION folder (the `<category>/` itself, e.g. `features/features.md`). Operator-zone — plugin writes only the managed `iconize_*` keys.
- **`asset-note.md`** — the folder-note for each individual ASSET folder (`<slug>/<slug>.md`). Carries `spec_role: status`, gates, `# Gates`, `# History`. Plugin-managed.
- The named docs (`design.md`, `plan.md`, `bug.md`, `tech.md`) — authored content the operator + lazy-review experts fill in.

Each built-in category folder ships exactly the templates that category needs — no shared baseline that built-ins silently rely on. An **operator-defined category** (added via `/spec.add-asset-category`) is a different case: the plugin can't ship per-category templates for a category it doesn't know about ahead of time. So add-asset-category seeds `.claude/templates/spec.<name>/` by copying the four files from the plugin-shipped `spec._content/` baseline (design + plan + asset-note + group-note). The operator can then edit any file under their seeded `.claude/templates/spec.<name>/` directory to specialize the category — adding character-specific sections to `design.md`, tweaking the plan structure, etc.

Diagram exemplars are owned by the `lazycortex-diagram:lazy-diagram.draw` engine (shipped by the lazycortex-diagram plugin). Per-product diagram-exemplar overrides live under whatever directory a caller passes to the drawer via `exemplar_override_dir`.

**Template resolution (3-layer fallback).** When `spec.create-asset` scaffolds an asset, it resolves each template file in this order, first hit wins:

1. **Per-product override** — `.claude/templates/spec.<category>/<compound-key>/<file>.md` (operator-authored variant for one specific product; compound-key matches the product's settings key).
2. **Consumer category baseline** — `.claude/templates/spec.<category>/<file>.md` (the category-level baseline in the consumer vault — this is where operator-defined categories live, and where built-in categories CAN live if the operator hand-copies a file from the plugin baseline to override it).
3. **Plugin baseline** — `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/<file>.md` (the plugin-shipped baseline; exists only for built-in categories — `feature` / `change` / `bug` / `product` / `request`). Layer 3 is absent for operator-defined categories; their layer 2 (seeded by add-asset-category from `spec._content/`) is what makes them work.

There is no settings field for this — folder + file presence is the single signal at each layer.

### Generic Layout

All products follow this shape. No concrete names appear in this rule — skills discover products at runtime from the `products` section of `.claude/lazy.settings.json` (see [config](./spec.config-protocol.md) for the compound-key rule).

```
<settings-dir>/                              ← repo root (holds .claude/lazy.settings.json)
└── specs/                                   ← content-root (<spec.vault_root>, default "specs")
    ├── <Subsystem>/
    │   └── [<Namespace>/]                   ← optional grouping folder, no role files
    │       └── <product>/                   ← product folder (lowercase-with-hyphens)
    │           ├── <product>.md             ← product folder-note (operator-zone; managed iconize_icon)
    │           ├── design.md                ← product-level design (loose at product root)
    │           ├── tech.md                  ← product-level tech (loose at product root)
    │           ├── features/
    │           │   ├── features.md          ← category folder-note (operator-zone; managed iconize_icon)
    │           │   └── <slug>/              ← feature asset folder
    │           │       ├── <slug>.md        ← status folder-note (spec_role: status, flat gates)
    │           │       ├── design.md
    │           │       └── plan.md
    │           ├── changes/
    │           │   ├── changes.md           ← category folder-note (operator-zone)
    │           │   └── <slug>/              ← change asset folder
    │           │       ├── <slug>.md        ← status folder-note
    │           │       ├── design.md
    │           │       └── plan.md
    │           ├── bugs/
    │           │   ├── bugs.md              ← category folder-note (operator-zone)
    │           │   └── <slug>/              ← bug asset folder
    │           │       ├── <slug>.md        ← status folder-note
    │           │       ├── bug.md           ← report: summary, repro steps, observed vs expected
    │           │       └── plan.md          ← fix plan (no design.md, no tech.md)
    │           └── <category>/              ← operator-defined asset category (asset_categories key)
    │               ├── <category>.md        ← category folder-note (operator-zone; description + managed iconize_icon)
    │               └── <slug>/              ← asset folder
    │                   ├── <slug>.md        ← status folder-note
    │                   ├── design.md
    │                   └── plan.md
    └── requests/                            ← vault-wide free-form intake (sibling of subsystem folders)
        ├── requests.md                      ← inbox folder-note (operator-zone; managed iconize_icon, default LiInbox)
        └── <slug>.md                        ← request file (lifecycle in spec.request-protocol.md)
```

The request inbox is a direct child of the content-root — a sibling of the subsystem folders, not inside any product.

## Part 2 — File roles

The `spec_role` frontmatter key is a **closed set** of five values: `design`, `plan`, `bug`, `tech`, `status`. A plugin-owned spec doc carries exactly one of these. Role determines what content is allowed.

| `spec_role` | Purpose | May contain source URLs? | May carry `spec_source_branches`? | Per-file `spec_stage`? |
|------|---------|--------------------------|------------------------------|-------------------|
| `design` | Behavior, requirements, user flow — WHAT the system does (feature/change/operator-defined-asset doc) | **No** | No | **Yes** |
| `tech` | Technical specification: architecture, source file map, components, data structures, reuse notes. Product-level only (`tech.md` at the product root) — no per-asset `tech.md` | **Yes** | **Yes** | **Yes** |
| `plan` | Step-by-step implementation or fix task list with file-level refs | **Yes** | **Yes** | **Yes** |
| `bug` | Report doc for a bug: what's broken, repro steps, observed vs expected, environment, links to affected code / logs. No companion `design` or `tech` — a bug folder ships only `bug.md` + `plan.md` | **Yes** (only in the `## Related code / logs` section) | No | **Yes** |
| `status` | Asset folder-note: lifecycle state as flat gate booleans (`spec_design_done`…`spec_released` + `spec_cancelled`), `# Gates` callouts (H1), `# History` log (H1). See [lifecycle](./spec.lifecycle-protocol.md) | **No** | No | No — carries **gates**, not a per-file stage |

A file that violates its role (e.g., source URL in a `design` file) is a hard violation caught by `spec.doctor`.

**Per-file stage vs gates.** The four authored-doc roles — `design`, `plan`, `bug`, `tech` — carry a per-file `spec_stage` (`empty | draft | approved | rejected | cancelled`; see [lifecycle](./spec.lifecycle-protocol.md) and `spec.set-stage`). The `status` role carries the asset's **flat gate booleans** instead (it is a folder marker, not an authored doc) — see [lifecycle](./spec.lifecycle-protocol.md).

**Path constraints.** `status` files are only permitted at an asset folder-note path (`<spec_path>/<category>/<slug>/<slug>.md`) — never at the product root. `bug` files are only permitted under `<spec_path>/bugs/<slug>/`. `design.md` / `plan.md` live in an asset folder; the product-level `design.md` + `tech.md` are loose at the product root (`<spec_path>/design.md`, `<spec_path>/tech.md`).

### Removed roles

The following roles no longer exist — do not author them, do not reference them:

- **`layout`** — there is no Excalidraw layout doc/role.
- **`human-tasks`** — there is no plugin-managed human-attention dashboard.
- **`*-index`** (`spec-index`, `features-index`, `changes-index`, `bugs-index`, `requests-index`, `backlog-index`) — container index dataview is **operator-zone**, not a plugin role. The plugin defines no `*-index` role.

### Operator-zone folder-notes carry no `spec_role`

Product and category folder-notes (`<spec_path>/<product>.md`, `features/features.md`, `<spec_path>/<category>/<category>.md`, …) are **operator-zone** — same-name-as-folder folder-notes the plugin does not own. They carry **NO `spec_role`** key. The plugin writes only the managed `iconize_icon` / `iconize_color` keys (and reads a category folder-note's `description`); their bodies are operator-owned. See Part 1 above.

The only same-name-as-folder folder-note that DOES carry a `spec_role` is the asset status folder-note (`spec_role: status`).

### Request files

A request file (`<content-root>/requests/<slug>.md`) is free-form user intake captured before classification. It is governed by [request-format](./spec.request-protocol.md) (its own `request_*` frontmatter and lifecycle); it is not part of the `spec_role` closed set.

## Part 3 — File naming, header section, wikilinks

### File naming

Filenames are **role-only** — a plugin-owned spec doc's basename is its role, nothing else — with two folder-note exceptions (status + operator folder-notes carry the parent folder's name) and the request slug exception:

| Role | Filename | Allowed under |
|------|----------|---------------|
| `design` | `design.md` | product root `<spec_path>/` (product-level), `<spec_path>/<category>/<slug>/` (any category except `bugs`) |
| `tech` | `tech.md` | product root `<spec_path>/` (product-level only) |
| `bug` | `bug.md` | `bugs/<slug>/` (bug-report doc; bugs omit design/tech) |
| `plan` | `plan.md` | `<spec_path>/<category>/<slug>/` (asset-level actionable task list) |
| `status` | `<slug>.md` (matches parent asset folder name) | `<spec_path>/<category>/<slug>/` |
| operator folder-note | `<product>.md` / `<category>.md` (matches parent folder name) | product root / category folder root |
| request | `<slug>.md` | `<content-root>/requests/` (vault-wide inbox) |

- No scope suffix, no name prefix, no underscores. `design.md` is just `design.md` everywhere.
- **Exception: the `status` role uses a filename matching its parent asset folder** — `features/chapter-log/chapter-log.md`, `changes/rename-chapter-log/rename-chapter-log.md`. This is the Obsidian folder-note convention: clicking the folder opens this file, and the file itself is hidden in the file tree. An asset folder without its status folder-note has no lifecycle state — `spec.doctor` flags it.
- **Exception: operator folder-notes also use the folder-note convention** — `<spec_path>/<product>.md`, `features/features.md`, `<spec_path>/<category>/<category>.md`. The filename matches the parent folder. These carry NO `spec_role` (operator-zone) and only the managed `iconize_*` keys (plus `description` on category folder-notes) — see Part 2.
- **Exception: the `request` role uses a user-controlled `<slug>.md` filename.** Requests have no per-folder identity, so the slug IS the identity. Slugs are lowercase-with-hyphens, globally unique across the content-root `requests/` inbox. See [request-format](./spec.request-protocol.md).
- Folder names carry identity: product folders, category folders, and asset folders all use lowercase-with-hyphens.
- **Reserved product slugs.** A product folder MUST NOT be named `design` or `tech`: its folder-note (`<product>.md`) would then collide with the product-level `design.md` / `tech.md` that sit loose at the product root. `spec.doctor` flags a product slug in this reserved set.
- Basenames intentionally collide across the vault (every feature and every change has a `design.md`). Collisions are disambiguated by path (in file references) and by the in-file header section (when reading).

### Header section (mandatory in every authored spec doc)

Because filenames are role-only, every authored spec doc carries a structured body header identifying its product / asset and role. Skills generate this header when they create a file; `spec.doctor` enforces it.

**Frontmatter fields** (the keys the plugin reads / writes):

| Field | Applies to | Value |
|-------|-----------|-------|
| `tags` | every file | list of tag paths (includes the product tag + the `spec/<stage>` mirror for stage-bearing docs) |
| `spec_role` | every plugin-owned spec doc | one of the closed set: `design`, `plan`, `bug`, `tech`, `status`. Operator-zone folder-notes carry NO `spec_role` — see Part 2 |
| `spec_stage` | authored docs (`design`, `plan`, `bug`, `tech`) | per-file lifecycle stage, one of `empty | draft | approved | rejected | cancelled`; mirrored to a `spec/<stage>` tag. See [lifecycle](./spec.lifecycle-protocol.md) |
| `spec_design_done` | `status` files only | bool gate — see [lifecycle](./spec.lifecycle-protocol.md) |
| `spec_plan_done` | `status` files only | bool gate |
| `spec_develop_done` | `status` files only | bool gate |
| `spec_tests_passing` | `status` files only | bool gate |
| `spec_released` | `status` files only | bool gate |
| `spec_cancelled` | `status` files only | bool — terminal overlay freezing all gates |
| `spec_source_requests` | every authored doc (`design`, `plan`, `bug`, asset-level `tech`) AND `status` folder-notes | per-doc subset on authored docs / asset-wide union on the folder-note. List of path-qualified wikilinks to request files that contributed (`[]` when created directly). Forward-only; the reverse link lives in the request body. The body's `# Sources` section is a projection of this key — see [sources](./spec.sources-protocol.md) Part 1 |
| `spec_source_docs` | every authored doc | per-doc list of path-qualified wikilinks to companion reference documents. See [sources](./spec.sources-protocol.md) Part 1 |
| `spec_source_branches` | `tech` and `plan` only (when applicable) | per-repo branch pins — see [sources](./spec.sources-protocol.md) Part 2 |
| `iconize_icon` | every folder-note (product / category / asset status) | managed iconize identifier the plugin writes from config — see Part 1 |
| `iconize_color` | every folder-note (when a color is configured) | managed iconize color the plugin writes from config |
| `description` | category folder-notes only | operator-authored prose explaining the category; the plugin only READS it |

Request files carry their own `request_*` frontmatter (see [request-format](./spec.request-protocol.md)), not the keys above.

**Body header**: immediately after frontmatter, every authored doc starts with:

```markdown
# <Title> — <role>

> **<Subsystem>** · **<Product>**[ · **<Asset display name>**] — <role>
```

- `<Title>` is the display name — the product name, asset slug, or status name depending on role.
- The breadcrumb line uses ` · ` as a separator and includes the asset segment only when applicable.
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

> **Tester** · **chapter** · **chapter-log** — design

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
- Bare wikilinks like `[[design]]` or `[[plan]]` are FORBIDDEN because role-only basenames collide by design (every feature has a `design.md`). `spec.doctor` flags any bare wikilink that resolves ambiguously.

Examples:

- `[[Server/Tester/chapter/design|chapter design]]`
- `[[Server/Tester/chapter/features/chapter-log/design|chapter-log design]]`
- `[[Server/Tester/chapter/features/chapter-log/plan|chapter-log plan]]`
- `[[Server/Tester/chapter/changes/rename-chapter-log/design|rename-chapter-log design]]`

Asset folder names are NOT required to be globally unique across products — the wikilink path disambiguates them. Request slugs, by contrast, are globally unique across the single content-root `requests/` inbox.

## Part 4 — Status file (folder-note) shape

Every asset folder (`features/<feat>/`, `changes/<change-name>/`, `bugs/<bug-name>/`) MUST contain exactly one folder-note — a file whose basename matches the parent folder (e.g., `features/chapter-log/chapter-log.md`, `changes/Rename Chapter Log/Rename Chapter Log.md`, `bugs/login-accepts-empty-password/login-accepts-empty-password.md`). It carries the asset's progression in a machine-consumable form for `spec.*` skills. The folder-note is identified by `spec_role: status` in frontmatter; `spec.doctor` also enforces the basename-matches-parent invariant.

The status file owns the asset's **gates** — five flat top-level booleans plus a `spec_cancelled` overlay. There is no `gates:` dict, no `stage:`, no `awaits_human:`, and no `## Workflow` section: the gate booleans are the entire progression model. The authoritative gate semantics — the linear S0..S5 ladder, the precondition table, derived-vs-human-signal mechanics, and the single mutation channel — live in [lifecycle](./spec.lifecycle-protocol.md). This section covers only the file's frontmatter shape and body layout; it does NOT restate the gate rules.

### Status frontmatter schema

The status folder-note carries five flat boolean gates and one overlay flag — no nesting, no `gates:` dict. This matches the shipped per-category template `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/asset-note.md`:

```yaml
---
tags:
  - <product_tag>
  - spec/status
spec_role: status
spec_design_done: false
spec_plan_done: false
spec_develop_done: false
spec_tests_passing: false
spec_released: false
spec_cancelled: false
iconize_icon: <inherited from the asset's category config>
iconize_color: <inherited from the asset's category config>
---
```

- The five gate booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) and the `spec_cancelled` overlay are the asset's whole progression state. Their ladder, preconditions, and flip rules are owned by [lifecycle](./spec.lifecycle-protocol.md).
- `iconize_icon` / `iconize_color` are managed keys, inherited from the asset's category config (the product's `asset_categories` block); they paint the folder icon in the Obsidian file explorer. Not authored by hand.
- This is distinct from the per-file `spec_stage` on sibling authored docs (`design.md` / `bug.md` / `plan.md`) — see [lifecycle](./spec.lifecycle-protocol.md). The folder-note carries gates, not a stage.

### Status body format

The status folder-note body carries three plugin-owned protected H1 sections. There is no title H1, no `## Current`, no `## Workflow`, no `## Log`, no H2-level Gates or History.

Each protected section's **first content line** is the ownership tag `#protected/spec/<region>`. This tag tells every other plugin (reviewer, wiki, etc.) that the section is owned by the spec plugin and must be preserved byte-for-byte across any edit those plugins make to the note.

The three sections in order:

1. **`# Summary`** (`#protected/spec/summary`) — used on asset status folder-notes for a one-line précis of the asset (written by `spec.create-asset` / `spec.product-config` / `spec.add-asset-category` at scaffold time; on container notes it carries `<!-- spec:precis:* -->` and `<!-- spec:stats:* -->` markers filled by `summary_render`). The operator-zone body is below the protected sections.
2. **`# Gates`** (`#protected/spec/gates`) — the callouts written by `bin/flip_gate.py` and `bin/gate_tick.py`. Never any task checkboxes here.
3. **`# History`** (`#protected/spec/history`) — one line per gate or stage transition, appended chronologically. Earlier lines are never rewritten.

```markdown
# Summary
#protected/spec/summary

<one-line précis of the asset>

# Gates
#protected/spec/gates

> [!gate] spec_design_done — flipped 2026-05-01 (auto: design.md approved)

> [!gate] spec_plan_done — flipped 2026-05-02 (auto: plan.md approved)

> [!ready] spec_develop_done ready to flip
> preconditions met: spec_plan_done = true.
> to flip — run `/spec.flip-gate <slug> spec_develop_done`.

# History
#protected/spec/history

- 2026-05-01 — spec.flip-gate · spec_design_done → true
- 2026-05-02 — spec.flip-gate · spec_plan_done → true
```

**Rules**:

- `# Gates` carries the callouts written by `bin/flip_gate.py` and `bin/gate_tick.py` — there are NEVER any task checkboxes here.
  - **`[!gate]`** — appended by `flip_gate` on every flip. Format: `> [!gate] <gate> — flipped <date> (<note>)`. `<note>` is the reason text; an auto-flip (from the `gate-tick` worker) prefixes it with `auto:` — e.g. `(auto: design.md approved)`, or just `(auto)` when no reason is supplied.
  - **`[!ready]`** — dropped once by the `gate-tick` worker for the next human-signal gate whose precondition holds. A three-line block: a `> [!ready] <gate> ready to flip` heading, a `> preconditions met: <prev-gate> = true.` line (or `all derived gates resolved` for the first human-signal gate), and a `> to flip — run \`/spec.flip-gate <slug> <gate>\`.` line.
  - **`[!info]`** — a `[!ready]` block is rewritten in place to `> [!info] readiness withdrawn — <gate> precondition no longer met` when its precondition has since regressed.
- `# History` is one line per gate (or stage) transition, appended chronologically. `flip_gate` writes `- <date> — spec.flip-gate · <gate> → <true|false>`; `spec.set-stage` writes its own per-file stage-transition lines here too. Earlier lines are never rewritten.

### Shared primitives — pointers

Skills touching status files or authored-doc stages use these named primitives rather than restating the mechanics:

- **`spec.flip-gate`** (`bin/flip_gate.py`) — the only writer of gate booleans. Checks the precondition, rewrites the gate in frontmatter, appends the `[!gate]` callout + a `# History` line. See [lifecycle](./spec.lifecycle-protocol.md) → "The single mutation channel".
- **`spec.gate-tick`** (`bin/gate_tick.py`) — the pure md-scan worker that auto-flips derived gates and drops `[!ready]` / `[!info]` callouts. See [lifecycle](./spec.lifecycle-protocol.md) → "The `gate-tick` md-scan worker".
- **`spec.set-stage`** — change a per-file stage on an authored doc; see [lifecycle](./spec.lifecycle-protocol.md). Every per-file stage change in the system MUST go through this primitive.
- **`spec.resolve-dependency`** — resolve a dep entry to `{kind, spec_link, dev_link, local_spec_path?}`; see [sources](./spec.sources-protocol.md) Part 3.
- **`spec.resolve-repo`** — turn a repo-config key into `{local_path, branch, remote_url, host, owner, repo, forge, base_url}` by inspecting the local checkout's git remote and applying the known-forges table; see [sources](./spec.sources-protocol.md) Part 2.
- **`spec.source-url`** — build a forge-correct source URL for `(repo_key, path, kind, branch?)` via the known-forges table. EVERY source URL emitted by any skill or agent MUST go through this primitive; see [sources](./spec.sources-protocol.md) Part 2.

Skills MUST reference these primitive names rather than restate the mechanics.

## Part 5 — Asset sibling topology (from an author-doc's POV)

An author-document lives at `<spec_path>/<category>/<slug>/`. Wherever an agent reads or writes an author-doc, sibling and product-level docs are at predictable relative paths:

| Target | Relative path from an asset's author-doc |
|--------|-------------------------------------------|
| Sibling `design.md` (or `bug.md` for bug-category) | `./design.md` (or `./bug.md`) |
| Sibling status folder-note | `./<slug>.md` (basename = the parent folder name) |
| Sibling `plan.md` | `./plan.md` |
| Product-level `design.md` | `../../design.md` |
| Product-level `tech.md` | `../../tech.md` |

When an agent works over a specific author-doc, the canonical references it needs are usually already listed in that doc's `spec_source_docs` frontmatter — resolving those wikilinks is preferred over reasoning about paths from first principles (the dispatcher materialises the resolved files into the agent's `context/` payload). See [sources](./spec.sources-protocol.md) Part 1.

## Part 6 — Canonical writer per artifact (sanity check)

Every plugin-managed frontmatter key and body section has exactly one writer. Any other agent / skill / human writing to a key or section it does not own is a contract violation; `spec.doctor` and `lazy-core.audit` flag this.

| Artifact | Canonical writer |
|----------|------------------|
| `spec_stage` on any author-doc | `spec.set-stage` (single writer; field changes only through it) |
| `spec_*_done` gates on a status folder-note | `spec.flip-gate` (for derived gates — invoked by `gate-tick` with `--auto`) |
| `spec_source_requests` frontmatter + body `## Requests` sub-section | `spec.request-attach` |
| `spec_source_docs` frontmatter + body `## Docs` sub-section | `spec.create-asset` (initial scaffold) / `spec.refresh-sources` (resync) |
| `iconize_*` on a folder-note | `spec.create-asset` (asset status), `spec.product-config` / `spec.add-asset-category` (product / category folder-notes) |
| Body prose of an author-doc | the operator + lazy-review experts (`main` writer, `validation` writers, `terminal` writer per the doc's review-class) |
| `# History` H1 section in an author-doc inside a review cycle | `lazy-review.historian` |
| `# Sources` H1 section + the `#protected/spec/sources` owner tag | specs writers (`spec.request-attach`, `spec.create-asset`, `spec.refresh-sources`) — never lazy-review, never operator-bypass |

Any attempt by an expert or agent to write into a frontmatter key or body section not owned by it per this table is a contract violation.
