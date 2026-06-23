---
name: spec.create-asset
description: Universal asset-creation skill — scaffolds one asset folder (`<spec_path>/<category>/<slug>/`) under a registered product for any asset category (built-in feature / change / bug, or an operator-defined category from the product's `asset_categories`), asks category-scaled clarifying questions, authors the docs in the product's language, and draws the primary behavioral diagram(s). The three built-in `spec.create-feature` / `spec.create-change` / `spec.create-bug` skills are thin wrappers that pin `<category>` and delegate here.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Create Asset

Scaffold and author one asset under a registered product. Resolves the product from `lazy.settings.json[products][<key>]`, validates the requested category against the built-in set plus the product's operator-defined `asset_categories`, scaffolds the asset folder with its status folder-note and authored docs, applies per-file start stages, authors the prose in the product's language, and draws the primary behavioral diagram(s) for the layout. Invoke when a user wants to add a new feature / change / bug — or any operator-defined asset category — to a product that already has a spec.

Folder layout, filenames, status-file shape, and wikilink format are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those patterns.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Use these canonical titles verbatim:
   - `Step 1 — Resolve the product`
   - `Step 2 — Validate the category`
   - `Step 3 — Ask clarifying questions`
   - `Step 4 — Resolve the layout + icon`
   - `Step 5 — Scaffold the asset folder`
   - `Step 6 — Author the asset précis`
   - `Step 7 — Author the prose`
   - `Step 8 — Draw the behavioral diagram(s)`
   - `Step 9 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`skipped-empty-mode`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product> <category> <slug> [--empty]`.

1. **`<product>`** — the product compound-key (e.g. `dashboards`, `server-tester-chapter`).
2. **`<category>`** — the asset category: built-in `feature` / `change` / `bug`, or an operator-defined key declared in the product's `asset_categories` (e.g. `characters`, `scenes`).
3. **`<slug>`** — the asset slug, lowercase-with-hyphens. The skill does NOT infer it — the caller passes it.
4. **`--empty`** (optional) — scaffold-only mode. Produces the folder-note plus empty-stage authored docs, with no clarifying questions, no prose, and no diagrams. Used by the request system's spawn path (`spec.request-spawn`), which populates the bodies afterward via `spec.request-attach`.

## --empty mode (skip-pattern)

When invoked with `--empty`:

- Skip Step 3 (no clarifying questions) — emit outcome `skipped-empty-mode`.
- Step 4 still resolves the layout + icon (the scaffold needs both).
- Step 5 (scaffold) runs as usual; authored docs keep their templates' default `spec_stage: empty` for `plan.md`, and the design/bug doc is set to `draft` via `spec.set-stage` as in normal mode — see Step 5 note.
- Skip Step 6 (no précis) — emit outcome `skipped-empty-mode`.
- Skip Step 7 (no prose) — emit outcome `skipped-empty-mode`.
- Skip Step 8 (no diagrams) — emit outcome `skipped-empty-mode`.

`--empty` mode is silent on stdout (no `AskUserQuestion`). The audit trail for empty-mode scaffolds lives in the originating request file's body until the asset's docs are filled and reviewed; no separate changelog entry is needed.

## Step 1 — Resolve the product

Resolve the product record by reading `.claude/lazy.settings.json` directly via the `Read` tool (the repo root is `git rev-parse --show-toplevel` of the current working directory). Look up `products[<product>]`.

The record (when present) carries `spec_path` (required, vault-relative), optional `source`, optional `language` (defaults to `en`), and optional `asset_categories: {<name>: {icon: ..., color?: ...}}`.

- If the key is absent or its value is null → the product is not registered. Refuse with a message naming `<product>` and suggesting `/spec.product-config` to register it. Do NOT proceed.
- Otherwise capture `spec_path`, `language` (default `en` when absent), and `asset_categories` (default `{}` when absent).

This skill MUST NOT invoke `lazycortex-specs resolve-product` via `Bash` for this resolution: apply-context experts run under Claude Code's `dontAsk` permission mode which silently denies arbitrary plugin-CLI invocations and would force the agent into a partial improv path. A direct `Read` of `.claude/lazy.settings.json` is the contract here. The CLI subcommand remains valid for direct shell use; the skill just no longer depends on it.

All narrative prose this skill authors (doc bodies, diagram request prose) is rendered in the product's `language`. Frontmatter keys/values, fixed section headers (`## Summary`, `## Repro steps`, …), wikilinks, and code/URLs stay English. The effective language for any authored doc is the resolved product's `language` field; no separate per-doc resolution step is required.

## Step 2 — Validate the category

- **Built-in** (`feature` / `change` / `bug`) — always accepted.
- **Anything else** — MUST appear as a key in the resolved product's `asset_categories`. If it does not, refuse with a message naming `<category>` and the product, and suggest `/spec.add-asset-category` to declare it on the product. Do NOT proceed.

Record the validated category for use by later steps. Outcome word: `built-in` or `operator-defined`.

## Step 3 — Ask clarifying questions

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise ask 2–5 targeted questions via `AskUserQuestion` — ONE question at a time. Author every question as a full-context block per the wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` → Wizard-question explanation standard (stem + why-it-matters + per-option copy + reference pointer). Never ask yes/no questions; offer concrete options with tradeoffs.

Scale the topics to the category:

- **`feature`** — scope (in/out), users (who triggers it, how), edge-case behavior the user likely hasn't considered.
- **`change`** — what it was → what it becomes, migration / compatibility from current behavior.
- **`bug`** — repro steps, observed-vs-expected, environment (platform / version / data state).
- **operator-defined** — whatever the category's `design.md` should capture; ground the questions in the prose sections that doc will hold.

## Step 4 — Resolve the layout + icon

**Layout** — choose the authored-doc set from the category:

- **built-in `bug`** — `bug.md` (from `spec.bug/bug.md`, start stage `draft`) + `plan.md` (from `spec.bug/plan.md`, start stage `empty`). NO `design.md`.
- **everything else** (`feature` / `change` / any operator-defined) — `design.md` (from `spec.<category>/design.md`, start stage `draft`) + `plan.md` (from `spec.<category>/plan.md`, start stage `empty`). The per-category template folder is `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/`; operator-defined categories must have a folder seeded by `/spec.add-asset-category`.

There is NO per-asset `tech.md` (removed — only the product carries `tech.md` at its root) and NO `layout` doc/role (removed).

**Icon** — resolve the iconize icon to inject into the status folder-note frontmatter (Step 5):

- **operator-defined category** — `asset_categories[<category>].icon`. If the category config also carries a `color`, capture it for `iconize_color`.
- **built-in category** — the built-in default when `asset_categories[<category>].icon` is absent: `feature` → `LiRocket`, `change` → `LiRefreshCcw`, `bug` → `LiBug`. (A built-in category MAY still be overridden in `asset_categories` — prefer the configured `icon`/`color` when present.)

The status template ships WITHOUT `iconize_icon` / `iconize_color` lines (a dev-vault hook strips placeholder icon values), so this skill INJECTS them.

## Step 5 — Scaffold the asset folder

Invoke the deterministic scaffold primitive via `Bash`:

```
Bash(lazycortex-specs scaffold-asset <product> <category> <slug>)
```

The primitive (`claude/lazycortex-specs/bin/scaffold_asset.py`) owns the mechanical scaffold work — template resolution (3-layer fallback: per-product override → project-wide override → plugin baseline), token substitution (`{{product}}`, `{{slug}}`, `{{subsystem}}`, `{{product_tag}}`, `iconize_icon`, `iconize_color`), file writes (folder-note + authored docs per category layout), per-file stage seeding, and folder-note `# History` line stamping (one line per doc transition). It refuses if the target folder already exists; the operator must pick a unique slug.

On success the primitive prints a JSON object to stdout:

```json
{
  "outcome": "success",
  "folder": "specs/<spec_path>/<category-folder>/<slug>",
  "folder_note": "specs/<spec_path>/<category-folder>/<slug>/<slug>.md",
  "docs": [{"file": "...design.md", "stage": "draft"}, {"file": "...plan.md", "stage": "empty"}],
  "history_lines": 3
}
```

The `folder` and `folder_note` fields are **repo-root-relative** (they include the vault-root prefix, e.g. `specs/`). Consumers that need to open a file use `<repo-root>/<folder>`; wikilinks remain content-root-relative (omit the vault-root prefix).

On `outcome: error` (logical failure — folder exists, unknown product, missing template, etc.) propagate the JSON to the caller and abort; do NOT improvise the scaffold inline. Emit outcome word: `scaffolded:<N>` where N is the doc count, or `refused:<error.category>`.

After this step, the folder exists with template-substituted content, `spec_source_docs` defaults populated, `# Sources / ## Docs` projection rendered, and per-file stages matching the template defaults (`design.md` / `bug.md` → `draft`, `plan.md` → `empty`). The folder-note's `# History` section carries one scaffold line + one line per authored doc's stage transition.

## Step 6 — Author the asset précis

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise author the asset's `# Summary` précis: 1–2 phrases capturing the feature / change / bug essence drawn from the clarification answers (Step 3) and the doc just scaffolded. Write the précis between the `<!-- spec:precis:start -->` and `<!-- spec:precis:end -->` markers in the asset's `<slug>.md` folder-note (the `folder_note` path from the scaffold's JSON output), replacing the `_TBD` placeholder. The `# Summary` section in the folder-note is protected (`#protected/spec/summary`) — edit ONLY the précis text inside the markers; do not touch the `<!-- spec:stats:* -->` markers or the operator-zone body below the section.

Commit the updated folder-note atomically (`git add <folder_note> && git commit -m "docs(<slug>): author précis"`).

Outcome: `precis-authored` or `skipped-empty-mode`.

## Step 7 — Author the prose

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise author the authored-doc bodies in the product's language (Step 1), drawing on the Step 3 clarification:

- **default layout** — rewrite `design.md`'s sections with real content from the clarification. `design.md` describes WHAT, never HOW: no source URLs, repo file paths, or class/function names. The section list is owned by `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/design.md` — replace its placeholder prose, do not append. Author a user-flow / behavior section that the Step 7 diagram can anchor under.
- **`bug` layout** — fill `bug.md`'s sections (`## Summary`, `## Repro steps`, `## Observed behavior`, `## Expected behavior`, `## Environment`, `## Related code / logs`) from the repro / observed-vs-expected / environment answers. Keep the frontmatter and header exactly as the scaffold wrote them.

`plan.md` stays a placeholder — an external planning tool fills it during planning. Do not populate it here.

## Step 8 — Draw the behavioral diagram(s)

Skip entirely under `--empty` (outcome `skipped-empty-mode`).

Otherwise draw only diagrams that have a real home in the authored doc — invoke `lazycortex-diagram:lazy-diagram.draw` via the `Skill` tool, once per diagram, passing `target_file`, `anchor_section` (an existing `##` heading in the doc), `kind`, `format="mermaid"`, and a `request=` one-sentence summary followed by `facts:` naming the actors / steps / decision points the host section's prose just established (terminology parity with the host section is the only contract). The drawer's return value (`created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`) IS this step's outcome word.

Diagram set by layout:

- **default layout** — one `flow` diagram under `design.md`'s user-flow / behavior section.
- **`bug` layout** — one `flow` under `## Repro steps` + one `sequence` under `## Observed behavior`.

This is a deliberate reduction. The obsolete fixed five-seam list (architecture / erd / state-or-flow / layout across a per-asset `design.md`+`tech.md`) no longer applies now that per-asset `tech.md` and the `layout` role are gone. Draw ONLY diagrams with a real anchor section in `design.md` / `bug.md`; never invent a section to host a diagram.

## Step 9 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.create-asset/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.create-asset)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC), `input` (the arguments passed). Body: `# spec.create-asset` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list with its outcome word — a missing line is a bug.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/spec.create-asset` refuses naming an unknown product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/spec.product-config`, then re-invoke.
- **`/spec.create-asset` refuses naming an unknown category** — `<category>` is neither built-in nor declared in the product's `asset_categories` → declare it via `/spec.add-asset-category`, then re-invoke.
