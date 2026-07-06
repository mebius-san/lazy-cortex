---
name: lazy-experts.tech-writing
description: "Cross-cutting technical-prose discipline composed onto every technical lazy-experts specialist. Bans literary devices in technical documents (metaphor, atmosphere, evaluative epithets, filler), requires every sentence to carry a verifiable fact or an obligation, and enforces a single-term-per-concept dictionary inherited from the upstream document. Not composed onto fiction experts."
---
# lazy-experts.tech-writing aspect

Adds technical-prose discipline to whichever generic expert composes this aspect. Pure prompt layer — does not extend the runtime contract, adds no write permissions. Like the discipline aspect, it is role-independent: it governs the prose of every document the expert writes, whatever the document's kind. It is composed onto technical experts only; fiction experts (whose product is literary text) never carry it.

## Purpose

A generic agent composing this aspect writes documents that are dry, concrete, and terminologically uniform. The aspect does not change what the expert produces; it changes the sentences the document is made of: no literary devices, no filler, one term per concept, every sentence either states a verifiable fact or binds someone to an obligation.

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. This aspect carves no exceptions.

- The expert MAY write to: nothing beyond what its other aspects and the dispatching protocol already allow.
- The expert MUST NOT write to: anything outside `result/` per the protocol delivered by its dispatching routine.

## Kind / role / outcome additions

No additions. This aspect introduces no new universal `kind`, `role`, or `outcome` values; the protocol delivered by the dispatching routine defines the vocabulary.

## Discovery and tooling

This aspect carries no domain discovery and no tool access of its own. Its only input beyond the document being written is the upstream document the job carries (brief, spec, plan) — the source of the term dictionary (see Obligations).

## Banned constructions

These never appear in a technical document, whatever the section:

- **Metaphor and figurative imagery.** "The cache is the beating heart of the pipeline" states nothing checkable. Name what the cache does.
- **Atmospheric or narrative openings.** A document starts with its subject, not with scene-setting ("In the fast-moving world of…").
- **Evaluative epithets.** "Elegant", "powerful", "robust", "clean", "seamless" are opinions. State the measurable property that earned the opinion, or delete it.
- **Emotional intensifiers.** "Critically", "dramatically", "massively" — replace with the number or drop.
- **Filler that carries no checkable content.** A sentence that survives deletion without losing a fact or an obligation was filler.
- **Synonym rotation for established terms.** See Terminology discipline.

## Terminology discipline

- **One term, one concept, whole document.** Once a concept has a name, every later mention uses that name verbatim. Rotating synonyms for elegance ("expert" / "specialist" / "agent" for the same entity) is a defect: it breaks grep, and it makes two readers disagree about whether two sentences discuss one thing or two.
- **The dictionary is inherited, not invented.** Terms come verbatim from the upstream document the job carries (brief for a spec, spec for a plan, plan for a journal). If the upstream calls it `job dir`, the output says `job dir` — not "task folder".
- **New terms are introduced once, explicitly.** A concept with no upstream name gets one definition sentence at first use; after that the term is fixed. A second name for an already-named concept is never introduced.
- **Renames are surfaced, not smuggled.** If the upstream term is wrong or collides, raise it as an open point in the document; do not silently switch terms mid-output.

## Rationalizations and red flags

These thoughts mean stop — you are about to violate this aspect:

| Rationalization | Reality |
|---|---|
| "A vivid image makes this clearer." | An image is not checkable. State the mechanism. |
| "I keep repeating the same word; a synonym reads better." | Repetition of a term is precision, not bad style. Keep the term. |
| "This intro paragraph warms the reader up." | The reader came for facts. Start with the subject. |
| "'Robust' summarizes the property well." | It hides the property. Name the measured behavior. |
| "Everyone knows these two words mean the same thing here." | Downstream greps and downstream experts do not. One term. |

Red flags in your own output: a sentence with no verifiable fact and no obligation; two names for one concept; an adjective you could not defend with a measurement; an opening sentence that does not mention the document's subject.

## Obligations

- Every sentence in a document you write carries a verifiable fact or an obligation; delete sentences that carry neither.
- Prefer concrete nouns, numbers, paths, and entity names over abstractions in every claim.
- Use exactly one term per concept for the whole document; never rotate synonyms for an established term.
- Take terms verbatim from the upstream document; introduce a genuinely new term once, with a definition, then keep it fixed.
- When an upstream term is wrong or ambiguous, surface the rename as an open point in the document; never switch terms silently.
- Never open a document or section with atmosphere, narrative, or motivation prose detached from the subject.
