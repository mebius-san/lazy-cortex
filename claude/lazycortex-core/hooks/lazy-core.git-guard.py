#!/usr/bin/env python3
"""Pre/PostToolUse hook: serialize git staging across Claude Code sessions.

Fires on:
- ``Bash`` tool calls — command starts with `git add|rm|mv|reset|commit`.
- ``mcp__git__git_add|reset|commit`` MCP tool calls.

Hook satisfies the lazy-core.hook-writing § 1–8 contract:
  § 1 script discipline · § 2 trigger gating · § 3 branch determinism
  § 4 no-dirty-tree · § 5 no-foreign-staged · § 6 auto-commit loop guard
  § 7 transactional skip · § 8 logging
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Locate the helper module relative to this script.
_HOOK_DIR = Path(__file__).resolve().parent
_BIN_DIR = _HOOK_DIR.parent / "bin"
sys.path.insert(0, str(_BIN_DIR))
import staging_lock  # noqa: E402

# --- Tool / command gating ----------------------------------------------------

_GIT_INDEX_VERBS_RE = re.compile(r"^\s*git\s+(add|rm|mv|reset|commit)\b")
_MCP_INDEX_TOOLS = {
    "mcp__git__git_add",
    "mcp__git__git_reset",
    "mcp__git__git_commit",
}
_DIAGNOSTIC_ONLY_VERBS = {"commit"}     # PreToolUse: log, never block.
_RELEASE_VERBS = {"commit", "reset"}    # PostToolUse: maybe release.


def _gate(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    """Return (relevant, verb). verb in {add, rm, mv, reset, commit}."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        m = _GIT_INDEX_VERBS_RE.match(cmd)
        if not m:
            return False, ""
        return True, m.group(1)
    if tool_name in _MCP_INDEX_TOOLS:
        return True, tool_name.rsplit("_", 1)[-1]
    return False, ""


def _repo_root() -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out) if out else None


def _emit_deny(reason: str) -> None:
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"lazy-core.git-guard: {reason}",
        }
    }, sys.stdout)


def _emit_context(msg: str, event: str = "PostToolUse") -> None:
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": f"lazy-core.git-guard: {msg}",
        }
    }, sys.stdout)


def main() -> int:
    # § 1 — defensive JSON parse; never crash.
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    is_post = "tool_response" in hook_input

    # § 2 — trigger gating.
    relevant, verb = _gate(tool_name, tool_input)
    if not relevant:
        return 0

    repo = _repo_root()
    if repo is None:
        return 0

    cfg = staging_lock.load_config(repo)
    if not cfg.enabled:
        return 0

    session_id = staging_lock.resolve_session_id()

    if is_post:
        return _handle_post(repo, session_id, verb)
    return _handle_pre(repo, session_id, verb, cfg)


def _handle_pre(repo: Path, session_id: str, verb: str, cfg) -> int:
    # Diagnostic-only verbs: never block; emit context if peer holds.
    if verb in _DIAGNOSTIC_ONLY_VERBS:
        peer = staging_lock.inspect(repo)
        if peer and peer.session_id != session_id:
            age = int(__import__("time").time() - peer.started_at)
            _emit_context(
                f"peer session {peer.session_id} holds the staging lock on {peer.branch} "
                f"(PID {peer.pid}, {age}s old) — proceeding with this commit anyway.",
                event="PreToolUse",
            )
        return 0

    # Acquiring verbs: try the lock.
    res = staging_lock.acquire(repo, session_id, cfg)
    if res.status == "refused":
        _emit_deny(res.message)
    return 0


def _handle_post(repo: Path, session_id: str, verb: str) -> int:
    if verb not in _RELEASE_VERBS:
        return 0
    staging_lock.release_if_index_empty(repo, session_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
