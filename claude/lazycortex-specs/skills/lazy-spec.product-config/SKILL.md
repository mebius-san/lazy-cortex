---
name: lazy-spec.product-config
description: Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the product root with its operator-zone folder-note and iconize icon (group folders appear lazily with their first asset), generates or reuses the shared vault-wide behavior-keyed review classes (one per doc-kind, right-anchored wildcard globs spanning every product and asset type; a product with divergent experts gets a per-product override), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_types.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Task, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# Configure Product

Unified wizard that owns the product-registration lifecycle. One entry point for **creating a new product** (with source code, or design-only) and for **editing an existing product** (add `source` to a design-only product, extend `dependencies`, switch `language` / `icon`). The product record lives in `lazy.settings.json[products][<compound-key>]`, read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`. On save the skill scaffolds the product root, writes its operator-zone folder-note carrying the iconize icon (group folders and their notes appear lazily — the first `create-asset` landing an asset seeds them), and generates or reuses the shared review classes so the product's design / tech / feature / change / bug docs flow through the review loop.

Repo records are NOT part of this product record — they live in the cross-plugin `lazy.settings.json[repos]` section (read/written via `lazycortex-core settings-get repos` / `lazycortex-core settings-set repos`) and are resolved by `lazy-spec.resolve-repo`. The inline repo wizard in Step 4 writes a `repos[<repo-key>]` record when the operator attaches a new source repo. The product `language` overrides the repo-global `spec.language` (the `language` key in the `spec` settings section) for narrative prose this product emits.

## Execution discipline (MANDATORY — read before any action)

This skill has 13 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Mode detection + resolve registry`
   - `Step 2 — Product key + spec_path`
   - `Step 3 — Language`
   - `Step 4 — Source (repo + paths, or design-only)`
   - `Step 5 — Dependencies (autodetect + confirm)`
   - `Step 6 — Product icon`
   - `Step 7 — Guidelines (optional per-role context)`
   - `Step 8 — Built-in review experts (designer / system-designer / architect / planner / developer / tester / data-writer)`
   - `Step 9 — Asset types (delegate)`
   - `Step 10 — Workflow mode (full vs spec-only)`
   - `Step 11 — Write product record + scaffold folders + folder-notes`
   - `Step 12 — Built-in review classes + routine sync + audit`
   - `Step 13 — Verify + log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, `design-only`, `taken-from-arg`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer. Never ask a bare one-line question. Never present options as plain-text prose.

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

The first prints the `products` object — each key is a compound-key, each value a record (`spec_path`, optional `language`, `icon`, `source`, `dependencies`, `asset_types`, `tool_types`). The second prints the `repos` object — each key is a repo key, each value a record (`local_path`, `branch`, optional `forge`); this is the repo registry the source step offers. Ignore the `_version` key in each section.

Resolve the user's input to a mode:

- If the input resolves to an existing product key (or a path under an existing product's `spec_path`) via the "Resolving a Product" protocol in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` → **edit mode** (jump to Step 2's edit branch, then Step 11 writes the merged record).
- Otherwise → **create mode**.

When intent is ambiguous (e.g. the user just says "configure product"), `AskUserQuestion` whether they want to create a new product or edit an existing one, then proceed.

The products object + `repos` section drive: uniqueness of the new product key, flat-product validation (`spec_path` not nested under another product's `spec_path` per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`), and registered-repo options.

Outcome: `create` or `edit`.

## Step 2 — Product key + spec_path

**Create mode.** Two questions:

1. **Product key** — `AskUserQuestion` for the product's settings key: an arbitrary stable string the operator chooses (lowercase-with-hyphens recommended, e.g. `chapter`). Stem: the key names the record under `products[<key>]` and is the product's stable identity across config and every skill invocation; it is NOT derived from the product's path and never changes when the folder moves. Why-it-matters: every `spec.*` skill addresses the product by this key, so pick a name that stays meaningful as the vault grows. Validate uniqueness among existing `products` keys. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.
2. **Spec path** — `AskUserQuestion` for `spec_path`: the content-root-relative path of the product's folder, any shape the operator likes (a top-level folder, or nested under any organizational folders — the plugin dictates no form and reads no meaning from path segments). Offer existing folders under the content-root as suggestions plus an "other — type a path" free-text path. Validate: not nested inside another product's `spec_path`; the final path segment is not one of the reserved names `design` / `tech` / `decisions` (folder-note collision per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`); the folder does not already exist on disk unless the user is registering a spec on top of a pre-created folder. Stem: `spec_path` is where this product's specs live, content-root-relative; it is written into `products[<key>].spec_path` and is the root every review-class glob hangs off. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

**Edit mode.** Present the current record (its JSON block as the `AskUserQuestion` preview) and confirm this is the correct product. The key and `spec_path` are FIXED in edit mode — this skill does not rename or move products. Capture the existing record fields (`spec_path`, `language`, `icon`, `source`, `dependencies`, `asset_types`, `tool_types`, `guidelines`, `mode`) to merge into; never drop a field the user does not touch.

Outcome: `collected` (create) or `confirmed` (edit).

## Step 3 — Language

`AskUserQuestion` for the product language (optional override of the repo-global `spec.language`). Stem: `language` is the ISO 639-1 code skills use when writing this product's narrative prose; written into `products[<key>].language` it overrides the `language` key in the `spec` settings section for this product only. Why-it-matters: this drives localization of generated folder-note bodies and design/tech prose — fixed headers and frontmatter keys stay English regardless. Offer `inherit default (no override)` (omit the field; the product follows `spec.language`), `en`, plus an "other — type an ISO 639-1 code" path. In edit mode, default the menu to the product's current value. Capture `<language>` only when the user picks a concrete override; treat `inherit default` as absent. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

Outcome: `set` or `inherit-default`.

## Step 4 — Source (repo + paths, or design-only)

A product is **design-only** when it carries no `source` block (specs authored ahead of code). Otherwise `source` is `{ repo: <repo-key>, paths: [<path>, …] }`.

1. `AskUserQuestion` whether this product has source code. Stem: `source` maps the product to a repo checkout and the subdirectories within it the product covers; written into `products[<key>].source` it is what dependency autodetect and `lazy-spec.source-url` read. Why-it-matters: a design-only product (no `source`) skips code-grounded autodetect and source links until source is added later in edit mode. Options: `has source code` and `design-only (no source)`. In edit mode this is where a design-only product gains a `source` block. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

   - **design-only** → record no `source`; skip the rest of this step (outcome `design-only`) and skip Step 5's autodetect.

2. **Repo** — `AskUserQuestion`. Options: each registered repo key (from the `repos` section read in Step 1) + an "other — register a new repo" path. If the user picks the latter, run the **inline repo wizard** (below) before continuing. Stem: `source.repo` is the key of the `lazy.settings.json[repos]` record whose checkout holds this product's code. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`.

3. **Paths** — `AskUserQuestion`. Offer `single subpath` (one string via "other"), `multiple subpaths` (comma-separated via "other"). Stem: `source.paths` is the list of subdirectories within the repo checkout this product covers; it bounds dependency autodetect and source-url resolution. For each path, validate it exists under the resolved repo's `local_path`; if any does not exist, warn and `AskUserQuestion` whether to proceed (keep the path as a forward declaration) or correct it. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

Outcome: `sourced` or `design-only`.

### Inline repo wizard

Triggered from Step 4 when `source.repo` names an unregistered repo:

1. `AskUserQuestion` for the repo key (lowercase-with-hyphens, e.g. `backend`, `shared`). Validate uniqueness among the keys in the `repos` section read in Step 1.
2. `AskUserQuestion` for `local_path`. Stem: `local_path` is where `lazy-spec.resolve-repo` reads this repo's source and git remote. Why-it-matters: an absolute path pins the repo to one machine's checkout; `"."` (same-repo) stays checkout-agnostic. Options: `this repo (.)` — the code lives in the very repo that holds `lazy.settings.json`; write the literal `"."` and every checkout (dev, or a runtime checkout under `~/lazy-runtime/<repo>`) resolves it to its own root via `git rev-parse --show-toplevel`, so no absolute path leaks into the tracked settings; and `absolute path` — a fixed checkout elsewhere on this machine (the cross-repo case, e.g. a separate spec-vault and code repo), typed via "other". Validate existence: for `"."` run `git rev-parse --show-toplevel` (cwd must be a git repo); for an absolute path, the directory exists and is a git repo. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.
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

   In the parsed object, set `repos[<repo-key>]` to `{ "local_path": <local_path>, "branch": <branch> }`; add `"forge": <key>` ONLY when the host is not in the known-forges table (per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`) — otherwise omit it so `lazy-spec.resolve-repo` auto-detects. The remote URL and forge type are NOT written — they are derived at runtime by `lazy-spec.resolve-repo`. Then write the whole object back:

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

- **internal-product** — imported path falls under another registered product's `source.paths`. Suggest a dep entry resolved via `lazy-spec.resolve-dependency` (see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`).
- **repo** — imported path crosses into a different registered repo's `local_path` but not into a specific product. Suggest a `{repo: <key>}` dep.
- **external** — third-party package from a manifest (`requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`, …). Listed but not added by default.

Iterate candidates **one `AskUserQuestion` call per candidate** with options `add`, `skip` (with "other" for a free-text note). Keep one running list. In edit mode, append accepted entries to the existing `dependencies` list (never clobber prior entries); never emit an empty `dependencies: []`.

Outcome: `confirmed`, `design-only`, or `none`.

## Step 6 — Product icon

`AskUserQuestion` for the product icon. Stem: the icon is the iconize identifier (a Lucide name like `LiBook`, or a literal emoji) written into BOTH `products[<key>].icon` AND the product folder-note's managed `iconize_icon` frontmatter; the Obsidian iconize system paints it on the product folder. Why-it-matters: the icon is how the operator visually distinguishes this product in the file explorer. Every product carries an icon — a note without one reads as an unpainted stray in the file explorer, so declining the question falls back to the default `LiPackage`, never to an icon-less note. Offer a couple of concrete suggestions plus `default (LiPackage)` and an "other — type your own" path. In edit mode, default to the product's current icon. `<icon>` is the operator's value when one is given, otherwise `LiPackage`. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`.

**The colour is not asked.** A product root carries the neutral `#64748b` — the one ordinary container that is coloured at all, so products read apart from the group folders beneath them (which carry no colour key whatsoever). `products[<key>].color` exists as a per-product override an operator may write by hand; the wizard never proposes one, and in edit mode it preserves an existing value like every other untouched field. The full three-tier rule, including the `#f0abfc` accent the intake shelves carry, is `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Container colour.

Outcome: `iconed` or `default-icon`.

## Step 7 — Guidelines (optional per-role context)

`AskUserQuestion` for the optional per-role guideline paths folded into this product's launch-checkbox job dispatch (`spec.coordinator`, per `products[<key>].guidelines` in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`). Stem: `guidelines` is a dict keyed by the dispatched role token (`planner`, `tester`, `developer`, `architect`) plus the wildcard `"*"`, each value a list of repo-relative file paths whose contents are folded into the job's context when an operator ticks a launch checkbox in an asset's `# Gates` section — the code-plan checkbox dispatches under `planner`, `Write test-plan` and `Start testing` both dispatch under `tester`, `Start implementation` dispatches under `developer`, `Write architecture` dispatches under `architect`; `*` paths are folded into every one of those jobs regardless of role. Why-it-matters: a declared path that resolves to a real file hands its contents to the dispatched expert as extra context; a path that does not resolve is never silently dropped — it surfaces as a warning appended to the asset's `# History` section on every dispatch, so a typo stays visible until fixed. Offer `none (no guidelines)` and `add guideline paths` (free text via "other", one role at a time — ask which role first, then the comma-separated paths for that role, repeating until the operator is done). In edit mode, present the product's current `guidelines` dict (if any) as the preview and offer `keep as-is`, `add/change a role's paths`, and `remove a role's paths`, iterating per role via a follow-up `AskUserQuestion`. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

No new delivery mechanism exists or is needed for the project-structure map: when `lazycortex-wiki` is installed, `docs/structure.md` is an ordinary repo-relative path an operator can add under the `architect` role like any other guideline file — this wizard does not special-case it.

For each entered path, validate it exists relative to the repo root; if it does not, warn and `AskUserQuestion` whether to proceed (keep it as a forward declaration, matching Step 4's `source.paths` validation pattern) or correct it.

Outcome: `guidelines-set`, `no-guidelines`, or (edit mode) `unchanged`.

## Step 8 — Built-in review experts (designer / system-designer / architect / planner / developer / tester / data-writer)

The built-in review classes generated in Step 12 are driven by seven roles — `designer`, `system-designer`, `architect`, `planner`, `developer`, `tester`, `data-writer`. These experts are **shared vault-wide**: one common set of review classes serves every product whose role-experts are identical, so a second product normally reuses the first product's experts rather than adding its own classes (see Step 12). Read the available expert names and the current review classes first:

```bash
lazycortex-core settings-get experts
lazycortex-core settings-get review
```

The keys of the first printed object are the registered expert names. In the second, the **shared set** is the classes whose `class` labels are the bare doc-kinds `design`, `system-design`, `system-tech`, `code-plan`, `test-plan`, `bug`, `code-report`, `test-report`, `data-report`, `docs-report` (no `@<key>` suffix). Determine the path:

- **Shared set absent** (no bare-label class of any of those kinds — the usual first-product case) → ask the role questions below; the answers seed the shared set in Step 12. Outcome `assigned`.
- **Shared set present** → `AskUserQuestion` whether this product rides the shared experts or defines a product-specific override. Stem: the vault already carries a shared review-expert set (name the experts read from the shared classes); reusing it adds NO new review classes for this product, while an override generates product-scoped `<kind>@<key>` classes that shadow the shared set for this product only (Step 12 inserts them earlier in the list so first-match-wins routes this product's docs to them). Why-it-matters: overrides exist for a product whose design / code-plan / test-plan / bug docs need a different persona than the rest of the vault — every other product keeps riding the shared set. Options: `use shared experts` and `define product-specific override`. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.
  - **use shared experts** → read the experts from the shared classes (`designer` = the `design` class `experts.main[0].name`, `system-designer` = the `system-design` class main writer, `architect` = the `system-tech` class main writer, `planner` = the `code-plan` class main writer, `developer` = the `code-report` class main writer, `tester` = the `bug` class main writer, `data-writer` = the `data-report` class main writer) and do NOT ask the role questions. Outcome `shared-set`.
  - **define product-specific override** → ask the role questions below; the answers drive this product's override classes in Step 12. Outcome `override`.

Role questions (asked only on the `assigned` and `override` paths — skipped on `shared-set`): for EACH of the seven roles in order (`designer`, then `system-designer`, then `architect`, then `planner`, then `developer`, then `tester`, then `data-writer`), issue a SEPARATE `AskUserQuestion` (one per role) offering the registered expert names as options. Stem for each: name the role and where it lands in the built-in classes (Step 12) — `designer` is the main writer of the asset-level `design` class ONLY and is never a validation writer; `system-designer` is the main writer of the `system-design` class (the product-root and project-root `design.md`) and likewise never validates; `architect` is the main writer of the `system-tech` and `architecture` classes and the standing validator of everything design-shaped (a section validator on `design`, `system-design`, and `code-plan`); `planner` is the main writer of the `code-plan` class and a section validator on `architecture`; `developer` is the main writer of the `code-report` class and a section validator on the `test-plan` and `bug` classes; `tester` is the main writer of `bug`, `test-plan`, and `test-report`, and a section validator on the `code-plan` class; `data-writer` is the main writer of the `data-report` class, defaulting to `<domain>.data-writer` when `lazycortex-experts` seeded one. The `docs-report` class has no default writer — offer only the "other" path for it, pointing the operator at `lazycortex-experts` to compose one, and omit the class when they have none. Why-it-matters: the chosen expert's persona is what actually reviews/writes the product's design / tech / code-plan / test-plan / code-report / test-report / data-report / bug docs in the review loop. Each question MUST offer an "other — define a new persona" path whose per-option copy points the operator at `lazycortex-experts` to compose a new expert, then re-run this skill (do NOT invent an expert name — only names present in `settings-get experts` are valid). See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.


Validate that every chosen role expert (designer / system-designer / architect / planner / developer / tester / data-writer) is a key in `settings-get experts`. If any chosen name is the "other" sentinel, abort with the `lazycortex-experts` pointer and do NOT write — the product is not registered until real expert names exist.

Outcome: `assigned`, `shared-set`, or `override` (or abort `expert-undefined`).

## Step 9 — Asset types (delegate)

`AskUserQuestion` whether to declare any asset types of the product's own (beyond the shipped feature / change / bug / content / research set) now. Stem: an asset type is a declared kind of asset (characters / scenes / chapters / …) written into `products[<key>].asset_types.<name>`, carrying its icon, the one document a fresh asset starts from, its default tools, the folder its assets land in by default, and the playbook the coordinator works them under; its design / code-plan / test-plan docs are covered automatically by the shared behavior-keyed review classes (Step 12's right-anchored wildcard globs), so no per-type class exists. Why-it-matters: declaring a type creates nothing on disk — every group folder, shipped types included, appears only at the first `create-asset` that lands an asset in it, seeded with its group folder-note by the scaffold — so it is a dedicated skill's job, not an inline branch of this wizard; the shipped types need no declaration at all. Options: `declare types now` and `none (shipped types only)`. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

- **declare types now** → after this skill finishes (Step 13 done), the operator runs `/lazy-spec.add-asset-type <compound-key>` once per type. Do NOT inline-duplicate that flow — surface the instruction in the Report (outcome `delegated`). Do NOT call `lazy-spec.add-asset-type` from here; the product must be fully written and audited first.
- **none** → outcome `shipped-only`.

Outcome: `delegated` or `shipped-only`.

## Step 10 — Workflow mode (full vs spec-only)

`AskUserQuestion` for the product's workflow profile. Stem: `mode` controls how far the coordinator's ladder runs for every asset under this product (`lazy-spec.coordination-playbook.md` Chapter 14) — absent or `"full"` runs the ordinary design → architecture → plan → implementation → test ladder; `"spec-only"` stops after `design.md` approves (`spec_design_done`), with `spec_released` flipped by an explicit operator word and no architecture/plan/implementation/test steps ever hanging a checkbox. Why-it-matters: this is a per-product commitment, not a per-asset toggle — every asset under a spec-only product follows the shorter ladder, so pick it for a product whose specs are the whole deliverable (a design-only reference other repos consume, not code this repo will itself implement). Options: `full (default — design through implementation and testing)` and `spec-only (design and review only; released by operator word)`, each with a one-sentence consequence. In edit mode, default the menu to the product's current value (absent reads as `full`). See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`.

Capture `<mode>` only when `spec-only` is chosen; absent/`full` writes no key (matching the "absence = full mode" contract).

Outcome: `spec-only` or `full` (no key written).

## Step 11 — Write product record + scaffold folders + folder-notes

Each settings mutation is an atomic read-modify-write. Read the products section, edit the in-memory object, write it back:

```bash
lazycortex-core settings-get products
```

In the parsed object, set `products[<compound-key>]` to the gathered fields:

- `spec_path` (always).
- `language` — only when Step 3 set a concrete override.
- `icon` — always: the Step 6 value, or the default `LiPackage` when the operator declined.
- `guidelines` — only when Step 7 produced at least one role's paths.
- `source` — `{ repo, paths }` only when Step 4 produced a source block.
- `dependencies` — only when Step 5 accepted at least one entry.
- `mode` — only when Step 10 captured `spec-only`; absent/`full` writes no key.

**Edit mode**: start from the existing record captured in Step 2 and merge — add `source` to a design-only product, extend `dependencies`, switch `language` / `icon` / `guidelines` / `mode` — while preserving `asset_types` / `tool_types` and every untouched field. Never emit empty `dependencies: []` or an empty `source`; likewise, a Step 7 outcome of `no-guidelines` or an `unchanged`/`remove a role's paths` edit that empties every role means an absent `guidelines` key, never an empty `guidelines: {}`. Then write the whole products object back:

```bash
printf '%s' '<edited-products-json>' | lazycortex-core settings-set products
```

Initialize the on-disk structure (create mode, or any missing piece in edit mode). Use two separate calls for each folder-note — `Bash(mkdir -p <dir>)` then the `Write` tool (never chain):

1. **No group folders are pre-created.** `features/`, `changes/`, `bugs/`, and every declared type's folder appear lazily — the first `create-asset` landing an asset in one creates the folder and seeds its group folder-note (`lazy-spec.layout-protocol.md` Part 1). NO `backlog/`, and NO per-product `requests/` — the request inbox is a single vault-root folder, created once in step 3 below (a request may target multiple products, so it is never per-product; see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md`).
2. **Product folder-note** `<spec_path>/<leaf>.md` (`<leaf>` = the final segment of `spec_path`) — an operator-zone folder-note. Frontmatter: `iconize_icon: <icon>` always (Step 6 guarantees a value — the operator's or the default `LiPackage`), plus `iconize_color: "<color>"` — `products[<key>].color` when the record declares one, otherwise the product default `#64748b`. **Always double-quote the hex**: a bare `#rrggbb` opens a YAML comment and the key parses as empty. A product root is the only ordinary container that carries a colour; group folders beneath it carry none (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Container colour). NO `spec_role`. Body: the protected `# Summary` skeleton first, then operator-zone body after the closing stats marker:

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

   After writing the product folder-note, author its `<!-- spec:precis -->` region — one-line description drawn from the product's design intent — inline between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers, replacing the `_TBD` placeholder. Then run `render-container-stats` on it so the `<!-- spec:stats:* -->` region is populated:

   ```bash
   lazycortex-specs render-container-stats <content_root>/<spec_path>/<leaf>.md
   ```

3. **Vault-root request inbox** (shared by every product — created once, idempotent): resolve the spec content-root `<content_root> = <repo>/<spec.vault_root>` (default `specs`; read `spec.vault_root` from `.claude/lazy.settings.json`). Ensure `<content_root>/requests/` exists (`Bash(mkdir -p <content_root>/requests)`). ALWAYS `Write` `<content_root>/requests/requests.md` when absent as the operator-zone inbox folder-note (`iconize_icon: LiInbox`, `iconize_color: "#f0abfc"` — the intake-shelf accent, double-quoted, NO `spec_role`, the `# Summary` skeleton from the group-note template with the static précis `Vault-wide request intake inbox.` filled in, then operator-zone body) and ALWAYS `git add` it so the `requests/` directory is committed and pushed even with zero request files. If it already exists, leave the body untouched (stats are refreshed by the event-driven primitive). When creating the requests inbox, run `render-container-stats` on it too:

   ```bash
   lazycortex-specs render-container-stats <content_root>/requests/requests.md
   ```

Real icon values are fine — the iconize hook only strips unresolvable placeholder icon values, not concrete ones.

Outcome: `written`.

## Step 12 — Built-in review classes + routine sync + audit

Append the built-in review classes to `review.classes`. Read the section, append, write back:

```bash
lazycortex-core settings-get review
```

In the parsed object, write the classes below into `review.classes` (create the list if absent) per the reconcile rule further down. **The review-class schema is owned by `lazycortex-review`** — match it exactly:

- Each class is an object with a `class` string label (human-readable identity; there is NO `id` field — the daemon matches files to classes purely by `paths` globs), a `paths` non-empty list of glob strings, and an `experts` object.
- `experts.main` — a LIST of `{ "name": <expert> }` writer objects (the opening-writer chain).
- `experts.validation` and `experts.terminal` — a DICT keyed by stable `section-id` (`^[a-z][a-z0-9_-]*$`), each value a writer object `{ "name": <expert>, "section": "<H1 title>", "position": "top" | "bottom" }`. These author named post-approve H1 sections; `validation` sections block finalize and trigger revert-to-main on concerns. There is NO flat "list of reviewers" bucket — a reviewer is expressed as one named validation section.

A class's label IS the name of a document type (`spec_doc_type`), and that is the class's only identity. `paths` stay in the schema, but their role has narrowed: they discriminate a product override `<type>@<key>` from the bare-type class, and they catch documents carrying no type at all. A typed document is routed by its frontmatter, never by where it sits or what it is called.

Generate **one class per declared type carrying `review: true`** — the shipped types plus whatever the product declares under `products[<key>].doc_types`. The **shared set** — bare-type labels with right-anchored wildcard globs — serves every product whose role-experts match; a product with divergent experts (Step 8 outcome `override`) gets the same types re-emitted as product-scoped `<type>@<key>` classes inserted BEFORE the shared set. Globs span the product root and every category folder (built-in AND operator-defined) — so `lazy-spec.add-asset-type` never touches `review.classes`, a new category needs no new class, and a new product needs no new class when it rides the shared experts. Reusable validation dicts plus a no-validation case. **`designer` and `system-designer` are never validation writers in any class** — they appear only as `main` writers; the `architect` is the standing validator of everything design-shaped (`design`, `system-design`, `code-plan`); no class is validated by its own main writer; the report classes carry no validation bucket, same as `system-tech`. Each checkbox in the launch ladder (`lazy-spec.lifecycle-protocol.md` Part 3) resolves its dispatched expert from the review class matching its own result document — `planner` writes `code-plan.md`, `developer` writes `code-report.md`, `tester` writes both `test-plan.md` and `test-report.md`, `data-writer` writes `data-report.md` — mirroring `lazy-spec.install` § 6e's seed template:

- **A = architect review** — `{ "architect_review": { "name": "<architect>", "section": "Architect review", "position": "bottom" } }`.
- **TA = tester + architect review** — `{ "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" }, "architect_review": { "name": "<architect>", "section": "Architect review", "position": "bottom" } }`.
- **DV = developer review** — `{ "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" } }`.
- **P = planner review** — `{ "planner_review": { "name": "<planner>", "section": "Planner review", "position": "bottom" } }`.
- **NONE** — omit the `experts.validation` key entirely (no validation writers this iteration).

**Enumerate the types first.** The set of classes is derived, not written down here:

```
Bash(lazycortex-specs doc-type list --product <key>)
Bash(lazycortex-specs doc-type resolve <type> --product <key>)
```

Take every name `doc-type list` returns, keep those whose declaration carries `review: true`, and emit one class per surviving type with `class` = the type's own name. A type declared `review: false` (the shipped `decisions`, and any project type declaring the same) gets no class and never enters the review loop.

**Expert bindings** (bare-type labels; substituting `<designer>`, `<system-designer>`, `<architect>`, `<planner>`, `<developer>`, `<tester>`, `<data-writer>`, `<docs-writer>`) — the defaults for the shipped types. For a project-declared type the experts are not derivable: ask the operator with `AskUserQuestion`, exactly one question per such type, naming the type and offering the same A / TA / DV / P / NONE validation shapes. `design` and `bug` additionally carry `context_from_frontmatter: [spec_source_requests]` — at main-job dispatch the dispatcher resolves that frontmatter key's wikilink/path values on the document under review to repo files and folds them into the job's `context/`, so the design/bug writer's job bundle includes the request(s) that spawned the doc (`lazy-spec.request-apply`'s `ensure_source_request` writer stamps `spec_source_requests`):

| `class` label | `paths` | `experts.main` | `experts.validation` | extra |
|---|---|---|---|---|
| `design` | `["*/*/design.md"]` | `[{ "name": "<designer>" }]` | A | `context_from_frontmatter: [spec_source_requests]` |
| `system-design` | `["*/design.md", "design.md"]` | `[{ "name": "<system-designer>" }]` | A | `context_from_frontmatter: [spec_source_requests]` |
| `system-tech` | `["*/tech.md", "tech.md"]` | `[{ "name": "<architect>" }]` | NONE | — |
| `architecture` | `["*/architecture.md"]` | `[{ "name": "<architect>" }]` | P | — |
| `code-plan` | `["*/code-plan.md"]` | `[{ "name": "<planner>" }]` | TA | — |
| `test-plan` | `["*/test-plan.md"]` | `[{ "name": "<tester>" }]` | DV | — |
| `bug` | `["bugs/*/bug.md"]` | `[{ "name": "<tester>" }]` | DV | `context_from_frontmatter: [spec_source_requests]` |
| `code-report` | `["*/code-report.md"]` | `[{ "name": "<developer>" }]` | NONE | — |
| `test-report` | `["*/test-report.md"]` | `[{ "name": "<tester>" }]` | NONE | — |
| `data-report` | `["*/data-report.md"]` | `[{ "name": "<data-writer>" }]` | NONE | — |
| `docs-report` | `["*/docs-report.md"]` | `[{ "name": "<docs-writer>" }]` | NONE | — |

The `system-design` / `system-tech` classes serve the **level docs** — the product-root `design.md` / `tech.md` pair AND the same pair at the spec content-root (the project-wide spec; no config key declares it — the files' existence is the declaration). One expert set serves both scales. A typed document routes by its `spec_doc_type`, so the overlapping design globs are untyped-fallback tie-breakers only: the asset `design` class sits earlier in the list and wins the fallback.

**Override set** (product-scoped labels; generated ONLY on Step 8 outcome `override`, with this product's `<spec_path>` and override experts) — shadows the shared set for one product:

| `class` label | `paths` | `experts.main` | `experts.validation` |
|---|---|---|---|
| `design@<key>` | `["<spec_path>/*/*/design.md"]` | `[{ "name": "<designer>" }]` | A |
| `system-design@<key>` | `["<spec_path>/design.md"]` | `[{ "name": "<system-designer>" }]` | A |
| `system-tech@<key>` | `["<spec_path>/tech.md"]` | `[{ "name": "<architect>" }]` | NONE |
| `architecture@<key>` | `["<spec_path>/*/*/architecture.md"]` | `[{ "name": "<architect>" }]` | P |
| `code-plan@<key>` | `["<spec_path>/*/*/code-plan.md"]` | `[{ "name": "<planner>" }]` | TA |
| `test-plan@<key>` | `["<spec_path>/*/*/test-plan.md"]` | `[{ "name": "<tester>" }]` | DV |
| `bug@<key>` | `["<spec_path>/bugs/*/bug.md"]` | `[{ "name": "<tester>" }]` | DV |
| `code-report@<key>` | `["<spec_path>/*/*/code-report.md"]` | `[{ "name": "<developer>" }]` | NONE |
| `test-report@<key>` | `["<spec_path>/*/*/test-report.md"]` | `[{ "name": "<tester>" }]` | NONE |
| `data-report@<key>` | `["<spec_path>/*/*/data-report.md"]` | `[{ "name": "<data-writer>" }]` | NONE |
| `docs-report@<key>` | `["<spec_path>/*/*/docs-report.md"]` | `[{ "name": "<docs-writer>" }]` | NONE |

The content-root (project-wide) `design.md` / `tech.md` pair is never product-scoped — it belongs to no product, so only the shared `system-design` / `system-tech` classes ever cover it.

The `class` label is the schema's only identity slot (a `class` field, not `id`): the shared set uses the bare type name, the override set the `<type>@<key>` value. **Two types never share one class** — that is the price of the identity, and it is deliberate: a class is addressable by its type, so a label serving two types would make the type non-addressable.

**Matching semantics.** For a document carrying `spec_doc_type`, resolution is type-first: among the classes whose label's part before `@` equals the document's type, a product-scoped one whose `paths` cover the file wins, otherwise the bare-type class does. Neither the filename nor the directory participates — a document named `races.md` typed `design` lands in the `design` class.

`paths` still matter in two places. They discriminate which product an `@<key>` override applies to, and they are the whole matcher for a document carrying no `spec_doc_type` (a free-form intake file, a consumer's own document class), which falls back to first-match-wins over `paths` in list order. On that fallback path the globs use `PurePath.match` right-anchored, where `*` never crosses `/` and `**` acts as a SINGLE path segment — never write `**` into class paths expecting recursion. (The daemon's md-scan sieve additionally supports recursive `**`, but that concerns only the coarse discovery masks below, never class paths.) Right-anchoring is why the shared globs need no `<spec_path>` prefix: `*/design.md` matches BOTH the product-root `<spec_path>/design.md` (its last two segments) and every asset `<category>/<slug>/design.md`; `bugs/*/bug.md` matches `<spec_path>/bugs/<slug>/bug.md`. The per-product md-scan sieve mask (below) bounds discovery to each product's own subtree. A product's override globs deliberately OVERLAP the shared globs, so override classes MUST still sit earlier in `review.classes` than the shared set.

**Reconcile, not append.** Read `review.classes` and act per Step 8's outcome:

1. **`assigned` (shared set absent)** — append the **shared** classes with the Step-8 experts. Then run the *per-product collapse* below to drop any stale `<kind>@<key>` classes this product carries from the old per-product scheme.
2. **`shared-set` (present, reuse)** — leave the shared set untouched; run the *per-product collapse* to drop this product's stale `<kind>@<key>` classes (this is the migration — the product stops carrying its own classes and rides the shared set).
3. **`override` (present, product-specific)** — first compute this product's override experts; if they are identical to the shared set's experts for every role, there is no divergence, so fall through to the `shared-set` behavior (no override classes written). Otherwise remove any prior `<kind>@<key>` classes for THIS product, then insert the **override** classes (product-scoped globs, override experts) immediately BEFORE the first shared-set class.

**Per-product collapse.** Remove from `review.classes` every class whose `class` label ends in `@<key>` for THIS `<key>` and whose prefix either matches a type declared in this product's scope (`doc-type list --product <key>`) or is one of the legacy labels the open set no longer covers — the removed `plan`, and any dotted per-category label (`spec.design`, `spec.tech`, `bugs.bug`, `bugs.plan`, `<category>.design`, `<category>.plan`). Before removing one, compare its `experts` block to the shared-set class of the same type: if they **differ**, `AskUserQuestion` first — keep the operator's variant as a product override (re-insert it before the shared set, as in outcome 3) vs collapse it into the shared set. Bare doc-kind labels (the shared set) and `@<key>` labels naming a DIFFERENT product are never touched. This makes Step 12 idempotent across create and edit mode — re-running `/lazy-spec.product-config` in edit mode on a product generated under the old per-product scheme IS the migration to the shared set (a per-product scheme's classes collapse onto the shared set).

**Expert re-verification (MANDATORY, before the write).** Collect every expert name the classes are about to carry — each `main[].name`, each `validation.<section-id>.name`, each `history.name` — and re-check every one against the keys of `lazycortex-core settings-get experts`. Any name missing → abort WITHOUT calling `settings-set review`, naming the dangling expert and pointing at `lazycortex-experts` (same abort as Step 8's `expert-undefined`). Step 8's earlier validation does not guard this write — a dangling reference (e.g. an unregistered tester) must be impossible to persist.

Write the edited review object back:

```bash
printf '%s' '<edited-review-json>' | lazycortex-core settings-set review
```

Then normalize the `lazy-review.scan` routine — but only when `routines["lazy-review.scan"]` is present (skip silently when absent: daemon-disabled project). (1) Resolve `<content_root>` = the `spec.vault_root` setting (default `specs`); ensure the mask `<content_root>/<spec_path>/**/*.md` is in the routine's `paths` — one coarse scope-root mask per product, nothing filename-specific. When `spec.vault_root` is `.`, the prefix is omitted and the mask is `<spec_path>/**/*.md`. **Warning:** `**`-bearing sieve masks are matched anchored at the repo root (unlike class `paths`, which the dispatcher matches right-anchored), so the mask MUST carry the content-root prefix — a mask missing it matches nothing under the default `specs/` layout. (2) Remove every legacy mask this union scheme wrote for this product, in BOTH shapes — with or without the content-root prefix — that falls under this product's subtree and ends in a concrete doc filename or is otherwise subsumed by the new mask. (3) Inside `filter.frontmatter` set `review_active` to `{"in": [true], "not_in": []}` (drop the legacy `null` leg). `review_active` stays the routine's ONLY frontmatter condition — do NOT add `spec_doc_type` to the filter: this routine selects "everything currently in review", not documents of one kind, and the kind is the class's business at dispatch time. The `paths` list likewise carries no filename-shaped mask; one coarse scope-root mask per product is the whole discovery surface. (4) Set `interval_sec` to `60` when it still carries the legacy `5` (minute cadence for coarse scans; an operator-chosen value other than 5 stays untouched). Discovery is deliberately coarse: class `paths` do the precise routing at dispatch time, and the frontmatter filter admits only opted-in files, so a new category, doc-kind, or nesting depth inside the product never touches the sieve — only a new product adds its one mask. Idempotent — re-running on an already-normalized routine changes nothing.

Then, symmetrically, normalize the `lazy-spec.coordinator-watch` routine — but only when `routines["lazy-spec.coordinator-watch"]` is present (skip silently when absent: daemon-disabled project). Union this product's glob `<content_root>/<spec_path>/*/*` into the routine's `group_globs` list (create the key if absent) — `group_globs` collapses per-asset file items into one worker dispatch per asset directory (`lazy-core.runtime-schema.md` § git `group_globs`); the mask reuses `<content_root>`/`<spec_path>` from the `lazy-review.scan` normalization above but stops one level short, at category/asset depth rather than a recursive `**/*.md` scan. When `spec.vault_root` is `.`, the prefix is omitted and the glob is `<spec_path>/*/*`. Idempotent — a glob already present for this product is left untouched, and no other product's entry is ever removed.

Finally, verify the generated classes by invoking `/lazy-review.audit` via the `Skill` tool (`skill: "lazycortex-review:lazy-review.audit"`) and surface its findings — report the `audit: <LEVEL> (<N> findings)` line and any FAIL/WARN detail. If the audit reports FAIL, report it; do not silently leave broken classes.

Outcome: `wired` (carry the audit level into the report).

## Step 13 — Verify + log the run

Invoke `/lazy-spec.doctor <compound-key>` via the `Skill` tool (`skill: "lazycortex-specs:lazy-spec.doctor"`) to confirm the product record, folder tree, and folder-notes are consistent. Surface its findings.

Then, per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.product-config/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.product-config)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC, `date -u +'%Y-%m-%d %H:%M:%S UTC'`), `input` (the arguments passed, or `none`). Body: `# lazy-spec.product-config` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `verified` + `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with the `lazy-spec.doctor` summary line from Step 13 and the `audit:` line from Step 12. If Step 9 was `delegated`, include the `/lazy-spec.add-asset-type <compound-key>` instruction.

## Failure modes

- **`/lazy-spec.product-config` aborts pointing at `lazycortex-experts`** — a chosen role expert (designer / system-designer / architect / planner / developer / tester / data-writer) is not registered in `experts` → compose the persona via `lazycortex-experts`, then re-run this skill.
- **`/lazy-spec.product-config` refuses because the spec_path is nested** — the chosen `spec_path` sits under another product's `spec_path` (products are flat) → choose a path outside every registered product's subtree, then re-run.
- **`/lazy-spec.product-config` refuses because the product key already exists** — the chosen key is already a `products` key → edit that product instead, or pick a different key.
- **`/lazy-review.audit` reports FAIL after Step 12** — a generated class references an unregistered expert or violates the section-writer schema → fix the expert assignments (re-run Step 8 with registered experts) and re-audit.
- **`/lazy-spec.product-config` skips a declared type, leaving it with no class** — a type declared `review: true` whose experts the operator never answered for gets no class, and every document of that type then stays outside the review loop indefinitely → re-run the skill and answer the `AskUserQuestion` naming that type, or declare the type `review: false` if it genuinely should not be reviewed.
