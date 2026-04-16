# lazycortex-core

Core skills and hooks for Claude Code — context optimization, project health checks, and public repo security.

## Skills

| Skill | Description |
|---|---|
| `lazy-core.audit` | Read-only audit of context loading at startup. Shows sizes, loading behavior, and optimization opportunities. |
| `lazy-core.doctor` | Health check for project configuration. Verifies rules, agents, skills, settings, memory, hooks, and CLAUDE.md consistency. |
| `lazy-core.optimize` | Slims oversized rules files, audits global settings for project-specific leakage, checks memory index health. |
| `lazy-guard.check-public-repo` | Scans git-tracked files for leaked secrets, PII, infrastructure details, and hardcoded paths. Reads `.guard-waivers.json` for exceptions. |
| `lazy-repo.mark-public` | End-to-end workflow for making a repo public: runs security audit, resolves findings, creates waivers, optionally flips GitHub visibility. |
| `lazy-project.init` | Bootstrap project settings: creates `settings.json` (tracked: Skill, MCP tools) and `settings.local.json` (local: Edit, Write, Bash, WebSearch). |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-guard.settings` | `Edit\|Write` on settings files | Guards `settings.json` / `settings.local.json` against dangerous changes: blocks broad wildcards, protects critical deny rules, enforces global `settings.local.json` stays empty. |
| `lazy-guard.check-public-repo` | `git commit` (Bash or MCP) | Pre-commit scan of staged changes for secrets and PII. Only active in repos with `.guard-waivers.json`. Blocks on secrets, warns on PII/infra/paths. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

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
    "lazycortex-core@lazycortex": true
  }
}
```

Then restart Claude Code. Skills will appear as `lazycortex-core:lazy-core.audit`, etc.

## Usage

Invoke skills with slash commands:

```
/lazy-core.audit          # audit context loading
/lazy-core.doctor         # project health check
/lazy-core.optimize       # optimize context and settings
/lazy-guard.check-public-repo  # security audit for public repos
/lazy-repo.mark-public    # make a repo public safely
/lazy-project.init        # bootstrap project settings
```

Hooks activate automatically after installation.
