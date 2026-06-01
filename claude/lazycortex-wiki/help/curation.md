---
chapter_type: block
summary: Relink a wiki scope in-session — classify nodes, normalise the tag vocabulary, and build glossed See-also links — using the curator agent as a synchronous subagent.
last_regen: 2026-06-01
diagram_spec:
  anchor: "How the pieces fit together"
  request: "Flow diagram showing /wiki.relink driving the curation block: (1) relink-plan produces classify[], link[], drop[] lists; (2) curator agent runs classify per node via apply-node; (3) normalize-tags consolidates the tag vocabulary via retag; (4) build-index rebuilds topics.md; (5) curator agent runs link per node via apply-node; (6) relink commits all touched files and records the wiki_synced_sha anchor. Show that the curator agent is dispatched twice (classify phase, link phase) and that the skill owns the single commit."
  kind_hint: flow
source_skills:
  - lazy-wiki.relink
  - lazy-wiki.curator
---
# Curation

When you run `/wiki.relink`, you get a fully curated wiki scope without needing the runtime daemon. Every changed node receives a one-line summary and hierarchical topic tags (so it shows up in the scope's topic index), then a See-also section whose entries are glossed with the target's summary (so an agent can judge relevance without opening the target file). The entire process runs synchronously in the current Claude Code session and ends with a single atomic commit.

Two pieces share this work. `/wiki.relink` is the orchestrator: it computes what to process, fires the curator agent for each node, rebuilds the topic index at the right moment, and makes the commit. `lazy-wiki.curator` is the expert: it reads each node in place, applies editorial judgment, and writes the result directly to the file via the deterministic `apply-node` or `retag` primitives — it never hand-edits. The two pieces are cleanly separated: the skill owns the index rebuild and the commit; the curator owns every write to node content.

## When you'd use this

- You want the LLM-navigable wiki layer in place immediately, without waiting for the background daemon to process a backlog.
- A batch of files changed (code refactor, docs overhaul, imported content) and you want all summaries, tags, and See-also links updated in one go before the next review.
- You are working in a project that runs without the runtime daemon and need the wiki to stay current after each session's changes.
- You need to force a full rescan of a scope — for example after a rebase or a `reset --hard` that orphaned the previous sync anchor.

## How it fits together

You invoke `/wiki.relink [<scope-id>]`. If you omit the scope id, the skill lists the configured scopes and asks you which to process.

The skill starts by running `relink-plan`, which inspects the `wiki_synced_sha` anchor stored in `topics.md` and returns three path lists — nodes to classify (new or modified), nodes to link (whose summary or neighbours changed), and nodes to drop (deleted since the anchor). The plan operates in one of three modes: `initial` (no anchor yet — process everything), `incremental` (delta from the anchor to HEAD), or `anchor-lost` (the anchor commit became unreachable; the plan falls back to a content-hash backstop). You do not need to choose the mode; the plan decides automatically.

**Classify phase.** For each node in the classify list, the skill dispatches `lazy-wiki.curator` as a synchronous subagent in `tail:false` mode. The curator reads the real node on disk, chooses a `wiki_summary`, `wiki/*` topic tags, and connector phrases, writes a temporary curation file outside the repo, then applies it via `apply-node` — which grafts the summary, tags, and connectors into the node's frontmatter or `<wiki>` block. The curator then removes its temp file and returns. The skill does not touch node content at all.

**Normalise phase.** After all classify writes land, the skill runs `collect-tags` to gather the full set of tag values now present in the scope, then dispatches the curator once more with `kind=normalize-tags`. The curator examines the collected vocabulary, builds an alias map (merging synonyms, nesting subtypes), and applies it via `retag` — which rewrites every affected node's tags in one pass. An empty alias map is valid; the curator skips `retag` and reports `empty`.

**Index rebuild.** The skill runs `build-index` once, after the normalise pass and before linking. This produces the freshly populated `topics.md` that the link phase reads.

**Link phase.** For each node in the link list, the skill first runs `find-candidates` to get a ranked shortlist of topic-overlapping nodes, then dispatches the curator with `kind=link`. The curator verifies those candidates against the node's content, selects the genuinely related ones, glosses each from their `topics.md` entry (verbatim summary — no paraphrase), and applies the `see_also` section via `apply-node`. When the candidate list is empty, the curator selects targets from the full `topics.md` by judgment.

**Commit.** The skill stages every touched node file plus `topics.md`, records the new `wiki_synced_sha` anchor, and makes a single atomic commit with a message in the form `wiki(relink): <scope-id> (<mode>, classify N / link M / drop K)`. If an idempotent re-run produced no byte changes, no empty commit is created.

If the curator reports an error for a specific node (malformed input, a failed `apply-node`), the skill skips that node, continues with the rest, and surfaces the error in the report. The skipped node is picked up on the next relink.

## Common adjustments

**Scope not recognised.** If `/wiki.relink` reports "unknown scope", the scope id is not in your wiki settings. Run `/wiki.configure` to create or correct it, then re-invoke.

**Anchor lost after a rebase or reset.** The plan detects this automatically and switches to `anchor-lost` mode using a content-hash backstop. The run proceeds normally and records a fresh anchor at the end — you do not need to do anything.

**Tag vocabulary is drifting.** The normalise step runs automatically on every relink, but it only sees values that exist after the current classify pass. If you want to consolidate tags across an already-classified scope without relinking everything, invoke `/wiki.relink` on that scope — the plan will return an `incremental` set of changed nodes and the normalise pass will tidy the vocabulary.

**Selecting a specific scope.** Pass the scope id directly: `/wiki.relink <scope-id>`. The skill skips the interactive prompt.

## How the pieces fit together

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  wikiRelink[/wiki.relink skill]
  relinkPlan[relink-plan]
  classifyList[[classify list]]
  linkList[[link list]]
  dropList[[drop list]]
  curatorClassify[curator agent — classify phase]
  applyNodeClassify[apply-node per classify item]
  normalizeTags[normalize-tags]
  retag[retag]
  buildIndex[build-index]
  topicsMd[(topics.md)]
  curatorLink[curator agent — link phase]
  applyNodeLink[apply-node per link item]
  commitStep[relink — commit all touched files]
  wikiSyncedSha[(wiki_synced_sha anchor)]

  wikiRelink -->|invoke| relinkPlan
  relinkPlan -->|emit| classifyList
  relinkPlan -->|emit| linkList
  relinkPlan -->|emit| dropList
  classifyList -->|dispatch| curatorClassify
  curatorClassify -->|call| applyNodeClassify
  applyNodeClassify -->|classified| normalizeTags
  normalizeTags -->|call| retag
  retag -->|consolidated| buildIndex
  buildIndex -->|write| topicsMd
  topicsMd -->|ready| curatorLink
  linkList -->|dispatch| curatorLink
  curatorLink -->|call| applyNodeLink
  applyNodeLink -->|linked| commitStep
  dropList -->|pass-through| commitStep
  commitStep -->|record| wikiSyncedSha

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef sub fill:#2e2240,stroke:#7e63a8,color:#fff
  classDef store fill:#5f3a1e,stroke:#e2904a,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px

  class wikiRelink entry
  class relinkPlan action
  class curatorClassify sub
  class curatorLink sub
  class applyNodeClassify action
  class applyNodeLink action
  class normalizeTags action
  class retag action
  class buildIndex action
  class commitStep success
  class classifyList store
  class linkList store
  class dropList store
  class topicsMd store
  class wikiSyncedSha store
```

## See also

- [install-and-audit](install-and-audit.md) — Bootstrap lazycortex-wiki in your project, compose the wiki-curator expert, and register the scan and weekly routines.
- [query](query.md) — Associative Q&A over the wiki graph built by this block.
