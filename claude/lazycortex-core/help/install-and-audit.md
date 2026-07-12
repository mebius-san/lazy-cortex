---
chapter_type: block
summary: Bootstrap and verify lazycortex-core — the shared scaffolding layer every other plugin depends on.
last_regen: 2026-07-12
diagram_spec:
  anchor: "Bootstrap order"
  request: "Flowchart of the single-plugin vs multi-plugin bootstrap path — install/setup, optional restart, audit, and the optional optimize+doctor branch — ending at bootstrap complete."
source_skills:
  - lazy-core.install
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.optimize
  - lazy-core.setup
  - lazy-core.autosetup
  - lazy-core.autocheckup
---
# Install, audit, and maintain lazycortex-core

Every lazycortex plugin ships lifecycle skills — install, audit, doctor, optimize, and setup. For most plugins those skills are scoped to their own rules and config. For `lazycortex-core` the stakes are higher: core ships the shared scaffolding every other plugin assumes is already in place — the rule authoring templates, the `lazy.settings.json` runtime structure, the agent-model routing layer, and the expert runtime daemon. Bootstrapping core is bootstrapping the whole lazycortex baseline.

This block covers all five of core's interactive lifecycle skills, plus two non-interactive maintenance agents — `lazy-core.autosetup` and `lazy-core.autocheckup` — for driving the same install and checkup logic across many repos without stopping for questions. The order the interactive skills run in and the way they build on each other is what matters; the two agents are a separate, unattended path for repos that already have their first-run decisions on record.

**Prerequisite:** all lazycortex plugins require Python 3.12 or later. `/lazy-core.install` verifies this at Step 0 and aborts with install instructions if the floor is not met — nothing else in this block runs until Python 3.12+ is available.

## What's in this block

**`/lazy-core.install`** is the foundation step. Run it once per project (or globally) right after enabling the plugin and restarting Claude Code. It syncs every rule template the plugin ships into the correct rules directory, copies authoring templates into `.claude/templates/core/`, and bootstraps the scaffold registry. It then seeds `lazy.settings.json` with the three built-in agent-model routing defaults and adds `.logs/`, `.runtime/`, and `.lazyignore` to the repo. After the rules and settings groundwork is in place, it registers expert candidates: any agent file in an enabled plugin that carries `expert_protocol:` frontmatter is added to `lazy.settings.json[experts]` — this happens regardless of whether you use the background daemon, because experts are also dispatched interactively. Step 10.5 bootstraps `.memory/` for the same reason. Behind two remembered gates — `daemon.enabled` (does this project use the background daemon at all? — a project-wide policy shared with everyone who clones the repo) and `daemon.run_here` (run it for this checkout? — a per-working-copy choice, so several checkouts of the project on one machine each decide independently) — it also sets up the daemon routines and installs a launchd or systemd supervisor (named per checkout so two same-named checkouts don't collide). When the daemon runs for this checkout, Step 13.6 offers to provision Prometheus-style metrics: a free loopback port is allocated automatically and reused on re-run, the enablement flag and repo label are written to tracked `lazy.settings.json` (shared across every clone), the allocated port itself goes only into this checkout's gitignored local overlay (a port free on one machine may be taken on another), and a host-wide scrape-targets file is regenerated so an external Prometheus with `file_sd_configs` picks up every enabled checkout on the machine with zero manual edits. The skill is idempotent — re-running after a plugin update picks up new rule templates without clobbering rules you chose to keep local.

**`/lazy-core.audit`** is the read-only context-weight and compliance measurement. It first runs a set of inline logging-compliance checks — confirming the logging rule is installed, `.logs/` and `.runtime/` exist and are gitignored, and any `logging-waiver:` frontmatter carries a concrete reason rather than a placeholder — then dispatches four parallel scan agents. Agent A measures everything that loads at conversation start — CLAUDE.md files, always-loaded rules, and the memory index — sorted by size. Agent B covers on-demand assets, MCP server enablement, Python runtime availability, path hygiene, naming hygiene, and skill/agent/rule-writing compliance checks (missing Execution-Discipline preambles, "Optional" headings, narrative padding, broken artifact references, oversize files, non-canonical `paths:` shapes). Agent C checks help-doc coverage and staleness against each plugin's README scenario list. Agent D audits the expert runtime across ten sub-checks: `lazy.settings.json[experts]` schema (D1), agent reference resolution (D2), aspect reference resolution (D8), arguments key and size validation (D9), `.memory/` directory hygiene (D10), flat `daemon`/`routines` section schema (D3), routine command resolvability (D4), orphan job directories (D5), stale completed jobs (D6), and daemon liveness (D7). No changes are made.

**`/lazy-core.doctor`** is the deeper, interactive health check. It dispatches three parallel scan agents to check artifact integrity, config and memory health, and path hygiene across all config files. After collecting findings it checks plugin version currency against the live marketplace manifest, then applies release-mode suppression — if an installed plugin is outdated, content-level findings on its synced rule files are suppressed until you upgrade, so the version-outdated warning is the only thing you see. It then reconciles findings against your stored per-warning waivers and delegates to sibling audit skills (`lazy-guard.check-public`, `lazy-log.audit`, and plugin-specific audits when those plugins are enabled). It re-runs the full D1–D10 expert runtime checks inline. Then it offers targeted fixes — applying them only after your explicit confirmation — and a per-warning waive loop where each remaining warning can be permanently suppressed with a waiver file.

**`/lazy-core.optimize`** addresses the two most common sources of bloat. For each rule file over 3 KB it classifies every section as a constraint (a prohibition or one-liner fact needed every turn) or reference material (layouts, tables, procedures, API details), shows the classification, and on confirmation rewrites the rule to constraints only and moves reference material into the agent definition. Phase 2.5 runs an LLM-readability audit across all rules, skills, agents, and commands — flagging decision-logic tables, abstract-header tables, narrative preambles, restated cross-references, decorative markers, and long explanatory paragraphs — and offers rewrites with a diff preview per finding. Phase 5.5 adds expert memory hygiene: orphan notes and near-duplicate note pairs within the same expert's `.memory/` directory are surfaced for interactive resolution. On the settings side it audits global `~/.claude/settings.json` for project-specific entries and migrates them to `settings.local.json`. It closes by running `/lazy-core.agent-models` to fill any missing model-routing entries.

**`/lazy-core.setup`** is the shortcut for a fresh project bootstrap when you have multiple lazycortex plugins enabled. Step 0 migrates `.claude/lazy.settings.json` through the current per-section version ladder before any installer reads or writes it — if migration fails, the run aborts immediately. Then it scans every enabled plugin for `<namespace>.install` skills and any skill opting in via `lazy_setup_phase:` frontmatter, builds a dependency-ordered execution plan with `lazy-core.install` always first, shows a preview, and runs each child in sequence without a top-level confirmation prompt. Children that fail are logged but don't abort the loop; you get one coherent summary at the end. Pass `--dry-run` to see the plan without executing.

**`lazy-core.autosetup`** is the non-interactive twin of `/lazy-core.setup`, built for rolling an install-chain update out across many repos at once instead of running the wizard in each one by hand. You dispatch it (directly, or from your own cross-project rollout loop) with a `repo=<absolute path>` argument; it never asks a question. It refuses to touch a repo with a dirty working tree or an unusable git identity, then walks every applicable `<namespace>.install` skill against the target repo the same way `/lazy-core.setup` would — "applicable" is resolved from the target repo's own enabled plugins (its `settings.json` / `settings.local.json`), never the machine-wide plugin cache, so a repo that enables only two plugins never receives the install chains of plugins enabled elsewhere on the host. Any step that skill would normally resolve via `AskUserQuestion` is skipped and reported as `needs-interactive` instead of guessed. Steps that are derivable or already on record (a persisted `daemon.enabled` gate, a conflict-free file sync, a registry upsert) apply exactly as the skill prescribes — and a plugin-shipped defaults table counts as a recorded decision too: when a step's own skill declares a non-interactive resolution for it, autosetup follows that resolution instead of skipping the step. `/lazy-core.agent-models`, for instance, auto-accepts curated tiers from its `default-tiers.json` table for newly discovered agents — autosetup applies those tiers silently rather than reporting them as `needs-interactive`. Only genuine first-time or preference decisions (a daemon gate never answered, a model tier that isn't in the curated table) still come back `needs-interactive`. It commits its own changes in the target repo under that repo's local identity, with no push. Because it only ever executes decisions that are already recorded or resolvable from a plugin-shipped defaults table, it is not a substitute for the first-time `/lazy-core.install` or `/lazy-core.setup` run — a repo with nothing on record mostly comes back reporting `needs-interactive`.

**`lazy-core.autocheckup`** is the non-interactive twin of the checks `/lazy-core.checkup` orchestrates. Dispatched the same way, with `repo=<absolute path>`, it runs the full read-only audit/doctor sweep against the target repo and collects findings in the usual `PASS` / `WARN` / `FAIL` vocabulary — scoped, like autosetup, to whichever plugins that repo itself has enabled, not every plugin present anywhere on the host machine. It then applies a fix only when the fix is mechanically derivable with no operator preference involved — regenerating an install-managed mirror from its plugin source, creating a directory or registry entry an install skill would create silently, resyncing a derived file from its source of truth, or pinning an unpinned agent model whose dispatch string already has a tier in the default-tiers table. Anything content-shaped, destructive, preference-shaped, or normally resolved via `AskUserQuestion` is left as a reported finding, never applied. Like autosetup, it refuses a dirty tree, commits only the files it touched under the repo's local identity, and never pushes.

## How they work together

The five interactive skills form a directed pipeline. `/lazy-core.install` (or `/lazy-core.setup`) lands first and lays the foundation every other skill assumes: rules in the right directory, `lazy.settings.json` seeded, `.logs/` and `.runtime/` bootstrapped, experts registered. If any rules were created or updated, restart Claude Code before proceeding — rules load only at session start.

Once the installation is complete, `/lazy-core.audit` gives you a read-only snapshot of what is actually loaded. Run it right after install to confirm the rules landed, measure your startup context weight, and see the merged model-routing view. The audit's Agent D sub-checks are the first indication of whether your expert runtime config is structurally sound; its Agent C sub-checks tell you whether help-doc coverage is current for all your plugins. Because audit makes no changes, you can run it at any time — after adding a rule, after enabling a new MCP server, before a release.

`/lazy-core.doctor` goes deeper when something feels off. It reads everything the audit reads and more — config consistency across all four settings files, always-loaded context budget (WARN at 20 KB, FAIL at 40 KB), hook registration hygiene, MCP permission wildcard detection, cross-reference integrity, and the full D1–D10 expert runtime sweep. It also checks whether your installed plugins are current against the marketplace manifest and applies release-mode suppression so stale plugin findings don't crowd out the root cause. It offers to restart a stalled daemon, delete orphan job directories, or unregister routines whose plugin bin path has gone missing. Run doctor periodically or whenever the audit surfaces a pattern you want to investigate interactively.

`/lazy-core.optimize` acts on the cost side. When audit or doctor reports oversized rules or settings leakage, optimize is the remediation path: it slims the rules, moves reference material to the right place, patches settings hygiene, and ensures every agent in your vault has a model-routing tier. Because it rewrites files, always run it after — not before — an audit or doctor pass so you know what you're trimming.

The full journey for a new project: install → restart → audit → doctor if anything looks off → optimize if context is heavy. For an existing project after `/plugin update`: re-run install (or setup) to pick up new rule templates, restart, then audit to confirm the new rules landed cleanly.

`lazy-core.autosetup` and `lazy-core.autocheckup` sit outside that per-project pipeline — they exist for the moment you have many repos that already went through the interactive path once and just need the same update or checkup applied everywhere without repeating the wizard in each one. Point a cross-project rollout loop at each repo path and dispatch the matching agent per repo; each repo's own enabled-plugin set decides what runs there, so repos with different plugin combinations on the same machine never cross-contaminate each other's install chains. Anything that would require a first-time decision comes back as `needs-interactive` for you to resolve the normal way, in that one repo, with the interactive skill.

## Common adjustments

**Project scope vs user scope** — `/lazy-core.install` detects whether the plugin is enabled at user or project scope and installs rules and templates to the matching directory. If you have both scopes, it asks which to target. For most workflows the project scope (`<repo-root>/.claude/`) is correct; user scope (`~/.claude/`) installs the hygiene and security rules into every project without re-running per-repo.

**Skipping the daemon while keeping experts** — during install, the two daemon gates are asked once each. Answering "No" to `daemon.enabled` permanently skips all daemon-only setup (routines, supervisor, sandbox, metrics), but expert registration and the `.memory/` directory still bootstrap — experts work in interactive dispatch too, not only through the daemon. Answering "No" to `daemon.run_here` skips the supervisor and metrics provisioning on this machine while leaving the project's daemon config intact for other checkouts.

**Skipping the daemon supervisor** — if you prefer to start the expert-pump daemon manually (`bash .claude/bin/lazy.runtime.sh`), choose "Skip — I'll start the daemon manually" when `/lazy-core.install` offers to install the launchd or systemd unit. The supervisor is a convenience, not a requirement.

**Adding experts after initial install** — re-run `/lazy-core.install` to pick up newly discovered expert candidates. It filters out already-registered experts so only new candidates are added.

**Configuring the expert-spawn sandbox** — re-run `/lazy-core.install` and confirm Step 13.5 to have the skill write the recommended sandbox block into `.runtime/sandbox.settings.json` (the daemon-owned file passed via `--settings` to every spawned expert subprocess) and union the permissions and `additionalDirectories` scope into `.claude/settings.local.json`. The sandbox and permission files are separate because the sandbox settings apply only to daemon-spawned experts, never to your interactive session. If you previously had a `sandbox` key directly in `settings.local.json` (written by an older install), Step 13.5 removes it automatically and moves the block to the correct runtime file.

**Enabling the metrics endpoint** — Step 13.6 only asks once, and only on a checkout where the daemon is actually running (`daemon.run_here = true`). If you declined at install time, re-run `/lazy-core.install`: it reads the recorded `daemon.metrics.enabled` flag silently on re-run and never re-asks. To revisit the decision, edit the flag in `lazy.settings.json` and re-run `/lazy-core.install` — it will allocate a port, write the repo label, and regenerate the scrape-targets file. Because the allocated port lives only in this checkout's gitignored local overlay, cloning the repo onto a second machine re-runs port allocation independently rather than inheriting a possibly-taken port.

**Previewing the setup chain** — run `/lazy-core.setup --dry-run` to see the ordered list of install skills that would run, grouped by phase, with no changes applied.

**Filling missing model-routing entries** — run `/lazy-core.agent-models` directly (or let `/lazy-core.optimize` Phase 7 do it) to assign haiku/sonnet/opus tiers to newly discovered agents without running the full optimize pipeline.

**Checking aspect and arguments health** — run `/lazy-core.audit` and look at the Expert runtime section. D8 reports any unresolvable aspect references; D9 flags argument keys that don't match `^[a-z][a-z0-9_]*$` or payloads over 4 KB. D10 reports `.memory/` orphans, persona-mark mismatches, and tag-file drift.

**Settings migration failed during setup** — if `/lazy-core.setup` aborts at Step 0, read the captured stderr in the Step 6 report. A non-zero exit typically means a malformed migration callable in the `lazy_settings_migrations/` ladder. Fix the root cause, then re-run `/lazy-core.setup`.

**Stale hook registrations from retired plugins** — if you see references to a `lazycortex-log` plugin path in your hook pipeline, re-run `/lazy-core.install`. Step 8 automatically strips those stale entries from all four standard settings paths.

**Re-running after `git clone`** — rules, templates, `lazy.settings.json`, and `lazy.runtime.sh` are committed into the repo (so `daemon.enabled` travels with the clone), but daemon supervisor units (launchd plist / systemd service), `daemon.run_here`, and the allocated metrics port live in this checkout's gitignored local overlay and are not committed — each working copy decides for itself. Re-run `/lazy-core.install` after cloning to install the supervisor for this checkout. It reads both daemon gates silently when they're already on record — if `daemon.run_here` is unset, it asks once for this checkout.

**Re-run never asks about the daemon again** — once both gate values are on record (`daemon.enabled` in tracked settings, `daemon.run_here` in the gitignored local overlay), install is silent on re-run. To revisit a decision, edit or delete the relevant flag and re-run `/lazy-core.install`.

**Dev-mode supervisor** — if this repo is a plugin-authoring vault, re-run `/lazy-core.install` and the dev-mode flag is derived automatically (detected by the presence of `plugin.json` files under `claude/`). The supervisor passes `--dev-mode` to `lazy.runtime.sh`, which prefers in-repo plugin sources over the plugin cache. For all other repos the flag is False.

**Settings file auto-migration** — if `/lazy-core.doctor` or `/lazy-core.audit` warns that `lazy.settings.json` has a root `version` key, run any lazy-core skill (such as `/lazy-core.audit`) to trigger the one-time automatic migration: the settings loader rewrites the file to the current per-section `_version` format on its first read and removes the legacy root key.

**Rolling an update out across many repos** — dispatch `lazy-core.autosetup` once per repo path from a cross-project rollout loop rather than running `/lazy-core.setup` interactively in each checkout. It is meant for repos that have already been through a first-time install — it will not make the first-time decisions for you. Each dispatch reads the target repo's own enabled-plugin set, so a rollout loop touching repos with different plugin combinations installs the right chain in each one rather than the union of everything on the machine.

**A repo comes back `needs-interactive` from autosetup or autocheckup** — this means the step it hit is genuinely a first-time or preference decision (a daemon gate never answered, a file conflict, a model tier not in the default-tiers table). Open that repo and run the equivalent interactive skill (`/lazy-core.install`, `/lazy-core.setup`, or `/lazy-core.doctor`) once to put the decision on record; subsequent autosetup/autocheckup passes on that repo will apply it silently from then on.

**Autosetup or autocheckup reports `skipped-dirty` or `skipped-identity`** — the target repo had uncommitted changes, or the recorded git identity looked wrong for the repo's remote (e.g. a private-persona email against a public GitHub remote). Neither agent will touch a repo in that state. Commit or stash the working tree, or fix `git config user.email` in that repo, then re-dispatch.

**A plugin enabled in the repo but missing from the machine's plugin cache** — autosetup and autocheckup report that plugin's step as `skipped: plugin not installed on this machine` rather than failing the whole run. Install the plugin through the marketplace on that machine (or run its install chain interactively there), then re-dispatch to pick it up.

## Where this fits

Every other lazycortex plugin assumes that `lazy.settings.json` exists and carries the `agent_models` structure, that the scaffold registry in `.claude/templates/core/` is populated, and that the always-loaded hygiene and security rules are in place. Those are all artifacts of `/lazy-core.install`. Other plugins' own install-and-audit documentation covers their plugin-specific bootstrap, but each starts from a foundation that core has already laid.

The audit and doctor can run at any time without side effects and do not require install to have completed first — though their findings are more meaningful once the plugin is properly bootstrapped.

For public-repo safety, see the **guardian** block: `/lazy-repo.mark-public` creates `.guard-waivers.json`, which also activates the pre-commit hook for every subsequent commit. For the async expert team, see the **runtime**, **experts**, and **memory** blocks — their setup walkthroughs pick up where this block's install step leaves off.

## Bootstrap order

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  enablePlugin[Enable plugin and restart]
  installPath{Single or multi-plugin?}
  singleInstall[/lazy-core.install]
  multiSetup[/lazy-core.setup]
  rulesChanged{Rules changed?}
  secondRestart[Restart Claude Code]
  runAudit[/lazy-core.audit]
  auditResult{Audit passed?}
  resolveIssues[Resolve issues]
  optimizeGuard{Run optimize and doctor?}
  runOptimize[/lazy-core.optimize]
  runDoctor[/lazy-core.doctor]
  bootstrapComplete[Bootstrap complete]

  enablePlugin -->|trigger| installPath
  installPath -->|single-plugin| singleInstall
  installPath -->|multi-plugin| multiSetup
  singleInstall -->|done| rulesChanged
  multiSetup -->|done| rulesChanged
  rulesChanged -->|yes| secondRestart
  rulesChanged -->|no| runAudit
  secondRestart -->|restarted| runAudit
  runAudit -->|results| auditResult
  auditResult -->|fail| resolveIssues
  resolveIssues -->|re-audit| runAudit
  auditResult -->|pass| optimizeGuard
  optimizeGuard -->|yes| runOptimize
  runOptimize -->|next| runDoctor
  runDoctor -->|done| bootstrapComplete
  optimizeGuard -->|no| bootstrapComplete

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef error fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px

  class enablePlugin entry
  class installPath guard
  class rulesChanged guard
  class auditResult guard
  class optimizeGuard guard
  class singleInstall action
  class multiSetup action
  class secondRestart action
  class runAudit action
  class resolveIssues error
  class runOptimize action
  class runDoctor action
  class bootstrapComplete success
```
