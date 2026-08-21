---
chapter_type: faq
summary: Answers to common questions about setting up scopes, running relinks, querying the wiki, the terms dictionary, the structure map, and the domain-spec tree.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-wiki.install
  - lazy-wiki.configure
  - lazy-wiki.doctor
  - lazy-wiki.query
  - lazy-wiki.relink
  - lazy-wiki.structure
  - lazy-wiki.terms
  - lazy-wiki.domains
  - lazy-wiki.domain-sync
source_sha: e758792cb8f978c3f3e230b8233d46a2da076903
---
# Frequently asked questions

## Do I need to run `/lazy-wiki.install` before anything else?

Yes. `/lazy-wiki.install` seeds the `wiki` settings section in `lazy.settings.json`, seeds agent model tiers for the wiki curator, registers the `wiki.curator` expert, and copies the navigation rule into your rules directory. If your project uses the background daemon (or hasn't decided yet), it also registers the `lazy-wiki.scan`, `lazy-wiki.scan-deletes`, and `lazy-wiki.relink-weekly` routines; if the daemon is explicitly disabled for the project, the routines are skipped and only the curator expert and settings are installed. Nothing else in the plugin will work until the `wiki` section exists. The install is idempotent — running it again on an already-configured project is safe and will not overwrite values you have set.

After install, run `/lazy-wiki.configure` to define at least one scope (the set of path globs the wiki covers, the tag axes it narrows to, and where to write the topics index). `/lazy-wiki.query` and `/lazy-wiki.relink` both require at least one configured scope to proceed.

---

## What is a scope, and how many should I create?

A scope is a named slice of your repository that the wiki tracks independently. Each scope has its own `topics.md` index, its own tag-axis narrowing, and its own anchor tracking which commit has been fully linked. You configure scopes via `/lazy-wiki.configure`.

Create one scope per coherent body of content that you want to navigate independently — for example a `docs` scope over `docs/**/*.md` and a `codebase` scope over `src/**/*.py`. Scopes can coexist in the same repo; `/lazy-wiki.doctor` can check all of them in a single run. If your whole project is one unified body of knowledge, a single scope is fine.

---

## `/lazy-wiki.configure` keeps re-asking me for the same scope id — what went wrong?

The id must match `^[a-z][a-z0-9_-]*$` — lowercase letters, digits, hyphens, and underscores, starting with a letter. Uppercase letters, dots, or spaces cause the wizard to re-ask. If you enter a valid id that already exists in `lazy.settings.json`, the wizard enters edit mode and shows existing values so you can keep or change them.

---

## What does the "review-skip filter" question in `/lazy-wiki.configure` do?

During Phase 7 of the configure wizard, you are asked whether to skip documents that are currently under review. If you answer yes, the scope gains a filter that excludes any node with `review_active: true` in its frontmatter — the same flag set by `lazycortex-review` when a review opens. While a document is under active review, the curator will not classify or link it, and it will not appear in the topics index. When the review closes and `review_active` is removed, the document re-enters the wiki on the next relink.

The same filter is also seeded into the `lazy-wiki.scan` routine at install time so that the runtime daemon drops review-active documents before they ever reach the curator. Both filters work together — you do not need to configure them separately.

Alongside the review-skip answer, every scope is seeded with `folder_note: false`. A note named after its own folder (`sync/sync.md` inside `sync/`) displays as the folder itself under the folder-notes convention, so it is a structural navigation node rather than a document worth curating; excluding it keeps summaries, tags, and See-also sections off your folder tree. You are not asked about this — it is the default. Set `folder_note: true` in the scope's `filter` by hand for the opposite selection, or remove the key to curate folder notes alongside everything else.

---

## How do I get the wiki populated for the first time?

Run `/lazy-wiki.relink [<scope-id>]`. On a fresh scope with no anchor, the plan runs in `initial` mode and processes every node matched by the scope's path globs. The wiki curator classifies each node (summary, topic tags, connectors), the index is rebuilt once, and then each node receives its glossed See-also links. Everything is committed in a single atomic commit. For large codebases this may take a while — progress is reported step by step.

Subsequent runs are incremental: only nodes touched since the last committed anchor are re-processed.

---

## When should I run `/lazy-wiki.relink` versus waiting for the daemon routines?

`/lazy-wiki.relink` is the right choice when you do not have the runtime daemon running, when you want to force a full or incremental relink right now in your current session, or after a rebase or `reset --hard` that made the previous anchor unreachable. The daemon routines (`lazy-wiki.scan` for per-commit event processing, `lazy-wiki.scan-deletes` for per-commit deletion pruning, and `lazy-wiki.relink-weekly` for the weekly full sweep) handle ongoing maintenance automatically when the lazycortex-core runtime is active — the weekly routine sweeps every configured scope in one pass, reporting one result line per scope, so you never need to trigger it per scope yourself. `/lazy-wiki.relink` is the manual equivalent that works standalone and covers the same ground for one scope at a time in a single dispatch.

---

## `/lazy-wiki.relink` reported `anchor-lost` — is my wiki data damaged?

No. `anchor-lost` means the `wiki_synced_sha` stored in `topics.md` became unreachable — most commonly because of a rebase, `reset --hard`, squash merge, or a shallow clone that pruned the commit. The plan automatically falls back to a content-hash backstop using each node's `wiki_src_hash` field to decide what needs re-processing. After the run completes, a fresh HEAD anchor is recorded and future runs are incremental again. No wiki metadata written to nodes is lost; only the delta detection needed a backstop.

---

## A curator subagent reported an error during `/lazy-wiki.relink` — do I need to restart?

No. When a curator reports an error for a specific node (malformed input, a failed `apply-node`, or a schema violation), `/lazy-wiki.relink` skips that node and continues with the rest. The skipped node is picked up on the next relink. After the run finishes, check the report for any skipped nodes and run `/lazy-wiki.relink` again to re-process them once the underlying issue is resolved.

---

## What happens to See-also links when I delete a wiki node?

Deleting a file that was part of the wiki does not leave dangling links behind. `/lazy-wiki.relink` detects deleted nodes as the `drop[]` set in its plan and, in Step 5, drops any See-also line pointing at the deleted path from every node that still references it, then folds that change into the same commit as the rest of the relink.

If the runtime daemon is active, this happens automatically and independently of a relink: the `lazy-wiki.scan-deletes` routine watches for deleted files on every commit and calls the same prune logic, committing the cleanup on its own as soon as the deletion is detected. Either path also rebuilds `topics.md` so the deleted node's entry disappears from the index. You do not need to manually search for or remove broken links after deleting a file.

---

## What does `/lazy-wiki.query` actually do, and what can it answer?

`/lazy-wiki.query "<question>"` answers questions by traversing the wiki graph — the glossed See-also links and topic index entries written by the curator. It dispatches a seeker subagent per configured scope to pick entry points from `topics.md`, validates those paths, then hands them to a gatherer subagent that walks See-also links, reads relevant node bodies, and synthesises an answer. The large topic index and all traversed node bodies stay in the subagents' contexts and never load into your main session.

The quality of answers depends on the wiki being well-linked. On a fresh install with no relink completed, seekers will find no entry points and the response will say so.

---

## Why does Claude reach for `/lazy-wiki.query` before it just greps or opens a file I ask about?

Once `/lazy-wiki.install` has synced the navigation rule into your project, any session working in this repo is instructed not to answer a question from its own reading of the sources when the question is about material a configured scope covers — `/lazy-wiki.query` runs first, before Grep, Glob, or opening a file in that scope. This is because a blind grep or a file-by-file read misses the glosses and See-also edges that say which node actually answers the question; the wiki graph is the shortcut around that search.

Which questions count as "covered" is decided by the `## Coverage` section of the installed navigation rule, listing each scope's path globs. `/lazy-wiki.configure` writes that section for you — every time you create or edit a scope, Phase 9 rewrites `## Coverage` with one bullet per configured scope (its globs and any exclusions) so the rule stays in sync with `lazy.settings.json[wiki.scopes]`. You never need to hand-edit the rule file yourself. Files outside every configured scope's globs are unaffected — the session works with them as it always has.

---

## `/lazy-wiki.query` says "no wiki material matched this question" — why?

There are two common causes. First, the topics index for the relevant scope may not exist yet — run `/lazy-wiki.relink` to build it. Second, the question may use terms that do not appear in any topic tag or summary in the index; try rephrasing with vocabulary closer to how the codebase names concepts. The skill shows you the entry points it attempted (including any paths dropped as not on disk) so you can see what the seeker found.

---

## What does `/lazy-wiki.doctor` check, and which findings can it fix automatically?

`/lazy-wiki.doctor [<scope-id>]` runs a read-only audit first and groups findings by severity (`FAIL`, `WARN`, `INFO`). Fixable findings — `orphan-topic`, `index-desync`, `see-also-path-base`, `broken-see-also`, and `stale-gloss` — are repaired by rebuilding the topic index, rewriting See-also links onto the canonical path base, dropping broken See-also lines, or refreshing stale glosses. The skill asks for confirmation before applying any fix.

`see-also-path-base` catches a See-also link written against the wrong path form for the target node (for example, a relative link that no longer matches how the node's canonical path is tracked in the index) — the fix rewrites the link's target to the canonical path without touching its gloss.

Report-only findings (`broken-repo-key`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`, `domain-output-in-scope`) identify structural issues that require a curator relink or a scope reconfiguration to resolve — the doctor surfaces them but does not modify nodes for those checks.

The same run also audits the terms dictionary (when any terms scope is configured) and the project-structure map (when it is configured or already built) — see the dedicated questions below for what each of those sections reports.

---

## `/lazy-wiki.doctor` says "unknown scope" — how do I fix it?

The scope id you passed is not present in `lazy.settings.json[wiki.scopes]`. Either run `/lazy-wiki.configure` to create it, or re-invoke `/lazy-wiki.doctor` without a scope argument to audit every configured scope. You can list existing scopes by running `/lazy-wiki.configure`, which displays them in edit mode.

---

## Can I change the tag axes after the wiki is already built?

The axis vocabulary itself — `wiki.tag_axes` — is repository-wide, not per scope: it is the closed set of coordinate dimensions (`domain`, `kind`, `layer`, and so on) every scope draws from, seeded with the mandatory `doc-kind` axis by `/lazy-wiki.install`. Edit it with `/lazy-wiki.configure vault`. A scope's own `tag_axes` is only a **narrowing** of that vocabulary — an empty or absent list means the scope uses the full vault vocabulary, and a scope can never widen it by naming an axis the vault doesn't declare.

To narrow one scope's axes, run `/lazy-wiki.configure` for that scope and answer Phase 5 with the subset it should use. To grow or shrink the vocabulary itself for every scope at once, run `/lazy-wiki.configure vault` instead — `/lazy-wiki.configure` for a single scope offers only what `wiki.tag_axes` already contains and cannot add a new axis to it.

Either way, expect a normalization pass on the next relink. On the next `/lazy-wiki.relink` run, Step 2 resolves each scope's effective axis list (vault vocabulary narrowed by the scope), and Step 3 (normalize tags + rebuild topics index) consolidates any values that no longer match a known axis into the new canonical set, with the curator's retag step updating affected nodes. Findings of `unknown-axis` from `/lazy-wiki.doctor` indicate nodes that carry axis keys not in the current effective set — a relink clears them.

---

## How do I edit the vault-wide axis vocabulary or the exclusions every scope inherits?

Run `/lazy-wiki.configure vault`. It edits the two repository-wide keys of `lazy.settings.json[wiki]` that no other branch of the wizard reaches: `tag_axes`, the closed vocabulary every scope narrows from (see the tag-axes question above), and `exclude`, the glob list unioned into every scope's `exclude_paths` automatically. `docs/structure.md` is seeded into `wiki.exclude` by `/lazy-wiki.install` and should stay there — the project-structure map has no frontmatter to defend itself, and without the entry the curator would append a `# See also` block to it. The generated domain-spec tree needs no entry in either scope or vault `exclude` — it is derived from `wiki.domains.output` and excluded from every scope structurally, so `/lazy-wiki.configure` won't let you add it there.

The regular scope branch of `/lazy-wiki.configure` still collects an `exclude_paths` list per scope, but only for exclusions specific to that one scope, on top of what `wiki.exclude` already covers — you never need to repeat the vault-wide list per scope.

---

## `/lazy-wiki.doctor` reports `domain-output-in-scope` — is a file being written twice?

No. It means a scope's `paths` glob reaches the generated domain-spec tree, but the tree is excluded from every scope structurally (derived from `wiki.domains.output`, not declared anywhere) — no file actually has two writers. The finding is about the glob claiming coverage it doesn't have: narrow the scope's `paths` via `/lazy-wiki.configure` so what the scope declares matches what it actually curates.

---

## How do I add a second repository to a scope's See-also links?

See-also links can reference nodes in other repositories using a `@<repo-key>/<path>` notation. Both `/lazy-wiki.query` and `/lazy-wiki.relink` resolve `<repo-key>` against the `repos` map at the top level of `lazy.settings.json` — a project-wide registry that lazycortex-wiki reads but does not itself manage. If the key you need is not already present in that map, it needs to be added at the project level before cross-repo links will resolve; consult your project's setup for how that registry is maintained. Once the key exists, the curator can resolve cross-repo paths when building links, and `/lazy-wiki.query` can validate and traverse them.

---

## Is it safe to re-run `/lazy-wiki.install` on a project that is already set up?

Yes. `/lazy-wiki.install` is fully idempotent. It will not overwrite existing scope configurations, agent model overrides, routine entries, or expert definitions that you have customised. It reports each item's outcome (`already-present`, `kept-local`, `unchanged`) so you can see what it skipped. The only interactive prompt you may see is around rule file drift — if the shipped navigation rule differs from your local copy, the install will ask whether to overwrite.

---

## Does the weekly full sweep relink every scope, or do I need one per scope?

One weekly run covers every configured scope. The `lazy-wiki.relink-weekly` routine calls the plugin's full-sweep sub-command with no scope id, which passes over every scope registered in `lazy.settings.json[wiki.scopes]` and prints one result line per scope. You do not need to configure or trigger the sweep separately for each scope — adding a new scope via `/lazy-wiki.configure` is enough for it to be picked up on the next weekly run.

---

## What is the terms dictionary, and how do I set one up?

It is one markdown file per configured "terms scope" — every `## <term>` heading in it is a concept the project has agreed on a single name for, and the body underneath is the definition. The point is that a concept never grows a second name: a writer consults the dictionary before coining a word, because after a document ships a synonym can no longer be recalled from it.

Set one up with `/lazy-wiki.configure terms`. You are asked which documents the dictionary serves (a `paths` glob — a document under it may consult the dictionary), where the dictionary file itself lives (created empty if it does not exist yet), and `source_exclude` — the documents the dictionary still serves but never takes terms from (the dictionary file itself, and the tool-report/plan-document globs your project uses, so build journals don't pollute the dictionary with one-off wording). The wizard refuses an id whose `paths` overlap another terms scope's, since one document can only belong to one dictionary, and it registers a per-scope `lazy-wiki.terms-scan-<id>` routine (when the daemon is enabled) that dispatches the terms curator to fill the dictionary from finished documents automatically.

---

## How do I look up a term, or check a name before I use it?

Run `/lazy-wiki.terms` from inside a document you are writing — it matches the document's own path against the configured terms scopes and answers from the winning scope's dictionary. It has two modes: look up one term's exact definition, or check a name you are about to coin against what the dictionary already has, so you can reuse an existing term instead of inventing a synonym for it. It only ever returns the matching entries, never the whole dictionary, and it never writes anything — entering or revising a term is the terms curator's job, done later by reading the finished document.

---

## `/lazy-wiki.doctor` flags `divergence` or `dead` findings for a terms scope — what do they mean?

These come from the terms section of `/lazy-wiki.doctor`, which dispatches the terms curator in report mode to compare the dictionary against the documents it serves. `divergence` means a document uses a different word than the dictionary's canonical one for a concept the curator recognises; `duplicate` means two dictionary entries describe the same concept and should be merged under the name the corpus actually uses; `dead` means a defined term no longer occurs anywhere in the served documents. `missing` covers a concept the corpus uses that the dictionary has not captured yet. Every finding is presented and decided one at a time, never applied in a batch — a `format` or `config` finding (a malformed dictionary, or a scope whose `file` no longer exists) routes back to `/lazy-wiki.configure terms` instead.

---

## What is `docs/structure.md`, and how do I build it?

It is one file per repository — a compact, model-written map of what lives where and where new work belongs, distinct from the per-scope wiki topic indexes. Configure it with `/lazy-wiki.configure structure`: you define `depth_profiles` (named classes of path globs, each at depth `file`, `dir`, or `brief` — controlling how much detail that part of the tree gets) and `exclude` globs the map must never describe (`docs/structure.md` itself is always included automatically, since a map describing itself would loop). Build the initial map with `/lazy-wiki.structure rebuild` — the wizard only configures the section, it does not create the file.

Any agent that needs to know where something lives (an architect deciding where a new file belongs, an expert asking "where does X live in this repo") should query it with `/lazy-wiki.structure query [<path>]` rather than reading the file directly — the query returns just the slice under `<path>`, never the whole map.

---

## Does the structure map stay current on its own, or do I need to rebuild it by hand?

`/lazy-wiki.configure structure` registers three git-watch routines — one for changed files, one for deletions, and one for renames — that dispatch the structure curator to update just the affected entries as commits land, when your project runs the background daemon. Without the daemon, the map only updates when you run `/lazy-wiki.structure rebuild` yourself; the terms section of `/lazy-wiki.doctor` — more precisely its structure counterpart — also flags drift (`missing-dir`, `missing-file`, `dead-entry`, `divergence`, `depth`) you can act on by hand or by rebuilding. A `config` finding there that says the map is reachable by the wiki is fixed once for the whole vault via `/lazy-wiki.configure vault` (putting `docs/structure.md` back into `wiki.exclude`), not by editing any one scope.

---

## What are the domain-spec tree and `Domain(…)` markers?

`wiki.domains` (configured via `/lazy-wiki.configure domains`) generates a tree of documentation — `docs/domains/` by default — synthesised from `Domain(…)` markers annotated on code, grouped by a dictionary of accepted group keys. Each generated doc carries fixed Terms, Principles, and Mechanics sections, with formulas verified against the annotated code, plus a trailing Contracts section for any attributed `Contract:` blocks. Query the generated tree with `/lazy-wiki.domains group <group-key> [<section>]` or `/lazy-wiki.domains term "<text>"` — it returns one doc's section or matching excerpts, never the whole tree, mirroring how `/lazy-wiki.structure query` works over the project-structure map instead.

---

## How do I regenerate the domain-spec tree, and do I need the background daemon?

Run `/lazy-wiki.domain-sync` — it works entirely inside your current session, with no daemon required. It computes what changed since the last generation, dispatches the domain-spec writer per changed group, removes docs whose group no longer has any markers or was renamed out of the dictionary, rebuilds the `domains.md` index, and makes one commit. If your project does run the background daemon, the same regeneration happens automatically: a git-watch routine reacts per commit, and a weekly routine does a full sweep — `/lazy-wiki.domain-sync` is the manual equivalent for a checkout without it, or for right after a `/lazy-python.knowledge-sweep` backfill.

---

## `/lazy-wiki.domain-sync` reports `unknown_groups` — what do I do?

It means code carries `Domain(<group>)` markers whose group key is not listed in the domain-groups dictionary, so that group's doc is skipped this run rather than generated under an unrecognised name. Either add the group to the dictionary by hand and re-run, or run `/lazy-python.knowledge-sweep`, which grows the dictionary together with the operator and refiles the markers under the accepted groups before the next sync. The sweep is the better route when several groups turn up at once, when markers sit under `Domain(unfiled):`, or after a dictionary rename left the old group name behind in the code.
