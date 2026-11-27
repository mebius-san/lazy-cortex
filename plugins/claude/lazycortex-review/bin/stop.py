"""
`/lazy-review.stop <file>` — bail out of the review loop without finalizing.

Cancels the coordinator job and the expert job in flight on the document, sets `review_active: false` and commits.
Optionally the review banner is removed as well. Body and `approved` are otherwise left untouched so a subsequent
`start` can resume from the operator's last state. A job that cannot be confirmed cancelled, or whose marker cannot
be cleared after a confirmed cancel, leaves the review as it was; so does a job-marker sidecar that cannot be read or
is no store. A stop commit that git refuses puts the document back as it was before the stop. With `--json` the stop
prints one JSON report naming the jobs it cancelled and the jobs already over, so a caller can raise their wakes
again or resume the review.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import EnvVar, JobFile, JobKey, JobMarker, ReviewKey  # noqa: E402


# The per-cycle autorun choices stopping a review removes from the frontmatter.
_AUTORUN_KEYS = ( ReviewKey.SKIP_VALIDATION, ReviewKey.AUTORUN, ReviewKey.AUTORUN_CYCLES )

# The core CLI verb that cancels an expert job, and the seconds one call may run before the cancel counts as
# unconfirmed.
_CANCEL_JOB = "cancel-job"
_CANCEL_TIMEOUT_S = 60

# How the core CLI's undecodable output bytes are read: replaced, so odd output reads as an unreadable report and
# never raises.
_DECODE_ERRORS = "replace"

# waiver: the core `cancel-job` report's own wire key saying whether the call cancelled the job
_CANCELLED_KEY = "cancelled"

# Git's per-path magic prefix that makes one path argument literal, never a pattern; unlike the global
# `--literal-pathspecs` option it exports nothing into the environment of the hooks git runs.
_LITERAL_PATHSPEC = ":(literal)"


def _atomic_commit(file_path: Path) -> None:
  """
  Commit a stopped document on its own.

  Args:
    file_path: The stopped document; its file name is taken literally, never as a pattern.

  Raises:
    subprocess.CalledProcessError: If staging or committing the document fails.
  """
  # the document is staged from its own folder, under its literal name, never as a pattern
  cwd = file_path.parent
  literal_name = f"{_LITERAL_PATHSPEC}{file_path.name}"
  subprocess.run(
      ["git", "add", "--", literal_name],
      cwd = cwd, check = True, capture_output = True,
  )

  # the pathspec keeps a concurrently staged foreign file out of the stop commit
  subprocess.run(
      [
          "git", "commit", "-q",
          "-m", f"review: stop {file_path.name}", "--", literal_name,
      ],
      cwd = cwd, check = True, capture_output = True,
  )


def _restore_document(file_path: Path, before: bytes) -> str | None:
  """
  Put a document whose stop commit failed back as it was before the stop.

  Args:
    file_path: The stopped document.
    before: The document's bytes before the stop.

  Returns:
    `None` when the document is restored; otherwise a one-line reason, `document left staged` when its index entry
    could not be put back to HEAD or `document left rewritten` when its bytes could not be written back.
  """
  # the stop commit staged the document before git refused it: the index entry goes back to HEAD first, under the
  # document's literal name, so nothing of the stop is left staged
  try:
    unstaged = subprocess.run(
        [ "git", "restore", "--staged", "--", f"{_LITERAL_PATHSPEC}{file_path.name}" ],
        cwd = file_path.parent, check = False, capture_output = True,
    )
  except OSError as error:
    return f"document left staged: {error}"

  # guard: an index entry git would not put back leaves the stop staged; the working copy is not touched then
  if unstaged.returncode != 0:
    return f"document left staged: {os.fsdecode(unstaged.stderr).strip()}"

  # the working copy takes back the bytes it had before the stop
  try:
    _atomic_io.write_bytes_atomic(file_path, before)
  except OSError as error:
    return f"document left rewritten: {error}"
  return None


def stop_review(file_path: Path, *, strip_banner: bool = False) -> bool:
  """
  Set `review_active` to `false` and drop the cycle's autorun choices from the frontmatter.

  Guarantees:
    - Leaves the round counter, phase, done-lists, approval state, and the document body
      unchanged; only `review_active` is modified and `review_skip_validation`, `review_autorun`,
      and `review_autorun_cycles` are removed.
    - With `strip_banner` set the review banner is removed from the body as well; without it the banner
      stays as it was.

  Args:
    file_path: Absolute path to the markdown file to update.
    strip_banner: Whether to remove the review banner from the body as well.

  Returns:
    `True` if the file was modified, `False` if it was already inactive.
  """

  # Domain(review.lifecycle):
  # # Stopping pauses the round machine, it does not reset it
  # Leaving review turns the loop off and drops the cycle's autorun choices; the round
  # counter, phase, done-lists, and approval state are left exactly as they stood, and the
  # document body is untouched. A later re-entry into review resumes the round machine from
  # wherever it was paused, rather than starting the cycle over. A caller abandoning the
  # document may ask for the review banner, with its approval gestures, to be taken down
  # as well; otherwise the banner stays as it was.

  # Contract:
  # Stopping review changes only `review_active` and removes `review_skip_validation`,
  # `review_autorun`, and `review_autorun_cycles`; the round counter, phase,
  # done-lists, approval state, and the document body are left unchanged.
  # The one exception is `strip_banner`: when it is set the review banner is removed from the body as well,
  # and when it is not set the banner stays as it was.

  # flip the active flag
  text = _atomic_io.read_text(file_path)
  lf_text, ending = _atomic_io.to_lf(text)
  lf_text = _fm.set_field(lf_text, ReviewKey.ACTIVE, False)

  # drop the cycle's autorun choices; every other lifecycle key is left untouched
  for key in _AUTORUN_KEYS:
    lf_text = _fm.unset_field(lf_text, key)

  # a caller abandoning the document takes its banner, and the approval gestures on it, down too
  if strip_banner:
    meta_end = len(lf_text) - len(_fm.parse(lf_text)[1])
    lf_text = lf_text[:meta_end] + _banner.strip_banner(lf_text[meta_end:])

  # write only when something changed
  new_text = _atomic_io.restore_ending(lf_text, ending)
  # guard: an unchanged document is not rewritten
  if new_text == text:
    return False
  _atomic_io.write_text_atomic(file_path, new_text)
  return True


def _find_repo_root(file_path: Path) -> Path:
  """
  Return the root of the git repository holding a document.

  Args:
    file_path: The reviewed document.

  Returns:
    The root of the checkout the document sits in, a linked worktree's own root inside one; the document's own
    folder when it is not inside a git repository.
  """
  # the checkout git names for the document's folder is the repository the sidecar lives in
  return _review_locator.query_checkout_toplevel(file_path.parent)


@dataclass(frozen = True)
class JobsCancelResult:
  """
  The outcome of cancelling the jobs a document's review has in flight.

  Attributes:
    cancelled: The ids of the jobs the call confirmed cancelled, in cancel order.
    terminal: The ids of the jobs already over before the call, their markers kept for the collect tick.
    failure: The reason a job could not be cancelled, absent when every job in flight is gone.
  """

  cancelled: list[str] = field(default_factory = list)
  terminal: list[str] = field(default_factory = list)
  failure: str | None = None


@dataclass(frozen = True)
class _JobAnswer:
  """
  The core CLI's answer for one job.

  Attributes:
    cancelled: Whether a bundle of the job was cancelled by the call.
    terminal: Whether the job's bundles were all already over, none cancelled by the call.
    failure: The reason the cancel is unconfirmed, absent when it is confirmed.
  """

  cancelled: bool = False
  terminal: bool = False
  failure: str | None = None


def cancel_review_jobs(file_path: Path) -> JobsCancelResult:
  """
  Cancel the coordinator job and the expert job a document's review has in flight and clear their markers.

  Guarantees:
    - A document whose job markers were read and show no job in flight is left alone and the core CLI is never
      called.
    - A job-marker sidecar that exists but cannot be read, or reads but is no store, is never read as "no job in
      flight": a failure naming the sidecar and the error is returned before any cancel call is made and before any
      marker is changed.
    - The coordinator job is cancelled before the expert job.
    - A job the core CLI does not confirm cancelled keeps its marker, and no job after it is tried; a call that times
      out, cannot be launched, exits non-zero or prints an unreadable report confirms nothing.
    - A marker that cannot be cleared after a confirmed cancel refuses the stop: the failure names the sidecar, the
      job confirmed cancelled is still listed as cancelled, and no job after it is tried.
    - A job the core CLI reports already over keeps its marker for the collect tick and is reported as terminal,
      never as cancelled.
    - A job with no bundle on disk has its marker cleared and is reported as neither cancelled nor terminal.

  Args:
    file_path: Absolute path to the reviewed document.

  Returns:
    The ids of the jobs cancelled, the ids of the jobs already over, and the failure reason when a job could not be
    cancelled, a marker could not be cleared after a confirmed cancel, or the job markers could not be read; in the
    last case nothing is changed.
  """

  # Contract:
  # A document whose job markers were read and show no job in flight is left alone and the core CLI is never called.

  # Contract:
  # A job-marker sidecar that exists but cannot be read, or reads but is no store, is NEVER read as "no job in
  # flight": the call returns a failure naming the sidecar and the error, before any cancel call is made and before
  # any marker is changed.

  # Contract:
  # The coordinator job is cancelled before the expert job.

  # Contract:
  # A job the core CLI does not confirm cancelled keeps its marker, and no job after it is tried; a call that times
  # out, cannot be launched, exits non-zero or prints an unreadable report confirms nothing.

  # Contract:
  # A marker that cannot be cleared after a confirmed cancel refuses the stop: the returned failure names the
  # sidecar, the job confirmed cancelled is still listed as cancelled, and no job after it is tried.

  # Contract:
  # Only a job the core CLI reports `cancelled: true` is listed as cancelled; a job it reports already over keeps
  # its marker for the collect tick and is listed as terminal.

  # Contract:
  # A job with no bundle on disk has its marker cleared and is listed as neither cancelled nor terminal.

  # Domain(review.lifecycle):
  # # Stopping first cancels the work in flight
  # An expert may still be writing into a document whose review is being stopped, and its result would land in a
  # document that no longer expects it; the coordinator deciding the document's next move would hand out more work.
  # Stopping therefore cancels the work in flight on the document first, the coordinator's turn before the
  # expert's. The stop goes ahead only when every cancellation is confirmed; if one is not, the review is refused
  # its stop, the jobs after it are not tried and the document is not changed, since the job may still be
  # running. A job already confirmed cancelled before it stays cancelled and is reported as such. A cancellation that does not answer
  # in time counts as unconfirmed. A job that had already finished is not cancelled at all: it stays tracked so
  # that its result is still collected. Before anything is cancelled the stop looks up which jobs are in flight on
  # the document; when that record exists but cannot be read, or can be read but is not a valid record at all, the
  # stop is refused and nothing is changed. A failed lookup is never taken to mean that no job is running, because
  # stopping a review whose jobs may still be running leaves work in flight that nobody will collect. The same
  # holds once a job has been cancelled: if the record of that job cannot then be cleared, the stop is refused as
  # well, since the record would go on naming a job that no longer runs.

  repo = _find_repo_root(file_path)

  # guard: markers that cannot be read do not say "no job in flight"; the stop is refused before anything changes
  try:
    markers = _job_markers.read_checked(repo, file_path)
  except OSError as error:
    return JobsCancelResult(
        failure = (
            f"job markers cannot be read: {_job_markers.sidecar_path(repo)}: {type(error).__name__}: {error}"
        ),
    )
  cancelled: list[str] = []
  terminal: list[str] = []

  # the coordinator's turn goes first, so it cannot hand out a new job once the expert's is gone
  for marker in ( JobMarker.COORDINATOR_JOB, JobMarker.ACTIVE_JOB ):
    # guard: nothing in flight under this marker, nothing to cancel
    if not (job_id := markers[marker]):
      continue

    # the core CLI answers for the job under this marker
    answer = _cancel_job(repo, job_id)

    # guard: an unconfirmed cancel leaves the job tracked and stops the sweep
    if answer.failure is not None:
      return JobsCancelResult(cancelled = cancelled, terminal = terminal, failure = answer.failure)

    # a job already over keeps its marker, so the collect tick still collects its result
    if answer.terminal:
      terminal.append(job_id)
      continue

    # a job gone or cancelled no longer needs its marker; only a cancelled one is reported as such
    if answer.cancelled:
      cancelled.append(job_id)

    # guard: a marker that cannot be cleared keeps naming the job, so the stop is refused before the next job
    try:
      _job_markers.update(repo, file_path, { marker: None })
    except OSError as error:
      return JobsCancelResult(
          cancelled = cancelled, terminal = terminal,
          failure = (
              f"job marker cannot be cleared: {_job_markers.sidecar_path(repo)}: {type(error).__name__}: {error}"
          ),
      )

  # every job in flight is gone
  return JobsCancelResult(cancelled = cancelled, terminal = terminal)


def _cancel_job(repo: Path, job_id: str) -> _JobAnswer:
  """
  Cancel every bundle of one job through the core CLI.

  Args:
    repo: Repository root holding the job store.
    job_id: The job's id.

  Returns:
    No flag set when no bundle carries the id; `cancelled` when the call cancelled a bundle; `terminal` when every
    bundle was already over; `failure` when a cancel is unconfirmed — the job queue cannot be listed, the core CLI
    cannot be resolved, a non-zero exit, a report that cannot be read, a call that cannot be launched or runs out of
    time.
  """
  # the bundle's parent folder names the expert the core CLI addresses the job by
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR

  # guard: a job queue that cannot be listed cannot show whether the job is still there, so nothing is confirmed
  try:
    experts = sorted(
        folder.name for folder in (jobs_root.iterdir() if jobs_root.is_dir() else ()) if (folder / job_id).is_dir()
    )
  except OSError as error:
    return _JobAnswer(failure = f"{_CANCEL_JOB} {job_id}: job queue cannot be listed: {error}")

  # guard: no bundle on disk, nothing left to stop
  if not experts:
    return _JobAnswer()

  # guard: without the core CLI, which is what cancels a bundle, the job cannot be stopped
  try:
    cli = _git_ops.require_core_cli(repo)
  except RuntimeError as error:
    return _JobAnswer(failure = f"{_CANCEL_JOB} {job_id}: {error}")

  # every bundle carrying the id is cancelled before the marker is let go
  env = { **os.environ, EnvVar.LAZY_REPO_ROOT: str(repo) }
  cancelled = False
  for expert in experts:
    try:
      done = subprocess.run(
          [ sys.executable, str(cli), _CANCEL_JOB ],
          input = json.dumps({ JobKey.EXPERT: expert, JobKey.JOB_ID: job_id }),
          capture_output = True, text = True, env = env, check = False, encoding = "utf-8",
          errors = _DECODE_ERRORS, timeout = _CANCEL_TIMEOUT_S,
      )
    except (OSError, subprocess.TimeoutExpired) as error:
      return _JobAnswer(failure = f"{_CANCEL_JOB} {expert}/{job_id} failed: {error}")

    # guard: an unconfirmed cancel leaves the job tracked
    if done.returncode != 0:
      return _JobAnswer(
          failure = f"{_CANCEL_JOB} {expert}/{job_id} failed: {(done.stderr or done.stdout or '').strip()}",
      )

    # guard: a report that does not say whether the job was cancelled confirms nothing
    if (answer := _parse_cancelled(done.stdout)) is None:
      return _JobAnswer(failure = f"{_CANCEL_JOB} {expert}/{job_id}: unreadable report {done.stdout.strip()!r}")

    # one cancelled bundle is enough for the job to count as cancelled by the call
    cancelled = cancelled or answer

  # a job none of whose bundles the call cancelled was already over
  return _JobAnswer(cancelled = cancelled, terminal = not cancelled)


def _parse_cancelled(stdout: str) -> bool | None:
  """
  Parse whether a core `cancel-job` report says the call cancelled the job.

  Args:
    stdout: What the core CLI printed.

  Returns:
    The report's `cancelled` flag; None when the report cannot be read or carries no such flag.
  """
  # an unreadable report says nothing
  try:
    report = json.loads(stdout)
  except json.JSONDecodeError:
    return None

  # only a boolean flag on an object is an answer
  flag = report.get(_CANCELLED_KEY) if isinstance(report, dict) else None
  return flag if isinstance(flag, bool) else None


def main(argv: list[str]) -> int:
  """
  Stop an active review from the command line.

  Guarantees:
    - A review whose in-flight coordinator job or expert job cannot be confirmed cancelled, a cancel call that
      times out or cannot be launched included, or whose job marker cannot be cleared after a confirmed cancel, is
      not stopped: the command exits 1 and the document is left unchanged.
    - A job-marker sidecar that exists but cannot be read, or reads but is no store, is never read as "no job in
      flight": the command exits 1 with one stderr line naming the sidecar path and the error, and changes nothing:
      no cancel call is made, the document is not written and nothing is committed.
    - When git refuses the stop commit, the command exits 1 with one stderr line naming the commit failure and never
      ends in a traceback; the document is restored to its pre-stop bytes and its index entry is put back to HEAD, so
      the tree is left clean. The jobs the call cancelled stay cancelled and are reported.
    - With `--json` the command prints exactly one JSON object,
      `{"file", "changed", "cancelled_jobs", "terminal_jobs", "error"}`, on exit 0 and on exit 1 alike, a failed
      stop commit and a marker that cannot be cleared included, every key always present: `changed` reports whether
      the document was left rewritten, so it is false after a failed commit whose restore succeeded and true when the
      restore failed, `cancelled_jobs` names every job the call cancelled, in cancel order, `terminal_jobs` names
      every job already over whose marker was kept, and `error` is null unless the stop was refused or its commit
      failed: a job could not be cancelled, a job marker could not be read or cleared, or git refused the commit,
      which `error` then names, together with the failure of the restore when the restore itself failed.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success; 1 when the job in flight cannot be cancelled, a job marker cannot be cleared after a
    confirmed cancel, or the job markers cannot be read (the stop is refused and the document is left unchanged), or
    when the stop commit fails (the document is restored and the cancelled jobs stay cancelled); 2 when the file is
    not found.
  """

  # Contract:
  # When the coordinator job or the expert job in flight on the document cannot be confirmed cancelled, a cancel call
  # that times out or cannot be launched included, or its job marker cannot be cleared after a confirmed cancel, the
  # command exits 1 and the document is left unchanged.

  # Contract:
  # When the job-marker sidecar exists but cannot be read, or reads but is no store, the command NEVER treats it as
  # "no job in flight": it exits 1 with one stderr line naming the sidecar path and the error, and changes nothing.
  # No cancel call is made, the document is NOT written and nothing is committed.

  # Contract:
  # When git refuses the stop commit, the command exits 1 with one stderr line naming the commit failure and NEVER
  # ends in a traceback. The document is restored to its pre-stop bytes and its index entry is put back to HEAD, so
  # the tree is left clean. The jobs the call cancelled stay cancelled and are reported.

  # Contract:
  # With `--json` the command prints exactly one JSON object,
  # `{"file", "changed", "cancelled_jobs", "terminal_jobs", "error"}`, on exit 0 and on exit 1 alike, a failed stop
  # commit and a marker that cannot be cleared included, every key always present: `changed` reports whether the
  # document was left rewritten, so it is false after a failed commit whose restore succeeded and true when the
  # restore failed, `cancelled_jobs` names every job the call cancelled, in cancel order, `terminal_jobs` names every
  # job already over whose marker was kept, and `error` is null unless the stop was refused or its commit failed: a
  # job could not be cancelled, a job marker could not be read or cleared, or git refused the commit, which `error`
  # then names, together with the failure of the restore when the restore itself failed.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.stop")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--strip-banner", action="store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--json", action="store_true")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()

  # guard: a missing document has no review to stop
  if not file_path.exists():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # the work in flight is cancelled first, so no writer lands into the stopped document
  jobs = cancel_review_jobs(file_path)

  # guard: a job that may still be running leaves the review as it is
  if jobs.failure is not None:
    sys.stderr.write(f"{jobs.failure}\n")
    if args.json:
      print(_format_report(file_path, jobs, changed = False))
    return 1

  # with every job gone the review is stopped, and committed unless the caller keeps the commit
  before = file_path.read_bytes()
  changed = stop_review(file_path, strip_banner = args.strip_banner)

  # guard: a commit git refused puts the document back as it was before the stop, so the tree stays clean and the
  # stop can be retried; the failure is told in one line and, with `--json`, in the one report the caller reads
  try:
    if changed and not args.no_commit:
      _atomic_commit(file_path)
  except subprocess.CalledProcessError as error:

    # Domain(review.lifecycle):
    # # A refused stop leaves no half-done stop behind
    # A stop is recorded by one commit of the document. When that commit is refused, the document is put back
    # exactly as it was before the stop, so nothing of the stop lingers in it, neither in the file nor among the
    # changes waiting to be committed, and the stop can simply be tried again. The work that was already cancelled
    # before the commit is not revived: it stays cancelled, and the refusal is reported together with the jobs
    # that were cancelled, so the caller can resume the review or raise its wakes again.

    # the refusal is told first, then the document is put back, and a failed put-back is appended to the same line
    reason = f"stop commit failed: {os.fsdecode(error.stderr or error.stdout or b'').strip() or error}"
    unrestored = _restore_document(file_path, before)
    if unrestored is not None:
      reason = f"{reason}; {unrestored}"
    sys.stderr.write(f"{reason}\n")
    if args.json:
      print(_format_report(file_path, replace(jobs, failure = reason), changed = unrestored is not None))
    return 1

  # a caller that acts on what the stop cancelled reads the JSON form
  report = f"stopped: {file_path} (changed={changed})"
  if args.json:
    report = _format_report(file_path, jobs, changed = changed)
  print(report)
  return 0


def _format_report(file_path: Path, jobs: JobsCancelResult, *, changed: bool) -> str:
  """
  Render the `--json` report of one stop.

  Args:
    file_path: The reviewed document.
    jobs: The outcome of cancelling the jobs in flight.
    changed: Whether the document was rewritten.

  Returns:
    The report as one line of JSON.
  """
  # waiver: the report's own wire-shape keys, read by callers that resume or wake the review
  return json.dumps({ "file": str(file_path), "changed": changed, "cancelled_jobs": jobs.cancelled,
                      "terminal_jobs": jobs.terminal, "error": jobs.failure })


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
