---
chapter_type: faq
summary: Common questions about installing lazycortex-experts, the technical/fiction class map, composing specialists, and the eight generic agents' lane boundaries.
last_regen: 2026-07-22
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.planner
  - lazy-experts.implementer
  - lazy-experts.debugger
  - lazy-experts.reviewer
  - lazy-experts.tester
  - lazy-experts.fiction-writer
---
# Frequently asked questions

## Does /lazy-experts.install create my expert entries automatically?

Yes, but the shape follows the class map, not a flat product. The plugin ships seven domain aspects split into two families — five technical (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) and two fiction genre aspects (`sci-fi`, `fantasy`). Choosing a technical class seeds all seven engineering roles for that class (`interpreter`, `designer`, `planner`, `implementer`, `debugger`, `reviewer`, `tester`) — for example choosing `claude-plugin` gives you `claude-plugin.interpreter` through `claude-plugin.tester`, seven entries. Choosing a fiction class seeds only one entry: `fiction-writer` named for that class, e.g. `sci-fi.fiction-writer`. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs, plus `lazycortex-experts:lazy-experts.discipline-aspect`; technical entries additionally carry `lazycortex-experts:lazy-experts.tech-writing-aspect`, fiction entries never do.

Each seeded entry also includes a `git_author` block — a `name` (the expert key with hyphens and dots replaced by spaces, title-cased, e.g. `Game Interpreter`) and an `email` using the `@lazycortex.local` domain.

If you need a specialist that doesn't match the class map — say, a custom aspect you authored, or an agent from another plugin — you write that entry yourself in `<repo-root>/.claude/lazy.settings.json` (project scope) or `~/.claude/lazy.settings.json` (global scope). The install skill leaves any hand-authored entries untouched.

---

## Why did choosing a fiction class only seed one entry instead of seven?

Because fiction and technical classes seed a different set of roles by design. Technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) pair with all seven engineering agents — interpreter through tester — because a plugin design, a game design, a dotfiles migration, an Obsidian plugin release, or a data pipeline all move through the same interpret-design-plan-implement-debug-review-test lifecycle. Fiction classes (`sci-fi`, `fantasy`) pair with exactly one agent, `lazy-experts.fiction-writer`, because there's no equivalent lifecycle for narrative prose — the fiction writer takes a brief or outline and produces prose directly. This is not a partial install; a single `fiction-writer`-only entry is the complete, correct result for a fiction class.

---

## Why doesn't my sci-fi or fantasy specialist carry the tech-writing aspect?

Because `lazy-experts.tech-writing-aspect` bans metaphor, figurative imagery, atmospheric openings, and evaluative epithets — obligations that directly contradict the craft `lazy-experts.fiction-writer` exists to practice. The class map reflects that: technical classes get `discipline-aspect` and `tech-writing-aspect` on every seeded entry; fiction classes get `discipline-aspect` only. If you hand-author a fiction specialist, follow the same rule and leave `tech-writing-aspect` out — adding it produces prose instructions that fight the fiction writer's own persona.

---

## Do I need to re-run /lazy-experts.install after a plugin update?

Yes, if the update ships new agent-model tier entries, a new role agent, or a new domain aspect. `/plugin update` refreshes the plugin cache but does not re-sync your `lazy.settings.json`. Re-run `/lazy-experts.install` to pick up any new `lazycortex-experts:*` entries from `lazycortex-core`'s `default-tiers.json`, and to fill in any role the class map now prescribes for a class you've already registered — for example, a project that registered a technical class before the `tester` role shipped picks up the missing `<domain>.tester` entry on re-run. The skill is idempotent — re-running it is always safe; it only adds absent entries and leaves your customised values in place. It never adds a class you haven't already registered, and it never re-asks which classes to register once you have at least one domain-class expert registered.

---

## I customised a tier for one of the agents. Will /lazy-experts.install overwrite it?

No. When an entry is already in your `lazy.settings.json` and differs from the upstream default, the skill leaves your value untouched and reports `kept-local` alongside both values so the divergence is visible. If you want to change a tier, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json` and writes the value correctly. Do not hand-edit the file directly.

---

## /lazy-experts.install reported a "missing" system expert I didn't ask for. What is that?

That's the install skill's completeness check for **system experts** — entries other LazyCortex plugins register through their own install skills (for example `wiki.curator` from `lazycortex-wiki`, or `review.historian` from `lazycortex-review`). `/lazy-experts.install` never seeds or edits these itself; it only checks, for each sibling plugin that is enabled in your project, whether that plugin's expert keys are present in your `experts` section, and reports a gap so a plugin update that shipped a new system expert doesn't go unnoticed. A `missing` line names the fix — the owning plugin's own install skill (e.g. `/lazy-wiki.install`) — or you can ignore it if that plugin's feature is deliberately unconfigured in your project.

---

## What is the memory aspect that gets attached to every seeded expert?

Every expert entry seeded by `/lazy-experts.install` — technical or fiction — includes `lazycortex-core:lazy-memory.persona-aspect` in its `aspects` array. This aspect opts the expert into `lazycortex-core`'s memory subsystem: the expert can accumulate notes about your project, preferences, and prior work under `.memory/<expert-key>/` in the working repo. That memory persists across runs and is loaded back into the expert's context on subsequent dispatches.

If you remove the persona aspect from a seeded entry, the expert stops growing memory — the install skill never re-adds it on re-run, so the removal holds until you add it back manually. Removing it does not delete existing memory files; it just stops the expert from reading or writing them.

---

## The agents don't seem to do anything when I invoke them directly. Why?

All eight generic agents — the seven technical-lifecycle agents plus the fiction writer — are persona-only: they have no inline I/O contract and wait for a dispatching routine to hand them a protocol document. Without a protocol, an agent returns an error naming the missing contract. You need a routine on your side (consumer-authored, or via a future `lazycortex-specs` integration) that dispatches jobs to these agents along with the appropriate protocol. The agents themselves are building blocks, not standalone commands.

---

## Can I skip the interpreter and dispatch the designer directly?

Yes. Each of the seven technical-lifecycle agents is independently dispatchable. If you already have a well-formed, gap-free brief, you can dispatch the designer directly without running the interpreter first. The interpreter-designer-planner sequence is a convention that produces the best results starting from a vague idea, but it is not enforced — any agent can be dispatched at any point given the right input and a protocol. The same independence applies to the fiction writer: it never sits downstream of the other seven, so you dispatch it directly against whatever brief or outline your own workflow produces.

---

## What's the actual difference between the designer and the planner?

The designer answers *what and why*; the planner answers *how*. The designer takes a gap-free brief and writes a design specification — premise first, then the solution, with an explicit in-scope/out-of-scope boundary — and it deliberately stays out of file paths, function names, and task ordering. The planner takes that design spec and turns it into an ordered, file-level implementation plan: which files change, in what order, with a test plan and a rollback procedure for each task. If you ask the designer for a task checklist, or ask the planner to reconsider a scope decision, you're asking the wrong agent — each one raises what it can't resolve as an open question against its own upstream input rather than silently deciding it.

---

## Do the debugger, reviewer, and tester all fix the problems they find?

No — only the debugger does, and only as the last step of its own investigation. The debugger's four-phase process (investigate, find a working pattern to compare against, form one hypothesis at a time, then fix) ends with it writing a failing test and making the change itself. The reviewer and the tester never fix anything: the reviewer returns ranked, evidence-backed findings and leaves the fix to the implementer; the tester discovers defects, writes bug reports, and minimizes reproductions, but creates no fixes and edits no existing tests. If your workflow needs a review's findings or a tester's bug report turned into code, that's a separate dispatch to the implementer or the debugger.

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

Run `/lazy-core.agent-models`. That skill manages the `agent_models` section of `lazy.settings.json` and writes the entry with the correct shape. The `lazycortex-experts:lazy-experts.<agent>` key under `agent_models.lazycortex` is the entry to update — this applies to the fiction writer the same as any technical-lifecycle agent. Do not edit `lazy.settings.json` by hand — the skill owns that file's `agent_models` section.

---

## Can I author my own aspects and use them with these agents?

Yes. An aspect is a markdown file that adds domain guidance to whichever agent composes it. Nothing in the `lazycortex-experts` runtime restricts aspects to the seven domain aspects (or two cross-cutting aspects) that ship with the plugin. You author an aspect file in your own plugin (or locally), then reference its path in the `aspects` array of your `lazy.settings.json[experts]` entry. The convention is to name the file `<namespace>.<domain>-aspect.md` and place it in your plugin's `references/` directory.

---

## The game-dev-aspect, dotfiles-aspect, obsidian-plugin-aspect, or data-pipeline-aspect doesn't mention the specific engine / tool I use. Is that a problem?

No. All four aspects are deliberately tool-agnostic and domain-neutral in their bodies — neutral on bundler, language, storage, or transport, opinionated only on the conceptual axes their domain always raises (lifecycle hygiene and API boundaries for Obsidian plugins; incremental state and resumability for data pipelines; and the equivalent axes for game-dev and dotfiles). The same is true of `sci-fi-aspect` and `fantasy-aspect` on the subgenre axis (hard SF vs space opera, epic vs urban fantasy). When your brief or request pins a specific engine (Unity, Unreal, Godot), dotfile tool (chezmoi, yadm, stow, Nix home-manager), plugin bundler, sync transport, or subgenre, the specialist honors that pin literally in its output. The aspect body names category-level patterns and obligations; the concrete choices flow from your request.

---

## Where do I ask questions about the expert runtime itself — job dispatch, the daemon, model resolution?

Not here. `lazycortex-experts` ships the generic agents and aspect files you compose into specialists; it ships no dispatcher, no daemon, and no job-queue logic. All of that lives in `lazycortex-core` — the expert runtime that resolves `lazy.settings.json[experts]` entries, dispatches jobs, and runs the daemon that picks up routine-triggered work. Questions about how a job actually gets dispatched, how the daemon schedules routines, or how model tiers resolve at runtime belong in `lazycortex-core`'s own documentation, not here.
