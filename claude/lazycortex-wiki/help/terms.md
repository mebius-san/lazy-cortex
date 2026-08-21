---
chapter_type: block
summary: One agreed dictionary per scope, consulted at write-time and kept honest by a curator and a doctor audit, so a concept never grows a second name.
last_regen: 2026-08-19
diagram_spec:
  anchor: "How the pieces fit together"
  request: "Flow diagram with three legs sharing one dictionary file. Leg 1 (write-time): a writing expert calls lazy-wiki.terms mid-document, in lookup mode or check-a-candidate-word mode; the skill reads the dictionary and returns matching definitions, never writes. Leg 2 (curate, git-watch): a document commit triggers the terms-scan routine, which dispatches lazy-wiki.terms-curator in curate mode; the curator reads the changed document plus the dictionary headings, decides add / extend / split per new concept, edits the dictionary, and commits. Leg 3 (audit): the terms section of /lazy-wiki.doctor checks format and scope configuration by reading, then dispatches lazy-wiki.terms-curator in report mode for meaning checks (divergence, missing, duplicate, dead); doctor presents each finding to the operator one at a time via AskUserQuestion and applies only what they choose. Show all three legs converging on the one dictionary file, and that report mode writes nothing itself."
  kind_hint: flow
source_skills:
  - lazy-wiki.terms
  - lazy-wiki.terms-curator
  - lazy-wiki.doctor
source_sha: e758792cb8f978c3f3e230b8233d46a2da076903
---
# Terms

A wiki scope can carry a terms dictionary — one markdown file where every `## <term>` heading is a concept the project has agreed a name for, and the body under it is the definition. The point is narrow but easy to lose without tooling: once a second name for the same thing spreads across a handful of documents, nobody can un-write it. This block is the three pieces that keep that from happening — a lookup a writer consults before coining a word, a curator that grows the dictionary from finished documents, and an audit that catches the drift that slips through anyway.

The three pieces never touch the same file at the same time. `lazy-wiki.terms` only reads the dictionary, mid-document, and never writes to it. `lazy-wiki.terms-curator` is the dictionary's only writer, and it writes only after a document is finished — never the document itself. The terms section of `/lazy-wiki.doctor` writes nothing at all; it surfaces divergences and lets you decide, one at a time, which side is right.

## When you'd use this

- You're writing a document in a scope that has a terms dictionary configured, and you're about to name a concept — you want to know if the project already has a word for it before you pick your own.
- You want the dictionary to grow on its own as documents get written, without a separate step to remember.
- You suspect a document and the dictionary have drifted onto different words for the same thing, or that the dictionary has grown a stale or duplicate entry, and you want that confirmed and fixed.
- You're setting up a new scope and need to decide which documents feed the dictionary and where the dictionary file lives.

## How it fits together

**Lookup, at write time.** `lazy-wiki.terms` is what a writing expert (or you, mid-session) calls before naming something. It resolves which scope's dictionary covers the document being written from `.claude/lazy.settings.json[terms.scopes]`, then runs in one of two modes: look up one term's existing definition, or check a name you're about to use against the headings already taken. In the second mode it greps just the headings first, picks the candidates that plausibly name the same thing, and only then reads those candidates' definitions — the whole dictionary never enters the caller's context. If a candidate really does name your concept, you take the existing word, even when yours reads better; a second name for one thing is exactly what the dictionary exists to prevent. If none do, your word is new and the curator will pick it up later. This skill never edits the dictionary — deciding a term deserves an entry, or that its definition needs widening, is the curator's call once the document is finished, not a mid-sentence decision by whoever is writing.

**Curation, after the fact.** `lazy-wiki.terms-curator` owns the dictionary file and nothing else. When a document under a terms scope changes and the `lazy-wiki.terms-scan-<scope-id>` routine fires, the curator runs in `curate` mode: it reads the changed document, reads the dictionary's headings, and for each concept the document introduces decides whether it's genuinely new (**add**), already named but under-defined for this shade of meaning (**extend** — the existing heading stays, the body widens), or colliding with a name that actually belongs to a neighbouring concept (**split** — a second entry lands under a different name, and both definitions are reworded to name each other, so a future audit can tell a fresh split from an unused term). It writes the dictionary directly — sections sorted by heading, three physical lines per definition at most — and commits. It never edits the document that triggered it.

**Audit, on demand.** The terms section of `/lazy-wiki.doctor` is where drift that slipped past both of the above gets caught. It checks format and scope configuration itself, by reading — a dictionary file that doesn't exist, two scopes' `paths` overlapping, a missing `source_exclude` entry, definitions run past three lines, headings out of sort order. Then, for the judgment calls a program can't make, it dispatches `lazy-wiki.terms-curator` in `report` mode — no job dir this time, just the scope id, the dictionary path, and the scope's globs in the prompt — and gets back `divergence` (a document and the dictionary disagree on the word for one concept), `missing` (a document names a project entity the dictionary doesn't carry), `duplicate` (two entries describe one concept), and `dead` (a term no document in the scope actually uses, excluding a term whose definition names a sibling — that's a fresh split, not a corpse). Report mode writes nothing. Doctor then walks you through each finding individually via `AskUserQuestion`, since which side of a divergence is "right" is your call, not a default — and leaves alone anything under a document with `review_active: true` or inside a mirrored tree, since editing either would fight the process that owns them.

## Common adjustments

- **No terms dictionary configured for a scope yet, or you want to change which documents feed it** — run `/lazy-wiki.configure terms`. It's the wizard for which documents the dictionary serves, where the dictionary file lives, and which documents count as term sources; the skills in this block only read that configuration, they don't write it.
- **`lazy-wiki.terms` says no scope matches your document** — the document's path isn't covered by any scope's `paths` globs in `terms.scopes`, or the `terms` section doesn't exist yet. Run `/lazy-wiki.configure terms` to add or widen a scope.
- **The dictionary file is missing** — none of these skills will create it for you; a silent recreation would hide the loss of every term it used to hold. Run `/lazy-wiki.configure terms` to point the scope at the right file, or restore it from git history yourself.
- **The dictionary isn't picking up new terms automatically** — check that the scope's `lazy-wiki.terms-scan-<scope-id>` routine is registered; `/lazy-wiki.doctor` reports this as a `config` finding, and `/lazy-wiki.install` seeds any routine that's missing (absent-only, so an existing one is left alone).
- **You suspect drift but don't want to wait for the next commit** — run `/lazy-wiki.doctor [<scope-id>]` directly; the terms section runs every time, alongside the rest of the wiki audit.

## How the pieces fit together

<!-- /lazy-diagram.draw lands the fence here; do not author a code block manually. -->

## See also

- [audit](audit.md) — The full `/lazy-wiki.doctor` integrity sweep this block's audit half belongs to, including the checks that aren't about terminology.
- [curation](curation.md) — The sibling curator that classifies and links wiki nodes; a different expert, same one-writer-per-file discipline.
