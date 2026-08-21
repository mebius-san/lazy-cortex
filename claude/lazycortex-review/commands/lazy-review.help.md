---
description: "Run when the operator asks what lazycortex-review does, how a document gets into or out of the unattended review loop, or where its state and logs land — lists the review loop's surface: the start / submit / stop / status / finalize verbs, the install → configure → audit setup order, the two routines that wake the coordinator, and the job-queue and log paths."
logging-waiver: "static text — no executable steps"
---
# /lazy-review.help

`lazycortex-review` runs an unattended review loop over documents marked `review_active: true` in frontmatter. Decisions belong to the `review.coordinator` agent, which wakes on a commit, reads its playbook, and acts through a closed set of Python verbs; the verbs do the mechanics and decide nothing.

## Public verbs

- `/lazy-review.start <file> [--expert <name>]` — opt the doc into review.
- `/lazy-review.submit <file> [--expert <name>]` — opt the doc into review skipping the opening writer round, landing straight on a reviewer.
- `/lazy-review.stop <file>` — opt out.
- `/lazy-review.status <file>` — print state JSON.
- `/lazy-review.finalize <file>` — strip the review markup and stamp the `review_result` verdict.

## Setup flow (per repo)

1. `/lazy-review.install` — write skeleton config, routines, and dirs.
2. `/lazy-review.configure` — wizard: classes, expert chains, section owners, marker style.
3. `/lazy-review.audit` — verify everything is reachable.

## What runs unattended

- `lazy-review.coordinator-watch` — git-watch routine; turns a commit on an opted-in document into one coordinator wake.
- `lazy-review.collect` — interval routine; lands finished expert payloads, clears the runtime job marker, raises the job-done wake, commits the batch.

Both need the `lazycortex-core` runtime daemon; with the daemon off, nothing wakes.

## Where things land

- Job queue: `.experts/.jobs/<expert>/<job_id>/` (request, response, and the terminal `DONE` / `DEAD` marker).
- Per-run logs: `.logs/lazy-review/runs/`.
- Failures: the `lazycortex-core` error registry — read it with `lazycortex-core error-list`.
- Expert wire contract: `references/lazy-review.doc-review-protocol.md`; the coordinator's own law: `references/lazy-review.coordination-playbook.md`.

<!-- help-block:start -->
**Documentation:**

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/install-and-audit.md) — Bootstrap lazycortex-review in a repo, define document review classes, and validate configuration with a read-only audit.
- [review-cycle](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/review-cycle.md) — Control the full lifecycle of a document under review — opt in, track state, pause, and seal the result in one auditable commit chain.
- [run-a-document-review](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/walkthroughs/run-a-document-review.md) — Take one document through a full review cycle from opt-in to finalize.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/troubleshooting.md) — Common failure modes across lazycortex-review skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-review/help/faq.md) — Answers to common questions about installing, configuring, and running the lazycortex-review document-review loop.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-review/help/`.
<!-- help-block:end -->
