---
name: lazy-review.start
description: "Use when a markdown document is NOT yet in the review loop and the operator wants it to be — 'put this under review', 'start the review on X', or resuming a document that `/lazy-review.stop` parked. The review opens at the writing round, so the expert chain drafts first; use `/lazy-review.submit` instead when the content is already written and only needs reviewing. No-op on a document already opted in."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Agent
execution-discipline-waiver: "thin dispatcher — work lives in bin/start.py (open_review + atomic git add/commit), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.start

A single, idempotent operation that opens a document for review. The bin script applies the surgical frontmatter set (`review_active: true`, `review_round: 1`, `approved: false`), inserts the Waiting banner, and produces ONE operator commit under the caller's git identity (no `Doc-Review-*` trailer — the dispatcher's next tick sees a human commit and starts the chain).

`# History` is NOT created here. The coordinator seats the section on the wake that opens the loop and writes one line per approved state into it from then on — there is no historian job.

Re-running on an already-opted-in document is a no-op (no commit, exit 0).

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Apply + commit** — `python3 claude/lazycortex-review/bin/start.py <file> [--expert <name>]`. The bin script does the frontmatter edit + banner insertion + `git add` + `git commit` in one subprocess, leaving the working tree clean.
3. **Run-log** — `./.logs/claude/lazy-review.start/<UTC ts>.md`.

## Report

`opted in: <file>` (or `already opted-in: <file>` on the idempotent re-run).
