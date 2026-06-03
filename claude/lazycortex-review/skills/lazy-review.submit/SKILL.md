---
name: lazy-review.submit
description: "Public verb — open one document into the review loop skipping the opening writer round (the diffs are already in the file), landing straight on a reviewer. Atomically writes review_active/review_round/approved frontmatter, pre-seeds the main-writer round as done, drops the Waiting banner above the first H1, and commits under the operator's git identity. Optional --expert pins a per-document main-writer override."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
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
