#!/usr/bin/env python3

"""
Pre/PostToolUse + Stop/SubagentStop hook guarding the shared git index against agent sessions.

Two independent behaviours, selected per repo by `lazy.settings.json["git"]`:

- `pathspec_enabled` (default) — the index belongs to the operator. Commits must name their
  paths; `git add` may only register an intent-to-add; `git rm` / `git mv` are refused. The lock
  machinery stays dormant, and the Stop branch never nags (a non-empty index is operator
  parking, not the session's unfinished work).
- `mutex_enabled` without `pathspec_enabled` — the staging-window mutex: serialize staging
  across sessions and refuse to end a turn with a non-empty index.

`pathspec_enabled` supersedes the mutex rather than composing with it — an intent-to-add entry
would otherwise hold a lock the "index empty after commit" release check can never clear.

Fires on:
- `Bash` tool calls invoking `git`.
- `mcp__git__git_add|reset|commit` MCP tool calls.
- `Stop` and `SubagentStop` lifecycle events.

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
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import staging_lock  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_cmdline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import hook_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from constants import HookKey, HookName  # noqa: E402


# --- Tool / command gating ----------------------------------------------------

_GIT_INDEX_VERBS_RE = re.compile(r"^\s*git\s+(add|rm|mv|reset|commit)\b")
# Coarse filter for the pathspec branch — a git invocation anywhere in the command, chained or
# prefixed. The precise classification is `git_cmdline.parse_segments`.
_GIT_WORD_RE = re.compile(r"\bgit\b")
# Fallback classifier for a command the tokeniser choked on: only a shape that plainly reaches an
# index verb is worth failing closed over. A python one-liner that merely mentions git is not.
_GIT_INDEX_VERB_SEARCH_RE = re.compile(
  r"\bgit\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+(?:add|rm|mv|commit)\b"
)
_MCP_INDEX_TOOLS = {
  "mcp__git__git_add",
  "mcp__git__git_reset",
  "mcp__git__git_commit",
}
# PreToolUse: log, never block.
_DIAGNOSTIC_ONLY_VERBS = { "commit" }
# PostToolUse: maybe release.
_RELEASE_VERBS = { "commit", "reset" }

# --- Pathspec-row vocabulary --------------------------------------------------

# Verbs the pathspec row refuses outright — both stage as a side effect.
_AUTO_STAGING_VERBS = { "rm", "mv" }

_REQUIRED_FORM = "commit with explicit paths: `git commit -m \"...\" -- <path> <path>`"

_DENY_COMMIT = (
  "this commit would snapshot the whole shared index, sweeping in whatever the operator has "
  f"parked there. {_REQUIRED_FORM} — never `-a`, `.`, `:/`, or a bare commit. "
  "This deny means the pathspec discipline was broken; rephrase, do not retry or bypass."
)
_DENY_COMMIT_DIR = (
  "a directory pathspec covers whatever the operator parked underneath it. Name the individual "
  f"files instead — {_REQUIRED_FORM}."
)
_DENY_ADD = (
  "the git index belongs to the operator; staging content into it is not yours to do. Register "
  "a new path with `git add -N <path>` (stages no content), then commit it explicitly: "
  f"{_REQUIRED_FORM}."
)
_DENY_AUTO_STAGING = (
  "`git rm` / `git mv` auto-stage, which claims the operator's index. Use Bash `rm` / `mv` in "
  f"the worktree, then {_REQUIRED_FORM} naming the old and new paths."
)
_DENY_UNPARSEABLE = (
  "this command could not be parsed, so the guard cannot tell whether it snapshots the shared "
  f"index. Rephrase into the canonical form — {_REQUIRED_FORM}."
)
_DENY_MCP = (
  "the MCP git tools cannot carry a pathspec, so they always snapshot the whole shared index. "
  f"Use Bash instead — {_REQUIRED_FORM}."
)


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
  # Enablement gate — first action, before stdin/git. An expert spawn short-circuits here via a
  # pure env check; an interactive session skips only when the operator disabled this hook.
  # guard: hook disabled in the current context
  if not hook_gate.is_enabled(HookName.GIT_GUARD):
    return 0

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

  # § 2 — trigger gating. Coarse here (any git invocation); each branch narrows it further.
  # guard: tool call cannot touch the git index
  if not _invokes_git(tool_name, tool_input):
    return 0

  # Resolve the repository root; bail when not inside a repo.
  repo = _repo_root()
  # guard: not inside a git repository
  if repo is None:
    return 0

  # Load the per-repo config and respect the master kill-switch.
  cfg = staging_lock.load_config(repo)
  # guard: guard disabled for this repo
  if not cfg.enabled:
    return 0

  # Pathspec row: the index belongs to the operator, the lock machinery stays dormant.
  if cfg.pathspec_enabled:
    # guard: nothing to release — the pathspec row never takes a lock
    if is_post:
      return 0
    return _handle_pre_pathspec(repo, tool_name, tool_input)

  # guard: mutex row disabled too — guard silent
  if not cfg.mutex_enabled:
    return 0

  # Mutex row: classify by leading verb and dispatch by lifecycle phase.
  relevant, verb = _gate(tool_name, tool_input)
  # guard: tool call does not touch the git index
  if not relevant:
    return 0
  session_id = staging_lock.resolve_session_id()

  # dispatch by lifecycle phase — Pre takes the lock, Post may release it
  if is_post:
    return _handle_post(repo, session_id, verb)
  return _handle_pre(repo, session_id, verb, cfg)


def _invokes_git(tool_name: str, tool_input: dict) -> bool:
  """
  Report whether a tool call could reach git at all.

  Args:
    tool_name: The Claude Code tool identifier (e.g. `Bash`, `mcp__git__git_add`).
    tool_input: The tool's input payload as delivered by Claude Code.

  Returns:
    True for an index-mutating MCP tool, or a Bash command mentioning `git` anywhere — chained,
    prefixed, or leading. False otherwise.
  """
  # waiver: external Claude Code tool name, not a domain key
  if tool_name == "Bash":
    # waiver: external-format tool-input field name, not an internal key
    return bool(_GIT_WORD_RE.search(tool_input.get("command", "")))
  return tool_name in _MCP_INDEX_TOOLS


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


def _handle_pre_pathspec(repo: Path, tool_name: str, tool_input: dict) -> int:
  """
  Apply the PreToolUse branch of the pathspec discipline for one tool call.

  Every git invocation in the command is classified independently, so a chained
  `git add x && git commit -m y` is caught on its first offending segment. An unparseable
  command fails closed — the caller can always rephrase into the canonical form.

  Args:
    repo: Absolute path to the repository root.
    tool_name: The Claude Code tool identifier.
    tool_input: The tool's input payload as delivered by Claude Code.

  Returns:
    Always 0; refusals are signaled via the emitted JSON payload.
  """
  # MCP branch: these tools cannot carry a pathspec, so only the harmless verb survives
  if tool_name in _MCP_INDEX_TOOLS:
    verb = tool_name.rsplit("_", 1)[-1]
    # guard: reset only ever removes entries — the operator may need it mid-session
    # waiver: git CLI vocabulary, not a domain constant
    if verb == "reset":
      return 0
    _emit_deny(_DENY_MCP)
    return 0

  # Bash branch: every git invocation in the command line is judged on its own
  # waiver: external-format tool-input field name, not an internal key
  command = tool_input.get("command", "")
  segments = git_cmdline.parse_segments(command)
  # guard: command could not be tokenised — fail closed, but only when it plainly reaches an
  # index verb; an unrelated command that merely mentions git is not this hook's business
  if segments is None:
    # guard: no index verb in sight — nothing to refuse
    if not _GIT_INDEX_VERB_SEARCH_RE.search(command):
      return 0
    _emit_deny(_DENY_UNPARSEABLE)
    return 0
  for segment in segments:
    reason = _pathspec_violation(repo, segment)
    # guard: this segment breaks the discipline — refuse the whole command
    if reason:
      _emit_deny(reason)
      return 0
  return 0


def _targets_this_repo(repo: Path, repo_dir: str) -> bool:
  """
  Report whether a `git -C <dir>` invocation still targets the repository this hook guards.

  Args:
    repo: Absolute path to the repository root the hook resolved for the current call.
    repo_dir: The `-C` value taken from the command line, absolute or relative to the cwd.

  Returns:
    True when `repo_dir` resolves into the same repository, False when it names a different
    checkout. An unresolvable path counts as different — the hook then leaves it alone rather
    than judging a repository it cannot see.
  """
  # waiver: git CLI vocabulary, not domain constants
  probe = _git_at(Path(repo_dir) if Path(repo_dir).is_absolute() else Path.cwd() / repo_dir,
                  "rev-parse", "--show-toplevel")
  # guard: cannot resolve the target — treat as a foreign repository
  if probe.returncode != 0:
    return False
  return Path(probe.stdout.strip()).resolve() == repo.resolve()


def _pathspec_violation(repo: Path, segment: git_cmdline.GitSegment) -> str | None:
  """
  Return the reason one git invocation breaks the pathspec discipline, or None when it is legal.

  Args:
    repo: Absolute path to the repository root.
    segment: One parsed git invocation from the command line.

  Returns:
    A human-readable refusal reason, or None when the invocation leaves the operator's index
    alone.
  """
  # guard: `git -C <dir>` targets a different checkout — that repository's own settings govern
  # it, not this one's. A publish mirror or a sibling clone is not this operator's index.
  if segment.repo_dir is not None and not _targets_this_repo(repo, segment.repo_dir):
    return None
  # guard: an `add` is legal only as intent-to-add — staging content claims the operator's index
  # waiver: git CLI vocabulary, not a domain constant
  if segment.verb == "add":
    return None if not git_cmdline.adds_content(segment) else _DENY_ADD
  # guard: both verbs stage as a side effect
  if segment.verb in _AUTO_STAGING_VERBS:
    return _DENY_AUTO_STAGING
  # guard: every other verb (reset, push, status, ...) leaves the index to the operator
  # waiver: git CLI vocabulary, not a domain constant
  if segment.verb != "commit":
    return None
  git_dir = _git_dir(repo)
  # guard: mid merge / rebase / cherry-pick — git itself refuses a partial commit there
  if git_dir is not None and _mid_operation(git_dir):
    return None
  # guard: a directory pathspec sweeps in whatever is parked beneath it
  if any((repo / p).is_dir() for p in segment.pathspecs):
    return _DENY_COMMIT_DIR
  # guard: every committed path is named explicitly
  if not git_cmdline.is_indexful_commit(segment):
    return None
  # guard: an amend against a clean index only rewrites the previous commit
  if git_cmdline.is_amend(segment) and not _staged_paths(repo):
    return None
  return _DENY_COMMIT


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
    cwd: Directory to resolve from — the repository root on the PreToolUse path, or the
      operator working directory reported by Claude Code at Stop event time.

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
    cwd: Directory to check — the repository root on the PreToolUse path, or the operator
      working directory reported by Claude Code at Stop event time.

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

  Belongs to the mutex row only. Skips silently when the operator cwd is outside a git repo,
  when the repo is mid-transaction (merge / rebase / cherry-pick / revert), when the per-repo
  kill-switch is off, when the pathspec row is active, or when the index is already clean.
  Otherwise emits a `decision: block` payload with a preview of the
  staged paths and the three recovery commands the operator can run.

  Args:
    payload: The Claude Code Stop hook payload parsed from stdin.

  Returns:
    Always 0; the block is signaled via the emitted JSON payload.
  """
  # the operator cwd is the only repo reference a Stop payload carries
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

  # this nag belongs to the mutex row alone — every other configuration ends the turn freely
  repo = Path(r.stdout.strip()).resolve()
  cfg = staging_lock.load_config(repo)
  # guard: guard disabled for this repo
  if not cfg.enabled:
    return 0
  # guard: on the pathspec row a non-empty index is operator parking, never this session's
  # unfinished work — the session never stages at all
  if cfg.pathspec_enabled:
    return 0
  # guard: mutex row disabled too
  if not cfg.mutex_enabled:
    return 0

  # only work this session staged is worth nagging about
  staged = _staged_paths(cwd)
  # guard: index is already clean
  if not staged:
    return 0
  lock = staging_lock.inspect(repo)
  # guard: staged content isn't this session's — a peer session or a manual/terminal stage owns
  # it, so ending this turn isn't leaving OUR work hanging. The Stop nag only fires when the
  # session that staged is the one about to stop.
  if lock is None or lock.session_id != staging_lock.resolve_session_id():
    return 0

  # bounded preview so a large index doesn't flood the operator-facing message
  preview = staged[: 10]
  more = len(staged) - len(preview)
  file_list = "\n".join(f"  {p}" for p in preview)
  if more > 0:
    file_list += f"\n  ... and {more} more"

  # block the turn and name the three ways out
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
