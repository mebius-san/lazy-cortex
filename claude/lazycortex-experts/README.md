---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-experts

Generic doc-producing experts (interpreter, designer, planner) plus a starter set of domain aspects (claude-plugin, game-dev, dotfiles). Building blocks — compose specialists in lazy.settings.json[experts] with one agent + one or more aspects.

## Why this plugin

LazyCortex experts run as queued jobs through `lazycortex-core`'s expert runtime. Each one specializes via two layers: the **agent** (persona) and the **aspect** (domain knowledge composed into the system prompt). `lazycortex-experts` ships the generic agents and domain aspects you compose into specialists by hand-authoring `lazy.settings.json[experts]` entries.

## Who it's for

- LazyCortex users who want a starting set of generic doc-producing experts — interpret a free-form request into a gap-free brief, write a design spec from that brief, write an implementation plan from that design.
- Plugin / domain authors who want to ship aspect files that layer their expertise on top of these generic agents instead of authoring a fresh agent per domain.

## Blocks

- **install-and-audit** — Bootstrap `lazycortex-experts` in your project. `/lazy-experts.install` seeds agent-model tiers for the three generic agents from `lazycortex-core`'s defaults. No health-audit skill — health verification routes through `/lazy-core.doctor`. Members: lazy-experts.install.
- **agents** — Three generic doc-producing agents. Each is persona-only; the protocol comes from whichever routine dispatches the job. Members: lazy-experts.interpreter, lazy-experts.designer, lazy-experts.planner.
- **aspects** — Three domain aspect files that compose into any of the three generic agents via `lazy.settings.json[experts][<expert>].aspects[]`. Members: lazy-experts.claude-plugin-aspect, lazy-experts.game-dev-aspect, lazy-experts.dotfiles-aspect.
- **composition** — How to assemble a concrete specialist (e.g. `game-designer`, `claude-plugin-planner`) by pairing one agent with one or more aspects in `lazy.settings.json[experts]`. No skills in this block — it's documentation only.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the expert runtime, aspect resolver, and agent-model wizard.

## Quick start

1. Install the marketplace and enable the plugin (`/plugin install lazycortex-experts@lazycortex`).
2. Run `/lazy-experts.install` to seed agent-model tiers.
3. Compose your first specialist in `<repo>/.claude/lazy.settings.json`:
   ```jsonc
   "experts": {
     "_version": 1,
     "claude-plugin-designer": {
       "agent": "lazycortex-experts:lazy-experts.designer",
       "aspects": ["lazycortex-experts:lazy-experts.claude-plugin-aspect"]
     }
   }
   ```
4. Wire a routine elsewhere (consumer-side, or via a future `lazycortex-specs` integration) to dispatch jobs to this expert. The plugin itself ships no routines or dispatcher.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-experts.install` | Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds agent-model tiers for the three generic agents (interpreter, designer, planner) from `lazycortex-core`'s `default-tiers.json` into `lazy.settings.json[agent_models].lazycortex`. Ships no expert-entry seeding — composition lives in the consumer's `lazy.settings.json[experts]`. Idempotent — safe to re-run. Detects install scope automatically. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/agents.md) — Three persona-only agents (interpreter, designer, planner) that transform a raw request into a structured brief, a design spec, and an implementation plan.
- [aspects](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/aspects.md) — Three domain aspect files (claude-plugin, game-dev, dotfiles) that layer domain knowledge onto any generic expert via lazy.settings.json composition.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, composing specialists, understanding the three-agent pipeline, and working with domain aspects.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/install-and-audit.md) — Bootstrap lazycortex-experts in your project by seeding agent-model tiers for the three generic experts from lazycortex-core's defaults.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.

## Agents

| Agent | Description |
|---|---|
| `lazy-experts.designer` | Generic designer expert — takes a gap-free brief and writes a detailed design specification with premise-led structure, scope discipline, and declarative-over-prescriptive language. Stays out of implementation choices; those belong to the planner. Dispatch via a routine that supplies a protocol; this agent has no inline I/O contract. |
| `lazy-experts.interpreter` | Generic interpreter expert — takes a free-form human request, log, or doc and produces a gap-free structured brief that downstream LLM work (designer / planner / etc.) can consume without ambiguity. Surfaces uncertainty as in-doc callouts instead of asking interactively. Dispatch via a routine that supplies a protocol; this agent has no inline I/O contract. |
| `lazy-experts.planner` | Generic planner expert — takes a detailed design spec and produces an ordered implementation plan: file-level tasks, test plan, rollback procedure. Models its output on superpowers:writing-plans. Stays out of design choices; those belong to the designer. Dispatch via a routine that supplies a protocol; this agent has no inline I/O contract. |

## Commands

| Command | Description |
|---|---|
| `lazy-experts.help` | Show lazycortex-experts purpose and a one-line summary of each agent, aspect, skill, and command it ships |

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
    "lazycortex-experts@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-experts:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-experts.install
```
