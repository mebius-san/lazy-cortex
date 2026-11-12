---
name: lazy-spec.product-config
description: "Use when the operator asks to create a new product in the spec system or edit an existing product's registration — 'add a product', 'register this repo as a product', 'add source to this design-only product', 'change its dependencies, language or icon'. Products are registered here, never by /lazy-spec.install."
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, Agent
---
# Configure Product

**Resolve `<core-cli>` once, before the first call.** It is the core plugin's `bin/lazycortex-core` file; `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" core-cli)` prints its absolute path — this plugin's own resolver tries the daemon's `$LAZYCORTEX_PLUGIN_DIRS`, then the dev-vault sibling `plugins/claude/lazycortex-core/`, then the install `~/.claude/plugins/installed_plugins.json` records; exit 1 with an `error:` line means core is not installed — abort and say so. Hold the absolute path and run every verb as `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb> …)` — never as a bare command: the file carries no exec bit and no plugin `bin/` is on `PATH`.

Unified wizard that owns the product-registration lifecycle. One entry point for **creating a new product** (with source code, or design-only) and for **editing an existing product** (add `source` to a design-only product, extend `dependencies`, switch `language` / `icon`). The product record lives in `lazy.settings.json[products][<compound-key>]`, read and written atomically via `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get products` / `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set products`. On save the skill scaffolds the product root and brings up its level note (`spec_role: product`, via `catalog-note backfill`, Step 11) carrying the iconize icon (group folders and their notes appear lazily — the first `create-asset` landing an asset seeds them). The product's documents flow through the review loop on the shared review classes `/lazy-spec.install` seeds.

A product's code lives in this same repository; its `source` names only the repo-relative paths it covers. The product `language` overrides the repo-global `spec.language` (the `language` key in the `spec` settings section) for narrative prose this product emits.

## Execution discipline (MANDATORY — read before any action)

This skill has 12 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Mode detection + resolve registry`
   - `Step 2 — Product key + spec_path`
   - `Step 3 — Language`
   - `Step 4 — Source (paths, or design-only)`
   - `Step 5 — Dependencies (autodetect + confirm)`
   - `Step 6 — Product icon`
   - `Step 7 — Guidelines (optional per-role context)`
   - `Step 9 — Asset types (delegate)`
   - `Step 10 — Workflow mode (full vs spec-only)`
   - `Step 10b — Release (implementer, manifest, deploy targets)`
   - `Step 11 — Write product record + scaffold folders + folder-notes`
   - `Step 13 — Verify`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, `design-only`, `taken-from-arg`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer — and preceded by the context block each site below spells out (`Where` / `Found` / `Why asking` / `Answers`, per `lazy-core.skill-writing` § 11), printed to the operator as prose immediately before the call. Once the wizard's opening has named the skill and mode, the `Where` line may stay short; `Found`, `Why asking`, and `Answers` are per question, filled from the run at hand. Never ask a bare one-line question. Never present options as plain-text prose.

All narrative prose this skill authors (folder-note bodies) is rendered in the product's effective `language`. Frontmatter keys, fixed headers, wikilinks, settings JSON, and section ids stay English.

## Input

The user provides one of:

1. A natural-language request ("new product for X", "edit chapter settings", "add source to Tester/chapter", …).
2. A product compound-key (new or existing) or a path under an existing product's `spec_path`.
3. The caller form `create <key> at <spec_path> [source <path>[,<path>]]` — a skill registering a nested product (e.g. `lazy-spec.create-from-code` Step P2b) hands the key, the spec path, and the source folder in this form. Step 2 and Step 4 take those values directly, outcome `taken-from-arg`, and ask nothing for them; every other step runs as usual, with `inherited` where the effective record already carries the value.
4. Nothing — the skill asks whether to create or edit.

## Step 1 — Mode detection + resolve registry

Read the products section once:

```bash
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get products
```

The first prints the `products` object — each key is a compound-key, each value a record (`spec_path`, optional `language`, `icon`, `source`, `dependencies`, `asset_types`, `tool_types`). Ignore the section's `_version` key.

Resolve the user's input to a mode:

- If the input resolves to an existing product key (or a path under an existing product's `spec_path`) via the "Resolving a Product" protocol in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` → **edit mode** (jump to Step 2's edit branch, then Step 11 writes the merged record).
- An input in the `create <key> at <spec_path>` form with an unregistered `<key>` is **create mode** even when `<spec_path>` sits under an existing product's `spec_path` — that is a nested product, not an edit of the parent.
- Otherwise → **create mode**.

When intent is ambiguous (e.g. the user just says "configure product"), ask, then proceed:

```
Context (print before asking):
- Where: /lazy-spec.product-config · Step 1 — Mode detection; target `products` in <settings-dir>/lazy.settings.json
- Found: registered products: <keys, or "none">; the request named no product key or path
- Why asking: the input resolves to neither an existing product nor a new key — the mode is the operator's call
- Answers: `create` — create mode (Step 2 create branch); `edit` — edit mode (Step 2 edit branch); this answer writes nothing and is asked only on ambiguous input
AskUserQuestion: header "Create or edit", question "Configure a product in <repo>: create a new product, or edit one of the registered ones (<keys>)?", options `create` / `edit` with the descriptions above.
```

**Vault-spec gate (create mode only).** Products are a consequence of the repo-wide spec: resolve the content-root (`<settings-dir>/<spec.vault_root>`, default `specs`) and check that `<content-root>/vision.md` — the vault spec — exists, OR that a pre-existing `<content-root>/design.md` without a vision does (the legal pre-vision state; documents are migrated by the operator by hand). Both absent → abort with outcome `aborted:no-vault-spec`, pointing the operator at `/lazy-spec.install` (its Step 6.9 seeds the vision draft). Presence is the whole gate; how far the document must have progressed (written / approved) is deliberately outside this contract yet. Edit mode skips the check — the registered catalog predates the gate.

The products object drives uniqueness of the new product key. A `spec_path` under another product's `spec_path` is legal — products may nest, and the innermost owns its tree per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

Outcome: `create`, `edit`, or `aborted:no-vault-spec`.

## Step 2 — Product key + spec_path

**Create mode.** When the input carried the key and the spec path in the `create <key> at <spec_path>` caller form, take both directly, outcome `taken-from-arg`, and ask neither question below. Otherwise, two questions:

1. **Product key** — the product's settings key: an arbitrary stable string the operator chooses (lowercase-with-hyphens recommended, e.g. `chapter`). Validate uniqueness among existing `products` keys.

   ```
   Context (print before asking):
   - Where: Step 2 — Product key; target `products[<key>]` in <settings-dir>/lazy.settings.json
   - Found: registered keys: <keys, or "none">
   - Why asking: the key is the product's stable identity across config and every skill invocation — NOT derived from its path, never changed when the folder moves; nothing derives it
   - Answers: any typed key (via "other") — written as `products[<key>]` in Step 11 and addressed by every `spec.*` skill from then on; fixed thereafter (edit mode never renames); a key already registered is refused and re-asked
   AskUserQuestion: header "Product key", question "Settings key for the new product in <repo> (lowercase-with-hyphens, e.g. `chapter`; taken: <keys>)? It names `products[<key>]`, so pick a name that stays meaningful as the vault grows. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", free text via "other".
   ```

2. **Spec path** — `spec_path`: the content-root-relative path of the product's folder, any shape the operator likes (a top-level folder, or nested under any organizational folders — the plugin dictates no form and reads no meaning from path segments). Validate: the final path segment is not one of the reserved names `vision` / `design` / `ui-design` / `tech` / `use-cases` / `decisions` (folder-note collision per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md`); the folder does not already exist on disk unless the user is registering a spec on top of a pre-created folder.

   ```
   Context (print before asking):
   - Where: Step 2 — Spec path; target `products[<key>].spec_path`, content-root <content-root>
   - Found: existing folders under <content-root>: <list, or "none">; registered spec_paths: <paths, or "none">
   - Why asking: where this product's specs live is layout the plugin reads no meaning from — only the operator knows it
   - Answers: `<existing folder>` — register on top of that pre-created folder; `other — type a path` — a new content-root-relative path, scaffolded by Step 11; either is written as `products[<key>].spec_path`, the root every review-class glob hangs off, fixed thereafter (edit mode never moves it); a path ending in a reserved name (`vision` / `design` / `ui-design` / `tech` / `use-cases` / `decisions`), or already on disk without intent to register over it, is refused and re-asked; a path under another product's `spec_path` is legal — products may nest, the innermost owning its tree
   AskUserQuestion: header "Spec path", question "Content-root-relative folder for product `<key>` under <content-root>? Any shape — top-level, or nested under organizational folders. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options: each existing folder + `other — type a path`, with the descriptions above.
   ```

   A `spec_path` under another product's makes this a nested product: the wizard resolves its ancestor chain and, for every step below whose key the effective record already carries (`lazy-spec.config-protocol.md` § Effective record), records outcome `inherited` instead of asking.

**Edit mode.** Confirm this is the correct product. The key and `spec_path` are FIXED in edit mode — this skill does not rename or move products. Capture the existing record fields (`spec_path`, `language`, `icon`, `source`, `dependencies`, `asset_types`, `tool_types`, `guidelines`, `mode`) to merge into; never drop a field the user does not touch.

```
Context (print before asking):
- Where: Step 2 — Confirm product (edit mode); target `products[<key>]`
- Found: current record: <JSON block of the record>
- Why asking: the input resolved to `<key>` by key or path; merging into the wrong record is a hand-repair
- Answers: `confirm` — proceed; key and `spec_path` stay fixed, every untouched field is preserved through Step 11; `wrong product` — nothing written; re-run naming the intended key or path
AskUserQuestion: header "Confirm product", question "Edit product `<key>` (spec_path `<spec_path>`) in <repo> — is this the record above?", options `confirm` / `wrong product` with the descriptions above.
```

Outcome: `collected` (create) or `confirmed` (edit).

## Step 3 — Language

**Nested product:** when the effective record already carries this step's key from an ancestor, outcome `inherited`, no question; edit mode still lets the operator declare an own value, which wins.

Optional override of the repo-global `spec.language`. In edit mode, default the menu to the product's current value. Capture `<language>` only when the user picks a concrete override; treat `inherit default` as absent.

```
Context (print before asking):
- Where: Step 3 — Language; target `products[<key>].language`
- Found: repo default `spec.language` = `<code>`; product override on record: <code, or "none">
- Why asking: the language of this product's narrative prose is project config nothing derives
- Answers: `inherit default (no override)` — no key written; the product follows `spec.language` now and whenever it changes; `en` / `other — type an ISO 639-1 code` — written as `products[<key>].language` in Step 11, overriding `spec.language` for this product only: every generated folder-note body and design/tech prose from then on (fixed headers and frontmatter keys stay English regardless); re-asked only in edit mode
AskUserQuestion: header "Language", question "Narrative language for product `<key>` (ISO 639-1)? Repo default is `<code>`; an override applies only to this product's generated prose. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `inherit default (no override)` / `en` / `other — type an ISO 639-1 code` with the descriptions above.
```

Outcome: `set` or `inherit-default`.

## Step 4 — Source (paths, or design-only)

A product is **design-only** when it carries no `source` block (specs authored ahead of code). Otherwise `source` is `{ paths: [<path>, …] }` — repo-relative directories of this repository, which holds both the spec catalog and the product's code.

When the input's caller form carried a `source <path>[,<path>]` clause, take `has source code` and `source.paths` from it directly, outcome `taken-from-arg`, and ask neither question below. A caller form with no `source` clause runs this step as usual.

1. Whether this product has source code. In edit mode this is where a design-only product gains a `source` block.

   ```
   Context (print before asking):
   - Where: Step 4 — Source; target `products[<key>].source`
   - Found: `source` on record: <{paths}, or "none — design-only">
   - Why asking: whether specs are authored ahead of code is a fact about the product only the operator knows
   - Answers: `has source code` — continue to the paths question; `source` is written in Step 11 and read by dependency autodetect (Step 5) and `lazy-spec.source-url`; `design-only (no source)` — no `source` key; code-grounded autodetect and source links are skipped until source is added later in edit mode
   AskUserQuestion: header "Source code", question "Does product `<key>` have source code in this repository to bind — the subdirectories it covers — or is it design-only for now? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `has source code` / `design-only (no source)` with the descriptions above.
   ```

   - **design-only** → record no `source`; skip the rest of this step (outcome `design-only`) and skip Step 5's autodetect.
   - **A nested product under an owner may only narrow the owner's `source`.** Before asking for paths, walk the ancestor chain of `<spec_path>` (`resolve-product ancestor-chain`, or the registry read in Step 1): when any enclosing product declares a `source`, the outermost such product owns the releases, and this product never does — its assets ship in the owner's releases and it owns no `releases/` folder (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Products may nest). Say so, and skip Step 10b for it whatever the answers below. It may still declare a `source` of its own whose paths lie inside its parent's source paths: that `source` only narrows the code area for `sync-with-code` and the audit. A path outside the parent's source paths is refused with that explanation rather than written, in the Paths question below and in a caller form alike. A nested product that declares no `source` records none, outcome `inherits-owner-source`.

2. **Paths** — for each path, validate it exists relative to the repository root; if any does not exist, warn and ask whether to proceed (keep the path as a forward declaration) or correct it.

   ```
   Context (print before asking):
   - Where: Step 4 — Paths; target `products[<key>].source.paths`
   - Found: `source.paths` on record: <paths, or "none">; repository root <git root>
   - Why asking: which subdirectories the product covers bounds dependency autodetect, `sync-with-code`, and the audit — a scope only the operator can draw
   - Answers: `single subpath` — one repo-relative string via "other"; `multiple subpaths` — comma-separated via "other"; written as `source.paths` in Step 11, each validated relative to the repository root (a missing one raises the follow-up below)
   AskUserQuestion: header "Source paths", question "Repo-relative subdirectories of this repository that product `<key>` covers? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `single subpath` / `multiple subpaths` (free text via "other") with the descriptions above.
   ```

   ```
   Context (print before asking):
   - Where: Step 4 — Paths validation; target `<path>` relative to the repository root
   - Found: `<path>` does not exist in the working tree
   - Why asking: a typo and a forward declaration look the same — only the operator knows which
   - Answers: `proceed` — keep `<path>` in `source.paths` as a forward declaration; `correct` — re-ask the paths question for this entry
   AskUserQuestion: header "Missing path", question "`<path>` does not exist in this repository. Keep it as a forward declaration, or correct it?", options `proceed` / `correct` with the descriptions above.
   ```

Outcome: `sourced`, `design-only`, `inherits-owner-source`, or `taken-from-arg`.

## Step 5 — Dependencies (autodetect + confirm)

When `source.paths` is non-empty and the paths exist, dispatch **one Explore subagent** (`subagent_type: "Explore"`, `mode: "dontAsk"`, read-only) to scan imports/requires within each `source.paths` entry. Skip this step entirely for a design-only product (outcome `design-only`).

The agent's prompt must include: the exact globs to scan (the `source.paths` entries, repo-relative); the set of registered product `source.paths` (to classify candidates as `internal-product`); the structured-report contract below; and a word budget ("Report under 400 words").

Expected report block (per the parallel-scan coordinator pattern in `lazycortex-core`'s `references/lazy-core.parallel-scan.md`):

```markdown
## scan: dependencies

### findings
- [DEP] <dep-label> | <import-path-or-package-name>
  kind: internal-product | external
  evidence: <file>:<line> — <import line>
  suggest: <dep entry snippet>

### summary
internal: <n>  external: <n>
```

Classification:

- **internal-product** — imported path falls under another registered product's `source.paths`. Suggest a `{product: <key>}` dep entry resolved via `lazy-spec.resolve-dependency` (see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`).
- **external** — third-party package from a manifest (`requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`, …). Listed but not added by default.

Iterate candidates **one `AskUserQuestion` call per candidate**. Keep one running list. In edit mode, append accepted entries to the existing `dependencies` list (never clobber prior entries); never emit an empty `dependencies: []`.

```
Context (print before asking, one block per candidate):
- Where: Step 5 — Dependencies; target `products[<key>].dependencies`
- Found: `[DEP] <dep-label>` kind `<internal-product | external>`, evidence `<file>:<line> — <import line>`; accepted so far: <running list, or "none">
- Why asking: the scan proves the import exists, not that the operator wants it declared as a spec dependency
- Answers: `add` — append `<dep entry snippet>` to the running list, written into `dependencies` in Step 11 (edit mode appends to the existing list); `skip` — leave it out; "other" — a free-text note
AskUserQuestion: header "Dependency", question "Declare `<dep-label>` (<kind>, seen at <file>:<line>) as a dependency of product `<key>`?", options `add` / `skip` (+ "other" for a note) with the descriptions above.
```

Outcome: `confirmed`, `design-only`, or `none`.

## Step 6 — Product icon

In edit mode, default to the product's current icon. `<icon>` is the operator's value when one is given, otherwise `LiPackage`.

```
Context (print before asking):
- Where: Step 6 — Product icon; target `products[<key>].icon` and the managed `iconize_icon` frontmatter of `<spec_path>/<leaf>.md`
- Found: icon on record: <icon, or "none (default LiPackage)">
- Why asking: how the product is told apart in the file explorer is the operator's choice; only the fallback is fixed
- Answers: `<suggestion>` (a couple of concrete Lucide names or emoji) / `default (LiPackage)` / `other — type your own` — the value is written to both targets in Step 11 and painted on the product folder by the Obsidian iconize system; every product carries an icon, so declining still yields `LiPackage`, never an icon-less note (an unpainted stray in the explorer); the colour is not asked (below)
AskUserQuestion: header "Product icon", question "Icon for product `<key>` — a Lucide name like `LiBook` or a literal emoji, painted on <spec_path>? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md", options: two concrete suggestions + `default (LiPackage)` + `other — type your own`, with the descriptions above.
```

**The colour is not asked.** A product root carries the neutral `#64748b` — the one ordinary container that is coloured at all, so products read apart from the group folders beneath them (which carry no colour key whatsoever). `products[<key>].color` exists as a per-product override an operator may write by hand; the wizard never proposes one, and in edit mode it preserves an existing value like every other untouched field. The full three-tier rule, including the `#f0abfc` accent the intake shelves carry, is `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Container colour.

Outcome: `iconed` or `default-icon`.

## Step 7 — Guidelines (per-role context)

**Nested product:** when the effective record already carries this step's key from an ancestor, outcome `inherited`, no question; edit mode still lets the operator declare an own value, which wins.

Optional per-role guideline paths folded into every expert job on this product's documents — the launch-checkbox jobs `spec.coordinator` dispatches and the review rounds `lazycortex-review`'s coordinator dispatches (per `products[<key>].guidelines` in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`). `guidelines` is a dict keyed by the dispatched role token (`planner`, `tester`, `developer`, `architect`, `researcher`, `coordinator`, and any role token a registered expert carries — `designer`, `data-writer`, …) plus the wildcard `"*"`, each value a list of repo-relative file paths. A path every role on one asset type needs — a content type's record schema — belongs on the type instead, under `asset_types.<type>.guidelines`.

```
Context (print before asking):
- Where: Step 7 — Guidelines; target `products[<key>].guidelines`
- Found: `guidelines` on record: <dict, or "none">
- Why asking: which repo files an expert should read before a launch-checkbox job is project knowledge nothing derives
- Answers (create mode): `none (no guidelines)` — no key written; `add guideline paths` — the role/paths follow-up below, one role at a time until the operator is done. Answers (edit mode, current dict shown): `keep as-is` — unchanged; `add/change a role's paths` / `remove a role's paths` — the same follow-up per role. A path's contents are folded into the job's context when a `Write <doc>` row's writer round opens or a release build job runs — a release's `Write code-plan` under `planner`, every `Write test-plan` row and the release's `Test` job under `tester`, the release's `Build` job under `developer` (the implementer, who hands the paths on to the child agents it delegates to), the product's `Write architecture` row and the build's `Revise architecture` job under `architect`; `*` paths are folded into every one of those jobs regardless of role. A path that does not resolve is never silently dropped — it surfaces as a warning appended to the asset's `# History` section on every dispatch, so a typo stays visible until fixed
AskUserQuestion: header "Guidelines", question "Per-role guideline files to hand product `<key>`'s dispatched experts as extra context (on record: <dict, or none>)? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options per mode as above, with the descriptions above.
```

Role/paths follow-up (repeat until the operator is done):

```
Context (print before asking):
- Where: Step 7 — Guideline role, then its paths; target `products[<key>].guidelines.<role>`
- Found: roles already set: <roles → paths, or "none">
- Why asking: the dict is keyed by role; the paths are free text
- Answers: `planner` / `tester` / `developer` / `architect` / `*` — the role to set, any other role token from the list above via "other" (edit mode's `remove a role's paths` offers the roles on record instead, and removes the chosen one); then any comma-separated repo-relative paths (via "other") — validated below, written under that role in Step 11
AskUserQuestion: header "Guideline role", question "Which role of product `<key>` gets guideline paths (set so far: <roles>)?", options the five role tokens with the descriptions above, any other token via "other"; then header "Guideline paths", question "Repo-relative paths for role `<role>` of product `<key>` (comma-separated)?", free text via "other".
```

No new delivery mechanism exists or is needed for the project-structure map: when `lazycortex-wiki` is installed, `docs/structure.md` is an ordinary repo-relative path an operator can add under the `architect` role like any other guideline file — this wizard does not special-case it.

For each entered path, validate it exists relative to the repo root; if it does not, warn and ask whether to proceed (keep it as a forward declaration, matching Step 4's `source.paths` validation pattern) or correct it.

```
Context (print before asking):
- Where: Step 7 — Guideline path validation; target `<repo-root>/<path>`
- Found: `<path>` does not exist relative to the repo root
- Why asking: a typo and a forward declaration look the same — only the operator knows which
- Answers: `proceed` — keep `<path>` under role `<role>` as a forward declaration (it warns in `# History` on every dispatch until it resolves); `correct` — re-ask the paths for role `<role>`
AskUserQuestion: header "Missing guideline", question "`<path>` (role `<role>`) does not exist in <repo>. Keep it as a forward declaration, or correct it?", options `proceed` / `correct` with the descriptions above.
```

Outcome: `guidelines-set`, `no-guidelines`, or (edit mode) `unchanged`.

## Step 9 — Asset types (delegate)

**Nested product:** when the effective record already carries this step's key from an ancestor, outcome `inherited`, no question; edit mode still lets the operator declare an own value, which wins.

Whether to declare any asset types of the product's own (beyond the shipped feature / change / bug / content / research / release set) now. An asset type is a declared kind of asset (characters / scenes / chapters / …) written into `products[<key>].asset_types.<name>`, carrying its icon, its primary document (the type's `start_doc` — the attach target; a fresh asset spawns with no documents), its default tools, the folder its assets land in by default, and the playbook the coordinator works them under.

```
Context (print before asking):
- Where: Step 9 — Asset types; target `products[<key>].asset_types`
- Found: declared types on record: <names, or "none">; shipped types need no declaration: feature / change / bug / content / research / release
- Why asking: which kinds of asset the product has beyond the shipped set is content design only the operator knows
- Answers: `declare types now` — nothing written here; after Step 13 the operator runs `/lazy-spec.add-asset-type <compound-key>` once per type (a dedicated skill's job, not an inline branch of this wizard; outcome `delegated`, instruction surfaced in the Report); `none (shipped types only)` — outcome `shipped-only`. Declaring a type creates nothing on disk — every group folder, shipped types included, appears only at the first `create-asset` that lands an asset in it, seeded with its group folder-note by the scaffold; a type's design / code-plan / test-plan docs are covered by the shared behavior-keyed review classes `/lazy-spec.install` seeds, so no per-type class exists
AskUserQuestion: header "Asset types", question "Does product `<key>` need asset types of its own (characters / scenes / chapters / …) beyond the shipped feature / change / bug / content / research / release set? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `declare types now` / `none (shipped types only)` with the descriptions above.
```

- **declare types now** → after this skill finishes (Step 13 done), the operator runs `/lazy-spec.add-asset-type <compound-key>` once per type. Do NOT inline-duplicate that flow — surface the instruction in the Report (outcome `delegated`). Do NOT call `lazy-spec.add-asset-type` from here; the product must be fully written and audited first.
- **none** → outcome `shipped-only`.

Outcome: `delegated` or `shipped-only`.

## Step 10 — Workflow mode (full vs spec-only)

**Nested product:** when the effective record already carries this step's key from an ancestor, outcome `inherited`, no question; edit mode still lets the operator declare an own value, which wins.

The product's workflow profile. In edit mode, default the menu to the product's current value (absent reads as `full`).

```
Context (print before asking):
- Where: Step 10 — Workflow mode; target `products[<key>].mode`
- Found: `mode` on record: <"spec-only", or absent → full>
- Why asking: a per-product commitment, not a per-asset toggle — every asset under the product follows the chosen ladder, and only the operator knows whether specs are the whole deliverable
- Answers: `full (default — design through implementation and testing)` — no key written; every asset's ladder is design-only (start document → review → approve → `spec_design_done`) and the product's releases carry the implementation (`lazy-spec.release-playbook.md`); `spec-only (design and review only; released by operator word)` — `mode: "spec-only"` written in Step 11; the product owns no releases, `Start release` never hangs, and `spec_released` flips only on an explicit operator word — for a product whose specs are the whole deliverable (a design-only reference other repos consume, not code this repo will itself implement)
AskUserQuestion: header "Workflow mode", question "How far does the coordinator's ladder run for every asset of product `<key>` — full, or spec-only? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `full (default — design through implementation and testing)` / `spec-only (design and review only; released by operator word)` with the descriptions above.
```

Capture `<mode>` only when `spec-only` is chosen; absent/`full` writes no key (matching the "absence = full mode" contract).

Outcome: `spec-only` or `full` (no key written).

## Step 10b — Release (implementer, manifest, deploy targets)

Only for a product that owns releases: Step 4 produced a `source` block, no enclosing product declares a `source`, and Step 10 kept `full`. Otherwise outcome `no-releases`, no question. In edit mode default every menu to the record's current `release` values.

1. **Implementer.** The expert key that leads every release build. Resolve `<default>` first with `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" resolve-product release-implementer <key>`: it prints `{"key": "<key>", "implementer": <expert-or-null>}` — the record's explicit `release.implementer` when set, else the first registered expert of the product's `release.implementer_chain`, else of the repository's `spec.release.implementer_chain` (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`). A key not yet registered (create mode) resolves through the repository chain alone.

   ```
   Context (print before asking):
   - Where: Step 10b — Release implementer; target `products[<key>].release.implementer` / `.implementer_chain`
   - Found: `release.implementer` on record: <key, or absent>; `release.implementer_chain` on record: <list, or absent>; `spec.release.implementer_chain`: <list, or absent>; resolved now: <implementer, or none>; registered experts: <keys>
   - Why asking: one implementer answers for the whole product inside a release and delegates every foreign tool; the repository chain may not fit what this product is made of, and a null resolution leaves the release with no one to build it
   - Answers: `<default> (inherited)` — no `implementer` and no `implementer_chain` written in create mode (edit mode keeps whichever the record holds); the implementer follows the chain whenever it or the expert registry changes; `explicit expert` — a registered expert key via "other", written as `release.implementer`, which wins over every chain; `product chain` — an ordered list of registered expert keys via "other", comma-separated, written as `release.implementer_chain` and replacing the repository chain for this product entirely
   AskUserQuestion: header "Implementer", question "Which expert leads every release build of product `<key>` — the inherited `<default>`, an explicit expert, or a chain of the product's own? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.release-playbook.md", options `<default> (inherited)` / `explicit expert` / `product chain`.
   ```

   When `<default>` resolves to none, the `<default> (inherited)` option reads `none (inherited)` and its description says that no build can run until an expert is named or registered.

2. **Manifest.** The repo-relative file whose version field a published release reads and writes.

   ```
   Context (print before asking):
   - Where: Step 10b — Release manifest; target `products[<key>].release.manifest`
   - Found: `release.manifest` on record: <path, or absent>; candidates under `<source.paths>`: <plugin.json / package.json / pyproject.toml / manifest.json found, or none>
   - Why asking: the previous version is read from the manifest and the published one written back; without one the version chain starts from the highest published release, then `0.1.0`
   - Answers: `<candidate>` — written as `release.manifest`; `none` — no key, versions chain through the published releases alone
   AskUserQuestion: header "Manifest", question "Which file carries product `<key>`'s version?", one option per candidate plus `none`.
   ```

3. **Deploy targets.** Up to two, `staging` and `production`, each `{ "command": [<argv>], "url": "<address>" }`.

   ```
   Context (print before asking):
   - Where: Step 10b — Deploy targets; target `products[<key>].release.deploy.staging` / `.production`
   - Found: targets on record: <staging: command/url or absent; production: command/url or absent>
   - Why asking: a built release is deployed to `staging` automatically before its tests and to `production` on `Publish`; only the operator knows the commands and addresses, and a product may have neither
   - Answers: `none` — no `deploy` key, tests run against a local instance and `Publish` sets `spec_released` at once; `staging only` / `production only` / `both` — for each chosen target, the argv (via "other", space-separated, run from the repo root) and an optional address shown beside `Publish`
   AskUserQuestion: header "Deploy targets", question "Does product `<key>` deploy anywhere — a staging instance to test against, a production target to publish to, both, or neither?", options `none` / `staging only` / `production only` / `both`.
   ```

Capture `<release>` = `{ implementer?, implementer_chain?, manifest?, deploy? }`; only the keys the operator settled are written — the inherited answer settles neither implementer key.

Outcome: `release-configured`, `unchanged`, or `no-releases`.

## Step 11 — Write product record + scaffold folders + folder-notes

Each settings mutation is one keyed write: `settings-set products --key <a>/<b>/…` replaces exactly the value at that path and leaves every other product and every other field as it is. The product record carries the gathered fields:

- `spec_path` (always).
- `language` — only when Step 3 set a concrete override.
- `icon` — always: the Step 6 value, or the default `LiPackage` when the operator declined.
- `guidelines` — only when Step 7 produced at least one role's paths.
- `source` — `{ paths }` only when Step 4 produced a source block.
- `dependencies` — only when Step 5 accepted at least one entry.
- `mode` — only when Step 10 captured `spec-only`; absent/`full` writes no key.
- `release` — only when Step 10b settled at least one key: `implementer` or `implementer_chain` when the operator named one, `manifest` and `deploy` when settled; an empty `release` is never written.

**Create mode**: write the whole record at its own key:

```bash
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set products --key <compound-key> --value '<record-json>'
```

**Edit mode**: start from the existing record captured in Step 2 and write one call per field that changed — add `source` to a design-only product, extend `dependencies`, switch `language` / `icon` / `guidelines` / `mode` / `release` — each as `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set products --key <compound-key>/<field> --value '<field-json>'` (`<field>` one of `source`, `dependencies`, `language`, `icon`, `guidelines`, `mode`, `release`). `asset_types` / `tool_types` and every untouched field are never written, so they stay as they are. Never emit empty `dependencies: []` or an empty `source`; likewise, a Step 7 outcome of `no-guidelines` or an `unchanged`/`remove a role's paths` edit that empties every role means an absent `guidelines` key, never an empty `guidelines: {}` — a field that must go away is removed with `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set products --key <compound-key>/<field> --delete`.

Initialize the on-disk structure (create mode, or any missing piece in edit mode). Use two separate calls for each folder-note — `Bash(mkdir -p <dir>)` then the `Write` tool (never chain):

1. **No group folders are pre-created.** `changes/`, `bugs/`, and every declared type's folder appear lazily — the first `create-asset` landing an asset in one creates the folder and seeds its group folder-note (`lazy-spec.layout-protocol.md` Part 1). NO `backlog/`, and NO per-product `requests/` — the request inbox is a single vault-root folder, created once in step 3 below (a request may target multiple products, so it is never per-product; see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md`).
2. **Product level note** `<spec_path>/<leaf>.md` (`<leaf>` = the final segment of `spec_path`) — the folder-note `spec.catalog-coordinator` owns (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md`). Never hand-written here: one verb creates it, or brings an existing one up to the level schema without disturbing what the operator put in it.

   ```bash
   "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" catalog-note backfill <compound-key>
   ```

   The verb writes `spec_role: product`, the five level gates at `false`, `spec_halted: false`, and the managed paint keys — `iconize_icon` from the Step 6 value (the operator's, or the default `LiPackage`) and `iconize_color` from `products[<key>].color` when the record declares one, otherwise the product default `#64748b` — plus the coordinator's own body sections (`# Summary`, `# Gates`, `# Attachments`, `# Status brief`, `# Coordinator rules`, `# Coordinator commands`, `# History`). On an existing note it adds only what is missing: no key is rewritten, no section is moved, and the operator's `# Coordinator rules` and rendered `# Summary` survive byte-for-byte. A product root is the only ordinary container that carries a colour; group folders beneath it carry none (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Container colour). Run the verb in edit mode too — it is idempotent, and a note that predates the level schema gains it here.

   Then author the note's `<!-- spec:precis -->` region — one-line description drawn from the product's design intent — inline between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers of its `# Summary` section, replacing any `_TBD` placeholder, and run `render-container-stats` so the `<!-- spec:stats:* -->` region is populated:

   ```bash
   "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" render-container-stats <content_root>/<spec_path>/<leaf>.md
   ```

   Fold the verb's returned `note` path into this step's own commit.

   A new product also changes the `N products` count of every level above it. Run the same verb on each folder-note between the product and the content root, up to and including the catalog root's note `<content_root>/<content_root leaf>.md` — the verb leaves a note without stats markers alone — and fold every note it rewrites into the same commit.

3. **Product-level `vision.md`** (create mode only): if `<content_root>/<spec_path>/vision.md` does not exist AND `<content_root>/<spec_path>/design.md` does not exist either (the seeding guard — a product with a pre-vision `design.md` is a legal state migrated by the operator by hand, never seeded over), seed it beside the level note item 2 just wrote — never by copying the template yourself:

   ```bash
   "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" seed-doc --root <content_root>/<spec_path>/<leaf>.md --doc vision.md:system-vision
   ```

   The primitive resolves the product from the note's folder, instantiates the `system-vision` type's template with every token filled (`{{product}}`, `{{product_tag}}`), injects the type's `iconize_icon` / `iconize_color`, sets `spec_stage: empty` — the same file a coordinator's launch checkbox would produce; seeding journals nothing. Fold the returned `doc` path into this step's own commit. The seeding is the whole obligation — no gate and no doctor check exists at this level. Outcome: `vision-seeded`, `vision-already-present`, or `vision-skipped-pre-vision-design`.
4. **Vault-root request inbox** (shared by every product — created once, idempotent): resolve the spec content-root `<content_root> = <repo>/<spec.vault_root>` (default `specs`; read `spec.vault_root` from `.claude/lazy.settings.json`). Ensure `<content_root>/requests/` exists (`Bash(mkdir -p <content_root>/requests)`). ALWAYS `Write` `<content_root>/requests/requests.md` when absent as the operator-zone inbox folder-note (`iconize_icon: LiInbox`, `iconize_color: "#f0abfc"` — the intake-shelf accent, double-quoted, NO `spec_role`, the `# Summary` skeleton from the group-note template with the static précis `Vault-wide request intake inbox.` filled in, then operator-zone body) and ALWAYS `git add` it so the `requests/` directory is committed and pushed even with zero request files. If it already exists, leave the body untouched (stats are refreshed by the event-driven primitive). When creating the requests inbox, run `render-container-stats` on it too:

   ```bash
   "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" render-container-stats <content_root>/requests/requests.md
   ```

Real icon values are fine — the iconize hook only strips unresolvable placeholder icon values, not concrete ones.

Outcome: `written`.

Product-specific reviewers are added as `<kind>@<key>` classes through `/lazy-review.configure`.

## Step 13 — Verify

Invoke `/lazy-spec.audit <compound-key>` via the `Skill` tool (`skill: "lazycortex-specs:lazy-spec.audit"`) to confirm the product record, folder tree, and folder-notes are consistent. Surface its findings.

Outcome: `verified`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with the `lazy-spec.audit` summary line from Step 13. If Step 9 was `delegated`, include the `/lazy-spec.add-asset-type <compound-key>` instruction.

## Failure modes

- **`/lazy-spec.product-config` aborts with `aborted:no-vault-spec`** — create mode with neither `vision.md` nor a pre-vision `design.md` at the spec content-root → run `/lazy-spec.install` (its Step 6.9 seeds the vault-vision draft), fill it in, then re-run this skill.
- **`/lazy-spec.product-config` refuses because the product key already exists** — the chosen key is already a `products` key → edit that product instead, or pick a different key.
