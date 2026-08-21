---
name: lazy-spec.flip-gate
description: "Run when the operator declares an asset's progression gate reached or wants one walked back — 'design is approved', 'tests pass now', 'this is released', 'un-flip spec_released'. Interactive by default (one confirm question); non-interactive callers such as `spec.coordinator` pass `--auto`."
execution-discipline-waiver: "Thin confirm-then-subprocess wrapper over bin/flip_gate.py — the flip is unconditional in the primitive; no multi-phase orchestration where step-skip can hide."
---
# Flip a Gate

Thin Claude wrapper over the gate-flip primitive `bin/flip_gate.py`. The gate model — the five flat booleans, the linear S0..S5 ladder, and what the primitive mutates — lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md`. This skill never restates it.

**The flip is unconditional.** The primitive refuses only when the target asset is cancelled (`spec_cancelled: true`) — there is no precondition table it checks on its own. Deciding WHEN a gate is ready to move is `spec.coordinator`'s job, reasoning from `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`; this skill (and the primitive underneath it) trusts whoever called it to have already made that call. The operator confirmation in step 2 below exists precisely because a human invoking this skill directly has not necessarily gone through that reasoning — the confirmation is the human's own check, not a stand-in for a removed precondition.

## Input

1. **Asset** — a status folder-note path, asset directory, or any path/slug the product resolver can map to one asset folder `<spec_path>/<category>/<slug>/`. Resolve the product per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` → Resolving a Product, then narrow to the single asset directory.
2. **Gate** — one of `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`.
3. **`--off`** (optional) — regress the gate true→false instead of flipping it on.
4. **`--auto`** (optional) — skip the confirmation question (`spec.coordinator` and other non-interactive callers pass this). Without it, this is an interactive operator action.

## Process

### 1. Resolve the asset

Map the input to exactly one asset directory. If the input is ambiguous (matches more than one product or asset), prompt the operator to pick via `AskUserQuestion` (options = the candidate asset directories). If nothing resolves, refuse with a message naming the input.

### 2. Confirm the flip

Unless `--auto` was passed, ask a single `AskUserQuestion` to confirm. Author the question as a full-context block per the wizard-question standard in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` → Wizard-question explanation standard:

- **Stem** — name the gate and the asset, state that flipping it advances the asset one notch along the S0..S5 ladder (or regresses it when `--off`), and state that the primitive performs the mutation unconditionally once confirmed — it does not itself check whether the gate's usual readiness condition holds.
- **Why it matters** — flipping a gate is the recorded progression signal; a human-signal gate (`spec_develop_done` / `spec_tests_passing` / `spec_released`) asserts that external work (deploy / green tests / merge) actually happened.
- **Options** — `yes` (run the flip) and `no` (no-op, leave the asset unchanged), each with a one-sentence consequence.
- **Pointer** — `See: ${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-protocol.md` and `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`.

On `no` → exit no-op (outcome `skipped-per-user-choice`). On `yes` → continue.

### 3. Subprocess the primitive

Run `lazycortex-specs flip-gate <asset_dir> <gate>`, appending `--off` when regressing. Do NOT pass `--auto` from the interactive path — `--auto` is only for the non-interactive callers that skipped step 2. Report the primitive's result verbatim: on success, the flipped gate and new value; on refusal, the primitive's refusal message (always "asset is cancelled" — the only refusal case) — do NOT retry or work around it.

## Output

- The resolved asset directory.
- The flip outcome: `flipped` (gate + new value) or `refused` (primitive's message) or `skipped-per-user-choice`.

## Failure modes

- **`/lazy-spec.flip-gate` refuses with "asset is cancelled"** — `spec_cancelled: true` freezes all gates, the one refusal the primitive still enforces on its own → uncancel the asset before flipping.
- **`/lazy-spec.flip-gate` cannot resolve the asset** — the input maps to zero or more than one asset → pass an unambiguous asset directory or slug.
- **A gate was flipped that shouldn't have been** — the primitive trusted the caller; there is no precondition to have caught it. Flip it back with `--off` (also unconditional, refused only while cancelled), then check `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md` Chapter 3 for what the gate's readiness actually requires before flipping forward again.

## Run Log

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.flip-gate/YYYY-MM-DD_HH-MM-SS.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`), a short `## Actions` bullet list, and a `## Result` line. The `flip_gate` primitive also writes its own log under the same dir on a successful flip; this skill's log records the wrapper run (resolution + confirmation outcome) regardless of whether the primitive ran.
