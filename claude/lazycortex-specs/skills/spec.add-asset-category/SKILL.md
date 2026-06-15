---
name: spec.add-asset-category
description: Register a new operator-defined asset category on a product — writes the category block (`icon`, optional `color`) into `products[<key>].asset_categories.<name>`, scaffolds the category folder + operator-zone folder-note (carrying the managed `iconize_icon`/`iconize_color` and an operator-authored `description`), and appends the two default review classes (design + plan) so the category's docs enter the review loop. Invoke when an operator wants a product to grow a new asset kind (characters / scenes / chapters / …) beyond the built-in feature / change / bug set.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Add Asset Category

Register one operator-defined asset category on a product and wire it into the system end to end. Resolves the product from `lazy.settings.json[products][<key>]`, collects the category name / description / icon / per-role expert assignments through a one-question-at-a-time wizard, writes the category block into the product's `asset_categories`, scaffolds the category folder and its operator-zone folder-note, and appends the default design + plan review classes so `spec.create-asset` instances of this category flow through review. Asset categories are an open set — a category registered here is recognised by `spec.request-classify`, `spec.create-asset`, and the review daemon on their next run, with no rubric or code edit.

The category's per-block config carries ONLY `{ "icon": <icon> }` (plus optional `"color"`). The category's human description does NOT live in config — it is authored into the `description` frontmatter of the category folder-note (`<spec_path>/<name>/<name>.md`), which the plugin only READS. The plugin WRITES the managed `iconize_icon` / `iconize_color` keys into that folder-note from config. The folder-note carries NO `spec_role` — it is an operator-zone folder-note.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Ask the category name`
   - `Step 3 — Ask the description`
   - `Step 4 — Ask the icon + color`
   - `Step 5 — Pick the per-role experts`
   - `Step 6 — Write the category block`
   - `Step 7 — Seed local category templates from spec._content/`
   - `Step 8 — Render the category folder-note from the seeded template`
   - `Step 9 — Append the two review classes + audit`
   - `Step 10 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product> [<category-name>]`.

1. **`<product>`** — the product compound-key (e.g. `server-tester-chapter`).
2. **`<category-name>`** (optional) — the category folder name under the product, lowercase-with-hyphens. When passed, Step 2's question is skipped (outcome `taken-from-arg`); when absent, Step 2 asks for it.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer. Never ask a bare one-line question.

## Step 1 — Resolve the product

Resolve the product record:

```bash
lazycortex-specs resolve-product by-key <product>
```

The command prints `{"key": "<product>", "record": <record-or-null>}` with `spec_path` (required, vault-relative), optional `language` (defaults to `en`), and optional `asset_categories`.

- If `record` is `null` → the product is not registered. Refuse with a message naming `<product>` and suggesting `/spec.product-config` to register it. Do NOT proceed.
- Otherwise capture `spec_path`, `language` (default `en` when absent), and the existing `asset_categories` keys (default `{}`).

All narrative prose this skill authors (the folder-note `description`) is rendered in the product's `language`. Frontmatter keys, fixed headers, wikilinks, settings JSON, review-class `class` labels, and section ids stay English.

Outcome: `resolved`.

## Step 2 — Ask the category name

If `<category-name>` was passed as an argument, validate it against `^[a-z][a-z0-9-]*$`, confirm it is not already a key in the product's `asset_categories` (refuse and stop if it is — suggest editing the existing category instead), and skip the question (outcome `taken-from-arg`).

Otherwise `AskUserQuestion` for the category folder name. Stem: the category name is the folder created under `<spec_path>/<name>/` AND the key written into `products[<key>].asset_categories.<name>`; `spec.create-asset <product> <name> <slug>` scaffolds instances of it, and `spec.request-classify` recognises it as a request class. Why-it-matters: the name is the stable identity of the category across config, folder layout, and review-class `paths` globs — renaming later means moving folders and rewriting classes. Offer concrete example labels (e.g. `characters`, `scenes`, `chapters`) plus an "other (type your own)" path; validate the chosen string against `^[a-z][a-z0-9-]*$` and re-ask on failure or collision with an existing category. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Outcome: `named` or `taken-from-arg`.

## Step 3 — Ask the description

`AskUserQuestion` for the category description (free prose). Stem: this prose is written verbatim into the `description` frontmatter of the category folder-note (`<spec_path>/<name>/<name>.md`); the plugin only READS it (it never overwrites operator description text), so it is the durable human explanation of what this category holds. Why-it-matters: downstream help and request-classification read this folder-note to understand the category's intent; an empty description leaves the category undocumented. Offer a short menu of framings (e.g. "one-line summary", "a paragraph with examples") plus an "other (type your own)" free-text path; render the final prose in the product's `language`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Outcome: `described`.

## Step 4 — Ask the icon + color

`AskUserQuestion` for the required icon. Stem: the icon is the iconize identifier (a Lucide name like `LiUsers`, or a literal emoji) written into BOTH `products[<key>].asset_categories.<name>.icon` AND the category folder-note's managed `iconize_icon` frontmatter; the Obsidian iconize system paints it on the category folder. Why-it-matters: the icon is how the operator visually distinguishes this category in the file explorer; the category is incomplete without one. Offer a few concrete suggestions plus an "other (type your own)" path. **The skill MUST refuse to finish if no icon is provided** — if the operator declines every option and gives no value, abort with a message stating an icon is required and do NOT write anything. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Then `AskUserQuestion` for the optional color. Stem: an optional hex color (e.g. `#7E57C2`) written into `asset_categories.<name>.color` and mirrored into the folder-note's managed `iconize_color`; it tints the icon. Why-it-matters: purely cosmetic — omit it to inherit the default icon color. Offer a couple of example hex values plus "none (skip color)" and an "other (type your own)" path. Capture `<color>` only when a real hex is given; treat "none" as absent.

Outcome: `iconed` (or abort `missing-icon` — never write).

## Step 5 — Pick the per-role experts

The default review layout for an operator-defined category has three roles — `designer`, `developer`, `tester` — plus a historian. Read the available expert names first:

```bash
lazycortex-core settings-get experts
```

The keys of the printed object are the registered expert names. Then, for EACH of the three roles in order (`designer`, then `developer`, then `tester`), issue a SEPARATE `AskUserQuestion` (one per role) offering those expert names as options. Stem for each: name the role and where it lands in the two review classes (Step 9) — `designer` is the design class's main writer ONLY and is never a validation writer; `developer` is the plan class's main writer and the design class's section validator; `tester` is the sole section validator on the plan class (plus a section validator on the design class). Why-it-matters: the chosen expert's persona is what actually reviews/writes the category's `design.md` / `plan.md` in the review loop. Each question MUST offer an "other — define a new persona" path whose per-option copy points the operator at `lazycortex-experts` to compose a new expert, then re-run this skill (do NOT invent an expert name here — only names present in `settings-get experts` are valid). See: `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

Then `AskUserQuestion` for the historian — single-select from the expert names, default `review.historian`. Stem: the historian writes the `# History` section of every reviewed doc in both classes. Why-it-matters: it is the `experts.history` writer; it must be an expert registered with commit permission in the local repo.

Validate that every chosen role expert (designer / developer / tester / historian) is a key in `settings-get experts`. If any chosen name is the "other" sentinel, abort with the `lazycortex-experts` pointer and do NOT write — the category is not registered until real expert names exist.

Outcome: `assigned` (or abort `expert-undefined`).

## Step 6 — Write the category block

Each settings mutation is an atomic read-modify-write. Read the current products section, edit the in-memory object, write it back:

```bash
lazycortex-core settings-get products
```

In the parsed object, set `products[<key>].asset_categories.<name>` to `{ "icon": <icon> }` — add `"color": <color>` ONLY when Step 4 captured a hex. Preserve every other product, every other category under this product, and every other field on this product's record. Create the `asset_categories` map if the product has none yet. Then write the whole products object back via stdin:

```bash
printf '%s' '<edited-products-json>' | lazycortex-core settings-set products
```

`settings-set` performs the atomic write. Do NOT touch any other settings section in this step.

Outcome: `registered`.

## Step 7 — Seed local category templates from `spec._content/`

The plugin ships a content-asset baseline at `${CLAUDE_PLUGIN_ROOT}/templates/spec._content/` (four files: `design.md`, `plan.md`, `asset-note.md`, `group-note.md`). This step copies all four into `.claude/templates/spec.<name>/` so that:

- `spec.create-asset <product> <name> <slug>` can later resolve per-category templates without a plugin-baseline (operator-defined categories never have layer 3 — see `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` § Template storage);
- the operator can edit `.claude/templates/spec.<name>/design.md` (and the others) to specialise the category — adding character-specific sections, tweaking plan structure, etc.

Use two separate calls — `Bash(mkdir -p .claude/templates/spec.<name>)` then `Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/spec._content/{design,plan,asset-note,group-note}.md .claude/templates/spec.<name>/)`. Never chain the mkdir into the cp via `&&` (per logging-rule discipline).

The seeded files keep their `{{...}}` placeholders intact — they are templates, not instances. `spec.create-asset` substitutes the asset-side placeholders (`{{slug}}`, `{{product_tag}}`, …) at per-asset scaffold time; this skill substitutes the category-side placeholders (`{{name}}`, `{{description}}`, `{{iconize_icon}}`, `{{iconize_color}}`) in Step 8 below when rendering the actual category folder-note instance.

Outcome: `seeded` (carry the file count — should be `4`).

## Step 8 — Render the category folder-note from the seeded template

Create the category directory and write the operator-zone folder-note from the just-seeded `group-note.md` template. Use two separate calls — `Bash(mkdir -p <spec_path>/<name>)` then the `Write` tool (never chain).

1. Read `.claude/templates/spec.<name>/group-note.md` (the file just seeded in Step 7).
2. Substitute the four category-side placeholders:
   - `{{name}}` → `<name>` (the category name from Step 2);
   - `{{description}}` → the prose from Step 3 (rendered in the product's `language`);
   - `{{iconize_icon}}` → `<icon>` from Step 4;
   - `{{iconize_color}}` → `<color>` from Step 4 if captured. If Step 4 captured no color, REMOVE the `iconize_color:` frontmatter line entirely (do not leave it as `iconize_color: ` with an empty value — that produces a `null` key which iconize misreads as "transparent" rather than "fall back to default").
3. Write the substituted result to `<spec_path>/<name>/<name>.md`.

The folder-note carries NO `spec_role` line (it is an operator-zone folder-note, not a status/role-bearing doc). The body is the operator-owned H1 + HTML comment from the template — author no further prose; the operator fills the body.

Real icon values are fine in both the seeded template and the rendered instance — the iconize hook only strips unresolvable placeholder icon values (e.g. `LiPlaceholder`), not concrete Lucide names or emojis.

Outcome: `rendered`.

## Step 9 — Append the two review classes + audit

Append the default design + plan classes to `review.classes`. Read the section, append, write back:

```bash
lazycortex-core settings-get review
```

In the parsed object, append two entries to `review.classes` (create the list if absent), preserving every existing class. **The review-class schema is owned by `lazycortex-review`** — match it exactly. The schema (from `claude/lazycortex-review/bin/audit.py` + the `lazy-review.configure` skill):

- Each class is an object with a `class` string label (human-readable identity; there is NO `id` field — the daemon matches files to classes purely by `paths` globs), a `paths` non-empty list of glob strings, and an `experts` object.
- `experts.main` — a LIST of `{ "name": <expert> }` writer objects (the opening-writer chain).
- `experts.validation` and `experts.terminal` — a DICT keyed by stable `section-id` (`^[a-z][a-z0-9_-]*$`), each value a writer object `{ "name": <expert>, "section": "<H1 title>", "position": "top" | "bottom" }`. These author named post-approve H1 sections; `validation` sections block finalize and trigger revert-to-main on concerns. There is NO flat "list of reviewers" bucket — a reviewer is expressed as one named validation section.
- `experts.history` — a single `{ "name": <historian> }` object (no `repo`, no `@<repo>` syntax).

Write the two classes (substituting `<spec_path>`, `<name>`, `<designer>`, `<developer>`, `<tester>`, `<historian>`):

- **design class** — `class: "<name>.design@<key>"`, `paths: ["<spec_path>/<name>/**/design.md"]`, `experts.main: [{ "name": "<designer>" }]`, `experts.validation: { "developer_review": { "name": "<developer>", "section": "Developer review", "position": "bottom" }, "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }`, `experts.history: { "name": "<historian>" }`.
- **plan class** — `class: "<name>.plan@<key>"`, `paths: ["<spec_path>/<name>/**/plan.md"]`, `experts.main: [{ "name": "<developer>" }]`, `experts.validation: { "tester_review": { "name": "<tester>", "section": "Tester review", "position": "bottom" } }` (tester-only — `designer` is never a validation writer), `experts.history: { "name": "<historian>" }`.

The `class` label carries the `<name>.<role>@<key>` value because the schema has a `class` field (not `id`) — this is its only identity slot. Write the edited review object back:

```bash
printf '%s' '<edited-review-json>' | lazycortex-core settings-set review
```

Then sync the `lazy-review.scan` routine's `paths:` list to include the two new globs so the daemon's md-scan routine actually sees the category's docs (the routine's `paths:` must be the union of every `review.classes[].paths` glob — read the routine config, add the two globs if absent, write back). Finally, verify the generated classes by invoking `/lazy-review.audit` via the `Skill` tool (`skill: "lazycortex-review:lazy-review.audit"`) and surface its findings — report the `audit: <LEVEL> (<N> findings)` line and any FAIL/WARN detail. If the audit reports FAIL, report it; do not silently leave broken classes.

Outcome: `wired` (carry the audit level into the report).

## Step 10 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.add-asset-category/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.add-asset-category)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the arguments passed). Body: `# spec.add-asset-category` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with the audit summary line from Step 9.

## Failure modes

- **`/spec.add-asset-category` refuses naming an unknown product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/spec.product-config`, then re-invoke.
- **`/spec.add-asset-category` refuses because the category already exists** — `<name>` is already a key in the product's `asset_categories` → pick a different name, or edit the existing category's block / folder-note directly.
- **`/spec.add-asset-category` aborts saying an icon is required** — the operator declined every icon option without typing one → re-invoke and supply an iconize name or emoji; the category is not registered without an icon.
- **`/spec.add-asset-category` aborts pointing at `lazycortex-experts`** — a chosen role expert is not registered in `experts` → compose the persona via `lazycortex-experts`, then re-run this skill.
- **`/lazy-review.audit` reports FAIL after Step 9** — the generated classes reference an unregistered expert or violate the section-writer schema → fix the expert assignments (re-run with registered experts) and re-audit.
