---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-experts

Generic lifecycle experts (interpreter, designer, planner, implementer, debugger, reviewer, tester) plus a fiction-writer agent, a starter set of domain aspects (claude-plugin, game-dev, dotfiles, obsidian-plugin, data-pipeline, sci-fi, fantasy), and two cross-cutting aspects (discipline, tech-writing). Building blocks — compose specialists in lazy.settings.json[experts] with one agent + one or more aspects.

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

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-experts.install` | Run when the operator asks to set up lazycortex-experts in a repo, to add or complete an expert class (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `sci-fi`, `fantasy`), or when dispatching an expert fails because `lazy.settings.json` has no matching `experts` entry or no model tier for a generic agent. Unlike the sibling install skills, it syncs no rules — it only seeds composed expert entries per the class map plus agent-model tiers, asks for classes only on a project that has none yet, and never overwrites an existing entry. Idempotent and quiet on re-run; install scope is detected. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/agents.md) — Eight persona-only agents — three design-time, four execution-stage, and one literary agent for fiction deliverables.
- [aspects](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/aspects.md) — Nine aspect files (seven domain, two cross-cutting) that layer knowledge and working rigor onto any generic expert via lazy.settings.json composition.
- [composition](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/composition.md) — Assemble a named specialist by pairing one generic agent with aspects in lazy.settings.json[experts], following the technical/fiction class map.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/install-and-audit.md) — Bootstrap lazycortex-experts by seeding agent-model tiers and class-mapped composed expert entries into lazy.settings.json.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, the technical/fiction class map, composing specialists, and the eight generic agents' lane boundaries.

(`mebius-san` resolves from `.guard-waivers.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-experts.debugger` | Use when something fails, returns a wrong result, or behaves unexpectedly and nobody knows why yet — the job is to explain the cause and only then fix it. Dispatched by the expert runtime for any `debugger`-class expert; also dispatchable directly with the failure and a working journal. Pick it over the tester when the defect is already known and needs a root cause, and over the implementer when there is no plan to follow because the problem itself is the unknown. |
| `lazy-experts.designer` | Use when a brief is settled and the work needs a scoped design spec stating what is being built and why — not how. Dispatched by the expert runtime for any `designer`-class expert; also dispatchable directly with a brief and a target spec path. Pick it over the planner when file paths, task lists, and test plans would be premature, and over the interpreter when the gaps in the request are already closed. |
| `lazy-experts.fiction-writer` | Use when the deliverable is literary text — narrative prose, a scene, dialogue, a lyrical fragment — written from an existing brief or story outline. Dispatched by the expert runtime for any `fiction-writer`-class expert (the only role `/lazy-experts.install` seeds for the sci-fi and fantasy classes); also dispatchable directly with the outline and a target document. Never dispatch it for technical documents, and never for story architecture — what happens, to whom, in what order comes from upstream. |
| `lazy-experts.implementer` | Use when an ordered implementation plan exists and needs carrying into code task by task, test-first, verified with the repo's own check and test runners. Dispatched by the expert runtime for any `implementer`-class expert; also dispatchable directly with a plan and a working journal. Pick it over the debugger when the job is building what the plan describes rather than explaining a failure, and over the planner when the task breakdown already exists. |
| `lazy-experts.interpreter` | Use when a request is too vague to act on — a free-form ask, a rough note, an old doc, a log — and someone needs a gap-free structured brief before any design starts. Dispatched by the expert runtime for any `interpreter`-class expert; also dispatchable directly with the raw input and a target brief path. Pick it over the designer when the why and the unknowns are not yet pinned down; it raises its questions inside the document and never proposes a solution. |
| `lazy-experts.planner` | Use when a design spec exists and the work still needs breaking down into an ordered, file-level implementation plan with a test command and a rollback procedure. Dispatched by the expert runtime for any `planner`-class expert; also dispatchable directly with a spec and a target plan path. Pick it over the designer when what to build is already decided and only the sequencing is missing, and over the implementer when nothing should be written yet. |
| `lazy-experts.reviewer` | Use when a change — a diff, a finished task, a feature branch — needs an independent correctness-and-quality read before it lands, returned as ranked findings with evidence. Dispatched by the expert runtime for any `reviewer`-class expert; also dispatchable directly with a file or diff list. Pick it over the tester when the verdict comes from reading the change rather than running it; it never edits the code it reviews. |
| `lazy-experts.tester` | Use when the answer has to come from actually running things — a test plan, a plan execution, a bug report, or a minimal reproduction of a failure — against the test mechanisms the repo really ships. Dispatched by the expert runtime for any `tester`-class expert; also dispatchable directly with the change or feature to exercise. Pick it over the reviewer when reading the code is not enough, and over the debugger when the defect still has to be found and documented rather than explained and fixed; it never fixes what it finds. |

## Commands

| Command | Description |
|---|---|
| `lazy-experts.help` | Show lazycortex-experts purpose and a one-line summary of each agent, aspect, skill, and command it ships |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-experts@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-experts:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-experts.install
```
