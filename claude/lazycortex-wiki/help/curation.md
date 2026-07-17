---
chapter_type: block
summary: Curate wiki nodes in-session via /wiki.relink or via daemon routines — classify summaries and topic tags, normalise the tag vocabulary, build glossed See-also links, and prune links to deleted nodes.
last_regen: 2026-07-16
diagram_spec:
  anchor: "How the pieces fit together"
  request: "Flow diagram showing /wiki.relink driving the curation block: (1) relink-plan produces classify[], link[], drop[] lists; (2) curator agent runs classify per node via apply-node; (3) normalize-tags consolidates the tag vocabulary via retag; (4) build-index rebuilds topics.md; (5) curator agent runs link per node via apply-node; (6) prune-node drops dangling See-also lines for each path in drop[]; (7) relink commits all touched files and records the wiki_synced_sha anchor. Show that the curator agent is dispatched twice (classify phase, link phase), that prune-node is a deterministic primitive with no curator dispatch, and that the skill owns the single commit."
source_skills:
  - wiki.relink
---
# Curation

When you run `/wiki.relink`, you get a fully curated wiki scope without needing the runtime daemon. Every changed node receives a one-line summary and hierarchical topic tags (so it shows up in the scope's topic index), then a See-also section whose entries are glossed with the target's summary (so an agent can judge relevance without opening the target file). Nodes deleted since the last run have their dangling See-also links dropped from the rest of the scope. The entire process runs synchronously in the current Claude Code session and ends with a single atomic commit.

Two pieces share this work. `/wiki.relink` is the orchestrator: it computes what to process, fires the curator agent for each node, prunes links to deleted nodes, rebuilds the topic index at the right moment, and makes the commit. `lazy-wiki.curator` is the expert: it reads each node in place, applies editorial judgment, and writes the result directly to the file via the deterministic `apply-node` or `retag` primitives — it never hand-edits. The two pieces are cleanly separated: the skill owns the index rebuild, the deletion pruning, and the commit; the curator owns every write to node content.

The same curation logic runs autonomously when the runtime daemon is active. On every commit, the `wiki.scan` routine watches changed files and feeds each one through `lazycortex-wiki process-file` (per-node classify + link, committed by the curator itself in tail-on mode). A companion `wiki.scan-deletes` routine watches for deleted files and feeds each one through `lazycortex-wiki prune-node` — a deterministic pass with no curator dispatch at all, since a deleted file has no content left to classify. Every Monday at 04:00 the `wiki.relink-weekly` routine fires `lazycortex-wiki relink-all`, which re-classifies every node in the scope — useful for consolidating tag vocabulary drift that accumulates between daily commits.

## When you'd use this

- You want the LLM-navigable wiki layer in place immediately, without waiting for the background daemon to process a backlog.
- A batch of files changed (code refactor, docs overhaul, imported content) and you want all summaries, tags, and See-also links updated in one go before the next review.
- You are working in a project that runs without the runtime daemon and need the wiki to stay current after each session's changes.
- You need to force a full rescan of a scope — for example after a rebase or a `reset --hard` that orphaned the previous sync anchor.
- A file you deleted was linked from other nodes and you want those dangling See-also lines cleaned up in the same run, not left to rot.
- The daemon is running and you want to understand what it does automatically: classify + link per changed node on each commit, link pruning per deleted node, a full rescan on the weekly sweep.

## How it fits together

You invoke `/wiki.relink [<scope-id>]`. If you omit the scope id, the skill lists the configured scopes and asks you which to process.

The skill starts by running `relink-plan`, which inspects the `wiki_synced_sha` anchor stored in `topics.md` and returns three path lists — nodes to classify (new or modified), nodes to link (whose summary or neighbours changed), and nodes to drop (deleted since the anchor). The plan operates in one of three modes: `initial` (no anchor yet — process everything), `incremental` (delta from the anchor to HEAD), or `anchor-lost` (the anchor commit became unreachable; the plan falls back to a content-hash backstop). You do not need to choose the mode; the plan decides automatically.

**Classify phase.** For each node in the classify list, the skill dispatches `lazy-wiki.curator` as a synchronous subagent. The curator reads the real node on disk, chooses a `wiki_summary`, `wiki/*` topic tags, and connector phrases, then applies them itself via `apply-node` — which grafts the summary, tags, and connectors into the node's frontmatter or `<wiki>` block. The skill does not touch node content at all.

**Normalise phase.** After all classify writes land, the skill collects the full set of tag values now present in the scope and dispatches the curator once more to consolidate them. The curator examines the collected vocabulary, builds an alias map (merging synonyms, nesting subtypes), and applies it via `retag` — which rewrites every affected node's tags in one pass. An empty alias map is valid; the curator skips `retag` and reports so.

**Index rebuild.** The skill rebuilds `topics.md` once, after the normalise pass and before linking. This produces the freshly populated catalog the link phase reads.

**Link phase.** For each node in the link list, the skill first computes a ranked shortlist of topic-overlapping candidates, then dispatches the curator to verify those candidates against the node's content, select the genuinely related ones, gloss each from their `topics.md` entry (verbatim summary — no paraphrase), and apply the `see_also` section via `apply-node`. When the candidate list is empty, the curator selects targets from the full `topics.md` by judgment.

**Prune phase.** For each path in the drop list, the skill runs `prune-node` — a deterministic primitive, no curator involved — which drops any dangling See-also line elsewhere in the scope that still points at the now-deleted node. The index rebuild already dropped the node from `topics.md` itself; this phase cleans up the links pointing *at* it.

**Commit.** The skill stages every touched node file plus `topics.md`, records the new `wiki_synced_sha` anchor, and makes a single atomic commit under your operator identity. If an idempotent re-run produced no byte changes, no empty commit is created.

If the curator reports an error for a specific node (malformed input, a failed `apply-node`), the skill skips that node, continues with the rest, and surfaces the error in the report. The skipped node is picked up on the next relink.

**Daemon paths.** When the runtime daemon is active, curation happens without any `/wiki.relink` invocation. The `wiki.scan` routine watches every commit for changed files and calls `lazycortex-wiki process-file` for each one — the curator runs in tail-on mode and owns its own classify, link, and commit. The `wiki.scan-deletes` routine watches every commit for deleted files and calls `lazycortex-wiki prune-node` for each one — no curator dispatch, since there is no content left to judge; it drops dangling See-also links, rebuilds `topics.md`, and commits on its own. The `wiki.relink-weekly` routine calls `lazycortex-wiki relink-all` on a cron schedule, dispatching a classify job for every node regardless of change — the primary mechanism for vocabulary consolidation across a mature scope. All three routines are seeded by `/wiki.install` and managed by the core runtime; you do not invoke them directly.

## Common adjustments

**Scope not recognised.** If `/wiki.relink` reports "unknown scope", the scope id is not in your wiki settings. Run `/wiki.configure` to create or correct it, then re-invoke.

**Anchor lost after a rebase or reset.** The plan detects this automatically and switches to `anchor-lost` mode using a content-hash backstop. The run proceeds normally and records a fresh anchor at the end — you do not need to do anything.

**Tag vocabulary is drifting.** The normalise step runs automatically on every relink, but it only sees values that exist after the current classify pass. If you want to consolidate tags across an already-classified scope without relinking everything, invoke `/wiki.relink` on that scope — the plan will return an `incremental` set of changed nodes and the normalise pass will tidy the vocabulary.

**Selecting a specific scope.** Pass the scope id directly: `/wiki.relink <scope-id>`. The skill skips the interactive prompt.

**Daemon routines not seeded.** If `wiki.scan`, `wiki.scan-deletes`, or `wiki.relink-weekly` are missing from your settings, run `/wiki.install` — it seeds all three (absent-only, so existing configuration is untouched).

## How the pieces fit together

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  relinkInvoked[wiki.relink invoked]
  relinkPlan[relink-plan produces classify, link, drop lists]
  curatorClassify[Curator agent runs classify phase via apply-node]
  normalizeTags[normalize-tags consolidates vocabulary via retag]
  buildIndex[build-index rebuilds topics.md]
  curatorLink[Curator agent runs link phase via apply-node]
  pruneNode[prune-node drops dangling See-also lines]
  relinkCommit[relink commits touched files and records wiki_synced_sha anchor]

  relinkInvoked -->|invoke| relinkPlan
  relinkPlan -->|classify list| curatorClassify
  curatorClassify -->|nodes classified| normalizeTags
  normalizeTags -->|tags retagged| buildIndex
  buildIndex -->|link list| curatorLink
  curatorLink -->|nodes linked| pruneNode
  relinkPlan -->|drop list| pruneNode
  pruneNode -->|dangling links pruned| relinkCommit

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px

  class relinkInvoked entry
  class relinkPlan action
  class curatorClassify action
  class normalizeTags action
  class buildIndex action
  class curatorLink action
  class pruneNode action
  class relinkCommit success
```

## See also

- [install-and-audit](install-and-audit.md) — Bootstrap lazycortex-wiki in your project, compose the wiki-curator expert, and register the scan and weekly routines.
- [query](query.md) — Associative Q&A over the wiki graph built by this block.
