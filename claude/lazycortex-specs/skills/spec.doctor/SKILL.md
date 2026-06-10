---
name: spec.doctor
description: Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or inconsistencies with the actual source code — audits a product's folder tree, status folder-notes (flat gate booleans), per-file stages, source links, and wikilinks, then reports issues grouped by severity and offers targeted fixes. Read-only by default; pass `--apply` to write fixes.
---
# Spec Doctor

Audit a product specification for validity, consistency, and staleness. Reports issues and offers fixes. Naming, folder structure, header section, wikilink format, gate model, per-file stages, and file-role rules are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill enforces them but never inlines the patterns.

`spec.doctor` validates STATE only — frontmatter, body structure, cross-links, and source references. It never changes product config or runs migrations: there are no existing customers and no legacy model to migrate from. It validates the current flat-gate model and ignores any artifact from an older model (legacy product `spec.cfg-<product>.md` files, `## Workflow` sections, `gates:` dicts) rather than detecting or migrating them.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Resolve product`
   - `Step 1 — Dispatch parallel scan agents A/B/C/D`
   - `Step 2 — Cross-reference check (inline)`
   - `Step 3 — Merge findings by severity`
   - `Step 4 — Report`
   - `Step 5 — Fix loop (per-finding AskUserQuestion, apply on --apply)`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `clean`, `no-source-binding`, `skipped-per-user-choice`, `read-only`).
3. **Do not reach the Report step until `TaskList` shows the prior tasks `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per Agent (A/B/C/D) plus Check 0 and Check 8. A missing line is a bug; do not render the report with gaps.

## Input

The user provides the product key (compound `<subsystem>[-<namespace>]-<product>`) or a path under a product's `spec_path`. If omitted, ask which product to check. Can also run on all products: iterate `lazy.settings.json[products]`.

Accepts an optional `--apply` flag. Without it, the skill is **read-only** — it reports findings and stops at the Report step (the fix loop only previews what it would do). With `--apply`, the per-finding fix loop offers to write each fix via `AskUserQuestion`.

## Step 0 — Resolve product (Check 0)

Resolve the product record from `lazy.settings.json[products]` — there is NO `.claude/rules/spec.cfg-<product>.md` product file in this model.

1. Run `lazycortex-specs resolve-product by-key <key>` (or `by-path <path>` when given a path). It prints `{"key": "<product>", "record": <record-or-null>}`.
2. **`record` null** — the product is not registered. Report as an error and stop: "product `<key>` is not in `lazy.settings.json[products]`; register it via `/spec.product-config`." Do NOT proceed.
3. **`record` present** — capture `spec_path` (required, vault-relative), optional `source` (`{ repo, paths }`), optional `language` (default `en`), `icon` (optional), and `asset_categories` (default `{}`).
   - Verify `spec_path` exists as a directory. Missing → error.
   - **Code-bound** (`source` block present) — resolve `source.repo` via the `spec.resolve-repo` primitive to get `{ local_path, branch, host, owner, repo, forge, base_url, … }`. Resolution failure (repo key not registered in `lazy.settings.json[repos]`, missing `local_path`, no git remote, unknown host with no `forge:` override on the repo record) is an error — report the underlying cause. Code-bound products run the full check set (A + B + C + D).
   - **Design-only** (no `source` block) — there is no code to diff. Run structural-only checks: A (link health, minus source-URL host matching), C (role/header), D (status/gates/folders). Skip Agent B (source staleness) entirely with outcome `no-source-binding`.
   - **Repo records** — repos live in the `lazy.settings.json[repos]` section (read via `lazycortex-core settings-get repos`); `spec.resolve-repo` reads them. Verify each referenced repo record's `branch` matches the checkout's actual default branch; a mismatch breaks every source link (error, offer to rewrite in `--apply`).
4. **All products** — iterate every key in `lazy.settings.json[products]` (skip the `_version` schema marker) and run the check set per product.

Outcome: `code-bound` / `design-only` / `unregistered` / `all-products(<N>)`.

## Parallel scanning

For each product checked, dispatch 4 Explore subagents **in a single assistant message with 4 Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). The coordinator pattern, dispatch rules, and structured-report contract (`## scan: …` + `### findings` with `[SEVERITY] title | path:line` + `### summary`) are owned by `lazy-core.parallel-scan.md` (in the `lazycortex-core` plugin) — read it before authoring or modifying agent prompts.

Severity vocabulary: `PASS` / `WARN` / `FAIL`. Budget per agent: "Report under 600 words". Each agent prompt MUST include:

1. The exact scope globs / paths to scan (no broad searches) — scoped to this product's `spec_path`.
2. The relevant per-check rules from the agent slice below — the coordinator copies the right slice into each prompt rather than asking the agent to discover them.
3. The structured-report contract.

The coordinator (the main session) does NOT scan files itself — it dispatches the four agents, awaits their structured reports, merges findings by severity, and drives the interactive fix loop. The cross-reference scan (Check 8) runs inline in the coordinator because it is small and one-shot.

### Agent A — link health

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` (Wikilinks) and `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`.

- **Wikilinks** — extract every `[[wikilink]]` from every `.md` under `<spec_path>`:
  - **Bare wikilink (FAIL)** — any target without a `/`. Role-only basenames collide by design; the path-qualified form is required. Propose `[[<path>|<display>]]`.
  - **Missing display text (WARN)** — a path-qualified wikilink with no `|<display>`.
  - **Broken target (FAIL)** — the target page does not exist in the vault. Report file:line.
- **Source links** (skip for design-only — no `base_url` to match against):
  - Grep every `.md` for markdown links whose host+base matches the resolved repo `base_url` (from `spec.resolve-repo`). Delegate path-scheme matching to the known-forges table — never grep for a literal `/blob/` pattern.
  - For each link in a file allowed to carry source URLs (`tech` and feature/change-level `plan` only), verify: host+base matches `base_url`; the URL is reproducible via `spec.source-url(<repo-key>, <path>, <kind>, branch=<pin-or-default>)`; `<local_path>/<path>` exists locally; no `#L<line>` fragment (forbidden).
  - **Inconsistent path / body-frontmatter pin drift (FAIL)** — a body URL whose branch does not match the file's `source_branches` pin (or the repo default when unpinned).

### Agent B — source staleness (code-bound only; skip for design-only)

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`. Diff the documented surface in the product **tech file** against current source. The design file is NOT checked for staleness — it describes behavior, not code 1:1.

1. Read the product tech file (`<spec_path>/docs/tech.md`) and any feature/change-level `tech.md`; extract documented routes/methods, function/class names, constants and values, and file references.
2. Read the actual source from `<local_path>/<source.paths>`.
3. Report deltas:
   - **Missing from tech (WARN)** — route/function/class in code but not documented.
   - **Removed from code (WARN)** — documented item no longer in source.
   - **Changed values (WARN)** — constants, signatures, or route paths that differ.
   - **New files (WARN)** — source files not referenced anywhere in tech.

### Agent C — role & header violations

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, and `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`.

- **`spec_role` closed set** — every role-bearing spec doc carries `spec_role` in one of the closed set `{design, plan, bug, tech, status}`. Any other value (including the removed `layout`, `human-tasks`, `changelog`, and any `*-index` role) is a FAIL. Operator-zone folder-notes carry NO `spec_role` (validated by Agent D) — finding `spec_role` on a product or category folder-note is a FAIL.
- **Role matches location** — `spec_role` must agree with the file's basename and enclosing folder:
  - `design.md` → `spec_role: design`; `tech.md` → `tech`; `plan.md` → `plan`; `bug.md` → `bug`.
  - The asset status folder-note (`<spec_path>/<category>/<slug>/<slug>.md`, basename matches the parent folder) → `spec_role: status`.
  - Source URLs / `source_branches:` are permitted ONLY on `tech` and feature/change-level `plan` docs. A source URL or `source_branches:` on any other role is a FAIL (propose to move into the tech file / strip the frontmatter).
- **Header section** — every role-bearing authored doc must start with the expected H1 (`# <title> — <role>`) and breadcrumb (`> **<Subsystem>** · **<Product>**[ · **<asset>**] — <role>`) per `spec.layout-protocol.md`. Mismatch is a FAIL — the header is the file's identity under role-only filenames. (The status folder-note carries the `# <slug> — status` H1; it does NOT require the breadcrumb line.)
- **Required sections** — feature/change `design.md` carries a non-empty Requirements/Changes section; `bug.md` carries non-empty `## Repro steps`, `## Observed behavior`, `## Expected behavior`. Missing → FAIL.
- **`spec_stage` closed set + tag mirror** — every authored doc (`design`, `tech`, `plan`, `bug`) carries `spec_stage` in the closed set `{empty, draft, approved, rejected, cancelled}` AND a `spec/<stage>` tag in `tags:` mirroring it in lock-step (per `spec.lifecycle-protocol.md` → status mirror tag; `spec.set-stage` is the only writer of both). FAIL on: missing `spec_stage`; value outside the set (including the removed `review` / `done` / `wtr`); missing/stale/duplicate `spec/*` tag. The fix is `spec.set-stage <doc> <current-stage>` (re-syncs the tag), or `spec.set-stage <doc> draft|approved` to map a removed value.
- **Cancellability** — `spec_stage: cancelled` on `design.md` (feature/change mandatory doc) or `bug.md` (bug mandatory doc) is FAIL, always. `tech.md` / `plan.md` may be `cancelled`.

### Agent D — status folder-notes + gates + per-file stages + folders + intake

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`, `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, and `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md`. The asset enumeration is the product's category set: built-in `{feature, change, bug}` ∪ the keys of `products[<key>].asset_categories`.

**Top-level folders**

- The product's top-level folders MUST be a subset of `{features, changes, bugs, requests}` ∪ `asset_categories` keys. Any other top-level `.md`-bearing folder is an **unknown folder** (FAIL). Each built-in folder (`features`, `changes`, `bugs`, `requests`) is expected to exist — a missing built-in is a WARN (operator may not have used it yet; in `--apply` offer to create).

**Status folder-notes**

- Every asset folder (`<spec_path>/<category>/<slug>/`) contains exactly one status folder-note (basename matches the parent folder). Missing / duplicate / misplaced → FAIL.
- Frontmatter carries `spec_role: status` and the five flat boolean gates plus the overlay: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`, `spec_cancelled`. Each must be present and a boolean. Missing key or non-boolean value → FAIL. A `gates:` dict, a `stage:` key, `awaits_human:`, or a `## Workflow` section on the folder-note are old-model artifacts → FAIL (propose to strip).
- Managed `iconize_icon` (and `iconize_color` when the category config carries a color) — see Icon drift below.
- Body carries `## Gates` and `## History` sections. Missing either → FAIL.

**Linear gate precedence (S0..S5)**

- The five gates are a strict ladder (`spec.lifecycle-protocol.md` → Linear map): each true gate requires every earlier gate true. Order: `spec_design_done` → `spec_plan_done` → `spec_develop_done` → `spec_tests_passing` → `spec_released`. A later gate true while an earlier gate is false is a **precedence violation** (FAIL) — name the offending pair. In `--apply`, offer to turn the orphaned later gate off (the `--off` direction).
- **`spec_cancelled` overlay** — `spec_cancelled: true` freezes the gates (no flips). It is orthogonal to the ladder; a cancelled asset with any gate state is sane (no precedence enforcement while cancelled). `spec_cancelled` must be a boolean.

**Gate ⇔ per-file stage coupling**

- `spec_design_done: true` ⇒ the WTR doc is `approved`: feature/change `design.md.spec_stage == approved`; bug `bug.md.spec_stage == approved`. Mismatch → FAIL.
- `spec_plan_done: true` ⇒ `plan.md.spec_stage ∈ {approved, cancelled}`. Mismatch → FAIL.
- `spec_released: true` ⇒ every authored doc present under the asset is resolved: the mandatory WTR doc (`design.md` for feature/change, `bug.md` for bug) is `approved` (never `cancelled`); the `plan.md` is `approved` or `cancelled`. Any doc still `empty`/`draft`/`rejected` → FAIL. (Assets carry no `tech.md` — only the product `docs/tech.md` does.)
- The per-file `spec_stage` re-validation here repeats Agent C's closed-set check only as needed to evaluate coupling — coupling findings are D's, the closed-set / tag-mirror findings are C's. Do not double-report.

**Per-file stage surfacing**

- Any doc stuck at `spec_stage: rejected` is a WARN in every run — valid state, but signals unfinished review work. Fix: `spec.set-stage <doc> draft` + re-open review (`review_active: true`).

**Operator-zone folder-notes + icon drift**

- The product folder-note (`<spec_path>/<leaf>.md`) and each category folder-note (`<spec_path>/<category>/<category>.md` for built-in `features`/`changes`/`bugs`/`requests` and for every `asset_categories` key) are operator-zone folder-notes: they carry NO `spec_role`, NO `*-index` role, NO dataviewjs. Finding `spec_role` on one → FAIL. Category folder-notes additionally carry a `description` frontmatter key (operator-authored prose; the plugin only reads it) — absent on a category folder-note is a WARN.
- **`iconize_icon` drift (WARN)** — the managed `iconize_icon` on each operator-zone folder-note must match its config source of truth. Resolve the expected value:
  - Product folder-note → `products[<key>].icon` (absent in config ⇒ no `iconize_icon` expected; a stray one is the drift).
  - Category folder-note → `asset_categories[<name>].icon` for operator-defined categories; for built-in categories the default applies unless overridden in `asset_categories`: `features` → `LiRocket`, `changes` → `LiRefreshCcw`, `bugs` → `LiBug`, `requests` → `LiInbox`.
  - The asset status folder-note's `iconize_icon` mirrors the asset's category icon (same resolution as the category folder-note for that category). Drift → WARN.
  - `iconize_color` likewise mirrors the category config `color` when present; a stray `iconize_color` with no configured color, or a mismatch, is a WARN. In `--apply`, offer to rewrite the managed `iconize_*` keys to the config value.

**Request intake**

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.request-protocol.md`. Validate `<spec_path>/requests/` — request files stay there for their entire lifecycle (no `archive/` move).

- Each `requests/<slug>.md` carries `spec_role: request`, `request_status` ∈ `{draft, accepted, rejected}`, `request_class` ∈ the closed-meta ∪ asset-category set, and `created` (ISO date). Missing key / out-of-set value / malformed date → FAIL.
- Active-inbox files (`request_status: draft`) are eligible for routine pick-up; terminal files (`accepted | rejected`) carry a terminal status callout above the title and, for `accepted`, at least one `[[<entity-folder-note>]]` wikilink in the callout body (missing → FAIL).
- **`source_requests` forward link** — every wikilink in a status folder-note's `spec_source_requests` list MUST resolve to an existing request file under `<spec_path>/requests/`. Unresolvable → FAIL. (Forward-only; the reverse link lives in the request's terminal callout body and is not separately enforced.)

## Cross-reference check (Check 8, inline in coordinator)

- Verify the product is referenced in any relevant index pages.
- A loose `<spec_path>/changelog.md` is a FAIL: the role is removed from the model. The fix is to delete the file (its history has migrated into per-doc `## History` H1 sections and the status folder-note `## History` of each asset).

## Output (Report)

Merge the four agents' findings plus Check 0 and Check 8, then print a report grouped by severity. The report MUST contain one line per Agent (A/B/C/D) plus Check 0 and Check 8 — a missing line is a bug.

```
## <Product Name> — Spec Doctor Report

scan: Check 0 resolve-product — <code-bound|design-only|unregistered>
scan: Agent A link-health — <PASS|WARN|FAIL> (<N> findings)
scan: Agent B source-staleness — <PASS|WARN|FAIL|skipped:no-source-binding> (<N> findings)
scan: Agent C role-header — <PASS|WARN|FAIL> (<N> findings)
scan: Agent D status-gates-folders-intake — <PASS|WARN|FAIL> (<N> findings)
scan: Check 8 cross-reference — <PASS|WARN> (<N> findings)

### Errors (must fix)
- [ ] Bare wikilink: `[[design]]` in `features/<feat>/plan.md:<line>` — use `[[<path>|<display>]]`
- [ ] Broken wikilink: `[[<target>]]` in `docs/design.md:<line>`
- [ ] Role violation: source URL in `docs/design.md:<line>` — belongs in `docs/tech.md`
- [ ] Role violation: `source_branches:` frontmatter on `features/<feat>/design.md`
- [ ] Unknown `spec_role`: `<file>` carries `spec_role: <value>` (closed set: design, plan, bug, tech, status)
- [ ] Loose `changelog.md`: `<spec_path>/changelog.md` exists — the role is removed; delete the file
- [ ] Header mismatch: `features/<feat>/design.md` H1/breadcrumb does not match its path + role
- [ ] Invalid `spec_stage`: `<doc>` has `spec_stage: <value>` (closed set: empty, draft, approved, rejected, cancelled)
- [ ] Stage/tag mirror drift: `<doc>` `spec_stage: approved` but `tags:` has `spec/draft`
- [ ] Cancelled WTR doc: `features/<feat>/design.md` is `spec_stage: cancelled` — design may never be cancelled
- [ ] Missing status folder-note: `features/<feat>/` has no folder-note
- [ ] Missing gate boolean: `features/<feat>/<feat>.md` lacks `spec_develop_done`
- [ ] Old-model artifact: `features/<feat>/<feat>.md` carries a `gates:` dict / `stage:` key / `## Workflow` section — strip
- [ ] Gate precedence: `spec_tests_passing: true` but `spec_develop_done: false` (gates are a strict ladder S0..S5)
- [ ] Gate/stage coupling: `spec_design_done: true` but `design.md.spec_stage: draft` (must be approved)
- [ ] Release coupling: `spec_released: true` but `plan.md.spec_stage: draft` (every doc must resolve before release)
- [ ] Missing `## Gates`/`## History`: `features/<feat>/<feat>.md`
- [ ] `spec_role` on operator-zone folder-note: `<spec_path>/features/features.md` carries `spec_role` (must have none)
- [ ] Unknown top-level folder: `<spec_path>/<folder>/` is neither built-in nor a declared asset category
- [ ] Request schema: `requests/<slug>.md` missing/invalid `request_status`/`request_class`/`created`
- [ ] Unresolvable `spec_source_requests`: `<feat>/<feat>.md` lists `<path>` but no request file exists there

### Warnings (should fix)
- [ ] Missing display text: path-qualified wikilink with no `|<display>` in `<file>:<line>`
- [ ] Route `<METHOD> <path>` exists in code but not in `docs/tech.md`
- [ ] Constant `<NAME>` changed: tech file says `<X>`, code says `<Y>`
- [ ] Missing built-in folder: `<spec_path>/changes/` does not exist
- [ ] Missing category description: `<spec_path>/characters/characters.md` has no `description`
- [ ] Icon drift: `<spec_path>/features/features.md` `iconize_icon: <X>` ≠ config default `LiRocket`
- [ ] Rejected doc: `features/<feat>/design.md` is `spec_stage: rejected` (unfinished review)

### Info
- N source files, M routes, K assets documented
- All header sections consistent
- All wikilinks resolve
- All gates precedence-consistent
```

## Fix loop

After the report, in **read-only mode (no `--apply`)** stop here — the report is the deliverable. State clearly that no files were changed and that re-running with `--apply` enables fixes.

In **`--apply` mode**, walk the errors and warnings and, **per finding**, call `AskUserQuestion` (one question per fix) before writing. State the exact file, the specific issue, and what the fix concretely does. Typical fixes:

- Rewrite a bare wikilink to path-qualified form.
- Strip a forbidden source URL / `source_branches:` from a role that may not carry it (move the URL into the tech file when the user confirms).
- Re-sync a `spec/<stage>` tag to its `spec_stage` value (delegate to `spec.set-stage <doc> <current-stage>` — never raw-edit the tag).
- Turn off a precedence-orphaned gate (`spec.flip-gate <asset> <gate> --off`).
- Add a missing gate boolean / `## Gates` / `## History` to a status folder-note.
- Rewrite a drifted `iconize_icon` / `iconize_color` to the config value.
- Create a missing built-in folder.
- Add missing routes/functions or update changed values in the tech file.

Never auto-fix without the per-finding confirmation. **Never** change product config in `lazy.settings.json`, run any migration, or touch a doc's content beyond the specific approved fix.

When `--apply` writes fixes, the audit trail is the per-doc `## History` entries written by the canonical writers it delegates to (`spec.set-stage`, `spec.flip-gate`) plus this skill's own run log under `.logs/claude/spec.doctor/`. There is no product-wide changelog to update.

## Key rules

- **Read-only by default** — report first; fix only under `--apply` and only with per-finding approval.
- **No migration, ever** — there are no existing customers; doctor validates the current flat-gate model and ignores old-model artifacts rather than detecting or migrating them. Never add a "stale spec.cfg / suggest migration" check.
- **Never remove spec content** — flag items that may be stale; let the user decide.
- **Concrete line references** — every finding points to the exact file and line/section.
- **Delegate heavy reads to the four parallel Explore agents** — the coordinator only resolves the product, runs the small cross-reference check inline, merges findings, and drives the fix loop.
- **Gates are flat booleans on a strict ladder** — `spec_design_done` → `spec_plan_done` → `spec_develop_done` → `spec_tests_passing` → `spec_released`, plus the `spec_cancelled` overlay. There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, no `## Workflow`. A later gate true while an earlier is false is a hard error.
- **Closed `spec_role` set** — design, plan, bug, tech, status. No `layout`, no `human-tasks`, no `changelog`, no `*-index`. Operator-zone folder-notes (product + category) carry NO `spec_role`.
- **Closed `spec_stage` set** — empty, draft, approved, rejected, cancelled, mirrored by a `spec/<stage>` tag in lock-step. `spec.set-stage` is the only writer of both.
- **Top-level folders** — built-in `{features, changes, bugs, requests}` ∪ the product's `asset_categories` keys; anything else is an unknown-folder error.
- **`iconize_*` is config-derived** — managed icon/color on every folder-note must match `products[<key>].icon` (product), `asset_categories[<name>].icon` (category), or the built-in default (feature→LiRocket / change→LiRefreshCcw / bug→LiBug / requests→LiInbox); drift is a warning.
- **Naming, folder structure, header section, wikilink format, gates, per-file stages, and request schema** are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill enforces but never inlines them.

## Logging

Per `lazy-log.logging`, write a run log to `./.logs/claude/spec.doctor/YYYY-MM-DD_HH-MM-SS.md`: `mkdir -p` then the `Write` tool (never chain). Frontmatter `git_sha` / `git_branch` / `date` / `input`; body `## Actions` (products checked, findings by severity, fixes applied in `--apply`) and `## Result`.
