---
chapter_type: block
summary: Assign haiku/sonnet/opus tiers to every agent in your vault and let the model-router hook route each dispatch automatically.
last_regen: 2026-05-06
no_diagram: true
source_skills:
  - lazy-core.agent-models
---
# Per-agent model routing

Every `Agent` call in Claude Code spins up a subagent. By default they all run on the same model tier. That's fine for a handful of agents, but a vault with dozens — distill workers, diagram drawers, log taggers, expert-job processors — burns opus-level budget on work a haiku model handles just as well.

This block lets you declare, once, which tier each agent deserves. Run `/lazy-core.agent-models` and a batched wizard walks you through every agent that doesn't yet have a routing entry. Curated defaults are suggested automatically; you accept, adjust, or skip in bulk. Once the entries are written, the `lazy-core.model-router` PreToolUse hook intercepts every `Agent` dispatch and silently injects the right model — no per-call flags, no per-session reminders.

## What's in this block

**`lazy-core.agent-models`** owns the interactive setup half of the routing system. It discovers every dispatchable agent across your vault — Claude Code built-ins, globally-authored agents, project-local agents, and plugin-shipped agents — compares that list against existing `agent_models` entries in `lazy.settings.json`, and presents only the gaps. A three-batch structure keeps the session short: curated LazyCortex agents with pre-baked tier suggestions first, then any third-party plugin agents, then your project's own agents. You answer once per batch; the skill writes each entry to whichever settings file owns that scope.

The `lazy-core.model-router` PreToolUse hook is the runtime half. It fires before every `Agent` call, reads the `agent_models` section, matches the dispatch string, and injects the configured tier into the call. It runs silently — you dispatch agents exactly as before. Agents with no entry, or entries set to `default`, fall through to Claude Code's own model default.

## How they work together

You run `/lazy-core.agent-models` after a fresh install or after adding new agents. The skill loads the current `agent_models` sections from both your global `~/.claude/lazy.settings.json` and the project `./.claude/lazy.settings.json`, then merges them into a single lookup. Any agent whose dispatch string already appears in that lookup — including entries explicitly set to `default` — is considered decided and stays out of the wizard.

The remaining agents surface in three ordered batches. For built-ins and LazyCortex plugin agents, suggested tiers come from a built-in tier table: `Explore` → haiku, `Plan` → opus, log distillers → haiku, and so on. For your own agents, the wizard falls back to a description heuristic and lets you confirm or override. Each batch is a single `AskUserQuestion`: accept all suggestions, review each agent individually, mass-set the batch to `default`, or skip it for now.

When you accept, the skill routes each entry to its structurally correct file. `_user.*` agents (authored globally in `~/.claude/agents/`) land in the global settings file; `_project.*` agents (in `./.claude/agents/`) land in the project file; built-ins land in the global file because they're identical across every repo. Plugin agents follow the plugin's own install scope. You can override all of this with `--scope=project` to force every entry into the project file — useful when you want project-specific tier overrides that take precedence over your global defaults.

After the write, `lazy-core.model-router` picks up the new entries immediately on the next `Agent` dispatch. No restart needed.

## Common adjustments

**Preview before writing.** Run `/lazy-core.agent-models --dry-run` to see exactly which entries would be written and to which file, without making any changes.

**Project-specific overrides.** If your global config sets `general-purpose` to `sonnet` but this repo's general-purpose work is lightweight, run `/lazy-core.agent-models --scope=project`. The project entry takes precedence over the global one.

**After adding new agents.** The wizard is idempotent — running it again on a fully-configured vault reports "nothing to do". Run it freely after installing a new plugin or authoring a new agent.

**Changing an existing tier.** `/lazy-core.agent-models` never overwrites existing entries; it only adds missing ones. To change a tier already set, run `/lazy-core.agent-models --scope=project` for a project-level override, or edit the entry directly via `/lazy-core.optimize` Phase 7, which re-prompts for any newly-missing entries.

## Where this fits

The routing system assumes `lazy-core.install` has already run — install seeds `_builtin` defaults non-interactively, while this skill fills in every other discovered agent via the interactive wizard. If `/lazy-core.audit` reports missing `agent_models` entries, this is the direct fix. `/lazy-core.optimize` Phase 7 delegates here automatically when it reaches the model-routing step, so running the full optimizer end-to-end covers both optimization passes and model-tier setup in one session.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap lazycortex-core and verify your configuration baseline before setting up model routing.
