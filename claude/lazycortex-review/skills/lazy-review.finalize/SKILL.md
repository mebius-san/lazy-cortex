---
name: lazy-review.finalize
description: "Public verb — close out a fully-approved document. Folds all edit-annotation markers into final text, strips the banner and approve checkbox, removes every system callout (keeps # History), sets review_active false, and commits with Doc-Review-Phase: finalize trailer."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
execution-discipline-waiver: "thin dispatcher — work lives in bin/finalize.py (finalize_text + atomic git commit), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.finalize

The finalize-commit is the audit-trail terminator: after it, the document looks like an ordinary markdown file again, with `approved: true` and a `# History` log to prove the lifecycle.

Normally the dispatcher fires this branch automatically once every final writer has confirmed; this skill is the operator's hand-crank for the rare case where they want to close out a doc manually.

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Apply + commit** — `python3 claude/lazycortex-review/bin/finalize.py <file>`. The bin script reads `lazycortex-review.edit_marker_style` from `lazy.settings.json` (default `simple`), folds the markup, strips review-loop scaffolding, sets `review_active: false`, and commits with the `Doc-Review-Phase: finalize` trailer under the bot identity.
3. **Run-log** — `./.logs/claude/lazy-review.finalize/<UTC ts>.md`.

## Report

`finalized: <file> (sha=<short-sha>)` (or `already finalized: <file>` when the file is already in finalized shape).
