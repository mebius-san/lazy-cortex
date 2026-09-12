---
description: Pre-launch rollback — the launched-asset definition, the halted/cancelled refusals, and the five ordered steps that roll a not-yet-launched ladder back before an attach delta is seeded. Conditional Part 6 of the asset lifecycle protocol, read when a request attaches to a not-yet-launched asset.
---
# Pre-launch rollback — conditional chapter of the asset lifecycle protocol

Extracted Part 6 of `lazy-spec.lifecycle-protocol.md`, loaded on demand: read this file when a request's routing resolves to an ATTACH target whose implementation ladder has started but not launched. Every bare "Part N" cross-reference below names a Part of that protocol.

When a request's routing resolves to an ATTACH target whose implementation ladder has already started (an `architecture.md`, `code-plan.md`, or `test-plan.md` sibling exists, or any gate from `spec_plan_done` onward already reads `true`) but has NOT yet launched implementation, `lazy-spec.request-apply` rolls the ladder back to its pre-launch state before seeding the attach delta (`lazy-spec.request-protocol.md` § Body distribution rules, point 2) — rather than seeding an attach delta on top of in-flight planning work that a fresh design change is about to revise.

## The launched-feature definition (mechanical, not a judgment call)

A feature counts as LAUNCHED — and must never reach the rollback path at all — when any of:

- `spec_develop_done` reads `true`, OR
- the tracked `active_job` names an implementation checkbox (an implementation job is dispatched, even before `spec_develop_done` itself flips), OR
- a `code-report.md` sibling already exists on disk.

`spec.coordinator`, running in its routing mode (`lazy-spec.coordination-playbook.md` Chapter 9), is responsible for keeping a launched feature off the attach path in the first place — it must propose a change-spawn (naming the feature via the change-spawn line's `targets=` field) instead of a plain attach. `lazy-spec.request-apply` re-checks the same three signals as a worker-side safety net, not the primary enforcement: an attach target found to be launched at apply time is refused outright with a logical error naming the target and the rule, never silently allowed through as a plain attach.

## Halted- and cancelled-asset refusal

An attach target already carrying `spec_halted: true` refuses the ENTIRE attach outright, regardless of ladder state — automation stays off a halted asset until an operator resolves it by hand, so a not-yet-launched-but-halted feature errors rather than touching its ladder. This is unconditional: even a not-yet-started ladder's plain attach-seed step (point 2 of the body-distribution model) is refused the same way, before any mutation — a halted asset gets no automated attach at all, seed included, until the operator resolves it. The same unconditional refusal applies to a `spec_cancelled: true` target, checked first: a cancelled asset would otherwise have its rollback destroy the plan siblings before discovering the refusal at Step 4 below, or (with no ladder started) sail through a plain attach-seed unguarded.

## The five steps (strict order; a failure anywhere halts and aborts rather than proceeding partially)

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/`, or `claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`<review-cli>` stands for the review plugin's `bin/lazycortex-review` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-review/<version>/`, or `claude/lazycortex-review/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <review-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

1. **Cancel the active job.** When the sidecar tracks an `active_job`, invoke the `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> cancel-job` CLI (resolved via `$LAZYCORTEX_PLUGIN_DIRS`, the § 1c inter-plugin contract). A return that does not confirm the job is dead halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts the whole apply run — a half-dropped ladder with a job possibly still running is worse than an intact one. On confirmed success, the `active_job` marker is cleared.
2. **Stop review on the dropped documents.** `"${LAZYCORTEX_PYTHON:-python3}" <review-cli> stop` on each named document that exists, best-effort — any failure (CLI crash, timeout) degrades to a silent skip, since the doc is about to be deleted regardless of its review state.
3. **Drop those documents.** Unlink each one from the worktree directly (not `git rm`). A document surviving its own deletion attempt halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts — proceeding to flip gates over a ladder that is only partly dropped would leave state worse than either extreme.

**WHICH documents Steps 2–3 touch comes from the CALLER, never from a list this worker holds.** The attach line's own `drop=<name>[,...]` field (`lazy-spec.request-protocol.md` → Routing-block grammar) names them; the router decides what a rollback removes, because which documents an asset even has is a property of its type and its tools. An attach line with no `drop=` field drops nothing at all — the gates still roll back and every file stays on disk.
4. **Flip the downstream gates off.** `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`, each via an unconditional `flip_gate.flip_gate(..., off=True, auto=True)` (an `--off` flip needs no precondition, per `lazy-spec.lifecycle-protocol.md` Part 2). `spec_design_done` is left untouched — design is what the incoming request is about to revise, not what the rollback undoes. A refused flip (the asset went `spec_cancelled` mid-rollback) halts (`HaltReason.PLAN_DROP_PARTIAL`) and aborts — Steps 1–3 already cancelled the job and dropped the named documents, so a refused flip here still leaves that work half-done.
5. **Seed the attach delta and re-submit.** The ordinary attach-seed step runs exactly as it does for any attach target (`lazy-spec.request-protocol.md` § Body distribution rules, point 2), but the primary doc re-enters review via `lazycortex-review submit` (skipping the opening writer round) instead of `start`, since the doc already carries prior approved content the rollback just reopened.

Steps 1–4 are the rollback's own responsibility; Step 5 is the ordinary attach-seed flow every attach target runs — a rollback changes only which review verb (`submit` vs `start`) that step uses on this feature's primary doc, never what the step does. Whether to invoke the rollback AT ALL — versus modifying the target in place, or routing through a change despite it technically not being launched — is `spec.catalog-coordinator`'s judgment call in routing mode (playbook Chapter 9); the rollback primitive itself stays unconditional on its own three refusal checks (launched, halted, cancelled) no matter who calls it.

The halt phrases these steps pass — `HaltReason.PLAN_DROP_PARTIAL` above included — are drawn verbatim from the closed set in `lazy-spec.lifecycle-protocol.md` Part 5; no caller composes one.
