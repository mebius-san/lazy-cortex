---
chapter_type: block
summary: Query a generated reference tree built from code's Domain(…) comments — one section or one term at a time, never the whole tree.
last_regen: 2026-08-19
diagram_spec:
  anchor: "How the domain tree stays current"
  request: "Flow diagram: code Domain(…)/Contract: comments feed domain-plan detection, which dispatches the domain-spec writer per changed group to (re)write docs/domains/<group>.md, then rebuilds the domains.md index; /lazy-wiki.domains reads that generated tree to answer group and term queries."
  kind_hint: flow
source_skills:
  - lazy-wiki.domains
  - lazy-wiki.domain-sync
  - lazy-wiki.domain-spec-writer
source_sha: c301465a877136aa8d703e42c792fceacbe77b87
---
# Domain knowledge lookup

Some codebases carry their design knowledge in comments — a `Domain(…)` block explaining a mechanic, a formula, an invariant, sitting next to the code it describes. That knowledge is useless to anyone who has to read the whole codebase to find it. This block turns those comments into a small generated reference tree (`docs/domains/` by default) and gives you a query skill that hands back one section of one group's doc, or every excerpt matching a term — never the whole tree, never a whole doc you didn't ask for.

The tree itself is generated, not hand-written: a synthesising agent reads each group's `Domain(…)` blocks, verifies every formula and rule against the actual code, and writes a whole document per group with fixed Terms / Principles / Mechanics sections (plus a Contracts section when the group has attributed `Contract:` guarantees). You never edit those files directly — you either query them or trigger a regeneration.

## When you'd use this

- Looking up what a term means, or how a mechanic works, without reading the implementation.
- Checking a formula or invariant before changing code that depends on it.
- Getting an overview of a domain group — its terms, its principles, its guarantees — before diving into a bigger task.
- Refreshing the generated docs right after `Domain(…)` markers changed, when you're not waiting for the background routines.

## How it fits together

You ask `/lazy-wiki.domains group <group-key> [<section>]` for one group's doc, or `/lazy-wiki.domains term "<text>"` to search the whole tree for a term. A group query with no section returns the doc's overview paragraph plus the list of sections actually present, so you can narrow a follow-up query; naming a section (`Terms`, `Principles`, `Mechanics`, or `Contracts` when present) returns just that block. A term query greps every generated doc case-insensitively and returns the matching excerpts with their file paths — never a full file. Both modes assume the tree already exists; if it doesn't, the skill tells you to run `/lazy-wiki.configure domains` (first-time setup) and `/lazy-wiki.domain-sync` (to generate it) before it can answer anything.

The tree behind those queries is generated, not maintained by hand. When your project runs the background daemon, a git-watch routine and a weekly full sweep keep it current automatically as `Domain(…)` and `Contract:` comments change — you don't have to do anything. When you're not running the daemon, or you just changed a batch of markers and want the docs current right now, `/lazy-wiki.domain-sync` does the same work synchronously: it detects which groups changed since the last generation, dispatches the domain-spec writer once per changed group, deletes docs for groups that no longer have code behind them, rebuilds the `domains.md` index, and commits everything in one step.

The domain-spec writer is the piece that actually produces a doc. For each group it reads every source file its `Domain(…)` blocks name, verifies the formulas and rules against the real implementation, and writes the group's document as a synthesised story — not a block-by-block transcript — with formulas recorded as proper math notation. It never mentions file paths or symbol names in that prose; the one exception is the Contracts section, where each guarantee is anchored back to `path:symbol` so you can jump to the code the guarantee governs. If the group carries no `Contract:` blocks, that section is left out entirely rather than padded with a placeholder.

Source comments stay English regardless of the project's documentation language — the writer translates them into the target language you configured (via `/lazy-wiki.configure domains`) when it composes each doc, favouring a term the project has already agreed on over a literal rendering.

## Common adjustments

- **First-time setup** — run `/lazy-wiki.configure domains` to point the plugin at your code globs, dictionary, output directory, and target language; nothing works until this is done.
- **Forcing an immediate refresh** — run `/lazy-wiki.domain-sync` instead of waiting for the background routines, e.g. right after a batch of `Domain(…)` edits or a terminology sweep.
- **A group reports "not in the domain tree"** — the group key is new, misspelled, or not yet generated; check the group list `/lazy-wiki.domains group` returns for a doc, or the `domains.md` index directly.
- **New groups show up as "unknown"** during a sync — the dictionary doesn't list them yet. Add the group to the dictionary via `/lazy-wiki.configure domains`, or run a knowledge sweep to have code markers refiled under accepted groups automatically.

## How the domain tree stays current

## See also

- [install-and-audit](install-and-audit.md) — bootstrap the plugin before configuring domain generation.
