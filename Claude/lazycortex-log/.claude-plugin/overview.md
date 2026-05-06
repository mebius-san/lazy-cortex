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
