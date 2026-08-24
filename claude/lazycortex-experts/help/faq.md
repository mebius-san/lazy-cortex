---
chapter_type: faq
summary: Common questions about installing lazycortex-experts, the class map, composing specialists, and the thirteen generic agents' lane boundaries.
last_regen: 2026-08-24
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.architect
  - lazy-experts.planner
  - lazy-experts.use-case-writer
  - lazy-experts.ui-designer
  - lazy-experts.implementer
  - lazy-experts.data-implementer
  - lazy-experts.docs-writer
  - lazy-experts.debugger
  - lazy-experts.reviewer
  - lazy-experts.tester
  - lazy-experts.fiction-writer
source_sha: bd6abf68b291ce676681d87882caf99ee9e57b44
---
# Frequently asked questions

## Does /lazy-experts.install create my expert entries automatically?

Yes, but the shape follows the class map, not a flat product. The plugin ships eight domain aspects split into two families — six technical (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`) and two fiction genre aspects (`sci-fi`, `fantasy`). Choosing a technical class seeds twelve composed entries — `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `debugger`, `reviewer`, `tester` — for example choosing `claude-plugin` gives you `claude-plugin.interpreter`, `claude-plugin.designer`, `claude-plugin.system-designer`, `claude-plugin.architect`, `claude-plugin.planner`, `claude-plugin.use-case-writer`, `claude-plugin.ui-designer`, `claude-plugin.developer`, `claude-plugin.data-writer`, `claude-plugin.debugger`, `claude-plugin.reviewer`, and `claude-plugin.tester`. Three of those role keys resolve to an agent whose name doesn't match: `developer` composes the `lazy-experts.implementer` agent, `data-writer` composes the `lazy-experts.data-implementer` agent, and `system-designer` composes the `lazy-experts.designer` agent — the same agent the ordinary `designer` role composes, seeded as a second, independently dispatchable entry under its own key rather than sharing the `designer` entry. `data-writer` seeds with every technical class now, not just `game-dev` — writing data files against an approved design is a general genre a project of any technical class can need, not a game-dev particularity. Choosing a fiction class seeds only one entry: `fiction-writer` named for that class, e.g. `sci-fi.fiction-writer`. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs, plus `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect`; technical entries additionally carry `lazycortex-experts:lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect`, fiction entries never do.

Each seeded entry also includes a `git_author` block — a `name` (the expert key with hyphens and dots replaced by spaces, title-cased, e.g. `Game Interpreter`) and an `email` using the `@bot.invalid` domain. Writing-role entries (`designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester`) also carry `can_commit_in_repo: true`, and the four roles whose work runs on a job-scoped branch (`developer`, `data-writer`, `docs-writer`, `tester`) carry `workspace: "branch"`.

The plugin ships thirteen generic agents in total. Twelve get a role somewhere in the technical class map — `interpreter`, `designer` (composed twice, as `designer` and `system-designer`), `architect`, `planner`, `use-case-writer`, `ui-designer`, `implementer` (composed as `developer`), `data-implementer` (composed as `data-writer`), `debugger`, `reviewer`, and `tester`. The thirteenth, `lazy-experts.docs-writer`, gets no role under any class — technical, data, or fiction. If you need a docs-writer specialist, or any other specialist that doesn't match the class map — say, a custom aspect you authored, or an agent from another plugin — you write that entry yourself in `<repo-root>/.claude/lazy.settings.json` (project scope) or `~/.claude/lazy.settings.json` (global scope). The install skill leaves any hand-authored entries untouched.

---

## Why did choosing a fiction class only seed one entry instead of twelve?

Because fiction and technical classes seed a different set of entries by design. Technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`) seed twelve composed entries — interpreter through tester, including the architect who turns an approved design into a code-structure document, the use-case-writer who formalizes actor-facing scenarios before design starts, the ui-designer who settles the interface once a design is approved, and the designer seeded twice under separate keys (`designer` and `system-designer`, two independently dispatchable specialists sharing one persona) — because a plugin design, a game design, a dotfiles migration, an Obsidian plugin release, a data pipeline, or a general software product all move through the same interpret-design-architect-plan-implement-debug-review-test lifecycle, with use cases and UI design as parallel specialists inside it. Fiction classes (`sci-fi`, `fantasy`) pair with exactly one agent, `lazy-experts.fiction-writer`, because there's no equivalent lifecycle for narrative prose — the fiction writer takes a brief or outline and produces prose directly. This is not a partial install; a single `fiction-writer`-only entry is the complete, correct result for a fiction class.

---

## What is the software-product class for, and when do I pick it over a narrower domain?

`software-product` is the fallback technical class — pick it when your project is a piece of software but doesn't fit any of the five narrower shipped domains (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`). Its aspect stays neutral on language, stack, and delivery form (CLI, service, app, library), and instead pushes every seeded specialist toward the questions any product must answer regardless of domain: who uses it and how, what platforms it supports, what its compatibility and deprecation promises are, how a persisted-data format change gets migrated, what its configuration surface costs, and how a failure is seen by a user versus a maintainer. It seeds the same twelve roles the class map assigns every technical class — `interpreter` through `tester`, including `system-designer`, `use-case-writer`, and `ui-designer` — with the same five mandatory cross-cutting aspects.

Registering `software-product` is not a placeholder you swap out later. If your project's domain crystallizes into something narrower — say, a data pipeline emerges inside a broader software product — you keep the `software-product`-composed experts and stack the narrower domain aspect on top of the same entries (see "Can I attach more than one aspect to the same agent?" below) rather than re-registering the class from scratch.

---

## Why doesn't my sci-fi or fantasy specialist carry the tech-writing aspect?

Because `lazy-experts.tech-writing-aspect` bans metaphor, figurative imagery, atmospheric openings, and evaluative epithets — obligations that directly contradict the craft `lazy-experts.fiction-writer` exists to practice. The same reasoning excludes two more cross-cutting aspects from fiction classes: `lazy-experts.terms-aspect` (an obligation to call a thing by its registered term, read literally inside a scene, replaces pronouns and descriptive phrases with the entity name) and `lazy-experts.structure-aspect` (a repository map has nothing to say inside a scene). The class map reflects all three exclusions: technical classes get `discipline-aspect`, `research-aspect`, `tech-writing-aspect`, `terms-aspect`, and `structure-aspect` on every seeded entry; fiction classes get `discipline-aspect` and `research-aspect` only. If you hand-author a fiction specialist, follow the same rule and leave the other three out — adding them produces prose instructions that fight the fiction writer's own persona.

---

## Do I need to re-run /lazy-experts.install after a plugin update?

Yes, if the update ships new agent-model tier entries, a new role agent, or a new domain aspect. `/plugin update` refreshes the plugin cache but does not re-sync your `lazy.settings.json`. Re-run `/lazy-experts.install` to pick up any new `lazycortex-experts:*` entries from `lazycortex-core`'s `default-tiers.json`, and to fill in any role the class map now prescribes for a class you've already registered — for example, a project that registered a technical class before the `architect` role shipped picks up the missing `<domain>.architect` entry on re-run, a technical-class project registered before `system-designer` shipped picks up the missing `<domain>.system-designer` entry, and a technical-class project registered before `use-case-writer` or `ui-designer` shipped picks up the missing `<domain>.use-case-writer` and `<domain>.ui-designer` entries. The same applies to `data-writer`: it now seeds with every technical class rather than `game-dev` alone, so any technical-class project registered before that change picks up the missing `<domain>.data-writer` entry on re-run. A newly shipped class like `software-product` isn't retrofitted onto an existing project this way, though — re-running install only completes classes you've already registered; picking up a brand-new class still means registering one of its experts by hand (see "Class set is sticky once seeded" below). The skill is idempotent — re-running it is always safe; it only adds absent entries and leaves your customised values in place. It never adds a class you haven't already registered, and it never re-asks which classes to register once you have at least one domain-class expert registered. Note that a new role agent added to the class map is picked up this way; the docs-writer agent is not — no class map row seeds it, so re-running install never adds a docs-writer entry on its own.

---

## I customised a tier for one of the agents. Will /lazy-experts.install overwrite it?

No. When an entry is already in your `lazy.settings.json` and differs from the upstream default, the skill leaves your value untouched and reports `kept-local` alongside both values so the divergence is visible. If you want to change a tier, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json` and writes the value correctly. Do not hand-edit the file directly.

---

## /lazy-experts.install reported a "missing" system expert I didn't ask for. What is that?

That's the install skill's completeness check for **system experts** — entries other LazyCortex plugins register through their own install skills (for example `wiki.curator` from `lazycortex-wiki`, or `review.doc_doctor` from `lazycortex-review`). `/lazy-experts.install` never seeds or edits these itself; it only checks, for each sibling plugin that is enabled in your project, whether that plugin's expert keys are present in your `experts` section, and reports a gap so a plugin update that shipped a new system expert doesn't go unnoticed. A `missing` line names the fix — the owning plugin's own install skill (e.g. `/lazy-wiki.install`) — or you can ignore it if that plugin's feature is deliberately unconfigured in your project.

---

## What is the memory aspect that gets attached to every seeded expert?

Every expert entry seeded by `/lazy-experts.install` — technical or fiction — includes `lazycortex-core:lazy-memory.persona-aspect` in its `aspects` array. This aspect opts the expert into `lazycortex-core`'s memory subsystem: the expert can accumulate notes about your project, preferences, and prior work under `.memory/<expert-key>/` in the working repo. That memory persists across runs and is loaded back into the expert's context on subsequent dispatches.

If you remove the persona aspect from a seeded entry, the expert stops growing memory — the install skill never re-adds it on re-run, so the removal holds until you add it back manually. Removing it does not delete existing memory files; it just stops the expert from reading or writing them.

---

## The agents don't seem to do anything when I invoke them directly. Why?

All thirteen generic agents — the six design-time agents (interpreter, designer, architect, planner, use-case-writer, ui-designer), the six execution-stage agents (implementer, data-implementer, docs-writer, debugger, reviewer, tester), and the fiction writer — are persona-only: they have no inline I/O contract and wait for a dispatching routine to hand them a protocol document. Without a protocol, an agent returns an error naming the missing contract. You need a routine on your side (consumer-authored, or via a future `lazycortex-specs` integration) that dispatches jobs to these agents along with the appropriate protocol. The agents themselves are building blocks, not standalone commands.

---

## Can I skip the interpreter and dispatch the designer directly?

Yes. Each of the ten technical-lifecycle agents (interpreter, designer, architect, planner, use-case-writer, ui-designer, implementer, debugger, reviewer, tester) is independently dispatchable. If you already have a well-formed, gap-free brief, you can dispatch the designer directly without running the interpreter first. The interpreter-designer-architect-planner sequence is a convention that produces the best results starting from a vague idea, but it is not enforced — any agent can be dispatched at any point given the right input and a protocol. The same independence applies to the data-implementer, the docs-writer, and the fiction writer: none of them sit strictly downstream of the other agents, so you dispatch each one directly against whatever design or brief your own workflow produces.

---

## What's the actual difference between the designer and the planner?

The designer answers *what and why*; the planner answers *how*. The designer takes a gap-free brief and writes a design specification — premise first, then the solution, with an explicit in-scope/out-of-scope boundary — and it deliberately stays out of file paths, function names, and task ordering. The planner takes that design spec (or the architect's structure document, when the work has one) and turns it into an ordered, file-level implementation plan: which files change, in what order, with a test plan and a rollback procedure for each task. If you ask the designer for a task checklist, or ask the planner to reconsider a scope decision, you're asking the wrong agent — each one raises what it can't resolve as an open question against its own upstream input rather than silently deciding it.

---

## What's the difference between the `designer` and `system-designer` entries the class map seeds?

Nothing in the agent itself — both keys compose the same `lazy-experts.designer` agent, with the same domain and cross-cutting aspects the class map assigns to the technical row. The class map seeds them as two separately keyed entries (`<domain>.designer` and `<domain>.system-designer`) so a project can dispatch two independent design specialists that share one persona, rather than routing every design job through a single shared entry. Which jobs get routed to `system-designer` versus `designer` is decided by whichever routine dispatches the job — `lazycortex-experts` composes the entry but does not define that routing itself.

---

## Where does the architect fit between the designer and the planner?

The architect turns an approved design — behavior already settled — into a code-structure document: which modules exist, which way the dependencies point, what is public contract versus internals, what data has to migrate, and what it costs the callers that already exist. It answers *how the code is shaped*, which sits between the designer's *what and why* and the planner's *in what order*. Dispatch it over the designer when the behavior is decided and only the shape of the code is open, and over the planner when nothing should be sequenced into tasks yet. Like the other technical-lifecycle agents, it's independently dispatchable — hand it an approved design spec and a target `architecture.md` path directly, without going through the expert runtime.

---

## What does the use-case-writer do, and where does it sit relative to the designer?

The use-case-writer takes a settled brief or request and writes the formal use cases it implies — scenarios stated in the actor's language, with no system internals. Every scenario it produces carries an actor, a goal, a main flow, alternative flows, and pre- and postconditions; a scenario missing any of those five is incomplete and does not ship half-stated. It answers *what the actor needs and does*, which sits alongside — not downstream of — the designer's *what and why*: both take the same settled brief as input, but the designer scopes and justifies a solution while the use-case-writer states the scenarios that solution has to satisfy, in language a non-technical actor could check. It deliberately stays out of acceptance criteria and test plans — whether a scenario is satisfied, and how it would be tested, belongs to the tester's document. Like the designer, it raises a gap in the brief as a question in the document rather than closing it itself, and it's independently dispatchable — hand it a brief and a target use-cases document without going through the expert runtime.

---

## What does the ui-designer do, and how does it relate to the designer and the architect?

The ui-designer takes an approved design and settles its user interface: the screens, states, navigation, and interaction decisions, written into a ui-design document, with self-contained static HTML mockups laid down beside it as attachments so a reviewer can open them straight in a browser with no build step or live server. It sits downstream of the designer — behavior has to be approved first — parallel to the architect: the architect answers how the code is shaped, the ui-designer answers how the interface looks and behaves, and neither one waits on the other. Every screen it records states its empty, loading, error, and populated states and what moves it from one to the next; a screen recorded without them is incomplete. The document is the record of what was decided and why — a mockup that shows a layout or interaction the document doesn't mention is a decision made in the wrong artifact, so the ui-designer writes the decision first and the mockup second. It never produces production frontend code: no framework, no component library, no build output, nothing meant to be lifted into the product as-is — mockups approve a look and a flow, they ship nothing. Reviewer feedback arrives as callouts in the document; the ui-designer answers them there and regenerates the affected mockups on the next pass, rather than patching a live HTML page mid-review.

---

## What does the data-implementer do, and why does every technical class get it now?

The data-implementer takes an approved content design — a race, a skill, an item, a rule table — and writes it into the product's own data files, in the schemas the project already uses. There is no plan document in between: the design itself is the specification. It differs from the implementer because there is no ordered plan to follow, and from the tester because the job produces data rather than validates it. The class map now seeds `<domain>.data-writer` for every technical class, not only `game-dev` — writing data files against an approved design is a general genre a project of any technical class can need, not a game-dev particularity, so a project that registered a technical class before this change shipped picks up the missing `<domain>.data-writer` entry on re-running `/lazy-experts.install` (see "Do I need to re-run /lazy-experts.install after a plugin update?" above).

---

## What does the docs-writer do, and why doesn't any class seed it?

The docs-writer takes an approved design and writes what it delivers straight into the product's own user-facing documentation — whatever place, format, and voice that documentation already uses. There is no plan document in between: the design itself is the specification, the same relationship the data-implementer has to a content design. It differs from the data-implementer because the deliverable is documentation rather than data, and from the fiction-writer because the text is user-facing product documentation, not literary prose; where the design leaves user-visible behavior genuinely unsettled, it records the gap as an open question in its report rather than inventing behavior to fill the page.

Unlike every other role, the class map seeds no `docs-writer` entry for any class — technical, data, or fiction — so `/lazy-experts.install` never composes one for you, and re-running the skill after a plugin update won't add one either. If you want a docs-writer specialist, hand-author the entry in `lazy.settings.json[experts]`, pairing `lazycortex-experts:lazy-experts.docs-writer` with whichever aspects your project needs, `workspace: "branch"`, and `can_commit_in_repo: true` — the same field conventions the class map applies to the other writing roles.

---

## Do the debugger, reviewer, and tester all fix the problems they find?

No — only the debugger does, and only as the last step of its own investigation. The debugger's four-phase process (investigate, find a working pattern to compare against, form one hypothesis at a time, then fix) ends with it writing a failing test and making the change itself. The reviewer and the tester never fix anything: the reviewer returns ranked, evidence-backed findings and leaves the fix to the implementer; the tester discovers defects, writes bug reports, and minimizes reproductions, but creates no fixes and edits no existing tests. Neither does the docs-writer, the use-case-writer, or the ui-designer — each of them writes its own document straight from an approved brief or design and journals whatever is left unsettled as an open question, rather than fixing the product to match what it wanted to document. If your workflow needs a review's findings or a tester's bug report turned into code, that's a separate dispatch to the implementer or the debugger.

---

## What is an aspect and how does it differ from an agent?

An agent is a persona — it defines who the expert is, what its lane is, and what output it produces. An aspect is a pure prompt layer that adds domain knowledge or working discipline to whichever agent you pair it with. Aspects compose onto agents via the `lazy.settings.json[experts]` entry; the expert runtime merges the aspect bodies into the agent's system prompt at dispatch time. Aspects carry no side-effects and add no new write permissions; they expand what the agent knows without changing where or how it writes its output.

---

## Can I attach more than one aspect to the same agent?

Yes. The `aspects` array in your `lazy.settings.json[experts]` entry accepts any number of aspect references. The expert runtime merges them all into the system prompt in declaration order. When two aspects impose obligations that could conflict, earlier aspects take precedence. For example, a specialist that interprets a config-repo brief for a LazyCortex development machine could combine `dotfiles-aspect` and `claude-plugin-aspect` on the same interpreter entry, alongside `discipline-aspect` and `tech-writing-aspect`. On the fiction side, you can combine both genre aspects — `sci-fi-aspect` and `fantasy-aspect` — on the same `fiction-writer` entry for a story that blends the two.

---

## Can I use an aspect from this plugin with an agent from a different plugin?

That depends on the expert runtime's resolution rules, which are governed by `lazycortex-core`. Aspects shipped by `lazycortex-experts` are pure prompt files — nothing in their body is tied to a specific agent namespace. Whether a cross-plugin pairing is valid is determined by how the dispatching routine constructs the aspect references in the user-message prompt. Consult your dispatching routine's documentation or `lazycortex-core`'s expert runtime reference for the resolution contract.

---

## How do I verify my install is healthy after running /lazy-experts.install?

Run `/lazy-core.doctor`. There is no plugin-local audit skill for `lazycortex-experts` — health checks for the full LazyCortex setup, including whether the experts' `agent_models` entries and seeded `experts` entries are present and well-formed, route through `lazycortex-core`'s doctor.

---

## How do I change which Claude model tier a specific agent uses?

Run `/lazy-core.agent-models`. That skill manages the `agent_models` section of `lazy.settings.json` and writes the entry with the correct shape. The `lazycortex-experts:lazy-experts.<agent>` key under `agent_models.lazycortex` is the entry to update — this applies to the use-case-writer, the ui-designer, the fiction writer, the data-implementer, and the docs-writer the same as any other generic agent. Do not edit `lazy.settings.json` by hand — the skill owns that file's `agent_models` section.

---

## Can I author my own aspects and use them with these agents?

Yes. An aspect is a markdown file that adds domain guidance to whichever agent composes it. Nothing in the `lazycortex-experts` runtime restricts aspects to the eight domain aspects (or cross-cutting aspects) that ship with the plugin. You author an aspect file in your own plugin (or locally), then reference its path in the `aspects` array of your `lazy.settings.json[experts]` entry. The convention is to name the file `<namespace>.<domain>-aspect.md` and place it in your plugin's `references/` directory.

---

## The game-dev-aspect, dotfiles-aspect, obsidian-plugin-aspect, or data-pipeline-aspect doesn't mention the specific engine / tool I use. Is that a problem?

No. All four aspects are deliberately tool-agnostic and domain-neutral in their bodies — neutral on bundler, language, storage, or transport, opinionated only on the conceptual axes their domain always raises (lifecycle hygiene and API boundaries for Obsidian plugins; incremental state and resumability for data pipelines; and the equivalent axes for game-dev and dotfiles). The same is true of `sci-fi-aspect` and `fantasy-aspect` on the subgenre axis (hard SF vs space opera, epic vs urban fantasy), and of `software-product-aspect` on the delivery-form axis (CLI, service, app, library) — see the software-product question above for what it stays opinionated on instead. When your brief or request pins a specific engine (Unity, Unreal, Godot), dotfile tool (chezmoi, yadm, stow, Nix home-manager), plugin bundler, sync transport, or subgenre, the specialist honors that pin literally in its output. The aspect body names category-level patterns and obligations; the concrete choices flow from your request.

---

## Where do I ask questions about the expert runtime itself — job dispatch, the daemon, model resolution?

Not here. `lazycortex-experts` ships the generic agents and aspect files you compose into specialists; it ships no dispatcher, no daemon, and no job-queue logic. All of that lives in `lazycortex-core` — the expert runtime that resolves `lazy.settings.json[experts]` entries, dispatches jobs, and runs the daemon that picks up routine-triggered work. Questions about how a job actually gets dispatched, how the daemon schedules routines, or how model tiers resolve at runtime belong in `lazycortex-core`'s own documentation, not here.
