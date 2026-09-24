---
name: lazy-core.git-status
description: "Run when a git command was refused because another Claude session is staging, or the operator asks who holds the git staging lock and whether it can be broken. Read-only — `/lazy-core.git-unlock` is the one that breaks it."
allowed-tools: 'Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(git rev-parse *), Bash(mkdir -p *), Bash(date -u *), Read, Write, Agent'
---

# /lazy-core.git-status

Print the current state of `<repo>/.git/lazy-git.lock` — who holds it, how old, whether the holder is alive, and whether break-the-lock heuristics would let us break it.

This skill never mutates the lock. For manual breakage see `/lazy-core.git-unlock`.

## Execution discipline (MANDATORY — read before any action)

This skill has 2 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve repo root`
   - `Step 2 — Run the inspect helper`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve repo root

Run:

```bash
git rev-parse --show-toplevel
```

If exit non-zero → print "not a git repository" and emit outcome `failed`.

**Outcome: `asserted` or `failed`.**

## Step 2 — Run the inspect helper

Run the lock report:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" git-lock status
```

It prints one of: `Lock: N/A (git guard disabled for this repo)`; `Lock: N/A (pathspec mode — the guard never opens a staging window)` plus a hint line; `Lock: NONE (no staging in progress)`; or, for a held lock, the multi-line report — `Lock: HELD by session <id> (PID <pid>)`, `Branch:`, `Held for:`, `Index touched:`, `Liveness:` (PID alive, this/other host), `Breakable:` (`YES (<reason>)` / `NO (within thresholds)`), `Owner:` (`this session` / `peer`).

**Outcome: `inspected`, `no-lock-in-play` (pathspec row), or `guard-disabled`.**

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.
