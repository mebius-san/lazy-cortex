---
chapter_type: troubleshooting
summary: Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
last_regen: 2026-07-22
no_diagram: true
source_skills:
  - lazy-experts.install
---
# Troubleshooting

## `/lazy-experts.install` aborts with "plugin not enabled"

**Symptom**: Running `/lazy-experts.install` immediately stops with a message like `lazycortex-experts not enabled — add "lazycortex-experts@lazycortex": true to enabledPlugins in your settings.json and run /plugin install lazycortex/lazycortex-experts.`

**Likely cause**: `lazycortex-experts@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json`. This happens when the plugin was never installed, or when the install completed but the plugin key was not added to `enabledPlugins` before the run.

**Fix**: Add `"lazycortex-experts@lazycortex": true` to `enabledPlugins` in your `settings.json`, restart Claude Code so the plugin loads, then run `/plugin install lazycortex/lazycortex-experts` to complete the install. Once the entry appears in `installed_plugins.json`, re-run `/lazy-experts.install`.

---

## `/lazy-experts.install` aborts with "lazycortex-core not installed"

**Symptom**: Running `/lazy-experts.install` stops with `lazycortex-core not installed; install it before /lazy-experts.install`.

**Likely cause**: The defaults file that `lazy-experts.install` reads from `lazycortex-core`'s plugin cache was not found. This means `lazycortex-core` is either not installed or its cache was cleared and not repopulated. `lazycortex-core` is a declared dependency — it must be present so that agent-model tiers can be seeded from its `default-tiers.json`.

**Fix**: Install `lazycortex-core` first by running `/plugin install lazycortex/lazycortex-core`, then re-run `/lazy-experts.install`. If `lazycortex-core` is already installed but its cache appears incomplete, run `/plugin update` to refresh the cache and try again.

---

## `/lazy-experts.install` aborts with "plugin-cache-incomplete"

**Symptom**: Running `/lazy-experts.install` stops with `plugin-cache-incomplete: <missing-dir>` while enumerating the available expert classes.

**Likely cause**: The skill globs `<installPath>/references/lazy-experts.*-aspect.md` (domain aspects) and `<installPath>/agents/lazy-experts.*.md` (agent roles) to build the class/role menu. If either glob comes back empty, the plugin cache is only partially synced — a `/plugin install` or `/plugin update` was interrupted, or the cache directory was manually cleared.

**Fix**: Run `/plugin update lazycortex-experts@lazycortex` to restore the cache, then re-run `/lazy-experts.install`.

---

## Only `fiction-writer` got seeded for my sci-fi or fantasy class

**Symptom**: You picked `sci-fi` (or `fantasy`) when `/lazy-experts.install` asked which classes to register, but only one expert entry appeared — `sci-fi.fiction-writer` (or `fantasy.fiction-writer`) — with no interpreter, designer, planner, implementer, debugger, reviewer, or tester for that class.

**Likely cause**: This is the intended behaviour, not a bug. The class map seeds roles differently by class kind: technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, and any future non-fiction class) get all seven engineering roles; fiction classes (`sci-fi`, `fantasy`) get only `fiction-writer`, because the other seven roles assume an engineering lifecycle (design specs, implementation plans, code review) that doesn't apply to literary work. Fiction classes also never receive `lazy-experts.tech-writing-aspect` — its bans on prose style contradict literary craft.

**Fix**: Nothing to fix if you're working purely in a fiction domain — `fiction-writer` is the complete role set for `sci-fi`/`fantasy`. If your project also spans a technical domain (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`), register at least one expert of that class by hand in `lazy.settings.json[experts]`, or clear the `experts` section and re-run `/lazy-experts.install` so it asks again and seeds both class kinds together.

---

## Report ends with "system-experts: N missing"

**Symptom**: The final report from `/lazy-experts.install` ends with a line like `system-experts: 2 missing`, followed by entries such as `system: review.historian (missing — run /lazy-review.install to register, or ignore if the feature is deliberately unconfigured)`.

**Likely cause**: Every sibling plugin (`lazycortex-core`, `lazycortex-review`, `lazycortex-specs`, `lazycortex-wiki`) registers its own system expert (`lazy-runtime.doctor`, `review.doc_doctor`/`review.historian`, `spec.request-router`, `wiki.curator`) through its own install skill. `/lazy-experts.install` only checks whether those entries are present for sibling plugins that are enabled at the current scope — it reports a gap when a sibling plugin is enabled but has never run its own install.

**Fix**: `/lazy-experts.install` never seeds these entries itself — the owning plugin's install is the sole writer. Run the fix command the report names for the missing entry (e.g. `/lazy-review.install`, `/lazy-core.install`, `/spec.install`, `/lazy-wiki.install`), or leave it alone if you deliberately haven't configured that plugin's feature yet.

---

## Report shows `verify-failed: agent-ref-unresolved <expert-key>`

**Symptom**: The final report from `/lazy-experts.install` includes a line like `verify-failed: agent-ref-unresolved claude-plugin.designer` instead of `verified`.

**Likely cause**: Step 6 confirms that every seeded expert's `agent` ref resolves to an actual file under `<installPath>/agents/` (e.g. `lazy-experts.designer.md`). This check fails when the plugin cache is missing an agent file the class map expects for the seeded role — typically a partially completed `/plugin update` that dropped an agent file without also dropping the reference/aspect files the earlier glob checks already passed.

**Fix**: Run `/plugin update lazycortex-experts@lazycortex` to restore the missing agent file, then re-run `/lazy-experts.install`. Step 6 re-verifies on every run, so the report should show `verified` once the cache is complete.

---

## Report shows a hint about experts missing the tech-writing aspect

**Symptom**: The report ends with a line like `hint: 3 existing expert(s) missing lazycortex-experts:lazy-experts.tech-writing-aspect — append it to their aspects[] by hand, or remove the entries and re-run to re-seed.`

**Likely cause**: `/lazy-experts.install` never overwrites an existing expert entry, even a hand-customized one. If those entries were seeded before `lazy-experts.tech-writing-aspect` was added to the technical-class composition (or were hand-authored without it), they stay exactly as they are on every re-run — the skill only fills in entries that are entirely absent.

**Fix**: As the hint itself says, either append `lazycortex-experts:lazy-experts.tech-writing-aspect` to the affected entries' `aspects[]` by hand, or delete those expert entries from `lazy.settings.json[experts]` and re-run `/lazy-experts.install` — Step 5 re-seeds them from the current class map, tech-writing aspect included.
