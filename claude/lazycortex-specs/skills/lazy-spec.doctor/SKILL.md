---
name: lazy-spec.doctor
description: Use when checking a product spec for staleness, broken links, missing sections, role/header violations, or inconsistencies with the actual source code — audits a product's folder tree, status folder-notes (flat gate booleans), per-file stages, source links, and wikilinks, then reports issues grouped by severity and offers targeted fixes. Read-only by default; pass `--apply` to write fixes.
---
# Spec Doctor

Audit a product specification for validity, consistency, and staleness. Reports issues and offers fixes. Naming, folder structure, header section, wikilink format, gate model, per-file stages, and file-role rules are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill enforces them but never inlines the patterns.

`lazy-spec.doctor` validates STATE only — frontmatter, body structure, cross-links, and source references. It never changes product config or runs migrations: there are no existing customers and no legacy model to migrate from. It validates the current flat-gate model and ignores any artifact from an older model (legacy product `spec.cfg-<product>.md` files, `## Workflow` sections, `gates:` dicts) rather than detecting or migrating them.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Resolve product`
   - `Step 1 — Dispatch parallel scan agents A/B/C/D`
   - `Step 2 — Cross-reference + upstream + wiki-companion checks (inline)`
   - `Step 3 — Merge findings by severity`
   - `Step 4 — Report`
   - `Step 5 — Fix loop (per-finding AskUserQuestion, apply on --apply)`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `clean`, `no-source-binding`, `skipped-per-user-choice`, `read-only`).
3. **Do not reach the Report step until `TaskList` shows the prior tasks `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per Agent (A/B/C/D) plus Check 0, Check 8, Check 9, and Check 10. A missing line is a bug; do not render the report with gaps.

## Input

The user provides the product key (the operator-chosen `products` key) or a path under a product's `spec_path`. If omitted, ask which product to check. Can also run on all products: iterate `lazy.settings.json[products]`.

Accepts an optional `--apply` flag. Without it, the skill is **read-only** — it reports findings and stops at the Report step (the fix loop only previews what it would do). With `--apply`, the per-finding fix loop offers to write each fix via `AskUserQuestion`.

## Step 0 — Resolve product (Check 0)

Resolve the product record from `lazy.settings.json[products]` — there is NO `.claude/rules/spec.cfg-<product>.md` product file in this model.

1. Run `lazycortex-specs resolve-product by-key <key>` (or `by-path <path>` when given a path). It prints `{"key": "<product>", "record": <record-or-null>}`.
2. **`record` null** — the product is not registered. Report as an error and stop: "product `<key>` is not in `lazy.settings.json[products]`; register it via `/lazy-spec.product-config`." Do NOT proceed.
3. **`record` present** — capture `spec_path` (required, vault-relative), optional `source` (`{ repo, paths }`), optional `language` (default `en`), `icon` (optional), and the two declaration blocks `asset_types` / `tool_types` (default `{}` each — the product's own declarations merge key-by-key over the plugin's shipped ones at `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json` and `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.tool-types.json`). The merged pair is what every type / tool check below resolves against; carry it into the Agent C and Agent D prompts.
   - Verify `spec_path` exists as a directory. Missing → error.
   - Verify the product folder leaf (basename of `spec_path`) is not a reserved name (`design`, `tech`, or `decisions`): such a slug makes the product folder-note (`<leaf>.md`) collide with the product-level `design.md` / `tech.md` / `decisions.md` at the root (FAIL, per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` Part 3). No auto-fix — the operator must rename the product.
   - **Code-bound** (`source` block present) — resolve `source.repo` via the `lazy-spec.resolve-repo` primitive to get `{ local_path, branch, host, owner, repo, forge, base_url, … }`. Resolution failure (repo key not registered in `lazy.settings.json[repos]`, missing `local_path`, no git remote, unknown host with no `forge:` override on the repo record) is an error — report the underlying cause. Code-bound products run the full check set (A + B + C + D).
   - **Design-only** (no `source` block) — there is no code to diff. Run structural-only checks: A (link health, minus source-URL host matching), C (role/header), D (status/gates/folders). Skip Agent B (source staleness) entirely with outcome `no-source-binding`.
   - **Repo records** — repos live in the `lazy.settings.json[repos]` section (read via `lazycortex-core settings-get repos`); `lazy-spec.resolve-repo` reads them. Verify each referenced repo record's `branch` matches the checkout's actual default branch; a mismatch breaks every source link (error, offer to rewrite in `--apply`).
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

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` (Wikilinks) and `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`.

- **Wikilinks** — extract every `[[wikilink]]` from every `.md` under `<spec_path>`:
  - **Bare wikilink (FAIL)** — any target without a `/`. Role-only basenames collide by design; the path-qualified form is required. Propose `[[<path>|<display>]]`.
  - **Missing display text (WARN)** — a path-qualified wikilink with no `|<display>`.
  - **Broken target (FAIL)** — the target page does not exist in the vault. Report file:line.
- **Source links** (skip for design-only — no `base_url` to match against):
  - Grep every `.md` for markdown links whose host+base matches the resolved repo `base_url` (from `lazy-spec.resolve-repo`). Delegate path-scheme matching to the known-forges table — never grep for a literal `/blob/` pattern.
  - For each link in a file allowed to carry source URLs (`tech`, `code-plan`, and `test-plan` only), verify: host+base matches `base_url`; the URL is reproducible via `lazy-spec.source-url(<repo-key>, <path>, <kind>, branch=<pin-or-default>)`; `<local_path>/<path>` exists locally; no `#L<line>` fragment (forbidden).
  - **Inconsistent path / body-frontmatter pin drift (FAIL)** — a body URL whose branch does not match the file's `source_branches` pin (or the repo default when unpinned).
- **Decisions-registry links** — for every `decisions.md` under `<spec_path>`:
  - **Broken decision anchor (FAIL)** — a wikilink target `<path>/decisions#D-NNN — <thesis>` whose target file carries no `## D-NNN — …` heading matching that number. Covers both a stale `Origin` back-link and a stray reference-link left by a hand-edited living doc.
  - **`superseded-by` to a nonexistent record (FAIL)** — a `Status: superseded-by [[<path>/decisions#D-NNN — …|D-NNN]]` line whose target number does not exist in the named file.
  - **`active` record with a dangling `Origin` (WARN)** — a `Status: active` record whose `Origin` names a living doc that itself carries no reference-link back to that record's `D-NNN`. Only records whose `Origin` is a living doc are checked — a manual record (`Origin: —`) has nothing to link back to. This check and Agent D's un-promoted-block check read the same document from opposite sides: this one checks the registry (does the reference resolve), Agent D checks the document (did every block actually leave the body once it reached `approved`) — they are not duplicate reports.
- **Code decision links** (skip for design-only — no `source` to grep; language-agnostic, plain grep, not Python-only):
  - Grep every file under `<local_path>/<source.paths>` (the product's resolved code tree, per `lazy-spec.config-protocol`) for the pattern `Decision:.*#D-\d{3,}`. A bare `D-NNN` token with no path is not a link — ignore it.
  - Each qualified token's path is the asset/product folder path from the vault content root (no `/decisions` segment); resolve it to `<content-root>/<path>/decisions.md` and look for a `## D-NNN — …` heading matching the number, same resolution rule as the spec-side registry links above.
  - **Unresolvable code decision link (FAIL)** — the token's `decisions.md` does not exist, or exists but carries no `## D-NNN` heading matching that number. Report the code file:line that carries the comment — code claims a decision that does not exist.
  - **Rescinded code decision link (WARN)** — the token resolves to a record whose `Status:` reads `superseded-by …` or `obsolete …` — code claims a rescinded decision.

### Agent B — source staleness (code-bound only; skip for design-only)

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`. Diff the documented surface in the product **tech file** against current source. The design file is NOT checked for staleness — it describes behavior, not code 1:1.

1. Read the product tech file (`<spec_path>/tech.md`) and any asset-level `tech.md`; extract documented routes/methods, function/class names, constants and values, and file references.
2. Read the actual source from `<local_path>/<source.paths>`.
3. Report deltas:
   - **Missing from tech (WARN)** — route/function/class in code but not documented.
   - **Removed from code (WARN)** — documented item no longer in source.
   - **Changed values (WARN)** — constants, signatures, or route paths that differ.
   - **New files (WARN)** — source files not referenced anywhere in tech.

### Agent C — role & header violations

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, and `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`.

- **`spec_role` closed set** — every role-bearing spec doc carries `spec_role` in one of the closed set `{design, architecture, code-plan, test-plan, code-report, test-report, bug, tech, status, decisions}`. Any other value (including the removed `layout`, `human-tasks`, `changelog`, `plan`, and any `*-index` role) is a FAIL. Operator-zone folder-notes carry NO `spec_role` (validated by Agent D) — finding `spec_role` on a product or container folder-note is a FAIL.
- **`spec_doc_type` present (FAIL)** — every authored catalog document carries `spec_doc_type`. Absence is a FAIL; the fix is `lazycortex-specs doc-type backfill`. The status folder-note (`spec_role: status`) and operator-zone folder-notes are excluded — they have no type and must not have one, so a `spec_doc_type` key found on any of them is itself a FAIL.
- **`spec_doc_type` declared (FAIL)** — the value resolves through `lazycortex-specs doc-type resolve <type> --product <key>`. A non-zero exit is a FAIL: ``type `<type>` is declared nowhere``. The fix is to declare the type under `products[<key>].doc_types` in `.claude/lazy.settings.json`, or to correct the value.
- **Type/role agreement (WARN)** — while `spec_role` still lives alongside `spec_doc_type`, a document carrying non-empty values for both must have them equal. A divergence is a WARN, not a FAIL: the type is authoritative and the role is the legacy key, so the role is what gets corrected.
- **Location constraints** — the basename of an authored document is FREE: `races.md` carrying `spec_doc_type: design` is legal and is never a finding. So is the FOLDER an asset sits in — no rule here reads a folder name. Only these placement rules survive:
  - An `architecture` document is legal exactly where the owning asset's type playbook (`asset_types.<type>.playbook`) provides for one. Presence under an asset whose type playbook describes no architecture step → FAIL, naming the doc and the playbook. The symmetric direction — the type playbook names an architecture step and the asset carries no such document — is judged only against the asset's gate state (§ Gate/stage coupling below), never as a standalone finding: an asset that has not reached that step yet has nothing missing.
  - The asset status folder-note (basename matches its own folder) → `spec_role: status`. That note is what makes the folder an asset; nothing else does.
  - `decisions.md` lives ONLY at the product root (`<spec_path>/decisions.md`) or directly under an asset folder (beside that folder's status note) — never anywhere else. Opt-in and lazily created by the `decide` primitive — absence is never a finding on its own.
  - Source URLs / `source_branches:` are permitted ONLY on documents of type `tech`, `code-plan`, and `test-plan`. A source URL or `source_branches:` on any other type (including `code-report` / `test-report` / `decisions`) is a FAIL (propose to move into the tech file / strip the frontmatter).
- **Header section** — every role-bearing authored doc must start with the expected H1 (`# <title> — <role>`) per `lazy-spec.layout-protocol.md`; a leftover breadcrumb line (`> **…** · **…** — <role>`) is a finding too — that form is removed. Mismatch is a FAIL — the header is the file's identity under role-only filenames. (The status folder-note carries NO `# <slug> — status` title H1; that form is removed.)
- **Status note protected sections** — the status folder-note (the note whose basename matches its own folder and whose frontmatter carries `spec_role: status`) MUST carry six plugin-owned H1 sections, each tagged as its first content line: `# Summary` (`#protected/spec/summary`), `# Gates` (`#protected/spec/gates`), `# Status brief` (`#protected/spec/status-brief`), `# Coordinator rules` (`#protected/spec/coordinator-rules`), `# Coordinator commands` (`#protected/spec/coordinator-commands`), and `# History` (`#protected/spec/history`). A missing section or a duplicate → FAIL. These tags are the ownership markers; no other H1 in the status note may carry a `#protected/spec/*` tag. `# Coordinator rules` and `# Coordinator commands` are owned by the `spec` plugin domain like every other protected section here (the protected-sections contract behind those tags binds other PLUGINS to preserve them byte-for-byte, never the operator) — but the plugin's own writer inside that domain differs per section: the operator writes `# Coordinator rules` by hand, and `spec.coordinator` locks progress marks into `# Coordinator commands` and clears it on completion. This agent checks `# Summary`, `# Gates`, and `# History` directly (above); `# Status brief`, `# Coordinator rules`, and `# Coordinator commands` — the three markers `note-check` validates — are checked by Agent D via `note-check` below rather than re-derived here.
- **Required sections** — keyed on the document's TYPE, never on the folder it sits in: a `design` document carries a non-empty Requirements/Changes section; a `bug` document carries non-empty `## Way to reproduce`, `## Observed behavior`, `## Expected behavior`; a present `architecture` document carries non-empty `## Overview` and `## Module boundaries` sections, mirroring the `design` type's own requirement — an architecture doc that exists but is still template placeholder prose is a doc that never should have promoted past `draft`. Missing/empty → FAIL.
- **`spec_stage` closed set + tag mirror** — which documents carry a stage is decided by the `stages` flag of their type's declaration, never by a list of names here. Four FAILs:
  - the type carries `stages: true` and the document has no `spec_stage` — FAIL;
  - the type carries `stages: false` and the document has a `spec_stage` — FAIL (the shipped `code-report` / `test-report` / `data-report` / `docs-report` / `decisions` are the standing instances of this, not the rule itself);
  - the value falls outside the closed set `{empty, draft, approved, rejected, cancelled}` (including the removed `review` / `done` / `wtr`) — FAIL;
  - the **tag mirror is broken** — the `spec/<stage>` entry in `tags:` must track `spec_stage` in lock-step (per `lazy-spec.lifecycle-protocol.md` → status mirror tag; `lazy-spec.set-stage` is the only writer of both); a missing, stale, or duplicated `spec/*` tag is a FAIL.
  - the **attachment mirror is broken** — a markdown attachment (`spec_owner_doc` present) whose `spec_stage` differs from its owner's, while the attachment does NOT carry `review_active: true`, is a FAIL: the key is a derived mirror (`lazy-spec.layout-protocol.md` § Attachments) and the cascade or the coordinator's reconciliation should have caught it up. An attachment in its own review is skipped — the catch-up lands on the finalize wake.

  The fix is `lazy-spec.set-stage <doc> <current-stage>` (re-syncs the tag), or `lazy-spec.set-stage <doc> draft|approved` to map a removed value.
- **Cancellability** — `spec_stage: cancelled` is FAIL, always, on the asset's start document (the type declaration's `start_doc`, e.g. `design.md:design` for a feature, `bug.md:bug` for a bug) and on a present `architecture` document: an asset is abandoned as a whole through `spec_cancelled`, never through the document that defines it. A `tech` document and a tool's plan document (`tool_types.<tool>.plan_doc` — the shipped `code-plan` / `test-plan`) may be `cancelled`.
- **Unreviewed draft doc (FAIL)** — a document whose type carries `stages: true` AND `review: true`, whose `spec_stage` reads `draft` but carries NEITHER `review_active: true` NOR a `review_result` value is a doc nobody ever opened for review — the coordinator's mandatory `submit` call on a `Write <doc>` job's `DONE` (`lazy-spec.coordination-playbook.md` Chapter 3) never fired for it. FAIL, naming the doc. The `gate_tick` stuck-draft backstop already auto-submits the file-provably certain subset of these on its own cadence (checkbox-written doc, its `Write <doc>` DONE recorded in `# History` with no review-open record, no tracked job or pending wake, asset not halted) — a doc this check still surfaces either predates the backstop's evidence trail or needs a human eye; propose `lazycortex-review submit <doc>`, never auto-run it here.
- **Decisions-registry record shape** — for every `decisions.md` under `<spec_path>` (product-level or asset-level; absence is never a finding — the file is lazily created):
  - **Missing `Status:` line (FAIL)** — a `## D-NNN — <thesis>` heading whose following metadata block carries no `Status:` line.
  - **Header mismatch (FAIL)** — the file's leading `# <title> — decisions` H1 does not match its own path + role, same rule as every other role-bearing doc's header check above.
  - **Duplicate `D-NNN` (FAIL)** — two `## D-NNN — …` headings in the same file share a number. The primitive's own file-lock prevents this under normal operation; a duplicate here means the lock was bypassed (a hand-edit, or a lock broken mid-write) — no auto-fix, the operator resolves which record keeps the number.
  - **Missing `wiki_pinned_topics` doc-kind pin (WARN, report-only)** — only when a spec-scope is configured in `wiki.scopes` (skip entirely otherwise — an unconfigured wiki has nothing to be wrong, same honesty rule as Check 10). A `decisions.md`, or any other role-bearing doc, whose `wiki_pinned_topics` lacks its expected `wiki/doc-kind/<role>` entry. **The doctor never backfills a missing pin itself** — it has a standing "no migration, ever" rule and a vault-wide pin sweep is exactly that; the fix is the dedicated `lazycortex-specs pins` CLI verb (a separate, later addition), run once and re-run after any bulk content import.
- **Decision statement in the wrong document (WARN)** — a `[!decision] … #spec/decision` block (a full decision statement, not a candidate) found in a document that is not a living doc, i.e. whose type does NOT carry both `stages: true` and `append_only: false`. Two examples of what the predicate cuts off:
  - **A plan** (a tool's `plan_doc` — the shipped `code-plan` / `test-plan`; `stages: true`, but a plan is a decomposition of already-accepted decisions, never their source): propose raising the block into the asset's design (or tech / architecture) document instead.
  - **A report** (a tool's `report_doc` — the shipped `code-report` / `test-report` / `data-report` / `docs-report`; `append_only: true`): a report only ever holds a decision-*candidate*; propose rewriting the block as one, or raising it into the living doc through the normal review round.

### Agent D — status folder-notes + gates + per-file stages + folders + intake

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`, `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, and `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md`.

**Asset enumeration — the status note is the boundary**

- Enumerate assets by SCANNING every `.md` under `<spec_path>` for `spec_role: status` in frontmatter. The asset is the folder that note sits in and whose basename it matches. No folder name resolves anything: `features/` / `changes/` / `bugs/` are places the operator files things, never facts about what a thing is.
- **Nesting is legal.** An asset folder may contain another asset folder. The boundary of an asset is its own status note: every per-asset scan below (documents, stages, decision blocks, protected sections) stops at a nested status note — a nested asset's files are ITS files, never its parent's, and are judged only under the nested asset's own type and tools.

**Top-level folders**

- Folder layout under `<spec_path>` is free — a folder the operator invented is never a finding, and there is no expected folder roster to be a subset of. One placement rule survives: a top-level `docs/` folder is the **removed product-docs subfolder** (FAIL) — product-level `design.md` / `tech.md` now live loose at the product root; in `--apply` offer to move them up and delete `docs/`.

**Status folder-notes**

- A folder holding a status note holds exactly one (basename matches the folder). Duplicate / basename mismatch → FAIL.
- **`spec_asset_type`** — every status note carries the key. Absent → FAIL (`asset-type-missing`), naming the note; the fix is `lazycortex-specs asset-type backfill`, run by the operator, or a coordinator wake that determines the type. The sentinel value `unknown` is **NOT a finding** — it is the legal "not determined yet" state, and the coordinator resolves it on its own cadence.
- **`asset-type-undeclared` (FAIL)** — a `spec_asset_type` value other than `unknown` that appears in neither the shipped `lazy-spec.asset-types.json` nor the product's own `asset_types`. Name the note and the value; the fix is to declare the type (`/lazy-spec.add-asset-type`) or to correct the value.
- **`type-playbook-missing` (FAIL)** — a declaration the assets under this product actually use that carries neither a `playbook` nor an `alias_of` (an alias borrows only its base's playbook, and chains are forbidden — an `alias_of` pointing at another alias is the same finding). Nothing can drive an asset of that type; the fix is to add the `playbook` ref to the declaration.
- **`tool-undeclared` (FAIL)** — a value in a status note's `spec_tools` list that appears in neither the shipped `lazy-spec.tool-types.json` nor the product's own `tool_types`. Name the note and the tool. An ABSENT `spec_tools` key is not a finding (the tool set is simply not determined yet), and neither is an empty list (determined: this asset needs no tool).
- Frontmatter carries `spec_role: status` and the five flat boolean gates plus the overlay: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`, `spec_cancelled`. Each must be present and a boolean. Missing key or non-boolean value → FAIL. A `gates:` dict, a `stage:` key, `awaits_human:`, or a `## Workflow` section on the folder-note are old-model artifacts → FAIL (propose to strip).
- **Structural `note-check` delegation.** For every asset's status folder-note, run `lazycortex-specs note-check <note>` and fold its violations directly into this agent's findings, rather than re-deriving them by hand — it already validates every frontmatter key against the closed schema (`unknown-key` / `bad-type`, covering `spec_halted`, `spec_targets`, `spec_depends_on`, `spec_cascade_done`, `spec_cascade_targets_done`, `spec_draft`, `spec_coordinator_answered`, `spec_coordinator_doc_state`, `spec_coordinator_ready_state`), the presence and canonical order of `# Gates` / `# Status brief` / `# Coordinator rules` / `# Coordinator commands` / `# History` (`missing-section` / `section-order`), and the `#protected/spec/status-brief` marker on the line immediately after the `# Status brief` heading (`missing-marker`). Map every returned violation kind to FAIL. The same call also returns the note's `job_markers` block — its runtime-sidecar entry (`active_job` / `coordinator_job` / `pending_wake`), which the three bullets below read.
- **Job markers out of the sidecar** — the two job markers are runtime state at `<repo>/.runtime/lazy-specs.jobs.json`, never frontmatter. A `spec_active_job` or `spec_coordinator_job` key appearing in a folder-note's frontmatter is a regression, and `note-check` already reports it as `unknown-key` → FAIL. Never repair it by re-registering the key; the fix is to clear it off the note and, if a live job was tracked there, re-mark it with `lazycortex-specs mark-job`.
- **`active_job` deep shape** — when the `job_markers` block carries one, it MUST have exactly the three keys `checkbox`, `expert`, `job_id`, with `checkbox` a non-empty string. A missing or extra key → FAIL. The label's VALUE is not checked against any list: launch-checkbox vocabulary is playbook property (see the **Launch-checkbox labels** bullet below), and `mark-job` holds no dictionary of it either — so a violation here means the sidecar was hand-edited into the wrong shape.
- **`coordinator_job` deep shape** — when the `job_markers` block carries one, it MUST have exactly the three keys `trigger`, `expert`, `job_id`, and `trigger` MUST be one of the closed set `{operator-edit, command, answer, job-done, doc-transition, dependency-ready}` (`lazy-spec.coordination-playbook.md` § 1's eight wake triggers, minus the two that never persist a job record — routing and the drive-hook). A missing key or a `trigger` value outside the closed set → FAIL.
- **Launch-checkbox labels** — every `[!gate] <label>` block found in `# Gates` (a block carrying a `- [ ]`/`- [x]` line, as opposed to `lazy-spec.flip-gate`'s own `[!gate] <gate> — flipped …` flip-record callout) MUST carry a non-empty `<label>`; the wire shape is `lazy-spec.lifecycle-protocol.md` Part 3. **There is no closed label set to check against, and this skill MUST NOT reintroduce one.** Which labels exist on an asset is declared by its type playbook and the playbooks of the tools in its `spec_tools`, including labels a playbook parameterises by tool (`Start implementation (code)`, `Start implementation (data)`); `spec.coordinator` reconciles exactly that declared set (`lazy-spec.coordination-playbook.md` Chapter 5). A label that no playbook of this asset's type or tools accounts for is a WARN, not a FAIL — the playbooks are prose and this reading is a judgment, so report it and let the operator decide. A malformed block (no label at all, or a checkbox line outside any `[!gate]` callout) → FAIL.
- Managed `iconize_icon` (and `iconize_color` when the type declaration carries a color) — see Icon drift below.
- Old-style `## Gates` / `## History` H2 sections without a plugin-owned H1 wrapper are an old-shape artifact — flag as FAIL but do NOT auto-rewrite (report-only, no `--apply`). The canonical shape (all six protected H1s, including `# Coordinator rules` and `# Coordinator commands`) is Agent C's own check, above.

**Linear gate precedence (S0..S5)**

- The five gates are a strict ladder (`lazy-spec.lifecycle-protocol.md` → Linear map): each true gate requires every earlier gate true. Order: `spec_design_done` → `spec_plan_done` → `spec_develop_done` → `spec_tests_passing` → `spec_released`. A later gate true while an earlier gate is false is a **precedence violation** (FAIL) — name the offending pair. In `--apply`, the fix loop offers two resolutions and the operator picks one: turn the orphaned later gate off (the `--off` direction), or halt the asset instead via `lazycortex-specs flip-gate <asset> --halt "later gate true while an earlier gate is false"` (the `HaltReason.GATE_PRECEDENCE` phrase) when the break looks like more than a stray flip.
- **`spec_cancelled` overlay** — `spec_cancelled: true` freezes the gates (no flips). It is orthogonal to the ladder; a cancelled asset with any gate state is sane (no precedence enforcement while cancelled). `spec_cancelled` must be a boolean.

**Gate ⇔ per-file stage coupling**

**Where the preconditions come from.** Resolve, per asset: the type playbook at `asset_types[<spec_asset_type>].playbook` (through `alias_of` when the declaration is an alias — an alias borrows its base's playbook and nothing else), and one tool playbook per entry in `spec_tools` at `tool_types[<tool>].playbook`. READ those files and judge each true gate against what they require. **This skill holds no hardcoded table of which document closes which gate** — that table lives in the playbooks, differs per type and per tool, and grows with every declaration an operator adds. An asset whose `spec_asset_type` is `unknown` and one whose `spec_tools` key is absent have no resolvable precondition for the affected gates: report the coupling as `undetermined`, never as a finding.

- `spec_design_done` / `spec_plan_done` — the TYPE playbook's half. It names the documents each gate waits on (for the shipped types: the start document for design; the architecture step, when the playbook has one, plus each tool's declared `plan_doc`, for plan). A gate true while a document its playbook requires for that gate is still `empty`/`draft`/`rejected` → FAIL, quoting the requirement and naming the playbook.
- `spec_develop_done` — an AND over every tool in `spec_tools` EXCEPT `test`: each closes its own term by an ACCEPTED report of its declared `report_doc` type (`review_result ∈ {approved, approved-with-concerns}`; reports carry no `spec_stage`). The gate true while any non-test tool's report is missing or unaccepted → FAIL, naming the tool and its `report_doc`. `spec_tools: []` (determined: no tool) leaves the gate unconstrained — nothing is expected, nothing is a finding.
- `spec_tests_passing` — the `test` tool's own gate, and no other tool contributes to it. With `test` ∈ `spec_tools`, the gate true requires an accepted `test-report` and, since that tool declares a `plan_doc`, a present `test-plan` at `approved` (`cancelled` does NOT waive it) → otherwise FAIL. With `test` ∉ `spec_tools`, the asset is free by absence: the gate is unconstrained and its state is never a finding.
- `spec_released: true` ⇒ every stage-bearing document present under the asset — up to its boundary, so a nested asset's documents are excluded — is resolved: `approved`, or `cancelled` only where § Cancellability (Agent C) permits it. Any doc still `empty`/`draft`/`rejected` → FAIL. Report documents carry no `spec_stage` and are never part of this resolution check. (Assets carry no `tech.md` — only the product `tech.md` at its root does.)
- The per-file `spec_stage` re-validation here repeats Agent C's closed-set check only as needed to evaluate coupling — coupling findings are D's, the closed-set / tag-mirror findings are C's. Do not double-report.

**Per-file stage surfacing**

- Any doc stuck at `spec_stage: rejected` is a WARN in every run — valid state, but signals unfinished review work. Fix: `lazy-spec.set-stage <doc> draft` + re-open review (`review_active: true`).
- **Un-promoted decision block in an approved living doc (WARN)** — a `design.md` / `bug.md` / `tech.md` / `architecture.md` at `spec_stage: approved` that still carries a `[!decision] … #spec/decision` block in its body: the automatic transfer on approve never ran (or the block was added after approval). Fix: `lazycortex-specs decide promote <doc>` (or `/lazy-spec.decide`).
  - **Skip entirely** when the owning asset carries `spec_cancelled: true` or `spec_released: true` — both states freeze the automatic transfer permanently by design; a block left in place there is expected, not a finding.
  - **WARN, not skip**, when the owning asset carries `spec_halted: true` — halt is temporary, and a block that got stuck while halted needs the operator to see the debt once the flag is lifted, not silence forever.
  - This check is scoped to living docs only — a `[!decision-candidate]` in a tool's report document (`code-report` / `test-report` / any other declared `report_doc`) is a standing to-do, never a transfer debt; it lives there indefinitely and is never a finding.

**Change-cascade fields**

- **`spec_targets`** — optional; carried by an asset whose type playbook declares a cascade (the shipped `change`), naming the assets its design cascades into. When present it MUST parse as a list; each element is a **path relative to the product's `spec_path`** that MUST resolve to an existing asset — a directory under `spec_path` whose folder-note carries `spec_role: status`. Today's `<folder>/<slug>` tokens already are such paths; a nested asset is addressed by its full relative path, and no segment of it is a category name being resolved. An unresolvable token → WARN (name the asset and the offending token).
- **`spec_cascade_done`** — optional; when present its value MUST be a boolean. A non-boolean value → FAIL.
- **`spec_cascade_targets_done`** — optional; when present it MUST parse as a list. A non-list value → FAIL.
- **`spec_draft`** — optional; when present its value MUST be a boolean. A non-boolean value → FAIL. Negative gate: absent or `false` means ready for a downstream consumer.
- **`spec_state`** — the coordinator's derived state token, the iconize registry's only input for painting the asset folder. Its value MUST be one of `draft`, `in-review`, `implementation`, `testing`, `waits-operator`, `blocked`, `done` (`spec_keys.py::AssetState`); anything else → FAIL. An absent key on an asset the coordinator has already woken on → WARN, since the folder paints from the scaffold seed until the key lands. Do NOT check it against the gates: three of the values are decided by facts outside this note (a sibling's `review_active`, a job in the runtime sidecar, a dependency's own state), so a state that looks inconsistent with the gate booleans is normal, not drift. `spec_halted` / `spec_cancelled` are separate flags and never appear as a value here — finding one is the FAIL above.

**Dependency graph field**

- **`spec_depends_on`** — optional; on any asset, naming the assets it needs (`lazy-spec.coordination-playbook.md` § 8's dependency graph, and a decomposer's own children). When present it MUST parse as a list; each element is a **path relative to the product's `spec_path`**, resolved exactly like a `spec_targets` token: it must land on a directory under `spec_path` whose folder-note carries `spec_role: status`. It is a path, not a `<kind>/<slug>` pair — no segment is matched against a type name or a declaration. An unresolvable token → WARN (name the asset and the offending token), same severity as an unresolvable `spec_targets` entry.
- **Self-dependency and direct cycles → FAIL.** An asset naming itself in its own `spec_depends_on` → FAIL. A direct two-node cycle (asset A's `spec_depends_on` names B, and B's `spec_depends_on` names A) → FAIL, name both assets. This check is cheap — only the asset under scan plus its immediate dependencies' own `spec_depends_on` lists, no further graph walk. A longer cycle (A → B → C → A) is NOT this check's job: walking the full dependency graph on every scan is the coordinator's own judgment call when it proposes a working order (playbook § 8's "leaves of the graph outward"), not a mechanical doctor pass — the split is deliberate, not a gap.
- **Decomposer `spec_develop_done` coupling → FAIL.** `spec_develop_done: true` on an asset with a non-empty `spec_depends_on` AND no report document of its own (the decomposer shape — Chapter 8: its own "implementation" IS its children, so it authors no tool report) implies EVERY named child's own `spec_develop_done` reads `true` — any child false or unresolved → FAIL, naming the decomposer and the offending child. An asset that DOES carry a tool's report document is an ordinary tool-driven asset that merely happens to declare dependencies (Chapter 8's bottom-up order) — this coupling does not apply to it.

**Operator-zone folder-notes + container-note protected section + icon drift**

- The product folder-note (`<spec_path>/<leaf>.md`) and each container folder-note (any other folder-note under `<spec_path>` whose own folder carries no `spec_role: status` — the `features/` / `changes/` / `bugs/` / `requests/` folders the product scaffold creates, and any folder the operator adds) are operator-zone folder-notes: they carry NO `spec_role`, NO `*-index` role, NO dataviewjs. Finding `spec_role` on one → FAIL. Container folder-notes additionally carry a `description` frontmatter key (operator-authored prose; the plugin only reads it) — absent on a container folder-note is a WARN.
- **Product folder-note `# Coordinator rules` section (WARN)** — the product folder-note (`<spec_path>/<leaf>.md`) SHOULD carry a `# Coordinator rules` H1 section — the product-scoped layer of `lazy-spec.coordination-playbook.md` § 2's rule chain (playbook → vault doc → product note → asset note), read by `spec.coordinator` on every asset under this product before it decides anything. Missing → WARN, not FAIL: an operator who has not yet needed product-wide constraints has nothing wrong, just nothing written. In `--apply`, offer to add an empty section carrying the same `#protected/spec/coordinator-rules` tag the asset-note template carries. Container folder-notes do NOT carry this section — the rule layers name only the product and the asset, never a container in between; finding one on a container folder-note is not itself a violation (nothing declares it forbidden), but it is also never expected or read by the coordinator.
- **Container-note `#protected/spec/summary` section** — the product root folder-note and every container folder-note MUST each carry a `# Summary` section whose first content line is `#protected/spec/summary`. That section body MUST contain both a `<!-- spec:precis:* -->` marker and a `<!-- spec:stats:* -->` marker (used by the plugin to inject generated precis text and aggregate stats). Missing `# Summary` section → FAIL. Missing either marker inside the section → FAIL. Stats-marker content staleness is NOT a doctor finding — stats are kept fresh by event-driven writes and do not require periodic validation. Asset status folder-notes carry a `# Summary` section with a precis marker only — no stats marker required on assets; apply that narrower check only to asset notes. (The vault-root `requests/` inbox note is validated separately in Check 8, which is the only check that runs outside any product's `spec_path`.)
- **`iconize_icon` drift (WARN)** — the managed `iconize_icon` on each operator-zone folder-note must match its config source of truth. Resolve the expected value:
  - Product folder-note → `products[<key>].icon` (absent in config ⇒ no `iconize_icon` expected; a stray one is the drift).
  - Container folder-note → the `icon` of the asset type whose merged declaration names that folder as its `default_path` (shipped: `features` → `LiRocket`, `changes` → `LiRefreshCcw`, `bugs` → `LiBug`), plus the vault-shaped `requests` → `LiInbox` for the inbox container. A container no declaration points at has no expected icon — neither its presence nor its absence is drift.
  - The asset status folder-note's `iconize_icon` mirrors the icon of its OWN type's declaration (`asset_types[<spec_asset_type>].icon`), never the folder it sits in and never the base an `alias_of` names — an alias borrows only its base's playbook, its paint stays its own. Drift → WARN. An asset at `spec_asset_type: unknown` (or missing the key — already a FAIL above) has no resolvable icon: skip the check rather than propose one.
  - A typed document's `iconize_icon` mirrors its own `spec_doc_type` declaration's `icon` (`products[<key>].doc_types` over the shipped `references/lazy-spec.doc-types.json`) — the seed the scaffold wrote at creation. Drift → WARN. A document whose type declares no `icon` has none expected.
  - `iconize_color` on a CONTAINER folder-note mirrors the same declaration's `color` when it carries one; a stray `iconize_color` with no declared color, or a mismatch, is a WARN. In `--apply`, offer to rewrite the managed `iconize_*` keys to the declared value.
  - **`iconize_color` on an asset status folder-note is NEVER checked.** Its colour is owned by the iconize registry (`references/lazy-spec.iconize-registry.json`), which paints the folder from `spec_state`, `spec_halted`, and `spec_cancelled` — a render-time DERIVED value that the worker writes back into frontmatter on every run. The type declaration's `color` reaches a status note only as the seed before the first paint. Comparing the two would report drift on every healthy asset, and proposing a rewrite would fight the matcher until the next run undid it. Skip `iconize_color` on every note carrying `spec_role: status`; the same holds for a typed document, whose colour the stage matchers own once it has a stage.
  - **Document colour is checked only before the first stage.** A document carrying no `spec_stage` is still on its seed, so its `iconize_color` must match the declaration's; one that has a stage is the stage matchers' and is skipped.

**Guideline paths**

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` (`products[<key>].guidelines`). The product record's `guidelines` dict, when present, is keyed by dispatched role token (`planner`, `tester`, `developer`, `architect`) plus the wildcard `"*"`, each value a list of repo-relative file paths.

- **Missing guideline path (WARN)** — every path listed under any role key (or `"*"`) in `products[<key>].guidelines` that does not resolve to a file on disk (relative to the repo root). Report the role key and the declared path; this mirrors the same-shaped warning `gate_dispatch.py` appends to an asset's `# History` at dispatch time, surfaced here ahead of any tick so a stale path is caught before it silently drops context from a launch-checkbox job.

**Request intake**

Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md`. Validate the single vault-root `<vault-root>/requests/` inbox (NOT per-product `<spec_path>/requests/`) — request files stay there for their entire lifecycle (no `archive/` move).

- Each `requests/<slug>.md` carries `spec_role: request`, `request_status` ∈ `{draft, accepted, rejected}`, `request_class` ∈ the closed-meta ∪ asset-category set, and `created` (ISO date). Missing key / out-of-set value / malformed date → FAIL.
- Active-inbox files (`request_status: draft`) are eligible for routine pick-up; terminal files (`accepted | rejected`) carry a terminal status callout above the title and, for `accepted`, at least one `[[<entity-folder-note>]]` wikilink in the callout body (missing → FAIL).
- **`source_requests` forward link** — every wikilink in a status folder-note's `spec_source_requests` list MUST resolve to an existing request file under the vault-root `requests/` inbox. Unresolvable → FAIL. (Forward-only; the reverse link lives in the request's terminal callout body and is not separately enforced.)

## Cross-reference check (Check 8, inline in coordinator)

This check runs once, vault-wide — not scoped to any single product's `spec_path`. It is one of two places checks outside all products' `spec_path` boundaries are performed — the other is Check 9, below.

- Verify the product is referenced in any relevant index pages.
- A loose `<spec_path>/changelog.md` is a FAIL: the role is removed from the model. The fix is to delete the file (its history has migrated into per-doc `# History` H1 sections maintained by the review system, and the status folder-note's `# History` H1 section of each asset).
- **Requests-inbox `#protected/spec/summary` section** — the vault-root `requests/requests.md` inbox note (at `<content-root>/requests/requests.md`, outside any product's `spec_path`) MUST carry a `# Summary` section whose first content line is `#protected/spec/summary`. That section body MUST contain both a `<!-- spec:precis:* -->` marker and a `<!-- spec:stats:* -->` marker. Missing `# Summary` section → FAIL. Missing either marker → FAIL. This check is report-only — no `--apply` auto-rewrite.

## Upstream sources check (Check 9, inline in coordinator)

Runs once, vault-wide, exactly like Check 8 — `upstream/` sits outside every product's `spec_path`, alongside `requests/`, so this scope is never enumerated per-product and never as part of "all products".

Run `Bash(lazycortex-specs upstream-doctor)`. It prints one JSON object: `{configured, findings}`.

- **`configured: false`** — `spec.upstream` carries no configured source. Report `scan: Check 9 upstream — skipped:not-configured (0 findings)` and stop; this is the wiki.domains-style honesty rule (§ 13 wording: a scope the operator never set up has nothing to be wrong) — never a WARN, never a FAIL.
- **`configured: true`** — fold every entry in `findings` into the report as a FAIL (this worker's whole finding vocabulary is FAIL-severity; there is no WARN tier here). Each entry carries `{kind, repo_key, unit_path, detail}` — render `detail` verbatim, and include `unit_path` when present. The closed `kind` vocabulary (`DoctorFinding` in `${CLAUDE_PLUGIN_ROOT}/bin/spec_keys.py`-adjacent `upstream_tick.py`):
  - `missing-note` — a unit directory carries `source/` or `processed/` but no own note file.
  - `tag-status-mismatch` — a unit note's `tags:` list does not mirror its own `spec_upstream_status`.
  - `processed-without-snapshot` — a unit note reads `processed` but `processed/` is missing or empty.
  - `dangling-request-link` — a `in-review` unit's request link is missing or no longer resolves (§ 8's own doctor-visible mutex — this worker never fixes it itself; the fix loop offers the reset, above).
  - `unknown-action-label` — a unit note's `# Actions` section carries a checkbox label outside the closed `UpstreamAction` set (`Take into work`, `Process update`, `Postpone`).
  - `clone-origin-mismatch` — a configured source's working clone points at a different remote than its current `url` (Task 4's own guard, named here for the operator).
  - `unconfigured-source` / `unconfigured-mount` — a `upstream/<repo-key>/` or `upstream/<repo-key>/<mount>/` subtree exists on disk with no matching config entry (§ 12: "the subtree exists, the config entry does not") — report only; `lazy-spec.upstream-tick` never deletes an unconfigured subtree itself, and neither does this skill.
- **NOT findings, ever** — `orphaned` / `invalid` / `excluded` / `postponed` unit statuses, and a unit correctly frozen `in-review` with a resolvable request link. These are the documented steady states (§ 13: "does NOT flag ... or an ongoing review").

## Wiki companion check (Check 10, inline in coordinator)

Runs once, vault-wide, like Checks 8–9 — the pairing between the spec plugin and `lazycortex-wiki` is repo-level, never per-product. INFO severity only, report-only, no fix-loop entry: the fix is installing/configuring a different plugin, which this skill never does.

- `lazycortex-wiki@lazycortex` absent from `~/.claude/plugins/installed_plugins.json` → `[INFO] wiki-companion-missing — lazycortex-wiki is not installed; spec experts (architect, designer, planner) fall back to reading code directly. Install and configure it (structure map, domain tree, terms dictionary, wiki scopes) for cheaper, better-grounded expert research.`
- Installed, but `lazy.settings.json` has `wiki.scopes` empty AND `structure.depth_profiles` empty AND no `wiki.domains` → `[INFO] wiki-companion-unconfigured — lazycortex-wiki is installed but nothing is configured; run /lazy-wiki.configure.`
- Otherwise → `scan: Check 10 wiki-companion — clean`.

## Output (Report)

Merge the four agents' findings plus Check 0, Check 8, Check 9, and Check 10, then print a report grouped by severity. The report MUST contain one line per Agent (A/B/C/D) plus Check 0, Check 8, Check 9, and Check 10 — a missing line is a bug. Checks 9 and 10 run exactly once per invocation (not once per product, even under "all products") — render each scan line once, at the end.

```
## <Product Name> — Spec Doctor Report

scan: Check 0 resolve-product — <code-bound|design-only|unregistered>
scan: Agent A link-health — <PASS|WARN|FAIL> (<N> findings)
scan: Agent B source-staleness — <PASS|WARN|FAIL|skipped:no-source-binding> (<N> findings)
scan: Agent C role-header — <PASS|WARN|FAIL> (<N> findings)
scan: Agent D status-gates-folders-intake — <PASS|WARN|FAIL> (<N> findings)
scan: Check 8 cross-reference — <PASS|WARN> (<N> findings)
scan: Check 9 upstream — <PASS|FAIL|skipped:not-configured> (<N> findings)
scan: Check 10 wiki-companion — <clean|INFO> (<0|1> findings)

### Errors (must fix)
- [ ] Bare wikilink: `[[design]]` in `features/<feat>/code-plan.md:<line>` — use `[[<path>|<display>]]`
- [ ] Broken wikilink: `[[<target>]]` in `<spec_path>/design.md:<line>`
- [ ] Role violation: source URL in `<spec_path>/design.md:<line>` — belongs in `<spec_path>/tech.md`
- [ ] Role violation: `source_branches:` frontmatter on `features/<feat>/design.md`
- [ ] Unknown `spec_role`: `<file>` carries `spec_role: <value>` (closed set: design, architecture, code-plan, test-plan, code-report, test-report, bug, tech, status, decisions)
- [ ] Loose `changelog.md`: `<spec_path>/changelog.md` exists — the role is removed; delete the file
- [ ] Header mismatch: `features/<feat>/design.md` H1 does not match its path + role
- [ ] Invalid `spec_stage`: `<doc>` has `spec_stage: <value>` (closed set: empty, draft, approved, rejected, cancelled)
- [ ] Stage/tag mirror drift: `<doc>` `spec_stage: approved` but `tags:` has `spec/draft`
- [ ] Cancelled primary doc: `features/<feat>/design.md` is `spec_stage: cancelled` — design may never be cancelled
- [ ] Duplicate status folder-note: `features/<feat>/` holds two notes carrying `spec_role: status`
- [ ] Status-note basename mismatch: `features/<feat>/status.md` carries `spec_role: status` but its basename is not `<feat>`
- [ ] `asset-type-missing`: `features/<feat>/<feat>.md` carries no `spec_asset_type` — run `lazycortex-specs asset-type backfill` (`unknown` is a legal value, not a finding)
- [ ] `asset-type-undeclared`: `features/<feat>/<feat>.md` reads `spec_asset_type: <value>`, declared in neither the shipped types nor `products[<key>].asset_types`
- [ ] `type-playbook-missing`: `asset_types.<type>` declares neither `playbook` nor `alias_of` — no playbook can drive an asset of this type
- [ ] `tool-undeclared`: `features/<feat>/<feat>.md` `spec_tools` names `<tool>`, declared in neither the shipped tools nor `products[<key>].tool_types`
- [ ] Architecture doc outside its playbook: `bugs/<bug>/architecture.md` exists but the `bug` type playbook describes no architecture step
- [ ] Missing gate boolean: `features/<feat>/<feat>.md` lacks `spec_develop_done`
- [ ] Old-model artifact: `features/<feat>/<feat>.md` carries a `gates:` dict / `stage:` key / `## Workflow` section — strip
- [ ] Invalid `spec_halted`: `features/<feat>/<feat>.md` has `spec_halted: <non-boolean>`
- [ ] Malformed `active_job` marker: `features/<feat>/<feat>.md`'s sidecar `active_job` is not `{checkbox, expert, job_id}`
- [ ] Malformed `coordinator_job` marker: `features/<feat>/<feat>.md`'s sidecar `coordinator_job` is not `{trigger, expert, job_id}`, or `trigger` is outside `{operator-edit, command, answer, job-done, doc-transition, dependency-ready}`
- [ ] Job marker in frontmatter: `features/<feat>/<feat>.md` carries `spec_active_job` / `spec_coordinator_job` as a frontmatter key, which belongs to the runtime sidecar
- [ ] Malformed launch checkbox: `features/<feat>/<feat>.md` `# Gates` carries a `[!gate]` block with no label, or a checkbox line outside any `[!gate]` callout
- [ ] `note-check` violation: `features/<feat>/<feat>.md` — `<violation kind>` on `<key-or-section>` (unknown-key / bad-type / missing-section / missing-marker / section-order, folded verbatim from `lazycortex-specs note-check`)
- [ ] Invalid `spec_cascade_done`: `changes/<chg>/<chg>.md` has `spec_cascade_done: <non-boolean>`
- [ ] Invalid `spec_cascade_targets_done`: `changes/<chg>/<chg>.md` `spec_cascade_targets_done` is not a list
- [ ] Invalid `spec_draft`: `<feat-or-chg>/<slug>.md` has `spec_draft: <non-boolean>`
- [ ] Invalid `spec_state`: `<feat-or-chg>/<slug>.md` has `spec_state: <value>` outside the declared set
- [ ] Self-dependency: `features/<feat>/<feat>.md` `spec_depends_on` names itself
- [ ] Direct dependency cycle: `features/<a>/<a>.md` `spec_depends_on` names `features/<b>` and `features/<b>/<b>.md` `spec_depends_on` names `features/<a>` back
- [ ] Decomposer coupling: `features/<feat>/<feat>.md` `spec_develop_done: true`, no report document of its own, but child `features/<child>` still `spec_develop_done: false`
- [ ] Tool report missing: `features/<feat>/<feat>.md` `spec_develop_done: true` but tool `code` has no accepted `code-report` under the asset
- [ ] Unreviewed draft doc: `features/<feat>/architecture.md` `spec_stage: draft` with neither `review_active` nor `review_result` set
- [ ] Gate precedence: `spec_tests_passing: true` but `spec_develop_done: false` (gates are a strict ladder S0..S5)
- [ ] Gate/stage coupling: `spec_design_done: true` but `design.md.spec_stage: draft` (must be approved)
- [ ] Release coupling: `spec_released: true` but `code-plan.md.spec_stage: draft` (every present doc must resolve before release)
- [ ] Old-shape H2 sections: `features/<feat>/<feat>.md` carries `## Gates`/`## History` H2 without a `#protected/spec/*` H1 wrapper — old-model artifact (report-only; no auto-rewrite)
- [ ] Missing protected section: `features/<feat>/<feat>.md` has no `# Summary` (`#protected/spec/summary`) — status note must carry Summary, Gates, and History protected H1 sections
- [ ] Missing protected section: `features/<feat>/<feat>.md` has no `# Gates` (`#protected/spec/gates`)
- [ ] Missing protected section: `features/<feat>/<feat>.md` has no `# History` (`#protected/spec/history`)
- [ ] Duplicate protected section: `features/<feat>/<feat>.md` has two `# Summary` sections
- [ ] Missing container Summary section: `<spec_path>/features/features.md` has no `# Summary` (`#protected/spec/summary`)
- [ ] Missing precis marker: `<spec_path>/features/features.md` `# Summary` body lacks `<!-- spec:precis:* -->` marker
- [ ] Missing stats marker: `<spec_path>/features/features.md` `# Summary` body lacks `<!-- spec:stats:* -->` marker (required on container notes; not required on asset status notes)
- [ ] `spec_role` on operator-zone folder-note: `<spec_path>/features/features.md` carries `spec_role` (must have none)
- [ ] Removed `docs/` subfolder: `<spec_path>/docs/` exists — move `design.md` / `tech.md` to the product root and delete `docs/`
- [ ] Reserved product slug: product folder leaf is `design`/`tech`/`decisions` — collides with the product-level doc of the same name; rename the product
- [ ] Decision record without `Status`: `features/<feat>/decisions.md` `## D-003 — …` has no `Status:` line
- [ ] Broken decision anchor: `[[features/<feat>/decisions#D-005 — thesis|D-005]]` in `<file>:<line>` — no such heading in the target
- [ ] Dangling `superseded-by`: `features/<feat>/decisions.md` `## D-003` points at `D-011`, which does not exist
- [ ] Duplicate decision number: `features/<feat>/decisions.md` has two `## D-004 — …` headings
- [ ] Decisions header mismatch: `features/<feat>/decisions.md` H1 does not match its path + role
- [ ] Code decision link unresolved: `<repo>/src/export.py:42` cites `Decision: core/features/export#D-007` — no such `decisions.md` or `D-007` heading
- [ ] Request schema: `requests/<slug>.md` missing/invalid `request_status`/`request_class`/`created`
- [ ] Unresolvable `spec_source_requests`: `<feat>/<feat>.md` lists `<path>` but no request file exists there
- [ ] Upstream unit without note: `upstream/<repo-key>/<mount>/<unit>/` carries `source/` or `processed/` but no `<unit>.md` note
- [ ] Upstream status/tag mismatch: `upstream/<repo-key>/<mount>/<unit>/<unit>.md` reads `spec_upstream_status: <X>` but `tags:` lacks `upstream/<X>`
- [ ] Upstream processed without snapshot: `upstream/<repo-key>/<mount>/<unit>/<unit>.md` reads `spec_upstream_status: processed` but `processed/` is missing or empty
- [ ] Upstream dangling request link: `upstream/<repo-key>/<mount>/<unit>/<unit>.md` reads `spec_upstream_status: in-review` with a missing or unresolvable request link
- [ ] Upstream unknown action label: `upstream/<repo-key>/<mount>/<unit>/<unit>.md` `# Actions` carries a label outside `{Take into work, Process update, Postpone}`
- [ ] Upstream clone origin mismatch: `<repo-key>`'s working clone points at a different remote than its configured `url`
- [ ] Upstream unconfigured subtree: `upstream/<repo-key>/` or `upstream/<repo-key>/<mount>/` exists with no matching `spec.upstream` config entry

### Warnings (should fix)
- [ ] Missing display text: path-qualified wikilink with no `|<display>` in `<file>:<line>`
- [ ] Route `<METHOD> <path>` exists in code but not in `<spec_path>/tech.md`
- [ ] Constant `<NAME>` changed: tech file says `<X>`, code says `<Y>`
- [ ] Missing container description: `<spec_path>/characters/characters.md` has no `description`
- [ ] Missing product `# Coordinator rules`: `<spec_path>/<product>.md` has no `# Coordinator rules` section
- [ ] Icon drift: `<spec_path>/features/features.md` `iconize_icon: <X>` ≠ the `feature` declaration's `LiRocket`
- [ ] Missing `spec_state`: `features/<feat>/<feat>.md` carries no `spec_state` though the coordinator has already woken on it
- [ ] Unaccounted launch checkbox: `features/<feat>/<feat>.md` `# Gates` carries `[!gate] <label>` that no playbook of its type or tools accounts for
- [ ] Rejected doc: `features/<feat>/design.md` is `spec_stage: rejected` (unfinished review)
- [ ] Unresolvable `spec_targets`: `changes/<chg>/<chg>.md` lists `<path>` but no asset resolves at `<spec_path>/<path>`
- [ ] Unresolvable `spec_depends_on`: `features/<feat>/<feat>.md` lists `<path>` but no asset resolves at `<spec_path>/<path>`
- [ ] Un-promoted decision block: `features/<feat>/design.md` is `spec_stage: approved` but still carries a `[!decision]` block in its body
- [ ] Decision statement in a plan: `features/<feat>/code-plan.md` carries a `[!decision]` block — raise it into `design.md` instead
- [ ] Decision statement in a report: `features/<feat>/code-report.md` carries a `[!decision]` block — that role holds only a decision-candidate
- [ ] Dangling `Origin` back-link: `features/<feat>/decisions.md` `## D-002` is `active` with `Origin` naming `design.md`, which has no reference-link back to it
- [ ] Missing `doc-kind` pin: `features/<feat>/decisions.md` `wiki_pinned_topics` lacks `wiki/doc-kind/decisions` (spec-scope configured in `wiki.scopes`) — run `lazycortex-specs pins`
- [ ] Code decision link rescinded: `<repo>/src/export.py:42` cites `Decision: core/features/export#D-007` — record `Status: superseded-by D-011`

### Info
- N source files, M routes, K assets documented
- All header sections consistent
- All wikilinks resolve
- All gates precedence-consistent
```

## Fix loop

After the report, in **read-only mode (no `--apply`)** stop here — the report is the deliverable. State clearly that no files were changed and that re-running with `--apply` enables fixes.

In **`--apply` mode**, walk the errors and warnings and, **per finding**, call `AskUserQuestion` (one question per fix) before writing. For every finding, state the exact file, the specific issue, and what the fix concretely does. Typical fixes:

- Rewrite a bare wikilink to path-qualified form.
- Strip a forbidden source URL / `source_branches:` from a role that may not carry it (move the URL into the tech file when the user confirms).
- Re-sync a `spec/<stage>` tag to its `spec_stage` value (delegate to `lazy-spec.set-stage <doc> <current-stage>` — never raw-edit the tag).
- Turn off a precedence-orphaned gate (`lazy-spec.flip-gate <asset> <gate> --off`), or, presented as the alternative option in the same question, halt the asset instead (`lazycortex-specs flip-gate <asset> --halt "later gate true while an earlier gate is false"`).
- Add a missing gate boolean to a status folder-note.
- Rewrite a drifted `iconize_icon` / `iconize_color` to the declared value.
- Add missing routes/functions or update changed values in the tech file.
- Add a missing `# Coordinator rules` / `# Coordinator commands` section to a status folder-note (empty except for the template's `#protected/spec/coordinator-rules` / `#protected/spec/coordinator-commands` tag), or a missing `# Coordinator rules` section to a product folder-note (same tag) — never write content into either, only the empty tagged scaffold; the operator authors the constraints.
- On a `dangling-request-link` finding (Check 9, § 13), offer the doctor's own fix (§ 8: "the doctor catches it and offers the fix"): reset the unit note's `spec_upstream_status` to `drifted` when `processed/` exists, else `new`, and clear the stale `spec_upstream_request` line — the same fallback the tick's own release branch would have written had the request resolved. Never touch `source/` / `processed/` themselves.

Never auto-fix without the per-finding confirmation. **Never** change product config in `lazy.settings.json`, run any migration, or touch a doc's content beyond the specific approved fix.

When `--apply` writes fixes, the audit trail is the per-doc `# History` entries written by the canonical writers it delegates to (`lazy-spec.set-stage`, `lazy-spec.flip-gate`) plus this skill's own run log under `.logs/claude/lazy-spec.doctor/`. There is no product-wide changelog to update.

## Key rules

- **Read-only by default** — report first; fix only under `--apply` and only with per-finding approval.
- **No migration, ever** — there are no existing customers; doctor validates the current flat-gate model and ignores old-model artifacts rather than detecting or migrating them. Never add a "stale spec.cfg / suggest migration" check. This binds `spec_doc_type` and `spec_asset_type` too: the doctor NEVER backfills either key itself, exactly as it never backfills a `wiki_pinned_topics` pin — the fix it proposes is always `lazycortex-specs doc-type backfill` / `lazycortex-specs asset-type backfill`, run by the operator.
- **Open type set, closed stage set** — a `spec_doc_type`, `spec_asset_type`, or `spec_tools` value is valid because a declaration for it exists in the product's scope (shipped defaults merged under `products[<key>].asset_types` / `tool_types`), never because its name appears in a list here. Stages stay a closed five-value set.
- **An asset is a status note, not a folder name** — enumeration scans for `spec_role: status`, nesting is legal, and the asset's boundary is its own note: a nested asset's files are never its parent's. No check resolves anything from a folder name, and none may be reintroduced that does.
- **The playbooks own the workflow; this skill owns the state** — which document closes which gate, which launch checkboxes exist, which documents a type carries at all: all of it is read from the type playbook (`asset_types.<type>.playbook`) and the tool playbooks (`tool_types.<tool>.playbook`) of the asset under scan. `spec_develop_done` is an AND across the non-test tools' accepted reports; `spec_tests_passing` belongs to the `test` tool and is free by its absence. A hardcoded per-kind table here is a bug, not a shortcut.
- **Never remove spec content** — flag items that may be stale; let the user decide.
- **Concrete line references** — every finding points to the exact file and line/section.
- **Delegate heavy reads to the four parallel Explore agents** — the coordinator only resolves the product, runs the small cross-reference check inline, merges findings, and drives the fix loop.
- **Gates are flat booleans on a strict ladder** — `spec_design_done` → `spec_plan_done` → `spec_develop_done` → `spec_tests_passing` → `spec_released`, plus the `spec_cancelled` overlay. There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, no `## Workflow`. A later gate true while an earlier is false is a hard error.
- **Launch-checkbox labels are playbook vocabulary, not a closed set** — which boxes an asset carries, and how a playbook parameterises one by tool (`Start implementation (code)`), is declared by its type and tool playbooks and reconciled by `spec.coordinator` (`lazy-spec.coordination-playbook.md` Chapter 5); no primitive holds a label dictionary and neither does this skill. Only the wire SHAPE is checked (`lazy-spec.lifecycle-protocol.md` Part 3). `spec_halted` (optional, boolean) is the supporting frontmatter key, and the dispatched job rides in the runtime sidecar's `active_job` marker (`{checkbox, expert, job_id}`) rather than in the note; a halted asset's rendered color is derived by an iconize matcher, never a stored `iconize_color` — never treat it as icon drift.
- **`note-check` is the structural source of truth for a status folder-note's frontmatter schema and section roster** — Agent D delegates to it rather than re-deriving the same checks; see Agent D above for exactly what it covers and what still needs a deeper prose check on top.
- **`# Coordinator rules` exists at the product and asset levels; `# Coordinator commands` exists only at the asset level** — per `lazy-spec.coordination-playbook.md` § 2, a command with no addressee asset is ambiguous. A container folder-note carries neither.
- **Closed `spec_role` set** — design, architecture, code-plan, test-plan, code-report, test-report, bug, tech, status, decisions. No `layout`, no `human-tasks`, no `changelog`, no bare `plan`, no `*-index`. Operator-zone folder-notes (product + container) carry NO `spec_role`. Every role but the asset's own start document is opt-in — its absence is never a finding on its own; an `architecture` document present where the type playbook describes no architecture step is.
- **Closed `spec_stage` set** — empty, draft, approved, rejected, cancelled, mirrored by a `spec/<stage>` tag in lock-step. `lazy-spec.set-stage` is the only writer of both.
- **Folder layout is free** — there is no expected folder roster under `spec_path` and no unknown-folder finding; only the removed `docs/` subfolder survives as a placement error.
- **`iconize_*` is declaration-derived** — managed icon/color must match `products[<key>].icon` (product folder-note), the `icon` of the type whose `default_path` names the folder (container folder-note), or `asset_types[<spec_asset_type>].icon` (asset status note, read through the asset's own type and never through `alias_of`); drift is a warning.
- **Naming, folder structure, header section, wikilink format, gates, per-file stages, and request schema** are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill enforces but never inlines them.
- **Layout/body-shape findings are report-only — no `--apply` auto-migrate** — findings about stray repo-root `requests/`, content outside `vault_root`, or old-shape note bodies (missing protected sections, old title H1) are flagged but MUST NOT trigger an `--apply` action that moves, relocates, or rewrites existing content. The operator resolves these manually.
- **Halt reasons are a closed four-item list** — every `lazycortex-specs flip-gate <asset> --halt <reason>` call, including this skill's own fix-loop escalation, draws `<reason>` verbatim from `HaltReason` in `${CLAUDE_PLUGIN_ROOT}/bin/spec_keys.py`. The full trigger table (which worker fires which reason, and when) is documented in `lazy-spec.lifecycle-protocol.md` Part 5 — this skill never invents a new reason string.
- **Upstream sources (§ 13) are a separate, vault-wide scope** — `upstream/` sits outside every product's `spec_path` (like `requests/`); Check 9 covers it once per doctor run, never per-product, and stays silent when `spec.upstream` has no configured source (wiki.domains-style honesty — a scope the operator never set up has nothing to be wrong). It never reports on `orphaned` / `invalid` / `excluded` / `postponed` units or an active `in-review` freeze — those are the documented steady states, not findings.

## Logging

Per `lazy-log.logging`, write a run log to `./.logs/claude/lazy-spec.doctor/YYYY-MM-DD_HH-MM-SS.md`: `mkdir -p` then the `Write` tool (never chain). Frontmatter `git_sha` / `git_branch` / `date` / `input`; body `## Actions` (products checked, findings by severity, fixes applied in `--apply`) and `## Result`.
