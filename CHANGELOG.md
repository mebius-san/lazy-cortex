# Changelog

User-visible changes per plugin release. Each plugin in this marketplace is versioned independently via SemVer.

## lazycortex-core

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

### 0.1.1 — 2026-04-18

- Internal manifest metadata update; no functional changes.

### 0.1.0 — 2026-04-17

- Initial release.
