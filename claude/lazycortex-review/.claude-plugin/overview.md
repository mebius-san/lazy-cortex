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
