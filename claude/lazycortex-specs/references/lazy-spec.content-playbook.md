---
name: lazy-spec.content-playbook
description: Type playbook for content assets — one design document describing a game entity, tools preset to data at creation, no architecture and no planning step.
---
# Content type playbook — one game entity, one document, zero planning

This file is the law of the wake on which `spec.coordinator` works an asset whose status folder-note carries `spec_asset_type: content`. It covers the first half of the flow: what defines the asset, what closes `spec_design_done` and `spec_plan_done`, and which checkboxes hang before work starts. Implementation and verification are declared by the `data` and `test` tool playbooks.

## What this type is

`spec_asset_type: content` — the asset describes **one** game entity: a race, a skill, an item, an enemy class, a faction. Not a set, not a subsystem, not a mechanic — a single unit of content that is then entered into the project's data files against its schemas.

- **Start document** — `design.md`, `spec_doc_type: design`, and it is the only document of definition. The design states what the entity is, how it differs from its neighbours, what its numbers and links are. No second document is authored on this type: a unit of content has no separate "how it is built" layer — the build is dictated by the project's schemas, not by the asset.
- **`cancelled` is refused on `design.md`** — the asset is abandoned as a whole through `spec_cancelled`.
- **Location is not a fact of the type.** The declaration's `default_path` drops new content assets into their own subfolder, but the asset is legal anywhere: inside the folder of a feature that introduces a family of entities, or next to its siblings. Type resolution reads `spec_asset_type`, never a path; the asset boundary stays the folder whose folder-note carries `spec_role: status`.
- **Tools are known from creation.** The type declaration names `default_tools: ["data"]`, and the scaffold writes that list into `spec_tools` when the asset is created. The tool determination that happens after design approval on other types has already happened here: a unit of content is made by entering data. The `test` tool is added by the same rules as any other — a coordinator decision, when the entity warrants an executed check, never automatically.
- **Buying an extra tool is possible.** When the approved design plainly demands something more — say a user-facing description of the entity, i.e. the `docs` tool — the coordinator does not extend the list silently: it raises a `[!question]` listing the candidates with a case for each, and only extends `spec_tools` through `note-set-key` once the operator answers. A tool named in `spec_tools` but not declared in the product's `tool_types` is a finding for `# Status brief`, not a gap to fill in.

## The first two gates

| Gate | What closes it on a content asset |
|---|---|
| `spec_design_done` | `design.md.spec_stage == approved` — the entity's design is accepted by review. |
| `spec_plan_done` | `spec_design_done` already `true` — and that is all: there is nothing to plan. |

The second gate closes **by absence**. The `data` tool declares no `plan_doc`: between an approved entity design and the writing of its data there is no intermediate document anyone would read. The coordinator flips `spec_plan_done` on the same wake as the first gate, the moment its condition holds; there is nothing and no one to wait for. If the asset has bought a tool with a declared plan, the gate starts waiting on that plan by the general rule — `approved`/`cancelled` or absent.

The gates are a strict ladder — each requires the one before it. The `lazy-spec.flip-gate` primitive flips whichever gate it is called on, unconditionally (its only refusal is a cancelled asset), so the ORDER is held by the coordinator's reasoning, not by a script.

`spec_develop_done` is closed by the `data` tool's own accepted report, `spec_tests_passing` by the `test` tool or by freedom from its absence, `spec_released` by an external signal. What exactly closes them is stated by the tool playbooks.

## The first-half checkboxes

Exactly one:

| Checkbox | Appears when |
|---|---|
| `Publish` | the terminal gate `spec_released` has closed and `spec_draft` is still `true`. |

Neither `Write architecture` nor a plan checkbox ever hangs on this type: there is no architecture step for a unit of content by definition of the type, and there are no plans because none of its tools declares one. Block shape in `# Gates` is the common one:

```
> [!gate] Publish
> - [ ] Publish
> tick to clear spec_draft
```

`Publish` is the one label that never produces a job: the tick clears `spec_draft` through `note-set-key`, the coordinator removes the block, and the asset becomes visible to a downstream consumer. There is no automatic clearing — a closed terminal gate means the work is done, not that the operator is ready to hand it on.

The implementation checkbox (`Start implementation (data)`) and the testing one (`Start testing`) are declared by the respective tool playbooks — they are not here.

## Data conformance to the design

The approved design is the source of truth for the data, and a divergence between them is always resolved in one direction: **by work, never by rewriting the design after the fact**.

- The data diverged from the approved design (wrong number, wrong link, a missing field) — that is a defect in the work: the tool's report goes back for rework through a comment in the acceptance cycle, same job, same expert.
- The data writer disagrees with the design itself (the number breaks balance, the link is impossible under the schema) — that is an objection to the design, and it travels back into the design through review: the expert records the disagreement in its report, the coordinator returns `design.md` to review rather than settling the argument itself. Data written "the way it should be" against an approved design is the same finding even when the writer is substantively right.
- An approved design that turns out to be unimplementable is not grounds for a `[!question]` asking whether a deviation is allowed: the question goes into the design's review, where the document has its history and its reviewers.

This is a standing judgment, not a one-off: every "data versus design" conflict is walked through this fork before the coordinator writes a line into `# Status brief`.

## Pre-launch rollback

There is nothing to drop. When an incoming request attaches to a not-yet-launched content asset, the `attach` line carries no `drop=` field: the asset has no architecture document and no plans — only `design.md`, which is exactly what the request revises.

The rollback reduces to seeding the delta into `design.md` and returning the document to review; gates below `spec_design_done` are turned off through `flip-gate --off` if they had closed. An asset whose work has already launched (`spec_develop_done` true, an implementation job active, or a tool report already on disk) never reaches this path: changes to it ride a separate asset.
