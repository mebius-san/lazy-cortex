---
chapter_type: block
summary: Query past changes from any angle — ranked recall, chronological timeline, or topical synthesis.
last_regen: 2026-05-08
diagram_spec:
  anchor: "How the three agents share a substrate"
  request: "Flow diagram showing lazy-log.recall, lazy-log.timeline, and lazy-log.summary as three query paths fanning into a shared substrate of four sources: changelog.md, run logs, commits.jsonl, and git log/memory. Each agent has a distinct output shape: ranked table, chronological list, narrative prose."
source_skills:
  - lazy-log.recall
  - lazy-log.timeline
  - lazy-log.summary
---
# Query the history of any change

Six weeks after a change lands, "why did we do this?" is expensive to answer from memory alone. The `lazycortex-log` change-history block gives you three purpose-built agents — `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary` — each approaching the same underlying sources from a different angle. Knowing which angle to reach for is the whole skill.

## What's in this block

**`lazy-log.recall` — keyword-first ranked retrieval.**
You give it a natural-language query ("the auth middleware rewrite", "when did we switch to dot-namespaces") and it searches every source, scores each match by how strongly it correlates with your keywords, deduplicates by git SHA, and returns a ranked table of up to ten results. Each row includes the source that produced the match and the SHA you can hand to `git show`. The ranking tiers run from multi-keyword changelog hits (strongest) down to diff-content-only matches found via `git log -S` (weakest), so the highest-confidence answer appears first. Use recall when you have a keyword or phrase and want to know where and when that thing happened.

**`lazy-log.timeline` — date-range chronological view.**
You give it a date range ("last 2 weeks", "since 2026-04-01"), a topic, or both. It collects entries from all sources within those bounds, deduplicates by SHA, sorts newest-first (or oldest-first on request), and groups by day. Every entry is a short factual reference — SHA, time, and subject — with `(internal)` prefixed on chore/refactor commits so you can skim past them. Use timeline when you want to reconstruct "what happened when" across a span of time, without needing a synthesized narrative.

**`lazy-log.summary` — topical narrative synthesis.**
You give it a topic ("how the plugin system evolved", "everything about the logging skills") and it reads the most relevant commits in full, clusters the results by sub-theme, and writes 2–4 paragraphs of prose with inline SHA citations. The sub-themes are structured around "why and what" — design decisions, implementation phases, issues that surfaced, follow-up work — not around "when". A supporting-references table follows the prose, and a Gaps section flags periods with no captured records. Use summary when you need to understand the arc of something, not just locate the specific change.

## How they work together

The three agents are not alternatives to each other — they are stages of a natural investigation.

Start with **recall**. A keyword search is fast and returns SHAs. If one or two results look right, run `git show <sha>` and you're done. If the results are scattered or you realize you need context across a longer span, move to **timeline**: take the date range implied by the recall results and feed it back in. The timeline fills in adjacent commits and run logs that recall's keyword filter may have missed.

If timeline shows a cluster of activity around a theme, and you want to understand the whole arc — not just the individual entries — dispatch **summary**. Summary reads commit bodies in full and synthesizes across all sources, so it picks up design decisions that weren't in the commit message but appeared in a run log or changelog entry.

All three agents search the same substrate:

1. `.logs/changelog.md` — functional prose distilled from commits by `lazy-log.distill`. Already written in user-facing language; the fastest match for recall and the highest-signal source for summary.
2. `.logs/claude/**/*.md` — every skill/agent/command run log, each tagged with the `git_sha` that was current at the time. The bridge from "the AI did Y" back to the commit.
3. `.logs/commits.jsonl` — raw commit metadata captured by the post-commit hook on every `git commit`. No LLM call, no prompt — just sha, date, author, message, and files.
4. **Git log and memory** — `git log --grep` for commit-message search, `git log -S` for diff-content search, and the project's memory files for context that was retained across sessions.

## Where this fits

The distilled changelog (`.logs/changelog.md`) is the highest-signal source for all three agents, because it is already written as user-facing themed prose. A well-maintained changelog means recall returns tier-1 matches immediately, timeline's day-groups contain meaningful summaries rather than raw commit subjects, and summary has pre-digested material to cluster from. Running `/lazy-log.distill` after meaningful commits — described in the changelog block — directly improves the quality of every change-history query.

## How the three agents share a substrate
