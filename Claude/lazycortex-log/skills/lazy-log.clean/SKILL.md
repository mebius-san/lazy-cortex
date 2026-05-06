---
name: lazy-log.clean
description: "Interactive housekeeping for `./.logs/claude/`. Classifies each subdirectory against the live set of canonical skills/agents/commands; offers merge / distill-to-memory / delete / leave per orphan, batched by pattern when a cluster of anonymous folders (e.g. `task-N`) would otherwise produce dozens of prompts. Read-first — no folder is touched until the user has approved every action."
allowed-tools: Read, Glob, Grep, Bash(mkdir -p *), Bash(date *), Bash(python3 *), Bash(ls *), Bash(stat *), Bash(find *), Bash(mv *), Bash(rmdir *), Bash(rm -rf .logs/claude/*), Bash(git rev-parse*)
---
# Run-Log Housekeeping

Classify every folder under `./.logs/claude/` against the live set of canonical skill/agent/command names, surface orphans, offer to distill substantive logs into Hindsight memory before deletion, and apply the user's choices in one final pass. Re-runnable; idempotent on repeat answers.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve canonical name set`
   - `Step 2 — Enumerate log folders`
   - `Step 3 — Stale-canonical age check`
   - `Step 4 — Rename-candidate review`
   - `Step 5 — Pattern-clustered orphan review`
   - `Step 6 — Other orphan review`
   - `Step 7 — Distill execution`
   - `Step 8 — Apply deletions`
   - `Step 9 — Report + log run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `none-stale`, `no-rename-candidates`, `cluster-left`, `applied`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Pre-flight invariants

- The skill operates on `./.logs/claude/` relative to the current working directory. If that directory does not exist, abort with **absent** for every step and write the run log anyway.
- All filesystem mutations (merges and deletions) are deferred to Step 8. Steps 3–6 collect intent into in-memory action lists; nothing on disk changes until the user has answered every prompt.
- One `AskUserQuestion` at a time — wait for the answer before the next prompt. Never bulk-render options as prose.

## Step 1: Resolve canonical name set

Run the helper script and parse its JSON output:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-log.clean/scripts/resolve-canonical.py
```

The script returns `{ "canonical": [...], "by_kind": {...}, "sources": {...} }`. Read the `canonical` array into a set called `CANONICAL`.

Outcome line: `resolved <N> canonical names from <sources.files_scanned> files` — or `failed: <reason>` if the script errors. If `failed`, abort the skill (skip to Step 9) — without a canonical set, every folder would be flagged as orphan.

## Step 2: Enumerate log folders

For each immediate subdirectory of `./.logs/claude/`:

- `name`: directory name
- `file_count`: number of `*.md` files inside
- `oldest`, `newest`: oldest and newest `*.md` filename (they are timestamp-named, so lexical sort = chronological)

Classify each folder into exactly one bucket:

| Bucket | Definition |
|---|---|
| `canonical` | `name` is in `CANONICAL` |
| `orphan-rename-candidate` | not in `CANONICAL`; `difflib.SequenceMatcher(None, name, c).ratio() ≥ 0.8` for some `c` in `CANONICAL`. Pair with the highest-ratio match. |
| `orphan-pattern` | not in `CANONICAL`; matches one of: `^task-\d+$`, `^subagent-task-\d+$`, `^subagent-audit-fixup$`, `^plan-execute$`, `^plan-execute-\d+$` |
| `orphan-other` | none of the above |

Use a one-shot Python invocation (via `Bash(python3 *)`) to do the enumeration and classification — pass `CANONICAL` as JSON on stdin. Capture the four bucket lists as in-memory state.

Outcome line: `enumerated <total>: canonical=<a>, rename=<b>, pattern=<c>, other=<d>`.

## Step 3: Stale-canonical age check

Filter `canonical` bucket for folders whose `newest` log file is older than 30 days (compare against `date -u +%Y-%m-%d`).

- If the filtered list is empty, outcome line: `none-stale`. Move to Step 4.
- Otherwise, for each stale folder issue **one** `AskUserQuestion`:

  - question: ``Folder `<name>` has logs from <oldest> to <newest>. Newest is <N> days old. What do you want to do?``
  - options:
    - `keep` — leave folder untouched
    - `archive-then-delete` — distill substantive logs to memory in Step 7, then delete the folder in Step 8
    - `delete` — delete in Step 8 without distilling

Append each chosen action to the corresponding intent list. Outcome line: `stale-decided <count> (kept=<k>, archive=<a>, delete=<d>)`.

## Step 4: Rename-candidate review

For each `orphan-rename-candidate` (paired with its canonical match `target`), issue **one** `AskUserQuestion`:

- question: ``Folder `<name>` looks like a renamed/typo'd version of canonical `<target>` (similarity <ratio>). Action?``
- description includes `<file_count>` files, oldest/newest dates, and a one-line preview of each top-3 log's `## Result` heading if available.
- options:
  - `merge` — `mv <source>/*.md <target>/` then `rmdir <source>` (in Step 8)
  - `distill-then-delete` — distill in Step 7, delete in Step 8
  - `delete` — delete in Step 8 without distilling
  - `leave` — no action

Append to intent lists. Outcome line: `rename-decided <count>` or `no-rename-candidates`.

## Step 5: Pattern-clustered orphan review

Group the `orphan-pattern` bucket by the regex that matched. For each cluster, issue **one** `AskUserQuestion`:

- question: ``<count> folders matching `<pattern>` (`<example1>`, `<example2>`, …) — these are anonymous subagent runs. Action?``
- options:
  - `delete-all` — schedule every folder in the cluster for deletion in Step 8
  - `distill-then-delete-all` — distill substantive logs in Step 7, delete in Step 8
  - `leave-all` — no action
  - `per-folder` — fall through to one prompt per folder in this cluster (same options as Step 6)

Append to intent lists. Outcome line: `cluster-decided <cluster_count>` or `no-pattern-orphans`.

## Step 6: Other orphan review

For each folder in the `orphan-other` bucket (including any "per-folder" fall-throughs from Step 5), issue **one** `AskUserQuestion`:

- question: ``Folder `<name>` (<file_count> logs, <oldest> → <newest>) does not match any canonical name. Action?``
- description includes one-line previews of up to three logs' `## Result` sections.
- options:
  - `distill-then-delete` — distill in Step 7, delete in Step 8
  - `delete` — delete in Step 8
  - `leave` — no action

Append to intent lists. Outcome line: `other-decided <count>` or `no-other-orphans`.

## Step 7: Distill execution

Process every folder marked for distillation across Steps 3–6 in a single pass.

For each folder:
1. Read every `*.md` log file inside.
2. Extract the `## Result` section, plus any line containing `decided`, `failed`, `error`, `surprised`, or `unexpected`.
3. **Substance gate**: if the union of extracted text is < 100 chars and contains no error/decision keywords, skip with outcome `trivial-skip` for that folder.
4. Otherwise, summarize into one or two terse one-sentence facts (decisions taken, errors hit, surprising results) and call `mcp__memory-project__retain` per fact, with:
   - `tags`: `["log-distill", "<folder-name>"]` plus any obvious topical tags
   - `context`: the original folder name and date range

Aggregate outcome line: `distilled <facts> from <folders> (trivial-skip=<s>)` or `none`.

## Step 8: Apply deletions

Execute the deferred filesystem actions in this order (so merges land before any of their source folders disappear):

1. **Merges** from Step 4: for each `(source, target)` pair —
   - `Bash: mkdir -p .logs/claude/<target>`
   - `Bash: mv .logs/claude/<source>/*.md .logs/claude/<target>/` (handles empty-glob gracefully)
   - `Bash: rmdir .logs/claude/<source>` (only removes if now empty)
2. **Deletions** from Steps 3, 4, 5, 6:
   - `Bash: rm -rf .logs/claude/<name>` per folder marked for deletion.

Refuse to delete or merge a folder whose name is empty or contains `..` / `/`. Refuse to operate outside `./.logs/claude/`.

Outcome line: `applied merges=<m> deletions=<d>` — or `none` if both lists are empty.

## Failure modes

- **`/lazy-log.clean` aborts immediately: ".logs/claude/ absent"** — the log directory does not exist yet (no skill has ever logged in this repo) → run any logged skill once to create it, then re-run clean.
- **Step 1 aborts: "failed: \<reason\>"** — the canonical-name resolver script errored (e.g. Python missing, `CLAUDE_PLUGIN_ROOT` unset, or malformed JSON) → check the reason string; re-run `/lazy-log.install` to ensure the plugin is properly set up, then retry.

## Step 9: Report + log run

### Report

Render exactly one line per Step 1–8, in order, using the outcome strings collected above. Then a final `## Summary` table:

```
| Bucket | Before | Kept | Merged | Deleted | Distilled |
| canonical              |  N |  N |  – |  N |  N |
| orphan-rename-candidate|  N |  N |  N |  N |  N |
| orphan-pattern         |  N |  N |  – |  N |  N |
| orphan-other           |  N |  N |  – |  N |  N |
```

A missing per-step line is a bug. Do not render the report with gaps.

### Log the run

Per the `lazy-log.logging` rule:

1. `Bash(mkdir -p .logs/claude/lazy-log.clean)`
2. `Write` to `./.logs/claude/lazy-log.clean/<UTC-timestamp>.md` with the required frontmatter (`git_sha`, `git_branch`, `date`, `input`) and the report body.

Outcome line: `reported`.
