---
chapter_type: block
summary: Bootstrap lazycortex-experts by seeding agent-model tiers and class-mapped composed expert entries into lazy.settings.json.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-experts.install
source_sha: 05f6f9a9fc372840e99c4cdcda9b7f182e336140
---
# Installing lazycortex-experts

`lazycortex-experts` ships eleven generic agents spanning the full development lifecycle plus fiction and documentation — interpreter, designer, architect, planner, implementer, data-implementer, docs-writer, debugger, reviewer, tester, and fiction-writer — plus a set of domain aspects and five cross-cutting aspects (discipline, research, tech-writing, terms, structure) that compose expertise onto those agents. Before the expert runtime in `lazycortex-core` can route jobs to them, two things must land in your `lazy.settings.json`: the agent-model tier for each generic agent (so dispatch knows which Claude tier to use), and a composed expert entry for every class × role pair the class map prescribes (so each specialist is addressable by name with the right aspect stack). `/lazy-experts.install` handles both in a single idempotent run.

Health checks after install route through `/lazy-core.doctor`, not through a plugin-local audit skill.

## When you'd use this

- You've just enabled `lazycortex-experts` from the marketplace and want your chosen domain classes fully composed and ready to use.
- You've updated the plugin and a new release shipped additional domain aspects, revised tier entries, a new role agent, or a newly-mandatory field — re-running picks up everything new without disturbing your existing config.
- You're setting up a fresh project-scoped environment and want agent-model tiers and expert entries isolated from your global config.
- You added a new agent or domain aspect to the plugin cache and want the class-map entries seeded without writing them by hand.

## How it fits together

Run `/lazy-experts.install`. The skill first checks that `lazycortex-experts@lazycortex` appears in your Claude Code installed-plugins list — if it's missing, it stops and tells you exactly what to add to `enabledPlugins` before re-running.

Next, it detects whether the plugin is installed at project scope or user (global) scope, then targets the matching `lazy.settings.json` — `<repo-root>/.claude/lazy.settings.json` for project-scoped installs, `~/.claude/lazy.settings.json` for global. If both scopes appear, it targets project scope without asking.

**Seeding agent-model tiers.** The skill locates the `default-tiers.json` file that `lazycortex-core` caches locally and selects every entry whose key starts with `lazycortex-experts:` — one entry per generic agent. For each one it compares what's already in your `lazy.settings.json`:

- If the entry is **absent**, it adds it.
- If the entry is **already there and identical**, it leaves it untouched.
- If the entry is **different from the default** (meaning you've customised it), it leaves your value in place and reports `kept-local` so you can see the divergence.

If `lazycortex-core` isn't installed at all — meaning the defaults file can't be found — the skill fails immediately rather than falling back to hardcoded values. Install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

**Seeding composed experts follows a class map.** On a fresh project with no domain-class experts yet, the skill asks which domain classes to register — the options are the domain aspects the plugin ships: `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`. What each class seeds depends on its kind:

- **Technical classes** (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`) seed nine roles: `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester`. Each entry stacks the domain aspect plus five cross-cutting aspects: `lazycortex-experts:lazy-experts.discipline-aspect` (execution discipline), `lazycortex-experts:lazy-experts.research-aspect`, `lazycortex-experts:lazy-experts.tech-writing-aspect` (documentation rigor), `lazycortex-experts:lazy-experts.terms-aspect` (call things by their registered term instead of a paraphrase), and `lazycortex-experts:lazy-experts.structure-aspect` (repository-map awareness). Three of the nine roles carry an expert-key name that differs from the underlying agent's basename: `developer` resolves to the `lazy-experts.implementer` agent, and `system-designer` resolves to the same `lazy-experts.designer` agent that the plain `designer` role also uses — seeded as a separate, independently-addressable expert entry under its own key.
- **`game-dev` additionally seeds `data-writer`.** Writing entity data files against an approved design is a subject-matter particularity of game development, so this tenth role — which resolves to the `lazy-experts.data-implementer` agent — rides on top of the nine technical roles every technical class gets, carrying the same domain aspect plus the same five cross-cutting aspects as the other `game-dev` roles. A project of another class that wants this role registers it by hand rather than receiving it by default.
- **Fiction classes** (`sci-fi`, `fantasy`) seed only `fiction-writer`. Each entry stacks the domain aspect plus `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect` — the tech-writing, terms, and structure aspects are never added to a fiction expert, since their rules (call the entity by its registered term, respect the repository map) would contradict literary craft.

Every seeded entry, technical or fiction, also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs under `.memory/<expert-key>/`. A `developer`, `data-writer`, `docs-writer`, or `tester` entry additionally carries `workspace: "branch"` — those roles run their acceptance-cycle job and every continuation on a job-scoped branch; every other role stays on the implicit `workspace: main` (the field is simply omitted).

**`can_commit_in_repo` marks which roles are allowed to land their own work in the tracked tree.** Every writing role — `designer`, `system-designer`, `architect`, `planner`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester` — is seeded with `can_commit_in_repo: true`; `interpreter`, `reviewer`, and `fiction-writer` never get the flag, since those three deliver findings or narrative payload rather than editing files in place. Without it, a launch-checkbox job's document strands in the job's own `result/` directory instead of landing where the review/spec system can find it. Example technical entry:

```jsonc
"claude-plugin.designer": {
  "agent": "lazycortex-experts:lazy-experts.designer",
  "aspects": [
    "lazycortex-experts:lazy-experts.claude-plugin-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-experts:lazy-experts.research-aspect",
    "lazycortex-experts:lazy-experts.tech-writing-aspect",
    "lazycortex-experts:lazy-experts.terms-aspect",
    "lazycortex-experts:lazy-experts.structure-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "Claude Plugin Designer",
    "email": "claude-plugin.designer@bot.invalid"
  },
  "can_commit_in_repo": true
}
```

And the corresponding fiction entry — note there's no role choice (fiction classes only ever seed `fiction-writer`), none of the technical-only cross-cutting aspects, and no `can_commit_in_repo` (fiction-writer is not a writing role):

```jsonc
"sci-fi.fiction-writer": {
  "agent": "lazycortex-experts:lazy-experts.fiction-writer",
  "aspects": [
    "lazycortex-experts:lazy-experts.sci-fi-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-experts:lazy-experts.research-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "Sci Fi Fiction Writer",
    "email": "sci-fi.fiction-writer@bot.invalid"
  }
}
```

On a re-run against a project that already has domain-class expert entries, the skill never re-asks which classes to register. Instead it inspects the aspects already present in your `experts` section and derives the class set from those refs — excluding the cross-cutting aspects (`discipline`, `research`, `tech-writing`, `terms`, `structure`) and any system experts seeded by sibling plugins from that derivation, since neither is a class in its own right. It then completes any missing (class × role) pairs the class map prescribes for exactly those classes — nothing more. Expert entries are only written when absent; any entry you've customised by hand is left untouched, except for two things it treats as completion rather than overwrite: **a missing mandatory cross-cutting aspect is appended, not skipped**, and **a missing `can_commit_in_repo` key on a writing-role entry is set to `true`, not skipped**. `discipline` and `research` are mandatory on every domain-class entry regardless of class kind, and `tech-writing`, `terms`, and `structure` are mandatory on every technical-class entry; an entry seeded before one of these aspects shipped is treated as incomplete rather than customised, so a re-run appends whatever it's missing to the end of that entry's `aspects[]` array — order preserved, nothing else touched, nothing removed. If you deliberately dropped one of the five by hand, the install run reports it as `completed: <aspect>` and you're free to drop it again on the next re-run — there is no opt-out flag for this. `can_commit_in_repo` behaves differently: an entry that carries no key at all is incomplete and gets `true` seeded, but an entry with an explicit `false` is an operator choice and is left alone — the completion pass only fills a genuine absence.

**Checking system-expert completeness.** Separately from the classes you compose yourself, several sibling plugins register their own "system experts" the same way — `lazycortex-core`'s `runtime.doctor`, `lazycortex-review`'s `review.doc_doctor`, `lazycortex-specs`'s `spec.coordinator`, `lazycortex-wiki`'s `wiki.curator`. `/lazy-experts.install` never seeds these itself (the owning plugin's own install does), but for every one of those plugins that's enabled in your project, it checks whether the expected expert key is present and reports any that are missing, pointing you at the sibling plugin's own install skill to fill the gap.

After both seeding passes, the skill reads the file back to confirm every entry is present and parseable. For each seeded expert it also verifies the `agent` ref resolves to an actual agent file in the plugin cache — catching a stale or mistyped agent reference before you ever dispatch a job against it — then logs the run.

## Common adjustments

**Re-running after a plugin update.** `/plugin update` refreshes the plugin cache but does not re-sync settings. If a new release of `lazycortex-experts` ships additional domain aspects, revised `lazycortex-experts:*` tier entries in `default-tiers.json`, a new role agent, a newly-mandatory cross-cutting aspect, or a newly-mandatory `can_commit_in_repo` flag, re-run `/lazy-experts.install` to pick it up. The class map re-runs and adds any new (class × role) pairs it prescribes for your existing classes, and the completion pass appends any missing mandatory cross-cutting aspect or `can_commit_in_repo` key to entries that predate it; existing entries are otherwise left alone.

**Adding a new class to an existing project.** Because the skill derives its class set from your current domain-class `experts` entries, it won't add a class you haven't registered yet. To introduce a new domain, add one expert of the new class by hand (for a technical class, any of the nine roles will do — or `data-writer` too, if the new class is `game-dev`, since that's the only class where it's seeded; for a fiction class it must be `fiction-writer` — that's the only role the class map seeds), then re-run `/lazy-experts.install`. The skill derives the expanded class set and fills in the remaining entries the class map prescribes for the new class.

**Changing a tier after install.** If you want a different Claude tier for one of the agents than the default provides, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json`. `/lazy-experts.install` will then report `kept-local` on subsequent runs so your customisation is visible.

**Customising a composed expert.** If you want to add or remove aspects from a seeded expert, edit it via whatever skill manages `lazy.settings.json[experts]` in your workflow — `/lazy-experts.install` will not overwrite hand-authored or hand-modified entries on re-run, aside from completing a missing mandatory cross-cutting aspect or a missing `can_commit_in_repo` key (see above).

**Removing a cross-cutting aspect or the memory side-effect.** `discipline` and `research` are mandatory on every domain-class entry, and — for technical-class entries — so are `tech-writing`, `terms`, and `structure`. If you strip one of these from a seeded expert's `aspects[]`, the next `/lazy-experts.install` run treats the entry as incomplete rather than customised and appends it back; there's no per-entry opt-out. The one aspect that stays removed once you drop it is `lazycortex-core:lazy-memory.persona-aspect` — dropping it stops the expert from writing to `.memory/<self>/`, and the install skill never re-adds it on re-run.

**Preventing a writing role from committing.** `can_commit_in_repo` defaults to `true` on every seeded writing role (`designer`, `system-designer`, `architect`, `planner`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester`). If you want a particular expert to never commit in place, set `can_commit_in_repo: false` explicitly on its entry — unlike the cross-cutting aspects, an explicit `false` is respected as your choice and is never overwritten on re-run. Only a genuinely missing key is treated as incomplete and seeded to `true`.

**A sibling plugin's system expert is reported missing.** This isn't something `/lazy-experts.install` fixes — it only detects the gap. Run the owning plugin's own install skill instead: `/lazy-core.install` for `runtime.doctor`, `/lazy-review.install` for `review.doc_doctor`, `/lazy-spec.install` for `spec.coordinator`, `/lazy-wiki.install` for `wiki.curator`.

**Verifying the install.** Run `/lazy-core.doctor` to check the health of your full LazyCortex setup, including whether the experts' agent-model entries and composed expert entries are present, well-formed, and pointing at agent files that actually exist.
