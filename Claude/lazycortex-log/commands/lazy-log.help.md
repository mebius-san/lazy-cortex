---
description: Show lazycortex-log purpose and a one-line summary of each skill and agent it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-log** — capture and recall the *why* behind every change. Three streams: raw commit log (`.logs/commits.jsonl`), functional changelog (`.logs/changelog.md`), and AI run logs (`.logs/claude/**`). One agent searches across all of them.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-log.install` — bootstrap the plugin into a project (or globally); drops the logging rule, creates `.logs/changelog.md`, ensures `.gitignore` covers `.logs/`. Idempotent.
- `lazy-log.audit` — verify the logging rule is installed and coherent. Read-first; never modifies without confirmation.
- `lazy-log.clean` — interactive housekeeping for `./.logs/claude/`: classify each folder against the live set of canonical skills/agents/commands, batch anonymous subagent runs, offer to distill substantive logs to memory before deleting. Read-first; deletions deferred until you've approved every action.

**Agents** (invoke via Agent tool):

- `lazy-log.distill` — convert raw `.logs/commits.jsonl` entries into themed prose in `.logs/changelog.md` (theme-first, one paragraph per day; same-day re-runs rewrite today's paragraph). Invoke per the `lazy-log.logging` rule (qualitative + 4h throttle) or on demand.
- `lazy-log.recall` — search changelog, run logs, commit log, git history, memory for a query. Returns ranked matches with git SHAs.
- `lazy-log.timeline` — chronological view of changes matching a date range or topic, across all three streams.
- `lazy-log.summary` — multi-paragraph synthesis of "the whole story" of a topic (not chronological).
- `lazy-log.bullets` — convert one plugin's commit range into a user-facing CHANGELOG release block. Filters internal commits and rewrites the rest as outcome-led bullets. Dispatched by publish workflows.

No other commands.

<!-- help-block:start -->
**Documentation:**

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/install-and-audit.md) — Bootstrap lazycortex-log in a project with /lazy-log.install, then verify the logging rule stays coherent with /lazy-log.audit.
- [change-history](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/change-history.md) — Query past changes from any angle — ranked recall, chronological timeline, or topical synthesis.
- [changelog](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/changelog.md) — Keep a human-readable changelog current with lazy-log.distill, then cut release-ready CHANGELOG bullets with lazy-log.bullets when you ship.
- [housekeeping](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/housekeeping.md) — Keep .logs/claude/ tidy as skills and agents come and go by running /lazy-log.clean to classify, merge, distill, and delete orphaned log folders.
- [cut-a-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/walkthroughs/cut-a-release.md) — Take a fresh batch of commits all the way to a published CHANGELOG bullet block — distill themed prose, then generate outcome-led bullets filtered for public release.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/troubleshooting.md) — Common failure modes across lazycortex-log skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-log/help/faq.md) — Answers to common questions about installing, running, and understanding lazycortex-log's skills and agents.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-log/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for the full rationale and recall workflow.
