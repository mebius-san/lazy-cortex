#!/bin/sh
# <Pre|Post>ToolUse hook (shell variant): <one-line purpose>.
#
# Use this template only for hooks that genuinely benefit from being a shell
# shim (no JSON parsing, simple command dispatch, calls another binary).
# For anything that reads stdin JSON, parses tool_input fields, or branches
# on multiple matchers, use hook-template.py instead — Python's `json` and
# `re` modules make those hooks far less brittle than `jq`/`grep` chains.
#
# Fires on:
# - <MatcherName> tool calls — <gate condition>.
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

# § 1 — defensive JSON-stdin parsing. Tolerate malformed input. Without
# `jq` available we just skip non-JSON paths.
PAYLOAD="$(cat)"
if [ -z "$PAYLOAD" ]; then
    exit 0
fi

# Tool name extraction (requires jq — declare it as a dep or fall back to
# grep-based extraction if jq is unavailable).
if ! command -v jq >/dev/null 2>&1; then
    # jq absent: shell hook can't reliably parse the payload. Bail safely.
    exit 0
fi

TOOL_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // ""')"

# § 2 — TRIGGER GATING — broad matchers MUST be narrowed in-script.
case "$TOOL_NAME" in
    Bash)
        COMMAND="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // ""')"
        case "$COMMAND" in
            # match the precise command shape this hook handles
            *<command-prefix>*) ;;
            *) exit 0 ;;
        esac
        ;;
    <other-matcher>)
        # narrow this branch (e.g. .tool_input.subagent_type for Agent).
        :
        ;;
    *)
        exit 0
        ;;
esac

# § 1 — bail outside git repo / wrong workspace shape.
if ! ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    exit 0
fi
if [ ! -d "$ROOT/<expected-marker-dir>" ]; then
    exit 0
fi

# § 7 — TRANSACTIONAL SKIP — never auto-commit during merge/rebase/cherry-pick.
GIT_DIR="$(git -C "$ROOT" rev-parse --git-dir)"
case "$GIT_DIR" in /*) : ;; *) GIT_DIR="$ROOT/$GIT_DIR" ;; esac
for marker in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD REBASE_HEAD \
              rebase-merge rebase-apply BISECT_LOG; do
    if [ -e "$GIT_DIR/$marker" ]; then
        exit 0
    fi
done

# § 6 — LOOP GUARD — content-based bail (replace with predicate that
# recognises THIS hook's own footprint; see pub.status.hook._is_real_commit
# for a Python worked example).
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
#   shell — thin shim, simple command dispatch, calls another binary, no JSON
#           parsing beyond tool_name. Requires `jq` available on PATH.
#   python — anything that reads multiple tool_input fields, branches on
#            patterns, manipulates index, parses output of git commands. Use
#            hook-template.py.
#
# Naming
#   File: <dot-namespace>.hook.sh (e.g., my-thing.hook.sh).
#   Register in settings.json: hooks.{Pre,Post}ToolUse[].matcher = "<MatcherName>"
#   with hooks[].command = sh "${CLAUDE_PLUGIN_ROOT}/hooks/<file>".
#
# Contract (lazy-core.hook-writing §§ 1–8) — same as Python variant.
#
# Reference implementations (Python — read these for the worked patterns):
#   .claude/hooks/pub.status.hook.py
#   .claude/hooks/pub.autobump.py
#
# Out-of-scope
#   Inline `command:` strings in settings.json (one-liners) don't need a
#   script file at all.
# ============================================================================
