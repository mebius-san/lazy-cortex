---
name: lazy-spec.config-protocol
version: 1
description: Canonical contract for spec product / language config in lazy.settings.json — what the products and spec sections hold and how spec.* skills resolve product and language at runtime.
---
# Config protocol — products, language resolution

Everything the spec system needs to know about products and what language prose is written in lives in one cross-plugin section of `.claude/lazy.settings.json` (`products`) plus one plugin-owned section (`spec`). A product's code lives in the same repository as the spec catalog. This document is the canonical contract for what's in each section, how to read it, and how `spec.*` skills resolve product / language at runtime.

### `spec` settings section — vault root

The `spec` section of `.claude/lazy.settings.json` carries plugin-owned settings. The key relevant to layout is:

| Key | Default | Description |
|-----|---------|-------------|
| `spec.vault_root` | `specs` | Path of the spec content-root relative to the settings-dir (the directory holding `.claude/lazy.settings.json`, i.e. the repo root). All spec content — the operator's product trees and the `requests/` inbox — lives under `<settings-dir>/<spec.vault_root>`. The value must name a sub-directory of the settings-dir: `.` (the settings-dir itself), an absolute path, and a path climbing out through `..` are not allowed — every verb that resolves the content-root refuses such a value with exit 2 and a message telling the operator to move the catalog into a sub-directory and set `spec.vault_root` to it, and `/lazy-spec.install` stops on it. An absent or empty value is the default `specs`. Vault-relative paths (`spec_path`, tags) are relative to this content-root; a wikilink's short form is too, while its vault form carries this segment — see [file-roles](./lazy-spec.file-roles-protocol.md) § Wikilinks. See [layout](./lazy-spec.layout-protocol.md) Part 1 § Spec content-root. |
| `spec.language` | none (optional) | ISO 639-1 language code for spec prose across the vault. When absent the top-level `language` key applies, then the floor `en` — see Part 3 |
| `spec.guidelines` | none (optional) | Catalog-wide guidelines every product inherits, in the same role-keyed shape as `products[<key>].guidelines` (below). They form the outermost layer of each product's per-role union, ahead of its enclosing products and its own, and the catalog-root coordinator reads the `coordinator` and `"*"` roles from here alone. Products standing side by side at the top of the catalog share no ancestor, so this is the one place a guideline reaches them all. |
| `spec.release.implementer_chain` | none (optional) | Ordered list of expert keys — the repository-wide default for which expert leads a release build. The first entry registered in `experts` is the implementer of every release-owning product that sets neither `release.implementer` nor `release.implementer_chain` of its own; a product chain replaces this one entirely, never merging with it. Resolved by `resolve-product release-implementer` (Part 1, product record `release`); a chain with no registered entry yields no implementer. |
| `spec.coordination_rules` | none (optional) | Repo-relative path to the vault-wide operator doc of coordinator rules — the second of the six rule layers `spec.coordinator` reads before every decision (playbook → this doc → product guidelines → product folder-note rules → container folder-note rules → asset folder-note rules; see `lazy-spec.coordination-playbook.md` § 3). States what the coordinator may run automatically across the whole vault, and any vault-wide override of the playbook's defaults. When set, its content is injected into every `spec.coordinator` job's context; `lazy-spec.audit` flags a configured path that doesn't resolve to a file. |

## Part 1 — Config files (products)

Product config is a set of records in `lazy.settings.json` under the `products` section.

### Product records — `lazy.settings.json[products]`

A product's registration is a record under the `products` section of `.claude/lazy.settings.json`, keyed by the product's **compound-key** — an arbitrary stable string the operator chooses at registration (lowercase-with-hyphens recommended). The key is NOT derived from the product's path: `spec_path` says where the product lives, the key says how it is addressed, and the two vary independently — moving the folder never renames the key. The section's `_version` key carries the schema version and is not a product record.

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

There is no `spec.cfg-<product>.md` rule file any more — that form is removed. The product record is read and written atomically via `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get products` / `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set products`, and resolved by the `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product` primitive (below). `/lazy-spec.product-config` is the wizard that creates and edits these records.

| Field | Required | Description |
|-------|----------|-------------|
| `spec_path` | yes | Where the product's specs live, relative to vault root |
| `source.paths` | no | Repo-relative directories of this repository the product's code covers. `source` is `{ "paths": [...] }` and nothing else; it is omitted for a design-only product (specs authored ahead of code) |
| `language` | no (default `en`) | ISO 639-1 language code overriding the repo-global `spec.language`. Skills write narrative prose in this language — see Part 3 (inherited from the nearest ancestor when absent) |
| `icon` | no (default `LiPackage`) | Iconize identifier (Lucide name or emoji) painted on the product folder; mirrored into the product folder-note's managed `iconize_icon`. The wizard writes the default when the operator declines — every product folder-note carries an icon |
| `color` | no (default `#64748b`) | Iconize colour of the product folder, mirrored into the managed `iconize_color`. A product root is the one ordinary container that carries a colour — the neutral one — so the products stand out from the group folders beneath them; the key exists to override that for one product. See § Container colour below |
| `dependencies` | no | List of upstream deps (other products or external tools) — see [sources](./lazy-spec.sources-protocol.md) Part 3 |
| `asset_types` | no | Per-type declarations, merged **key-by-key** over the plugin's shipped spawnable set (`feature`, `change`, `bug`, `content`, `research`, plus `release`, which the product coordinator creates under `releases/` rather than routing spawning it; `references/lazy-spec.asset-types.json` also carries the `catalog` and `product` level entries, which have no `default_path` and spawn nothing), so a product may replace one field of a shipped type without restating the rest, or declare a type of its own. Along a nested product's ancestor chain the same merge runs over each ancestor's declarations in turn, outermost first. Written by `/lazy-spec.add-asset-type`. See below and [layout](./lazy-spec.layout-protocol.md) § Asset types |
| `tool_types` | no | Per-tool declarations, merged key-by-key over the plugin's shipped set (`references/lazy-spec.tool-types.json` — `code`, `data`, `test`, `docs`, `research`). See below |
| `guidelines` | no | Extra context files folded into launch-checkbox job dispatch, keyed by dispatched role token plus the wildcard `"*"` — the union along the ancestor chain, outermost first. See below |
| `release` | no | The product's release section, read where the product owns releases (the outermost product in its chain with a `source`): `release.implementer` names the expert key that leads every build explicitly and wins over any chain; `release.implementer_chain` is an ordered list of expert keys whose first entry registered in `experts` leads the build when no explicit `release.implementer` is set, and replaces the repository's `spec.release.implementer_chain` for this product entirely; with neither key the repository chain applies, and nothing registered means no implementer — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product release-implementer <key>` prints `{"key", "implementer"}` with the result or `null`; `release.manifest` names the repo-relative file whose version field a published release reads and writes (`plugin.json`, `package.json`, `pyproject.toml`, `manifest.json`); `release.deploy.staging` and `release.deploy.production` each take `{ "command": [<argv>], "url": "<address>" }` — the command `release-deploy` runs from the repo root, the optional address shown beside `Publish`. See `lazy-spec.release-playbook.md` |
| `mode` | no (default full) | `"spec-only"` marks a product that owns no releases (`lazy-spec.coordination-playbook.md` Chapter 17, extracted as `lazy-spec.spec-only-playbook.md`): every asset's ladder is design-only as everywhere, `Start release` never hangs, and `spec_released` flips only on the operator's word. Absence means the ordinary ladder. Written by `/lazy-spec.product-config`'s wizard. `_build_bundle` folds the owning product's whole record — `mode` included — into every coordinator job's `payload["product"]` unconditionally, so no separate settings read is needed to detect the profile. (inherited from the nearest ancestor when absent) |

Example product record:

```json
"server-tester-chapter": {
  "spec_path": "Server/Tester/chapter",
  "source": { "paths": [ "chapter", "shared/log" ] },
  "language": "ru",
  "icon": "LiBook",
  "color": "#64748b",
  "dependencies": [ { "product": "server-tester-session" } ],
  "asset_types": {
    "characters": {
      "icon": "LiUsers",
      "color": "#7E57C2",
      "playbook": "characters-playbook",
      "default_path": "characters",
      "start_doc": "design.md:design"
    }
  }
}
```

### Icon and colour — what each axis carries

The **icon** is the type. It says what a note IS — its asset type, its document type, its role — and it comes from that type's own declaration: the `icon` field of `references/lazy-spec.doc-types.json`, of the asset-type registry, or of a product's settings record. **No state ever repaints it.** Every state this catalog tracks — `spec_stage`, `spec_state`, `spec_halted`, `spec_cancelled`, an upstream status, a level gate, a request status — moves the **colour** and nothing else. Accordingly every state matcher in `references/lazy-spec.iconize-registry.json` resolves its icon as `"{{frontmatter.iconize_icon}}"`; the three `spec_role: request` matchers are the sole literal, and they all carry the same `LiMail` because that IS the request type's icon — one icon, three status colours.

**The declaration stays authoritative after scaffolding.** The scaffolding writer puts the icon on the note first, but it is not frozen there: the borrow token names no icon, so the walk always reaches the registry's base band (priorities 147–150), which resolves the pair afresh through the `spec-type-icon` callback. A note whose `iconize_icon` disagrees with what its type declares — because the declaration changed after the note was written — is therefore **corrected on the next reconcile**, keeping the colour its current state deserves. Change a type's `icon` and every existing note of that type follows on the next `iconize-sync reconcile`; a note the callback declines to claim keeps whatever it carries. The full rule is `lazycortex-obsidian:lazy-obsidian.iconize-registry-contract.md` § 3a.

### Container colour

Colour is the state axis: an asset's folder takes its colour from its own `spec_state`, and a document from its stage. A container has no state, so the catalog paints containers on a three-tier rule rather than giving every shelf a colour it cannot mean.

| Container | Colour |
|---|---|
| Product root (`<spec_path>/<leaf>.md`) | Neutral `#64748b` — `products[<key>].color` overrides it |
| Ordinary group folder (`changes/`, `bugs/`, any declared type's `default_path`, any ad-hoc folder) | None. The note carries `iconize_icon` and no `iconize_color` at all |
| Intake shelf — the vault-root request inbox (`requests/requests.md`) and every upstream note (`upstream/upstream.md`, `upstream/<repo-key>/<repo-key>.md`) | Accent `#f0abfc` |

The accent is deliberate and is the one place a colourless-shelf rule is broken: intake is where unprocessed material lands, so those folders have to be findable at a glance in a file explorer full of grey. `#f0abfc` is chosen to sit outside the state palette entirely, so an intake shelf can never be misread as an asset in some state.

A group folder's own type may still declare a `color` — it reaches that type's asset status notes as their seed, never the group folder-note.

### `products[<key>].asset_types` — declared asset types

Each key is a type name — the value an asset status folder-note's `spec_asset_type` carries. Each value is an object:

| Field | Required | Description |
|---|---|---|
| `icon` | yes | Iconize identifier painted on the type's folder and on every asset folder of the type (mirrored into the managed `iconize_icon` key) |
| `color` | no | Iconize colour seeded onto every asset status folder-note of the type, mirrored into the managed `iconize_color` key. It does NOT reach the type's own group folder — an ordinary container carries no colour (§ Container colour) |
| `playbook` | yes (unless `alias_of`) | Reference key of the playbook `spec.coordinator` loads on every wake of an asset of this type |
| `alias_of` | no | Names a base type whose playbook this type borrows when it declares none of its own. The folder, icon, colour, start document and tools stay this type's own, aliases never chain, and `release` is never a base |
| `default_path` | no | Folder name under `<spec_path>/` where assets of this type land unless the caller names another location |
| `start_doc` | yes | `"<file>:<doc_type>"` token naming the one document a fresh asset of the type is seeded with (e.g. `design.md:design`, `bug.md:bug`). A type with no `start_doc` cannot be scaffolded at all. `release` is the one type whose start document is opt-in: `code-plan.md:code-plan` is declared, but the release note is created alone and the plan arrives through its `Write code-plan` row |
| `vision` | no | The type's `vision.md` contract: `opt-in` (the shipped `feature`, `change` and `content` — the operator may launch one, nothing requires it), `none` (the shipped `bug`, `research` and `release` — the type carries no vision), or `mandatory` (no shipped type; an operator-declared type only — `vision.md:vision` is seeded in place of the start document, which waits for the vision's approval); an undeclared field reads as `opt-in` (`lazy-spec.layout-protocol.md`). Read by `lazy-spec.create-asset`, `lazy-spec.create-from-code` and the type playbooks; no script validates it |
| `default_tools` | no | Tool-type names an asset of this type is realised and checked with; written into the status folder-note's `spec_tools` at scaffold time |
| `guidelines` | no | Repo-relative file paths every expert job on an asset of this type carries, whatever role it dispatches — folded after the role's own `products[<key>].guidelines[<role>]` paths and before the wildcard `"*"` ones. This is where a content type declares the schema its records are written against: the designer writing a content design, the data writer validating it and later writing the data all read the same files. Merges like every other field — the nearest declaration wins whole |

**Merge rule: key-by-key over the shipped declaration, never whole-record replacement.** `{"bug": {"icon": "LiSkull"}}` repaints the shipped `bug` type and leaves its `default_path`, `start_doc`, and `playbook` exactly as shipped.

The declaration is the whole of what a type is: the folder is a place, not a fact. An asset's kind is the `spec_asset_type` key on its own status folder-note, and everything that resolves the asset's law reads that key, never the path. `/lazy-spec.add-asset-type` writes the declaration and an own-playbook stub and nothing else — no folder, no folder-note, no templates. The type's folder appears the first time `lazy-spec.create-asset` scaffolds an asset into it.

### `products[<key>].tool_types` — declared tool types

Each key is a tool name — the value an asset's `spec_tools` list carries. Each value is an object:

| Field | Required | Description |
|---|---|---|
| `playbook` | yes | Reference key of the playbook the coordinator loads when driving this tool's work on an asset |
| `report_doc` | yes | Document type of the tool's report — an append-only execution journal for `code` / `test` (e.g. `code-report`), a stage-bearing deliverable for `research` (`research-report`). For `data` / `docs` it only names the review class whose main writer is the tool's expert; a release build journals their work in `code-report.md` |
| `plan_doc` | no | Document type of the tool's plan. Its presence is what hangs the `Write <tool>-plan` launch checkbox; a tool without `plan_doc` gets no plan checkbox |

The shipped set is `code` (`code-plan` / `code-report`), `data` (`data-report`), `test` (`test-plan` / `test-report`), `docs` (`docs-report`), and `research` (the research report written from the approved research design; its report type carries a stage).

Per-product doc-template overrides are NOT declared in the record. The override signal is **folder presence** under `.claude/templates/` — a per-product override folder `spec.<type>/<compound-key>/`, and the consumer's own type baseline `spec.<type>/`. Resolution is per-file across a six-layer chain plus one override layer per ancestor product, so a type needs no template folder of its own to be scaffoldable, and an override folder may contain only the files that differ. See [layout](./lazy-spec.layout-protocol.md) Part 1 § Template storage for the full layer order.

### `products[<key>].guidelines` — expert-job context paths

A product record MAY carry a `guidelines` dict supplying extra context to every expert job dispatched on the product's documents — the writer rounds a `Write <doc>` row opens (`Write design`, `Write test-plan`, `Write architecture` on a product note, `Write code-plan` on a release note, `Start research` on a research asset) and the release's build jobs (`Revise architecture`, `Build`, `Test`), and the writer and validator rounds `lazycortex-review`'s coordinator dispatches on a document under review (every `Write <doc>` row ends in such a round, so a design's author reads the product's guidelines for its role the same way an implementer does):

```json
"guidelines": {
  "architect": [ "docs/guidelines/architecture.md", "docs/structure.md" ],
  "planner": [ "docs/guidelines/planning.md" ],
  "tester": [ "docs/guidelines/testing.md" ],
  "developer": [ "docs/guidelines/coding.md" ],
  "coordinator": [ "docs/guidelines/coordination.md" ],
  "*": [ "docs/guidelines/house-style.md" ]
}
```

| Key | Description |
|---|---|
| `architect` | Guideline paths folded into the product's `Write architecture` row and into the `Revise architecture` job of every release build — this is also the blessed route for handing the architect an operator-declared `docs/structure.md` project-structure map (`lazy-spec.coordination-playbook.md` Chapter 8), when the operator wants it injected as job context instead of left to the architect's own pull-skill query. |
| `planner` | Guideline paths folded into a release's `Write code-plan` row. |
| `tester` | Guideline paths folded into every `Write test-plan` row — an asset's test cases, the product's standing plan, a release's composed plan — and into a release's `Test` job; all dispatch under the `tester` role. |
| `developer` | Guideline paths folded into a release's `Build` job, led by the release implementer (`resolve-product release-implementer`), and handed on to the child agents it delegates foreign tools to. |
| `researcher` | Guideline paths folded into the research type's `Start research` writer row. |
| `coordinator` | Guideline paths folded into every `spec.coordinator` job dispatched for this product's assets — the third of the six rule layers the coordinator reads before deciding (see `lazy-spec.coordination-playbook.md` § 3). Distinct from a product, container, or asset folder-note's `# Coordinator rules` section: this key names files, the folder-note sections carry operator-authored prose directly. |
| `designer`, `data-writer`, … | Guideline paths folded into every review round a `<domain>.<role>` expert of that role writes on the product's documents — the role token is the expert key's part after the first dot. Any role token a registered expert carries is valid here. |
| `*` | Guideline paths folded into every expert job for this product, regardless of role. |

Values are lists of repo-relative file paths, read literally — no glob expansion. Each path that resolves to a file is named in the dispatched job's context so the expert reads it in the working tree; a declared path that does not resolve to a file is never silently skipped — it is recorded as a warning in the dispatch result and journaled in the asset's `# History` as a job that failed to start. The key is entirely optional: a product record with no `guidelines` key dispatches jobs with the catalog-wide `spec.guidelines` and its ancestors' guidelines alone, or with no extra context when neither is declared. The effective list for a role is the ordered union catalog first, then enclosing products outermost first, then the product's own, with a path already listed never repeated; the paths a job carries are the role's own first, then the dispatched asset's `asset_types[<type>].guidelines`, then the wildcard set.

### `products[<key>].doc_types` — project-declared document types

A product record MAY carry a `doc_types` dict declaring document types beyond the ones the plugin ships in `references/lazy-spec.doc-types.json`, or adjusting the flags of a shipped one:

```json
"doc_types": {
  "content-report": { "review": true, "append_only": true },
  "system-tech":    { "review": false }
}
```

Each key is a type name — the value a document's `spec_doc_type` carries. Each value is an object whose fields are all optional:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `stages` | boolean | `false` | The document carries `spec_stage`, and is the only kind `lazy-spec.set-stage` accepts. |
| `review` | boolean | `false` | The document goes through the review loop under a class of the same name; `lazy-spec.install` seeds that class for a shipped type, and the operator adds it through `/lazy-review.configure` for any other. |
| `append_only` | boolean | `false` | The file is only ever appended to, never rewritten. |
| `icon` | string | absent | Iconize identifier a document of the type is seeded with at creation, written into its managed `iconize_icon`. |
| `color` | string | absent | Iconize colour paired with the icon, written into the managed `iconize_color`. |

**Merge rule: key-by-key over the shipped declaration, never whole-record replacement.** `{"system-tech": {"review": false}}` turns review off for `system-tech` and leaves its `stages: true` and its `template` exactly as shipped. A type the plugin does not ship is declared from scratch, so every field it omits takes the `false` / absent default — `{"content-report": {"review": true, "append_only": true}}` is a review-bearing, append-only, non-staged document, which is a complete declaration and not an error.

**`icon` / `color` are the document's kind half of the paint contract.** The seed says what kind of document this is; the iconize registry's matchers say what state it is in and own the colour from the first `lazy-spec.set-stage` onward. A stage-less type — a journal, the decisions registry — is never claimed by any matcher, so its seed is the only paint it will ever carry; a stage-bearing type shows the seed only until its first stage lands. This is why the registry enumerates no document kinds at all: a project type declares its own paint here and needs no registry edit.

The key is entirely optional: a product with no `doc_types` sees exactly the shipped set, whatever `references/lazy-spec.doc-types.json` currently declares — the file is the count, never a number repeated in prose that a later type silently invalidates. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type list --product <key>` prints the merged set, `doc-type resolve <type> --product <key>` one merged declaration.

> The word `spec` in skill names (`spec.*`) refers to the overall specification system. It is unrelated to the per-file `design` role introduced elsewhere.

## Part 2 — Product resolution

### Resolving a Product

Product resolution goes through the `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product` primitive, which reads the `products` settings section directly. Four modes — two raw, two inherited:

- **by-key** — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product by-key <key>` returns `{"key": <key>, "record": <record-or-null>}`. A direct record fetch by the exact compound-key.
- **by-path** — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product by-path <path>` returns `{"key": <owning-key-or-null>, "record": <record-or-null>}`. The `<path>` argument is resolved relative to the content-root (`<settings-dir>/<spec.vault_root>`); a repo-relative path that begins with the vault-root segment (e.g. `specs/Server/Tester/chapter/foo`) is accepted too. When that leading segment could also be a product's own first segment (a product at `specs/assets` under the `specs/` root), the reading that exists on disk wins; when neither or both exist, the reading a product claims more deeply wins, and a tie drops the segment. Finds the product whose `spec_path` equals the normalised path or is a segment-wise prefix of it; when several products nest, the longest matching `spec_path` wins. Segment-wise matching means `A/B` owns `A/B/x` but not `A/Bx/...`, so it transparently covers the product's standard subtree (`<spec_path>/<feat>/...` for a feature at the product root, `<spec_path>/changes/<change-name>/...`, `<spec_path>/bugs/<bug-name>/...`) and the product-root files (`<spec_path>/<product>.md` folder-note, `<spec_path>/design.md`, `<spec_path>/tech.md`). Request files are NOT under a product — they live in `<content-root>/requests/` — so `resolve-product by-path` never attributes them to a product.
- **effective** — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product effective <key>` returns the same `{"key", "record"}` shape as `by-key`, the record replaced by `resolve_product.effective_record` — every key the product does not declare taken from its nearest declaring ancestor (see § Effective record). An unregistered key still yields `{"key": <key>, "record": null}` and exit 0.
- **effective-by-path** — `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-product effective-by-path <path>` attributes `<path>` exactly as `by-path` does and returns that product's effective record.

**Which verb to use.** A reader that acts on a product's configuration — its `asset_types`, `doc_types`, `tool_types`, `guidelines`, `language`, `mode` — asks for the `effective` pair, so a nested product never looks unconfigured for a key its parent declares. The raw `by-key` / `by-path` pair is for a caller that writes the record back, where only the product's own declarations may be edited.

`spec.*` skills follow this protocol:

1. Resolve the user's input to a product. Try in order: exact compound-key (`resolve-product by-key`); a `spec_path` exact-or-sub-path match (`resolve-product by-path`); a `source.paths` entry match; then a **bare-name fallback** — if the input matches exactly one record key's trailing `-<input>` suffix, resolve it. If two or more records match the bare name, abort the non-interactive path AND prompt the user via `AskUserQuestion` to pick (options = the full keys of the candidates).
2. A `null` record means the product is not registered. Tell the user and suggest registering it via `/lazy-spec.product-config`.

**Products may nest**: a product's `spec_path` may sit under another product's `spec_path`. Ownership of any path is the innermost product — the longest matching `spec_path` — so an enclosing product never claims a nested product's own documents or assets, and a nested product's cross-asset tokens resolve against its own root (see [folder-structure](./lazy-spec.layout-protocol.md)).

**Releases are owned by the outermost product in the chain that declares a `source`.** A product nested under such an owner owns no releases: its approved assets enter the owner's delta, the owner's release sets their `spec_released`, and it has no `releases/` folder. A nested product may declare a `source` of its own when its paths lie inside its parent's source paths; that `source` only narrows the code area for `sync-with-code` and the audit, and the product still owns no releases. Only a nested `source` naming a path outside the parent's source paths is a configuration error — `lazy-spec.product-config` refuses it at registration and `lazy-spec.audit` reports it (`resolve_product.find_all_own_source_conflicts`, the `own-source-conflicts` mode of `resolve-product`). A product without `source` is a design-only umbrella, and products with their own `source` under it each own their releases; the path rule holds only inside an owner. A separate deliverable is registered as a product beside the owner and linked through `dependencies`.

### Effective record

A nested product's record is read through `resolve_product.effective_record`: every key it does not declare is taken from the nearest ancestor that declares it. `asset_types` merges key-by-key from the outermost ancestor down to the product's own; `guidelines` is the per-role ordered union along the same chain; `mode` and `language` take the nearest declaration. `source`, `dependencies`, `icon` and `color` are never inherited — a code binding, a dependency list and a paint belong to one product. The ancestor chain is derived from `spec_path` prefixes (`resolve_product.ancestor_chain`, outermost first); no key records a parent. The template chain gains one per-product override layer per ancestor between the product's own and the project-wide layer, innermost first.

The same innermost-wins reading governs review routing: among the `<type>@<product>` review classes whose `paths` cover a typed document, the one whose globs anchor on the most leading literal segments — the innermost product's — takes the document, so a nested product's own class outranks its ancestor's (`doc_class._scope_depth`; see [lazy-review.configure](../../lazycortex-review/skills/lazy-review.configure/SKILL.md)).

### Spec Roots

Each product's `spec_path` is its spec root. Self-containment holds **between sibling roots**: skills work within a single spec root at a time and never cross-reference state files sideways, between roots neither of which contains the other. A nested root does read **upward** along its ancestor chain — the ancestors' effective records, their level notes, their guidelines and their template layers — because an ancestor's tree contains its own. Upward is inheritance; sideways is the thing that never happens.

## Part 3 — Language resolution

A spec doc's effective prose language is resolved through a fallback chain (first non-empty wins), via the `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-language <relpath>` primitive:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's effective `language` — its own `language` field in `products[<key>]` (`lazy.settings.json`), else the nearest ancestor product's, as `resolve_product.effective_record` merges it;
3. the `spec` settings section's `language` key;
4. the top-level `language` key in `lazy.settings.json` (repo-wide default, shared with the other plugins);
5. the hardcoded floor `en`.

Skills that write or edit spec content MUST honour the resolved language (ISO 639-1).

**Translated** — narrative prose: `## Overview` body, paragraph text, free-form bullets that describe behavior or rationale, the group folder-note `description`, and free-text portions of history entries.

**NOT translated — always kept as English identifiers**:

- ALL frontmatter keys and values (e.g., `spec_role: design`, `spec_stage: draft`).
- Role words in the body header — the `<role>` in the `# <Title> — <role>` line.
- Fixed section headers — `# Summary`, `# Gates`, `# History` (H1 on the status folder-note), `## Overview`, `## Way to reproduce`, etc. (H2/H3 on authored docs). Skills use the canonical English heading even when the body below is localized.
- Review-class `class` labels and section ids.
- Source URLs and wikilink targets — the part before `|` in `[[path|display text]]` stays English; the display text MAY be translated.
- Code blocks, command snippets, function/class names, file names.
- Product and asset names, and every other folder name — they are path segments.
- Product-specific terminology (entity names, domain nouns) that appear in source code or product config.

**Skill behavior**:

- Resolve the effective language via `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> resolve-language <relpath>` (the five-rung chain above). If unresolvable, treat as `en`.
- When generating new prose, write in that language.
- When editing existing prose, keep the existing language — do not retranslate.
- No linguistic validation is attempted.

## Part 4 — Upstream sources (`spec.upstream`)

`upstream/` mirrors one or more foreign git repos' design content into this repository at the
**repository root** — a sibling of the content-root, never a subtree of it, and so outside the
product hierarchy entirely (see [file-roles](./lazy-spec.file-roles-protocol.md) § Upstream unit notes: a
mirrored source is not vault content until Phase C's request accepts it in). Every `upstream/…`
path in this Part is therefore repo-root-relative, unlike the vault-relative paths the rest of
this protocol uses. Configuration lives in the plugin-owned `spec` settings section, under
`spec.upstream`:

```json
"spec": {
  "upstream": {
    "max_units_per_tick": 7,
    "max_text_file_bytes": 1048576,
    "fetch_failure_threshold": 5,
    "product-docs": {
      "url": "git@github.com:example-org/product-docs.git",
      "branch": "main",
      "mounts": {
        "specs": {
          "source_path": "specs",
          "units": [ "features/*", "services/*" ],
          "exclude": [ "features/_shared" ]
        }
      }
    }
  }
}
```

| Key | Scope | Required | Description |
|-----|-------|----------|-------------|
| `max_units_per_tick` | whole `upstream` section | no (default `7`) | Ceiling on units the `lazy-spec.upstream-tick` routine does actual work on in one tick, shared across every configured source — not per-mount. A unit that needed no work (already `processed`, unchanged) is free and does not spend the budget. |
| `max_text_file_bytes` | whole `upstream` section | no (default `1048576`) | Per-file size ceiling above which a source file mirrors as skipped (`too-large`), passed straight through to the `remote-mirror` core primitive's `max_bytes`. |
| `fetch_failure_threshold` | whole `upstream` section | no (default `5`) | Consecutive tick failures a source may accumulate before its fetch state reads as failing (source-note bookkeeping; not consumed by the Task 4 fetch/detect phase — see `upstream_tick.py`'s module docstring). |
| `<repo-key>` | one entry per source | — | Any key not in the reserved set above (`max_units_per_tick`, `max_text_file_bytes`, `fetch_failure_threshold`) names one upstream source. Renaming a `<repo-key>` or a mount is a manual operation — the key is encoded into the mirror path at the repository root (`<repo-root>/upstream/<repo-key>/<mount>/...`). |
| `<repo-key>.url` | per source | yes | Git URL (or local path) `remote-mirror` clones/fetches. |
| `<repo-key>.branch` | per source | no | Branch to track; absent follows the remote default. |
| `<repo-key>.mounts.<mount>.source_path` | per mount | yes | Path inside the source repo this mount roots at. |
| `<repo-key>.mounts.<mount>.units` | per mount | yes | Glob patterns (relative to `source_path`) whose each match is one whole unit directory — `*` matches within one path segment, `**` matches zero or more whole segments, mirroring the `remote-mirror` primitive's own glob semantics. Directories above a match contribute only path segments; their own content is never mirrored. Two `units` patterns matching an overlapping (nested or identical) directory is a per-mount refusal — that mount is skipped for the tick, every other configured mount and source still runs. |
| `<repo-key>.mounts.<mount>.exclude` | per mount | no | Same-shaped globs excluding matches out of `units`, checked before the fetch/detect phase's own orphaned-vs-excluded distinction. |

The working clone lives at `.runtime/lazy-specs/upstreams/<repo-key>/` (gitignored runtime scratch,
never a tracked path) — one clone per `<repo-key>`, shared across every mount that source
declares. If a clone already exists there, the fetch phase compares `git remote get-url origin`
against the configured `url`; a mismatch is reported as a fetch error for that source (the clone
is never re-pointed or deleted automatically) rather than silently fetching the wrong repo.

**Registration** happens by hand-editing this section (or a future `/spec.upstream-config`
wizard, not yet built) — `lazy-spec.install` only registers the `lazy-spec.upstream-tick` schedule routine
once at least one `<repo-key>` entry is present, and re-checks on every re-run so a source added
later still gets the routine wired without re-invoking install from scratch.

**Manual run** — `/lazy-spec.upstream-run` drives the same fetch/detect primitive the routine calls,
for an operator who wants to see the result immediately instead of waiting for the next tick.

**Ignore handling** honors only git's own mechanism, on both sides: `remote-mirror`'s
`git ls-files` over the source clone means anything the source's own `.gitignore` excludes is
never fetched, and a freshly-synced file the vault's own `.gitignore` would also ignore is pulled
back out into the skip list. The core plugin's `.lazyignore` convention (`repo_walk.RepoWalk`) is
never consulted for either side — it hides a path from the runtime's tree walks, not from git, so
the vault's commit still carries a file it lists.

## Part 5 — Upstream unit enumeration

Each tick's unit list is the union of two trees, not the source tree alone: every directory the
configured `<mount>.units` globs currently match in the freshly-fetched source, plus every unit
directory that already exists under the repository root's `upstream/<repo-key>/<mount>/` path from
a prior tick. Deduplicated by unit identity `(repo-key, mount, unit-path)` and sorted for tick-to-tick
stability.

The union is what lets the fetch/detect phase tell `excluded` and `orphaned` apart, both of which
would otherwise be invisible from one side alone:

- A unit present in the vault but no longer matched by the source-side glob (dropped from
  `units`, or newly caught by `exclude`) is `excluded` — enumerating from the source tree only
  would never surface it, since it no longer matches there.
- A unit present in the vault whose directory has vanished from the source repo entirely is
  `orphaned` — enumerating from the vault tree only would still catch it, but conflating the two
  trees without tracking provenance would misreport it as freshly matched.

A unit that exists on the source side but has never landed in the vault is simply `new` — the
source tree is where it is discovered.

## Part 6 — Wizard-question explanation standard

Every `AskUserQuestion` call issued by a `spec.*` skill MUST be authored as a full-context block so a user seeing the field for the first time can answer without reading any other doc. Short one-line questions ("Language?", "Workflow overrides?") are forbidden — they force the user to guess what is being asked.

A conforming wizard question has four parts:

1. **Question stem** (2–3 sentences) — name the field, state what it controls, and state when/where the value takes effect. Refer to terminology introduced elsewhere in `${CLAUDE_PLUGIN_ROOT}/references/` by its exact name so the user can search for it.
2. **Why it matters** (1 sentence) — the concrete consequence of the choice. What breaks, what changes, or what downstream skill reads this value.
3. **Per-option copy** — each `AskUserQuestion` option MUST carry a 1-sentence consequence + a concrete example. Never rely on the option label alone. If two options differ only in a tradeoff, state the tradeoff explicitly ("faster to set up, harder to extend later" vs. "more upfront work, cleanly versioned").
4. **Pointer** — the trailing line `See: ${CLAUDE_PLUGIN_ROOT}/references/<file>.md` pointing at the reference doc that owns this field's semantics. Always use the reference path, not a skill path — skills are callers, not the source of truth.

Example (for the `default path` question in `lazy-spec.add-asset-type`):

```
Question stem:
  asset_types.<name>.default_path names WHERE lazy-spec.create-asset scaffolds
  an asset of this type when the caller names no folder of its own: "." is the
  product root itself, and any other value is a group folder under the
  product's spec_path, created lazily on the first asset that lands in it.

Why it matters:
  It is a convenience for whoever creates the asset, NOT a fact of the type —
  type resolution reads spec_asset_type off the status folder-note and never a
  path, so a single asset may be placed anywhere under spec_path (including
  inside another asset's folder) with --path and nothing downstream breaks.

Options:
  - .                 — the product root itself, so the assets sit loose beside
                        the product's own documents. Example: the shipped
                        "feature" type, landing at <spec_path>/<slug>/.
  - characters        — the pluralised type name, a group folder of its own.
                        Example: a "character" type whose assets collect under
                        <spec_path>/characters/.
  - alongside scenes  — reuse a folder an already-declared type uses, when the
                        two kinds genuinely share a shelf. Example: variant
                        types of the same narrative unit.
  - none              — declare no default_path; the scaffold falls back to the
                        type's own name. Example: a type whose assets are always
                        created with an explicit --path anyway.

See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md
```

Skills invoking `AskUserQuestion` are responsible for rendering this block into the tool's `question` and per-option `description` fields. The stem + why + pointer go into `question`; the per-option copy goes into each option's `description`. Never drop the pointer — it is the user's escape hatch when the wizard explanation is still unclear.
