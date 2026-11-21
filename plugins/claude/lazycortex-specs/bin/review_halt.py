from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_keys import SpecKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The sibling plugin that owns reviews, reached through its CLI.
_REVIEW_CLI = "lazycortex-review"

# The stop verb with its flags: the commit stays with the caller, the banner comes down, and the report is JSON.
_STOP_ARGS = ( "stop", "--no-commit", "--strip-banner", "--json" )

# The verb that raises a review's `job-done` wake again, and the flag naming the repository it acts in.
_WAKE_VERB = "raise-wake"
_REPO_FLAG = "--repo"

# The seconds one review verb may run before it counts as failed.
_VERB_TIMEOUT_S = 60

# The jobs a review stop may cancel one after the other — the coordinator's, then the expert's — and the seconds of
# headroom the stop keeps beyond their cancels for its own work.
_STOP_JOBS = 2
_STOP_MARGIN_S = 30

# The seconds the stop verb may run: one core job-cancel bound per job it may cancel, plus the margin, so a slow but
# successful stop is never cut short.
_STOP_TIMEOUT_S = _STOP_JOBS * spec_job_markers.CANCEL_TIMEOUT_S + _STOP_MARGIN_S

# How a verb's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# The prefixes of the reasons a failed stop or wake is reported with.
_STOP_FAILED = "review stop failed"
_WAKE_FAILED = "review wake failed"

# waiver: the review plugin's own `stop --json` wire key naming the jobs the stop cancelled
_CANCELLED_JOBS_KEY = "cancelled_jobs"

# The frontmatter spelling of a true flag.
_TRUE = "true"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class ReviewRun:
  """
  The outcome of one review plugin verb.

  Attributes:
    failure: The reason the verb did not exit zero, absent when it did.
    stdout: The text the verb printed.
  """

  failure: str | None = None
  stdout: str = ""


# ----------------------------------------------------------------------------------------
class ReviewHalt:
  """
  Record of the reviews one call stopped and the files it may have to put back.

  Lets a call that stops reviews and writes files take every stop and write back when it is refused or fails, with
  the jobs the stops cost woken again. It also tells whether a commit has landed since the call started writing, and
  leaves the committed tree alone once one has.

  Attributes:
    stopped: The documents whose review the call stopped, in stop order.
    failed_doc: The document whose stop failed.
    failure: The reason that stop failed.
  """

  def __init__(self) -> None:
    """
    Start with nothing stopped and nothing held.
    """
    # the bytes each held file had before the call, None for a file that did not exist
    self._snapshots: dict[Path, bytes | None] = {}

    # the documents whose review the call stopped, in stop order
    self.stopped: list[Path] = []

    # the documents whose review may have lost a job to a stop, so a taken-back stop raises their wake again
    self._wake: list[Path] = []

    # the document whose stop failed and why, absent while every stop succeeded
    self.failed_doc: Path | None = None
    self.failure: str | None = None

    # the repository and the commit it stood on when the call started writing, absent until `hold_head`
    self._repo: Path | None = None
    self._head = ""

  def hold_head(self, repo: Path) -> None:
    """
    Record the commit a repository stands on before the call writes.

    Lets `rollback_uncommitted` tell whether a commit has landed in that repository since.

    Args:
      repo: The repository the call commits into.

    Raises:
      subprocess.CalledProcessError: If git fails while reading HEAD.
      OSError: If git cannot be run to read HEAD.
    """
    self._repo, self._head = repo, _read_head(repo)

  def rollback_uncommitted(self) -> bool:
    """
    Take every stop and write back, but only while no commit has landed since `hold_head`.

    Guarantees:
      - Once a commit has landed in the held repository since `hold_head`, no file is restored, no wake is raised and
        the result is False, so the committed tree stays as HEAD has it.
      - Until such a commit lands, or when `hold_head` was never called, it takes back exactly what `rollback` takes
        back and the result is True.

    Returns:
      True when the stops and writes were taken back; False when a commit had already landed.

    Raises:
      subprocess.CalledProcessError: If git fails while reading HEAD; a failed read is never compared with the held
        commit, and nothing is taken back.
      OSError: If git cannot be run to read HEAD; nothing is taken back.
    """

    # Contract:
    # Once a commit has landed in the held repository since `hold_head`, NO file is restored, no wake is raised and
    # the result is False, so the committed tree stays as HEAD has it.

    # Contract:
    # Until such a commit lands, or when `hold_head` was never called, it takes back exactly what `rollback` takes
    # back and the result is True.

    # guard: a landed commit carries the writes, so taking them back would dirty the tree against HEAD
    if self._repo is not None and _read_head(self._repo) != self._head:
      return False

    # nothing is committed yet, so every stop and write is taken back
    self.rollback()
    return True

  def stop(self, docs: Iterable[Path]) -> bool:
    """
    Stop the review of every given document that is under review, until one stop fails.

    Guarantees:
      - Every document a stop is attempted on is held with its bytes from before the attempt, the failing one
        included, so `rollback` gives each of them its bytes back.
      - A document whose stop reports cancelled jobs, or whose stop leaves no readable report, is woken again by
        `rollback`.
      - No stop is attempted after the first one that fails.

    Args:
      docs: The documents to consider; one outside review is skipped.

    Returns:
      True when every review was stopped; False when one could not be, `failed_doc` and `failure` then naming it.
    """

    # Contract:
    # Every document a stop is attempted on is held with its bytes from before the attempt, the failing one included,
    # so `rollback` gives each of them its bytes back.

    # Contract:
    # A document whose stop reports cancelled jobs, or leaves no readable report, is woken again by `rollback`.

    # Contract:
    # No stop is attempted after the first one that fails.

    # Domain(spec.lifecycle):
    # # Stopping reviews that may have to be taken back
    # A review stopped for a call that is later refused, or that fails, has to come back exactly as it was.
    # Stopping a review also cancels the jobs it had running, and the review would wait for them forever, so a
    # review whose stop cancelled a job, or whose stop said nothing that can be read, is woken again when the stop is
    # taken back. The stops end at the first one that fails, and that review is put back too, since a failed stop may
    # already have written part of its change.

    for doc in docs:
      values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))

      # guard: a document outside review has no review to stop
      if values.get(SpecKey.REVIEW_ACTIVE, "").strip() != _TRUE:
        continue

      # the document is held with its bytes from before the attempt, then its review is stopped
      self.keep([ doc ])
      run = run_review_verb(doc, _STOP_ARGS, _STOP_FAILED)

      # a stop that cancelled a job, or whose report cannot be read, may have left the review waiting
      if _has_lost_jobs(run.stdout):
        self._wake.append(doc)

      # guard: the first stop that fails ends the stops and names its document
      if run.failure is not None:
        self.failed_doc, self.failure = doc, run.failure
        return False

      # a stopped review rides the caller's commit
      self.stopped.append(doc)

    # every review under way is stopped
    return True

  def keep(self, paths: Iterable[Path]) -> None:
    """
    Hold the current bytes of files the caller is about to write, so `rollback` restores them.

    A file already held keeps the bytes it was first held with; a file that does not exist yet is removed again by
    `rollback`.

    Guarantees:
      - A file held more than once is given back the bytes of its first hold.

    Args:
      paths: The files about to be written.
    """

    # Contract:
    # A file held more than once is given back by `rollback` with the bytes of its FIRST hold, so a later hold never
    # overwrites what the call started from.

    # the first bytes held win, so a later hold never overwrites what the call started from
    for path in paths:
      if path not in self._snapshots:
        self._snapshots[path] = path.read_bytes() if path.is_file() else None

  def rollback(self) -> None:
    """
    Give every held file its bytes back, then raise again the wake of every review that may have lost a job.

    A wake that cannot be raised, one whose repository cannot be looked up included, is reported on stderr and
    skipped; the other wakes still run.

    Guarantees:
      - Every held file has exactly the bytes it was held with, and a held file that did not exist is removed.
      - A wake that cannot be raised is reported on stderr, never raised, and never stops the next one.
    """

    # Contract:
    # Every held file has exactly the bytes it was held with after `rollback`, and a held file that did not exist is
    # removed; the wake of every review that may have lost a job is raised again after the files are back.

    # Contract:
    # A wake that cannot be raised is reported on stderr, NEVER raised, and never stops the next wake.

    # every held file is back to what it was, a file created since removed
    for path, data in self._snapshots.items():
      if data is None:
        path.unlink(missing_ok = True)
      else:
        path.write_bytes(data)

    # each review whose job a stop cancelled carries on from its wake
    for doc in dict.fromkeys(self._wake):
      # guard: a wake whose repository cannot be named is reported and skipped, so it never stops the next one
      try:
        repo = flip_gate.repo_root(doc.parent)
      except (subprocess.CalledProcessError, OSError) as error:
        sys.stderr.write(f"review-halt: {doc.name}: {_WAKE_FAILED}: {error}\n")
        continue
      if (failure := run_review_verb(doc, ( _WAKE_VERB, _REPO_FLAG, str(repo) ), _WAKE_FAILED).failure) is not None:
        sys.stderr.write(f"review-halt: {doc.name}: {failure}\n")


def _read_head(repo: Path) -> str:
  """
  Read the commit a repository's HEAD names.

  Args:
    repo: The folder whose repository is read.

  Returns:
    The commit id, empty only when the folder is not in a git repository or the repository has no commit.

  Raises:
    subprocess.CalledProcessError: If git fails while reading HEAD.
    OSError: If git cannot be run to read HEAD.
  """
  # a folder outside git, or a repository with no commit yet, names no HEAD; a git failure raises, so a failed
  # lookup is never compared as if it were an answer
  return flip_gate.read_head(repo)


def _has_lost_jobs(stdout: str) -> bool:
  """
  Tell whether a stop's report says, or cannot rule out, that the stop cancelled a job of the review.

  Args:
    stdout: What the stop printed.

  Returns:
    True when the report names a cancelled job or cannot be read; False when it names none.
  """
  # an unreadable or malformed report cannot rule a cancelled job out
  try:
    report = json.loads(stdout)
  except json.JSONDecodeError:
    return True

  # guard: a report that is not an object names nothing it can be trusted for
  if not isinstance(report, dict):
    return True
  return bool(report.get(_CANCELLED_JOBS_KEY))


def _timeout_for(verb: str) -> float:
  """
  Name the seconds one review verb may run by default.

  Args:
    verb: The review plugin verb.

  Returns:
    The stop bound for `stop`, the ordinary verb bound otherwise.
  """
  # a stop cancels jobs one after the other, each under its own bound
  return _STOP_TIMEOUT_S if verb == _STOP_ARGS[0] else _VERB_TIMEOUT_S


def run_review_verb(doc: Path, args: tuple[str, ...], failed: str, *, timeout: float | None = None) -> ReviewRun:
  """
  Run one review plugin verb on a document, bounded in time.

  Guarantees:
    - A verb that cannot be launched, runs out of time or exits non-zero is reported in the returned failure and
      never raised.
    - The stop verb, run without an explicit timeout, is allowed longer than the cancels of both jobs it may
      stop take together, so a slow but successful stop is never cut short and counted as failed.

  Args:
    doc: The document the verb acts on.
    args: The verb followed by its flags.
    failed: The prefix of the reason returned on a failure.
    timeout: The seconds the verb may run; None gives the stop verb its own bound and every other verb the default.

  Returns:
    The reason the verb failed, None when it exited zero, and what it printed; a verb that cannot be launched or runs
    out of time is a failure with nothing printed.
  """

  # Contract:
  # A verb that cannot be launched, runs out of time or exits non-zero is reported in the returned failure and NEVER
  # raised, so a caller taking its work back can always carry on.

  # Contract:
  # The stop verb, run without an explicit timeout, is allowed longer than the cancels of both jobs it may stop take
  # together, so a slow but successful stop is never cut short and counted as failed.

  # guard: no explicit timeout given, fall back to the verb's own allowance
  if timeout is None:
    timeout = _timeout_for(args[0])

  # the review plugin owns the review keys and the banner, so its own verbs change them
  try:
    cli = spec_paths.require_plugin_cli(_REVIEW_CLI, spec_paths.find_settings_root(doc.parent))
    done = subprocess.run(
        [ sys.executable, str(cli), args[0], str(doc.resolve()), *args[1:] ],
        capture_output = True, timeout = timeout, check = False,
        encoding = "utf-8", errors = _DECODE_ERRORS,
    )
  except (RuntimeError, OSError, subprocess.SubprocessError) as error:
    return ReviewRun(failure = f"{failed}: {error}")

  # a non-zero exit names its own cause on stderr
  failure = None if done.returncode == 0 else f"{failed}: {(done.stderr or '').strip()}"
  return ReviewRun(failure = failure, stdout = done.stdout or "")
