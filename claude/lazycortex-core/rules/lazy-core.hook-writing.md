---
description: Authoring contract for Claude Code lifecycle hooks — PreToolUse, PostToolUse, Stop, SessionStart, etc. Covers script discipline, trigger gating, branch determinism, loop guards, transactional skip, the no-dirty-tree clause, and logging.
paths:
  - ".claude/hooks/**"
  - ".claude/templates/core/hook-template.py"
  - ".githooks/**"
---
# Hook Authoring

Audience: anyone authoring a Claude Code lifecycle hook script (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, etc.). Applies to every hook script under `.claude/hooks/**` and `claude/*/hooks/**`.

This file is the single source of truth for **how to write** hook scripts. Shared execution-discipline rules: `lazy-core.skill-writing § 1`. The no-dirty-tree clause: `lazy-core.skill-writing § 6` — hooks are its most common offender, firing on tool boundaries that may lack a clean commit anchor.

## 1. Script discipline

- Shebang `#!/usr/bin/env python3` (or `#!/bin/sh` for shell shims). Never rely on the caller to pass an interpreter.
- Stdin is JSON per the Claude Code hook protocol. Read with `json.load(sys.stdin)` and tolerate malformed input — return 0 silently if the payload cannot be parsed (a hook must never crash the trigger).
- Exit 0 on every path that should not block the trigger. Exit 2 only if the hook is a `Pre*` hook intentionally vetoing the tool call.
- Wrap every `subprocess.run` performing a git operation with `-c core.hooksPath=/dev/null` to avoid re-entry into the hook chain. Re-entry is not the only failure mode under automation — see § 9.

## 2. Trigger gating

A hook attached to a broad matcher (`Bash`, `Agent`) MUST gate its work on the actual tool input — match the command pattern (e.g., `re.match(r"\s*git\s+commit\b", command)`), the subagent name, etc. An ungated hook runs on every tool call and is pathological. The matcher in `settings.json` is the coarse filter; the in-script gate is the precise one.

## 3. Branch determinism

For each trigger this hook handles, the body MUST have an explicit, documented branch with a deterministic outcome:

- "this branch writes file X and commits it"
- "this branch only emits `additionalContext` to stdout"
- "this branch is a no-op"

No fall-through to a write path the trigger did not explicitly opt in to. If a branch ends in a write, the same branch MUST end in the matching commit (per §§ 4–5 below or via a documented callee chain).

## 4. No dirty working tree

Cross-reference `lazy-core.skill-writing § 6` — the full clause and waiver mechanism live there. Restated tersely: if your hook writes to a tracked file, your hook commits that file in the same execution. If you cannot commit (transactional state, no commit anchor, ambiguous trigger), do not write. Hooks offend most often because tool boundaries rarely represent meaningful commit points, and a write-and-leave path costs the author nothing while leaving the user a perpetually dirty tree. If your trigger has no commit story, drop the trigger rather than add a write-and-leave path.

## 5. No foreign staged content survives the hook

§ 4 covers working-tree hygiene; this section covers the parallel **index** invariant: hooks must not leak unrelated staged content across process boundaries.

### Rule

A hook MUST NOT extend, modify, unstage, or commit index entries it didn't author. At hook exit, files staged by external processes (what was already in the index when the hook started) must be EXACTLY as they were on entry.

A process at exit must put every file *it touched* into exactly one of:

1. **Committed** — the hook produced new git history for it.
2. **Working tree only** — modified, not staged; the user (or a coordinating outer process) decides when to stage and commit.
3. **Restored** — touched transiently (cache, fixture) and reverted.

Files that belong to *other* processes are option (4) — left exactly as found.

### 5.1 No `git commit -- <pathspec>` to filter the index

A hook that auto-commits its own writes MUST NOT use a pathspec on `git commit` to "only commit my files". The pattern silently accepts orphan staged content from external processes — it stays in the index after our commit, dangling, and rides along with the user's next commit.

Right pattern: detect pre-existing staged content; if foreign paths exist in the index, **defer** the auto-commit (write the file in the working tree, log a warning, return) and let the next deliberate commit include the writes.

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

A `Pre*` hook MUST NOT stage a file and exit relying on the in-progress tool call to pick it up — UNLESS the hook can prove the in-progress call will. The handoff is fragile: a pathspec on the in-progress commit, or a parallel hook with its own pathspec, silently excludes the staged content from any commit, leaving it dangling.

Right pattern: detect commit shape. For `mcp__git__git_commit` (no pathspec possible) staging is always safe. For `Bash` matching `git commit`, parse the command for a pathspec — if present, refuse the modification (write nothing, emit a warning).

```python
# Bash branch: refuse if pathspec
if re.search(r"\bgit\s+commit\b.*\s--\s+\S", command):
    _context("<hook-name>: pathspec on commit; modification declined")
    return
```

Forbidden: blind `git_add(file)` after writing, "hopes the commit picks it up".

### Severity

`lazy-core.audit` Agent B:

- **FAIL** — hook calls `git commit ... -- <pathspec>` (literal pattern: `commit"` followed by `"--"` plus path arguments in the same arg list).
- **FAIL** — hook calls `git add` with no matching `git commit` in the same execution branch (heuristic, same shape as § 4 enforcement).
- **WARN** — hook detects pre-existing staged content (`git diff --cached --name-only`) but doesn't act on the detection (no defer / no refuse / no warning emitted).

## 6. Auto-commit loop guard

A hook that auto-commits its own writes MUST have a content-based bail: `git diff-tree --no-commit-id --name-only -r --root HEAD` plus a predicate recognising this hook's own footprint (e.g., "every changed path matches `claude/<x>/<x>.md`"). On match, return 0 without re-running the work — otherwise the hook re-fires on its own commit indefinitely.

Time-based throttles (cooldown files, mtime checks) and counter-based guards are not acceptable substitutes — they leak state across sessions and fail when the user reorders or amends commits.

## 7. Transactional skip

A hook that auto-commits MUST refuse to do so when the repo has any of: `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `REBASE_HEAD`, `rebase-merge/`, `rebase-apply/`, `BISECT_LOG`. Auto-commit during these flows interferes with the user's interactive operation and can corrupt the in-progress merge/rebase state.

## 8. Logging

Cross-reference `lazy-log.logging`. Hooks log to `./.logs/claude/<hook-name>/<timestamp>.md` like every other artifact. Naming: `<dot-namespace>.hook`.

## 9. The daemon gate

A hook that rewrites the working tree or calls git MUST check `LAZYCORTEX_HOOKS_ALLOW_LIST` before doing any work, and stay silent when its own short name is absent. This covers git hooks and inline-shell hook bodies in a plugin's `hooks.json`, not only python scripts under `hooks/`.

The variable's *presence* is the signal: the daemon exports it for every routine it dispatches, from that routine's `hooks_enabled`, so anything the daemon spawns runs no lazycortex hook unless the routine opted in. An absent variable means an operator's own session, where the hook behaves as it always has.

- Python hooks call `hook_gate.is_enabled(<short-name>)` as their first action.
- Shell hooks read the variable directly — one string comparison; reaching into the plugin tree from a git hook has no legal path anyway (`${CLAUDE_PLUGIN_ROOT}` is not exported to git hooks).

Why: a developer hook is written for a human at a keyboard. Under the daemon the same hook fires on autonomous commits — one that rewrites files after the commit is assembled leaves a dirty tree, and `runtime_daemon._check_working_tree` halts the whole runtime on it until an operator intervenes.

Read-only hooks that neither touch the tree nor call git are out of this clause.

## Enforcement

The marketplace audit tooling enforces § 9 against every hook artifact a plugin ships — `hooks/*.py`, `hooks/*.sh`, inline commands in `hooks/hooks.json`, and shim templates under `templates/**` — reporting a tree-writing or git-calling hook that never reads the allow-list. `lazy-core.audit` Agent B enforces §§ 1–7 as part of its skill/agent compliance pass: shebang present, JSON-stdin handling defensive, write paths paired with commits (heuristic, as skill-writing § 6), broad matchers gated in-script, auto-commit loops guarded by content predicate, no pathspec-on-commit / no staging-without-committing (§ 5). Severity: PASS / WARN / FAIL per the audit's standard vocabulary.

## Scope

- **In-scope:** scripts directly invoked by the Claude Code hook chain — anything listed in the `hooks` block of `settings.json` or installed by a plugin's `lazy-core.install` step. § 9 additionally reaches git hooks (`.githooks/**`, `.git/hooks/**`), the shim templates a plugin ships for them, and inline-shell hook bodies declared in a plugin's `hooks.json`.
- **Out-of-scope:** scripts under `.claude/skills/*/bin/` (governed by their parent skill via `lazy-core.skill-writing § 1`), arbitrary tooling under `bin/` or `scripts/` (governed by repo-wide conventions, not by Claude Code).
