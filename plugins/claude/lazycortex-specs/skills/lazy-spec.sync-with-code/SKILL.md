---
name: lazy-spec.sync-with-code
description: "Use when source code has changed and the spec tree should match it again — 'sync the specs with the code', 'the code moved on, update the spec' — for the whole tree, one code-bound product, or one asset. Every edit stays uncommitted until the operator reads the diff and says yes. Pick /lazy-spec.create-from-code instead when no spec exists yet."
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, AskUserQuestion, Agent
dirty-tree-waiver: "spec rewrites and the sync checkpoints stay uncommitted until the operator has read the diff and allowed the commit"
---
# Spec Sync

Bring the spec tree in line with the code. The code is the truth: whatever an authored document says that the code no longer does is rewritten, whatever the code does that no document says is written down, a code unit no asset covers gets an asset, and an asset whose code is gone is deleted. The run edits freely and commits nothing until the operator has read the whole diff and allowed the commit.

Product config, the five flat gates, per-file stages, source links and the decisions registry are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill calls the named primitives and references the reference docs, never inlines their mechanics.

## Execution discipline (MANDATORY — read before any action)

This skill has 14 ordered steps. The diagram seam set is **runtime-computed** — it depends on which sections the writers actually rewrote — so the ledger carries one meta-step (`Step 6 — Compute runtime seam list`) whose output fans out into one dynamic task per seam before `Step 7` completes. The executing agent MUST NOT skip, merge, reorder, or silently omit any step — a step that does not apply to the resolved scope still records its own outcome.

1. **Before calling any other tool**, write out the step ledger — one line per static step below, each marked `pending`. Use these canonical titles verbatim:
   - `Step 0 — Resolve the scope`
   - `Step 1 — Determine each product's window`
   - `Step 2 — List changes`
   - `Step 3 — Map the code against the tree (parallel agents)`
   - `Step 4 — Ask before touching approved assets`
   - `Step 5 — Rewrite the documents (parallel writers)`
   - `Step 6 — Compute runtime seam list`
   - `Step 7 — Dispatch diagram per computed seam` (expands into one ledger line per seam right after Step 6, titled `draw-diagram <relative-path>:<anchor>:auto`)
   - `Step 8 — Create assets for uncovered code`
   - `Step 9 — Delete assets whose code is gone`
   - `Step 10 — Mark abandoned decisions obsolete`
   - `Step 11 — Propose gate and stage corrections`
   - `Step 12 — Update state`
   - `Step 13 — Run doctor and verify`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND produced an outcome word. A dynamic `Step 7` child records the `lazycortex-diagram:lazy-diagram.draw` return value (`created` | `replaced` | `unchanged` | `skipped-below-threshold` | `failed:<reason>` | `split-into-N`); an empty seam list records `no-seams-this-run` for Steps 6 and 7.
3. **Do not reach the Report until the ledger shows every prior task `completed`.** A still-`pending` task — dynamic children included — is a bug; execute it first.
4. **The Report is a structural verifier** — one line per task above, dynamic children included.

## Input

`/lazy-spec.sync-with-code [<scope>] [--full]`

- **No scope** — the whole tree: every product under `lazy.settings.json[products]` that carries a `source` block.
- **A product compound-key, or a source path under one** — that product and every product nested under its `spec_path`.
- **An asset** — a status folder-note path, an asset directory, or `<product> <product-relative-path>`, resolved the way `lazy-spec.flip-gate` resolves its asset argument: that one asset, against its owning product's code. A bug asset is accepted — its folder-note précis and any document it carries are reconciled like any other.
- **`--full`** — compare every document in scope with the current code instead of only what the commit window touched. A product with no checkpoint yet always runs full.

A path matching several products, or a bare key matching none, is asked — context first: where (`/lazy-spec.sync-with-code · Input`), found (the candidate keys under `lazy.settings.json[products]`), why asking (the argument names no single scope), answers (one option per key, plus `whole tree`; nothing persisted); then `AskUserQuestion` header "Sync scope", question "Which part of the spec tree should this sync run against?", one option per candidate with its `spec_path` as description.

## Step 0 — Resolve the scope

For each product key the input reaches, resolve its record:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" resolve-product by-key <product>
```

- **`record` is `null`** — refuse naming `<product>` and pointing at `/lazy-spec.product-config`. A whole-tree run never reaches this branch: it lists only registered keys.
- **No `source` block** — a design-only product: skip it with outcome `design-only` (a single-product run stops here with that message).
- **`source` present** — capture `spec_path`, `source.paths`, `language` (default `en`) and the visible `asset_types`. The code lives in this repository: every `source.paths` entry is relative to its root, and every git command below runs in it. Every source link the run writes goes through `lazy-spec.source-url`.

A product owns its `spec_path` subtree **minus** every nested product's `spec_path`: each nested product is its own unit of work in the steps below, so no document is reconciled twice. In asset scope, the unit is the one asset folder (its nested assets excluded), and the owning product supplies `source` and `language`.

Outcome: `resolved:<N> products` (or `resolved:asset`).

## Step 1 — Determine each product's window

Per product, read its checkpoint through the verb:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" sync-state read <product-key>
```

It prints one JSON line: `checkpoint` holds `last_commit`, `last_sync`, `source_paths`, or `null` when the product has none yet; a non-null `renamed_from` means the verb moved a pre-convention file onto the current name, and Step 12's write reports that old path for the commit.

- **Checkpoint present, no `--full`** — the window is `last_commit..HEAD`. When `last_commit` equals HEAD the product records `already-synced` and drops out of Steps 2–11.
- **No checkpoint, or `--full`** — the product runs **full**: Step 3 compares every document of the product's subtree with the current code, whatever changed when.

Asset scope always runs full on its one asset and writes no checkpoint.

Outcome: `windows:<N> window, <M> full, <K> already-synced`.

## Step 2 — List changes

For each window product: `git log --oneline <last_commit>..HEAD -- <source.paths>` (one `--` argument per `source.paths` entry). **Follow moves of the source tree:** `git log --format=%H --diff-filter=R -M --name-status <last_commit>..HEAD`, unfiltered, and for every `R` line whose destination lies under a `source.paths` entry add `git log --oneline <last_commit>..<rename-commit>~1 -- <old-prefix>`. A window product with no commits records `no-changes` and drops out of Steps 3–11.

Outcome: `listed:<N> commits across <M> products`.

## Step 3 — Map the code against the tree (parallel agents)

One read-only agent per product unit (`subagent_type: "Explore"`, `mode: "dontAsk"`), at most 4 dispatched in one message, the next batch after the previous returns, per `lazycortex-core`'s `references/lazy-core.parallel-scan.md`. Each prompt carries: the product key, its `spec_path`, the subtrees excluded as nested products, `source.paths`, the commit list (window) or `full`, and the report contract below.

Each agent reads every status folder-note (`spec_role: status`) and every authored document in its subtree — `vision.md`, `design.md`, `architecture.md`, `use-cases.md`, `ui-design.md`, the product-level `tech.md`, each folder-note's `# Summary` précis, and `decisions.md` — and the code they describe: in window mode the code the commits touched, in full mode the whole of `source.paths`. It reports:

```markdown
## scan: <product-key>

### findings
- [DRIFT] <doc-path> | <section> — <what the document states> ≠ <what the code does>
- [GAP] <doc-path> | <section> — <behaviour the code has and the document does not describe>
- [UNCOVERED] <candidate-slug> | <one-line purpose>
  placement: <folder under spec_path where its sibling code's assets live, or root>
  evidence:
    - <file-path> — <symbol or route group>
- [GONE] <asset-dir> — <the code it described, and the commit that removed it or "absent">
- [DECISION] <decisions.md> <D-id> — <the choice it records> ≠ <what the code does now> | origin: <as-built | design>
- [TARGET] <asset-dir> — <D-ids and document sections stating a reviewed target design the code does not implement yet>
- [APPROVED] <asset-dir> — <doc names whose spec_stage is approved>
- [GATE] <release-dir> — spec_develop_done <v>, spec_plan_done <v>, spec_cancelled <v>; commits <hashes> implement its spec_includes
- [GATE] <asset-dir> — implemented outside a release; commits <hashes> implement it   (a design-only asset carries no develop or plan gate)

### summary
drift: <n> gap: <n> uncovered: <n> gone: <n> decisions: <n>
```

Rules every agent applies:

- **The code is the truth.** A finding states what the code does, read from the code — never from a commit message, a comment the code contradicts, or another document.
- **Which document a fact belongs to** follows `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md` and `lazy-spec.doc-height-protocol.md`: what an asset does goes into that asset's documents, what the product does as a whole into the product's, the technical requirements and infrastructure decisions into the product `tech.md` — never the same fact at two heights.
- **`tech.md` findings** cover the document's own role: the technical requirements and infrastructure decisions — stack, platforms, runtime floors, external dependencies, constraints, boundaries. Every statement of `tech.md` the code contradicts is a `[DRIFT]` — a wrong version floor, a dependency added or dropped, a platform, a mechanism the document describes that does not exist or works differently. A stack-level fact the code introduces and the document lacks — a new external tool, a new runtime requirement — is a `[GAP]`. A code-level change that alters no requirement is never a `tech.md` finding: it goes to the Report only. `tech.md` is not a mirror of the code; no finding ever asks it to list functions, verbs or files.
- **`[UNCOVERED]`** is a feature-sized unit by the candidate heuristics of `lazy-spec.create-from-code`'s Agent D contract, and only when no existing asset already describes it. **`[GONE]`** is an asset none of whose described behaviour exists in the code any more; an asset with part of its behaviour gone takes `[DRIFT]` instead.
- **`[TARGET]`** marks an asset whose disagreement with the code comes from a reviewed target design rather than from stale description: a `decisions.md` record whose `Origin:` links a document (promoted from an approved design, not `as-built`) that the code contradicts, together with the document sections that state the same design. Every `[DRIFT]`, `[GAP]` and `[DECISION]` finding of such an asset is reported as usual and also listed under its `[TARGET]` line.
- A cancelled asset (`spec_cancelled: true`) is reported by no finding at all.

The main session merges the reports into one finding list per product. Outcome: `mapped:<drift>/<gap>/<uncovered>/<gone>/<decisions>`.

## Step 4 — Ask before touching approved assets

An asset reported `[APPROVED]` that also carries a `[DRIFT]`, `[GAP]`, `[GONE]` or `[DECISION]` finding is asked **once for the whole asset**, never once per document. The product itself counts as one asset for its system documents.

```
Context (print before asking):
- Where: /lazy-spec.sync-with-code · Step 4 — Ask before touching approved assets; target <asset-dir>
- Found: approved documents <doc names>; the code disagrees in <one line per finding: doc · section · what changes> (or: the asset's code is gone — <evidence>)
- Why asking: an approved document is a reviewed decision, and changing or deleting one is the operator's call
- Answers: `update` — every finding of this asset is applied in Steps 5, 9 and 10, approved documents keep their stage; `leave` — the asset is untouched this run and listed in the report, a later `--full` run finds the same drift and asks again
AskUserQuestion: header "Approved asset", question "Bring the approved asset <asset-dir> of <product> in line with the code?", options `update` / `leave` with those descriptions.
```

An asset reported `[TARGET]` is asked the same way, once per asset, whatever its stages read — the code may simply be behind a design someone reviewed and approved, and only the operator knows whether that design still stands:

```
Context (print before asking):
- Where: /lazy-spec.sync-with-code · Step 4 — Ask before touching approved assets; target <asset-dir>
- Found: decisions <D-ids> and sections <doc · section> state a target design from review; the code does <one line per disagreement>
- Why asking: rewriting them to the code discards a reviewed design, keeping them leaves the spec ahead of the code — whether that design still stands is the operator's call
- Answers: `update` — the asset is brought in line with the code in Steps 5 and 10, its design records marked obsolete; `keep` — the asset is untouched this run and listed in the report as ahead of the code, asked again on the next run that finds it
AskUserQuestion: header "Target design", question "Does the target design of <asset-dir> still stand, or should it follow the code?", options `keep` / `update` with those descriptions.
```

Assets with neither an approved document nor a `[TARGET]` finding are never asked about. Outcome: `asked:<N>, update:<a>, leave:<b>` or `none-approved`.

## Step 5 — Rewrite the documents (parallel writers)

One writer per product unit with `[DRIFT]` or `[GAP]` findings left after Step 4 (`subagent_type: "general-purpose"`), at most 4 in one message. Each prompt carries the product's findings, the paths it may edit (the documents those findings name — nothing else), and these rules:

- **Edit, never overwrite** — `Edit` on the section a finding names: correct a statement the code made false, add one for behaviour no document described. Hand-written sections (Goals, Principles, Known Limitations) are touched only to correct a statement that is now false.
- **Language** — the language the document is already written in. A document with no prose yet takes the product's `language`.
- **File roles** — a design, vision, use-cases or ui-design document carries no source links, repo file paths, class or function names. Source links appear only in `tech.md` and only through `lazy-spec.source-url`.
- **`tech.md`** — a contradicted statement is rewritten to match the code, and a new stack-level fact is added, in the document's own sections and style, exactly like a design rewrite; the document stays a narrow statement of requirements and infrastructure decisions. No architecture narrative and no list of functions, verbs or files enters it.
- **Folder-note précis** — the one line under the `#protected/spec/summary` tag in `# Summary` is rewritten when the asset's subject changed; nothing else in a folder-note is written.
- **Protected sections** — `# Sources`, `# See also` and every other `#protected/<owner>/…` section stays byte-for-byte, except the `# History` line below.
- **History** — each edited document gets one line in its `# History` section, naming the synced window or `full` and what changed. The writer composes the text and lands it with `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" note-history <doc> --line "<text>"`; the verb places it under today's day group and creates the section when absent.
- **No git** — no `git add`, `commit`, `stash`, `checkout`, `restore`, nothing that writes the index.

Each writer returns one line per edited section: `<file> | <heading> | rewritten`. The main session keeps that list for Step 6. Outcome: `rewritten:<N> sections in <M> documents`.

## Step 6 — Compute runtime seam list

A seam is **refresh-only**: an existing drawer-authored fence (a line starting `%%{init:`, found with `Bash(grep -n "^%%{init:" <file>)`) whose **own** heading — the nearest `##` or `###` heading above the fence — is a heading Step 5 rewrote. A fence under a heading whose prose did not change illustrates nothing that changed and is no seam, even when a sibling subsection of the same `##` section was rewritten. A rewritten section without a fence gets none — creating diagrams is not this skill's mandate.

Build `seams[] = [{target_file, anchor_section: <that heading>, facts: <bullet list from the rewritten prose>}, …]`. Outcome: `seams:<N>` or `no-seams-this-run`.

## Step 7 — Dispatch diagram per computed seam

Add one ledger line per seam titled `draw-diagram <relative-path>:<anchor>:auto`, then for each, in order, invoke `Skill(skill: "lazycortex-diagram:lazy-diagram.draw", …)` with `target_file`, `anchor_section` (the fence's own heading, so the drawer replaces that fence and no other), `format="mermaid"`, and `request=` one sentence on what the diagram depicts followed by `facts: <bullet list>`. `kind` is left unset: the drawer's heuristic resolves it against the existing picture's subject. Record its return value as the child's outcome. With no seams, record `no-seams-this-run`.

## Step 8 — Create assets for uncovered code

For each `[UNCOVERED]` finding, scaffold the asset exactly as `lazy-spec.create-from-code` Step P5 scaffolds a confirmed candidate — `Skill(skill: "lazycortex-specs:lazy-spec.create-asset", args: "<product> feature <candidate-slug> [--path <placement>] --empty")`, `vision.md` seeded through `seed-doc` only when the type declares `vision: mandatory` (the shipped `feature` declares `opt-in`, so it gets none), every seeded document authored from the finding's evidence by that skill's Step F2b procedure, the folder-note précis written. No question is asked per candidate: the operator reviews the new folders in the run's diff.

**A document this skill authors is born parked.** Every document this step creates is written with `spec_stage: deferred` in its frontmatter and `spec/deferred` in its `tags:` list — both keys in the same edit of the still-uncommitted file, never through `lazy-spec.set-stage`, which would also recompute the containers' stats that a birth leaves alone — so nothing automatic acts on it until the operator picks it up with `/lazy-spec.set-stage <doc> draft`. Documents the run merely edits keep the stage they carry.

Outcome: `created:<N>` or `no-uncovered`.

## Step 9 — Delete assets whose code is gone

For each `[GONE]` finding left after Step 4, delete the asset folder with `Bash(rm -r <asset-dir>)` — first confirming `find <asset-dir> -name .git -print -quit` prints nothing. A folder holding a nested asset that is itself not `[GONE]` is not deleted; it is reported instead. Every wikilink elsewhere in the tree that pointed into the deleted folder is listed for Step 13's audit to surface.

Outcome: `deleted:<N>` or `none-gone`.

## Step 10 — Mark abandoned decisions obsolete

For each `[DECISION]` finding left after Step 4, mark the record through the registry primitive — never by editing `decisions.md`, a record of what was chosen when:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" decide obsolete <decisions.md> <D-id> "<what the code does now, and the commit that changed it>"
```

Outcome: `obsoleted:<N>` or `no-decisions`.

## Step 11 — Propose gate and stage corrections

The flat-gate model is owned by `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`; the only gate channel is `/lazy-spec.flip-gate`, the only stage channel `/lazy-spec.set-stage`. A cancelled asset gets no proposal.

**Missing folder-note.** A folder Step 3 found with authored documents but no status folder-note is scaffolded from the template the layout chain resolves for its type (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` Part 1 § Template storage; the type-agnostic base is `${CLAUDE_PLUGIN_ROOT}/templates/spec.asset/asset-note.md`): substitute `{{product_tag}}` (`product/<spec_path>`), `{{product}}` and `{{category}}` (the type name), write `spec_asset_type: <type>`, splice the type's `iconize_icon` / `iconize_color`, and record the line `lazy-spec.sync-with-code · status folder-note scaffolded` with `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" note-history <note> --line "<text>"`. The type comes from the one asset type whose `default_path` matches the enclosing folder; on none or several, ask:

```
Context (print before asking):
- Where: /lazy-spec.sync-with-code · Step 11 — Propose gate and stage corrections; target <asset-folder>/<basename>.md (missing)
- Found: folder <asset-folder> has no status folder-note; its parent matches the default_path of <none | several: type, type> of <product>'s types
- Why asking: `spec_asset_type` lives on the note that is missing, and a folder name is not a fact
- Answers: `<type>` (one per visible type) — the note is scaffolded with that type and its icon; never re-asked once the note exists
AskUserQuestion: header "Asset type", question "Which asset type of <product> is the asset at <asset-folder>?", one option per visible type with a description.
```

**Develop gate.** Only a `release` note carries `spec_develop_done`; a design-only asset's code lands through a release build, so no gate of its own is proposed here — an asset whose code is already on the default branch with no release carrying it is reported under `[GATE]` as `implemented outside a release` for the operator to fold into the next one. For an open release note with `spec_develop_done: false`, `spec_plan_done: true`, and commits on the default branch implementing its `spec_includes`, propose the flip:

```
Context (print before asking):
- Where: /lazy-spec.sync-with-code · Step 11 — Propose gate and stage corrections; target <release-dir>/<NNN>.md
- Found: spec_develop_done false, spec_plan_done true; commits <short-hash list> on <default-branch> implement the release's included assets <tokens>
- Why asking: a gate flip is the recorded progression signal and this skill never writes one silently
- Answers: `confirm` — runs `/lazy-spec.flip-gate <asset> spec_develop_done` now, never re-proposed; `skip` — gate untouched, proposed again on the next sync that sees the evidence
AskUserQuestion: header "Develop done", question "Code for release <product>/releases/<NNN> landed on <default-branch> in <commits> — flip spec_develop_done to true?", options `confirm` / `skip` with descriptions.
```

On confirm: `Skill(skill: "lazycortex-specs:lazy-spec.flip-gate", args: "<release-dir> spec_develop_done")`. With `spec_plan_done` still `false`, report the release as held at its plan gate instead. Never propose `spec_tests_passing`, `spec_built` or `spec_released` here.

**Stage correction.** A document whose `spec_stage` is objectively wrong against the code (missing entirely, or `draft` on a feature that has fully shipped) is proposed the same way — context block naming the doc, the stage it reads, and the code evidence; `AskUserQuestion` header "Stage correction", question "Set spec_stage of <doc-path> from <current> to <stage>?", options `confirm` / `skip`. On confirm: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" set-stage <doc-path> <stage>)`. The stage is corrected only when the JSON answer reads `status` `set` or `noop`, and its `touched_paths` ride in this run's commit; a `refused` answer — a stage outside the closed set among them — has its `reason` reported as it stands.

Outcome: `proposed:<N>, confirmed:<M>` or `nothing-to-propose`.

## Step 12 — Update state

For every product that took part in Step 2 (window or full, `no-changes` included), rewrite its checkpoint through the verb, which records HEAD, today and the product's `source_paths`:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" sync-state write <product-key>
```

Every path in the printed `touched_paths` joins the paths this run wrote — a renamed pre-convention file included, so its deletion is committed with the new one. Asset scope writes none.

**No commit without the operator's yes.** The run commits nothing it wrote — rewrites, created and deleted assets, obsoleted records, checkpoints. After Step 13 it shows the operator a summary (documents edited, assets created, assets deleted, decisions obsoleted, approved assets left) and `git diff --stat` of every path it wrote, and stops. The commit happens only after the operator has read the diff and allowed it, with exactly those paths as the explicit pathspec (`git add -N` first for every created file). A rejected diff is reverted path by path, checkpoints included, so the next sync sees the same window again.

Outcome: `checkpoints:<N>` or `asset-scope-no-state`.

## Step 13 — Run doctor and verify

Run `/lazy-spec.audit` over the scope and report its findings beside the diff; never auto-fix them. Then verify:

- Every `Step 7` child is `completed` with a legal outcome word, and `seams[]` matches the seams logged under `.logs/claude/lazy-diagram.draw/` for this run in both directions. For each `target_file` in `seams[]`, `grep -c "^%%{init:" <target_file>` is not lower than its count before the run.
- No edited design, vision, use-cases or ui-design document gained a source link (a markdown link whose target starts with `/` and names a file under `source.paths`).
- Every created document reads `spec_stage: deferred`; every edited document reads the stage it carried before.
- No asset that Step 4 answered `leave` has a changed path in the diff.

Outcome: `verified` or `failed:<check>`.

## Report

One line per task in the canonical list, with its outcome word, dynamic `Step 7` children included; then the approved assets left untouched, the releases held at their plan gate, and the audit's findings.

## Failure modes

- **`sync-state` reports `reason: unknown-product`** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/lazy-spec.product-config`, then re-invoke.
- **`sync-state` reports `reason: design-only`** — the product has no `source` block, so the run no-ops on it → add its source paths via `/lazy-spec.product-config` (edit mode), then re-invoke.
- **`sync-state` reports `reason: no-head`** — the repository's HEAD is unreadable (no commit yet, or not a git checkout) → make the first commit, then re-invoke.
- **An approved asset keeps its drift run after run** — it was answered `leave` in Step 4 → re-run with `--full` and answer `update`.
- **A release never gets a `spec_develop_done` proposal despite landed code** — the release's `spec_plan_done` does not read `true` yet → settle the release's plan gate first (an approved or absent `code-plan.md` in the release folder), then re-run. A design-only asset never gets the proposal at all: its code lands through a release.

## Key Rules

- **The code is the truth** — every authored document in scope is brought in line with it: false statements rewritten, missing behaviour written down, uncovered code given an asset, assets of gone code deleted, abandoned decisions marked obsolete.
- **Scope is the whole tree, one product with its nested products, or one asset**; a nested product is always its own unit, so no document is reconciled twice.
- **Approved assets and assets ahead of the code are asked once per asset**, never once per document; an answered `update` keeps every document's stage, and a reviewed target design the code has not reached is never rewritten without the operator's `update`.
- **A created document is born `deferred`** — `spec_stage: deferred` plus the `spec/deferred` tag; editing an existing document never changes its stage.
- **Stages through `lazy-spec.set-stage`, gates through `lazy-spec.flip-gate`, decisions through `decide`** — never a raw frontmatter or registry edit; the one exception is the born-`deferred` stage and tag of a document this run created.
- **File roles hold** — source links only in `tech.md`, only through `lazy-spec.source-url`; `tech.md` carries technical requirements and infrastructure decisions, never architecture and never a list of functions, verbs or files; the sync keeps every statement in it true to the code.
- **Write in the document's own language**; a document without prose takes the product's `language`.
- **Edit freely, commit only on the operator's yes** — no per-edit questions beyond Steps 4 and 11; nothing is committed until the operator has read the whole diff and allowed it.
- **Diagrams are refreshed, never created** — only a fence whose own heading was rewritten is redrawn, and the drawer is anchored at that heading.
