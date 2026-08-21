---
description: Two duties for anyone editing a spec-catalog document — read the accumulated decisions before the first edit, and reserve a decision statement for a genuine fork. Owns the weight test that keeps the decisions registry from filling with restated conclusions.
paths:
  - "**/*.md"
---
# Spec Decisions

This rule concerns documents in a spec catalog (`lazycortex-specs`) — it has nothing to say about markdown elsewhere.

## 1. Read before you edit

Working on an asset or product whose folder carries a `decisions.md` — read it, and the product's own `decisions.md`, before your first edit to any of that asset's documents. A record explains why a choice was made; skipping it risks re-proposing a rejected option or quietly reversing something already settled.

## 2. A decision statement deserves only a real fork

Not every sentence in a design, bug, tech, or architecture document is a decision. Reserve the decision-statement role for a claim that passes all three tests:

- **A fork existed** — at least two viable options were genuinely considered. No alternative, no decision — just the only move available.
- **Reversal is expensive** — the choice constrains later work, or undoing it touches more than one place. A cheap, reversible detail is not a decision.
- **Unrecoverable from the artifact** — a later session can read the code and the text and see *what* was done, but not *why*. When the "why" is obvious from the text itself, a record only duplicates it.

Short test: will a later session ask "why not the other way?" and burn an hour re-deriving the answer? If no, it is not a decision.

**Anti-list** — never worth a decision statement: a consequence of an already-recorded decision, a repo convention, naming or private structure, anything the existing code or contract already dictates.

**Trap marker** — if there is nothing honest to write for the rejected side, there was no fork; do not force one.

The same bar applies to a decision-candidate marked in a report — a candidate that fails these tests is noise the coordinator would carry into design for nothing.

## Enforcement

`lazy-spec.audit` verifies this rule's invariants — the closed transfer-source set and the registry's wiring in `lazy-core.markdown-style` — still hold against the plugin's actual state. `lazy-spec.doctor` enforces the registry's structural shape (record format, header, numbering, links) file by file.
