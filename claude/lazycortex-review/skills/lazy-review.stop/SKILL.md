---
name: lazy-review.stop
description: "Public verb — opt one document out of the review loop. Sets review_active false; preserves review_round, approved, and # History so a later /lazy-review.start can resume from the operator's last state."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
execution-discipline-waiver: "thin dispatcher — work lives in bin/stop.py (surgical frontmatter set + atomic commit), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.stop

A single, idempotent operation that takes a document out of the review loop. The bin script flips `review_active: false` (everything else preserved) and commits under the caller's identity. Already-stopped documents are a no-op.

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Apply + commit** — `python3 claude/lazycortex-review/bin/stop.py <file>`. Single subprocess, leaves the working tree clean.
3. **Run-log** — `./.logs/claude/lazy-review.stop/<UTC ts>.md`.

## Report

`stopped: <file>` (or `already stopped: <file>` on re-run).
