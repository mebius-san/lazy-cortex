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
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import subprocess

import error_ledger
import runtime_state
from constants import (
  HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  IncidentResolution, JobArtifact, JobFile, JobMarker, RecoverMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


class RecoverError(Exception):
  """
  Recovery failure raised when the daemon halt cannot be cleared.

  Raised when the working tree is still dirty after cleanup, when the
  caller supplies an unknown cleanup mode, or when the commit mode is
  invoked without a non-empty commit message.
  """


VALID_MODES = {
  RecoverMode.COMMIT, RecoverMode.STASH, RecoverMode.DISCARD, RecoverMode.ABORT, RecoverMode.MANUAL_FIX,
}

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
      cwd = str(repo), capture_output = True, text = True, check = False,
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
  if mode in { RecoverMode.ABORT, RecoverMode.MANUAL_FIX }:
    return

  if mode == RecoverMode.COMMIT:
    # guard: commit mode demands an explicit message — refuse to invent one
    if not message:
      raise RecoverError("commit mode requires a non-empty message")
    # stage every tracked + untracked change, then commit with the operator-supplied message
    subprocess.run([ "git", "add", "-A" ],
                   cwd = str(repo), check = True, capture_output = True)
    subprocess.run([ "git", "commit", "-m", message ],
                   cwd = str(repo), check = True, capture_output = True)
    return

  if mode == RecoverMode.STASH:
    # push everything (including untracked) onto the stash with a recovery marker
    subprocess.run(
      [ "git", "stash", "push", "-u", "-m", "lazycortex-runtime: halt recovery" ],
      cwd = str(repo), check = True, capture_output = True,
    )
    return

  if mode == RecoverMode.DISCARD:
    # revert tracked file changes, then remove untracked files + directories
    subprocess.run([ "git", "checkout", "--", "." ],
                   cwd = str(repo), check = True, capture_output = True)
    subprocess.run([ "git", "clean", "-fd" ],
                   cwd = str(repo), check = True, capture_output = True)
    return


def resume(repo: Path) -> None:
  """
  Clear the active halt block for the given repository so the daemon can resume work.

  Reason-aware: only `uncommitted_changes` requires a clean working tree (that is the
  halt's root cause and clearing without committing would re-halt immediately). All
  other reasons (`suspected_loop`, `git_pull_diverged`, `git_push_failed`,
  `git_remote_unavailable`, future) clear unconditionally — if the underlying cause
  still holds, the daemon will re-halt on the next iteration.

  Args:
    repo: Absolute path to the repository root.

  Raises:
    RecoverError: If the active halt is `uncommitted_changes` and the working tree
      still has pending changes; the error message lists the offending paths in
      `git status --porcelain` form.
  """
  halt = runtime_state.get_halted(repo)
  # guard: daemon is not halted — nothing to clear
  if halt is None:
    return
  reason = halt.get(HaltKey.REASON)
  # guard: dirty-tree halt specifically requires a clean tree before clearing
  if reason == HaltReason.UNCOMMITTED_CHANGES and not is_clean(repo):
    # re-query porcelain status so the error message names the offending paths
    rc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True, check = False,
    )
    raise RecoverError(
      "working tree still dirty; refusing to resume:\n"
      f"{rc.stdout.strip()}"
    )
  runtime_state.clear_halted(repo)
  error_ledger.resolve(repo, f"halt:{repo.name}", resolution = IncidentResolution.RESUMED,
                       kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.RECOVER)


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
  # spec § Emit points #7 — revert resolves the halt; resume after a revert overwrites with
  # `resumed` but either resolution alone yields a closed incident
  error_ledger.resolve(
    repo, f"halt:{repo.name}", resolution = IncidentResolution.REVERTED,
    kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.DOCTOR, detail = f"reverted {len(paths)} path(s)",
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
  for name in ( JobMarker.DEAD, JobArtifact.DEAD_JSON, JobMarker.PID,
                JobArtifact.TRANSCRIPT, JobArtifact.ERROR_JSON, JobFile.RESPONSE ):
    try:
      (jdir / name).unlink()
    except FileNotFoundError:
      pass
  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric literal (parents-index depth), not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.TRIAGED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: "retry", IncidentKey.ACTOR: IncidentActor.DOCTOR,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name,
  })


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
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import json
  (jdir / JobArtifact.DIAGNOSIS_JSON).write_text(json.dumps(diagnosis, indent = 2))
  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric literal (parents-index depth), not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.TRIAGED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: "permanent_fail",
    IncidentKey.ACTOR: IncidentActor.DOCTOR,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.REFS: { "diagnosis_json": str(jdir / JobArtifact.DIAGNOSIS_JSON) },
  })
