# LazyCortex

AI tooling plugins for Claude Code — skills, agents, and hooks that add context optimization, change-history recall, security scanning, and permission management to your Claude Code workflows.

## Why LazyCortex

Claude Code grows powerful with skills, agents, and hooks — but unmanaged, it also grows noisy, leaky, and forgetful. LazyCortex is an opinionated toolkit for the same issues you keep hitting:

- **Context bloat.** Rule files, CLAUDE.md, and MCP tools quietly consume your token budget. You can't optimize what you can't see.
- **Forgotten history.** "Why did we change this?" six weeks later, when the commit message is `fix` and the PR is closed, is a real cost.
- **Accidental leaks.** Secrets, PII, and internal paths slip into public repos because no one was checking staged diffs.
- **Permission fatigue.** Every new MCP server means a round of "allow this tool? allow that tool?" prompts.

Each plugin addresses one of these pains without forcing you to adopt the others.

## Who it's for

- **Individual developers** using Claude Code daily who want their config, history, and security posture to stay tidy without manual effort.
- **Teams** publishing skills or agents publicly, who need a last-mile check for secrets and PII before pushing.
- **Plugin authors** who want a consistent baseline (rules, logging, health checks) across their own plugins.

## Plugins

### lazycortex-core

Core skills and agents for Claude Code

Ships 9 skills, 2 commands, 6 rules, and 3 hooks.

See [`claude/lazycortex-core/`](claude/lazycortex-core/) for details.

### lazycortex-log

Logging, changelog, and change-history recall for Claude Code

Ships 3 skills, 4 agents, 1 command, 1 rule, and 2 hooks.

Requires: lazycortex-core

See [`claude/lazycortex-log/`](claude/lazycortex-log/) for details.

### lazycortex-obsidian

Obsidian vault bootstrap and configuration management for Claude Code

Ships 6 skills, 1 agent, 1 command, and 2 hooks.

Requires: lazycortex-core

See [`claude/lazycortex-obsidian/`](claude/lazycortex-obsidian/) for details.

### lazycortex-specs

Specification and design skills for Claude Code

Ships 1 command.

See [`claude/lazycortex-specs/`](claude/lazycortex-specs/) for details.

## Requirements

- **Claude Code** — the plugins use skills, agents, hooks, and the plugin marketplace system.
- **git** — hooks and logging depend on git repos. Installing in a non-git directory degrades gracefully but loses most value.
- **Python 3** — for hook scripts bundled with plugins that install hooks (e.g. `lazycortex-core`, `lazycortex-log`).

## Quick start

1. Add the marketplace and enable the plugins you want (see Installation below).
2. Restart Claude Code.
3. For each enabled plugin, run its install skill once per project: `/lazy-core.install`, `/lazy-log.install`, etc. This drops the plugin's rule templates into `.claude/rules/` and sets up any log/changelog scaffolding.
4. Invoke skills via slash commands. Hooks activate automatically.

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
    "lazycortex-obsidian@lazycortex": true,
    "lazycortex-specs@lazycortex": true
  }
}
```

Restart Claude Code after enabling. Each plugin's README explains its setup steps — most have a `<plugin>.install` skill you run once per project.

## Author

Mebius-san
