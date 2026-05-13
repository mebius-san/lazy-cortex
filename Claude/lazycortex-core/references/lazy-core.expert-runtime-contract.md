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

## Where your files live

The user message you receive lists the concrete paths for this job:
the protocol(s), the aspect(s) (zero or more behavior layers your expert
opts into via its entry in `lazy.settings.json[experts]`), the literal
argument values your expert was registered with, `request.json`,
`source/`, `context/`, `result/`, and `response.json`. Use those paths
verbatim — do not look up environment variables. Read every protocol
and aspect before acting.

## Input — `request.json`

Read `request.json` (path given in your user message). Required fields:

- `role` (string) — what kind of work this is.
- Plus any fields your expert-specific protocol declares.

Do not assume fields beyond what your protocol declares. The runtime does not
validate them for you.

## Output — `response.json`

Write `response.json` (path given in your user message):

```json
{
  "outcome": "<protocol-defined-string>" | "error",
  "result":  [...],
  "error":   { "category": "...", "message": "..." }
}
```

- `outcome` is **protocol-defined**: the protocol you implement declares an enum
  of success values (e.g. `edited`, `confirmed`, `empty`, `summarized`). The
  string `"error"` is the only reserved universal value across all protocols
  and signals failure. Do NOT write `"ok"` — that's not in any current
  protocol's enum; consumers either accept the protocol-defined string or
  branch on `"error"`.
- On a success outcome (any protocol-defined value), `result` is the array of
  artifact descriptors per your protocol. Omit when your protocol's outcome
  doesn't carry artifacts (e.g. `confirmed` / `empty`).
- On `outcome: "error"`, `error.category` is one of your protocol's error
  categories. `error.message` is human-readable detail.

Write artifact files into the `result/` directory inside your job dir and
commit them as part of the working-tree step above.

## What you must not touch

- The `DONE` marker inside your job dir — the daemon writes this after you
  exit cleanly.
- Files outside your job dir and your own commits.
- Other experts' job dirs (`.experts/.jobs/<other-expert>/...`).
- Branches other than the daemon's working branch.
- The runtime's state file (`.logs/lazy-core/runtime/state.json`).
