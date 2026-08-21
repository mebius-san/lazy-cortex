---
name: lazy-wiki.domain-sync
description: "Use when the domain-spec tree needs regenerating right now — this checkout runs no runtime daemon, domain markers or the dictionary just changed and the operator wants the docs current, or a `/lazy-python.knowledge-sweep` backfill has landed. Computes the domain plan, dispatches the domain-spec writer synchronously per changed group, removes orphaned docs, rebuilds `domains.md`, and makes one commit under the operator identity."
allowed-tools: Read, Bash(lazycortex-wiki *), Bash(date -u *), Bash(git *), Bash(mkdir -p *), Bash(rm *), Write, Agent, TaskCreate, TaskUpdate, TaskList
---
# lazy-wiki.domain-sync

Regenerate the domain-spec tree without the runtime daemon — entirely in the current Claude Code session. The deterministic core (`domain-plan`, `domain-apply-index`) decides *what* changed; this skill orchestrates by dispatching the `lazy-wiki.domain-spec-writer` agent as a synchronous subagent in **tail-off mode** (`tail: false`) per changed group. There are **no job dirs** — each writer receives its group's data in the dispatch prompt, writes the doc file, and stops; this skill owns orphan removal, the single index rebuild, and the single commit. The daemon path (`lazy-wiki.domain-scan` git routine + `lazy-wiki.domain-full` weekly schedule) is unaffected and runs the same detect through `domain-tick`.

Invocation: `/lazy-wiki.domain-sync`

Prerequisites: `/lazy-wiki.install` has run and `wiki.domains` is configured in `.claude/lazy.settings.json` (via `/lazy-wiki.configure domains`). The working tree should be clean for the output paths — this skill writes and commits doc files and `domains.md`.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Compute the domain plan`
   - `Step 2 — Write each changed group`
   - `Step 3 — Remove orphaned docs`
   - `Step 4 — Rebuild the index`
   - `Step 5 — Commit touched files`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. No-ops must emit an explicit outcome (`empty-set`, `unchanged`, …).
3. **Do not reach the Log step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug.

## Step 1 — Compute the domain plan

Compute `<repo-root>` via `Bash(git rev-parse --show-toplevel)`, then run:

```
Bash(lazycortex-wiki domain-plan --repo <repo-root>)
```

A non-zero exit means `wiki.domains` is not configured — surface the message, point at `/lazy-wiki.configure domains`, and stop.

Parse the JSON: `changed_groups` (each entry: `group`, `hash`, `files`, `doc_path`, `gloss`, `blocks`, `contracts`), `orphaned_docs`, `unlisted_docs`, `unknown_groups`, `index_path`, `index_needs_update`, `language`, `dictionary`, `output`. Report any `unknown_groups` to the operator verbatim (groups used in code but absent from the dictionary — `/lazy-wiki.doctor` territory; this run skips them, never generates them).

`contracts` is the group's attributed `Contract:` blocks (each entry: `path`, `line`, `text`, `symbol` — `symbol` may be `null` when the file did not parse as Python). A `Contract:` marker carries no group of its own; a block is attributed to the nearest `Domain(…)` header in the same file, so `contracts` may be empty even when `blocks` is not.

`unlisted_docs` is the subset of `orphaned_docs` whose group the dictionary no longer lists (a renamed or deleted dictionary entry, not a group that lost its blocks). Those docs are deleted with the rest in Step 3 — carry the list to the Report step and name every path there, so a deletion the operator did not intend is visible in the same run that made it.

If `changed_groups` and `orphaned_docs` are both empty and `index_needs_update` is false, the tree is in sync — report `empty-set`, mark Steps 2–5 `skipped` with outcome `empty-set`, and go to the Log step.

Outcome: `planned: changed=<n> orphaned=<m> unknown=<k>`.

## Step 2 — Write each changed group

For each entry in `changed_groups`, dispatch the writer synchronously — **no job dir**; the prompt carries the entry's data and the agent writes the doc itself:

```
Agent(subagent_type: "lazycortex-wiki:lazy-wiki.domain-spec-writer",
      prompt: "kind=domain-spec, tail=false. repo_root=<repo-root>, group=<group>, gloss=<gloss>, language=<language>, doc_path=<doc_path>, hash=<hash>, blocks=<the entry's blocks JSON>, contracts=<the entry's contracts JSON>. Read the source files the blocks name, verify every formula against the code, and write the doc at doc_path whole (frontmatter domain_group + domain_hash=<hash>, fixed Terms/Principles/Mechanics sections, Obsidian LaTeX formulas, no source references, target language; a trailing Contracts section listing every contract's guarantee text with its path:symbol anchor when contracts is non-empty). STOP after writing — do NOT touch the index, do NOT run git. Report the outcome.")
```

If a writer reports an error, skip that group and continue; it is re-detected on the next run. Track each written `doc_path` for the Step 5 commit. A `doc_path` that did not exist before this run must be registered with `Bash(git add -N <doc_path>)` so the commit pathspec can see it.

Outcome: `written:<n>` (or `empty-set`).

## Step 3 — Remove orphaned docs

For each path in `orphaned_docs`, the doc is deleted — the tree is a derivative of the code and the dictionary, so orphaned docs do not exist. A path is on that list for one of two reasons: its group has no blocks left in code, or its group is no longer listed in the dictionary (the `unlisted_docs` subset — no writer will ever refresh it again while the group is unlisted).

```
Bash(rm <repo-root>/<orphaned-doc-path>)
```

Plain `rm`, never `git rm` (auto-stages, violating the pathspec discipline). Track each removed path for the Step 5 commit.

Outcome: `dropped:<n>` (or `empty-set`); when `unlisted_docs` is non-empty, append `unlisted:<m>`.

## Step 4 — Rebuild the index

After all writes and removals:

```
Bash(lazycortex-wiki domain-apply-index --repo <repo-root>)
```

Parse `{index, updated}`; track the index path for the commit when `updated` is true.

Outcome: `index-updated` or `index-unchanged`.

## Step 5 — Commit touched files

Commit everything in one atomic step under the operator identity (not a bot `git_author` — the skill owns this commit), naming every touched path in the pathspec:

```
Bash(git commit -m "wiki(domains): sync (write N / drop M)" -- <doc-1> … <orphan-1> … <index-path>)
```

No `git add` — the pathspec carries the worktree content straight into the commit, which is what `lazy-core.git`'s pathspec discipline requires and what leaves the operator's index alone (new files were registered with `git add -N` in Step 2). Do NOT invoke any project-level pre-commit pipeline — these are generated data files, not plugin source. If nothing changed (idempotent re-run produced no byte change), report `unchanged` and do not create an empty commit.

Outcome: `committed` / `unchanged`.

## Logging

Write a run log to `./.logs/claude/lazy-wiki.domain-sync/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-wiki.domain-sync)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-wiki.domain-sync/<timestamp>.md` with frontmatter:

```
---
git_sha: <sha>
git_branch: <branch>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: none
---
# lazy-wiki.domain-sync

## Actions
- <bullet per step with outcome>

## Result
<success/failure + one-sentence summary: written/dropped counts, index and commit outcomes>
```

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. Append the `unknown_groups` list (when non-empty) so the operator can file them into the dictionary, and the `unlisted_docs` list (when non-empty) naming every doc deleted because its group left the dictionary — a rename in the dictionary is the usual cause, and restoring the group name brings the doc back on the next run.

## Failure modes

- **`domain-plan` exits non-zero saying wiki.domains is not configured** — the `wiki.domains` section is missing from `lazy.settings.json` → run `/lazy-wiki.configure domains`, then re-run.
- **A writer subagent reports an error** — unreadable source file or malformed dispatch data → the group is skipped this run and re-detected on the next; surface the message and continue.
- **Groups reported under `unknown_groups`** — code carries `Domain(<group>)` blocks whose group is not in the dictionary → either add the group to the dictionary by hand and re-run, or run `/lazy-python.knowledge-sweep`, which grows the dictionary with the operator and refiles the blocks under the accepted groups before this skill runs again. The sweep is the route when several groups are reported at once, when the blocks sit under `Domain(unfiled):`, or when a dictionary rename left the old group name in the code; `/lazy-wiki.doctor` flags the same condition.
- **Docs deleted under `unlisted_docs`** — a group was renamed or removed in the dictionary, so its generated doc is no longer regenerable and this run dropped it → restore the group key in the dictionary and re-run to bring the doc back, or accept the removal and let `/lazy-python.knowledge-sweep` refile the code's blocks under the new group name.
- **The commit at Step 5 stages nothing** — an idempotent re-run produced no byte change → reported as `unchanged`; no empty commit is created.
