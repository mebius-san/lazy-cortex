---
name: lazy-spec.sync-with-code
description: Use when source code has changed since the last spec sync — compares a registered code-bound product's source commits against the last synced commit, updates the product tech doc, surfaces behavior changes for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections from the code state. No-ops on a design-only product. Given an `<asset>` argument instead of a bare product key, runs in asset mode instead: reconciles ONE feature/change asset's design.md / architecture.md against the current code by anchor (source-links, domain-groups, structure) rather than by commit diff, and never edits spec content silently — every drift finding becomes an `[!attention]` callout, a change-asset proposal, or a gate-correction proposal.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, Task, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent
---
# Spec Sync

Synchronize a product specification with source code changes since the last sync. Updates the product tech doc from the code, surfaces user-visible behavior changes to the operator for the product design doc, reconciles branch pins, and proposes flat-gate / per-file-stage corrections grounded in the observed code state — never silently. Per-asset history of these proposals lives in each touched status folder-note's `# History` H1 section, written by `lazy-spec.flip-gate` and `lazy-spec.set-stage`; per-document history of design/tech rewrites lives in the rewritten doc's `# History` H1 section. There is no separate product-wide changelog.

This skill runs in one of two modes, resolved from the argument in Step 0:

- **Product mode** (a bare product compound-key or a source path under one) — the flow below: commit-diff since `last_commit`, tech-doc updates, refresh of existing diagrams whose sections were rewritten, product-wide gate/stage reconciliation, branch-pin reconciliation, state update. Unchanged by this section.
- **Asset mode** (an `<asset>` argument naming one feature/change asset) — reconciles that ONE asset's `design.md` / `architecture.md` against the current code state by anchor, never by commit diff. Steps 1–4b, 5a, and 6 do not apply and are marked `skipped` with outcome `skipped-per-mode`; Step 5 runs its **Asset mode** subsection instead of the product-wide folder walk. There is no periodic routine for asset mode — see "Asset-mode triggers" below.

Product config, the five flat gates, per-file stages, source URLs, and pin reconciliation are all owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those mechanics; it calls the named primitives and references the reference docs.

## Execution discipline (MANDATORY — read before any action)

This skill has 11 ordered steps. The diagram seam set is **runtime-computed** — it depends on which sections were actually rewritten in Step 4 — so the preamble TaskCreate list contains one meta-step (`Step 4a — Compute runtime seam list`) that fans out into one dynamic task per discovered seam (`diagram <file>:<anchor>:<kind>` × N) before Step 5 begins. In **asset mode** (Step 0 resolves `mode = asset`), most of these 11 steps are `skipped-per-mode` — see each step's own **Asset mode:** note and Step 5's **Asset mode — anchor reconciliation** subsection. The executing agent MUST NOT skip, merge, reorder, or silently omit any step — including a mode-skip, which still needs its own explicit outcome, not a silent absence.

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

4. **Verify is a structural verifier** (per the `## Verify` section below). In **product mode** it diffs the runtime-computed seam list (the output of `Step 4a`) against the seams actually logged to `.logs/claude/lazy-diagram.draw/` for this run — any non-empty diff is a Verify failure. In **asset mode** the seam-diff logic does not apply (`seams[]` is always empty per Step 4a's `skipped-per-mode`); Verify instead checks that every anchor-driven finding from Step 5's Asset mode subsection produced exactly one of the legal outcome words.

5. **The same canonical step titles cover both modes** — asset mode does not get its own parallel TaskCreate list. Steps that don't apply are marked `skipped` with outcome `skipped-per-mode` (per-step notes above name exactly which); Step 5 branches internally on the resolved mode instead of duplicating itself as a separate step.

## Input

**Product mode**: a product compound-key (e.g. `dashboards`, `server-tester-chapter`) or a source path under a registered product. If omitted or ambiguous, ask which product to sync.

**Asset mode**: an `<asset>` argument naming one feature/change asset — a status folder-note path, an asset directory, `<product> <category>/<slug>`, or any token the product resolver can map to one asset folder `<spec_path>/<category>/<slug>/` (same resolution the `lazy-spec.flip-gate` Input contract uses). Bug assets are out of scope for asset mode — they carry no `design.md` / `architecture.md` to reconcile; refuse naming the asset and pointing at product mode's per-asset gate proposals instead.

## Step 0 — Resolve the product

Resolve the product record:

```bash
lazycortex-specs resolve-product by-key <product>
```

The command prints `{"key": "<product>", "record": <record-or-null>}`. The record (when present) carries `spec_path` (required, vault-relative), optional `source` (`{ repo, paths }`), optional `language` (defaults to `en`), and optional `asset_types` / `tool_types` (each merged key-by-key over the plugin's shipped set).

Branch on the record:

- **`record` is `null`** — the product is not registered. Refuse with a message naming `<product>` and telling the operator to run `/lazy-spec.product-config` first. Do NOT proceed.
- **`record` present but no `source` block** — the product is design-only (specs ahead of code, no code to sync). No-op with the message: "product is design-only — no code binding to sync; use /lazy-spec.product-config to attach a repo." Do NOT proceed.
- **`record` present with a `source` block** — capture `spec_path`, `source.repo`, `source.paths`, `language` (default `en`), and the visible `asset_types` names. Resolve `source.repo` via the `lazy-spec.resolve-repo` primitive to get `{ local_path, branch, host, owner, repo, forge, base_url, … }`. All source URLs emitted by this skill go through `lazy-spec.source-url(<repo-key>, …)` — never inline forge-specific path schemes. Continue.

**Resolving the mode.** If the input names an asset (not a bare product key or product-scoped source path — see Input above), resolve it to one asset folder `<spec_path>/<category>/<slug>/` the same way `lazy-spec.flip-gate` does, still requiring the OWNING product's `source` block per the branches above (asset mode compares against code — a design-only product has nothing to compare against, same refusal). Refuse a bug-category match (no `design.md` / `architecture.md`). Confirm `design.md` exists (`architecture.md` is optional — present only on a code-bearing feature/change). Absent (e.g. an `--empty`-scaffolded asset with no design authored yet) → refuse, outcome `no-design-doc`: "`<asset>` has no `design.md` yet — nothing to compare against code; author and approve `design.md` first, or re-invoke in product mode." Do NOT proceed. Present → set `mode = asset`, carrying `asset_dir`, `design_path`, and `architecture_path` (when present) forward. Otherwise `mode = product` — the flow below is unchanged.

All narrative prose this skill writes (folder-note `# History` lines, user-facing summaries presented via `AskUserQuestion`) is rendered in the product's `language` per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`. Frontmatter keys/values, role words, fixed section headers, wikilinks, URLs, file paths, and gate names stay English.

## Step 1 — Determine scope

**Asset mode:** skipped, outcome `skipped-per-mode` — asset mode reads only the ONE resolved asset's `design.md` / `architecture.md` (already in hand from Step 0), never the product-level design/tech docs or a commit range. Go to Step 5.

1. Read the product design doc (`<spec_path>/design.md` — behavior) and product tech doc (`<spec_path>/tech.md` — code architecture) per `${CLAUDE_PLUGIN_ROOT}/references/`. The design doc describes WHAT; the tech doc describes the code. This skill mostly touches the tech doc; it only flags design-doc changes to the operator for their decision.
2. Read `.state/lazy-spec.sync-<product-key>.json` to get `last_commit`. When that file is absent but the pre-convention `.state/spec-sync-<product-key>.json` exists, rename it first (`Bash(mv ...)`) and read the result — the checkpoint follows the `.state/` naming convention (`<namespace>.<name>.json`), and the rename joins Step 6's commit pathspec:

   ```json
   { "last_commit": "<commit hash>", "last_sync": "<ISO date>", "source_paths": ["<source.paths>"] }
   ```

   If the state file doesn't exist, this is a first sync — ask the operator for the commit to start from (or default to the first commit touching `source.paths` after the product folder-note's git creation time).
3. Get current source repo HEAD: `git -C <repo-config>.local_path log -1 --format=%H`.
4. If `last_commit` == current HEAD → print "Already synced at `<short-hash>`" and stop.

## Step 2 — Get relevant changes

**Asset mode:** skipped, outcome `skipped-per-mode` — no commit range in asset mode.

1. Run `git -C <repo-config>.local_path fetch --prune <remote>` (prefer `origin`; else the first remote `git -C <local_path> remote` returns). If the fetch fails (network, auth, missing remote) → abort the whole sync with a clear error; never operate on stale branch state — Step 5a's pin reconciliation depends on fresh refs.
2. Run `git -C <repo-config>.local_path log --oneline <last_commit>..HEAD -- <source.paths>` (one `--` path argument per entry in `source.paths`) to get commits touching this product's source.
3. If no commits → still run Step 5a (pins may need reconciling against the freshly-fetched refs), update the state file with current HEAD, print "No code changes to `<source.paths>`", and stop after Step 5a + state + log.
4. For each commit, run `git -C <repo-config>.local_path diff <commit>~1..<commit> -- <source.paths>` to get the specific diff.

## Step 2a — Delegate categorization to parallel agents

**Asset mode:** skipped, outcome `skipped-per-mode`.

If the commit list is large (>5 commits) or touches many files, delegate analysis. In a single message, launch up to 3 parallel Explore agents (`subagent_type: "Explore"`, `mode: "dontAsk"`, read-only), each covering a subset of commits or a concern:

- **Agent A — structural changes**: routes, classes, functions (added / removed / signature-changed).
- **Agent B — data & templates**: data structure changes, template/UI changes, constant changes.
- **Agent C — behavior signals**: commit messages + diffs hinting at user-visible behavior changes (these surface as design-doc candidates).

Each agent returns a structured summary of findings with commit hashes per the parallel-scan coordinator pattern in `claude/lazycortex-core/references/lazy-core.parallel-scan.md`. The main session synthesizes them. For small commit lists, do the analysis inline.

## Step 3 — Analyze each commit

**Asset mode:** skipped, outcome `skipped-per-mode`.

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

**Asset mode:** skipped, outcome `skipped-per-mode` — no tech-doc or design-doc rewrite here; asset mode's drift findings are signals (Step 5's Asset mode subsection), never a routed rewrite.

Changes go to different files depending on their nature. Per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`:

- **Code-level changes** (routes, functions, signatures, new/removed files, constants) → update the product tech doc. If it does not yet exist, create it from the current state before applying updates.
- **User-visible behavior changes** (identified by Agent C or by inspection of diffs that change what the user sees) → surface to the operator as "This commit appears to change user-facing behavior X. Update the product design doc?" Never silently rewrite the design doc — always ask.
- **Source URLs** must never appear in design docs. If a code change needs documenting with a source link, it belongs in the tech doc or, for asset-level implementation detail, in the asset's `code-plan.md` (when one exists — it is opt-in, not scaffolded by default).

Tech-doc edits:
- **Added routes/functions**: add to the appropriate table/section in the tech doc.
- **Removed routes/functions**: ask before removing from the tech doc (mark as candidate for deletion).
- **Changed values**: update the documented value in the tech doc.
- **New files**: add a new subsection under Components in the tech doc.
- **Removed files**: ask before removing the component subsection from the tech doc.

Present all planned changes to the operator before applying: show a summary grouped by target file (tech-doc edits vs. design-doc candidates). Apply tech-doc edits after approval; apply design-doc edits only on per-item approval.

After all approved prose rewrites land, record a list of `(target_file, anchor_section)` pairs that were actually rewritten in this run. This list is the input to Step 4a.

## Step 4a — Compute runtime seam list

**Asset mode:** skipped, outcome `skipped-per-mode` — Step 4 produced no rewritten sections to seam.

A seam here is **refresh-only**: a rewritten section whose heading ALREADY carries a drawer-authored fence (`Grep(pattern: "^%%\\{init:", …)` under the anchor proves it). Rewritten prose invalidates the picture that illustrated it, so the existing fence is redrawn; a section with no fence gets none — creating diagrams is not this skill's mandate (the operator asks via `/lazy-diagram.draw`, the writing experts follow `lazy-core.markdown-style` § Figures). For every rewritten `(target_file, anchor_section)` pair that carries a fence, look up the canonical kind for that anchor:

| Role | Anchor | kind |
|---|---|---|
| design (product) | `## Behavior` | `flow` |
| tech (product) | `## Architecture` | `architecture` |
| tech (product) | `## Components` | `class` |
| design (asset) | `## User Flow` | `flow` |
| design (asset) | `## Changes` | `flow` |

Anchors not in this map, and anchors without an existing fence, are NOT seams — they get no diagram call. Build the runtime seam list `seams[] = [{target_file, anchor_section, kind, facts: <bullet list extracted from the just-rewritten section>}, …]`. If `seams[]` is empty, record outcome `no-seams-this-run` for `Step 4a` and skip `Step 4b` with the same outcome.

## Step 4b — Dispatch diagram per computed seam

**Asset mode:** skipped, outcome `skipped-per-mode` — `seams[]` is empty per Step 4a.

Before invoking the skill, call `TaskCreate` once per entry in `seams[]` with the canonical title `diagram <relative-path>:<anchor>:<kind>` (path is `<target_file>` relative to the vault root). Then, for each task in declaration order, mark `in_progress`, invoke `lazycortex-diagram:lazy-diagram.draw` (via the `Skill` tool) with the matching `target_file`, `anchor_section`, `kind`, `format="mermaid"`, and `request=` a one-sentence summary of what the diagram should depict followed by `facts: <bullet list>` (terminology parity with the host section is the only contract). Pass `exemplar_override_dir=<spec_path>/.claude/templates/spec.diagrams/<compound-key>` if that directory exists (`<exemplar_override_dir>/diagram.mermaid/diagram-<kind>.md`). Mark the task `completed` with the skill's return value as the outcome word (`created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`).

`lazycortex-diagram:lazy-diagram.draw` is idempotent: a fence with the same `%% intent:` line is replaced in place when its body bytes differ, returns `unchanged` when bytes match, or appends a new fence when the intent line differs. Sections whose prose was NOT rewritten in Step 4 leave their existing diagrams untouched (they never enter `seams[]`).

## Step 5 — Reconcile asset status

**Product mode:** walk every asset folder under `<spec_path>` — the folders named by the `default_path` of each type the product declares in `asset_types` (`features/`, `changes/`, `bugs/`, plus whatever the product added), and any other location an asset was placed in. The folder is a place, not a fact: an asset's boundary is the folder whose folder-note carries `spec_role: status`, its kind is that note's `spec_asset_type`, and assets may nest — so a folder sitting inside another asset's folder is its own asset all the same. The flat-gate status model is owned by `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md` — the five top-level booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay live on the asset's status folder-note. There is no `gates:` dict, no `stage:`, no `awaits_human:`, no `## Workflow` section. The ONLY gate mutation channel is `/lazy-spec.flip-gate`; the ONLY per-file-stage channel is `/lazy-spec.set-stage`.

**Missing folder-note (scaffold)**

A folder with no status folder-note has no recorded kind — `spec_asset_type` lives on the note that is missing — so the type cannot be read off the tree. Reverse-match the enclosing folder against the `default_path` of each type the product declares in `asset_types`; on exactly one match take that type, and on none or several `AskUserQuestion` which of the product's visible types the asset is (never guess from the folder name alone — the folder is a place, not a fact).

Scaffold the note from the template the 5-layer fallback resolves for that type (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` Part 1 § Template storage) — a type with no `asset-note.md` of its own lands on the type-agnostic base `${CLAUDE_PLUGIN_ROOT}/templates/spec.asset/asset-note.md`, which is why an operator-defined type needs no template folder at all. Whichever layer wins carries the same flat-gate body and the same three `{{...}}` tokens: substitute `{{product_tag}}` (derived from `spec_path` the same way `scaffold_asset.py`'s `_product_tag` does), `{{product}}` (the product's compound key), and `{{category}}` (the type name just settled — never the plural folder name; the template's `wiki_pinned_topics` frontmatter reads both). Also write `spec_asset_type: <type>` — it is the key everything downstream resolves the asset's law from. Then splice in the resolved `iconize_icon` / `iconize_color` frontmatter keys from the type's declaration — a post-substitution injection, the same as `scaffold_asset.py`'s `_inject_iconize`, NOT a `{{}}` token (the template carries none for these). The asset-folder basename becomes the file's own name and needs no token — `{{slug}}` does not appear in this template. Write it at `<asset-folder>/<asset-folder-basename>.md` (basename matches the parent folder per the status-file invariant). Append a `# History` line: `- <YYYY-MM-DD> — lazy-spec.sync-with-code · status folder-note scaffolded`. Do NOT infer or set any gate to `true` during the scaffold — the gate proposals below are a separate, operator-confirmed step.

**Code-grounded gate proposal**

For each asset (freshly scaffolded or pre-existing), inspect whether the code that implements it objectively landed in the source repo's default branch (the synced commits in Steps 2–4 touch the asset's documented routes/functions/components, AND those commits are on the default branch — not an open feature branch). `/lazy-spec.flip-gate` no longer checks `spec_develop_done`'s own precondition (`spec_plan_done` true) — it flips unconditionally once confirmed, refusing only a cancelled asset — so this skill checks it itself now: when the code-landed evidence holds, `spec_develop_done` is currently `false`, AND `spec_plan_done` already reads `true`, PROPOSE the flip via one `AskUserQuestion` (full-context block per the Wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md`): name the asset, the commits that evidence the landing, and that confirming runs `/lazy-spec.flip-gate <asset> spec_develop_done`. When `spec_plan_done` is still `false`, do NOT propose — report the asset as blocked on its code-plan gate instead. On confirm, invoke via the `Skill` tool:

```
Skill(skill: "lazycortex-specs:lazy-spec.flip-gate", args: "<asset-dir> spec_develop_done")
```

`spec_plan_done` itself is satisfied either by an approved/cancelled `code-plan.md` or by that file's absence (it is opt-in — see `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`); this skill never authors a `code-plan.md` to force it. Never propose `spec_tests_passing` or `spec_released` here — `spec_tests_passing` needs a green test report (and, when a `test-plan.md` exists, its approval — only `approved` waives, unlike `code-plan.md`'s `approved`-or-`cancelled`) and `spec_released` is owned by `/lazy-spec.finalize-branch`. The flip's audit trail lives in the status folder-note's `# History` section (written by `lazy-spec.flip-gate` itself) and in this skill's run log.

**Per-file stage correction**

When an authored doc's per-file `spec_stage` is objectively wrong against the code reality (e.g. the design doc is `draft` but its feature has fully shipped, or a doc is missing a `spec_stage` entirely), PROPOSE the correction via `AskUserQuestion` and on confirm apply it through the `Skill` tool:

```
Skill(skill: "lazycortex-specs:lazy-spec.set-stage", args: "<doc-path> <stage>")
```

The closed stage set is `empty | draft | approved | rejected | cancelled` — owned by `lazy-spec.set-stage`. `lazy-spec.set-stage` keeps the `# History` line and the `spec/<stage>` tag mirror in sync; never rewrite `spec_stage` frontmatter directly. Docs missing on disk are skipped — this skill never creates placeholder authored docs during sync.

If `spec_cancelled: true` on the folder-note, skip both proposals for that asset — cancelled assets never advance. Every change in this step is operator-confirmed; this skill writes no gate or stage silently.

**Asset mode — anchor reconciliation**

Skips the folder walk and the missing-folder-note scaffold above — those are product-mode-only (Step 0 already resolved the single asset, and asset mode never scaffolds a folder-note the operator hasn't reached through `lazy-spec.create-asset`). Everything else in this step — the code-grounded gate proposal and the per-file stage correction — still applies, scoped to `asset_dir` alone, with the evidence swapped from Steps 2–4's commit list (asset mode ran none) to the anchor walk below.

1. **Resolve anchors**, opportunistically — none is required, and a missing anchor kind is not a failure:
   - **Source-links** — `Grep` `asset_dir/code-plan.md` and `asset_dir/test-plan.md` (opt-in; either or both may not exist) for forge URLs built by `lazy-spec.source-url` (`<base_url>/blob/…`, `/-/blob/…`, `/src/…`, `/tree/…`, per the known-forges table in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md` Part 2). Each match names a `<path>` (and often a symbol in the surrounding prose) — the most precise anchor, pinned at authoring time. `design.md` / `architecture.md` never carry these themselves (forbidden by role — `lazy-spec.layout-protocol.md` Part 2); this is the one place asset mode reads a SIBLING doc for evidence about the design/architecture doc.
   - **Domain-groups** — for a term `design.md` / `architecture.md` uses to name a mechanic or concept, dispatch `Skill(skill: "lazycortex-wiki:lazy-wiki.domains", args: "term \"<term>\"")` (best-effort; skip silently on outcome `not-configured` — most repos have no `wiki.domains` set up). A match's file/excerpt names the `Domain(…)`-annotated code the term maps to.
   - **Structure** — for a component/module `design.md` / `architecture.md` names that no source-link or domain match covered, dispatch `Skill(skill: "lazycortex-wiki:lazy-wiki.structure", args: "query <best-guess-path>")` (best-effort; skip silently on outcome `no-map` / `no-match`) to locate the actual code area.
   - No anchor resolves at all (no code-plan/test-plan, no domain match, no structure match) → outcome `no-anchors` — report the doc as checked structurally only (its frontmatter/header shape still gets `lazy-spec.doctor`'s pass in Step 7) and skip straight to the code-grounded gate proposal / per-file stage correction below (they may still apply — a missing code-plan is itself evidence for `spec_plan_done`, per the existing rule above).
2. **Compare.** For each resolved anchor, `Read` the anchor-pointed source (the file/symbol a source-link names, the code a domain excerpt annotates, the area a structure slice describes) against what `design.md`'s `## Behavior` / `architecture.md`'s `## Module boundaries` (or `## Data & contracts`) actually claims — a described route/component/flow no longer present at the anchor, or code at the anchor doing something the doc never mentions. Agreement → no finding for that anchor; move on.
3. **On a discrepancy, pick exactly one of three outcomes — never a silent rewrite of `design.md` / `architecture.md` prose:**
   - **`[!attention]` on the doc** — the drift is real but doesn't yet need a plan: splice `> [!attention] code drift: <one-line description naming the anchor and what disagrees>` before the doc's `# Sources` heading (end-of-doc when absent) — the canonical shape and splice point `lazy-spec.request-protocol.md` § Body distribution rules already establishes for attach-target deltas (`> [!attention] change requested: <description>`) and the regression callout in `lazy-spec.coordination-playbook.md` Chapter 4 (`> [!attention] regression failed on <target> — […]`); general callout shape and hard-wrap rules per `lazy-core.markdown-style.md`. This is the ONLY body edit asset mode ever makes to `design.md` / `architecture.md`.
   - **Propose a change-asset** — the drift is big enough to need its own plan (a described flow the code no longer implements at all, not a one-line staleness): `AskUserQuestion` naming the asset, the discrepancy, and that confirming creates a change asset to plan the reconciliation. On confirm: `Skill(skill: "lazycortex-specs:lazy-spec.create-change", args: "<product> <proposed-slug>")`. On decline, fall back to the `[!attention]` callout above so the drift isn't lost.
   - **Propose a gate correction to the coordinator** — the drift is evidence a gate is wrong (the anchors show code landed on the default branch, or a doc whose `spec_stage` no longer matches what the anchors show): run the SAME "Code-grounded gate proposal" / "Per-file stage correction" primitives above, scoped to `asset_dir`, with this anchor walk as the landing evidence in place of Steps 2–4's commit list. Both primitives already commit through the status folder-note / doc frontmatter — the coordinator wakes on that commit per `lazy-spec.coordination-playbook.md`'s own wake triggers; there is no separate gate-correction channel to invent.
4. Record one outcome word per finding: `attention-written` | `change-proposed` | `gate-proposed` | `no-finding` | `no-anchors`. A run with findings across multiple anchors logs one outcome line per finding — Step 5 is `completed` once every resolved anchor produced one.

If `spec_cancelled: true` on the folder-note, skip the whole Asset mode subsection — cancelled assets never advance.

## Step 5a — Reconcile branch pins

**Asset mode:** skipped, outcome `skipped-per-mode` — pin reconciliation walks the whole product tree; asset mode touches one asset and never rewrites `spec_source_branches` (a key `design.md` / `architecture.md` may not even carry, per `lazy-spec.sources-protocol.md` Part 2).

After code changes are applied (or even when no code changes were needed), walk every markdown file under `<spec_path>` looking for `spec_source_branches:` frontmatter. For each file with at least one pin, run the **Pin Reconciliation** primitive from `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md`:

- Merged pins → rewrite URLs to the default branch and remove the `<repo-key>` entry.
- Deleted pins → rewrite URLs to the default branch and remove the `<repo-key>` entry ("deleted = merged").
- Open pins → leave the file untouched; URLs keep pointing at the open branch.

Auto-apply (no prompt — the primitive never rewrites an unmerged pin). The list of rebased files lives in this skill's run log; no separate product changelog is written. The mandatory `fetch --prune` already ran in Step 2; the primitive relies on those fresh refs.

## Step 6 — Update state

**Asset mode:** skipped, outcome `skipped-per-mode` — there is no per-asset sync-state file; `last_commit` tracking is product-wide and belongs to product mode only.

Write `.state/lazy-spec.sync-<product-key>.json` with current HEAD and today's date. The file is a tracked cross-machine checkpoint: fold its path (and the removal of a just-renamed `spec-sync-<product-key>.json`, when Step 1 migrated one) into the commit that carries this sync's changes — left dirty it halts the runtime daemon's clean-tree check.

## Step 7 — Run doctor

Runs in both modes. After sync, run `/lazy-spec.doctor` (structure, wikilinks, gate/stage consistency, staleness) to catch any issues the sync may have introduced. Report but don't auto-fix — the operator just approved sync changes and should review doctor findings separately.

## Verify

The declared diagram seam set for one sync run is **runtime-computed in Step 4a**: it is exactly the list of `(target_file, anchor_section, kind)` triples produced from the `(target_file, anchor_section)` pairs whose prose was rewritten in Step 4 and that have an entry in the seam-kind map. Anchors not in the map are not seams; sections whose prose was not rewritten are not seams.

For every seam in `seams[]`, the corresponding `Step 4b` child task `diagram <relative-path>:<anchor>:<kind>` MUST be `completed` with one of the legal outcome words: `created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`. Any task still `pending` or carrying a non-vocabulary outcome is a Verify failure — re-execute the missing seam.

Then diff `seams[]` against the run logs `lazycortex-diagram:lazy-diagram.draw` actually emitted under `.logs/claude/lazy-diagram.draw/` during this session (filtered by today's UTC timestamp range). Each entry in `seams[]` must appear at least once with `target_file`, `anchor_section`, and `kind` matching the computed triple. Any computed seam missing from the logs, or any logged seam not in `seams[]`, is a Verify failure. `unchanged` is a successful seam invocation, not a missing seam — the diff treats it as present.

Then check the artifact, not just the process — run it, do not attest. Every mermaid fence the drawer emits opens with an init directive on the fence's first line, so a hand-composed fence is detectable from the file alone. For each distinct `target_file` in `seams[]`, run `Grep(pattern: "^%%\\{init:", path: <target_file>, output_mode: "count")` and compare the count against the number of seams targeting that file with outcome `created` / `replaced` / `unchanged`. A lower count means a fence was hand-written instead of drawn — Verify failure; re-invoke `lazycortex-diagram:lazy-diagram.draw` for the affected seam rather than editing the fence.

When `seams[]` is empty (no prose was rewritten in Step 4), Verify passes trivially — log outcome `no-seams-this-run` for `Step 4a` and `Step 4b` and continue. In **asset mode**, `seams[]` is always empty (Step 4a is `skipped-per-mode`), so the seam-diff logic above never applies — Verify instead checks Step 5's Asset mode subsection: every discrepancy the anchor walk found MUST have exactly one of `attention-written` | `change-proposed` | `gate-proposed` recorded against it (a finding with no outcome word is a Verify failure — re-run Step 5's decision for that finding), and a run with `no-anchors` or zero discrepancies passes trivially.

The seam-kind map in Step 4a is owned by the parallel definitions in `lazy-spec.create-from-code` / `lazy-spec.create-asset` Verify sections. If any of those add or rename a seam, update Step 4a's table here in the same edit.

## Failure modes

- **`/lazy-spec.sync-with-code` refuses naming an unregistered product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/lazy-spec.product-config`, then re-invoke.
- **`/lazy-spec.sync-with-code` no-ops on a design-only product** — the product has no `source` block → attach a repo via `/lazy-spec.product-config` (edit mode), then re-invoke.
- **`/lazy-spec.sync-with-code` aborts: "fetch failed"** — `git fetch --prune` failed for the product's source repo (network, auth, or no remote) → fix connectivity or credentials and re-run; the skill never reconciles branch pins against stale refs.
- **An asset never gets a `spec_develop_done` proposal despite landed code** — `spec_plan_done` doesn't read `true` yet, so Step 5's own readiness check skips it (the primitive itself no longer refuses this) → settle the dev plan first (`spec_plan_done` derives from `code-plan.md` approval when one exists, or from its absence, or let `spec.coordinator` derive it), then re-run.
- **`/lazy-spec.sync-with-code <asset>` refuses naming a bug asset** — asset mode only reconciles `design.md` / `architecture.md`, and a bug folder ships neither → use product mode's per-asset gate proposals for a bug instead (Step 5, product mode).
- **`/lazy-spec.sync-with-code <asset>` reports `no-design-doc`** — the asset has no `design.md` yet (e.g. still `--empty`-scaffolded) → author and approve `design.md` first, or re-invoke in product mode instead.
- **Asset mode reports `no-anchors` on every run** — the asset has no `code-plan.md` / `test-plan.md` (source-links), no `wiki.domains` configured (domain-groups), and no `docs/structure.md` (structure) → this is a valid, not a failed, outcome; the doc still gets `lazy-spec.doctor`'s structural pass in Step 7. Configure `wiki.domains` / run `/lazy-wiki.structure rebuild` to sharpen future runs, or author a `code-plan.md` for precise source-links.

## Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.sync-with-code/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-spec.sync-with-code)`, then `Write` the file — never chain. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`. Body: `# lazy-spec.sync-with-code` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the preamble's canonical list AND one line per dynamically-created `Step 4b` child task with its outcome word — a missing line is a bug. **Asset mode:** the same rule applies with the mode's own outcome vocabulary — one line per `skipped-per-mode` step, plus one line per anchor finding from Step 5's Asset mode subsection (`attention-written` | `change-proposed` | `gate-proposed` | `no-finding` | `no-anchors`).

## Asset-mode triggers

There is no periodic routine for asset mode — no `routines[]` registration, nothing the daemon polls. It runs only when one of these calls it:

- **On-demand** — the operator invokes `/lazy-spec.sync-with-code <asset>` directly, e.g. before trusting a design/architecture doc that hasn't been touched in a while.
- **From `/lazy-spec.drive`** — when the drive loop is about to act on a feature/change asset's design or architecture doc and wants fresh code-truth first, it invokes this skill in asset mode as a pre-step rather than assuming the doc is current.
- **At `spec.coordinator` decision points** — before the coordinator proposes a gate flip or narrates a `# Status brief` that depends on code state, per `lazy-spec.coordination-playbook.md`; the coordinator dispatches this skill in asset mode rather than trusting the doc's prose unchecked.

## Key Rules

- **Resolve via settings** — products live in `lazy.settings.json[products]`; resolve with `resolve-product by-key`. Refuse an unregistered product; no-op a design-only one (no `source`).
- **Respect file roles** — per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, source URLs belong in `tech` docs and asset-level `code-plan` / `test-plan` docs only. Sync never inserts URLs into design docs.
- **Flat gates only** — five `spec_*` booleans + `spec_cancelled` on the status folder-note. The ONLY mutation channel is `/lazy-spec.flip-gate`; this skill proposes flips (operator-confirmed) and never edits gate frontmatter directly. No `gates:` dict, no `stage:`, no `awaits_human:`, no `## Workflow`.
- **Per-file stages via `lazy-spec.set-stage`** — closed set `empty | draft | approved | rejected | cancelled`; never rewrite `spec_stage` frontmatter directly.
- **Scaffold, don't infer** — a missing status folder-note is scaffolded with all gates `false`; code-grounded `spec_develop_done` flips and stage corrections are separate, operator-confirmed proposals.
- **Never delete without asking** — if a function/route was removed from code, flag it and ask before removing from the tech doc.
- **Preserve manual additions** — design docs may contain hand-written sections (Goals, Principles, Known Limitations). Never touch these during sync; surface behavior-level change candidates and let the operator edit the design doc.
- **Diff, don't rewrite** — use `Edit` to update specific sections, not `Write` to overwrite the whole file.
- **Delegate heavy reads** — when the change set is large, fan out to parallel Explore agents; main session synthesizes and asks.
- **Asset mode never edits `design.md` / `architecture.md` prose** — a drift finding becomes exactly one of an `[!attention]` callout, a change-asset proposal, or a gate-correction proposal (Step 5's Asset mode subsection); the `[!attention]` splice is the only body edit it ever makes, and even that never touches existing content — it only appends the callout.
- **Asset mode has no periodic routine** — no `routines[]` entry; it runs on-demand, from `/lazy-spec.drive`, or at a `spec.coordinator` decision point (see "Asset-mode triggers" above).
