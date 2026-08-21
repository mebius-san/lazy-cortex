---
name: lazy-experts.structure
description: "Cross-cutting placement discipline composed onto every technical lazy-experts specialist. Routes the question 'where does this live, and where does new work belong' through the repository's structure map via the `lazy-wiki.structure` skill's query mode instead of scanning the tree, and forbids loading the whole map into context. Not composed onto fiction experts."
---
# lazy-experts.structure aspect

Adds placement lookup to whichever generic expert composes this aspect. Pure prompt layer — does not extend the runtime contract, adds no write permissions. Role-independent: it governs how the expert grounds a location claim in any document it writes — where an existing thing lives, where a new file or directory belongs. It is composed onto technical experts only; fiction experts never carry it — a repository map has nothing to say inside a scene.

## Purpose

An expert composing this aspect answers "what is where" from the repository's structure map instead of scanning the tree and reading files at random. The map answers both directions — what exists and where new work belongs — in one query, and the query returns a slice, so the expert's context never pays for the parts of the repository its task does not touch.

The failure this closes is quiet waste with a wrong ending: an expert without the map globs directories, opens files that sound relevant, and places its new file where the last-read neighbour happened to sit — which is how one repository grows three conventions for the same kind of artifact.

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. This aspect carves no exceptions and adds a prohibition of its own.

- The expert MAY write to: nothing beyond what its other aspects and the dispatching protocol already allow.
- The expert MUST NOT write to: `docs/structure.md`, under any circumstance — not to enter the file it is about to create, not to fix an entry it knows is stale. The map is owned by its curator and by the structure skill's rebuild mode; a stale entry is at most a remark in the expert's own document.

## Kind / role / outcome additions

No additions. This aspect introduces no new universal `kind`, `role`, or `outcome` values; the protocol delivered by the dispatching routine defines the vocabulary.

## Discovery and tooling

The map is reached through the `lazy-wiki.structure` skill in `query` mode, named here and never resolved from a path — `query [<path>]` returns the slice under `<path>`, an empty path returns the top level. Never `Read` `docs/structure.md` whole: the map covers the repository and a job touches a corner of it.

**When the skill is absent, or reports that no map exists, this repository has no map.** Ground the same answer by reading the tree directly (`Glob` the relevant subtree, `Read` its entry points), say nothing about the missing tooling in your document, and move on — the absence is a configuration fact for the install and doctor tooling to surface, never for an expert's output.

## Obligations

- Before claiming where something lives, or choosing where a new file or directory goes, query the structure map through `lazy-wiki.structure` for the relevant slice.
- Place new work where the map's descriptions say that kind of thing belongs; when the map offers two plausible homes, name the choice and the reason in your document rather than picking silently.
- When the map's entry contradicts what you then find on disk, trust the disk and note the stale entry in your own document — the doctor and the rebuild own the repair.
- Query a slice, never the whole map; an empty-path query for the top level is the widest read this aspect permits.
- Never write to the structure map.
