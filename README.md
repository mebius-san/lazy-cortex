# LazyCortex

AI tooling plugins for Claude Code — skills, agents, and hooks that add context optimization, change-history recall, security scanning, and permission management to your Claude Code workflows.

## Plugins

### lazycortex-core

Core skills and agents for Claude Code.

Ships 7 skills, 2 hooks, and 2 rule templates:

- **Context management** — `lazy-core.audit`, `lazy-core.doctor`, `lazy-core.optimize` to measure and slim what Claude Code loads at startup
- **Security** — `lazy-guard.check-public` (secret/PII scan, pre-commit hook) and `lazy-repo.mark-public` (end-to-end flow for making a repo public)
- **Permissions** — `lazy-guard.allow-mcp` allows every tool of an MCP server in one step, routed to the settings file at the matching scope
- **Settings protection** — `lazy-guard.settings` hook blocks dangerous edits to `settings.json` / `settings.local.json`
- **Install** — `lazy-core.install` drops the hygiene and security rule templates into the target project

See [`Claude/lazycortex-core/`](Claude/lazycortex-core/) for details.

### lazycortex-log

Logging, changelog, and change-history recall for Claude Code.

Ships 2 skills, 4 agents, 1 hook, and 1 rule template. Records every commit to a raw log, distills commits into a readable `docs/changelog.md`, tags every skill/agent/command run with the current `git_sha`, and provides recall/timeline/summary agents that search across run logs, changelog, git history, and memory.

Run `/lazy-log.install` once per project after enabling the plugin.

See [`Claude/lazycortex-log/`](Claude/lazycortex-log/) for details.

### lazycortex-specs

Specification and design skills for Claude Code.

See [`Claude/lazycortex-specs/`](Claude/lazycortex-specs/) for details.

## Installation

All plugins live in a single Claude Code marketplace. Add the marketplace and enable the plugins you want in your `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-core@lazycortex": true,
    "lazycortex-log@lazycortex": true,
    "lazycortex-specs@lazycortex": true
  }
}
```

Restart Claude Code after enabling. Skills become available as `<plugin>:<skill-name>` (e.g. `lazycortex-core:lazy-core.audit`). Each plugin's README lists its one-time per-project setup — most have an `<plugin>.install` skill for that.

## Author

Alik Tabunov
