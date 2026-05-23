---
chapter_type: block
summary: Per-expert long-term memory tracked in git — experts consult notes before primary work, write new notes as a side-effect of jobs, and consolidate via reflect passes.
last_regen: 2026-05-23
diagram_spec:
  anchor: "How the four skills compose"
  request: "Flow diagram showing the four memory skills and how they compose: mark-persona opts an expert in (writes lazy.settings.json experts entry); write is the only blessed note writer (writes .memory/<expert>/ notes, regenerates .tags/); reflect dispatches a kind=reflect job that feeds run logs and existing notes to the expert, which then calls write; index rebuilds .tags/ from note frontmatter as a recovery path. Show .memory/<expert>/ and .memory/.tags/ as shared state that write maintains and reflect reads."
source_skills:
  - lazy-memory.write
  - lazy-memory.index
  - lazy-memory.reflect
  - lazy-memory.mark-persona
---
# Expert memory — notes that survive runs

Most experts are stateless across jobs: each dispatch starts fresh, each pattern re-learned. The memory subsystem changes that. An expert opted into memory carries a private notebook at `.memory/<expert>/` that travels with the repo in git. Before every job, the expert consults that notebook. During a job, it may add to it as a side-effect of its work. On a dedicated reflect pass, it reviews recent run logs, finds patterns worth keeping, and consolidates them into durable notes. Teammates can see what any expert has learned and read peer notes on shared topics.

Four skills make this work: one to opt an expert in, one to write notes atomically, one to trigger consolidation, and one to recover if the tag index drifts.

## When you'd use this

- Give a specialist expert (a designer, developer, or reviewer) a persistent rulebook it builds from its own experience running jobs.
- Preserve hard-won patterns — code style decisions, project-specific conventions, recurring failure modes — so the expert doesn't rediscover them on every run.
- Let multiple experts share knowledge on overlapping topics via the global tag index without one expert writing into another's notebook.
- Trigger a reflect pass after a burst of work to compact dozens of run logs into a handful of durable notes, keeping the notebook small and the expert's startup context lean.

## How it fits together

**Opt in first.** Run `/lazy-memory.mark-persona <expert>`. The skill reads `lazy.settings.json`, appends `lazycortex-core:lazy-memory.persona-aspect` to the expert's `aspects[]`, and saves. From the next dispatch onward, the expert's runtime context includes the aspect's obligations — consulting `.memory/<self>/.tags/*.md` before primary work, writing notes only through `/lazy-memory.write`, and handling `kind=reflect` dispatch. The skill is idempotent: re-running on an already-marked expert is a no-op.

**Accumulate on the job.** As the expert runs ordinary jobs, it calls `/lazy-memory.write` to capture a pattern, rule, or fact it wants to remember. Every note body must carry frontmatter with `title`, `tags` (each prefixed `memory/`), `type` (one of `persona`, `rule`, `example`, `warning`, or `fact`), and `summary`. The skill validates these fields, picks a non-colliding slug from the title, writes the note under `.memory/<expert>/`, and regenerates the touched `.tags/` files — both the expert-local `.memory/<expert>/.tags/<topic>.md` and the global `.memory/.tags/<topic>.md` that other experts use for cross-expert discovery. You commit the note and updated tag files yourself (or the expert's job script does it). Only `/lazy-memory.write` may create or overwrite files under `.memory/` — hand-edits bypass validation and leave the tag index stale.

**Consolidate with reflect.** When the expert has accumulated a run log but the notebook feels thin relative to the work done, run `/lazy-memory.reflect <expert>`. The skill confirms the expert is persona-marked, then dispatches a `kind=reflect` job. The job payload includes recent `.logs/claude/<expert>/*.md` run logs (last 30 days by default) and all current `.memory/<expert>/*.md` notes. The runtime daemon picks up the job, the expert reads the material, calls `/lazy-memory.write` one or more times with consolidated insights, and returns `outcome=edited` (notes changed) or `outcome=empty` (nothing new to consolidate). Collect the job with `/lazy-expert.collect-job` and commit the new notes.

**Recover with index.** Under normal operation you never need `/lazy-memory.index` — `/lazy-memory.write` keeps the tag tree in sync atomically. Run it only if hand-edits have drifted the tree: it walks every expert under `.memory/`, recomputes the topic set from note frontmatter, regenerates the local and global `.tags/` trees, and removes stale tag files with no backing note.

**Cross-expert discovery.** The global `.memory/.tags/<topic>.md` file aggregates pointers to every expert's local tag file for that topic. When one expert wants to know what a peer knows about a subject, it reads the global tag file to find who has notes there, reads the relevant peer's local tag file to find the specific note paths, then reads those notes directly. All reads happen inside the expert's own job execution — no expert can write to a peer's notebook.

## Common adjustments

- **Reflect window.** By default `/lazy-memory.reflect` pulls run logs from the last 30 days. Pass `--days <N>` to widen or narrow the window — use a longer window after a period of inactivity, a shorter one for a high-frequency expert that produces many runs per day.

- **Periodic reflect.** Register a subprocess routine via `/lazy-routine.register` that dispatches a reflect job for every persona-marked expert on a cycle. The daemon drains the queue and the notes accumulate without manual intervention.

- **Consolidating log files.** Pass `--consolidate <path>…` to `/lazy-memory.write` when a note supersedes older log entries. The writer deletes those log files atomically with the note write. Only paths under `.logs/` or `.memory/` are accepted — paths outside that scope reject the entire operation.

- **Hierarchical tags.** Tags follow `memory/<topic>` and may nest — `memory/auth/oauth`, `memory/release-process`, and so on. Keep tags consistent across an expert's notes so the tag index stays meaningful.

- **Updating a note's tags.** Remove the old tag from the note's `tags:` frontmatter and re-run `/lazy-memory.write` with the same `--slug` override. The writer regenerates `.tags/` and the now-orphaned entry disappears from both the local and global tag files.

## How the four skills compose

<!-- /lazy-diagram.draw lands the fence here; do not author a code block manually. -->

## See also

- [experts](experts.md) — dispatch jobs to named expert workers; aspects and arguments are configured on the same expert entries the memory skills read.
- [add-memory-to-expert](walkthroughs/add-memory-to-expert.md) — end-to-end walkthrough: opt an existing expert into memory, dispatch jobs to accumulate run logs, then run the first reflect pass.
- [runtime](runtime.md) — register a periodic routine that triggers reflect passes automatically between jobs.
