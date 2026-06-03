---
description: Cheatsheet for lazycortex-review — public verbs, install/configure flow, where logs and errors land. The first thing a new consumer should run.
logging-waiver: "static text — no executable steps"
---
# /lazy-review.help

`lazycortex-review` is the doc-review dispatcher. It runs unattended, finds documents marked for review (`review_active: true` in frontmatter), routes each to the configured specialists round-by-round, and commits their proposals.

## Public verbs

- `/lazy-review.start <file> [--expert <name>]` — opt the doc into review.
- `/lazy-review.submit <file> [--expert <name>]` — opt the doc into review skipping the opening writer round, landing straight on a reviewer.
- `/lazy-review.stop <file>` — opt out.
- `/lazy-review.status <file>` — print state JSON.
- `/lazy-review.finalize <file>` — set `approved: true` and Form C; next scan finalizes.

## Setup flow (per repo)

1. `/lazy-review.install` — write skeleton config and dirs.
2. `/lazy-review.configure` — wizard: classes, executors, triggers.
3. `/lazy-review.audit` — verify everything is reachable.

## Where things land

- Per-run logs: `.logs/claude/lazy-review.{dispatcher,process-file}/<ts>.md`.
- Errors stream: `.logs/lazy-review/errors.jsonl` (gitignored; tail with Prometheus / Loki).
- Lock file: `.lazycortex-review/scan.lock`.
- Dispatch contract: `claude/lazycortex-review/references/lazy-review.doc-review-protocol.md`.
