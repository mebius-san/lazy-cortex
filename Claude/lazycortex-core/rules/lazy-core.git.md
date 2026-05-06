---
description: "Serialize git staging across concurrent Claude Code sessions sharing one checkout — honor the lazy-core.git-guard hook and the lock file under .git/lazy-git.lock."
always_loaded: "Constrains every git add/rm/mv/reset/commit tool call. The cost is constant; the protection prevents lost commits when two sessions share a checkout."
---

# `lazy-core.git` — staging-window mutex

Multiple Claude Code sessions on the same checkout share **one git index**. Without coordination, session A's `git commit` can capture session B's staged files. The `lazy-core.git-guard` hook (`hooks/lazy-core.git-guard.py`, helper at `bin/staging_lock.py`) enforces a per-repo mutex on the *staging window* — the interval from the first `git add` that creates a non-empty index to the `git commit` that empties it.

## What you (Claude) need to do

- **Trust the hook.** If the hook returns a `permissionDecision: deny` saying "another Claude session is staging…", do not retry the same call immediately. Wait briefly and try once; if it still refuses, escalate to the user — do not bypass with raw shell git or `--no-verify`.
- **Do not break the lock yourself.** The hook auto-breaks dead PIDs, host mismatches, and stale-and-idle holders. Manual breakage is `/lazy-core.git-unlock` only, and it asks before acting.
- **Stage → commit promptly.** Plan all edits before any `git add` — staging is final assembly, not a workspace. Run `git_add` → `/pub.pre-commit` → `git_commit` back-to-back, nothing between. `git mv` auto-stages: for multi-file refactors prefer Bash `mv` and a single `git add -A` at the end. Idle non-empty index >10 min triggers the stale-and-idle break-rule (work in the tree stays).
- **Same session re-stages freely.** Re-entry is a no-op; you can `git add` multiple times in a row without the hook intervening.

## Hook surface

- **PreToolUse** on `git add|rm|mv|reset` (Bash + MCP) — acquires or refuses the lock.
- **PreToolUse** on `git commit` — diagnostic only; never blocks (could be `--amend` or a path-specced commit).
- **PostToolUse** on `git commit|reset` — releases the lock if the index is now empty.

## Known edges

- **`git stash push`** — empties the index without going through hook matchers; the lock stays until next commit/reset/manual unlock. Stale-and-idle break-rule catches it within ~10 min. Don't stash mid-stage if you can avoid it.
- **`git commit -- <pathspec>`** — bypasses the index entirely; doesn't violate the invariant; rare in agent flows.
- **Raw shell `git`** outside Claude Code — invisible to the hook. Stale-and-idle break-rule limits damage if a human staged-and-walked-away.

## Operator escape hatches

- `/lazy-core.git-status` — read-only inspect (holder, age, liveness, breakability).
- `/lazy-core.git-unlock` — confirmed manual break.

## Disabling

In `<repo>/.claude/lazy.settings.json` add `{"lazy-core.git": {"enabled": false}}` to short-circuit the hook entirely. Useful in single-session repos where the lock is noise.
