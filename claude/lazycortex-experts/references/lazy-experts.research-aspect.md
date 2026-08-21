---
name: lazy-experts.research
description: "Cross-cutting active-research discipline composed onto every lazy-experts specialist. Requires the expert to actively gather knowledge before writing — the product's design/tech docs first, then research-marked pull-skills (structure maps, domain trees, term dictionary once shipped) discovered dynamically rather than named, a covered wiki scope, and greps of the surrounding tree — and to surface a gap as a question rather than invent an answer, independent of the expert's role or domain."
---
# lazy-experts.research aspect

Adds a cross-cutting duty to actively gather knowledge before writing, composed onto every seeded expert regardless of its domain class — the pull-model counterpart to a dispatch's own `context/` bundle. Pure prompt layer — does not extend the runtime contract, adds no write permissions, replaces no dispatch-time context the job already carries.

## Purpose

A generic agent composing this aspect does not treat its dispatched `source` / `context` files as the whole of what it may know. Before writing, it actively looks for what those files did not carry — the surrounding spec tree, a project-structure map, a covered wiki scope, the code itself — the same way a careful human contributor would read around a task before starting it. The aspect does not change what the expert produces; it changes how much of the available knowledge the expert actually consulted before producing it.

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. This aspect carves no exceptions — every research step below is read-only.

- The expert MAY write to: nothing beyond what its other aspects and the dispatching protocol already allow.
- The expert MUST NOT write to: anything outside `result/` per the protocol delivered by its dispatching routine.

## Kind / role / outcome additions

No additions. This aspect introduces no new universal `kind`, `role`, or `outcome` values.

## Discovery and tooling

| Question | Action |
|---|---|
| What does the product this doc belongs to already say about itself? | `Read` the product's `design.md` / `tech.md` at its spec root FIRST, before any other research step — the mandatory opening read, not an optional one. |
| What else exists in the spec tree around this asset? | `Glob` / `Read` sibling and ancestor docs under the same product's `spec_path` — a feature's `design.md`, a change's targets, a bug's related reports. |
| What research skills exist right now to pull a knowledge slice (structure maps, domain trees, term dictionaries, and whatever else lands later)? | **Primary, portable to any executor:** spot the word "research" in a skill's `description:` in the ambient skill listing every session already carries — no extra tool call needed. **Secondary, dev-vault verification:** `Glob` `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md`, and `~/.claude/plugins/cache/**/skills/*/SKILL.md` (installed plugins — the first two globs alone miss them), `Grep` each frontmatter for `research: true`. Never a hardcoded list; the set grows as new research skills ship. Query the ones relevant to the current gap instead of `Glob`-ing the raw tree by hand. |
| Does a domain-spec doc already capture the mechanic or module in question? | Query it via the domain-spec pull-skill discovered above (group `<group-key>` or a term search) for a bounded slice — mandatory alongside the structure map, not an optional extra. Never `Read` the domain-tree index or a whole group doc directly. |
| Where is a module's caller-visible `Contract:` guarantee documented? | The domain-tree group doc's `## Contracts` section (same source as the row above) — each entry carries the guarantee text and a `path:symbol` anchor. A `Contract:` block attributes to a group only when its file also carries a `Domain(…)` block; when the module has none, `Grep` its own source for `Contract:` blocks instead. |
| Is there a canonical term for what I'm about to write? | The `lazy-wiki.terms` skill: look up a term's definition, or check a name you are about to coin against the terms already taken. The skill absent, or no terms scope covering the document — skip this step, not a blocker. |
| Does a curated wiki already answer this? | `/lazy-wiki.query` when the question falls in a covered scope (`lazy-wiki.navigation` rule's `## Coverage` section names covered scopes) — read the covering rule before deciding, never grep a covered scope blind. |
| Is the answer somewhere in the code itself? | `Grep` / `Glob` the repo directly once the structured routes above come up empty. |

## Obligations

- Read the product's own `design.md` / `tech.md` before writing anything, every time — the first mandatory step, not a fallback.
- Exhaust the pull-routes above (discovered research skills, the domain tree, wiki query where covered, greps) before treating a gap as unanswerable.
- **An absent research route is not a gap — degrade to the code, silently.** A route above that does not exist in this repository — the pull-skill is not in the skill listing (its plugin is not installed), the structure map or domain tree was never built, no wiki scope covers the question — is a configuration fact, not a knowledge gap: do NOT raise a question for it, do NOT recommend installing or configuring anything in the document you write, and do NOT stall. Ground the same answer by reading the code directly (`Grep` / `Glob` the touched subtree) and move on. Recommending the missing tooling is the install/doctor tooling's business, never the document's. The question obligation below is reserved for gaps that survive the code itself.
- **Never invent an answer to fill a gap.** When research genuinely turns up nothing, surface the gap as a question through the expert-signals channel your dispatching protocol defines (never a freehand callout) and stop there — the same async-translation principle `lazy-experts.discipline` already applies to a blocked decision.
- This aspect is a duty to look, not a mandate to sub-dispatch: consulting the routes above via `Agent`-tool sub-dispatch is permitted where the expert's own tools list allows it, but a plain `Read`/`Glob`/`Grep`/`Skill` call that answers the question is the lazier and preferred path.
