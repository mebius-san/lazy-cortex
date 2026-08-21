---
name: lazy-wiki.domains
description: "Use when a question needs domain knowledge synthesised from code's `Domain(…)` markers — defining a term, looking up a mechanic or formula, or surveying a group of related domain concepts — and `wiki.domains` is configured in this repo. A research skill: given a group key or a search term, hands back a bounded slice of the domain-spec tree (`docs/domains/` by default, materialized by `/lazy-wiki.domain-sync`) — one doc's section, or matching excerpts — never the whole group doc or the whole tree. Mirrors `lazy-wiki.structure`'s query mode, over the domain tree instead of the project structure map."
research: true
allowed-tools: Read, Grep, Glob, Agent, AskUserQuestion, Bash(test -f *), Bash(git rev-parse *), Bash(mkdir -p *), Bash(date -u *), Write, TaskCreate, TaskUpdate, TaskList
dirty-tree-waiver: "writes only its run log under .logs/ (untracked) — never a tracked file"
---
# lazy-wiki.domains

Query the domain-spec tree — the `docs/domains/` output `wiki.domains` materializes from code's `Domain(…)` markers — without loading a whole group doc, let alone the whole tree, into the caller's context. This skill never writes the tree itself; that is `/lazy-wiki.domain-sync`'s and the daemon routine's job. It runs agentless: `Read`/`Grep`/`Glob` directly against the generated `domains.md` index and group docs, no seeker/gatherer dispatch — the tree is a handful of small, already-synthesised files, cheap enough to read straight.

Invocation: `/lazy-wiki.domains group <group-key> [<section>]` or `/lazy-wiki.domains term "<text>"`

Prerequisites: `wiki.domains` is configured (`.claude/lazy.settings.json[wiki][domains]`, via `/lazy-wiki.configure domains`) and the tree has been generated at least once (`/lazy-wiki.domain-sync` or the daemon routine).

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Load domains config`
   - `Phase 2 — Resolve query target`
   - `Phase 3 — Answer a group query`
   - `Phase 4 — Answer a term query`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. The phase that does not match the resolved mode is marked `skipped` with outcome `skipped-per-mode` — not left `pending`.
3. **Do not reach the Log step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Load domains config

`Read` `.claude/lazy.settings.json`. Extract `[wiki][domains]` — a dict carrying `output` (repo-relative output directory, default `docs/domains` when the key is absent or empty).

If `[wiki][domains]` is absent, not a dict, or empty → outcome `not-configured`; answer *"Domain service not configured — `wiki.domains` is not set up in this repo. Run `/lazy-wiki.configure domains` first."*, mark Phases 2–4 `skipped` with outcome `skipped-per-mode`, and go to the Log step.

Resolve `<repo-root>` via `Bash(git rev-parse --show-toplevel)`. `Bash(test -f <repo-root>/<output>/domains.md)` — absent → outcome `not-configured`; answer *"Domain service not configured — no domain tree at `<output>/domains.md` yet. Run `/lazy-wiki.domain-sync` (or wait for the daemon routine) first."*, mark Phases 2–4 `skipped` with outcome `skipped-per-mode`, and go to the Log step.

Outcome: `loaded` or `not-configured`.

## Phase 2 — Resolve query target

Parse the invocation: `group <group-key> [<section>]` or `term "<text>"`. `<group-key>` is the dot-separated dictionary key (e.g. `mechanics.actions`); `<section>` is one of `Terms` / `Principles` / `Mechanics` / `Contracts`, case-insensitive, and optional. `Terms`, `Principles`, `Mechanics` are always present; `Contracts` is optional — the writer omits it when the group has no attributed `Contract:` blocks.

Neither keyword given → `AskUserQuestion`: *"Query a domain group's doc, or search for a term across the domain tree?"* with options `group` / `term`; follow up asking for the missing key/section or the search text.

Outcome: `resolved: <group|term>`.

## Phase 3 — Answer a group query

**mode=group only.** If the resolved mode is `term`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Phase 4.

1. Derive the group's doc path from its key, mirroring the writer's own layout: split `<group-key>` on `.`; every segment but the last becomes a subdirectory under `<output>`, the last segment plus `.md` is the filename (`mechanics.actions` → `<output>/mechanics/actions.md`; a one-segment key `simulation` → `<output>/simulation.md`).
2. `Bash(test -f <repo-root>/<doc-path>)` — absent → answer *"Group `<group-key>` is not in the domain tree — it may be new, not yet generated, or misspelled; check `<output>/domains.md` for the group list."*, outcome `no-such-group`, done.
3. Present → `Read` the file.
   - **No `<section>` given**: return the overview paragraph (the prose between the H1 title and the first `##` heading) plus the list of `##` headings actually present in the doc (`Terms` / `Principles` / `Mechanics` always, plus `Contracts` when the group has attributed contracts) — enough for the caller to ask a follow-up narrowly. Never the full body.
   - **`<section>` given**: match it case-insensitively against the doc's `##` headings; no match → answer *"`<section>` is not a section of this doc — sections are Terms, Principles, Mechanics, and (when present) Contracts."*, outcome `no-such-section`. A match → return that one `##` block (the heading line through the line before the next `##`, or EOF) — nothing else from the file.

Never paste the full doc file into the response or into this session's context.

Outcome: `answered: group=<group-key>[/<section>]`, `no-such-group`, `no-such-section`, or `skipped-per-mode`.

## Phase 4 — Answer a term query

**mode=term only.** If the resolved mode is `group`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Logging.

1. `Grep` the term, case-insensitive with word boundaries (`\b<term>\b` — a short term like `AP` otherwise false-positive-matches inside unrelated words such as "map"), across `<output>/domains.md` and every group doc under `<output>/**/*.md`, with a line or two of surrounding context per hit.
2. No match anywhere → answer *"`<text>` not found in the domain tree."*, outcome `no-match`.
3. Match(es) → return, per matched file, its repo-relative path and the matched excerpt lines only — never the full file.

Outcome: `answered: term="<text>" (<n> matches)`, `no-match`, or `skipped-per-mode`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.domains/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.domains)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.domains/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<mode> <group-key-or-term> <section-if-any>"
---
# lazy-wiki.domains

## Actions
- <one line per Phase/step above with its outcome word>

## Result
<success/failure + one-sentence summary>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **Reports "Domain service not configured"** — `wiki.domains` is absent from `lazy.settings.json`, or the tree was never generated → run `/lazy-wiki.configure domains`, then `/lazy-wiki.domain-sync` (or wait for the daemon routine), then re-run.
- **Group query reports "not in the domain tree"** — the key is new, not yet generated, or misspelled → check `<output>/domains.md` for the current group list.
- **Group query reports "not a section of this doc"** — `Terms` / `Principles` / `Mechanics` always exist on a generated doc; `Contracts` exists only when the group has attributed `Contract:` blocks → re-query with a section actually present (check the no-`<section>` heading list).
- **Term query reports "not found"** — the term is not referenced anywhere in the generated tree yet, or the tree is stale → run `/lazy-wiki.domain-sync` to refresh, then re-run.
