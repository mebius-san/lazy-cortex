"""
Sanitizer for stuck review-loop state, run by the daily `lazy-review.sanitize` routine.

Repairs ONLY the three file-provable stuck states named by `state-sanitizers-design.md` — a
finding with any doubt in it reads as not-a-problem and is left exactly as found:

- **Lost writer wake**: the sidecar's `active_job` marker names a bundle that reached a terminal
  state the postman's own sweep never collects — DEAD, CANCELLED, vanished from disk, already
  CONSUMED, or DONE without a deliverable (`edited`) payload. `collect-tick` re-raises the wake
  for a DONE-and-`edited` bundle every minute on its own, so that case is deliberately skipped
  here; every other terminal shape lands nowhere without this sweep. Repair: clear the marker
  (kept in place for the DONE-without-payload shape, which the coordinator judges off the stuck
  marker per `collect_ops`'s contract), raise the `job-done` pending wake, and dispatch the
  coordinator directly.
- **Orphaned review**: a document carries `review_active: true` while nothing can ever move it —
  no live coordinator job, no tracked writer job, no pending wake, and the banner is not one of
  the operator-waiting states (`ready` / `action-needed` / `concerns-decision`, where silence is
  the loop legitimately handing the turn to the operator). Repair: dispatch a coordinator wake —
  the coordinator decides the next move, never this sweep.
- **Review without a document**: a sidecar entry keys a path that no longer exists on disk.
  Repair: drop the entry.

Every repair is runtime-sidecar state or a job dispatch — nothing here writes or commits a
tracked file. One failing document never stops the rest of the sweep; failures are folded into
the summary's `error` field and the exit code, as the error-ledger contract requires.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser`-adjacent sibling modules resolved at runtime via sys.path
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import banner as _banner  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import collect_ops as _collect_ops  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobFile, JobKey, JobMarker, JobStatus, Outcome, ReviewKey  # noqa: E402


# Bundle-state token for an `active_job` marker whose job directory left no trace on disk —
# `_job_status` has no word for it because it classifies an existing directory.
_STATUS_VANISHED = "vanished"

# The banner states in which a silent review loop is the operator's turn, not a stuck loop —
# the orphaned-review check never fires on them.
_OPERATOR_WAITING_STATES = frozenset({
    _banner.State.READY, _banner.State.ACTION_NEEDED, _banner.State.CONCERNS_DECISION,
})

# The `true` literal `frontmatter.parse`'s raw string values are compared against.
_BOOL_TRUE = "true"

# Dedup hint this sweep stamps into its coordinator dispatches, so a re-run of the same repair
# folds into one queued job.
_DEDUP_HINT = "sanitize"


def _job_bundle_dir(repo: Path, job_id: str) -> Path | None:
  """
  Locate the job bundle directory named `job_id` under any expert's queue.

  The sidecar's `active_job` marker records only the job id; the owning expert's name is
  recovered by scanning the queue's expert subdirectories.

  Args:
    repo: Repository root holding `.experts/.jobs/`.
    job_id: The job id read off the sidecar marker.

  Returns:
    The bundle directory, or None when no expert's queue holds one by that name.
  """
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR
  # guard: no job queue at all — every tracked job has vanished
  if not jobs_root.is_dir():
    return None
  for expert_dir in sorted(jobs_root.iterdir()):
    # guard: only expert subdirectories hold job bundles
    if not expert_dir.is_dir():
      continue
    jdir = expert_dir / job_id
    if jdir.is_dir():
      return jdir
  return None


def _done_outcome(jdir: Path) -> str:
  """
  Read a DONE bundle's response outcome.

  Args:
    jdir: The job bundle directory.

  Returns:
    The `response.json` outcome value, or an empty string when the response is absent,
    unreadable, or malformed — a shape the postman will never collect either.
  """
  try:
    outcome = json.loads((jdir / JobFile.RESPONSE).read_text()).get(JobKey.OUTCOME)
  except (OSError, json.JSONDecodeError):
    return ""
  return outcome if isinstance(outcome, str) else ""


def _repair_lost_wake(repo: Path, doc: Path, entry: dict) -> bool:
  """
  Repair one document's lost writer wake, when its tracked job is certainly beyond collection.

  A bundle still running (no terminal marker) and a DONE bundle with an `edited` payload (the
  postman's own minutely sweep re-raises that wake itself) are both skips. Every other terminal
  shape — DEAD, CANCELLED, vanished, CONSUMED, DONE without a deliverable payload — lands
  nowhere without this repair: the wake goes up and the coordinator is dispatched to judge.
  The marker is cleared except in the DONE-without-payload shape, where the coordinator's
  judgment reads off the stuck marker (`collect_ops`'s own contract).

  Args:
    repo: Repository root.
    doc: The tracked document's absolute path (exists on disk — checked by the caller).
    entry: The document's sidecar marker entry.

  Returns:
    True when a repair was applied; False on every skip.
  """
  job_id = entry.get(JobMarker.ACTIVE_JOB)
  # guard: no writer job tracked — nothing to lose a wake for
  if not isinstance(job_id, str) or not job_id:
    return False

  # classify the tracked bundle; a running one keeps its turn untouched
  jdir = _job_bundle_dir(repo, job_id)
  # waiver: type: ignore — collect_ops is a deferred/late-bound sibling import; mypy cannot resolve it
  status = _STATUS_VANISHED if jdir is None else _collect_ops._job_status(jdir)  # type: ignore[attr-defined]
  # guard: still running — not stuck, not this sweep's business
  if status == JobStatus.PENDING:
    return False
  # guard: DONE with a deliverable payload — `collect-tick`'s own minutely sweep re-raises this
  # wake itself; doubling it here would be a second mechanism for a covered case
  if status == JobStatus.DONE and jdir is not None and _done_outcome(jdir) == Outcome.EDITED:
    return False

  # the DONE-without-payload shape keeps its marker for the coordinator to judge off; every
  # other terminal shape clears it alongside the wake
  changes: dict[str, str | None] = { JobMarker.PENDING_WAKE: JobMarker.JOB_DONE }
  if status != JobStatus.DONE:
    changes[JobMarker.ACTIVE_JOB] = None
  _job_markers.update(repo, doc, changes)
  # waiver: type: ignore — coordinator_dispatch is a deferred/late-bound sibling import; mypy cannot resolve it
  _coordinator_dispatch.dispatch_job_done(repo, doc, _DEDUP_HINT)  # type: ignore[attr-defined]
  return True


def _is_orphaned(repo: Path, doc: Path) -> bool:
  """
  Report whether a `review_active` document's loop is certainly silent forever.

  Args:
    repo: Repository root.
    doc: The document's absolute path.

  Returns:
    True when no live coordinator job, no tracked writer job, and no pending wake can ever
    move the document, and the banner is not an operator-waiting state; False on any doubt.
  """
  entry = _job_markers.read(repo, doc)
  # guard: a tracked writer job or a raised wake means the loop still has a next move
  if entry.get(JobMarker.ACTIVE_JOB) or entry.get(JobMarker.PENDING_WAKE):
    return False
  coordinator_job = entry.get(JobMarker.COORDINATOR_JOB)
  # guard: a live coordinator job owns the turn — silence is it working
  # waiver: type: ignore — coordinator_dispatch is a deferred/late-bound sibling import; mypy cannot resolve it
  if isinstance(coordinator_job, str) and coordinator_job \
      and _coordinator_dispatch._is_job_live(repo, coordinator_job):  # type: ignore[attr-defined]
    return False
  _meta, body = _fm.parse(doc.read_text())
  # an operator-waiting banner makes the silence legitimate: the turn is the operator's
  return _banner.extract(body) not in _OPERATOR_WAITING_STATES


def _review_active_docs(repo: Path) -> list[Path]:
  """
  Enumerate every tracked markdown document carrying `review_active: true`.

  Args:
    repo: Repository root.

  Returns:
    Absolute paths of the matching documents, in `git ls-files` order; empty when the repo
    has no git index to enumerate (a bare fixture directory).
  """
  proc = subprocess.run(
      ["git", "ls-files", "--", "*.md"],
      cwd = str(repo), capture_output = True, text = True, check = False,
  )
  # guard: not a git repository — nothing to enumerate
  if proc.returncode != 0:
    return []
  active: list[Path] = []
  for rel in proc.stdout.splitlines():
    path = repo / rel
    # guard: the index can name a file deleted from the worktree — nothing to read there
    if not path.is_file():
      continue
    try:
      meta, _body = _fm.parse(path.read_text())
    except OSError:
      continue
    if meta.get(ReviewKey.ACTIVE, "").strip().lower() == _BOOL_TRUE:
      active.append(path)
  return active


def sanitize(repo: Path) -> dict:
  """
  Run the three stuck-state repairs across the repository and summarize what was applied.

  Args:
    repo: Repository root.

  Returns:
    `{"cleared": N, "lost_wakes": N, "orphaned": N}` counting sidecar entries dropped for
    vanished documents, lost writer wakes re-raised, and orphaned reviews re-dispatched;
    carries an additional `error` field when one or more documents failed to process.
  """
  failed: list[str] = []

  # review-without-a-document first: an entry keying a vanished path is dropped before the
  # lost-wake pass below would try to dispatch a coordinator on it
  cleared = 0
  for key in sorted(_job_markers._read_store(repo)):
    doc = repo / key
    if not doc.is_file():
      _job_markers.clear(repo, doc)
      cleared += 1

  # lost writer wakes, over the entries that survived the prune
  lost = 0
  for key in sorted(_job_markers._read_store(repo)):
    doc = repo / key
    try:
      if _repair_lost_wake(repo, doc, _job_markers.read(repo, doc)):
        lost += 1
    # waiver: per-document error boundary — one failed dispatch must not stop the sweep
    except Exception as exc:
      sys.stderr.write(f"sanitize: {key}: {exc}\n")
      failed.append(key)

  # orphaned reviews, re-reading each document's markers so a wake the pass above just raised
  # (or the coordinator job it just stamped) reads as the loop moving again
  orphaned = 0
  for doc in _review_active_docs(repo):
    try:
      if _is_orphaned(repo, doc):
        # waiver: type: ignore — coordinator_dispatch is a deferred/late-bound sibling import; mypy cannot resolve it
        _coordinator_dispatch.dispatch_job_done(repo, doc, _DEDUP_HINT)  # type: ignore[attr-defined]
        orphaned += 1
    # waiver: per-document error boundary — one failed dispatch must not stop the sweep
    except Exception as exc:
      sys.stderr.write(f"sanitize: {doc}: {exc}\n")
      failed.append(str(doc))

  # the "error" field is additive — a clean sweep's summary stays exactly the three counts
  # waiver: 'cleared'/'lost_wakes'/'orphaned' are this sweep's own wire-shape keys, not keys.py-promoted constants
  summary: dict[str, int | str] = { "cleared": cleared, "lost_wakes": lost, "orphaned": orphaned }
  # a sweep with failures must not report success via exit 0 (the error-ledger contract)
  if failed:
    summary[JobKey.ERROR] = f"{len(failed)} document(s) failed to sanitize: {', '.join(failed)}"
  return summary


def main(argv: list[str]) -> int:
  """
  Run the sanitize sweep from the command line, printing the summary as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the sweep completed cleanly, 1 when at least one document failed.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-review sanitize")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # the CLI's whole contract is this one summary line
  summary = sanitize(Path(args.repo).resolve())
  print(json.dumps(summary))
  return 1 if JobKey.ERROR in summary else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
