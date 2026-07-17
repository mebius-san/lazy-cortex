## Why this plugin

`lazycortex-wiki` turns a flat markdown- and code-base into a curated, LLM-navigable semantic wiki. On every node (markdown document or code file) a curator expert maintains a one-line summary, hierarchical topic tags, and a glossed See-also section; at the scope level it maintains a topic-index tree. Connections are kept in sync incrementally via two git-watch routines (one reacts to changed nodes per commit; one prunes dangling See-also links when a node is deleted) and a weekly full-scan routine (integrity sweep). The primary consumer is not a human but an LLM agent: glosses let the agent decide whether to open a linked node without opening it, and summaries make graph traversal cheap.

## Who it's for

- Developers and teams who want an LLM-navigable knowledge layer over their codebase or documentation without migrating to a dedicated wiki tool — everything materialises as plain markdown and code comments.
- Developers who want a curator specialist that builds and maintains the wiki incrementally as part of their normal git workflow.

## Blocks

- **curation** — Per-node curator dispatch: curate one node's summary, topic tags, and See-also links; update the topic index. Members: wiki.relink.
- **query** — Associative Q&A over the wiki graph. `/wiki.query` dispatches a per-scope `lazy-wiki.seeker` to pick entry points from the topic index, then a single `lazy-wiki.gatherer` to traverse glossed See-also links and synthesise the answer — the large index and node bodies stay in the subagents' contexts. Members: wiki.query.
- **audit** — Integrity checks across the scope: orphan topics, broken links, missing summaries, stale glosses, unknown axes, overlapping scopes. Members: wiki.doctor.
- **install-and-audit** — Bootstrap lazycortex-wiki in your project: create scope config, register routines, compose the wiki-curator expert, sync the navigation rule. Members: wiki.install, wiki.configure, wiki.doctor, wiki.help.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the expert runtime, routine registry, and repo resolver.

## Quick start

1. Install the plugin (`/plugin install lazycortex-wiki@lazycortex`).
2. Run `/wiki.install` to register routines, compose the wiki-curator expert, and sync the navigation rule.
3. Run `/wiki.configure` to create your first scope (paths, tag axes, topics index location).
4. Run `/wiki.relink <scope-id>` to curate all nodes in the scope and build the initial `topics.md`.
5. From then on the git-watch routine handles incremental updates on each commit automatically.
