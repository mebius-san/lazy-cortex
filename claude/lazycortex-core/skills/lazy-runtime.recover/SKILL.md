---
name: lazy-runtime.recover
description: Recover the lazycortex-core runtime daemon from a working-tree halt. Walks the operator through cleanup (commit / stash / discard / abort) and clears the daemon_halted block from state.json once the tree is clean.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(git status *), Bash(date -u *), Write, AskUserQuestion
dirty-tree-waiver: "applies operator-chosen cleanup ops to the working tree (commit/stash/discard) — the operator is the commit author, not this skill"
---
# Runtime Recover

The runtime daemon halts when a routine or expert leaves the working tree dirty. This skill is the way out: it shows the halt context, asks how to clean up, applies the cleanup, then atomically clears the `daemon_halted` block from `<repo>/.logs/lazy-core/runtime/state.json`. The daemon resumes scheduling on its next iteration.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read halt context`
   - `Step 2 — Choose cleanup mode`
   - `Step 3 — Apply cleanup`
   - `Step 4 — Resume + report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Read halt context

Load `daemon_halted` from `<repo>/.logs/lazy-core/runtime/state.json`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from pathlib import Path
import recover
halt = recover.read_halt(Path('.'))
if halt is None:
    print('not_halted')
else:
    print(json.dumps(halt, indent=2))
" )
```

If output is `not_halted`: print "Daemon is not halted. Nothing to recover." and skip to Step 4 with outcome `not-halted`.

Otherwise, parse the JSON and surface to the operator:

- `triggered_by` — which routine (or `lazy-expert.pump` for pump-internal halts)
- `expert` + `job_id` — populated when the dirt came from inside an expert
- `reason` — currently always `uncommitted_changes`
- `dirty_paths` — the captured `git status --porcelain` lines

Outcome: `context-shown` or `not-halted`.

## Step 2 — Choose cleanup mode

Ask via `AskUserQuestion`:

> The working tree has uncommitted changes (see Step 1's dirty paths). How should I clean up before resuming?
> - **commit** — `git add -A && git commit -m <message>`. Captures every dirty path. You provide the message.
> - **stash** — `git stash push -u`. Tucks dirt into a stash you can restore later by hand.
> - **discard** — `git checkout -- . && git clean -fd`. Throws away every dirty change. Irreversible.
> - **abort** — leave everything as-is and exit. Daemon stays halted.

If `commit`: ask one follow-up via `AskUserQuestion`:

> Commit message? Default: `<triggered_by>: recover from halt`.

Outcome: `commit`, `stash`, `discard`, or `aborted`.

## Step 3 — Apply cleanup

Skip if Step 2 outcome is `aborted` (mark this step `skipped-per-user-choice`).

Run `recover.cleanup(repo, mode, message=...)`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys
from pathlib import Path
import recover
mode = sys.argv[1]
message = sys.argv[2] if len(sys.argv) > 2 else None
recover.cleanup(Path('.'), mode, message=message)
print('cleaned')
" '<mode>' '<message-or-empty>')
```

Outcome: `cleaned`, `skipped-per-user-choice`, or `error`.

## Step 4 — Resume + report

Skip resume if Step 2 was `aborted`. Otherwise call `recover.resume(repo)`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
import recover
try:
    recover.resume(Path('.'))
    print('resumed')
except recover.RecoverError as e:
    print(f'still-dirty: {e}')
" )
```

If output starts with `still-dirty`: print the message and tell the operator to inspect manually (`git status`) and re-run the skill. The halt block remains.

Otherwise print: "Daemon halt cleared. The runtime will resume scheduling on its next iteration."

Report block: one line per task in the canonical list, with its outcome word.

Outcome: `resumed`, `still-dirty`, or `aborted`.

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-runtime.recover)
```

Then `Write` to `.logs/claude/lazy-runtime.recover/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "mode=<mode>"
---
```

`# lazy-runtime.recover`

`## Actions`
- Read halt context (`triggered_by=<...>`, `expert=<...>`, `job_id=<...>`)
- Chose cleanup mode (`<mode>`)
- Applied cleanup
- Resumed daemon

`## Result`
`<resumed|still-dirty|aborted|not-halted>`

## Failure modes

- **"Daemon is not halted. Nothing to recover."** — the daemon was not in halt state when this skill ran → no action needed; verify with `cat .logs/lazy-core/runtime/state.json`.
- **"working tree still dirty; refusing to resume"** — the cleanup did not produce a clean tree (e.g., submodules left dirt, or the operator chose `abort`) → run `git status` manually, resolve, and re-invoke `/lazy-runtime.recover`.
- **"commit mode requires a non-empty message"** — operator picked commit but provided no message → re-invoke and supply a message.
- **"`.logs/lazy-core/runtime/state.json` unparseable"** — state file is corrupt → inspect manually; the daemon treats unparseable state as "not halted" and resumes on next iteration, but you may have lost `last_run` history.
