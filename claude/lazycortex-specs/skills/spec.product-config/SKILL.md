---
name: spec.product-config
description: Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the on-disk folder tree + operator-zone folder-notes with iconize icons, generates or reuses the shared vault-wide behavior-keyed review classes (one per doc-kind, right-anchored wildcard globs spanning every product and asset category; a product with divergent experts gets a per-product override), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_categories.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Task, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Configure Product

Unified wizard that owns the product-registration lifecycle. One entry point for **creating a new product** (with source code, or design-only) and for **editing an existing product** (add `source` to a design-only product, extend `dependencies`, switch `language` / `icon`). The product record lives in `lazy.settings.json[products][<compound-key>]`, read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`. On save the skill scaffolds the on-disk folder tree, writes operator-zone folder-notes carrying iconize icons, and generates or reuses the shared review classes so the product's design / tech / feature / change / bug docs flow through the review loop.

Repo records are NOT part of this product record — they live in the cross-plugin `lazy.settings.json[repos]` section (read/written via `lazycortex-core settings-get repos` / `lazycortex-core settings-set repos`) and are resolved by `spec.resolve-repo`. The inline repo wizard in Step 4 writes a `repos[<repo-key>]` record when the operator attaches a new source repo. The product `language` overrides the repo-global `spec.default_language` (the `default_language` key in the `spec` settings section) for narrative prose this product emits.

## Execution discipline (MANDATORY — read before any action)

This skill has 11 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Mode detection + resolve registry`
   - `Step 2 — Derive compound-key / subsystem / namespace / spec_path`
   - `Step 3 — Language`
   - `Step 4 — Source (repo + paths, or design-only)`
   - `Step 5 — Dependencies (autodetect + confirm)`
   - `Step 6 — Product icon`
   - `Step 7 — Built-in review experts (designer / developer / tester / historian)`
   - `Step 8 — Asset categories (delegate)`
   - `Step 9 — Write product record + scaffold folders + folder-notes`
   - `Step 10 — Built-in review classes + routine sync + audit`
   - `Step 11 — Verify + log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, `design-only`, `taken-from-arg`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer. Never ask a bare one-line question. Never present options as plain-text prose.

All narrative prose this skill authors (folder-note bodies) is rendered in the product's effective `language`. Frontmatter keys, fixed headers, wikilinks, settings JSON, review-class `class` labels, and section ids stay English.

## Input

The user provides one of:

1. A natural-language request ("new product for X", "edit chapter settings", "add source to Tester/chapter", …).
2. A product compound-key (new or existing) or a path under an existing product's `spec_path`.
3. Nothing — the skill asks whether to create or edit.

## Step 1 — Mode detection + resolve registry

Read the products section and the existing repo records once:

```bash
lazycortex-core settings-get products
lazycortex-core settings-get repos
```

The first prints the `products` object — each key is a compound-key, each value a record (`spec_path`, optional `language`, `icon`, `source`, `dependencies`, `asset_categories`). The second prints the `repos` object — each key is a repo key, each value a record (`local_path`, `branch`, optional `forge`); this is the repo registry the source step offers. Ignore the `_version` key in each section.

Resolve the user's input to a mode:

- If the input resolves to an existing product key (or a path under an existing product's `spec_path`) via the "Resolving a Product" protocol in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` → **edit mode** (jump to Step 2's edit branch, then Step 9 writes the merged record).
- Otherwise → **create mode**.

When intent is ambiguous (e.g. the user just says "configure product"), `AskUserQuestion` whether they want to create a new product or edit an existing one, then proceed.

The products object + `repos` section drive: uniqueness of the new compound-key, flat-product validation (`spec_path` not nested under another product's `spec_path` per `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`), subsystem/namespace folder candidates, and registered-repo options.

Outcome: `create` or `edit`.

## Step 2 — Derive compound-key / subsystem / namespace / spec_path

**Create mode.** Build the compound-key `<subsystem>[-<namespace>]-<product>` (each segment the vault folder name lowercased-with-hyphens) by deriving its parts:

1. **Product leaf** — `AskUserQuestion` for the product folder name (the leaf segment, e.g. `chapter`). Stem: this is the leaf folder created under the subsystem/namespace and the trailing segment of the compound-key written into `products[<key>]`. Why-it-matters: the leaf is the product's stable identity across config, folder layout, and every review-class `paths` glob. Validate lowercase-with-hyphens per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.
2. **Subsystem** — `AskUserQuestion`. Options are the existing top-level TitleCase folders discovered under the vault root, plus an "other — new subsystem" free-text path. Stem: the subsystem is the top-level TitleCase folder the product lives under and the first segment of the compound-key. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.
3. **Namespace** — `AskUserQuestion` whether to place the product directly under the subsystem or inside an optional namespace grouping folder. If inside, offer existing TitleCase namespace folders under the chosen subsystem plus an "other — new namespace" path. Skip this question (outcome `no-namespace`) only when the user explicitly declines grouping. Stem: a namespace is an optional TitleCase grouping folder collecting related sibling products; present iff chosen, it becomes the middle segment of the compound-key. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.
4. **Spec path** — auto-derive `<Subsystem>/[<Namespace>/]<leaf>`. `AskUserQuestion` to confirm with options `confirm` and `edit` (type a different vault-relative path). Validate: not nested inside another product's `spec_path`; the derived compound-key is unique among existing `products` keys; the folder does not already exist on disk unless the user is registering a spec on top of a pre-created folder. Stem: `spec_path` is where this product's specs live, vault-relative; it is written into `products[<key>].spec_path` and is the root every review-class glob hangs off. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

**Edit mode.** Present the current record (its JSON block as the `AskUserQuestion` preview) and confirm this is the correct product. The compound-key, subsystem, namespace, and `spec_path` are FIXED in edit mode — this skill does not rename or move products. Capture the existing record fields (`spec_path`, `language`, `icon`, `source`, `dependencies`, `asset_categories`) to merge into; never drop a field the user does not touch.

Outcome: `derived` (create) or `confirmed` (edit).

## Step 3 — Language

`AskUserQuestion` for the product language (optional override of the repo-global `spec.default_language`). Stem: `language` is the ISO 639-1 code skills use when writing this product's narrative prose; written into `products[<key>].language` it overrides the `default_language` key in the `spec` settings section for this product only. Why-it-matters: this drives localization of generated folder-note bodies and design/tech prose — fixed headers and frontmatter keys stay English regardless. Offer `inherit default (no override)` (omit the field; the product follows `spec.default_language`), `en`, plus an "other — type an ISO 639-1 code" path. In edit mode, default the menu to the product's current value. Capture `<language>` only when the user picks a concrete override; treat `inherit default` as absent. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

Outcome: `set` or `inherit-default`.

## Step 4 — Source (repo + paths, or design-only)

A product is **design-only** when it carries no `source` block (specs authored ahead of code). Otherwise `source` is `{ repo: <repo-key>, paths: [<path>, …] }`.

1. `AskUserQuestion` whether this product has source code. Stem: `source` maps the product to a repo checkout and the subdirectories within it the product covers; written into `products[<key>].source` it is what dependency autodetect and `spec.source-url` read. Why-it-matters: a design-only product (no `source`) skips code-grounded autodetect and source links until source is added later in edit mode. Options: `has source code` and `design-only (no source)`. In edit mode this is where a design-only product gains a `source` block. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

   - **design-only** → record no `source`; skip the rest of this step (outcome `design-only`) and skip Step 5's autodetect.

2. **Repo** — `AskUserQuestion`. Options: each registered repo key (from the `repos` section read in Step 1) + an "other — register a new repo" path. If the user picks the latter, run the **inline repo wizard** (below) before continuing. Stem: `source.repo` is the key of the `lazy.settings.json[repos]` record whose checkout holds this product's code. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`.

3. **Paths** — `AskUserQuestion`. Offer `single subpath` (one string via "other"), `multiple subpaths` (comma-separated via "other"). Stem: `source.paths` is the list of subdirectories within the repo checkout this product covers; it bounds dependency autodetect and source-url resolution. For each path, validate it exists under the resolved repo's `local_path`; if any does not exist, warn and `AskUserQuestion` whether to proceed (keep the path as a forward declaration) or correct it. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

Outcome: `sourced` or `design-only`.

### Inline repo wizard

Triggered from Step 4 when `source.repo` names an unregistered repo:

1. `AskUserQuestion` for the repo key (lowercase-with-hyphens, e.g. `backend`, `shared`). Validate uniqueness among the keys in the `repos` section read in Step 1.
2. `AskUserQuestion` for `local_path`. Stem: `local_path` is where `spec.resolve-repo` reads this repo's source and git remote. Why-it-matters: an absolute path pins the repo to one machine's checkout; `"."` (same-repo) stays checkout-agnostic. Options: `this repo (.)` — the code lives in the very repo that holds `lazy.settings.json`; write the literal `"."` and every checkout (dev, or a runtime checkout under `~/lazy-runtime/<repo>`) resolves it to its own root via `git rev-parse --show-toplevel`, so no absolute path leaks into the tracked settings; and `absolute path` — a fixed checkout elsewhere on this machine (the cross-repo case, e.g. a separate spec-vault and code repo), typed via "other". Validate existence: for `"."` run `git rev-parse --show-toplevel` (cwd must be a git repo); for an absolute path, the directory exists and is a git repo. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.
3. Auto-detect the default branch:

   ```bash
   git -C <local_path> symbolic-ref --short refs/remotes/<remote-name>/HEAD 2>/dev/null \
     | sed 's@^[^/]*/@@' \
     || git -C <local_path> rev-parse --abbrev-ref HEAD
   ```

4. `AskUserQuestion` to confirm detected `local_path` + `branch` before writing.
5. Write the new repo record into the cross-plugin `repos` section, preserving every other repo and the section's `_version`. Read-modify-write atomically:

   ```bash
   lazycortex-core settings-get repos
   ```

   In the parsed object, set `repos[<repo-key>]` to `{ "local_path": <local_path>, "branch": <branch> }`; add `"forge": <key>` ONLY when the host is not in the known-forges table (per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`) — otherwise omit it so `spec.resolve-repo` auto-detects. The remote URL and forge type are NOT written — they are derived at runtime by `spec.resolve-repo`. Then write the whole object back:

   ```bash
   printf '%s' '<edited-repos-json>' | lazycortex-core settings-set repos
   ```

## Step 5 — Dependencies (autodetect + confirm)

When `source.paths` is non-empty and the paths exist, dispatch **one Explore subagent** (`subagent_type: "Explore"`, `mode: "dontAsk"`, read-only) to scan imports/requires within `<repo-config>.local_path/<each source.path>`. Skip this step entirely for a design-only product (outcome `design-only`).

The agent's prompt must include: the exact globs to scan (source.paths under local_path); the set of registered product `source.paths` (to classify candidates as `internal-product`); the set of registered repo `local_path` values (to classify candidates crossing into a different repo as `repo` kind); the structured-report contract below; and a word budget ("Report under 400 words").

Expected report block (per the parallel-scan coordinator pattern in `claude/lazycortex-core/references/lazy-core.parallel-scan.md`):

```markdown
## scan: dependencies

### findings
- [DEP] <dep-label> | <import-path-or-package-name>
  kind: internal-product | repo | external
  evidence: <file>:<line> — <import line>
  suggest: <dep entry snippet>

### summary
internal: <n>  repo: <n>  external: <n>
```

Classification:

- **internal-product** — imported path falls under another registered product's `source.paths`. Suggest a dep entry resolved via `spec.resolve-dependency` (see `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`).
- **repo** — imported path crosses into a different registered repo's `local_path` but not into a specific product. Suggest a `{repo: <key>}` dep.
- **external** — third-party package from a manifest (`requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`, …). Listed but not added by default.

Iterate candidates **one `AskUserQuestion` call per candidate** with options `add`, `skip` (with "other" for a free-text note). Keep one running list. In edit mode, append accepted entries to the existing `dependencies` list (never clobber prior entries); never emit an empty `dependencies: []`.

Outcome: `confirmed`, `design-only`, or `none`.

## Step 6 — Product icon

`AskUserQuestion` for the optional product icon. Stem: the icon is the iconize identifier (a Lucide name like `LiBook`, or a literal emoji) written into BOTH `products[<key>].icon` AND the product folder-note's managed `iconize_icon` frontmatter; the Obsidian iconize system paints it on the product folder. Why-it-matters: the icon is how the operator visually distinguishes this product in the file explorer — omit it and the product folder-note carries no `iconize_icon` key. Offer a couple of concrete suggestions plus `none (no icon)` and an "other — type your own" path. In edit mode, default to the product's current icon. Capture `<icon>` only when a real value is given; treat `none` as absent. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Outcome: `iconed` or `no-icon`.

## Step 7 — Built-in review experts (designer / developer / tester / historian)

The built-in review classes generated in Step 10 are driven by three roles — `designer`, `developer`, `tester` — plus a historian. These experts are **shared vault-wide**: one common set of four review classes serves every product whose role-experts are identical, so a second product normally reuses the first product's experts rather than adding its own classes (see Step 10). Read the available expert names and the current review classes first:

```bash
lazycortex-core settings-get experts
lazycortex-core settings-get review
```

The keys of the first printed object are the registered expert names. In the second, the **shared set** is the four classes whose `class` labels are the bare doc-kinds `design`, `plan`, `tech`, `bug` (no `@<key>` suffix). Determine the path:

- **Shared set absent** (no bare-label `design`/`plan`/`tech`/`bug` class — the usual first-product case) → ask the role questions below; the answers seed the shared set in Step 10. Outcome `assigned`.
- **Shared set present** → `AskUserQuestion` whether this product rides the shared experts or defines a product-specific override. Stem: the vault already carries a shared review-expert set (name the experts read from the shared classes); reusing it adds NO new review classes for this product, while an override generates four product-scoped `<kind>@<key>` classes that shadow the shared set for this product only (Step 10 inserts them earlier in the list so first-match-wins routes this product's docs to them). Why-it-matters: overrides exist for a product whose design / plan / bug docs need a different persona than the rest of the vault — every other product keeps riding the shared set. Options: `use shared experts` and `define product-specific override`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.
  - **use shared experts** → read the four experts from the shared classes (`designer` = the `design` class `experts.main[0].name`, `developer` = the `plan` class main writer, `tester` = the `bug` class main writer, `historian` = any shared class `experts.history.name`) and do NOT ask the role questions. Outcome `shared-set`.
  - **define product-specific override** → ask the role questions below; the answers drive this product's override classes in Step 10. Outcome `override`.

Role questions (asked only on the `assigned` and `override` paths — skipped on `shared-set`): for EACH of the three roles in order (`designer`, then `developer`, then `tester`), issue a SEPARATE `AskUserQuestion` (one per role) offering the registered expert names as options. Stem for each: name the role and where it lands in the built-in classes (Step 10) — `designer` is the main writer of the `design` class ONLY and is never a validation writer; `developer` is the main writer of the `plan` and `tech` classes and a section validator on the design and bug classes; `tester` is the main writer of `bug` and the sole section validator on the plan class (plus a section validator on the design class). Why-it-matters: the chosen expert's persona is what actually reviews/writes the product's design / tech / plan / bug docs in the review loop. Each question MUST offer an "other — define a new persona" path whose per-option copy points the operator at `lazycortex-experts` to compose a new expert, then re-run this skill (do NOT invent an expert name — only names present in `settings-get experts` are valid). See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

Then `AskUserQuestion` for the historian — single-select from the expert names, default `review.historian`. Stem: the historian writes the `# History` section of every reviewed doc across all built-in classes. Why-it-matters: it is the `experts.history` writer; it must be an expert registered with commit permission in the local repo. On the `shared-set` path the historian is read from the shared classes, not asked.

Validate that every chosen role expert (designer / developer / tester / historian) is a key in `settings-get experts`. If any chosen name is the "other" sentinel, abort with the `lazycortex-experts` pointer and do NOT write — the product is not registered until real expert names exist.

Outcome: `assigned`, `shared-set`, or `override` (or abort `expert-undefined`).

## Step 8 — Asset categories (delegate)

`AskUserQuestion` whether to register any operator-defined asset categories (beyond the built-in feature / change / bug set) now. Stem: an asset category is an operator-defined kind (characters / scenes / chapters / …) registered under `products[<key>].asset_categories`; each gets its own folder and folder-note — its design/plan docs are covered automatically by the shared behavior-keyed review classes (Step 10's right-anchored wildcard globs), no per-category class exists. Why-it-matters: the built-in feature / change / bug categories are always created in Step 9 — extra categories are added by a dedicated skill, not inline here. Options: `add categories now` and `none (built-in only)`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

- **add categories now** → after this skill finishes (Step 11 done), the operator runs `/spec.add-asset-category <compound-key>` once per category. Do NOT inline-duplicate that flow — surface the instruction in the Report (outcome `delegated`). Do NOT call `spec.add-asset-category` from here; the product must be fully written and audited first.
- **none** → outcome `built-in-only`.

Outcome: `delegated` or `built-in-only`.

## Step 9 — Write product record + scaffold folders + folder-notes

Each settings mutation is an atomic read-modify-write. Read the products section, edit the in-memory object, write it back:

```bash
lazycortex-core settings-get products
```

In the parsed object, set `products[<compound-key>]` to the gathered fields:

- `spec_path` (always).
- `language` — only when Step 3 set a concrete override.
- `icon` — only when Step 6 captured a value.
- `source` — `{ repo, paths }` only when Step 4 produced a source block.
- `dependencies` — only when Step 5 accepted at least one entry.

**Edit mode**: start from the existing record captured in Step 2 and merge — add `source` to a design-only product, extend `dependencies`, switch `language` / `icon` — while preserving `asset_categories` and every untouched field. Never emit empty `dependencies: []` or an empty `source`. Then write the whole products object back:

```bash
printf '%s' '<edited-products-json>' | lazycortex-core settings-set products
```

Initialize the on-disk structure (create mode, or any missing piece in edit mode). Use two separate calls for each folder-note — `Bash(mkdir -p <dir>)` then the `Write` tool (never chain):

1. Empty category dirs under `spec_path`: `features/`, `changes/`, `bugs/`. NO `backlog/`, and NO per-product `requests/` — the request inbox is a single vault-root folder, created once in step 4 below (a request may target multiple products, so it is never per-product; see `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md`).
2. **Product folder-note** `<spec_path>/<leaf>.md` — an operator-zone folder-note. Frontmatter: `iconize_icon: <icon>` ONLY when Step 6 captured an icon. NO `spec_role`. Body: the protected `# Summary` skeleton first, then operator-zone body after the closing stats marker:

   ```markdown
   # Summary
   #protected/spec/summary
   <!-- spec:precis:start -->
   _TBD — one-line description; regenerated on refresh._
   <!-- spec:precis:end -->
   <!-- spec:stats:start -->

   <!-- spec:stats:end -->

   <!-- Body below is operator-zone. The plugin owns only the # Summary section above. -->
   ```

3. **Built-in category folder-notes** — one operator-zone folder-note per built-in category, each carrying `iconize_icon` and NO `spec_role`, NO `*-index` role, NO dataviewjs (operator owns the body):
   - `features/features.md` — default icon `LiRocket`.
   - `changes/changes.md` — default icon `LiRefreshCcw`.
   - `bugs/bugs.md` — default icon `LiBug`.

   A default icon is overridable: if the gathered record carries `asset_categories[<name>].icon` for the built-in name (`feature` / `change` / `bug`), use that value instead. Each folder-note body uses the same protected `# Summary` skeleton shown in item 2 above (précis placeholder + stats markers + operator-zone comment), substituting the category leaf name in any narrative prose the product's language requires.

   After writing all folder-notes (items 2 and 3), author the `<!-- spec:precis -->` region for each container note — one-line description drawn from the product's design intent (for the product root) and the category purpose (for each built-in category) — and write the précis inline between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers, replacing the `_TBD` placeholder. Then run `render-container-stats` for each container note so the `<!-- spec:stats:* -->` region is populated:

   ```bash
   lazycortex-specs render-container-stats <content_root>/<spec_path>/<leaf>.md
   lazycortex-specs render-container-stats <content_root>/<spec_path>/features/features.md
   lazycortex-specs render-container-stats <content_root>/<spec_path>/changes/changes.md
   lazycortex-specs render-container-stats <content_root>/<spec_path>/bugs/bugs.md
   ```

4. **Vault-root request inbox** (shared by every product — created once, idempotent): resolve the spec content-root `<content_root> = <repo>/<spec.vault_root>` (default `specs`; read `spec.vault_root` from `.claude/lazy.settings.json`). Ensure `<content_root>/requests/` exists (`Bash(mkdir -p <content_root>/requests)`). ALWAYS `Write` `<content_root>/requests/requests.md` when absent as the operator-zone inbox folder-note (`iconize_icon: LiInbox`, NO `spec_role`, the `# Summary` skeleton from the group-note template with the static précis `Vault-wide request intake inbox.` filled in, then operator-zone body) and ALWAYS `git add` it so the `requests/` directory is committed and pushed even with zero request files. If it already exists, leave the body untouched (stats are refreshed by the event-driven primitive). When creating the requests inbox, run `render-container-stats` on it too:

   ```bash
   lazycortex-specs render-container-stats <content_root>/requests/requests.md
   ```

Real icon values are fine — the iconize hook only strips unresolvable placeholder icon values, not concrete ones.

Outcome: `written`.

## Step 10 — Built-in review classes + routine sync + audit

Append the built-in review classes to `review.classes`. Read the section, append, write back:

```bash
lazycortex-core settings-get review
```

In the parsed object, write the classes below into `review.classes` (create the list if absent) per the reconcile rule further down. **The review-class schema is owned by `lazycortex-review`** — match it exactly:

- Each class is an object with a `class` string label (human-readable identity; there is NO `id` field — the daemon matches files to classes purely by `paths` globs), a `paths` non-empty list of glob strings, and an `experts` object.
- `experts.main` — a LIST of `{ "name": <expert> }` writer objects (the opening-writer chain).
- `experts.validation` and `experts.terminal` — a DICT keyed by stable `section-id` (`^[a-z][a-z0-9_-]*$`), each value a writer object `{ "name": <expert>, "section": "<H1 title>", "position": "top" | "bottom" }`. These author named post-approve H1 sections; `validation` sections block finalize and trigger revert-to-main on concerns. There is NO flat "list of reviewers" bucket — a reviewer is expressed as one named validation section.
- `experts.history` — a single `{ "name": <historian> }` object (no `repo`, no `@<repo>` syntax).

The classes are keyed by **behavior** AND shared vault-wide. The **shared set** — four classes with bare doc-kind labels and right-anchored wildcard globs — serves every product whose role-experts match; a product with divergent experts (Step 7 outcome `override`) gets four product-scoped `<kind>@<key>` classes inserted BEFORE the shared set. One class per doc-kind, with globs spanning the product root and every category folder (built-in AND operator-defined) — so `spec.add-asset-category` never touches `review.classes`, a new category needs no new class, and a new product needs no new class when it rides the shared experts. Three reusable validation dicts plus a no-validation case. **`designer` is never a validation writer in any class** — it appears only as a `main` writer; plan validation is tester-only; `tech` carries no validation bucket at all:

- **D = developer + tester review** — `{ "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" }, "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }`.
- **T = tester review** — `{ "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }`.
- **DV = developer review** — `{ "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" } }`.
- **NONE** — omit the `experts.validation` key entirely (no validation writers this iteration).

Every class also carries `experts.history: { "name": "<historian>" }`.

**Shared set** (bare doc-kind labels; substituting `<designer>`, `<developer>`, `<tester>`, `<historian>`) — the four classes every product rides by default:

| `class` label | `paths` | `experts.main` | `experts.validation` |
|---|---|---|---|
| `design` | `["*/design.md"]` | `[{ "name": "<designer>" }]` | D |
| `plan` | `["*/plan.md"]` | `[{ "name": "<developer>" }]` | T |
| `tech` | `["*/tech.md"]` | `[{ "name": "<developer>" }]` | NONE |
| `bug` | `["bugs/*/bug.md"]` | `[{ "name": "<tester>" }]` | DV |

**Override set** (product-scoped labels; generated ONLY on Step 7 outcome `override`, with this product's `<spec_path>` and override experts) — shadows the shared set for one product:

| `class` label | `paths` | `experts.main` | `experts.validation` |
|---|---|---|---|
| `design@<key>` | `["<spec_path>/design.md", "<spec_path>/*/*/design.md"]` | `[{ "name": "<designer>" }]` | D |
| `plan@<key>` | `["<spec_path>/*/*/plan.md"]` | `[{ "name": "<developer>" }]` | T |
| `tech@<key>` | `["<spec_path>/tech.md"]` | `[{ "name": "<developer>" }]` | NONE |
| `bug@<key>` | `["<spec_path>/bugs/*/bug.md"]` | `[{ "name": "<tester>" }]` | DV |

The `class` label is the schema's only identity slot (a `class` field, not `id`): the shared set uses the bare doc-kind, the override set the `<doc-kind>@<key>` value.

**Glob semantics.** The review dispatcher's file→class matcher (`_class_for_file`) uses `PurePath.match` right-anchored, where `*` never crosses `/` and `**` acts as a SINGLE path segment — never write `**` into class paths expecting recursion. (The daemon's md-scan sieve additionally supports recursive `**`, but that concerns only the coarse discovery masks below, never class paths.) Right-anchoring is why the shared globs need no `<spec_path>` prefix: `*/design.md` matches BOTH the product-root `<spec_path>/design.md` (its last two segments) and every asset `<category>/<slug>/design.md`; `bugs/*/bug.md` matches `<spec_path>/bugs/<slug>/bug.md`. The per-product md-scan sieve mask (below) bounds discovery to each product's own subtree, so a bare `*/design.md` never reaches a design doc outside the spec vault. The four shared globs are disjoint within a single product, but a product's override globs deliberately OVERLAP the shared globs — the matcher is **first-match-wins**, so override classes MUST sit earlier in `review.classes` than the shared set. Bug plans (`bugs/<slug>/plan.md`) intentionally fall into the `plan` class via `*/plan.md` — same tester-validated plan behavior; there is no separate bugs-plan class.

**Reconcile, not append.** Read `review.classes` and act per Step 7's outcome:

1. **`assigned` (shared set absent)** — append the four **shared** classes with the Step-7 experts. Then run the *per-product collapse* below to drop any stale `<kind>@<key>` classes this product carries from the old per-product scheme.
2. **`shared-set` (present, reuse)** — leave the shared set untouched; run the *per-product collapse* to drop this product's stale `<kind>@<key>` classes (this is the migration — the product stops carrying its own classes and rides the shared set).
3. **`override` (present, product-specific)** — first compute this product's four override experts; if they are identical to the shared set's experts for every role, there is no divergence, so fall through to the `shared-set` behavior (no override classes written). Otherwise remove any prior `<kind>@<key>` classes for THIS product, then insert the four **override** classes (product-scoped globs, override experts) immediately BEFORE the first shared-set class.

**Per-product collapse.** Remove from `review.classes` every class whose `class` label ends in `@<key>` for THIS `<key>` and whose prefix names a built-in doc-kind (`design`, `plan`, `tech`, `bug`) or a legacy per-category label (`spec.design`, `spec.tech`, `bugs.bug`, `bugs.plan`, `<category>.design`, `<category>.plan` — any dotted prefix). Before removing one, compare its `experts` block to the shared-set class of the same doc-kind: if they **differ**, `AskUserQuestion` first — keep the operator's variant as a product override (re-insert it before the shared set, as in outcome 3) vs collapse it into the shared set. Bare doc-kind labels (the shared set) and `@<key>` labels naming a DIFFERENT product are never touched. This makes Step 10 idempotent across create and edit mode — re-running `/spec.product-config` in edit mode on a product generated under the old per-product scheme IS the migration to the shared set (16 per-product classes on a 4-product vault collapse to 4).

**Expert re-verification (MANDATORY, before the write).** Collect every expert name the classes are about to carry — each `main[].name`, each `validation.<section-id>.name`, each `history.name` — and re-check every one against the keys of `lazycortex-core settings-get experts`. Any name missing → abort WITHOUT calling `settings-set review`, naming the dangling expert and pointing at `lazycortex-experts` (same abort as Step 7's `expert-undefined`). Step 7's earlier validation does not guard this write — a dangling reference (e.g. an unregistered tester) must be impossible to persist.

Write the edited review object back:

```bash
printf '%s' '<edited-review-json>' | lazycortex-core settings-set review
```

Then normalize the `lazy-review.scan` routine — but only when `routines["lazy-review.scan"]` is present (skip silently when absent: daemon-disabled project). (1) Resolve `<content_root>` = the `spec.vault_root` setting (default `specs`); ensure the mask `<content_root>/<spec_path>/**/*.md` is in the routine's `paths` — one coarse scope-root mask per product, nothing filename-specific. When `spec.vault_root` is `.`, the prefix is omitted and the mask is `<spec_path>/**/*.md`. **Warning:** `**`-bearing sieve masks are matched anchored at the repo root (unlike class `paths`, which the dispatcher matches right-anchored), so the mask MUST carry the content-root prefix — a mask missing it matches nothing under the default `specs/` layout. (2) Remove every legacy mask this union scheme wrote for this product, in BOTH shapes — with or without the content-root prefix — that falls under this product's subtree and ends in a concrete doc filename or is otherwise subsumed by the new mask. (3) Inside `filter.frontmatter` set `review_active` to `{"in": [true], "not_in": []}` (drop the legacy `null` leg). (4) Set `interval_sec` to `60` when it still carries the legacy `5` (minute cadence for coarse scans; an operator-chosen value other than 5 stays untouched). Discovery is deliberately coarse: class `paths` do the precise routing at dispatch time, and the frontmatter filter admits only opted-in files, so a new category, doc-kind, or nesting depth inside the product never touches the sieve — only a new product adds its one mask. Idempotent — re-running on an already-normalized routine changes nothing. Finally, verify the generated classes by invoking `/lazy-review.audit` via the `Skill` tool (`skill: "lazycortex-review:lazy-review.audit"`) and surface its findings — report the `audit: <LEVEL> (<N> findings)` line and any FAIL/WARN detail. If the audit reports FAIL, report it; do not silently leave broken classes.

Outcome: `wired` (carry the audit level into the report).

## Step 11 — Verify + log the run

Invoke `/spec.doctor <compound-key>` via the `Skill` tool (`skill: "lazycortex-specs:spec.doctor"`) to confirm the product record, folder tree, and folder-notes are consistent. Surface its findings.

Then, per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.product-config/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.product-config)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC, `date -u +'%Y-%m-%d %H:%M:%S UTC'`), `input` (the arguments passed, or `none`). Body: `# spec.product-config` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `verified` + `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with the `spec.doctor` summary line from Step 11 and the `audit:` line from Step 10. If Step 8 was `delegated`, include the `/spec.add-asset-category <compound-key>` instruction.

## Failure modes

- **`/spec.product-config` aborts pointing at `lazycortex-experts`** — a chosen role expert (designer / developer / tester / historian) is not registered in `experts` → compose the persona via `lazycortex-experts`, then re-run this skill.
- **`/spec.product-config` refuses because the spec_path is nested** — the derived `spec_path` sits under another product's `spec_path` (products are flat) → choose a sibling path or a namespace folder, then re-run.
- **`/spec.product-config` refuses because the compound-key already exists** — the derived `<subsystem>[-<namespace>]-<leaf>` is already a `products` key → edit that product instead, or pick a different leaf / namespace.
- **`/lazy-review.audit` reports FAIL after Step 10** — a generated class references an unregistered expert or violates the section-writer schema → fix the expert assignments (re-run Step 7 with registered experts) and re-audit.
