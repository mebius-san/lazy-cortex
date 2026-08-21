---
chapter_type: block
summary: Assemble a named specialist by pairing one generic agent with aspects in lazy.settings.json[experts], following the technical/fiction class map.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-experts.install
source_sha: 159ac1288fe27b2672a13bdafc577c34c46cb8d5
---
# Assembling a specialist from agents and aspects

A specialist is a named expert entry you declare in `lazy.settings.json[experts]`. It pairs one generic agent (the persona) with one or more aspects (the knowledge and discipline layers) so the expert runtime can produce a fully-qualified specialist system prompt at dispatch time — without you authoring a fresh agent for each domain or use-case.

The composition pattern has two moving parts. The **agent** supplies the output discipline: the interpreter knows how to structure a gap-free brief, the designer knows how to write a declarative spec, the architect knows how to design a code structure once the behavior is settled, the planner knows how to produce a file-level task list, the implementer/debugger/reviewer/tester know their execution-stage disciplines, the data-implementer knows how to turn an approved content design into a product's own data files, the docs-writer knows how to turn an approved design straight into user-facing documentation with no plan in between, and the fiction-writer knows the craft of narrative prose. The **aspect** supplies the knowledge layer on top: a domain aspect adds what counts as a complete brief for a LazyCortex plugin change, an Obsidian plugin, a data pipeline, a game-design document, or what a science-fiction premise owes the reader; a cross-cutting aspect adds working discipline that applies no matter the domain. Neither layer changes the other's responsibilities; the expert runtime merges them at dispatch time in the order you declare them.

## When you'd use this

- You want a specialist that does not exist in the entries `/lazy-experts.install` seeds by default — for example a `game-planner-strict` variant with a custom aspect, or a `my-domain.interpreter` for a domain aspect your own plugin ships.
- You want a `lazy-experts.docs-writer` specialist — no class the install wizard seeds ever registers one automatically, so building it is always a manual composition.
- You want to combine two aspects in one specialist — for instance, a designer that knows both LazyCortex plugin conventions and dotfiles structure because your target project is a plugin that also manages machine config.
- You want to pair the fiction-writer agent with a genre aspect (`sci-fi` or `fantasy`) to get a specialist for a particular kind of literary work, rather than accepting whichever class `/lazy-experts.install` already seeded.
- You want to give a specialist a different model tier than the built-in default.
- You received an aspect from a third-party plugin and want to wire it onto one of the generic agents.

## How it fits together

Start by deciding which generic agent fits the job. Four agents are design-time: `lazy-experts.interpreter` clarifies a request into a structured brief, `lazy-experts.designer` turns a brief into a declarative design spec, `lazy-experts.architect` takes a settled design and works out the code structure it implies — module boundaries, dependency direction, public contract versus internals — for when the behavior is decided and only the shape of the code is still open, `lazy-experts.planner` turns a design (or an architecture doc) into an ordered implementation plan. Four are execution-stage: `lazy-experts.implementer` executes a plan test-first, `lazy-experts.debugger` investigates a bug to its root cause, `lazy-experts.reviewer` returns ranked findings against a change, `lazy-experts.tester` surveys the testing mechanisms the repository actually ships and works only through them — writing test plans, executing them step by step, filing bug reports, and minimizing failures to steps-to-reproduce. One is literary: `lazy-experts.fiction-writer` takes a brief or outline and produces narrative prose, dialogue, or lyrical fragments — dispatch it for fiction deliverables, never for technical documents. `lazy-experts.data-implementer` writes an approved content design's entity data files into the product's own repository — it composes only with the `game-dev` domain aspect, the one class where content authoring diverges enough from code implementation to need its own role. `lazy-experts.docs-writer` takes an approved design straight to user-facing documentation, with no plan in between — pick it over the implementer when the deliverable is documentation rather than code, and over the fiction-writer when the text is product documentation rather than literary prose. Each agent is independently dispatchable — you do not need the whole set to build a specialist.

The specialist entry's key names a **role**, and a role does not always share its agent's basename. `/lazy-experts.install`'s class map seeds nine technical roles — `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester` — plus `data-writer` on the `game-dev` class and `fiction-writer` on the two fiction classes. Most role names match their agent's own name, but three don't: role `developer` dispatches the `lazy-experts.implementer` agent, role `data-writer` dispatches `lazy-experts.data-implementer`, and role `system-designer` dispatches `lazy-experts.designer` — the same agent the plain `designer` role dispatches, composed under a second expert key. When you hand-compose a specialist, the role name (the expert key's second segment) and the agent it dispatches are independent choices — they don't have to match.

Next, pick the aspects that add the knowledge and discipline your specialist needs. Aspects fall into two groups:

- **Domain aspects** name the subject matter. Five are technical — `lazy-experts.claude-plugin-aspect`, `lazy-experts.game-dev-aspect`, `lazy-experts.dotfiles-aspect`, `lazy-experts.obsidian-plugin-aspect`, `lazy-experts.data-pipeline-aspect` — and pair with any of the nine technical roles (plus `data-writer` for `game-dev`). Two are fiction genre aspects — `lazy-experts.sci-fi-aspect`, `lazy-experts.fantasy-aspect` — and pair with `lazy-experts.fiction-writer`. If another plugin in your project ships a domain aspect, reference it by its plugin-namespace prefix the same way.
- **Cross-cutting aspects** apply regardless of domain. `lazy-experts.discipline-aspect` carries the iron laws (verify before completion, never guess past a gap, no performative agreement, read decisions before starting and never revisit one silently) and `lazy-experts.research-aspect` obliges the expert to actively gather knowledge — the product's own docs, a structure map, a covered wiki scope, the surrounding tree — before writing, rather than treating its dispatched input as the whole of what it may know; both belong on every specialist you build, technical or fiction. Three more are technical-only: `lazy-experts.tech-writing-aspect` bans literary devices and enforces a single-term-per-concept dictionary within a document, `lazy-experts.terms-aspect` routes word choice through the repository's terms dictionary so two documents written months apart converge on the same word, and `lazy-experts.structure-aspect` routes placement questions ("where does this live, where does new work belong") through the repository's structure map instead of scanning the tree. None of the three belong on a fiction specialist — banning metaphor and figurative imagery directly contradicts what `lazy-experts.fiction-writer`'s own persona requires, and a terms dictionary or a structure map has nothing to say inside a scene.

This technical/fiction split is the same class map `/lazy-experts.install` applies when it seeds specialists automatically: technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) compose `lazy-experts.discipline-aspect`, `lazy-experts.research-aspect`, `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect` onto all nine technical-lifecycle roles (`interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester`); the `game-dev` class additionally seeds `data-writer` (dispatching `lazy-experts.data-implementer`) with the same five cross-cutting aspects, since data authoring is a `game-dev` particularity rather than something every technical class needs. Fiction classes (`sci-fi`, `fantasy`) compose `lazy-experts.discipline-aspect` and `lazy-experts.research-aspect` only, onto `fiction-writer`. `lazy-experts.docs-writer` is never seeded by any class — every docs-writer specialist is hand-composed. When you hand-compose a specialist outside the wizard, follow the same split — a technical specialist missing one of the five cross-cutting aspects loses discipline it should have, and a fiction specialist carrying `tech-writing-aspect`, `terms-aspect`, or `structure-aspect` gets instructions that fight its own agent persona.

Declare the entry in `<repo>/.claude/lazy.settings.json` under the `experts` key:

```jsonc
"experts": {
  "_version": 1,
  "game.designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": [
      "lazycortex-experts:lazy-experts.game-dev-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect",
      "lazycortex-experts:lazy-experts.terms-aspect",
      "lazycortex-experts:lazy-experts.structure-aspect"
    ],
    "can_commit_in_repo": true
  },
  "sci-fi.fiction-writer": {
    "agent": "lazycortex-experts:lazy-experts.fiction-writer",
    "aspects": [
      "lazycortex-experts:lazy-experts.sci-fi-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect"
    ]
  },
  "config-plugin.interpreter": {
    "agent": "lazycortex-experts:lazy-experts.interpreter",
    "aspects": [
      "lazycortex-experts:lazy-experts.claude-plugin-aspect",
      "lazycortex-experts:lazy-experts.dotfiles-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect",
      "lazycortex-experts:lazy-experts.terms-aspect",
      "lazycortex-experts:lazy-experts.structure-aspect"
    ]
  },
  "claude-plugin.docs-writer": {
    "agent": "lazycortex-experts:lazy-experts.docs-writer",
    "aspects": [
      "lazycortex-experts:lazy-experts.claude-plugin-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect",
      "lazycortex-experts:lazy-experts.terms-aspect",
      "lazycortex-experts:lazy-experts.structure-aspect"
    ],
    "workspace": "branch",
    "can_commit_in_repo": true
  }
}
```

Note that `sci-fi.fiction-writer` and `config-plugin.interpreter` carry no `can_commit_in_repo` flag — `fiction-writer` and `interpreter` deliver through the review payload channel rather than landing a file in the tree, so they stay without commit rights, same as `reviewer`. `game.designer` and `claude-plugin.docs-writer` each get `can_commit_in_repo: true` because their agents write a document in place; `claude-plugin.docs-writer` additionally gets `workspace: "branch"` because `docs-writer` is one of the acceptance-cycle roles that commits its work on a job-scoped branch.

The entry key (`"game.designer"`, `"sci-fi.fiction-writer"`, `"config-plugin.interpreter"`, `"claude-plugin.docs-writer"`) becomes the specialist's identity — the name a dispatching routine uses to look up which agent and aspects to load. Keep names lowercase and descriptive, following the marketplace-wide `<domain>.<role>` convention the built-in entries use — dot-separated between domain and role, e.g. `claude-plugin.designer`, `game.interpreter`, `sci-fi.fiction-writer` (cf. `review.doc_doctor`, `wiki.curator`, `spec.coordinator`). A domain name that carries its own hyphen (`claude-plugin`, `data-pipeline`) keeps that hyphen; only the domain/role boundary uses a dot.

When you list more than one aspect, the expert runtime merges them in declaration order. Earlier aspects take precedence when obligations conflict. In the `config-plugin.interpreter` example above, `claude-plugin-aspect` obligations run first, and `dotfiles-aspect` obligations supplement them.

## Common adjustments

**Register a model tier.** Every specialist entry should have a model tier so the expert runtime knows which capability class to request. Run `/lazy-core.agent-models` — the skill presents a wizard that writes the `lazy.settings.json[agent_models]` entry for you. Do not edit the `agent_models` section by hand; the skill owns that schema.

**Use `/lazy-experts.install` as a baseline.** If you are building a specialist that is close to one already seeded by the class map, run `/lazy-experts.install` first to register the nearest base class, then add your custom entry alongside it. The install skill never overwrites existing entries, so your custom work is safe.

**Building a technical specialist by hand.** Mirror the class map: pair one of the nine technical-lifecycle roles (`interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester` — remember `developer` dispatches the `lazy-experts.implementer` agent, and `system-designer` dispatches `lazy-experts.designer`) with a technical domain aspect (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, or `data-pipeline`), then append `lazy-experts.discipline-aspect`, `lazy-experts.research-aspect`, `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect` in that order, same as `/lazy-experts.install` would. Add `can_commit_in_repo: true` to every role except `interpreter` and `reviewer` — those two deliver through the review payload channel rather than landing a file in the tree, so they stay without commit rights. Add `workspace: "branch"` only on `developer` and `tester` — the acceptance-cycle roles that run their launch-checkbox job and every continuation on a job-scoped branch. If the class is `game-dev`, you can additionally pair `lazy-experts.data-implementer` under the role key `data-writer` with `lazy-experts.game-dev-aspect` and the same five cross-cutting aspects, plus `workspace: "branch"` and `can_commit_in_repo: true` — it is the one role the class map seeds beyond the shared nine.

**Building a docs-writer specialist by hand.** No class `/lazy-experts.install` seeds ever registers `lazy-experts.docs-writer` — it always has to be composed by hand. Pick a role key such as `<domain>.docs-writer`, pair it with a technical domain aspect and the same five cross-cutting aspects as any technical role, then add `workspace: "branch"` and `can_commit_in_repo: true` so its documentation lands in the tracked tree on a job-scoped branch instead of stranding in the job's own result.

**Building a fiction specialist by hand.** Pair `lazy-experts.fiction-writer` with a genre aspect (`sci-fi` or `fantasy`), then append `lazy-experts.discipline-aspect` and `lazy-experts.research-aspect`. Leave `can_commit_in_repo` unset — `fiction-writer` delivers through the review payload channel rather than committing a file, same as `interpreter` and `reviewer`. Never add `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, or `lazy-experts.structure-aspect` to a fiction specialist — none of the three have anything useful to say inside a scene.

**Bring an aspect from another plugin.** The `aspects` array accepts any qualified `<plugin-namespace>:<skill-name>` reference. If a plugin you have installed ships an aspect, check its block documentation for the correct reference string to use here.

**Adjust aspect order.** If two aspects impose conflicting obligations (rare, but possible when layering a domain-specific aspect over a highly opinionated second one), reorder them so the aspect whose rules should win is listed first.

## See also

- The **agents** block (`agents.md`) — describes the generic agents, the design-time / execution-stage / literary groupings, and how the technical-lifecycle agents function as a linear pipeline.
- The **aspects** block (`aspects.md`) — describes the domain aspect files (technical and fiction) and the cross-cutting aspects, and shows what each one obliges the composing agent to do.
- The **install-and-audit** block (`install-and-audit.md`) — bootstraps the plugin and seeds specialist entries per the class map, technical classes vs fiction classes.
