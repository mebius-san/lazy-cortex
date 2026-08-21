---
name: lazy-spec.research-playbook
description: Type playbook for research assets — a decision-producing design document, an empty tool set, and a cycle that ends at approval.
---
# Research type playbook — an asset whose deliverable is the decision itself

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: research`. The type is short: it has neither work nor verification, and its whole cycle ends at the approval of one document.

## What this type is

`spec_asset_type: research` — the asset poses a question and ends at the answer to it. The deliverable is **the decision itself**: the options compared, the measurements taken, the conclusion and its justification, recorded so that later work can cite them.

- **Start document** — `design.md`, `spec_doc_type: design`, and it is the only one. Here a design document carries not "what we are building" but "what we found out": the question, the options considered, the criteria, the conclusion. The approved document IS the asset's result — no separate report ever appears.
- **`cancelled` is refused on `design.md`** — research that stopped being needed is abandoned as a whole through `spec_cancelled`.
- **Location is not a fact of the type.** The declaration's `default_path` drops new research into its own subfolder, but the asset is legal anywhere, nesting inside the folder of the feature whose question it settles included. Type resolution reads `spec_asset_type`, never a path; the asset boundary stays the folder whose folder-note carries `spec_role: status`.
- **The tool set is definitively empty.** The type declaration names `default_tools: []`, and the scaffold writes the empty list into `spec_tools` at creation. This is not "tools not determined yet" — it is a recorded fact that the asset will have no work: an empty list and an absent key read differently, and the coordinator never completes the emptiness into anything. If the research turns out to require work after all, that work is opened as a separate asset (below), never by appending tools to this one.

## Gates

| Gate | What closes it on a research asset |
|---|---|
| `spec_design_done` | `design.md.spec_stage == approved` — the conclusions are accepted by review. |
| `spec_plan_done` | ready by absence: nothing to plan, no tools. |
| `spec_develop_done` | ready by absence: an AND over non-`test` tools is true over an empty set. |
| `spec_tests_passing` | ready by absence: the `test` tool is not in the set. |
| `spec_released` | an external "the conclusions were handed on" signal — as a rule, a `Publish` tick. |

In practice this means the approval of the single document carries the asset from `S0` to `S4` within one coordinator wake: it flips `spec_design_done` on the approval, then the next three in turn, since each of them waits on work the asset does not have. Not one job is dispatched along the way.

The gates remain a strict ladder — each requires the one before it — and the `lazy-spec.flip-gate` primitive flips whichever it is called on, unconditionally (its only refusal is a cancelled asset). The order is held by the coordinator's reasoning: the four flips of that one wake go in ladder order, not as an unordered batch.

`spec_released` is the one gate the coordinator does not derive from document state: it waits on an external signal that the conclusions reached whoever needed them. An asset whose conclusions are approved but which nobody has picked up stands honestly at `S4`.

## Checkboxes

Exactly one:

| Checkbox | Appears when |
|---|---|
| `Publish` | the terminal gate `spec_released` has closed and `spec_draft` is still `true`. |

No architecture, plan, or implementation checkbox exists on this type: `Write architecture` never hangs, because research introduces no shape of code, and `Write <tool>-plan` never hangs, because there are no tools at all. Block shape in `# Gates` is the common one:

```
> [!gate] Publish
> - [ ] Publish
> tick to clear spec_draft
```

`Publish` is the one label that never produces a job: the tick clears `spec_draft` through `note-set-key` and the coordinator removes the block. There is no automatic clearing — approved conclusions do not mean the operator is ready to hand them on.

## Work that grows out of research

Research almost always spawns work — but never inside itself. New work is opened as a **new asset**: an expert or the coordinator raises an `[!asset-proposal]` citing the approved conclusions, the coordinator materialises an asset of the appropriate type and links it to the research through `spec_depends_on`.

Mutating the research asset instead is forbidden: appending tools to it, hanging an implementation checkbox on it, rewriting the approved document into a specification of a future feature — each destroys the thing the asset existed for. An approved research document is immutable as a citation: the very assets that grew out of it will point at it, and it must read the way it read at the moment of approval.

Research whose conclusion turns out to be wrong is not rewritten after the fact — a new one is opened, citing the previous through `spec_depends_on`.
