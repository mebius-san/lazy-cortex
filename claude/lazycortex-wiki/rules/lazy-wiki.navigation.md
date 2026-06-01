---
description: Discovery and navigation contract for the curated semantic wiki. Tells agents how to enter the wiki, follow glossed links, find backlinks, and when to use /wiki.query.
always_loaded: "wiki navigation is a cross-cutting concern — any agent working in a wiki-enabled repo must know the entry points and conventions on every turn"
---
# Wiki navigation

A curated semantic wiki may exist in this repo. Its entry points are the `topics_index` path(s) declared in `.claude/lazy.settings.json[wiki.scopes]`.

**How nodes are structured.** Every wiki node carries a `wiki_summary` (one-line description) in its frontmatter and a `## See also (auto)` section with glossed relative-path links — each link followed by ` — <gloss>` that describes the target. Glosses let you decide whether to open a node without opening it. Topic tags live in `tags:` as `wiki/<axis>/<value>`.

**How to find material on a topic.** Use `/wiki.query "<question>"` — do NOT read `topics.md` into your own context for search. The skill dispatches retrieval subagents whose contexts hold the large topic catalog and the traversed node bodies, returning only the entry points and a synthesised answer. When you are already standing on a node, follow its See-also glosses directly. Do not grep blind when the wiki covers the question.

**How to find what links to a node.** Grep the node's repo-relative path across the scope. Cross-repo backlinks: resolve `repos.<key>.path` from `.claude/lazy.settings.json`, then grep in that repo.

**Cross-repo links** use the form `@<repo-key>/relative/path`; resolve via `repos` registry.

**To answer a question by traversal** — use `/wiki.query "<question>"`.

Detailed navigation protocol: `references/lazy-wiki.navigation-protocol.md` (read on demand).
