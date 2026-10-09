---
description: Four duties for anyone editing a spec-catalog document — read the accumulated decisions before the first edit, reserve a decision statement for a genuine fork, raise a decision candidate only for a product fork taken mid-job, and ask the operator only for a contradiction, an unclear purpose, or a product fork no approved document answers. Owns the weight test that keeps the decisions registry from filling with restated conclusions and the review loop from filling with questions.
paths:
  - "**/*.md"
---
# Spec Decisions

This rule concerns documents in a spec catalog (`lazycortex-specs`) — it has nothing to say about markdown elsewhere.

## 1. Read before you edit

Working on an asset or product whose folder carries a `decisions.md` — read it, and the product's own `decisions.md`, before your first edit to any of that asset's documents. Editing the project-wide system pair at the content-root — read the project-level `<content-root>/decisions.md` the same way, when it exists. A record explains why a choice was made; skipping it risks re-proposing a rejected option or quietly reversing something already settled.

## 2. A decision statement deserves only a real fork

Not every sentence in a design, bug, tech, or architecture document is a decision. Reserve the decision-statement role for a claim that passes all three tests:

- **A fork existed** — at least two viable options were genuinely considered. No alternative, no decision — just the only move available.
- **Reversal is expensive** — the choice constrains later work, or undoing it touches more than one place. A cheap, reversible detail is not a decision.
- **Unrecoverable from the artifact** — a later session can read the code and the text and see *what* was done, but not *why*. When the "why" is obvious from the text itself, a record only duplicates it.

Short test: will a later session ask "why not the other way?" and burn an hour re-deriving the answer? If no, it is not a decision.

**Anti-list** — never worth a decision statement: a consequence of an already-recorded decision, a repo convention, naming or private structure, anything the existing code or contract already dictates.

**Trap marker** — if there is nothing honest to write for the rejected side, there was no fork; do not force one.

## 3. A decision candidate deserves the same bar

The same bar applies to a decision-candidate — a candidate that fails these tests is noise the coordinator would carry into design for nothing. Only an expert producing code, data, or a report raises one, because it cannot stop mid-job to ask. An expert writing a document under review never does: a product fork it may not settle under § 4 is a `[!question]` with options, and a call about the document itself — what its Terms list holds, section order, wording, formatting — it settles silently, with no signal at all. Decisions are about the product, never about the document that describes it.

## 4. A question deserves a higher bar still

An expert writing a document settles every fork it meets, records the choice in the text, and moves on. The operator reads a finished document, not a questionnaire. A `[!question]` is legitimate in exactly three cases:

- **A contradiction** — the request, the approved documents, or the recorded decisions disagree with each other, and no reading reconciles them.
- **An unclear purpose** — the goal of the product or the design as a whole cannot be made out from the vision and the approved documents, so nothing can be derived from it.
- **A product fork no approved document answers** — the choice changes what the product does for its users, and the approved vision, design, tech, and sibling documents, read in full, hold no answer and no principle it follows from.

Everything else is the writer's own call: behaviour on failure, a race during a dialog, wording, where an element sits when its neighbour is collapsed, a lifetime, a default. The writer derives it from the approved documents and from the principles its own document states, writes the result as prose, and raises no signal. An answer that an approved document already holds is a fact, never a gap — asking for it is a round defect. A round that ends in questions and no settled text is the failure this section exists to prevent: a question callout is the exception in a round, never its output.

## Enforcement

The plugin maintainer's own audit tooling verifies this rule's invariants — the closed transfer-source set and the registry's wiring in `lazy-core.markdown-style` — still hold against the plugin's actual state. `lazy-spec.audit` enforces the registry's structural shape (record format, header, numbering, links) file by file.
