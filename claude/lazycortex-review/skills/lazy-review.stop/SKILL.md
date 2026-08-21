---
name: lazy-review.stop
description: "Use when a document is currently in the review loop and the operator wants the experts to stop touching it before it is approved — 'pause the review', 'take this out of review for now', or when a doc is churning and needs to be parked. Round, approval flag and `# History` survive, so `/lazy-review.start` resumes where it left off; for a document that IS approved and just needs closing out, use `/lazy-review.finalize`."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Agent
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
