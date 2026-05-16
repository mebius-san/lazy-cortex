---
name: lazy-core.git-unlock
description: "Manually break the lazy-core.git staging lock. Asks before acting (AskUserQuestion). Use only when /lazy-core.git-status shows a lock that the hook's break-the-lock heuristics will not auto-break."
allowed-tools: "Bash(python3 *), Bash(git rev-parse *), Bash(mkdir -p *), Bash(date -u *), Read, Write, AskUserQuestion"
dirty-tree-waiver: "deletes .git/lazy-git.lock under .git/ — never tracked by git, never enters the working tree"
---

# /lazy-core.git-unlock

Force-delete `<repo>/.git/lazy-git.lock`. The hook's automatic break-the-lock heuristics (dead PID / different host / stale-and-idle) handle most cases. Use this skill only when the lock is genuinely stuck — for example, the holder is alive but you know it has abandoned the staging window.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve repo root and inspect`
   - `Step 2 — Confirm with the operator`
   - `Step 3 — Break the lock`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve repo root and inspect

Run the same inspect one-liner as `/lazy-core.git-status` Step 2 to capture current lock state. Read that skill's `SKILL.md` to extract the snippet — use it verbatim.

If `state is None` (no lock) → print "no lock to break" and emit outcome `not-found`.

If the lock exists, the one-liner output includes the holder's session ID, PID, age, host, branch, liveness status, and whether it is currently breakable. Capture this output for Step 2.

**Outcome: `asserted` (lock found) or `not-found` (no lock).**

## Step 2 — Confirm with the operator

Use `AskUserQuestion` with one question. Phrase it as:

> "Lock held by session `<state.session_id>` (PID `<state.pid>`, started `<age>s` ago, host `<state.host>`, branch `<state.branch>`). Liveness: `<alive|dead>`. Break the lock?"

- "Yes, break it" → proceed to Step 3.
- "Cancel" → emit outcome `cancelled` and stop.

**Outcome: `confirmed` (user said yes) or `cancelled` (user said no).**

## Step 3 — Break the lock

Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/bin")
import staging_lock
from pathlib import Path
import subprocess
repo = Path(subprocess.check_output(["git","rev-parse","--show-toplevel"], text=True).strip())
existed = staging_lock.break_lock(repo, reason="manual")
print("broken" if existed else "no-lock")
PY
```

If output is `broken` → the lock was present and has been deleted. Emit outcome `broken`. If output is `no-lock` → the lock had already been deleted (race with another tool). Emit outcome `race`.

**Outcome: `broken` or `race`.**

## Step 4 — Log the run

Per `.claude/rules/lazy-log.logging.md`. Use `mkdir -p` then `Write`, never chained with `&&`.

```bash
mkdir -p .logs/claude/lazy-core.git-unlock
date -u +%Y-%m-%d_%H-%M-%S
```

Use the timestamp to write `.logs/claude/lazy-core.git-unlock/<ts>.md` with the standard frontmatter (`git_sha`, `git_branch`, `date`, `input: none`) and a body capturing:

- **Pre-break state**: lock holder details from Step 1 output.
- **Confirmation**: user's choice from Step 2.
- **Post-break outcome**: the result from Step 3.

**Outcome: `logged`.**

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.
