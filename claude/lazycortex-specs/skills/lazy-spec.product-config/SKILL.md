---
name: lazy-spec.product-config
description: Use when creating a new product in the spec system OR editing an existing product's registration — unified wizard that collects answers via AskUserQuestion, writes the product record into lazy.settings.json[products][<compound-key>], scaffolds the product root with its operator-zone folder-note and iconize icon (group folders appear lazily with their first asset), generates or reuses the shared vault-wide behavior-keyed review classes (one per doc-kind, right-anchored wildcard globs spanning every product and asset type; a product with divergent experts gets a per-product override), and auto-detects code dependencies. Edit mode adds source to a design-only product, extends dependencies, or switches language/icon without clobbering asset_types.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, Agent
---
# Configure Product

Unified wizard that owns the product-registration lifecycle. One entry point for **creating a new product** (with source code, or design-only) and for **editing an existing product** (add `source` to a design-only product, extend `dependencies`, switch `language` / `icon`). The product record lives in `lazy.settings.json[products][<compound-key>]`, read and written atomically via `lazycortex-core settings-get products` / `lazycortex-core settings-set products`. On save the skill scaffolds the product root, writes its operator-zone folder-note carrying the iconize icon (group folders and their notes appear lazily — the first `create-asset` landing an asset seeds them), and generates or reuses the shared review classes so the product's design / tech / feature / change / bug docs flow through the review loop.

Repo records are NOT part of this product record — they live in the cross-plugin `lazy.settings.json[repos]` section (read/written via `lazycortex-core settings-get repos` / `lazycortex-core settings-set repos`) and are resolved by `lazy-spec.resolve-repo`. The inline repo wizard in Step 4 writes a `repos[<repo-key>]` record when the operator attaches a new source repo. The product `language` overrides the repo-global `spec.language` (the `language` key in the `spec` settings section) for narrative prose this product emits.

## Execution discipline (MANDATORY — read before any action)

This skill has 13 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Mode detection + resolve registry`
   - `Step 2 — Product key + spec_path`
   - `Step 3 — Language`
   - `Step 4 — Source (repo + paths, or design-only)`
   - `Step 5 — Dependencies (autodetect + confirm)`
   - `Step 6 — Product icon`
   - `Step 7 — Guidelines (optional per-role context)`
   - `Step 8 — Built-in review experts (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer)`
   - `Step 9 — Asset types (delegate)`
   - `Step 10 — Workflow mode (full vs spec-only)`
   - `Step 11 — Write product record + scaffold folders + folder-notes`
   - `Step 12 — Built-in review classes + routine sync + audit`
   - `Step 13 — Verify + log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, `design-only`, `taken-from-arg`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer — and preceded by the context block each site below spells out (`Where` / `Found` / `Why asking` / `Answers`, per `lazy-core.skill-writing` § 11), printed to the operator as prose immediately before the call. Once the wizard's opening has named the skill and mode, the `Where` line may stay short; `Found`, `Why asking`, and `Answers` are per question, filled from the run at hand. Never ask a bare one-line question. Never present options as plain-text prose.

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

The products object + `repos` section drive: uniqueness of the new product key, flat-product validation (`spec_path` not nested under another product's `spec_path` per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`), and registered-repo options.

Outcome: `create`, `edit`, or `aborted:no-vault-spec`.

## Step 2 — Product key + spec_path

**Create mode.** Two questions:

1. **Product key** — the product's settings key: an arbitrary stable string the operator chooses (lowercase-with-hyphens recommended, e.g. `chapter`). Validate uniqueness among existing `products` keys.

   ```
   Context (print before asking):
   - Where: Step 2 — Product key; target `products[<key>]` in <settings-dir>/lazy.settings.json
   - Found: registered keys: <keys, or "none">
   - Why asking: the key is the product's stable identity across config and every skill invocation — NOT derived from its path, never changed when the folder moves; nothing derives it
   - Answers: any typed key (via "other") — written as `products[<key>]` in Step 11 and addressed by every `spec.*` skill from then on; fixed thereafter (edit mode never renames); a key already registered is refused and re-asked
   AskUserQuestion: header "Product key", question "Settings key for the new product in <repo> (lowercase-with-hyphens, e.g. `chapter`; taken: <keys>)? It names `products[<key>]`, so pick a name that stays meaningful as the vault grows. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", free text via "other".
   ```

2. **Spec path** — `spec_path`: the content-root-relative path of the product's folder, any shape the operator likes (a top-level folder, or nested under any organizational folders — the plugin dictates no form and reads no meaning from path segments). Validate: not nested inside another product's `spec_path`; the final path segment is not one of the reserved names `design` / `tech` / `decisions` (folder-note collision per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md`); the folder does not already exist on disk unless the user is registering a spec on top of a pre-created folder.

   ```
   Context (print before asking):
   - Where: Step 2 — Spec path; target `products[<key>].spec_path`, content-root <content-root>
   - Found: existing folders under <content-root>: <list, or "none">; registered spec_paths: <paths, or "none">
   - Why asking: where this product's specs live is layout the plugin reads no meaning from — only the operator knows it
   - Answers: `<existing folder>` — register on top of that pre-created folder; `other — type a path` — a new content-root-relative path, scaffolded by Step 11; either is written as `products[<key>].spec_path`, the root every review-class glob hangs off, fixed thereafter (edit mode never moves it); a path nested under another product's `spec_path`, ending in `design` / `tech` / `decisions`, or already on disk without intent to register over it is refused and re-asked
   AskUserQuestion: header "Spec path", question "Content-root-relative folder for product `<key>` under <content-root>? Any shape — top-level, or nested under organizational folders. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options: each existing folder + `other — type a path`, with the descriptions above.
   ```

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

## Step 4 — Source (repo + paths, or design-only)

A product is **design-only** when it carries no `source` block (specs authored ahead of code). Otherwise `source` is `{ repo: <repo-key>, paths: [<path>, …] }`.

1. Whether this product has source code. In edit mode this is where a design-only product gains a `source` block.

   ```
   Context (print before asking):
   - Where: Step 4 — Source; target `products[<key>].source`
   - Found: `source` on record: <{repo, paths}, or "none — design-only">; registered repos: <keys, or "none">
   - Why asking: whether specs are authored ahead of code is a fact about the product only the operator knows
   - Answers: `has source code` — continue to the repo and paths questions; `source` is written in Step 11 and read by dependency autodetect (Step 5) and `lazy-spec.source-url`; `design-only (no source)` — no `source` key; code-grounded autodetect and source links are skipped until source is added later in edit mode
   AskUserQuestion: header "Source code", question "Does product `<key>` have source code to bind — a repo checkout plus the subdirectories it covers — or is it design-only for now? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `has source code` / `design-only (no source)` with the descriptions above.
   ```

   - **design-only** → record no `source`; skip the rest of this step (outcome `design-only`) and skip Step 5's autodetect.

2. **Repo** — if the user picks "other", run the **inline repo wizard** (below) before continuing.

   ```
   Context (print before asking):
   - Where: Step 4 — Repo; target `products[<key>].source.repo`
   - Found: registered repos (`repos` section, Step 1): <key → local_path, …, or "none">
   - Why asking: which registered checkout holds this product's code is not derivable from the vault
   - Answers: `<repo-key>` — written as `source.repo`, the `lazy.settings.json[repos]` record `lazy-spec.resolve-repo` resolves; `other — register a new repo` — the inline repo wizard runs first, then this product uses the new key
   AskUserQuestion: header "Source repo", question "Which repo record holds the code of product `<key>`? Registered: <keys>. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md", options: each registered repo key + `other — register a new repo`, with the descriptions above.
   ```

3. **Paths** — for each path, validate it exists under the resolved repo's `local_path`; if any does not exist, warn and ask whether to proceed (keep the path as a forward declaration) or correct it.

   ```
   Context (print before asking):
   - Where: Step 4 — Paths; target `products[<key>].source.paths`, checkout <local_path>
   - Found: repo `<repo-key>` at <local_path>, branch `<branch>`
   - Why asking: which subdirectories the product covers bounds dependency autodetect and source-url resolution — a scope only the operator can draw
   - Answers: `single subpath` — one string via "other"; `multiple subpaths` — comma-separated via "other"; written as `source.paths` in Step 11, each validated under <local_path> (a missing one raises the follow-up below)
   AskUserQuestion: header "Source paths", question "Subdirectories of `<repo-key>` (<local_path>) that product `<key>` covers? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `single subpath` / `multiple subpaths` (free text via "other") with the descriptions above.
   ```

   ```
   Context (print before asking):
   - Where: Step 4 — Paths validation; target `<local_path>/<path>`
   - Found: `<path>` does not exist under <local_path>
   - Why asking: a typo and a forward declaration look the same — only the operator knows which
   - Answers: `proceed` — keep `<path>` in `source.paths` as a forward declaration; `correct` — re-ask the paths question for this entry
   AskUserQuestion: header "Missing path", question "`<path>` does not exist under `<repo-key>` (<local_path>). Keep it as a forward declaration, or correct it?", options `proceed` / `correct` with the descriptions above.
   ```

Outcome: `sourced` or `design-only`.

### Inline repo wizard

Triggered from Step 4 when `source.repo` names an unregistered repo:

1. The repo key. Validate uniqueness among the keys in the `repos` section read in Step 1.

   ```
   Context (print before asking):
   - Where: Step 4 — Inline repo wizard, repo key; target `repos[<repo-key>]`
   - Found: registered repo keys: <keys, or "none">
   - Why asking: the key is the record's identity across products; nothing derives it
   - Answers: any typed key (via "other") — becomes `repos[<repo-key>]` at wizard step 5 and this product's `source.repo`; a key already registered is refused and re-asked
   AskUserQuestion: header "Repo key", question "Key for the new repo record (lowercase-with-hyphens, e.g. `backend`, `shared`; taken: <keys>)?", free text via "other".
   ```

2. `local_path`. Validate existence: for `"."` run `git rev-parse --show-toplevel` (cwd must be a git repo); for an absolute path, the directory exists and is a git repo.

   ```
   Context (print before asking):
   - Where: Step 4 — Inline repo wizard, local path; target `repos[<repo-key>].local_path`
   - Found: cwd git root: <`git rev-parse --show-toplevel` output, or "not a git repo">
   - Why asking: an absolute path pins the record to one machine's checkout, `"."` stays checkout-agnostic — the trade-off is the operator's
   - Answers: `this repo (.)` — the code lives in the very repo that holds `lazy.settings.json`: the literal `"."` is written, and every checkout (dev, or a runtime checkout under `~/lazy-runtime/<repo>`) resolves it to its own root via `git rev-parse --show-toplevel`, so no absolute path leaks into tracked settings; `absolute path` — a fixed checkout elsewhere on this machine (the cross-repo case, e.g. a separate spec-vault and code repo), typed via "other"; either is validated, then written at wizard step 5
   AskUserQuestion: header "Local path", question "Where does repo `<repo-key>` live on this machine — the repo holding lazy.settings.json (<git root>), or a fixed absolute path elsewhere? `lazy-spec.resolve-repo` reads its source and git remote there. See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `this repo (.)` / `absolute path` with the descriptions above.
   ```

3. Auto-detect the default branch:

   ```bash
   git -C <local_path> symbolic-ref --short refs/remotes/<remote-name>/HEAD 2>/dev/null \
     | sed 's@^[^/]*/@@' \
     || git -C <local_path> rev-parse --abbrev-ref HEAD
   ```

4. Confirm detected `local_path` + `branch` before writing.

   ```
   Context (print before asking):
   - Where: Step 4 — Inline repo wizard, confirm; target `repos[<repo-key>]`
   - Found: local_path `<local_path>`, default branch `<branch>` (from `symbolic-ref`, or the HEAD fallback)
   - Why asking: the branch was auto-detected, and the record is about to be persisted
   - Answers: `write` — wizard step 5 writes `{ "local_path", "branch" }` into `repos[<repo-key>]`; `correct` — re-enter the branch or local_path via "other", then re-confirm
   AskUserQuestion: header "Confirm repo", question "Register `<repo-key>` as local_path `<local_path>`, branch `<branch>`?", options `write` / `correct` with the descriptions above.
   ```

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

Expected report block (per the parallel-scan coordinator pattern in `lazycortex-core`'s `references/lazy-core.parallel-scan.md`):

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

Iterate candidates **one `AskUserQuestion` call per candidate**. Keep one running list. In edit mode, append accepted entries to the existing `dependencies` list (never clobber prior entries); never emit an empty `dependencies: []`.

```
Context (print before asking, one block per candidate):
- Where: Step 5 — Dependencies; target `products[<key>].dependencies`
- Found: `[DEP] <dep-label>` kind `<internal-product | repo | external>`, evidence `<file>:<line> — <import line>`; accepted so far: <running list, or "none">
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

Optional per-role guideline paths folded into this product's launch-checkbox job dispatch (`spec.coordinator`, per `products[<key>].guidelines` in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`). `guidelines` is a dict keyed by the dispatched role token (`planner`, `tester`, `developer`, `architect`) plus the wildcard `"*"`, each value a list of repo-relative file paths.

```
Context (print before asking):
- Where: Step 7 — Guidelines; target `products[<key>].guidelines`
- Found: `guidelines` on record: <dict, or "none">
- Why asking: which repo files an expert should read before a launch-checkbox job is project knowledge nothing derives
- Answers (create mode): `none (no guidelines)` — no key written; `add guideline paths` — the role/paths follow-up below, one role at a time until the operator is done. Answers (edit mode, current dict shown): `keep as-is` — unchanged; `add/change a role's paths` / `remove a role's paths` — the same follow-up per role. A path's contents are folded into the job's context when an operator ticks a launch checkbox in an asset's `# Gates` section — the code-plan checkbox dispatches under `planner`, `Write test-plan` and `Start testing` both under `tester`, `Start implementation` under `developer`, `Write architecture` under `architect`; `*` paths are folded into every one of those jobs regardless of role. A path that does not resolve is never silently dropped — it surfaces as a warning appended to the asset's `# History` section on every dispatch, so a typo stays visible until fixed
AskUserQuestion: header "Guidelines", question "Per-role guideline files to hand product `<key>`'s dispatched experts as extra context (on record: <dict, or none>)? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options per mode as above, with the descriptions above.
```

Role/paths follow-up (repeat until the operator is done):

```
Context (print before asking):
- Where: Step 7 — Guideline role, then its paths; target `products[<key>].guidelines.<role>`
- Found: roles already set: <roles → paths, or "none">
- Why asking: the dict is keyed by role; the paths are free text
- Answers: `planner` / `tester` / `developer` / `architect` / `*` — the role to set (edit mode's `remove a role's paths` offers the roles on record instead, and removes the chosen one); then any comma-separated repo-relative paths (via "other") — validated below, written under that role in Step 11
AskUserQuestion: header "Guideline role", question "Which role of product `<key>` gets guideline paths (set so far: <roles>)?", options the five role tokens with the descriptions above; then header "Guideline paths", question "Repo-relative paths for role `<role>` of product `<key>` (comma-separated)?", free text via "other".
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

## Step 8 — Built-in review experts (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer)

The built-in review classes generated in Step 12 are driven by nine roles — `use-case-writer`, `designer`, `system-designer`, `architect`, `ui-designer`, `planner`, `developer`, `tester`, `data-writer`. These experts are **shared vault-wide**: one common set of review classes serves every product whose role-experts are identical, so a second product normally reuses the first product's experts rather than adding its own classes (see Step 12). Read the available expert names and the current review classes first:

```bash
lazycortex-core settings-get experts
lazycortex-core settings-get review
```

The keys of the first printed object are the registered expert names. In the second, the **shared set** is the classes whose `class` labels are the bare doc-kinds `use-cases`, `design`, `system-design`, `system-tech`, `ui-design`, `code-plan`, `test-plan`, `bug`, `code-report`, `test-report`, `data-report`, `docs-report` (no `@<key>` suffix). Determine the path:

- **Shared set absent** (no bare-label class of any of those kinds — the usual first-product case) → ask the role questions below; the answers seed the shared set in Step 12. Outcome `assigned`.
- **Shared set present** → ask whether this product rides the shared experts or defines a product-specific override:

  ```
  Context (print before asking):
  - Where: Step 8 — Review experts; target `review.classes` (shared set vs `<kind>@<key>` override)
  - Found: shared set present — experts read from its bare-label classes: use-case-writer `<…>`, designer `<…>`, system-designer `<…>`, architect `<…>`, ui-designer `<…>`, planner `<…>`, developer `<…>`, tester `<…>`, data-writer `<…>`
  - Why asking: whether this product's design / code-plan / test-plan / bug docs need a different persona than the rest of the vault is a judgement about the product, not derivable
  - Answers: `use shared experts` — NO new review classes for this product; Step 12 reuses the shared set and collapses this product's stale `@<key>` classes (outcome `shared-set`); `define product-specific override` — the nine role questions below, then Step 12 generates product-scoped `<kind>@<key>` classes that shadow the shared set for this product only, inserted earlier in the list so first-match-wins routes this product's docs to them (outcome `override`); every other product keeps riding the shared set either way
  AskUserQuestion: header "Review experts", question "Product `<key>`: ride the vault's shared review experts (<experts>), or define a product-specific override? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `use shared experts` / `define product-specific override` with the descriptions above.
  ```

  - **use shared experts** → read the experts from the shared classes (`use-case-writer` = the `use-cases` class main writer, `designer` = the `design` class `experts.main[0].name`, `system-designer` = the `system-design` class main writer, `architect` = the `system-tech` class main writer, `ui-designer` = the `ui-design` class main writer, `planner` = the `code-plan` class main writer, `developer` = the `code-report` class main writer, `tester` = the `bug` class main writer, `data-writer` = the `data-report` class main writer) and do NOT ask the role questions. Outcome `shared-set`. **Fallback for a class the shared set lacks:** a vault seeded before the `use-cases` and `ui-design` classes existed carries neither, so those two reads come back empty — for each missing one, take the same path the `docs-report` class takes below: ask that single role question offering only the "other — define a new persona" option, pointing the operator at `lazycortex-experts` to compose one, and omit the class when they have none. Every other role still rides the shared set and the outcome stays `shared-set`.
  - **define product-specific override** → ask the role questions below; the answers drive this product's override classes in Step 12. Outcome `override`.

Role questions (asked only on the `assigned` and `override` paths — skipped on `shared-set`): for EACH of the nine roles in order (`use-case-writer`, then `designer`, then `system-designer`, then `architect`, then `ui-designer`, then `planner`, then `developer`, then `tester`, then `data-writer`), issue a SEPARATE `AskUserQuestion` (one per role) offering the registered expert names as options. Where each role lands in the built-in classes (Step 12), for the question's `<landing>`:

- `use-case-writer` — main writer of the `use-cases` class, defaulting to `<domain>.use-case-writer` when `lazycortex-experts` seeded one.
- `designer` — main writer of the asset-level `design` and `vision` classes and a section validator on `use-cases`.
- `system-designer` — main writer of the `system-design` and `system-vision` classes (the product-root and project-root `design.md` / `vision.md`); never validates.
- `architect` — main writer of the `system-tech` and `architecture` classes and the standing validator of everything design-shaped (a section validator on `design`, `system-design`, `ui-design`, and `code-plan`).
- `ui-designer` — main writer of the `ui-design` class, defaulting to `<domain>.ui-designer` when `lazycortex-experts` seeded one.
- `planner` — main writer of the `code-plan` class and a section validator on `architecture`.
- `developer` — main writer of the `code-report` class and a section validator on the `test-plan` and `bug` classes.
- `tester` — main writer of `bug`, `test-plan`, and `test-report`, and a section validator on the `code-plan` class.
- `data-writer` — main writer of the `data-report` class, defaulting to `<domain>.data-writer` when `lazycortex-experts` seeded one.

The `docs-report` class has no default writer — offer only the "other" path for it, pointing the operator at `lazycortex-experts` to compose one, and omit the class when they have none. Do NOT invent an expert name — only names present in `settings-get experts` are valid.

```
Context (print before asking, one block per role):
- Where: Step 8 — Role `<role>` (<n> of 9); target the class(es) Step 12 binds it to: <landing>
- Found: registered experts (`settings-get experts`): <names>; default for this role: <`<domain>.<role>` if seeded, or "none">
- Why asking: the chosen expert's persona is what actually reviews/writes the product's use-cases / design / tech / ui-design / code-plan / test-plan / code-report / test-report / data-report / bug docs in the review loop, and only a registered name is valid
- Answers: `<expert-name>` — bound as this role's writer/validator in Step 12's classes, persisted in `review.classes`; `other — define a new persona` — compose the expert via `lazycortex-experts`, then re-run this skill (choosing it aborts with `expert-undefined`; nothing is written)
AskUserQuestion: header "<role>", question "Which registered expert is product `<key>`'s `<role>` — <landing>? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options: each registered expert name + `other — define a new persona`, with the descriptions above.
```


Validate that every chosen role expert (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer) is a key in `settings-get experts`. If any chosen name is the "other" sentinel, abort with the `lazycortex-experts` pointer and do NOT write — the product is not registered until real expert names exist.

Outcome: `assigned`, `shared-set`, or `override` (or abort `expert-undefined`).

## Step 9 — Asset types (delegate)

Whether to declare any asset types of the product's own (beyond the shipped feature / change / bug / content / research set) now. An asset type is a declared kind of asset (characters / scenes / chapters / …) written into `products[<key>].asset_types.<name>`, carrying its icon, its primary document (the type's `start_doc` — the attach target; a fresh asset spawns with no documents), its default tools, the folder its assets land in by default, and the playbook the coordinator works them under.

```
Context (print before asking):
- Where: Step 9 — Asset types; target `products[<key>].asset_types`
- Found: declared types on record: <names, or "none">; shipped types need no declaration: feature / change / bug / content / research
- Why asking: which kinds of asset the product has beyond the shipped set is content design only the operator knows
- Answers: `declare types now` — nothing written here; after Step 13 the operator runs `/lazy-spec.add-asset-type <compound-key>` once per type (a dedicated skill's job, not an inline branch of this wizard; outcome `delegated`, instruction surfaced in the Report); `none (shipped types only)` — outcome `shipped-only`. Declaring a type creates nothing on disk — every group folder, shipped types included, appears only at the first `create-asset` that lands an asset in it, seeded with its group folder-note by the scaffold; a type's design / code-plan / test-plan docs are covered by the shared behavior-keyed review classes (Step 12's right-anchored wildcard globs), so no per-type class exists
AskUserQuestion: header "Asset types", question "Does product `<key>` need asset types of its own (characters / scenes / chapters / …) beyond the shipped feature / change / bug / content / research set? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `declare types now` / `none (shipped types only)` with the descriptions above.
```

- **declare types now** → after this skill finishes (Step 13 done), the operator runs `/lazy-spec.add-asset-type <compound-key>` once per type. Do NOT inline-duplicate that flow — surface the instruction in the Report (outcome `delegated`). Do NOT call `lazy-spec.add-asset-type` from here; the product must be fully written and audited first.
- **none** → outcome `shipped-only`.

Outcome: `delegated` or `shipped-only`.

## Step 10 — Workflow mode (full vs spec-only)

The product's workflow profile. In edit mode, default the menu to the product's current value (absent reads as `full`).

```
Context (print before asking):
- Where: Step 10 — Workflow mode; target `products[<key>].mode`
- Found: `mode` on record: <"spec-only", or absent → full>
- Why asking: a per-product commitment, not a per-asset toggle — every asset under the product follows the chosen ladder, and only the operator knows whether specs are the whole deliverable
- Answers: `full (default — design through implementation and testing)` — no key written; the coordinator's ladder (`lazy-spec.coordination-playbook.md` Chapter 14) runs vision → design → architecture → plan → implementation → test for every asset; `spec-only (design and review only; released by operator word)` — `mode: "spec-only"` written in Step 11; the ladder stops after `design.md` approves (`spec_design_done`), `spec_released` flips only on an explicit operator word, and no architecture/plan/implementation/test step ever hangs a checkbox — for a product whose specs are the whole deliverable (a design-only reference other repos consume, not code this repo will itself implement)
AskUserQuestion: header "Workflow mode", question "How far does the coordinator's ladder run for every asset of product `<key>` — full, or spec-only? See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md", options `full (default — design through implementation and testing)` / `spec-only (design and review only; released by operator word)` with the descriptions above.
```

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
2. **Product level note** `<spec_path>/<leaf>.md` (`<leaf>` = the final segment of `spec_path`) — the folder-note `spec.catalog-coordinator` owns (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md`). Never hand-written here: one verb creates it, or brings an existing one up to the level schema without disturbing what the operator put in it.

   ```bash
   lazycortex-specs catalog-note backfill <compound-key>
   ```

   The verb writes `spec_role: product`, the four level gates at `false`, `spec_halted: false`, and the managed paint keys — `iconize_icon` from the Step 6 value (the operator's, or the default `LiPackage`) and `iconize_color` from `products[<key>].color` when the record declares one, otherwise the product default `#64748b` — plus the coordinator's own body sections (`# Summary`, `# Gates`, `# Status brief`, `# Coordinator rules`, `# Coordinator commands`, `# History`, `# Attachments`). On an existing note it adds only what is missing: no key is rewritten, no section is moved, and the operator's `# Coordinator rules` and rendered `# Summary` survive byte-for-byte. A product root is the only ordinary container that carries a colour; group folders beneath it carry none (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` § Container colour). Run the verb in edit mode too — it is idempotent, and a note that predates the level schema gains it here.

   Then author the note's `<!-- spec:precis -->` region — one-line description drawn from the product's design intent — inline between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers of its `# Summary` section, replacing any `_TBD` placeholder, and run `render-container-stats` so the `<!-- spec:stats:* -->` region is populated:

   ```bash
   lazycortex-specs render-container-stats <content_root>/<spec_path>/<leaf>.md
   ```

   Fold the verb's returned `note` path into this step's own commit.

3. **Product-level `vision.md`** (create mode only): if `<content_root>/<spec_path>/vision.md` does not exist AND `<content_root>/<spec_path>/design.md` does not exist either (the seeding guard — a product with a pre-vision `design.md` is a legal state migrated by the operator by hand, never seeded over), instantiate `${CLAUDE_PLUGIN_ROOT}/templates/spec.docs/system-vision.md`, substituting `{{product}}` with the product key, and `Write` it to `<content_root>/<spec_path>/vision.md`. The seeding is the whole obligation — no gate and no doctor check exists at this level. Outcome: `vision-seeded`, `vision-already-present`, or `vision-skipped-pre-vision-design`.
4. **Vault-root request inbox** (shared by every product — created once, idempotent): resolve the spec content-root `<content_root> = <repo>/<spec.vault_root>` (default `specs`; read `spec.vault_root` from `.claude/lazy.settings.json`). Ensure `<content_root>/requests/` exists (`Bash(mkdir -p <content_root>/requests)`). ALWAYS `Write` `<content_root>/requests/requests.md` when absent as the operator-zone inbox folder-note (`iconize_icon: LiInbox`, `iconize_color: "#f0abfc"` — the intake-shelf accent, double-quoted, NO `spec_role`, the `# Summary` skeleton from the group-note template with the static précis `Vault-wide request intake inbox.` filled in, then operator-zone body) and ALWAYS `git add` it so the `requests/` directory is committed and pushed even with zero request files. If it already exists, leave the body untouched (stats are refreshed by the event-driven primitive). When creating the requests inbox, run `render-container-stats` on it too:

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

Generate **one class per declared type carrying `review: true`** — the shipped types plus whatever the product declares under `products[<key>].doc_types`. The **shared set** — bare-type labels with right-anchored wildcard globs — serves every product whose role-experts match; a product with divergent experts (Step 8 outcome `override`) gets the same types re-emitted as product-scoped `<type>@<key>` classes inserted BEFORE the shared set. Globs span the product root and every category folder (built-in AND operator-defined) — so `lazy-spec.add-asset-type` never touches `review.classes`, a new category needs no new class, and a new product needs no new class when it rides the shared experts. Reusable validation dicts plus a no-validation case. **`system-designer` is never a validation writer in any class** — it appears only as a `main` writer; `designer` appears as a validation writer only on `use-cases`, never elsewhere; the `architect` is the standing validator of everything design-shaped (`design`, `system-design`, `ui-design`, `code-plan`); no class is validated by its own main writer; the report classes carry no validation bucket, same as `system-tech`. Each checkbox in the launch ladder (`lazy-spec.lifecycle-protocol.md` Part 3) resolves its dispatched expert from the review class matching its own result document — `planner` writes `code-plan.md`, `developer` writes `code-report.md`, `tester` writes both `test-plan.md` and `test-report.md`, `data-writer` writes `data-report.md` — mirroring `lazy-spec.install` § 6e's seed template:

- **A = architect review** — `{ "architect_review": { "name": "<architect>", "section": "Architect review", "position": "bottom" } }`.
- **D = designer review** — `{ "designer_review": { "name": "<designer>", "section": "Designer review", "position": "bottom" } }`.
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

**Expert bindings** (bare-type labels; substituting `<use-case-writer>`, `<designer>`, `<system-designer>`, `<architect>`, `<ui-designer>`, `<planner>`, `<developer>`, `<tester>`, `<data-writer>`, `<docs-writer>`) — the defaults for the shipped types. For a project-declared type the experts are not derivable: ask the operator, exactly one question per such type, naming the type and offering the same A / D / TA / DV / P / NONE validation shapes:

```
Context (print before asking, one block per project-declared type):
- Where: Step 12 — Review classes; target the `<type>` class about to be written into `review.classes`
- Found: `doc-type resolve <type> --product <key>` → `review: true`, declared under `products[<key>].doc_types`, no shipped binding
- Why asking: the validation shape of a project-declared type is not derivable
- Answers: `A` / `D` / `TA` / `DV` / `P` / `NONE` — the validation dict listed above, filled with this product's role experts and persisted on the `<type>` class; asked again only when the type's class is regenerated
AskUserQuestion: header "<type> class", question "Validation shape for product `<key>`'s project-declared type `<type>` — who validates its documents after the main writer?", options `A` / `D` / `TA` / `DV` / `P` / `NONE` with the descriptions above.
```

`design`, `bug`, and `use-cases` additionally carry `context_from_frontmatter: [spec_source_requests]` — at main-job dispatch the dispatcher resolves that frontmatter key's wikilink/path values on the document under review to repo files and folds them into the job's `context/`, so the writer's job bundle includes the originating request(s). Attribution reaches a doc two ways: `lazy-spec.request-apply`'s `ensure_source_request` writer stamps `spec_source_requests` onto an attach target's primary doc, and `lazycortex-specs seed-doc` copies the status folder-note's union (stamped there at apply) onto every checkbox-seeded doc:

| `class` label | `paths` | `experts.main` | `experts.validation` | extra |
|---|---|---|---|---|
| `use-cases` | `["*/use-cases.md"]` | `[{ "name": "<use-case-writer>" }]` | D | `context_from_frontmatter: [spec_source_requests]` |
| `design` | `["*/*/design.md"]` | `[{ "name": "<designer>" }]` | A | `context_from_frontmatter: [spec_source_requests]` |
| `vision` | `["*/*/vision.md"]` | `[{ "name": "<designer>" }]` | NONE | `context_from_frontmatter: [spec_source_requests]` |
| `system-vision` | `["*/vision.md", "vision.md"]` | `[{ "name": "<system-designer>" }]` | NONE | `context_from_frontmatter: [spec_source_requests]` |
| `system-design` | `["*/design.md", "design.md"]` | `[{ "name": "<system-designer>" }]` | A | `context_from_frontmatter: [spec_source_requests]` |
| `system-tech` | `["*/tech.md", "tech.md"]` | `[{ "name": "<architect>" }]` | NONE | — |
| `architecture` | `["*/architecture.md"]` | `[{ "name": "<architect>" }]` | P | — |
| `ui-design` | `["*/ui-design.md"]` | `[{ "name": "<ui-designer>" }]` | A | — |
| `code-plan` | `["*/code-plan.md"]` | `[{ "name": "<planner>" }]` | TA | — |
| `test-plan` | `["*/test-plan.md"]` | `[{ "name": "<tester>" }]` | DV | — |
| `bug` | `["bugs/*/bug.md"]` | `[{ "name": "<tester>" }]` | DV | `context_from_frontmatter: [spec_source_requests]` |
| `code-report` | `["*/code-report.md"]` | `[{ "name": "<developer>" }]` | NONE | — |
| `test-report` | `["*/test-report.md"]` | `[{ "name": "<tester>" }]` | NONE | — |
| `data-report` | `["*/data-report.md"]` | `[{ "name": "<data-writer>" }]` | NONE | — |
| `docs-report` | `["*/docs-report.md"]` | `[{ "name": "<docs-writer>" }]` | NONE | — |

The `system-vision` / `system-design` / `system-tech` classes serve the **level docs** — the product-root `vision.md` / `design.md` / `tech.md` set AND the same set at the spec content-root (the project-wide spec; no config key declares it — the files' existence is the declaration, except `vision.md`, which is seeded). One expert set serves both scales. The vision classes carry NO validators — the writer and the operator close the loop. A typed document routes by its `spec_doc_type`, so the overlapping design globs are untyped-fallback tie-breakers only: the asset `design` class sits earlier in the list and wins the fallback.

**Override set** (product-scoped labels; generated ONLY on Step 8 outcome `override`, with this product's `<spec_path>` and override experts) — shadows the shared set for one product:

| `class` label | `paths` | `experts.main` | `experts.validation` |
|---|---|---|---|
| `use-cases@<key>` | `["<spec_path>/*/*/use-cases.md"]` | `[{ "name": "<use-case-writer>" }]` | D |
| `design@<key>` | `["<spec_path>/*/*/design.md"]` | `[{ "name": "<designer>" }]` | A |
| `vision@<key>` | `["<spec_path>/*/*/vision.md"]` | `[{ "name": "<designer>" }]` | NONE |
| `system-vision@<key>` | `["<spec_path>/vision.md"]` | `[{ "name": "<system-designer>" }]` | NONE |
| `system-design@<key>` | `["<spec_path>/design.md"]` | `[{ "name": "<system-designer>" }]` | A |
| `system-tech@<key>` | `["<spec_path>/tech.md"]` | `[{ "name": "<architect>" }]` | NONE |
| `architecture@<key>` | `["<spec_path>/*/*/architecture.md"]` | `[{ "name": "<architect>" }]` | P |
| `ui-design@<key>` | `["<spec_path>/*/*/ui-design.md"]` | `[{ "name": "<ui-designer>" }]` | A |
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

`paths` still matter in two places. They discriminate which product an `@<key>` override applies to, and they are the whole matcher for a document carrying no `spec_doc_type` (a free-form intake file, a consumer's own document class), which falls back to first-match-wins over `paths` in list order. On that fallback path the globs use `PurePath.match` right-anchored, where `*` never crosses `/` and `**` acts as a SINGLE path segment — never write `**` into class paths expecting recursion. Right-anchoring is why the shared globs need no `<spec_path>` prefix: `*/design.md` matches BOTH the product-root `<spec_path>/design.md` (its last two segments) and every asset `<category>/<slug>/design.md`; `bugs/*/bug.md` matches `<spec_path>/bugs/<slug>/bug.md`. Discovery itself is review's own repo-wide `lazy-review.coordinator-watch` pathspec — no per-product mask bounds it, so a class's globs are the whole of the routing. A product's override globs deliberately OVERLAP the shared globs, so override classes MUST still sit earlier in `review.classes` than the shared set.

**Reconcile, not append.** Read `review.classes` and act per Step 8's outcome:

1. **`assigned` (shared set absent)** — append the **shared** classes with the Step-8 experts. Then run the *per-product collapse* below to drop any stale `<kind>@<key>` classes this product carries from the old per-product scheme.
2. **`shared-set` (present, reuse)** — leave the shared set untouched; run the *per-product collapse* to drop this product's stale `<kind>@<key>` classes (this is the migration — the product stops carrying its own classes and rides the shared set).
3. **`override` (present, product-specific)** — first compute this product's override experts; if they are identical to the shared set's experts for every role, there is no divergence, so fall through to the `shared-set` behavior (no override classes written). Otherwise remove any prior `<kind>@<key>` classes for THIS product, then insert the **override** classes (product-scoped globs, override experts) immediately BEFORE the first shared-set class.

**Per-product collapse.** Remove from `review.classes` every class whose `class` label ends in `@<key>` for THIS `<key>` and whose prefix either matches a type declared in this product's scope (`doc-type list --product <key>`) or is one of the legacy labels the open set no longer covers — the removed `plan`, and any dotted per-category label (`spec.design`, `spec.tech`, `bugs.bug`, `bugs.plan`, `<category>.design`, `<category>.plan`). Before removing one, compare its `experts` block to the shared-set class of the same type: if they **differ**, ask first:

```
Context (print before asking):
- Where: Step 12 — Per-product collapse; target class `<kind>@<key>` in `review.classes`
- Found: its `experts` block differs from the shared `<kind>` class: <the two blocks, or their diff>
- Why asking: the divergence is either a deliberate override or a leftover of the old per-product scheme — only the operator knows which
- Answers: `keep as override` — re-insert `<kind>@<key>` before the shared set (as in outcome 3); this product keeps its variant; `collapse` — remove it; the product rides the shared `<kind>` class
AskUserQuestion: header "Diverging class", question "Class `<kind>@<key>` carries different experts than the shared `<kind>` class. Keep the variant as product `<key>`'s override, or collapse it into the shared set?", options `keep as override` / `collapse` with the descriptions above.
```

Bare doc-kind labels (the shared set) and `@<key>` labels naming a DIFFERENT product are never touched. This makes Step 12 idempotent across create and edit mode — re-running `/lazy-spec.product-config` in edit mode on a product generated under the old per-product scheme IS the migration to the shared set (a per-product scheme's classes collapse onto the shared set).

**Expert re-verification (MANDATORY, before the write).** Collect every expert name the classes are about to carry — each `main[].name`, each `validation.<section-id>.name`, each `history.name` — and re-check every one against the keys of `lazycortex-core settings-get experts`. Any name missing → abort WITHOUT calling `settings-set review`, naming the dangling expert and pointing at `lazycortex-experts` (same abort as Step 8's `expert-undefined`). Step 8's earlier validation does not guard this write — a dangling reference (e.g. an unregistered tester) must be impossible to persist.

Write the edited review object back:

```bash
printf '%s' '<edited-review-json>' | lazycortex-core settings-set review
```

Then check for the retired `lazy-review.scan` routine — a leftover of the md-scan sieve model, which `/lazy-review.install` deletes on sight (its `process-file` consumer no longer exists, so a surviving registration is a routine the daemon runs into a missing subcommand). Review's live discovery surface is the repo-wide `lazy-review.coordinator-watch` git-watch routine, which its own install seeds and which carries no per-product masks — nothing here to normalize, in either routine. `Bash`-free check: **absent** → outcome `legacy-scan-routine-absent`. **Present** → do NOT touch it, and report `legacy-scan-routine-present` so the operator re-runs `/lazy-review.install`. Same posture as `/lazy-spec.install`'s Step 6f, which owns this cleanup for the install path.

Then normalize the `lazy-spec.coordinator-watch` routine — but only when `routines["lazy-spec.coordinator-watch"]` is present (skip silently when absent — `/lazy-spec.install` has not run here). Resolve `<content_root>` = the `spec.vault_root` setting (default `specs`) and union this product's glob `<content_root>/<spec_path>/*/*` into the routine's `group_globs` list (create the key if absent) — `group_globs` collapses per-asset file items into one worker dispatch per asset directory (`lazy-core.routine-types-schema.md` § git `group_globs`); the glob stops at category/asset depth rather than reaching every document under the product. When `spec.vault_root` is `.`, the prefix is omitted and the glob is `<spec_path>/*/*`. Idempotent — a glob already present for this product is left untouched, and no other product's entry is ever removed.

Finally, verify the generated classes by invoking `/lazy-review.audit` via the `Skill` tool (`skill: "lazycortex-review:lazy-review.audit"`) and surface its findings — report the `audit: <LEVEL> (<N> findings)` line and any FAIL/WARN detail. If the audit reports FAIL, report it; do not silently leave broken classes.

Outcome: `wired` (carry the audit level into the report).

## Step 13 — Verify + log the run

Invoke `/lazy-spec.audit <compound-key>` via the `Skill` tool (`skill: "lazycortex-specs:lazy-spec.audit"`) to confirm the product record, folder tree, and folder-notes are consistent. Surface its findings.

Then, per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.product-config/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.product-config)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC, `date -u +'%Y-%m-%d %H:%M:%S UTC'`), `input` (the arguments passed, or `none`). Body: `# lazy-spec.product-config` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `verified` + `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with the `lazy-spec.audit` summary line from Step 13 and the `audit:` line from Step 12. If Step 9 was `delegated`, include the `/lazy-spec.add-asset-type <compound-key>` instruction.

## Failure modes

- **`/lazy-spec.product-config` aborts with `aborted:no-vault-spec`** — create mode with neither `vision.md` nor a pre-vision `design.md` at the spec content-root → run `/lazy-spec.install` (its Step 6.9 seeds the vault-vision draft), fill it in, then re-run this skill.

- **`/lazy-spec.product-config` aborts pointing at `lazycortex-experts`** — a chosen role expert (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer) is not registered in `experts` → compose the persona via `lazycortex-experts`, then re-run this skill.
- **`/lazy-spec.product-config` refuses because the spec_path is nested** — the chosen `spec_path` sits under another product's `spec_path` (products are flat) → choose a path outside every registered product's subtree, then re-run.
- **`/lazy-spec.product-config` refuses because the product key already exists** — the chosen key is already a `products` key → edit that product instead, or pick a different key.
- **`/lazy-review.audit` reports FAIL after Step 12** — a generated class references an unregistered expert or violates the section-writer schema → fix the expert assignments (re-run Step 8 with registered experts) and re-audit.
- **`/lazy-spec.product-config` skips a declared type, leaving it with no class** — a type declared `review: true` whose experts the operator never answered for gets no class, and every document of that type then stays outside the review loop indefinitely → re-run the skill and answer the `AskUserQuestion` naming that type, or declare the type `review: false` if it genuinely should not be reviewed.
