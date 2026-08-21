---
description: "Run when the operator asks what lazycortex-experts ships, which generic expert fits a piece of work, or how to assemble a named specialist — lists the eleven persona agents (interpreter, designer, architect, planner, implementer, data-implementer, docs-writer, debugger, reviewer, tester, fiction-writer), the domain and cross-cutting aspects that layer onto them, and the `lazy.settings.json[experts]` composition shape."
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-experts** — generic lifecycle experts plus a starter set of domain aspects. Nine persona-only agents (interpreter / designer / architect / planner / implementer / debugger / reviewer / tester / fiction-writer) combine with composable aspect files (claude-plugin / game-dev / dotfiles / obsidian-plugin / data-pipeline / software-product / sci-fi / fantasy) and five cross-cutting aspects (discipline, research, tech-writing, terms, structure) to form specialists you assemble in `lazy.settings.json[experts]`. No protocols, routines, or dispatcher ship from this plugin — the dispatching routine supplies the protocol and the agent follows it.

**Agents** (invoke via Agent tool, normally only via a routine that dispatches expert jobs):

- `lazy-experts.interpreter` — takes a free-form human request / doc / log, produces a gap-free premise-first structured brief. Surfaces unresolved gaps and candidate alternatives as callouts in the output; never calls AskUserQuestion. Models its iteration shape on `superpowers:brainstorming`.
- `lazy-experts.designer` — takes a brief, produces a detailed design specification with premise-led structure, scope discipline, and declarative-over-prescriptive language. Stays out of implementation choices.
- `lazy-experts.architect` — takes a settled brief or design spec, produces a code-structure design: module boundaries and the direction of the dependencies between them, public contract versus internals, migrations for every change to stored data, and what breaks for existing callers. Refuses an abstraction with only one consumer. Stays out of the designer's lane (what the system does) and the planner's lane (task ordering).
- `lazy-experts.planner` — takes a design spec, produces an ordered bite-sized implementation plan with file-level tasks, test plan, and rollback. Models its output on `superpowers:writing-plans`. Stays out of design choices.
- `lazy-experts.implementer` — takes an ordered plan, executes it task by task against a working journal, test-first (RED→GREEN→REFACTOR), one task at a time. Writes code as a side-effect; surfaces blockers in the journal rather than guessing. Models its discipline on `superpowers:test-driven-development` + `executing-plans`.
- `lazy-experts.debugger` — investigates a bug to its root cause before any fix, one hypothesis at a time, four phases (investigate / pattern / hypothesis / fix). After repeated failed fixes, surfaces the architecture itself as the open question. Models its discipline on `superpowers:systematic-debugging`.
- `lazy-experts.reviewer` — reviews a change for correctness and quality, returns ranked findings (location + cause + severity) with evidence, verifying each against the codebase before asserting it. Stays out of the implementer's lane. Models its discipline on `superpowers:requesting-code-review` + `receiving-code-review`.
- `lazy-experts.tester` — discovers the testing mechanisms the repository actually ships (runners, fixtures, harnesses, Makefile / CI targets) and works only through them: writes risk-to-coverage test plans, executes plans step by step recording actual vs expected, writes evidence-grade bug reports, minimizes failures to the shortest deterministic steps-to-reproduce. Finds and documents defects; never fixes them.
- `lazy-experts.fiction-writer` — takes a brief or story outline, produces literary text: narrative prose, dialogue, lyrical fragments. Owns POV/psychic distance, show-don't-tell, dialogue subtext, rhythm; story architecture comes from upstream documents. Never dispatched for technical documents.

**Aspects** (compose into any agent via `lazy.settings.json[experts][<expert>].aspects[]`):

- `lazy-experts.claude-plugin-aspect` — Claude Code plugin authoring expertise (plugin tree, marketplace, artifact contracts, install / sync / publish lifecycle, consumer-effort versioning).
- `lazy-experts.game-dev-aspect` — general game-development expertise (core loop, progression, balance, telemetry, content vs mechanics separation).
- `lazy-experts.dotfiles-aspect` — general principles for personal-computer / network configuration management (dotfile-repo conventions, shell rc structure, host-vs-personal split, package manifests, init systems, secret handling). Public-marketplace-safe.
- `lazy-experts.obsidian-plugin-aspect` — Obsidian community-plugin development expertise (plugin lifecycle, vault/workspace API boundaries, settings persistence, mobile compatibility, metadata-cache interplay, community release process).
- `lazy-experts.data-pipeline-aspect` — data synchronization / pipeline engineering expertise (idempotency, incremental state, resumability, quota/rate-limit budgeting, integrity verification, source-data safety).
- `lazy-experts.software-product-aspect` — generic software-product expertise (users and workflows, platform constraints, compatibility and upgrade paths, configuration surface, failure behavior, observability) — the fallback technical class when no narrower one fits.
- `lazy-experts.sci-fi-aspect` — science-fiction genre expertise (novum and worked-through consequences, extrapolation coherence, limits-as-pressure, terms introduced through use).
- `lazy-experts.fantasy-aspect` — fantasy genre expertise (magic with rules and cost, world-consistency, naming/language coherence, lore continuity, wonder anchored in consequence).
- `lazy-experts.discipline-aspect` — cross-cutting execution discipline, auto-composed onto every seeded expert regardless of domain: verify-before-completion, never-guess-past-a-gap, no-performative-agreement, and the principle that turns would-be human gates into document questions.
- `lazy-experts.research-aspect` — cross-cutting research discipline, auto-composed onto every seeded expert: find the repository's own answer through its research skills before reading sources at large or answering from memory.
- `lazy-experts.tech-writing-aspect` — cross-cutting technical-prose discipline, auto-composed onto technical-class experts only: no literary devices in technical documents, every sentence a verifiable fact or an obligation, one term per concept inherited from the upstream document.
- `lazy-experts.terms-aspect` — cross-cutting terminology lookup, auto-composed onto technical-class experts only: ask the repository's terms dictionary through `/lazy-wiki.terms` before coining a word, take its term when it has one, and never write to the dictionary.
- `lazy-experts.structure-aspect` — cross-cutting placement lookup, auto-composed onto technical-class experts only: query the repository's structure map through `/lazy-wiki.structure query` before claiming where something lives or placing new work, read slices only, and never write to the map.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-experts.install` — bootstrap the plugin for the current project (or globally). Seeds agent-model tiers from `lazycortex-core`'s defaults into `lazy.settings.json[agent_models].lazycortex` and composes expert entries per the class map (technical classes: eight roles, discipline + tech-writing; sci-fi/fantasy: fiction-writer, discipline only). Also checks system-expert completeness against sibling plugins' registrations and reports gaps. Idempotent.

**Commands**:

- `lazy-experts.help` — this listing.

**Composition example** (consumer-side, `<repo>/.claude/lazy.settings.json`):

```jsonc
"experts": {
  "_version": 1,
  "claude-plugin-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": ["lazycortex-experts:lazy-experts.claude-plugin-aspect"]
  },
  "game-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": ["lazycortex-experts:lazy-experts.game-dev-aspect"]
  }
}
```

The expert never runs until a routine elsewhere dispatches a job to it — by design.

<!-- help-block:start -->
**Documentation:**

- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, the class map, composing specialists, and the eleven generic agents' lane boundaries.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-experts/help/`.
<!-- help-block:end -->
