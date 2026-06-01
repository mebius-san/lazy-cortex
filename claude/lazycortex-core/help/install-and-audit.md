---
chapter_type: block
summary: Bootstrap and verify lazycortex-core — the shared scaffolding layer every other plugin depends on.
last_regen: 2026-06-01
diagram_spec:
  anchor: "Bootstrap order"
  request: "Flowchart showing the lazycortex-core bootstrap order: enable plugin and restart → single-plugin path via /lazy-core.install or multi-plugin path via /lazy-core.setup → rules changed triggers second restart → /lazy-core.audit → if audit fails resolve issues and re-audit; if audit passes decide whether to run /lazy-core.optimize and /lazy-core.doctor → bootstrap complete"
source_skills:
  - lazy-core.install
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.optimize
  - lazy-core.setup
---
# Install, audit, and maintain lazycortex-core

Every lazycortex plugin ships lifecycle skills — install, audit, doctor, optimize, and setup. For most plugins those skills are scoped to their own rules and config. For `lazycortex-core` the stakes are higher: core ships the shared scaffolding every other plugin assumes is already in place — the rule authoring templates, the `lazy.settings.json` runtime structure, the agent-model routing layer, and the expert runtime daemon. Bootstrapping core is bootstrapping the whole lazycortex baseline.

This block covers all five of core's lifecycle skills. The order they run in and the way they build on each other is what matters.

**Prerequisite:** all lazycortex plugins require Python 3.12 or later. `/lazy-core.install` verifies this at Step 0 and aborts with install instructions if the floor is not met — nothing else in this block runs until Python 3.12+ is available.

## What's in this block

**`/lazy-core.install`** is the foundation step. Run it once per project (or globally) right after enabling the plugin and restarting Claude Code. It syncs every rule template the plugin ships into the correct rules directory, copies authoring templates into `.claude/templates/core/`, and bootstraps the scaffold registry. It then seeds `lazy.settings.json` with the three built-in agent-model routing defaults. After the rules and settings groundwork is in place, it offers a runtime wizard: if you want the expert daemon in this repo, the wizard writes `.experts/`, the `lazy.runtime.sh` shim, the flat `daemon` and `routines` sections in `lazy.settings.json`, the expert-add wizard, and optionally a launchd or systemd supervisor. Step 10.5 bootstraps `.memory/` when runtime is enabled. Step 13.5 offers to merge the recommended expert-spawn sandbox and permissions block into `settings.local.json`. The skill is idempotent — re-running after a plugin update picks up new rule templates without clobbering rules you chose to keep local.

**`/lazy-core.audit`** is the read-only context-weight and compliance measurement. It dispatches four parallel scan agents. Agent A measures everything that loads at conversation start — CLAUDE.md files, always-loaded rules, and the memory index — sorted by size. Agent B covers on-demand assets, MCP server enablement, Python runtime availability, path hygiene, naming hygiene, and skill/agent/rule-writing compliance checks (missing Execution-Discipline preambles, "Optional" headings, narrative padding, broken artifact references, oversize files, non-canonical `paths:` shapes). Agent C checks help-doc coverage and staleness against each plugin's README `## Scenarios` list. Agent D audits the expert runtime across ten sub-checks: `lazy.settings.json[experts]` schema (D1), agent reference resolution (D2), aspect reference resolution (D8), arguments key and size validation (D9), `.memory/` directory hygiene (D10), flat `daemon`/`routines` section schema (D3), routine command resolvability (D4), orphan job directories (D5), stale completed jobs (D6), and daemon liveness (D7). No changes are made.

**`/lazy-core.doctor`** is the deeper, interactive health check. It dispatches three parallel scan agents to check artifact integrity, config and memory health, and path hygiene across all config files. After collecting findings it checks plugin version currency, applies release-mode suppression so outdated-plugin content findings don't crowd out the root cause, reconciles against your stored per-WARN waivers, and delegates to sibling audit skills (`lazy-guard.check-public`, `lazy-log.audit`, and plugin-specific audits when those plugins are enabled). It re-runs the full D1–D10 expert runtime checks inline. Then it offers targeted fixes — applying them only after your explicit confirmation — and a per-WARN waive loop where each remaining warning can be permanently suppressed with a waiver file.

**`/lazy-core.optimize`** addresses the two most common sources of bloat. For each rule file over 3 KB it classifies every section as a constraint (a prohibition or one-liner fact needed every turn) or reference material (layouts, tables, procedures, API details), shows the classification, and on confirmation rewrites the rule to constraints only and moves reference material into the agent definition. Phase 2.5 runs an LLM-readability audit across all rules, skills, agents, and commands — flagging decision-logic tables, abstract-header tables, narrative preambles, restated cross-references, decorative markers, and long explanatory paragraphs — and offers rewrites with a diff preview per finding. Phase 5.5 adds expert memory hygiene: orphan notes and near-duplicate note pairs within the same expert's `.memory/` directory are surfaced for interactive resolution. On the settings side it audits global `~/.claude/settings.json` for project-specific entries and migrates them to `settings.local.json`. It closes by running `/lazy-core.agent-models` to fill any missing model-routing entries.

**`/lazy-core.setup`** is the shortcut for a fresh project bootstrap when you have multiple lazycortex plugins enabled. Step 0 migrates `.claude/lazy.settings.json` through the current per-section version ladder before any installer reads or writes it — if migration fails, the run aborts immediately. Then it scans every enabled plugin for `<namespace>.install` skills and any skill opting in via `lazy_setup_phase:` frontmatter, builds a dependency-ordered execution plan with `lazy-core.install` always first, shows a preview, and runs each child in sequence after a single confirmation. Children that fail are logged but don't abort the loop; you get one coherent summary at the end. Pass `--dry-run` to see the plan without executing.

## How they work together

The five skills form a directed pipeline. `/lazy-core.install` (or `/lazy-core.setup`) lands first and lays the foundation every other skill assumes: rules in the right directory, `lazy.settings.json` seeded, `.logs/` and `.runtime/` bootstrapped. If any rules were created or updated, restart Claude Code before proceeding — rules load only at session start.

Once the installation is complete, `/lazy-core.audit` gives you a read-only snapshot of what is actually loaded. Run it right after install to confirm the rules landed, measure your startup context weight, and see the merged model-routing view. The audit's Agent D sub-checks are the first indication of whether your expert runtime config is structurally sound; its Agent C sub-checks tell you whether help-doc coverage is current for all your plugins. Because audit makes no changes, you can run it at any time — after adding a rule, after enabling a new MCP server, before a release.

`/lazy-core.doctor` goes deeper when something feels off. It reads everything the audit reads and more — config consistency across all four settings files, always-loaded context budget (WARN at 20 KB, FAIL at 40 KB), hook registration hygiene, MCP permission wildcard detection, cross-reference integrity, and the full D1–D10 expert runtime sweep. It also checks whether your installed plugins are current against the marketplace manifest and offers to restart a stalled daemon, delete orphan job directories, or unregister routines whose plugin bin path has gone missing. Run doctor periodically or whenever the audit surfaces a pattern you want to investigate interactively.

`/lazy-core.optimize` acts on the cost side. When audit or doctor reports oversized rules or settings leakage, optimize is the remediation path: it slims the rules, moves reference material to the right place, patches settings hygiene, and ensures every agent in your vault has a model-routing tier. Because it rewrites files, always run it after — not before — an audit or doctor pass so you know what you're trimming.

The full journey for a new project: install → restart → audit → doctor if anything looks off → optimize if context is heavy. For an existing project after `/plugin update`: re-run install (or setup) to pick up new rule templates, restart, then audit to confirm the new rules landed cleanly.

## Common adjustments

**Project scope vs user scope** — `/lazy-core.install` detects whether the plugin is enabled at user or project scope and installs rules and templates to the matching directory. If you have both scopes, it asks which to target. For most workflows the project scope (`<repo-root>/.claude/`) is correct; user scope (`~/.claude/`) installs the hygiene and security rules into every project without re-running per-repo.

**Skipping the expert runtime** — during install, Steps 9–13 cover the runtime daemon and expert wizard. You can decline all of them without affecting the rule and settings steps; choose "Skip — this repo doesn't need runtime/experts" when prompted. Re-run `/lazy-core.install` later to set them up when ready.

**Skipping the daemon supervisor** — if you prefer to start the expert-pump daemon manually (`bash .claude/bin/lazy.runtime.sh`), choose "Skip — I'll start the daemon manually" when `/lazy-core.install` offers to install the launchd or systemd unit. The supervisor is a convenience, not a requirement.

**Adding experts after initial install** — re-run `/lazy-core.install` to run the expert-add wizard again. It filters out already-registered experts so only new candidates are presented.

**Configuring the expert-spawn sandbox** — re-run `/lazy-core.install` and confirm Step 13.5 to have the skill merge the recommended sandbox and permissions block into `settings.local.json`. The skill unions into your existing keys rather than overwriting them.

**Previewing the setup chain** — run `/lazy-core.setup --dry-run` to see the ordered list of install skills that would run, grouped by phase, with no changes applied.

**Filling missing model-routing entries** — run `/lazy-core.agent-models` directly (or let `/lazy-core.optimize` Phase 7 do it) to assign haiku/sonnet/opus tiers to newly discovered agents without running the full optimize pipeline.

**Checking aspect and arguments health** — run `/lazy-core.audit` and look at the Expert runtime section. D8 reports any unresolvable aspect references; D9 flags argument keys that don't match `^[a-z][a-z0-9_]*$` or payloads over 4 KB. D10 reports `.memory/` orphans, persona-mark mismatches, and tag-file drift.

**Settings migration failed during setup** — if `/lazy-core.setup` aborts at Step 0, read the captured stderr in the Step 6 report. A non-zero exit typically means a malformed migration callable in the `lazy_settings_migrations/` ladder. Fix the root cause, then re-run `/lazy-core.setup`.

**Stale hook registrations from retired plugins** — if you see references to a `lazycortex-log` plugin path in your hook pipeline, re-run `/lazy-core.install`. Step 8 automatically strips those stale entries from all four standard settings paths.

**Re-running after `git clone`** — rules, templates, `lazy.settings.json`, and `lazy.runtime.sh` are committed into the repo, but daemon supervisor units (launchd plist / systemd service) are per-machine and not committed. Re-run `/lazy-core.install` after cloning to install the supervisor for the current machine and to pick up any newer shipped plugin versions.

## Where this fits

Every other lazycortex plugin assumes that `lazy.settings.json` exists and carries the `agent_models` structure, that the scaffold registry in `.claude/templates/core/` is populated, and that the always-loaded hygiene and security rules are in place. Those are all artifacts of `/lazy-core.install`. Other plugins' own install-and-audit documentation covers their plugin-specific bootstrap, but each starts from a foundation that core has already laid.

The audit and doctor can run at any time without side effects and do not require install to have completed first — though their findings are more meaningful once the plugin is properly bootstrapped.

For public-repo safety, see the **guardian** block: `/lazy-repo.mark-public` creates `.guard-waivers.json`, which also activates the pre-commit hook for every subsequent commit. For the async expert team, see the **runtime**, **experts**, and **memory** blocks — their setup walkthroughs pick up where this block's install step leaves off.

## Bootstrap order
