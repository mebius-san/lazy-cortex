---
name: lazy-experts.terms
description: "Cross-cutting terminology-lookup discipline composed onto every technical lazy-experts specialist. Routes the choice of a word through the repository's terms dictionary before the expert coins one, forbids the expert from editing that dictionary, and settles the precedence question when the dictionary and the job's upstream document name one concept differently. Not composed onto fiction experts."
---
# lazy-experts.terms aspect

Adds terminology lookup to whichever generic expert composes this aspect. Pure prompt layer — does not extend the runtime contract, adds no write permissions. Role-independent: it governs how the expert picks a word in every document it writes, whatever the document's kind. It is composed onto technical experts only. Fiction experts never carry it: an obligation to call a thing by its registered term, read literally inside a scene, replaces pronouns and descriptive phrases with the entity's name, and the prose dies.

## Purpose

An expert composing this aspect names a concept with the word the repository already uses for it, instead of inventing a second one. The sibling tech-writing aspect requires one term per concept *within* a document; this aspect supplies the term from *outside* it, so two documents written months apart by two experts converge on the same word.

The failure this closes is silent and cumulative. An expert that invents a name is not wrong about anything: its document is internally consistent and reads well. The cost lands later, on the reader who now has two words and no way to tell whether they mean one thing.

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. This aspect carves no exceptions and adds a prohibition of its own.

- The expert MAY write to: nothing beyond what its other aspects and the dispatching protocol already allow.
- The expert MUST NOT write to: the terms dictionary, under any circumstance — not to add the term it just coined, not to fix a definition it disagrees with, not to correct a typo. The dictionary is owned by a curator that reads finished documents; an expert editing it mid-sentence decides for the whole repository from inside one paragraph.

## Kind / role / outcome additions

No additions. This aspect introduces no new universal `kind`, `role`, or `outcome` values; the protocol delivered by the dispatching routine defines the vocabulary.

## Discovery and tooling

The dictionary is reached through the `lazy-wiki.terms` skill, named here and never resolved from a path: which scope serves the document, and which file holds that scope's dictionary, are the skill's business, not yours. Pass it the path of the document you are writing — it knows where it writes, the skill does not.

**When the skill is absent, this repository has no dictionary.** Write as you normally would and say nothing about it — the absence is a configuration fact, not a problem for your document to report.

## Obligations

- Before naming a concept with a word of your own, ask `lazy-wiki.terms` whether the repository already has one.
- When the dictionary carries the concept, use its term verbatim, even when your own word reads better. A better second name is still a second name.
- When the dictionary carries a *neighbouring* concept under the name you were about to use, pick a different word for yours and make the difference readable from your text.
- When the dictionary carries nothing matching, use your own word and keep writing. The curator enters it later, reading the finished document; nothing is expected of you.
- When the dictionary and the job's upstream document name one concept differently, the dictionary wins — and you state the disagreement in your own document rather than resolving it silently.
- When the choice is genuinely ambiguous, take the existing term. You have no operator to ask, two definitions that drifted apart can be merged afterwards, and a synonym already spread across documents cannot be recalled from them.
- Never write to the terms dictionary.
