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
- **audit** — Integrity checks across the scope: orphan topics, broken links, missing summaries, stale glosses, unknown axes, overlapping scopes. Members: wiki.audit.
- **install-and-audit** — Bootstrap lazycortex-wiki in your project: create scope config, register routines, compose the wiki.curator expert, sync the navigation and structure rules. Members: wiki.install, wiki.configure, wiki.audit, wiki.help.
- **structure** — One repo-wide map, `docs/structure.md`, of what lives where. `/lazy-wiki.structure rebuild` walks the tracked tree and rewrites it; `/lazy-wiki.structure query [<path>]` returns just the slice a caller needs; three git-watch routines dispatch a curator that keeps the map current per commit (added, deleted, and renamed paths — a content edit never changes the tree's shape, so modifications are deliberately not watched), wired by `/lazy-wiki.configure structure`. Members: wiki.structure.
- **terms** — One dictionary per scope so a concept never grows a second name. A writing expert asks `/lazy-wiki.terms` for the repository's agreed word before coining one; a curator fills the dictionary from finished documents on a git-watch routine, and the terms section of `/lazy-wiki.audit` reports where documents and dictionary have drifted apart. Members: wiki.terms.
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
| `lazy-wiki.audit` | Run when the operator asks to check the wiki's health, or when the wiki misbehaves — `/lazy-wiki.query` misses covered material or returns entries that no longer exist, See-also links point at moved nodes, the topic index disagrees with the disk, or documents and the terms dictionary use different words for one concept. Read-only: it reports and leaves the repairs to the operator. |
| `lazy-wiki.configure` | Use when the user wants to add a wiki scope or change what one covers — paths, axes, exclusions, topics index — or to set up domain specs (`domains`), a foreign-repo mirror (`mirror`), a terms dictionary (`terms`), the structure map (`structure`), or the vault-wide wiki keys (`vault`). Defines coverage only; bootstrapping the plugin is `/lazy-wiki.install`. |
| `lazy-wiki.domain-sync` | Use when the domain-spec tree needs regenerating right now — this checkout runs no runtime daemon, domain markers or the dictionary just changed and the operator wants the docs current, or a `/lazy-python.knowledge-sweep` backfill has landed. An optional group key limits the run to one group; reading the tree is `/lazy-wiki.domains`. |
| `lazy-wiki.domains` | Use when a question needs domain knowledge from code's `Domain(…)` markers — defining a term, looking up a mechanic or formula, or surveying a group of related concepts — and `wiki.domains` is configured. A research skill: it hands back a bounded slice of the domain-spec tree, never the whole tree; regenerating the tree is `/lazy-wiki.domain-sync`. |
| `lazy-wiki.install` | Run when the operator asks to set up the wiki in a repo, after a lazycortex-wiki update, or when wiki skills fail because the `lazy-wiki.navigation` rule, a `wiki` / `structure` / `terms` settings section, or a wiki expert is missing. Bootstrap only — what the wiki, the terms dictionary or the structure map covers is `/lazy-wiki.configure`. |
| `lazy-wiki.query` | Use when a question needs material the wiki curates — 'why is it built this way', 'where is X described', 'what relates to Y', or any request whose answer lives in files a wiki scope covers. Run it BEFORE grepping or opening files in a covered scope. A research skill: it hands back a bounded matched slice of the wiki graph, so the topic index never enters the calling context. |
| `lazy-wiki.relink` | Use when a wiki scope's nodes need classifying and See-also linking right now — this checkout runs no runtime daemon, or the operator wants to force a relink instead of waiting for the `lazy-wiki.scan` / `lazy-wiki.relink-weekly` routines. |
| `lazy-wiki.structure` | Use when an agent doing research (an architect deciding where a new file belongs, any expert asking 'where does X live in this repo') needs the project's structure map, or when the operator asks to resync `docs/structure.md` after files moved. `query [<path>]` returns just the slice under `<path>`; `rebuild` rewrites the map. |
| `lazy-wiki.terms` | Use when an expert or a live session is about to name a concept in a document and needs the repository's agreed word for it — the research skill that answers 'what do we call this here?' from the scope's terms dictionary. It looks up one term or checks a name about to be coined, and returns only the matching entries. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/plugins/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, mirroring foreign repos, querying the wiki, the terms dictionary, the structure map, the domain-spec tree, the tag-values canon, and the wiki's own writing language.

## Agents

| Agent | Description |
|---|---|
| `lazy-wiki.curator` | Dispatch when a wiki node needs classification (kind=classify) or See-also linking (kind=link) — from the daemon's scan routines or `/lazy-wiki.relink`. Consolidating a surface's tag values is the sibling `lazy-wiki.tag-curator`'s job, not this one's. |
| `lazy-wiki.domain-spec-writer` | Dispatched by the `lazy-wiki.domain-scan` / `lazy-wiki.domain-full` routines and /lazy-wiki.domain-sync; not for direct use. |
| `lazy-wiki.gatherer` | Dispatch from /lazy-wiki.query once, after the seekers have returned validated entry points. Walks the wiki graph from those entry points — following glossed See-also links and on-demand backlinks (grep) — reads only the relevant node bodies, and returns a synthesised answer with source links. Keeps all traversed node bodies out of the caller's context. |
| `lazy-wiki.seeker` | Dispatch from /lazy-wiki.query, one per configured wiki scope, to pick entry points for a question. Reads ONLY the one scope's topics.md named in the prompt and returns the relevant node paths (verbatim from the index) with their glosses — never traverses, never reads node bodies. Keeps the large topic catalog out of the caller's context. |
| `lazy-wiki.structure-curator` | Dispatch when a tracked path changed and the project-structure map may need its entry updated (kind=curate or kind=rename, from the structure routines), or when the whole map must be checked against the tree (kind=report, from `/lazy-wiki.audit`). Owns `docs/structure.md` only and never edits the files it describes. |
| `lazy-wiki.tag-curator` | Dispatch when one tag surface's axis values need consolidating into a canon (kind=normalize-tags) — a wiki scope or the generated domain-doc tree — from the `tag-tick` schedule or `/lazy-wiki.relink` mid-run. Classifying and See-also linking a single node is the sibling `lazy-wiki.curator`'s job. |
| `lazy-wiki.terms-curator` | Dispatch when a document just changed and the scope's terms dictionary may need a term (kind=curate, from the terms-scan routine), or when a whole scope must be checked for terminology divergence (kind=report, from `/lazy-wiki.audit`). Owns the dictionary file only; looking a term up is `/lazy-wiki.terms`. |

## Commands

| Command | Description |
|---|---|
| `lazy-wiki.help` | Run when the operator asks what lazycortex-wiki can do, how the semantic wiki gets built, curated, or asked a question, or which verb sets up a scope — lists the wiki surface: install / configure / relink / query / audit / domain-sync, plus the curator, seeker, gatherer, and domain-spec-writer agents those skills dispatch. |

## Rules

| Rule | Description |
|---|---|
| `lazy-wiki.navigation.md` | Discovery and navigation contract for the curated wiki and the domain tree — when to query them instead of reading sources, and where the wiki's node format is described. |
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
/lazy-wiki.audit
/lazy-wiki.configure
/lazy-wiki.domain-sync
/lazy-wiki.domains
/lazy-wiki.install
/lazy-wiki.query
/lazy-wiki.relink
/lazy-wiki.structure
/lazy-wiki.terms
```
