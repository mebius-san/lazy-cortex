---
name: lazy-spec.feature-playbook
description: Type playbook for feature assets — the design-first definition flow, the code-bearing judgment that inserts the architecture step, how and when the tool set is determined, and what closes the first two gates.
---
# Feature type playbook — the definition half of the flow

This document is the coordinator's law for any asset whose status folder-note carries `spec_asset_type: feature`. It covers the first half of that asset's life — definition, from the starting document up to the moment the tool set is written down and the first two gates have closed. Everything after that point — implementation, reports, verification — belongs to the playbooks of the tools declared in this asset's `spec_tools` and is not described here.

## What this type is

`spec_asset_type: feature` is a full-mode asset: it walks all five gates from `spec_design_done` through `spec_released`, and its result is a working part of the product, not a document about one.

The starting document is declared by the type record as `start_doc: "design.md:design"` — a feature begins with `design.md`, of doc type `design`, which the scaffold primitive creates alongside the asset folder and its status folder-note.

**Place is not a fact about type.** The type record carries `default_path` (`features` as shipped), and that is where a new feature lands at creation when the routing line named no explicit `path=`. But a feature is legal anywhere in the catalog, including nested under another asset's folder: an asset's boundary is a folder-note carrying `spec_role: status`, never the name of a parent directory. The type is read from the status folder-note's frontmatter and from nowhere else; where the folder sits plays no part in resolving it.

## The definition documents

- **`design`** (`design.md`) — always mandatory. What the feature does and why: behaviour, not construction. Written by the designer. This document is never `cancelled` — the stage primitive refuses it, and cancelling an asset is the `spec_cancelled` overlay on the status folder-note, not a cancelled design.
- **`architecture`** (`architecture.md`) — mandatory from the moment the coordinator judges the asset code-bearing (below). Construction: module boundaries, direction of dependencies, public contract versus internals, the cost to existing callers. Written by the architect. Never `cancelled` either.
- **Plans and reports are the tools' property.** This playbook declares and demands neither `code-plan`, nor `test-plan`, nor `code-report`, nor `test-report`. Which plan document and which report document a tool has is declared by that tool's record (`tool_types.<name>.plan_doc`, optional; `report_doc`, mandatory) and described by that tool's own playbook. A tool without `plan_doc` has no plan document at all — that is a declared absence, not a gap.
- **`decisions`** — the asset's decision registry, kept by `lazy-spec.decide`. Created lazily by the first recorded decision; its absence means nothing and blocks nobody.

## Code-bearing

Whether a feature carries code is the coordinator's judgment, not a flag in script.

**An explicit declaration settles it.** When the product or the type itself declares the asset code-bearing (or, conversely, docs-only) — in the product's guidelines, in the `# Coordinator rules` section of the product folder-note, or in that same section on the asset itself — the judgment is closed and there is no reason to read the design.

**Otherwise, read the design.** Absent an explicit declaration the coordinator reads `design.md`'s own content and decides for itself: does the document describe a change to code. If it does, the asset is code-bearing and the architecture step is imposed. A docs-only feature is never imposed an architecture step: the `Write architecture` checkbox never hangs, `architecture.md` never comes into existence, and `spec_plan_done` waits on no architecture.

The judgment is re-checked on every wake until `architecture.md` exists: an approved design that turns out to be about code raises the architecture step exactly as it would have had this been visible from the start.

## Determining the tool set

An absent `spec_tools` key on the status folder-note means "tools are not determined" — not "there are no tools". While the key is absent, definition proceeds normally and implementation does not start.

**When.** Tools are determined on the design's approval — and, when the asset is code-bearing, on the architecture's approval too: until the architecture is approved, its conclusions about what is actually being built are not yet fact.

**From what.** The definition documents' own direct statements about the nature of the work: whether code is edited, whether data files are written, whether documentation is needed, whether a verification case is needed. The architect's conclusions take priority over the design's phrasing — the architecture is written later and knows what the work actually decomposed into.

**Writing it down.** The coordinator writes the resulting list through `note-set-key` on the asset's status folder-note — through a primitive, like every other frontmatter mutation, never by hand. Every name in the list must be a declared tool (`tool_types.<name>`): a tool in `spec_tools` with no declaration behind it is a finding, not a guess at what was meant.

**Ambiguity is a question, not a bet.** When the documents give no unambiguous answer (the border between `data` and `code`, whether `docs` is needed at all), the coordinator raises a `[!question]` listing the candidates and waits for the operator. Writing an empty key "for now" is forbidden: it lifts the block on implementation while having determined nothing.

## The gates of the definition half

- **`spec_design_done`** closes once `design.md` has reached stage `approved` (the gate formally accepts `cancelled` too, but the design document itself is never moved into that stage). This gate is derived: the coordinator flips it itself the moment the precondition holds, with no operator signal.
- **`spec_plan_done`** closes once all three conditions hold at the same time: `spec_design_done` is already closed; the asset is either not code-bearing, or `architecture.md` is at stage `approved`; and every tool in `spec_tools` whose record carries `plan_doc` has that plan at stage `approved` or `cancelled` — or has no plan document at all. The plan is opt-in: its absence on disk means "no plan needed" and the gate is free of it; its presence means "intent to plan", and then it must clear review. This gate is derived as well.

The architecture step gets no boolean gate of its own — it lives inside `spec_plan_done`'s precondition, between the design check and the plan check.

**Downward reconciliation.** An already-closed `spec_plan_done` goes stale when a declared tool's plan reappears outside `{approved, cancelled}`; the coordinator turns the gate back off with `flip-gate --off` and re-runs its upward checks against the fresh state in the same pass, so a dependent checkbox disappears that same cycle rather than a tick later.

## The checkboxes of the definition half

Checkboxes live in the status folder-note's `[!gate]` block. The coordinator reconciles the set on every relevant invocation — hangs a block the moment its precondition starts holding, removes an un-ticked one the moment it stops holding — and never ticks one itself: ticking is the operator's gesture. `spec_halted: true` takes every one of them down.

| Checkbox | Appears when | Dispatches (role · source · context · result) |
|---|---|---|
| `Write architecture` | `spec_design_done` closed AND the asset is code-bearing AND `architecture.md` doesn't exist | architect · `design.md` · guidelines · `architecture.md` |
| `Write <tool>-plan` | `spec_design_done` closed AND (the asset is NOT code-bearing OR `architecture.md` is `approved`) AND that tool's plan document doesn't exist | role from the plan document's own review class · `design.md` · guidelines · the plan document |
| `Publish` | `spec_released` closed AND `spec_draft` still `true` | no job — the tick clears `spec_draft` and the coordinator removes the checkbox |

`Write <tool>-plan` hangs once per tool of the asset whose record carries `plan_doc`, and the label is parametrised by the tool's name: `Write code-plan`, `Write test-plan`. A tool without `plan_doc` gets no plan checkbox.

The implementation checkboxes — `Start implementation (<tool>)` and everything downstream of them — are declared by the tool playbooks; this playbook neither hangs them nor knows their conditions.

On the `DONE` of a job that wrote a document, the coordinator opens review on it by calling `Skill(lazycortex-review:lazy-review.submit, "<result doc>")` — the only route a fresh document takes into review. A `DONE` carrying a `blocked` field wrote no document: there is nothing to submit.

## The architect must read the project-structure map

**The architect must read the project-structure service.** A wiki-adjacent curated aggregate describing the code structure of the repository — one file at a fixed, repo-wide path (`docs/structure.md`; no per-product scoping, unlike `wiki.scopes`), read through the `lazy-wiki.structure` pull-skill (`query` mode) as its primary route, since the map may be large. NOT injected wholesale into job context BY DEFAULT — but an operator may bless the guideline route instead, declaring `docs/structure.md` as an `architect`-role guideline path (`products[<key>].guidelines.architect`); when declared, it IS ordinary job context and the architect reads it from there first, ahead of the pull-skill. No curator routine yet — the map is kept current by hand or by the skill's own `rebuild` mode until one lands. Same aggregate-file-without-frontmatter pattern established elsewhere in the wiki plugin, with the same exclude-path discipline against an overlapping wiki scope.

## Architects propose children, they don't create them

Decomposing a feature into sub-features is a proposal, not an act of the expert. The architect drops an `[!asset-proposal]` callout describing the child into `architecture.md`; it creates no folder itself and calls no scaffold.

The coordinator is what materializes the proposal — through the scaffold verb, and only once the proposal has been approved together with the architecture document that carries it. The child's type must be a declared one: a proposal naming a type outside the declarations is bounced back with a `[!question]` to the operator, never turned into a folder silently.

The parent-child relationship is recorded in exactly one way — the child's token is appended to the parent status folder-note's `spec_depends_on` through `note-set-key`. Tokens are paths relative to `spec_path`, so a nested child is addressed by its full path. There is no separate "parenthood" mechanism: this is the same dependency-graph edge as any other and behaves the same way — the parent does not start implementation until its children have closed theirs.

## Rollback before launch

While a feature has not been launched into work, it can be rolled back to its definition state without opening a change asset. A rollback is the dropping of documents that describe an already-abandoned way of doing the work.

The drop list for an `attach` line's `drop=` field: `architecture.md` plus the plan documents of every declared tool of the asset — `code-plan.md` for the `code` tool, `test-plan.md` for the `test` tool, and so on by each record's `plan_doc`. `design.md` is never in the drop list: attach means precisely that the request is being routed to that design.

A docs-only feature has no architecture — only plans remain in its drop list. A feature whose tools are not yet determined has no plans either: there is nothing to drop, and `drop=` is then either empty or not written at all, which means "drop nothing".
