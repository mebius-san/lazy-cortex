---
name: lazy-log.clean
description: "Run when the operator asks to tidy `./.logs/claude/` — stray or misnamed run-log folders, clusters of anonymous `task-N` dirs, logs left behind by skills that no longer exist. Read-first and interactive: classifies every folder against the live artifact names and offers merge / delete / leave before anything is touched."
allowed-tools: Read, Write, Glob, Grep, Bash(mkdir -p *), Bash(date *), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(ls *), Bash(stat *), Bash(git rev-parse*), AskUserQuestion, Agent
---
# Run-Log Housekeeping

Classify every folder under `./.logs/claude/` against the live set of canonical skill/agent/command names, surface orphans, and apply the user's choices in one final pass. Re-runnable; idempotent on repeat answers.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve canonical name set`
   - `Step 2 — Enumerate log folders`
   - `Step 3 — Stale-canonical age check`
   - `Step 4 — Rename-candidate review`
   - `Step 5 — Pattern-clustered orphan review`
   - `Step 6 — Unlogged-bucket review`
   - `Step 7 — Other orphan review`
   - `Step 8 — Apply deletions`
   - `Step 9 — Report + log run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `none-stale`, `no-rename-candidates`, `cluster-left`, `applied`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Pre-flight invariants

- The skill operates on `./.logs/claude/` relative to the current working directory. If that directory does not exist, abort with **absent** for every step and write the run log anyway.
- All filesystem mutations (merges and deletions) are deferred to Step 8. Steps 3–7 collect intent into in-memory action lists; nothing on disk changes until the user has answered every prompt.
- One `AskUserQuestion` at a time — wait for the answer before the next prompt. Never bulk-render options as prose.

## Step 1: Resolve canonical name set

Run the helper script and parse its JSON output:

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-log.clean/scripts/resolve-canonical.py"
```

The script returns `{ "canonical": [...], "by_kind": {...}, "logged": [...], "sources": {...} }`. Read the `canonical` array into a set called `CANONICAL` and the `logged` array — the artifacts whose frontmatter declares `logging: true` — into a set called `LOGGED`.

Outcome line: `resolved <N> canonical names from <sources.files_scanned> files` — or `failed: <reason>` if the script errors. If `failed`, abort the skill (skip to Step 9) — without a canonical set, every folder would be flagged as orphan.

## Step 2: Enumerate log folders

Run the classifier:

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-log.clean/scripts/log-folders.py" classify
```

The `log-folders.py classify` script reads the same canonical and logged sets Step 1 resolved and puts every immediate subdirectory of `./.logs/claude/` into exactly one bucket. It prints `{"buckets": {...}, "folders": [...]}`: `buckets` holds `unlogged` (the artifact exists but no longer writes a log, so every file is residue), `canonical`, `orphan-rename-candidate` (`{name, match, ratio}`), `orphan-pattern` and `orphan-other`; `folders` holds `{name, file_count, oldest, newest}` per folder. Capture both as in-memory state.

Outcome line: `enumerated <total>: unlogged=<u>, canonical=<a>, rename=<b>, pattern=<c>, other=<d>`.

## Step 3: Stale-canonical age check

Filter `canonical` bucket for folders whose `newest` log file is older than 30 days (compare against `date -u +%Y-%m-%d`).

- If the filtered list is empty, outcome line: `none-stale`. Move to Step 4.
- Otherwise, for each stale folder print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 3 — Stale-canonical age check; target ./.logs/claude/<name>/
- Found: canonical folder `<name>` — <file_count> logs, <oldest> → <newest>; newest is <N> days old (threshold 30)
- Why asking: the artifact still exists, so the folder is live — whether its old logs are worth keeping is the operator's call
- Answers: `keep` — untouched, re-asked on the next run while it stays stale; `delete` — folder deleted in Step 8
AskUserQuestion: header "Stale log folder", question "Log folder ./.logs/claude/<name>/ has <file_count> logs from <oldest> to <newest>, newest <N> days old — keep or delete it?", options with descriptions.
```

  - options, each with a `description` restating its Answers line:
    - `keep` — leave folder untouched
    - `delete` — delete in Step 8

Append each chosen action to the corresponding intent list. Outcome line: `stale-decided <count> (kept=<k>, delete=<d>)`.

## Step 4: Rename-candidate review

For each `orphan-rename-candidate` (paired with its canonical match `target`), print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 4 — Rename-candidate review; target ./.logs/claude/<name>/ → ./.logs/claude/<target>/
- Found: `<name>` is not a canonical name; closest canonical `<target>` (similarity <ratio>); <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: a near-match may be a renamed skill or an unrelated name — only the operator knows
- Answers: `merge` — logs moved into `<target>/` and the emptied source removed in Step 8, never re-asked; `delete` — deleted in Step 8; `leave` — untouched, re-asked on the next run
AskUserQuestion: header "Rename candidate", question "Merge log folder ./.logs/claude/<name>/ into canonical ./.logs/claude/<target>/ (similarity <ratio>), or delete or leave it?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `merge` — logs moved into the target folder, emptied source removed (in Step 8)
  - `delete` — delete in Step 8
  - `leave` — no action

Append to intent lists. Outcome line: `rename-decided <count>` or `no-rename-candidates`.

## Step 5: Pattern-clustered orphan review

Group the `orphan-pattern` bucket by the regex that matched. For each cluster, print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that cluster:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 5 — Pattern-clustered orphan review; target <count> folders under ./.logs/claude/ matching `<pattern>`
- Found: `<example1>`, `<example2>`, … — anonymous subagent run dirs; <total files> logs, <oldest> → <newest> across the cluster
- Why asking: these dirs map to no artifact, but deletion is irreversible
- Answers: `delete-all` — every folder in the cluster deleted in Step 8; `leave-all` — untouched, re-asked on the next run; `per-folder` — one Step 7 prompt per folder in this cluster
AskUserQuestion: header "Orphan cluster", question "<count> log folders under ./.logs/claude/ match `<pattern>` (`<example1>`, `<example2>`, …) — delete all, leave all, or decide per folder?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `delete-all` — schedule every folder in the cluster for deletion in Step 8
  - `leave-all` — no action
  - `per-folder` — fall through to one prompt per folder in this cluster (same options as Step 7)

Append to intent lists. Outcome line: `cluster-decided <cluster_count>` or `no-pattern-orphans`.

## Step 6: Unlogged-bucket review

For each folder in the `unlogged` bucket, print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 6 — Unlogged-bucket review; target ./.logs/claude/<name>/
- Found: `<name>` maps to a live artifact whose frontmatter declares no `logging: true` (from Step 1's JSON); <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: the artifact still exists but nothing writes here any more — the logs are residue, but deletion is irreversible
- Answers: `delete` — deleted in Step 8; `leave` — untouched, re-asked on the next run; `delete-all-unlogged` — (first prompt only) every remaining unlogged folder scheduled for deletion, no further Step 6 prompts
AskUserQuestion: header "Unlogged logs", question "Log folder ./.logs/claude/<name>/ belongs to an artifact that no longer logs — delete, leave, or delete every unlogged folder?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `delete` (Recommended) — schedule for deletion in Step 8
  - `leave` — no action
  - `delete-all-unlogged` — first-prompt-only escape; schedule every remaining `unlogged` folder for deletion

Append to intent lists. Outcome line: `unlogged-decided <count>` or `no-unlogged`.

## Step 7: Other orphan review

For each folder in the `orphan-other` bucket (including any "per-folder" fall-throughs from Step 5), print the context block, then issue **one** `AskUserQuestion`; each iteration fills the block from that folder:

```
Context (print before asking):
- Where: /lazy-log.clean · Step 7 — Other orphan review; target ./.logs/claude/<name>/
- Found: `<name>` matches no canonical name and no known pattern; <file_count> logs, <oldest> → <newest>; `## Result` preview of up to three logs: <one line each, or none>
- Why asking: the folder may be a retired artifact worth keeping or plain noise — only the operator knows
- Answers: `delete` — deleted in Step 8; `leave` — untouched, re-asked on the next run
AskUserQuestion: header "Orphan logs", question "Log folder ./.logs/claude/<name>/ matches no live skill, agent, or command — delete or leave it?", options with descriptions.
```

- options, each with a `description` restating its Answers line:
  - `delete` — delete in Step 8
  - `leave` — no action

Append to intent lists. Outcome line: `other-decided <count>` or `no-other-orphans`.

## Step 8: Apply deletions

Execute the deferred filesystem actions in one call — one `--merge <source>:<target>` per Step 4 merge, one `--delete <name>` per folder Steps 3–7 marked for deletion:

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-log.clean/scripts/log-folders.py" apply --merge <source>:<target> --delete <name>
```

The `log-folders.py apply` script runs every merge before any deletion and never leaves `./.logs/claude/`. It prints `{"merged": N, "deleted": N, "refused": [{name, reason}]}`; a `refused` entry (`invalid-name`, `missing`, `exists-in-target`) is reported by name and left on disk.

Outcome line: `applied merges=<merged> deletions=<deleted>` plus one `refused <name>: <reason>` line per refusal — or `none` if both lists are empty (the script is not run).

## Failure modes

- **`/lazy-log.clean` aborts immediately: ".logs/claude/ absent"** — the log directory does not exist yet (no skill has ever logged in this repo) → run any logged skill once to create it, then re-run clean.
- **Step 1 aborts: "failed: \<reason\>"** — the canonical-name resolver script errored (e.g. Python missing, `CLAUDE_PLUGIN_ROOT` unset, or malformed JSON) → check the reason string; re-run `/lazy-core.install` to ensure the plugin is properly set up, then retry.

## Step 9: Report + log run

### Report

Render exactly one line per Step 1–8, in order, using the outcome strings collected above. Then a final `## Summary` table:

```
| Bucket | Before | Kept | Merged | Deleted |
| unlogged               |  N |  N |  – |  N |
| canonical              |  N |  N |  – |  N |
| orphan-rename-candidate|  N |  N |  N |  N |
| orphan-pattern         |  N |  N |  – |  N |
| orphan-other           |  N |  N |  – |  N |
```

A missing per-step line is a bug. Do not render the report with gaps.
