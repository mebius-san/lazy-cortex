# Changelog

User-visible changes per plugin release. Each plugin in this marketplace is versioned independently via SemVer.

## lazycortex-core

### 0.1.0 — 2026-04-17

- Initial release.
- **Context management** — `lazy-core.audit`, `lazy-core.doctor`, `lazy-core.optimize` measure and slim what Claude Code loads at startup.
- **Security** — `lazy-guard.check-public` scans for leaked secrets, PII, and local paths; `lazy-repo.mark-public` walks a repo through the full public-release flow; a pre-commit hook blocks new leaks.
- **Permissions** — `lazy-guard.allow-mcp` allows every tool of an MCP server in one step, routed to the settings file at the matching scope.
- **Settings protection** — `lazy-guard.settings` hook blocks dangerous edits to `settings.json` / `settings.local.json`.
- **Install** — `lazy-core.install` drops the hygiene and security rule templates into the target project.

## lazycortex-log

### 0.1.0 — 2026-04-17

- Initial release.
- Per-commit run logging: every skill, agent, and command writes `./.logs/claude/<name>/YYYY-MM-DD_HH-MM-SS.md` with the current `git_sha`.
- `lazy-log.distill` agent turns raw commits into a readable `docs/changelog.md`.
- `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary` agents search across run logs, changelog, git history, and memory.
- `lazy-log.install` bootstraps the logging rule, `docs/changelog.md`, and the commit-capture hook into a project.
- `lazy-log.audit` verifies the logging rule is installed and coherent.

## lazycortex-specs

### 0.1.0 — 2026-04-17

- Initial release.
