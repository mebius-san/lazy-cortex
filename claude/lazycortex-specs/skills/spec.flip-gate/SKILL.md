---
name: spec.flip-gate
description: Flip one asset progression gate (spec_design_done / spec_plan_done / spec_develop_done / spec_tests_passing / spec_released) true→false or back, by subprocessing the flip-gate primitive. Confirms the flip with one wizard question unless invoked --auto.
execution-discipline-waiver: "Thin confirm-then-subprocess wrapper over bin/flip_gate.py — the precondition logic and all side effects live in the primitive; no multi-phase orchestration where step-skip can hide."
---
# Flip a Gate

Thin Claude wrapper over the gate-flip primitive `bin/flip_gate.py`. The gate model — the five flat booleans, the linear S0..S5 ladder, the precondition table, derived vs human-signal gates, and what the primitive mutates — lives in `${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`. This skill never restates it.

## Input

1. **Asset** — a status folder-note path, asset directory, or any path/slug the product resolver can map to one asset folder `<spec_path>/<category>/<slug>/`. Resolve the product per `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` → Resolving a Product, then narrow to the single asset directory.
2. **Gate** — one of `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`.
3. **`--off`** (optional) — regress the gate true→false instead of flipping it on.
4. **`--auto`** (optional) — skip the confirmation question (the worker / non-interactive callers pass this). Without it, this is an interactive operator action.

## Process

### 1. Resolve the asset

Map the input to exactly one asset directory. If the input is ambiguous (matches more than one product or asset), prompt the operator to pick via `AskUserQuestion` (options = the candidate asset directories). If nothing resolves, refuse with a message naming the input.

### 2. Confirm the flip

Unless `--auto` was passed, ask a single `AskUserQuestion` to confirm. Author the question as a full-context block per the wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md` → Wizard-question explanation standard:

- **Stem** — name the gate and the asset, state that flipping it advances the asset one notch along the S0..S5 ladder (or regresses it when `--off`), and state that the primitive will refuse if the precondition is not met.
- **Why it matters** — flipping a gate is the recorded progression signal; a human-signal gate (`spec_develop_done` / `spec_tests_passing` / `spec_released`) asserts that external work (deploy / green tests / merge) actually happened.
- **Options** — `yes` (run the flip) and `no` (no-op, leave the asset unchanged), each with a one-sentence consequence.
- **Pointer** — `See: ${CLAUDE_PLUGIN_ROOT}/references/spec.lifecycle-protocol.md`.

On `no` → exit no-op (outcome `skipped-per-user-choice`). On `yes` → continue.

### 3. Subprocess the primitive

Run `lazycortex-specs flip-gate <asset_dir> <gate>`, appending `--off` when regressing. Do NOT pass `--auto` from the interactive path — `--auto` is only for the non-interactive callers that skipped step 2. Report the primitive's result verbatim: on success, the flipped gate and new value; on refusal, the primitive's refusal message (precondition not met, or asset cancelled) — do NOT retry or work around it.

## Output

- The resolved asset directory.
- The flip outcome: `flipped` (gate + new value) or `refused` (primitive's message) or `skipped-per-user-choice`.

## Failure modes

- **`/spec.flip-gate` refuses with the primitive's "precondition not met" message** — the gate's precondition in `spec.lifecycle-protocol.md` does not hold (e.g. flipping `spec_plan_done` while `plan.md.spec_stage` is still `draft`) → satisfy the precondition first, then re-invoke.
- **`/spec.flip-gate` refuses with "asset cancelled"** — `spec_cancelled: true` freezes all gates → uncancel the asset before flipping.
- **`/spec.flip-gate` cannot resolve the asset** — the input maps to zero or more than one asset → pass an unambiguous asset directory or slug.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.flip-gate/YYYY-MM-DD_HH-MM-SS.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`), a short `## Actions` bullet list, and a `## Result` line. The `flip_gate` primitive also writes its own log under the same dir on a successful flip; this skill's log records the wrapper run (resolution + confirmation outcome) regardless of whether the primitive ran.
