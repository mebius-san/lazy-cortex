---
chapter_type: block
summary: Assemble a named specialist by pairing one generic agent with aspects in lazy.settings.json[experts], following the technical/fiction class map.
last_regen: 2026-07-22
no_diagram: true
source_skills: []
---
# Assembling a specialist from agents and aspects

A specialist is a named expert entry you declare in `lazy.settings.json[experts]`. It pairs one generic agent (the persona) with one or more aspects (the knowledge and discipline layers) so the expert runtime can produce a fully-qualified specialist system prompt at dispatch time — without you authoring a fresh agent for each domain or use-case.

The composition pattern has two moving parts. The **agent** supplies the output discipline: the interpreter knows how to structure a gap-free brief, the designer knows how to write a declarative spec, the planner knows how to produce a file-level task list, the implementer/debugger/reviewer/tester know their execution-stage disciplines, and the fiction-writer knows the craft of narrative prose. The **aspect** supplies the knowledge layer on top: a domain aspect adds what counts as a complete brief for a LazyCortex plugin change, an Obsidian plugin, a data pipeline, a game-design document, or what a science-fiction premise owes the reader; a cross-cutting aspect adds working discipline that applies no matter the domain. Neither layer changes the other's responsibilities; the expert runtime merges them at dispatch time in the order you declare them.

## When you'd use this

- You want a specialist that does not exist in the entries `/lazy-experts.install` seeds by default — for example a `game-planner-strict` variant with a custom aspect, or a `my-domain-interpreter` for a domain aspect your own plugin ships.
- You want to combine two aspects in one specialist — for instance, a designer that knows both LazyCortex plugin conventions and dotfiles structure because your target project is a plugin that also manages machine config.
- You want to pair the fiction-writer agent with a genre aspect (`sci-fi` or `fantasy`) to get a specialist for a particular kind of literary work, rather than accepting whichever class `/lazy-experts.install` already seeded.
- You want to give a specialist a different model tier than the built-in default.
- You received an aspect from a third-party plugin and want to wire it onto one of the generic agents.

## How it fits together

Start by deciding which generic agent fits the job. Three agents are design-time: `lazy-experts.interpreter` clarifies a request into a structured brief, `lazy-experts.designer` turns a brief into a declarative design, `lazy-experts.planner` turns a design into an ordered implementation plan. Four are execution-stage: `lazy-experts.implementer` executes a plan test-first, `lazy-experts.debugger` investigates a bug to its root cause, `lazy-experts.reviewer` returns ranked findings against a change, `lazy-experts.tester` surveys the testing mechanisms the repository actually ships and works only through them — writing test plans, executing them step by step, filing bug reports, and minimizing failures to steps-to-reproduce. One is literary: `lazy-experts.fiction-writer` takes a brief or outline and produces narrative prose, dialogue, or lyrical fragments — dispatch it for fiction deliverables, never for technical documents. Each agent is independently dispatchable — you do not need the whole set to build a specialist.

Next, pick the aspects that add the knowledge and discipline your specialist needs. Aspects fall into two groups:

- **Domain aspects** name the subject matter. Five are technical — `lazy-experts.claude-plugin-aspect`, `lazy-experts.game-dev-aspect`, `lazy-experts.dotfiles-aspect`, `lazy-experts.obsidian-plugin-aspect`, `lazy-experts.data-pipeline-aspect` — and pair with any of the seven technical-lifecycle agents. Two are fiction genre aspects — `lazy-experts.sci-fi-aspect`, `lazy-experts.fantasy-aspect` — and pair with `lazy-experts.fiction-writer`. If another plugin in your project ships a domain aspect, reference it by its plugin-namespace prefix the same way.
- **Cross-cutting aspects** apply regardless of domain. `lazy-experts.discipline-aspect` carries the iron laws (verify before completion, never guess past a gap, no performative agreement) and belongs on every specialist you build, technical or fiction. `lazy-experts.tech-writing-aspect` bans literary devices and enforces a single-term-per-concept dictionary — it belongs on every **technical** specialist, but never on a fiction specialist: its bans on metaphor and figurative imagery directly contradict what `lazy-experts.fiction-writer`'s own persona requires.

This technical/fiction split is the same class map `/lazy-experts.install` applies when it seeds specialists automatically: technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) compose `discipline-aspect` and `tech-writing-aspect` onto all seven technical-lifecycle roles (interpreter, designer, planner, implementer, debugger, reviewer, tester); fiction classes (`sci-fi`, `fantasy`) compose `discipline-aspect` only onto `fiction-writer`. When you hand-compose a specialist outside the wizard, follow the same split — a technical specialist without `tech-writing-aspect` loses terminology discipline it should have, and a fiction specialist carrying `tech-writing-aspect` gets crippled prose instructions that fight its own agent persona.

Declare the entry in `<repo>/.claude/lazy.settings.json` under the `experts` key:

```jsonc
"experts": {
  "_version": 1,
  "game-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": [
      "lazycortex-experts:lazy-experts.game-dev-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect"
    ]
  },
  "sci-fi-writer": {
    "agent": "lazycortex-experts:lazy-experts.fiction-writer",
    "aspects": [
      "lazycortex-experts:lazy-experts.sci-fi-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect"
    ]
  },
  "config-plugin-interpreter": {
    "agent": "lazycortex-experts:lazy-experts.interpreter",
    "aspects": [
      "lazycortex-experts:lazy-experts.claude-plugin-aspect",
      "lazycortex-experts:lazy-experts.dotfiles-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect"
    ]
  }
}
```

Note that `sci-fi-writer` omits `tech-writing-aspect` for the reason above, while both technical entries carry it alongside `discipline-aspect`.

The entry key (`"game-designer"`, `"sci-fi-writer"`, `"config-plugin-interpreter"`) becomes the specialist's identity — the name a dispatching routine uses to look up which agent and aspects to load. Keep names lowercase, hyphenated, and descriptive: `<domain>-<role>` is the convention the built-in entries follow.

When you list more than one aspect, the expert runtime merges them in declaration order. Earlier aspects take precedence when obligations conflict. In the `config-plugin-interpreter` example above, `claude-plugin-aspect` obligations run first, and `dotfiles-aspect` obligations supplement them.

## Common adjustments

**Register a model tier.** Every specialist entry should have a model tier so the expert runtime knows which capability class to request. Run `/lazy-core.agent-models` — the skill presents a wizard that writes the `lazy.settings.json[agent_models]` entry for you. Do not edit the `agent_models` section by hand; the skill owns that schema.

**Use `/lazy-experts.install` as a baseline.** If you are building a specialist that is close to one already seeded by the class map, run `/lazy-experts.install` first to register the nearest base class, then add your custom entry alongside it. The install skill never overwrites existing entries, so your custom work is safe.

**Building a technical specialist by hand.** Mirror the class map: pair one of the seven technical-lifecycle agents (interpreter, designer, planner, implementer, debugger, reviewer, tester) with a technical domain aspect (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, or `data-pipeline`), then append `lazy-experts.discipline-aspect` and `lazy-experts.tech-writing-aspect` in that order, same as `/lazy-experts.install` would.

**Building a fiction specialist by hand.** Pair `lazy-experts.fiction-writer` with a genre aspect (`sci-fi` or `fantasy`), then append `lazy-experts.discipline-aspect` only. Never add `lazy-experts.tech-writing-aspect` to a fiction specialist.

**Bring an aspect from another plugin.** The `aspects` array accepts any qualified `<plugin-namespace>:<skill-name>` reference. If a plugin you have installed ships an aspect, check its block documentation for the correct reference string to use here.

**Adjust aspect order.** If two aspects impose conflicting obligations (rare, but possible when layering a domain-specific aspect over a highly opinionated second one), reorder them so the aspect whose rules should win is listed first.

## See also

- The **agents** block (`agents.md`) — describes the eight generic agents, the design-time / execution-stage / literary groupings, and how the seven technical-lifecycle agents function as a linear pipeline.
- The **aspects** block (`aspects.md`) — describes the domain aspect files (technical and fiction) and the two cross-cutting aspects, and shows what each one obliges the composing agent to do.
- The **install-and-audit** block (`install-and-audit.md`) — bootstraps the plugin and seeds specialist entries per the class map, technical classes vs fiction classes.
