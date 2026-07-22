---
chapter_type: block
summary: Bootstrap lazycortex-experts by seeding agent-model tiers and class-mapped composed expert entries into lazy.settings.json.
last_regen: 2026-07-22
no_diagram: true
source_skills:
  - lazy-experts.install
---
# Installing lazycortex-experts

`lazycortex-experts` ships eight generic agents spanning the full development lifecycle plus fiction — interpreter, designer, planner, implementer, debugger, reviewer, tester, and fiction-writer — plus a set of domain aspects and two cross-cutting aspects (discipline, tech-writing) that compose expertise onto those agents. Before the expert runtime in `lazycortex-core` can route jobs to them, two things must land in your `lazy.settings.json`: the agent-model tier for each generic agent (so dispatch knows which Claude tier to use), and a composed expert entry for every class × role pair the class map prescribes (so each specialist is addressable by name with the right aspect stack). `/lazy-experts.install` handles both in a single idempotent run.

Health checks after install route through `/lazy-core.doctor`, not through a plugin-local audit skill.

## When you'd use this

- You've just enabled `lazycortex-experts` from the marketplace and want your chosen domain classes fully composed and ready to use.
- You've updated the plugin and a new release shipped additional domain aspects, revised tier entries, or a new role agent — re-running picks up everything new without disturbing your existing config.
- You're setting up a fresh project-scoped environment and want agent-model tiers and expert entries isolated from your global config.
- You added a new agent or domain aspect to the plugin cache and want the class-map entries seeded without writing them by hand.

## How it fits together

Run `/lazy-experts.install`. The skill first checks that `lazycortex-experts@lazycortex` appears in your Claude Code installed-plugins list — if it's missing, it stops and tells you exactly what to add to `enabledPlugins` before re-running.

Next, it detects whether the plugin is installed at project scope or user (global) scope, then targets the matching `lazy.settings.json` — `<repo-root>/.claude/lazy.settings.json` for project-scoped installs, `~/.claude/lazy.settings.json` for global. If both scopes appear, it targets project scope without asking.

**Seeding agent-model tiers.** The skill locates the `default-tiers.json` file that `lazycortex-core` caches locally and selects every entry whose key starts with `lazycortex-experts:` — one entry per generic agent (interpreter, designer, planner, implementer, debugger, reviewer, tester, fiction-writer). For each one it compares what's already in your `lazy.settings.json`:

- If the entry is **absent**, it adds it.
- If the entry is **already there and identical**, it leaves it untouched.
- If the entry is **different from the default** (meaning you've customised it), it leaves your value in place and reports `kept-local` so you can see the divergence.

If `lazycortex-core` isn't installed at all — meaning the defaults file can't be found — the skill fails immediately rather than falling back to hardcoded values. Install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

**Seeding composed experts follows a class map.** On a fresh project with no domain-class experts yet, the skill asks which domain classes to register — the options are the domain aspects the plugin ships: `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `sci-fi`, `fantasy`. What each class seeds depends on its kind:

- **Technical classes** (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`) seed all seven engineering roles — interpreter, designer, planner, implementer, debugger, reviewer, tester. Each entry stacks the domain aspect plus two cross-cutting aspects: `lazycortex-experts:lazy-experts.discipline-aspect` (execution discipline) and `lazycortex-experts:lazy-experts.tech-writing-aspect` (documentation rigor).
- **Fiction classes** (`sci-fi`, `fantasy`) seed only `fiction-writer`. Each entry stacks the domain aspect plus `lazycortex-experts:lazy-experts.discipline-aspect` only — the tech-writing aspect is never added to a fiction expert, since its rules would contradict literary craft.

Every seeded entry, technical or fiction, also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs under `.memory/<expert-key>/`. Example technical entry:

```jsonc
"claude-plugin.designer": {
  "agent": "lazycortex-experts:lazy-experts.designer",
  "aspects": [
    "lazycortex-experts:lazy-experts.claude-plugin-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-experts:lazy-experts.tech-writing-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "Claude Plugin Designer",
    "email": "claude-plugin.designer@lazycortex.local"
  }
}
```

And the corresponding fiction entry — note there's no role choice (fiction classes only ever seed `fiction-writer`) and no tech-writing aspect:

```jsonc
"sci-fi.fiction-writer": {
  "agent": "lazycortex-experts:lazy-experts.fiction-writer",
  "aspects": [
    "lazycortex-experts:lazy-experts.sci-fi-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "Sci Fi Fiction Writer",
    "email": "sci-fi.fiction-writer@lazycortex.local"
  }
}
```

On a re-run against a project that already has domain-class expert entries, the skill never re-asks which classes to register. Instead it inspects the aspects already present in your `experts` section and derives the class set from those refs — excluding the cross-cutting aspects (`discipline`, `tech-writing`) and any system experts seeded by sibling plugins from that derivation, since neither is a class in its own right. It then completes any missing (class × role) pairs the class map prescribes for exactly those classes — nothing more. Expert entries are only written when absent; any entry you've customised by hand is left untouched.

**Checking system-expert completeness.** Separately from the classes you compose yourself, several sibling plugins register their own "system experts" the same way — `lazycortex-core`'s `lazy-runtime.doctor`, `lazycortex-review`'s `review.doc_doctor` and `review.historian`, `lazycortex-specs`'s `spec.request-router`, `lazycortex-wiki`'s `wiki.curator`. `/lazy-experts.install` never seeds these itself (the owning plugin's own install does), but for every one of those plugins that's enabled in your project, it checks whether the expected expert key is present and reports any that are missing, pointing you at the sibling plugin's own install skill to fill the gap.

After both seeding passes, the skill reads the file back to confirm every entry is present and parseable. For each seeded expert it also verifies the `agent` ref resolves to an actual agent file in the plugin cache — catching a stale or mistyped agent reference before you ever dispatch a job against it — then logs the run.

## Common adjustments

**Re-running after a plugin update.** `/plugin update` refreshes the plugin cache but does not re-sync settings. If a new release of `lazycortex-experts` ships additional domain aspects, revised `lazycortex-experts:*` tier entries in `default-tiers.json`, or a new role agent, re-run `/lazy-experts.install` to pick them up. The class map re-runs and adds any new (class × role) pairs it prescribes for your existing classes; existing entries are left alone.

**Adding a new class to an existing project.** Because the skill derives its class set from your current domain-class `experts` entries, it won't add a class you haven't registered yet. To introduce a new domain, add one expert of the new class by hand (for a technical class, any of the seven roles will do; for a fiction class it must be `fiction-writer` — that's the only role the class map seeds), then re-run `/lazy-experts.install`. The skill derives the expanded class set and fills in the remaining entries the class map prescribes for the new class.

**Changing a tier after install.** If you want a different Claude tier for one of the agents than the default provides, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json`. `/lazy-experts.install` will then report `kept-local` on subsequent runs so your customisation is visible.

**Customising a composed expert.** If you want to add or remove aspects from a seeded expert, edit it via whatever skill manages `lazy.settings.json[experts]` in your workflow — `/lazy-experts.install` will not overwrite hand-authored or hand-modified entries on re-run.

**Removing the discipline or memory side-effect.** Every seeded expert carries `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-core:lazy-memory.persona-aspect`. Removing the discipline aspect from an entry stops that expert from loading the cross-cutting execution rules. Removing the persona aspect stops the expert from writing to `.memory/<self>/`. The install skill will not re-add either on subsequent runs.

**A sibling plugin's system expert is reported missing.** This isn't something `/lazy-experts.install` fixes — it only detects the gap. Run the owning plugin's own install skill instead: `/lazy-core.install` for `lazy-runtime.doctor`, `/lazy-review.install` for `review.doc_doctor` / `review.historian`, `/spec.install` for `spec.request-router`, `/lazy-wiki.install` for `wiki.curator`.

**Verifying the install.** Run `/lazy-core.doctor` to check the health of your full LazyCortex setup, including whether the experts' agent-model entries and composed expert entries are present, well-formed, and pointing at agent files that actually exist.
