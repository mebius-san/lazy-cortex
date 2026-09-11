---
chapter_type: troubleshooting
summary: Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
last_regen: 2026-09-11
no_diagram: true
source_skills:
  - lazy-experts.install
  - lazy-experts.audit
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.architect
  - lazy-experts.planner
  - lazy-experts.use-case-writer
  - lazy-experts.ui-designer
  - lazy-experts.implementer
  - lazy-experts.data-implementer
  - lazy-experts.docs-writer
  - lazy-experts.debugger
  - lazy-experts.reviewer
  - lazy-experts.tester
source_sha: 5a28d4bdd32d8e9cead0b771ea95d2cee4c8c212
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

**Symptom**: You picked `sci-fi` (or `fantasy`) when `/lazy-experts.install` asked which classes to register, but only one expert entry appeared — `sci-fi.fiction-writer` (or `fantasy.fiction-writer`) — with no interpreter, designer, system-designer, architect, planner, use-case-writer, ui-designer, developer, data-writer, docs-writer, debugger, reviewer, or tester for that class.

**Likely cause**: This is the intended behaviour, not a bug. The class map seeds roles differently by class kind: technical classes (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, and any future non-fiction class) get all thirteen engineering roles — `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `reviewer`, `tester`; fiction classes (`sci-fi`, `fantasy`) get only `fiction-writer`, because the other roles assume an engineering lifecycle (design specs, code architecture, implementation plans, code review, user-facing docs) that doesn't apply to literary work. `data-writer` is seeded with every technical class, not only `game-dev` — writing data files against an approved design is a general genre, not a game-dev particularity. Fiction classes also never receive `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, or `lazy-experts.structure-aspect` — those three assume a technical repository, which a scene has nothing to do with.

**Fix**: Nothing to fix if you're working purely in a fiction domain — `fiction-writer` is the complete role set for `sci-fi`/`fantasy`. If your project also spans a technical domain (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`), register at least one expert of that class by hand in `lazy.settings.json[experts]`, or clear the `experts` section and re-run `/lazy-experts.install` so it asks again and seeds both class kinds together.

---

## Report ends with "system-experts: N missing"

**Symptom**: The final report from `/lazy-experts.install` ends with a line like `system-experts: 2 missing`, followed by entries such as `system: review.doc_doctor (missing — run /lazy-review.install to register, or ignore if the feature is deliberately unconfigured)`.

**Likely cause**: Every sibling plugin that ships a system expert declares the keys its own install skill registers in a `provides_experts` array in its own `.claude-plugin/plugin.json` — `lazy-experts.install` builds the check's registry at run time from every installed plugin's manifest, rather than from a hardcoded list, so a plugin that adds a new system expert later is picked up automatically without this skill needing an update. It only checks keys declared by sibling plugins that are enabled at the current scope, and reports a gap when a sibling plugin is enabled but has never run its own install.

**Fix**: `/lazy-experts.install` never seeds these entries itself — the owning plugin's install is the sole writer. Run the fix command the report names for the missing entry (e.g. `/lazy-review.install`, `/lazy-core.install`, `/lazy-spec.install`, `/lazy-wiki.install`, `/lazy-python.install`), or leave it alone if you deliberately haven't configured that plugin's feature yet.

---

## Report shows `verify-failed: agent-ref-unresolved <expert-key>`

**Symptom**: The final report from `/lazy-experts.install` includes a line like `verify-failed: agent-ref-unresolved claude-plugin.designer` instead of `verified`.

**Likely cause**: The verify step confirms that every seeded expert's `agent` ref resolves to an actual file under `<installPath>/agents/` (e.g. `lazy-experts.designer.md`). This check fails when the plugin cache is missing an agent file the class map expects for the seeded role — typically a partially completed `/plugin update` that dropped an agent file without also dropping the reference/aspect files the earlier glob checks already passed.

**Fix**: Run `/plugin update lazycortex-experts@lazycortex` to restore the missing agent file, then re-run `/lazy-experts.install`. The verify step re-checks on every run, so the report should show `verified` once the cache is complete.

---

## Report lists `experts.<key> (completed: <aspect>[, <aspect>…])` for entries that already existed

**Symptom**: The report includes lines like `experts.claude-plugin.designer (completed: lazy-experts.terms-aspect, lazy-experts.structure-aspect)`, or `experts.claude-plugin.planner (completed: can_commit_in_repo)`, for expert entries that were already in `lazy.settings.json` before this run — nothing you asked to be added.

**Likely cause**: `/lazy-experts.install` never touches a field an operator owns on an existing entry — `agent`, `git_author`, `workspace`, or the domain aspect stay exactly as they are. But two kinds of thing are treated as mandatory rather than as an operator choice: five cross-cutting aspects (`lazy-experts.discipline-aspect` and `lazy-experts.research-aspect` on every domain-class entry, plus `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect` on technical-class entries specifically), and the `can_commit_in_repo` flag on every writing-role entry (`designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester`). An entry seeded before one of these shipped (or hand-authored without it) isn't customized with respect to it — it's incomplete. Every re-run appends whatever's still missing from the mandatory aspect list, and seeds `can_commit_in_repo: true` on any writing-role entry that carries no such key at all, without touching anything else on the entry.

**Fix**: Nothing to fix — this is `/lazy-experts.install` keeping an older or hand-authored entry current with the mandatory list, not an error. If you deliberately want an expert without one of the five aspects (e.g. a technical expert that should never load `lazy-experts.terms-aspect`), there's no opt-out marker for it: the aspect gets re-appended on every future run — remove it by hand after each run if you need to keep it off. `can_commit_in_repo` is different: an explicit `false` you set yourself is an operator choice the skill leaves untouched, exactly like a customized `workspace` — only a *missing* key gets completed to `true`.

---

## Report lists `experts.<key> (refreshed: workspace)` for entries that already existed

**Symptom**: The report includes a line like `experts.game.developer (refreshed: workspace)` for an expert entry that already existed in `lazy.settings.json` before this run — you didn't touch that entry's `workspace` field.

**Likely cause**: `workspace: "branch"` is seeded on every entry for the `developer`, `data-writer`, `docs-writer`, and `tester` roles — the acceptance-cycle roles that run their launch-checkbox job and every continuation on a job-scoped branch, so their work never lands directly on `main`. A missing `workspace` key on one of these four roles is indistinguishable from a deliberate `"main"` choice, so `/lazy-experts.install` treats the absent key as an incomplete entry (predating this backfill, or hand-authored without it) rather than an operator preference, and writes `workspace: "branch"` in.

**Fix**: Nothing to fix — this brings an older or hand-authored entry in line with every other developer/data-writer/docs-writer/tester expert, which all run isolated by default. If you deliberately want one of these four roles to keep working directly on `main`, set `"workspace": "main"` explicitly on that entry — an explicit value, in either direction, is an operator choice the skill leaves untouched on every future run.

---

## Why does `<domain>.system-designer` (or `.developer`, `.data-writer`) point at a different agent name?

**Symptom**: A seeded entry's role suffix doesn't match its `agent` field — e.g. `claude-plugin.system-designer` carries `"agent": "lazycortex-experts:lazy-experts.designer"`, `game.developer` carries `"agent": "lazycortex-experts:lazy-experts.implementer"`, or `game.data-writer` carries `"agent": "lazycortex-experts:lazy-experts.data-implementer"`.

**Likely cause**: This is intended, not a mismatch to fix. Three roles in the class map name the job an expert does rather than reusing its agent's file name: `system-designer` and `developer` are two distinct jobs the `designer` and `implementer` agents perform depending on which stage of the class map dispatches them, and `data-writer` is the job name for the `data-implementer` agent's role across every technical class. Every other role's `agent` field matches its own name verbatim (`interpreter` → `lazy-experts.interpreter`, `architect` → `lazy-experts.architect`, `use-case-writer` → `lazy-experts.use-case-writer`, `ui-designer` → `lazy-experts.ui-designer`, and so on).

**Fix**: Nothing to fix. Before assuming a seeded entry is broken, check whether its role is one of the three that intentionally maps to a differently-named agent (`system-designer` → designer, `developer` → implementer, `data-writer` → data-implementer).

---

## A launch-job expert's document never lands in the tracked tree

**Symptom**: An expert with a writing role (`designer`, `system-designer`, `architect`, `planner`, `use-case-writer`, `ui-designer`, `developer`, `data-writer`, `docs-writer`, `debugger`, or `tester`) runs a launch-checkbox job to completion, but its document never shows up in the working tree — the job strands in its own result, and whatever coordinates the job can only flag it as undelivered.

**Likely cause**: The expert's `lazy.settings.json[experts]` entry is missing `can_commit_in_repo: true`. Without that flag, the expert runtime treats the job as read-only and never lets the expert write its deliverable into the tracked tree. This normally happens to an entry that was seeded or hand-authored before `can_commit_in_repo` existed — it isn't a deliberate no-commit configuration, it's an incomplete entry.

**Fix**: Re-run `/lazy-experts.install`. Its completion pass seeds `can_commit_in_repo: true` on any writing-role entry that carries no such key at all, reported as `experts.<key> (completed: can_commit_in_repo)`. If the entry already carries an explicit `false`, that was set on purpose and the skill leaves it alone — remove it by hand if you want that expert able to commit.

---

## `agent_models` report shows `sot-missing` or `no-entries`

**Symptom**: The `agent_models` portion of the report shows `sot-missing` or `no-entries` instead of the usual per-key `added` / `unchanged` / `kept-local` list.

**Likely cause**: Seeding `agent_models` is delegated to a shared tier-seeding primitive that locates `lazycortex-core`'s `default-tiers.json` and reads the `lazycortex-experts:*` rows out of it. `sot-missing` means the primitive couldn't find that file at all — the same root cause as the "lazycortex-core not installed" abort above, just surfaced from inside the primitive instead of at the top of the run. `no-entries` means the file was found but carries no `lazycortex-experts:*` rows yet — usually a version mismatch after `lazycortex-experts` was updated ahead of `lazycortex-core`.

**Fix**: Run `/plugin update lazycortex-core@lazycortex` to refresh the tiers file (add `/plugin update lazycortex-experts@lazycortex` too if `no-entries` persists), then re-run `/lazy-experts.install`.

---

## `/lazy-experts.audit` aborts with "plugin-root-unresolved"

**Symptom**: Running `/lazy-experts.audit` stops immediately with `FAIL plugin-root-unresolved` before any other check runs.

**Likely cause**: The audit couldn't find `lazycortex-experts@lazycortex`'s `installPath` in `~/.claude/plugins/installed_plugins.json`, and this repo isn't the one authoring the plugin's own sources — so there is no shipped agent/reference tree to check your composed experts against.

**Fix**: Run `/plugin install lazycortex/lazycortex-experts`, then re-run `/lazy-experts.audit`.

---

## `/lazy-experts.audit` reports "no-experts-configured"

**Symptom**: The audit report includes `INFO no-experts-configured`, and only the shipped-surface checks ran — no per-entry findings for your composed experts.

**Likely cause**: The project's `lazy.settings.json` has no `experts` section yet, or the section holds nothing besides `_version` — there is nothing composed yet to check.

**Fix**: Run `/lazy-experts.install` to seed a class set, then re-run `/lazy-experts.audit` to check the seeded entries.

---

## `/lazy-experts.audit` reports `FAIL agent-missing` or `FAIL aspect-missing`

**Symptom**: The report includes a line like `FAIL agent-missing: developer → lazy-experts.implementer.md` or `FAIL aspect-missing: lazy-experts.terms-aspect.md`.

**Likely cause**: These two checks run against the plugin's own shipped tree, not your settings — a role the class map assigns has no matching agent file, or an aspect the map assigns has no matching reference file. The shipped plugin cache itself is incomplete, usually from an interrupted `/plugin install` or `/plugin update`.

**Fix**: Run `/plugin update lazycortex-experts@lazycortex` to restore the missing file, then re-run `/lazy-experts.audit`. Unlike every other finding this skill raises, the fix here is NOT `/lazy-experts.install` — that skill has no way to repair a gap in the shipped plugin cache.

---

## `/lazy-experts.audit` reports `FAIL agent-ref-unresolved`

**Symptom**: The report includes a line like `FAIL agent-ref-unresolved: claude-plugin.designer → lazycortex-experts:lazy-experts.designer`, for an entry already composed in your `lazy.settings.json`.

**Likely cause**: This is the read-only counterpart to the `verify-failed: agent-ref-unresolved` abort `/lazy-experts.install` reports at its own verify step (above) — the entry's `agent` ref names a basename this plugin no longer ships under `agents/`, most often a hand-edited `agent` field in `lazy.settings.json`.

**Fix**: Correct the ref by hand in `lazy.settings.json`, or delete the entry and re-run `/lazy-experts.install` to reseed it from the class map.
