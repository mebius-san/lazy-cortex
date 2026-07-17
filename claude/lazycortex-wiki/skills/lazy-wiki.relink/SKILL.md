---
name: lazy-wiki.relink
description: "Daemon-free, in-session relink of one wiki scope. Computes the relink plan (initial / incremental / anchor-lost) via lazycortex-wiki relink-plan, then dispatches the wiki curator as a synchronous subagent in tail:false mode to classify then link each node — the curator applies its own curation via apply-node (C-hybrid, no collector). The skill rebuilds topics.md once between phases, records the new wiki_synced_sha anchor, and makes the single commit under the operator identity. Use when there is no runtime daemon (the plugin must work standalone) or to force an in-session relink."
allowed-tools: Read, Bash(lazycortex-wiki *), Bash(date -u *), Bash(git *), Bash(mkdir -p *), Bash(rm -rf *), Bash(test *), Bash(cp *), Write, Agent, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# lazy-wiki.relink

Relink one wiki scope without the runtime daemon — entirely in the current Claude Code session. The deterministic core (`relink-plan`, `apply-node`, `build-index`, `set-synced-sha`) decides *what* to process; this skill orchestrates by dispatching the `wiki.curator` agent as a synchronous subagent in **tail-off mode** (`tail: false`). There are **no job dirs** — the curator reads the real node (and the real `topics.md` for link) named in its dispatch prompt and **applies its own curation via `apply-node`** (C-hybrid, exactly as on the daemon — there is no collector); it just skips the *tail* (`build-index` / git-commit / `dispatch-link`), which this skill owns: the skill rebuilds the index once between phases and makes the single commit. The daemon path (event-driven `wiki.scan` + weekly `wiki.relink-weekly`) is unaffected and runs in parallel as the autonomous alternative (it, not this skill, uses the runtime's job dirs, and there the curator runs its full tail with `tail: true`).

Invocation: `/wiki.relink [<scope-id>]`. When `<scope-id>` is omitted, ask the operator which configured scope to relink.

Prerequisites: `/wiki.install` has run, at least one scope is configured in `.claude/lazy.settings.json[wiki.scopes]`, and the `wiki.curator` expert is composed. The working tree should be clean for the touched paths — this skill writes and commits node files and `topics.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve scope + compute plan`
   - `Step 2 — Classify each node`
   - `Step 3 — Normalize tags + rebuild topics index`
   - `Step 4 — Link each node`
   - `Step 5 — Prune dropped nodes`
   - `Step 6 — Commit touched files + record anchor`
   - `Step 7 — Clean up scratch`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`empty-set`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Log step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug.

## Step 1 — Resolve scope + compute plan

If no `<scope-id>` was passed, list the configured scopes (`Bash(lazycortex-wiki resolve-scope . --repo <repo-root>)` is per-path, not a lister — instead read `.claude/lazy.settings.json[wiki.scopes]` keys) and ask the operator which to relink via `AskUserQuestion`.

Compute `<repo-root>` via `Bash(git rev-parse --show-toplevel)`.

Run the plan:

```
Bash(lazycortex-wiki relink-plan <scope-id> --repo <repo-root>)
```

Parse the JSON `{mode, synced_sha, classify[], link[], drop[]}`. The three modes — `initial` (no anchor → all nodes), `incremental` (delta from `wiki_synced_sha`..HEAD), `anchor-lost` (content-hash backstop) — are all returned uniformly: process the path sets as given. Note the mode for the report.

This skill creates **no** scratch of its own — no job dirs, no out-of-tree dir. Each dispatched curator manages (and removes) its own `mktemp` curation file inside its run; nothing relink-related is ever written inside the repo.

If `classify`, `link`, and `drop` are all empty, the scope is already in sync — report `empty-set` and skip Steps 2–5 (still run Step 6 to refresh the anchor and Step 7/Log).

Outcome: `planned:<mode>`.

## Step 2 — Classify each node

Read the scope's `tag_axes` once from `.claude/lazy.settings.json[wiki.scopes][<scope-id>]`. Then capture the existing tag values as the classify **anchor**: `Bash(lazycortex-wiki collect-tags <scope-id> --repo <repo-root>)` — capture its JSON (empty `axes` on cold-start, when nothing is classified yet).

For each absolute node path in `classify[]`, dispatch the curator synchronously — **no job dir**; it reads the real node in place AND applies its own curation via `apply-node` (the skill does NOT apply — the curator owns its write, C-hybrid):

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.curator",
      prompt: "kind=classify, tail=false. node_path=<abs-node-path>, scope_id=<scope-id>, repo_root=<repo-root>, tag_axes=<comma-separated tag_axes>, existing_tags=<the collect-tags JSON from above>. Read the real node at node_path (and its own pin fields); choose wiki_summary, topics, connectors — anchor topic values to existing_tags (reuse a fitting existing value instead of coining a synonym); apply them to the node yourself via `lazycortex-wiki apply-node <node_path> --from <a mktemp curation file you create>` (this writes wiki_summary, the wiki/* tags, wiki_connectors, and the wiki_src_hash backstop), then rm the temp; STOP — do NOT build-index, git, or dispatch-link. Report the outcome.")
```

The curator writes the node via `apply-node`; the skill runs no `apply-node`. If a curator reports an error, skip that node and continue. Track each curated node path for the Step 6 commit. Outcome: `classified:<n>` (or `empty-set` when `classify[]` was empty).

## Step 3 — Normalize tags + rebuild topics index

After all classify-applies, first **consolidate the tag vocabulary** (so a cold-start run's free-form values collapse to a canon), then rebuild `topics.md` once before any link:

1. **Collect + normalize.** Capture the now-classified value set: `Bash(lazycortex-wiki collect-tags <scope-id> --repo <repo-root>)`. Dispatch the curator to judge a canonical set — **no job dir**; it self-applies via `retag` (the skill does NOT retag):

   ```
   Agent(subagent_type: "lazycortex-wiki:lazy-wiki.curator",
         prompt: "kind=normalize-tags, tail=false. scope_id=<scope-id>, repo_root=<repo-root>, collected_tags=<the collect-tags JSON from above>. Judge a canonical axis-value set; build the alias map ({axis:{old-value:new-value}} — merge a synonym, nest a subtype, or keep); apply it yourself via `lazycortex-wiki retag <scope-id> --from <a mktemp alias-map file you create> --repo <repo-root>`, then rm the temp; STOP — do NOT build-index or git. An empty map → skip retag, report empty. Report the alias map and outcome.")
   ```

   The curator runs `retag`; the skill does not. `retag` may modify any scope node whose tags were aliased — capture those paths (e.g. from `git status`) for the Step 6 commit alongside the classified nodes.

2. **Rebuild the index.** `Bash(lazycortex-wiki build-index <scope-id> --repo <repo-root>)` — once, after normalize, before Step 4. The link phase reads this freshly-populated, canonicalised catalog. Track the `topics.md` path for the Step 6 commit.

Outcome: `normalized index-rebuilt` (or `skipped-per-user-choice` only when the plan was `empty-set`).

## Step 4 — Link each node

For each absolute node path in `link[]`:

1. Compute the recall shortlist: `Bash(lazycortex-wiki find-candidates <abs-node-path> --scope <scope-id> --repo <repo-root>)` — capture its JSON-array stdout (a ranked top-N of repo-relative candidate paths; deterministic content overlap, pins honored; `[]` when nothing overlaps → the curator falls back to `topics.md` judgment).
2. Dispatch the curator synchronously — **no job dir**; it reads the real node + the real `topics.md` AND applies its own curation via `apply-node` (the skill does NOT apply):

   ```
   Agent(subagent_type: "lazycortex-wiki:lazy-wiki.curator",
         prompt: "kind=link, tail=false. node_path=<abs-node-path>, scope_id=<scope-id>, repo_root=<repo-root>, topics_path=<repo-root>/<topics_index>, candidates=<the JSON array from step 1>. Read the real node (it now carries the classify writes) and the real topics.md (and the node's own pin fields); verify the candidates first (empty → judge from topics.md); build see_also; apply it to the node yourself via `lazycortex-wiki apply-node <node_path> --from <a mktemp curation file you create>` (this grafts only the # See also section), then rm the temp; STOP — do NOT git. Report the outcome.")
   ```

The curator writes the node via `apply-node`; the skill runs no `apply-node`. If a curator reports an error, skip that node and continue. Track each curated node path for the Step 6 commit. Outcome: `linked:<n>` (or `empty-set` when `link[]` was empty).

## Step 5 — Prune dropped nodes

For each path in `drop[]`: the node was deleted since the anchor. The Step 3 index rebuild already excludes it from `topics.md` (it no longer exists on disk, so `iter_nodes` skips it), but other nodes may still carry See-also links pointing at it. Drop those dangling lines deterministically:

```
Bash(lazycortex-wiki prune-node <dropped-path> --repo <repo-root> --no-commit)
```

Run once per dropped path. `--no-commit` is mandatory here — the Step 6 commit owns all writes. Capture the `pruned_nodes` paths from each JSON result and add them to the Step 6 staging set (the index is already tracked from Step 3). A `skip (no scope)` note is fine — the node resolved to no scope and nothing was touched.

Outcome: `dropped:<n> pruned:<m>` (or `empty-set` when `drop[]` was empty).

## Step 6 — Commit touched files + record anchor

Record the new anchor, then commit everything in one atomic step under the operator identity (not the curator's `git_author` — the skill owns this commit):

1. Capture `HEAD`: `Bash(git rev-parse HEAD)`.
2. Write the anchor into `topics.md`:

   ```
   Bash(lazycortex-wiki set-synced-sha <scope-id> <HEAD> --repo <repo-root>)
   ```
3. Stage the touched node files + `topics.md` and commit in a single atomic Bash chain:

   ```
   Bash(git add <node-1> <node-2> … <topics.md> && git commit -m "wiki(relink): <scope-id> (<mode>, classify N / link M / drop K)")
   ```

   Use plain `git commit` — do NOT invoke `pub.pre-commit` (these are scope/data files, not plugin source). If the staged set is empty (idempotent re-run produced no byte change), report `unchanged` and do not create an empty commit.

Outcome: `committed` / `unchanged`.

## Step 7 — Clean up scratch

This skill creates no scratch — no job dirs, no out-of-tree dir; each curator removes its own `mktemp` curation file inside its run. So there is nothing for the skill to delete. Assert the worktree carries no relink residue (no `.experts/.wiki-relink/`, no stray curation files) — there should be none. Outcome: `cleaned` (nothing to remove).

## Logging

Write a run log to `./.logs/claude/lazy-wiki.relink/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.relink)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.relink/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<scope-id>"
---
# lazy-wiki.relink

## Actions
- <bullet per step with outcome>

## Result
<success/failure + one-sentence summary: mode, classify/link/drop counts, commit outcome>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/wiki.relink` reports "unknown scope '<id>'"** — the scope id is not in `lazy.settings.json[wiki.scopes]` → run `/wiki.configure` to create it, or re-invoke with a known id.
- **`relink-plan` returns `anchor-lost` unexpectedly** — the `wiki_synced_sha` commit became unreachable (rebase, `reset --hard`, squash, gc, shallow clone) → the plan falls back to a content-hash backstop over `wiki_src_hash`; this is expected recovery, not an error. The run records a fresh HEAD anchor at Step 6.
- **A curator subagent reports an error** — malformed input, a failed `apply-node`, or a curator-side schema violation → in tail:false the curator reports it in its reply (there is no `result/response.json`); surface the message, skip that node, and continue with the rest; the node is picked up on the next relink.
- **The commit at Step 6 stages nothing** — an idempotent re-run produced no byte change → reported as `unchanged`; no empty commit is created.
