---
iconize_icon: LiInfo
iconize_color: "#fca5a5"
---
# lazycortex-wiki

Maintains a curated, LLM-navigable semantic wiki over a markdown+code base — summaries, hierarchical topic tags, and glossed See-also links, kept in sync via git-watch and weekly full-scan routines.

## Why this plugin

`lazycortex-wiki` turns a flat markdown- and code-base into a curated, LLM-navigable semantic wiki. On every node (markdown document or code file) a curator expert maintains a one-line summary, hierarchical topic tags, and a glossed See-also section; at the scope level it maintains a topic-index tree. Connections are kept in sync incrementally via two git-watch routines (one reacts to changed nodes per commit; one prunes dangling See-also links when a node is deleted) and a weekly full-scan routine (integrity sweep). The primary consumer is not a human but an LLM agent: glosses let the agent decide whether to open a linked node without opening it, and summaries make graph traversal cheap.

## Who it's for

- Developers and teams who want an LLM-navigable knowledge layer over their codebase or documentation without migrating to a dedicated wiki tool — everything materialises as plain markdown and code comments.
- Developers who want a curator specialist that builds and maintains the wiki incrementally as part of their normal git workflow.

## Blocks

- **curation** — Per-node curator dispatch: curate one node's summary, topic tags, and See-also links; update the topic index. Members: wiki.relink.
- **query** — Associative Q&A over the wiki graph. `/lazy-wiki.query` dispatches a per-scope `lazy-wiki.seeker` to pick entry points from the topic index, then a single `lazy-wiki.gatherer` to traverse glossed See-also links and synthesise the answer — the large index and node bodies stay in the subagents' contexts. Members: wiki.query.
- **audit** — Integrity checks across the scope: orphan topics, broken links, missing summaries, stale glosses, unknown axes, overlapping scopes. Members: wiki.doctor.
- **install-and-audit** — Bootstrap lazycortex-wiki in your project: create scope config, register routines, compose the wiki.curator expert, sync the navigation and structure rules. Members: wiki.install, wiki.configure, wiki.doctor, wiki.help.
- **structure** — One repo-wide map, `docs/structure.md`, of what lives where. `/lazy-wiki.structure rebuild` walks the tracked tree and rewrites it; `/lazy-wiki.structure query [<path>]` returns just the slice a caller needs; three git-watch routines dispatch a curator that keeps the map current per commit (changed, deleted, and renamed paths), wired by `/lazy-wiki.configure structure`. Members: wiki.structure.
- **terms** — One dictionary per scope so a concept never grows a second name. A writing expert asks `/lazy-wiki.terms` for the repository's agreed word before coining one; a curator fills the dictionary from finished documents on a git-watch routine, and the terms section of `/lazy-wiki.doctor` reports where documents and dictionary have drifted apart. Members: wiki.terms.
- **domains** — Query the generated domain-spec tree (`docs/domains/` by default, materialized from code's `Domain(…)` markers) for a group's doc section or a term across the whole tree, without loading the whole group doc or the tree. Members: wiki.domains.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the expert runtime, routine registry, and repo resolver.

## Quick start

1. Install the plugin (`/plugin install lazycortex-wiki@lazycortex`).
2. Run `/lazy-wiki.install` to register routines, compose the wiki.curator expert, and sync the navigation rule.
3. Run `/lazy-wiki.configure` to create your first scope (paths, tag axes, topics index location).
4. Run `/lazy-wiki.relink <scope-id>` to curate all nodes in the scope and build the initial `topics.md`.
5. From then on the git-watch routine handles incremental updates on each commit automatically.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-wiki.configure` | Use when the user wants to add a wiki scope, change which paths the wiki covers, edit an existing scope's globs, axes, exclusions, or topics-index path — or set up domain-spec generation (`/lazy-wiki.configure domains`: code globs, dictionary, output tree, language) — or mirror a foreign repo's markdown into a scope (`/lazy-wiki.configure mirror`: source url/branch, source globs, excludes, mirror directory) — or set up a terms dictionary (`/lazy-wiki.configure terms`: which documents it serves, where the dictionary file lives, which documents are term sources) — or configure the project-structure map (`/lazy-wiki.configure structure`: depth profiles, exclusions, the three scan routines) — or edit the vault-wide wiki keys themselves (`/lazy-wiki.configure vault`: the `tag_axes` vocabulary every scope narrows from, the `exclude` globs every scope inherits). Wizard over .claude/lazy.settings.json[wiki.scopes] / [wiki.tag_axes] / [wiki.exclude] / [wiki.domains] / [terms.scopes] / [structure], one question per turn via AskUserQuestion; also refreshes the Coverage section of the installed navigation rule. |
| `lazy-wiki.doctor` | Run when the operator asks to check the wiki's health, or when the wiki misbehaves — `/lazy-wiki.query` misses material it should cover or returns entries that no longer exist, See-also links point at moved or deleted nodes, the topic index disagrees with the files on disk, or documents and the terms dictionary have drifted onto different words for one concept. Read-only audit of one scope or all; the repairs it CAN make (index rebuild, broken/stale See-also lines) are applied only after the operator confirms. |
| `lazy-wiki.domain-sync` | Use when the domain-spec tree needs regenerating right now — this checkout runs no runtime daemon, domain markers or the dictionary just changed and the operator wants the docs current, or a `/lazy-python.knowledge-sweep` backfill has landed. Computes the domain plan, dispatches the domain-spec writer synchronously per changed group, removes orphaned docs, rebuilds `domains.md`, and makes one commit under the operator identity. |
| `lazy-wiki.domains` | Use when a question needs domain knowledge synthesised from code's `Domain(…)` markers — defining a term, looking up a mechanic or formula, or surveying a group of related domain concepts — and `wiki.domains` is configured in this repo. A research skill: given a group key or a search term, hands back a bounded slice of the domain-spec tree (`docs/domains/` by default, materialized by `/lazy-wiki.domain-sync`) — one doc's section, or matching excerpts — never the whole group doc or the whole tree. Mirrors `lazy-wiki.structure`'s query mode, over the domain tree instead of the project structure map. |
| `lazy-wiki.install` | Run when the operator asks to set up the wiki in a repo, after a lazycortex-wiki update, or when wiki skills fail because the `lazy-wiki.navigation` rule, the `wiki`, `structure`, or `terms` settings section, or the `wiki.curator` / `wiki.terms-curator` / `wiki.structure-curator` expert is missing from the project. Bootstrap only — defining what the wiki covers is `/lazy-wiki.configure`, what the terms dictionary covers is `/lazy-wiki.configure terms`, and the structure map's profiles and routines are `/lazy-wiki.configure structure`. Idempotent and quiet on re-run; install scope is detected, never asked. |
| `lazy-wiki.query` | Use when a question needs material the wiki curates — 'why is it built this way', 'where is X described', 'what relates to Y', or any request whose answer lives in files a wiki scope covers. Run it BEFORE grepping or opening files in a covered scope, and whenever the user asks about a topic rather than a specific file. A research skill: given a question, it hands back a bounded matched slice of the wiki graph, never the whole topic index. With the `Agent` tool available it dispatches per-scope seekers plus one gatherer so the topic index and traversed node bodies never enter the calling context; without `Agent` (a one-shot expert job or subagent) it runs the same lookup agentless, reading the scope's topics.md directly in its own context. |
| `lazy-wiki.relink` | Use when a wiki scope's nodes need classifying and See-also linking right now — this checkout runs no runtime daemon, or the operator wants to force a relink instead of waiting for the `lazy-wiki.scan` / `lazy-wiki.relink-weekly` routines. Computes the plan (initial / incremental / anchor-lost), dispatches the wiki curator synchronously per node in tail-off mode, rebuilds `topics.md`, records the new anchor, and makes one commit under the operator identity. |
| `lazy-wiki.structure` | Use when an agent doing research (an architect deciding where a new file belongs, any expert asking 'where does X live in this repo') needs the project's structure map, or when the operator asks to resync `docs/structure.md` with the tree after files moved. Two modes: `rebuild` walks the tracked tree and rewrites the map; `query [<path>]` returns just the slice under `<path>` — the whole file is never loaded into the caller's context. |
| `lazy-wiki.terms` | Use when an expert or a live session is about to name a concept in a document and needs the repository's agreed word for it — the research skill that answers 'what do we call this here?' from the scope's terms dictionary. Two modes: look up one term's definition, or check a name you are about to coin against the terms already taken. Returns only the matching entries, never the whole dictionary; it never writes to the dictionary. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/audit.md) — Run integrity checks across a wiki scope, its terms dictionary, structure map, mirrors, and domain tree — with optional auto-repair.
- [curation](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/curation.md) — Curate wiki nodes in-session via /lazy-wiki.relink or via daemon routines — classify summaries and topic tags, normalise the tag vocabulary, build glossed See-also links, and prune links to deleted nodes.
- [domains](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/domains.md) — Query a generated reference tree built from code's Domain(…) comments — one section or one term at a time, never the whole tree.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/install-and-audit.md) — Bootstrap and maintain lazycortex-wiki — install, configure scopes plus vault-wide axes/domains/mirror/terms/structure, and audit everything for integrity.
- [query](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/query.md) — Associative Q&A over the wiki graph — /lazy-wiki.query runs in dispatcher mode (seeker + gatherer subagents) when the Agent tool is available, and agentless mode otherwise.
- [structure](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/structure.md) — Keep one repo-wide map, docs/structure.md, current — rebuild it wholesale, query a slice of it, or let git-watch routines patch it per commit.
- [terms](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/terms.md) — One agreed dictionary per scope, consulted at write-time and kept honest by a curator and a doctor audit, so a concept never grows a second name.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, querying the wiki, the terms dictionary, the structure map, and the domain-spec tree.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-wiki.curator` | Dispatch when a wiki node needs classification (kind=classify) or See-also linking (kind=link), or when a scope's tag values need consolidating (kind=normalize-tags). It applies its result via a deterministic primitive — apply-node for the per-node kinds, retag for normalize-tags (C-hybrid, no collector). The tail flag (default true) gates only the daemon tail after the apply. tail:true (daemon path): reads its job dir (request.json + source/context), then runs build-index, git-commit, dispatch-link. tail:false (/lazy-wiki.relink skill path): no job dir — reads the real files named in the dispatch prompt, applies, then stops (the skill owns build-index/commit). Has Bash; writes node content only via apply-node/retag, never by hand. |
| `lazy-wiki.domain-spec-writer` | Dispatched by the `lazy-wiki.domain-scan` / `lazy-wiki.domain-full` routines (daemon path — reads its job dir) and by the /lazy-wiki.domain-sync skill (tail:false path — data in the dispatch prompt); not for direct use. Writes one domain group's spec doc under the configured output tree: a whole-document rewrite with fixed Terms / Principles / Mechanics sections, formulas verified against the code the group's Domain(…) blocks annotate and recorded as Obsidian LaTeX, plus a trailing Contracts section for the group's attributed Contract: blocks, in the configured language. |
| `lazy-wiki.gatherer` | Dispatch from /lazy-wiki.query once, after the seekers have returned validated entry points. Walks the wiki graph from those entry points — following glossed See-also links and on-demand backlinks (grep) — reads only the relevant node bodies, and returns a synthesised answer with source links. Keeps all traversed node bodies out of the caller's context. |
| `lazy-wiki.seeker` | Dispatch from /lazy-wiki.query, one per configured wiki scope, to pick entry points for a question. Reads ONLY the one scope's topics.md named in the prompt and returns the relevant node paths (verbatim from the index) with their glosses — never traverses, never reads node bodies. Keeps the large topic catalog out of the caller's context. |
| `lazy-wiki.structure-curator` | Dispatch when a tracked path changed and the project-structure map may need its entry updated (kind=curate from the structure-scan routines, kind=rename from the rename routine — both read a job dir), or when the whole map must be checked against the tree (kind=report, from the structure section of `/lazy-wiki.doctor` — no job dir, the prompt names the real files). Owns `docs/structure.md` and nothing else: it never edits the files it describes, and on report it writes nothing at all. |
| `lazy-wiki.terms-curator` | Dispatch when a document just changed and the scope's terms dictionary may need a term (kind=curate, from the terms-scan routine — reads its job dir), or when a whole scope must be checked for terminology divergence (kind=report, from the terms section of `/lazy-wiki.doctor` — no job dir, the prompt names the real files). Owns the dictionary file and nothing else: it never edits the document that triggered it, and on report it writes nothing at all. |

## Commands

| Command | Description |
|---|---|
| `lazy-wiki.help` | Run when the operator asks what lazycortex-wiki can do, how the semantic wiki gets built, curated, or asked a question, or which verb sets up a scope — lists the wiki surface: install / configure / relink / query / doctor / domain-sync, plus the curator, seeker, gatherer, and domain-spec-writer agents those skills dispatch. |

## Rules

| Rule | Description |
|---|---|
| `lazy-wiki.navigation.md` | Discovery and navigation contract for the curated semantic wiki — when to query it instead of reading sources, how to enter it, follow glossed links, and find backlinks. |
| `lazy-wiki.structure.md` | Pointer to the project-structure map — consult it before placing a new file or directory, or when asked where something lives in this repo. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-wiki@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-wiki:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-wiki.configure
/lazy-wiki.doctor
/lazy-wiki.domain-sync
/lazy-wiki.domains
/lazy-wiki.install
/lazy-wiki.query
/lazy-wiki.relink
/lazy-wiki.structure
/lazy-wiki.terms
```
