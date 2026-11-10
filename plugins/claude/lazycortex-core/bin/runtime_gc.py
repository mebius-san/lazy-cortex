"""
Implementation of the `lazycortex-core runtime-gc` subcommand.

Sweeps the garbage the core runtime leaves in a checkout: job bundles past their retention window, job bundles
that sit in the queue root outside any expert folder, and files in `.runtime/` that no one owns. Queued jobs that
nobody claimed for too long are never deleted; they are reported to the error ledger instead. A dry run deletes and
records nothing, and each real deletion is appended to a journal under `.logs/lazy-core/`.
"""
from __future__ import annotations

from typing import TypeAlias

import json
import os
import shutil
import stat
import time
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import error_ledger  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from job_response import classify_response, is_job_bundle, read_response  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  DaemonKey, IncidentActor, IncidentKey, IncidentKind, IncidentPhase, IncidentState, JobMarker, JobStatus,
  RuntimeFile, RuntimeGcKey, RuntimeGcKind, SettingsFile, SettingsKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# The sweep summary: the mode flag, removed paths per kind, stuck job names, and failed deletions.
SweepSummary: TypeAlias = dict[str, bool | dict[str, list[str]] | list[str] | list[dict[str, str]]]

# Repo-relative root of the expert job queue.
JOBS_BASE = ".experts/.jobs"
# Repo-relative directory of the per-machine runtime files.
RUNTIME_DIR = ".runtime"
# Repo-relative journal the sweep appends one line to per deletion.
JOURNAL_REL = ".logs/lazy-core/runtime-gc.jsonl"
# Error-ledger cause of a queued job nobody claimed within the staleness age.
CAUSE_QUEUED_TOO_LONG = "queued-too-long"
# Severity of the queued-too-long event: the job is waiting, nothing has failed yet.
_SEVERITY_WARN = "warn"
# UTC timestamp format of a journal line and of the event detail.
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
# Shipped retention windows, used when the `daemon` section leaves a key unset.
_DEFAULT_COMPLETED_AFTER = "7d"
_DEFAULT_FAILED_AFTER = "30d"
_DEFAULT_DEAD_AFTER = "7d"
# Name prefix every plugin namespace starts with; a runtime file under it belongs to that plugin.
_PLUGIN_PREFIX = "lazy-"
# File each self-ignoring service directory carries so git never sees its contents.
_GITIGNORE = ".gitignore"
# Names of the runtime files core itself writes.
_CORE_RUNTIME_NAMES = frozenset({
  *(Path(rel).name for rel in (
    runtime_state.STATE_REL, error_ledger.JOURNAL_REL, error_ledger.SNAPSHOT_REL,
    RuntimeFile.SANDBOX_SETTINGS, RuntimeFile.PAUSE, RuntimeFile.CONSUMED_UNPUSHED,
    RuntimeFile.CONSUMED_UNPUSHED_LOCK, RuntimeFile.RATE_LIMIT_DEFERRED,
  )),
  _GITIGNORE,
})
# Markers whose presence means a queued job was claimed or has already ended.
_PAST_QUEUE_MARKERS = ( JobMarker.DONE, JobMarker.DEAD, JobMarker.CANCELLED, JobMarker.PID )


# ----------------------------------------------------------------------------------------
class _Sweep:
  """
  One pass of the runtime sweep over a repository, collecting what it removed, found stuck, or failed to remove.

  Attributes:
    repo: Repository root the sweep runs over.
    dry_run: Whether the sweep only reports what it would remove.
    done_after: Retention window in seconds for jobs whose response proves the work finished.
    fail_after: Retention window in seconds for every other finished or cancelled job, and the staleness age.
    dead_after: Retention window in seconds for jobs that were marked dead.
    removed: Repository-relative paths removed, grouped by garbage kind.
    stuck: Queued jobs nobody claimed, as `<expert>/<job id>`.
    errors: Deletions that failed and journal records that were lost, each with its kind, path, and error text.
  """

  def __init__(self, repo: Path, *, dry_run: bool) -> None:
    """
    Prepare a sweep of the given repository.

    Args:
      repo: Repository root the sweep runs over.
      dry_run: Whether the sweep only reports what it would remove.
    """
    # the repository and the mode every step below consults
    self.repo: Path = repo
    self.dry_run: bool = dry_run

    # retention windows, in seconds, from the `daemon` section
    daemon = load_section(repo / SettingsFile.REL, SettingsKey.DAEMON)
    self.done_after: float = _parse_duration(
      daemon.get(DaemonKey.CLEANUP_COMPLETED_AFTER, _DEFAULT_COMPLETED_AFTER))
    self.fail_after: float = _parse_duration(daemon.get(DaemonKey.CLEANUP_FAILED_AFTER, _DEFAULT_FAILED_AFTER))
    self.dead_after: float = _parse_duration(daemon.get(DaemonKey.CLEANUP_DEAD_AFTER, _DEFAULT_DEAD_AFTER))

    # the summary the sweep fills in as it goes
    self.removed: dict[str, list[str]] = {
      kind: [] for kind in (
        RuntimeGcKind.EXPIRED_JOB, RuntimeGcKind.MISPLACED_JOB, RuntimeGcKind.OWNERLESS_RUNTIME_FILE)
    }
    self.stuck: list[str] = []
    self.errors: list[dict[str, str]] = []

  def run(self) -> SweepSummary:
    """
    Sweep the job queue and the runtime directory.

    Returns:
      The sweep summary.
    """
    # both garbage sources, each skipped when absent
    self._sweep_jobs()
    self._sweep_runtime_files()

    # the summary, with the removed paths in a stable order
    return {
      RuntimeGcKey.DRY_RUN: self.dry_run,
      RuntimeGcKey.REMOVED: { kind: sorted(paths) for kind, paths in self.removed.items() },
      RuntimeGcKey.STUCK_QUEUED: self.stuck,
      RuntimeGcKey.ERRORS: self.errors,
    }

  def _sweep_jobs(self) -> None:
    """
    Sweep the job queue for misplaced bundles, expired bundles, and queued jobs nobody claimed.
    """
    jobs_root = self.repo / JOBS_BASE

    # guard: no queue on disk yet — nothing to sweep
    if not jobs_root.is_dir():
      return

    # walk every queue-root entry against one clock reading
    now = time.time()
    for entry in sorted(jobs_root.iterdir()):
      # guard: a stray file in the queue root is neither an expert folder nor a bundle
      if not entry.is_dir():
        continue

      # Domain(runtime.jobs):
      # # Misplaced job folder
      # A job folder belongs inside an expert's own folder. One that sits directly in the queue root belongs to
      # no expert, so nothing owns it. It is removed once nothing in it has changed for the failed window; the
      # newest change among its entries counts, not the date of the folder itself.

      # a bundle directly in the queue root belongs to no expert; it goes once nothing touched it for long
      if is_job_bundle(entry):
        if now - _newest_entry_mtime(entry) >= self.fail_after:
          self._remove(entry, RuntimeGcKind.MISPLACED_JOB, _delete_tree)
        continue

      # every bundle of an expert folder is either stuck in the queue, expired, or left alone
      for jdir in sorted(entry.iterdir()):
        # guard: only real bundles are queue entries
        if not is_job_bundle(jdir):
          continue

        # a bundle nobody claimed is reported as stuck; one past its retention window goes
        if _is_stuck_queued(jdir, self.fail_after, now):
          self._report_stuck(entry.name, jdir.name)
        elif _is_expired(jdir, self.done_after, self.fail_after, self.dead_after):
          self._remove(jdir, RuntimeGcKind.EXPIRED_JOB, self._cleanup_bundle)

  def _sweep_runtime_files(self) -> None:
    """
    Remove the stale files in the runtime directory that neither core nor a plugin owns.
    """

    # Domain(unfiled):
    # # Ownership of runtime directory files
    # The per-machine runtime directory holds files that someone owns and files that nobody does. Core's own
    # runtime files, their temporary siblings (the same name followed by a dot and a suffix, whether or not it is
    # also led by a dot) and everything under the `lazy-` plugin-namespace prefix are owned and always kept.
    # Any other plain file not modified for the failed window is leftover and removed. Directories and links are
    # never touched.

    runtime_dir = self.repo / RUNTIME_DIR

    # guard: no runtime directory yet — nothing to sweep
    if not runtime_dir.is_dir():
      return

    # walk every runtime-directory entry against one clock reading
    now = time.time()
    for path in sorted(runtime_dir.iterdir()):
      # guard: an entry that vanished between the listing and the stat is skipped
      try:
        info = path.lstat()
      except OSError:
        continue

      # guard: only plain files are swept; directories, links and owned names stay
      if not stat.S_ISREG(info.st_mode) or _is_owned_runtime_name(path.name):
        continue

      # an ownerless file untouched for the failed window goes
      if now - info.st_mtime >= self.fail_after:
        self._remove(path, RuntimeGcKind.OWNERLESS_RUNTIME_FILE, _delete_file)

  def _cleanup_bundle(self, jdir: Path) -> int:
    """
    Remove one expired job bundle under the sweep's retention windows.

    Args:
      jdir: The job bundle.

    Returns:
      1 when the bundle was removed, 0 when it turned out to be inside its window after all.
    """
    return _maybe_cleanup(jdir, self.done_after, self.fail_after, self.dead_after)

  def _remove(self, path: Path, kind: str, delete: Callable[[Path], int]) -> None:
    """
    Remove one piece of garbage, or only record it in a dry run.

    Args:
      path: The file or directory to remove.
      kind: The garbage kind it is recorded under.
      delete: Deletes the path and returns how many items it removed.
    """
    rel = path.relative_to(self.repo).as_posix()

    # a dry run only reports what would go
    if self.dry_run:
      self.removed[kind].append(rel)
      return

    # a failed deletion is recorded and the sweep moves on to the next item
    try:
      gone = delete(path)
    except OSError as error:
      self.errors.append({ RuntimeGcKey.KIND: kind, RuntimeGcKey.PATH: rel, RuntimeGcKey.ERROR: str(error) })
      return

    # a deletion that happened is listed and journaled
    if gone:
      self.removed[kind].append(rel)
      self._journal(kind, rel)

  def _journal(self, kind: str, rel: str) -> None:
    """
    Append one deletion to the sweep's journal, or list the lost record in the errors when the write fails.

    Args:
      kind: The garbage kind removed.
      rel: The repository-relative path removed.
    """
    line = json.dumps({
      RuntimeGcKey.TS: time.strftime(_TS_FMT, time.gmtime()), RuntimeGcKey.KIND: kind, RuntimeGcKey.PATH: rel,
    }, ensure_ascii = False)

    # a journal that cannot be written loses the record, never the deletion already done; the lost record lands in
    # the summary's errors so the verb fails and the daemon records it
    journal = self.repo / JOURNAL_REL
    try:
      journal.parent.mkdir(parents = True, exist_ok = True)
      # waiver: stdlib append file-mode idiom
      with journal.open("a", encoding = "utf-8") as handle:
        handle.write(line + "\n")
    except OSError as error:
      self.errors.append({ RuntimeGcKey.KIND: kind, RuntimeGcKey.PATH: JOURNAL_REL, RuntimeGcKey.ERROR: str(error) })

  def _report_stuck(self, expert: str, job_id: str) -> None:
    """
    List a queued job nobody claimed and open its error-ledger incident when none is open yet.

    Args:
      expert: The expert whose queue holds the job.
      job_id: The job's identifier.
    """

    # Domain(runtime.incidents):
    # # Stuck queued job
    # A job that was queued but never claimed is waiting, not failed, so it is never deleted. Once it has waited
    # longer than the failed window with no claim and no end marker, it is reported to the error ledger as one
    # open incident per job with warn severity; a job that already has an open incident gets no second one.
    # The incident closes only when the job later finishes cleanly and its folder is removed past the completed
    # window, which resolves it as recovered by a successful retry.

    self.stuck.append(f"{expert}/{job_id}")

    # guard: a dry run records nothing
    if self.dry_run:
      return

    # the job's incident key
    key = f"job:{expert}/{job_id}"

    # guard: an incident already open for this job is left as it is
    if any(incident.get(IncidentKey.INCIDENT) == key
           and incident.get(IncidentKey.STATE) in ( IncidentState.OPEN, IncidentState.NEEDS_OPERATOR )
           for incident in error_ledger.read_incidents(self.repo, state = IncidentState.ALL)):
      return

    # open the incident on the job's own key; it closes only when the job later finishes cleanly and its bundle is
    # removed past the completed window
    jdir = self.repo / JOBS_BASE / expert / job_id
    queued_at = time.strftime(_TS_FMT, time.gmtime((jdir / JobMarker.READY).stat().st_mtime))
    error_ledger.record(self.repo, {
      IncidentKey.INCIDENT: key, IncidentKey.PHASE: IncidentPhase.OPENED,
      IncidentKey.KIND: IncidentKind.JOB_ERROR, IncidentKey.CAUSE: CAUSE_QUEUED_TOO_LONG,
      IncidentKey.SEVERITY: _SEVERITY_WARN, IncidentKey.ACTOR: IncidentActor.RUNTIME_GC,
      IncidentKey.EXPERT: expert, IncidentKey.JOB_ID: job_id,
      IncidentKey.DETAIL: f"queued since {queued_at} and never claimed",
      # waiver: refs map key, mirroring the pump's own incident refs
      IncidentKey.REFS: { "jdir": str(jdir) },
    })


def sweep(repo: Path, *, dry_run: bool = False) -> SweepSummary:
  """
  Sweep a repository's runtime garbage.

  Removes expired job bundles, job bundles sitting in the queue root outside an expert folder, and stale runtime
  files no one owns. Queued jobs that nobody claimed for too long are reported to the error ledger.

  Guarantees:
    - A queued job that nobody has claimed is never deleted, however long it has waited.
    - A dry run deletes nothing and writes neither the deletion journal nor the error ledger.
    - A deletion that fails is listed in the summary's errors and never stops the sweep.
    - A deletion whose journal record cannot be written still stands and is listed as removed; the lost record is
      listed in the summary's errors.

  Args:
    repo: Repository root.
    dry_run: Whether to only report what would be removed.

  Returns:
    The sweep summary.
  """

  # Contract:
  # A queued job that nobody has claimed is never deleted, only reported. A dry run deletes nothing and records
  # nothing in the journal or the error ledger. One failed deletion lands in the summary's errors and never stops
  # the rest of the sweep. A deletion whose journal record cannot be written is still done and listed as removed,
  # and the lost record lands in the summary's errors, on which the verb's non-zero exit rests.

  return _Sweep(Path(repo), dry_run = dry_run).run()


def _newest_entry_mtime(directory: Path) -> float:
  """
  Return the newest modification time among a directory's direct entries.

  Args:
    directory: The directory to inspect.

  Returns:
    The newest entry mtime, or the directory's own mtime when it has no readable entry.
  """
  # an entry that vanished between the listing and the stat simply does not count
  mtimes: list[float] = []
  for child in directory.iterdir():
    try:
      mtimes.append(child.lstat().st_mtime)
    except OSError:
      continue
  return max(mtimes, default = directory.stat().st_mtime)


def _delete_tree(path: Path) -> int:
  """
  Delete a directory and everything under it.

  Args:
    path: The directory.

  Returns:
    1, the one item removed.

  Raises:
    OSError: When the directory cannot be removed.
  """
  shutil.rmtree(path)
  return 1


def _delete_file(path: Path) -> int:
  """
  Delete a single file.

  Args:
    path: The file.

  Returns:
    1, the one item removed.

  Raises:
    OSError: When the file cannot be removed.
  """
  os.unlink(path)
  return 1


def _is_owned_runtime_name(name: str) -> bool:
  """
  Report whether a file name in the runtime directory belongs to core or to a plugin.

  Args:
    name: The file name.

  Returns:
    `True` for a core runtime file, a temporary sibling of one, or a file under a plugin namespace.
  """
  # core's own names, their temporary siblings, and any plugin namespace are owned
  return (
    name in _CORE_RUNTIME_NAMES
    or name.startswith(_PLUGIN_PREFIX)
    or any(name.startswith((f"{owned}.", f".{owned}.")) for owned in _CORE_RUNTIME_NAMES)
  )


def _is_stuck_queued(jdir: Path, fail_after: float, now: float) -> bool:
  """
  Report whether a job has waited in the queue unclaimed for longer than the staleness age.

  Args:
    jdir: The job bundle.
    fail_after: The staleness age in seconds.
    now: The current wall-clock time.

  Returns:
    `True` for a READY job with no claim and no end marker whose READY is older than `fail_after`.
  """
  ready = jdir / JobMarker.READY

  # guard: a job never queued, or already claimed or ended, is not stuck in the queue
  if not ready.exists() or any((jdir / marker).exists() for marker in _PAST_QUEUE_MARKERS):
    return False
  return now - ready.stat().st_mtime >= fail_after


def _is_expired(jdir: Path, done_after: float, fail_after: float, dead_after: float) -> bool:
  """
  Report whether a job bundle has outlived its retention window.

  Args:
    jdir: The job bundle.
    done_after: Retention window in seconds for jobs whose response proves the work finished.
    fail_after: Retention window in seconds for every other finished or cancelled job.
    dead_after: Retention window in seconds for jobs that were marked dead.

  Returns:
    `True` when the bundle's retention window has elapsed.
  """

  # Domain(runtime.jobs):
  # # Retention windows per job outcome
  # A finished job's bundle is kept for a window that depends on how the job ended, so evidence of trouble
  # outlives evidence of success. Cancellation outranks every other end marker and uses the failed window.
  # A job that ended as done uses the completed window only when its response proves the work succeeded; any
  # other done job (an error outcome, a deferral, a violated envelope) uses the failed window. A job marked
  # dead has its own dead window, kept as a forensic period. A job with no end marker is still live and never
  # expires. The windows are set in the daemon settings; each window runs from the job's end marker.

  # Decision: a cancelled job shares the failed window, not a retention knob of its own — a cancellation is an
  # operator intervention whose forensics deserve the long window.

  # cancellation outranks every other marker (same precedence as status classification)
  if (jdir / JobMarker.CANCELLED).exists():
    return time.time() - (jdir / JobMarker.CANCELLED).stat().st_mtime >= fail_after

  # a finished job is retained for its own window, longer when it ended short of a proven success
  if (jdir / JobMarker.DONE).exists():
    threshold = done_after if classify_response(read_response(jdir)) == JobStatus.DONE else fail_after
    return time.time() - (jdir / JobMarker.DONE).stat().st_mtime >= threshold

  # a dead job is retained on its own window so the operator can still inspect it
  if (jdir / JobMarker.DEAD).exists():
    return time.time() - (jdir / JobMarker.DEAD).stat().st_mtime >= dead_after

  # a job carrying none of these markers is still live
  return False


def _maybe_cleanup(jdir: Path, done_after: float, fail_after: float, dead_after: float) -> int:
  """
  Remove a single job directory once its retention window has elapsed.

  The window is picked by how the job ended. Live jobs and bundles still inside their window are left untouched.

  Notes:
    - Removing a cleanly finished job also closes its still-open error-ledger incident as `retried_ok`.

  Args:
    jdir: Path to the job directory being considered for cleanup.
    done_after: Retention window in seconds for jobs whose response proves the work finished.
    fail_after: Retention window in seconds for every other finished job — an error outcome,
      a deferral, or a violated envelope.
    dead_after: Retention window in seconds for jobs that were marked dead.

  Returns:
    1 if the job directory was removed, 0 otherwise.
  """

  # guard: a bundle still inside its retention window stays
  if not _is_expired(jdir, done_after, fail_after, dead_after):
    return 0

  # a clean job that still has an open incident was retried after a failure → resolved:retried_ok
  is_clean = (
    not (jdir / JobMarker.CANCELLED).exists()
    and (jdir / JobMarker.DONE).exists()
    and classify_response(read_response(jdir)) == JobStatus.DONE
  )
  key = f"job:{jdir.parent.name}/{jdir.name}"
  if is_clean and any(
    incident.get(IncidentKey.INCIDENT) == key
    and incident.get(IncidentKey.STATE) in ( IncidentState.OPEN, IncidentState.NEEDS_OPERATOR )
    # waiver: the queue layout fixes the repo root at <repo>/.experts/.jobs/<expert>/<job>
    for incident in error_ledger.read_incidents(jdir.parents[3], state = IncidentState.ALL)):
    # waiver: the queue layout fixes the repo root at <repo>/.experts/.jobs/<expert>/<job>; resolution token
    error_ledger.resolve(jdir.parents[3], key, resolution = "retried_ok",
                         kind = IncidentKind.JOB_DEAD, actor = IncidentActor.RUNTIME_GC)

  # the expired bundle goes
  shutil.rmtree(jdir)
  return 1


def _parse_duration(text: str) -> float:
  """
  Parse a human-readable duration string into seconds.

  Args:
    text: Duration string of the form `<number><unit>` where unit is one of `s`, `m`, `h`, `d`.

  Returns:
    The duration expressed in seconds as a float.

  Raises:
    KeyError: When the trailing unit character is not recognized.
    ValueError: When the leading portion does not parse as a number.
  """
  units = { "s": 1, "m": 60, "h": 3600, "d": 86400 }
  return float(text[:-1]) * units[text[-1]]
