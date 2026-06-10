---
name: spec.sync-with-code
description: Use when source code has changed since the last spec sync — compares a registered code-bound product's source commits against the last synced commit, updates the product tech doc, surfaces behavior changes for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections from the code state. No-ops on a design-only product.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, Task, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Spec Sync

Synchronize a product specification with source code changes since the last sync. Updates the product tech doc from the code, surfaces user-visible behavior changes to the operator for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections grounded in the observed code state — never silently. Per-asset history of these proposals lives in each touched status folder-note's `## History`, written by `spec.flip-gate` and `spec.set-stage`; per-document history of design/tech rewrites lives in the rewritten doc's `## History` H1 section. There is no separate product-wide changelog.

Product config, the five flat gates, per-file stages, source URLs, and pin reconciliation are all owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those mechanics; it calls the named primitives and references the reference docs.

## Execution discipline (MANDATORY — read before any action)

This skill has 11 ordered steps. The diagram seam set is **runtime-computed** — it depends on which sections were actually rewritten in Step 4 — so the preamble TaskCreate list contains one meta-step (`Step 4a — Compute runtime seam list`) that fans out into one dynamic task per discovered seam (`diagram <file>:<anchor>:<kind>` × N) before Step 5 begins. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per static step below. Use these canonical titles verbatim:
   - `Step 0 — Resolve the product`
   - `Step 1 — Determine scope`
   - `Step 2 — Get relevant changes`
   - `Step 2a — Delegate categorization to parallel agents`
   - `Step 3 — Analyze each commit`
   - `Step 4 — Route updates by file role (rewrite prose per operator approval)`
   - `Step 4a — Compute runtime seam list` (output: a list of `{target_file, anchor_section, kind, facts}` triples — one per section whose prose was rewritten)
   - `Step 4b — Dispatch diagram per computed seam` (this single task expands into N additional `TaskCreate` calls right after Step 4a runs — one task per computed seam, titled `diagram <relative-path>:<anchor>:<kind>` — and only Step 5 may begin once they are all `completed` or `skipped` with an outcome word)
   - `Step 5 — Reconcile asset status (folder-note scaffold + gate/stage proposals)`
   - `Step 5a — Reconcile branch pins`
   - `Step 6 — Update state`
   - `Step 7 — Run doctor`
   - `Step 8 — Verify`
   - `Step 9 — Log the run`

2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". For dynamically-created `Step 4b` child tasks, the outcome word IS the `lazycortex-diagram:lazy-diagram.draw` return value (`created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`). When Step 4 rewrites zero sections (no commits touched documented prose), `Step 4a` produces the empty list and `Step 4b` records outcome `no-seams-this-run` — the task list still resolves cleanly.

3. **Do not reach Verify until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task — including any dynamically-created `Step 4b` child — is a bug; stop and execute it first.

4. **Verify is a structural verifier** (per the `## Verify` section below). It diffs the runtime-computed seam list (the output of `Step 4a`) against the seams actually logged to `.logs/claude/lazy-diagram.draw/` for this run. Any non-empty diff is a Verify failure.

## Input

The user provides a product compound-key (e.g. `dashboards`, `server-tester-chapter`) or a source path under a registered product. If omitted or ambiguous, ask which product to sync.

## Step 0 — Resolve the product

Resolve the product record:

```bash
lazycortex-specs resolve-product by-key <product>
```

The command prints `{"key": "<product>", "record": <record-or-null>}`. The record (when present) carries `spec_path` (required, vault-relative), optional `source` (`{ repo, paths }`), optional `language` (defaults to `en`), and optional `asset_categories`.

Branch on the record:

- **`record` is `null`** — the product is not registered. Refuse with a message naming `<product>` and telling the operator to run `/spec.product-config` first. Do NOT proceed.
- **`record` present but no `source` block** — the product is design-only (specs ahead of code, no code to sync). No-op with the message: "product is design-only — no code binding to sync; use /spec.product-config to attach a repo." Do NOT proceed.
- **`record` present with a `source` block** — capture `spec_path`, `source.repo`, `source.paths`, `language` (default `en`), and `asset_categories`. Resolve `source.repo` via the `spec.resolve-repo` primitive to get `{ local_path, branch, host, owner, repo, forge, base_url, … }`. All source URLs emitted by this skill go through `spec.source-url(<repo-key>, …)` — never inline forge-specific path schemes. Continue.

All narrative prose this skill writes (`## Current`-style blurbs, folder-note `## History` lines, user-facing summaries presented via `AskUserQuestion`) is rendered in the product's `language` per `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`. Frontmatter keys/values, role words, fixed section headers, wikilinks, URLs, file paths, and gate names stay English.

## Step 1 — Determine scope

1. Read the product design doc (`<spec_path>/docs/design.md` — behavior) and product tech doc (`<spec_path>/docs/tech.md` — code architecture) per `${CLAUDE_PLUGIN_ROOT}/references/`. The design doc describes WHAT; the tech doc describes the code. This skill mostly touches the tech doc; it only flags design-doc changes to the operator for their decision.
2. Read `.state/spec-sync-<product-key>.json` to get `last_commit`:

   ```json
   { "last_commit": "<commit hash>", "last_sync": "<ISO date>", "source_paths": ["<source.paths>"] }
   ```

   If the state file doesn't exist, this is a first sync — ask the operator for the commit to start from (or default to the first commit touching `source.paths` after the product folder-note's git creation time).
3. Get current source repo HEAD: `git -C <repo-config>.local_path log -1 --format=%H`.
4. If `last_commit` == current HEAD → print "Already synced at `<short-hash>`" and stop.

## Step 2 — Get relevant changes

1. Run `git -C <repo-config>.local_path fetch --prune <remote>` (prefer `origin`; else the first remote `git -C <local_path> remote` returns). If the fetch fails (network, auth, missing remote) → abort the whole sync with a clear error; never operate on stale branch state — Step 5a's pin reconciliation depends on fresh refs.
2. Run `git -C <repo-config>.local_path log --oneline <last_commit>..HEAD -- <source.paths>` (one `--` path argument per entry in `source.paths`) to get commits touching this product's source.
3. If no commits → still run Step 5a (pins may need reconciling against the freshly-fetched refs), update the state file with current HEAD, print "No code changes to `<source.paths>`", and stop after Step 5a + state + log.
4. For each commit, run `git -C <repo-config>.local_path diff <commit>~1..<commit> -- <source.paths>` to get the specific diff.

## Step 2a — Delegate categorization to parallel agents

If the commit list is large (>5 commits) or touches many files, delegate analysis. In a single message, launch up to 3 parallel Explore agents (`subagent_type: "Explore"`, `mode: "dontAsk"`, read-only), each covering a subset of commits or a concern:

- **Agent A — structural changes**: routes, classes, functions (added / removed / signature-changed).
- **Agent B — data & templates**: data structure changes, template/UI changes, constant changes.
- **Agent C — behavior signals**: commit messages + diffs hinting at user-visible behavior changes (these surface as design-doc candidates).

Each agent returns a structured summary of findings with commit hashes per the parallel-scan coordinator pattern in `claude/lazycortex-core/references/lazy-core.parallel-scan.md`. The main session synthesizes them. For small commit lists, do the analysis inline.

## Step 3 — Analyze each commit

For each commit, categorize changes:

| Category | Detection |
|----------|-----------|
| **Route added** | New route decorator |
| **Route removed** | Deleted route decorator |
| **Route changed** | Modified route path, method, or handler body |
| **Function added** | New `def` at module level or in documented class |
| **Function removed** | Deleted `def` |
| **Signature changed** | Modified parameters or return type of documented function |
| **Constant changed** | Value change in documented constant |
| **New file** | File added to module |
| **File removed** | File deleted from module |
| **Class added/removed** | New or deleted class definition |
| **Config changed** | Changes to configuration values |

## Step 4 — Route updates by file role

Changes go to different files depending on their nature. Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`:

- **Code-level changes** (routes, functions, signatures, new/removed files, constants) → update the product tech doc. If it does not yet exist, create it from the current state before applying updates.
- **User-visible behavior changes** (identified by Agent C or by inspection of diffs that change what the user sees) → surface to the operator as "This commit appears to change user-facing behavior X. Update the product design doc?" Never silently rewrite the design doc — always ask.
- **Source URLs** must never appear in design docs. If a code change needs documenting with a source link, it belongs in the tech doc or, for asset-level implementation detail, in the asset's `plan.md`.

Tech-doc edits:
- **Added routes/functions**: add to the appropriate table/section in the tech doc.
- **Removed routes/functions**: ask before removing from the tech doc (mark as candidate for deletion).
- **Changed values**: update the documented value in the tech doc.
- **New files**: add a new subsection under Components in the tech doc.
- **Removed files**: ask before removing the component subsection from the tech doc.

Present all planned changes to the operator before applying: show a summary grouped by target file (tech-doc edits vs. design-doc candidates). Apply tech-doc edits after approval; apply design-doc edits only on per-item approval.

After all approved prose rewrites land, record a list of `(target_file, anchor_section)` pairs that were actually rewritten in this run. This list is the input to Step 4a.

## Step 4a — Compute runtime seam list

For every `(target_file, anchor_section)` pair recorded at the end of Step 4, look up the canonical seam-kind for that anchor under that role (the same map the creator skills follow):

| Role | Anchor | kind |
|---|---|---|
| design (product) | `## Behavior` | `flow` |
| tech (product) | `## Architecture` | `c4-container` |
| tech (product) | `## Components` | `class` |
| design (asset) | `## User Flow` | `flow` |
| design (asset) | `## Changes` | `flow` |

Anchors not in this map are NOT seams — they get no diagram call. Build the runtime seam list `seams[] = [{target_file, anchor_section, kind, facts: <bullet list extracted from the just-rewritten section>}, …]`. If `seams[]` is empty, record outcome `no-seams-this-run` for `Step 4a` and skip `Step 4b` with the same outcome.

## Step 4b — Dispatch diagram per computed seam

Before invoking the skill, call `TaskCreate` once per entry in `seams[]` with the canonical title `diagram <relative-path>:<anchor>:<kind>` (path is `<target_file>` relative to the vault root). Then, for each task in declaration order, mark `in_progress`, invoke `lazycortex-diagram:lazy-diagram.draw` (via the `Skill` tool) with the matching `target_file`, `anchor_section`, `kind`, `format="mermaid"`, and `request=` a one-sentence summary of what the diagram should depict followed by `facts: <bullet list>` (terminology parity with the host section is the only contract). Pass `exemplar_override_dir=<spec_path>/.claude/templates/spec.diagrams/<compound-key>` if that directory exists (`<exemplar_override_dir>/diagram.mermaid/diagram-<kind>.md`). Mark the task `completed` with the skill's return value as the outcome word (`created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`).

`lazycortex-diagram:lazy-diagram.draw` is idempotent: a fence with the same `%% intent:` line is replaced in place when its body bytes differ, returns `unchanged` when bytes match, or appends a new fence when the intent line differs. Sections whose prose was NOT rewritten in Step 4 leave their existing diagrams untouched (they never enter `seams[]`).

## Step 5 — Reconcile asset status

Walk every asset folder under the product's `asset_categories` (e.g. `<spec_path>/features/<feat>/`, `<spec_path>/changes/<change-name>/`, `<spec_path>/bugs/<bug-name>/`). The flat-gate status model is owned by `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md` — the five top-level booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay live on the asset's status folder-note. There is no `gates:` dict, no `stage:`, no `awaits_human:`, no `## Workflow` section. The ONLY gate mutation channel is `/spec.flip-gate`; the ONLY per-file-stage channel is `/spec.set-stage`.

**Missing folder-note (scaffold)**

If an asset folder has no status folder-note, scaffold one from `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/asset-note.md` (where `<category>` is the asset's category, derived from its enclosing folder). The category-level template carries the same flat-gate body for every built-in and operator-defined category. Substitute `{{product_tag}}`, `{{slug}}` (the asset folder basename), and the resolved `{{iconize_icon}}` / `{{iconize_color}}` (from the category's config). Write it at `<asset-folder>/<asset-folder-basename>.md` (basename matches the parent folder per the status-file invariant). Append a `## History` line: `- <YYYY-MM-DD> — spec.sync-with-code · status folder-note scaffolded`. Do NOT infer or set any gate to `true` during the scaffold — the gate proposals below are a separate, operator-confirmed step.

**Code-grounded gate proposal**

For each asset (freshly scaffolded or pre-existing), inspect whether the code that implements it objectively landed in the source repo's default branch (the synced commits in Steps 2–4 touch the asset's documented routes/functions/components, AND those commits are on the default branch — not an open feature branch). When that holds and `spec_develop_done` is currently `false`, PROPOSE the flip via one `AskUserQuestion` (full-context block per the Wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`): name the asset, the commits that evidence the landing, and that confirming runs `/spec.flip-gate <asset> spec_develop_done`. On confirm, invoke via the `Skill` tool:

```
Skill(skill: "lazycortex-specs:spec.flip-gate", args: "<asset-dir> spec_develop_done")
```

`flip_gate` enforces its own precondition (`spec_plan_done` true) and refuses cleanly if unmet — surface its refusal verbatim, do NOT work around it. Never propose `spec_tests_passing` or `spec_released` here — `spec_tests_passing` needs a green test report and `spec_released` is owned by `/spec.finalize-branch`. The flip's audit trail lives in the status folder-note's `## History` (written by `spec.flip-gate` itself) and in this skill's run log.

**Per-file stage correction**

When an authored doc's per-file `spec_stage` is objectively wrong against the code reality (e.g. the design doc is `draft` but its feature has fully shipped, or a doc is missing a `spec_stage` entirely), PROPOSE the correction via `AskUserQuestion` and on confirm apply it through the `Skill` tool:

```
Skill(skill: "lazycortex-specs:spec.set-stage", args: "<doc-path> <stage>")
```

The closed stage set is `empty | draft | approved | rejected | cancelled` — owned by `spec.set-stage`. `spec.set-stage` keeps the `## History` line and the `spec/<stage>` tag mirror in sync; never rewrite `spec_stage` frontmatter directly. Docs missing on disk are skipped — this skill never creates placeholder authored docs during sync.

If `spec_cancelled: true` on the folder-note, skip both proposals for that asset — cancelled assets never advance. Every change in this step is operator-confirmed; this skill writes no gate or stage silently.

## Step 5a — Reconcile branch pins

After code changes are applied (or even when no code changes were needed), walk every markdown file under `<spec_path>` looking for `spec_source_branches:` frontmatter. For each file with at least one pin, run the **Pin Reconciliation** primitive from `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`:

- Merged pins → rewrite URLs to the default branch and remove the `<repo-key>` entry.
- Deleted pins → rewrite URLs to the default branch and remove the `<repo-key>` entry ("deleted = merged").
- Open pins → leave the file untouched; URLs keep pointing at the open branch.

Auto-apply (no prompt — the primitive never rewrites an unmerged pin). The list of rebased files lives in this skill's run log; no separate product changelog is written. The mandatory `fetch --prune` already ran in Step 2; the primitive relies on those fresh refs.

## Step 6 — Update state

Write `.state/spec-sync-<product-key>.json` with current HEAD and today's date.

## Step 7 — Run doctor

After sync, run `/spec.doctor` (structure, wikilinks, gate/stage consistency, staleness) to catch any issues the sync may have introduced. Report but don't auto-fix — the operator just approved sync changes and should review doctor findings separately.

## Verify

The declared diagram seam set for one sync run is **runtime-computed in Step 4a**: it is exactly the list of `(target_file, anchor_section, kind)` triples produced from the `(target_file, anchor_section)` pairs whose prose was rewritten in Step 4 and that have an entry in the seam-kind map. Anchors not in the map are not seams; sections whose prose was not rewritten are not seams.

For every seam in `seams[]`, the corresponding `Step 4b` child task `diagram <relative-path>:<anchor>:<kind>` MUST be `completed` with one of the legal outcome words: `created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`. Any task still `pending` or carrying a non-vocabulary outcome is a Verify failure — re-execute the missing seam.

Then diff `seams[]` against the run logs `lazycortex-diagram:lazy-diagram.draw` actually emitted under `.logs/claude/lazy-diagram.draw/` during this session (filtered by today's UTC timestamp range). Each entry in `seams[]` must appear at least once with `target_file`, `anchor_section`, and `kind` matching the computed triple. Any computed seam missing from the logs, or any logged seam not in `seams[]`, is a Verify failure. `unchanged` is a successful seam invocation, not a missing seam — the diff treats it as present.

When `seams[]` is empty (no prose was rewritten in Step 4), Verify passes trivially — log outcome `no-seams-this-run` for `Step 4a` and `Step 4b` and continue.

The seam-kind map in Step 4a is owned by the parallel definitions in `spec.create-from-code` / `spec.create-asset` Verify sections. If any of those add or rename a seam, update Step 4a's table here in the same edit.

## Failure modes

- **`/spec.sync-with-code` refuses naming an unregistered product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/spec.product-config`, then re-invoke.
- **`/spec.sync-with-code` no-ops on a design-only product** — the product has no `source` block → attach a repo via `/spec.product-config` (edit mode), then re-invoke.
- **`/spec.sync-with-code` aborts: "fetch failed"** — `git fetch --prune` failed for the product's source repo (network, auth, or no remote) → fix connectivity or credentials and re-run; the skill never reconciles branch pins against stale refs.
- **A proposed `spec_develop_done` flip is refused by `flip_gate`** — the gate's precondition (`spec_plan_done` true) does not hold → settle the plan first (`spec_plan_done` derives from `plan.md` approval), then re-run.

## Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.sync-with-code/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.sync-with-code)`, then `Write` the file — never chain. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`. Body: `# spec.sync-with-code` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list AND one line per dynamically-created `Step 4b` child task with its outcome word — a missing line is a bug.

## Key Rules

- **Resolve via settings** — products live in `lazy.settings.json[products]`; resolve with `resolve-product by-key`. Refuse an unregistered product; no-op a design-only one (no `source`).
- **Respect file roles** — per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, source URLs belong in `tech` docs and asset-level `plan` docs only. Sync never inserts URLs into design docs.
- **Flat gates only** — five `spec_*` booleans + `spec_cancelled` on the status folder-note. The ONLY mutation channel is `/spec.flip-gate`; this skill proposes flips (operator-confirmed) and never edits gate frontmatter directly. No `gates:` dict, no `stage:`, no `awaits_human:`, no `## Workflow`.
- **Per-file stages via `spec.set-stage`** — closed set `empty | draft | approved | rejected | cancelled`; never rewrite `spec_stage` frontmatter directly.
- **Scaffold, don't infer** — a missing status folder-note is scaffolded with all gates `false`; code-grounded `spec_develop_done` flips and stage corrections are separate, operator-confirmed proposals.
- **Never delete without asking** — if a function/route was removed from code, flag it and ask before removing from the tech doc.
- **Preserve manual additions** — design docs may contain hand-written sections (Roadmap, Known Limitations). Never touch these during sync; surface behavior-level change candidates and let the operator edit the design doc.
- **Diff, don't rewrite** — use `Edit` to update specific sections, not `Write` to overwrite the whole file.
- **Delegate heavy reads** — when the change set is large, fan out to parallel Explore agents; main session synthesizes and asks.
