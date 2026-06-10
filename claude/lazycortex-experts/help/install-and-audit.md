---
chapter_type: block
summary: Bootstrap lazycortex-experts by seeding agent-model tiers and composed expert entries for all agent × domain-aspect pairs into lazy.settings.json.
last_regen: 2026-06-10
no_diagram: true
source_skills:
  - lazy-experts.install
---
# Installing lazycortex-experts

`lazycortex-experts` ships three generic doc-producing agents — interpreter, designer, and planner — and three domain aspects that layer expertise onto those agents. Before the expert runtime in `lazycortex-core` can route jobs to them, two things must land in your `lazy.settings.json`: the agent-model tier for each generic agent (so dispatch knows which Claude tier to use), and a composed expert entry for every agent × domain-aspect combination (so each specialist is addressable by name with the right aspect stack). `/lazy-experts.install` handles both in a single idempotent run.

Health checks after install route through `/lazy-core.doctor`, not through a plugin-local audit skill.

## When you'd use this

- You've just enabled `lazycortex-experts` from the marketplace and want the three generic agents and all nine pre-composed experts ready to use.
- You've updated the plugin and a new release shipped additional domain aspects or revised tier entries — re-running picks up everything new without disturbing your existing config.
- You're setting up a fresh project-scoped environment and want agent-model tiers and expert entries isolated from your global config.
- You added a new agent or domain aspect to the plugin cache and want the cartesian-product entries seeded without writing them by hand.

## How it fits together

Run `/lazy-experts.install`. The skill first checks that `lazycortex-experts@lazycortex` appears in your Claude Code installed-plugins list — if it's missing, it stops and tells you exactly what to add to `enabledPlugins` before re-running.

Next, it detects whether the plugin is installed at project scope or user (global) scope, then targets the matching `lazy.settings.json` — `<repo-root>/.claude/lazy.settings.json` for project-scoped installs, `~/.claude/lazy.settings.json` for global. If both scopes appear, it targets project scope without asking.

**Seeding agent-model tiers.** The skill locates the `default-tiers.json` file that `lazycortex-core` caches locally and selects every entry whose key starts with `lazycortex-experts:` — the three entries for interpreter, designer, and planner. For each one it compares what's already in your `lazy.settings.json`:

- If the entry is **absent**, it adds it.
- If the entry is **already there and identical**, it leaves it untouched.
- If the entry is **different from the default** (meaning you've customised it), it leaves your value in place and reports `kept-local` so you can see the divergence.

If `lazycortex-core` isn't installed at all — meaning the defaults file can't be found — the skill fails immediately rather than falling back to hardcoded values. Install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

**Seeding composed experts.** On a fresh project with an empty `experts` section, the skill asks which domain aspects (classes) to register. Pick the domains your project works in — you can re-run later to extend coverage. The skill then takes the cartesian product of those classes with every available role (interpreter, designer, planner) and writes one entry per pair. Each entry names the agent, stacks the domain aspect, and automatically includes `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs under `.memory/<expert-key>/`. Example entry:

```jsonc
"claude-plugin-designer": {
  "agent": "lazycortex-experts:lazy-experts.designer",
  "aspects": [
    "lazycortex-experts:lazy-experts.claude-plugin-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "Claude Plugin Designer",
    "email": "claude-plugin-designer@lazycortex.local"
  }
}
```

On a re-run against a project that already has expert entries, the skill never re-asks which classes to register. Instead it inspects the aspects already present in your `experts` section, derives the class set from those refs, and completes any missing (role × class) pairs for exactly those classes — nothing more. Expert entries are only written when absent; any entry you've customised by hand is left untouched.

After both seeding passes, the skill reads the file back to confirm all entries are present and parseable, then logs the run.

## Common adjustments

**Re-running after a plugin update.** `/plugin update` refreshes the plugin cache but does not re-sync settings. If a new release of `lazycortex-experts` ships additional domain aspects or revised `lazycortex-experts:*` tier entries in `default-tiers.json`, re-run `/lazy-experts.install` to pick them up. The cartesian product re-runs and adds any new (agent × aspect) pairs; existing entries are left alone.

**Adding a new class to an existing project.** Because the skill derives its class set from your current `experts` entries, it won't add a class you haven't registered yet. To introduce a new domain, add one expert of the new class by hand (any role will do — e.g. add `game-designer` with the `game-dev` aspect), then re-run `/lazy-experts.install`. The skill derives the expanded class set and fills in the remaining roles for the new class.

**Changing a tier after install.** If you want a different Claude tier for one of the three agents than the default provides, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json`. `/lazy-experts.install` will then report `kept-local` on subsequent runs so your customisation is visible.

**Customising a composed expert.** If you want to add or remove aspects from a seeded expert, edit it via whatever skill manages `lazy.settings.json[experts]` in your workflow — `/lazy-experts.install` will not overwrite hand-authored or hand-modified entries on re-run.

**Removing the memory side-effect.** Every seeded expert carries `lazycortex-core:lazy-memory.persona-aspect`. Removing that aspect from an entry stops the expert from writing to `.memory/<self>/`, and the install skill will not re-add it on subsequent runs.

**Verifying the install.** Run `/lazy-core.doctor` to check the health of your full LazyCortex setup, including whether the experts' agent-model entries and composed expert entries are present and well-formed.
