#!/usr/bin/env bash
# <Pre|Post>ToolUse hook (shell variant): <one-line purpose>.
#
# Use this template only for hooks that genuinely benefit from being a shell
# shim (no JSON parsing, simple command dispatch, calls another binary).
# For anything that reads stdin JSON, parses tool_input fields, or branches
# on multiple matchers, use hook-template.py instead. A shell hook reads no
# payload field: `jq` is absent from Git Bash on Windows, and inline interpreter
# code is banned, so the payload is Python's to parse.
#
# Fires on:
# - <MatcherName> tool calls — the registered matcher is the whole gate.
# (Add more matchers if registered in settings.json.)
#
# Behavior:
# - <Branch 1: when <gate fires>, this branch <writes/commits/emits-context>.>
# - <Branch 2: when <other gate>, this branch is a no-op.>
# (Every branch terminates in a documented outcome — see lazy-core.hook-writing § 3.)
#
# This template encodes the lazy-core.hook-writing § 1–8 contract:
#   § 1 script discipline · § 2 trigger gating · § 3 branch determinism
#   § 4 no-dirty-tree · § 5 no-foreign-staged · § 6 auto-commit loop guard
#   § 7 transactional skip · § 8 logging
#
# Delete the trailing AUTHORING NOTES block before saving; it is a guide,
# not runtime documentation.

set -eu

# § 1 — the JSON payload arrives on stdin. A shell hook parses none of it;
# drain it so the writer never blocks on a full pipe.
cat >/dev/null

# § 2 — TRIGGER GATING — register a narrow matcher (one tool, e.g. `Write`); the
# matcher is this hook's gate. A broad matcher (`Bash`, `Agent`) must be narrowed
# on tool_input in-script, which only hook-template.py can read.

# § 1 — bail outside git repo / wrong workspace shape.
if ! ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    exit 0
fi
if [ ! -d "$ROOT/<expected-marker-dir>" ]; then
    exit 0
fi

# § 7 — TRANSACTIONAL SKIP — never auto-commit during merge/rebase/cherry-pick.
# REBASE_HEAD is deliberately absent: git records the commit a rebase stopped at there and never
# removes it when the rebase concludes, so a leftover would silence this hook forever. The
# rebase-merge / rebase-apply directories are what git itself reads, and they do get removed.
GIT_DIR="$(git -C "$ROOT" rev-parse --git-dir)"
case "$GIT_DIR" in /*) : ;; *) GIT_DIR="$ROOT/$GIT_DIR" ;; esac
for marker in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD \
              rebase-merge rebase-apply BISECT_LOG; do
    if [ -e "$GIT_DIR/$marker" ]; then
        exit 0
    fi
done

# § 6 — LOOP GUARD — content-based bail (replace with predicate that
# recognises THIS hook's own footprint; contract: lazy-core.hook-writing § 6).
# Time-based throttles and counter guards are forbidden — content predicate only.
# Example: bail if every changed path matches our own auto-commit pattern.
# CHANGED="$(git -C "$ROOT" diff-tree --no-commit-id --name-only -r --root HEAD)"
# if printf '%s\n' "$CHANGED" | awk 'NR==0 || ! /^claude\/.*\/.*\.md$/{e=1} END{exit !e}'; then
#     :  # only our own paths — bail
#     exit 0
# fi

# § 3 — BRANCH determinism — pick one outcome per branch:
#   (a) emit additionalContext to stdout (PostToolUse JSON shape).
#   (b) write file(s) AND commit them in same execution (§ 4) without
#       pathspec on commit (§ 5).
#   (c) no-op exit 0.

# ---- Example: write-then-commit branch (§ 4 + § 5) ----
# Per § 5: never use `git commit -- <pathspec>`. Detect foreign staged
# content first; defer (return) if any foreign paths are staged.
# PRE_STAGED="$(git -C "$ROOT" -c core.hooksPath=/dev/null \
#               diff --cached --name-only)"
# OUR_PATHS="path/we/own.md"
# FOREIGN="$(printf '%s\n' "$PRE_STAGED" | grep -vF -x "$OUR_PATHS" || true)"
# if [ -n "$FOREIGN" ]; then
#     echo "<hook-name>: foreign staged content; deferring auto-commit" >&2
#     exit 0
# fi
# git -C "$ROOT" -c core.hooksPath=/dev/null add -- "$OUR_PATHS"
# git -C "$ROOT" -c core.hooksPath=/dev/null \
#     commit -m "chore: <one-line>"   # NO pathspec

# ---- Example: context-only branch ----
# printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<msg>"}}'

exit 0

# ============================================================================
# AUTHORING NOTES — DELETE THIS BLOCK BEFORE SAVING
# ============================================================================
#
# When to use shell vs Python:
#   shell — thin shim, simple command dispatch, calls another binary, a narrow
#           matcher as its only gate, no JSON parsing at all.
#   python — anything that reads multiple tool_input fields, branches on
#            patterns, manipulates index, parses output of git commands. Use
#            hook-template.py.
#
# Naming
#   File: <dot-namespace>.hook.sh (e.g., my-thing.hook.sh).
#   Register in settings.json: hooks.{Pre,Post}ToolUse[].matcher = "<MatcherName>"
#   with hooks[].command = bash "${CLAUDE_PLUGIN_ROOT}/hooks/<file>".
#
# Contract (lazy-core.hook-writing §§ 1–8) — same as Python variant.
#
# Reference implementations: see lazy-core.hook-writing §§ 1–8 for worked
# patterns (PostToolUse loop-guarded auto-commit, PreToolUse deny / rideshare).
#
# Out-of-scope
#   Inline `command:` strings in settings.json (one-liners) don't need a
#   script file at all.
# ============================================================================
