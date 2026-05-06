---
name: lazy-core.git-status
description: "Read-only inspect of the lazy-core.git staging lock. Prints holder, age, liveness, and whether the lock is currently breakable. No state mutation."
allowed-tools: "Bash(python3 *), Bash(git rev-parse *), Bash(mkdir -p *), Bash(date -u *), Read, Write"
---

# /lazy-core.git-status

Print the current state of `<repo>/.git/lazy-git.lock` — who holds it, how old, whether the holder is alive, and whether break-the-lock heuristics would let us break it.

This skill never mutates the lock. For manual breakage see `/lazy-core.git-unlock`.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve repo root`
   - `Step 2 — Run the inspect helper`
   - `Step 3 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve repo root

Run:

```bash
git rev-parse --show-toplevel
```

If exit non-zero → print "not a git repository" and emit outcome `failed`.

**Outcome: `asserted` or `failed`.**

## Step 2 — Run the inspect helper

Invoke `staging_lock.inspect()` and `staging_lock.load_config()` via a one-liner:

```bash
python3 - <<'PY'
import sys, time, os, socket
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/bin")
import staging_lock
from pathlib import Path
import subprocess
repo = Path(subprocess.check_output(["git","rev-parse","--show-toplevel"], text=True).strip())
state = staging_lock.inspect(repo)
cfg = staging_lock.load_config(repo)
me = staging_lock.resolve_session_id()
if state is None:
    print("Lock: NONE (no staging in progress)")
    raise SystemExit(0)
now = time.time()
age = int(now - state.started_at)
idx_age = int(now - max(state.last_index_mtime, (repo/".git/index").stat().st_mtime if (repo/".git/index").exists() else 0))
breakable, reason = staging_lock._is_breakable(repo, state, cfg, now=now)
print(f"Lock:        HELD by session {state.session_id} (PID {state.pid})")
print(f"Branch:      {state.branch}")
print(f"Held for:    {age}s")
print(f"Index touched: {idx_age}s ago")
print(f"Liveness:    PID alive={staging_lock._pid_alive(state.pid)}, host={'this' if state.host == socket.gethostname() else 'other('+state.host+')'}")
print(f"Breakable:   {'YES ('+reason+')' if breakable else 'NO (within thresholds)'}")
print(f"Owner:       {'this session' if state.session_id == me else 'peer'}")
PY
```

**Outcome: `inspected`.**

## Step 3 — Log the run

Per `.claude/rules/lazy-log.logging.md`. Use `mkdir -p` then `Write`, never chained with `&&`.

```bash
mkdir -p .logs/claude/lazy-core.git-status
date -u +%Y-%m-%d_%H-%M-%S
```

Use the timestamp to write `.logs/claude/lazy-core.git-status/<ts>.md` with the standard frontmatter (`git_sha`, `git_branch`, `date`, `input: none`) and the captured output in the body.

**Outcome: `logged`.**

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.
