---
name: lazy-spec.doc-height-protocol
version: 2
description: The abstraction height a spec document holds — vision carries goals and value only, system design writes at product level, product design at feature level, mechanics one level down are delegated, never elaborated — binding both the class's main writer and its validators.
---
# Document height protocol v2

Contract for every expert dispatched against a document of the `vision`, `system-vision`, `system-design`, or `design` review class — the main writer and every validator alike. It governs one thing: at what level of abstraction this document speaks, and what to do with material that belongs a level below.

## The height ladder

Each design document writes at the level of its direct children and no deeper:

- **Vision (`vision.md`, any level)** — goals and value only: what this is, for whom, what counts as success, what could sink it. Not a single design decision — the Design Concept section is one paragraph plus a reference to the sibling design, never a digest of it. The ladder applies within the kind too: the content-root vision speaks of the system, a product vision of the product, an asset vision of the one feature. Goals live ONLY in a vision; a design document carries none and opens with a reference to its sibling vision.
- **System `design.md`** (class `system-design`, repo root) — the product level: which products exist, what each is responsible for, how they relate, and the principles shared by all of them. The inner workings of any single product are not its material — not its data records, not its failure branches, not its algorithms, not its edge cases.
- **Product `<product>/design.md`** (class `design` on a product folder) — the feature level: which features the product carries, what each does, how they share the product's surfaces. The inner workings of any single feature are not its material.
- **Feature `<feature>/design.md`** — the first level where a feature's own mechanics belong, still as design (what and why), never as code.

One test decides placement: **if a paragraph describes behavior that lives entirely inside one child, it belongs in that child's document.** A sentence naming the child and the obligation it carries is this document's ceiling; the mechanism satisfying the obligation is the child's floor.

Use cases follow the same ladder: the content-root `use-cases.md` speaks of the system's actors and cross-product scenarios, the product-level one of cross-feature scenarios, the asset-level one of the single feature's flows — so the three levels do not duplicate each other or the sibling design doc's own scope.

## Writer obligations

- Closing a finding or answering a question that requires mechanics from a level below is done with one boundary sentence — "the `<child>` design owns this: it must guarantee `<obligation>`" — never by writing the mechanics here.
- A decision recorded here states the principle and the constraint it imposes on children; the child's document records how the constraint is met. The rejected alternative behind a decision belongs in a decision record (`[!decision]` callout or `decisions.md` entry, per `lazy-core.markdown-style`'s decision-statement shape), never in the prose — a "Rejected …" tail inline in a design bullet is a style violation at every height.
- When a round's edits grow a section into per-record, per-branch, or per-failure detail, that growth is the signal to push the material down, not to polish it in place.

## Validator obligations

- A gap whose closure requires elaborating a child's mechanics is **not a finding against this document**. Verify instead that the document names the child and the obligation; when it does, the gap is closed at this height.
- Findings phrased as "the architecture cannot implement this without knowing `<mechanism>`" are answered by delegation: the mechanism is the child document's work, and its absence there is a finding against the child once the child enters review — flag it as a candidate for the child (an `[!asset-proposal]` or a note to the coordinator), never as a blocker here.
- The completeness bar for this document is: every child named, every child's obligation stated, no contradiction between siblings. It is never: every failure mode of every child resolved.

## Failure mode this protocol exists for

Without a height bound, the writer-validator loop ratchets downward: the validator demands a full machine contract, the writer folds it in, the new text spawns deeper edge cases, and the top document accumulates page-scale mechanics that belong to one product's runtime. Both sides stop the ratchet by delegating at the boundary instead of elaborating past it.
