---
name: lazy-wiki.domains
description: "Use when a question needs domain knowledge synthesised from code's `Domain(…)` markers — defining a term, looking up a mechanic or formula, or surveying a group of related domain concepts — and `wiki.domains` is configured in this repo. A research skill: given a group key or a search term, hands back a bounded slice of the domain-spec tree (`docs/domains/` by default, materialized by `/lazy-wiki.domain-sync`) — a group's overview and document list, one document's section, or matching excerpts — never a whole document or the whole tree. Mirrors `lazy-wiki.structure`'s query mode, over the domain tree instead of the project structure map."
research: true
allowed-tools: Read, Grep, Glob, Agent, AskUserQuestion, Bash(test -f *), Bash(git rev-parse *), Bash(mkdir -p *), Bash(date -u *), Write
---
# lazy-wiki.domains

Query the domain-spec tree — the `docs/domains/` output `wiki.domains` materializes from code's `Domain(…)` markers — without loading a whole group doc, let alone the whole tree, into the caller's context. This skill never writes the tree itself; that is `/lazy-wiki.domain-sync`'s and the daemon routine's job. It runs agentless: `Read`/`Grep`/`Glob` directly against the generated `domains.md` index and group docs, no seeker/gatherer dispatch — the tree is a handful of small, already-synthesised files, cheap enough to read straight.

Invocation: `/lazy-wiki.domains group <group-key> [<doc-slug>] [<section>]` or `/lazy-wiki.domains term "<text>"`

Prerequisites: `wiki.domains` is configured (`.claude/lazy.settings.json[wiki][domains]`, via `/lazy-wiki.configure domains`) and the tree has been generated at least once (`/lazy-wiki.domain-sync` or the daemon routine).

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Load domains config`
   - `Phase 2 — Resolve query target`
   - `Phase 3 — Answer a group query`
   - `Phase 4 — Answer a term query`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. The phase that does not match the resolved mode is marked `skipped` with outcome `skipped-per-mode` — not left `pending`.
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Load domains config

`Read` `.claude/lazy.settings.json`. Extract `[wiki][domains]` — a dict carrying `output` (repo-relative output directory, default `docs/domains` when the key is absent or empty).

If `[wiki][domains]` is absent, not a dict, or empty → outcome `not-configured`; answer *"Domain service not configured — `wiki.domains` is not set up in this repo. Run `/lazy-wiki.configure domains` first."*, mark Phases 2–4 `skipped` with outcome `skipped-per-mode`, and go to the Log step.

Resolve `<repo-root>` via `Bash(git rev-parse --show-toplevel)`. `Bash(test -f <repo-root>/<output>/domains.md)` — absent → outcome `not-configured`; answer *"Domain service not configured — no domain tree at `<output>/domains.md` yet. Run `/lazy-wiki.domain-sync` (or wait for the daemon routine) first."*, mark Phases 2–4 `skipped` with outcome `skipped-per-mode`, and go to the Log step.

Outcome: `loaded` or `not-configured`.

## Phase 2 — Resolve query target

Parse the invocation: `group <group-key> [<doc-slug>] [<section>]` or `term "<text>"`. `<group-key>` is the dot-separated dictionary key (e.g. `billing.invoices`). Each group is a folder holding a folder note and one document per `Domain(…)` block; `<doc-slug>` names one of those documents by its file stem (e.g. `late-fee`), and `<section>` is a `##` section of that document, case-insensitive. A block document always carries `Principles`, `Mechanics` and `Related`, and carries `Terms`, `Contracts` or `Discrepancies` only when it has such content. `<section>` is meaningful only with `<doc-slug>`.

Neither keyword given → ask.

Context (print before asking):
- Where: /lazy-wiki.domains · Phase 2 — Resolve query target; target `<output>/domains.md`
- Found: the invocation carried neither `group` nor `term`; groups listed in the index `<n>`
- Why asking: the query kind and its key are the caller's intent
- Answers: `group` — Phase 3 returns one group's overview and document list, or one document's section, after asking for the key, an optional document and an optional section; `term` — Phase 4 greps the tree and returns excerpts, after asking for the text; read-only, nothing persisted
AskUserQuestion: header "Domain query", question "Query one domain group under `<output>`, or search a term across the whole domain tree?", options `group` / `term` with those descriptions. Follow up, free text — on `group`: header "Group key", question "Group key (dot-separated, e.g. `billing.invoices`), optionally a document slug and a section?"; on `term`: header "Search term", question "Text to search across `<output>/**/*.md`?".

Outcome: `resolved: <group|term>`.

## Phase 3 — Answer a group query

**mode=group only.** If the resolved mode is `term`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Phase 4.

1. Derive the group's folder from its key, mirroring the writer's own layout: every segment of `<group-key>` becomes a directory under `<output>`, and the folder note is the file named like the last segment inside it (`billing.invoices` → `<output>/billing/invoices/invoices.md`).
2. `Bash(test -f <repo-root>/<folder-note>)` — absent → answer *"Group `<group-key>` is not in the domain tree — it may be new, not yet generated, or misspelled; check `<output>/domains.md` for the group list."*, outcome `no-such-group`, done.
3. **No `<doc-slug>` given**: `Read` the folder note and return its overview (the prose between the explainer line under the H1 and the first `##` heading) and its `## Documents` list — each line names one document and links its file, enough for the caller to ask for one document narrowly. Never the full body of any document.
4. **`<doc-slug>` given**: `Bash(test -f <repo-root>/<folder>/<doc-slug>.md)` — absent → answer *"`<doc-slug>` is not a document of `<group-key>` — the folder note's Documents list names them."*, outcome `no-such-doc`. Present → `Read` it.
   - **No `<section>` given**: return the H1 title and the list of `##` headings actually present.
   - **`<section>` given**: match it case-insensitively against the document's `##` headings; no match → answer *"`<section>` is not a section of this document — its sections are <the headings present>."*, outcome `no-such-section`. A match → return that one `##` block (the heading line through the line before the next `##`, or EOF) — nothing else from the file.

Never paste the full doc file into the response or into this session's context.

Outcome: `answered: group=<group-key>[/<doc-slug>[/<section>]]`, `no-such-group`, `no-such-doc`, `no-such-section`, or `skipped-per-mode`.

## Phase 4 — Answer a term query

**mode=term only.** If the resolved mode is `group`, mark this task `skipped` with outcome `skipped-per-mode` and proceed to Logging.

1. `Grep` the term, case-insensitive with word boundaries (`\b<term>\b` — a short term like `AP` otherwise false-positive-matches inside unrelated words such as "map"), across `<output>/domains.md` and every folder note and block document under `<output>/**/*.md`, with a line or two of surrounding context per hit.
2. No match anywhere → answer *"`<text>` not found in the domain tree."*, outcome `no-match`.
3. Match(es) → return, per matched file, its repo-relative path and the matched excerpt lines only — never the full file.

Outcome: `answered: term="<text>" (<n> matches)`, `no-match`, or `skipped-per-mode`.

## Report

One line per task in the canonical list, with its outcome word.

## Failure modes

- **Reports "Domain service not configured"** — `wiki.domains` is absent from `lazy.settings.json`, or the tree was never generated → run `/lazy-wiki.configure domains`, then `/lazy-wiki.domain-sync` (or wait for the daemon routine), then re-run.
- **Group query reports "not in the domain tree"** — the key is new, not yet generated, or misspelled → check `<output>/domains.md` for the current group list.
- **Group query reports "not a document of"** — the slug names no file in the group's folder → take the slug from the folder note's Documents list and re-query.
- **Group query reports "not a section of this document"** — `Principles` / `Mechanics` / `Related` always exist on a block document; `Terms`, `Contracts` and `Discrepancies` exist only when the document has such content → re-query with a section the answer listed.
- **Term query reports "not found"** — the term is not referenced anywhere in the generated tree yet, or the tree is stale → run `/lazy-wiki.domain-sync` to refresh, then re-run.
