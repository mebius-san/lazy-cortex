#!/usr/bin/env python3
"""<Pre|Post>ToolUse hook: <one-line purpose>.

Fires on:
- ``<MatcherName>`` tool calls — <gate condition, e.g., command matches `git commit`>.
- (Add more matchers if registered in settings.json.)

Filters by inspecting the hook payload on stdin so the broad matcher in
settings.json can stay coarse while the in-script gate is precise.

Behavior:
- <Branch 1: when <gate fires>, this branch <writes/commits/emits-context>.>
- <Branch 2: when <other gate>, this branch is a no-op.>
- (Every branch terminates in a documented outcome — see lazy-core.hook-writing § 3.)

Gates (cross-cutting):
- <e.g., "Only runs inside a git repo with `claude/` at root.">
- <e.g., "Skips if HEAD diff is folder-notes-only — see § 5 loop guard.">

This template encodes the lazy-core.hook-writing § 1–8 contract:
  § 1 script discipline · § 2 trigger gating · § 3 branch determinism
  § 4 no-dirty-tree · § 5 no-foreign-staged · § 6 auto-commit loop guard
  § 7 transactional skip · § 8 logging

Delete the trailing AUTHORING NOTES block before saving; it is a guide, not
runtime documentation.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# § 6 LOOP GUARD — content-based bail (replace with the predicate that
# recognises THIS hook's own footprint; see lazy-core.hook-writing § 6 for
# the contract).
# ---------------------------------------------------------------------------
def _is_real_event(root: str) -> bool:
    """True iff the just-handled event is NOT this hook's own auto-commit.

    Time-based throttles and counter-based guards are not acceptable
    substitutes — they leak state across sessions and fail when the user
    reorders or amends commits. Use a content predicate.
    """
    return True  # ← replace with real predicate


# ---------------------------------------------------------------------------
# § 7 TRANSACTIONAL SKIP — never auto-commit during merge/rebase/cherry-pick.
# Contract: lazy-core.hook-writing § 7.
# ---------------------------------------------------------------------------
_TRANSACTIONAL_MARKERS = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
    "REBASE_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG",
)


def _in_transactional_state(root: str) -> bool:
    """True if a merge/rebase/cherry-pick/bisect is in progress."""
    try:
        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"], cwd=root, text=True
        ).strip()
    except subprocess.CalledProcessError:
        return False
    git_path = os.path.join(root, git_dir) if not os.path.isabs(git_dir) else git_dir
    return any(os.path.exists(os.path.join(git_path, m)) for m in _TRANSACTIONAL_MARKERS)


# ---------------------------------------------------------------------------
# § 1 EMIT — additionalContext (PostToolUse) or permissionDecision (PreToolUse).
# Pick one shape per branch; mixing is a bug.
# ---------------------------------------------------------------------------
def _context(msg: str, event: str = "PostToolUse") -> None:
    """Emit a non-blocking transcript message."""
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}},
        sys.stdout,
    )


def _deny(reason: str, event: str = "PreToolUse") -> None:
    """PreToolUse only — veto the in-flight tool call. Exit 0 still."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": f"<hook-name>: {reason}",
            }
        },
        sys.stdout,
    )


def main() -> int:
    # § 1 — defensive JSON-stdin parsing, never crash the trigger.
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # § 2 — TRIGGER GATING — broad matchers MUST be narrowed in-script.
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not re.match(r"\s*<command-prefix>\b", command):
            return 0
    elif tool_name == "<other-matcher>":
        # narrow this branch too (e.g. subagent_type for Agent).
        pass
    else:
        return 0

    # § 1 — bail outside git repo / wrong workspace shape.
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0
    if not os.path.isdir(os.path.join(root, "<expected-marker-dir>")):
        return 0

    # § 6 — LOOP GUARD must run before any work.
    if not _is_real_event(root):
        return 0

    # § 3 — BRANCH determinism — pick one outcome per branch:
    #   (a) emit additionalContext via _context() and return.
    #   (b) write file(s) AND commit them in same execution (§ 4).
    #   (c) no-op return 0.
    #
    # If your branch ends in a write, the same branch MUST end in the
    # matching commit. Use `-c core.hooksPath=/dev/null` on the inner git
    # commit to avoid re-entry into the hook chain.

    # ---- Example: write-then-commit branch ----
    # if not _in_transactional_state(root):
    #     subprocess.run(
    #         ["git", "-C", root, "-c", "core.hooksPath=/dev/null",
    #          "add", "--", "<path>"],
    #         check=True, capture_output=True,
    #     )
    #     subprocess.run(
    #         ["git", "-C", root, "-c", "core.hooksPath=/dev/null",
    #          "commit", "-m", "<chore: ...>"],
    #         check=True, capture_output=True,
    #     )

    # ---- Example: context-only branch ----
    # _context("<hook-name>: <one-line summary>")

    return 0


if __name__ == "__main__":
    sys.exit(main())


# ============================================================================
# AUTHORING NOTES — DELETE THIS BLOCK BEFORE SAVING
# ============================================================================
#
# Naming
#   File: <dot-namespace>.hook.py.
#   Register in settings.json: hooks.{Pre,Post}ToolUse[].matcher = "<MatcherName>"
#   with hooks[].command = python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<file>".
#
# Contract (lazy-core.hook-writing §§ 1–8)
#   § 1 Script discipline   — shebang, JSON-stdin, exit 0, hooksPath=/dev/null
#                             on inner git ops.
#   § 2 Trigger gating      — broad matcher in settings.json; in-script gate
#                             must be precise (re.match on command, etc.).
#   § 3 Branch determinism  — every branch documented; no fall-through to write.
#   § 4 No dirty-tree       — write paths must commit in same execution.
#   § 5 No foreign staged   — never use pathspec on `git commit` to filter the
#                             index; never stage-and-exit relying on outer
#                             commit to pick up.
#   § 6 Auto-commit loop    — content-based bail predicate (this template's
#                             _is_real_event); time/counter guards forbidden.
#   § 7 Transactional skip  — never auto-commit during merge/rebase/cherry-pick
#                             (this template's _in_transactional_state).
#   § 8 Logging             — log to ./.logs/claude/<hook-name>/<timestamp>.md
#                             per lazy-log.logging.
#
# Reference implementations
#   See lazy-core.hook-writing §§ 1–8 for worked patterns covering full
#   PostToolUse hooks (worker dispatch, auto-commit, loop guard, transactional
#   skip, index refresh) and PreToolUse hooks (deny / context emission /
#   write-and-restage rideshare).
#
# Out-of-scope
#   This template targets full hook scripts. Thin shims (a one-liner that
#   exec's another command) belong as inline `command` strings in
#   settings.json — no script file needed.
# ============================================================================
