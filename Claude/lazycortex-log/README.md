# lazycortex-log

Logging, changelog generation, and change-history recall for Claude Code.

## Purpose

Solves a specific pain point: when you later ask "why was X changed?", this plugin makes it easy for the LLM to find the relevant commit/change. It does this by:

1. **Recording every git commit** to a raw log (`.logs/commits.jsonl`) via a post-commit hook
2. **Distilling commits** into a functional human-readable `./docs/changelog.md` via an on-demand agent
3. **Tagging every skill/agent/command run** with the current `git_sha` in its run log
4. **Providing a recall agent** that searches across run logs + changelog + git history + memory

## Installation

Enable the plugin at the project scope (recommended — logs and changelog belong to a specific repo):

In your project's `.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "lazycortex-log@lazycortex": true
  }
}
```

Then invoke `/lazy-log.install` once to copy the logging rule template into `.claude/rules/lazy-log.logging.md` and set up `docs/changelog.md`.

Global installation is supported too (`~/.claude/settings.json`), in which case the rule lands in `~/.claude/rules/`.

## Skills

| Skill | Description |
|---|---|
| `lazy-log.install` | Bootstrap the plugin: copies the rule template, creates `docs/changelog.md`, ensures `.gitignore` covers `.logs/`. Detects install scope (user vs project) and targets the right rules directory. |
| `lazy-log.audit` | Verify the project's logging rule is installed and internally coherent. The rule is the single source of truth — per-file `## Logging` sections are optional. |

## Agents

| Agent | Description |
|---|---|
| `lazy-log.recall` | Search across run logs, changelog, raw commit log, git history, and memory for a query. Returns ranked matches with git SHAs. |
| `lazy-log.distill` | Convert raw commit entries into functional prose in `./docs/changelog.md`. Guided to run after meaningful commits by the installed rule. |
| `lazy-log.timeline` | Chronological list of changes for a date range or topic. |
| `lazy-log.summary` | Synthesized summary of changes for a topic (not chronological). |

## Hook

| Hook | Trigger | Description |
|---|---|---|
| `lazy-log.commit-recorder` | After `git commit` (Bash or MCP) | Appends commit metadata (sha, date, author, message, file stats) to `.logs/commits.jsonl`. No LLM call, fast. |

## Usage

```
/lazy-log.install            # run once per project after enabling the plugin
/lazy-log.distill            # update docs/changelog.md from new commits
/lazy-log.recall "auth flow" # search for past changes to auth flow
/lazy-log.timeline "last 2 weeks"
/lazy-log.summary "the migration to lazy-core.*"
/lazy-log.audit              # verify logging across the project
```
