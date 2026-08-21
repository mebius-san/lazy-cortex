---
name: lazy-spec.lookup
description: "Use when an agent doing research over the spec tree — an expert following its research aspect, a subagent gathering context before writing, or the operator asking where something lives in specs or what depends on it — needs a bounded slice of the spec tree around a product or asset: a question or token plus an optional product/asset anchor, returning matching paths with short excerpts, never whole documents."
research: true
---
# lazy-spec.lookup

Answers one question against the spec tree (`specs/` by default) without loading whole documents into the caller's context. Given a query token and an optional anchor (a product key, a vault-relative path, or a `<category>/<slug>` pair), it walks the tree in three bounded directions — up toward the vault root, down through declared and materialized children, across to siblings and backlinks — and returns matched paths with one-line excerpts. The executing agent NEVER dispatches `Agent`-tool subagents for this walk: every step is a direct `Read` / `Glob` / `Grep` in the caller's own context, so the skill works inside a one-shot dispatch (an expert job, a review specialist) that has no budget for sub-dispatch overhead.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Resolve anchor and query`
   - `Phase 2 — Walk the spec tree`
   - `Phase 3 — Assemble matches`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`refused: <reason>`, `assembled: 0`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Resolve anchor and query

Parse the invocation: a free-form question or token, plus an optional anchor — a product key (a key under `lazy.settings.json[products]`), a vault-relative path already inside the content-root (e.g. `specs/specs/features/spec-lookup`), or a bare `<category>/<slug>` pair understood relative to a product key given alongside it.

1. `Read` `.claude/lazy.settings.json`. Extract `spec.vault_root` (default `specs`) — the content-root every vault-relative path resolves against — and the `products` section. This skill reads `lazy.settings.json` directly rather than shelling out to `lazycortex-specs resolve-product` — the same choice `lazy-spec.create-asset` makes, because a caller dispatched under Claude Code's `dontAsk` permission mode (an expert job, most callers of a research skill) would have an arbitrary plugin-CLI `Bash` invocation silently denied.
2. No anchor given → treat the query as vault-wide: every subsequent step greps `<vault_root>/**/*.md` instead of a scoped subtree.
3. Anchor is a bare product key present in `products` → resolve `spec_path` from the record; refuse (name the key, list the registered keys) when it's missing.
4. Anchor is already a `<vault_root>/...` path → use it directly; `Glob` to confirm it resolves to a folder or a `.md` file before proceeding, refusing with a clear "not found under the vault" message otherwise.
5. Anchor names a bare `<category>/<slug>` → require a product key alongside it (point 3's resolution); refuse when neither is resolvable.

Outcome: `resolved: <product-anchor|path-anchor|vault-wide>` or `refused: <reason>`.

## Phase 2 — Walk the spec tree

Three independent directions, each bounded by the anchor Phase 1 resolved — never the whole tree in one sweep.

### Up — anchor toward the vault root

- Asset anchor (`<spec_path>/<category>/<slug>/`): `Read` the asset's status folder-note `<slug>.md`, keep its `# Summary` line.
- Product anchor (an asset anchor's owning product, or a bare product key): `Read` `<spec_path>/design.md` and `<spec_path>/tech.md`, keep only the paragraph(s) mentioning the query token — never the whole file.
- Still nothing found → `Grep` the query token across `<vault_root>/**/*.md`, excluding paths already covered above (the vault-wide fallback).

### Down — declared and materialized children

- Asset anchor only: `Read` the asset's status folder-note frontmatter `spec_depends_on` list. Each `<category>/<slug>` token names a child under the same product — `Read` its `# Summary`.
- `Grep` the anchor's authored docs that exist (`design.md` / `architecture.md` / `bug.md`) for path-qualified wikilinks (`[[<path>|...]]`) pointing at another asset under the same product tree — a materialized asset-proposal link (`lazy-spec.coordination-playbook.md` Chapter 10). `Read` each target's `# Summary`.

### Across — siblings and backlinks

- Sibling assets: `Glob` the anchor's own category folder (or, for a product-only anchor, every category folder under it) for sibling `<slug>/` directories; `Grep` each sibling's authored docs and status note for the query token, keeping only the ones that actually match.
- Backlinks: `Grep` the query token — and, when the anchor is a path, the anchor's own vault-relative path as a literal wikilink target — across `<vault_root>/**/*.md`, excluding the anchor's own files. Keep one line of context per hit.
- `spec_targets`: when the anchor is an asset whose status folder-note carries `spec_targets` (a change asset), `Read` each named target's `# Summary`.

Outcome: `walked: up=<n> down=<n> across=<n>`.

## Phase 3 — Assemble matches

1. Deduplicate by path — a file reached from two directions keeps only its first-found excerpt.
2. Trim every excerpt to the one line or `# Summary` sentence that justified the match — never the surrounding paragraph, never the whole file.
3. Group the output by direction (`Up` / `Down` / `Across`), one `<path> — <excerpt>` line per match.
4. No matches anywhere → say so plainly, naming the anchor and the query token, rather than returning an empty list silently.

Outcome: `assembled: <n> matches` or `assembled: 0`.

## Logging

Per `.claude/rules/lazy-log.logging.md`:

1. `Bash(mkdir -p ./.logs/claude/lazy-spec.lookup)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-spec.lookup/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<query token> [anchor]"
---
# lazy-spec.lookup

## Actions
- <one line per Phase above with its outcome word>

## Result
<success/failure + one-sentence summary>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **`/lazy-spec.lookup` refuses: anchor not found** — the given product key isn't in `lazy.settings.json[products]`, or the given path doesn't resolve under the vault root → correct the key/path, or register the product via `/lazy-spec.product-config`.
- **`/lazy-spec.lookup` refuses: bare category/slug without a product** — a `<category>/<slug>` anchor was given with no product key to resolve it against → pass the product key alongside it, or use the full vault-relative path instead.
