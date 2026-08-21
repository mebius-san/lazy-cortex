---
name: lazy-runtime.tick
description: "Run when the operator asks to tick the runtime by hand — run the due routines once, drain the queues, or fire one named routine — on a checkout whose daemon is not running. Same primitives and serial order as the daemon; commits like the daemon, never pushes without an explicit word."
allowed-tools: Read, Bash, AskUserQuestion, Agent
---
# Manual Runtime Tick

Runs the daemon's own iteration primitive by hand: every due routine in priority order, then the READY-job queue through the local pump. No parallelism, no own composition — the result is what the daemon would have produced, minus the push. Refuses outright while a live daemon holds the checkout.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Parse arguments`
   - `Step 2 — Run the tick`
   - `Step 3 — Report`
   - `Step 4 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Parse arguments

The invocation is `/lazy-runtime.tick [<routine-name>] [--drain]`:

- no arguments — ONE daemon iteration: every due routine in priority order (the registered pump routine, when due, processes at most one READY job — exactly the daemon's own single-spawn ceiling);
- `--drain` — repeat iterations, sleeping between them exactly as the daemon would, until no routine is due and the READY queue is empty; stops early on a halt, a dirty tree, a raised rate-limit flag, or a pass that made no progress;
- `<routine-name>` — run ONLY that routine, ignoring its interval (the operator asked by name); other routines do not run. `--drain` is ignored in this mode.

Any unrecognised flag or extra positional is refused, not dropped.

Outcome: `single`, `drain`, or `named:<routine>`.

## Step 2 — Run the tick

Everything — the live-daemon refusal, the unknown-routine refusal, the iteration loop, the pump drain — is owned by the CLI; the skill only invokes it:

```
Bash(LAZY_REPO_ROOT="$PWD" ${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core runtime-tick [<routine-name>] [--drain])
```

Exit 2 with a `refused:` line on stderr means exactly what it says — surface the line verbatim to the operator and stop; do NOT stop the daemon yourself or retry. Exit 0 prints a JSON summary: `ticks`, `routine`, `dispatched` (named mode only), `ready_left`, `stopped` (`halted` / `dirty_tree` / `rate_limited` / `no_progress` / null), `halted`.

The tick commits exactly as the daemon does (per-routine, bot identities) and DEFERS the push: nothing is published during the run, but the commits stay on the branch and the next pushing iteration — the daemon's own, once restarted — will carry them. If the work must not reach origin, say so to the operator before they restart the daemon.

A non-null `stopped` means the run ended early — name the reason to the operator; `halted` and `dirty_tree` point at `/lazy-runtime.recover`, `rate_limited` means the subscription window is closed and the queue resumes when it reopens.

Outcome: `ticked`, `refused-daemon-live`, `refused-unknown-routine`, `refused-bad-args`, or `stopped-early:<reason>`.

## Step 3 — Report

One line per task in the canonical list, with its outcome word, then the CLI's JSON summary rendered as: which routines were due and ran (from the runtime journal `.logs/lazy-core/runtime/<date>.jsonl` tail for this tick's window), how many jobs the pump drained, what was committed (`git log --oneline` for commits made during the run, if any).

## Step 4 — Log the run

Per the `lazy-log.logging` contract: `Bash(mkdir -p ./.logs/claude/lazy-runtime.tick)`, then `Write` `./.logs/claude/lazy-runtime.tick/<UTC-timestamp>.md` with frontmatter `git_sha`, `git_branch`, `date`, `input` and an Actions/Result body.

Outcome: `logged`.

## Failure modes

- **`/lazy-runtime.tick` refuses saying the daemon is running** — the checkout's supervisor unit holds a live daemon; a concurrent manual tick would race it over the tree, index, and job queue → stop the unit (`launchctl stop com.lazycortex.runtime.<repo>` / `systemctl --user stop lazy-core-runtime-<repo>`) or run the tick on a checkout without a daemon.
- **`/lazy-runtime.tick <name>` refuses with `unknown routine`** — the name is not in `lazy.settings.json[routines]`; the refusal lists what is registered → pick one of those or register the routine via `/lazy-routine.register`.
- **The summary reports `halted: true`** — a routine halted the runtime mid-tick (dirty tree, rate limit, remote failure) → `/lazy-runtime.recover` explains and clears it; subsequent ticks refuse nothing but dispatch no non-`ignore_halt` routines until it clears.
