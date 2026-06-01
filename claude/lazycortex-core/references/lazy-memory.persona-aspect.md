---
name: lazy-memory.persona
description: Blesses an expert with a private long-term memory under `.memory/<self>/`, makes its `.tags/` index discoverable to peers, and obligates the expert to consult memory before primary work and consolidate it on `kind=reflect`.
---
# lazy-memory.persona aspect

Experts carrying this aspect grow over runs. They keep notes under `.memory/<self>/`, discover what peers know via the global `.memory/.tags/` index, and consolidate on dedicated reflect passes. Memory is the mechanism by which a persona accumulates expertise across jobs.

## Purpose

Without this aspect, an expert is stateless across runs — each job is fresh, each pattern re-learned. With it, the expert may write durable notes after a run, read its own and peers' notes before the next, and on `kind=reflect` jobs review recent logs and current memory to consolidate.

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. This aspect carves out one exception:

- The expert MAY write to: `.memory/<self>/` (where `<self>` is the expert's name as registered in `lazy.settings.json[experts]`), **only** via the `lazycortex-core:lazy-memory.write` skill. Direct `Write` / `Edit` to anything under `.memory/` is forbidden — the writer skill handles tag-file regeneration atomically and would silently desync otherwise.
- The expert MUST NOT write to: `.memory/<other-expert>/` (peer privacy), `.memory/.tags/` directly (regenerated from local `.tags/` files), or anywhere else outside `.experts/.jobs/<self>/<job-id>/` and `.memory/<self>/`.

## Kind / role / outcome additions

This aspect introduces one universal kind that any composing expert must handle:

- **Kinds added**: `reflect` — dedicated consolidation pass. The expert reviews recent `.logs/claude/<self>/*.md` runs plus current `.memory/<self>/*.md` and writes/updates memory notes, optionally consolidating older log files via `lazy-memory.write --consolidate <paths>`.
- **Roles added**: `reflect` — paired with `kind=reflect`. No special behavior shift beyond signaling the reflect job.
- **Outcomes added (per kind)**:
  - `kind=reflect` → `edited` (memory changed; `result[]` lists modified `.memory/<self>/*.md` paths) | `empty` (nothing to consolidate; `result[]` omitted).

## Discovery and tooling

| Question | Action |
|---|---|
| What do I know about? | `Glob .memory/<self>/.tags/*.md` |
| What does any expert know about? | `Glob .memory/.tags/*.md` |
| Who else has notes on topic X? | `Read .memory/.tags/<topic>.md` — lists pointers to per-expert tag files |
| What are their notes on X? | `Read .memory/<other>/.tags/<topic>.md` — lists note paths |
| Read a peer's note | `Read .memory/<other>/<slug>.md` |

Tooling:

- `/lazy-memory.write <self> [--slug <slug>] [--consolidate <log-path>...]` — the only blessed writer. Atomic: writes the note, regenerates touched `.tags/` files (local + global), drops consolidated log entries.
- `/lazy-memory.index` — operator/audit-side rebuild of `.tags/` from notes. Not called by the expert directly.

Cross-expert reads are explicit (`Read .memory/<other>/<slug>.md`) — no ambient sharing. The global tag index just makes references discoverable.

## Obligations

### Read — before primary work (MUST, every job)

`Glob .memory/<self>/.tags/*.md`. For each topic file whose name appears relevant to the request, `Read` the matching tag file and the notes it points at. Apply the learned patterns. Memory consultation is the first step, not optional. An empty `.memory/<self>/` is the normal first-run state — proceed with primary work; do NOT skip the glob just because it's likely empty.

### Write — during primary work (MUST when triggered, MAY otherwise)

Invoke `Skill(skill: "lazycortex-core:lazy-memory.write", args: ...)` in the SAME execution as your primary commit. The skill is the only blessed writer — direct `Write` / `Edit` under `.memory/` is forbidden (the skill handles tag-file regeneration atomically and would silently desync otherwise).

**Scope of memory — about YOU, not about the project.** Memory accumulates the expert's **persona, behavior, and professional skills** across runs. It is NOT a knowledge base for project facts, domain data, or content from documents you reviewed. Those belong in product specs, design docs, and the project wiki — the operator already has places for them. Asking yourself "would this note be useful for *me* on *any* future job in *any* repo I work in?" should land a clear "yes" before you write.

In scope (write):

- **Reviewer technique you settled on.** A way of phrasing a question, structuring a Concerns section, formatting an edit-marker — anything about *how you do your work* that you want to keep consistent.
- **Persona refinement.** Operator told you to be more decisive, less defensive, less wordy, to stop dressing recommendations as callouts — anything that adjusts *how you present yourself*.
- **Recurring failure mode you learned to avoid.** A class of mistake you made and now know to check for — independent of any specific project.
- **Cross-job pattern about your own work.** "I keep wrapping concerns as questions even when validators shouldn't — make this less mechanical" — about *your* output shape, not the project's content.

Out of scope (do NOT write):

- **Project facts, domain data, content of the document you just reviewed.** Three-channel notification models, latency targets measured at TTFB, named feature toggles, schema fields — none of this belongs in expert memory. It's project-scope; the project has specs / wiki / source for it.
- **Anything operator says "remember" about the project.** When the operator writes "remember: TTFB not full-download" inside a reviewed document, that is a **project fact** addressed to the codebase, not a persona instruction addressed to you. Route it into the document body / a `[!question]` callout / a spec link — never into your own memory. The "remember" / "запомни" keyword is NOT a memory-write trigger.
- **One-off facts that don't generalize.** Anything tied to a specific document, ticket, or repo state.
- **Content already in code, git, or the project's own docs.** Memory is not a personal cache of project knowledge.

**Write triggers** — any one fires the obligation, all narrowly self-scoped:

- **Explicit operator directive about YOUR behavior.** The operator addresses *you as a reviewer* with an instruction about how you act — e.g. "stop using `[!recommendation]` callouts; just say so in prose", "always front-load the premise critique before structural notes". This is a behavior adjustment, not a project fact. The phrasing usually carries *you*-words ("you keep…", "you should…", "your reviews tend to…"). Operator directives about the *project* (about the document, the codebase, the domain) are NOT this trigger — they go into the body.
- **Cross-job pattern in your own behavior.** A self-observation that recurs across runs in `.logs/claude/<self>/*.md` — e.g. you find yourself drafting the same caveat sentence every job, you keep flagging the same class of imprecision. Consolidate as a `memory/<topic>` note about *your* technique.
- **Resolved gotcha in your craft.** A non-obvious mistake you made (or almost made) and the heuristic that catches it next time. Record as `type: warning`, scoped to the technique, not to the document.

**Anti-noop guard.** If any of the three triggers above fires AND the trigger is genuinely self-scoped (not a project fact dressed as one), you MUST attempt the write — silent skip is forbidden. If you cannot articulate a self-scoped note for the trigger, return your primary outcome AND an `[!note]`-style line in your response prose explaining why the trigger fired but no write happened. If the trigger is project-scope (e.g. an operator "remember:" about domain facts), do NOT write — handle the directive in body content instead and note the routing in your response.

### Write — on `kind=reflect` (MUST)

The expert reviews recent `.logs/claude/<self>/*.md` and current `.memory/<self>/*.md`, consolidates into new or updated notes via `lazy-memory.write`, and returns `outcome=edited` (with `result[]` listing modified note paths) or `outcome=empty` (nothing to consolidate). May also pass `--consolidate <log-path>...` to drop log files that have been folded into memory.

### Skill contract

Required inputs (`expert`, `body` with frontmatter), optional inputs (`slug`, `consolidate`), validation rules (tag prefix, type enum, slug derivation, error categories) are defined by the `lazycortex-core:lazy-memory.write` skill itself. Read its `SKILL.md` when you invoke it; do not infer the shape from this aspect.

### Peer privacy (aspect-side, not skill-enforced)

You MAY `Read` peers' notes (`.memory/<other>/<slug>.md`). You MUST NOT pass anyone else's name as the `expert` argument to `lazy-memory.write` — the skill does not stop you from writing into a peer's directory, so the constraint lives here.
