---
iconize_icon: LiInfo
iconize_color: "#fca5a5"
---
# lazycortex-review

Coordinator-driven markdown document review loop: a closed set of Python primitive verbs (parse-note / set-key / paint-banner / collect-job), an LLM coordinator that owns every decision from a prose playbook, and a git-watch wake plus an interval postman that carry commits and finished expert jobs back into the loop.

## Why this plugin

Reviewing a long markdown document with several expert lenses gets messy fast: whose turn it is, which sections are still pending, what an approve should do to the body, what to do when the file comes back half-broken. Doing it by hand in Claude Code means re-pasting the doc, re-running each expert, and re-tracking approval state in your head.

`lazycortex-review` puts one markdown file into an unattended review loop. You opt the doc in, define a class (paths + expert chain + section assignments), and from then on every decision belongs to `review.coordinator` — an LLM persona that wakes on a commit, reads the document and its own prose playbook, and makes the single move that wake calls for. It acts only through a closed set of Python verbs: `parse-note` reads the structure, `set-key` is the one door into frontmatter, `paint-banner` repaints the gesture banner, `collect-job` lands a finished expert payload. There is no state machine and no dispatcher — a new edge case is a new paragraph in the playbook, not a code change.

The split is deliberate: judgement in prose, mechanics in Python. The verbs never decide anything, and the coordinator never hand-edits the markup a verb owns.

## Who it's for

- **Spec / RFC authors** who want a multi-pass review (a designer reads structure, a developer reads implementability, a security lens reads threats) without copy-pasting each pass.
- **Engineering managers** running async doc-review loops — every transition is one commit, and the document carries its own state in frontmatter.
- **Plugin authors** who need a document to travel a review loop and come out with a machine-readable verdict a downstream routine can act on.

## How the loop turns

Nothing polls the document. The coordinator wakes on exactly five triggers, resolved by the `lazy-review.coordinator-watch` git-watch routine from the commit that just landed: a commit turning `review_active` true (review entry, from any author — another plugin's bot opening a doc counts), an expert job's payload landing (the postman raises the wake in the runtime marker sidecar), a commit by an identity outside the review system's own (an operator edit), a non-empty `> [!todo] #review/command` callout, and a ticked option under a `[!question] #review/question` callout.

The second routine, `lazy-review.collect`, is the postman: on its own interval it sweeps finished expert jobs, lands each payload into its target document, clears the runtime `active_job` marker while raising the job-done wake in its place, and commits the batch. That commit is what carries the job-done wake back to the coordinator. It carries no scheduling judgement of its own — a dead or empty job is left exactly as found for the coordinator to decide about.

## Scenarios

- *"This RFC needs three pairs of eyes — designer, developer, security."* — `/lazy-review.configure` defines a class for `docs/specs/*.md` with three writers, then `/lazy-review.start <file>` opts the file in; the entry commit wakes the coordinator and the first writer round is dispatched.
- *"What state is this document in?"* — `/lazy-review.status <file>` prints one-line JSON with the round, the approval flags, the per-section owners, and the current banner state.
- *"The reviewer left a broken markdown block."* — the coordinator dispatches the `lazy-review.doc_doctor` agent for mechanical damage; for anything it cannot repair with confidence it writes a `[!question]` with concrete options instead of guessing.
- *"Redo the last round against my rewrite."* — drop the instruction into a `> [!todo] #review/command` callout. The coordinator unfolds it into a numbered mini-plan in the same callout, works through it, and files the finished block into `# History`.
- *"Round four was final — close it out."* — `/lazy-review.finalize` folds every edit-annotation marker into the final text, strips the banner, gesture checkboxes, and system callouts, and stamps `review_result` so a downstream apply gate can read the verdict.

## Blocks

- **review-cycle** — Run a multi-expert document review from opt-in to close-out: start a file, submit pre-authored content, check state, stop a cycle, and finalize the approved document. Members: lazy-review.start, lazy-review.submit, lazy-review.status, lazy-review.stop, lazy-review.finalize.
- **install-and-audit** — Bootstrap the plugin in a repo, define review classes and their expert chains, and audit the review config. Members: lazy-review.install, lazy-review.configure, lazy-review.audit.

## Walkthroughs

- **run-a-document-review** — Take one document through a full review cycle from opt-in to finalize. Path: lazy-review.start → lazy-review.status → lazy-review.finalize.

## Requirements

- **Claude Code** with plugin support.
- **`lazycortex-core`** installed and configured — the expert runtime, the job queue, the routine daemon, and the `lazy.settings.json` schema all live there. Hard dependency, declared in `plugin.json`.
- **A running core daemon** — both routines are daemon-driven; with the daemon off the loop never wakes.
- **git** — every transition is one commit, and a commit is how each wake reaches the coordinator.
- **Python 3.12+** — the verbs are pure Python and follow the marketplace's tech-stack floor.

## Quick start

1. Install and configure `lazycortex-core` first (`/lazy-core.install`), and make sure its runtime daemon is running.
2. Run `/lazy-review.install` inside the repo. Seeds the `review` settings block, the coordinator's own expert identity, and the `lazy-review.collect` + `lazy-review.coordinator-watch` routine pair; creates `.experts/.jobs/` and the log tree; installs the review callout styling into the vault when there is one.
3. Run `/lazy-review.configure` to define your first review class — the paths glob, the main-writer chain, any validation or terminal section owners, and the edit-marker style.
4. Run `/lazy-review.start <file>` to opt one doc in. The entry commit wakes the coordinator on the next watch tick.
5. Read what the writers propose, answer questions by ticking an option, tick approve when the document is right. When the post-approve barriers have run, `/lazy-review.finalize` seals it.

Day-to-day commands once configured:

```
/lazy-review.start    # opt a doc in (opens at the writing round)
/lazy-review.submit   # opt a doc in whose content is already written
/lazy-review.status   # one-line state
/lazy-review.stop     # opt a doc out (preserves round + history)
/lazy-review.audit    # validate the review block in lazy.settings.json
/lazy-review.finalize # strip the review markup, stamp the verdict, commit
```

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-review.audit` | Run when the operator asks whether the review setup is sane, or when review misbehaves in a way that smells like config — a document never enters the loop, a class points at an expert that was never registered, commits land under the wrong identity. Read-only check of the `review` section in `.claude/lazy.settings.json`; reports PASS/WARN/FAIL and never writes — fixes come from `/lazy-review.configure` or `/lazy-review.install`. |
| `lazy-review.configure` | Run when the operator wants a new kind of document to go through review, wants to change which paths a review class matches, or wants to reassign who writes / validates / closes out / narrates it. Wizard over `review.classes` in `.claude/lazy.settings.json`, one question per turn via AskUserQuestion; read-first, so an already-configured class is re-validated without a single prompt. Requires `/lazy-review.install` to have run. |
| `lazy-review.finalize` | Use when a document is already approved but still looks like a review artefact — banner, approve checkbox, edit markers, system callouts — and the operator wants it closed out by hand: 'finalize this', 'clean up the review markup', or the dispatcher's automatic finalize never fired. Leaves an ordinary markdown file with `approved: true` and its `# History`. Not for an unapproved doc — that is `/lazy-review.stop`. |
| `lazy-review.install` | Run when the operator asks to set up document review in this repo, after a lazycortex-review update, or when review skills fail because `lazy.settings.json` has no `review` section, the `.experts/.jobs/` queue is missing, or the coordinator routines were never registered. Per-repo bootstrap only — wiring the first document class is `/lazy-review.configure`. Idempotent and quiet on re-run. |
| `lazy-review.start` | Use when a markdown document is NOT yet in the review loop and the operator wants it to be — 'put this under review', 'start the review on X', or resuming a document that `/lazy-review.stop` parked. The review opens at the writing round, so the expert chain drafts first; use `/lazy-review.submit` instead when the content is already written and only needs reviewing. No-op on a document already opted in. |
| `lazy-review.status` | Use when the operator asks where a document stands in the review — is it still active, which round it is on, whether it is approved, what the banner is currently waiting for, which expert owns which section. Also the cheap way to check state before deciding between `/lazy-review.start`, `/lazy-review.stop`, and `/lazy-review.finalize`. Read-only; emits one line of JSON. |
| `lazy-review.stop` | Use when a document is currently in the review loop and the operator wants the experts to stop touching it before it is approved — 'pause the review', 'take this out of review for now', or when a doc is churning and needs to be parked. Round, approval flag and `# History` survive, so `/lazy-review.start` resumes where it left off; for a document that IS approved and just needs closing out, use `/lazy-review.finalize`. |
| `lazy-review.submit` | Use when a document is NOT yet in the review loop, its content is already written, and the operator wants it reviewed rather than drafted — 'submit this for review', 'I've made the edits, get it reviewed'. Skips the opening writer round and lands straight on a reviewer; use `/lazy-review.start` instead when the experts should write the document first. `--expert <name>` pins a per-document main-writer override. No-op on a document already opted in. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/install-and-audit.md) — Bootstrap lazycortex-review in a repo, define document review classes, and validate configuration with a read-only audit.
- [review-cycle](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/review-cycle.md) — Control the full lifecycle of a document under review — opt in, track state, pause, and seal the result in one auditable commit chain.
- [run-a-document-review](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/walkthroughs/run-a-document-review.md) — Take one document through a full review cycle from opt-in to finalize.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/troubleshooting.md) — Common failure modes across lazycortex-review skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/faq.md) — Answers to common questions about installing, configuring, and running the lazycortex-review document-review loop.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-review.coordinator` | Dispatched on any of the coordinator's four wake triggers: a commit turning `review_active` true (review entry, from any author including another plugin's bot), the postman landing an expert payload on a document under review (job-done), a commit by an identity outside the review system's own (operator edit, including a ticked option under a `[!question] #review/question` callout), or a non-empty `[!todo] #review/command` callout — not for direct use. Owns the review loop of one document in full: reads the rule layers and the document's structural report, decides the one move this wake calls for, acts only through the closed primitive-verb set, and leaves the banner repainted. |
| `lazy-review.doc_doctor` | Dispatched by the review.coordinator as the repair step when a document in the review loop no longer parses — a missing frontmatter delimiter, an unclosed code fence, an edit-annotation span left open; not for direct use. Repairs structure only, never content, and declares the file irreparable rather than guessing. |

## Commands

| Command | Description |
|---|---|
| `lazy-review.help` | Run when the operator asks what lazycortex-review does, how a document gets into or out of the unattended review loop, or where its state and logs land — lists the review loop's surface: the start / submit / stop / status / finalize verbs, the install → configure → audit setup order, the two routines that wake the coordinator, and the job-queue and log paths. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-review@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-review:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-review.audit
/lazy-review.configure
/lazy-review.finalize
/lazy-review.install
/lazy-review.start
/lazy-review.status
/lazy-review.stop
/lazy-review.submit
```
