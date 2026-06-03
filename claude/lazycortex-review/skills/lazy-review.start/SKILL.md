---
name: lazy-review.start
description: "Public verb — opt one document into the review loop. Atomically writes review_active/review_round/approved frontmatter, drops the Waiting banner above the first H1, and commits under the operator's git identity. # History is NOT created here — historian adds it lazily on first entry."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
execution-discipline-waiver: "thin dispatcher — work lives in bin/start.py (open_review + atomic git add/commit), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.start

A single, idempotent operation that opens a document for review. The bin script applies the surgical frontmatter set (`review_active: true`, `review_round: 1`, `approved: false`), inserts the Waiting banner, and produces ONE operator commit under the caller's git identity (no `Doc-Review-*` trailer — the dispatcher's next tick sees a human commit and starts the chain).

`# History` is NOT created here. The historian writes the section lazily on its first entry (`history.append_entry` calls `ensure_history_section`).

Re-running on an already-opted-in document is a no-op (no commit, exit 0).

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Apply + commit** — `python3 claude/lazycortex-review/bin/start.py <file> [--expert <name>]`. The bin script does the frontmatter edit + banner insertion + `git add` + `git commit` in one subprocess, leaving the working tree clean.
3. **Run-log** — `./.logs/claude/lazy-review.start/<UTC ts>.md`.

## Report

`opted in: <file>` (or `already opted-in: <file>` on the idempotent re-run).
