---
name: spec.config-protocol
version: 1
description: Canonical contract for spec product / repo / language config in lazy.settings.json — what the products, repos, and spec sections hold and how spec.* skills resolve product, repo, and language at runtime.
---
# Config protocol — products, repos, language resolution

Everything the spec system needs to know about products, source repos, and what language prose is written in lives in two cross-plugin sections of `.claude/lazy.settings.json` (`products`, `repos`) plus one plugin-owned section (`spec`). This document is the canonical contract for what's in each, how to read it, and how `spec.*` skills resolve product / repo / language at runtime.

### `spec` settings section — vault root

The `spec` section of `.claude/lazy.settings.json` carries plugin-owned settings. The key relevant to layout is:

| Key | Default | Description |
|-----|---------|-------------|
| `spec.vault_root` | `specs` | Path of the spec content-root relative to the settings-dir (the directory holding `.claude/lazy.settings.json`, i.e. the repo root). All spec content — subsystem folders and the `requests/` inbox — lives under `<settings-dir>/<spec.vault_root>`. Use `.` to place content directly at the settings-dir (content-root = settings-dir). Vault-relative paths (`spec_path`, wikilinks, tags) are relative to this content-root. See [layout](./spec.layout-protocol.md) Part 1 § Spec content-root. |

## Part 1 — Config files (products + repos)

Product config and repo config are both records in `lazy.settings.json`: products under the `products` section, repos under the cross-plugin `repos` section.

### Product records — `lazy.settings.json[products]`

A product's registration is a record under the `products` section of `.claude/lazy.settings.json`, keyed by the product's **compound-key** `<subsystem>[-<namespace>]-<product>`, where each segment is the corresponding vault folder name lowercased-with-hyphens. The namespace segment is present iff the product sits under an optional grouping folder; omitted when the product sits directly under its subsystem. Example: product folder `Server/Tester/chapter` → key `server-tester-chapter`. The section's `_version` key carries the schema version and is not a product record.

There is no `spec.cfg-<product>.md` rule file any more — that form is removed. The product record is read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`, and resolved by the `lazycortex-specs resolve-product` primitive (below). `/spec.product-config` is the wizard that creates and edits these records.

| Field | Required | Description |
|-------|----------|-------------|
| `spec_path` | yes | Where the product's specs live, relative to vault root |
| `source.repo` | no | Key of the repo config this product's source lives in (e.g., `backend`). Omitted for a design-only product (specs authored ahead of code) |
| `source.paths` | no | Subdirectories within that repo the product covers. Present iff `source` is present |
| `language` | no (default `en`) | ISO 639-1 language code overriding the repo-global `spec.default_language`. Skills write narrative prose in this language — see Part 3 |
| `icon` | no | Iconize identifier (Lucide name or emoji) painted on the product folder; mirrored into the product folder-note's managed `iconize_icon` |
| `dependencies` | no | List of upstream deps (other products, repos, or external) — see [sources](./spec.sources-protocol.md) Part 3 |
| `asset_categories` | no | Operator-defined categories beyond the built-in set, as `{<name>: {icon: <icon>, color?: <hex>}}`. See [folder-structure](./spec.layout-protocol.md) |
| `handoff.stop_after` | no | Marks this product as a cross-repo handoff source (spec-repo side). One of the five flat gates; default `spec_design_done` when `handoff` is present without an explicit `stop_after`. See Part 4 |

Example product record:

```json
"server-tester-chapter": {
  "spec_path": "Server/Tester/chapter",
  "source": { "repo": "backend", "paths": [ "chapter", "shared/log" ] },
  "language": "ru",
  "icon": "LiBook",
  "dependencies": [ { "product": "server-tester-session" } ],
  "asset_categories": { "characters": { "icon": "LiUsers", "color": "#7E57C2" } }
}
```

Per-product doc-template overrides are NOT declared in the record. The override signal is **folder presence** under `.claude/templates/spec.<category>/<compound-key>/` (one optional override folder per category). Resolution is **per-file fallback** — for each individual template file the resolver checks `spec.<category>/<compound-key>/` first and falls back to the category's top-level template (`spec.<category>/<file>`) when the file is absent. An override folder may contain only the files that differ; anything missing transparently resolves to the category-level copy. See [layout](./spec.layout-protocol.md) Part 1 § Template storage.

### Repo records — `lazy.settings.json[repos]`

Repo records live in the cross-plugin `repos` section of `.claude/lazy.settings.json`, symmetric to `products[]`. The section maps a symbolic `<repo-key>` to runtime metadata for one local checkout. It is read and written atomically via `lazycortex-core settings-get repos` / `lazycortex-core settings-set repos`, and resolved by the `spec.resolve-repo` primitive. The `repos` section is registered in lazy-core's `CURRENT_VERSIONS` and auto-initializes on first `settings-get`; `/spec.product-config` (inline repo wizard) is the wizard that writes records. Being cross-plugin (top-level, not under a plugin namespace), the section is also available to other plugins that need repo metadata.

```yaml
repos:
  _version: 1
  backend:
    local_path: /abs/path/to/backend
    branch: main
    # forge: gitea            # optional — override for self-hosted hosts; else auto-detected from the remote URL
  shared:
    local_path: /abs/path/to/shared
    branch: master
  self:                       # same-repo product — code lives in this very repo
    local_path: "."           # expands to `git rev-parse --show-toplevel` per checkout
    branch: master
    forge: github             # explicit when the remote host isn't auto-detected
```

| Field | Required | Description |
|-------|----------|-------------|
| `local_path` | yes | Absolute path to the local checkout, **or `"."` — the repo containing this settings file** (same-repo products); `spec.resolve-repo` expands `"."` to `git rev-parse --show-toplevel` so each checkout resolves to its own root |
| `branch` | yes | Branch to link against (typically `main` / `master`). Skills compare against this as the repo's default when reconciling pins |
| `forge` | no | Forge key override (`github` / `gitlab` / `bitbucket` / `gitea` / `forgejo` / `sourcehut`). Needed ONLY when the hostname on the local checkout's git remote is not in the known-forges table (e.g., self-hosted GitLab / Gitea). For well-known hosts, omit this field — the forge is auto-detected |

Repo records DO NOT carry the repo's URL. The URL is derived at runtime from the local checkout's git remote (`git -C <local_path> remote get-url origin`) via the `spec.resolve-repo` primitive — see [sources](./spec.sources-protocol.md) Part 2.

> The word `spec` in skill names (`spec.*`) refers to the overall specification system. It is unrelated to the per-file `design` role introduced elsewhere.

## Part 2 — Product / repo resolution

### Resolving a Product

Product resolution goes through the `lazycortex-specs resolve-product` primitive, which reads the `products` settings section directly. Two modes:

- **by-key** — `lazycortex-specs resolve-product by-key <key>` returns `{"key": <key>, "record": <record-or-null>}`. A direct record fetch by the exact compound-key.
- **by-path** — `lazycortex-specs resolve-product by-path <path>` returns `{"key": <owning-key-or-null>, "record": <record-or-null>}`. The `<path>` argument is resolved relative to the content-root (`<settings-dir>/<spec.vault_root>`); if the caller supplies a path that begins with the vault-root segment (e.g. `specs/Server/Tester/chapter/features/foo`), that leading segment is stripped before matching. Finds the product whose `spec_path` equals the normalised path or is a segment-wise prefix of it; when several products nest, the longest matching `spec_path` wins. Segment-wise matching means `A/B` owns `A/B/x` but not `A/Bx/...`, so it transparently covers the product's standard subtree (`<spec_path>/features/<feat>/...`, `<spec_path>/changes/<change-name>/...`, `<spec_path>/bugs/<bug-name>/...`) and the product-root files (`<spec_path>/<product>.md` folder-note, `<spec_path>/design.md`, `<spec_path>/tech.md`). Request files are NOT under a product — they live in `<content-root>/requests/` — so `resolve-product by-path` never attributes them to a product.

`spec.*` skills follow this protocol:

1. Resolve the user's input to a product. Try in order: exact compound-key (`resolve-product by-key`); a `spec_path` exact-or-sub-path match (`resolve-product by-path`); a `source.paths` entry match; then a **bare product-name fallback** — if the input matches exactly one record's trailing `-<product>` segment, resolve it. If two or more records match the bare name, abort the non-interactive path AND prompt the user via `AskUserQuestion` to pick (options = the full compound keys of the candidates).
2. A `null` record means the product is not registered. Tell the user and suggest registering it via `/spec.product-config`.
3. Resolve the product's `source.repo` (when present) against the repo configs via `spec.resolve-repo` to get `{local_path, branch, host, owner, repo, forge, base_url, …}`.

**Products are flat**: a product's `spec_path` MUST NOT be a sub-path of another product's `spec_path`. Nested products are forbidden — see [folder-structure](./spec.layout-protocol.md) for how to group related products using namespace folders.

### Spec Roots

Each product's `spec_path` is its spec root. Each spec root is self-contained — skills work within a single spec root at a time. Never cross-reference state files between roots.

## Part 3 — Language resolution

A spec doc's effective prose language is resolved through a four-step fallback chain (first non-empty wins), via the `lazycortex-specs resolve-language <relpath>` primitive:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's `language` field in `products[<key>]` (`lazy.settings.json`);
3. the `spec` settings section's `default_language` key (repo-global default);
4. the hardcoded floor `en`.

Skills that write or edit spec content MUST honour the resolved language (ISO 639-1).

**Translated** — narrative prose: `## Summary` body, paragraph text, free-form bullets that describe behavior or rationale, the category folder-note `description`, and free-text portions of history entries.

**NOT translated — always kept as English identifiers**:

- ALL frontmatter keys and values (e.g., `spec_role: design`, `spec_stage: draft`).
- Role words in the body header and breadcrumb — the `<role>` in `# <Title> — <role>` and `> **…** — <role>` lines.
- Fixed section headers — `# Summary`, `# Gates`, `# History` (H1 on the status folder-note), `## Summary`, `## Repro steps`, etc. (H2/H3 on authored docs). Skills use the canonical English heading even when the body below is localized.
- Review-class `class` labels and section ids.
- Source URLs and wikilink targets — the part before `|` in `[[path|display text]]` stays English; the display text MAY be translated.
- Code blocks, command snippets, function/class names, file names.
- Subsystem, product, and asset names — they are path segments.
- Product-specific terminology (entity names, domain nouns) that appear in source code or product config.

**Skill behavior**:

- Resolve the effective language via `lazycortex-specs resolve-language <relpath>` (the four-step chain above). If unresolvable, treat as `en`.
- When generating new prose, write in that language.
- When editing existing prose, keep the existing language — do not retranslate.
- No linguistic validation is attempted.

## Part 4 — Cross-repo handoff (spec-repo → dev-repo)

A design authored and approved in one repo (a spec-repo) can be pulled into another repo (a dev-repo) where planning and implementation continue. The transfer is git-pull-based, one-directional, and non-interactive — no cross-repo wikilinks, no shared local paths. Identity across repos is the product **compound-key + category + slug**, never a path and never a wikilink.

### `products[<key>].handoff` — spec-repo side (stop gate)

A product record MAY carry a `handoff` block marking it as a transfer source:

```json
"handoff": { "stop_after": "spec_design_done" }
```

`stop_after` is one of the five flat gates (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`; default `spec_design_done`). It names the gate at which this product's own asset lifecycle stops in this repo: scaffolding a new asset under this product omits every authored doc belonging to a stage after the stop gate (e.g. `stop_after: spec_design_done` scaffolds no `plan.md`). No other behavior changes — the gate ladder simply has nowhere further to advance, and no follow-up review opens past the missing doc. `handoff` carries no `target` field; a spec-repo does not know who consumes it — consumers declare their own sources via `spec.imports[]` below.

### `spec.imports[]` — dev-repo side (pull sources)

The plugin-owned `spec` settings section gains an `imports` array — the spec-repos this repo pulls approved designs from:

```json
"spec": {
  "imports": [
    { "git_url": "git@github.com:you/spec-repo.git", "ref": "main", "products": ["chapter"] }
  ]
}
```

| Field | Required | Description |
|---|---|---|
| `git_url` | yes | Any git-clonable URL. Fetched into a gitignored cache under `.experts/.spec-imports/` — never a tracked path, never assumed shared between machines |
| `ref` | no (default: remote HEAD) | Branch/tag/ref to fetch |
| `products` | no (default: every `handoff` product found in the fetched repo) | Restrict the pull to specific upstream product keys |

`/spec.import` and the daemon-registered `spec.import-pull` routine (see `spec.install`) drive the same import primitive over every configured entry: fetch, select each entry's `handoff` products whose stop gate is `true` AND have at least one qualifying asset to land this run, resolve (or auto-register) the matching dev-repo product record, land each qualifying asset's approved authored docs, and commit atomically under a bot identity. A product with no qualifying asset this run is never auto-registered — registration and landing happen together, never registration alone. Landing never requires the dev-repo product's `spec_path` to mirror the spec-repo's — only `<category>/<slug>/` is preserved. An unregistered dev-repo product is auto-registered from the fetched record (`spec_path` mirrored under this repo's content-root as the default; `source`, `handoff`, and `dependencies` stripped) — the mirrored path is the auto-registration default, not a constraint on an already-registered product. Auto-registration writes the product record only — it does not scaffold the product's folder-note tree or icons; the operator completes those via `/spec.product-config` edit mode when desired.

Each `spec.imports[]` entry is processed independently: a fetch/parse failure on one entry (unreachable `git_url`, malformed settings) is recorded and does not prevent the other configured entries from landing normally in the same run.

### `spec_imported: true` — frontmatter marker (read-only semantics)

Every doc landed by an import carries `spec_imported: true` in frontmatter, alongside its imported `spec_stage: approved`. The marker is a light signal, not hard enforcement:

- The `lazy-review.scan` routine's frontmatter filter excludes `spec_imported: true` docs (`"not_in": [true]`) — they never enter the review loop, so the plugin never proposes editing them.
- `spec.doctor` reports a doc that drifted from its cached upstream copy as a WARN finding, report-only.
- Nothing prevents a hand-edit (no chmod, no pre-commit hook) — the marker plus the scan-filter exclusion is the entire enforcement surface.

A re-import never overwrites a doc whose content already differs from the cached upstream copy (drift) — only a byte-identical or previously-unseen asset lands or updates.

## Part 5 — Wizard-question explanation standard

Every `AskUserQuestion` call issued by a `spec.*` skill MUST be authored as a full-context block so a user seeing the field for the first time can answer without reading any other doc. Short one-line questions ("Language?", "Workflow overrides?") are forbidden — they force the user to guess what is being asked.

A conforming wizard question has four parts:

1. **Question stem** (2–3 sentences) — name the field, state what it controls, and state when/where the value takes effect. Refer to terminology introduced elsewhere in `${CLAUDE_PLUGIN_ROOT}/references/` by its exact name so the user can search for it.
2. **Why it matters** (1 sentence) — the concrete consequence of the choice. What breaks, what changes, or what downstream skill reads this value.
3. **Per-option copy** — each `AskUserQuestion` option MUST carry a 1-sentence consequence + a concrete example. Never rely on the option label alone. If two options differ only in a tradeoff, state the tradeoff explicitly ("faster to set up, harder to extend later" vs. "more upfront work, cleanly versioned").
4. **Pointer** — the trailing line `See: ${CLAUDE_PLUGIN_ROOT}/references/<file>.md` pointing at the reference doc that owns this field's semantics. Always use the reference path, not a skill path — skills are callers, not the source of truth.

Example (for the `document template override` question in `spec.product-config`):

```
Question stem:
  Authored-doc templates are organised per asset category — one folder under
  ${CLAUDE_PLUGIN_ROOT}/templates/ per category (spec.feature/, spec.change/,
  spec.bug/, spec.product/, plus any operator-defined category). A per-product
  override of one category lives under
  .claude/templates/spec.<category>/<compound-key>/ and resolves per file: a
  file present there wins, anything missing falls back to the category's
  top-level template.

Why it matters:
  An override changes the starting frontmatter and body skeleton of every NEW
  asset doc created for this product in that category; existing docs are not
  rewritten. Override applies only to the chosen category — other categories
  keep using their top-level templates.

Options:
  - use default          — inherit templates/spec.<category>/ verbatim; zero
                           maintenance. Example: a product happy with the
                           standard feature/change/bug skeletons.
  - per-product override — pick a category, create
                           .claude/templates/spec.<category>/<compound-key>/
                           and drop an edited copy of only the files you want
                           to change (e.g. design.md). Per-file fallback covers
                           the rest. Example: a product whose feature/design.md
                           needs a bespoke section layout.

See: ${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md
```

Skills invoking `AskUserQuestion` are responsible for rendering this block into the tool's `question` and per-option `description` fields. The stem + why + pointer go into `question`; the per-option copy goes into each option's `description`. Never drop the pointer — it is the user's escape hatch when the wizard explanation is still unclear.
