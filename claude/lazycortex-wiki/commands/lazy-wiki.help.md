---
description: "Run when the operator asks what lazycortex-wiki can do, how the semantic wiki gets built, curated, or asked a question, or which verb sets up a scope — lists the wiki surface: install / configure / relink / query / doctor / domain-sync, plus the curator, seeker, gatherer, and domain-spec-writer agents those skills dispatch."
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-wiki** — curated, LLM-navigable semantic wiki over a markdown+code base. A curator expert maintains one-line summaries, hierarchical topic tags (`wiki/<axis>/<value>` in `tags:`), and glossed See-also links on every node; a topic-index tree (`topics.md`) provides a categorical entry point. Git-watch and weekly full-scan routines keep everything in sync incrementally.

**Skills** (invoke as `/<name>` or via Skill tool):

- `wiki.install` — bootstrap the plugin: create config directories, register the `wiki` settings section, register the git-watch (changed + deleted files) and weekly-scan routines, compose the `wiki.curator` expert, sync `lazy-wiki.navigation` rule to the consumer's rules directory, then point you at `/lazy-wiki.configure` for the first scope.
- `wiki.configure` — interactive wizard (one question at a time) to create or edit a scope: scope id, path globs (markdown and/or code), optional exclude paths, tag axes, topics-index path. Writes the scope entry to `lazy.settings.json[wiki.scopes]`. Invoked as `/lazy-wiki.configure domains`, configures domain-spec generation instead (`wiki.domains`: code globs, dictionary, output tree, language) and seeds the dictionary skeleton. Invoked as `/lazy-wiki.configure mirror`, registers a `mirror` block on an existing scope (source url/branch, source globs, excludes, mirror directory) so a foreign repo's markdown is mirrored into the vault as ordinary wiki nodes. Invoked as `/lazy-wiki.configure terms`, creates, edits, or removes a terms-dictionary scope (which documents it serves, the dictionary file, which documents are term sources) and registers that scope's scan routine. Invoked as `/lazy-wiki.configure structure`, configures the structure map's depth profiles and exclusions and registers its three scan routines.
- `wiki.relink` — daemon-free relink of one wiki scope: computes the relink plan, dispatches the wiki curator per node, rebuilds `topics.md`, and commits under the operator identity.
- `wiki.query` — associative Q&A over the wiki graph: a thin dispatcher that runs a per-scope `seeker` subagent to pick entry points from `topics.md`, then a single `gatherer` subagent to traverse glossed See-also links and synthesise the answer — keeping the large index and node bodies out of the main session.
- `wiki.doctor` — read-only integrity audit across a scope: orphan topics, broken See-also links, dangling `@`-prefixed links, topic-index desync, missing summaries, stale glosses, unknown axes, near-duplicate axis values, broken `<wiki>` blocks in code, overlapping scopes, mirror wiring (missing mirror dir, uncovered `mirror_path`, stale source clone, local edits a sync would erase); plus repo-level domain checks (missing dictionary, unknown groups/docs, stale `domain_hash`, routine mismatch) and per-scope terms checks (divergent, missing, duplicate, and dead terms, dictionary format, scope wiring), plus structure-map checks (map vs tree drift, depth-profile conformance, routine wiring). Run it by hand as `/lazy-wiki.doctor` whenever the wiki misbehaves.
- `wiki.domain-sync` — daemon-free domain-spec regeneration: computes the domain plan, dispatches the domain-spec writer per changed group, removes orphaned docs, rebuilds `domains.md`, and commits under the operator identity.
- `wiki.domains` — query the generated domain-spec tree for a group's doc section or a term across the whole tree, without loading the whole group doc or the tree into context.
- `wiki.terms` — consult the scope's terms dictionary before naming a concept: look up one term's definition, or check a name you are about to coin against the terms already taken. Returns only the matching entries, never the whole dictionary, and never writes to it.
- `wiki.structure` — resync or query the project-wide structure map (`docs/structure.md`): `rebuild` walks the tracked git tree and rewrites it, `query [<path>]` returns just the slice under `<path>` without loading the whole file into context.

**Agents** (dispatched by skills/routines, not invoked directly):

- `lazy-wiki.curator` — curates each node's summary, topic tags, and See-also links (classify + link phases); applies via `apply-node` and commits.
- `lazy-wiki.seeker` — read-only retrieval: reads one scope's `topics.md` and returns the entry points relevant to a `/lazy-wiki.query` question (paths verbatim).
- `lazy-wiki.gatherer` — traverses the graph from those entry points (See-also + on-demand backlinks), reads only relevant nodes, and synthesises the `/lazy-wiki.query` answer.
- `lazy-wiki.structure-curator` — owns `docs/structure.md`: on `curate`/`rename` it applies one path change to the map and commits; on `report` it returns where the map and the tree have drifted apart. Never edits the files it describes.
- `lazy-wiki.terms-curator` — owns the terms dictionary: on `curate` it reads one changed document and adds, widens, or splits a term, then commits; on `report` it returns where documents and dictionary have drifted apart. Never edits the documents themselves.
- `lazy-wiki.domain-spec-writer` — writes one domain group's spec doc from its `Domain(…)` blocks (fixed Terms / Principles / Mechanics sections, formulas verified against code, Obsidian LaTeX); dispatched by the domain routines and `/lazy-wiki.domain-sync`.

**Commands**:

- `lazy-wiki.help` — this listing.

**Rules:**

- `lazy-wiki.navigation` — discovery and navigation contract for the curated semantic wiki: when to query it instead of reading sources, how to follow glossed links and find backlinks.
- `lazy-wiki.structure` — pointer to the project-structure map; consult before placing a new file or when asked where something lives in the repo.

**Manual runs** (no daemon needed): mirror sync is a plain CLI call from any session — `lazycortex-wiki mirror-sync <scope-id>` fetches the source, syncs the mirror, and commits; `lazycortex-wiki mirror-plan <scope-id>` prints the dry-run plan as JSON. The daemon counterpart is the `lazy-wiki.mirror-sync.<scope-id>` schedule routine registered by `/lazy-wiki.install`.

<!-- help-block:start -->
**Documentation:**

- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, querying the wiki, the terms dictionary, the structure map, and the domain-spec tree.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-wiki/help/`.
<!-- help-block:end -->
