---
iconize_icon: LiInfo
iconize_color: "#86efac"
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
| `lazy-review.audit` | Read-only validation of lazy-review configuration in .claude/lazy.settings.json — checks schema, expert references, git_author completeness, and edit_marker_style. Returns PASS/WARN/FAIL plus per-finding detail. |
| `lazy-review.configure` | Wizard to add a review class to .claude/lazy.settings.json — collects path globs, main / validation / terminal / history expert assignments under the new experts schema. Strict one-question-per-turn via AskUserQuestion. |
| `lazy-review.finalize` | Public verb — close out a fully-approved document. Folds all edit-annotation markers into final text, strips the banner and approve checkbox, removes every system callout (keeps # History), sets review_active false, and commits with Doc-Review-Phase: finalize trailer. |
| `lazy-review.install` | Per-repo bootstrap for lazycortex-review. Seeds lazy.settings.json with review.classes / experts / routines defaults, creates .experts/.jobs/ and .logs/lazy-review/runs/ directories. Idempotent — re-runnable without overwriting existing config. |
| `lazy-review.start` | Public verb — opt one document into the review loop. Atomically writes review_active/review_round/approved frontmatter, drops the Waiting banner above the first H1, and commits under the operator's git identity. # History is NOT created here — historian adds it lazily on first entry. |
| `lazy-review.status` | Public verb — print one-line JSON describing a document's review state (review_active, review_round, approved, current banner, list of owned sections with their owner experts). Read-only. |
| `lazy-review.stop` | Public verb — opt one document out of the review loop. Sets review_active false; preserves review_round, approved, and # History so a later /lazy-review.start can resume from the operator's last state. |
| `lazy-review.submit` | Public verb — open one document into the review loop skipping the opening writer round (the diffs are already in the file), landing straight on a reviewer. Atomically writes review_active/review_round/approved frontmatter, pre-seeds the main-writer round as done, drops the Waiting banner above the first H1, and commits under the operator's git identity. Optional --expert pins a per-document main-writer override. |

## Agents

| Agent | Description |
|---|---|
| `lazy-review.doc_doctor` | Plugin-shipped repair specialist. Fixes broken frontmatter delimiters, markdown structure, and malformed inline markup so the review can proceed. |
| `lazy-review.historian` | Plugin-shipped history-summary specialist. Diffs the current and prior versions of a reviewed document and produces one substantive sentence summarising what is now in the document that was not there before. Never names actors, never narrates the review process. Never edits the reviewed document. |

## Commands

| Command | Description |
|---|---|
| `lazy-review.help` | Cheatsheet for lazycortex-review — public verbs, install/configure flow, where logs and errors land. The first thing a new consumer should run. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-review@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-review:<skill.name>`.

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
