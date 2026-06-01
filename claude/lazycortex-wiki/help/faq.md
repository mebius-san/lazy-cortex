---
chapter_type: faq
summary: Answers to common questions about setting up scopes, running relinks, querying the wiki, and interpreting doctor findings.
last_regen: 2026-06-01
no_diagram: true
source_skills:
  - lazy-wiki.query
  - lazy-wiki.relink
  - lazy-wiki.doctor
  - lazy-wiki.install
  - lazy-wiki.configure
---
# Frequently asked questions

## Do I need to run `/wiki.install` before anything else?

Yes. `/wiki.install` seeds the `wiki` settings section in `lazy.settings.json`, registers the `wiki.scan` and `wiki.relink-weekly` routines, seeds agent model tiers for the wiki curator, and copies the navigation rule into your rules directory. Nothing else in the plugin will work until that section exists. The install is idempotent — running it again on an already-configured project is safe and will not overwrite values you have set.

After install, run `/wiki.configure` to define at least one scope (the set of path globs the wiki covers, the tag axes, and where to write the topics index). `/wiki.query` and `/wiki.relink` both require at least one configured scope to proceed.

---

## What is a scope, and how many should I create?

A scope is a named slice of your repository that the wiki tracks independently. Each scope has its own `topics.md` index, its own tag axes, and its own anchor tracking which commit has been fully linked. You configure scopes via `/wiki.configure`.

Create one scope per coherent body of content that you want to navigate independently — for example a `docs` scope over `docs/**/*.md` and a `codebase` scope over `src/**/*.py`. Scopes can coexist in the same repo; `/wiki.doctor` can check all of them in a single run. If your whole project is one unified body of knowledge, a single scope is fine.

---

## `/wiki.configure` keeps re-asking me for the same scope id — what went wrong?

The id must match `^[a-z][a-z0-9_-]*$` — lowercase letters, digits, hyphens, and underscores, starting with a letter. Uppercase letters, dots, or spaces cause the wizard to re-ask. If you enter a valid id that already exists in `lazy.settings.json`, the wizard enters edit mode and shows existing values so you can keep or change them.

---

## How do I get the wiki populated for the first time?

Run `/wiki.relink [<scope-id>]`. On a fresh scope with no anchor, the plan runs in `initial` mode and processes every node matched by the scope's path globs. The wiki curator classifies each node (summary, topic tags, connectors), the index is rebuilt once, and then each node receives its glossed See-also links. Everything is committed in a single atomic commit. For large codebases this may take a while — progress is reported step by step.

Subsequent runs are incremental: only nodes touched since the last committed anchor are re-processed.

---

## When should I run `/wiki.relink` versus waiting for the daemon routines?

`/wiki.relink` is the right choice when you do not have the runtime daemon running, when you want to force a full or incremental relink right now in your current session, or after a rebase or `reset --hard` that made the previous anchor unreachable. The daemon routines (`wiki.scan` for per-commit event processing and `wiki.relink-weekly` for the weekly full sweep) handle ongoing maintenance automatically when the lazycortex-core runtime is active; `/wiki.relink` is the manual equivalent that works standalone.

---

## `/wiki.relink` reported `anchor-lost` — is my wiki data damaged?

No. `anchor-lost` means the `wiki_synced_sha` stored in `topics.md` became unreachable — most commonly because of a rebase, `reset --hard`, squash merge, or a shallow clone that pruned the commit. The plan automatically falls back to a content-hash backstop using each node's `wiki_src_hash` field to decide what needs re-processing. After the run completes, a fresh HEAD anchor is recorded and future runs are incremental again. No wiki metadata written to nodes is lost; only the delta detection needed a backstop.

---

## What does `/wiki.query` actually do, and what can it answer?

`/wiki.query "<question>"` answers questions by traversing the wiki graph — the glossed See-also links and topic index entries written by the curator. It dispatches a seeker subagent per configured scope to pick entry points from `topics.md`, validates those paths, then hands them to a gatherer subagent that walks See-also links, reads relevant node bodies, and synthesises an answer. The large topic index and all traversed node bodies stay in the subagents' contexts and never load into your main session.

The quality of answers depends on the wiki being well-linked. On a fresh install with no relink completed, seekers will find no entry points and the response will say so.

---

## `/wiki.query` says "no wiki material matched this question" — why?

There are two common causes. First, the topics index for the relevant scope may not exist yet — run `/wiki.relink` to build it. Second, the question may use terms that do not appear in any topic tag or summary in the index; try rephrasing with vocabulary closer to how the codebase names concepts. The skill shows you the entry points it attempted (including any paths dropped as not on disk) so you can see what the seeker found.

---

## What does `/wiki.doctor` check, and which findings can it fix automatically?

`/wiki.doctor [<scope-id>]` runs a read-only audit first and groups findings by severity (`FAIL`, `WARN`, `INFO`). Fixable findings — `orphan-topic`, `index-desync`, `broken-see-also`, and `stale-gloss` — are repaired by rebuilding the topic index, dropping broken See-also lines, or refreshing stale glosses. The skill asks for confirmation before applying any fix.

Report-only findings (`broken-repo-key`, `missing-summary`, `unknown-axis`, `dup-branch`, `broken-wiki-block`, `scope-overlap`) identify structural issues that require a curator relink or a scope reconfiguration to resolve — the doctor surfaces them but does not modify nodes for those checks.

---

## `/wiki.doctor` says "unknown scope" — how do I fix it?

The scope id you passed is not present in `lazy.settings.json[wiki.scopes]`. Either run `/wiki.configure` to create it, or re-invoke `/wiki.doctor` without a scope argument to audit every configured scope. You can check which scopes exist by reading `.claude/lazy.settings.json` — or by running `/wiki.configure` which lists them in edit mode.

---

## Can I change the tag axes for a scope after the wiki is already built?

Yes, but expect a normalization pass on the next relink. Run `/wiki.configure` and update the `tag_axes` for the scope. On the next `/wiki.relink` run, Step 3 (normalize tags + rebuild topics index) will consolidate any values that no longer match a known axis into the new canonical set, and the curator's retag step will update affected nodes. Findings of `unknown-axis` from `/wiki.doctor` indicate nodes that carry axis keys not in the current configured set — a relink clears them.

---

## How do I add a second repository to a scope's See-also links?

See-also links can reference nodes in other repositories using a `@<repo-key>/<path>` notation. Register the external repo in the `repos` map in `lazy.settings.json` by running `/lazy-core.configure` or the equivalent settings skill — do not edit `lazy.settings.json` by hand. Once the key is registered, the curator can resolve those cross-repo paths when building links, and `/wiki.query` can validate and traverse them.

---

## Is it safe to re-run `/wiki.install` on a project that is already set up?

Yes. `/wiki.install` is fully idempotent. It will not overwrite existing scope configurations, agent model overrides, routine entries, or expert definitions that you have customised. It reports each item's outcome (`already-present`, `kept-local`, `unchanged`) so you can see what it skipped. The only interactive prompt you may see is around rule file drift — if the shipped navigation rule differs from your local copy, the install will ask whether to overwrite.
