---
name: lazy-spec.doc-height-protocol
version: 2
description: The abstraction height a spec document holds — every document kind forms one vertical, each level writes at the height of its direct children and no deeper, and references run upward only — binding both the class's main writer and its validators.
---
# Document height protocol v2

Contract for every expert dispatched against a document of the `vision`, `system-vision`, `system-design`, or `design` review class — the main writer and every validator alike. It governs one thing: at what level of abstraction this document speaks, and what to do with material that belongs a level below.

## The height ladder

Documents of one kind form one vertical, whatever the kind — vision, design, use cases, tech, any future kind: the content-root document speaks of the system, a product-level document of the product, an asset-level document of the single asset. Each document writes at the level of its direct children and no deeper, and the levels of one vertical do not duplicate each other.

The asset-level design is the bottom of the design vertical: the first level where the mechanics of one asset belong, still as design, never as code.

One test decides placement: **behavior that lives entirely inside one child belongs at that child's level.** What must hold is this document's ceiling; the mechanism that makes it hold is the lower level's floor.

## Writer obligations

- A document is written before the documents below it and never cites them. References run upward only — the lower document, written later, cites this one where it unfolds a general principle into its detailed form. Naming child entities — products, assets — is this document's content; referencing child documents is not.
- When a round's edits grow a section into per-record, per-branch, or per-failure detail, that growth is the signal to push the material down, not to polish it in place.

## Validator obligations

- A gap whose closure requires elaborating lower-level mechanics is **not a finding against this document** — it is outside this document's height, and nothing is added here for it.
- Findings phrased as "the architecture cannot implement this without knowing `<mechanism>`" are answered by height: the mechanism is lower-level work, and its absence there is a finding against the lower document once it enters review — flag it as a candidate (an `[!asset-proposal]` or a note to the coordinator), never as a blocker here.
- The completeness bar for this document is its own height: no contradiction between siblings, no material that belongs a level below. It is never: every failure mode of every child resolved.

## Failure mode this protocol exists for

Without a height bound, the writer-validator loop ratchets downward: the validator demands a full machine contract, the writer folds it in, the new text spawns deeper edge cases, and the top document accumulates page-scale mechanics that belong to one product's runtime. Both sides stop the ratchet by holding the height instead of elaborating past it.
