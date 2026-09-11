# lazycortex-experts

Generic lifecycle experts (interpreter, use-case-writer, designer, architect, ui-designer, planner, implementer, data-implementer, docs-writer, debugger, reviewer, tester) plus a fiction-writer agent, a starter set of domain aspects (claude-plugin, game-dev, dotfiles, obsidian-plugin, data-pipeline, sci-fi, fantasy), and five cross-cutting aspects (discipline, research, tech-writing, terms, structure). Building blocks — compose specialists in lazy.settings.json[experts] with one agent + one or more aspects.

## Why this plugin

LazyCortex experts run as queued jobs through `lazycortex-core`'s expert runtime. Each one specializes via two layers: the **agent** (persona) and the **aspect** (domain knowledge composed into the system prompt). `lazycortex-experts` ships the generic agents and domain aspects you compose into specialists by hand-authoring `lazy.settings.json[experts]` entries.

## Who it's for

- LazyCortex users who want a starting set of generic experts spanning the whole lifecycle — interpret a free-form request into a gap-free brief, write a design spec from that brief, design the code structure that spec implies, write an implementation plan from that design, then carry the plan into code with test-first execution, root-cause debugging, review, and mechanism-grounded testing.
- Plugin / domain authors who want to ship aspect files that layer their expertise on top of these generic agents instead of authoring a fresh agent per domain.

## Blocks

- **install-and-audit** — Bootstrap `lazycortex-experts` in your project. `/lazy-experts.install` seeds agent-model tiers for the generic agents from `lazycortex-core`'s defaults and composes experts per the class map — technical classes seed fourteen roles with the mandatory cross-cutting aspects (discipline, research, tech-writing, terms, structure), fiction classes (sci-fi, fantasy) seed fiction-writer with discipline + research only; a re-run appends any mandatory cross-cutting aspect an existing entry lacks. It asks for classes only when no domain-class experts exist yet (system experts seeded by sibling plugins don't count), and checks system-expert completeness against the sibling-plugin registry, reporting gaps without seeding them. `/lazy-experts.audit` is the read-only counterpart: it checks that the class map's roles still resolve to shipped agents, that the aspect references exist, and that every seeded entry still points at an agent and a set of aspects this plugin ships — reporting findings and never writing. `/lazy-core.doctor` runs it as part of its cross-plugin sweep. Members: lazy-experts.install, lazy-experts.audit.
- **design-time-agents** — Seven agents that run before any code is written. Each is persona-only; the protocol comes from whichever routine dispatches the job. `lazy-experts.interpreter` turns a free-form request into a gap-free brief, `lazy-experts.use-case-writer` writes formal use cases from it, `lazy-experts.designer` states what is being built and why, `lazy-experts.ui-designer` settles the interface with HTML mockups beside the document, `lazy-experts.architect` designs the code structure the design implies, `lazy-experts.researcher` answers a research asset's question with a sourced report, and `lazy-experts.planner` breaks that into an ordered implementation plan. Members: lazy-experts.interpreter, lazy-experts.use-case-writer, lazy-experts.designer, lazy-experts.ui-designer, lazy-experts.architect, lazy-experts.planner, lazy-experts.researcher.
- **execution-stage-agents** — Seven agents that carry approved work into deliverables. `lazy-experts.implementer` follows a plan test-first, `lazy-experts.data-implementer` writes data files straight from a content design, `lazy-experts.docs-writer` writes user-facing documentation from the design, `lazy-experts.debugger` explains a failure before fixing it, `lazy-experts.reviewer` judges a change without editing it, `lazy-experts.tester` exercises what actually runs, and `lazy-experts.fiction-writer` produces literary prose from an outline. Members: lazy-experts.implementer, lazy-experts.data-implementer, lazy-experts.docs-writer, lazy-experts.debugger, lazy-experts.reviewer, lazy-experts.tester, lazy-experts.fiction-writer.
- **aspects** — Domain aspect files plus five cross-cutting aspects, composed into the generic agents via `lazy.settings.json[experts][<expert>].aspects[]`. Domain members (operator picks per project): lazy-experts.claude-plugin-aspect, lazy-experts.game-dev-aspect, lazy-experts.dotfiles-aspect, lazy-experts.obsidian-plugin-aspect, lazy-experts.data-pipeline-aspect, lazy-experts.software-product-aspect, lazy-experts.sci-fi-aspect, lazy-experts.fantasy-aspect. Cross-cutting: lazy-experts.discipline-aspect and lazy-experts.research-aspect (auto-composed onto every seeded expert), lazy-experts.tech-writing-aspect, lazy-experts.terms-aspect, and lazy-experts.structure-aspect (auto-composed onto technical-class experts only; fiction classes never carry them).
- **composition** — How to assemble a concrete specialist (e.g. `game.designer`, `claude-plugin.planner`) by pairing one agent with one or more aspects in `lazy.settings.json[experts]`. No skills in this block — it's documentation only.

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
     "claude-plugin.designer": {
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
| `lazy-experts.audit` | Run when the operator asks whether this project's expert composition is still sound, or when dispatching an expert fails in a way that smells like config — a job aborts saying the agent ref does not resolve, an expert writes to a contract it should not have, a role the class map prescribes turns out to have no entry. Delegated from `lazy-core.doctor` Phase 3. Read-only check of the plugin's shipped agents and aspect references against the `experts` entries in `.claude/lazy.settings.json`; reports PASS / WARN / FAIL / INFO and never writes — the fix is `/lazy-experts.install`. |
| `lazy-experts.install` | Run when the operator asks to set up lazycortex-experts in a repo, to add or complete an expert class (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`), or when dispatching an expert fails because `lazy.settings.json` has no matching `experts` entry or no model tier for a generic agent. Unlike the sibling install skills, it syncs no rules — it only seeds composed expert entries per the class map plus agent-model tiers, asks for classes only on a project that has none yet, and never overwrites what an operator chose — the one thing it completes on an existing entry is a missing mandatory cross-cutting aspect. Idempotent and quiet on re-run; install scope is detected. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, the class map, composing specialists, auditing the composition, and the fourteen generic agents' lane boundaries.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-experts.architect` | Use when a `design.md` has already settled what the system should do and the work still needs a code-structure design — module boundaries, dependency direction, public contract versus internals, data migration, and the cost to existing callers. Dispatched by the expert runtime as the `architecture` review class's main writer for any `architect`-class expert; also dispatchable directly with an approved design spec and a target `architecture.md` path. Pick it over the designer when the behavior is decided and only the shape of the code is open, and over the planner when nothing should be sequenced into tasks yet. |
| `lazy-experts.data-implementer` | Use when an approved content design settles what an entity is and the work still needs its data files written into the product's own repository, in the project's own schemas. Dispatched by the expert runtime for any `data-implementer`-class expert; also dispatchable directly with a design document and a report to journal into. Pick it over the implementer when there is no plan to follow because the design itself is the specification, and over the tester when the job is producing data rather than validating it. |
| `lazy-experts.debugger` | Use when something fails, returns a wrong result, or behaves unexpectedly and nobody knows why yet — the job is to explain the cause and only then fix it. Dispatched by the expert runtime for any `debugger`-class expert; also dispatchable directly with the failure and a working journal. Pick it over the tester when the defect is already known and needs a root cause, and over the implementer when there is no plan to follow because the problem itself is the unknown. |
| `lazy-experts.designer` | Use when a brief is settled and the work needs a scoped design spec stating what is being built and why — not how. Dispatched by the expert runtime for any `designer`-class expert; also dispatchable directly with a brief and a target spec path. Pick it over the planner when file paths, task lists, and test plans would be premature, and over the interpreter when the gaps in the request are already closed. |
| `lazy-experts.docs-writer` | Use when an approved design settles what the user gets and the product's user-facing documentation still needs writing — straight from the design document, with no plan in between. Dispatched by the expert runtime for any `docs-writer`-class expert; also dispatchable directly with a design document and a report to journal into. Pick it over the implementer when the deliverable is documentation rather than code, and over the fiction-writer when the text is user-facing product documentation rather than literary prose. |
| `lazy-experts.fiction-writer` | Use when the deliverable is literary text — narrative prose, a scene, dialogue, a lyrical fragment — written from an existing brief or story outline. Dispatched by the expert runtime for any `fiction-writer`-class expert (the only role `/lazy-experts.install` seeds for the sci-fi and fantasy classes); also dispatchable directly with the outline and a target document. Never dispatch it for technical documents, and never for story architecture — what happens, to whom, in what order comes from upstream. |
| `lazy-experts.implementer` | Use when an ordered implementation plan exists and needs carrying into code task by task, test-first, verified with the repo's own check and test runners. Dispatched by the expert runtime for any `implementer`-class expert; also dispatchable directly with a plan and a working journal. Pick it over the debugger when the job is building what the plan describes rather than explaining a failure, and over the planner when the task breakdown already exists. |
| `lazy-experts.interpreter` | Use when a request is too vague to act on — a free-form ask, a rough note, an old doc, a log — and someone needs a gap-free structured brief before any design starts. Dispatched by the expert runtime for any `interpreter`-class expert; also dispatchable directly with the raw input and a target brief path. Pick it over the designer when the why and the unknowns are not yet pinned down; it raises its questions inside the document and never proposes a solution. |
| `lazy-experts.planner` | Use when a design spec exists and the work still needs breaking down into an ordered, file-level implementation plan with a test command and a rollback procedure. Dispatched by the expert runtime for any `planner`-class expert; also dispatchable directly with a spec and a target plan path. Pick it over the designer when what to build is already decided and only the sequencing is missing, and over the implementer when nothing should be written yet. |
| `lazy-experts.researcher` | Use when a research asset's approved research design (`design.md` typed `research-design`) states the question and the research report `research.md` still needs writing — the routes walked, findings each with a source, compared options, a conclusion that answers the question and rules on the hypothesis, and the sources — from the spec tree, the code, the wiki, and the internet once the internal routes run dry. Dispatched by the expert runtime for any `researcher`-class expert as the `research` tool's job; also the validator of a research design in review. Pick it over the interpreter when the question is already settled and only the answer is missing, and over the designer when nothing is being built — the deliverable is the report, and an approved report is immutable. |
| `lazy-experts.reviewer` | Use when a change — a diff, a finished task, a feature branch — needs an independent correctness-and-quality read before it lands, returned as ranked findings with evidence. Dispatched by the expert runtime for any `reviewer`-class expert; also dispatchable directly with a file or diff list. Pick it over the tester when the verdict comes from reading the change rather than running it; it never edits the code it reviews. |
| `lazy-experts.tester` | Use when the answer has to come from actually running things — a test plan, a plan execution, a bug report, or a minimal reproduction of a failure — against the test mechanisms the repo really ships. Dispatched by the expert runtime for any `tester`-class expert; also dispatchable directly with the change or feature to exercise. Pick it over the reviewer when reading the code is not enough, and over the debugger when the defect still has to be found and documented rather than explained and fixed; it never fixes what it finds. |
| `lazy-experts.ui-designer` | Use when an approved design needs its user interface settled — screens, states, navigation, and interaction decisions written into a ui-design document, with self-contained HTML mockups laid down beside it as attachments. Dispatched by the expert runtime for any `ui-designer`-class expert; also dispatchable directly with an approved design and a target ui-design document. Pick it over the designer when behavior is already approved and only the interface is open, and never for production frontend code — mockups approve the look, they ship nothing. |
| `lazy-experts.use-case-writer` | Use when a settled brief or request needs formal use cases before any design starts — actors, goals, main and alternative flows, pre- and postconditions, written in the actor's language with no system internals. Dispatched by the expert runtime for any `use-case-writer`-class expert; also dispatchable directly with a brief and a target use-cases document. Pick it over the designer when requirements scenarios are the deliverable, and over the tester when the scenarios state what the user needs rather than how the product is accepted. |

## Commands

| Command | Description |
|---|---|
| `lazy-experts.help` | Run when the operator asks what lazycortex-experts ships, which generic expert fits a piece of work, or how to assemble a named specialist — lists the fourteen persona agents (interpreter, designer, architect, planner, researcher, use-case-writer, ui-designer, implementer, data-implementer, docs-writer, debugger, reviewer, tester, fiction-writer), the domain and cross-cutting aspects that layer onto them, and the `lazy.settings.json[experts]` composition shape. |

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
/lazy-experts.audit
/lazy-experts.install
```
