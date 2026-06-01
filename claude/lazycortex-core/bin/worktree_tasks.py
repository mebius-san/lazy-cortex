"""
Lifecycle for worktree-isolated code tasks: create, provision, poll, integrate, sweep.

A worktree-isolated task runs its unit of work on a dedicated `task-<id>` branch
inside an in-tree git worktree under `<repo>/<worktree_root>/task-<id>/`. The
manager creates the worktree off fresh base, provisions the gitignored local
config, registers the task in runtime state, and on completion reintegrates the
branch to base by auto-merge or pull request, then cleans up.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import os
import shutil
import subprocess
import time
from pathlib import Path

import runtime_state
from constants import StateKey, WorktreeEntryKey, WorktreeResult, WorktreeResultKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class WorktreeStartError(RuntimeError):
  """
  Raised when a worktree task cannot be created (git failure / branch-or-dir collision).
  """


class WorktreeTaskManager:
  """
  Owns the in-tree worktree lifecycle for `isolate: true` routine work units.

  Each work unit gets one `task-<id>` branch in its own worktree directory off
  the configured base branch. The manager creates and provisions the worktree,
  tracks it in runtime state, and on completion either rebases and fast-forward
  merges the branch into base or opens a pull request, degrading to the pull
  request path on conflict.
  """

  _LOCAL_CONFIG = ( ".claude/settings.local.json", ".claude/lazy.settings.local.json" )

  def __init__(self, repo: Path, base_branch: str, worktree_root: str = ".worktrees",
               max_concurrent: int = 3) -> None:
    """
    Bind the manager to one repository and its worktree configuration.

    Args:
      repo: Path-like reference to the primary checkout's root.
      base_branch: Branch that task branches fork from and reintegrate to.
      worktree_root: Repo-relative directory that holds the per-task worktrees.
      max_concurrent: Maximum number of live task worktrees allowed at once.
    """
    self._repo = Path(repo)
    self._base = base_branch
    self._root = self._repo / worktree_root
    self._max = max_concurrent

  @property
  def repo(self) -> Path:
    """
    Repository root this manager is bound to.
    """
    return self._repo

  def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """
    Run one git subcommand and return its completed process.

    Args:
      *args: git subcommand and arguments (without the leading `git`).
      cwd: Working directory for the invocation; the repository root by default.

    Returns:
      The completed process, with stdout and stderr captured as text. The caller
      inspects `returncode` — failures are not raised here.
    """
    return subprocess.run(
      [ "git", *args ], cwd = str(cwd or self._repo),
      capture_output = True, text = True, check = False,
    )

  def _registry(self, state: dict) -> dict:
    """
    Return the worktree-task registry block within a runtime state dict.

    Args:
      state: A runtime state dict, as loaded from disk.

    Returns:
      The `worktree_tasks` mapping, created empty on the passed dict when absent.
    """
    return state.setdefault(StateKey.WORKTREE_TASKS, {})

  def start(self, routine: str, work_id: str, allow_merge: bool) -> dict:
    """
    Create, provision, and register a worktree for one unit of work.

    The branch forks from fresh base — `origin/<base>` when a remote tracking
    ref exists, otherwise the local base branch. The worktree directory and
    branch are both named `task-<id>`.

    Args:
      routine: Name of the routine that originated the unit of work.
      work_id: Identifier for the unit of work; names the branch and worktree.
      allow_merge: Whether completion auto-merges to base or opens a pull request.

    Returns:
      The registry entry recorded for the task, or `{"result": "at_capacity"}`
      when the concurrency cap is already reached.
    """
    # guard: concurrency cap reached — caller re-queues the work unit
    if self.active_count() >= self._max:
      return { WorktreeResultKey.RESULT: WorktreeResult.AT_CAPACITY }
    wt = self._root / f"task-{work_id}"
    branch = f"task-{work_id}"
    # branch off FRESH base — prefer origin/<base> when a remote exists, else local base
    start_point = f"origin/{self._base}"
    # waiver: git CLI vocabulary, not a domain constant
    probe = self._git("rev-parse", "--verify", "--quiet", start_point)
    if probe.returncode != 0:
      start_point = self._base
    self._root.mkdir(parents = True, exist_ok = True)
    # waiver: git CLI vocabulary, not a domain constant
    add = self._git("worktree", "add", str(wt), "-b", branch, start_point)
    # guard: worktree add failed (branch/dir collision, git error) — surface, do not register a broken task
    if add.returncode != 0:
      raise WorktreeStartError(f"worktree add {branch}: {add.stderr.strip()[-300:]}")
    self._provision(wt)
    entry = {
      WorktreeEntryKey.BRANCH: branch, WorktreeEntryKey.WORKTREE_PATH: str(wt), WorktreeEntryKey.ROUTINE: routine,
      WorktreeEntryKey.ALLOW_MERGE: allow_merge, WorktreeEntryKey.JOB_ID: None,
      WorktreeEntryKey.STARTED: time.time(),
    }
    # atomic read-modify-write so registering this task does not clobber a concurrent state change
    runtime_state.update(self._repo, lambda s: self._registry(s).update({work_id: entry}))
    return entry

  def _provision(self, wt: Path) -> None:
    """
    Symlink the primary checkout's gitignored local config into a worktree.

    A fresh worktree materialises only tracked files, so the gitignored local
    settings layer is absent and must be linked in so task agents inherit the
    permission and path posture.

    Args:
      wt: Path to the worktree directory to provision.
    """
    # waiver: filesystem path idiom, not a domain constant
    ( wt / ".claude" ).mkdir(parents = True, exist_ok = True)
    for rel in self._LOCAL_CONFIG:
      src = self._repo / rel
      dst = wt / rel
      # guard: nothing to link / already linked
      if not src.is_file() or dst.exists() or dst.is_symlink():
        continue
      os.symlink(src.resolve(), dst)

  def finish(self, work_id: str) -> dict:
    """
    Reintegrate a completed task branch and clean up its worktree.

    For an `allow_merge` task, an attempt is made to rebase and fast-forward
    merge into base; a clean merge deletes the branch. On rebase or merge
    conflict, or for a non-`allow_merge` task, the branch is pushed (best effort)
    and a pull request is opened, keeping the branch.

    Args:
      work_id: Identifier of the task to finish, as passed to `start`.

    Returns:
      The integration outcome dict. `result` is one of `merged`, `pr_opened`,
      `pr_deferred`, or `unknown` when the work id is not registered.
    """
    state = runtime_state.load(self._repo)
    entry = self._registry(state).get(work_id)
    # guard: unknown task id — nothing to integrate
    if entry is None:
      return { WorktreeResultKey.RESULT: WorktreeResult.UNKNOWN, WorktreeResultKey.WORK_ID: work_id }
    branch = entry[WorktreeEntryKey.BRANCH]
    if entry[WorktreeEntryKey.ALLOW_MERGE]:
      outcome = self._try_merge(branch)
      # guard: merge degraded to PR on conflict — fall through to PR path
      if outcome[WorktreeResultKey.RESULT] == WorktreeResult.MERGED:
        self._cleanup(work_id, entry, delete_branch = True)
        return outcome
    outcome = self._open_pr(branch)
    self._cleanup(work_id, entry, delete_branch = False)
    return outcome

  def _try_merge(self, branch: str) -> dict:
    """
    Rebase a task branch onto base and fast-forward merge it into base.

    Args:
      branch: Name of the task branch to integrate.

    Returns:
      `{"result": "merged", "branch": <branch>}` on a clean fast-forward merge,
      or `{"result": "conflict"}` when the rebase conflicts or the base moved so
      the fast-forward merge is no longer possible.
    """
    # rebase the task branch onto the latest base, then ff-merge into base
    # waiver: git CLI vocabulary, not a domain constant
    rb = self._git("rebase", self._base, branch, cwd = self._worktree_of(branch))
    # guard: rebase conflict — abort and degrade to a PR
    if rb.returncode != 0:
      # waiver: git CLI vocabulary, not a domain constant
      self._git("rebase", "--abort", cwd = self._worktree_of(branch))
      return { WorktreeResultKey.RESULT: WorktreeResult.CONFLICT }
    # waiver: git CLI vocabulary, not a domain constant
    self._git("checkout", self._base)
    # waiver: git CLI vocabulary, not a domain constant
    merge = self._git("merge", "--ff-only", branch)
    # guard: ff-merge failed (base moved mid-finish) — degrade to PR
    if merge.returncode != 0:
      return { WorktreeResultKey.RESULT: WorktreeResult.CONFLICT }
    # waiver: git CLI vocabulary, not a domain constant
    self._git("push", "origin", self._base)   # best-effort; ignore when no remote
    return { WorktreeResultKey.RESULT: WorktreeResult.MERGED, WorktreeResultKey.BRANCH: branch }

  def _open_pr(self, branch: str) -> dict:
    """
    Push a task branch and open a pull request for it when possible.

    Args:
      branch: Name of the task branch to push and open a pull request for.

    Returns:
      `{"result": "pr_opened", ...}` when a pull request was created, otherwise
      `{"result": "pr_deferred", ...}` with a `reason` when `gh` is absent or the
      pull request could not be created (no remote, auth failure, etc.).
    """
    # push branch (best-effort) then open a PR via gh when available
    # waiver: git CLI vocabulary, not a domain constant
    self._git("push", "-u", "origin", branch)
    # guard: gh not installed or no remote — defer the PR, keep the branch, log, continue
    # waiver: external tool name, not a domain key
    if shutil.which("gh") is None:
      return {
        WorktreeResultKey.RESULT: WorktreeResult.PR_DEFERRED, WorktreeResultKey.BRANCH: branch,
        WorktreeResultKey.REASON: "gh_unavailable",
      }
    pr = subprocess.run(
      [ "gh", "pr", "create", "--base", self._base, "--head", branch,
        "--title", f"task {branch}", "--body", "Automated task branch." ],
      cwd = str(self._repo), capture_output = True, text = True, check = False,
    )
    # guard: gh failed (no GitHub remote, auth, etc.) — defer, keep branch
    if pr.returncode != 0:
      return {
        WorktreeResultKey.RESULT: WorktreeResult.PR_DEFERRED, WorktreeResultKey.BRANCH: branch,
        WorktreeResultKey.REASON: pr.stderr.strip()[-300:],
      }
    return {
      WorktreeResultKey.RESULT: WorktreeResult.PR_OPENED, WorktreeResultKey.BRANCH: branch,
      "url": pr.stdout.strip(),
    }

  def _worktree_of(self, branch: str) -> Path:
    """
    Return the worktree directory that holds a given task branch.

    Args:
      branch: Name of the task branch; equal to the worktree directory name.

    Returns:
      Path to the worktree directory for the branch.
    """
    return self._root / branch        # task-<id> dir name == branch name

  def _cleanup(self, work_id: str, entry: dict, delete_branch: bool) -> None:
    """
    Remove a task's worktree, optionally delete its branch, and deregister it.

    Args:
      work_id: Identifier of the task being cleaned up.
      entry: The task's registry entry, holding `worktree_path` and `branch`.
      delete_branch: Whether to delete the local task branch (auto-merge path).
    """
    # ensure the primary checkout is on base before removing the worktree
    # waiver: git CLI vocabulary, not a domain constant
    self._git("checkout", self._base)
    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "remove", "--force", entry[WorktreeEntryKey.WORKTREE_PATH])
    if delete_branch:
      # waiver: git CLI vocabulary, not a domain constant
      self._git("branch", "-D", entry[WorktreeEntryKey.BRANCH])
    # atomic deregister so cleanup does not clobber a concurrent state change made during the git ops
    runtime_state.update(self._repo, lambda s: self._registry(s).pop(work_id, None))

  def active_count(self) -> int:
    """
    Return the number of currently-registered live task worktrees.

    Returns:
      The count of entries in the persisted worktree-task registry.
    """
    return len(self._registry(runtime_state.load(self._repo)))

  def sweep(self) -> list[str]:
    """
    Prune git's worktree bookkeeping and remove orphaned worktree directories.

    A directory under the worktree root that is not in the registry is treated
    as an orphan left by a crashed task and is force-removed. Registered live
    tasks are left untouched.

    Returns:
      The paths of the orphan worktree directories that were removed.
    """
    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "prune")
    state = runtime_state.load(self._repo)
    known = { e[WorktreeEntryKey.WORKTREE_PATH] for e in self._registry(state).values() }
    removed: list[str] = []
    # guard: worktree root absent — nothing to sweep
    if not self._root.is_dir():
      return removed
    for child in self._root.iterdir():
      # guard: a registered (live) task or non-directory — leave it
      if str(child) in known or not child.is_dir():
        continue
      # waiver: git CLI vocabulary, not a domain constant
      self._git("worktree", "remove", "--force", str(child))
      removed.append(str(child))
    return removed
