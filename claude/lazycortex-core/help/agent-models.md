---
chapter_type: block
summary: Assign model tiers to every agent, prune dead entries, and register non-Anthropic provider endpoints for expert jobs to spawn against.
last_regen: 2026-09-07
no_diagram: true
source_skills:
  - lazy-core.agent-models
  - lazy-core.agent-models-seed
  - lazy-core.providers
source_sha: 897f6d87fe9edd5d16025ec6ce485db31ca56f03
---
# Per-agent model routing

Every `Agent` call in Claude Code spins up a subagent. By default they all run on the same model tier. That is fine for a handful of agents, but a vault with dozens — distill workers, diagram drawers, log taggers, expert-job processors — burns opus-level budget on work a haiku model handles just as well.

This block gives you two things: an interactive wizard that assigns each agent a tier once, and a runtime hook that enforces those assignments automatically on every subsequent dispatch. Run `/lazy-core.agent-models`, walk through the batched prompts, and from that point on every `Agent` call gets the right model without per-call flags or per-session reminders.

A related registry sits next to the wizard. `/lazy-core.providers` manages named LLM endpoints — a base URL, a credential variable name, and the same four-tier (fable/opus/sonnet/haiku) model map the wizard assigns per-agent — that an expert job can spawn against instead of Anthropic. Because an endpoint and its credential name are machine facts rather than a shared team decision, the registry lives only in the gitignored `.claude/lazy.settings.local.json`, never in the tracked settings file the wizard writes to.

## When you'd use this

- After a fresh install, when `/lazy-core.audit` reports that `agent_models` entries are missing for discovered agents.
- After installing a new LazyCortex plugin — most of its shipped agents are pre-seeded with curated tiers automatically at install time (every plugin's install runs the same shared seeding step behind the scenes), so this wizard only needs to cover the rest.
- After authoring a new project-local agent in `.claude/agents/`.
- When you want a project-specific model tier that overrides your global default for a particular agent.
- When previewing what routing entries would be written before committing to them.
- When running `/lazy-core.slim-context` end-to-end — Phase 7 of that skill delegates to this wizard automatically.
- After an automated rollout leaves some agents unrouted — a run driven by `lazy-core.autosetup` only fills in curated defaults and reports the rest as needing your attention; run this wizard yourself to finish them.
- After removing a plugin or an agent it shipped — the next run cleans up that agent's now-dead tier for you.
- When an expert job needs to spawn against a different LLM endpoint than Anthropic — register it with `/lazy-core.providers add <name>` and point the expert's own `provider` field at it.

## How it fits together

Run `/lazy-core.agent-models`. The skill loads the `agent_models` sections from both your global `~/.claude/lazy.settings.json` and the project `./.claude/lazy.settings.json`, merges them into a single lookup, and discovers every dispatchable agent across your vault — Claude Code built-ins (`Explore`, `Plan`, `general-purpose`, `statusline-setup`), globally-authored agents under `~/.claude/agents/`, project-local agents under `./.claude/agents/`, and plugin-shipped agents from the plugin cache. Any agent whose dispatch string already appears in the merged lookup — including those explicitly set to `default` — is considered decided and stays out of the wizard.

Plugin-shipped agents are filtered by install scope before they ever reach the missing list. The plugin cache on your machine is shared across every project, so the wizard only counts an agent from a plugin installed at user (global) scope, or installed at project scope for this exact repo. An agent belonging to a plugin some other project installed locally never surfaces here — so it can't get stuck popping up as "needs interactive" in every unrelated repo you happen to run this wizard in.

The remaining agents surface in three ordered batches. The first covers built-ins and agents from LazyCortex plugins that ship a curated tier table. For these the wizard already knows the right tier: `Explore` routes to haiku (fast, cheap navigation), `Plan` to opus (deliberate multi-step reasoning), review dispatchers and log taggers to haiku, and synthesis agents to sonnet. The second batch covers any other plugin agents not in the curated table. The third batch covers your own project agents. Each batch is a single prompt: accept all suggestions, review each agent individually, mass-set the whole batch to `default`, or skip it for now.

Accepting a batch records every entry as planned. Reviewing routes those agents into a per-agent prompt where you can accept the suggestion, pick a neighboring tier, fall back to `default`, or skip. For agents outside the curated table the wizard applies a heuristic: names containing `log`, `distill`, `tag`, or `timeline` land on haiku; names hinting at review, audit, or planning land on opus; everything else lands on sonnet.

After the prompts, the skill writes each entry to its structurally correct file. `_user.*` agents land in the global settings file (those agents live in `~/.claude/agents/`, so their tiers belong globally). `_project.*` agents land in the project settings file. Built-ins land in the global file because they are identical across every repo. Plugin agents follow the plugin's install scope. Pass `--scope=project` to force every entry into the project file — useful for repo-specific overrides — or `--scope=global` to bulk-promote decisions to your global settings.

One override cuts across all of that: if an agent is dispatchable by the runtime daemon — it is wired as an expert's `agent` in `lazy.settings.json`, or it is the built-in doctor dispatch — its entry always lands in the project settings file, regardless of group or `--scope`. The daemon reads `agent_models` from project scope only, so a globally-routed entry would be invisible to headless dispatches; the wizard writes where the stricter resolver actually looks, and flags the affected entries in the batch prompt so you know why they are routed that way.

Before writing anything new, the wizard also prunes stale tiers. If a plugin-namespaced entry (`<plugin>:<agent>`) still sits in either settings file but the plugin no longer ships that agent — you updated the plugin and it dropped an agent, or removed one yourself — the wizard deletes the dead entry automatically, in both interactive and unattended runs. No prompt, no confirmation: a tier for an agent that provably doesn't exist anymore is dead config, not a decision you made. The only thing the wizard won't touch on its own is an expert in `lazy.settings.json` still pointing its `agent` field at that removed dispatch — that comes back as a warning in the report instead, so you can fix the expert config yourself.

The `lazy-core.model-router` PreToolUse hook is the runtime counterpart. It fires before every `Agent` dispatch, reads the `agent_models` section, matches the dispatch string, and injects the configured tier silently. Agents with no entry, or entries set to `default`, fall through to Claude Code's built-in model default. No restart is needed after the wizard writes new entries — the hook picks them up on the next dispatch.

When this wizard runs without you at the keyboard — for example when `lazy-core.autosetup` is bringing a repo's whole install chain current across a cross-project rollout — only the first batch gets applied. Its curated tiers come from a plugin-shipped table, not a guess, so they are written immediately without a prompt. The second and third batches have no curated tier to fall back on, so nothing is written for them; they are reported as needing interactive attention and reappear the next time you run `/lazy-core.agent-models` yourself, exactly as if the automated run had never touched them. The stale-tier prune runs regardless of who is driving — it is mechanical either way.

## The provider registry

`/lazy-core.providers` manages the `providers` block in `.claude/lazy.settings.local.json` — a set of named LLM endpoints an expert job's `provider` field can point at instead of the default Anthropic dispatch. Each entry records a `base_url`, a `token_env` (the name of the environment variable holding the credential — never the credential itself), and a model name for each of the four tiers (`fable`, `opus`, `sonnet`, `haiku`).

Run `/lazy-core.providers` (or `/lazy-core.providers list`) to see every registered endpoint, its base URL, its token variable name, and whether it came from the local overlay or — flagged as a warning — was hand-written into the tracked settings file, where a machine-local fact doesn't belong. `/lazy-core.providers add <name>` walks you through the fields one at a time; `/lazy-core.providers update <name>` re-asks the same fields pre-filled with the current values; `/lazy-core.providers remove <name>` deletes an entry, warning you first if any expert's `provider` field still points at it.

Before writing anything, the skill validates the candidate entry against the same checks the runtime's own dispatch-time resolver enforces, so a broken entry can never slip through: the four tiers must all be present and none may hold a bare `claude-*` model name (which cannot pass through a foreign endpoint or the local proxy), the `openai` provider's tiers must carry the `rt-openai/` prefix, the token variable must actually resolve from your environment or `~/.claude/.env`, and the endpoint itself is probed live — a `curl` against `<base_url>/v1/models` with the resolved token must return `200` before the entry is written. The token value itself never appears in a tool-call transcript; only a presence verdict does.

Assigning a provider to a specific expert is a separate, content-level decision made on that expert's own `provider` field in `lazy.settings.json` — out of scope for this skill, which owns only the registry of available endpoints.

## Common adjustments

**Preview before writing.** Run `/lazy-core.agent-models --dry-run` to see exactly which entries would be written and to which file, without making any changes.

**Project-specific overrides.** If your global config sets `general-purpose` to `sonnet` but this repo's general-purpose work is lightweight, run `/lazy-core.agent-models --scope=project`. The project entry takes precedence over the global one without touching the global setting.

**After adding new agents.** The wizard is idempotent — running it again on a fully-configured vault reports "nothing to do". Run it freely after installing a new plugin or authoring a new agent; only the new agents surface.

**Changing an existing tier.** `/lazy-core.agent-models` never overwrites existing entries; it only adds missing ones. To override a tier that is already set globally, run `/lazy-core.agent-models --scope=project` — the project entry shadows the global one. To remove that project-level override and fall back to the global tier, delete the entry from `./.claude/lazy.settings.json` via `/lazy-core.slim-context` Phase 7, which re-prompts for any entries that go missing after cleanup.

**Relationship to install.** Every plugin's own install skill pre-seeds curated tiers for the agents it ships, through the same shared seeding step every LazyCortex plugin install calls — it reads the identical curated-tiers table this wizard uses, so a tier never drifts between the two paths. An entry already seeded that way, or one already set to `default`, doesn't reappear in the wizard's missing list. `/lazy-core.agent-models` fills the remaining per-agent entries — anything not curated, plus your own project agents — across all discovered sources interactively. They do not overlap — install handles the bootstrap, this wizard handles everything discovered afterwards.

**After an automated rollout.** If a repo was brought current by `lazy-core.autosetup` rather than by you running the install chain by hand, expect only the curated-default agents to already have tiers. Run `/lazy-core.agent-models` yourself afterward to finish routing the rest — it picks up exactly where the automated run left off.

**After removing a plugin agent.** Nothing to do by hand — the next run of `/lazy-core.agent-models` prunes that agent's now-dead tier automatically and lists it in the report as pruned. If the report also warns that an expert still references the removed agent, update that expert's `agent` field yourself; the wizard reports the warning but will not edit your expert config.

**Working across multiple projects.** If the same plugin is installed project-locally in more than one repo, its agents only surface in the wizard for the repo where that install happened — the install-scope filter keeps a project-scoped plugin's agents from bleeding into an unrelated repo's wizard run. Installing the plugin at user (global) scope instead makes its agents visible everywhere in one pass.

**Registering a new provider endpoint.** Run `/lazy-core.providers add <name>` and answer the base URL, token variable name, and the four tier model names when prompted. The skill refuses to write anything until the structural checks, the token-presence check, and a live `/v1/models` probe all pass.

**Removing a provider no longer in use.** Run `/lazy-core.providers remove <name>`. If any expert's `provider` field still names it, the skill lists those experts before you confirm — the removal itself still proceeds on confirmation, but you'll want to repoint those experts afterward.

## Failure modes

**`/lazy-core.agent-models` fails immediately: "invalid --scope value".** An unrecognised flag or token was passed. Only `--scope=auto`, `--scope=project`, `--scope=global`, and `--dry-run` are accepted. Re-run with a valid flag.

**`/lazy-core.providers` fails: "provider `<name>` is not registered".** `remove` or `update` named a provider that isn't in the merged registry. Run `/lazy-core.providers list` to see the actual names.

**`/lazy-core.providers` fails validation on add/update.** A `claude-*` literal in one of the four tiers, a missing tier, an `openai` provider tier missing the `rt-openai/` prefix, a token variable that can't be found in your environment or `~/.claude/.env`, or an endpoint that doesn't answer `<base_url>/v1/models` with `200` — each aborts the write with the specific check that failed, before anything is saved. Fix the named field and re-run.

**`/lazy-core.providers` refuses to write: "`.claude/lazy.settings.local.json` is not gitignored".** The local overlay path was removed from `.gitignore`. Restore the entry before the skill will write provider entries — it never writes machine-local endpoint facts into a path git would track.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap lazycortex-core and verify your configuration baseline before setting up model routing.
