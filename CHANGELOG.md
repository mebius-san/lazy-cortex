# Changelog

User-visible changes per plugin release. Each plugin in this marketplace is versioned independently via SemVer.

## lazycortex-core

### 0.2.49 — 2026-04-28

- `default-tiers.json` is now the single source of truth for per-agent model tiers. The previous `lazy.settings.recommended.md` rule duplicated each plugin's tier block; it has been rewritten as a schema-only document (group definitions, floor cap, tier-choice heuristic, pointers to the canonical JSON). `/lazy-core.install`, `/lazy-log.install`, and `/lazy-obsidian.install` now read tier seeds from `default-tiers.json` at runtime via the cross-plugin cache (`~/.claude/plugins/cache/lazycortex/lazycortex-core/...`) and fail fast if the SOT is missing — no more hardcoded tables to drift.
- Tier flips in `default-tiers.json`: `statusline-setup` haiku → inherit (cheap built-in should not be pinned), `lazy-log.distill` haiku → sonnet, `lazy-log.summary` opus → sonnet. New canonical entries: `lazy-log.bullets` = sonnet (release-block drafting), plus explicit tiers for `superpowers:code-reviewer`, `claude-code-guide`, `memory.optimise`, and `plugin.extractor`.
- `claude/lazycortex-core/references/scaffold-registry.md` renamed to `lazy-core.scaffold-registry.md` so the filename matches the dot-namespace convention already used by its siblings (`lazy-core.parallel-scan.md`, `lazy-core.setup-phases.md`) and the existing log directory. The pointer in `lazy-core.scaffold.md` was updated.

### 0.2.47 — 2026-04-28

- `lazy-core.scaffold` reshaped into a cross-plugin **registry**: a single always-loaded fenced YAML block keyed by plugin directory name (`<plugin-dir>: → template-path → [globs]`). Each plugin owns exactly one top-level key and mutates only that key during install; the reserved `_local:` key carries customer-authored entries and is never touched by install skills. Replaces the previous "every plugin needs its own scaffold" pattern. Structural-keys shape was chosen so ownership is data-level (no comment markers, no out-of-band annotations) and so other plugins' keys survive any install/uninstall cycle byte-for-byte.
- `lazy-core.rule-writing § 3` ("No large code blocks") gains an explicit exemption for fenced data blocks (`yaml`, `json`, `toml`) that are the rule's primary payload — the 10-line cap was written for embedded runnable templates and should not block a registry/schema rule from publishing its content. `lazy-core.audit` rule-writing-compliance check 5 now honors the exemption.
- Template paths in the registry are consumer-relative (`.claude/templates/core/...`) — once the rule is copied into the consumer's `.claude/rules/`, plugin-root expansion no longer applies. Plugins copy their templates into `.claude/templates/<group>/` during install and point their registry entries at the local copies; customers can edit those copies freely.
- Each `lazy-core.*-writing` rule's `paths:` now also covers its own template path under `.claude/templates/core/`, so reading a template at create-time auto-loads the matching authoring contract — the chain (always-loaded scaffold → Read template → path-scoped contract loads) closes without taxing every turn.
- `lazy-core.rule-writing § 1.2` rewrites the `paths:` shape clause: the inline-array form `paths: ["a", "b"]` is **silently ignored by the Claude Code loader** (rules don't fire, no error). Block-list (`- "<glob>"` per line) is the only form that loads. Audit detection unchanged; doc text now matches runtime behaviour.
- Plugin rules `lazy-core.skill-writing`, `lazy-core.agent-writing`, `lazy-core.setup-phases`, and `lazy-diagram.authoring` migrated from inline-array `paths:` to canonical block-list — they were silently not loading at runtime before this fix.
- `/lazy-core.install` gains Step 4 ("Sync authoring templates"): copies `<installPath>/templates/core/*` into `<consumerScope>/templates/core/`, per-template New / Unchanged / Drift handling with diff-shown overwrite prompts. Step list grew from 7 to 8; existing steps renumbered.
- New `claude/lazycortex-core/references/scaffold-registry.md` documents the registry contract end-to-end: schema, plain-scalar policy, install-skill responsibilities (upsert own key, never touch `_local` or other plugins' keys), and `lazy-core.audit` validation hooks (single fenced YAML block, parses valid, no orphan plugin keys). Other plugins' install skills read this when they need to register Class A authoring-contract templates.
- Authoring-notes block in core templates (`{rule,skill,agent,command}-template.md`) renamed from "delete before shipping" to "delete before saving" — there is no shipping step; the file is just `Write`-saved.
- Frontmatter on `lazy-core.scaffold` slimmed to one-line `description:` + terse `always_loaded:` (matching `lazy-core.hygiene` / `lazy-guard.security` shape) — every byte counts in always-loaded context.

### 0.2.46 — 2026-04-28

- New `lazy-core.scaffold` always-loaded index points new artifact creations at copy-pasteable templates under `${CLAUDE_PLUGIN_ROOT}/templates/core/{rule,skill,agent}-template.md`. Closes the create-time gap where path-scoped authoring rules (`lazy-core.{rule,skill,agent}-writing`) only fire on `Read` of an existing matching file — now Claude composing a brand-new rule/skill/agent has a structural pointer to the contract before writing the first line.
- Four new templates under `claude/lazycortex-core/templates/core/`: `rule-template.md` carries canonical block-list `paths:` and the rule-writing clause skeleton; `skill-template.md` carries the Execution-Discipline preamble and phase scaffolding; `agent-template.md` carries the single-response model contract and structured-report block; `command-template.md` carries the multi-phase coordinator shape with an alternative verbatim-output (help-style) shape documented in authoring notes. Each authoring rule (`lazy-core.{rule,skill,agent}-writing`) now opens with a `**Template:**` pointer at the canonical path so the Read-time path also surfaces the link.
- `/lazy-core.audit` rule-writing compliance gains check 9: authoring contracts (`*.writing.md` filenames, or bodies with an "authoring" `## ` heading) WARN when they don't reference a template path under `<plugin>/templates/`. Files matching `**/templates/**/*-template.md` are excluded from all rule-writing checks (skeletons, not rules).
- `/lazy-core.doctor` Phase 4 offers a two-step templated fix for the new WARN: copy the base template to `<plugin>/templates/<group>/<derived-name>-template.md` and prepend a `**Template:**` pointer to the rule body, both shown as a diff before any write.

### 0.2.39 — 2026-04-26

- New `/lazy-core.setup` meta-installer brings the current project up-to-date with every enabled plugin's install + post-install configurator chain in a single run. Discovery is convention-based: any `<namespace>.install` skill in an enabled plugin participates automatically, and any skill that opts in via `lazy_setup_phase:` frontmatter (e.g. `lazy-guard.allow-mcp`, `lazy-core.agent-models`) joins the plan in the right phase (pre-install → per-plugin → post-install) without an edit to the meta-installer. Use after `/plugin update`, on a fresh clone, or after enabling a new plugin. Idempotent. Optional `--dry-run` previews the plan without executing.
- New `lazy-core.setup-phases` rule documents the `lazy_setup_phase:` frontmatter contract — allowed values, ordering, and the anti-pattern for skills already chained from inside another install flow (so they don't double-run).
- `/lazy-core.audit` Agent B gains a fourth skill-writing check: WARNs when a `SKILL.md` declares `lazy_setup_phase:` with a value outside `{pre-install, per-plugin, post-install}`.

### 0.2.38 — 2026-04-26

- New `/lazy-core.checkup` unified read-only health command that orchestrates every audit/doctor skill this repo ships (`lazy-core.audit`, `lazy-core.doctor`, `tool.audit`, `tool.doctor`), merges findings into a per-plugin table, and prompts for which mutating fix-flow to run next (`lazy-core.optimize`, `tool.optimize`, doctor fix loops, or `pub.status`). Gracefully handles consumer-only repos by probing for author-side skills before invoking them.
- **Fix:** `/lazy-core.doctor`'s destructive-command guard now explicitly excludes `mcp__git__git_commit` from the `ask` bucket, preventing future drift. Doctor agents had been extending the `ask` bucket by analogy and misclassifying git-commit; the exclusion is now locked down in code.

### 0.2.34 — 2026-04-24

- `/lazy-core.agent-models` is now batch-mode: three grouped prompts (curated defaults / system + other plugins / project agents) each let you accept-all, review one-by-one, mass-set every entry in the batch to `inherit`, or skip the batch — instead of one prompt per agent. The per-agent picker (now only fired when you explicitly choose "review each individually") offers four choices: suggested tier / `inherit` / next-closest tier / skip — restoring the previously-missing `inherit` option that the prior six-option layout dropped.
- New canonical-tier template at `claude/lazycortex-core/skills/lazy-core.agent-models/default-tiers.json` records the recommended tier per known dispatch string — built-ins (`Explore=haiku`, `Plan=opus`, `general-purpose=inherit`, `statusline-setup=haiku`), LazyCortex agents (`lazy-log.summary=opus`, `lazy-log.distill=haiku`, `lazy-log.recall=sonnet`, `lazy-log.timeline=haiku`, `obsidian.gen-tag-pages=sonnet`), and `superpowers:code-reviewer=opus`. The wizard's first batch is built from this template, so accepting it routes ~10 agents in one prompt.
- New `lazy-core.agent-writing § 8`: when creating a new agent in a repo where `lazy.settings.json` exists, the author MUST register its model tier (consult `default-tiers.json` first, heuristic fallback) — and promote canonical defaults back to the template when the dispatch is one every install should get. `lazy-core.audit` Agent B coverage extended to enforce.

### 0.2.32 — 2026-04-24

- New `/lazy-core.agent-models` standalone wizard for assigning per-agent model tiers (`haiku` / `sonnet` / `opus` / `inherit`) without paying for the full `/lazy-core.optimize` pipeline. `--scope=auto` (default) routes each entry to its structurally-correct file: `_user.*` and `_builtin.*` go global, `_project.*` goes project, plugin-domain groups follow the plugin's install scope. `--scope=project|global` overrides; `--dry-run` previews. A single run can write to both global and project `lazy.settings.json` files. `/lazy-core.optimize` Phase 7 now delegates here.
- `/lazy-core.install` per-rule prompts now surface each rule's `description:` from frontmatter as **Purpose:** so you can decide install / overwrite / delete on a New, Drift, or Orphan rule without remembering what the file does. Drift prompts show the full diff inline with What-changed and Why-you-are-seeing-this framing; orphan prompts explain that the plugin no longer ships the rule. Step 5 (`lazy.settings.json` seed) now prints scope, structure, auto-routing, and precedence context above the permission prompt.
- Stripped narrative padding from the `lazy-guard.security` rule — removed a glob-syntax tutorial and a `claude/**` example that was triggering cosmetic drift on every consumer install of the rule and bloating an always-loaded file.

### 0.2.30 — 2026-04-24

- New `lazy-core.agent-model-router` PreToolUse hook routes every `Agent` dispatch to a configured model (`haiku` / `sonnet` / `opus` / `inherit`) via a shared `.claude/lazy.settings.json`. Agents that ship with `model: inherit` can now be cheap-by-default per project without plugins having to hardcode a tier. Set `LAZY_AGENT_MODEL_FLOOR=haiku|sonnet|opus` for a session-wide cap (wins over caller-supplied `model`). Config uses a grouped schema: `_builtin` (Explore, Plan, general-purpose), `_user` (`~/.claude/agents/*.md`), `_project` (`./.claude/agents/*.md`), and per-vendor domains for installed plugins.
- `/lazy-core.install` now seeds `.claude/lazy.settings.json` with defaults for the three built-in dispatch names (`Explore`→haiku, `Plan`→opus, `general-purpose`→inherit) plus empty `_user` / `_project` slots for `/lazy-core.optimize` to fill.
- `/lazy-core.audit` and `/lazy-core.doctor` gain a **Model routing** section: merged-with-provenance view across project + global scopes, orphan/gap detection, invalid-value reporting, env-var status, and a WARN when no `lazy.settings.json` is found at either scope.
- `/lazy-core.optimize` gains a Phase 7 wizard: enumerates every dispatchable agent (built-ins, user-authored, project-authored, plugin-shipped) and fires one `AskUserQuestion` per missing entry — heuristic-driven default tier, or pick haiku/sonnet/opus/inherit/skip. When the config is missing entirely, the wizard first offers to create it (project / global / skip).
- New `lazy.settings.recommended.md` reference doc with copy-paste entries for well-known third-party agents (superpowers, claude-code-guide, statusline-setup, etc.).
- **Rule reorganization:** the authoring-contract rule was split three ways — `lazy-core.skill-writing` (scoped to `.claude/skills/**` and `.claude/commands/**`), `lazy-core.agent-writing` (`.claude/agents/**`), and `lazy-core.rule-writing` (`.claude/rules/**`). Each scope is loaded only when editing the matching artifact type, so authoring a skill no longer drags the agent-frontmatter contract into context (and vice versa). Re-run `/lazy-core.install` to pick up the new rule files.

### 0.2.28 — 2026-04-24

- (Internal release catch-up; no user-facing changes since 0.2.13 — these autobumps accumulated during development. See `docs/changelog.md` for commit-level detail.)

### 0.2.13 — 2026-04-21

- `/lazy-core.optimize` now ships the Phase 2.5 LLM-readability audit: it scans rules, skills, agents, commands, and references for human-oriented constructs (decision-logic tables, narrative preamble, restated cross-references, decorative markers, long explanatory prose) with per-finding Apply / Skip / Waive prompts. Waivers share `lazy-core.doctor`'s `doctor.waivers/` store under the `llm-readability.*` check_id namespace so suppressions carry across both skills.
- `/lazy-core.doctor` gains a permanent WARN-waiver system so reviewed findings can be suppressed across runs. Waivers live in file-based auto-memory by default (reviewable, version-controlled) with a memory-MCP fallback as opt-in; the MCP server name is discovered from the environment rather than hardcoded. Also demotes two "filename lacks dot separator" checks from FAIL to WARN.
- `/lazy-guard.allow-mcp` now infers scope automatically when existing `mcp__<server>__*` entries already pin the server to one scope (global vs. project), eliminating the redundant "which scope?" prompt in the common case. The prompt still appears for first-time server registration or when entries are split across both scopes.

### 0.2.12 — 2026-04-19

- `/lazy-core.doctor` Phase 2.5 no longer WARNs on plugins with unrecorded versions — neither `installed_plugins.json` entries showing `"unknown"` nor marketplace manifests without a `version` field (e.g. GCS-distributed tarballs). Reinstalling doesn't change the manifest format, so the finding was noise. The comparison is now skipped silently when either side lacks a comparable version, and the Phase 2.6 outdated-plugins set is narrowed to match.
- The standalone `no-hardcoded-dynamic-content` rule was folded into `lazy-core.hygiene` as a new "Dynamic content in agents/skills" section — one less always-loaded rule file for consumers. The old file had no dot-namespace prefix and was orphaned; `/lazy-core.install` will prompt to remove it on the next run.

### 0.2.11 — 2026-04-19

- `/lazy-core.doctor` now tracks an **always-loaded context budget**: the summed byte size of `CLAUDE.md` + every rule file without a `paths:` scope. WARN over 20 KB, FAIL over 40 KB. The finding lists per-file sizes largest-first so you can see what's costing tokens on every turn.
- New WARN in `/lazy-core.doctor` for rule files whose frontmatter has neither a `paths:` folder scope nor an `always_loaded: <one-line reason>` waiver. Every unscoped rule without a waiver burns tokens on every turn for every user — the waiver makes the intent explicit. The plugin-shipped `lazy-core.hygiene` and `lazy-guard.security` rules now carry the waiver.
- `/lazy-core.doctor` detects **MCP permission entries with wildcards** (`*`, `?`, `{…}`) and flags them as silent no-ops. Claude Code matches MCP permissions as exact strings, so `mcp__github__*` never matches — the allow/ask never takes effect and every call falls through to the per-call prompt. Fix points at `/lazy-guard.allow-mcp <server>` which enumerates concrete names.
- `/lazy-core.doctor` now distinguishes **local-tool mode** (this repo authors plugins under `claude/**`) from **release mode** (consumer repos). In release mode, if a plugin is outdated per the marketplace-version check, content-level findings on its owned rule files are suppressed — upgrade the plugin first, then re-run to surface any remaining issues. A per-plugin INFO line reports the suppression count.
- `/lazy-core.doctor` trims several never-firing or low-signal checks (Meta-rule mandatory, missing model field, `.claude` allowed-set whitelist, medium-risk-pinned, project `CLAUDE.md` missing, and a handful of others) so the report stays focused on real hygiene issues. Broken-artifact-reference and hook-imports checks are reformulated to reduce false positives.
- `/lazy-core.optimize` thresholds now match the doctor's summed-budget WARN/FAIL so running both in sequence produces consistent verdicts.
- The plugin-shipped `lazy-core.hygiene` and `lazy-guard.security` rule files were slimmed (Meta-rule sections removed, prose compressed) to fit well under the per-file cap with the waiver line added.

### 0.2.9 — 2026-04-19

- **Breaking:** `/lazy-guard.allow-mcp` now uses a 3-bucket classifier. Safe/reversible tools go into `permissions.allow` (no prompt), truly destructive tools go into `permissions.ask` (always prompt), and medium-risk tools stay out of both lists so Claude Code prompts once per call and you decide each time. Default write target flipped to `settings.local.json` (gitignored) so personal permission choices don't leak to teammates through tracked settings. For globally-defined MCP servers the skill asks whether to register at global or project scope. Phase 6.5 strips leaked `mcp__*` entries from the paired tracked `settings.json`.
- `/lazy-core.doctor` now flags per-tool permissions sitting in tracked `settings.json` as leakage and offers an in-place migration to the paired `settings.local.json`. Its MCP hygiene check switched to the same 3-bucket logic — flags destructive tools mis-pinned in `allow`, flags medium-risk tools pinned into either list, and no longer warns about "missing" tools (since `skip` is a valid choice).
- New Phase 2.5 in `/lazy-core.doctor` verifies installed plugins are at the latest marketplace version. Reads `installed_plugins.json`, refreshes each referenced marketplace with a 5s `git fetch` timeout, and WARNs on outdated or unrecorded installs. Transient refresh failures surface as non-blocking INFO.
- The `lazy-core.hygiene` rule's settings-split policy now applies uniformly at both `~/.claude/` and project `.claude/` scopes: tracked `settings.json` owns only enablement flags (`enabledPlugins`, hooks, env, model, statusLine, marketplace registrations) while gitignored `settings.local.json` owns the entire `permissions` block plus machine-specific paths. The `lazy-guard.settings` PreToolUse hook dropped its obsolete "global `settings.local.json` must stay empty" block and now emits a non-blocking warning when per-tool permissions are added to tracked `settings.json`, nudging the edit toward the paired local file.

### 0.2.5 — 2026-04-19

- **Breaking:** `/lazy-guard.allow-mcp` no longer silently allows every tool of an MCP server. It now classifies each `mcp__<server>__*` tool and splits the entries between `permissions.allow` (read-only — get/list/search/recall/…) and `permissions.ask` (destructive — create/update/delete/write/commit/push/retain/…). Ambiguous tools default to `ask` for safety. Re-running the skill after a previous "allow everything" run will **promote** destructive tools from `allow` to `ask`; the Phase 7 report shows `→ allow`, `→ ask`, and `allow→ask` counts so the promotions are explicit.
- `/lazy-guard.allow-mcp` now also strips redundant `mcp__*` entries from `./.claude/settings.local.json` after writing the same entries to the project-tracked `settings.json`. No more stale duplicates accumulating from one-off click-through approvals.
- `/lazy-core.doctor` gains an MCP permissions completeness scan: for every enabled MCP server, it WARNs when a runtime tool is missing from both `permissions.allow` and `permissions.ask`, and WARNs again when a destructive tool is mis-placed in `allow` instead of `ask`. Both findings point at `/lazy-guard.allow-mcp <server>` for the fix.

### 0.2.3 — 2026-04-19

- `/lazy-core.doctor` now cross-references installed rules in `.claude/rules/` against the source files in each owning plugin. Drift (byte-level mismatch) and orphans (namespaced rules the plugin no longer ships) are flagged as WARN and point you at `/<namespace>.install` for reconciliation. Missing rules are intentionally not flagged — the install skill's per-rule prompt lets you skip them deliberately.
- `/lazy-core.install` now asks per rule on install (accept / skip) instead of silently copying every template, shows a diff on drift, and offers to delete orphaned `lazy-core.*` / `lazy-guard.*` rules left over from older plugin versions.
- The coordinator-pattern reference (`lazy-core.parallel-scan`) no longer loads as a rule — it moved under `references/` and is read on-demand by scan skills at dispatch time, shrinking the always-loaded rule set to `lazy-core.hygiene` + `lazy-guard.security`.

### 0.2.2 — 2026-04-18

- New **B4 Author identity in manifests** check in `/lazy-guard.check-public` flags literal author name/email in tracked package manifests (`plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `CITATION.cff`, `README*.md`) and auto-waives matches equal to a new `public_author` block in `.guard-waivers.json`. Setting `public_author` records the approved public identity for a repo so every scan — and every collaborator — sees the same answer without scattering per-match waivers.
- `/lazy-core.doctor` now reads `~/.claude/plugins/installed_plugins.json`, checks each installed plugin's declared dependencies against the actual install set, and WARNs when a required sibling plugin isn't installed.
- `/lazy-core.doctor`'s meta-rule WARN is now scoped — it only fires on rules that actually benefit from a `## Meta-rule` section (size > 3 KB, a paired `<namespace>.config.md` agent, or reference-style structure). Pure-constraint rules under those thresholds no longer produce spurious findings.
- Shipped rules (`lazy-core.hygiene`, `lazy-core.parallel-scan`, `lazy-guard.security`) each carry a one-line `## Meta-rule` section for consistency.

### 0.2.1 — 2026-04-18

- `/lazy-core.install` now installs every rule file shipped by the plugin, discovered via glob. Previously only `lazy-core.hygiene` and `lazy-guard.security` were copied, so new rule files added upstream silently never reached the target project.
- Heavy scan skills (`lazy-core.audit`, `lazy-core.doctor`, `lazy-core.optimize`, `lazy-guard.check-public`) now dispatch parallel Explore subagents internally — scans run faster and consume less main-thread context. User-visible output and interaction are unchanged.
- New `lazy-core.parallel-scan` rule documents the coordinator pattern shared by the refactored scan skills.

### 0.2.0 — 2026-04-17

- New `/lazy-core.help` slash command prints the plugin's purpose and a one-line summary of every skill it ships. Output is verbatim — no tool calls, no log write.

### 0.1.0 — 2026-04-17

- Initial release.
- **Context management** — `lazy-core.audit`, `lazy-core.doctor`, `lazy-core.optimize` measure and slim what Claude Code loads at startup.
- **Security** — `lazy-guard.check-public` scans for leaked secrets, PII, and local paths; `lazy-repo.mark-public` walks a repo through the full public-release flow; a pre-commit hook blocks new leaks.
- **Permissions** — `lazy-guard.allow-mcp` allows every tool of an MCP server in one step, routed to the settings file at the matching scope.
- **Settings protection** — `lazy-guard.settings` hook blocks dangerous edits to `settings.json` / `settings.local.json`.
- **Install** — `lazy-core.install` drops the hygiene and security rule templates into the target project.

## lazycortex-log

### 0.3.1 — 2026-04-26

- New `/lazy-log.clean` skill — interactive housekeeping for `./.logs/claude/`. It classifies every subdirectory against the live set of canonical skills, agents, and commands; surfaces orphans (renamed skills, anonymous subagent runs); and offers per-orphan choices (merge, distill-to-memory, delete, leave) with anonymous subagent clusters batched by pattern so a folder of 25 `task-N` runs becomes one prompt instead of 25. Read-first — every action waits for explicit approval; nothing is mutated until you confirm. Re-run `/lazy-log.install` after upgrade to register the new skill.
- **Fix:** `lazy-log.distill-trigger` Stop hook now stays silent on first run. When `.logs/.distill-trigger-last-mtime` didn't exist (fresh checkout, first install, or never-distilled repo), the hook's gate trivially passed and it fired regardless of whether commits were actually recorded. Bootstrap now writes the current `commits.jsonl` mtime as the baseline and exits silently; only real future advances trigger the distill nudge.

### 0.2.12 — 2026-04-26

- The `lazy-log.distill-trigger` Stop hook no longer fires on every turn — it now activates only on turns where a commit was actually recorded. Two gates must both pass: `.logs/commits.jsonl` mtime advanced this turn, and pending commits exist beyond the `last-distilled-sha` marker. No-commit turns are silent, killing the per-turn distill noise that hit dev-heavy repos hardest. Commits made outside Claude (terminal, cron) don't trip the hook — invoke the distill agent manually to catch up. The mtime is tracked in `.logs/.distill-trigger-last-mtime` (gitignored under `.logs/`).

### 0.2.11 — 2026-04-24

- (No user-facing changes; version autobumped during a publish-state reconciliation commit. See `docs/changelog.md` for commit-level detail.)

### 0.2.10 — 2026-04-24

- `/lazy-log.install` per-rule prompts now surface each rule's `description:` from frontmatter as **Purpose:** so you can install / overwrite / delete a rule on first sight, without remembering what the file does. Drift prompts show the full diff inline with What-changed framing; orphan prompts explain that the plugin no longer ships the rule. Same UX as the polished `/lazy-core.install`.

### 0.2.9 — 2026-04-24

- New `lazy-log.distill-trigger` Stop hook: at session end, compares `.logs/commits.jsonl` against the `last-distilled-sha` marker in `docs/changelog.md` and, when commits are pending, asks Claude to run `lazycortex-log:lazy-log.distill` before the turn ends. Loop-safe via `stop_hook_active`. You no longer need to remember to run distill manually.
- The `lazy-log.logging` rule's "distill after commits (MANDATORY)" section was rewritten to describe the Stop-hook-driven flow. The hard-skip override ("user says don't distill") still applies.
- `/lazy-log.install` seeds four routing entries into `.claude/lazy.settings.json` under the shared `lazycortex` domain group — `lazy-log.distill` and `lazy-log.timeline` default to `haiku` (mechanical rewriters); `lazy-log.recall` and `lazy-log.summary` default to `sonnet` (ranked retrieval / synthesis). Paired with `lazycortex-core` 0.2.30, this cuts distill cost to a fraction of what it was when subagents inherited Opus from the caller.

### 0.2.7 — 2026-04-22

- `/lazy-log.install` now gitignores `docs/changelog.md` in addition to `.logs/`. The distilled changelog is a per-contributor local cache feeding Claude's change-history recall — tracking it in git would cause merge conflicts between teammates, since every distill run rewrites the same file with a single `last-distilled-sha` marker. Existing installs: re-run `/lazy-log.install` to have the skill add `docs/changelog.md` to `.gitignore`. The file stays on disk; only git-tracking changes.

### 0.2.5 — 2026-04-19

- **Breaking:** the `lazy-log.logging` rule now **mandates** running `/lazy-log.distill` after any non-trivial commit. Previously this was worded as "consider" / "guidance, not a hard rule", and in practice distill was skipped and `docs/changelog.md` stayed empty. Trivial commits (typos, formatting, dep bumps) and explicit per-turn user opt-outs still skip.
- The `lazy-log.logging` rule now carries an `always_loaded: <reason>` frontmatter waiver — a new `/lazy-core.doctor` check (see `lazycortex-core` 0.2.11) requires every unscoped rule to justify being in context every turn. No behavior change for existing installs beyond the waiver line.

### 0.2.3 — 2026-04-19

- `/lazy-log.install` now asks per rule on install (accept / skip), shows a diff on drift, and offers to delete orphaned `lazy-log.*` rules from older plugin versions. Matches the new `/lazy-core.install` flow.
- `lazy-log.audit` now reads `lazy-core.parallel-scan` from `lazycortex-core`'s on-demand `references/` directory, matching the core plugin's rule-slimming pass.

### 0.2.2 — 2026-04-18

- `lazycortex-log` now declares `lazycortex-core` as a dependency in `plugin.json`. Users installing only this plugin will see `/lazy-core.doctor` WARN pointing them to install the required sibling.
- The `lazy-log.audit` skill's cross-plugin reference to `lazycortex-core`'s `lazy-core.parallel-scan` rule now explicitly names the owning plugin.

### 0.2.1 — 2026-04-18

- `/lazy-log.install` now installs every rule file shipped by the plugin, discovered via glob. Future-proof for additional rules.
- `lazy-log.audit` now dispatches parallel Explore subagents internally — runs faster and consumes less main-thread context. User-visible output and interaction are unchanged.

### 0.2.0 — 2026-04-17

- New `/lazy-log.help` slash command prints the plugin's purpose and a one-line summary of every skill and agent it ships. Output is verbatim — no tool calls, no log write.

### 0.1.0 — 2026-04-17

- Initial release.
- Per-commit run logging: every skill, agent, and command writes `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` with the current `git_sha`.
- `lazy-log.distill` agent turns raw commits into a readable `docs/changelog.md`.
- `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary` agents search across run logs, changelog, git history, and memory.
- `lazy-log.install` bootstraps the logging rule, `docs/changelog.md`, and the commit-capture hook into a project.
- `lazy-log.audit` verifies the logging rule is installed and coherent.

## lazycortex-specs

### 0.1.7 — 2026-04-26

- (No user-facing changes; internal autobumps from cross-cutting commits — versioning callout sync and a logging-rule description sync. See `docs/changelog.md` for commit-level detail.)

### 0.1.5 — 2026-04-24

- (No user-facing changes; internal plumbing — execution-discipline waiver added to the `lazy-specs.help` command and plugin-dev folder-note gitignore cleanup.)

### 0.1.4 — 2026-04-19

- Internal plumbing — seeded `.claude-plugin/overview.md` so the plugin meets the minimum marketplace surface required by `tool.doctor`. Still a namespace placeholder with no shipped skills; downstream plugins and the marketplace can now depend on the namespace ahead of the first real skill landing. No functional changes.

### 0.1.2 — 2026-04-19

- Internal plumbing — removed an empty `settings.json` stub. No functional changes.

### 0.1.1 — 2026-04-18

- Internal manifest metadata update; no functional changes.

### 0.1.0 — 2026-04-17

- Initial release.

## lazycortex-obsidian

### 0.3.0 — 2026-04-26

- **Fix:** the bundled `iconize-reloader` companion plugin now survives Folder Notes' class-strip race condition. When a folder and its folder-note were created simultaneously, Folder Notes' CSS-class management would strip the icon classes that iconize-reloader had just applied, leaving the note rendering as a sibling until you restarted Obsidian. v2.0.8 polls for elements with a 6-second timeout and attaches MutationObservers that revert any class strips instantly. Re-run `/lazy-obsidian.iconize-install` (or `/lazy-obsidian.update-plugin iconize-reloader`) to pick up the new bundle.
- **Fix:** `/lazy-obsidian.update-plugin` no longer silently resets your Iconize plugin toggles on every update. The shipped `obsidian-icon-folder` settings override was inherited wholesale from an older `data.json` snapshot and re-asserted every Iconize default each run — including `iconsInLinksEnabled: true`, which would clobber any user-set value. The override is now pruned to the three keys iconize-sync actually requires (`iconInFrontmatterEnabled`, `iconInFrontmatterFieldName`, `iconColorInFrontmatterFieldName`); all other user choices survive updates. Re-run `/lazy-obsidian.install` to pick up the slimmer override.
- Removed two `lazy-obsidian.audit` Phase 2 WARNs that scanned the icon-map template for matcher coverage. The template ships with empty matchers by design — consumers author their own in their vault's local `icon-map.json` — so those WARNs always fired on a clean release with no fix path. Matcher-coverage auditing now belongs only to a consumer-side audit of the actual vault's icon-map.

### 0.2.53 — 2026-04-24

- (No user-facing changes; version autobumped during a publish-state reconciliation commit. See `docs/changelog.md` for commit-level detail.)

### 0.2.52 — 2026-04-24

- `/lazy-obsidian.install` Dataview-install prompt and `/lazy-obsidian.iconize-install` protocol-doc prompts now include pre-write context — what the artifact is, why it's being installed, and what you're approving — so per-file decisions during a fresh vault bootstrap have the surrounding rationale instead of just a path.

### 0.2.51 — 2026-04-24

- `/lazy-obsidian.install` seeds `obsidian.gen-tag-pages=sonnet` into `.claude/lazy.settings.json` under the shared `lazycortex` domain group — the tag-page generator blends mechanical indexing with curated summaries, so sonnet is the appropriate default tier.
- **Fix:** `/lazy-obsidian.iconize-install` now enforces structural checklist discipline and installs all three hard-dependency plugins (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader`) up front in a single pass. Previously the dependency installs could be silently skipped mid-run, leaving an inconsistent iconize setup that failed to sync icons on save.

### 0.2.49 — 2026-04-24

- (No user-facing changes; version autobumped during an internal plugin README re-sync.)

### 0.2.48 — 2026-04-24

- **Breaking:** `/lazy-obsidian.config` is removed. Vault-plugin install/update behaviour is now factored into a reusable primitive `/lazy-obsidian.update-plugin <id>` and invoked from two entry points: `/lazy-obsidian.install` (installs Dataview for tag-page rendering; offers to chain into `/lazy-obsidian.iconize-install`) and `/lazy-obsidian.iconize-install` (installs the three iconize-sync hard-dependency plugins itself — `obsidian-icon-folder`, `folder-notes`, and the bundled `iconize-reloader`). `/lazy-obsidian.install` is now the root entry point for the plugin family: a single run bootstraps rules, the tag-page template, Dataview, and optionally the iconize-sync system. The deleted skill's opinionated override merges survive unchanged in `templates/obsidian/plugin-settings.json` — `update-plugin` is the new applier. Templates only referenced by the old config skill (`.lazy-obsidian.manifest.json`, `templates/obsidian/community-plugins.json`) were removed. If you relied on running `/lazy-obsidian.config` directly, switch to `/lazy-obsidian.install` or invoke `/lazy-obsidian.update-plugin <id>` for a single plugin.

### 0.2.7 — 2026-04-22

- (No user-facing changes; version autobumped during an internal plugin README re-sync.)

### 0.2.6 — 2026-04-22

- **Fix:** the bundled `iconize-reloader` companion plugin no longer toggles Iconize on every `data.json` change. The previous toggle behavior raced with Iconize's `onunload` writeback — whenever the icon-map worker wrote fresh entries, the reloader fired, Iconize unloaded, and its stale in-memory state clobbered the fresh write (in Dropbox-synced vaults this also produced `(conflicted copy)` files). It also defeated manual disables: turning Iconize off in Settings sprang it back on within ~250ms. The new reloader refreshes Iconize in place via its `loadData()` + `handleChangeLayout()` API and strips stale icon DOM nodes so folders re-paint correctly. If you manually disable Iconize, it now stays disabled.

### 0.2.5 — 2026-04-22

- **Breaking:** `folderNoteName` in the `folder-notes` plugin override (`templates/obsidian/plugin-settings.json`) changed from `"_folder"` to `"{{folder_name}}"`, matching the existing `newFolderNoteName` / `oldFolderNoteName` templates. After the next `/lazy-obsidian.config` run, the `folder-notes` plugin recognizes `<FolderName>.md` inside each folder as the folder note instead of `_folder.md`. If you have existing `_folder.md` files, rename them to the folder's own name to restore folder-note behavior.

### 0.2.4 — 2026-04-22

- New **Stop-hook safety net** closes a gap in the PostToolUse `Write|Edit` hook: edits that land through `Bash`, shell scripts, bulk renames, or `rg | xargs sed` no longer leave Iconize's `data.json` drifting from your icon-map. At the end of every agent turn, a new `iconize_sync.py reconcile-dirty` subcommand scans `git status` for dirty Markdown files and reconciles each dirty prefix in one batched write. Silent no-op on clean trees, non-git vaults, or when the icon-map isn't installed.
- **Fix (regression in 0.2.0):** the plugin-shipped PostToolUse hook wasn't actually writing icons on agent-initiated edits. Claude Code always supplies an absolute `file_path`, but the worker rejected anything starting with `/` — and the hook swallowed stderr, so the failure was invisible. The worker now relativizes absolute paths against the vault root and silently no-ops for paths outside the vault; the hook stopped discarding stderr so future worker errors surface.
- **Breaking:** `/lazy-obsidian.iconize-configure` is renamed to `/lazy-obsidian.iconize-config`. Update any references in your notes or shell history.
- `/lazy-obsidian.config` is now plugin-scope only — it no longer manages top-level Obsidian settings, `.gitignore`, the vault nickname, or MCP wiring. `vault-nickname`, `obsidian-git`, and `obsidian-linter` were dropped from the musthave list. If you relied on any of these phases, manage them separately.
- Community-plugin binaries are no longer vendored with the plugin. `/lazy-obsidian.config` now fetches the latest `manifest.json` / `main.js` / `styles.css` from each plugin's GitHub release at runtime, and only when the installed version is older than the remote. Plugin updates are always fresh; first-run installs don't download binaries they won't use.
- New opinionated per-plugin override blocks in `templates/obsidian/plugin-settings.json` are deep-merged onto each vault's `<plugin-id>/data.json` after every binary sync via `jq`. Any user keys outside the override block are preserved.
- Companion `iconize-reloader` Obsidian plugin (bundled) watches `obsidian-icon-folder/data.json` and soft-reloads Iconize when the worker writes to it, so new icons appear without restarting Obsidian or toggling the plugin.

### 0.2.0 — 2026-04-21

- **Breaking:** the iconize-sync PostToolUse hook is now shipped by the plugin itself (auto-loaded from `hooks/hooks.json`) instead of being written into your `.claude/settings.json` with a hardcoded plugin path. Consumers upgrading from 0.1.23 or earlier **must re-run `/lazy-obsidian.iconize-install` once** — the install wizard detects and offers to delete the stale PostToolUse entry and migrate the icon-map to the new schema.
- The `.githooks/pre-commit` shim now resolves the worker's plugin path at runtime instead of baking in an absolute `/Users/.../plugins/cache/.../<version>/bin/` path. The shim survives plugin upgrades and machine-to-machine moves, and no longer leaks a local user path into your tracked git hooks.
- New bilateral version handshake between the worker's `SCHEMA_VERSION` / `HOOK_VERSION` constants and the vault's `icon-map.json` — on incompatible drift the hook self-disables silently (exit 0 + stderr diagnostic) so git commits and editor writes never block. `/lazy-obsidian.iconize-sync check-versions` reports the handshake state.
- `/lazy-obsidian.audit` (Phase 1) now cross-checks the schema-handshake constants instead of the deleted PostToolUse snippet template.

### 0.1.23 — 2026-04-21

- `/lazy-obsidian.iconize-install` now scaffolds the protocol doc at the correct path `.claude/protocol/obsidian.iconize.md`. Previously a typo in the skill's artifact table and orphan-detection note misspelled the filename as `obsidian.iconizeize.md`, so the install would have dropped the protocol at the wrong path.

### 0.1.22 — 2026-04-21

- **Breaking:** Removed `/lazy-obsidian.iconize-file`. Its set/clear/get/list/bulk-apply/reconcile surface over the Iconize plugin's `data.json` is now covered by the new iconize-sync system described below.
- New **iconize-sync** workflow for declarative, frontmatter-driven Obsidian icon assignment, backed by a standalone worker at `bin/iconize_sync.py` and three user-facing skills:
  - `/lazy-obsidian.iconize-install` — per-file scaffolding wizard that drops the protocol doc, local icon-map, pre-commit shim, and PostToolUse hook entry into the vault's git repo. Asks before creating, shows diffs on drift, offers orphan deletion; idempotent.
  - `/lazy-obsidian.iconize-configure` — interactive wizard for adding, editing, or removing registry entries (roles, steps, requests, or any custom registry) in the vault's local `.claude/obsidian-iconize/icon-map.json`. Validates `iconName` / `iconColor` through the worker at prompt time so invalid entries never land.
  - `/lazy-obsidian.iconize-sync` — wraps the worker with five subcommands: `sync <path>`, `sync-staged` (pre-commit), `reconcile [--prefix]`, `install-hooks`, `check-versions`. Concurrent-safe writes into `obsidian-icon-folder/data.json` via mtime-guarded compare-and-swap; preserves `settings`, `rules`, and `recentlyUsedIcons`. Callable standalone, from `.githooks/pre-commit`, or from Claude Code's PostToolUse hook.
- New `obsidian.gen-tag-pages` agent that regenerates Obsidian tag pages from `tags:` frontmatter across every `.md` file in the vault. Six-phase flow (collect → compute parent tags → inventory → diff → delete stale → create new → report). Reads its page template from the consumer repo at `.claude/templates/obsidian.tag-page-template.md` (scaffolded by `/lazy-obsidian.install`), substituting `{{TAG_PATH}}` and `{{SUMMARY}}`. Never overwrites existing tag pages; cleans up empty directories after stale deletions.
- New `/lazy-obsidian.audit` semantic self-check (delegated from `lazy-core.doctor` Phase 3). Verifies iconize-sync coherence: worker `PROTOCOL_VERSION` / `HOOK_VERSION` constants match the `HOOK_VERSION:` markers in the pre-commit shim and post-tool-use snippet; the icon-map template parses and covers at least one authored-doc + one status-file matcher; the protocol template's `owner_skill` points at an existing skill. Read-first; presents findings, then asks which to fix.

### 0.1.2 — 2026-04-19

- Internal cleanup only: dropped two stale doc references to a legacy dotfiles agent in `/lazy-obsidian.config`. No functional changes.

### 0.1.1 — 2026-04-19

- Initial public release.
- **`/lazy-obsidian.config`** — 10-phase greenfield/audit flow that aligns a project's `.obsidian/` with a curated snapshot. Detects greenfield vs existing; syncs musthave and optional plugins with per-plugin diff prompts (overwrite / keep-local / merge-missing-keys); regenerates `community-plugins.json` in dependency-aware load order; drops in the canonical Obsidian `.gitignore` block; prompts for a vault nickname; optionally wires `obsidian-mcp` into project `.mcp.json` with `OBSIDIAN_VAULT_PATH="."` so it travels cleanly across machines.
- **`/lazy-obsidian.iconize-file`** — mechanics-only Python primitive for the Iconize plugin's `data.json` (`obsidian-icon-folder`). Supports `set` / `clear` / `get` / `list` / bulk-apply / `reconcile`. Concurrent-safe via mtime guard + retry. Callable standalone or as a primitive from other skills.
- **`/lazy-obsidian.install`** — per-rule-ask + orphan-delete install flow consistent with `lazy-core.install` / `lazy-log.install`. Currently ships no rules; primary job is cleaning up orphans from earlier plugin versions.
- **`/lazy-obsidian.help`** — one-line summary of every skill the plugin ships.
- Depends on `lazycortex-core`.

## lazycortex-diagram

### 0.1.0 — 2026-04-27

- Initial scaffold. Format-agnostic diagram engine: planner skill + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.
