---
name: lazy-spec.add-asset-type
description: "Use when a product must grow a new kind of asset beyond the shipped feature / change / bug / content / research set — characters, scenes, chapters, endpoints, whatever the operator names — or when `lazy-spec.request-classify` has no type to route a request into. Writes the type declaration into `products[<key>].asset_types.<name>` and settles the playbook the coordinator will work assets of that type under; review coverage is automatic, so it never touches `review.classes`."
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, AskUserQuestion, Agent
---
# Add Asset Type

Declare one asset type on a product and wire it into the system end to end. Resolves the product from `lazy.settings.json[products][<key>]`, collects the type's identity through a one-question-at-a-time wizard, writes the declaration into the product's `asset_types`, and settles the playbook the coordinator loads whenever it works an asset of that type. Review coverage is automatic: the shared behavior-keyed review classes (`design` / `code-plan` / `test-plan`, written by `lazy-spec.product-config` Step 10 with right-anchored `*/<doc>.md` globs — or a product's `<kind>@<key>` override) already span every asset folder, so this skill writes NO review classes and syncs NO routine globs. Asset types are an open set — a type declared here is recognised by `lazy-spec.request-classify`, `lazy-spec.create-asset`, the coordinator, and the review daemon on their next run, with no rubric, class, or code edit.

The type's per-block config is `{ "icon": <icon>, "color"?: <hex>, "playbook": <ref>, "alias_of"?: <base>, "default_path"?: <dir>, "start_doc": "<file>:<doc_type>", "default_tools"?: [<tool>, ...] }` under `products[<key>].asset_types.<name>`. A product's declarations merge key-by-key over the plugin's shipped ones (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json`), so a product may replace a single field of a shipped type without restating the rest. The type's human explanation does NOT live in config — it is the playbook's own opening chapter (Step 8).

**No folder is created on disk.** The type's folder appears lazily, the first time `lazy-spec.create-asset` scaffolds an asset into it; a type nobody has used yet is a declaration and nothing more.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Ask the type name`
   - `Step 3 — Ask the icon + color`
   - `Step 4 — Ask the start document`
   - `Step 5 — Ask the default tools`
   - `Step 6 — Ask the default path`
   - `Step 7 — Write the type block`
   - `Step 8 — Choose the type playbook`
   - `Step 9 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product> [<type-name>]`.

1. **`<product>`** — the product compound-key (e.g. `server-tester-chapter`).
2. **`<type-name>`** (optional) — the type's key, lowercase-with-hyphens. When passed, Step 2's name question is skipped (outcome `taken-from-arg`); when absent, Step 2 asks for it.

## Wizard contract

Every `AskUserQuestion` this skill issues is a single question (one question per call, wait for the answer, then ask the next) preceded by a context block the agent prints to the operator — where (this skill, the step, the field under `products[<key>].asset_types.<name>`), found (what Step 1 resolved and what earlier steps captured), why asking (the one reason the field is not derivable), answers (what each option writes, and that it is never re-asked) — then the call with a self-contained `question` naming the product and type, a short `header`, and a `description` per option. Per-option copy keeps the concrete example and tradeoff from the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`; the `See:` pointer closes the context block. Never ask a bare one-line question.

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

Otherwise ask for the type's key:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 2 — Ask the type name; target products[<product>].asset_types
- Found: no <type-name> argument; the product already declares <its own asset_types keys, or "none"> over the shipped feature / change / bug / content / research
- Why asking: the name is the stable identity of the type — written into every instance's `spec_asset_type` and into `products[<key>].asset_types.<name>`; `lazy-spec.create-asset <product> <name> <slug>` scaffolds by it, `lazy-spec.request-classify` routes by it, the coordinator resolves the asset's law through it; renaming later means rewriting `spec_asset_type` on every instance
- Answers: `<example>` (e.g. `characters`, `scenes`, `chapters`) — that key is declared in Step 7, never re-asked; `other (type your own)` — a key matching `^[a-z][a-z0-9-]*$`; a regex failure or a collision re-asks. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`
AskUserQuestion: header "Type name", question "What is the key of the new asset type on product <product>?", options: the example labels plus `other (type your own)`, each with a description.
```

Then ask whether the type is standalone or an alias:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 2 — Ask the type name; target products[<product>].asset_types.<name>.alias_of
- Found: legal bases in scope — the shipped feature / change / bug / content / research plus <every product-declared type that carries no alias_of>; aliases never chain
- Why asking: an alias borrows exactly ONE thing from its base — the base's playbook, and only when the alias declares no `playbook` of its own; folder, icon, colour, start document and default tools stay the alias's own. This decides whether the type gets a law of its own to maintain (Step 8) or rides the base's
- Answers: `standalone (own playbook)` — no `alias_of` written, Step 8 asks for the playbook; `<base>` — Step 7 writes `alias_of: <base>` and Step 8 is skipped (`skipped-alias`). Never re-asked
AskUserQuestion: header "Alias or standalone", question "Is `<name>` on <product> a standalone type with its own playbook, or an alias of an existing type?", options: `standalone (own playbook)` first, then one per legal base, each with a description.
```

Capture `<alias-base>` when an alias is chosen.

Outcome: `named` or `taken-from-arg` (append `alias-of-<base>` when an alias base was captured).

## Step 3 — Ask the icon + color

Ask for the required icon:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 3 — Ask the icon + color; target products[<product>].asset_types.<name>.icon
- Found: no icon on record for `<name>`; <when an alias: base <alias-base> paints <base-icon>, which is NOT inherited>
- Why asking: the icon is how the operator tells assets of this type apart in the file explorer — `lazy-spec.create-asset` injects it into every instance's status folder-note as `iconize_icon` and iconize paints it on the folder; an alias never inherits its base's paint, and a type without an icon is incomplete
- Answers: `<suggestion>` (a Lucide name like `LiUsers`, or a literal emoji) — written to the declaration in Step 7, never re-asked; `other (type your own)` — an iconize identifier; declining every option with no value aborts the run (`missing-icon`), nothing written. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`
AskUserQuestion: header "Icon", question "Which iconize icon should assets of type `<name>` on <product> carry?", options: a few concrete suggestions plus `other (type your own)`, each with a description.
```

**The skill MUST refuse to finish if no icon is provided** — if the operator declines every option and gives no value, abort with a message stating an icon is required and do NOT write anything.

Then ask for the optional color:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 3 — Ask the icon + color; target products[<product>].asset_types.<name>.color
- Found: icon <icon> just chosen; no color on record
- Why asking: purely cosmetic — a hex tints the icon through each instance's managed `iconize_color`; omitted, the icon keeps the default color
- Answers: `<hex>` (e.g. `#7E57C2`) — written as `color` in Step 7; `none (skip color)` — key omitted; `other (type your own)` — a hex value. Never re-asked
AskUserQuestion: header "Icon color", question "Tint the `<name>` icon on <product> with a hex color, or keep the default?", options: a couple of example hex values, `none (skip color)`, `other (type your own)`, each with a description.
```

Capture `<color>` only when a real hex is given; treat "none" as absent.

Outcome: `iconed` (or abort `missing-icon` — never write).

## Step 4 — Ask the start document

Ask for the document an asset of this type starts from:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 4 — Ask the start document; target products[<product>].asset_types.<name>.start_doc
- Found: doc types declared in scope — the shipped set in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.doc-types.json` plus <the product's own doc_types, or "none">
- Why asking: there is NO default layout anywhere in the system — a type with no `start_doc` cannot be scaffolded at all; `lazy-spec.create-asset` passes the `"<file>:<doc_type>"` token straight through as the first `--doc` of the scaffold call, and the doc type decides which review class picks the document up and which stages it moves through
- Answers: `design.md:design` — the type is defined by a design (the common case); `bug.md:bug` — defined by a report of something wrong; `other (type your own)` — any `<file>.md:<doc_type>` pair with exactly one `:` and a declared doc type on the right; an unresolvable token re-asks. Written in Step 7, never re-asked. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`
AskUserQuestion: header "Start document", question "Which document does an asset of type `<name>` on <product> start from?", options `design.md:design`, `bug.md:bug`, `other (type your own)`, each with a description.
```

Validate the typed value: exactly one `:`, a `.md` filename on the left, and a doc type on the right that is declared in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.doc-types.json` or in the product's own `doc_types` — re-ask on failure rather than writing an unresolvable token.

Outcome: `start-doc-set`.

## Step 5 — Ask the default tools

Ask (multi-select) for the tools an asset of this type implies before anyone has judged it:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 5 — Ask the default tools; target products[<product>].asset_types.<name>.default_tools
- Found: tools visible in scope — the shipped code / data / test / docs plus <the product's own tool_types, or "none">; each names a `tool_types` declaration whose playbook governs how that half of the work is done and reported
- Why asking: the list is written into a fresh asset's `spec_tools` at scaffold time, and the three states are genuinely different — a non-empty list means "known from creation, no determination step"; an EMPTY list means "definitely none, this type builds nothing itself"; the key ABSENT means "not determined yet, the coordinator settles it after the design is approved"
- Answers: `<tool>` (one per visible tool, multi-select) — written as `default_tools: [...]` in Step 7; `none — the coordinator determines the tools` — key left absent; `none — this type never builds anything` — writes `[]`. Never re-asked. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.tool-types.json`
AskUserQuestion (multiSelect): header "Default tools", question "Which tools does every asset of type `<name>` on <product> imply at creation?", options: one per tool with a one-line description of what it covers, plus the two explicit `none` options with descriptions.
```

Outcome: `tools-preset:<N>`, `tools-empty`, or `tools-undetermined`.

## Step 6 — Ask the default path

Ask for the folder new assets of this type land in:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 6 — Ask the default path; target products[<product>].asset_types.<name>.default_path
- Found: folders the product's declared types already use — <type: default_path, …>
- Why asking: the folder is a convenience for whoever creates the asset, NOT a fact of the type — type resolution reads `spec_asset_type` off the status folder-note and never a path, so an operator may put any single asset anywhere under `spec_path` (including inside another asset's folder) with `--path`, and nothing downstream breaks
- Answers: `<plural of name>` (e.g. `characters` for `character`) — written as `default_path` in Step 7; `<folder of an existing type>` — new assets share that folder; `other (type your own)` — any folder under `spec_path`; `none — use the type's own name` — key omitted, the scaffold falls back to `<name>`. Never re-asked. See: `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`
AskUserQuestion: header "Default folder", question "Under which folder of <product>'s spec_path should new `<name>` assets land when the caller names none?", options: the pluralised type name first, a sibling-of-an-existing-type folder drawn from the product's declared types, `other (type your own)`, `none — use the type's own name`, each with a description.
```

Capture `<default_path>` only when the operator names a folder; treat "none" as absent (the scaffold then falls back to the type's own name).

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

Otherwise ask for the playbook:

```
Context (print before asking):
- Where: /lazy-spec.add-asset-type · Step 8 — Choose the type playbook; target products[<product>].asset_types.<name>.playbook
- Found: Step 7 wrote the declaration without `playbook`; `<name>` is standalone (no alias_of), start doc <file>:<doc_type>, tools <preset | empty | undetermined>
- Why asking: the playbook is the type's law — what `spec.coordinator` loads on every wake of an asset carrying `spec_asset_type: <name>`; without it the type is inert, and no shipped flow can be assumed to fit
- Answers: a shipped reference — written verbatim as `playbook` (`shipped`); `own playbook (I will write it)` — a stub lands at `.claude/references/<name>-playbook.md` and its bare name is written (`stub-written`). Never re-asked
AskUserQuestion: header "Type playbook", question "Which playbook should spec.coordinator work `<name>` assets on <product> under?", options: the shipped type playbooks plus the own-playbook path, each with the description below.
```

- **`lazycortex-specs:lazy-spec.feature-playbook`** — a capability defined design-first, with an architecture step inserted when the asset bears code and the tool set determined once the design is approved.
- **`lazycortex-specs:lazy-spec.change-playbook`** — a modification of assets that already exist, defined as current-state versus target-state, whose approved design cascades into the assets it targets.
- **`lazycortex-specs:lazy-spec.bug-playbook`** — a defect whose report IS its definition: no architecture step, and the tools follow from where the defect actually lives.
- **`lazycortex-specs:lazy-spec.content-playbook`** — one unit of content described by a single design document, tools preset to `data` at creation, no planning step.
- **`lazycortex-specs:lazy-spec.research-playbook`** — an asset whose deliverable is the answer itself: a research design approved, then the research tool's report accepted; it closes on an answer, not on shipped code.
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
