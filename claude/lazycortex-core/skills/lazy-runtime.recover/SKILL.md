---
name: lazy-runtime.recover
description: Recover the lazycortex-core runtime daemon from a halt — either a working-tree halt (uncommitted_changes) or a remote-sync halt (git_pull_diverged, git_push_failed, git_remote_unavailable). Branches on the halt reason: walks the operator through dirt cleanup for tree halts, or through manual repair guidance for remote-sync halts. Atomically clears the daemon_halted block from state.json once the precondition holds.
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(git status *), Bash(date -u *), Write, AskUserQuestion
dirty-tree-waiver: "applies operator-chosen cleanup ops to the working tree (commit/stash/discard) — the operator is the commit author, not this skill"
---
# Runtime Recover

The runtime daemon halts in two distinct families of situations:

- **`uncommitted_changes`** — a routine or expert left the working tree dirty. The skill walks the operator through commit / stash / discard / abort.
- **`git_pull_diverged` / `git_push_failed` / `git_remote_unavailable`** — pre- or post-tick remote sync hit an unrecoverable state. The skill describes the situation and asks the operator to repair it externally (manual git ops, network fix, etc.) before confirming resume.

In both families the skill ends with an atomic clear of the `daemon_halted` block from `<repo>/.logs/lazy-core/runtime/state.json`. The daemon resumes scheduling on its next iteration.

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

- `triggered_by` — which routine name, or `_git_pre` / `_git_post` for daemon-side remote-sync halts, or `lazy-expert.pump` for pump-internal halts.
- `expert` + `job_id` — populated when the dirt came from inside an expert.
- `reason` — one of: `uncommitted_changes`, `git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`.
- `dirty_paths` — captured `git status --porcelain` lines (only populated when `reason == uncommitted_changes`; empty otherwise).

Outcome: `context-shown` or `not-halted`.

## Step 2 — Choose recovery mode

Branch on `reason`.

### Reason = `uncommitted_changes` — dirt cleanup wizard

Ask via `AskUserQuestion`:

> The working tree has uncommitted changes (see Step 1's dirty paths). How should I clean up before resuming?
> - **commit** — `git add -A && git commit -m <message>`. Captures every dirty path. You provide the message.
> - **stash** — `git stash push -u`. Tucks dirt into a stash you can restore later by hand.
> - **discard** — `git checkout -- . && git clean -fd`. Throws away every dirty change. Irreversible.
> - **abort** — leave everything as-is and exit. Daemon stays halted.

If `commit`: ask one follow-up via `AskUserQuestion`:

> Commit message? Default: `<triggered_by>: recover from halt`.

Outcome: `commit`, `stash`, `discard`, or `aborted`.

### Reason ∈ {`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`} — manual-fix path

The daemon does NOT attempt to fix remote-sync halts itself — automatic resolution could silently drop the operator's commits. Surface reason-specific guidance and ask the operator to repair the situation by hand, then confirm.

Print the matching guidance block first:

- `git_pull_diverged` — "Local branch and origin have diverged: each side has commits the other doesn't. Inspect with `git log --oneline HEAD origin/<branch>` and `git log --oneline origin/<branch> HEAD`, then either (a) `git reset --hard origin/<branch>` to drop local divergent commits, (b) rebase / merge by hand, or (c) push your local commits with `--force-with-lease` if you intend them to land."
- `git_push_failed` — "Push to origin retried 3 times and kept failing. Likely causes: auth (try `git push origin <branch>` by hand and read the error), force-protection or branch protection rule on the remote, an unusually persistent operator-side push race. Resolve before resuming, or `git reset --hard origin/<branch>` to drop your local commits if you'd rather start over."
- `git_remote_unavailable` — "Could not reach origin. Check network, VPN, and `git remote -v`. Run `git fetch origin <branch>` by hand to confirm the issue is gone before resuming."

Then ask via `AskUserQuestion`:

> Have you resolved the situation? Confirming runs no git commands itself — it just clears the halt block so the next daemon tick can re-evaluate.
> - **resume** — operator confirms repair done; halt block will be cleared. Working tree must be clean (the daemon re-verifies on next tick).
> - **abort** — leave halt in place and exit.

Outcome: `manual-fix` or `aborted`.

## Step 3 — Apply cleanup

Skip if Step 2 outcome is `aborted` or `manual-fix` (mark this step `skipped-per-user-choice`).

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

`## Result` `<resumed|still-dirty|aborted|not-halted>`

## Failure modes

- **"Daemon is not halted. Nothing to recover."** — the daemon was not in halt state when this skill ran → no action needed; verify with `cat .logs/lazy-core/runtime/state.json`.
- **"working tree still dirty; refusing to resume"** — the cleanup did not produce a clean tree (e.g., submodules left dirt, or the operator chose `abort`) → run `git status` manually, resolve, and re-invoke `/lazy-runtime.recover`.
- **"commit mode requires a non-empty message"** — operator picked commit but provided no message → re-invoke and supply a message.
- **"`.logs/lazy-core/runtime/state.json` unparseable"** — state file is corrupt → inspect manually; the daemon treats unparseable state as "not halted" and resumes on next iteration, but you may have lost `last_run` history.
- **Manual-fix path: halt re-fires immediately after resume** — the operator confirmed they fixed a `git_pull_diverged` / `git_push_failed` halt, but the underlying state was not actually resolved (branch still diverged, push still rejected). The next tick's `_git_pre` / `_git_post` re-detects the same condition and halts again with the same reason → reinspect with `git fetch origin <branch>; git log --oneline HEAD origin/<branch>` and address the actual cause before re-running `/lazy-runtime.recover`.
