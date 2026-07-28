---
description: "Protect the shared git index — the pathspec commit discipline and the staging-window mutex, both enforced by the lazy-core.git-guard hook."
always_loaded: "Constrains every git index verb. Prevents an agent commit from sweeping in operator-parked content."
---

# `lazy-core.git` — the shared index

The operator and every Claude session on a checkout share **one git index**. A bare `git commit` snapshots all of it, so anything parked there rides along silently. The `lazy-core.git-guard` hook enforces one of two behaviours, flagged in `<repo>/.claude/lazy.settings.json["git"]` under the `enabled` master switch (`false` there silences the hook entirely):

| `pathspec_enabled` | `mutex_enabled` | What applies |
|---|---|---|
| `true` (default) | either | Pathspec discipline; mutex dormant (you never open a staging window). |
| `false` | `true` | Staging-window mutex. |
| `false` | `false` | Guard silent. |

**The rule teaches, the hook catches.** A `permissionDecision: deny` means you broke the discipline below — rephrase. Never retry verbatim, never bypass with `--no-verify` or a raw wrapper.

## Pathspec discipline (`pathspec_enabled`)

**The index is not yours.** It belongs to the operator (parked adds, a half-assembled review). Its contents are none of your business, and you leave nothing in it.

- **New file** → `git add -N <path>` (registers the path, stages no content). Nothing else may `git add`.
- **Rename / delete** → Bash `mv` / `rm` in the worktree. Never `git mv` / `git rm` — both auto-stage.
- **Commit** → always explicit paths: `git commit -m "..." -- <path> <path>`. Never bare, never `-a` / `-am` / `-i`, never `.` / `:/` / a directory pathspec.
- **MCP `git_add` / `git_commit`** are unusable here — they cannot carry a pathspec. Use Bash.
- `git reset` stays allowed; the operator may need to un-park from inside a session.
- **Exceptions:** a bare commit mid-merge (git refuses a partial commit there), and `--amend` either with a pathspec or against a clean index.

A skill that stages for you returns the paths it touched — fold them into your commit pathspec.

## Staging-window mutex (`mutex_enabled` without `pathspec_enabled`)

Serializes the *staging window* — first `git add` to the `git commit` that empties the index — via a per-repo lock at `.git/lazy-git.lock`.

- **Trust the hook.** On "another Claude session is staging…", wait, retry once, then escalate to the user.
- **Stage → commit promptly.** Plan all edits before any `git add`; run add → pre-commit pipeline → commit back-to-back; re-staging within one session is a no-op. An idle non-empty index >10 min is broken by the stale-and-idle rule (worktree content stays).
- **Don't break the lock yourself.** Dead PIDs, host mismatches, and stale holders auto-break; the operator's hatches are `/lazy-core.git-status` and `/lazy-core.git-unlock`, both inert on the pathspec row.
- **Edges:** `git stash push` and raw shell `git` bypass the matchers, so a lock can linger until the stale rule fires.
