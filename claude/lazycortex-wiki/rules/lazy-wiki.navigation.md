---
description: Discovery and navigation contract for the curated semantic wiki — when to query it instead of reading sources, how to enter it, follow glossed links, and find backlinks.
always_loaded: "wiki navigation is a cross-cutting concern — any agent working in a wiki-enabled repo must know the entry points and conventions on every turn"
---
# Wiki navigation

A curated semantic wiki may exist in this repo. Its entry points are the `topics_index` path(s) declared in `.claude/lazy.settings.json[wiki.scopes]`.

## When to query (MANDATORY)

**Do not answer from your own reading of the sources when the question is about material a covered scope holds.** Coverage is the `paths` globs listed under `## Coverage` below. When the answer would come from files matching one of them, `/wiki.query "<question>"` runs first — before Grep, before Glob, before opening a file in the scope. Read specific files afterwards, once the wiki has named them.

This forbids the alternative; it is not a preference. Grepping a covered scope blind, opening nodes one by one to find the relevant one, and answering from memory of an earlier session are each the violation — they miss the glosses and See-also edges that say which node actually answers the question. Outside a covered scope, work normally.

Do **not** read `topics.md` into your own context to search it. `/wiki.query` dispatches retrieval subagents whose contexts hold the topic catalog and the traversed node bodies, returning only entry points and a synthesised answer. When you are already standing on a node, follow its See-also glosses directly.

## Coverage

Written here by `/wiki.configure` when a scope is created or edited. Until it has run, read `.claude/lazy.settings.json[wiki.scopes]` once before deciding whether a question is covered.

## How nodes are structured

Every wiki node carries a `wiki_summary` (one-line description) in its frontmatter and a `# See also` section (tagged `#protected/wiki/see-also` on its first line) with glossed relative-path links — each link followed by ` — <gloss>` that describes the target. Glosses let you decide whether to open a node without opening it. Topic tags live in `tags:` as `wiki/<axis>/<value>`.

**Backlinks** — grep the node's repo-relative path across the scope. Cross-repo: resolve `repos.<key>.path` from `.claude/lazy.settings.json`, then grep in that repo. Cross-repo links use the form `@<repo-key>/relative/path`.
