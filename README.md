# LazyCortex

AI tooling plugins for Claude Code — skills, agents, and hooks.

## Plugins

### [lazycortex-core](Claude/lazycortex-core/)

Core skills and hooks for Claude Code:

- **Context management** — audit, optimize, and health-check your Claude Code project configuration
- **Security** — scan repos for leaked secrets, PII, and infrastructure details before going public; pre-commit hooks to catch issues early
- **Permissions** — allow all tools of an MCP server in one step, routed to the settings file at the same scope
- **Settings protection** — guard against dangerous permission changes

### [lazycortex-log](Claude/lazycortex-log/)

Logging, changelog generation, and change-history recall for Claude Code. Records every commit to a raw log, distills commits into a human-readable `docs/changelog.md`, tags every skill/agent run with the current `git_sha`, and provides a recall agent that searches across run logs, changelog, git history, and memory.

### [lazycortex-specs](Claude/lazycortex-specs/)

Specification and design skills for Claude Code.

## Installation

See each plugin's README for installation instructions, or install from the [public repo](https://github.com/mebius-san/lazy-cortex).
