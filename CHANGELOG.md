# Changelog

User-visible changes per plugin release. Each plugin in this marketplace is versioned independently via SemVer.

## lazycortex-core

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
- `/lazy-core.doctor` now distinguishes **local-tool mode** (this repo authors plugins under `Claude/**`) from **release mode** (consumer repos). In release mode, if a plugin is outdated per the marketplace-version check, content-level findings on its owned rule files are suppressed — upgrade the plugin first, then re-run to surface any remaining issues. A per-plugin INFO line reports the suppression count.
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

### 0.1.4 — 2026-04-19

- Internal plumbing — seeded `.claude-plugin/overview.md` so the plugin meets the minimum marketplace surface required by `tool.doctor`. Still a namespace placeholder with no shipped skills; downstream plugins and the marketplace can now depend on the namespace ahead of the first real skill landing. No functional changes.

### 0.1.2 — 2026-04-19

- Internal plumbing — removed an empty `settings.json` stub. No functional changes.

### 0.1.1 — 2026-04-18

- Internal manifest metadata update; no functional changes.

### 0.1.0 — 2026-04-17

- Initial release.

## lazycortex-obsidian

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
