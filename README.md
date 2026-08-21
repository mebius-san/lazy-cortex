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

Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

31 skills, 8 agents, 6 hooks.

See [`claude/lazycortex-core/`](claude/lazycortex-core/) for details.

### lazycortex-diagram

Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.

4 skills, 2 agents.

Requires: lazycortex-core

See [`claude/lazycortex-diagram/`](claude/lazycortex-diagram/) for details.

### lazycortex-experts

Generic lifecycle experts (interpreter, designer, planner, implementer, debugger, reviewer, tester) plus a fiction-writer agent, a starter set of domain aspects (claude-plugin, game-dev, dotfiles, obsidian-plugin, data-pipeline, sci-fi, fantasy), and two cross-cutting aspects (discipline, tech-writing). Building blocks — compose specialists in lazy.settings.json[experts] with one agent + one or more aspects.

1 skill, 11 agents.

Requires: lazycortex-core

See [`claude/lazycortex-experts/`](claude/lazycortex-experts/) for details.

### lazycortex-observe

Ship lazycortex-core runtime metrics to a Prometheus-compatible observer (Grafana Alloy or OpenTelemetry Collector) — vendor-neutral, observer-server-blind, headless-portable.

4 skills.

Requires: lazycortex-core

See [`claude/lazycortex-observe/`](claude/lazycortex-observe/) for details.

### lazycortex-obsidian

Obsidian vault bootstrap and configuration management for Claude Code

7 skills, 1 agent, 1 hook.

Requires: lazycortex-core

See [`claude/lazycortex-obsidian/`](claude/lazycortex-obsidian/) for details.

### lazycortex-python

Python coding discipline as a plugin: shared rules + reference guidelines + chk/tst checkers + PostToolUse hook + docstring-writer/test-writer agents + canonical file template. Installs once per repo via /lazy-python.install.

4 skills, 5 agents, 1 hook.

Requires: lazycortex-core

See [`claude/lazycortex-python/`](claude/lazycortex-python/) for details.

### lazycortex-review

Coordinator-driven markdown document review loop: a closed set of Python primitive verbs (parse-note / set-key / paint-banner / collect-job), an LLM coordinator that owns every decision from a prose playbook, and a git-watch wake plus an interval postman that carry commits and finished expert jobs back into the loop.

8 skills, 2 agents.

Requires: lazycortex-core

See [`claude/lazycortex-review/`](claude/lazycortex-review/) for details.

### lazycortex-specs

Specification and design skills for Claude Code

27 skills, 1 agent.

Requires: lazycortex-core, lazycortex-diagram, lazycortex-review

See [`claude/lazycortex-specs/`](claude/lazycortex-specs/) for details.

### lazycortex-wiki

Maintains a curated, LLM-navigable semantic wiki over a markdown+code base — summaries, hierarchical topic tags, and glossed See-also links, kept in sync via git-watch and weekly full-scan routines.

9 skills, 6 agents.

Requires: lazycortex-core

See [`claude/lazycortex-wiki/`](claude/lazycortex-wiki/) for details.

## Requirements

- **Claude Code** — the plugins use skills, agents, hooks, and the plugin marketplace system.
- **git** — hooks and logging depend on git repos. Installing in a non-git directory degrades gracefully but loses most value.
- **Python 3** — for hook scripts bundled with plugins that install hooks (e.g. `lazycortex-core`, `lazycortex-obsidian`).

## Quick start

1. Add the marketplace and install the plugins you want (see Installation below).
2. Run `/reload-plugins` to activate them (no restart needed).
3. For each installed plugin, run its install skill once per project: `/lazy-core.install`, `/lazy-python.install`, etc. This drops the plugin's rule templates into `.claude/rules/` and sets up any log/changelog scaffolding.
4. Invoke skills via slash commands. Hooks activate automatically.

## Installation

All plugins live in a single Claude Code marketplace. Add the marketplace once, then install the plugins you want — run these inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-core@lazycortex
/plugin install lazycortex-diagram@lazycortex
/plugin install lazycortex-experts@lazycortex
/plugin install lazycortex-observe@lazycortex
/plugin install lazycortex-obsidian@lazycortex
/plugin install lazycortex-python@lazycortex
/plugin install lazycortex-review@lazycortex
/plugin install lazycortex-specs@lazycortex
/plugin install lazycortex-wiki@lazycortex
/reload-plugins
```

`/reload-plugins` activates them without a restart. Each plugin's README explains its setup steps — most have a `<plugin>.install` skill you run once per project.

## Author

Mebius-san
