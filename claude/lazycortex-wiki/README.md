---
iconize_icon: LiInfo
iconize_color: "#fde68a"
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
- **query** — Associative Q&A over the wiki graph. `/wiki.query` dispatches a per-scope `lazy-wiki.seeker` to pick entry points from the topic index, then a single `lazy-wiki.gatherer` to traverse glossed See-also links and synthesise the answer — the large index and node bodies stay in the subagents' contexts. Members: wiki.query.
- **audit** — Integrity checks across the scope: orphan topics, broken links, missing summaries, stale glosses, unknown axes, overlapping scopes. Members: wiki.doctor.
- **install-and-audit** — Bootstrap lazycortex-wiki in your project: create scope config, register routines, compose the wiki.curator expert, sync the navigation rule. Members: wiki.install, wiki.configure, wiki.doctor, wiki.help.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the expert runtime, routine registry, and repo resolver.

## Quick start

1. Install the plugin (`/plugin install lazycortex-wiki@lazycortex`).
2. Run `/wiki.install` to register routines, compose the wiki.curator expert, and sync the navigation rule.
3. Run `/wiki.configure` to create your first scope (paths, tag axes, topics index location).
4. Run `/wiki.relink <scope-id>` to curate all nodes in the scope and build the initial `topics.md`.
5. From then on the git-watch routine handles incremental updates on each commit automatically.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-wiki.configure` | Use when the user wants to add a wiki scope, change which paths the wiki covers, or edit an existing scope's globs, axes, exclusions, or topics-index path. Wizard over .claude/lazy.settings.json[wiki.scopes], one question per turn via AskUserQuestion; also refreshes the Coverage section of the installed navigation rule. |
| `lazy-wiki.doctor` | Run when the operator asks to check the wiki's health, or when the wiki misbehaves — `/wiki.query` misses material it should cover or returns entries that no longer exist, See-also links point at moved or deleted nodes, the topic index disagrees with the files on disk. Read-only audit of one scope or all; the repairs it CAN make (index rebuild, broken/stale See-also lines) are applied only after the operator confirms. |
| `lazy-wiki.install` | Run when the operator asks to set up the wiki in a repo, after a lazycortex-wiki update, or when wiki skills fail because the `lazy-wiki.navigation` rule, the `wiki` settings section, or the `wiki.curator` expert is missing from the project. Bootstrap only — defining what the wiki covers is `/wiki.configure`. Idempotent and quiet on re-run; install scope is detected, never asked. |
| `lazy-wiki.query` | Use when a question needs material the wiki curates — 'why is it built this way', 'where is X described', 'what relates to Y', or any request whose answer lives in files a wiki scope covers. Run it BEFORE grepping or opening files in a covered scope, and whenever the user asks about a topic rather than a specific file. Dispatches per-scope seekers plus one gatherer, so the topic index and traversed node bodies never enter the calling context. |
| `lazy-wiki.relink` | Use when a wiki scope's nodes need classifying and See-also linking right now — this checkout runs no runtime daemon, or the operator wants to force a relink instead of waiting for the `wiki.scan` / `wiki.relink-weekly` routines. Computes the plan (initial / incremental / anchor-lost), dispatches the wiki curator synchronously per node in tail-off mode, rebuilds `topics.md`, records the new anchor, and makes one commit under the operator identity. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/audit.md) — Run integrity checks across a wiki scope — orphan topics, broken links, missing summaries, stale glosses, unknown axes, and overlapping scopes — with optional auto-repair.
- [curation](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/curation.md) — Curate wiki nodes in-session via /wiki.relink or via daemon routines — classify summaries and topic tags, normalise the tag vocabulary, build glossed See-also links, and prune links to deleted nodes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/install-and-audit.md) — Bootstrap lazycortex-wiki in a project — install, configure scopes, run integrity audits, and orient yourself with the built-in help command.
- [query](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/query.md) — Associative Q&A over the wiki graph — /wiki.query dispatches seekers to find entry points then a gatherer to traverse glossed See-also links and synthesise the answer.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, querying the wiki, and interpreting doctor findings.

(`mebius-san` resolves from `.guard-waivers.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-wiki.curator` | Dispatch when a wiki node needs classification (kind=classify) or See-also linking (kind=link), or when a scope's tag values need consolidating (kind=normalize-tags). It applies its result via a deterministic primitive — apply-node for the per-node kinds, retag for normalize-tags (C-hybrid, no collector). The tail flag (default true) gates only the daemon tail after the apply. tail:true (daemon path): reads its job dir (request.json + source/context), then runs build-index, git-commit, dispatch-link. tail:false (/wiki.relink skill path): no job dir — reads the real files named in the dispatch prompt, applies, then stops (the skill owns build-index/commit). Has Bash; writes node content only via apply-node/retag, never by hand. |
| `lazy-wiki.gatherer` | Dispatch from /wiki.query once, after the seekers have returned validated entry points. Walks the wiki graph from those entry points — following glossed See-also links and on-demand backlinks (grep) — reads only the relevant node bodies, and returns a synthesised answer with source links. Keeps all traversed node bodies out of the caller's context. |
| `lazy-wiki.seeker` | Dispatch from /wiki.query, one per configured wiki scope, to pick entry points for a question. Reads ONLY the one scope's topics.md named in the prompt and returns the relevant node paths (verbatim from the index) with their glosses — never traverses, never reads node bodies. Keeps the large topic catalog out of the caller's context. |

## Commands

| Command | Description |
|---|---|
| `lazy-wiki.help` | Show lazycortex-wiki purpose and a one-line summary of each skill, agent, and command it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-wiki.navigation.md` | Discovery and navigation contract for the curated semantic wiki — when to query it instead of reading sources, how to enter it, follow glossed links, and find backlinks. |

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
/lazy-wiki.install
/lazy-wiki.query
/lazy-wiki.relink
```
