---
iconize_icon: LiInfo
iconize_color: "#93c5fd"
---
# lazycortex-experts

Generic lifecycle experts (interpreter, designer, planner, implementer, debugger, reviewer) plus a starter set of domain aspects (claude-plugin, game-dev, dotfiles) and a cross-cutting discipline aspect. Building blocks — compose specialists in lazy.settings.json[experts] with one agent + one or more aspects.

## Why this plugin

LazyCortex experts run as queued jobs through `lazycortex-core`'s expert runtime. Each one specializes via two layers: the **agent** (persona) and the **aspect** (domain knowledge composed into the system prompt). `lazycortex-experts` ships the generic agents and domain aspects you compose into specialists by hand-authoring `lazy.settings.json[experts]` entries.

## Who it's for

- LazyCortex users who want a starting set of generic experts spanning the whole lifecycle — interpret a free-form request into a gap-free brief, write a design spec from that brief, write an implementation plan from that design, then carry the plan into code with test-first execution, root-cause debugging, and review.
- Plugin / domain authors who want to ship aspect files that layer their expertise on top of these generic agents instead of authoring a fresh agent per domain.

## Blocks

- **install-and-audit** — Bootstrap `lazycortex-experts` in your project. `/lazy-experts.install` seeds agent-model tiers for the generic agents from `lazycortex-core`'s defaults and composes every expert with the cross-cutting discipline aspect. No health-audit skill — health verification routes through `/lazy-core.doctor`. Members: lazy-experts.install.
- **agents** — Six generic agents. Each is persona-only; the protocol comes from whichever routine dispatches the job. Three design-time (lazy-experts.interpreter, lazy-experts.designer, lazy-experts.planner) and three execution-stage (lazy-experts.implementer, lazy-experts.debugger, lazy-experts.reviewer).
- **aspects** — Domain aspect files plus one cross-cutting discipline aspect, composed into the generic agents via `lazy.settings.json[experts][<expert>].aspects[]`. Domain members (operator picks per project): lazy-experts.claude-plugin-aspect, lazy-experts.game-dev-aspect, lazy-experts.dotfiles-aspect. Cross-cutting (auto-composed onto every seeded expert): lazy-experts.discipline-aspect.
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
| `lazy-experts.install` | Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds two things into `lazy.settings.json`: (1) agent-model tiers for the generic agents from `lazycortex-core`'s `default-tiers.json` into `agent_models.lazycortex`; (2) composed expert entries (agent × domain-aspect) into `experts` — every entry also carries the cross-cutting `lazycortex-experts:lazy-experts.discipline-aspect`, `lazycortex-core:lazy-memory.persona-aspect`, and a deterministic bot `git_author`. Asks which expert classes to register ONLY when the experts list is empty; on a populated list it derives the classes already present and completes them without asking. Experts and tiers are dispatch-routing config used by interactive flows AND the daemon — never gated on `daemon.enabled`. Idempotent and quiet on re-run; existing entries are never overwritten. Detects install scope automatically. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/agents.md) — Six persona-only agents spanning the full lifecycle — three design-time (interpreter, designer, planner) and three execution-stage (implementer, debugger, reviewer).
- [aspects](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/aspects.md) — Four aspect files (three domain, one cross-cutting discipline) that layer knowledge and working rigor onto any generic expert via lazy.settings.json composition.
- [composition](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/composition.md) — Assemble a named specialist by pairing one generic agent with one or more domain aspects in lazy.settings.json[experts].
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/install-and-audit.md) — Bootstrap lazycortex-experts by seeding agent-model tiers and composed expert entries for all six agent × domain-aspect pairs into lazy.settings.json.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, composing specialists, understanding the three-agent pipeline, and working with domain aspects.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-experts/help/`.

## Agents

| Agent | Description |
|---|---|
| `lazy-experts.debugger` | Generic debugger expert — investigates a bug to its root cause before proposing any fix, one hypothesis at a time, against a working journal. Carries the investigation (evidence, hypotheses, the fix) in the journal. Stays out of speculative patching. |
| `lazy-experts.designer` | Generic designer expert — takes a gap-free brief and writes a detailed design specification with premise-led structure, scope discipline, and declarative-over-prescriptive language. Stays out of implementation choices; those belong to the planner. |
| `lazy-experts.implementer` | Generic implementer expert — takes an ordered implementation plan and executes it task by task, test-first, against a working journal. Writes code as a side-effect; carries the dialogue (progress, blockers, questions it cannot resolve from the plan) in the journal. Stays out of design and planning; those belong upstream. |
| `lazy-experts.interpreter` | Generic interpreter expert — takes a free-form human request, log, or doc and produces a gap-free structured brief that downstream LLM work (designer / planner / etc.) can consume without ambiguity. Surfaces uncertainty inside the document instead of asking interactively. |
| `lazy-experts.planner` | Generic planner expert — takes a detailed design spec and produces an ordered implementation plan: file-level tasks, test plan, rollback procedure. Stays out of design choices; those belong to the designer. |
| `lazy-experts.reviewer` | Generic reviewer expert — reviews a change for correctness and quality and returns ranked findings with evidence into a working journal. Verifies each finding against the codebase before asserting it. Stays out of implementing the fixes; describes the problem and leaves the fixing to the implementer. |

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
