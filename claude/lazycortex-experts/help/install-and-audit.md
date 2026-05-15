---
chapter_type: block
summary: Bootstrap lazycortex-experts in your project by seeding agent-model tiers for the three generic experts from lazycortex-core's defaults.
last_regen: 2026-05-15
no_diagram: true
source_skills:
  - lazy-experts.install
---
# Installing lazycortex-experts

`lazycortex-experts` ships three generic doc-producing agents — interpreter, designer, and planner — that the expert runtime in `lazycortex-core` dispatches as queued jobs. Before the runtime can route jobs to these agents, it needs to know which Claude tier to use for each one. `/lazy-experts.install` handles that: it reads the tier defaults that `lazycortex-core` ships and writes the relevant entries into your `lazy.settings.json`. That's the entire install surface for this plugin — no rules to sync, no expert entries to seed (composition is yours to define).

Health checks after install route through `/lazy-core.doctor`, not through a plugin-local audit skill.

## When you'd use this

- You've just enabled `lazycortex-experts` from the marketplace and want the three generic agents ready to dispatch jobs.
- You've updated the plugin and the upstream defaults shipped new or revised tier entries that you want to pick up.
- You're setting up a fresh project-scoped environment and want agent-model tiers isolated from your global config.

## How it fits together

Run `/lazy-experts.install`. The skill first checks that `lazycortex-experts@lazycortex` appears in your Claude Code installed-plugins list — if it's missing, it stops and tells you exactly what to add to `enabledPlugins` before re-running.

Next, it detects whether the plugin is installed at project scope or user (global) scope, then targets the matching `lazy.settings.json` — `<repo-root>/.claude/lazy.settings.json` for project-scoped installs, `~/.claude/lazy.settings.json` for global. If both scopes appear, it asks which one to target.

It then locates the `default-tiers.json` file that `lazycortex-core` caches locally and selects every entry whose key starts with `lazycortex-experts:` — the three entries for interpreter, designer, and planner. For each one it compares what's already in your `lazy.settings.json`:

- If the entry is **absent**, it adds it.
- If the entry is **already there and identical**, it leaves it untouched.
- If the entry is **different from the default** (meaning you've customised it), it leaves your value in place and reports `kept-local` so you can see the divergence.

After writing, it reads the file back to confirm all three entries are present and parseable, then logs the run.

If `lazycortex-core` isn't installed at all — meaning the defaults file can't be found — the skill fails immediately rather than falling back to hardcoded values. Install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

## Common adjustments

**Re-running after a plugin update.** `/plugin update` refreshes the plugin cache but does not re-sync settings. If a new release of `lazycortex-experts` ships additional or revised `lazycortex-experts:*` tier entries in `default-tiers.json`, re-run `/lazy-experts.install` to pick them up.

**Changing a tier after install.** If you want a different Claude tier for one of the three agents than the default provides, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json`. `/lazy-experts.install` will then report `kept-local` on subsequent runs so your customisation is visible.

**Verifying the install.** Run `/lazy-core.doctor` to check the health of your full LazyCortex setup, including whether the experts' agent-model entries are present and well-formed.
