## Why this plugin

LazyCortex experts run as queued jobs through `lazycortex-core`'s expert runtime. Each one specializes via two layers: the **agent** (persona) and the **aspect** (domain knowledge composed into the system prompt). `lazycortex-experts` ships the generic agents and domain aspects you compose into specialists by hand-authoring `lazy.settings.json[experts]` entries.

## Who it's for

- LazyCortex users who want a starting set of generic experts spanning the whole lifecycle — interpret a free-form request into a gap-free brief, write a design spec from that brief, write an implementation plan from that design, then carry the plan into code with test-first execution, root-cause debugging, review, and mechanism-grounded testing.
- Plugin / domain authors who want to ship aspect files that layer their expertise on top of these generic agents instead of authoring a fresh agent per domain.

## Blocks

- **install-and-audit** — Bootstrap `lazycortex-experts` in your project. `/lazy-experts.install` seeds agent-model tiers for the generic agents from `lazycortex-core`'s defaults and composes experts per the class map — technical classes seed seven roles with discipline + tech-writing, fiction classes (sci-fi, fantasy) seed fiction-writer with discipline only. It asks for classes only when no domain-class experts exist yet (system experts seeded by sibling plugins don't count), and checks system-expert completeness against the sibling-plugin registry, reporting gaps without seeding them. No health-audit skill — health verification routes through `/lazy-core.doctor`. Members: lazy-experts.install.
- **agents** — Eight generic agents. Each is persona-only; the protocol comes from whichever routine dispatches the job. Three design-time (lazy-experts.interpreter, lazy-experts.designer, lazy-experts.planner), four execution-stage (lazy-experts.implementer, lazy-experts.debugger, lazy-experts.reviewer, lazy-experts.tester), and one literary (lazy-experts.fiction-writer).
- **aspects** — Domain aspect files plus two cross-cutting aspects, composed into the generic agents via `lazy.settings.json[experts][<expert>].aspects[]`. Domain members (operator picks per project): lazy-experts.claude-plugin-aspect, lazy-experts.game-dev-aspect, lazy-experts.dotfiles-aspect, lazy-experts.obsidian-plugin-aspect, lazy-experts.data-pipeline-aspect, lazy-experts.sci-fi-aspect, lazy-experts.fantasy-aspect. Cross-cutting: lazy-experts.discipline-aspect (auto-composed onto every seeded expert) and lazy-experts.tech-writing-aspect (auto-composed onto technical-class experts; fiction classes never carry it).
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
