"""
Recovery primitives for the lazycortex-core runtime daemon halt state.

The lazy-runtime.recover skill walks an operator through cleanup +
resume after a halt. This module is the pure-Python core: read the
halt context, apply the operator-chosen cleanup mode, verify the tree
is clean, then atomically clear the daemon_halted block.

The cleanup modes wrap real git commands. `commit` stages the paths the caller names —
the doctor passes the halt block's own `dirty_paths` with `porcelain = True`, the shape the
block records them in, so a file nobody triaged stays out of the commit — and falls back
to staging every dirty path when the caller names none, which is
the operator's own hatch: they have seen the dirty list and chose the mode for it. The skill
MUST surface the dirty paths to the operator before they pick a mode (so the choice is
informed); this module assumes the choice was already informed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import error_ledger  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  IncidentResolution, JobArtifact, JobFile, JobIODir, JobMarker, RecoverMode,
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
# plugins/claude/lazycortex-core/bin/runtime_daemon.py:_halt_daemon callers.
# `rate_limit` rides this path too: there is no dirt to clean, resume simply
# clears the halt early — the pump's own pre-spawn flag check keeps tokens
# safe even when the operator resumes before the window reopens.
MANUAL_FIX_REASONS = {
  "git_pull_diverged",
  "git_push_failed",
  "git_remote_unavailable",
  "git_rebase_not_started",
  "routine_config_invalid",
  "rate_limit",
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

  Guarantees:
    - An ambiguous condition — no git repository at the path, git unavailable, or a failed
      invocation — resolves to clean rather than raising; only an actual pending modification
      reports as dirty.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    True when there are no tracked or untracked modifications, or when the path
    is not a git repository or git is unavailable. False when modifications are
    present.
  """

  # Contract:
  # An ambiguous condition — the path is not a git repository, git itself is unavailable, or
  # the invocation fails — MUST resolve to clean, never raised as an exception; only an actual
  # pending modification reports as dirty.

  try:
    proc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
    )
  except FileNotFoundError:
    return True

  # guard: git produced a non-zero exit — treat as clean to avoid wedging recovery on transient errors
  if proc.returncode != 0:
    return True
  return proc.stdout.strip() == ""


# A `git status --porcelain` line opens with the index and worktree status codes and the
# space that separates them from the path, so its path starts at the fourth character.
# Porcelain writes a rename or a copy as `ORIG -> PATH`, under one of these index codes.
_PORCELAIN_PREFIX_WIDTH = 3
_RENAME_ARROW = " -> "
_RENAME_CODES = "RC"
# `runtime_daemon.check_working_tree` caps a long dirty list with a sentinel line that names
# no path at all. It reaches here whenever a caller hands the halt block straight over.
_TRUNCATION_PREFIX = "..."


def _unquote(path: str) -> str:
  """
  Decode one C-style quoted porcelain path back to the name that is on disk.

  Git wraps a path in double quotes and escapes it whenever the name carries a quote, a
  backslash, a control character, or — unless `core.quotePath` is off — a non-ASCII byte,
  written as three octal digits per byte. The daemon now asks for raw names, but a halt block
  recorded before it did still carries the escaped form, and a quote or backslash in a name is
  escaped either way.

  Args:
    path: One path as porcelain spelled it, quoted or plain.

  Returns:
    The unescaped name; the argument unchanged when it was not a quoted path.
  """
  # guard: only a quoted path carries escapes — anything else is already the name
  if len(path) < 2 or not path.startswith('"') or not path.endswith('"'):
    return path

  # git escapes the name's bytes, so the escapes read back as latin-1 code points first and
  # the name itself is their UTF-8 reading
  # waiver: the latin-1 round trip is the standard way to read byte escapes out of a str
  escaped = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
  # waiver: stdlib codec and error-handler names of the same latin-1 round trip
  return escaped.encode("latin-1", "backslashreplace").decode("utf-8", "replace")


def _pathspecs_from_dirty(lines: list[str], *, porcelain: bool) -> list[str]:
  """
  Derive committable pathspecs from a path list whose shape the caller declared.

  A halt block records its dirty tree as `git status --porcelain` lines, so the doctor hands
  the block over as it stands and says so with `porcelain = True`; an operator naming paths
  by hand passes them bare. The shape comes from the caller and is never sniffed off the
  text: a bare name can open with two status codes and a space by accident (`MD file.md`),
  and truncating such a name to its tail would commit a path nobody asked for.

  Args:
    lines: Porcelain status lines when `porcelain` is true, else bare repo-relative paths.
    porcelain: True when every line carries a `git status --porcelain` status prefix.

  Returns:
    The repo-relative paths named, in the order given, with lines naming no path dropped. A
    porcelain rename or copy line yields both of its sides, and a C-style quoted path is
    unescaped.
  """

  # bare paths are already the pathspec — no prefix to strip, no escaping to undo
  if not porcelain:
    return [line for line in lines if line]

  # every porcelain line, stripped of its status prefix and unescaped back to the name on disk
  out: list[str] = []
  for line in lines:
    # guard: the truncation sentinel is prose about the list, not an entry in it
    if line.startswith(_TRUNCATION_PREFIX):
      continue

    # guard: a line shorter than the prefix plus one character names no path at all
    if len(line) <= _PORCELAIN_PREFIX_WIDTH:
      continue

    # the path follows the status prefix
    path = line[_PORCELAIN_PREFIX_WIDTH:]

    # a rename names both sides and both belong in one commit: staging the pair records the
    # new path and the old one's removal together, so no half-applied move is left behind
    parts = path.rsplit(_RENAME_ARROW, 1) if line[0] in _RENAME_CODES else [path]

    # each side is quoted on its own, so unquoting follows the split rather than preceding it
    # a blank entry is dropped, since it would widen the pathspec to the whole directory
    out.extend(_unquote(part) for part in parts if part)
  return out


def _filter_stageable(repo: Path, pathspec: list[str]) -> list[str]:
  """
  Narrow a pathspec to the paths worth staging ahead of a path-limited commit.

  Only a path still present in the worktree is staged. An untracked one has to be, since a
  path-limited commit cannot name content git has never seen; a deleted one must not be,
  because such a commit reads each named path from the index and a staged deletion leaves no
  entry there to read — staging it would drop the removal from the commit instead of
  carrying it. Left alone, the deletion is read off the worktree and lands. A path gone from
  the index as well, the left half of an already-staged rename, matches nothing either way
  and would abort the whole staging call.

  Args:
    repo: Absolute path to the repository root.
    pathspec: Repo-relative paths the commit will carry.

  Returns:
    The subset still present in the worktree.
  """
  return [ path for path in pathspec if (repo / path).exists() ]


def cleanup(repo: Path, mode: str, message: str | None = None, *,
            paths: list[str] | None = None, porcelain: bool = False) -> None:
  """
  Bring the working tree of the given repository into a clean state per the operator's choice.

  Args:
    repo: Absolute path to the repository root.
    mode: One of `commit`, `stash`, `discard`, `abort`, or `manual-fix`. `commit` stages the paths in `paths`
      — or every tracked and untracked change when `paths` is empty or None — and records a commit with
      `message`. `stash` pushes every tracked and untracked change onto the stash with a recovery marker.
      `discard` reverts tracked changes and removes untracked files and directories. `abort` leaves the
      working tree untouched and leaves the halt in place. `manual-fix` leaves the working tree untouched
      because the operator resolved the halt cause externally; a subsequent `resume` call clears the halt
      block.
    message: Commit message to use when `mode` is `commit`. Required and must be non-empty
      in that mode; ignored otherwise.
    paths: Paths the commit is limited to, in the shape `porcelain` declares. Empty or None
      stages every change, the operator-hatch shape. Ignored outside `commit` mode.
    porcelain: True when `paths` carries the `git status --porcelain` lines a halt block
      records — the doctor hands the block's `dirty_paths` over as it stands, so its commit
      never publishes dirt it did not classify, and a rename line contributes both of its
      sides so the move lands whole. False, the default, takes `paths` as bare repo-relative
      names, the shape an operator types.

  Raises:
    RecoverError: If `mode` is not recognised, if `mode` is `commit` and `message` is empty,
      or if `paths` names entries from which no committable path could be derived.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  # guard: reject unrecognised cleanup mode before invoking any git command
  if mode not in VALID_MODES:
    raise RecoverError(f"unknown cleanup mode: {mode!r}")

  # abort + manual-fix are both no-op shapes — nothing to do here
  if mode in { RecoverMode.ABORT, RecoverMode.MANUAL_FIX }:
    return

  # commit mode: preserve the halted work as a real commit
  if mode == RecoverMode.COMMIT:
    # guard: commit mode demands an explicit message — refuse to invent one
    if not message:
      raise RecoverError("commit mode requires a non-empty message")

    # a named path set is the whole footprint; an unnamed one is the operator's capture-all
    named = list(paths or [])
    pathspec = _pathspecs_from_dirty(named, porcelain = porcelain)

    # guard: the caller named paths but none resolved — refuse rather than widen to capture-all
    if named and not pathspec:
      raise RecoverError(f"no committable path among: {named!r}")

    # the capture-all hatch stages the whole tree; a named set stages only what git can still
    # act on, so a rename's already-staged left side does not abort the call that carries it
    to_stage = _filter_stageable(repo, pathspec) if pathspec else None
    if to_stage is None:
      subprocess.run([ "git", "add", "-A" ],
                     cwd = str(repo), check = True, capture_output = True)
    elif to_stage:
      subprocess.run([ "git", "add", "--", *to_stage ],
                     cwd = str(repo), check = True, capture_output = True)

    # the commit carries every named path, staged here or staged before it got here
    commit_cmd = ["git", "commit", "-m", message]
    if pathspec:
      commit_cmd += ["--", *pathspec]
    subprocess.run(commit_cmd, cwd = str(repo), check = True, capture_output = True)
    return

  # stash mode: park the halted work where the operator can restore it later
  if mode == RecoverMode.STASH:
    # push everything (including untracked) onto the stash with a recovery marker
    subprocess.run(
      [ "git", "stash", "push", "-u", "-m", "lazycortex-runtime: halt recovery" ],
      cwd = str(repo), check = True, capture_output = True,
    )
    return

  # discard mode: throw the halted work away and return the tree to HEAD
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
  halt's root cause and clearing without committing would re-halt immediately). Any
  other halt reason clears unconditionally — if the underlying cause still holds, the
  daemon will re-halt on the next iteration.

  Args:
    repo: Absolute path to the repository root.

  Raises:
    RecoverError: If the active halt is `uncommitted_changes` and the working tree
      still has pending changes; the error message lists the offending paths in
      `git status --porcelain` form.
  """

  # Domain(runtime.incidents):
  # # Clean-tree gate is reason-specific
  # A halted daemon divides by whether its own cause left the working tree dirty. Only the
  # reason naming uncommitted changes ties clearing the halt to a clean tree, because that is
  # the one halt whose root cause is the dirt itself — clearing it without a clean tree just
  # re-halts on the same condition next tick. Every other halt reason describes trouble that
  # lives outside the working tree — a diverged or rejected push, an unreachable remote, an
  # invalid routine configuration, a closed rate-limit window — so clearing any of those never
  # depends on the tree's state, whatever that state happens to be at the moment.

  halt = runtime_state.get_halted(repo)

  # guard: daemon is not halted — nothing to clear
  if halt is None:
    return
  reason = halt.get(HaltKey.REASON)

  # guard: dirty-tree halt specifically requires a clean tree before clearing
  if reason == HaltReason.UNCOMMITTED_CHANGES and not is_clean(repo):
    # re-query porcelain status so the error message names the offending paths
    proc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain" ],
      cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
    )
    raise RecoverError(
      "working tree still dirty; refusing to resume:\n"
      f"{proc.stdout.strip()}"
    )
  runtime_state.clear_halted(repo)
  error_ledger.resolve(repo, f"halt:{repo.name}", resolution = IncidentResolution.RESUMED,
                       kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.RECOVER)


def cleanup_and_resume(repo: Path, mode: str, message: str | None = None, *,
                       paths: list[str] | None = None, porcelain: bool = False) -> None:
  """
  Apply the chosen cleanup mode and then clear the halt block in a single call.

  Args:
    repo: Absolute path to the repository root.
    mode: Cleanup mode forwarded to `cleanup`.
    message: Commit message forwarded to `cleanup` when `mode` is `commit`.
    paths: Paths forwarded to `cleanup` to limit the commit to; None keeps the operator-hatch
      shape that captures every dirty path.
    porcelain: Shape of `paths`, forwarded to `cleanup`.

  Raises:
    RecoverError: If cleanup or the post-cleanup clean-tree check fails.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  cleanup(repo, mode, message, paths = paths, porcelain = porcelain)
  resume(repo)


# ---- doctor primitives (runtime.doctor uses these via Bash) ----

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


def _read_job_scope(repo: Path, jdir: Path) -> list[str]:
  """
  List the repository-relative paths a job is allowed to have created.

  Args:
    repo: Absolute path to the repository root.
    jdir: Absolute path to the job directory.

  Returns:
    Normalized repository-relative roots: the job's `result/` directory, plus the request's `file` target
    when the request names one.
  """

  # Domain(runtime.job-execution):
  # # A job's footprint is its result directory and its named target
  # A job may have created only two things in the repository: its own result directory, and the one target file
  # its request names, when the request names one. Anything else untracked in the tree was not made by this job,
  # whatever else the failed run left dirty. Cleaning up after a dead job deletes untracked paths only inside
  # this footprint, so a file that belongs to the operator or to another job is never removed on the job's account.
  # A request that is unreadable or names no target narrows the footprint to the result directory alone.

  # the job's own result directory is always its footprint
  scope = [ os.path.normpath(os.path.relpath(jdir / JobIODir.RESULT, repo)) ]

  # the request names the target file the job was dispatched to edit, when it names one
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    request = None
  # waiver: external request-payload field name the doctor already reads as `request_json.file`
  target = request.get("file") if isinstance(request, dict) else None
  if isinstance(target, str) and target:
    scope.append(os.path.normpath(target))
  return scope


def _is_in_scope(path: str, scope: list[str]) -> bool:
  """
  Check whether a path is one of the scope roots or lies beneath one.

  Args:
    path: Repository-relative path to test.
    scope: Normalized repository-relative scope roots.

  Returns:
    True when the path equals a root or sits under a root directory.
  """
  # a path is inside a scope root when it is the root itself or lies beneath it
  norm = os.path.normpath(path)
  return any(norm == root or norm.startswith(root + os.sep) for root in scope)


def _is_untracked(repo: Path, path: str) -> bool:
  """
  Check whether a path exists on disk but is unknown to git.

  Args:
    repo: Absolute path to the repository root.
    path: Repository-relative path to test.

  Returns:
    True when the path exists in the working tree and git does not track it.
  """
  # a path present on disk that git has never recorded is untracked
  proc = subprocess.run(
    [ "git", "ls-files", "--error-unmatch", "--", path ],
    cwd = str(repo), capture_output = True, check = False,
  )
  return proc.returncode != 0 and (repo / path).exists()


def _find_all_dirty_paths(repo: Path, paths: list[str]) -> list[str]:
  """
  List the named paths that still differ from `HEAD`.

  Args:
    repo: Absolute path to the repository root.
    paths: Repository-relative paths to inspect.

  Returns:
    The subset of the named paths that git reports as modified or untracked; empty when all are clean.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # porcelain lists exactly the named paths that still differ from HEAD
  proc = subprocess.run(
    [ "git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain", "--", *paths ],
    cwd = str(repo), capture_output = True, text = True, check = True, encoding = "utf-8",
  )
  return _pathspecs_from_dirty(proc.stdout.splitlines(), porcelain = True)


def revert_and_retry(repo: Path, jdir: Path, paths: list[str], *, remove_untracked: bool = False) -> list[str]:
  """
  Restore a dead job's dirty paths to `HEAD` and re-arm its bundle for retry.

  Untracked paths are deleted only when the caller opts in and only inside the job's own scope: its `result/`
  directory and the target `file` named by its request. The call never commits.

  Guarantees:
    - The bundle is re-armed only when every named path is clean after the restore; otherwise it stays disarmed
      and the still-dirty paths are returned.
    - An untracked path outside the job's own scope is never deleted; a call naming one is refused as a whole
      before any named path is touched.

  Args:
    repo: Absolute path to the repository root.
    jdir: Absolute path to the dead job's directory.
    paths: Repository-relative paths the failed run left dirty.
    remove_untracked: Delete the named untracked paths instead of leaving them in place.

  Returns:
    The named paths that are still dirty, in which case the bundle is not re-armed; empty when the bundle
    was re-armed.

  Raises:
    RecoverError: If `remove_untracked` is set and a named untracked path lies outside the job's scope.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """

  # Contract:
  # The job's bundle is re-armed only when every named path is clean after the restore; otherwise the bundle
  # stays disarmed and the still-dirty paths are returned.

  # Contract:
  # An untracked path outside the job's own scope is NEVER deleted. A call naming one is refused as a whole
  # before any named path is touched.

  # with the flag, untracked paths are split off and must all sit inside the job's own scope
  untracked = [ path for path in paths if _is_untracked(repo, path) ] if remove_untracked else []
  scope = _read_job_scope(repo, jdir)
  outside = [ path for path in untracked if not _is_in_scope(path, scope) ]

  # guard: one untracked path outside the job's scope refuses the whole call before anything is removed
  if outside:
    raise RecoverError(f"outside-job-scope: {' '.join(outside)}")

  # the job's own leftovers go away; every other named path is restored from HEAD
  for path in untracked:
    target = repo / path
    if target.is_dir():
      shutil.rmtree(target)
    else:
      target.unlink()
  revert_files(repo, [ path for path in paths if path not in untracked ])

  # a path that is still dirty means the revert did not take — the job is not re-armed
  if dirty := _find_all_dirty_paths(repo, paths):
    return dirty

  # the tree is back to HEAD on every named path, so the job can run again
  clear_dead_job(jdir)
  return []


def clear_dead_job(jdir: Path) -> None:
  """
  Prepare a failed job directory for retry by removing per-attempt artifacts.

  The bundle is left armed so the next pump tick can re-pick the job.

  Guarantees:
    - The cumulative attempt counter survives the reset untouched, so a job that keeps
      failing is still recognisable as having failed before.

  Args:
    jdir: Absolute path to the job directory to reset.
  """

  # Contract:
  # The job's cumulative attempt counter MUST survive this reset untouched; only the failed
  # attempt's own artifacts are removed.

  # Domain(runtime.job-execution):
  # # Retry resets the attempt, not the history
  # A dead job's retry throws away only what belongs to the failed attempt itself — its dead
  # marker, its process id, its transcript, its recorded error, its response. The cumulative
  # attempt counter belongs to the job as a whole rather than to any one attempt, and survives
  # untouched, so a job that keeps failing is still recognisable as having failed before and a
  # permanent-fail judgment can still act on its true attempt count.

  # iterate the fixed set of retry-resettable artifacts; missing files are expected
  for name in ( JobMarker.DEAD, JobArtifact.DEAD_JSON, JobMarker.PID, JobArtifact.CLAIM_HEAD,
                JobArtifact.TRANSCRIPT, JobArtifact.ERROR_JSON, JobFile.RESPONSE ):
    try:
      (jdir / name).unlink()
    except FileNotFoundError:
      pass

  # Decision: READY is placed rather than merely left alone — retry means the pump can pick the
  # job up, and a bundle whose dispatch died before arming it has no marker to preserve. Without
  # this the caller is told the retry succeeded while the bundle stays invisible to the pump, gets
  # buried again on the next scan, and comes back to the doctor forever. For an armed bundle the
  # touch is a no-op refresh.

  # the bundle leaves this call claimable, which is the whole meaning of a retry
  (jdir / JobMarker.READY).touch()

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
  (jdir / JobArtifact.DIAGNOSIS_JSON).write_text(json.dumps(diagnosis, indent = 2), encoding = "utf-8")

  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric literal (parents-index depth), not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.TRIAGED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: "permanent_fail",
    IncidentKey.ACTOR: IncidentActor.DOCTOR,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.REFS: { "diagnosis_json": str(jdir / JobArtifact.DIAGNOSIS_JSON) },
  })
