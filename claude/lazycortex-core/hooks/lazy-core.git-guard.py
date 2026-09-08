#!/usr/bin/env python3

"""
Pre/PostToolUse + Stop/SubagentStop hook guarding the shared git index against agent sessions.

Two independent behaviours, selected per repo by `lazy.settings.json["git"]`:

- `pathspec_enabled` (default) — the index belongs to the operator. Commits must name their
  paths; `git add` may only register an intent-to-add; `git rm` / `git mv` are refused. A commit
  additionally requires an index free of staged content (intent-to-add entries aside): the hook
  waits out a short window and then denies, and after a commit ran it alarms when staged content
  is still present — the signature of the shared index swapped for a partial commit's temporary
  index. After a pull / merge / rebase it likewise alarms when the staged content is exactly a
  lagging index — the worktree matching `HEAD` on every staged path. The lock machinery stays
  dormant, and the Stop branch never nags (a non-empty index is operator parking, not the
  session's unfinished work).
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
import os
import re
import subprocess
import sys
import time
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
import index_guard  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import hook_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from constants import HookKey, HookName  # noqa: E402


# --- Tool / command gating ----------------------------------------------------

_GIT_INDEX_VERBS_RE = re.compile(r"^\s*git\s+(add|rm|mv|reset|commit|checkout|restore)\b")
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
_DENY_FILE_CHECKOUT = (
  "`git checkout <tree-ish> -- <path>` writes the restored content into the operator's index as "
  "well as the worktree, which claims an index that is not yours. Use `git restore --worktree "
  "-- <path>` (restores from the index, index untouched) or `git restore --source=<tree-ish> "
  "--worktree -- <path>` (restores from a revision, index untouched). Reverting your own edit "
  "by hand with `Edit` is safer still when the file's pre-edit cleanliness is unproven."
)
_DENY_RESTORE_STAGED_SOURCE = (
  "`git restore --staged --source=<tree-ish>` writes that revision's content into the operator's "
  "index — that is staging, not un-staging. Drop `--source` to un-stage (equivalent to `git "
  "reset -- <path>`), or drop `--staged` to touch the worktree alone."
)
_DENY_UNPARSEABLE = (
  "this command could not be parsed, so the guard cannot tell whether it snapshots the shared "
  f"index. Rephrase into the canonical form — {_REQUIRED_FORM}."
)
_DENY_MCP = (
  "the MCP git tools cannot carry a pathspec, so they always snapshot the whole shared index. "
  f"Use Bash instead — {_REQUIRED_FORM}."
)
_DENY_DIRTY_INDEX = (
  "the shared git index is not clean, and a session commit must not run over staged content — "
  "everything staged belongs to the operator: parked work, an intentional untrack, or a swapped "
  "index. Stop and escalate to the operator; do not touch the index yourself, and do not retry "
  "until `git diff --cached` is empty."
)
_POST_SWAP_ALARM = (
  "ALARM — the index is non-empty right after this commit, but the clean-index precondition held "
  "before it ran. The shared `.git/index` was likely swapped by the partial commit's temporary "
  "index. Surface this to the operator now; the cure is `git reset` (rebuilds the index from "
  "HEAD, worktree untouched), run by the operator — never by the session. Run no further git "
  "index operations until it is resolved."
)
_POST_LAG_ALARM = (
  "ALARM — staged content right after this pull/merge/rebase, and every staged path's worktree "
  "file matches HEAD: the shared `.git/index` lagged behind the fast-forward (an index write "
  "lost a race), nobody staged anything. Surface this to the operator now; the cure is `git "
  "reset` (rebuilds the index from HEAD, worktree untouched), run by the operator — never by "
  "the session. Run no further git index operations until it is resolved."
)

# --- Clean-index precondition ------------------------------------------------

# Total time the precondition polls a dirty index before denying, and the pause between probes.
# The env variable is an operator-facing override of the wait window — shorten it to fail fast
# or stretch it for a slow staging workflow; an unparseable value falls back to the default.
_DIRTY_INDEX_WAIT_ENV = "LAZYCORTEX_GIT_GUARD_WAIT_SECONDS"
_DIRTY_INDEX_WAIT_SECONDS = 15.0
_DIRTY_INDEX_POLL_SECONDS = 1.0


def _gate(tool_name: str, tool_input: dict) -> tuple[bool, str]:
  """
  Classify a tool call as relevant or irrelevant to the staging-lock contract.

  Args:
    tool_name: The Claude Code tool identifier (e.g. `Bash`, `mcp__git__git_add`).
    tool_input: The tool's input payload as delivered by Claude Code.

  Returns:
    A tuple `(relevant, verb)` where `relevant` is True when the call touches the git index and
    `verb` is one of `add`, `rm`, `mv`, `reset`, `commit`, `checkout`, `restore` (empty string
    when irrelevant).
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

  # guard: a linked worktree has its own index — the shared-index premise of both rows fails,
  # so the discipline does not apply to an isolated job staging there. After the kill-switch,
  # so a disabled repo never pays the two rev-parse spawns.
  if _in_linked_worktree(repo):
    return 0

  # Pathspec row: the index belongs to the operator, the lock machinery stays dormant.
  if cfg.pathspec_enabled:
    # after a commit ran, verify the index survived it; before, apply the discipline
    if is_post:
      return _handle_post_pathspec(repo, tool_name, tool_input)
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
      age = int(time.time() - peer.started_at)
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
  # heal a sync-displaced index before judging anything — a resurrected pre-commit index
  # otherwise reads as operator-staged content and denies an innocent commit; the guard is a
  # no-op when no conflicted copy exists, and never touches a mid-operation repository
  try:
    index_guard.guard_index(repo)
  except OSError:
    # guard: a heal failure must never block the tool call the hook is judging
    pass

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


def _handle_post_pathspec(repo: Path, tool_name: str, tool_input: dict) -> int:
  """
  Apply the PostToolUse branch of the pathspec discipline — the index-health alarm.

  The clean-index precondition guarantees a session commit started over an index free of staged
  content, so staged content present right after one is the signature of the shared index being
  swapped for the partial commit's temporary index. After a pull / merge / rebase the same probe
  catches a lagging index — staged paths whose worktree files match HEAD mean the index write
  lost a race to the fast-forward, not that anyone staged. This branch only diagnoses; it never
  blocks and never touches the index itself.

  Args:
    repo: Absolute path to the repository root.
    tool_name: The Claude Code tool identifier.
    tool_input: The tool's input payload as delivered by Claude Code.

  Returns:
    Always 0; the alarm is signaled via the emitted JSON payload.
  """

  # Domain(guard.git-staging):
  # # Partial commit runs against a temporary index
  # A commit that names explicit paths builds a temporary index holding only those paths, computes
  # the commit against it, then discards the temporary file, leaving the real index untouched. On a
  # crash mid-commit, or a race where another party touches the shared index at the same moment,
  # that temporary file can end up written into place as the real index instead of being discarded.
  # The worktree is never touched by this failure — only the index is corrupted — so the visible
  # symptom is that nearly every tracked file now reads as staged for deletion, even though the
  # file itself is still present and unchanged on disk.

  # guard: the index-writing MCP tools are denied at Pre on this row — no commit ever ran
  # waiver: external Claude Code tool name, not a domain key
  if tool_name != "Bash":
    return 0
  # waiver: external-format tool-input field name, not an internal key
  segments = git_cmdline.parse_segments(tool_input.get("command", ""))
  # guard: untokenisable command — nothing to attribute a commit to, stay silent at Post
  if segments is None:
    return 0
  # waiver: git CLI vocabulary, not a domain constant
  commit_ran = any(
    seg.verb == "commit" and (seg.repo_dir is None or _targets_this_repo(repo, seg.repo_dir))
    for seg in segments
  )
  # waiver: git CLI vocabulary, not a domain constant
  sync_ran = any(
    seg.verb in ("pull", "merge", "rebase")
    and (seg.repo_dir is None or _targets_this_repo(repo, seg.repo_dir))
    for seg in segments
  )
  # guard: only a commit or a history-sync verb against this repo can leave the index behind
  if not commit_ran and not sync_ran:
    return 0
  git_dir = _git_dir(repo)
  # guard: mid merge / rebase / cherry-pick a full index is legitimate (the verb may have failed)
  if git_dir is not None and _mid_operation(git_dir):
    return 0
  staged = _content_staged_paths(repo)
  # guard: index is clean — the verb left it exactly as it found it
  if not staged:
    return 0
  # a commit runs over a precondition-checked index, so any leftover is the swap signature
  if commit_ran:
    _emit_context(_POST_SWAP_ALARM)
    return 0

  # a sync verb alarms only on the lag signature — worktree identical to HEAD for every staged
  # path; anything else may be the operator's parked stage riding across the sync
  if _worktree_matches_head(repo, staged):
    _emit_context(_POST_LAG_ALARM)
    return 0

  # parked operator content rode across the sync verb — none of the session's business
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


def _names_existing_path(repo: Path, segment: git_cmdline.GitSegment) -> bool:
  """
  Report whether any positional argument names a path that exists in the repository.

  `git_cmdline.parse_segments` drops the `--` separator, so a revision and a pathspec arrive in
  one positional tuple. Existence in the worktree is what tells a file-targeting invocation
  (`git checkout HEAD -- a.md`) from a branch-targeting one (`git checkout main`) — a branch name
  is not a path on disk, while the pathspec of a restore-a-file call is.

  Args:
    repo: Absolute path to the repository root.
    segment: One parsed git invocation from the command line.

  Returns:
    True when at least one positional argument resolves to an existing file or directory.
  """
  return any((repo / p).exists() for p in segment.pathspecs)


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
  # waiver: git CLI vocabulary, not a domain constant
  if segment.verb == "add":
    # guard: an `add` is legal as intent-to-add, or — mid merge / rebase / cherry-pick — when
    # every path it names is an unmerged entry: `git add` is git's only verb for recording a
    # resolved conflict, so denying it strands the operation; any other path still parks content
    if not git_cmdline.adds_content(segment) or _resolves_conflicts_only(repo, segment):
      return None
    return _DENY_ADD
  # guard: both verbs stage as a side effect
  if segment.verb in _AUTO_STAGING_VERBS:
    return _DENY_AUTO_STAGING
  # guard: a file-targeting checkout rewrites the index entry alongside the worktree file. A
  # branch-targeting one does not name a path at all, so an existing path among the positionals is
  # what separates the two — `git checkout main` passes, `git checkout HEAD -- a.md` does not.
  # waiver: git CLI vocabulary, not a domain constant
  if segment.verb == "checkout":
    return _DENY_FILE_CHECKOUT if _names_existing_path(repo, segment) else None
  # guard: `--staged` alone un-stages (the operator's own escape hatch, like `reset`); paired with
  # `--source` it writes a revision's content INTO the index, which is staging.
  # waiver: git CLI vocabulary, not a domain constant
  if segment.verb == "restore":
    staged_from_source = "--staged" in segment.flags and "--source" in segment.flags
    return _DENY_RESTORE_STAGED_SOURCE if staged_from_source else None
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
  # guard: every committed path is named explicitly — the clean-index precondition still applies
  if not git_cmdline.is_indexful_commit(segment):
    return _await_clean_index(repo)
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


def _in_linked_worktree(cwd: Path) -> bool:
  """
  Return True when `cwd` sits inside a linked git worktree rather than the primary checkout.

  A linked worktree has its own index, so the shared-index premise behind both the pathspec
  discipline and the staging-window mutex does not hold there — an isolated expert job staging
  in its worktree contends with nobody.

  Args:
    cwd: Directory to resolve from.

  Returns:
    True when the resolved `--git-dir` differs from `--git-common-dir`; False otherwise,
    including when either resolution fails.
  """
  # `--path-format=absolute` would need git >= 2.31 (the marketplace-wide git floor is 2.10), so both
  # possibly-relative results are resolved against cwd before comparison instead
  # waiver: git CLI vocabulary, not domain constants
  own = _git_at(cwd, "rev-parse", "--git-dir")
  # waiver: git CLI vocabulary, not domain constants
  common = _git_at(cwd, "rev-parse", "--git-common-dir")
  # guard: resolution failed — treat as the primary checkout so the guard stays in force
  if own.returncode != 0 or common.returncode != 0:
    return False
  own_path = Path(own.stdout.strip())
  common_path = Path(common.stdout.strip())
  # relative outputs resolve against the directory the probe ran in
  if not own_path.is_absolute():
    own_path = (cwd / own_path).resolve()
  if not common_path.is_absolute():
    common_path = (cwd / common_path).resolve()
  return own_path.resolve() != common_path.resolve()


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


def _resolves_conflicts_only(repo: Path, segment: git_cmdline.GitSegment) -> bool:
  """
  Report whether a content-staging `git add` only records resolved conflicts of an operation in flight.

  Args:
    repo: Absolute path to the repository root.
    segment: One parsed `git add` invocation.

  Returns:
    True when the repo is mid merge / rebase / cherry-pick / revert and every path the segment
    names is currently an unmerged index entry; False otherwise, including for an `add` that
    names no path at all.
  """
  git_dir = _git_dir(repo)
  # guard: outside a transactional operation there are no conflicts to resolve
  if git_dir is None or not _mid_operation(git_dir) or not segment.pathspecs:
    return False
  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(repo, "ls-files", "--unmerged")
  # guard: git could not list the index — nothing is proven unmerged, so nothing passes
  if r.returncode != 0:
    return False
  # `ls-files --unmerged` prints one `<mode> <sha> <stage>\t<path>` line per conflict stage
  unmerged = { line.split("\t", 1)[1] for line in r.stdout.splitlines() if "\t" in line }
  return all(os.path.normpath(p) in unmerged for p in segment.pathspecs)


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


def _content_staged_paths(cwd: Path) -> list[str]:
  """
  Return the staged paths that carry content — intent-to-add registrations excluded.

  Args:
    cwd: Directory to check; must be inside the repository of interest.

  Returns:
    List of repo-relative paths whose index entry differs from `HEAD` by actual content. An
    intent-to-add entry (`git add -N`) stages nothing and is never listed; on a git too old for
    the excluding flag the full staged list is returned instead, intent-to-add entries included.
    Empty list when the index is clean.
  """

  # Domain(guard.git-staging):
  # # Intent-to-add is invisible to the staged-content probe
  # An intent-to-add registration stages no content — it only records that a path now exists — so
  # it must never count as staged content when judging whether an index is clean. Modern git can be
  # asked to leave such entries out of a diff against the index; git older than the version that
  # introduced that exclusion has no way to leave them out, so on that older git an intent-to-add
  # entry counts as staged content instead. The fallback is stricter, never looser, than the
  # intended rule.

  # Modern git omits intent-to-add entries from `diff --cached` by itself; the flag pins that
  # behaviour on the 2.11..2.27 range where they would otherwise appear.
  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(cwd, "diff", "--cached", "--name-only", "--ita-invisible-in-index")
  # guard: the flag postdates the 2.10 git floor — on the one minor below it, retry without the
  # flag (stricter: intent-to-add entries then count as content) rather than fail
  if r.returncode != 0:
    return _staged_paths(cwd)
  return [ line for line in r.stdout.splitlines() if line.strip() ]


def _worktree_matches_head(cwd: Path, paths: list[str]) -> bool:
  """
  Report whether every given path's worktree file is identical to its `HEAD` version.

  Args:
    cwd: Directory to check; must be inside the repository of interest.
    paths: Repo-relative paths to compare; must be non-empty.

  Returns:
    True when `HEAD` and the worktree agree on every path — the staged entries for them are
    then the only divergence, the lagging-index signature. False on any real worktree
    difference, and on a git failure (a probe that cannot prove the signature must not alarm).
  """

  # Domain(guard.git-staging):
  # # A fast-forward can leave the shared index behind
  # A fast-forward rewrites the branch tip, the worktree, and the index together. When another
  # party writes the shared index file at the same moment, the pulled entries can be lost from
  # the index while the tip and the worktree already carry the new state. The visible symptom is
  # staged content nobody staged, reverting exactly the pulled changes, while every affected
  # file on disk is identical to the committed state.

  # waiver: git CLI vocabulary, not domain constants
  r = _git_at(cwd, "diff", "--quiet", "HEAD", "--", *paths)
  return r.returncode == 0


def _await_clean_index(repo: Path) -> str | None:
  """
  Enforce the clean-index precondition for one explicit-path commit, waiting out a busy operator.

  Polls the index for a bounded window so a commit racing the tail of an operator's staging
  burst can proceed once the index empties; a window of zero checks exactly once.

  Notes:
    - Blocks the calling hook for up to the wait window (15 s by default) while staged content
      remains, sleeping between probes.
    - Reads the `LAZYCORTEX_GIT_GUARD_WAIT_SECONDS` environment variable as an override of the
      wait window.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    The refusal reason when staged content remains after the wait window, or None when the
    index is (or becomes) free of staged content.
  """

  # Domain(guard.git-staging):
  # # Clean-index precondition around a session commit
  # A session never stages content itself, so a session-issued commit must start from an index free
  # of staged content — anything already staged there belongs to someone else and must not be swept
  # into the commit. When a dirty index blocks a commit, the refusal escalates to the operator without
  # prescribing a recovery command: staged content may be the operator's parked work, an intentional
  # untrack, or a swapped index, and a session has no way to tell these apart. Finding staged content
  # immediately after a session commit ran is the signature that the shared index was swapped for the
  # partial commit's own temporary index, rather than genuinely dirtied by a peer in the meantime. The
  # cure is to rebuild the index from the last commit, which leaves the worktree untouched — but that
  # recovery is the operator's move alone; a session only raises the alarm and never runs it.

  # Resolve the wait window, honouring the test-harness override.
  try:
    wait = float(os.environ.get(_DIRTY_INDEX_WAIT_ENV, _DIRTY_INDEX_WAIT_SECONDS))
  except ValueError:
    wait = _DIRTY_INDEX_WAIT_SECONDS

  # Poll until the index frees up or the window closes.
  deadline = time.monotonic() + wait
  while True:
    # guard: no staged content — the precondition holds
    if not _content_staged_paths(repo):
      return None
    remaining = deadline - time.monotonic()
    # guard: window closed with content still staged
    if remaining <= 0:
      return _DENY_DIRTY_INDEX
    time.sleep(min(_DIRTY_INDEX_POLL_SECONDS, remaining))


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

  Belongs to the mutex row only. Skips silently when the operator cwd is outside a git repo or
  inside a linked worktree (whose index is private), when the repo is mid-transaction (merge /
  rebase / cherry-pick / revert), when the per-repo kill-switch is off, when the pathspec row is
  active, when the index is already clean, or when the staged content belongs to another
  session. Otherwise emits a `decision: block` payload with a preview of the
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
  # guard: a linked worktree's index is private — nothing here contends with the operator
  if _in_linked_worktree(cwd):
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
