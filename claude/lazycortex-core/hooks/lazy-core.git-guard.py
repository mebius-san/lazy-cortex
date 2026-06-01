#!/usr/bin/env python3

"""
Pre/PostToolUse + Stop/SubagentStop hook: serialize git staging across Claude Code sessions and
refuse to end a turn with a non-empty git index.

Fires on:
- `Bash` tool calls — command starts with `git add|rm|mv|reset|commit`.
- `mcp__git__git_add|reset|commit` MCP tool calls.
- `Stop` and `SubagentStop` lifecycle events — block when the git index is non-empty.

Hook satisfies the lazy-core.hook-writing § 1-8 contract:
  § 1 script discipline · § 2 trigger gating · § 3 branch determinism
  § 4 no-dirty-tree · § 5 no-foreign-staged · § 6 auto-commit loop guard
  § 7 transactional skip · § 8 logging
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import json
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Locate the helper module relative to this script.

_HOOK_DIR = Path(__file__).resolve().parent
_BIN_DIR = _HOOK_DIR.parent / "bin"
sys.path.insert(0, str(_BIN_DIR))
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import staging_lock  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from constants import HookKey  # noqa: E402


# --- Tool / command gating ----------------------------------------------------

_GIT_INDEX_VERBS_RE = re.compile(r"^\s*git\s+(add|rm|mv|reset|commit)\b")
_MCP_INDEX_TOOLS = {
  "mcp__git__git_add",
  "mcp__git__git_reset",
  "mcp__git__git_commit",
}
# PreToolUse: log, never block.
_DIAGNOSTIC_ONLY_VERBS = { "commit" }
# PostToolUse: maybe release.
_RELEASE_VERBS = { "commit", "reset" }


def _gate(tool_name: str, tool_input: dict) -> tuple[bool, str]:
  """
  Classify a tool call as relevant or irrelevant to the staging-lock contract.

  Args:
    tool_name: The Claude Code tool identifier (e.g. `Bash`, `mcp__git__git_add`).
    tool_input: The tool's input payload as delivered by Claude Code.

  Returns:
    A tuple `(relevant, verb)` where `relevant` is True when the call touches the git index and
    `verb` is one of `add`, `rm`, `mv`, `reset`, `commit` (empty string when irrelevant).
  """
  # Bash branch: match the command against the index-verb regex.
  # waiver: external Claude Code tool name, not a domain key
  if tool_name == "Bash":
    # waiver: external-format tool-input field name, not an internal key
    cmd = tool_input.get("command", "")
    m = _GIT_INDEX_VERBS_RE.match(cmd)
    # guard: command does not invoke an index-mutating git verb
    if not m:
      return False, ""
    return True, m.group(1)
  # MCP branch: derive the verb from the trailing segment of the tool name.
  if tool_name in _MCP_INDEX_TOOLS:
    return True, tool_name.rsplit("_", 1)[-1]
  return False, ""


def _repo_root() -> Path | None:
  """
  Return the absolute root of the current git repository, or None when unavailable.

  Returns:
    The repository root as a `Path`, or None when the current directory is not inside a git
    repository or the `git` binary is missing.
  """
  try:
    out = subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL, text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None
  return Path(out) if out else None


def _emit_deny(reason: str) -> None:
  """
  Emit a PreToolUse `deny` decision to stdout for the current tool call.

  Args:
    reason: Human-readable explanation of why the call is being denied; surfaced to the operator
      verbatim under the hook's identifying prefix.
  """
  json.dump({
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": f"lazy-core.git-guard: {reason}",
    }
  }, sys.stdout)


def _emit_context(msg: str, event: str = "PostToolUse") -> None:
  """
  Emit non-blocking diagnostic context to stdout for the current tool call.

  Args:
    msg: Human-readable diagnostic message; surfaced to the operator verbatim under the
      hook's identifying prefix.
    event: The Claude Code lifecycle event name to attach the context to. Defaults to
      `PostToolUse`.
  """
  json.dump({
    "hookSpecificOutput": {
      "hookEventName": event,
      "additionalContext": f"lazy-core.git-guard: {msg}",
    }
  }, sys.stdout)


def main() -> int:
  """
  Entry point for the hook script.

  Reads the Claude Code hook payload from stdin, dispatches to the Pre/PostToolUse or
  Stop/SubagentStop branch based on the event name (and the presence of `tool_response`), and
  writes any resulting decision or context to stdout. Tolerates malformed input and unsupported
  tool calls by silently returning 0 so the hook never crashes the trigger.

  Returns:
    The process exit code; always 0 for this hook (denials and stop-blocks are signaled via the
    JSON payload, not the exit status).
  """
  # § 1 — defensive JSON parse; never crash.
  try:
    hook_input = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    return 0

  # Stop / SubagentStop branch — separate event family, no tool_name.
  event_name = hook_input.get(HookKey.HOOK_EVENT_NAME, "")
  if event_name in ("Stop", "SubagentStop"):
    return _handle_stop(hook_input)

  # Extract the fields we care about from the hook payload.
  tool_name = hook_input.get(HookKey.TOOL_NAME, "")
  tool_input = hook_input.get(HookKey.TOOL_INPUT, {})
  # waiver: external-format hook-payload field name, not an internal key
  is_post = "tool_response" in hook_input

  # § 2 — trigger gating.
  relevant, verb = _gate(tool_name, tool_input)
  # guard: tool call does not touch the git index
  if not relevant:
    return 0

  # Resolve the repository root; bail when not inside a repo.
  repo = _repo_root()
  # guard: not inside a git repository
  if repo is None:
    return 0

  # Load the per-repo lock config and respect the kill-switch.
  cfg = staging_lock.load_config(repo)
  # guard: staging lock disabled for this repo
  if not cfg.enabled:
    return 0

  # Identify this session and dispatch by lifecycle phase.
  session_id = staging_lock.resolve_session_id()

  if is_post:
    return _handle_post(repo, session_id, verb)
  return _handle_pre(repo, session_id, verb, cfg)


def _handle_pre(repo: Path, session_id: str, verb: str, cfg: staging_lock.StagingConfig) -> int:
  """
  Apply the PreToolUse branch of the lock contract for one index-mutating tool call.

  Diagnostic-only verbs (`commit`) never block — they emit a context note when a peer session
  holds the lock and otherwise pass through. Acquiring verbs (`add`, `rm`, `mv`, `reset`) try to
  take the lock and emit a `deny` decision when the helper refuses.

  Args:
    repo: Absolute path to the repository root.
    session_id: The current Claude Code session identifier.
    verb: The git index verb extracted by `_gate`.
    cfg: The per-repo lock configuration loaded from `lazy.settings.json`.

  Returns:
    Always 0; refusals are signaled via the emitted JSON payload.
  """
  # Diagnostic-only verbs: never block; emit context if peer holds.
  if verb in _DIAGNOSTIC_ONLY_VERBS:
    peer = staging_lock.inspect(repo)
    if peer and peer.session_id != session_id:
      # waiver: stdlib module name for __import__, not a domain constant
      age = int(__import__("time").time() - peer.started_at)
      _emit_context(
        f"peer session {peer.session_id} holds the staging lock on {peer.branch} "
        f"(PID {peer.pid}, {age}s old) — proceeding with this commit anyway.",
        # waiver: external Claude Code hook-event name, not a domain key
        event = "PreToolUse",
      )
    return 0

  # Acquiring verbs: try the lock.
  res = staging_lock.acquire(repo, session_id, cfg)
  # waiver: cross-module AcquireStatus token (staging_lock Literal), not an internal key
  if res.status == "refused":
    _emit_deny(res.message)
  return 0


def _git_at(cwd: Path, *args: str) -> subprocess.CompletedProcess:
  """
  Run `git <args>` in `cwd`, capturing stdout/stderr and never raising.

  Args:
    cwd: Working directory to invoke `git` from. Must be inside the repo of interest.
    *args: Arguments passed to `git` verbatim (e.g. `"rev-parse"`, `"--git-dir"`).

  Returns:
    The completed-process record with `returncode`, `stdout`, and `stderr` populated. On any
    OS-level failure (missing cwd, missing `git`, timeout) a synthetic record with
    `returncode=128` (git's generic failure code) and empty output is returned, so callers can
    rely on the `returncode != 0` guard without `try/except`.
  """
  try:
    return subprocess.run(
      [ "git", *args ],
      cwd = str(cwd),
      capture_output = True,
      text = True,
      check = False,
      # waiver: inline numeric literal (subprocess timeout seconds), not a domain constant
      timeout = 3,
    )
  except (OSError, subprocess.SubprocessError):
    # waiver: inline numeric literal (git generic-failure exit code), not a domain constant
    return subprocess.CompletedProcess(args = [ "git", *args ], returncode = 128, stdout = "", stderr = "")


def _git_dir(cwd: Path) -> Path | None:
  """
  Resolve the absolute path of the git directory governing `cwd`.

  Args:
    cwd: Operator working directory reported by Claude Code at Stop event time.

  Returns:
    Absolute `Path` to the git dir (`.git`, a linked worktree dir, or a custom GIT_DIR), or None
    when `cwd` is not inside a git repository.
  """
  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(cwd, "rev-parse", "--git-dir")
  # guard: cwd is not inside a git repository
  if r.returncode != 0:
    return None
  p = Path(r.stdout.strip())
  return p if p.is_absolute() else (cwd / p).resolve()


def _mid_operation(git_dir: Path) -> bool:
  """
  Return True when the repo is in the middle of a merge / rebase / cherry-pick / revert.

  Args:
    git_dir: Absolute path to the active git directory (output of `_git_dir`).

  Returns:
    True when any of the well-known transactional markers exist under `git_dir`; False otherwise.
  """
  return any(
    (git_dir / name).exists()
    for name in (
      "MERGE_HEAD",
      "CHERRY_PICK_HEAD",
      "REVERT_HEAD",
      "rebase-merge",
      "rebase-apply",
    )
  )


def _staged_paths(cwd: Path) -> list[str]:
  """
  Return the list of repo-relative paths currently in the git index.

  Args:
    cwd: Operator working directory reported by Claude Code at Stop event time.

  Returns:
    List of staged paths in the order reported by `git diff --cached --name-only`. Empty list
    when the index is clean or when the `git` invocation failed.
  """
  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(cwd, "diff", "--cached", "--name-only")
  # guard: git invocation failed — treat as clean to avoid false positives
  if r.returncode != 0:
    return []
  return [ line for line in r.stdout.splitlines() if line.strip() ]


def _handle_stop(payload: dict) -> int:
  """
  Apply the Stop / SubagentStop branch — refuse to end the turn while the git index is non-empty.

  Skips silently when the operator cwd is outside a git repo, when the repo is mid-transaction
  (merge / rebase / cherry-pick / revert), when the per-repo kill-switch is off, or when the
  index is already clean. Otherwise emits a `decision: block` payload with a preview of the
  staged paths and the three recovery commands the operator can run.

  Args:
    payload: The Claude Code Stop hook payload parsed from stdin.

  Returns:
    Always 0; the block is signaled via the emitted JSON payload.
  """
  cwd = Path(payload.get("cwd") or ".").resolve()
  git_dir = _git_dir(cwd)
  # guard: not inside a git repository
  if git_dir is None:
    return 0
  # guard: mid merge / rebase / cherry-pick / revert
  if _mid_operation(git_dir):
    return 0
  # Respect the same per-repo kill-switch as the PreTool / PostTool branches.
  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(cwd, "rev-parse", "--show-toplevel")
  # guard: cannot resolve repo root — fail open
  if r.returncode != 0:
    return 0
  repo = Path(r.stdout.strip()).resolve()
  cfg = staging_lock.load_config(repo)
  # guard: staging lock disabled for this repo
  if not cfg.enabled:
    return 0
  staged = _staged_paths(cwd)
  # guard: index is already clean
  if not staged:
    return 0
  preview = staged[: 10]
  more = len(staged) - len(preview)
  file_list = "\n".join(f"  {p}" for p in preview)
  if more > 0:
    file_list += f"\n  ... and {more} more"
  reason = (
    "lazy-core.git-guard: staged files detected at end of turn. The turn must not end with "
    "anything in the git index — commit or unstage before stopping.\n\n"
    f"Staged ({len(staged)}):\n{file_list}\n\n"
    "Resolve with one of:\n"
    "  • commit them: `git commit -m \"...\"`\n"
    "  • unstage (keep working-tree changes): `git restore --staged <path>...`\n"
    "  • full unstage: `git reset HEAD --`"
  )
  json.dump({ "decision": "block", "reason": reason }, sys.stdout)
  return 0


def _handle_post(repo: Path, session_id: str, verb: str) -> int:
  """
  Apply the PostToolUse branch of the lock contract for one index-mutating tool call.

  Releases the lock when the verb is `commit` or `reset` and the resulting index is empty.
  Other verbs are no-ops at this phase.

  Args:
    repo: Absolute path to the repository root.
    session_id: The current Claude Code session identifier.
    verb: The git index verb extracted by `_gate`.

  Returns:
    Always 0.
  """
  # guard: only commit / reset can transition the index to empty
  if verb not in _RELEASE_VERBS:
    return 0
  staging_lock.release_if_index_empty(repo, session_id)
  return 0


if __name__ == "__main__":
  sys.exit(main())
