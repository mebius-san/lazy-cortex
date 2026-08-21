---
name: lazy-spec.change-playbook
description: Type playbook for change assets — the feature-shaped definition flow plus the five-phase cascade that folds the delta into every declared target and the regression it triggers once implemented.
---
# Change playbook — the `change` asset type

This document is the coordinator's law on any asset whose status folder-note carries `spec_asset_type: change`. It covers the definition half of the flow — the documents, the code-bearing judgment, tool determination, the first two gates and their launch checkboxes — plus the cascade, which is what makes a change different from every other type. Implementation and verification belong to the playbooks of the tools declared in `spec_tools`.

## What this type is

`spec_asset_type: change` is a full-mode asset: the complete S0..S5 ladder, the complete launch-checkbox set, its own plans and reports for every declared tool.

The start document is `design.md`, of document type `design`: a change describes the delta it introduces the same way a feature describes what it builds.

**Place is not the type.** `default_path` files new changes under its own folder, but a change is legal anywhere in the product's catalog, including nested under another asset. The type is read from the key, never inferred from the folder.

The definition half of a change's flow is the same as a feature's, PLUS the cascade into its targets. Targets are declared as the `spec_targets` list on the status folder-note; the tokens are paths relative to the product's `spec_path`, and a nested asset is addressed by its full path.

## Definition documents

- `design` (`design.md`) — mandatory. Never `cancelled`: the stage primitive refuses it exactly as it refuses a cancelled `bug.md`.
- `architecture` (`architecture.md`) — mandatory the moment the asset is judged code-bearing. Never `cancelled` either.
- Plans and reports are the tools' property. Which ones exist and what they are called is declared by the tool playbooks through their own `plan_doc` / `report_doc` declarations; this playbook does not enumerate them.
- `decisions.md` — the registry of recorded decisions, written only by the `lazy-spec.decide` primitive. It carries no stage and takes no part in any gate.

## Code-bearing

Code-bearing is the coordinator's own judgment, not a script-level flag.

An explicit declaration settles it outright: a product or a type declaring itself code-bearing (or docs-only) in its guidelines or in a `# Coordinator rules` section closes the question without reading a document.

Absent an explicit declaration, the coordinator reads the change's own design document for whether the delta describes a change to code. A docs-only change is never charged the architecture step — the `Write architecture` checkbox never hangs, `architecture.md` never comes into existence, and the architecture clause drops out of the `spec_plan_done` precondition.

## Tool determination

**When.** Tools are determined on design approval — and on architecture approval too, where architecture exists. Until that moment the note carries no `spec_tools`, and that state means "not determined": the definition half runs normally, implementation does not start.

**From what.** The direct statements of the design and architecture documents about what is actually being made — code, data, documentation, tests. The architect's conclusions take priority over the design's phrasing wherever the two diverge.

**Written how.** The coordinator writes the list through `note-set-key`; until the key is written, no implementation checkbox hangs. An unobvious choice is never guessed — the coordinator raises a `[!question]` listing the candidates and waits for the operator's tick.

A tool that lands in `spec_tools` with no declaration in `tool_types` is a finding, not a guess: the coordinator raises the question rather than inventing behaviour for a playbook that does not exist.

## The gates of the definition half

- **`spec_design_done`** — closes once `design.md` reaches `spec_stage ∈ {approved, cancelled}`. A derived gate: its precondition is fully computable from sibling doc state, so the coordinator flips it itself the same cycle the precondition starts holding.
- **`spec_plan_done`** — closes once the previous gate is true AND — for a code-bearing asset — `architecture.md` is `approved` too, AND every declared tool carrying a declared `plan_doc` has its plan at `spec_stage ∈ {approved, cancelled}`, or has no plan at all. Absence is "no plan needed" and the gate is free; presence is "intent to plan", and then the plan must clear review. Derived as well.

The architecture clause adds no sixth boolean — it rides inside the same `spec_plan_done` precondition, between the design check and the plan checks.

**Downward reconciliation.** A gate already true goes stale when its governing document reappears un-accepted. `spec_plan_done` goes back to `false` (`flip-gate --off`, auto) when a declared tool's plan exists at a stage outside `{approved, cancelled}` while the gate reads true. The downward flip commits atomically and the coordinator immediately re-runs its upward checks against the fresh state, so a dependent checkbox disappears the same cycle rather than lagging a tick.

## The launch checkboxes of the definition half

| Checkbox | Appears when | Dispatches (role · source · context · result) |
|---|---|---|
| `Write architecture` | `spec_design_done` true AND the asset is code-bearing AND `architecture.md` doesn't exist | architect · `design.md` · guidelines only · `architecture.md` |
| `Write <tool>-plan` | `spec_design_done` true AND (the asset is NOT code-bearing OR `architecture.md` is `approved`) AND that tool's plan doesn't exist | role from the plan's review class · `design.md` · guidelines · that tool's plan |
| `Publish` | `spec_released` true AND `spec_draft` still true | no job — the tick clears `spec_draft` through `note-set-key` and the coordinator removes the checkbox |

`Write <tool>-plan` hangs once per declared tool of the asset whose declaration carries a `plan_doc`. A tool without a `plan_doc` gets no planning checkbox at all.

**The one difference from a feature on this table, and it is hard:** the change's OWN `Write test-plan` does NOT hang until the phase-II cascade has converged. Every target's test-plan must reflect the delta before the change starts writing its own — otherwise the change's own plan is written against a contract that is about to change.

Implementation checkboxes are declared by the tool playbooks, not by this document. With several tools in play their labels are parameterized by tool (`Start implementation (code)`), so two tools never contend for one slot.

Ticking is the operator's gesture and only theirs; the coordinator never ticks a checkbox under any circumstance. Dispatching a ticked box is an ordinary `dispatch-job` call: the expert resolves from the result document's own review class, `protocols` come from the review section's default plus that class entry's own list, and guideline context folds in from the product's role paths plus `"*"`, together with the asset's and the product's `decisions.md` where each exists. Dispatch is deduplicated by key — the status note's path relative to `spec_path` plus the label.

`spec_halted: true` overrides this table unconditionally: no checkbox hangs, and any un-ticked one comes down. A ticked one (`- [x]`) stays — the operator's tick has already happened.

## The cascade — five phases, strictly ordered

A `change` asset carries the FULL launch-checkbox ladder like any other asset — the plans of its declared tools (of whatever scale the change's own implementation needs, or none at all), its own `test-plan.md` (testing the change's OWN modifications, never a duplicate of a target's test-plan), the reports of its own tools. This chapter is the coordinator's prose for the parts that are specific to a change: folding its delta into the assets it targets, and the regression it triggers once implemented.

**(I) Design convergence + counter-check.** Once the change's OWN `design.md` is approved, the coordinator dispatches a designer job per declared target in `spec_targets` (one at a time, not in parallel) to fold the change's delta into that target's `design.md`; the target's `design.md` re-enters review. Once that review closes approved, the coordinator dispatches a counter-check job: the change's OWN writer, with the now-updated target delta in context, verifies the change's own spec still matches what actually landed and revises if not. This repeats to a fixed point — a change touching several targets runs this convergence loop per target, and any target's re-approval after a cascade fold triggers the same counter-check pattern generically: a re-approved doc downstream always earns its paired writer a verification pass. Each target folded to completion joins the `spec_cascade_targets_done` list on the change's status folder-note; once every `spec_targets` entry is accounted for there, `spec_cascade_done` flips to `true` — the change's terminal cascade state, separate from its own launch-checkbox ladder finishing.

**(II) Test-plans, only after convergence.** Once every declared target's design fold has converged, the tester folds the same delta into each target's `test-plan.md` (the target's living contract for functional behaviour — it must reflect what the feature now actually does). Only once this phase completes does `Write test-plan` hang for the CHANGE's own test-plan.

**(III) The change's own `code-plan.md`.** Targets' `code-plan.md` siblings are dead weight by this point — a target's code plan is a one-shot artifact of ITS OWN original build, and the FIRST change ever cascaded into a given target drops that target's `code-plan.md` from the worktree entirely (history lives in git and in the target's own `code-report.md`; the plan-absence precondition on `spec_plan_done` already tolerates this). A SECOND change cascading into an already-cascaded target later finds no `code-plan.md` left to drop — nothing to do, not an error. The change's OWN `code-plan.md` is authored fresh against the change's own scope via the ordinary `Write code-plan` checkbox.

**(IV) Implementation and testing of the change itself.** Runs through the ordinary ladder — the implementation checkbox and `Start testing` on the change asset, same as any asset. The change's implementation is what actually lands the folded delta in code; the targets' own docs were already updated in phases I–II, targets' code is not separately re-implemented by the coordinator.

**(V) Regression.** Closing the change's implementation (its `spec_develop_done` flipping true) flips `spec_tests_passing` back to `false` on every one of its `spec_targets` — an ordinary `flip-gate --off` call per target, the exact same downward-reconciliation primitive that takes a gate down on a stale test-plan, just triggered here by the change's own completion instead of a doc regression. Nothing bespoke follows: the SAME reconciliation pass that runs on every state change re-hangs each target's `Start testing` checkbox on its own, because the checkbox's precondition (`spec_develop_done` true AND `test-plan.md` approved) is untouched by the gate flip and the slot is free again — no special-cased "re-testing" code path exists. The change's OWN `spec_released` waits until every target is green again. On a red re-run, the change's `Start testing` tick (or the retest itself) drops a `> [!attention] regression failed on <target> — [[<path to the bug asset>]]` callout plus a `# History` line on the CHANGE asset; findings become bug assets exactly per the ordinary proposal mechanism — an expert drops an `[!asset-proposal]`, the coordinator materializes it through the scaffold primitive — and the bug asset's `# Sources` carries a wikilink back to the change (a two-way link). A red regression run is NOT a halt — it is the ordinary outcome the bug-asset mechanism exists to handle.

## Conflicting changes on one feature

The "one active feature — one active change" lock does not exist: a new change may cancel or modify an older one in flight. When a second change targets a feature already being cascaded into, the coordinator decides — wait for the in-flight one to finish, cancel the older one (via `cancel-job` plus the ordinary asset-cancellation path), or fold the new one in as a modification of the same fold. Whenever the right call is not obvious from the rules layers in scope, the coordinator surfaces a `[!question]` to the operator rather than guessing.

## Merge drift

A cascade fold that cannot apply cleanly, or a target that vanishes mid-flight, is handled by the ordinary halt mechanism: the coordinator calls `flip-gate --halt` with `HaltReason.MERGE_CONFLICT` or `HaltReason.PLAN_DROP_PARTIAL`, exactly as any other halting caller would. It does not invent new halt phrasing.

Halt silences the automation — checkboxes, cascade dispatch, rule-driven dispatch — but never the five gate booleans themselves, and never `# Coordinator commands`: an operator gesture runs on a halted asset too, and that is precisely how the operator directs recovery.

## Pre-launch rollback

When a change has not launched yet and routing decides to attach a new request onto it, the attach line carries a `drop=` list: `architecture.md` plus the plans of the declared tools. Reports and `design.md` are never dropped.

The rollback itself is an atomic primitive: it refuses on its own when the asset is cancelled or halted, no matter who calls it. The coordinator's judgment picks whether to invoke it; the primitive still enforces its own safety.
