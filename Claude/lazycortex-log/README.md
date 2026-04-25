---
iconize_icon: LiInfo
iconize_color: "#eab308"
---
# lazycortex-log

Logging, changelog, and change-history recall for Claude Code

## Why this plugin

Six weeks after a change lands, "why did we do this?" is expensive to answer. The commit message says `fix`, the PR is closed, the Slack thread is archived, and the LLM is guessing. `lazycortex-log` is designed so that future-you (or the LLM working on behalf of future-you) can actually answer that question.

It does this by capturing three complementary streams and making all of them searchable from one agent:

1. **Raw commit log** (`.logs/commits.jsonl`) — every commit, captured by a post-commit hook. No LLM call, no prompt, just metadata.
2. **Functional changelog** (`docs/changelog.md`) — human-readable prose distilled from commits by an on-demand agent.
3. **Run logs** (`.logs/claude/**`) — every skill/agent/command execution, tagged with the current `git_sha` so you can jump from "the AI did Y" back to the commit that made the change.

Then `lazy-log.recall` searches across all three plus git history and memory, and returns ranked results with git SHAs.

## Who it's for

- **Anyone working in a repo for long enough** to forget why a change was made.
- **Developers collaborating with AI assistants** who want a reliable trail from a run log back to the commit it produced.
- **Teams doing incident postmortems** who need chronological and topical views without manually grepping through git log.

## Scenarios

- *"Why did we change how X works?"* — Run `/lazy-log.recall "X"`. The agent searches changelog, commit log, run logs, git, and memory, and returns ranked matches with SHAs you can `git show`.
- *"What happened in the last two weeks?"* — Run `/lazy-log.timeline "last 2 weeks"` for a chronological view merging changelog entries, commits, and AI run logs.
- *"Summarize the whole story of the auth refactor."* — Run `/lazy-log.summary "auth refactor"` for a multi-source synthesized summary (not chronological).
- *"I just landed a batch of commits."* — Run `/lazy-log.distill` to update `docs/changelog.md` with user-facing prose for each new commit.
- *"Is the logging rule actually being followed?"* — Run `/lazy-log.audit` to verify the rule is installed and internally coherent. The rule is the single source of truth; individual skill/agent definitions do not need their own `## Logging` sections.

## Requirements

- **Claude Code** with plugin support.
- **git** — the commit log and changelog flows assume a git repo. The plugin degrades gracefully in non-git directories but loses most of its value.
- **Python 3** — the `lazy-log.commit-recorder` hook script is Python.
- **`lazycortex-core` (recommended)** — `lazy-core.doctor` delegates to `lazy-log.audit`, and many of the "why did we change" workflows pair naturally with `lazy-core`'s health checks.

## Quick start

1. Enable the plugin at **project scope** — logs and changelog belong to a specific repo, so this usually isn't a global install.
2. Restart Claude Code.
3. Run `/lazy-log.install` once per project. This drops the `lazy-log.logging` rule into `.claude/rules/`, creates `docs/changelog.md`, and ensures `.gitignore` covers `.logs/` and `docs/changelog.md` (both are per-contributor local — the structured commit log and distilled prose memory for your local Claude session).
4. From then on, the post-commit hook records every commit. Run `/lazy-log.distill` when you want the human-readable changelog updated. Run `/lazy-log.recall` whenever you're trying to remember something.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills and agents for Claude Code

## Skills

| Skill | Description |
|---|---|
| `lazy-log.audit` | Verify that the project's logging rule is installed and coherent. The rule itself is the single source of truth — individual skills/agents/commands do NOT need per-file ## Logging sections. Reports gaps and offers fixes. Read-first — never modifies files without confirmation. |
| `lazy-log.install` | Bootstrap the lazycortex-log plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, creates docs/changelog.md if missing, and ensures .gitignore covers .logs/ and docs/changelog.md. Idempotent — safe to re-run. Detects install scope automatically. |

## Agents

| Agent | Description |
|---|---|
| `lazy-log.distill` | Convert raw commit entries from .logs/commits.jsonl into functional prose in ./docs/changelog.md. Writes 1-3 sentence entries per commit focused on what changed for the user (not implementation detail). Invoke after meaningful commits (see lazy-log.logging rule) or on demand. |
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
| `lazy-log.commit-recorder` | `Bash`, `mcp__git__git_commit` | PostToolUse hook: record every successful git commit to .logs/commits.jsonl. |
| `lazy-log.distill-trigger` | `Stop` | Stop hook — trigger distill when a fresh commit landed this turn. |

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
/lazy-log.help
/lazy-log.install
```
