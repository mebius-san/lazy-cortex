"""
Lifecycle for job-isolated git worktrees: create-or-reuse, provision, bootstrap, remove, sweep.

An isolated expert job runs on its own branch inside a linked worktree under
`<repo>/<worktree_root>/job-<job_id>/`, so the primary checkout never leaves the base branch and
an agent's dirt or crash cannot touch the operator's tree. The manager creates the worktree off
fresh base (or off the job's existing branch on a continuation), symlinks the gitignored local
config in, runs the operator's bootstrap command, and removes the worktree once the job ends —
the branch always survives; reintegration belongs to the coordinator, never to the runtime.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import os
import subprocess
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class WorktreeStartError(RuntimeError):
  """
  Raised when a job worktree cannot be created (git failure / directory collision).
  """


class WorktreeTaskManager:
  """
  Owns the linked-worktree lifecycle for isolated expert jobs.

  Each job gets one worktree directory named after its job id, checked out on the job's own
  branch. The manager never merges, never opens pull requests, and never registers state: a
  worktree lives exactly as long as the pump's synchronous run over one job, and anything left
  behind by a crash is an orphan the hourly `sweep` collects. The daemon's main loop is serial
  by contract, so no live worktree exists while `sweep` runs.
  """

  _LOCAL_CONFIG = ( ".claude/settings.local.json", ".claude/lazy.settings.local.json" )

  def __init__(self, repo: Path, base_branch: str, worktree_root: str = ".worktrees") -> None:
    """
    Bind the manager to one repository and its worktree configuration.

    Args:
      repo: Path-like reference to the primary checkout's root.
      base_branch: Branch that fresh job branches fork from.
      worktree_root: Repo-relative directory that holds the per-job worktrees.
    """
    self._repo = Path(repo)
    self._base = base_branch
    self._root = self._repo / worktree_root

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

  def create(self, job_id: str, branch: str) -> tuple[Path, bool]:
    """
    Create and provision a worktree for one job, on a fresh or an existing branch.

    A fresh dispatch names a branch that does not exist yet — it is created off fresh base
    (`origin/<base>` when a remote tracking ref exists, else the local base branch). A
    continuation names the branch a prior dispatch already created and reuses it as-is.

    Args:
      job_id: Job identifier; names the worktree directory.
      branch: Branch the worktree checks out, created when absent.

    Returns:
      A `(worktree_path, branch_created)` pair; `branch_created` is False on a continuation.

    Raises:
      WorktreeStartError: When the worktree cannot be created.
    """
    wt = self.path_for(job_id)
    # waiver: git CLI vocabulary, not a domain constant
    branch_exists = self._git("rev-parse", "--verify", "--quiet", branch).returncode == 0
    self._root.mkdir(parents = True, exist_ok = True)
    if branch_exists:
      # continuation: the branch already carries the job's earlier commits — reuse it
      # waiver: git CLI vocabulary, not a domain constant
      add = self._git("worktree", "add", str(wt), branch)
    else:
      # fresh dispatch: fork off fresh base — prefer origin/<base> when a remote exists
      start_point = f"origin/{self._base}"
      # waiver: git CLI vocabulary, not a domain constant
      if self._git("rev-parse", "--verify", "--quiet", start_point).returncode != 0:
        start_point = self._base
      # waiver: git CLI vocabulary, not a domain constant
      add = self._git("worktree", "add", str(wt), "-b", branch, start_point)
    # guard: worktree add failed (dir collision, branch checked out elsewhere, git error)
    if add.returncode != 0:
      raise WorktreeStartError(f"worktree add {branch}: {add.stderr.strip()[-300:]}")
    self._provision(wt)
    return wt, not branch_exists

  def path_for(self, job_id: str) -> Path:
    """
    Return the worktree directory a given job would occupy.

    Args:
      job_id: Job identifier; names the worktree directory.

    Returns:
      Path to the job's worktree directory, which need not exist.
    """
    return self._root / f"job-{job_id}"

  def _provision(self, wt: Path) -> None:
    """
    Symlink the primary checkout's gitignored local config into a worktree.

    A fresh worktree materialises only tracked files, so the gitignored local
    settings layer is absent and must be linked in so job agents inherit the
    permission and path posture. Only the config layer is linked — the execution
    environment (a venv and the like) is the bootstrap command's business.

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

  def bootstrap(self, wt: Path, cmd: str | None) -> str | None:
    """
    Run the operator's bootstrap command inside a freshly created worktree.

    The command rebuilds the gitignored execution environment a worktree does not materialise.
    It runs on every creation — a continuation's worktree was removed after the previous run,
    so it bootstraps anew. Everything it creates must be gitignored: the post-job check reads
    `git status --porcelain`, so an un-ignored artifact fails the job. No own timeout: the
    daemon's per-routine timeout bounds the pump run this call is part of, the same bound the
    spawn itself lives under.

    Args:
      wt: Path to the worktree directory to bootstrap.
      cmd: Shell command from `daemon.git.worktree_bootstrap_cmd`, or None to skip.

    Returns:
      None on success or when no command is configured, else a one-line failure description.
    """
    # guard: no bootstrap configured — the worktree runs on tracked files alone
    if not cmd:
      return None
    proc = subprocess.run(
      # waiver: shell invocation idiom shared with the post-push hook, not a domain constant
      [ "sh", "-c", cmd ], cwd = str(wt),
      capture_output = True, text = True, check = False,
    )
    # guard: bootstrap failed — the caller fails the job rather than spawning into a broken env
    if proc.returncode != 0:
      return f"bootstrap exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-300:]}"
    return None

  def remove(self, wt: Path) -> None:
    """
    Remove one job worktree, keeping its branch.

    Runs after every job outcome — success and failure alike. The branch survives as the only
    durable product; an agent's uncommitted dirt disappears with the directory. Best-effort:
    a failed removal leaves an orphan the hourly `sweep` collects.

    Args:
      wt: Path to the worktree directory to remove.
    """
    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "remove", "--force", str(wt))

  def sweep(self) -> list[str]:
    """
    Prune git's worktree bookkeeping and remove crash-orphaned worktree directories.

    Every directory under the worktree root is an orphan by definition: a live worktree only
    exists inside one synchronous pump run, and the serial main loop never runs `sweep`
    concurrently with it.

    Returns:
      The paths of the orphan worktree directories that were removed.
    """
    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "prune")
    removed: list[str] = []
    # guard: worktree root absent — nothing to sweep
    if not self._root.is_dir():
      return removed
    for child in self._root.iterdir():
      # guard: only directories are worktrees
      if not child.is_dir():
        continue
      # waiver: git CLI vocabulary, not a domain constant
      self._git("worktree", "remove", "--force", str(child))
      removed.append(str(child))
    return removed
