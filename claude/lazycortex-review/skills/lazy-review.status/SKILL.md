---
name: lazy-review.status
description: "Public verb — print one-line JSON describing a document's review state (review_active, review_round, approved, current banner, list of owned sections with their owner experts). Read-only."
allowed-tools: Read, Bash(python3 *)
logging-waiver: "read-only status query — single read, no mutation, no decision"
execution-discipline-waiver: "thin dispatcher — work lives in bin/status.py (parser + frontmatter + banner introspection), this SKILL.md is a single subprocess call with no decision logic"
---
# lazy-review.status

Operator's quick-look at one document's review state. Always read-only.

## Steps

1. **Resolve the file** — argument is the markdown path.
2. **Read + emit** — `python3 claude/lazycortex-review/bin/status.py <file>`. Output is JSON on stdout: `{file, review_active, review_round, approved, banner, owners[]}`.

## Report

The JSON itself is the report.
