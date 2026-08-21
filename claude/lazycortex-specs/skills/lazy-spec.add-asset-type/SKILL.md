---
name: lazy-spec.add-asset-type
description: "Use when a product must grow a new kind of asset beyond the shipped feature / change / bug / content / research set — characters, scenes, chapters, endpoints, whatever the operator names — or when `lazy-spec.request-classify` has no type to route a request into. Writes the type declaration into `products[<key>].asset_types.<name>` and settles the playbook the coordinator will work assets of that type under; review coverage is automatic, so it never touches `review.classes`."
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# Add Asset Type

Declare one asset type on a product and wire it into the system end to end. Resolves the product from `lazy.settings.json[products][<key>]`, collects the type's identity through a one-question-at-a-time wizard, writes the declaration into the product's `asset_types`, and settles the playbook the coordinator loads whenever it works an asset of that type. Review coverage is automatic: the shared behavior-keyed review classes (`design` / `code-plan` / `test-plan`, written by `lazy-spec.product-config` Step 10 with right-anchored `*/<doc>.md` globs — or a product's `<kind>@<key>` override) already span every asset folder, so this skill writes NO review classes and syncs NO routine globs. Asset types are an open set — a type declared here is recognised by `lazy-spec.request-classify`, `lazy-spec.create-asset`, the coordinator, and the review daemon on their next run, with no rubric, class, or code edit.

The type's per-block config is `{ "icon": <icon>, "color"?: <hex>, "playbook": <ref>, "alias_of"?: <base>, "default_path"?: <dir>, "start_doc": "<file>:<doc_type>", "default_tools"?: [<tool>, ...] }` under `products[<key>].asset_types.<name>`. A product's declarations merge key-by-key over the plugin's shipped ones (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json`), so a product may replace a single field of a shipped type without restating the rest. The type's human explanation does NOT live in config — it is the playbook's own opening chapter (Step 8).

**No folder is created on disk.** The type's folder appears lazily, the first time `lazy-spec.create-asset` scaffolds an asset into it; a type nobody has used yet is a declaration and nothing more.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Ask the type name`
   - `Step 3 — Ask the icon + color`
   - `Step 4 — Ask the start document`
   - `Step 5 — Ask the default tools`
   - `Step 6 — Ask the default path`
   - `Step 7 — Write the type block`
   - `Step 8 — Choose the type playbook`
   - `Step 9 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product> [<type-name>]`.

1. **`<product>`** — the product compound-key (e.g. `server-tester-chapter`).
2. **`<type-name>`** (optional) — the type's key, lowercase-with-hyphens. When passed, Step 2's name question is skipped (outcome `taken-from-arg`); when absent, Step 2 asks for it.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) authored as a full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` — stem (name the field, what it controls, where it takes effect) + why-it-matters + per-option copy with a concrete example + a trailing `See:` reference pointer. Never ask a bare one-line question.

## Step 1 — Resolve the product

Resolve the product record:

```bash
lazycortex-specs resolve-product by-key <product>
```

The command prints `{"key": "<product>", "record": <record-or-null>}` with `spec_path` (required, vault-relative), optional `language` (defaults to `en`), and optional `asset_types` / `tool_types`.

- If `record` is `null` → the product is not registered. Refuse with a message naming `<product>` and suggesting `/lazy-spec.product-config` to register it. Do NOT proceed.
- Otherwise capture `spec_path`, `language` (default `en` when absent), the visible `asset_types` keys (the product's own merged over the shipped set), and the visible `tool_types` keys (needed by Step 5).

All narrative prose this skill authors (the playbook stub of Step 8) is rendered in the product's `language`. Frontmatter keys, fixed headers, wikilinks, and settings JSON stay English.

Outcome: `resolved`.

## Step 2 — Ask the type name

If `<type-name>` was passed as an argument, validate it against `^[a-z][a-z0-9-]*$`, confirm it is not already a key in the product's own `asset_types` (refuse and stop if it is — suggest editing the existing declaration instead), and skip the question (outcome `taken-from-arg`). A name that collides with a SHIPPED type is not a refusal — it is a per-field override of that type for this product, and the wizard says so plainly before continuing.

Otherwise `AskUserQuestion` for the type's key. Stem: the name is the value written into every instance's `spec_asset_type` frontmatter key AND the key written into `products[<key>].asset_types.<name>`; `lazy-spec.create-asset <product> <name> <slug>` scaffolds instances of it, `lazy-spec.request-classify` recognises it as a request class, and the coordinator resolves an asset's law through it. Why-it-matters: the name is the stable identity of the type across config, notes, and dependency tokens — renaming later means rewriting `spec_asset_type` on every instance. Offer concrete example labels (e.g. `characters`, `scenes`, `chapters`) plus an "other (type your own)" path; validate the chosen string against `^[a-z][a-z0-9-]*$` and re-ask on failure or collision. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`.

Then `AskUserQuestion` whether the type is standalone or an alias. Stem: an alias type (`asset_types.<name>.alias_of: <base>`) borrows exactly ONE thing from the base — the base's playbook, and only when it declares no `playbook` of its own; its folder, icon, colour, start document and default tools stay entirely its own, so an alias is a full type that happens to be coordinated like its base. Why-it-matters: this decides whether the type gets a law of its own to maintain (Step 8) or rides the base's. Offer "standalone (own playbook)" as the first option, then each legal base: the shipped types (`feature` / `change` / `bug` / `content` / `research`) and every already-declared type that does NOT itself carry `alias_of` — aliases never chain. Capture `<alias-base>` when an alias is chosen.

Outcome: `named` or `taken-from-arg` (append `alias-of-<base>` when an alias base was captured).

## Step 3 — Ask the icon + color

`AskUserQuestion` for the required icon. Stem: the icon is the iconize identifier (a Lucide name like `LiUsers`, or a literal emoji) written into `products[<key>].asset_types.<name>.icon`; `lazy-spec.create-asset` injects it into every instance's status folder-note as `iconize_icon`, and the Obsidian iconize system paints it on the asset folder. Why-it-matters: the icon is how the operator visually distinguishes assets of this type in the file explorer, and an alias never inherits its base's paint — a type without an icon is incomplete. Offer a few concrete suggestions plus an "other (type your own)" path. **The skill MUST refuse to finish if no icon is provided** — if the operator declines every option and gives no value, abort with a message stating an icon is required and do NOT write anything. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`.

Then `AskUserQuestion` for the optional color. Stem: an optional hex color (e.g. `#7E57C2`) written into `asset_types.<name>.color` and mirrored into each instance's managed `iconize_color`; it tints the icon. Why-it-matters: purely cosmetic — omit it to inherit the default icon color. Offer a couple of example hex values plus "none (skip color)" and an "other (type your own)" path. Capture `<color>` only when a real hex is given; treat "none" as absent.

Outcome: `iconed` (or abort `missing-icon` — never write).

## Step 4 — Ask the start document

`AskUserQuestion` for the document an asset of this type starts from. Stem: `asset_types.<name>.start_doc` is a `"<file>:<doc_type>"` token — the filename the scaffold seeds and the `spec_doc_type` that document carries; `lazy-spec.create-asset` passes it straight through as the first `--doc` of the scaffold call, and the type playbook decides whether anything else is authored alongside it. Why-it-matters: there is NO default layout anywhere in the system — a type with no `start_doc` cannot be scaffolded at all, and the doc type decides which review class picks the document up and which stages it moves through. Offer `design.md:design` (the type is defined by a design, the common case), `bug.md:bug` (the type is defined by a report of something wrong), and an "other (type your own)" path for any other pair. Validate the typed value: exactly one `:`, a `.md` filename on the left, and a doc type on the right that is declared in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.doc-types.json` or in the product's own `doc_types` — re-ask on failure rather than writing an unresolvable token. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`.

Outcome: `start-doc-set`.

## Step 5 — Ask the default tools

`AskUserQuestion` (multi-select) for the tools an asset of this type implies before anyone has judged it. Stem: `asset_types.<name>.default_tools` is the list written into a fresh asset's `spec_tools` frontmatter key at scaffold time; each tool names a `tool_types` declaration whose playbook governs how that half of the work is done and reported. Why-it-matters: the three states are genuinely different — a non-empty list means "known from creation, no determination step"; an EMPTY list means "definitely none, this type builds nothing itself"; the key ABSENT means "not determined yet, the coordinator settles it after the design is approved". Offer one option per tool visible in scope (the shipped `code` / `data` / `test` / `docs` plus anything the product declares under `tool_types`, each with a one-line description of what it covers), plus an explicit "none — the coordinator determines the tools" option that leaves the key absent, and an explicit "none — this type never builds anything" option that writes an empty list. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.tool-types.json`.

Outcome: `tools-preset:<N>`, `tools-empty`, or `tools-undetermined`.

## Step 6 — Ask the default path

`AskUserQuestion` for the folder new assets of this type land in. Stem: `asset_types.<name>.default_path` is the folder under the product's `spec_path` that `lazy-spec.create-asset` scaffolds into when the caller names no folder of its own. Why-it-matters: it is a convenience for whoever creates the asset, NOT a fact of the type — type resolution reads `spec_asset_type` off the status folder-note and never a path, so an operator may put any single asset anywhere under `spec_path` (including inside another asset's folder) with `--path`, and nothing downstream breaks. Offer the pluralised form of the type name as the first option (e.g. `characters` for `character`), a sibling-of-an-existing-type option drawn from the product's already-declared types, and an "other (type your own)" path plus "none — use the type's own name". Capture `<default_path>` only when the operator names a folder; treat "none" as absent (the scaffold then falls back to the type's own name). See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`.

Outcome: `path-set` or `path-defaulted`.

## Step 7 — Write the type block

Each settings mutation is an atomic read-modify-write. Read the current products section, edit the in-memory object, write it back:

```bash
lazycortex-core settings-get products
```

In the parsed object, set `products[<key>].asset_types.<name>` to `{ "icon": <icon>, "start_doc": "<file>:<doc_type>" }` — and add, ONLY when the corresponding step captured a value: `"color": <color>` (Step 3), `"alias_of": <alias-base>` (Step 2), `"default_tools": [...]` (Step 5 — write `[]` for the explicit "never builds anything" answer, omit the key entirely for "the coordinator determines"), `"default_path": <dir>` (Step 6). **Do NOT write `playbook` here** — Step 8 appends it with a second read-modify-write of its own, so a run that aborts between the two leaves a declaration the coordinator reports rather than a wrong law it obeys. Preserve every other product, every other type under this product, and every other field on this product's record. Create the `asset_types` map if the product has none yet. Then write the whole products object back via stdin:

```bash
printf '%s' '<edited-products-json>' | lazycortex-core settings-set products
```

`settings-set` performs the atomic write. Do NOT touch any other settings section in this step.

Outcome: `registered`.

## Step 8 — Choose the type playbook

The playbook is the type's law: the reference `spec.coordinator` loads on every wake of an asset carrying this `spec_asset_type`, describing what defines an asset of the type, how its tool set is determined, which gates close the definition half, and which checkboxes hang before work starts. It is the one field without which the type is inert.

**Alias branch.** When Step 2 captured an alias base, SKIP this step entirely: the alias borrows the base's playbook by construction, and writing a `playbook` of its own would defeat the borrowing the operator just chose. Outcome `skipped-alias`.

Otherwise `AskUserQuestion` for the playbook, offering the shipped type playbooks plus an own-playbook path:

- **`lazycortex-specs:lazy-spec.feature-playbook`** — a capability defined design-first, with an architecture step inserted when the asset bears code and the tool set determined once the design is approved.
- **`lazycortex-specs:lazy-spec.change-playbook`** — a modification of assets that already exist, defined as current-state versus target-state, whose approved design cascades into the assets it targets.
- **`lazycortex-specs:lazy-spec.bug-playbook`** — a defect whose report IS its definition: no architecture step, and the tools follow from where the defect actually lives.
- **`lazycortex-specs:lazy-spec.content-playbook`** — one unit of content described by a single design document, tools preset to `data` at creation, no planning step.
- **`lazycortex-specs:lazy-spec.research-playbook`** — an asset whose deliverable is the decision itself; it closes on an answer, not on shipped code.
- **own playbook (I will write it)** — the type's flow matches none of the above closely enough to borrow.

**Shipped-playbook branch.** Take the chosen reference verbatim as `<playbook-ref>`. Outcome sub-tag `shipped`.

**Own-playbook branch.** The reference is the bare name `<name>-playbook` (bare names resolve against the consumer's own `.claude/references/`). Write the stub at `.claude/references/<name>-playbook.md` — `Bash(mkdir -p .claude/references)` then the `Write` tool, never chained. The stub carries `description:` frontmatter naming it as the type playbook for `<name>`, an H1 title, one sentence stating that this file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: <name>`, and these six H2 headings, each holding a one-line `<!-- TBD: … -->` placeholder until the operator fills it (headings in English, placeholder prose in the product's `language`):

- `## What this type is` — what an asset of this type covers, and what it is not.
- `## The definition documents` — which documents define the asset beyond the `start_doc`, and what each is for.
- `## Tool determination` — how and when the asset's `spec_tools` list is settled.
- `## The gates of the definition half` — what closes `spec_design_done` and `spec_plan_done` for this type.
- `## The checkboxes of the definition half` — which launch checkboxes hang on the folder-note before work starts, and what each dispatches.
- `## Typical judgments` — the calls the coordinator makes on this type without asking, and the ones it must ask about.

State in the stub, above the headings, that until a heading is filled the coordinator raises a `[!question]` on the asset rather than guessing the missing rule. Outcome sub-tag `stub-written`.

**Append the field.** Whichever branch ran, write `playbook: <playbook-ref>` into `products[<key>].asset_types.<name>` with the same atomic read-modify-write as Step 7 (`settings-get products` → edit → `settings-set products`), preserving every field Step 7 already wrote.

Outcome: `playbook-set` (carrying the `shipped` / `stub-written` sub-tag) or `skipped-alias`.

## Step 9 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.add-asset-type/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.add-asset-type)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the arguments passed). Body: `# lazy-spec.add-asset-type` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. End with two notes: review coverage is inherited from the shared behavior-keyed classes — documents `lazy-spec.create-asset` seeds under `<spec_path>/<default_path>/<slug>/` match the right-anchored `design` / `code-plan` / `test-plan` globs (or the product's `<kind>@<key>` override) with no class written here; and the type's folder does not exist yet — it is created by the first `lazy-spec.create-asset` call against this type.

## Failure modes

- **`/lazy-spec.add-asset-type` refuses naming an unknown product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/lazy-spec.product-config`, then re-invoke.
- **`/lazy-spec.add-asset-type` refuses because the type already exists** — `<name>` is already a key in the product's own `asset_types` → pick a different name, or edit the existing declaration directly.
- **`/lazy-spec.add-asset-type` aborts saying an icon is required** — the operator declined every icon option without typing one → re-invoke and supply an iconize name or emoji; the type is not declared without an icon.
- **`/lazy-spec.add-asset-type` re-asks the start document** — the typed token is not `<file>.md:<doc_type>`, or the doc type is declared nowhere → supply a declared doc type, or declare it first under the product's `doc_types`.
- **The coordinator raises a `[!question]` saying the type has no playbook** — the declaration carries neither `playbook` nor `alias_of`, usually because a run aborted between Step 7 and Step 8 → re-invoke this skill on the same type to append the missing field; the coordinator picks it up on the asset's next wake.
