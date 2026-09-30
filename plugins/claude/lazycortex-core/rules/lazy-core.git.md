---
description: "Protect the shared git index — the pathspec commit discipline and the staging-window mutex, both enforced by the lazy-core.git-guard hook."
always_loaded: "Constrains every git index verb. Prevents an agent commit from sweeping in operator-parked content."
---

# `lazy-core.git` — the shared index

The operator and every Claude session on a checkout share **one git index**; a bare `git commit` snapshots all of it. The `lazy-core.git-guard` hook enforces one of two behaviours per `<repo>/.claude/lazy.settings.json["git"]`: `pathspec_enabled: true` (the default) applies the pathspec discipline; `pathspec_enabled: false` with `mutex_enabled: true` applies the staging-window mutex; both `false`, or `enabled: false`, silences the hook.

A `permissionDecision: deny` means you broke the discipline — rephrase. Never retry verbatim, never bypass with `--no-verify` or a raw wrapper.

## Pathspec discipline (`pathspec_enabled`)

**The index is not yours.** It belongs to the operator; you leave nothing in it.

- **New file** → `git add -N <path>` (registers the path, stages no content). No other `git add` — except `git add <path>` on unmerged index entries while resolving a conflict.
- **Rename / delete** → Bash `mv` / `rm`. Never `git mv` / `git rm` — both auto-stage.
- **Commit** → explicit paths only: `git commit -m "..." -- <path> <path>`. Never bare, never `-a` / `-am` / `-i`, never `.` / `:/` / a directory pathspec. MCP `git_add` / `git_commit` carry no pathspec — use Bash.
- **Revert** → `git restore --worktree -- <path>` or `git restore --source=<tree-ish> --worktree -- <path>`. Never `git checkout <tree-ish> -- <path>` and never `git restore --staged --source=<tree-ish>` — both write the index. Plain `git restore --staged` and `git reset` stay allowed.
- **`index (…conflicted copy…)` files beside `.git/index`** are a cloud-sync race; `lazy-core.index-guard` and the hook's pre-flight heal them. Never hand-copy them, never diagnose staged content before the heal.
- **Commit requires a clean index.** Staged content is the operator's; the hook denies the commit — stop and escalate, never `git reset` it yourself. Intent-to-add entries never block. Mass staged deletions with intact files are the operator's to recover.
- **Exceptions:** a bare commit mid-merge, and `--amend` with a pathspec or against a clean index.

A skill that stages for you returns the paths it touched — fold them into your commit pathspec.

## Staging-window mutex (`mutex_enabled` without `pathspec_enabled`)

A per-repo lock at `.git/lazy-git.lock` serializes the window from the first `git add` to the `git commit` that empties the index. Plan every edit before any `git add`, then add → pre-commit pipeline → commit back-to-back; an idle non-empty index over 10 min is broken by the stale-and-idle rule. On "another Claude session is staging…": wait, retry once, then escalate. Never break the lock yourself; `/lazy-core.git-status` and `/lazy-core.git-unlock` are the operator's hatches.
