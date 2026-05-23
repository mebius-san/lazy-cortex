"""
Recovery primitives for the lazycortex-core runtime daemon halt state.

The lazy-runtime.recover skill walks an operator through cleanup +
resume after a halt. This module is the pure-Python core: read the
halt context, apply the operator-chosen cleanup mode, verify the tree
is clean, then atomically clear the daemon_halted block.

The cleanup modes wrap real git commands. `commit` uses `git add -A`
because the operator has explicitly chosen to commit everything dirty
— that is the whole point of the mode. The skill MUST surface the
dirty paths to the operator before they pick a mode (so the choice is
informed); this module assumes the choice was already informed.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import runtime_state


class RecoverError(Exception):
  """
  Recovery failure raised when the daemon halt cannot be cleared.

  Raised when the working tree is still dirty after cleanup, when the
  caller supplies an unknown cleanup mode, or when the commit mode is
  invoked without a non-empty commit message.
  """


VALID_MODES = { "commit", "stash", "discard", "abort", "manual-fix" }

# Halt reasons where the working tree is presumed already clean and the
# operator's repair happened outside the skill (manual git ops). The skill
# offers `manual-fix` instead of the dirt-cleanup wizard. Source of truth:
# claude/lazycortex-core/bin/runtime_daemon.py:_halt_daemon callers.
MANUAL_FIX_REASONS = {
  "git_pull_diverged",
  "git_push_failed",
  "git_remote_unavailable",
}


def read_halt(repo: Path) -> dict | None:
  """
  Return the active halt context for the given repository.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    The stored `daemon_halted` block describing the halt reason, or None when
    the daemon is not currently halted.
  """
  return runtime_state.get_halted(repo)


def is_clean(repo: Path) -> bool:
  """
  Report whether the working tree of the given repository has no pending changes.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    True when there are no tracked or untracked modifications, or when the path
    is not a git repository or git is unavailable. False when modifications are
    present.
  """
  try:
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True,
    )
  except FileNotFoundError:
    return True
  # guard: git produced a non-zero exit — treat as clean to avoid wedging recovery on transient errors
  if rc.returncode != 0:
    return True
  return rc.stdout.strip() == ""


def cleanup(repo: Path, mode: str, message: str | None = None) -> None:
  """
  Bring the working tree of the given repository into a clean state per the operator's choice.

  Mode semantics:
    - `commit`: stages every tracked and untracked change and records a commit with `message`.
    - `stash`: pushes every tracked and untracked change onto the stash with a recovery marker.
    - `discard`: reverts tracked changes and removes untracked files and directories.
    - `abort`: leaves the working tree untouched and leaves the halt in place.
    - `manual-fix`: leaves the working tree untouched because the operator resolved the halt
      cause externally; a subsequent `resume` call clears the halt block.

  Args:
    repo: Absolute path to the repository root.
    mode: One of `commit`, `stash`, `discard`, `abort`, or `manual-fix`.
    message: Commit message to use when `mode` is `commit`. Required and must be non-empty
      in that mode; ignored otherwise.

  Raises:
    RecoverError: If `mode` is not recognised, or if `mode` is `commit` and `message` is empty.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  # guard: reject unrecognised cleanup mode before invoking any git command
  if mode not in VALID_MODES:
    raise RecoverError(f"unknown cleanup mode: {mode!r}")

  # guard: abort + manual-fix are both no-op shapes — nothing to do here
  if mode in { "abort", "manual-fix" }:
    return

  if mode == "commit":
    # guard: commit mode demands an explicit message — refuse to invent one
    if not message:
      raise RecoverError("commit mode requires a non-empty message")
    # stage every tracked + untracked change, then commit with the operator-supplied message
    subprocess.run([ "git", "add", "-A" ],
                   cwd = str(repo), check = True, capture_output = True)
    subprocess.run([ "git", "commit", "-m", message ],
                   cwd = str(repo), check = True, capture_output = True)
    return

  if mode == "stash":
    # push everything (including untracked) onto the stash with a recovery marker
    subprocess.run(
      [ "git", "stash", "push", "-u", "-m", "lazycortex-runtime: halt recovery" ],
      cwd = str(repo), check = True, capture_output = True,
    )
    return

  if mode == "discard":
    # revert tracked file changes, then remove untracked files + directories
    subprocess.run([ "git", "checkout", "--", "." ],
                   cwd = str(repo), check = True, capture_output = True)
    subprocess.run([ "git", "clean", "-fd" ],
                   cwd = str(repo), check = True, capture_output = True)
    return


def resume(repo: Path) -> None:
  """
  Clear the halt block for the given repository so the daemon can resume work.

  Args:
    repo: Absolute path to the repository root.

  Raises:
    RecoverError: If the working tree still has uncommitted changes; the error message
      lists the offending paths in `git status --porcelain` form.
  """
  # guard: refuse to clear the halt block while the working tree is still dirty
  if not is_clean(repo):
    # re-query porcelain status so the error message names the offending paths
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True,
    )
    raise RecoverError(
      "working tree still dirty; refusing to resume:\n"
      f"{rc.stdout.strip()}"
    )
  runtime_state.clear_halted(repo)


def cleanup_and_resume(repo: Path, mode: str, message: str | None = None) -> None:
  """
  Apply the chosen cleanup mode and then clear the halt block in a single call.

  Args:
    repo: Absolute path to the repository root.
    mode: Cleanup mode forwarded to `cleanup`.
    message: Commit message forwarded to `cleanup` when `mode` is `commit`.

  Raises:
    RecoverError: If cleanup or the post-cleanup clean-tree check fails.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  cleanup(repo, mode, message)
  resume(repo)


# ---- doctor primitives (lazy-runtime.doctor uses these via Bash) ----

def revert_files(repo: Path, paths: list[str]) -> None:
  """
  Restore the given tracked paths in the repository to their `HEAD` state.

  Untracked files are not affected; the caller is responsible for confirming the
  paths were clean before the failed run began.

  Args:
    repo: Absolute path to the repository root.
    paths: Repository-relative paths to restore. An empty list is a no-op.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # guard: nothing to revert — skip the subprocess call entirely
  if not paths:
    return
  subprocess.run(
    [ "git", "checkout", "HEAD", "--", *paths ],
    cwd = str(repo), check = True, capture_output = True,
  )


def clear_dead_job(jdir: Path) -> None:
  """
  Prepare a failed job directory for retry by removing per-attempt artifacts.

  The READY marker and the cumulative attempt counter survive so the next pump tick
  re-picks the job with prior failure history intact.

  Args:
    jdir: Absolute path to the job directory to reset.
  """
  # iterate the fixed set of retry-resettable artifacts; missing files are expected
  for name in ( "DEAD", "dead.json", "PID", "transcript.jsonl", "error.json", "response.json" ):
    try:
      (jdir / name).unlink()
    except FileNotFoundError:
      pass


def permanent_fail(jdir: Path, diagnosis: dict) -> None:
  """
  Mark a job as permanently failed by recording the doctor's diagnosis alongside it.

  The DEAD marker stays in place so pump skips the directory until the operator
  removes it.

  Args:
    jdir: Absolute path to the job directory to mark as permanently failed.
    diagnosis: Doctor-supplied summary of attempts, likely cause, last error excerpt,
      and follow-up actions for the operator.
  """
  import json
  (jdir / "diagnosis.json").write_text(json.dumps(diagnosis, indent = 2))
