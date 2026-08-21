---
name: lazy-spec.create-asset
description: "Use when the user asks to add a new feature, change, bug — or any operator-declared asset type such as characters / scenes / chapters — to a product that already has a spec. The built-in `lazy-spec.create-feature` / `lazy-spec.create-change` / `lazy-spec.create-bug` skills only pin the type and delegate here; invoke this one directly for every other type."
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# Create Asset

Scaffold and author one asset under a registered product. Resolves the product from `lazy.settings.json[products][<key>]`, validates the requested asset type against the shipped declarations plus the product's own `asset_types`, resolves the document the type starts from and the folder the asset lands in, scaffolds the asset folder with its status folder-note and seeded docs, applies per-file start stages, and authors the prose in the product's language. It draws no diagrams — the operator asks for one via `/lazy-diagram.draw`, and the writing experts carry their own figures discipline (`lazy-core.markdown-style`). Invoke when a user wants to add a new feature / change / bug — or any operator-declared asset type — to a product that already has a spec.

Folder layout, filenames, status-file shape, and wikilink format are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those patterns.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Validate the asset type`
   - `Step 3 — Ask clarifying questions`
   - `Step 4 — Resolve the start doc + icon`
   - `Step 5 — Scaffold the asset folder`
   - `Step 6 — Author the asset précis`
   - `Step 7 — Author the prose`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`skipped-empty-mode`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product> <asset-type> <slug> [--empty]`.

1. **`<product>`** — the product compound-key (e.g. `dashboards`, `server-tester-chapter`).
2. **`<asset-type>`** — the asset type: one of the plugin's shipped declarations (`feature` / `change` / `bug` / `content` / `research`), or a key the product declares under `asset_types` (e.g. `characters`, `scenes`).
3. **`<slug>`** — the asset slug, lowercase-with-hyphens. The skill does NOT infer it — the caller passes it.
4. **`--empty`** (optional) — scaffold-only mode. Produces the folder-note plus empty-stage authored docs, with no clarifying questions and no prose. Used by the request system's spawn path — `lazy-spec.request-apply` (`${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`) invokes the equivalent `scaffold-asset` CLI primitive directly, then seeds the router's per-target description onto the primary doc afterward (`lazy-spec.request-protocol.md` § Body distribution rules).

## --empty mode (skip-pattern)

When invoked with `--empty`:

- Step 2 validates the type as usual but asks nothing — its location question is skipped and the folder falls back to the type's `default_path` (outcome suffix `path-defaulted`).
- Skip Step 3 (no clarifying questions) — emit outcome `skipped-empty-mode`.
- Step 4 still resolves the start doc + icon (the scaffold needs both), and never widens the document set beyond the type's `start_doc`.
- Step 5 (scaffold) runs as usual; the seeded doc is set to `draft` via `lazy-spec.set-stage` as in normal mode — see Step 5 note. The scaffold seeds ONLY the type's start doc; every further document is opt-in and is never created here (see Step 4).
- Skip Step 6 (no précis) — emit outcome `skipped-empty-mode`.
- Skip Step 7 (no prose) — emit outcome `skipped-empty-mode`.


`--empty` mode is silent on stdout (no `AskUserQuestion`). The audit trail for empty-mode scaffolds lives in the originating request file's body until the asset's docs are filled and reviewed; no separate changelog entry is needed.

## Step 1 — Resolve the product

Resolve the product record by reading `.claude/lazy.settings.json` directly via the `Read` tool (the repo root is `git rev-parse --show-toplevel` of the current working directory). Look up `products[<product>]`.

The record (when present) carries `spec_path` (required, vault-relative), optional `source`, optional `language` (defaults to `en`), and optional `asset_types: {<name>: {icon, color?, playbook, alias_of?, default_path?, start_doc, default_tools?}}`.

- If the key is absent or its value is null → the product is not registered. Refuse with a message naming `<product>` and suggesting `/lazy-spec.product-config` to register it. Do NOT proceed.
- Otherwise capture `spec_path`, `language` (default `en` when absent), and `asset_types` (default `{}` when absent — the product's own declarations merge key-by-key over the plugin's shipped ones at `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json`).

This skill MUST NOT invoke `lazycortex-specs resolve-product` via `Bash` for this resolution: apply-context experts run under Claude Code's `dontAsk` permission mode which silently denies arbitrary plugin-CLI invocations and would force the agent into a partial improv path. A direct `Read` of `.claude/lazy.settings.json` is the contract here. The CLI subcommand remains valid for direct shell use; the skill just no longer depends on it.

All narrative prose this skill authors (doc bodies) is rendered in the product's `language`. Frontmatter keys/values, fixed section headers (`## Overview`, `## Way to reproduce`, …), wikilinks, and code/URLs stay English. The effective language for any authored doc is the resolved product's `language` field; no separate per-doc resolution step is required.

## Step 2 — Validate the asset type

- **Shipped** — the type appears in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json`. Always accepted.
- **Anything else** — MUST appear as a key in the resolved product's `asset_types`. If it does not, refuse with a message naming `<asset-type>` and the product, and suggest `/lazy-spec.add-asset-type` to declare it on the product. Do NOT proceed.

Then settle **where the asset lands**. The type's `default_path` is the default and needs no question when the caller named no folder; the operator may put the asset at ANY path under the product's `spec_path`, including a folder inside another asset — a nested asset is an ordinary asset, and its boundary is its own folder-note carrying `spec_role: status`, never its depth. Location is a placement decision, not a fact of the type: type resolution reads `spec_asset_type` off the note and never the path, so nothing downstream breaks when an asset sits somewhere unusual. Ask via `AskUserQuestion` (offering the `default_path` folder first, then a path the operator types) only when the caller passed no explicit folder AND the request itself suggests the asset belongs next to something else; otherwise take `default_path` silently. Under `--empty` never ask — take `default_path`.

Record the validated type and the resolved folder for use by later steps. Outcome word: `shipped` or `product-declared`, with suffix `path-default` or `path-chosen`.

## Step 3 — Ask clarifying questions

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise ask 2–5 targeted questions via `AskUserQuestion` — ONE question at a time. Author every question as a full-context block per the wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` → Wizard-question explanation standard (stem + why-it-matters + per-option copy + reference pointer). Never ask yes/no questions; offer concrete options with tradeoffs.

Scale the topics to the asset type:

- **`feature`** — scope (in/out), users (who triggers it, how), edge-case behavior the user likely hasn't considered.
- **`change`** — what it was → what it becomes, migration / compatibility from current behavior; also ask, as a separate targeted question, which existing asset(s) this change modifies — offer the product's existing `feature` (and other-type) assets as options, multi-select, explicitly optional (a cross-cutting or infrastructure-only change may name none). The answer becomes `spec_targets` (Step 5 note) — the design cascade in `lazy-spec.lifecycle-protocol.md` Part 4 folds this change's approved design into each named target's own `design.md` / `test-plan.md` once the change's own design is approved.
- **`bug`** — repro steps, observed-vs-expected, environment (platform / version / data state).
- **any other declared type** — whatever the type's start doc should capture; ground the questions in the prose sections that document will hold, per the type's own playbook.

## Step 4 — Resolve the start doc + icon

**Start doc** — the document set comes from the type's declaration, never from a table in this skill. The declaration's `start_doc` is a `"<file>:<doc_type>"` token (e.g. `design.md:design`, `bug.md:bug`); that ONE document is what the scaffold seeds. There is no default layout to fall back on: a type declaring no `start_doc` is a broken declaration, and this skill refuses rather than guessing a filename.

**Widening the set is the playbook's call, not this skill's.** When the operator asks for more than the start doc, `Read` the reference named by the declaration's `playbook` (resolving one `alias_of` hop when the type declares none of its own) and take the additional documents — and their `spec_doc_type` values — from the type playbook's definition-documents chapter. A declaration carrying neither `playbook` nor `alias_of` is refused: the coordinator would have no law to work the asset under, so creating it would strand it. Refuse with a message naming the type and pointing at `/lazy-spec.add-asset-type` to complete the declaration.

Every document not named by `start_doc` or by the type playbook stays opt-in and is never created here — plan and report documents are authored later, by the tool the coordinator dispatches, once there is work to plan or journal.

There is NO per-asset `tech.md` (removed — only the product carries `tech.md` at its root) and NO `layout` doc/role (removed).

**Icon** — resolve the iconize icon to inject into the status folder-note frontmatter (Step 5) from the same declaration: `asset_types[<asset-type>].icon`, with `color` captured for `iconize_color` when the declaration carries one. An alias borrows only its base's playbook — its icon, colour, folder, start doc and tools stay its own — so never read paint through `alias_of`. A type whose merged declaration names no icon is a broken declaration: refuse, do not invent one.

The status template ships WITHOUT `iconize_icon` / `iconize_color` lines (a dev-vault hook strips placeholder icon values), so this skill INJECTS them.

## Step 5 — Scaffold the asset folder

Invoke the deterministic scaffold primitive via `Bash`:

```
Bash(lazycortex-specs scaffold-asset <product> <asset-type> <slug> --doc <name>:<spec_doc_type> [--doc ...] [--path <dir>])
```

Pass one `--doc` per document Step 4 resolved — the type's `start_doc` first, then anything the type playbook added. **At least one `--doc` is mandatory**: the primitive has no default layout and a call carrying none is a logical refusal, not an empty scaffold. Pass `--path <dir>` only when Step 2 settled on a folder other than the type's `default_path`; omit it to take the default.

The primitive (`claude/lazycortex-specs/bin/scaffold_asset.py`) owns the mechanical scaffold work — template resolution (5-layer fallback: the type's own per-product override → its project-wide override → its plugin baseline → the linear per-doc-type base → the type-agnostic base; an alias type's own chain outranks its base type's in full), token substitution (`{{product}}`, `{{slug}}`, `{{product_tag}}`, `iconize_icon`, `iconize_color`), file writes (folder-note + the named documents), per-file stage seeding, folder-note `# History` line stamping (one line per doc transition), and lazy group-folder seeding — the first asset landing in a group folder seeds its operator-zone group folder-note (icon from the type whose `default_path` names that folder; an ad-hoc folder no declaration names gets a note without iconize keys). It refuses if the target folder already exists; the operator must pick a unique slug.

On success the primitive prints a JSON object to stdout:

```json
{
  "outcome": "success",
  "folder": "specs/<spec_path>/<asset-folder>/<slug>",
  "folder_note": "specs/<spec_path>/<asset-folder>/<slug>/<slug>.md",
  "docs": [{"file": "...design.md", "stage": "draft"}],
  "history_lines": 3,
  "group_note": "specs/<spec_path>/<asset-folder>/<asset-folder>.md"
}
```

The `folder`, `folder_note`, and `group_note` fields are **repo-root-relative** (they include the vault-root prefix, e.g. `specs/`). `group_note` is an empty string when nothing was seeded (the group note already existed, the asset nested inside another asset, or it landed at the product root); when non-empty, the caller MUST fold the path into its commit pathspec — a seeded note left untracked halts the runtime daemon's clean-tree check. Consumers that need to open a file use `<repo-root>/<folder>`; wikilinks remain content-root-relative (omit the vault-root prefix).

On `outcome: error` (logical failure — folder exists, unknown product, missing template, etc.) propagate the JSON to the caller and abort; do NOT improvise the scaffold inline. Emit outcome word: `scaffolded:<N>` where N is the doc count, or `refused:<error.category>`.

After this step, the folder exists with template-substituted content, `spec_source_docs` defaults populated, `# Sources / ## Docs` projection rendered, and each seeded doc's stage matching its own doc type's default. The folder-note's `# History` section carries one scaffold line + one line per doc stage transition.

**`change` type, targets named in Step 3.** When Step 3's clarification named one or more existing assets this change modifies, write `spec_targets: ["<folder>/<slug>", ...]` into the freshly-scaffolded folder-note's frontmatter — tokens relative to the product's `spec_path`, one per named target, in the order the operator picked them. No targets named → leave the key absent entirely (an absent `spec_targets` is a normal state for a cross-cutting or infrastructure-only change, not a gap). This is the same frontmatter key `lazy-spec.lifecycle-protocol.md` Part 4's design cascade reads once the change's own `spec_design_done` flips true.

**This skill never writes `spec_depends_on`.** Unlike `spec_targets` above, the dependency graph (`lazy-spec.coordination-playbook.md` § 8) is coordinator-written ONLY — via `note-set-key`, either materializing an architect's `[!asset-proposal]` child (Chapter 10) or an operator-driven edit routed through the coordinator. No wizard step here asks for dependencies; a freshly-scaffolded asset always starts with the key absent.

## Step 6 — Author the asset précis

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise author the asset's `# Summary` précis: 1–2 phrases capturing the feature / change / bug essence drawn from the clarification answers (Step 3) and the doc just scaffolded. Write the précis between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers in the asset's `<slug>.md` folder-note (the `folder_note` path from the scaffold's JSON output), replacing the `_TBD` placeholder. The `# Summary` section in the folder-note is protected (`#protected/spec/summary`) — edit ONLY the précis text inside the markers; do not touch the `<!-- spec:stats:* -->` markers or the operator-zone body below the section.

Commit the updated folder-note by naming it in the commit pathspec (`git commit -m "docs(<slug>): author précis" -- <folder_note>`), appending `<group_note>` whenever the scaffold's JSON reported a non-empty one — a freshly seeded group note left out of the pathspec stays untracked and halts the runtime daemon's clean-tree check. No `git add` — the pathspec carries the worktree content directly, per `lazy-core.git`'s pathspec discipline, and leaves the operator's index untouched.

Outcome: `precis-authored` or `skipped-empty-mode`.

## Step 7 — Author the prose

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise author the authored-doc bodies in the product's language (Step 1), drawing on the Step 3 clarification:

One prose pass per document the scaffold actually seeded, driven by that document's own `spec_doc_type` — never by the asset type. Replace each section's placeholder prose in place, never add or drop sections; the section list belongs to the template the scaffold resolved, and the frontmatter and header stay exactly as the scaffold wrote them.

- **`design`** — rewrite `design.md`'s sections with real content from the clarification. `design.md` describes WHAT, never HOW: no source URLs, repo file paths, or class/function names. It describes the **intended** behavior, not the current code's: existing gaps, half-built paths, or "not yet supported" branches are never written in as limitations, and only an explicit operator decision from the Step 3 clarification — never the state of the code — narrows scope. "It does not do that yet" is a question for the operator, not a fact for the spec.
- **`bug`** — fill `bug.md`'s sections (`## Overview`, `## Way to reproduce`, `## Observed behavior`, `## Expected behavior`, `## Environment`, `## Related code / logs`) from the repro / observed-vs-expected / environment answers.
- **any other seeded doc type** — author it per the sections its own template carries, grounded in the Step 3 clarification and in what the type playbook says that document is for.

This skill never authors plan or report documents — they are not part of the scaffold (Step 4/5) and stay out of scope here too.

## Step 8 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.create-asset/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.create-asset)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the arguments passed). Body: `# lazy-spec.create-asset` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/lazy-spec.create-asset` refuses naming an unknown product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/lazy-spec.product-config`, then re-invoke.
- **`/lazy-spec.create-asset` refuses naming an unknown asset type** — `<asset-type>` is neither shipped nor declared in the product's `asset_types` → declare it via `/lazy-spec.add-asset-type`, then re-invoke.
- **`/lazy-spec.create-asset` refuses saying the type has no playbook** — the declaration carries neither `playbook` nor `alias_of`, so the coordinator would have no law to work the asset under → complete the declaration via `/lazy-spec.add-asset-type`, then re-invoke.
- **`/lazy-spec.create-asset` refuses saying the type declares no start document** — the declaration has no `start_doc` token, and there is no default layout to fall back on → add `start_doc` via `/lazy-spec.add-asset-type`, then re-invoke.
