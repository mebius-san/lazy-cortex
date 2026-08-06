---
iconize_icon: LiInfo
iconize_color: "#93c5fd"
---
# lazycortex-review

Pure-Python source-side review CLI. Drives mechanical doc-review state machine (parse / approval-marker sync / dispatch); experts run via lazycortex-core's expert runtime queue.

## Why this plugin

Reviewing a long markdown document with multiple expert lenses gets messy fast: who reviewed what, which sections are still pending, what changed between rounds, who left which comment. Doing it by hand in Claude Code means re-pasting the doc, re-running each expert, and re-tracking approval state in your head.

`lazycortex-review` turns one markdown file into a mechanical review state machine. You opt the doc into review, define a class (paths + section assignments + experts), and the source-side CLI walks one round at a time: parse the current state, sync approval markers, dispatch one job per section to the right expert through `lazycortex-core`'s queue, splice the response back, and stop when every section is approved. Final commits, history entries, and round bumps are all the CLI's job — your role is to read suggestions and tick the approve box.

Pure Python — no LLM is in the CLI itself. Experts run as `lazycortex-core` jobs and write their suggestions through the shared protocol. The CLI only orchestrates state.

## Who it's for

- **Spec / RFC authors** who want a multi-pass review (designer reviews structure, developer reviews implementability, security reviews threats) without copy-pasting each pass.
- **Engineering managers** running async doc-review loops — every round is one commit with a structured `Doc-Review-*` trailer, history is auditable.
- **Plugin authors** who need a deterministic mechanical loop around an LLM-backed expert team.

## Scenarios

- *"This RFC needs 3 pairs of eyes — designer, developer, security."* — `/lazy-review.configure` defines a class for `docs/specs/*.md` with three section assignments, then `/lazy-review.start <file>` opts that file in and the daemon dispatches one job per section per round.
- *"Did this section already get approved in round 2?"* — `/lazy-review.status <file>` prints one-line JSON with `review_round`, `approved`, per-section owner, and current banner state.
- *"Reviewer left a broken markdown block."* — the `lazy-review.doc_doctor` agent fires automatically when the doc has malformed frontmatter or structure, before any expert runs.
- *"Round 4 was final — close it out."* — `/lazy-review.finalize` folds every edit-annotation marker into the final text, strips banners and approve checkboxes, removes system callouts (keeps `# History`), and commits with `Doc-Review-Phase: finalize`.

## Blocks

- **review-cycle** — Run a multi-expert document review from opt-in to close-out: start a file, submit pre-authored diffs, check round and per-section status, stop a cycle, and finalize the approved document. Members: lazy-review.start, lazy-review.submit, lazy-review.status, lazy-review.stop, lazy-review.finalize.
- **install-and-audit** — Bootstrap the plugin in a repo, define review classes and their section assignments, and audit the review config. Members: lazy-review.install, lazy-review.configure, lazy-review.audit.

## Walkthroughs

- **run-a-document-review** — Take one document through a full review cycle from opt-in to finalize. Path: lazy-review.start → lazy-review.status → lazy-review.finalize.

## Requirements

- **Claude Code** with plugin support.
- **`lazycortex-core`** installed and configured — the expert runtime, queue, and `lazy.settings.json` schema live there. Hard dependency, declared in `plugin.json`.
- **git** — every review-round transition is one commit; the state machine relies on the commit log for history.
- **Python 3.12+** — the CLI is pure Python and follows the marketplace's tech-stack floor.

## Quick start

1. Install and configure `lazycortex-core` first (`/lazy-core.install`). The expert runtime daemon must be running for review jobs to drain.
2. Run `/lazy-review.install` inside the repo. Seeds `review.classes` / `experts` / `routines` defaults in `lazy.settings.json` and creates `.experts/.jobs/` + `.logs/lazy-review/runs/`.
3. Run `/lazy-review.configure` to define your first review class — paths glob, main/section/final/history writer assignments, edit-marker style.
4. Run `/lazy-review.start <file>` to opt one doc into the loop. The daemon picks it up on the next tick.
5. Read suggestions, tick the approve checkbox per section, repeat. When every section is approved, run `/lazy-review.finalize` to seal the doc.

Day-to-day commands once configured:

```
/lazy-review.start    # opt a doc in
/lazy-review.status   # one-line state
/lazy-review.stop     # opt a doc out (preserves round + history)
/lazy-review.audit    # validate lazy.settings.json review block
/lazy-review.finalize # final round → strip banner, commit, done
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
| `lazy-review.install` | Run when the operator asks to set up document review in this repo, after a lazycortex-review update, or when review skills fail because `lazy.settings.json` has no `review` section, the `.experts/.jobs/` queue is missing, or the scan routine was never registered. Per-repo bootstrap only — wiring the first document class is `/lazy-review.configure`. Idempotent and quiet on re-run. |
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

(`mebius-san` resolves from `.guard-waivers.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-review.doc_doctor` | Dispatched by the lazy-review dispatcher as the repair step when a document in the review loop no longer parses — a missing frontmatter delimiter, an unclosed code fence, an edit-annotation span left open; not for direct use. Repairs structure only, never content, and declares the file irreparable rather than guessing. |
| `lazy-review.historian` | Dispatched by the lazy-review dispatcher once per approved clean state of a reviewed document, to produce that state's `# History` entry; not for direct use. Returns one sentence naming what the document now says that it did not before — never who changed it, never the review process itself. |

## Commands

| Command | Description |
|---|---|
| `lazy-review.help` | Cheatsheet for lazycortex-review — public verbs, install/configure flow, where logs and errors land. The first thing a new consumer should run. |

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
