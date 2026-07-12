---
chapter_type: block
summary: Assign haiku/sonnet/opus tiers to every agent in your vault and let the model-router hook route each dispatch automatically.
last_regen: 2026-07-12
no_diagram: true
source_skills:
  - lazy-core.agent-models
---
# Per-agent model routing

Every `Agent` call in Claude Code spins up a subagent. By default they all run on the same model tier. That is fine for a handful of agents, but a vault with dozens — distill workers, diagram drawers, log taggers, expert-job processors — burns opus-level budget on work a haiku model handles just as well.

This block gives you two things: an interactive wizard that assigns each agent a tier once, and a runtime hook that enforces those assignments automatically on every subsequent dispatch. Run `/lazy-core.agent-models`, walk through the batched prompts, and from that point on every `Agent` call gets the right model without per-call flags or per-session reminders.

## When you'd use this

- After a fresh install, when `/lazy-core.audit` reports that `agent_models` entries are missing for discovered agents.
- After installing a new plugin that ships additional agents.
- After authoring a new project-local agent in `.claude/agents/`.
- When you want a project-specific model tier that overrides your global default for a particular agent.
- When previewing what routing entries would be written before committing to them.
- When running `/lazy-core.optimize` end-to-end — Phase 7 of that skill delegates to this wizard automatically.
- After an automated rollout leaves some agents unrouted — a run driven by `lazy-core.autosetup` only fills in curated defaults and reports the rest as needing your attention; run this wizard yourself to finish them.

## How it fits together

Run `/lazy-core.agent-models`. The skill loads the `agent_models` sections from both your global `~/.claude/lazy.settings.json` and the project `./.claude/lazy.settings.json`, merges them into a single lookup, and discovers every dispatchable agent across your vault — Claude Code built-ins (`Explore`, `Plan`, `general-purpose`, `statusline-setup`), globally-authored agents under `~/.claude/agents/`, project-local agents under `./.claude/agents/`, and plugin-shipped agents from the plugin cache. Any agent whose dispatch string already appears in the merged lookup — including those explicitly set to `default` — is considered decided and stays out of the wizard.

The remaining agents surface in three ordered batches. The first covers built-ins and agents from LazyCortex plugins that ship a curated tier table. For these the wizard already knows the right tier: `Explore` routes to haiku (fast, cheap navigation), `Plan` to opus (deliberate multi-step reasoning), review dispatchers and log taggers to haiku, and synthesis agents to sonnet. The second batch covers any other plugin agents not in the curated table. The third covers your own project agents. Each batch is a single prompt: accept all suggestions, review each agent individually, mass-set the whole batch to `default`, or skip it for now.

Accepting a batch records every entry as planned. Reviewing routes those agents into a per-agent prompt where you can accept the suggestion, pick a neighboring tier, fall back to `default`, or skip. For agents outside the curated table the wizard applies a heuristic: names containing `log`, `distill`, `tag`, or `timeline` land on haiku; names hinting at review, audit, or planning land on opus; everything else lands on sonnet.

After the prompts, the skill writes each entry to its structurally correct file. `_user.*` agents land in the global settings file (those agents live in `~/.claude/agents/`, so their tiers belong globally). `_project.*` agents land in the project settings file. Built-ins land in the global file because they are identical across every repo. Plugin agents follow the plugin's install scope. Pass `--scope=project` to force every entry into the project file — useful for repo-specific overrides — or `--scope=global` to bulk-promote decisions to your global settings.

One override cuts across all of that: if an agent is dispatchable by the runtime daemon — it is wired as an expert's `agent` in `lazy.settings.json`, or it is the built-in doctor dispatch — its entry always lands in the project settings file, regardless of group or `--scope`. The daemon reads `agent_models` from project scope only, so a globally-routed entry would be invisible to headless dispatches; the wizard writes where the stricter resolver actually looks, and flags the affected entries in the batch prompt so you know why they are routed that way.

The `lazy-core.model-router` PreToolUse hook is the runtime counterpart. It fires before every `Agent` dispatch, reads the `agent_models` section, matches the dispatch string, and injects the configured tier silently. Agents with no entry, or entries set to `default`, fall through to Claude Code's built-in model default. No restart is needed after the wizard writes new entries — the hook picks them up on the next dispatch.

When this wizard runs without you at the keyboard — for example when `lazy-core.autosetup` is bringing a repo's whole install chain current across a cross-project rollout — only the first batch gets applied. Its curated tiers come from a plugin-shipped table, not a guess, so they are written immediately without a prompt. The second and third batches have no curated tier to fall back on, so nothing is written for them; they are reported as needing interactive attention and reappear the next time you run `/lazy-core.agent-models` yourself, exactly as if the automated run had never touched them.

## Common adjustments

**Preview before writing.** Run `/lazy-core.agent-models --dry-run` to see exactly which entries would be written and to which file, without making any changes.

**Project-specific overrides.** If your global config sets `general-purpose` to `sonnet` but this repo's general-purpose work is lightweight, run `/lazy-core.agent-models --scope=project`. The project entry takes precedence over the global one without touching the global setting.

**After adding new agents.** The wizard is idempotent — running it again on a fully-configured vault reports "nothing to do". Run it freely after installing a new plugin or authoring a new agent; only the new agents surface.

**Changing an existing tier.** `/lazy-core.agent-models` never overwrites existing entries; it only adds missing ones. To override a tier that is already set globally, run `/lazy-core.agent-models --scope=project` — the project entry shadows the global one. To remove that project-level override and fall back to the global tier, delete the entry from `./.claude/lazy.settings.json` via `/lazy-core.optimize` Phase 7, which re-prompts for any entries that go missing after cleanup.

**Relationship to install.** `/lazy-core.install` seeds `_builtin` defaults at install time non-interactively. `/lazy-core.agent-models` fills the remaining per-agent entries across all discovered sources interactively. They do not overlap — install handles the bootstrap, this wizard handles everything discovered afterwards.

**After an automated rollout.** If a repo was brought current by `lazy-core.autosetup` rather than by you running the install chain by hand, expect only the curated-default agents to already have tiers. Run `/lazy-core.agent-models` yourself afterward to finish routing the rest — it picks up exactly where the automated run left off.

## Failure modes

**`/lazy-core.agent-models` fails immediately: "invalid --scope value".** An unrecognised flag or token was passed. Only `--scope=auto`, `--scope=project`, `--scope=global`, and `--dry-run` are accepted. Re-run with a valid flag.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap lazycortex-core and verify your configuration baseline before setting up model routing.
</content>
