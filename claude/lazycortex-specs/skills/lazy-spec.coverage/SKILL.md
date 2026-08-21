---
name: lazy-spec.coverage
description: "Run when the operator asks to find capabilities the code already has that the product's spec tree does not cover yet — 'what's missing from the specs', 'gap-scan this product against its code'. Audits the product's structure map (`docs/structure.md`) and domain groups against its spec-asset tree, reporting uncovered capabilities with a proposed category + slug for a retro-spec. This is a whole-product audit sweep with judgment calls on every match, not a bounded lookup by query or anchor — it carries no `research: true` marker despite reading through `lazy-wiki.structure` and `lazy-wiki.domains`."
---
# Spec Coverage

Gap-scan for one product: what the code visibly does, against what the spec tree already documents. Reads the code side from two existing knowledge maps — `lazy-wiki.structure`'s structure map and `lazy-wiki.domains`' domain-group tree, both queried for bounded slices, never swallowed whole — and the spec side from the product's asset folders (status folder-note `# Summary` lines, per `lazy-spec.lookup`'s own pattern). Read-only by default: it reports gap candidates with a proposed category + slug, and offers materialization through paths that already exist (`lazy-spec.create-from-code`, or a printed `[!asset-proposal]` block the operator pastes by hand) — it never writes to the spec tree without the operator confirming each one. Naming, folder structure, and the asset-type registry are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those patterns.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Resolve the product`
   - `Phase 2 — Query the structure map`
   - `Phase 3 — Query domain groups`
   - `Phase 4 — Enumerate existing spec-tree coverage`
   - `Phase 5 — Compute gap candidates`
   - `Phase 6 — Report to the operator`
   - `Phase 7 — Offer materialization`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". A no-op counts only when it emits an explicit outcome (`structure-absent`, `domains-absent`, `no-gaps`, `skipped-per-user-choice`, …).
3. **Do not reach Phase 6 until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **Phase 6 is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

Signature: `<product>` — the product compound-key (e.g. `specs`, `core`). If omitted, `AskUserQuestion` which registered product to scan (list the keys under `lazy.settings.json[products]`).

## Phase 1 — Resolve the product

1. Run `lazycortex-specs resolve-product by-key <product>`. It prints `{"key": "<product>", "record": <record-or-null>}`.
2. **`record` is `null`** — refuse, naming `<product>` and pointing at `/lazy-spec.product-config` to register it. Do NOT proceed.
3. **`record` present** — capture `spec_path` (required, vault-relative), optional `source` (`{repo, paths}`), and the visible `asset_types` names (the product's own declarations merged key-by-key over the plugin's shipped `feature` / `change` / `bug` / `content` / `research`).
   - **No `source` block** (design-only product) — there is no code side to gap-scan. Mark Phases 2, 3, and the fallback branch of Phase 5 `skipped` with outcome `no-source-binding`, proceed straight to Phase 4 to confirm the spec tree exists, then report "no code binding — nothing to gap-scan" at Phase 6. Do NOT invent a code-side comparison.
   - **`source` present** — resolve `source.repo` via the `lazy-spec.resolve-repo` primitive to get `{local_path, ...}`. Continue to Phase 2.

Outcome: `code-bound` / `design-only` / `refused: <reason>`.

## Phase 2 — Query the structure map

**Skip with outcome `no-source-binding` if Phase 1 found no `source` block.**

1. `Read` `.claude/lazy.settings.json`. If the top-level `structure` key is absent, mark this phase `skipped-per-mode` with outcome `structure-not-configured` and go to Phase 3 — the fallback in Phase 5 covers this repo.
2. Otherwise, for each entry in `source.paths`, invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.structure", args: "query <path>")`. Two possible replies:
   - The map has no entry for that path yet (`docs/structure.md` was never rebuilt, or the path predates it) — outcome `structure-absent`. This is a normal, honest degradation, not an error — report it as such.
   - A slice comes back (directory line + role description, and per-file lines for load-bearing files) — capture it verbatim as the structure-derived capability list for Phase 5. Do NOT read `docs/structure.md` directly; the query mode is the only entry point.

Outcome: `queried: <n> slices` / `structure-absent` / `structure-not-configured` / `no-source-binding`.

## Phase 3 — Query domain groups

**Skip with outcome `no-source-binding` if Phase 1 found no `source` block.**

1. `Read` `.claude/lazy.settings.json[wiki][domains]`. Absent, not a dict, or empty → outcome `domains-not-configured`, go to Phase 4.
2. The domain-spec tree carries no per-group source-path mapping (`domains.md`'s own renderer emits only `- [group](link) — gloss`, and a group query returns Terms/Principles/Mechanics/Contracts prose, never file paths) — so the product's own live group list has to come from the code itself. `Grep` `^\s*#\s*Domain\(([^)]+)\):` across the product's `source.paths` and collect the distinct `<group>` captures — these are the domain groups this product's own code actually carries a `Domain(…)` block for.
3. `Read` `<output>/domains.md` (default `docs/domains`) for the group index and keep only the groups from step 2 that also appear there — a group the code carries but the tree hasn't synced yet is not yet queryable; note it as `unsynced` rather than silently dropping it (surfaced in Phase 6, not itself a gap-detection input).
4. For each group confirmed in the index, invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.domains", args: "group <group-key>")` (no section — the overview + heading list is enough to spot named mechanics) and, when a `Mechanics` heading is listed, a second call with that section to get the mechanic bullets. When a `Contracts` heading is also listed, a third call with that section — each entry is a caller-visible guarantee anchored to `path:symbol`, i.e. a capability the code already commits to, not just implements. Capture the returned excerpts (Mechanics and Contracts alike) as the domain-derived capability list for Phase 5.
5. No group from step 2 survives step 3 → outcome `no-matching-groups`.

Outcome: `queried: <n> groups` / `no-matching-groups` / `domains-not-configured` / `no-source-binding`.

## Phase 4 — Enumerate existing spec-tree coverage

1. Assets are found by their status folder-note, never by folder name: `Glob` `<spec_path>/**/*.md`, keep every file whose basename matches its parent folder, and `Read` its frontmatter — the ones carrying `spec_role: status` are the asset boundaries. Assets may nest, and a type's `default_path` is a convenience for whoever creates the asset, so folder names are not a discovery key.
2. For every status folder-note, keep its `spec_asset_type`, its `# Summary` line, and its path relative to `spec_path` — mirroring `lazy-spec.lookup`'s own "Up" direction. Never read the rest of the asset's docs.
3. Assemble the `(type, path, summary)` list — this is the coverage baseline Phase 5 checks candidates against.

Outcome: `enumerated: <n> assets across <m> types`.

## Phase 5 — Compute gap candidates

1. **Fallback scan** — only when Phase 2 returned `structure-absent` or `structure-not-configured` AND the product is code-bound: for each `source.paths` root, `Glob` its immediate subdirectories and keep the ones carrying their own entry-point file (`__init__.py`, `index.ts`, `mod.rs`, a package manifest, or — for this repo's own Claude-plugin shape — a `SKILL.md` / agent `.md` file directly under the subdirectory). This mirrors `lazy-spec.create-from-code`'s Agent D heuristic #1, applied inline rather than via a dispatched agent since it is a single shallow `Glob`, not a multi-file read. Outcome `fallback-scan: <n> candidates` or `fallback-scan: 0` when nothing structured is found.
2. Build the candidate capability list: the structure-map slices (Phase 2), the domain-group excerpts (Phase 3), and the fallback list (step 1 above) — deduplicated by name.
3. For each capability, check the Phase 4 coverage baseline: does any existing asset's slug or `# Summary` line already name or clearly describe it? Use judgment, not a literal string match — a reworded but equivalent capability counts as covered. Covered → drop it from the gap list, keep a count for the report.
4. For every uncovered capability, propose:
   - **category** — `feature` by default; `bug` when the evidence is a hazard/TODO comment naming a defect rather than a capability; `change` when the capability is an incremental modification of an ALREADY-documented asset (name that asset). When one of the product's other declared `asset_types` plausibly fits, note it as an alternative — the final choice happens in Phase 7's `AskUserQuestion`, not here.
   - **slug** — lowercase-with-hyphens per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md`, derived from the capability's name.

Outcome: `computed: <n> gaps, <m> covered` or `no-gaps`.

## Phase 6 — Report to the operator

Print a read-only report. It MUST contain one line per Phase 1–5 task above, then the gap list:

```
## <Product> — Coverage Report

scan: Phase 1 resolve — <code-bound|design-only|refused>
scan: Phase 2 structure-map — <queried:<n>|structure-absent|structure-not-configured|no-source-binding>
scan: Phase 3 domain-groups — <queried:<n>|no-matching-groups|domains-not-configured|no-source-binding>
scan: Phase 4 spec-tree — enumerated <n> assets across <m> types
scan: Phase 5 gap-compute — <n> gaps, <m> covered

### Gap candidates (<n>)
- [ ] <capability name> — evidence: <structure-map | domain-group | fallback-scan>: <path-or-group> | proposed: <category>/<slug>

### Covered (info)
- <n> capability units already matched to an existing asset
```

State plainly when no code-side signal exists at all (`structure-absent`/`structure-not-configured` AND `no-matching-groups`/`domains-not-configured` AND `fallback-scan: 0`) — that is an honest "nothing to compare against yet", not a bug, and Phase 5 correctly reports `no-gaps` in that case rather than a false "fully covered".

Outcome: `reported: <n> gaps`.

## Phase 7 — Offer materialization

**Skip entirely if Phase 5's gap list is empty** — outcome `no-gaps`.

Per gap, one `AskUserQuestion` (never a bulk list) with options:

- **`materialize via lazy-spec.create-from-code`** — only offered when the gap's proposed category is `feature` AND the product is code-bound (Phase 1). On confirm, invoke `Skill(skill: "lazycortex-specs:lazy-spec.create-from-code", args: "<product> feature <slug>")`, passing the gap's evidence (capability name, source path(s)) in the dispatch prompt so its own clarifying step has grounding.
- **`print asset-proposal markup`** — any category. Render the exact `[!asset-proposal] create` block (`category:`, `slug:`, `description:`) per `lazycortex-core:lazy-core.markdown-style` § The `[!asset-proposal]` callout — `create` only, never `link`/`reopen` (this skill has no existing target asset to link or reopen). This skill does NOT paste it into any document itself: an `[!asset-proposal]` is only legal inside a document an expert already owns mid-review, and this skill has no such document open. Print the block for the operator to paste into a living doc (`design.md`, `tech.md`, `architecture.md`) themselves, where the coordinator will materialize it once that doc is next accepted.
- **`skip`** — no trace.

Outcome per gap: `materialized-via-create-from-code` / `printed-asset-proposal` / `skipped-per-user-choice`.

## Logging

Per `.claude/rules/lazy-log.logging.md`:

1. `Bash(mkdir -p ./.logs/claude/lazy-spec.coverage)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-spec.coverage/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<product>"
---
# lazy-spec.coverage

## Actions
- <one line per Phase above with its outcome word>

## Result
<success/failure + one-sentence summary: N gaps found, M materialized, K printed, J skipped>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **Refuses: product not registered** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/lazy-spec.product-config`, then re-invoke.
- **Reports "no code binding — nothing to gap-scan"** — the product has no `source` block (design-only) → this skill has nothing to compare the spec tree against; attach a repo via `/lazy-spec.product-config` if the product does have code, or accept that a design-only product has no gap-scan surface.
- **Reports `structure-absent` / `domains-not-configured`** — the structure map or domain tree isn't built/configured for this repo → run `/lazy-wiki.structure rebuild` or `/lazy-wiki.configure domains` + `/lazy-wiki.domain-sync` if richer signal is wanted; the fallback scan still runs on the raw source tree either way.
