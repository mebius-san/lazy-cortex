---
chapter_type: faq
summary: Common questions about installing lazycortex-experts, composing specialists, understanding the three-agent pipeline, and working with domain aspects.
last_regen: 2026-05-15
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.planner
  - lazy-experts.claude-plugin-aspect
  - lazy-experts.game-dev-aspect
  - lazy-experts.dotfiles-aspect
---
# Frequently asked questions

## Does /lazy-experts.install create my expert entries automatically?

Yes. `/lazy-experts.install` seeds one composed expert entry per (agent × domain-aspect) pair into `lazy.settings.json[experts]`. For the three agents (interpreter, designer, planner) and three domain aspects (claude-plugin, game-dev, dotfiles), that gives you nine entries out of the box — for example, `claude-plugin-designer`, `game-interpreter`, `dotfiles-planner`. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs.

If you need a specialist that doesn't match the cartesian product — say, a custom aspect you authored, or an agent from another plugin — you write that entry yourself in `<repo-root>/.claude/lazy.settings.json` (project scope) or `~/.claude/lazy.settings.json` (global scope). The install skill leaves any hand-authored entries untouched.

---

## Do I need to re-run /lazy-experts.install after a plugin update?

Yes, if the update ships new agent-model tier entries or new domain aspects. `/plugin update` refreshes the plugin cache but does not re-sync your `lazy.settings.json`. Re-run `/lazy-experts.install` to pick up any new `lazycortex-experts:*` entries from `lazycortex-core`'s `default-tiers.json`, and to pick up any new (agent × domain-aspect) pairs that ship in a later release. The skill is idempotent — re-running it is always safe; it only adds absent entries and leaves your customised values in place.

---

## I customised a tier for one of the agents. Will /lazy-experts.install overwrite it?

No. When an entry is already in your `lazy.settings.json` and differs from the upstream default, the skill leaves your value untouched and reports `kept-local` alongside both values so the divergence is visible. If you want to change a tier, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json` and writes the value correctly. Do not hand-edit the file directly.

---

## What is the memory aspect that gets attached to every seeded expert?

Every expert entry seeded by `/lazy-experts.install` includes `lazycortex-core:lazy-memory.persona-aspect` in its `aspects` array. This aspect opts the expert into `lazycortex-core`'s memory subsystem: the expert can accumulate notes about your project, preferences, and prior work under `.memory/<expert-key>/` in the working repo. That memory persists across runs and is loaded back into the expert's context on subsequent dispatches.

If you remove the persona aspect from a seeded entry, the expert stops growing memory — the install skill never re-adds it on re-run, so the removal holds until you add it back manually. Removing it does not delete existing memory files; it just stops the expert from reading or writing them.

---

## The agents don't seem to do anything when I invoke them directly. Why?

The three generic agents — interpreter, designer, and planner — have no inline I/O contract. They wait for a dispatching routine to hand them a protocol document (via a `- protocol: <path>` line in the user-message prompt). Without a protocol, an agent returns an error naming the missing contract. You need a routine on your side (consumer-authored, or a future `lazycortex-specs` integration) that dispatches jobs to these agents along with the appropriate protocol. The agents themselves are building blocks, not standalone commands.

---

## Can I skip the interpreter and dispatch the designer directly?

Yes. Each agent is independently dispatchable. If you already have a well-formed, gap-free brief, you can dispatch the designer directly without running the interpreter first. The three-stage sequence (interpreter → designer → planner) is a convention that produces the best results starting from a vague idea, but it is not enforced — any agent can be dispatched at any point given the right input and a protocol.

---

## What is an aspect and how does it differ from an agent?

An agent is a persona — it defines who the expert is, what its lane is, and what output it produces. An aspect is a pure prompt layer that adds domain knowledge to whichever agent you pair it with. Aspects compose onto agents via the `lazy.settings.json[experts]` entry; the expert runtime merges the aspect bodies into the agent's system prompt at dispatch time. Aspects carry no side-effects and add no new write permissions; they expand what the agent knows without changing where or how it writes its output.

---

## Can I attach more than one aspect to the same agent?

Yes. The `aspects` array in your `lazy.settings.json[experts]` entry accepts any number of aspect references. The expert runtime merges them all into the system prompt in declaration order. When two aspects impose obligations that could conflict, earlier aspects take precedence. For example, a specialist that interprets a config-repo brief for a LazyCortex development machine could combine `dotfiles-aspect` and `claude-plugin-aspect` on the same interpreter entry.

---

## Can I use an aspect from this plugin with an agent from a different plugin?

That depends on the expert runtime's resolution rules, which are governed by `lazycortex-core`. Aspects shipped by `lazycortex-experts` are pure prompt files — nothing in their body is tied to a specific agent namespace. Whether a cross-plugin pairing is valid is determined by how the dispatching routine constructs the `- aspect: <path>` lines in the user-message prompt. Consult your dispatching routine's documentation or `lazycortex-core`'s expert runtime reference for the resolution contract.

---

## How do I verify my install is healthy after running /lazy-experts.install?

Run `/lazy-core.doctor`. There is no plugin-local audit skill for `lazycortex-experts` — health checks for the full LazyCortex setup, including whether the experts' `agent_models` entries are present and well-formed, route through `lazycortex-core`'s doctor.

---

## How do I change which Claude model tier a specific agent uses?

Run `/lazy-core.agent-models`. That skill manages the `agent_models` section of `lazy.settings.json` and writes the entry with the correct shape. The `lazycortex-experts:lazy-experts.<agent>` key under `agent_models.lazycortex` is the entry to update. Do not edit `lazy.settings.json` by hand — the skill owns that file's `agent_models` section.

---

## Can I author my own aspects and use them with these agents?

Yes. An aspect is a markdown file that adds domain guidance to whichever agent composes it. Nothing in the `lazycortex-experts` runtime restricts aspects to the three that ship with the plugin. You author an aspect file in your own plugin (or locally), then reference its path in the `aspects` array of your `lazy.settings.json[experts]` entry. The convention is to name the file `<namespace>.<domain>-aspect.md` and place it in your plugin's `references/` directory.

---

## The game-dev-aspect or dotfiles-aspect doesn't mention the specific engine / tool I use. Is that a problem?

No. Both aspects are deliberately tool-agnostic and domain-neutral in their bodies. When your brief or request pins a specific engine (Unity, Unreal, Godot) or dotfile tool (chezmoi, yadm, stow, Nix home-manager), the specialist honors that pin literally in its output. The aspect body names category-level patterns and obligations; the concrete tool choices flow from your request.
