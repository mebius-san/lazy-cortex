---
chapter_type: faq
summary: Common questions about installing lazycortex-experts, the class map, composing specialists, and the eleven generic agents' lane boundaries.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.architect
  - lazy-experts.planner
  - lazy-experts.implementer
  - lazy-experts.data-implementer
  - lazy-experts.docs-writer
  - lazy-experts.debugger
  - lazy-experts.reviewer
  - lazy-experts.tester
  - lazy-experts.fiction-writer
source_sha: 159ac1288fe27b2672a13bdafc577c34c46cb8d5
---
# Frequently asked questions

## Does /lazy-experts.install create my expert entries automatically?

Yes, but the shape follows the class map, not a flat product. The plugin ships seven domain aspects split into two families — five technical (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) and two fiction genre aspects (`sci-fi`, `fantasy`). Choosing a technical class seeds nine composed entries — `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester` — for example choosing `claude-plugin` gives you `claude-plugin.interpreter`, `claude-plugin.designer`, `claude-plugin.system-designer`, `claude-plugin.architect`, `claude-plugin.planner`, `claude-plugin.developer`, `claude-plugin.debugger`, `claude-plugin.reviewer`, and `claude-plugin.tester`. Three of those role keys resolve to an agent whose name doesn't match: `developer` composes the `lazy-experts.implementer` agent, and `system-designer` composes the `lazy-experts.designer` agent — the same agent the ordinary `designer` role composes, seeded as a second, independently dispatchable entry under its own key rather than sharing the `designer` entry. Choosing `game-dev` additionally seeds a tenth role, `game.data-writer`, composing the `lazy-experts.data-implementer` agent — writing entity data files is a `game-dev` particularity, not something every technical class gets. Choosing a fiction class seeds only one entry: `fiction-writer` named for that class, e.g. `sci-fi.fiction-writer`. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs, plus `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect`; technical entries additionally carry `lazycortex-experts:lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect`, fiction entries never do.

Each seeded entry also includes a `git_author` block — a `name` (the expert key with hyphens and dots replaced by spaces, title-cased, e.g. `Game Interpreter`) and an `email` using the `@bot.invalid` domain. Writing-role entries (designer, system-designer, architect, planner, developer, data-writer, debugger, tester) also carry `can_commit_in_repo: true`, and the four roles whose work runs on a job-scoped branch (developer, data-writer, docs-writer, tester) carry `workspace: "branch"`.

The plugin ships an eleventh agent, `lazy-experts.docs-writer`, for user-facing documentation, but the class map does not seed a role for it under any class — technical, data, or fiction. If you need a docs-writer specialist, or any other specialist that doesn't match the class map — say, a custom aspect you authored, or an agent from another plugin — you write that entry yourself in `<repo-root>/.claude/lazy.settings.json` (project scope) or `~/.claude/lazy.settings.json` (global scope). The install skill leaves any hand-authored entries untouched.

---

## Why did choosing a fiction class only seed one entry instead of nine?

Because fiction and technical classes seed a different set of entries by design. Technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) seed nine composed entries — interpreter through tester, including the architect who turns an approved design into a code-structure document, and the designer seeded twice under separate keys (`designer` and `system-designer`, two independently dispatchable specialists sharing one persona) — because a plugin design, a game design, a dotfiles migration, an Obsidian plugin release, or a data pipeline all move through the same interpret-design-architect-plan-implement-debug-review-test lifecycle. Fiction classes (`sci-fi`, `fantasy`) pair with exactly one agent, `lazy-experts.fiction-writer`, because there's no equivalent lifecycle for narrative prose — the fiction writer takes a brief or outline and produces prose directly. This is not a partial install; a single `fiction-writer`-only entry is the complete, correct result for a fiction class.

---

## Why doesn't my sci-fi or fantasy specialist carry the tech-writing aspect?

Because `lazy-experts.tech-writing-aspect` bans metaphor, figurative imagery, atmospheric openings, and evaluative epithets — obligations that directly contradict the craft `lazy-experts.fiction-writer` exists to practice. The same reasoning excludes two more cross-cutting aspects from fiction classes: `lazy-experts.terms-aspect` (an obligation to call a thing by its registered term, read literally inside a scene, replaces pronouns and descriptive phrases with the entity name) and `lazy-experts.structure-aspect` (a repository map has nothing to say inside a scene). The class map reflects all three exclusions: technical classes get `discipline-aspect`, `research-aspect`, `tech-writing-aspect`, `terms-aspect`, and `structure-aspect` on every seeded entry; fiction classes get `discipline-aspect` and `research-aspect` only. If you hand-author a fiction specialist, follow the same rule and leave the other three out — adding them produces prose instructions that fight the fiction writer's own persona.

---

## Do I need to re-run /lazy-experts.install after a plugin update?

Yes, if the update ships new agent-model tier entries, a new role agent, or a new domain aspect. `/plugin update` refreshes the plugin cache but does not re-sync your `lazy.settings.json`. Re-run `/lazy-experts.install` to pick up any new `lazycortex-experts:*` entries from `lazycortex-core`'s `default-tiers.json`, and to fill in any role the class map now prescribes for a class you've already registered — for example, a project that registered a technical class before the `architect` role shipped picks up the missing `<domain>.architect` entry on re-run, a technical-class project registered before `system-designer` shipped picks up the missing `<domain>.system-designer` entry, and a `game-dev` project registered before `data-writer` shipped picks up `game.data-writer`. The skill is idempotent — re-running it is always safe; it only adds absent entries and leaves your customised values in place. It never adds a class you haven't already registered, and it never re-asks which classes to register once you have at least one domain-class expert registered. Note that a new role agent added to the class map is picked up this way; the docs-writer agent is not — no class map row seeds it, so re-running install never adds a docs-writer entry on its own.

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

All eleven generic agents — the eight technical-lifecycle agents, the data-implementer, the docs-writer, and the fiction writer — are persona-only: they have no inline I/O contract and wait for a dispatching routine to hand them a protocol document. Without a protocol, an agent returns an error naming the missing contract. You need a routine on your side (consumer-authored, or via a future `lazycortex-specs` integration) that dispatches jobs to these agents along with the appropriate protocol. The agents themselves are building blocks, not standalone commands.

---

## Can I skip the interpreter and dispatch the designer directly?

Yes. Each of the eight technical-lifecycle agents is independently dispatchable. If you already have a well-formed, gap-free brief, you can dispatch the designer directly without running the interpreter first. The interpreter-designer-architect-planner sequence is a convention that produces the best results starting from a vague idea, but it is not enforced — any agent can be dispatched at any point given the right input and a protocol. The same independence applies to the fiction writer: it never sits downstream of the other eight, so you dispatch it directly against whatever brief or outline your own workflow produces.

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

## What does the data-implementer do, and why does only the game-dev class get it?

The data-implementer takes an approved content design — a race, a skill, an item, a rule table — and writes it into the product's own data files, in the schemas the project already uses. There is no plan document in between: the design itself is the specification. It differs from the implementer because there is no ordered plan to follow, and from the tester because the job produces data rather than validates it. The class map seeds `game.data-writer` only for the `game-dev` class — writing entity data files is a subject-matter particularity of game development, seeded in addition to the nine roles every technical class gets. If a project of another class wants this role, that's a hand-authored `lazy.settings.json[experts]` entry, not something the class map grants by default.

---

## What does the docs-writer do, and why doesn't any class seed it?

The docs-writer takes an approved design and writes what it delivers straight into the product's own user-facing documentation — whatever place, format, and voice that documentation already uses. There is no plan document in between: the design itself is the specification, the same relationship the data-implementer has to a content design. It differs from the data-implementer because the deliverable is documentation rather than data, and from the fiction-writer because the text is user-facing product documentation, not literary prose; where the design leaves user-visible behavior genuinely unsettled, it records the gap as an open question in its report rather than inventing behavior to fill the page.

Unlike every other role, the class map seeds no `docs-writer` entry for any class — technical, data, or fiction — so `/lazy-experts.install` never composes one for you, and re-running the skill after a plugin update won't add one either. If you want a docs-writer specialist, hand-author the entry in `lazy.settings.json[experts]`, pairing `lazycortex-experts:lazy-experts.docs-writer` with whichever aspects your project needs, `workspace: "branch"`, and `can_commit_in_repo: true` — the same field conventions the class map applies to the other writing roles.

---

## Do the debugger, reviewer, and tester all fix the problems they find?

No — only the debugger does, and only as the last step of its own investigation. The debugger's four-phase process (investigate, find a working pattern to compare against, form one hypothesis at a time, then fix) ends with it writing a failing test and making the change itself. The reviewer and the tester never fix anything: the reviewer returns ranked, evidence-backed findings and leaves the fix to the implementer; the tester discovers defects, writes bug reports, and minimizes reproductions, but creates no fixes and edits no existing tests. Neither does the docs-writer — it writes documentation straight from an approved design and journals whatever the design leaves unsettled as an open question, rather than fixing the product to match what it wanted to document. If your workflow needs a review's findings or a tester's bug report turned into code, that's a separate dispatch to the implementer or the debugger.

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

Run `/lazy-core.agent-models`. That skill manages the `agent_models` section of `lazy.settings.json` and writes the entry with the correct shape. The `lazycortex-experts:lazy-experts.<agent>` key under `agent_models.lazycortex` is the entry to update — this applies to the fiction writer, the data-implementer, and the docs-writer the same as any other generic agent. Do not edit `lazy.settings.json` by hand — the skill owns that file's `agent_models` section.

---

## Can I author my own aspects and use them with these agents?

Yes. An aspect is a markdown file that adds domain guidance to whichever agent composes it. Nothing in the `lazycortex-experts` runtime restricts aspects to the seven domain aspects (or cross-cutting aspects) that ship with the plugin. You author an aspect file in your own plugin (or locally), then reference its path in the `aspects` array of your `lazy.settings.json[experts]` entry. The convention is to name the file `<namespace>.<domain>-aspect.md` and place it in your plugin's `references/` directory.

---

## The game-dev-aspect, dotfiles-aspect, obsidian-plugin-aspect, or data-pipeline-aspect doesn't mention the specific engine / tool I use. Is that a problem?

No. All four aspects are deliberately tool-agnostic and domain-neutral in their bodies — neutral on bundler, language, storage, or transport, opinionated only on the conceptual axes their domain always raises (lifecycle hygiene and API boundaries for Obsidian plugins; incremental state and resumability for data pipelines; and the equivalent axes for game-dev and dotfiles). The same is true of `sci-fi-aspect` and `fantasy-aspect` on the subgenre axis (hard SF vs space opera, epic vs urban fantasy). When your brief or request pins a specific engine (Unity, Unreal, Godot), dotfile tool (chezmoi, yadm, stow, Nix home-manager), plugin bundler, sync transport, or subgenre, the specialist honors that pin literally in its output. The aspect body names category-level patterns and obligations; the concrete choices flow from your request.

---

## Where do I ask questions about the expert runtime itself — job dispatch, the daemon, model resolution?

Not here. `lazycortex-experts` ships the generic agents and aspect files you compose into specialists; it ships no dispatcher, no daemon, and no job-queue logic. All of that lives in `lazycortex-core` — the expert runtime that resolves `lazy.settings.json[experts]` entries, dispatches jobs, and runs the daemon that picks up routine-triggered work. Questions about how a job actually gets dispatched, how the daemon schedules routines, or how model tiers resolve at runtime belong in `lazycortex-core`'s own documentation, not here.
