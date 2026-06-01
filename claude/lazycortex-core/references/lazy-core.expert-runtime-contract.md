---
version: 1.1.0
description: Universal contract loaded into every expert run by lazycortex-core's expert pump. Read alongside your expert-specific protocol.
---
# Expert Runtime Contract

This document is loaded into every expert run via `--append-system-prompt-file`. The rules below apply universally on top of your expert-specific protocol. Read both before acting.

## Working tree

Your committable work is **mutations to tracked files in the worktree** — the review/request document at the path given in your request, sibling docs your protocol authorises you to touch, and tracked config the protocol explicitly names. Nothing else.

If — and only if — you mutated such tracked files, commit at the end:

```
git add -A
git commit -m "<expert-name>: <one-line summary>"
```

`git add -A` respects `.gitignore` and will skip your job dir automatically. That is intentional — see below.

**Never commit anything under your own job dir.** Your job dir (`.experts/.jobs/<expert>/<job-id>/` — `response.json`, `result/*`, `transcript.jsonl`, `request.json`, `source/`, `context/`, `PID`, `attempts`, …) is runtime scratch space. It is gitignored. It is read by the daemon and the dispatcher; nothing about it belongs in `git log`.

- If a bare `git add <path>` complains `paths are ignored by one of your .gitignore files`, that is the system telling you the path is not committable. **Do not retry with `-f`.** Stop and exit cleanly.
- Do not use `git add -f` for any path, ever. The flag exists to bypass `.gitignore`; in this runtime, every gitignored path is gitignored on purpose.

**If you produced no tracked-file mutations, exit with a clean tree.** Do NOT make a commit "to signal completion". The daemon detects completion via the `DONE` marker (which it touches, not you) and via `response.json` (which is gitignored — see above). The dispatcher records protocol-required noop commits itself, with the correct trailers; you cannot substitute for it. Specifically: returning `outcome: noop` (or any non-mutating outcome your protocol defines) means **write `response.json` and exit, no commit at all**.

Do **not** push. Do **not** change branches. Do **not** run `git checkout`, `git reset`, `git rebase`, or anything else that rewrites history or moves HEAD. The daemon owns those operations.

**Sub-skills count as your writes.** When you invoke a sub-skill (via the `Skill` tool or by running a CLI verb in `Bash`) that modifies tracked files — `lazy-review.start`, `spec.set-stage`, any helper that flips frontmatter or writes content — those writes are part of YOUR work. Two ways to keep the tree clean:

1. **Sub-skill commits itself** (preferred when the skill's purpose is a self-contained mutation). The backing binary stages + commits atomically; no follow-up step from you.
2. **You wrap the sub-skill in your own final commit**. Invoke the skill, then run `git add -A && git commit` once at the end of your job to sweep up anything the sub-skill left dirty.

A sub-skill that writes to disk and leaves `git status --porcelain` non-empty after the skill returns is a contract violation against THIS contract — fix the sub-skill (option 1) rather than relying on option 2 as the permanent solution.

Before exiting, your final `git status --porcelain` MUST be empty. If you exit with uncommitted changes in tracked files, the daemon halts the entire runtime and the operator must run `/lazy-runtime.recover` to restart it. Your job will be marked `outcome: error, category: uncommitted_changes`. (Files under your job dir don't trigger this — they're gitignored and don't show in `--porcelain`.)

## Where your files live

The user message you receive lists the concrete paths for this job: the protocol(s), the aspect(s) (zero or more behavior layers your expert opts into via its entry in `lazy.settings.json[experts]`), the literal argument values your expert was registered with, `request.json`, `source/`, `context/`, `result/`, and `response.json`. Use those paths verbatim — do not look up environment variables. Read every protocol and aspect before acting.

## Protocol awareness

Your user-message prompt contains zero or more `- protocol: <path>` lines. Each is the only source of truth for the I/O of one channel — what `request.json` contains, what enum values the protocol-defined fields take, what to write under `result/`, what `response.json` must contain, what callout / response shapes the consumer-side gating predicate expects. Read every protocol path before acting and follow each one literally. Nothing in your agent file overrides a protocol — your agent file describes who you are, the protocol describes how you communicate.

If your channel requires a protocol and no `- protocol: <path>` line appears in your prompt, return an error response naming the missing contract. You do not have a fallback contract — by design.

## Aspect awareness

Your user-message prompt contains zero or more `- aspect: <path>` lines. Read every file at every such path and apply its domain guidance on top of your persona. Aspects compose — multiple aspects may be present and all apply simultaneously. An aspect may add domain vocabulary you should mirror in your output, prescribe a section structure, name domain-specific premises / constraints / conventions, or call out pitfalls. Aspects shape *how* you do your job; they do not change *that* you do it.

## Input — `request.json`

Read `request.json` (path given in your user message). Required fields:

- `role` (string) — what kind of work this is.
- Plus any fields your expert-specific protocol declares.

Do not assume fields beyond what your protocol declares. The runtime does not validate them for you.

## Output — `response.json`

Write `response.json` (path given in your user message):

```json
{
  "outcome": "<protocol-defined-string>" | "error",
  "result":  [...],
  "error":   { "category": "...", "message": "..." }
}
```

- `outcome` is **protocol-defined**: the protocol you implement declares an enum of success values (e.g. `edited`, `confirmed`, `empty`, `summarized`). The string `"error"` is the only reserved universal value across all protocols and signals failure. Do NOT write `"ok"` — that's not in any current protocol's enum; consumers either accept the protocol-defined string or branch on `"error"`.
- On a success outcome (any protocol-defined value), `result` is the array of artifact descriptors per your protocol. Omit when your protocol's outcome doesn't carry artifacts (e.g. `confirmed` / `empty`).
- On `outcome: "error"`, `error.category` is one of your protocol's error categories. `error.message` is human-readable detail.

Write artifact files into the `result/` directory inside your job dir. The dispatcher reads them from there — they are runtime artifacts, not committable content. See the **Working tree** section above: never `git add` anything under your job dir.

## What you must not touch

- The `DONE` marker inside your job dir — the daemon writes this after you exit cleanly.
- Files outside your job dir and your own commits.
- Other experts' job dirs (`.experts/.jobs/<other-expert>/...`).
- Branches other than the daemon's base branch (`daemon.git.base_branch`, the operator's branch the daemon rides).
- The runtime's state file (`.runtime/state.json`).
