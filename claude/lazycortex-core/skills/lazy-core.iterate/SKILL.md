---
name: lazy-core.iterate
description: "Use when the operator asks to keep going until something is clean — audit this spec until no findings remain, fix these failures round after round, stabilise the refactor, drive the suite green. Locks target, done-state, and the verification action upfront, then loops with hard caps on cycles, repeated findings, and regression spirals so it cannot run away."
allowed-tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskUpdate, TaskList, Agent
user-invocable: true
---

# Iterative Improve-Until-Stable Loop

Drive a closed do → verify → fix → verify cycle against a target until one of six configured stop conditions fires. Frames the target and stop conditions upfront (Steps 1–2), then runs the loop with explicit per-cycle decide-gate (Step 3), reports what was fixed / what remains / why it stopped (Step 4), and logs the run (Step 5).

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Frame target`
   - `Step 2 — Set stop conditions`
   - `Step 3 — Run iteration loop`
   - `Step 4 — Final report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`framed`, `aborted-no-target`, `conditions-set`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Frame target

State explicitly three things — if any is unclear or absent from user's request, ask via `AskUserQuestion` (one decision at a time) before proceeding:

- **Target** — what is being iterated. Concrete file / PR / spec / test-suite / code-area, not a vague topic. Examples: «`docs/design/feature-spec.md`», «test failures in `tests/core/runtime/`», «the diff between current branch and main».
- **Done-state** — what does "stable" mean for this target. Examples: «verification finds zero issues», «no FAIL-severity findings», «all tests pass», «no diff between rounds».
- **Verification action** — the exact command / inspection / agent dispatch that produces an issue list each cycle. Examples: «read full spec end-to-end, list inconsistencies», «run `chk-py all -q`», «run `pytest tests/core/runtime -q`», «dispatch read-only audit agent with prompt X».

These three together form the iteration contract — Step 3 mechanically applies it.

Outcome: `framed` or `aborted-no-target`.

## Step 2 — Set stop conditions

Lock concrete values for ALL six stop conditions before starting cycle 1. Defaults apply when user hasn't overridden; user can adjust per condition:

- **Cycle cap (hard).** Default: `5`. After this many full cycles, stop regardless of state. Prevents runaway loops on stubborn targets.
- **Clean run.** If a verification cycle returns zero issues — stop, this is the success path.
- **Severity floor.** Default: stop when only WARN / INFO / minor remain (no FAIL or equivalent). User can lower (continue until all severity levels clear) or raise (stop as soon as no FAILs). Maps each severity to a numeric ordinal so comparisons are unambiguous.
- **Repeat detection.** If the same issue identifier surfaces in two consecutive cycles — fix is wrong or insufficient. Stop and escalate to user; don't keep trying the same fix path.
- **Regression spiral.** If a cycle introduces strictly more new issues than it resolves (compared to previous cycle's output) — fixes are causing more damage than repair. Stop and surface a revert prompt.
- **Budget exhaustion.** If the user specified a wall-clock or token budget — soft cap on cycle entry. Default: none.

Record chosen values in scratch reasoning context — they'll be checked at the end of each cycle in Step 3.

Outcome: `conditions-set`.

## Step 3 — Run iteration loop

The loop body. Each cycle has three phases — Verify, Decide, Fix — executed in order. Pseudo-flow:

```
cycle = 1
prev_issues = []
fixed_total = 0
while True:
  # Verify
  issues = <run verification action from Step 1>
  # Decide
  reason = pick_stop_reason(cycle, issues, prev_issues, fixed_total, ...)
  if reason: break
  # Fix
  before = len(issues)
  <apply minimal targeted change per issue above severity floor>
  fixed_total += <count actually resolved>
  prev_issues = issues
  cycle += 1
```

### 3.1 Verify

Run the verification action defined in Step 1. Collect findings into a structured list — each entry has at minimum `{severity, identifier, description}`. The `identifier` is whatever makes the issue uniquely re-identifiable across cycles (file:line, rule-id, test-name, error-signature).

If verification itself crashes — surface immediately, don't loop. That's a Step 1 contract failure, not a normal cycle outcome.

### 3.2 Decide (stop-condition gate)

Apply the six stop conditions **in this priority order** — first match wins:

1. **`cap-reached`** — `cycle > cycle_cap`. Hard stop, no further fixes.
2. **`clean`** — `issues == ∅`. Success path.
3. **`minor-only`** — all `issues[i].severity < severity_floor`. Done with the meaningful work; remaining items are noise.
4. **`repeat`** — `prev_issues` non-empty AND the identifier set `prev_issues ∩ issues` is non-empty. Same issue surfaced twice in a row → the fix didn't take or was wrong. Stop and escalate.
5. **`regression`** — `cycle > 1` AND `|new(issues, prev_issues)| > fixed_in_last_cycle`. More damage than repair. Stop and recommend revert.
6. **`budget`** — if a budget was set in Step 2 and is now exhausted. Soft stop.

If none match → no stop signal, proceed to Fix.

### 3.3 Fix

Address every issue above the severity floor. Discipline:

- **Minimal targeted change per issue.** Don't bundle unrelated fixes into a single edit; the next Verify needs to attribute each delta to a specific issue.
- **Don't change scope.** New ideas or refactor opportunities surfaced mid-loop go into a "follow-up" note, not the current fix path.
- **Don't fix issues below floor in this cycle.** Wasted cycles on noise; cycle budget is precious.

After Fix, count how many of the previous-cycle issues are now resolved (`fixed_in_last_cycle`). Then loop back to Verify (no separate confirm-without-fixing pass — the next Verify is the confirmation).

Outcome: `<N>-cycles-<reason>`, e.g., `3-cycles-clean`, `5-cycles-cap-reached`, `2-cycles-repeat`, `4-cycles-regression`, `1-cycles-budget`, `2-cycles-minor-only`.

## Step 4 — Final report

Print a structured summary to the user. Required fields:

- **Target** — what was iterated (from Step 1).
- **Cycles run** — N (1-based count of completed Verify+Fix passes).
- **Stop reason** — exactly one of `clean` / `minor-only` / `cap-reached` / `repeat` / `regression` / `budget`.
- **Fixed total** — count of distinct issues resolved across all cycles, with a brief per-cycle breakdown.
- **Remaining** — issues that survived the loop, grouped by severity. Empty list if `stop_reason == clean`.
- **Escalation note** — required when `stop_reason ∈ {repeat, regression, cap-reached}`. Says what specifically went wrong (which issue repeated, which cycle regressed, which target was too big for the cap) and proposes next-step options to the user (raise cap / revert / split target / change verification action).

The report is the deliverable — make it scannable, not a wall of text. Tables, bullet lists, short labels.

Outcome: `reported`.

## Step 5 — Log the run

Write a run log to `.logs/claude/lazy-core.iterate/YYYY-MM-DD_HH-MM-SS.md`. Use UTC time: `date -u +%Y-%m-%d_%H-%M-%S` for the filename. Create the directory with `Bash(mkdir -p ...)` then write with the `Write` tool — two separate steps, never chained.

Log format:

```markdown
---
git_sha: <sha or no-git>
git_branch: <branch or no-git>
date: YYYY-MM-DD HH:MM:SS UTC
input: <target + overrides or none>
---

# lazy-core.iterate

## Actions

<one bullet per cycle: cycle N — issues found / fixed / outcome>

## Result

<stop reason + cycles run + fixed-total + remaining count>
```

Outcome: `logged`.

## Report

One line per task in the canonical list above, each with its outcome word. A missing line is a bug.

## Failure modes

- **Loop never converges** — every cycle finds the same issue list; nothing actually changes between rounds → trips `repeat` on cycle 2 → stop and escalate. Lever: rethink the fix strategy; the verification might also be too strict (always re-flags work that's actually OK).
- **Cap reached but issues remain** — fixes too tentative, scope too broad, or verification finds too many independent issues per cycle → split target into smaller chunks and re-run, or raise cycle cap if confident the loop is making progress.
- **Regression spiral** — each fix breaks more than it solves → stop, revert to baseline, escalate. Often indicates the verification action is overly strict (finds issues the user doesn't actually care about) or the target is structurally wrong (file should be deleted, not iterated).
- **No clear target** — Step 1 can't be framed because the user's request is too vague («fix the code», «improve everything») → abort with `aborted-no-target` and ask the user to narrow.
- **Verification action crashes mid-loop** — that's a Step 1 contract failure, not a normal cycle outcome → surface the crash immediately, don't attempt to "fix" the verification tool itself.
