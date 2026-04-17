---
description: Show lazycortex-log purpose and a one-line summary of each skill and agent it ships
---

Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-log** — capture and recall the *why* behind every change. Three streams: raw commit log (`.logs/commits.jsonl`), functional changelog (`docs/changelog.md`), and AI run logs (`.logs/claude/**`). One agent searches across all of them.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-log.install` — bootstrap the plugin into a project (or globally); drops the logging rule, creates `docs/changelog.md`, updates `.gitignore`. Idempotent.
- `lazy-log.audit` — verify the logging rule is installed and coherent. Read-first; never modifies without confirmation.

**Agents** (invoke via Agent tool):

- `lazy-log.distill` — convert raw `.logs/commits.jsonl` entries into 1–3 sentence user-facing prose in `docs/changelog.md`. Auto-runs after meaningful commits.
- `lazy-log.recall` — search changelog, run logs, commit log, git history, memory for a query. Returns ranked matches with git SHAs.
- `lazy-log.timeline` — chronological view of changes matching a date range or topic, across all three streams.
- `lazy-log.summary` — multi-paragraph synthesis of "the whole story" of a topic (not chronological).

No other commands.

See `README.md` in the plugin for the full rationale and recall workflow.
