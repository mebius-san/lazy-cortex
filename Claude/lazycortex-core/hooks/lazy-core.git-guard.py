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


def _log_event(repo: Path, kind: str, **fields) -> None:
    """Write a markdown log entry per .claude/rules/lazy-log.logging.md."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = repo / ".logs" / "claude" / "lazy-core.git-guard"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{ts}.md"

    try:
        sha = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        sha = "no-git"
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        branch = "no-git"

    peer = fields.pop("peer", None)
    body_lines = [f"# lazy-core.git-guard\n", "## Actions\n"]
    body_lines.append(f"- kind: {kind}\n")
    for k, v in fields.items():
        body_lines.append(f"- {k}: {v}\n")
    if peer is not None:
        body_lines.append(
            f"- peer: session={peer.session_id} pid={peer.pid} "
            f"host={peer.host} branch={peer.branch} started_at={peer.started_at}\n"
        )
    body_lines.append("\n## Result\n")
    body_lines.append(f"- {kind}\n")

    log_path.write_text(
        "---\n"
        f"git_sha: {sha}\n"
        f"git_branch: {branch}\n"
        f"date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"input: kind={kind}\n"
        "---\n\n"
        + "".join(body_lines)
    )


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
            _log_event(repo, "diagnostic_peer_lock", peer=peer, verb=verb)
        return 0

    # Acquiring verbs: try the lock.
    res = staging_lock.acquire(repo, session_id, cfg)
    _log_event(
        repo,
        kind=res.status,
        peer=res.peer,
        verb=verb,
        break_reason=res.break_reason,
        waited_seconds=res.waited_seconds,
    )
    if res.status == "refused":
        _emit_deny(res.message)
    return 0


def _handle_post(repo: Path, session_id: str, verb: str) -> int:
    if verb not in _RELEASE_VERBS:
        return 0
    res = staging_lock.release_if_index_empty(repo, session_id)
    _log_event(repo, kind="release", verb=verb, release_reason=res.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
