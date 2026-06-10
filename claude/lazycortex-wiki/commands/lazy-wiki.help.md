---
description: Show lazycortex-wiki purpose and a one-line summary of each skill, agent, and command it ships
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-wiki** — curated, LLM-navigable semantic wiki over a markdown+code base. A curator expert maintains one-line summaries, hierarchical topic tags (`wiki/<axis>/<value>` in `tags:`), and glossed See-also links on every node; a topic-index tree (`topics.md`) provides a categorical entry point. Git-watch and weekly full-scan routines keep everything in sync incrementally.

**Skills** (invoke as `/<name>` or via Skill tool):

- `wiki.install` — bootstrap the plugin: create config directories, register the `wiki` settings section, register the git-watch and weekly-scan routines, compose the `wiki-curator` expert, sync `lazy-wiki.navigation` rule to the consumer's rules directory, and optionally create the first scope.
- `wiki.configure` — interactive wizard (one question at a time) to create or edit a scope: scope id, path globs (markdown and/or code), optional exclude paths, tag axes, topics-index path. Writes the scope entry to `lazy.settings.json[wiki.scopes]`.
- `wiki.relink-doc` — curate a single node: dispatch the `wiki-curator` expert for that node, then run the deterministic pass to update the topic index.
- `wiki.relink-all` — full pass over all nodes in a scope: `wiki.relink-doc` per node, then full rebuild of `topics.md`.
- `wiki.query` — associative Q&A over the wiki graph: a thin dispatcher that runs a per-scope `seeker` subagent to pick entry points from `topics.md`, then a single `gatherer` subagent to traverse glossed See-also links and synthesise the answer — keeping the large index and node bodies out of the main session.
- `wiki.doctor` — read-only integrity audit across a scope: orphan topics, broken See-also links, broken repo-keys, topic-index desync, missing summaries, stale glosses, unknown axes, near-duplicate axis values, broken `<wiki>` blocks in code, overlapping scopes.

**Agents** (dispatched by skills/routines, not invoked directly):

- `lazy-wiki.curator` — curates each node's summary, topic tags, and See-also links (classify + link phases); applies via `apply-node` and commits.
- `lazy-wiki.seeker` — read-only retrieval: reads one scope's `topics.md` and returns the entry points relevant to a `/wiki.query` question (paths verbatim).
- `lazy-wiki.gatherer` — traverses the graph from those entry points (See-also + on-demand backlinks), reads only relevant nodes, and synthesises the `/wiki.query` answer.

**Commands**:

- `lazy-wiki.help` — this listing.

<!-- help-block:start -->
**Documentation:**

- [audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/audit.md) — Run integrity checks across a wiki scope — orphan topics, broken links, missing summaries, stale glosses, unknown axes, and overlapping scopes — with optional auto-repair.
- [curation](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/curation.md) — Curate wiki nodes in-session or via daemon routines — classify summaries and topic tags, normalise the tag vocabulary, and build glossed See-also links.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/install-and-audit.md) — Bootstrap lazycortex-wiki in a project — install, configure scopes, run integrity audits, and orient yourself with the built-in help command.
- [query](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/query.md) — Associative Q&A over the wiki graph — /wiki.query dispatches seekers to find entry points then a gatherer to traverse glossed See-also links and synthesise the answer.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, querying the wiki, and interpreting doctor findings.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-wiki/help/`.
<!-- help-block:end -->
