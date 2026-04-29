---
description: Show lazycortex-log purpose and a one-line summary of each skill and agent it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
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

See `README.md` in the plugin for the full rationale and recall workflow.
