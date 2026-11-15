"""
`/lazy-review.stop <file>` — bail out of the review loop without finalizing.

Cancels the coordinator job and the expert job in flight on the document, sets `review_active: false` and commits.
Optionally the review banner is removed as well. Body and `approved` are otherwise left untouched so a subsequent
`start` can resume from the operator's last state. A job that cannot be confirmed cancelled leaves the review as it
was. With `--json` the stop prints one JSON report naming the jobs it cancelled and the jobs already over, so a
caller can raise their wakes again or resume the review.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

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
from keys import EnvVar, JobFile, JobKey, JobMarker, Paths, ReviewKey  # noqa: E402


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


def _atomic_commit(file_path: Path) -> None:
  """
  Commit a stopped document on its own.

  Args:
    file_path: The stopped document.

  Raises:
    subprocess.CalledProcessError: If staging or committing the document fails.
  """
  # the document is staged from its own folder
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )

  # the pathspec keeps a concurrently staged foreign file out of the stop commit
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: stop {file_path.name}", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )


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
    The nearest ancestor holding a `.git` entry, or the document's own folder when none does.
  """
  # the nearest ancestor carrying a `.git` entry is the repository the sidecar lives in
  return next(( folder for folder in file_path.parents if (folder / Paths.GIT_DIR).exists() ), file_path.parent)


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
    - A document with no job in flight is left alone and the core CLI is never called.
    - The coordinator job is cancelled before the expert job.
    - A job the core CLI does not confirm cancelled keeps its marker, and no job after it is tried; a call that times
      out, cannot be launched, exits non-zero or prints an unreadable report confirms nothing.
    - A job the core CLI reports already over keeps its marker for the collect tick and is reported as terminal,
      never as cancelled.
    - A job with no bundle on disk has its marker cleared and is reported as neither cancelled nor terminal.

  Args:
    file_path: Absolute path to the reviewed document.

  Returns:
    The ids of the jobs cancelled, the ids of the jobs already over, and the reason a job could not be cancelled
    when one could not.
  """

  # Contract:
  # A document with no job in flight is left alone and the core CLI is never called.

  # Contract:
  # The coordinator job is cancelled before the expert job.

  # Contract:
  # A job the core CLI does not confirm cancelled keeps its marker, and no job after it is tried; a call that times
  # out, cannot be launched, exits non-zero or prints an unreadable report confirms nothing.

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
  # its stop and stays exactly as it was, since the job may still be running. A cancellation that does not answer
  # in time counts as unconfirmed. A job that had already finished is not cancelled at all: it stays tracked so
  # that its result is still collected.

  repo = _find_repo_root(file_path)
  markers = _job_markers.read(repo, file_path)
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
    _job_markers.update(repo, file_path, { marker: None })
    if answer.cancelled:
      cancelled.append(job_id)

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
    bundle was already over; `failure` when a cancel is unconfirmed — a non-zero exit, a report that cannot be read,
    a call that cannot be launched or runs out of time.
  """
  # the bundle's parent folder names the expert the core CLI addresses the job by
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR
  experts = sorted(
      folder.name for folder in (jobs_root.iterdir() if jobs_root.is_dir() else ()) if (folder / job_id).is_dir()
  )

  # guard: no bundle on disk, nothing left to stop
  if not experts:
    return _JobAnswer()

  # guard: without the core CLI, which is what cancels a bundle, the job cannot be stopped
  if (cli := _git_ops.resolve_core_cli()) is None:
    return _JobAnswer(failure = f"{_CANCEL_JOB} {job_id}: lazycortex-core CLI not resolvable")

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
      times out or cannot be launched included, is not stopped: the command exits 1 and the document is left
      unchanged.
    - With `--json` the command prints exactly one JSON object,
      `{"file", "changed", "cancelled_jobs", "terminal_jobs", "error"}`, on exit 0 and on exit 1 alike, every key
      always present: `cancelled_jobs` names every job the call cancelled, in cancel order, `terminal_jobs` names
      every job already over whose marker was kept, and `error` is null unless a job could not be cancelled.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 1 when the job in flight cannot be cancelled, 2 when the file is not found.
  """

  # Contract:
  # When the coordinator job or the expert job in flight on the document cannot be confirmed cancelled, a cancel call
  # that times out or cannot be launched included, the command exits 1 and the document is left unchanged.

  # Contract:
  # With `--json` the command prints exactly one JSON object,
  # `{"file", "changed", "cancelled_jobs", "terminal_jobs", "error"}`, on exit 0 and on exit 1 alike, every key
  # always present: `cancelled_jobs` names every job the call cancelled, in cancel order, `terminal_jobs` names every
  # job already over whose marker was kept, and `error` is null unless a job could not be cancelled.

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
  changed = stop_review(file_path, strip_banner = args.strip_banner)
  if changed and not args.no_commit:
    _atomic_commit(file_path)

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
