---
name: spec.add-asset-category
description: Register a new operator-defined asset category on a product — writes the category block (`icon`, optional `color`) into `products[<key>].asset_categories.<name>` and scaffolds the category folder + operator-zone folder-note (carrying the managed `iconize_icon`/`iconize_color` and an operator-authored `description`). The category's docs are covered automatically by the shared behavior-keyed review classes (right-anchored wildcard globs) — this skill never touches `review.classes`. Invoke when an operator wants a product to grow a new asset kind (characters / scenes / chapters / …) beyond the built-in feature / change / bug set.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Add Asset Category

Register one operator-defined asset category on a product and wire it into the system end to end. Resolves the product from `lazy.settings.json[products][<key>]`, collects the category name / description / icon through a one-question-at-a-time wizard, writes the category block into the product's `asset_categories`, and scaffolds the category folder and its operator-zone folder-note. Review coverage is automatic: the shared behavior-keyed review classes (`design` / `plan`, written by `spec.product-config` Step 10 with right-anchored `*/<doc>.md` globs — or a product's `<kind>@<key>` override) already span every category folder, so this skill writes NO review classes and syncs NO routine globs. Asset categories are an open set — a category registered here is recognised by `spec.request-classify`, `spec.create-asset`, and the review daemon on their next run, with no rubric, class, or code edit.

The category's per-block config carries ONLY `{ "icon": <icon> }` (plus optional `"color"`). The category's human description does NOT live in config — it is authored into the `description` frontmatter of the category folder-note (`<spec_path>/<name>/<name>.md`), which the plugin only READS. The plugin WRITES the managed `iconize_icon` / `iconize_color` keys into that folder-note from config. The folder-note carries NO `spec_role` — it is an operator-zone folder-note.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Ask the category name`
   - `Step 3 — Ask the description`
   - `Step 4 — Ask the icon + color`
   - `Step 5 — Write the category block`
   - `Step 6 — Seed local category templates from spec._content/`
   - `Step 7 — Render the category folder-note from the seeded template`
   - `Step 8 — Log the run`
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

All narrative prose this skill authors (the folder-note `description`) is rendered in the product's `language`. Frontmatter keys, fixed headers, wikilinks, and settings JSON stay English.

Outcome: `resolved`.

## Step 2 — Ask the category name

If `<category-name>` was passed as an argument, validate it against `^[a-z][a-z0-9-]*$`, confirm it is not already a key in the product's `asset_categories` (refuse and stop if it is — suggest editing the existing category instead), and skip the question (outcome `taken-from-arg`).

Otherwise `AskUserQuestion` for the category folder name. Stem: the category name is the folder created under `<spec_path>/<name>/` AND the key written into `products[<key>].asset_categories.<name>`; `spec.create-asset <product> <name> <slug>` scaffolds instances of it, and `spec.request-classify` recognises it as a request class. Why-it-matters: the name is the stable identity of the category across config and folder layout — renaming later means moving folders (review-class globs are category-agnostic and need no rewrite). Offer concrete example labels (e.g. `characters`, `scenes`, `chapters`) plus an "other (type your own)" path; validate the chosen string against `^[a-z][a-z0-9-]*$` and re-ask on failure or collision with an existing category. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Outcome: `named` or `taken-from-arg`.

## Step 3 — Ask the description

`AskUserQuestion` for the category description (free prose). Stem: this prose is written verbatim into the `description` frontmatter of the category folder-note (`<spec_path>/<name>/<name>.md`); the plugin only READS it (it never overwrites operator description text), so it is the durable human explanation of what this category holds. Why-it-matters: downstream help and request-classification read this folder-note to understand the category's intent; an empty description leaves the category undocumented. Offer a short menu of framings (e.g. "one-line summary", "a paragraph with examples") plus an "other (type your own)" free-text path; render the final prose in the product's `language`. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Outcome: `described`.

## Step 4 — Ask the icon + color

`AskUserQuestion` for the required icon. Stem: the icon is the iconize identifier (a Lucide name like `LiUsers`, or a literal emoji) written into BOTH `products[<key>].asset_categories.<name>.icon` AND the category folder-note's managed `iconize_icon` frontmatter; the Obsidian iconize system paints it on the category folder. Why-it-matters: the icon is how the operator visually distinguishes this category in the file explorer; the category is incomplete without one. Offer a few concrete suggestions plus an "other (type your own)" path. **The skill MUST refuse to finish if no icon is provided** — if the operator declines every option and gives no value, abort with a message stating an icon is required and do NOT write anything. See: `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

Then `AskUserQuestion` for the optional color. Stem: an optional hex color (e.g. `#7E57C2`) written into `asset_categories.<name>.color` and mirrored into the folder-note's managed `iconize_color`; it tints the icon. Why-it-matters: purely cosmetic — omit it to inherit the default icon color. Offer a couple of example hex values plus "none (skip color)" and an "other (type your own)" path. Capture `<color>` only when a real hex is given; treat "none" as absent.

Outcome: `iconed` (or abort `missing-icon` — never write).

## Step 5 — Write the category block

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

## Step 6 — Seed local category templates from `spec._content/`

The plugin ships a content-asset baseline at `${CLAUDE_PLUGIN_ROOT}/templates/spec._content/` (four files: `design.md`, `plan.md`, `asset-note.md`, `group-note.md`). This step copies all four into `.claude/templates/spec.<name>/` so that:

- `spec.create-asset <product> <name> <slug>` can later resolve per-category templates without a plugin-baseline (operator-defined categories never have layer 3 — see `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` § Template storage);
- the operator can edit `.claude/templates/spec.<name>/design.md` (and the others) to specialise the category — adding character-specific sections, tweaking plan structure, etc.

Use two separate calls — `Bash(mkdir -p .claude/templates/spec.<name>)` then `Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/spec._content/{design,plan,asset-note,group-note}.md .claude/templates/spec.<name>/)`. Never chain the mkdir into the cp via `&&` (per logging-rule discipline).

The seeded files keep their `{{...}}` placeholders intact — they are templates, not instances. `spec.create-asset` substitutes the asset-side placeholders (`{{slug}}`, `{{product_tag}}`, …) at per-asset scaffold time; this skill substitutes the category-side placeholders (`{{name}}`, `{{description}}`, `{{iconize_icon}}`, `{{iconize_color}}`) in Step 7 below when rendering the actual category folder-note instance.

Outcome: `seeded` (carry the file count — should be `4`).

## Step 7 — Render the category folder-note from the seeded template

Create the category directory and write the operator-zone folder-note from the just-seeded `group-note.md` template. Use two separate calls — `Bash(mkdir -p <spec_path>/<name>)` then the `Write` tool (never chain).

1. Read `.claude/templates/spec.<name>/group-note.md` (the file just seeded in Step 6).
2. Substitute the four category-side placeholders:
   - `{{name}}` → `<name>` (the category name from Step 2);
   - `{{description}}` → the prose from Step 3 (rendered in the product's `language`);
   - `{{iconize_icon}}` → `<icon>` from Step 4;
   - `{{iconize_color}}` → `<color>` from Step 4 if captured. If Step 4 captured no color, REMOVE the `iconize_color:` frontmatter line entirely (do not leave it as `iconize_color: ` with an empty value — that produces a `null` key which iconize misreads as "transparent" rather than "fall back to default").
3. Write the substituted result to `<spec_path>/<name>/<name>.md`. The rendered body carries the protected `# Summary` skeleton (from the `group-note.md` template: précis placeholder + stats markers + operator-zone comment), which replaces the bare `# <name>` H1 previously authored here.

The folder-note carries NO `spec_role` line (it is an operator-zone folder-note, not a status/role-bearing doc). The body is the operator-owned HTML comment from the template — author no further prose; the operator fills the body.

Real icon values are fine in both the seeded template and the rendered instance — the iconize hook only strips unresolvable placeholder icon values (e.g. `LiPlaceholder`), not concrete Lucide names or emojis.

After writing the folder-note, author an initial précis one-liner for the category — one sentence drawn from the category's purpose and the description from Step 3 (rendered in the product's `language`) — and write it between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers in the folder-note, replacing the `_TBD` placeholder. Then run `render-container-stats` so the `<!-- spec:stats:* -->` region is populated:

```bash
lazycortex-specs render-container-stats <spec_path>/<name>/<name>.md
```

Outcome: `rendered`.

## Step 8 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.add-asset-category/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.add-asset-category)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the arguments passed). Body: `# spec.add-asset-category` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with a note that review coverage is inherited from the shared behavior-keyed classes — `spec.create-asset` docs under `<spec_path>/<name>/<slug>/` match the right-anchored `design` / `plan` globs (or the product's `<kind>@<key>` override) with no class written here.

## Failure modes

- **`/spec.add-asset-category` refuses naming an unknown product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/spec.product-config`, then re-invoke.
- **`/spec.add-asset-category` refuses because the category already exists** — `<name>` is already a key in the product's `asset_categories` → pick a different name, or edit the existing category's block / folder-note directly.
- **`/spec.add-asset-category` aborts saying an icon is required** — the operator declined every icon option without typing one → re-invoke and supply an iconize name or emoji; the category is not registered without an icon.
