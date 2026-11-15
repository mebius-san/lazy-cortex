"""
Logic behind cancelling and un-cancelling an asset — the `lazycortex-specs flip-gate <asset> spec_cancelled` call,
with and without `--off`.

Cancelling an asset abandons its documents with it: every review running in the asset folder is stopped with its
banner removed, then the expert job running for the asset is cancelled, and every staged document there moves to
`cancelled`. Each moved document is marked with the stage it had and each stopped review is marked as taken by the
asset, and the members of a cancelled release wait for the next one and are woken once the flip has landed. A
moved document loses its status callouts. The job the cancel stops is recorded as the asset's last job and its
pending wake is dropped. A published release, or one in the releases archive, is refused. A cancel whose review or
job cannot be stopped is refused with nothing written: every document is put back exactly as it was, the job record
and the pending wake are given back and the reviews that lost a job to a stop are woken again. A cancel that fails
or is refused after it killed the asset's running job does not give that job back: it stays retired as the last job
with a wake raised. A cancel or an un-cancel that fails part-way, before its commit lands, puts every other file
back the same way. An asset already cancelled that still holds documents its cancel did not take, or a job
still tracked as running or a wake still pending, can have the same abandon applied to it, with its flag left as it is.

Clearing the cancellation returns only the documents marked as taken by the asset, each to the stage its mark
records: an empty, deferred or rejected stage as it was, every other one, a legacy mark included, to `draft`. A
document that was approved also has its review opened fresh at the writer round, and the reviews the cancellation
stopped are resumed with their banner repainted from the stored review state, except on a document still cancelled.
The design gate, or on a release its plan gate, that a document returned as a draft had closed is turned off, a
returned plan on a release rolls back its develop, tests and built gates too, and a release whose last job the
cancel cut short, or whose build or test job it let go before it landed, is marked as owing its rebuild only when
its record carries the cancellation's stamp, is unlanded and names the release's build or test job. The stamp is
dropped from the record of an un-cancelled asset's last job. The members of a release and the asset's own coordinator
are woken once the flip has landed, so the asset can take its ordinary path again. A release is refused its
un-cancel, with nothing written, when another release of its owner is open or when it sits in the releases archive. The documents move through the stage primitive, so each one's `spec/<stage>` tag follows, and the
flag and the moved documents land in one commit. Every other `flip-gate` call is handed to the gate-flip primitive
unchanged.
"""
from __future__ import annotations

import argparse
import json
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
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_delta  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import review_halt  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    FLIP_GATE_NAME, AssetState, AssetTypeKey, AttachmentKey, FlipResult, Gate, JobMarker, ReleaseKey, SiblingDoc,
    SpecKey, SpecMomentKey, SpecStateKey, SpecValue, Stage, StageKey,
)


_MD_SUFFIX = ".md"
_STAGE_KEY = "spec_stage"

# waiver: the result's own wire-shape keys, read by the coordinator and the tests
_DRAFTED_KEY = "drafted"
_RESTORED_KEY = "restored"
_CANCELLED_KEY = "cancelled"
_STOPPED_KEY = "stopped"
_REFUSED_KEY = "refused"
_RESUMED_KEY = "resumed"
_GATE_KEY = "gate"
_DOC_KEY = "doc"
_REASON_KEY = "reason"

# The frontmatter spelling of a true flag.
_TRUE = "true"

# The review plugin verb that re-opens a stopped review, leaving the commit to this call.
_REVIEW_START_ARGS = ( "start", "--no-commit" )

# The review plugin verb that repaints a review's banner from its stored state, and the flag naming its repository.
_REVIEW_PAINT_VERB = "paint-banner"
_REVIEW_REPO_FLAG = "--repo"

# The review plugin verb that removes every terminal-state status callout from a document, leaving the commit to
# this call, and the prefix of the reason a failed removal is reported with.
_REVIEW_STRIP_STATUS_ARGS = ( "strip-status", )
_REVIEW_STRIP_STATUS_FAILED = "review status callout removal failed"

# waiver: the result's own wire-shape key naming the job a failed or refused cancel had already killed
_KILLED_JOB_KEY = "killed_job"

# The prefixes of the reasons a failed re-open or repaint is reported with.
_REVIEW_START_FAILED = "review start failed"
_REVIEW_PAINT_FAILED = "review banner repaint failed"

# The frontmatter spelling of a false flag.
_FALSE = "false"

# The per-round review keys a review opened fresh at the writer round must not carry over: the round machine, the
# verdict, the done-lists and the cycle's own choices; the review plugin seeds the missing ones on `start`
# waiver: the review plugin's own frontmatter keys, mirrored here for the specs side; not in `SpecKey` yet
_REVIEW_ROUND_KEYS = (
    SpecKey.REVIEW_ROUND, SpecKey.REVIEW_APPROVED, SpecKey.REVIEW_PHASE, SpecKey.REVIEW_MAIN_DONE,
    SpecKey.REVIEW_RESULT, "review_validation_round", "review_skip_validation", "review_autorun",
    "review_autorun_cycles",
)

# The gates a release's plan returned from approval takes down with it, by the plan they are read from: the code
# plan rolls the whole build back, the test plan only the test run and the build on top of it.
_RELEASE_PLAN_GATES = (
    ( SiblingDoc.CODE_PLAN, ( Gate.PLAN_DONE, Gate.DEVELOP_DONE, Gate.TESTS_PASSING, Gate.BUILT ) ),
    ( SiblingDoc.TEST_PLAN, ( Gate.TESTS_PASSING, Gate.BUILT ) ),
)

# The release keys naming the jobs of its last build and test run.
_RELEASE_JOB_KEYS = ( ReleaseKey.BUILD_JOB, ReleaseKey.TEST_JOB )

# The key of a path-only wake item, the shape a manual wake hands the coordinator.
_ITEM_PATH = "path"

# The job-bundle terminal marker of a finished job, as the core runtime touches it; a `last_job` record stores it
# lowercased.
_DONE_MARKER = "DONE"

# The status word and key of a cancel or un-cancel that failed with an exception.
_ERROR_STATUS = "error"
_ERROR_KEY = "error"

# The exit code of a cancel or un-cancel that failed with an exception, told apart from a refusal.
_EXIT_FAILED = 2

# The status word of a sweep that applied the cancel to an asset already cancelled.
_SWEPT = "swept"

# The status word of a sweep that found nothing left behind.
_NOTHING_LEFT = "noop"

# The bot identity a sweep commit lands under, the same one a cancel's flip commit carries.
_SWEEP_AUTHOR_NAME = FLIP_GATE_NAME
_SWEEP_AUTHOR_EMAIL = f"{FLIP_GATE_NAME}@bot.invalid"

# The names the cancel and the un-cancel report a failure on stderr under.
_CANCEL_LOG = "asset-cancel"
_UNCANCEL_LOG = "asset-uncancel"

# Refusal reasons of a cancel or un-cancel that writes nothing.
_JOB_CANCEL_FAILED = "the asset's running expert job could not be cancelled"
_STOPS_FAILED = "a review in the asset folder could not be stopped"
_OPEN_RELEASE = "another release of the same owner is open"
_ARCHIVED_RELEASE = "the release sits in the releases archive"
_PUBLISHED_RELEASE = "the release is already published"
_STILL_CANCELLED = "the document is still cancelled, so its review was not resumed"


def cancel(asset_dir: Path, *, auto: bool = False, reason: str = "", today: str | None = None) -> dict:
  """
  Cancel an asset and abandon its documents with it.

  On a live asset whose note is a status note, every review running in the asset folder is stopped, then the expert
  job running for the asset is cancelled last, and every document directly in the asset folder is abandoned with the
  asset; nested folders and the status note are never touched.

  Guarantees:
    - On a live asset with a status note, every review running on a markdown file directly in the asset folder is
      stopped, its round and phase kept.
    - On such an asset every staged document there that is not an attachment moves to `cancelled` with its
      `spec/<stage>` tag, the defining documents such as `design.md` included; attachments follow their owner.
    - The raised flag and every stopped review and moved document land in one commit, when the asset is in a git
      repository.
    - A document whose move to `cancelled` is refused keeps its bytes and is the only document named for it in
      `refused` with its reason; the flag is still raised.
    - A published release, or a release under `releases/archive/`, is refused: nothing is written.
    - A review whose stop fails refuses the whole cancel: no document is moved, no flag or mark is written, only
      the first failing review is named in `refused`, and the asset's own running job is left untouched and still
      tracked.
    - An asset's running job that cannot be confirmed cancelled refuses the whole cancel: no document is moved, no
      flag or mark is written, and the job stays tracked.
    - Any refusal after a review was stopped — a failed stop, a job that cannot be confirmed cancelled, a refused
      flip — and any exception raised before the flip's commit has landed leave the folder byte-identical: every
      file the call may have written, the stopped documents with the failing one included, the status note, the
      other documents of the folder, the containers above it, the members of a release and the runtime job
      sidecar, gets its original bytes back, and the `job-done` wake of every review whose stop cancelled a job or
      left no readable report is raised again on a best-effort basis. The sidecar gives the tracked `active_job` and
      `pending_wake` back only when the cancel killed no job; a job the cancel had already killed is not given back
      as `active_job`: the sidecar keeps `active_job` null with the cancelled record of the killed job as
      `last_job`, without `retired_by_cancel` since the asset stays live, and raises `pending_wake: job-done`. An
      exception is re-raised after that.
    - An exception raised after the flip's commit has landed restores no file and raises no wake: the committed
      tree stays as HEAD has it, and the exception is re-raised.
    - Each document moved to `cancelled` carries `spec_cancelled_with_asset` holding the stage it had and each
      review stopped carries `spec_review_stopped_with_asset: true`; in the same commit a stale
      `spec_review_stopped_with_asset` on any other document of the folder is dropped.
    - On a successful cancel the asset's `pending_wake` in the specs runtime sidecar is cleared.
    - A tracked job the cancel lets go is recorded in the specs runtime sidecar as `last_job`, always carrying
      `unlanded: true`: with outcome and marker `cancelled` when the cancel stopped it, and with the outcome its own
      response reports, else its lowercased terminal marker, when it had already ended. The record of a job the
      cancel stopped, and of a tracked job that had already ended `done`, also carries `retired_by_cancel: true`;
      that of a tracked job that had ended `dead` or `cancelled` does not. A cancel that finds no running job but a
      pending `job-done` wake drops the wake and marks the existing `last_job` `unlanded: true` only when its
      result did not land; a result landed when the record's marker is `done`, it carries no `unlanded`, and its
      job bundle is marked consumed. A `done` record not yet unlanded is then also stamped `retired_by_cancel:
      true`; one already unlanded, and one of a job that did not end `done`, gets no stamp.
    - Every document the cancel moves to `cancelled` has every `#status/<state>` callout removed from its body
      through the review plugin's `strip-status` verb, in no commit of its own: the removal rides the flip's commit.
      A failed removal is reported on stderr and does not stop the cancel.
    - The live members of a cancelled release whose note does not read `spec_design_done: false` are repainted
      `awaiting-release` in the same commit as the raised flag and, once the flip has landed, woken on a
      best-effort basis.
    - An already cancelled asset, or a note that is not a status note, has no document touched and gets the gate
      flip's own refusal.

  Args:
    asset_dir: The asset folder holding its status note `<asset_dir.name>.md`.
    auto: When True, mark the flip's run-log reason with an `auto:` prefix.
    reason: Optional note recorded in the flip's run log.
    today: Optional ISO date pinned into the flip's run log.

  Returns:
    The gate-flip result for `spec_cancelled` turned on, plus `"cancelled"` — the file names of the documents moved
    to `cancelled`, sorted — `"stopped"` — the file names whose review was stopped, sorted — and `"refused"` — one
    `{"doc", "reason"}` entry per document left where it was. A refused result carries `"killed_job"` — the
    `last_job` record of the job the cancel had already killed — when it killed one.
  """

  # Contract:
  # On a live asset inside a git repository, the raised flag, every stopped review and every document moved to
  # `cancelled` land in ONE commit.

  # Contract:
  # A document whose move to `cancelled` is refused keeps its bytes and is the only document named for it in the
  # result with its reason; the flag is still raised.

  # Contract:
  # A published release (`spec_released: true`) and a release under `releases/archive/` are refused: nothing is
  # written.

  # Contract:
  # A review in the asset folder whose stop fails refuses the WHOLE cancel: no document is moved, no flag or mark is
  # written, only the first failing review is named in `refused`, and the asset's own running job is left untouched
  # and still tracked.

  # Contract:
  # An asset's running job that cannot be confirmed cancelled refuses the WHOLE cancel: no document is moved, no
  # flag or mark is written, and the job stays tracked.

  # Contract:
  # Any refusal after a review was stopped, a failed stop, a job that cannot be confirmed cancelled or a refused
  # flip, and any exception raised before the flip's commit has landed leave the folder byte-identical: every file
  # the call may have written, the stopped documents with the failing one included, the status note, the other
  # documents of the folder, the containers above it, the members of a release and the runtime job sidecar, gets
  # its original bytes back, and the `job-done` wake of every review whose stop cancelled a job or left no readable
  # report is raised again on a best-effort basis. The sidecar gives the tracked `active_job` and `pending_wake`
  # back only when the cancel killed no job. A job the cancel had already killed is never given back as
  # `active_job`: the sidecar keeps `active_job` null with the cancelled record of the killed job as `last_job`,
  # without `retired_by_cancel` since the asset stays live, and raises `pending_wake: job-done`, and a refused
  # result then carries that record as `killed_job`.
  # An exception is re-raised after that.

  # Contract:
  # An exception raised after the flip's commit has landed restores no file and raises no wake: the committed tree
  # stays as HEAD has it, and the exception is re-raised.

  # Contract:
  # Each document moved to `cancelled` carries `spec_cancelled_with_asset` holding the stage it had and each review
  # stopped carries `spec_review_stopped_with_asset: true`; in the same commit a stale
  # `spec_review_stopped_with_asset` on any other document of the folder is dropped.

  # Contract:
  # On a successful cancel the asset's `pending_wake` in the specs runtime sidecar is cleared.

  # Contract:
  # A tracked job the cancel lets go is recorded in the specs runtime sidecar as `last_job`, always carrying
  # `unlanded: true`: with outcome and marker `cancelled` when the cancel stopped it, and with the outcome its own
  # response reports, else its lowercased terminal marker, when it had already ended. The record of a job the cancel
  # stopped, and of a tracked job that had already ended `done`, also carries `retired_by_cancel: true`; that of a
  # tracked job that had ended `dead` or `cancelled` does not. A cancel that finds no running job but a pending
  # `job-done` wake drops the wake and marks the existing `last_job` `unlanded: true` only when its result did not
  # land; a result landed when the record's marker is `done`, it carries no `unlanded`, and its job bundle is marked
  # consumed. A `done` record not yet unlanded is then also stamped `retired_by_cancel: true`; one already unlanded,
  # and one of a job that did not end `done`, gets no stamp.

  # Contract:
  # Every document the cancel moves to `cancelled` has every `#status/<state>` callout removed from its body
  # through the review plugin's `strip-status` verb, in no commit of its own: the removal rides the flip's commit.
  # A failed removal is reported on stderr and does not stop the cancel.

  # Contract:
  # The live members of a cancelled release, those neither released nor cancelled and whose note does not read
  # `spec_design_done: false`, are repainted `awaiting-release` in the same commit as the raised flag and, once the
  # flip has landed, woken on a best-effort basis.

  # Contract:
  # An asset that is already cancelled, or a note that is not a status note, has NO document touched and gets the
  # gate flip's own refusal.

  # Domain(spec.lifecycle):
  # # Cancelling an asset
  # Cancelling an asset abandons its documents with it, so that a cancelled asset never keeps asking the operator to
  # approve anything. A published release is the record of what shipped and a release in the archive is closed
  # history: neither can be cancelled, and the refusal writes nothing.
  # Every review in the asset folder is stopped first, paused where it stands so that nothing is lost if the asset
  # comes back, and its banner is taken down. If any review cannot be stopped, the cancellation is refused as a
  # whole: every document is put back exactly as it was, and every review whose own job the stop cancelled, or whose
  # stop gave no readable answer, has its wake raised again so it carries on.
  # Only then is the expert job still working for the asset cancelled, and last, because it would otherwise keep
  # writing into an abandoned asset and nothing before it may be left half done. A job that cannot be confirmed
  # cancelled refuses the whole cancellation the same way: the reviews are not resumed and their banners are not
  # repainted, since they are put back as they were, and the lost wakes are raised again. A failure part-way through
  # the abandoning puts everything back too, but only while the commit that records the cancellation has not landed:
  # a failure after it puts nothing back, the committed cancellation stands and the failure is reported. A wake still
  # pending on the asset is dropped, so that the wake of a finished job never reaches a cancelled asset.
  # The work the cancellation stops stays on record as the asset's last job: marked cancelled when the cancellation
  # stopped it, or carrying its own result when it had already finished. Work let go before its result landed,
  # whether the cancellation stopped it or it had already finished with its wake not yet taken, is recorded as never
  # landed; a finished job whose result had already landed keeps its record as it was. Work the cancellation stopped,
  # and work that had finished and only waited for its landing, is also recorded as withheld by the cancellation;
  # work that had died, or been cancelled on its own, before the cancellation failed of itself and is not.
  # A refused or failed cancellation gives the record of the running work and the pending wake back, so the
  # asset carries on as if nothing had been tried, but only when the work was not killed. Work the cancellation
  # already stopped can never run again: on a take-back it stays recorded as cancelled, without the cancellation's
  # mark since the asset stays live, the asset's coordinator is woken to see that it is gone, and the report of a
  # failed cancellation names that stopped work.
  # A document that moves to cancelled loses its terminal-state callout, for example "Approved", because it no
  # longer is in that state.
  # Each stopped review is marked as taken by the asset, and each document that moves to cancelled is marked with
  # the stage it had, so that un-cancelling can tell them from what was stopped or cancelled on its own and bring
  # each document back to where it was; a stale review mark left on any other
  # document of the folder by an earlier cancellation is cleared. Every staged document of the asset
  # moves to cancelled, the defining documents included; attachments follow the document that owns them. A report
  # without a stage only has its review stopped. A document that cannot be moved stays where it is and is named.
  # Documents of an asset nested inside are not touched. Cancelling an asset that is already cancelled, or a note
  # that is not an asset's own, moves nothing.

  note = asset_dir / f"{asset_dir.name}.md"
  fm_values, _end = spec_frontmatter.parse(spec_paths.read_text(note))
  done = _Abandoned()
  halt = review_halt.ReviewHalt()

  # only a live asset's own status note takes its documents with it; any other note is the primitive's to refuse
  if not flip_gate.is_true(fm_values, Gate.SPEC_CANCELLED) \
      and flip_gate.note_role(fm_values) == SpecValue.ROLE_STATUS:
    # guard: a published or archived release is closed history, never abandoned
    if (closed := _find_closed_release(asset_dir, fm_values)) is not None:
      return _create_refusal(closed, [])

    # every step runs guarded: a failure before the flip's commit takes every stop and write back
    # noinspection PyBroadException
    try:
      # guard: an abandon refused part-way has already taken back its stops and writes
      if _abandon_asset(asset_dir, note, fm_values, halt, done).refusal is not None:
        return done.refusal or {}

      # the raised flag carries the stopped reviews and the moved documents into the flip's own commit
      flipped = flip_gate.flip_gate(asset_dir, Gate.SPEC_CANCELLED, auto = auto, reason = reason, today = today,
                                    extra_paths = done.touched)
    except Exception:
      # a failure before the flip's commit takes every write back but the job it killed; one after it leaves the
      # committed tree alone
      if not halt.rollback_uncommitted():
        sys.stderr.write(f"{_CANCEL_LOG}: failed after the flip landed, nothing restored\n")
      else:
        _keep_killed_job(note, done.killed, wake = True)
      raise
  else:
    # a note the cancel does not abandon goes to the gate primitive untouched
    flipped = flip_gate.flip_gate(asset_dir, Gate.SPEC_CANCELLED, auto = auto, reason = reason, today = today)

  # guard: a flip refused after the abandon takes every write back but the job it killed, which it names
  if flipped[FlipResult.STATUS] != FlipResult.FLIPPED:
    halt.rollback()
    kept = _keep_killed_job(note, done.killed, wake = True)
    killed = { _KILLED_JOB_KEY: kept } if kept is not None else {}
    return { **flipped, _CANCELLED_KEY: [], _STOPPED_KEY: [], _REFUSED_KEY: done.refused, **killed }

  # the repainted members learn of it only once the flip has landed
  _wake_members(asset_dir, done.painted, today)
  return { **flipped, _CANCELLED_KEY: sorted(done.cancelled), _STOPPED_KEY: sorted(done.stopped),
           _REFUSED_KEY: done.refused }


# ----------------------------------------------------------------------------------------
@dataclass
class _Abandoned:
  """
  What abandoning an asset's documents did, or why it was refused.

  Attributes:
    refusal: The refused result when the abandon wrote nothing, absent when it went through.
    stopped: The names of the documents whose review was stopped.
    cancelled: The names of the documents moved to `cancelled`.
    refused: One `{"doc", "reason"}` entry per document left where it was.
    touched: Every path written, each once, for the commit.
    painted: The release member notes repainted.
    killed: The `last_job` record of the running job the abandon cancelled, absent when it cancelled none.
  """

  refusal: dict | None = None
  stopped: list[str] = field(default_factory = list)
  cancelled: list[str] = field(default_factory = list)
  refused: list[dict] = field(default_factory = list)
  touched: list[Path] = field(default_factory = list)
  painted: list[Path] = field(default_factory = list)
  killed: dict | None = None


def _abandon_asset(asset_dir: Path, note: Path, fm_values: dict, halt: review_halt.ReviewHalt,
                   done: _Abandoned) -> _Abandoned:
  """
  Stop every review of an asset folder, cancel the asset's running job, and abandon its documents and members.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note.
    fm_values: The note's parsed frontmatter.
    halt: The record of the stops and held files, which the caller's commit or rollback uses.
    done: The record the abandon fills as it goes, so a caller whose later step fails still knows the job it killed.

  Returns:
    `done`, filled with what the abandon did; on a failed stop or a job that cannot be confirmed cancelled, carrying
    the refusal, with every stop and write already taken back.
  """
  # the documents directly in the asset folder are the ones abandoned with it
  docs = _find_all_authored_docs(asset_dir, note)

  # guard: an abandon that cannot stop every review takes back the stops it made and writes nothing
  if not halt.stop(docs):
    halt.rollback()
    done.refusal = _create_refusal(
        _STOPS_FAILED, [ { _DOC_KEY: _name_of(halt.failed_doc), _REASON_KEY: halt.failure or "" } ])
    return done

  # Decision: only the asset's `active_job` is cancelled, not its spec `coordinator_job` — the core runtime
  # exports no job id to a spawned agent, so the cancel cannot tell its own calling coordinator job from another.

  # the job sidecar is held too, so a cancel taken back gives the asset its tracked job and its pending wake back
  halt.keep([ spec_job_markers.sidecar_path(_sidecar_repo(asset_dir)) ])

  # guard: a running expert job that cannot be stopped would keep writing into the abandoned asset
  if not (job := _cancel_active_job(note)).confirmed:
    halt.rollback()
    done.refusal = _create_refusal(_JOB_CANCEL_FAILED, [])
    return done
  done.killed = job.killed

  # every file the abandon may write is held, so a failure part-way gives each its bytes back
  halt.keep([ note, *docs, *flip_gate.containers_above(asset_dir), *_find_all_member_notes(note, fm_values) ])
  halt.hold_head(flip_gate.repo_root(asset_dir))

  # the reviews stopped are marked and the staged documents moved to cancelled
  done.stopped, done.cancelled, done.refused, touched = _abandon_docs(docs, halt.stopped)

  # a cancelled release no longer carries its members, so they wait for the next one
  done.painted = _repaint_members(note, fm_values, AssetState.AWAITING_RELEASE)
  done.touched = list(dict.fromkeys([ *touched, *done.painted ]))
  return done


def is_sweep_due(asset_dir: Path) -> bool:
  """
  Tell whether a cancelled asset still holds documents its cancel did not take with it.

  Guarantees:
    - True exactly when `sweep_cancelled` has something to abandon on the asset; never True for a live asset, a note
      that is not a status note, or a published or archived release.
    - A job still tracked as running, or a wake still pending, on the cancelled asset counts as left behind.

  Args:
    asset_dir: The asset folder holding its status note `<asset_dir.name>.md`.

  Returns:
    True when the folder's status note reads `spec_cancelled: true` and is neither a published nor an archived
    release, and the asset has a job still tracked as running or a wake still pending, or a markdown file directly
    in the folder is under review or is a staged document, attachments aside, that the stage primitive would move
    to `cancelled` with the asset; False otherwise.
  """

  # Contract:
  # It is True exactly when `sweep_cancelled` has something to abandon on the asset, and never for a live asset, a
  # note that is not a status note, or a published or archived release.

  # Contract:
  # A job still tracked as running, or a wake still pending, on a cancelled asset counts as left behind, so the
  # asset is due a sweep even when every document of it is already abandoned.

  note = asset_dir / f"{asset_dir.name}.md"

  # guard: only an asset's own status note can be cancelled
  if not note.is_file():
    return False
  fm_values, _end = spec_frontmatter.parse(spec_paths.read_text(note))

  # guard: a live asset, a note that is not a status note, and a closed release have nothing left behind
  if not flip_gate.is_true(fm_values, Gate.SPEC_CANCELLED) \
      or flip_gate.note_role(fm_values) != SpecValue.ROLE_STATUS \
      or _find_closed_release(asset_dir, fm_values) is not None:
    return False

  # a job the cancel would have stopped or a wake it would have dropped is left behind, and so is any document it
  # would have stopped or moved
  markers = spec_job_markers.read(_sidecar_repo(asset_dir), note)
  if isinstance(markers[JobMarker.ACTIVE_JOB], dict) or markers[JobMarker.PENDING_WAKE]:
    return True
  return any(_is_left_behind(doc) for doc in _find_all_authored_docs(asset_dir, note))


def _is_left_behind(doc: Path) -> bool:
  """
  Tell whether a document of a cancelled asset still waits for the cancel.

  Args:
    doc: A markdown file directly in the asset folder.

  Returns:
    True when the document is under review, or is a staged document outside `cancelled`, not an attachment, that the
    stage primitive would move to `cancelled` with its asset.
  """
  values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))

  # a running review is always left behind
  if values.get(SpecKey.REVIEW_ACTIVE, "").strip() == _TRUE:
    return True

  # guard: an attachment follows its owner, and a stageless or already cancelled document never moves
  stage = values.get(_STAGE_KEY, "").strip()
  if values.get(AttachmentKey.OWNER_DOC) or not stage or stage == Stage.CANCELLED:
    return False

  # a document the stage primitive would refuse could never be swept, so it does not count
  try:
    set_stage.validate(doc, Stage.CANCELLED, restamp = False, with_asset = True)
  except set_stage.SetStageRefusedError:
    return False
  return True


def sweep_cancelled(asset_dir: Path, *, today: str | None = None) -> dict:
  """
  Apply the cancel's abandon to an asset already cancelled, leaving its flag as it is.

  Guarantees:
    - The stopped reviews, the moved documents and the repainted members land in one commit under the flip-gate bot
      identity, and the cancellation flag is left as it is; the repainted members are woken after it has landed, on a
      best-effort basis.
    - A review that cannot be stopped, or a job that cannot be confirmed cancelled, refuses the sweep with nothing
      written.
    - An asset with nothing left behind is not touched and gets the `noop` status, so a second sweep writes nothing.
    - A job still tracked as running on the asset is cancelled and a wake still pending is cleared.
    - A sweep that wrote no tracked file makes no commit.
    - An exception raised before the sweep's commit has landed restores every file but the job the sweep killed:
      the sidecar keeps `active_job` null with the cancelled record of the killed job as `last_job`, still carrying
      `retired_by_cancel: true`, and raises no wake, so the asset stays cancelled.
    - Every moved document has every `#status/<state>` callout removed from its body, as in the cancel.

  Args:
    asset_dir: The asset folder holding its status note `<asset_dir.name>.md`.
    today: Optional ISO date forwarded into the woken release members' History lines.

  Returns:
    `{"status": "swept", "cancelled", "stopped", "refused"}` as the cancel names them; the refused result of the
    cancel when a review cannot be stopped or the job cannot be confirmed cancelled, with nothing written; a
    `"noop"` status with empty lists when nothing is left behind.
  """

  # Contract:
  # The stopped reviews, the moved documents and the repainted members land in ONE commit, and the cancellation flag
  # is left as it is.

  # Contract:
  # A review that cannot be stopped, or a job that cannot be confirmed cancelled, refuses the sweep with nothing
  # written.

  # Contract:
  # An asset with nothing left behind is not touched and gets the `noop` status, so a second sweep writes nothing.

  # Contract:
  # A job still tracked as running on the asset is cancelled and a wake still pending is cleared.

  # Contract:
  # A sweep that wrote no tracked file makes no commit.

  # Contract:
  # An exception raised before the sweep's commit has landed restores every file but the job the sweep killed: the
  # sidecar keeps `active_job` null with the cancelled record of the killed job as `last_job`, still carrying
  # `retired_by_cancel: true`, and raises no wake, so the asset stays cancelled.

  # Contract:
  # Every document the sweep moves to `cancelled` has every `#status/<state>` callout removed from its body, as in
  # the cancel.

  # Domain(spec.lifecycle):
  # # Sweeping an asset cancelled by an earlier version
  # An asset cancelled before cancelling took its documents with it still holds them at their old stages, and
  # reviews or expert jobs may still be running on it. A sweep applies the same abandon to such an asset: reviews
  # are stopped, the job is cancelled, the documents move to cancelled and carry the stage they had, and release
  # members wait for the next release. The cancellation itself is left as it is, neither raised again nor cleared.
  # Only what the cancel would have taken counts as left behind: a running review, expert work still tracked as
  # running, a wake still pending, or a staged document outside cancelled that is not an attachment. Work still
  # running is cancelled and a pending wake is dropped, exactly as the cancel would have done. Work a failed sweep
  # had already stopped stays recorded as cancelled and as withheld by the cancellation, with no wake, since the
  # asset stays cancelled. The swept documents lose their status callouts, as in the cancel. A document the stage
  # rules would never move to cancelled is not left behind. An asset with nothing left behind is not touched, so
  # sweeping twice changes nothing. A live asset, a note that is not an asset's own, and a published or archived
  # release are never swept.

  note = asset_dir / f"{asset_dir.name}.md"

  # guard: an asset with nothing left behind is not touched, so a second sweep writes nothing
  if not is_sweep_due(asset_dir):
    return { FlipResult.STATUS: _NOTHING_LEFT, _CANCELLED_KEY: [], _STOPPED_KEY: [], _REFUSED_KEY: [] }
  fm_values, _end = spec_frontmatter.parse(spec_paths.read_text(note))
  halt = review_halt.ReviewHalt()
  done = _Abandoned()

  # every step runs guarded: a failure before the sweep's commit takes every stop and write back
  # noinspection PyBroadException
  try:
    # guard: an abandon refused part-way has already taken back its stops and writes
    if _abandon_asset(asset_dir, note, fm_values, halt, done).refusal is not None:
      return done.refusal or {}

    # the stopped reviews, the moved documents and the repainted members land in one commit of their own; a sweep
    # that only let go of a tracked job or wake wrote nothing tracked and commits nothing
    if done.touched:
      flip_gate.commit_paths(flip_gate.repo_root(asset_dir), done.touched,
                             subject = f"{FLIP_GATE_NAME}: cancel sweep on {asset_dir.name}",
                             author_name = _SWEEP_AUTHOR_NAME, author_email = _SWEEP_AUTHOR_EMAIL)
  except Exception:
    # a failure before the commit takes every write back; one after it leaves the committed tree alone
    if not halt.rollback_uncommitted():
      sys.stderr.write(f"{_CANCEL_LOG}: sweep failed after its commit landed, nothing restored\n")
    else:
      # the job the sweep killed stays retired; the asset is still cancelled, so no wake reaches it
      _keep_killed_job(note, done.killed, wake = False)
    raise

  # the repainted members learn of it only once the commit has landed
  _wake_members(asset_dir, done.painted, today)
  return { FlipResult.STATUS: _SWEPT, _CANCELLED_KEY: sorted(done.cancelled), _STOPPED_KEY: sorted(done.stopped),
           _REFUSED_KEY: done.refused }


def _abandon_docs(docs: list[Path], reviewed: list[Path]) -> tuple[list[str], list[str], list[dict], list[Path]]:
  """
  Mark the reviews a cancel stopped, move every staged document of the folder to `cancelled` and strip its status
  callouts.

  Args:
    docs: The markdown files directly in the asset folder.
    reviewed: The documents whose review the cancel stopped.

  Returns:
    The names of the stopped documents, the names of the documents moved to `cancelled`, one `{"doc", "reason"}`
    entry per document whose move was refused, and every path written.
  """
  stopped: list[str] = []
  cancelled: list[str] = []
  refused: list[dict] = []
  touched: list[Path] = []

  # each review stopped now is marked, and a mark a past cancel left behind is cleared, so un-cancelling the
  # asset re-opens exactly these
  for doc in docs:
    text = spec_paths.read_text(doc)
    if doc in reviewed:
      new = spec_frontmatter.set_scalar(text, StageKey.REVIEW_STOPPED_WITH_ASSET, _TRUE)
      stopped.append(doc.name)
    else:
      new = spec_frontmatter.drop_key(text, StageKey.REVIEW_STOPPED_WITH_ASSET)

    # guard: an unstopped document whose mark already reads right is not rewritten; a stopped one always is, since
    # its stop changed it and it rides the flip's commit
    if new == text and doc not in reviewed:
      continue

    # a changed mark is written and joins the flip's commit
    spec_paths.write_text_atomic(doc, new)
    touched.append(doc)

  # every staged document of the folder is abandoned with the asset, its attachments following it
  for doc in docs:
    values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))
    stage = values.get(_STAGE_KEY, "").strip()

    # guard: an attachment follows its owner, and a stageless or already cancelled document does not move
    if values.get(AttachmentKey.OWNER_DOC) or not stage or stage == Stage.CANCELLED:
      continue

    # a refused move leaves its document where it was, named with the reason
    result = set_stage.apply_stage(doc, Stage.CANCELLED, with_asset = True)
    if result.status == set_stage.StageStatus.REFUSED:
      refused.append({ _DOC_KEY: doc.name, _REASON_KEY: result.reason or "" })
      continue
    cancelled.append(doc.name)
    touched.extend(Path(path) for path in result.touched_paths)

    # a cancelled document claims no state it has left, so its status callout comes down through the review plugin
    failure = review_halt.run_review_verb(doc, _REVIEW_STRIP_STATUS_ARGS, _REVIEW_STRIP_STATUS_FAILED).failure
    if failure is not None:
      sys.stderr.write(f"{_CANCEL_LOG}: {doc.name}: {failure}\n")

  # what the abandon did, for the result and the flip's commit
  return stopped, cancelled, refused, touched


def _name_of(doc: Path | None) -> str:
  """
  Name a document by its file name.

  Args:
    doc: The document, or None.

  Returns:
    The file name, empty for None.
  """
  return doc.name if doc is not None else ""


def _create_refusal(reason: str, refused: list[dict]) -> dict:
  """
  Build the result of a cancel or un-cancel refused before anything was written.

  Args:
    reason: Why nothing was written.
    refused: The documents named with their own reasons, possibly none.

  Returns:
    The refused `spec_cancelled` flip result with empty move lists and the named documents.
  """
  return {
      FlipResult.STATUS: FlipResult.REFUSED, _GATE_KEY: Gate.SPEC_CANCELLED, _REASON_KEY: reason,
      _CANCELLED_KEY: [], _STOPPED_KEY: [], _REFUSED_KEY: refused,
  }


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _JobCancel:
  """
  The outcome of cancelling an asset's running job.

  Attributes:
    confirmed: Whether no job was running or it is confirmed cancelled.
    killed: The `last_job` record of a job the call cancelled while it still ran, absent otherwise.
  """

  confirmed: bool
  killed: dict | None = None


def _cancel_active_job(note: Path) -> _JobCancel:
  """
  Cancel the expert job running on an asset, retire it as the asset's last job and drop any wake still pending.

  When no job is running and a `job-done` wake is still pending, the wake is dropped and the last job is marked
  `unlanded: true` only if its result had not landed. The retired record is stamped `retired_by_cancel: true` when
  the cancel killed the job while it ran, or when the job had finished `DONE` and only its landing was pending; a
  job that had died or been cancelled on its own before the cancel is retired without the stamp.

  Args:
    note: The asset's status note.

  Returns:
    Whether no job was running or it is confirmed cancelled, and the `last_job` record of a job the call cancelled
    while it still ran, absent for a job that had already ended.
  """
  # the asset's job markers, kept in the sidecar of the repository tracking it
  repo = _sidecar_repo(note.parent)
  markers = spec_job_markers.read(repo, note)

  # guard: nothing running, nothing to cancel; a wake still raised must not reach the cancelled asset, and a
  # finished job whose result had not landed is kept on record as never landed
  if not isinstance(job_info := markers[JobMarker.ACTIVE_JOB], dict):
    if markers[JobMarker.PENDING_WAKE]:
      last = markers[JobMarker.LAST_JOB]
      unlanded = markers[JobMarker.PENDING_WAKE] == JobMarker.JOB_DONE and isinstance(last, dict) \
          and not spec_job_markers.is_result_landed(repo, last)
      spec_job_markers.update(repo, note, {
          JobMarker.PENDING_WAKE: None,
          **({ JobMarker.LAST_JOB: _unlanded_by_cancel(last) } if unlanded and isinstance(last, dict) else {}),
      })
    return _JobCancel(confirmed = True)

  # guard: without the core CLI the job cannot be confirmed cancelled, so it stays tracked
  try:
    cli = spec_paths.resolve_core_cli(repo)
  except RuntimeError:
    return _JobCancel(confirmed = False)

  # a job that already ended before the cancel keeps its own result in the record, so it is read first
  finished = spec_job_markers.find_terminal_marker(repo, job_info)

  # guard: the core verb confirms the job dead before its marker is let go; an unconfirmed cancel keeps it tracked
  if not spec_job_markers.cancel_job(repo, cli, job_info):
    return _JobCancel(confirmed = False)

  # the confirmed-dead job and any wake it left are no longer tracked, and the job stays readable as the last one
  record = spec_job_markers.build_retired_record(repo, job_info, finished)

  # the cancel kept the result from landing when it killed the job, or when the job had finished and only waited
  # for its landing; a job that died or was cancelled on its own before the cancel failed of itself
  if finished in ( None, _DONE_MARKER ):
    record = spec_job_markers.mark_retired_by_cancel(record)
  spec_job_markers.update(repo, note, {
      JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: None, JobMarker.LAST_JOB: record,
  })
  return _JobCancel(confirmed = True, killed = record if finished is None else None)


def _unlanded_by_cancel(last: dict) -> dict:
  """
  Mark the record of a retired job whose result had not landed as unlanded, stamping it when the cancel withheld it.

  Args:
    last: The stored `last_job` record, already known not to have landed.

  Returns:
    The record marked `unlanded: true`; also stamped `retired_by_cancel: true` when the job had finished and was
    not already marked unlanded, so only its landing was still to come.
  """
  # a finished job not yet marked unlanded only waited for its landing, which the cancel now withholds; a death
  # or a refused landing recorded before the cancel failed of itself
  withheld = last.get(JobMarker.MARKER) == _DONE_MARKER.lower() and not spec_job_markers.is_unlanded_record(last)
  record = spec_job_markers.mark_unlanded(last)
  return spec_job_markers.mark_retired_by_cancel(record) if withheld else record


def _keep_killed_job(note: Path, killed: dict | None, *, wake: bool) -> dict | None:
  """
  Keep a job a taken-back cancel had already killed on record as cancelled, never as running again.

  Notes:
    - With `wake` true the asset stays live, so the record is kept without its `retired_by_cancel` stamp; with
      `wake` false the asset stays cancelled and the stamp is kept for its un-cancel.

  Args:
    note: The asset's status note.
    killed: The `last_job` record of the killed job; None leaves the sidecar as the rollback gave it back.
    wake: Whether the asset's `job-done` wake is raised, so its coordinator sees the job is gone.

  Returns:
    The `last_job` record kept in the sidecar, None when the cancel killed no job.
  """
  # guard: a cancel that killed no job has nothing to keep
  if killed is None:
    return None

  # a cancel taken back leaves the asset live, so the record loses the cancellation's stamp; an asset that stays
  # cancelled keeps it for its un-cancel
  record = spec_job_markers.drop_retired_by_cancel(killed) if wake else killed

  # the killed job can never run again, so it is retired, and a live asset's coordinator is woken to see it
  spec_job_markers.update(_sidecar_repo(note.parent), note, {
      JobMarker.ACTIVE_JOB: None, JobMarker.LAST_JOB: record,
      JobMarker.PENDING_WAKE: JobMarker.JOB_DONE if wake else None,
  })
  return record


def read_running_job(note: Path) -> dict | list | str | None:
  """
  Read the expert job tracked as running on an asset.

  Args:
    note: The asset's status note.

  Returns:
    The asset's stored `active_job` value, None when no job is tracked.
  """
  # the marker lives in the sidecar of the repository tracking the asset
  return spec_job_markers.read(_sidecar_repo(note.parent), note)[JobMarker.ACTIVE_JOB]


def find_killed_job(note: Path, before: dict | list | str | None) -> dict | None:
  """
  Name the job a failed cancel killed, read from the sidecar it left.

  Lets a caller whose cancel raised report the job that cancel had already killed.

  Args:
    note: The asset's status note.
    before: The asset's `active_job` before the cancel ran.

  Returns:
    The `last_job` record when the job that was running before the cancel is now retired as cancelled; None
    otherwise.
  """
  # guard: a cancel that found nothing running killed nothing
  if not isinstance(before, dict):
    return None

  # the job that ran is killed when it is no longer tracked and its record reads cancelled
  markers = spec_job_markers.read(_sidecar_repo(note.parent), note)
  last = markers[JobMarker.LAST_JOB]
  if markers[JobMarker.ACTIVE_JOB] is None and spec_job_markers.is_cancelled_record(last) \
      and isinstance(last, dict) and last.get(JobMarker.JOB_ID) == before.get(JobMarker.JOB_ID):
    return last
  return None


def _sidecar_repo(folder: Path) -> Path:
  """
  Name the repository whose runtime job sidecar tracks an asset.

  Args:
    folder: The asset folder, or any folder inside it.

  Returns:
    The git top level holding the folder; outside git, the folder holding `.claude/lazy.settings.json`, else the
    folder itself.
  """
  # guard: inside git the sidecar sits at the repository root
  if flip_gate.git_field(folder, [ "rev-parse", "--show-toplevel" ], ""):
    return flip_gate.repo_root(folder)

  # outside git the settings root stands in for the repository root
  try:
    return spec_paths.find_settings_root(folder)
  except (RuntimeError, OSError):
    return folder


def _repaint_members(note: Path, fm_values: dict, state: str) -> list[Path]:
  """
  Paint every member of a release that is neither released nor cancelled with one state.

  A member whose note reads `spec_design_done: false` keeps its own state.

  Args:
    note: The asset's status note; a note that is not a release's paints nothing.
    fm_values: The note's parsed frontmatter.
    state: The `spec_state` value to paint.

  Returns:
    The member notes whose bytes changed.
  """

  # Domain(spec.lifecycle):
  # # Members of a cancelled release
  # A release carries the documents included in it. While the release is live its members are in the release; when it
  # is cancelled its members no longer ride on it and wait for the next release, and when it is taken back they are
  # in the release again. A member that is already released or cancelled keeps its own final state, and so does a
  # member whose start document is not approved yet: its own coordinator sets its state. Members that were repainted
  # are woken once the cancellation or the taking back has landed.

  painted: list[Path] = []
  for member in _find_all_member_notes(note, fm_values):
    text = spec_paths.read_text(member)
    values, _end = spec_frontmatter.parse(text)

    # guard: a released or cancelled member keeps its own final state
    if flip_gate.is_true(values, Gate.RELEASED) or flip_gate.is_true(values, Gate.SPEC_CANCELLED):
      continue

    # guard: a member whose start document is not approved yet has its state set by its own coordinator
    if values.get(Gate.DESIGN_DONE, "").strip() == _FALSE:
      continue

    # a live member takes the state, and only a member whose bytes changed is written and reported
    new = spec_frontmatter.set_scalar(text, SpecStateKey.STATE, state)
    if new != text:
      spec_paths.write_text_atomic(member, new)
      painted.append(member)
  return painted


def _find_all_member_notes(note: Path, fm_values: dict) -> list[Path]:
  """
  List the member notes of a release that are on disk.

  Args:
    note: The asset's status note.
    fm_values: The note's parsed frontmatter.

  Returns:
    The included notes on disk, in the order the release lists them; none for a note that is not a release's.
  """
  # guard: only a release carries members
  if fm_values.get(AssetTypeKey.TYPE, "").strip() != ReleaseKey.ASSET_TYPE:
    return []

  # a member gone from disk has nothing to paint or keep
  return [
      member for member in release_delta.resolve_included_notes(spec_paths.find_settings_root(note.parent),
                                                                  spec_paths.read_text(note))
      if member.is_file()
  ]


def _resume_review(doc: Path) -> str | None:
  """
  Re-open the review of one document through the review plugin with the banner its stored state calls for,
  leaving the commit to the caller.

  Args:
    doc: The document whose stopped review resumes.

  Returns:
    None when the review was re-opened and its banner repainted, otherwise the reason it was not.
  """
  # guard: a review that cannot be re-opened has no banner to repaint
  if (failure := review_halt.run_review_verb(doc, _REVIEW_START_ARGS, _REVIEW_START_FAILED).failure) is not None:
    return failure

  # re-opening paints a fresh in-process banner, so the banner is repainted from the review's stored state
  return review_halt.run_review_verb(
      doc, ( _REVIEW_PAINT_VERB, _REVIEW_REPO_FLAG, str(flip_gate.repo_root(doc.parent)) ), _REVIEW_PAINT_FAILED,
  ).failure


def _wake_members(asset_dir: Path, painted: list[Path], today: str | None) -> None:
  """
  Wake the coordinator of every release member a landed cancel or un-cancel repainted, best-effort.

  Args:
    asset_dir: The release folder.
    painted: The member notes the call repainted.
    today: Optional ISO date forwarded into each member's own History line.
  """
  # guard: a call that repainted no member has nobody to wake
  if not painted:
    return

  # the flip has landed, so no failure waking a member may change its outcome
  try:
    coordinator_dispatch.wake_release_members(flip_gate.repo_root(asset_dir), painted, today = today)
  # waiver: best-effort boundary — the flip is already committed, a failed wake is reported, never raised
  except Exception as error:
    sys.stderr.write(f"{_CANCEL_LOG}: member wake failed after the flip: {error}\n")


def _find_all_authored_docs(asset_dir: Path, note: Path) -> list[Path]:
  """
  List the markdown files directly in an asset folder, the status note aside.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note, never listed.

  Returns:
    The markdown files of the folder itself, sorted by name.
  """
  # every markdown file in the folder itself; a nested folder belongs to another asset
  return [
      path for path in sorted(asset_dir.iterdir())
      if path.is_file() and path.suffix == _MD_SUFFIX and path != note
  ]


def uncancel(asset_dir: Path, *, auto: bool = False, reason: str = "", today: str | None = None) -> dict:
  """
  Clear an asset's cancellation and return the documents it took to the stages they had.

  Reviews the cancellation stopped are resumed with their banner, and the members of a release are woken once the
  clearing has landed.

  Guarantees:
    - On a cancelled asset the cleared flag and every moved document land in one commit, when the asset is in a
      git repository.
    - A document whose move is refused keeps its bytes and is reported in the result with its reason.
    - Only documents carrying a `spec_cancelled_with_asset` mark return from `cancelled`: a recorded `empty`,
      `deferred` or `rejected` stage returns as it is, and every other value, `approved` and the legacy `true`
      included, returns to `draft`; a cancelled document without the mark and every attachment are left untouched.
    - A marked document recorded as empty, deferred or rejected returns to that stage and is listed in `restored`;
      one recorded as draft or approved, or by the legacy `true` mark, returns to `draft` and is listed in `drafted`.
    - A document recorded as approved has every per-round review key dropped and its review opened once, fresh at
      the writer round, in the same commit and is listed in `resumed`, whether or not the cancellation had stopped
      its review; when the open fails it is named in `refused` and stays at `draft`.
    - Every other review carrying `spec_review_stopped_with_asset: true` is re-opened with its banner repainted from
      its stored review state; the mark is dropped in the same commit even when the re-open fails, and that
      document is named in `refused`.
    - A stopped review whose document is still `cancelled`, because its return was refused, is not re-opened; its
      mark is still dropped and the document is named in `refused`.
    - A checkpoint closed by a returned approval is opened again in the same commit: `spec_design_done`, with its
      timestamp, for the asset's start document, and on a release `spec_plan_done` for `code-plan.md`.
    - On a release, a returned `code-plan.md` recorded as approved turns off `spec_plan_done`, `spec_develop_done`,
      `spec_tests_passing` and `spec_built`, and a returned `test-plan.md` recorded as approved turns off
      `spec_tests_passing` and `spec_built`, each with its timestamp dropped.
    - A release carries `spec_rebuild_owed: true` after the flip's commit only when its last tracked job in the
      specs runtime sidecar is marked `unlanded: true` and `retired_by_cancel: true` and its `job_id` equals the
      note's `spec_build_job` or `spec_test_job`; a record unlanded before the cancel, by a refused landing or a dead
      job, owes nothing.
    - Once the flip has landed, the `retired_by_cancel` stamp is dropped from the status note's `last_job`, on a
      best-effort basis.
    - The live members of a release whose note does not read `spec_design_done: false` are repainted as members of
      the release and, once the flip has landed, woken on a best-effort basis.
    - Once the flip has landed, the asset's own coordinator is woken on a best-effort basis.
    - A release beside another open release of its owner, or under `releases/archive/`, is refused with nothing
      written.
    - The result always carries `drafted`, `restored`, `resumed` and `refused`.
    - An asset that is not cancelled, or a note that is not a status note, has no document moved and gets the gate
      flip's own refusal before anything is written.
    - A refused flip, and any exception raised before the flip's commit has landed, give every file the call may
      have written its original bytes back: the documents, the status note, the containers above it and the members
      of a release. An exception is re-raised after that.
    - An exception raised after the flip's commit has landed restores no file: the committed tree stays as HEAD has
      it, and the exception is re-raised.

  Notes:
    - Each moved document is rewritten in place and its `spec/<stage>` tag follows the new stage.
    - Only authored documents directly in the asset folder at `cancelled` are candidates; the status note never is.
    - A review that cannot be re-opened is named in `refused` and the call carries on.

  Args:
    asset_dir: The asset folder holding its status note `<asset_dir.name>.md`.
    auto: When True, mark the flip's run-log reason with an `auto:` prefix.
    reason: Optional note recorded in the flip's run log.
    today: Optional ISO date pinned into the flip's run log.

  Returns:
    The gate-flip result for `spec_cancelled` turned off, plus `"drafted"` — the file names of the documents moved
    to `draft`, sorted — `"restored"` — the file names returned to `empty`, `deferred` or `rejected`, sorted —
    `"resumed"` — the file names whose review was opened or re-opened, sorted — and `"refused"` — one
    `{"doc", "reason"}` entry per document left where it was or whose review could not be opened. A refused
    un-cancel carries the refused flip status with its reason and empty `drafted`, `restored` and `resumed` lists.
  """

  # Contract:
  # On a cancelled asset inside a git repository, the cleared flag and every moved document land in ONE commit.

  # Contract:
  # A document whose move is refused keeps its bytes and is reported in the result with its reason.

  # Contract:
  # Only documents carrying a `spec_cancelled_with_asset` mark return from `cancelled`: a recorded `empty`,
  # `deferred` or `rejected` stage returns as it is, and every other value, `approved` and the legacy `true`
  # included, returns to `draft`; a cancelled document without the mark and every attachment are left untouched.

  # Contract:
  # A document recorded as approved has every per-round review key dropped and its review opened ONCE, fresh at the
  # writer round, in the same commit, whether or not the cancellation had stopped its review; when the open fails it
  # is named in `refused` and stays at `draft`.

  # Contract:
  # Every other review carrying `spec_review_stopped_with_asset: true` is re-opened with its banner repainted from
  # its stored review state; the mark is dropped in the same commit even when the re-open fails, and that document
  # is named in `refused`.

  # Contract:
  # A stopped review whose document is still `cancelled`, because its return was refused, is not re-opened; its mark
  # is still dropped and the document is named in `refused`.

  # Contract:
  # A checkpoint closed by a returned approval is opened again in the same commit: `spec_design_done`, with its
  # timestamp, for the asset's start document, and on a release `spec_plan_done` for `code-plan.md`.

  # Contract:
  # On a release, a returned `code-plan.md` recorded as approved turns off `spec_plan_done`, `spec_develop_done`,
  # `spec_tests_passing` and `spec_built`, and a returned `test-plan.md` recorded as approved turns off
  # `spec_tests_passing` and `spec_built`, each with its timestamp dropped.

  # Contract:
  # A release carries `spec_rebuild_owed: true` after the flip's commit only when its last tracked job in the specs
  # runtime sidecar is marked `unlanded: true` and `retired_by_cancel: true` and its `job_id` equals the note's
  # `spec_build_job` or `spec_test_job`; a record unlanded before the cancel, by a refused landing or a dead job,
  # owes nothing.

  # Contract:
  # Once the flip has landed, the `retired_by_cancel` stamp is dropped from the status note's `last_job`, on a
  # best-effort basis: a sidecar that cannot be written is reported and never raised.

  # Contract:
  # The live members of a release whose note does not read `spec_design_done: false` are repainted as members of the
  # release and, once the flip has landed, woken on a best-effort basis.

  # Contract:
  # Once the flip has landed, the asset's own coordinator is woken on a best-effort basis.

  # Contract:
  # A release beside another open release of its owner, or under `releases/archive/`, is refused with nothing
  # written.

  # Contract:
  # The result always carries `drafted`, `restored`, `resumed` and `refused`, whether the call flipped, refused or
  # moved nothing.

  # Contract:
  # An asset that is not cancelled, or a note that is not a status note, has NO document moved and gets the gate
  # flip's own refusal before anything is written.

  # Contract:
  # A refused flip, and any exception raised before the flip's commit has landed, give every file the call may have
  # written its original bytes back: the documents, the status note, the containers above it and the members of a
  # release. An exception is re-raised after that.

  # Contract:
  # An exception raised after the flip's commit has landed restores no file: the committed tree stays as HEAD has
  # it, and the exception is re-raised.

  # Domain(spec.lifecycle):
  # # Un-cancelling an asset
  # A cancelled asset can be taken back. Clearing its cancellation returns only the documents that were taken with
  # the asset, each to the stage it had: one that had no stage yet, was parked or was rejected comes back as it was,
  # and every other one comes back as a draft, so the asset walks its ordinary path again. An approved document
  # comes back as a draft too, because its approval described it before the asset was abandoned: the earlier verdict
  # and round are dropped and a fresh review opens for it at the writing round in the same commit, once, whether or
  # not the cancellation had stopped its review. A document that was cancelled on its own before the asset was stays
  # cancelled, and an attachment follows its owner. Every other review the cancellation stopped is re-opened, where
  # it was paused and with its banner repainted from the review's stored state, so a document stopped at ready comes
  # back at ready; a review that was off before is left off. The mark of a stopped review is dropped even when its
  # re-opening fails, and that document is named among the refused. A stopped review whose document could not be
  # brought back, and so is still cancelled, is not reopened: it is named among the refused and loses its mark.
  # A release's live members are painted again as members of the release and woken once the clearing has landed,
  # and so is the asset's own coordinator.
  # Until then the asset refuses every checkpoint move but the clearing itself. A document
  # that cannot be moved stays where it is and is named, never guessed at. A clearing that is refused, or that fails
  # part-way before its commit has landed, puts every file back exactly as it was; a failure after the commit has
  # landed puts nothing back, the committed clearing stands and the failure is reported. Clearing the flag on
  # an asset that was never cancelled moves nothing — a single document cancelled on a live asset stays cancelled.

  note = asset_dir / f"{asset_dir.name}.md"
  fm_values, _end = spec_frontmatter.parse(spec_paths.read_text(note))
  drafted: list[str] = []
  restored: list[str] = []
  resumed: list[str] = []
  refused: list[dict] = []
  painted: list[Path] = []
  halt = review_halt.ReviewHalt()

  # only a cancelled asset's own status note has documents abandoned with it to bring back; any other note is the
  # primitive's to refuse before it writes anything
  if flip_gate.is_true(fm_values, Gate.SPEC_CANCELLED) and flip_gate.note_role(fm_values) == SpecValue.ROLE_STATUS:
    # guard: a release that cannot be open again refuses before anything is written
    if (blocker := _find_release_blocker(asset_dir, note, fm_values)) is not None:
      return { **_create_refusal(blocker, []), _DRAFTED_KEY: [], _RESTORED_KEY: [], _RESUMED_KEY: [] }

    # every file the un-cancel may write is held, so a failure part-way gives each its bytes back
    halt.keep([ note, *_find_all_authored_docs(asset_dir, note), *flip_gate.containers_above(asset_dir),
                *_find_all_member_notes(note, fm_values) ])
    halt.hold_head(flip_gate.repo_root(asset_dir))

    # the restore runs under the hold: a failure before the flip's commit takes every write back
    # noinspection PyBroadException
    try:
      # the documents that were approved when the asset was cancelled, read before they move
      left_approved = { doc.name for doc, recorded in _cancelled_docs(asset_dir, note)
                        if recorded.strip() == Stage.APPROVED }
      drafted, restored, resumed, refused, touched = _restore_docs(asset_dir, note)

      # the gates those approvals carried go down with them, in the flip's own commit
      _settle_note(note, fm_values, left_approved)

      # the release carries its members again
      painted = _repaint_members(note, fm_values, AssetState.IN_RELEASE)
      touched.extend(painted)

      # the cleared flag carries the moved documents into the flip's own commit
      flipped = flip_gate.flip_gate(asset_dir, Gate.SPEC_CANCELLED, off = True, auto = auto, reason = reason,
                                    today = today, extra_paths = list(dict.fromkeys(touched)))
    except Exception:
      # a failure before the flip's commit takes every write back; one after it leaves the committed tree alone
      if not halt.rollback_uncommitted():
        sys.stderr.write(f"{_UNCANCEL_LOG}: failed after the flip landed, nothing restored\n")
      raise
  else:
    # a note the un-cancel does not restore goes to the gate primitive untouched
    flipped = flip_gate.flip_gate(asset_dir, Gate.SPEC_CANCELLED, off = True, auto = auto, reason = reason,
                                  today = today)

  # guard: a flip refused after the restore takes every write back
  if flipped[FlipResult.STATUS] != FlipResult.FLIPPED:
    halt.rollback()
    return { **flipped, _DRAFTED_KEY: [], _RESTORED_KEY: [], _RESUMED_KEY: [], _REFUSED_KEY: refused }

  # the cancellation is taken back, so its stamp on the last job goes with it
  if flip_gate.note_role(fm_values) == SpecValue.ROLE_STATUS:
    _drop_cancel_stamp(note)

  # the repainted members and the asset's own coordinator learn of it only once the flip has landed
  _wake_members(asset_dir, painted, today)
  if flip_gate.note_role(fm_values) == SpecValue.ROLE_STATUS:
    _wake_own_coordinator(note, today)
  return { **flipped, _DRAFTED_KEY: sorted(drafted), _RESTORED_KEY: sorted(restored), _RESUMED_KEY: sorted(resumed),
           _REFUSED_KEY: refused }


def _restore_docs(asset_dir: Path, note: Path) -> tuple[list[str], list[str], list[str], list[dict], list[Path]]:
  """
  Return the documents a cancellation took with the asset to the stages they had and re-open the reviews it stopped.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note.

  Returns:
    The names of the documents moved to `draft`, the names of the documents returned to `empty`, `deferred` or
    `rejected`, the names of the documents whose review opened or re-opened, one `{"doc", "reason"}` entry per
    document left where it was or whose review did not open, and every path written.
  """
  drafted: list[str] = []
  restored: list[str] = []
  resumed: list[str] = []
  refused: list[dict] = []
  touched: list[Path] = []

  # the documents whose review the cancellation stopped re-open below, so an approved one is not opened twice
  stopped_docs = _find_all_stopped_docs(asset_dir, note)

  # each document taken with the asset returns to the stage its cancel recorded; a refused move leaves it where it
  # was, named
  for doc, recorded in _cancelled_docs(asset_dir, note):
    target = set_stage.compute_restored_stage(recorded)
    result = set_stage.apply_stage(doc, target, restore_from_cancel = True)
    if result.status == set_stage.StageStatus.REFUSED:
      refused.append({ _DOC_KEY: doc.name, _REASON_KEY: result.reason or "" })
      continue
    (drafted if target == Stage.DRAFT else restored).append(doc.name)
    touched.extend(Path(path) for path in result.touched_paths)

    # only a document that was approved goes on to a fresh review
    if recorded.strip() != Stage.APPROVED:
      continue

    # the old verdict described the document before the asset was abandoned, so its round state is dropped and
    # the review opens fresh at the writer round
    _clear_round_state(doc)
    touched.append(doc)

    # guard: a review the cancellation stopped re-opens below, so it is never opened twice
    if doc in stopped_docs:
      continue

    # an approved document comes back to be reviewed again from the writer round, in the same commit
    failure = _resume_review(doc)
    touched.append(doc)
    if failure is not None:
      refused.append({ _DOC_KEY: doc.name, _REASON_KEY: failure })
      continue
    resumed.append(doc.name)

  # every review the cancellation stopped re-opens where it was paused, and loses its mark whether or not it
  # re-opened, so no later un-cancel takes a stale mark for its own
  for doc in stopped_docs:
    spec_paths.write_text_atomic(
        doc, spec_frontmatter.drop_key(spec_paths.read_text(doc), StageKey.REVIEW_STOPPED_WITH_ASSET),
    )
    touched.append(doc)

    # guard: a document whose return was refused is still cancelled, and a cancelled document has no review to run
    if _stage_of(doc) == Stage.CANCELLED:
      if all(entry[_DOC_KEY] != doc.name for entry in refused):
        refused.append({ _DOC_KEY: doc.name, _REASON_KEY: _STILL_CANCELLED })
      continue

    # the review re-opens where it was paused
    failure = _resume_review(doc)
    if failure is not None:
      refused.append({ _DOC_KEY: doc.name, _REASON_KEY: failure })
      continue
    resumed.append(doc.name)

  # what the restore did, for the result and the flip's commit
  return drafted, restored, resumed, refused, touched


def _stage_of(doc: Path) -> str:
  """
  Read a document's stage.

  Args:
    doc: The document.

  Returns:
    Its `spec_stage` value, empty when it carries none.
  """
  # the stage is a plain frontmatter scalar
  return spec_frontmatter.parse(spec_paths.read_text(doc))[0].get(_STAGE_KEY, "").strip()


def _clear_round_state(doc: Path) -> None:
  """
  Drop every per-round review key from a document, so its next `start` opens the review fresh.

  Args:
    doc: The document whose review is opened again.
  """
  # each key leaves with its whole value span; a key already absent changes nothing
  text = spec_paths.read_text(doc)
  new = text
  for key in _REVIEW_ROUND_KEYS:
    new = spec_frontmatter.drop_key(new, key)
  if new != text:
    spec_paths.write_text_atomic(doc, new)


def _settle_note(note: Path, fm_values: dict, left_approved: set[str]) -> None:
  """
  Reopen the gates the returned approvals had closed and mark a release whose build or test job the cancel kept from
  landing as owing its rebuild.

  Args:
    note: The asset's status note.
    fm_values: The note's parsed frontmatter.
    left_approved: The file names of the documents recorded as approved when the asset was cancelled.
  """

  # Domain(spec.lifecycle):
  # # Taking an asset back reopens what its approvals had closed
  # A checkpoint that an approved document closed stays closed only while that document is approved. An asset taken
  # back returns its approved documents as drafts, so the checkpoints they closed open again with them in the same
  # step: the design checkpoint with the asset's start document, and on a release the plan checkpoint with its code
  # plan. On a release, a returned code plan rolls the whole build back: the plan, development, tests passing and
  # built checkpoints all open again. A returned test plan opens tests passing and built. This is the same rollback
  # a rebuild applies. The build is owed again only when the release's own build or test job lost its result because
  # of the cancellation: the cancellation killed it, or it had finished and only its landing was pending, or it
  # finished after the asset was cancelled, whatever that job's outcome. A result lost before the cancellation, a
  # refused landing or a job that died, owes nothing; it keeps waiting for the operator's rebuild. An earlier job
  # that is not the release's current build or test job owes nothing either. Such a release carries the
  # rebuild-owed flag that resumes it once the plan is settled. The cancellation's mark on the job's record is
  # removed once the asset is taken back.

  text = spec_paths.read_text(note)
  new = text
  is_release = fm_values.get(AssetTypeKey.TYPE, "").strip() == ReleaseKey.ASSET_TYPE

  # the gates each returned approval had closed, named by the document they are read from
  plan_gates = _RELEASE_PLAN_GATES if is_release else ( ( _start_doc_name(note), ( Gate.DESIGN_DONE, ) ), )
  for source, gates in plan_gates:
    # guard: a document that was not approved closed nothing to reopen
    if not source or source not in left_approved:
      continue
    for gate in gates:
      # guard: a gate already open stays as it is
      if not flip_gate.is_true(fm_values, gate):
        continue
      new = spec_frontmatter.drop_key(spec_frontmatter.set_scalar(new, gate, _FALSE),
                                      f"{gate}{SpecMomentKey.AT_SUFFIX}")

  # a release whose last job the cancellation cut short, or whose build or test job it let go before the result
  # landed, owes its build again
  if is_release and _is_build_unlanded(note, fm_values):
    new = spec_frontmatter.set_scalar(new, ReleaseKey.REBUILD_OWED, _TRUE)

  # only a changed note is written; the flip's commit carries it
  if new != text:
    spec_paths.write_text_atomic(note, new)


def _is_build_unlanded(note: Path, fm_values: dict) -> bool:
  """
  Tell whether a release's last job record names its build or test job whose result the cancel kept from landing.

  Args:
    note: The release's status note, whose sidecar holds the stored `last_job` record.
    fm_values: The release note's parsed frontmatter.

  Returns:
    True only when the record is marked both `unlanded: true` and `retired_by_cancel: true` and its job id is the
    release's last build or test job.
  """
  # the release's stored last job, read from the sidecar of the repository tracking it
  last = spec_job_markers.read(_sidecar_repo(note.parent), note)[JobMarker.LAST_JOB]

  # a job let go before its result landed owes the build only when it was the release's own build or test run
  build_jobs = { fm_values.get(key, "").strip().strip('"') for key in _RELEASE_JOB_KEYS } - { "" }
  return spec_job_markers.is_unlanded_record(last) and spec_job_markers.is_retired_by_cancel(last) \
      and isinstance(last, dict) and str(last.get(JobMarker.JOB_ID, "")) in build_jobs


def _start_doc_name(note: Path) -> str:
  """
  Name the document an asset starts from, by the type its product declares.

  Args:
    note: The asset's status note.

  Returns:
    The start document's file name, empty when the type names none or the product cannot be read.
  """
  # the asset's own product decides what its type starts from
  try:
    vault = spec_paths.find_settings_root(note.parent)
    _key, record = resolve_product.effective_record_by_path(vault, note.resolve().relative_to(vault.resolve())
                                                            .as_posix())
  except (RuntimeError, ValueError, OSError):
    record = None
  name, _doc_type = asset_types.start_doc(asset_types.type_of(note), record or {})
  return name


def _drop_cancel_stamp(note: Path) -> None:
  """
  Remove the cancellation's stamp from an un-cancelled asset's last job, best-effort.

  Args:
    note: The asset's status note.
  """
  # the un-cancel is committed, so a sidecar that cannot be written is reported, never raised
  try:
    repo = _sidecar_repo(note.parent)
    last = spec_job_markers.read(repo, note)[JobMarker.LAST_JOB]
    if isinstance(last, dict) and spec_job_markers.is_retired_by_cancel(last):
      spec_job_markers.update(repo, note, { JobMarker.LAST_JOB: spec_job_markers.drop_retired_by_cancel(last) })
  except (OSError, ValueError) as error:
    sys.stderr.write(f"{_UNCANCEL_LOG}: could not drop the cancel stamp after the flip: {error}\n")


def _wake_own_coordinator(note: Path, today: str | None) -> None:
  """
  Wake the coordinator of an asset whose un-cancel has landed, best-effort.

  Args:
    note: The asset's status note.
    today: Optional ISO date forwarded into the note's own History line.
  """
  # the un-cancel is committed, so no failure of the wake may change its outcome
  try:
    repo = flip_gate.repo_root(note.parent)
    item = { _ITEM_PATH: note.resolve().relative_to(repo.resolve()).as_posix() }
    coordinator_dispatch.coordinator_dispatch(note, item, today = today)
  # waiver: best-effort boundary — the un-cancel is already committed, a failed wake is reported, never raised
  except Exception as error:
    sys.stderr.write(f"{_UNCANCEL_LOG}: coordinator wake failed after the flip: {error}\n")


def _find_release_blocker(asset_dir: Path, note: Path, fm_values: dict) -> str | None:
  """
  Name why a cancelled release cannot be open again.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note.
    fm_values: The note's parsed frontmatter.

  Returns:
    The reason when the note is a release that sits in the releases archive or whose owner already has another
    open release; None otherwise, and for every other asset type.
  """

  # Domain(spec.lifecycle):
  # # A cancelled release cannot always be reopened
  # A product has at most one open release at a time. A cancelled release is taken back only when its owner holds no
  # other open release, and never from the releases archive, which is closed history the product no longer reads.
  # Either way the un-cancelling is refused and nothing is written.

  # guard: only a release is bound by the one-open-release rule
  if fm_values.get(AssetTypeKey.TYPE, "").strip() != ReleaseKey.ASSET_TYPE:
    return None

  # an archived release is closed history the product no longer reads, so it names its own reason
  if _is_archived(asset_dir):
    return _ARCHIVED_RELEASE

  # the product the release sits under, and the release its owner holds open
  vault = spec_paths.find_settings_root(asset_dir)
  rel_note = note.resolve().relative_to(vault.resolve()).as_posix()
  key, _record = resolve_product.effective_record_by_path(vault, rel_note)
  open_note = release_delta.find_open_release(vault, key) if key is not None else None
  if open_note is not None and open_note.resolve() != note.resolve():
    return _OPEN_RELEASE
  return None


def _find_closed_release(asset_dir: Path, fm_values: dict) -> str | None:
  """
  Name why a release cannot be cancelled.

  Args:
    asset_dir: The asset folder.
    fm_values: The asset note's parsed frontmatter.

  Returns:
    The reason when the note is a published release or sits in the releases archive; None otherwise, and for
    every other asset type.
  """

  # Domain(spec.lifecycle):
  # # A closed release cannot be cancelled
  # A published release is the record of what shipped, and a release in the releases archive is closed history the
  # product no longer reads. Neither can be cancelled: the cancellation is refused and nothing is written.

  # guard: only a release can be closed
  if fm_values.get(AssetTypeKey.TYPE, "").strip() != ReleaseKey.ASSET_TYPE:
    return None

  # a published release is the record of what shipped
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return _PUBLISHED_RELEASE
  return _ARCHIVED_RELEASE if _is_archived(asset_dir) else None


def _is_archived(asset_dir: Path) -> bool:
  """
  Tell whether an asset folder sits in a releases archive.

  Args:
    asset_dir: The asset folder.

  Returns:
    True when a `releases/archive/` folder holds it.
  """
  # the archive is the `archive` folder directly under a `releases` folder, at any depth above the asset
  return any(folder.name == ReleaseKey.ARCHIVE and folder.parent.name == ReleaseKey.FOLDER
             for folder in asset_dir.parents)


def _cancelled_docs(asset_dir: Path, note: Path) -> list[tuple[Path, str]]:
  """
  List the documents directly in an asset folder that were cancelled together with the asset.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note, never a candidate.

  Returns:
    The documents at `cancelled` carrying the cancelled-with-asset mark, attachments aside, sorted by name, each
    with the mark's value.
  """
  # a document cancelled on its own before the asset was, and an attachment that follows its owner, stay out
  docs: list[tuple[Path, str]] = []
  for path in _find_all_authored_docs(asset_dir, note):
    values, _end = spec_frontmatter.parse(spec_paths.read_text(path))

    # guard: an attachment returns with its owner's cascade
    if values.get(AttachmentKey.OWNER_DOC):
      continue

    # a document at `cancelled` carrying the mark was taken with the asset, and its mark names the stage it had
    recorded = values.get(StageKey.CANCELLED_WITH_ASSET, "").strip()
    if values.get(_STAGE_KEY, "").strip() == Stage.CANCELLED and recorded:
      docs.append(( path, recorded ))
  return docs


def _find_all_stopped_docs(asset_dir: Path, note: Path) -> list[Path]:
  """
  List the documents directly in an asset folder whose review the asset's cancellation stopped.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note, never a candidate.

  Returns:
    The documents carrying the review-stopped-with-asset mark, sorted by name.
  """
  # the mark alone says the cancellation stopped the review
  return [
      path for path in _find_all_authored_docs(asset_dir, note)
      if spec_frontmatter.parse(spec_paths.read_text(path))[0].get(StageKey.REVIEW_STOPPED_WITH_ASSET, "").strip()
      == _TRUE
  ]


def main(argv: list[str]) -> int:
  """
  Run the `flip-gate` verb: cancel on `spec_cancelled`, un-cancel on `spec_cancelled --off`, otherwise flip through
  the gate primitive.

  Guarantees:
    - A cancel or un-cancel that fails with an exception prints one JSON object `{"status": "error", "error": ...}`
      and returns 2, never 1, which a caller reads as a refusal.
    - A cancel that fails with an exception after killing the job that ran before it adds `killed_job`, that job's
      `last_job` record, to the JSON error object; otherwise the object has no `killed_job` key.

  Args:
    argv: The `flip-gate` arguments, excluding the program name, exactly as the gate primitive takes them.

  Returns:
    Exit code: 0 when the cancel or un-cancel flipped, 1 when it was refused, 2 when it failed with an exception
    (the JSON error is printed); every other call, a missing asset note included, returns the gate primitive's own
    exit code.
  """
  # only the cancel and un-cancel shapes are taken here; the parse never fails on the primitive's other options
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs flip-gate", add_help = False)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", nargs = "?", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("gate", nargs = "?", default = None)
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--off", action = "store_true")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--auto", action = "store_true")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--reason", default = "")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--halt", default = None)
  args, extra = parser.parse_known_args(argv)

  # Contract:
  # A cancel or un-cancel that fails with an exception prints one JSON object `{"status": "error", "error": ...}` on
  # stdout and returns 2, never 1, which a caller reads as a refusal. A cancel that fails with an exception after
  # killing the job that ran before it adds `killed_job`, that job's `last_job` record, to that object; otherwise
  # the object has no `killed_job` key.

  # anything but a plain cancel or un-cancel is the gate primitive's own call
  if extra or args.halt is not None or args.asset_dir is None or args.gate != Gate.SPEC_CANCELLED:
    return flip_gate.main(argv)

  # the asset folder the cancel or un-cancel acts on
  asset_dir: Path = args.asset_dir.resolve()

  # guard: the asset's status note must exist
  if not (asset_dir / f"{asset_dir.name}.md").is_file():
    return flip_gate.main(argv)

  # the job running before a cancel, so a failed cancel can name the job it had already killed
  note = asset_dir / f"{asset_dir.name}.md"
  running = None if args.off else read_running_job(note)

  # the cancel's or the un-cancel's result goes to stdout whole; a failure leaves as a JSON error with its own code,
  # never as a refusal
  try:
    result = (uncancel if args.off else cancel)(asset_dir, auto = args.auto, reason = args.reason)
  # waiver: CLI boundary — an exception must not leave as a traceback and exit 1, which reads as a refusal
  except Exception as error:
    killed = find_killed_job(note, running)
    print(json.dumps({ FlipResult.STATUS: _ERROR_STATUS, _ERROR_KEY: f"{type(error).__name__}: {error}",
                       **({ _KILLED_JOB_KEY: killed } if killed is not None else {}) }))
    return _EXIT_FAILED
  print(json.dumps(result))
  return 0 if result[FlipResult.STATUS] == FlipResult.FLIPPED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
