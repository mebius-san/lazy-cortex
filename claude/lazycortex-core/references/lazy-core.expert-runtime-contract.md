---
version: 3.0.0
description: Universal contract loaded into every expert run by lazycortex-core's expert pump. Read alongside your expert-specific protocol.
---
# Expert Runtime Contract

This document is loaded into every expert run via `--append-system-prompt-file`. The rules below apply universally on top of your expert-specific protocol. Read both before acting.

## Working tree

**Where a file lands decides how it gets there.** Two questions, one answer each — and one limit that holds whatever the answers are.

**Does it land in the spec catalog?** Then you never write it and never commit it. The document your job produces, its attachments, its reports, a request you raise — every one of them goes back through `result/`, declared in your response's `result` array, and a collector puts it in place and commits it. This holds in every job type, every round, every mode. The catalog is not yours to write into.

**Does it land anywhere else — code, data, product documentation, configuration?** Then you edit it in place and commit it yourself at the end of your job, naming every path:

```
git add -- <path> <path>
git commit -m "<expert-name>: <one-line summary>" -- <path> <path>
```

Never stage with a wildcard, never sweep the whole worktree into a commit, and never commit without a pathspec. The checkout's index is shared with the operator and with every other routine: a wildcard stage or a pathspec-less commit publishes work that is not yours. Your own persona memory under `.memory/<self>/` is committable too, but you never stage it by hand — the memory-write skill writes the note, its tag index and its commit as one atomic act, and running that skill is the whole of your part. Run logs under `.logs/` are the same shape.

**The right stops at any file the system itself owns regions of.** A file carrying review frontmatter, a protected section, or a system-painted banner goes through the applying route (`result/`), never a direct worktree edit, for as long as it is in that state. A file you created outside that state and which later enters it stops being directly editable until it leaves again. This limit is independent of the two questions above: it reaches a code file, a data file and a configuration file exactly as it reaches a document, and a `true` commit right does not lift it.

**Never commit anything under your own job dir.** Your job dir (`.experts/.jobs/<expert>/<job-id>/` — `response.json`, `result/*`, `transcript.jsonl`, `request.json`, `source/`, `context/`, `PID`, `attempts`, …) is runtime scratch space. It is gitignored. It is read by the daemon and the dispatcher; nothing about it belongs in `git log`.

- If a bare `git add <path>` complains `paths are ignored by one of your .gitignore files`, that is the system telling you the path is not committable. **Do not retry with `-f`.** Stop and exit cleanly.
- Do not use `git add -f` for any path, ever. The flag exists to bypass `.gitignore`; in this runtime, every gitignored path is gitignored on purpose.

**If you produced no tracked-file mutations, exit with a clean tree.** Do NOT make a commit "to signal completion". The daemon detects completion via the `DONE` marker (which it touches, not you) and via `response.json` (which is gitignored — see above). The dispatcher records protocol-required noop commits itself, with the correct trailers; you cannot substitute for it. Specifically: returning `outcome: noop` (or any non-mutating outcome your protocol defines) means **write `response.json` and exit, no commit at all**.

Do **not** push. Do **not** change branches. Do **not** run `git checkout`, `git reset`, `git rebase`, or anything else that rewrites history or moves HEAD. The daemon owns those operations. Some experts run on a job-scoped branch the pump checked out before you started (a per-expert `workspace: branch` setting you never see or touch) — commit exactly as described above regardless; which branch is currently checked out is not your concern.

**Sub-skills count as your writes.** When you invoke a sub-skill (via the `Skill` tool or by running a CLI verb in `Bash`) that modifies tracked files — `lazy-review.start`, `lazy-spec.set-stage`, any helper that flips frontmatter or writes content — those writes are part of YOUR work. Two ways to keep the tree clean:

1. **Sub-skill commits itself** (preferred when the skill's purpose is a self-contained mutation). The backing binary stages + commits atomically; no follow-up step from you.
2. **You wrap the sub-skill in your own final commit**. Invoke the skill, then commit once at the end of your job, naming the paths the skill left dirty — the same explicit pathspec every other commit of yours carries.

A sub-skill that writes to disk and leaves `git status --porcelain` non-empty after the skill returns is a contract violation against THIS contract — fix the sub-skill (option 1) rather than relying on option 2 as the permanent solution.

Before exiting, your final `git status --porcelain` MUST be empty. If you exit with uncommitted changes in tracked files, the daemon halts the entire runtime and the operator must run `/lazy-runtime.recover` to restart it. Your job will be marked `outcome: error, category: uncommitted_changes`. (Files under your job dir don't trigger this — they're gitignored and don't show in `--porcelain`.)

## Where your files live

The user message you receive lists the concrete paths for this job: the protocol(s), the aspect(s) (zero or more behavior layers your expert opts into via its entry in `lazy.settings.json[experts]`), the literal argument values your expert was registered with, `request.json`, `source/`, `context/`, `result/`, and `response.json`. Use those paths verbatim — do not look up environment variables. Read every protocol and aspect before acting.

## Attachments

**An attachment is returned, never placed.** A mockup, a diagram, a data file, an additional prose chapter that belongs beside your result document is written into `result/` and declared in your response: the FIRST entry of the `result` array is the document itself, and every entry after it is one attachment. Each entry is `{"path": "result/<file>"}` and nothing else — the basename is the name the file takes beside the document, and it is a plain filename: no directory, no parent hop, never empty. An entry that carries a location of its own makes the whole response malformed and the job undelivered.

**Link an attachment by its neighbour name.** Inside the document you write `[app-shell.html](app-shell.html)`, as if both files already sat side by side — because after the landing they do. A link spelled `result/<file>` is rewritten for you, and a link naming a file you did not return is reported in the daemon log.

**Regeneration goes the same way.** A later round that changes a mockup returns the new file through `result/` again; the collector overwrites the old one. The file's body belongs to the job whose document owns it.

**Where the attachment ends up, and which frontmatter it carries, is your protocol's call.** Your channel's protocol says which frontmatter keys a markdown attachment must carry — ownership, kind, or both — and whether the channel accepts attachments at all. Read it; a protocol that permits none says so, and its silence is not permission.

**No format is forbidden.** Prefer text formats you can author yourself — markup, vector graphics, stylesheets, structured data. Reach for a binary only when a generator exists that produces it.

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
  "outcome": "<protocol-defined-string>" | "error" | "deferred",
  "result":  [...],
  "error":   { "category": "...", "message": "..." }
}
```

- `outcome` is **mandatory, and its name is not negotiable**. A protocol declares which *values* it takes (e.g. `edited`, `confirmed`, `empty`, `summarized`) — never a different field. If the protocol you were handed prescribes some other status key, write `outcome` anyway and report the contradiction in your response; a response without `outcome` is rejected and re-dispatched to you, and work you report as finished through any other key is read as a failure. Two values are reserved universally across all protocols: `"error"` signals failure, and `"deferred"` signals work you deliberately did not do — you left every input exactly as you found it and expect to be asked again later. Never report `deferred` after touching, moving, or consuming an input. Do NOT write `"ok"` — that's not in any current protocol's enum; consumers either accept the protocol-defined string or branch on `"error"`.
- On a success outcome (any protocol-defined value), `result` is the array of artifact descriptors per your protocol. Omit when your protocol's outcome doesn't carry artifacts (e.g. `confirmed` / `empty`).
- On `outcome: "error"`, `error.category` is one of your protocol's error categories. `error.message` is human-readable detail.

Write artifact files into the `result/` directory inside your job dir. The dispatcher reads them from there — they are runtime artifacts, not committable content. See the **Working tree** section above: never `git add` anything under your job dir.

## What you must not touch

- The `DONE` marker inside your job dir — the daemon writes this after you exit cleanly.
- Files outside your job dir and your own commits.
- Other experts' job dirs (`.experts/.jobs/<other-expert>/...`).
- Branches other than the daemon's base branch (`daemon.git.base_branch`, the operator's branch the daemon rides).
- The runtime's state file (`.runtime/state.json`).
- The input file, until your work has succeeded. The input handed to you (`source/*` and any external paths passed as input) may be moved, deleted, or filed away — but only as the **last action once your result is ready and you return a success outcome**. While `outcome: "error"` is still possible, leave the original in place: on failure it is the only copy left to reprocess. (Leaving it untouched is equally fine — the dispatcher removes it on `outcome: "done"`.)
