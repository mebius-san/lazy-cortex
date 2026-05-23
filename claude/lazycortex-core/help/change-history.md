---
chapter_type: block
summary: Run-log housekeeping and change-history access — clean up orphaned log directories, distill commits into themed prose, and ask "why was X changed?" across every source at once.
last_regen: 2026-05-23
diagram_spec:
  anchor: "How the members fit together"
  request: "Architecture diagram showing the two groups of members in the change-history block: (1) lazy-log.clean prunes the .logs/claude/ tree; (2) lazy-log.distill converts .logs/commits.jsonl into .logs/changelog.md; (3) lazy-log.recall, lazy-log.timeline, and lazy-log.summary read from changelog + run logs + git log + memory to answer history queries; (4) lazy-log.bullets reads git commits to produce a user-facing release block. Show the shared inputs (commits.jsonl, changelog.md, run logs) feeding the query agents."
source_skills:
  - lazy-log.clean
  - lazy-log.distill
  - lazy-log.recall
  - lazy-log.timeline
  - lazy-log.summary
  - lazy-log.bullets
---
# Change history and run-log housekeeping

Every skill run, commit, and changelog entry your project accumulates is a potential source of truth — but only if the logs stay tidy and you can query them. The change-history block covers both sides of that equation. On the housekeeping side, `/lazy-log.clean` classifies and prunes the `.logs/claude/` tree so orphaned directories from renamed or retired skills do not pile up. On the history side, `lazy-log.distill` rolls raw commit entries into themed prose in `.logs/changelog.md`; `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary` answer "why was X changed?" and "what happened last week?" by searching the changelog, run logs, git history, and project memory in one pass; and `lazy-log.bullets` converts a commit range into user-facing release notes ready to prepend to `CHANGELOG.public.md`.

## What's in this block

**`lazy-log.clean`** is the interactive log-tree janitor. It resolves the live set of canonical skill, agent, and command names from your vault, then classifies every immediate subdirectory of `.logs/claude/` into one of five buckets: canonical (still active), rename-candidate (a close match to a current name), pattern-clustered orphan (anonymous `task-N` or `subagent-task-N` folders), waivered (a skill that exists but now carries a logging waiver), or other orphan. For each non-canonical or stale folder it asks — one question at a time — whether to merge into the canonical folder, distill substantive logs into Hindsight project memory before deletion, delete outright, or leave alone. Nothing on disk changes until you have answered every prompt.

**`lazy-log.distill`** is the engine behind `.logs/changelog.md`. After meaningful commits it runs automatically per the `lazy-log.logging` rule, or you can invoke it on demand. The agent reads pending entries from `.logs/commits.jsonl` (written by the `lazy-log.commit-recorder` hook on every successful commit), groups them by Conventional-commits scope or keyword cluster, and writes functional 1–3 sentence paragraphs into the changelog using a theme-first layout. Each theme block is bumped to the top of the file when touched, so the most recently active areas stay visible. A 4-hour throttle prevents noisy same-session re-runs.

**`lazy-log.recall`** answers point-in-time questions: "why was X changed?" or "when did we touch Y?". You give it a natural-language query; it decomposes the query into keywords, searches the changelog, run logs, `.logs/commits.jsonl`, git log (both message and diff-content search), and project memory, ranks matches by source quality, deduplicates by SHA, and returns a table of top matches with the git SHAs you need to `git show <sha>` for full context.

**`lazy-log.timeline`** takes a date range or topic and produces a chronological, newest-first, day-by-day listing of everything that matches, drawn from the same sources. It is the right tool when you want a "what happened when" overview — a sprint retrospective view rather than a per-question lookup.

**`lazy-log.summary`** aggregates every match for a topic and synthesizes a multi-paragraph narrative: why the work started, what was done, what issues came up, and where it ended up. Unlike `recall` (point-in-time) and `timeline` (chronological), `summary` clusters by sub-theme and writes prose for a reader who was not there. Every claim is backed by a supporting SHA reference.

**`lazy-log.bullets`** is the release-time tool. You dispatch it with a plugin name, the commit range since the last release, the new version, and the date. It reads the commits, drops anything that is purely internal (chore, style, test, docs-sync, dev-tooling), rewrites the survivors as outcome-led bullets grouped by scope, and returns a formatted `### <version> — <date> UTC` block ready to prepend to `CHANGELOG.public.md`. The coordinator that dispatches it handles the actual file prepend; `lazy-log.bullets` only generates the block.

## How they work together

The block divides cleanly into two groups: **maintenance** and **querying**.

On the maintenance side, `/lazy-log.clean` and `lazy-log.distill` are the keepers of record quality. Run `/lazy-log.clean` when `.logs/claude/` has accumulated folders from renamed or retired skills — it removes the noise without destroying historical value, offering a distill-to-memory path for any logs worth keeping. Run `lazy-log.distill` (or let it run automatically after commits) to keep the internal changelog current; without distillation the query agents fall back to raw `.logs/commits.jsonl` and miss the functional prose that makes recall searches fast and accurate.

On the query side, the three search agents — `recall`, `timeline`, and `summary` — draw from the same four sources (changelog, run logs, raw commits, git log) and differ only in what they return. Reach for `recall` when you have a specific question ("who changed the auth middleware?"), `timeline` when you want a window in time ("what happened last week?"), and `summary` when you want to understand the full arc of a feature or refactor. All three return git SHAs so you can `git show <sha>` to inspect the exact change.

`lazy-log.bullets` sits outside the normal query flow. It is dispatched by the publish pipeline when drafting a release and needs the git commit range for one plugin translated into what a user installing the plugin would actually care about. Internal chore commits are filtered out automatically; what surfaces is a ready-to-paste release block.

## When you'd reach for this block

- Your `.logs/claude/` directory has grown folders whose names no longer match any skill or agent in the vault (renamed, merged, or retired artifacts leave orphaned directories behind).
- After a series of commits you want the internal changelog to catch up — readable summaries grouped by theme, not raw commit subjects.
- You need to answer "why did we change the auth middleware?" or "when did the logging rule land?" without manually grepping git log, the changelog, and run logs in sequence.
- You want a day-by-day timeline of everything that touched a particular area of the codebase across a given week or sprint.
- You want to understand the full arc of a feature or refactor across all sources, not just the chronology.
- You are drafting a plugin release and need the commit range translated into user-facing bullets, with internal chore and refactor commits automatically filtered out.

## Common adjustments

- To bypass the distill throttle after a burst of commits, invoke `lazy-log.distill` with `force` in the prompt, or ask Claude to distill manually.
- `/lazy-log.clean` holds all deletions in memory until you have answered every prompt; if you change your mind mid-run the cleanest path is to abort and re-run — no changes land until the final apply step.
- `lazy-log.recall` broadens automatically by including plural/singular variants and obvious synonyms; if the result set is too wide, add a more specific keyword in a follow-up prompt.
- `lazy-log.bullets` expects coordinate-style input (plugin, plugin_dir, range, new_version, date) and is typically dispatched by the publish pipeline rather than invoked directly.

## How the members fit together

## See also

- [runtime](runtime.md) — the daemon and routine system that drives `lazy-log.distill` on a cadence.
- [memory](memory.md) — `lazy-log.clean`'s distill-to-memory path calls into the same Hindsight memory that persona-marked experts use.
