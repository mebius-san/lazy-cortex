---
name: lazy-spec.config-protocol
version: 1
description: Canonical contract for spec product / repo / language config in lazy.settings.json — what the products, repos, and spec sections hold and how spec.* skills resolve product, repo, and language at runtime.
---
# Config protocol — products, repos, language resolution

Everything the spec system needs to know about products, source repos, and what language prose is written in lives in two cross-plugin sections of `.claude/lazy.settings.json` (`products`, `repos`) plus one plugin-owned section (`spec`). This document is the canonical contract for what's in each, how to read it, and how `spec.*` skills resolve product / repo / language at runtime.

### `spec` settings section — vault root

The `spec` section of `.claude/lazy.settings.json` carries plugin-owned settings. The key relevant to layout is:

| Key | Default | Description |
|-----|---------|-------------|
| `spec.vault_root` | `specs` | Path of the spec content-root relative to the settings-dir (the directory holding `.claude/lazy.settings.json`, i.e. the repo root). All spec content — the operator's product trees and the `requests/` inbox — lives under `<settings-dir>/<spec.vault_root>`. Use `.` to place content directly at the settings-dir (content-root = settings-dir). Vault-relative paths (`spec_path`, wikilinks, tags) are relative to this content-root. See [layout](./lazy-spec.layout-protocol.md) Part 1 § Spec content-root. |
| `spec.language` | none (optional) | ISO 639-1 language code for spec prose across the vault. When absent the top-level `language` key applies, then the floor `en` — see Part 3 |
| `spec.coordination_rules` | none (optional) | Repo-relative path to the vault-wide operator doc of coordinator rules — the second of the five rule layers `spec.coordinator` reads before every decision (playbook → this doc → product guidelines → product folder-note rules → asset folder-note rules; see `lazy-spec.coordination-playbook.md` § 2). States what the coordinator may run automatically across the whole vault, and any vault-wide override of the playbook's defaults. When set, its content is injected into every `spec.coordinator` job's context; `lazy-spec.doctor` flags a configured path that doesn't resolve to a file. |

## Part 1 — Config files (products + repos)

Product config and repo config are both records in `lazy.settings.json`: products under the `products` section, repos under the cross-plugin `repos` section.

### Product records — `lazy.settings.json[products]`

A product's registration is a record under the `products` section of `.claude/lazy.settings.json`, keyed by the product's **compound-key** — an arbitrary stable string the operator chooses at registration (lowercase-with-hyphens recommended). The key is NOT derived from the product's path: `spec_path` says where the product lives, the key says how it is addressed, and the two vary independently — moving the folder never renames the key. The section's `_version` key carries the schema version and is not a product record.

There is no `spec.cfg-<product>.md` rule file any more — that form is removed. The product record is read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`, and resolved by the `lazycortex-specs resolve-product` primitive (below). `/lazy-spec.product-config` is the wizard that creates and edits these records.

| Field | Required | Description |
|-------|----------|-------------|
| `spec_path` | yes | Where the product's specs live, relative to vault root |
| `source.repo` | no | Key of the repo config this product's source lives in (e.g., `backend`). Omitted for a design-only product (specs authored ahead of code) |
| `source.paths` | no | Subdirectories within that repo the product covers. Present iff `source` is present |
| `language` | no (default `en`) | ISO 639-1 language code overriding the repo-global `spec.language`. Skills write narrative prose in this language — see Part 3 |
| `icon` | no (default `LiPackage`) | Iconize identifier (Lucide name or emoji) painted on the product folder; mirrored into the product folder-note's managed `iconize_icon`. The wizard writes the default when the operator declines — every product folder-note carries an icon |
| `color` | no (default `#64748b`) | Iconize colour of the product folder, mirrored into the managed `iconize_color`. A product root is the one ordinary container that carries a colour — the neutral one — so the products stand out from the group folders beneath them; the key exists to override that for one product. See § Container colour below |
| `dependencies` | no | List of upstream deps (other products, repos, or external) — see [sources](./lazy-spec.sources-protocol.md) Part 3 |
| `asset_types` | no | Per-type declarations, merged **key-by-key** over the plugin's shipped set (`references/lazy-spec.asset-types.json` — `feature`, `change`, `bug`, `content`, `research`), so a product may replace one field of a shipped type without restating the rest, or declare a type of its own. Written by `/lazy-spec.add-asset-type`. See below and [layout](./lazy-spec.layout-protocol.md) § Asset types |
| `tool_types` | no | Per-tool declarations, merged key-by-key over the plugin's shipped set (`references/lazy-spec.tool-types.json` — `code`, `data`, `test`, `docs`). See below |
| `guidelines` | no | Extra context files folded into launch-checkbox job dispatch, keyed by dispatched role token plus the wildcard `"*"`. See below |
| `mode` | no (default full) | `"spec-only"` activates the designer-only ladder (`lazy-spec.coordination-playbook.md` Chapter 14) for every asset under this product — design.md → review → approve → `spec_design_done`, no architecture/plan/implementation/test steps. Absence means the ordinary full ladder. Written by `/lazy-spec.product-config`'s wizard. `_build_bundle` folds the owning product's whole record — `mode` included — into every coordinator job's `payload["product"]` unconditionally, so no separate settings read is needed to detect the profile. |

Example product record:

```json
"server-tester-chapter": {
  "spec_path": "Server/Tester/chapter",
  "source": { "repo": "backend", "paths": [ "chapter", "shared/log" ] },
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

### Container colour

Colour is the state axis: an asset's folder takes its colour from its own `spec_state`, and a document from its stage. A container has no state, so the catalog paints containers on a three-tier rule rather than giving every shelf a colour it cannot mean.

| Container | Colour |
|---|---|
| Product root (`<spec_path>/<leaf>.md`) | Neutral `#64748b` — `products[<key>].color` overrides it |
| Ordinary group folder (`features/`, `changes/`, `bugs/`, any declared type's `default_path`, any ad-hoc folder) | None. The note carries `iconize_icon` and no `iconize_color` at all |
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
| `alias_of` | no | Names a base type whose playbook this type borrows when it declares none of its own. The folder, icon, colour, start document and tools stay this type's own, and aliases never chain |
| `default_path` | no | Folder name under `<spec_path>/` where assets of this type land unless the caller names another location |
| `start_doc` | yes | `"<file>:<doc_type>"` token naming the one document a fresh asset of the type is seeded with (e.g. `design.md:design`, `bug.md:bug`). A type with no `start_doc` cannot be scaffolded at all |
| `default_tools` | no | Tool-type names an asset of this type is realised and checked with; written into the status folder-note's `spec_tools` at scaffold time |

**Merge rule: key-by-key over the shipped declaration, never whole-record replacement.** `{"bug": {"icon": "LiSkull"}}` repaints the shipped `bug` type and leaves its `default_path`, `start_doc`, and `playbook` exactly as shipped.

The declaration is the whole of what a type is: the folder is a place, not a fact. An asset's kind is the `spec_asset_type` key on its own status folder-note, and everything that resolves the asset's law reads that key, never the path. `/lazy-spec.add-asset-type` writes the declaration and an own-playbook stub and nothing else — no folder, no folder-note, no templates. The type's folder appears the first time `lazy-spec.create-asset` scaffolds an asset into it.

### `products[<key>].tool_types` — declared tool types

Each key is a tool name — the value an asset's `spec_tools` list carries. Each value is an object:

| Field | Required | Description |
|---|---|---|
| `playbook` | yes | Reference key of the playbook the coordinator loads when driving this tool's work on an asset |
| `report_doc` | yes | Document type of the tool's append-only execution journal (e.g. `code-report`, `data-report`) |
| `plan_doc` | no | Document type of the tool's plan. Its presence is what hangs the `Write <tool>-plan` launch checkbox; a tool without `plan_doc` gets no plan checkbox |

The shipped set is `code` (`code-plan` / `code-report`), `data` (`data-report`), `test` (`test-plan` / `test-report`), and `docs` (`docs-report`).

Per-product doc-template overrides are NOT declared in the record. The override signal is **folder presence** under `.claude/templates/` — a per-product override folder `spec.<type>/<compound-key>/`, and the consumer's own type baseline `spec.<type>/`. Resolution is per-file across a five-layer fallback that ends at the plugin's linear per-doc-type base (`spec.docs/`), so a type needs no template folder of its own to be scaffoldable, and an override folder may contain only the files that differ. See [layout](./lazy-spec.layout-protocol.md) Part 1 § Template storage for the full layer order.

### `products[<key>].guidelines` — launch-checkbox context paths

A product record MAY carry a `guidelines` dict supplying extra context to the jobs `spec.coordinator` dispatches when an operator ticks a launch checkbox (`Write architecture` / `Write code-plan` / `Write test-plan` / `Start implementation` / `Start testing`) in an asset's `# Gates` section:

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
| `architect` | Guideline paths folded into the `Write architecture` checkbox's job — this is also the blessed route for handing the architect an operator-declared `docs/structure.md` project-structure map (`lazy-spec.coordination-playbook.md` Chapter 8), when the operator wants it injected as job context instead of left to the architect's own pull-skill query. |
| `planner` | Guideline paths folded into the `Write code-plan` checkbox's job. |
| `tester` | Guideline paths folded into both the `Write test-plan` and `Start testing` checkboxes' jobs — both dispatch under the `tester` role. |
| `developer` | Guideline paths folded into the `Start implementation` checkbox's job. |
| `coordinator` | Guideline paths folded into every `spec.coordinator` job dispatched for this product's assets — the third of the five rule layers the coordinator reads before deciding (see `lazy-spec.coordination-playbook.md` § 2). Distinct from a product or asset folder-note's `# Coordinator rules` section: this key names files, the folder-note sections carry operator-authored prose directly. |
| `*` | Guideline paths folded into every launch-checkbox job for this product, regardless of role. |

Values are lists of repo-relative file paths, read literally — no glob expansion. Each path that resolves to a file has its contents folded into the dispatched job's context bundle, keyed by basename; a declared path that does not resolve to a file is never silently skipped — it is recorded as a warning in the dispatch result and appended to the asset's `# History` section. The key is entirely optional: a product record with no `guidelines` key dispatches launch-checkbox jobs with no extra context.

### `products[<key>].doc_types` — project-declared document types

A product record MAY carry a `doc_types` dict declaring document types beyond the nine the plugin ships in `references/lazy-spec.doc-types.json`, or adjusting the flags of a shipped one:

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
| `review` | boolean | `false` | The document goes through the review loop under a class of the same name; `lazy-spec.product-config` generates that class. |
| `append_only` | boolean | `false` | The file is only ever appended to, never rewritten. |
| `icon` | string | absent | Iconize identifier a document of the type is seeded with at creation, written into its managed `iconize_icon`. |
| `color` | string | absent | Iconize colour paired with the icon, written into the managed `iconize_color`. |
| `template` | string | absent | Filename of the type's linear template under `templates/spec.docs/`. |

**Merge rule: key-by-key over the shipped declaration, never whole-record replacement.** `{"system-tech": {"review": false}}` turns review off for `system-tech` and leaves its `stages: true` and its `template` exactly as shipped. A type the plugin does not ship is declared from scratch, so every field it omits takes the `false` / absent default — `{"content-report": {"review": true, "append_only": true}}` is a review-bearing, append-only, non-staged document, which is a complete declaration and not an error.

**`icon` / `color` are the document's kind half of the paint contract.** The seed says what kind of document this is; the iconize registry's matchers say what state it is in and own the colour from the first `lazy-spec.set-stage` onward. A stage-less type — a journal, the decisions registry — is never claimed by any matcher, so its seed is the only paint it will ever carry; a stage-bearing type shows the seed only until its first stage lands. This is why the registry enumerates no document kinds at all: a project type declares its own paint here and needs no registry edit.

The key is entirely optional: a product with no `doc_types` sees exactly the nine shipped types. `lazycortex-specs doc-type list --product <key>` prints the merged set, `doc-type resolve <type> --product <key>` one merged declaration.

### Repo records — `lazy.settings.json[repos]`

Repo records live in the cross-plugin `repos` section of `.claude/lazy.settings.json`, symmetric to `products[]`. The section maps a symbolic `<repo-key>` to runtime metadata for one local checkout. It is read and written atomically via `lazycortex-core settings-get repos` / `lazycortex-core settings-set repos`, and resolved by the `lazy-spec.resolve-repo` primitive. The `repos` section is registered in lazy-core's `CURRENT_VERSIONS` and auto-initializes on first `settings-get`; `/lazy-spec.product-config` (inline repo wizard) is the wizard that writes records. Being cross-plugin (top-level, not under a plugin namespace), the section is also available to other plugins that need repo metadata.

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
| `local_path` | yes | Absolute path to the local checkout, **or `"."` — the repo containing this settings file** (same-repo products); `lazy-spec.resolve-repo` expands `"."` to `git rev-parse --show-toplevel` so each checkout resolves to its own root |
| `branch` | yes | Branch to link against (typically `main` / `master`). Skills compare against this as the repo's default when reconciling pins |
| `forge` | no | Forge key override (`github` / `gitlab` / `bitbucket` / `gitea` / `forgejo` / `sourcehut`). Needed ONLY when the hostname on the local checkout's git remote is not in the known-forges table (e.g., self-hosted GitLab / Gitea). For well-known hosts, omit this field — the forge is auto-detected |

Repo records DO NOT carry the repo's URL. The URL is derived at runtime from the local checkout's git remote (`git -C <local_path> remote get-url origin`) via the `lazy-spec.resolve-repo` primitive — see [sources](./lazy-spec.sources-protocol.md) Part 2.

> The word `spec` in skill names (`spec.*`) refers to the overall specification system. It is unrelated to the per-file `design` role introduced elsewhere.

## Part 2 — Product / repo resolution

### Resolving a Product

Product resolution goes through the `lazycortex-specs resolve-product` primitive, which reads the `products` settings section directly. Two modes:

- **by-key** — `lazycortex-specs resolve-product by-key <key>` returns `{"key": <key>, "record": <record-or-null>}`. A direct record fetch by the exact compound-key.
- **by-path** — `lazycortex-specs resolve-product by-path <path>` returns `{"key": <owning-key-or-null>, "record": <record-or-null>}`. The `<path>` argument is resolved relative to the content-root (`<settings-dir>/<spec.vault_root>`); if the caller supplies a path that begins with the vault-root segment (e.g. `specs/Server/Tester/chapter/features/foo`), that leading segment is stripped before matching. Finds the product whose `spec_path` equals the normalised path or is a segment-wise prefix of it; when several products nest, the longest matching `spec_path` wins. Segment-wise matching means `A/B` owns `A/B/x` but not `A/Bx/...`, so it transparently covers the product's standard subtree (`<spec_path>/features/<feat>/...`, `<spec_path>/changes/<change-name>/...`, `<spec_path>/bugs/<bug-name>/...`) and the product-root files (`<spec_path>/<product>.md` folder-note, `<spec_path>/design.md`, `<spec_path>/tech.md`). Request files are NOT under a product — they live in `<content-root>/requests/` — so `resolve-product by-path` never attributes them to a product.

`spec.*` skills follow this protocol:

1. Resolve the user's input to a product. Try in order: exact compound-key (`resolve-product by-key`); a `spec_path` exact-or-sub-path match (`resolve-product by-path`); a `source.paths` entry match; then a **bare-name fallback** — if the input matches exactly one record key's trailing `-<input>` suffix, resolve it. If two or more records match the bare name, abort the non-interactive path AND prompt the user via `AskUserQuestion` to pick (options = the full keys of the candidates).
2. A `null` record means the product is not registered. Tell the user and suggest registering it via `/lazy-spec.product-config`.
3. Resolve the product's `source.repo` (when present) against the repo configs via `lazy-spec.resolve-repo` to get `{local_path, branch, host, owner, repo, forge, base_url, …}`.

**Products are flat**: a product's `spec_path` MUST NOT be a sub-path of another product's `spec_path`. Nested products are forbidden — group related products under a shared organizational parent folder instead (see [folder-structure](./lazy-spec.layout-protocol.md)).

### Spec Roots

Each product's `spec_path` is its spec root. Each spec root is self-contained — skills work within a single spec root at a time. Never cross-reference state files between roots.

## Part 3 — Language resolution

A spec doc's effective prose language is resolved through a fallback chain (first non-empty wins), via the `lazycortex-specs resolve-language <relpath>` primitive:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's `language` field in `products[<key>]` (`lazy.settings.json`);
3. the `spec` settings section's `language` key;
4. the top-level `language` key in `lazy.settings.json` (repo-wide default, shared with the other plugins);
5. the hardcoded floor `en`.

Skills that write or edit spec content MUST honour the resolved language (ISO 639-1).

**Translated** — narrative prose: `## Overview` body, paragraph text, free-form bullets that describe behavior or rationale, the category folder-note `description`, and free-text portions of history entries.

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

- Resolve the effective language via `lazycortex-specs resolve-language <relpath>` (the four-step chain above). If unresolvable, treat as `en`.
- When generating new prose, write in that language.
- When editing existing prose, keep the existing language — do not retranslate.
- No linguistic validation is attempted.

## Part 4 — Upstream sources (`spec.upstream`)

`upstream/` mirrors one or more foreign git repos' design content into this vault, outside the
product hierarchy. Configuration lives in the plugin-owned `spec` settings section, under
`spec.upstream`:

```json
"spec": {
  "upstream": {
    "max_units_per_tick": 7,
    "max_text_file_bytes": 1048576,
    "fetch_failure_threshold": 5,
    "game-design": {
      "url": "git@github.com:studio/game-design.git",
      "branch": "main",
      "mounts": {
        "designs": {
          "source_path": "designs",
          "units": [ "features/*", "systems/*" ],
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
| `<repo-key>` | one entry per source | — | Any key not in the reserved set above (`max_units_per_tick`, `max_text_file_bytes`, `fetch_failure_threshold`) names one upstream source. Renaming a `<repo-key>` or a mount is a manual operation — the key is encoded into the vault path (`upstream/<repo-key>/<mount>/...`). |
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
back out into the skip list. The wiki plugin's `.lazyignore` convention is never consulted for
either side — merging it would reach into a sibling plugin's own ignore semantics.

## Part 5 — Upstream unit enumeration

Each tick's unit list is the union of two trees, not the source tree alone: every directory the
configured `<mount>.units` globs currently match in the freshly-fetched source, plus every unit
directory that already exists under the vault's `upstream/<repo-key>/<mount>/` path from a prior
tick. Deduplicated by unit identity `(repo-key, mount, unit-path)` and sorted for tick-to-tick
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
  asset_types.<name>.default_path is the folder under the product's spec_path
  that lazy-spec.create-asset scaffolds into when the caller names no folder of
  its own. The folder is created lazily, on the first asset of the type that
  lands in it.

Why it matters:
  It is a convenience for whoever creates the asset, NOT a fact of the type —
  type resolution reads spec_asset_type off the status folder-note and never a
  path, so a single asset may be placed anywhere under spec_path (including
  inside another asset's folder) with --path and nothing downstream breaks.

Options:
  - characters        — the pluralised type name; the ordinary choice. Example:
                        a "character" type whose assets collect under
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
