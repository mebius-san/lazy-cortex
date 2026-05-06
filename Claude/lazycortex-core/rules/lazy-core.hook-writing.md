---
description: Authoring contract for Claude Code lifecycle hooks — PreToolUse, PostToolUse, Stop, SessionStart, etc. Covers script discipline, trigger gating, branch determinism, loop guards, transactional skip, the no-dirty-tree clause, and logging.
paths:
  - ".claude/hooks/**"
  - ".claude/templates/core/hook-template.py"
---
# Hook Authoring

Audience: anyone authoring a Claude Code lifecycle hook script (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, etc.). Applies to every hook script under `.claude/hooks/**` and `claude/*/hooks/**`.

This file is the single source of truth for **how to write** hook scripts. For the broader execution-discipline rules that all runnable artifacts share, see `lazy-core.skill-writing § 1`. For the no-dirty-tree clause that applies equally to skills, agents, and hooks, see `lazy-core.skill-writing § 6` — hooks are the most common offender of that rule because they fire on tool boundaries that may not have a clean commit anchor.

## 1. Script discipline

- Shebang `#!/usr/bin/env python3` (or `#!/bin/sh` for shell shims). Never rely on the caller to pass an interpreter.
- Stdin is JSON per the Claude Code hook protocol. Read with `json.load(sys.stdin)` and tolerate malformed input — return 0 silently if the payload cannot be parsed (a hook must never crash the trigger).
- Exit 0 on every path that should not block the trigger. Exit 2 only if the hook is a `Pre*` hook intentionally vetoing the tool call.
- Wrap every `subprocess.run` that performs a git operation with `-c core.hooksPath=/dev/null` to avoid re-entry into the hook chain. Example: `subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "commit", ...])`.

## 2. Trigger gating

A hook attached to a broad matcher (`Bash`, `Agent`) MUST gate its work on the actual tool input — match the command pattern (e.g., `re.match(r"\s*git\s+commit\b", command)`), the subagent name, etc. A hook that does not gate runs on every tool call and is pathological. The matcher in `settings.json` is the coarse filter; the in-script gate is the precise filter.

## 3. Branch determinism

For each trigger this hook handles, the body MUST have an explicit, documented branch with a deterministic outcome:

- "this branch writes file X and commits it"
- "this branch only emits `additionalContext` to stdout"
- "this branch is a no-op"

No fall-through to a write path that the trigger did not explicitly opt in to. If a branch ends in a write, the same branch MUST end in the matching commit (per §§ 4–5 below or via a documented callee chain).

## 4. No dirty working tree

Cross-reference `lazy-core.skill-writing § 6`. The full clause and waiver mechanism live there. Restated tersely for hook authors: if your hook writes to a tracked file, your hook commits that file in the same execution. If you cannot commit (transactional state, no commit anchor, ambiguous trigger), do not write.

Hooks are the most likely offenders because:

- They fire on tool boundaries that may not represent meaningful commit points.
- They are easy to write without a commit story ("just refresh the cache file") and the cost — a perpetually dirty working tree — is invisible to the author and obvious to the user.

If your trigger has no commit story, the right answer is usually to drop the trigger, not to add a write-and-leave path.

## 5. No foreign staged content survives the hook

§ 4 covers working-tree hygiene. This section covers **index hygiene** — the parallel invariant: hooks must not leak unrelated staged content across process boundaries.

### Rule

A hook MUST NOT extend, modify, unstage, or commit index entries it didn't author. At hook exit, files staged by external processes (i.e., what was already in the index when the hook started) must be EXACTLY as they were on entry.

A process at exit must put every file *it touched* into exactly one of:

1. **Committed** — the hook produced new git history for it.
2. **Working tree only** — modified, not staged; the user (or a coordinating outer process) decides when to stage and commit.
3. **Restored** — touched transiently (cache, fixture) and reverted.

Files that belong to *other* processes are option (4) — left exactly as found.

### 5.1 No `git commit -- <pathspec>` to filter the index

A hook that auto-commits its own writes MUST NOT use a pathspec on `git commit` to "only commit my files, leave others alone". The pattern silently accepts orphan staged content from external processes — they remain in index after our commit, dangling, and ride along with the user's next commit. Cross-process index pollution.

Right pattern: detect pre-existing staged content. If foreign paths exist in index, **defer** the auto-commit (write the file in working tree, log a warning, return). Let the user (or a coordinating outer process) include the writes in their next deliberate commit.

```python
# Acceptable: detect foreign, defer
foreign = [p for p in pre_staged if p not in our_paths]
if foreign:
    sys.stderr.write(f"<hook>: foreign staged content; deferring\n")
    return                                      # writes stay in working tree
git_add(our_paths); git_commit(message)         # NO pathspec — index is clean
```

Forbidden: `git commit -m "..." -- our_paths` — pathspec leaves foreign paths in index.

### 5.2 No staging-without-committing handoff

A `Pre*` hook MUST NOT stage a file and exit relying on the in-progress tool call to pick it up — UNLESS the hook can prove the in-progress call will. The handoff is fragile: a pathspec on the in-progress commit, or a parallel hook with its own pathspec, will silently exclude the staged content from any commit, leaving it dangling.

Right pattern: detect commit shape. For `mcp__git__git_commit` (no pathspec possible) staging is always safe. For `Bash` matching `git commit`, parse the command for a pathspec — if present, refuse the modification (write nothing, emit a warning).

```python
# Bash branch: refuse if pathspec
if re.search(r"\bgit\s+commit\b.*\s--\s+\S", command):
    _context("<hook-name>: pathspec on commit; modification declined")
    return
```

Forbidden: blind `git_add(file)` after writing, "hopes the commit picks it up".

### Reference incident

The 2026-05-04 git-state-hygiene incident: a `pub.autobump` rideshare collided with `pub.status._autocommit` running with pathspec, leaving a `plugin.json` staged at the *previous* version while HEAD and working tree advanced. A naive `git commit -am` would have silently downgraded the manifest. See `docs/specs/2026-05-04-git-state-hygiene.md`.

### Severity

`lazy-core.audit` Agent B:

- **FAIL** — hook calls `git commit ... -- <pathspec>` (literal pattern: `commit"` followed by `"--"` plus path arguments in the same arg list).
- **FAIL** — hook calls `git add` with no matching `git commit` in the same execution branch (heuristic, same shape as § 4 enforcement).
- **WARN** — hook detects pre-existing staged content (`git diff --cached --name-only`) but doesn't act on the detection (no defer / no refuse / no warning emitted).

## 6. Auto-commit loop guard

A hook that auto-commits its own writes MUST have a content-based bail. Pattern: `git diff-tree --no-commit-id --name-only -r --root HEAD` plus a predicate that recognises this hook's own footprint (e.g., "every changed path matches `claude/<x>/<x>.md`"). If the predicate matches, return 0 without re-running the work — otherwise the hook re-fires on its own commit indefinitely.

Time-based throttles (cooldown files, mtime checks) and counter-based guards are not acceptable substitutes — they leak state across sessions and fail when the user reorders or amends commits.

Reference implementation: `.claude/hooks/pub.status.hook.py::_is_real_commit`.

## 7. Transactional skip

A hook that auto-commits MUST refuse to do so when the repo has any of: `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `REBASE_HEAD`, `rebase-merge/`, `rebase-apply/`, `BISECT_LOG`. Auto-commit during these flows interferes with the user's interactive operation and can corrupt the in-progress merge/rebase state.

Reference implementation: `.claude/hooks/pub.status.hook.py::_in_transactional_state`.

## 8. Logging

Cross-reference `lazy-log.logging`. Hooks log to `./.logs/claude/<hook-name>/<timestamp>.md` like every other artifact. Naming: `<dot-namespace>.hook` (e.g., `pub.status.hook`).

## Enforcement

`lazy-core.audit` Agent B enforces §§ 1-7 of this file as part of its existing skill/agent compliance pass: shebang present, JSON-stdin handling defensive, write paths paired with commits (heuristic — same as skill-writing § 6), broad matchers gated in-script, auto-commit loops guarded by content predicate, no pathspec-on-commit / no staging-without-committing (§ 5). Severity: PASS / WARN / FAIL per the audit's standard vocabulary.

## Scope

- **In-scope:** scripts directly invoked by the Claude Code hook chain — anything listed in the `hooks` block of `settings.json` or installed by a plugin's `lazy-core.install` step.
- **Out-of-scope:** scripts under `.claude/skills/*/bin/` (governed by their parent skill via `lazy-core.skill-writing § 1`), arbitrary tooling under `bin/` or `scripts/` (governed by repo-wide conventions, not by Claude Code).
