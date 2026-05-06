---
version: 1.0.0
description: Universal contract loaded into every expert run by lazycortex-core's expert pump. Read alongside your expert-specific protocol.
---
# Expert Runtime Contract

This document is loaded into every expert run via `--append-system-prompt-file`.
The rules below apply universally on top of your expert-specific protocol.
Read both before acting.

## Working tree

When your work is done, every change you made must be committed. As your last
step, run:

```
git add -A
git commit -m "<expert-name>: <one-line summary>"
```

Do **not** push. Do **not** change branches. Do **not** run `git checkout`,
`git reset`, `git rebase`, or anything else that rewrites history or moves
HEAD. The daemon owns those operations.

If you exit with uncommitted changes in the working tree, the daemon halts the
entire runtime and the operator must run `/lazy-runtime.recover` to restart it.
Your job will be marked `outcome: error, category: uncommitted_changes`.

## Input — `request.json`

Read `request.json` from `$JOB_DIR`. Required fields:

- `role` (string) — what kind of work this is.
- Plus any fields your expert-specific protocol declares.

Do not assume fields beyond what your protocol declares. The runtime does not
validate them for you.

## Output — `response.json`

Write `response.json` to `$JOB_DIR/response.json`:

```json
{
  "outcome": "ok" | "error",
  "result":  [...],
  "error":   { "category": "...", "message": "..." }
}
```

- `outcome: "ok"` — success. `result` is the array of artifact descriptors per
  your protocol.
- `outcome: "error"` — failure. `error.category` is one of your protocol's
  error categories. `error.message` is human-readable detail.

Write artifact files into `$JOB_DIR/result/` and commit them as part of the
working-tree step above.

## What you must not touch

- `$JOB_DIR/DONE` — the daemon writes this after you exit cleanly.
- Files outside `$JOB_DIR` and your own commits.
- Other experts' job dirs (`.experts/.jobs/<other-expert>/...`).
- Branches other than the daemon's working branch.
- The runtime's state file (`.logs/lazy-core/runtime/state.json`).
