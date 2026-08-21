---
name: lazy-review.submit
description: "Use when a document is NOT yet in the review loop, its content is already written, and the operator wants it reviewed rather than drafted — 'submit this for review', 'I've made the edits, get it reviewed'. Skips the opening writer round and lands straight on a reviewer; use `/lazy-review.start` instead when the experts should write the document first. `--expert <name>` pins a per-document main-writer override. No-op on a document already opted in."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Agent
execution-discipline-waiver: "thin dispatcher — work lives in bin/submit.py (open_submit + atomic git add/commit), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.submit

A single, idempotent operation that opens a document for review without running the opening main-writer round. The bin script applies the same bootstrap as `start` (`review_active: true`, `review_round: 1`, `approved: false`, Waiting banner), additionally pre-seeds `review_main_done` so the main-pending set is empty on the first tick, and produces ONE operator commit under the caller's git identity (no `Doc-Review-*` trailer). The document lands directly on the operator's Ready banner.

`--expert <name>` (optional) writes a `review_expert` per-document override of the class `experts.main` list, honoured by the dispatcher.

Re-running on an already-opted-in document is a no-op (no commit, exit 0).

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Apply + commit** — `python3 claude/lazycortex-review/bin/submit.py <file> [--expert <name>]`. The bin script does the frontmatter edit + skip-seed + banner insertion + `git add` + `git commit` in one subprocess, leaving the working tree clean.
3. **Run-log** — `./.logs/claude/lazy-review.submit/<UTC ts>.md`.

## Report

`submitted: <file>` (or `already opted-in: <file>` on the idempotent re-run).
