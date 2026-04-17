## Why this plugin

Claude Code configs drift fast. Rule files bloat. `settings.json` fills with one-off permissions. MCP servers each add another round of allow prompts. And if the repo ever goes public, secrets and internal paths that no one was looking for will be the thing that ships.

`lazycortex-core` is the opinionated hygiene layer: it tells you what's actually loading into context, slims what's oversized, flags what's risky before the commit, and makes new MCP servers permissioned in one step.

## Who it's for

- **Claude Code users** who want to see (and shrink) their startup context footprint.
- **Maintainers of public-facing repos** who need a deterministic pre-commit check for secrets, PII, and internal paths.
- **Teams adopting MCP** that are tired of per-tool allow prompts.
- **Plugin authors** who want a consistent rules-and-settings baseline across their own plugins.

## Scenarios

- *"My Claude Code feels slow to start and loads too much."* — Run `/lazy-core.audit` to see sizes by category, then `/lazy-core.optimize` to slim oversized rule files and audit global settings for project-specific leakage.
- *"I'm about to make this repo public."* — Run `/lazy-repo.mark-public` for the end-to-end flow: security audit, guided resolution, waiver file, optional GitHub visibility flip.
- *"I just added a new MCP server and I'm drowning in allow prompts."* — Run `/lazy-guard.allow-mcp` and pick the server. It appends every `mcp__<server>__<tool>` entry to `permissions.allow` in the settings file at the server's scope (global vs. project vs. project-local).
- *"Something's weird with my project config."* — Run `/lazy-core.doctor` for a full health check across rules, agents, skills, settings, memory, hooks, and CLAUDE.md. It delegates to `lazy-guard.check-public` and `lazy-log.audit` when those plugins are installed.
- *"Has anything leaked into my public repo recently?"* — The `lazy-guard.check-public` hook activates automatically in any repo with a `.guard-waivers.json` and scans staged diffs on every commit. Blocks on secrets; warns on PII and paths.

## Requirements

- **Claude Code** with plugin support.
- **git** — the public-repo security flow and settings hooks assume a git repo.
- **Python 3** — bundled hook scripts (`lazy-guard.check-public`, `lazy-guard.settings`) are Python.
- **GitHub CLI (`gh`)** — optional, only needed if you want `lazy-repo.mark-public` to flip repo visibility for you.

## Quick start

1. Enable the plugin in `~/.claude/settings.json` (see Installation below).
2. Restart Claude Code.
3. Run `/lazy-core.install` inside each project (or once globally) to drop the `lazy-core.hygiene` and `lazy-guard.security` rule templates into `.claude/rules/`.
4. Run `/lazy-core.audit` to see what's currently loading. Run `/lazy-core.doctor` whenever the config feels off.
5. For public repos: create an empty `.guard-waivers.json` at the repo root to opt into pre-commit scanning.
