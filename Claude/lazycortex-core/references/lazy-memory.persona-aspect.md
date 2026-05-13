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

- **Before primary work** on any job: `Glob .memory/<self>/.tags/*.md` and, when topics relevant to the request appear, `Read` the matching tag files and apply learned patterns. Memory consultation is the first step, not optional.
- **During any job**: the expert MAY write memory as a side-effect of primary work — via `lazy-memory.write` only. Memory writes happen in the same execution as the primary commit; they do NOT touch DONE on their own.
- **On `kind=reflect`**: the expert MUST review recent `.logs/claude/<self>/*.md` and current `.memory/<self>/*.md`, consolidate into new or updated notes via `lazy-memory.write`, and return `outcome=edited` (with `result[]` listing modified note paths) or `outcome=empty` (nothing to consolidate).
- **Tag prefix**: every note's frontmatter `tags:` entry MUST be prefixed `memory/` (e.g. `memory/auth`, `memory/release-process`). Unprefixed tags are an audit `FAIL`.
- **Slug discipline**: file names are derived by `lazy-memory.write` from the note's `title`. The expert never picks the on-disk filename directly — pass `--slug` only to override collisions.
