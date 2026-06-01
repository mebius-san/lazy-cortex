---
chapter_type: block
summary: Assemble a named specialist by pairing one generic agent with one or more domain aspects in lazy.settings.json[experts].
last_regen: 2026-06-01
no_diagram: true
source_skills: []
---
# Assembling a specialist from agents and aspects

A specialist is a named expert entry you declare in `lazy.settings.json[experts]`. It pairs one generic agent (the persona) with one or more domain aspects (the knowledge layer) so the expert runtime can produce a fully-qualified specialist system prompt at dispatch time — without you authoring a fresh agent for each domain or use-case.

The composition pattern has two moving parts. The **agent** supplies the output discipline: the interpreter knows how to structure a gap-free brief, the designer knows how to write a declarative spec, the planner knows how to produce a file-level task list. The **aspect** supplies the domain obligations: what counts as a complete brief for a LazyCortex plugin change, what a game-design document must contain, what a dotfiles migration plan must never do. Neither layer changes the other's responsibilities; the expert runtime merges them at dispatch time in the order you declare them.

## When you'd use this

- You want a specialist that does not exist in the nine built-in entries seeded by `/lazy-experts.install` — for example a `game-planner-strict` variant with a custom aspect, or a `my-domain-interpreter` for a domain aspect your own plugin ships.
- You want to combine two aspects in one specialist — for instance, a designer that knows both LazyCortex plugin conventions and dotfiles structure because your target project is a plugin that also manages machine config.
- You want to give a specialist a different model tier than the built-in default.
- You received an aspect from a third-party plugin and want to wire it onto one of the three generic agents.

## How it fits together

Start by deciding which generic agent fits the job. If the job is to clarify a request and produce a structured brief, choose `lazy-experts.interpreter`. If the job is to take a resolved brief and write a declarative design, choose `lazy-experts.designer`. If the job is to take a design and produce an ordered implementation plan, choose `lazy-experts.planner`. Each agent is independently dispatchable — you do not need all three to build a specialist.

Next, pick the aspects that add the knowledge your specialist needs. The three built-in aspects shipped by this plugin are `lazy-experts.claude-plugin-aspect`, `lazy-experts.game-dev-aspect`, and `lazy-experts.dotfiles-aspect`. If another plugin in your project ships an aspect, reference it by its plugin-namespace prefix the same way.

Declare the entry in `<repo>/.claude/lazy.settings.json` under the `experts` key:

```jsonc
"experts": {
  "_version": 1,
  "game-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": ["lazycortex-experts:lazy-experts.game-dev-aspect"]
  },
  "config-plugin-interpreter": {
    "agent": "lazycortex-experts:lazy-experts.interpreter",
    "aspects": [
      "lazycortex-experts:lazy-experts.claude-plugin-aspect",
      "lazycortex-experts:lazy-experts.dotfiles-aspect"
    ]
  }
}
```

The entry key (`"game-designer"`, `"config-plugin-interpreter"`) becomes the specialist's identity — the name a dispatching routine uses to look up which agent and aspects to load. Keep names lowercase, hyphenated, and descriptive: `<domain>-<role>` is the convention the built-in entries follow.

When you list more than one aspect, the expert runtime merges them in declaration order. Earlier aspects take precedence when obligations conflict. In the example above, `claude-plugin-aspect` obligations run first, and `dotfiles-aspect` obligations supplement them.

## Common adjustments

**Register a model tier.** Every specialist entry should have a model tier so the expert runtime knows which capability class to request. Run `/lazy-core.agent-models` — the skill presents a wizard that writes the `lazy.settings.json[agent_models]` entry for you. Do not edit the `agent_models` section by hand; the skill owns that schema.

**Use `/lazy-experts.install` as a baseline.** If you are building a specialist that is close to one of the nine built-in entries, run `/lazy-experts.install` first to seed the nearest base entry, then add your custom entry alongside it. The install skill never overwrites existing entries, so your custom work is safe.

**Bring an aspect from another plugin.** The `aspects` array accepts any qualified `<plugin-namespace>:<skill-name>` reference. If a plugin you have installed ships an aspect, check its block documentation for the correct reference string to use here.

**Adjust aspect order.** If two aspects impose conflicting obligations (rare, but possible when layering a domain-specific aspect over a highly opinionated second one), reorder them so the aspect whose rules should win is listed first.

## See also

- The **agents** block (`agents.md`) — describes the three generic agents and how they function as a linear pipeline.
- The **aspects** block (`aspects.md`) — describes the three built-in domain aspect files and shows what each one obliges the composing agent to do.
- The **install-and-audit** block (`install-and-audit.md`) — bootstraps the plugin and seeds the nine built-in specialist entries into `lazy.settings.json[experts]`.
