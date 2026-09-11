---
name: lazy-log.clean
description: "Run when the operator asks to tidy `./.logs/claude/` — stray or misnamed run-log folders, clusters of anonymous `task-N` dirs, logs left behind by skills that no longer exist. Read-first and interactive: classifies every folder against the live artifact names and offers merge / distill-to-memory / delete / leave before anything is touched."
allowed-tools: Read, Write, Glob, Grep, Bash(mkdir -p *), Bash(date *), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(ls *), Bash(stat *), Bash(find *), Bash(mv *), Bash(rmdir *), Bash(rm -rf .logs/claude/*), Bash(git rev-parse*), AskUserQuestion, Agent
---
# Run-Log Housekeeping

Classify every folder under `./.logs/claude/` against the live set of canonical skill/agent/command names, surface orphans, offer to distill substantive logs into Hindsight memory before deletion, and apply the user's choices in one final pass. Re-runnable; idempotent on repeat answers.

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve canonical name set`
   - `Step 2 — Enumerate log folders`
   - `Step 3 — Stale-canonical age check`
   - `Step 4 — Rename-candidate review`
   - `Step 5 — Pattern-clustered orphan review`
   - `Step 6 — Waivered-bucket review`
   - `Step 7 — Other orphan review`
   - `Step 8 — Distill execution`
   - `Step 9 — Apply deletions`
   - `Step 10 — Report + log run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `none-stale`, `no-rename-candidates`, `cluster-left`, `applied`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Pre-flight invariants

- The skill operates on `./.logs/claude/` relative to the current working directory. If that directory does not exist, abort with **absent** for every step and write the run log anyway.
- All filesystem mutations (merges and deletions) are deferred to Step 9. Steps 3–7 collect intent into in-memory action lists; nothing on disk changes until the user has answered every prompt.
- One `AskUserQuestion` at a time — wait for the answer before the next prompt. Never bulk-render options as prose.

## Step 1: Resolve canonical name set

Run the helper script and parse its JSON output:

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-log.clean/scripts/resolve-canonical.py"
```

The script returns `{ "canonical": [...], "by_kind": {...}, "sources": {...} }`. Read the `canonical` array into a set called `CANONICAL`.

Outcome line: `resolved <N> canonical names from <sources.files_scanned> files` — or `failed: <reason>` if the script errors. If `failed`, abort the skill (skip to Step 10) — without a canonical set, every folder would be flagged as orphan.

## Step 2: Enumerate log folders

For each immediate subdirectory of `./.logs/claude/`:

- `name`: directory name
- `file_count`: number of `*.md` files inside
- `oldest`, `newest`: oldest and newest `*.md` filename (they are timestamp-named, so lexical sort = chronological)

Classify each folder into exactly one bucket:

| Bucket | Definition |
|---|---|
| `waivered` | `name` is a key in `waivered` (from Step 1's JSON). |
| `canonical` | `name` is in `CANONICAL` and NOT in `waivered`. |
| `orphan-rename-candidate` | not in `CANONICAL`; `difflib.SequenceMatcher(None, name, c).ratio() ≥ 0.8` for some `c` in `CANONICAL`. Pair with the highest-ratio match. |
| `orphan-pattern` | not in `CANONICAL`; matches one of: `^task-\d+$`, `^subagent-task-\d+$`, `^subagent-audit-fixup$`, `^plan-execute$`, `^plan-execute-\d+$` |
| `orphan-other` | none of the above |

Use a one-shot Python invocation (via `Bash(python3 *)`) to do the enumeration and classification — pass both `CANONICAL` and the `waivered` keys as JSON on stdin so a name appearing in both routes to the `waivered` bucket first. Capture the five bucket lists as in-memory state.

Outcome line: `enumerated <total>: waivered=<w>, canonical=<a>, rename=<b>, pattern=<c>, other=<d>`.

## Step 3: Stale-canonical age check

Filter `canonical` bucket for folders whose `newest` log file is older than 30 days (compare against `date -u +%Y-%m-%d`).

- If the filtered list is empty, outcome line: `none-stale`. Move to Step 4.
- Otherwise, for each stale folder print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 3 — Stale-canonical age check; target ./.logs/claude/<name>/
- Found: canonical folder `<name>` — <file_count> logs, <oldest> → <newest>; newest is <N> days old (threshold 30)
- Why asking: the artifact still exists, so the folder is live — whether its old logs are worth keeping is the operator's call
- Answers: `keep` — untouched, re-asked on the next run while it stays stale; `archive-then-delete` — substantive logs distilled to memory in Step 8, folder deleted in Step 9; `delete` — folder deleted in Step 9 without distilling
AskUserQuestion: header "Stale log folder", question "Log folder ./.logs/claude/<name>/ has <file_count> logs from <oldest> to <newest>, newest <N> days old — keep, archive then delete, or delete it?", options with descriptions.
```

  - options, each with a `description` restating its Answers line:
    - `keep` — leave folder untouched
    - `archive-then-delete` — distill substantive logs to memory in Step 8, then delete the folder in Step 9
    - `delete` — delete in Step 9 without distilling

Append each chosen action to the corresponding intent list. Outcome line: `stale-decided <count> (kept=<k>, archive=<a>, delete=<d>)`.

## Step 4: Rename-candidate review

For each `orphan-rename-candidate` (paired with its canonical match `target`), print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 4 — Rename-candidate review; target ./.logs/claude/<name>/ → ./.logs/claude/<target>/
- Found: `<name>` is not a canonical name; closest canonical `<target>` (similarity <ratio>); <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: a near-match may be a renamed skill or an unrelated name — only the operator knows
- Answers: `merge` — logs moved into `<target>/` and the emptied source removed in Step 9, never re-asked; `distill-then-delete` — distilled to memory in Step 8, deleted in Step 9; `delete` — deleted in Step 9 without distilling; `leave` — untouched, re-asked on the next run
AskUserQuestion: header "Rename candidate", question "Merge log folder ./.logs/claude/<name>/ into canonical ./.logs/claude/<target>/ (similarity <ratio>), or distill, delete, or leave it?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `merge` — `mv <source>/*.md <target>/` then `rmdir <source>` (in Step 9)
  - `distill-then-delete` — distill in Step 8, delete in Step 9
  - `delete` — delete in Step 9 without distilling
  - `leave` — no action

Append to intent lists. Outcome line: `rename-decided <count>` or `no-rename-candidates`.

## Step 5: Pattern-clustered orphan review

Group the `orphan-pattern` bucket by the regex that matched. For each cluster, print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that cluster:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 5 — Pattern-clustered orphan review; target <count> folders under ./.logs/claude/ matching `<pattern>`
- Found: `<example1>`, `<example2>`, … — anonymous subagent run dirs; <total files> logs, <oldest> → <newest> across the cluster
- Why asking: these dirs map to no artifact, but deletion is irreversible and the operator may want their content distilled first
- Answers: `delete-all` — every folder in the cluster deleted in Step 9; `distill-then-delete-all` — substantive logs distilled in Step 8, all deleted in Step 9; `leave-all` — untouched, re-asked on the next run; `per-folder` — one Step 7 prompt per folder in this cluster
AskUserQuestion: header "Orphan cluster", question "<count> log folders under ./.logs/claude/ match `<pattern>` (`<example1>`, `<example2>`, …) — delete all, distill then delete all, leave all, or decide per folder?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `delete-all` — schedule every folder in the cluster for deletion in Step 9
  - `distill-then-delete-all` — distill substantive logs in Step 8, delete in Step 9
  - `leave-all` — no action
  - `per-folder` — fall through to one prompt per folder in this cluster (same options as Step 7)

Append to intent lists. Outcome line: `cluster-decided <cluster_count>` or `no-pattern-orphans`.

## Step 6: Waivered-bucket review

For each folder in the `waivered` bucket, print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 6 — Waivered-bucket review; target ./.logs/claude/<name>/
- Found: `<name>` maps to a live artifact carrying `logging-waiver: "<reason>"` (from Step 1's JSON); <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: the artifact still exists and only its logging was switched off — the logs are residue, but deletion is irreversible
- Answers: `delete` — deleted in Step 9; `distill-then-delete` — distilled in Step 8, deleted in Step 9; `leave` — untouched, re-asked on the next run; `delete-all-waivered` — (first prompt only) every remaining waivered folder scheduled for deletion, no further Step 6 prompts
AskUserQuestion: header "Waivered logs", question "Log folder ./.logs/claude/<name>/ belongs to an artifact whose logging is waived (\"<reason>\") — delete, distill then delete, leave, or delete every waivered folder?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `delete` (Recommended) — schedule for deletion in Step 9
  - `distill-then-delete` — distill in Step 8, delete in Step 9
  - `leave` — no action
  - `delete-all-waivered` — first-prompt-only escape; schedule every remaining `waivered` folder for deletion

Append to intent lists. Outcome line: `waivered-decided <count>` or `no-waivered`.

## Step 7: Other orphan review

For each folder in the `orphan-other` bucket (including any "per-folder" fall-throughs from Step 5), print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 7 — Other orphan review; target ./.logs/claude/<name>/
- Found: `<name>` matches no canonical name, no waiver, no known pattern; <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: the folder may be a retired artifact worth distilling or plain noise — only the operator knows
- Answers: `distill-then-delete` — distilled in Step 8, deleted in Step 9; `delete` — deleted in Step 9; `leave` — untouched, re-asked on the next run
AskUserQuestion: header "Orphan logs", question "Log folder ./.logs/claude/<name>/ matches no live skill, agent, or command — distill then delete, delete, or leave it?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `distill-then-delete` — distill in Step 8, delete in Step 9
  - `delete` — delete in Step 9
  - `leave` — no action

Append to intent lists. Outcome line: `other-decided <count>` or `no-other-orphans`.

## Step 8: Distill execution

Process every folder marked for distillation across Steps 3–7 in a single pass.

For each folder:
1. Read every `*.md` log file inside.
2. Extract the `## Result` section, plus any line containing `decided`, `failed`, `error`, `surprised`, or `unexpected`.
3. **Substance gate**: if the union of extracted text is < 100 chars and contains no error/decision keywords, skip with outcome `trivial-skip` for that folder.
4. Otherwise, summarize into one or two terse one-sentence facts (decisions taken, errors hit, surprising results) and call `mcp__memory-project__retain` per fact, with:
   - `tags`: `["log-distill", "<folder-name>"]` plus any obvious topical tags
   - `context`: the original folder name and date range

Aggregate outcome line: `distilled <facts> from <folders> (trivial-skip=<s>)` or `none`.

## Step 9: Apply deletions

Execute the deferred filesystem actions in this order (so merges land before any of their source folders disappear):

1. **Merges** from Step 4: for each `(source, target)` pair —
   - `Bash: mkdir -p .logs/claude/<target>`
   - `Bash: mv .logs/claude/<source>/*.md .logs/claude/<target>/` (handles empty-glob gracefully)
   - `Bash: rmdir .logs/claude/<source>` (only removes if now empty)
2. **Deletions** from Steps 3, 4, 5, 6, 7:
   - `Bash: rm -rf .logs/claude/<name>` per folder marked for deletion.

Refuse to delete or merge a folder whose name is empty or contains `..` / `/`. Refuse to operate outside `./.logs/claude/`.

Outcome line: `applied merges=<m> deletions=<d>` — or `none` if both lists are empty.

## Failure modes

- **`/lazy-log.clean` aborts immediately: ".logs/claude/ absent"** — the log directory does not exist yet (no skill has ever logged in this repo) → run any logged skill once to create it, then re-run clean.
- **Step 1 aborts: "failed: \<reason\>"** — the canonical-name resolver script errored (e.g. Python missing, `CLAUDE_PLUGIN_ROOT` unset, or malformed JSON) → check the reason string; re-run `/lazy-core.install` to ensure the plugin is properly set up, then retry.

## Step 10: Report + log run

### Report

Render exactly one line per Step 1–9, in order, using the outcome strings collected above. Then a final `## Summary` table:

```
| Bucket | Before | Kept | Merged | Deleted | Distilled |
| waivered               |  N |  N |  – |  N |  N |
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
