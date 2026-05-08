---
chapter_type: faq
summary: Answers to common questions about installing, running, and understanding lazycortex-log's skills and agents.
last_regen: 2026-05-08
no_diagram: true
source_skills:
  - lazy-log.recall
  - lazy-log.timeline
  - lazy-log.summary
  - lazy-log.distill
  - lazy-log.bullets
  - lazy-log.clean
---
# Frequently asked questions

## Where should I install lazycortex-log — globally or per project?

Per project, in almost every case. Logs, the raw commit log (`.logs/commits.jsonl`), and the human-readable changelog (`.logs/changelog.md`) all live inside a specific repo's `.logs/` directory. Installing globally would mean every Claude Code session in every directory tries to write `.logs/` wherever the working directory happens to be, which is rarely what you want. Run `/lazy-log.install` once inside each repo you want tracked.

---

## What files does the plugin create, and are they committed to git?

`/lazy-log.install` creates three things:

- `.claude/rules/lazy-log.logging.md` — the logging rule that makes every skill and agent log its runs. This IS committed (it is project configuration).
- `.logs/changelog.md` — the human-readable distilled changelog. This is gitignored by default.
- `.logs/commits.jsonl` — the raw per-commit metadata recorded by the post-commit hook. Also gitignored.

Run logs under `.logs/claude/**` are also gitignored. The intent is that `.logs/` is a per-contributor local artifact, not shared state.

---

## What gets recorded in the raw commit log versus the distilled changelog?

The raw commit log (`.logs/commits.jsonl`) is written by the `lazy-log.commit-recorder` hook on every `git commit`. It captures metadata only: SHA, date, author, branch, commit subject, body, files changed, insertions, and deletions. No LLM is involved; it is fast and unconditional.

The distilled changelog (`.logs/changelog.md`) is written by `lazy-log.distill`, which reads the raw log and produces themed, user-facing prose grouped by topic (not by date). Distillation requires an LLM call and is throttled to run at most once every four hours. Run `/lazy-log.distill` to trigger it on demand, or it fires automatically after meaningful commits in the same session.

---

## When does distillation run automatically, and when do I need to trigger it manually?

After a commit lands in a session, Claude judges qualitatively whether the change is meaningful enough to narrate (notable feature, fix, or refactor). If yes, and if `.logs/changelog.md` was last updated more than four hours ago, distillation fires automatically. Small housekeeping commits (a `chore:` tweak, a typo fix) are skipped.

If you want distillation to run regardless — for example after a batch of commits landed in a previous session — invoke `/lazy-log.distill` directly. Including the word `force` in the prompt bypasses the four-hour throttle.

---

## What is the difference between recall, timeline, and summary?

All three search the same sources (changelog, run logs, raw commit log, git history, memory). The difference is the output shape:

- **`lazy-log.recall`** is a ranked-match retrieval. You give it a query and it returns a table of the strongest hits across every source, each with a git SHA you can pass to `git show`. Best for "find me the commit where X happened."
- **`lazy-log.timeline`** is a chronological view. You give it a date range or topic and it returns a day-by-day list of what happened. Best for "what was going on during the week of the auth migration?"
- **`lazy-log.summary`** is a synthesized narrative. You give it a topic and it clusters related changes across all time into a prose story grouped by sub-theme. Best for "explain the whole arc of how the plugin system evolved."

When in doubt, start with `lazy-log.recall` — if the answer is a single commit, recall will surface it fastest.

---

## Do recall, timeline, and summary produce run logs?

No. All three carry a `logging-waiver` — their output is the response itself, so a separate run log would only duplicate the prose already returned to you. You will not find `.logs/claude/lazy-log.recall/` (or timeline / summary) entries accumulating over time, and `/lazy-log.clean` will not flag those names as orphan folders.

---

## What is the difference between `lazy-log.bullets` and `lazy-log.distill`?

`lazy-log.distill` writes to `.logs/changelog.md` — a private, themed, contributor-facing record of what changed and why. It captures every commit, including internal chores and refactors, and is not filtered for public consumption.

`lazy-log.bullets` produces a formatted `### <version> — <date> UTC` release block ready to prepend to `CHANGELOG.public.md`. It filters out internal-only commits (pure `chore:`, `style:`, `test:`, README syncs) and rewrites the survivors as outcome-led bullets that a user installing the plugin would care about. It is dispatched as part of the release flow — see [cut-a-release](walkthroughs/cut-a-release.md) for the end-to-end steps.

---

## How do I search for why a specific change was made?

Run `/lazy-log.recall` with a plain-language description, for example:

```
/lazy-log.recall "why we removed the old settings hook"
```

The agent decomposes your query into keywords, searches changelog, run logs, raw commits, git history, and memory, and returns ranked results with git SHAs. From there, `git show <sha>` takes you to the actual change. No manual grepping required.

---

## My `.logs/claude/` directory has dozens of folders from anonymous subagent runs. How do I clean it up?

Run `/lazy-log.clean`. The skill compares every subfolder name against the live set of canonical skill, agent, and command names. Anonymous runs (folders named `task-N`, `subagent-task-N`, and similar patterns) are clustered and presented as a single prompt — you can delete the whole cluster, distill substantive logs to memory first, or leave them. Nothing is touched on disk until you have approved every action.

---

## Do I need to do anything after upgrading to a new version of lazycortex-log?

It depends on the bump kind:

- **Patch bump** — drop in the new files; no action needed.
- **Minor bump** — re-run `/lazy-log.install` to pick up any new rules, settings, or templates the bump added.
- **Major bump** — check the release notes in `CHANGELOG.public.md`; a major bump means user-data migration may be required.

The README's versioning note at the top of the plugin always states which bump kind applies to the current release.

---

## The post-commit hook is not recording commits. What do I check?

First verify the plugin is installed in this repo: run `/lazy-log.audit`. If the audit reports the logging rule is missing or the hook is not wired, re-run `/lazy-log.install`. If the hook is present but commits still are not being recorded, check that Python 3 is on your `PATH` — the `lazy-log.commit-recorder` hook script requires it. The audit will flag this as a gap and tell you what to fix.
