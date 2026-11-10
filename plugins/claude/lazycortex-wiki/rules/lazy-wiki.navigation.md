---
description: Discovery and navigation contract for the curated wiki and the domain tree — when to query them instead of reading sources, and where the wiki's node format is described.
always_loaded: "wiki navigation is a cross-cutting concern — any agent working in a wiki-enabled repo must know the entry points and conventions on every turn"
---
# Wiki navigation

A curated semantic wiki may exist in this repo. Its entry points are the `topics_index` path(s) declared in `.claude/lazy.settings.json[wiki.scopes]`.

## When to query (MANDATORY)

**Do not answer from your own reading of the sources when the question is about material a covered scope holds.** Coverage is the `paths` globs listed under `## Coverage` below. When the answer would come from files matching one of them, `/lazy-wiki.query "<question>"` runs first — before Grep, before Glob, before opening a file in the scope. Read specific files afterwards, once the wiki has named them.

Grepping a covered scope blind, opening nodes one by one, or answering from memory of an earlier session is the violation. Outside a covered scope, work normally.

With the `Agent` tool, never read `topics.md` yourself: `/lazy-wiki.query` fans out to subagents that hold the catalog and return only entry points and an answer. On a node, follow its See-also glosses directly.

Without the `Agent` tool (an expert job, a leaf subagent), `/lazy-wiki.query`'s agentless mode applies: read the scope's `topics.md`, pick entry points, follow glossed links yourself.

## Coverage

Written here by `/lazy-wiki.configure` when a scope is created or edited. Until it has run, read `.claude/lazy.settings.json[wiki.scopes]` once before deciding whether a question is covered.

## Domain knowledge (MANDATORY)

The domain tree documents the knowledge written as `Domain(…)` comments in code: one document per comment, a folder per group, an index. **When the question is about a rule, mechanic or formula in code matched by `## Domain coverage` below, run `/lazy-wiki.domains` first — before Grep, before opening the code.** Read the code afterwards, to verify. Answering from the code alone, or grepping covered code blind, is the violation. A document's `## Discrepancies` names where its comment and the code disagree; there the code is the truth, and the answer says so.

## Domain coverage

Written here by `/lazy-wiki.install` and `/lazy-wiki.configure domains`. Until then, read `.claude/lazy.settings.json[wiki.domains]` once; no key means no domain tree.

## Node format

Inside a wiki node, read `${CLAUDE_PLUGIN_ROOT}/references/lazy-wiki.node-format.md`: summary, topic tags, glossed See-also links, backlinks.
