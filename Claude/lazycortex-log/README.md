---
iconize_icon: LiInfo
iconize_color: "#86efac"
---
# lazycortex-log

Logging, changelog, and change-history recall for Claude Code

## Why this plugin

Six weeks after a change lands, "why did we do this?" is expensive to answer. The commit message says `fix`, the PR is closed, the Slack thread is archived, and the LLM is guessing. `lazycortex-log` is designed so that future-you (or the LLM working on behalf of future-you) can actually answer that question.

It does this by capturing three complementary streams and making all of them searchable from one agent:

1. **Raw commit log** (`.logs/commits.jsonl`) — every commit, captured by a post-commit hook. No LLM call, no prompt, just metadata.
2. **Functional changelog** (`.logs/changelog.md`) — human-readable prose distilled from commits by an on-demand agent.
3. **Run logs** (`.logs/claude/**`) — every skill/agent/command execution, tagged with the current `git_sha` so you can jump from "the AI did Y" back to the commit that made the change.

Then `lazy-log.recall` searches across all three plus git history and memory, and returns ranked results with git SHAs.

## Who it's for

- **Anyone working in a repo for long enough** to forget why a change was made.
- **Developers collaborating with AI assistants** who want a reliable trail from a run log back to the commit it produced.
- **Teams doing incident postmortems** who need chronological and topical views without manually grepping through git log.

## Blocks

- **install-and-audit** — Bootstrap and verify lazycortex-log in your project. Covers what `/lazy-log.install` drops (the `lazy-log.logging` rule, `.logs/changelog.md`, `.gitignore` entry, post-commit hook), and what `/lazy-log.audit` checks (rule presence, integrity, no-conflicting per-file `## Logging` sections). Members: lazy-log.install, lazy-log.audit.
- **change-history** — Query past changes from any angle. Members: lazy-log.recall, lazy-log.timeline, lazy-log.summary.
- **changelog** — Maintain the human-readable changelog and draft release notes. Members: lazy-log.distill, lazy-log.bullets.
- **housekeeping** — Keep `.logs/claude/` tidy as skills/agents come and go. Members: lazy-log.clean.

## Walkthroughs

- **cut-a-release** — Take a fresh batch of commits all the way to a published CHANGELOG bullet block. Path: lazy-log.distill (refresh `.logs/changelog.md` so commit groups are coherent prose) → lazy-log.bullets (filter internal commits, draft the user-facing bullet block) → prepend to `CHANGELOG.public.md`. Useful when cutting a public release where the public CHANGELOG must omit churn-only commits.

## Requirements

- **Claude Code** with plugin support.
- **git** — the commit log and changelog flows assume a git repo. The plugin degrades gracefully in non-git directories but loses most of its value.
- **Python 3** — the `lazy-log.commit-recorder` hook script is Python.
- **`lazycortex-core` (recommended)** — `lazy-core.doctor` delegates to `lazy-log.audit`, and many of the "why did we change" workflows pair naturally with `lazy-core`'s health checks.

## Quick start

1. Enable the plugin at **project scope** — logs and changelog belong to a specific repo, so this usually isn't a global install.
2. Restart Claude Code.
3. Run `/lazy-log.install` once per project. This drops the `lazy-log.logging` rule into `.claude/rules/`, creates `.logs/changelog.md`, and ensures `.gitignore` covers `.logs/` (the structured commit log, distilled prose changelog, and AI run logs all live there as per-contributor local artifacts).
4. From then on, the post-commit hook records every commit. Run `/lazy-log.distill` when you want the human-readable changelog updated. Run `/lazy-log.recall` whenever you're trying to remember something.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-log.audit` | Verify that the project's logging rule is installed and coherent. The rule itself is the single source of truth — individual skills/agents/commands do NOT need per-file ## Logging sections. Reports gaps and offers fixes. Read-first — never modifies files without confirmation. |
| `lazy-log.clean` | Interactive housekeeping for `./.logs/claude/`. Classifies each subdirectory against the live set of canonical skills/agents/commands; offers merge / distill-to-memory / delete / leave per orphan, batched by pattern when a cluster of anonymous folders (e.g. `task-N`) would otherwise produce dozens of prompts. Read-first — no folder is touched until the user has approved every action. |
| `lazy-log.install` | Bootstrap the lazycortex-log plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, creates .logs/changelog.md if missing, and ensures .gitignore covers .logs/. Idempotent — safe to re-run. Detects install scope automatically. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/install-and-audit.md) — Bootstrap lazycortex-log in a project with /lazy-log.install, then verify the logging rule stays coherent with /lazy-log.audit.
- [change-history](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/change-history.md) — Query past changes from any angle — ranked recall, chronological timeline, or topical synthesis.
- [changelog](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/changelog.md) — Keep a human-readable changelog current with lazy-log.distill, then cut release-ready CHANGELOG bullets with lazy-log.bullets when you ship.
- [housekeeping](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/housekeeping.md) — Keep .logs/claude/ tidy as skills and agents come and go by running /lazy-log.clean to classify, merge, distill, and delete orphaned log folders.
- [cut-a-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/walkthroughs/cut-a-release.md) — Take a fresh batch of commits all the way to a published CHANGELOG bullet block — distill themed prose, then generate outcome-led bullets filtered for public release.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/troubleshooting.md) — Common failure modes across lazycortex-log skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/faq.md) — Answers to common questions about installing, running, and understanding lazycortex-log's skills and agents.

## Agents

| Agent | Description |
|---|---|
| `lazy-log.bullets` | Convert one plugin's commit range into a user-facing CHANGELOG release block. Reads commits via git, drops internal-only commits by Conventional-commits type, rewrites the rest as outcome-led bullets grouped by scope, and returns the rendered `### <version> — <date> UTC` block ready to prepend to CHANGELOG.public.md. Dispatch from any release-drafting flow that needs commit-subjects → user-bullets translation. |
| `lazy-log.distill` | Convert raw commit entries from .logs/commits.jsonl into themed functional prose in ./.logs/changelog.md. Output is theme-first (## <theme>) with one paragraph per day (### YYYY-MM-DD); same-day re-runs rewrite today's paragraph in place; touched theme blocks bump to the top. Throttled to once per 4h via mtime(.logs/changelog.md). Invoke after meaningful commits (see lazy-log.logging rule) or on demand. |
| `lazy-log.recall` | Search all change-history sources (run logs, changelog, raw commit log, git history, memory) for a query. Returns ranked matches with git SHAs so the user can jump to the actual commit. Use when the user asks 'why was X changed?' or 'when did we change Y?' |
| `lazy-log.summary` | Synthesize a multi-paragraph summary of all changes related to a topic across time (not chronological). Use when the user wants to understand 'the whole story' of a feature, refactor, or area of the codebase. |
| `lazy-log.timeline` | Generate a chronological timeline view of all changes matching a date range or topic. Combines changelog entries, commits, and AI run logs. Use when the user wants a 'what happened when' view. |

## Commands

| Command | Description |
|---|---|
| `lazy-log.help` | Show lazycortex-log purpose and a one-line summary of each skill and agent it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-log.logging` | Logging conventions for skills, agents, and commands. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-log.commit-recorder` | `Bash`, `mcp__git__git_commit` | Record every git commit to .logs/commits.jsonl. |

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
    "lazycortex-log@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-log:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-log.audit
/lazy-log.clean
/lazy-log.help
/lazy-log.install
```
