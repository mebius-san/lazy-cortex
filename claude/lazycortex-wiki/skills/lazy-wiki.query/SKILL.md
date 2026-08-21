---
name: lazy-wiki.query
description: "Use when a question needs material the wiki curates — 'why is it built this way', 'where is X described', 'what relates to Y', or any request whose answer lives in files a wiki scope covers. Run it BEFORE grepping or opening files in a covered scope, and whenever the user asks about a topic rather than a specific file. A research skill: given a question, it hands back a bounded matched slice of the wiki graph, never the whole topic index. With the `Agent` tool available it dispatches per-scope seekers plus one gatherer so the topic index and traversed node bodies never enter the calling context; without `Agent` (a one-shot expert job or subagent) it runs the same lookup agentless, reading the scope's topics.md directly in its own context."
research: true
allowed-tools: Read, Grep, Agent, Bash(test -f *), Bash(date -u *), Bash(git rev-parse *), Bash(mkdir -p *), Write
dirty-tree-waiver: "writes only its run log under .logs/ (untracked) — never a tracked file"
---
# lazy-wiki.query

Answer a question by traversing the wiki graph — without loading the large `topics.md` or the traversed node bodies into a context worth protecting. This skill runs in one of two modes, chosen by the executing agent before Phase 1:

- **Dispatcher mode** — the executing agent has the `Agent` tool (the main session, or any subagent whose own tool list carries it). Asks a `lazy-wiki.seeker` subagent (one per scope) to pick entry points from each scope's `topics.md`, validates those paths, then hands them to a single `lazy-wiki.gatherer` subagent that walks See-also and synthesises the answer. Only the chosen entry points and the final answer enter this context.
- **Agentless mode** — the executing agent has no `Agent` tool: a one-shot context (an expert job, or a subagent dispatched without further fan-out capability) with no downstream context to protect. The executing agent reads the relevant scope's `topics.md` directly, picks entry points itself, and walks glossed See-also links itself — the same traversal the seeker/gatherer perform, done here because there is nowhere else to put it.

Invocation: `/lazy-wiki.query "<question>"`

Prerequisites: `/lazy-wiki.install` has run and at least one scope is configured in `.claude/lazy.settings.json[wiki.scopes]`.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps, run in either mode. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Load wiki config`
   - `Phase 2 — Resolve entry points`
   - `Phase 3 — Gather answer`
   - `Phase 4 — Present answer and seed`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`no-scopes`, `no-entry-points`, …).
3. **Do not reach the Log step until `TaskList` shows every prior task `completed`.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Phase 1 — Load wiki config

`Read` `.claude/lazy.settings.json`. Extract `wiki.scopes` — the map of scope-id → config (each carries `topics_index`).

If the file is absent or `wiki.scopes` is empty, abort: *"No wiki scopes configured — run `/lazy-wiki.install` and `/lazy-wiki.configure` first."*

Resolve the repo root via `Bash(git rev-parse --show-toplevel)`. For each scope, the index's absolute path is `<repo-root>/<topics_index>`.

Outcome: `loaded` (or `no-scopes`).

## Phase 2 — Resolve entry points

### Dispatcher mode (Agent tool available)

For each scope whose `topics_index` exists on disk (`Bash(test -f <abs-index-path>)`), dispatch a seeker — **in parallel** (issue the `Agent` calls in a single message):

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.seeker",
      prompt: "question=<the question verbatim>, scope_id=<id>, topics_index_abs_path=<abs-index-path>, repo_root=<repo-root>. Read only that index; return the entry-points block per your contract.")
```

If no scope has a `topics_index` on disk, skip to Phase 4 with an empty entry-point set and note it.

Collect each seeker's `### selected` lines into one merged list, tagging each with its `scope_id`. **Validate every path on disk AND rebase it to repo-relative** before passing it on. The seeker returns each `<rel-link>` *verbatim from the index*, i.e. relative to the index file's directory — NOT relative to the repo root (the two differ whenever `topics_index` is not at the repo root). So: the index dir is `<repo-root>/<dirname(topics_index)>`; the node is at `<repo-root>/<dirname(topics_index)>/<rel-link>`. `Bash(test -f <that absolute path>)`. The **repo-relative** path to carry forward is `<dirname(topics_index)>/<rel-link>` (drop a leading `./`). This is what the gatherer receives, so its `repo_root`-based resolution is correct.

Drop any path that fails the test and record it as `dropped: <path> (not on disk)`.

If the merged-and-validated set is empty, proceed to Phase 4 noting `no-entry-points`.

### Agentless mode (no Agent tool)

For each scope whose `topics_index` exists on disk (`Bash(test -f <abs-index-path>)`), `Read` the index yourself — this is the one context in which reading `topics.md` directly is correct (per `lazy-wiki.navigation` § When to query). Pick the entry points a seeker would: the node paths whose gloss addresses the question, tagged with their `scope_id`. Paths come from the index verbatim, so they're already on disk; no separate validation pass is needed.

If no scope has a `topics_index` on disk, proceed to Phase 4 with an empty entry-point set.

Outcome: `seeded (<n> entry points)` in dispatcher mode, `seeded` in agentless mode, or `no-entry-points`.

## Phase 3 — Gather answer

### Dispatcher mode (Agent tool available)

Dispatch exactly one gatherer with the question and the merged, validated entry points:

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.gatherer",
      prompt: "question=<the question verbatim>. entry_points=<JSON array of {scope_id, path, gloss}>. repo_root=<repo-root>. Traverse from these entry points per your contract and return the answer block.")
```

If Phase 2 produced no entry points, skip the dispatch and carry an empty answer into Phase 4.

### Agentless mode (no Agent tool)

Do what the gatherer would, in this same context: `Read` each Phase-2 entry point's body, follow its `# See also` (`#protected/wiki/see-also`) glossed links that bear on the question, `Read` those in turn — bounded to what the question needs, not an exhaustive walk. Fall back to `Grep` for the node's repo-relative path across the scope only when the entry points and their forward links don't answer it (backlinks). Synthesise the same shape the gatherer returns: `## answer` plus `## sources` (the paths actually read).

If Phase 2 produced no entry points, skip straight to Phase 4 with an empty answer.

Outcome: `gathered` | `skipped-no-entry-points`.

## Phase 4 — Present answer and seed

Present to the user:

1. The synthesised `## answer` and `## sources` verbatim — from the gatherer in dispatcher mode, from your own Phase 3 walk in agentless mode — or, when there were no entry points, an explicit *"No wiki material matched this question."*
2. A short **Entry points** list showing the seed the answer worked from (path + gloss per scope), plus any `dropped:` lines from Phase 2 — so the seed is visible and debuggable.

Dispatcher mode: do not re-read node bodies or the index into this context — relay the subagents' results. Agentless mode: no such caller to relay to — this context already holds what it read.

Outcome: `presented`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.query/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.query)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.query/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<question>"
---
# lazy-wiki.query

## Actions
- <one line per Phase/step above with its outcome word>

## Result
<success/failure + one-sentence summary>
```

Outcome: `logged`.
