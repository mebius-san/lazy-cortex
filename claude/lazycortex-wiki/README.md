---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-wiki

Maintains a curated, LLM-navigable semantic wiki over a markdown+code base — summaries, hierarchical topic tags, and glossed See-also links, kept in sync via git-watch and weekly full-scan routines.

## Why this plugin

`lazycortex-wiki` turns a flat markdown- and code-base into a curated, LLM-navigable semantic wiki. On every node (markdown document or code file) a curator expert maintains a one-line summary, hierarchical topic tags, and a glossed See-also section; at the scope level it maintains a topic-index tree. Connections are kept in sync incrementally via a git-watch routine (reacts to changed nodes per commit) and a weekly full-scan routine (integrity sweep). The primary consumer is not a human but an LLM agent: glosses let the agent decide whether to open a linked node without opening it, and summaries make graph traversal cheap.

## Who it's for

- Developers and teams who want an LLM-navigable knowledge layer over their codebase or documentation without migrating to a dedicated wiki tool — everything materialises as plain markdown and code comments.
- Developers who want a curator specialist that builds and maintains the wiki incrementally as part of their normal git workflow.

## Blocks

- **curation** — Per-node curator dispatch: curate one node's summary, topic tags, and See-also links; update the topic index. Members: wiki.relink-doc, wiki.relink-all.
- **query** — Associative Q&A by traversing the wiki graph via glossed See-also links and the topic index. Members: wiki.query.
- **audit** — Integrity checks across the scope: orphan topics, broken links, missing summaries, stale glosses, unknown axes, overlapping scopes. Members: wiki.doctor.
- **install-and-audit** — Bootstrap lazycortex-wiki in your project: create scope config, register routines, compose the wiki-curator expert, sync the navigation rule. Members: wiki.install, wiki.configure, wiki.doctor, wiki.help.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the expert runtime, routine registry, and repo resolver.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-wiki.configure` | Wizard to create or edit a wiki scope in .claude/lazy.settings.json — collects id, path globs, optional exclude_paths, tag_axes, and topics_index. Strict one-question-per-turn via AskUserQuestion. |
| `lazy-wiki.doctor` | Audit a wiki scope's integrity: orphan topics, broken See-also links and repo keys, index desync, missing summaries, stale glosses, unknown axes, duplicate branches, broken code <wiki> blocks, and scope overlaps. Read-only by default; applies fixable repairs only after the operator confirms. |
| `lazy-wiki.install` | Bootstrap the lazycortex-wiki plugin for the current project (or globally). Creates the template dir, syncs the navigation rule, seeds wiki settings + agent_models + routines + expert entry. Idempotent — safe to re-run. |
| `lazy-wiki.query` | Associative Q&A over the wiki graph. Thin dispatcher: a per-scope seeker subagent picks entry points from topics.md, a single gatherer subagent traverses See-also and synthesises the answer. The large topic index and traversed node bodies stay in the subagents' contexts, never the main session. |
| `lazy-wiki.relink` | Daemon-free, in-session relink of one wiki scope. Computes the relink plan (initial / incremental / anchor-lost) via lazycortex-wiki relink-plan, then dispatches the wiki curator as a synchronous subagent in tail:false mode to classify then link each node — the curator applies its own curation via apply-node (C-hybrid, no collector). The skill rebuilds topics.md once between phases, records the new wiki_synced_sha anchor, and makes the single commit under the operator identity. Use when there is no runtime daemon (the plugin must work standalone) or to force an in-session relink. |

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

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/audit.md) — Run integrity checks across a wiki scope — orphan topics, broken links, missing summaries, stale glosses, unknown axes, and overlapping scopes — with optional auto-repair.
- [curation](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/curation.md) — Curate wiki nodes in-session or via daemon routines — classify summaries and topic tags, normalise the tag vocabulary, and build glossed See-also links.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/install-and-audit.md) — Bootstrap lazycortex-wiki in a project — install, configure scopes, run integrity audits, and orient yourself with the built-in help command.
- [query](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/query.md) — Associative Q&A over the wiki graph — /wiki.query dispatches seekers to find entry points then a gatherer to traverse glossed See-also links and synthesise the answer.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/troubleshooting.md) — Common failure modes across lazycortex-wiki skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-wiki/help/faq.md) — Answers to common questions about setting up scopes, running relinks, querying the wiki, and interpreting doctor findings.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-wiki/help/`.

## Rules

| Rule | Description |
|---|---|
| `lazy-wiki.navigation.md` | Discovery and navigation contract for the curated semantic wiki. Tells agents how to enter the wiki, follow glossed links, find backlinks, and when to use /wiki.query. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-wiki@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-wiki:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-wiki.configure
/lazy-wiki.doctor
/lazy-wiki.install
/lazy-wiki.query
/lazy-wiki.relink
```
