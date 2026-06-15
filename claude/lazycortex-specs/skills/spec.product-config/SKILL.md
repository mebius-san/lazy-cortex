---
name: spec.product-config
description: Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the on-disk folder tree + operator-zone folder-notes with iconize icons, generates the built-in design/tech/feature/change/bug review classes, and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_categories.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Task, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Configure Product

Unified wizard that owns the product-registration lifecycle. One entry point for **creating a new product** (with source code, or design-only) and for **editing an existing product** (add `source` to a design-only product, extend `dependencies`, switch `language` / `icon`). The product record lives in `lazy.settings.json[products][<compound-key>]`, read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`. On save the skill scaffolds the on-disk folder tree, writes operator-zone folder-notes carrying iconize icons, and generates the built-in review classes so the product's design / tech / feature / change / bug docs flow through the review loop.

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
2. `AskUserQuestion` for `local_path` (an absolute path to the checkout). Validate the directory exists and is a git repo.
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

The built-in review classes generated in Step 10 are driven by three roles — `designer`, `developer`, `tester` — plus a historian. Read the available expert names first:

```bash
lazycortex-core settings-get experts
```

The keys of the printed object are the registered expert names. Then, for EACH of the three roles in order (`designer`, then `developer`, then `tester`), issue a SEPARATE `AskUserQuestion` (one per role) offering those expert names as options. Stem for each: name the role and where it lands in the built-in classes (Step 10) — `designer` is the main writer of the design classes (`spec.design`, `features.design`, `changes.design`) ONLY and is never a validation writer; `developer` is the main writer of the plan/tech classes (`spec.tech`, `features.plan`, `changes.plan`, `bugs.plan`) and a section validator on the design and bug classes; `tester` is the main writer of `bugs.bug` and the sole section validator on the plan classes (plus a section validator on the design classes). Why-it-matters: the chosen expert's persona is what actually reviews/writes the product's design / tech / plan / bug docs in the review loop. Each question MUST offer an "other — define a new persona" path whose per-option copy points the operator at `lazycortex-experts` to compose a new expert, then re-run this skill (do NOT invent an expert name — only names present in `settings-get experts` are valid). See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

Then `AskUserQuestion` for the historian — single-select from the expert names, default `review.historian`. Stem: the historian writes the `# History` section of every reviewed doc across all built-in classes. Why-it-matters: it is the `experts.history` writer; it must be an expert registered with commit permission in the local repo.

Validate that every chosen role expert (designer / developer / tester / historian) is a key in `settings-get experts`. If any chosen name is the "other" sentinel, abort with the `lazycortex-experts` pointer and do NOT write — the product is not registered until real expert names exist.

Outcome: `assigned` (or abort `expert-undefined`).

## Step 8 — Asset categories (delegate)

`AskUserQuestion` whether to register any operator-defined asset categories (beyond the built-in feature / change / bug set) now. Stem: an asset category is an operator-defined kind (characters / scenes / chapters / …) registered under `products[<key>].asset_categories`; each gets its own folder, folder-note, and design + plan review classes. Why-it-matters: the built-in feature / change / bug categories are always created in Step 9 — extra categories are added by a dedicated skill, not inline here. Options: `add categories now` and `none (built-in only)`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

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
2. **Product folder-note** `<spec_path>/<leaf>.md` — an operator-zone folder-note. Frontmatter: `iconize_icon: <icon>` ONLY when Step 6 captured an icon. NO `spec_role`. Body: a single `# <leaf>` H1 followed by a one-line HTML comment marking the body operator-owned (e.g. `<!-- Operator-owned: author this product's overview prose here. -->`). Author no further prose.
3. **Built-in category folder-notes** — one operator-zone folder-note per built-in category, each carrying `iconize_icon` and NO `spec_role`, NO `*-index` role, NO dataviewjs (operator owns the body):
   - `features/features.md` — default icon `LiRocket`.
   - `changes/changes.md` — default icon `LiRefreshCcw`.
   - `bugs/bugs.md` — default icon `LiBug`.

   A default icon is overridable: if the gathered record carries `asset_categories[<name>].icon` for the built-in name (`feature` / `change` / `bug`), use that value instead. Each folder-note body is a single `# <name>` H1 plus the operator-owned HTML comment.
4. **Vault-root request inbox** (shared by every product — created once, idempotent): ensure the vault-root `requests/` directory exists (`mkdir -p requests` at the repo root, where `.claude/lazy.settings.json` lives — NOT under `spec_path`). When `requests/requests.md` is absent, `Write` it as an operator-zone inbox folder-note: `iconize_icon: LiInbox`, NO `spec_role`, body a single `# requests` H1 plus the operator-owned HTML comment. If it already exists (an earlier product registration created it), leave it untouched. All request files for the whole vault live in this one inbox.

Real icon values are fine — the iconize hook only strips unresolvable placeholder icon values, not concrete ones.

Outcome: `written`.

## Step 10 — Built-in review classes + routine sync + audit

Append the built-in review classes to `review.classes`. Read the section, append, write back:

```bash
lazycortex-core settings-get review
```

In the parsed object, append the classes below to `review.classes` (create the list if absent), preserving every existing class. **The review-class schema is owned by `lazycortex-review`** — match it exactly (this is the same schema `spec.add-asset-category` writes):

- Each class is an object with a `class` string label (human-readable identity; there is NO `id` field — the daemon matches files to classes purely by `paths` globs), a `paths` non-empty list of glob strings, and an `experts` object.
- `experts.main` — a LIST of `{ "name": <expert> }` writer objects (the opening-writer chain).
- `experts.validation` and `experts.terminal` — a DICT keyed by stable `section-id` (`^[a-z][a-z0-9_-]*$`), each value a writer object `{ "name": <expert>, "section": "<H1 title>", "position": "top" | "bottom" }`. These author named post-approve H1 sections; `validation` sections block finalize and trigger revert-to-main on concerns. There is NO flat "list of reviewers" bucket — a reviewer is expressed as one named validation section.
- `experts.history` — a single `{ "name": <historian> }` object (no `repo`, no `@<repo>` syntax).

Generate the classes below (substituting `<spec_path>`, `<key>` = compound-key, `<designer>`, `<developer>`, `<tester>`, `<historian>`). Three reusable validation dicts plus a no-validation case. **`designer` is never a validation writer in any class** — it appears only as a `main` writer; plan validation is tester-only; `docs/tech` carries no validation bucket at all:

- **D = developer + tester review** — `{ "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" }, "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }`.
- **T = tester review** — `{ "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }`.
- **DV = developer review** — `{ "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" } }`.
- **NONE** — omit the `experts.validation` key entirely (no validation writers this iteration).

Every class also carries `experts.history: { "name": "<historian>" }`.

| `class` label | `paths` | `experts.main` | `experts.validation` |
|---|---|---|---|
| `spec.design@<key>` | `["<spec_path>/docs/design.md"]` | `[{ "name": "<designer>" }]` | D |
| `spec.tech@<key>` | `["<spec_path>/docs/tech.md"]` | `[{ "name": "<developer>" }]` | NONE |
| `features.design@<key>` | `["<spec_path>/features/**/design.md"]` | `[{ "name": "<designer>" }]` | D |
| `features.plan@<key>` | `["<spec_path>/features/**/plan.md"]` | `[{ "name": "<developer>" }]` | T |
| `changes.design@<key>` | `["<spec_path>/changes/**/design.md"]` | `[{ "name": "<designer>" }]` | D |
| `changes.plan@<key>` | `["<spec_path>/changes/**/plan.md"]` | `[{ "name": "<developer>" }]` | T |
| `bugs.bug@<key>` | `["<spec_path>/bugs/**/bug.md"]` | `[{ "name": "<tester>" }]` | DV |
| `bugs.plan@<key>` | `["<spec_path>/bugs/**/plan.md"]` | `[{ "name": "<developer>" }]` | T |

The `class` label carries the `<scope>.<doc>@<key>` value because the schema has a `class` field (not `id`) — its only identity slot. Write the edited review object back:

```bash
printf '%s' '<edited-review-json>' | lazycortex-core settings-set review
```

Then sync the `lazy-review.scan` routine's `paths:` list to include every new glob so the daemon's md-scan routine sees the product's docs (the routine's `paths:` must be the union of every `review.classes[].paths` glob — read the routine config, add any absent globs, write back) — exactly as `spec.add-asset-category` does. Finally, verify the generated classes by invoking `/lazy-review.audit` via the `Skill` tool (`skill: "lazycortex-review:lazy-review.audit"`) and surface its findings — report the `audit: <LEVEL> (<N> findings)` line and any FAIL/WARN detail. If the audit reports FAIL, report it; do not silently leave broken classes.

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
