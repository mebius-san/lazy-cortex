---
chapter_type: block
summary: Bootstrap lazycortex-experts via seeded tiers and composed experts, then verify with the plugin's own read-only audit skill.
last_regen: 2026-09-11
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.audit
source_sha: 5a28d4bdd32d8e9cead0b771ea95d2cee4c8c212
---
# Installing and auditing lazycortex-experts

`lazycortex-experts` ships thirteen generic agents spanning the full development lifecycle plus fiction and documentation — interpreter, designer, architect, planner, use-case-writer, ui-designer, implementer, data-implementer, docs-writer, debugger, reviewer, tester, and fiction-writer — plus a set of domain aspects and five cross-cutting aspects (discipline, research, tech-writing, terms, structure) that compose expertise onto those agents. Before the expert runtime in `lazycortex-core` can route jobs to them, two things must land in your `lazy.settings.json`: the agent-model tier for each generic agent (so dispatch knows which Claude tier to use), and a composed expert entry for every class × role pair the class map prescribes (so each specialist is addressable by name with the right aspect stack). `/lazy-experts.install` handles both in a single idempotent run, and `/lazy-experts.audit` is the plugin's own read-only counterpart — it verifies the shipped roles and aspects still resolve and that your seeded entries still point at real files, without ever writing anything.

## When you'd use this

- You've just enabled `lazycortex-experts` from the marketplace and want your chosen domain classes fully composed and ready to use.
- You've updated the plugin and a new release shipped additional domain aspects, revised tier entries, a new role agent, or a newly-mandatory field — re-running install picks up everything new without disturbing your existing config.
- You're setting up a fresh project-scoped environment and want agent-model tiers and expert entries isolated from your global config.
- You added a new agent or domain aspect to the plugin cache and want the class-map entries seeded without writing them by hand.
- Dispatching an expert fails in a way that smells like config — a job aborts saying the agent ref does not resolve, an expert writes to a contract it should not have, a role the class map prescribes turns out to have no entry — and you want to know exactly what's wrong before re-running install.
- You want a periodic sanity check that your composed experts still match what the plugin actually ships, without risking any write to `lazy.settings.json`.

## How it fits together

Run `/lazy-experts.install`. The skill first checks that `lazycortex-experts@lazycortex` appears in your Claude Code installed-plugins list — if it's missing, it stops and tells you exactly what to add to `enabledPlugins` before re-running.

Next, it detects whether the plugin is installed at project scope or user (global) scope, then targets the matching `lazy.settings.json` — `<repo-root>/.claude/lazy.settings.json` for project-scoped installs, `~/.claude/lazy.settings.json` for global. If both scopes appear, it targets project scope without asking.

**Seeding agent-model tiers.** The skill locates the `default-tiers.json` file that `lazycortex-core` caches locally and selects every entry whose key starts with `lazycortex-experts:` — one entry per generic agent. For each one it compares what's already in your `lazy.settings.json`:

- If the entry is **absent**, it adds it.
- If the entry is **already there and identical**, it leaves it untouched.
- If the entry is **different from the default** (meaning you've customised it), it leaves your value in place and reports `kept-local` so you can see the divergence.

If `lazycortex-core` isn't installed at all — meaning the defaults file can't be found — the skill fails immediately rather than falling back to hardcoded values. Install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

**Seeding composed experts follows a class map.** On a fresh project with no domain-class experts yet, the skill asks which domain classes to register — the options are the domain aspects the plugin ships: `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`. What each class seeds depends on its kind:

- **Technical classes** (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`) seed thirteen roles: `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `reviewer`, `tester`. Each entry stacks the domain aspect plus five cross-cutting aspects: `lazycortex-experts:lazy-experts.discipline-aspect` (execution discipline), `lazycortex-experts:lazy-experts.research-aspect`, `lazycortex-experts:lazy-experts.tech-writing-aspect` (documentation rigor), `lazycortex-experts:lazy-experts.terms-aspect` (call things by their registered term instead of a paraphrase), and `lazycortex-experts:lazy-experts.structure-aspect` (repository-map awareness). Three of the thirteen roles carry an expert-key name that differs from the underlying agent's basename: `developer` resolves to the `lazy-experts.implementer` agent, `data-writer` resolves to the `lazy-experts.data-implementer` agent, and `system-designer` resolves to the same `lazy-experts.designer` agent that the plain `designer` role also uses — each seeded as a separate, independently-addressable expert entry under its own key.
- **`data-writer` seeds with every technical class**, not just `game-dev`. Writing entity or content data files against an approved design is a general genre, not a game-dev particularity, so this role — resolving to the `lazy-experts.data-implementer` agent — carries the same domain aspect plus the same five cross-cutting aspects as every other role the technical row seeds.
- **Fiction classes** (`sci-fi`, `fantasy`) seed only `fiction-writer`. Each entry stacks the domain aspect plus `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect` — the tech-writing, terms, and structure aspects are never added to a fiction expert, since their rules (call the entity by its registered term, respect the repository map) would contradict literary craft.

Every seeded entry, technical or fiction, also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert accumulates private memory across runs under `.memory/<expert-key>/`. A `developer`, `data-writer`, `docs-writer`, or `tester` entry additionally carries `workspace: "branch"` — those roles run their acceptance-cycle job and every continuation on a job-scoped branch; every other role stays on the implicit `workspace: main` (the field is simply omitted, never written as the literal string). The companion `merge` field (`auto` / `ask`) is never seeded either way — it defaults to `ask`, which is the right pairing for an isolated workspace, so writing it would only restate the default.

**`can_commit_in_repo` marks which roles are allowed to land their own work in the tracked tree.** Every writing role — `designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester` — is seeded with `can_commit_in_repo: true`; `interpreter`, `reviewer`, and `fiction-writer` never get the flag, since those three deliver findings or narrative payload rather than editing files in place. Without it, a launch-checkbox job's document strands in the job's own `result/` directory instead of landing where the review/spec system can find it. Example technical entry:

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

On a re-run against a project that already has domain-class expert entries, the skill never re-asks which classes to register. Instead it inspects the aspects already present in your `experts` section and derives the class set from those refs — excluding the cross-cutting aspects (`discipline`, `research`, `tech-writing`, `terms`, `structure`) and any system experts seeded by sibling plugins from that derivation, since neither is a class in its own right. It then completes any missing (class × role) pairs the class map prescribes for exactly those classes — nothing more. Expert entries are only written when absent; any entry you've customised by hand is left untouched, except for three things it treats as completion rather than overwrite: **a missing mandatory cross-cutting aspect is appended, not skipped**, **a missing `can_commit_in_repo` key on a writing-role entry is set to `true`, not skipped**, and **a missing `workspace` key on a `developer`, `data-writer`, `docs-writer`, or `tester` entry is backfilled to `"branch"`, not skipped**. `discipline` and `research` are mandatory on every domain-class entry regardless of class kind, and `tech-writing`, `terms`, and `structure` are mandatory on every technical-class entry; an entry seeded before one of these aspects shipped is treated as incomplete rather than customised, so a re-run appends whatever it's missing to the end of that entry's `aspects[]` array — order preserved, nothing else touched, nothing removed. If you deliberately dropped one of the five by hand, the install run reports it as `completed: <aspect>` and you're free to drop it again on the next re-run — there is no opt-out flag for this. `can_commit_in_repo` behaves differently: an entry that carries no key at all is incomplete and gets `true` seeded, but an entry with an explicit `false` is an operator choice and is left alone — the completion pass only fills a genuine absence. `workspace` on the four isolated roles works the same way: absence is treated as a pre-existing gap and backfilled to `"branch"` (reported `refreshed`), but an explicit `"main"` you set by hand is a deliberate opt-out and is never touched.

**Checking system-expert completeness.** Separately from the classes you compose yourself, several sibling plugins register their own "system experts" the same way — each plugin declares the expert keys its own install skill seeds in a `provides_experts` array in its `.claude-plugin/plugin.json`, and `/lazy-experts.install` reads that array from every installed plugin's manifest at run time rather than from a hardcoded list, so a plugin update that adds a new system expert is picked up without this skill needing an edit. As shipped today, `lazycortex-core` declares `runtime.doctor` and `core.autocheckup`, `lazycortex-review` declares `review.coordinator` and `review.doc_doctor`, `lazycortex-specs` declares `spec.coordinator` and `spec.catalog-coordinator`, and `lazycortex-wiki` declares `wiki.curator`, `wiki.terms-curator`, `wiki.structure-curator`, `wiki.tag-curator`, and `wiki.domain-writer`. `/lazy-experts.install` never seeds any of these itself (the owning plugin's own install is the sole writer), but for every one of those plugins that's enabled in your project, it checks whether each declared key is present and reports any that are missing, pointing you at that plugin's own install skill to fill the gap.

After both seeding passes, the skill reads the file back to confirm every entry is present and parseable. For each seeded expert it also verifies the `agent` ref resolves to an actual agent file in the plugin cache — catching a stale or mistyped agent reference before you ever dispatch a job against it — then logs the run.

**Checking it afterwards.** `/lazy-experts.audit` is the read-only counterpart — it never seeds, edits, or removes anything in `lazy.settings.json`, it only reports. Run it any time you want to confirm your composition is still sound, whether or not you've made hand edits since the last install. It runs two passes:

- **The shipped surface** — every role the class map assigns resolves to a real agent file under the plugin's `agents/` directory, and every aspect the class map assigns (domain and cross-cutting alike) resolves to a real reference file. A gap here means the plugin cache itself is incomplete, not your settings — the fix is `/plugin update lazycortex-experts@lazycortex`, not a re-run of install.
- **Your seeded expert entries** — for every composed entry in `experts`, it confirms the `agent` ref resolves, every `lazycortex-experts:` aspect ref resolves, the mandatory cross-cutting aspects for the entry's class kind are present (technical entries need `discipline`, `research`, `tech-writing`, `terms`, `structure`; fiction entries need only `discipline` and `research`, and carrying any of the other three on a fiction entry is itself flagged), and that `can_commit_in_repo` / `workspace` are present on the roles that need them. System entries seeded by sibling plugins are listed but not judged — that's the owning plugin's business.

Each finding comes back as `PASS`, `WARN`, `FAIL`, or `INFO`, grouped by severity with the fix named alongside every `WARN` and `FAIL`. For nearly everything the audit finds, the fix is simply re-running `/lazy-experts.install` — it seeds a missing entry, appends a missing mandatory aspect, and backfills an absent `can_commit_in_repo` or `workspace` key. The two exceptions (`agent-missing`, `aspect-missing`) mean the plugin's own shipped files are incomplete, so the fix is `/plugin update lazycortex-experts@lazycortex` instead. `/lazy-core.doctor` also runs this audit for you as part of its own cross-plugin sweep, so you don't have to remember to invoke it directly unless you want the plugin-scoped result on its own.

## Common adjustments

**Re-running after a plugin update.** `/plugin update` refreshes the plugin cache but does not re-sync settings. If a new release of `lazycortex-experts` ships additional domain aspects, revised `lazycortex-experts:*` tier entries in `default-tiers.json`, a new role agent, a newly-mandatory cross-cutting aspect, or a newly-mandatory `can_commit_in_repo` / `workspace` value, re-run `/lazy-experts.install` to pick it up. The class map re-runs and adds any new (class × role) pairs it prescribes for your existing classes, and the completion pass appends any missing mandatory cross-cutting aspect, `can_commit_in_repo` key, or `workspace: "branch"` backfill to entries that predate it; existing entries are otherwise left alone. Run `/lazy-experts.audit` afterwards (or just check `/lazy-core.doctor`'s next sweep) to confirm nothing from the new release is still unresolved.

**Adding a new class to an existing project.** Because the skill derives its class set from your current domain-class `experts` entries, it won't add a class you haven't registered yet. To introduce a new domain, add one expert of the new class by hand (for a technical class, any of the thirteen roles will do — `data-writer` included, since it now seeds with every technical class; for a fiction class it must be `fiction-writer` — that's the only role the class map seeds), then re-run `/lazy-experts.install`. The skill derives the expanded class set and fills in the remaining entries the class map prescribes for the new class.

**Changing a tier after install.** If you want a different Claude tier for one of the agents than the default provides, run `/lazy-core.agent-models` — that skill owns the `agent_models` section of `lazy.settings.json`. `/lazy-experts.install` will then report `kept-local` on subsequent runs so your customisation is visible.

**Customising a composed expert.** If you want to add or remove aspects from a seeded expert, edit it via whatever skill manages `lazy.settings.json[experts]` in your workflow — `/lazy-experts.install` will not overwrite hand-authored or hand-modified entries on re-run, aside from completing a missing mandatory cross-cutting aspect, a missing `can_commit_in_repo` key, or a missing `workspace` value on one of the four isolated roles (see above).

**Removing a cross-cutting aspect or the memory side-effect.** `discipline` and `research` are mandatory on every domain-class entry, and — for technical-class entries — so are `tech-writing`, `terms`, and `structure`. If you strip one of these from a seeded expert's `aspects[]`, the next `/lazy-experts.install` run treats the entry as incomplete rather than customised and appends it back; there's no per-entry opt-out. The one aspect that stays removed once you drop it is `lazycortex-core:lazy-memory.persona-aspect` — dropping it stops the expert from writing to `.memory/<self>/`, and the install skill never re-adds it on re-run.

**Preventing a writing role from committing.** `can_commit_in_repo` defaults to `true` on every seeded writing role (`designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester`). If you want a particular expert to never commit in place, set `can_commit_in_repo: false` explicitly on its entry — unlike the cross-cutting aspects, an explicit `false` is respected as your choice and is never overwritten on re-run. Only a genuinely missing key is treated as incomplete and seeded to `true`.

**Keeping a role on `workspace: main`.** `developer`, `data-writer`, `docs-writer`, and `tester` default to `workspace: "branch"` — their launch-checkbox job and every continuation run isolated. If you want one of these roles to stay on the implicit `main` workspace instead, set `workspace: "main"` explicitly on its entry; an explicit value, in either direction, is your choice and stays untouched. Only an entry that carries no `workspace` key at all is treated as an incomplete seed and backfilled to `"branch"` on the next run.

**A sibling plugin's system expert is reported missing.** This isn't something `/lazy-experts.install` fixes — it only detects the gap by reading each installed plugin's `provides_experts` manifest entry. Run the owning plugin's own install skill instead — for the system experts shipped today: `/lazy-core.install` for `runtime.doctor` / `core.autocheckup`, `/lazy-review.install` for `review.coordinator` / `review.doc_doctor`, `/lazy-spec.install` for `spec.coordinator` / `spec.catalog-coordinator`, `/lazy-wiki.install` for `wiki.curator` / `wiki.terms-curator` / `wiki.structure-curator` / `wiki.tag-curator` / `wiki.domain-writer`.

**A job aborts saying an agent ref or aspect ref doesn't resolve.** Run `/lazy-experts.audit` first to pin down exactly which expert key and which ref are broken (it distinguishes a bad `agent` ref on your entry from a missing shipped file), then apply the fix it names — a re-run of `/lazy-experts.install`, a hand-correction of a stray `agent` ref, or `/plugin update lazycortex-experts@lazycortex` if the plugin's own files are incomplete.

**Verifying the install.** Run `/lazy-experts.audit` directly for a plugin-scoped, read-only report of your composed experts and the shipped surface they depend on, or run `/lazy-core.doctor` to check the health of your full LazyCortex setup — it delegates to this same audit as part of its cross-plugin sweep, alongside every other plugin's check.
