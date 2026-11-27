"""
Per-file gate-tick worker for the md-scan daemon.

Invoked once per matched asset status folder-note. `spec.coordinator` (per
`lazy-spec.coordination-playbook.md`, dispatched by the sibling `coordinator_dispatch.py` routine, not
by this one) now owns every inter- and intra-asset sequencing decision — which gate to flip,
which sibling doc to promote, which checkbox-equivalent job to dispatch next, whether a change
cascades into its targets. This worker keeps only the four concerns no LLM needs to be woken for:

- Active-job polling (`spec_job_markers.py`'s `active_job`): an asset tracking the marker has its
  job bundle's terminal marker (`DONE` / `DEAD` / `CANCELLED`, per the `lazycortex-core` job-runtime
  layout, read file-wise — never imported across the plugin boundary) checked on every tick.
  `DONE` lands the job's `result/` into the asset folder through the `land-result` collector —
  the only channel a job's document and attachments take into the catalog. A landing that is
  `landed` or `empty` clears the marker and retires the bundle (`gate_dispatch.consume_stale_job`,
  freeing its dedup key so the checkbox can be re-dispatched), writing nothing into the folder-note;
  `CANCELLED` does the same without the landing. `DEAD`, and a `DONE` whose landing was `refused`,
  instead set `spec_halted: true` and append a persistent `[!failure]` callout to `# Gates`
  (un-halting is a manual operator act, out of scope here), leaving the bundle unretired for
  diagnostics; a refused landing also reports a `plugin_error` warning to the core error ledger,
  fire-and-forget. A `DONE` whose document belongs to a declared `spec_targets` asset (a cascade fold) is
  neither landed nor halted: it is retired with `last_job` recorded without `unlanded`, and its bundle stays for
  the coordinator's `land-result --target`. A `DONE` on a cancelled note is retired with no landing and no wake,
  `last_job` recorded `unlanded` and `retired_by_cancel`. Every other clear also raises `pending_wake: job-done`
  in the sidecar, and that
  flag is the whole wake: the `collect-tick` postman sweep dispatches the coordinator on it directly, with no
  commit behind it. This worker opens no review itself; the
  coordinator opens it with `lazy-review.submit` on the `job-done` wake this same poll raises.
- Coordinator-job polling (`spec_job_markers.py`'s `coordinator_job`): the same terminal-marker
  check, applied to the coordinator's own one-job-per-asset slot instead. `DONE` / `CANCELLED` retire the
  bundle (`gate_dispatch.consume_stale_job`, freeing its dedup key) and clear the marker, touching
  the note not at all — that branch's whole effect is runtime state, so it costs no commit; `DEAD`
  clears the marker, writes a `# History` WARNING line, and never halts the asset — the
  coordinator's own wake job is not a ladder expert job, so `spec_halted` stays untouched. This
  sweep is `coordinator_dispatch.py`'s own backstop: that git-watch routine only re-checks a
  coordinator job's marker when a NEW commit wakes it, so a job that dies with no further commit
  landing would otherwise leave the marker stranded forever — this worker's periodic md-scan
  cadence catches it regardless, because the routine is registered with `change_gate: false`
  (the md-scan change gate would otherwise skip a note whose folder did not change, and a
  finished job changes nothing there).
- Coherence-check polling (`spec_job_markers.py`'s `coherence_jobs`): each coherence check tracked on the
  note is polled independently of the jobs above, on every tick and before them. A `DONE` check has its
  conflicts hung as callouts on the folder-notes of the documents involved through the `coherence-apply`
  verb, which records the check's `# History` line with the count in the same commit, and is retired; a check
  whose line already stands in the history is only retired, never applied again. `CANCELLED` is retired with
  no line; `DEAD`, and a `DONE` whose apply was refused or failed, log a WARNING line and never halt the asset.
  A finished check leaves the note's list once no line is owed for it and wakes no coordinator, and the tick
  result gains a `coherence` list of the checks that finished.
- Structural note-check: `note_ops.note_check`'s violations (an unrecognized or mistyped
  frontmatter key, a missing or misordered required section) are folded into this tick's own
  result — read-only, repaired by the coordinator through its pen and `note-set-key`, never by
  this worker.

A no-op tick (no active job with a terminal marker yet, note structurally clean) reports
`{"action": "noop"}`. `coordinator_dispatch.py` is this worker's own sibling routine, not a step
of this tick — it wakes `spec.coordinator` on its own schedule.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from types import ModuleType

  from collections.abc import Callable, Iterable, Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import error_report  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_rows  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES,
    CoordinatorTrigger,
    Gate,
    HaltReason,
    HistoryEvent,
    JobMarker,
    LevelDoc,
    PluginErrorCause,
    Section,
    SpecCoordinatorDocStateKey,
    SpecHaltKey,
    SpecKey,
    SpecTargetsKey,
    TickAction,
)


# How a subprocess's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# How a top-level heading line opens; such a line bounds a note's sections.
_H1_PREFIX = "# "

# The `pending_wake` values a tick-pending wake may stand in place of: none raised, or a wake the busy guard declined
_REPLACEABLE_WAKES = frozenset({ None, JobMarker.DECLINED })

# Regex template for locating a frontmatter key's line, shared by `set_fm_json` / `del_fm_key`.
_FM_KEY_RE_TEMPLATE = r"(?m)^{key}\s*:.*$"
# Trailing-newline suffix `del_fm_key` appends to `_FM_KEY_RE_TEMPLATE` so the deleted key's
# own line break goes with it, rather than leaving a blank line behind.
_TRAILING_NEWLINE_RE = r"\n?"

# The sibling CLI entry point's bare filename, resolved via `_BIN` (this module's own directory)
# rather than `$LAZYCORTEX_PLUGIN_DIRS` — `_run_note_check` calls back into this same plugin, not
# across the plugin boundary.
_SPEC_CLI_NAME = "lazycortex-specs"
_NOTE_CHECK_SUBVERB = "note-check"
_COHERENCE_APPLY_SUBVERB = "coherence-apply"

# The `coherence-apply` verb's flags naming the note whose history takes the check's line, the line and its day.
COHERENCE_HISTORY_NOTE_FLAG = "--history-note"
COHERENCE_HISTORY_LINE_FLAG = "--history-line"
COHERENCE_HISTORY_DATE_FLAG = "--history-date"
# The token standing in a check's History line for the conflict count, which only the apply comes to know.
COHERENCE_COUNT_SLOT = "{count}"
# The fields of the History line of a landed check: the document, the job, the count and the dropped neighbours.
_LINE_DOC = "doc"
_LINE_JOB = "job_id"
_LINE_COUNT = "count"
_LINE_DROPPED = "dropped"

# The two states a raised stage lag moves through: woken once, then warned and left alone.
_LAG_WOKEN = "woken"
_LAG_WARNED = "warned"

# What follows a lag's fingerprint in the record key that marks where its episode began: the number of that lag's
# warning lines the history already carried when the lag was woken. A document basename holds no slash, so the key
# never reads as a fingerprint.
_LAG_EPISODE_SUFFIX = "/lines-before"

# What follows a lag's fingerprint in the record key naming the job whose finish woke the lag, so a second pass
# over that same job is not counted as a second finish.
_LAG_JOB_SUFFIX = "/woken-by"

# The result key naming the documents a finished coordinator job left with a lagging stage.
_STAGE_LAG_RESULT = "stage_lag"

# The env var naming the repository root a sibling verb resolves against.
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# `note_ops.note_check`'s result-dict key this worker folds into its own tick result.
_VIOLATIONS_KEY = "violations"

# The landing collector's result-dict vocabulary, mirrored from `land_result`: the paths it wrote,
# what became of the landing, and the one-line reason of a refused one.
_LANDED_KEY = "landed"
_LANDING_ACTION_KEY = "action"
_LANDING_EMPTY = "empty"
_LANDING_REFUSED = "refused"
_LANDING_REASON_KEY = "reason"

# Prefix of the error-ledger incident a refused landing opens, completed with `<expert>/<job_id>`.
_LANDING_INCIDENT_PREFIX = "landing-refused:"

# The `coherence-apply` verb's summary key counting the conflicts it hung.
_CONFLICTS_KEY = "conflicts"

# The tick result's key listing the coherence checks that finished, and each record's outcome field.
_COHERENCE_KEY = "coherence"
_OUTCOME_KEY = "outcome"
# The outcome of a finished coherence check whose result could not be applied.
_OUTCOME_FAILED = "failed"


# Mirrored job-bundle terminal-marker filenames from `lazycortex-core`'s job runtime, read
# file-wise only, per `dev.plugin-boundaries.md` § 2a — a cross-plugin Python import of
# `lazycortex-core`'s own constants module would break in a consumer install where the two
# plugins live at unrelated cache paths. Each is a bare filename `touch()`-ed empty by the
# core expert pump inside a job's `.experts/.jobs/<expert>/<job_id>/` directory.
JOB_MARKER_DONE = "DONE"
JOB_MARKER_DEAD = "DEAD"
_JOB_MARKER_CANCELLED = "CANCELLED"

# Mirrored job-bundle lifecycle markers from the same runtime: `READY` is touched last by a
# dispatch (the bundle is complete and queued), `PID` is written by the pump the moment it
# claims the job and copies its `source/` / `context/` from the tree as it stands then.
_JOB_MARKER_READY = "READY"
_JOB_MARKER_PID = "PID"

# Mirrored claim-time artifact from the same runtime: the commit the work tree stood at when the
# pump claimed the job, i.e. the tree its `source/` / `context/` were copied from.
_JOB_ARTIFACT_CLAIM_HEAD = "claim_head"

# Mirrored job-bundle directory layout: `<repo>/.experts/.jobs/<expert>/<job_id>/`.
_JOBS_BASE = ".experts/.jobs"
# The finished job's response envelope inside its bundle, and the field naming how the job ended
_RESPONSE_FILE = "response.json"
_RESPONSE_OUTCOME = "outcome"

# Bot identity for this worker's own commits (job-marker application + History line).
_PROMOTE_AUTHOR_NAME = "lazy-spec.gate-tick"
_PROMOTE_AUTHOR_EMAIL = "lazy-spec.gate-tick@bot.invalid"

def commit_note_change(asset_dir: Path, asset_note: Path, subject: str) -> None:
  """
  Commit the rewritten status folder-note under the `lazy-spec.gate-tick` bot identity.

  Shared by every gate-tick mutation that touches only the single folder-note file, so the note
  never stays dirty for the next daemon iteration. Nothing is committed when the asset lives in
  a vault outside a git checkout; the folder-note write is then the whole mutation.

  Args:
    asset_dir: The asset folder, locating the enclosing repository.
    asset_note: The status folder-note path that was just rewritten.
    subject: The commit subject line.

  Raises:
    subprocess.CalledProcessError: If the commit fails, or git fails inside a repository while the repository is
      looked up; such a failure is never read as "no repository".
    OSError: If git cannot be run inside a repository while the repository is looked up.
  """
  # the repository holding the asset anchors both the repaint and the git commands below
  repo = flip_gate.find_repo_top(asset_dir)

  # guard: the vault lives outside a git checkout — nothing to commit into; the file write
  # above stays and is the whole mutation. A git failure inside a checkout raised above
  if repo is None:
    return

  # commit the note by pathspec under the dedicated bot identity, its icon repaint folded in, so the tree is
  # clean for the next daemon iteration and the operator's authorship and staging stay untouched
  flip_gate.commit_paths(
      repo, [ asset_note ], subject = subject, author_name = _PROMOTE_AUTHOR_NAME,
      author_email = _PROMOTE_AUTHOR_EMAIL,
  )


def write_and_commit_note(
    asset_dir: Path, asset_note: Path, new_text: str, *, original_text: str, subject: str,
    commit: Callable[[Path, Path, str], None] | None = None,
) -> None:
  """
  Write a folder-note's new text and commit it, putting the old text back when the commit fails.

  Guarantees:
    - When the commit raises `OSError` or `subprocess.CalledProcessError` and the note can be put back, it is put
      back to exactly `original_text` before the error propagates, so no uncommitted text is left in the tree and
      a retry starts from the same bytes.
    - When putting the note back fails too, the error that propagates is still the commit's own, never the
      restore's; the restore failure is attached to it as a note and named on stderr together with the note's
      path, and the note is left holding the uncommitted text.

  Args:
    asset_dir: The asset folder, locating the enclosing repository.
    asset_note: The status folder-note path.
    new_text: The note's whole new text.
    original_text: The note's whole text as it stood before this write.
    subject: The commit subject line.
    commit: The commit callable, called with the asset folder, the note and the subject; `None` commits under
      the `lazy-spec.gate-tick` bot identity.

  Raises:
    OSError: If the first write of the note fails, in which case nothing was committed; or if the commit itself
      raises it, in which case the note is put back to `original_text` and the commit's error is re-raised, with
      a failed put-back attached to it as a note.
    subprocess.CalledProcessError: If the commit fails; the note is put back to `original_text` and the error is
      re-raised, with a failed put-back attached to it as a note and the note left holding the uncommitted text.
  """

  # Contract:
  # When the commit raises `OSError` or `subprocess.CalledProcessError` and the note can be put back, it is put
  # back to exactly `original_text` before the error propagates, so no uncommitted text is left and a retry
  # starts from the same bytes.
  # When putting the note back fails too, the error that propagates is still the commit's own, never
  # the restore's. The restore failure is attached to it as a note and named on stderr together with
  # the note's path, and the note is then left holding the uncommitted text.

  # write the new text first, the commit below decides whether it stays
  spec_paths.write_text_atomic(asset_note, new_text)

  # a commit that fails leaves the note as it was found, so the tick that retries it starts from the same text
  # and records its line or callout once, and no uncommitted text is left in the tree
  try:
    (commit or commit_note_change)(asset_dir, asset_note, subject)
  except (OSError, subprocess.CalledProcessError) as error:
    # a restore that fails too must not hide the commit's own error: it is named on stderr and attached to the
    # error that propagates, and the note is then left holding the uncommitted text
    try:
      spec_paths.write_text_atomic(asset_note, original_text)
    except OSError as restore_error:
      sys.stderr.write(f"gate-tick: {asset_note}: could not put the note back after a failed commit: "
                       f"{restore_error}\n")
      error.add_note(f"the note {asset_note} could not be put back: {restore_error}")
    raise


def target_asset_dir(asset_dir: Path, raw_target: str) -> Path | None:
  """
  Resolve a cascade-target token to its asset folder.

  The token is a path relative to the owning product's root — the product `resolve_product`
  attributes `asset_dir` to by the longest matching `spec_path`, so a nested product resolves to
  the inner one — with any number of segments: `bugs/crash`, a nested asset's full path, or a
  bare slug at the product root. `coordinator_dispatch.py`'s own `spec_targets` context fold-in
  resolves every token through this same primitive.

  Args:
    asset_dir: The asset folder the token is declared on.
    raw_target: The product-relative path token (e.g. `bugs/my-bug`).

  Returns:
    The target asset folder, resolved, or None when the token is malformed or names no
    folder-note that actually exists on disk.
  """
  return resolve_product.resolve_asset_token(asset_dir, raw_target)


def find_active_job_marker(repo_root: Path, expert: str, job_id: str) -> str | None:
  """
  Check which terminal marker, if any, is present in an active job's bundle directory.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    The bare marker filename found (`"DONE"` / `"DEAD"` / `"CANCELLED"`), or None when the
    job's bundle directory carries none of them yet (still running).
  """
  job_dir = repo_root / _JOBS_BASE / expert / job_id
  for marker in (JOB_MARKER_DONE, JOB_MARKER_DEAD, _JOB_MARKER_CANCELLED):
    if (job_dir / marker).is_file():
      return marker
  return None


def has_job_bundle(repo_root: Path, expert: str, job_id: str) -> bool:
  """
  Check whether a job's bundle directory still exists.

  Guarantees:
    - An unknown state is never answered as absent: a bundle directory that, or whose parent folder, does not exist
      is answered `False`, and any other failure to examine it raises `OSError`.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name.
    job_id: The dispatched job id.

  Returns:
    True while the bundle directory is on disk, whatever state the job is in; False when the path is not a
    directory, or a folder above it is missing or is not a directory.

  Raises:
    OSError: If the directory cannot be examined, for instance when a folder above it cannot be searched; an
      unknown state is never answered as absent.
  """

  # Contract:
  # An unknown state MUST NEVER be answered as absent. A bundle directory that does not exist, or whose parent
  # folder does not exist, is answered `False`; any other failure to examine it raises `OSError`, so a caller
  # can tell "gone" from "cannot tell" and retries the second case later instead of acting on it.

  # a missing path is a plain no; any other failure to look means the answer is unknown, so it is raised
  try:
    mode = os.stat(repo_root / _JOBS_BASE / expert / job_id).st_mode
  except (FileNotFoundError, NotADirectoryError):
    return False
  return stat.S_ISDIR(mode)


def is_job_queued(repo_root: Path, expert: str, job_id: str) -> bool:
  """
  Check whether an active job is still waiting in the queue — dispatched, never claimed.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    True when the bundle carries `READY` and no `PID`; False for a claimed job, and for a
    bundle that is missing altogether, whose state cannot be told and so reads as running.
  """
  job_dir = repo_root / _JOBS_BASE / expert / job_id
  return (job_dir / _JOB_MARKER_READY).is_file() and not (job_dir / _JOB_MARKER_PID).exists()


def read_job_claim_head(repo_root: Path, expert: str, job_id: str) -> str | None:
  """
  Read the commit a claimed job's inputs were copied from.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    The recorded commit hash, or None when the bundle carries no claim-head marker — a job
    not yet claimed, a bundle that is gone, or a pump older than the marker.
  """
  try:
    value = (
        repo_root / _JOBS_BASE / expert / job_id / _JOB_ARTIFACT_CLAIM_HEAD
    ).read_text(encoding = "utf-8").strip()
  except OSError:
    return None
  return value or None


def _load_collector() -> ModuleType:
  """
  Load the `land-result` collector module on demand.

  Returns:
    The `land_result` module.

  Raises:
    ImportError: If the `land_result` module is missing or fails to import.
  """
  # waiver: local import inside the try on purpose -- a broken or missing `land_result` module
  # degrades into a refused landing like any other landing failure instead of crashing the tick
  import land_result  # pylint: disable=import-error
  return land_result


def _land_job_result(repo_root: Path, asset_dir: Path, expert: str, job_id: str) -> dict:
  """
  Put one finished job's document in the asset folder through the `land-result` collector.

  Notes:
    - Nothing is raised: a landing failure of any kind is reported as a refused landing.

  Args:
    repo_root: The repository root holding the job queue.
    asset_dir: The asset folder the job's document belongs in.
    expert: The dispatched expert's name, the job queue's first path segment.
    job_id: The finished job's id.

  Returns:
    The collector's result: `{"action": "landed", "landed": [<paths>]}` when files landed,
    `{"action": "empty", "landed": []}` when the job delivered nothing or its bundle is gone, and
    `{"action": "refused", "landed": [], "reason": <one line>}` when the delivery failed.
  """

  # the finished job's bundle directory in the expert job queue
  job_dir = repo_root / _JOBS_BASE / expert / job_id

  # guard: the bundle is gone — there is nothing to land
  if not job_dir.is_dir():
    return { _LANDING_ACTION_KEY: _LANDING_EMPTY, _LANDED_KEY: [] }
  try:
    return _load_collector().land_job(job_dir, asset_dir)
  # waiver: the tick survives ANY landing failure — it is turned into a refused landing the caller
  # halts the asset on, rather than an exception that stops the tick mid-marker
  except Exception as error:
    sys.stderr.write(f"gate-tick: land-result {expert}/{job_id}: {error}\n")
    return {
        _LANDING_ACTION_KEY: _LANDING_REFUSED, _LANDED_KEY: [],
        _LANDING_REASON_KEY: str(error) or type(error).__name__,
    }


def _is_cascade_fold(text: str, fm_end: int, *, asset_dir: Path, repo_root: Path, expert: str, job_id: str) -> bool:
  """
  Tell whether a finished job is a cascade fold, whose document the coordinator lands into a target asset itself.

  Notes:
    - A collector that will not import, or a dispatch or catalog settings that cannot be read, reads as no fold: one
      `gate-tick: fold check <expert>/<job_id>: <error>` line is written to stderr and nothing is raised.

  Args:
    text: The folder-note's full text as last read from disk.
    fm_end: Index just past the frontmatter's closing `---` fence in `text`.
    asset_dir: The asset folder the job was dispatched from.
    repo_root: The repository root holding the job queue.
    expert: The dispatched expert's name.
    job_id: The finished job's id.

  Returns:
    True when the job's `target_doc` lies outside the asset folder, inside the spec catalog, and inside the folder of
    one of the asset's declared `spec_targets`; False otherwise.
  """
  # guard: a collector that will not import, or a catalog root that cannot be read, leaves the target unknown, so
  # the job is no fold and the landing below decides its fate
  try:
    target = _load_collector().find_foreign_target(repo_root / _JOBS_BASE / expert / job_id, asset_dir)
  except (ImportError, OSError, ValueError) as error:
    sys.stderr.write(f"gate-tick: fold check {expert}/{job_id}: {error}\n")
    return False

  # guard: a document meant for the asset's own folder, or for no catalog place at all, is no fold
  if target is None:
    return False

  # only a document belonging to one of the asset's own declared cascade targets is a fold
  for token in read_fm_list(text[:fm_end], SpecTargetsKey.TARGETS):
    folder = target_asset_dir(asset_dir, token)
    if folder is not None and target.is_relative_to(folder.resolve()):
      return True
  return False


def _apply_coherence_result(repo_root: Path, job_dir: Path, *, note: Path, line: str, today: str) -> int | None:
  """
  Hang a finished coherence check's conflicts on the folder-notes of the documents involved.

  The check's History line is recorded in the same commit, in the note that tracks the check.

  Notes:
    - Nothing is raised: a result that is refused, unusable or fails to commit hangs nothing and records no line.

  Args:
    repo_root: The repository root holding the job queue.
    job_dir: The finished coherence job's bundle directory.
    note: The folder-note tracking the check, whose history takes the line.
    line: The check's History line, holding `COHERENCE_COUNT_SLOT` where the conflict count goes.
    today: ISO date string the line is recorded under.

  Returns:
    The number of conflicts hung, or `None` when the apply was refused or failed.
  """

  # Decision: subprocess the sibling CLI, not an in-process import — `coherence.py` already imports this module
  # (for `del_fm_key` / `set_fm_json`), so importing it here would be circular

  # the sibling CLI that hosts the `coherence-apply` verb, run against this repository
  cli = _BIN / _SPEC_CLI_NAME
  env = { **os.environ, _ENV_REPO_ROOT: str(repo_root) }
  try:
    proc = subprocess.run(
        [ sys.executable, str(cli), _COHERENCE_APPLY_SUBVERB, str(job_dir),
          COHERENCE_HISTORY_NOTE_FLAG, str(note), COHERENCE_HISTORY_LINE_FLAG, line,
          COHERENCE_HISTORY_DATE_FLAG, today ],
        capture_output = True, text = True, check = False, encoding = "utf-8", errors = _DECODE_ERRORS, env = env,
    )
    answer = json.loads(proc.stdout)
  except (OSError, json.JSONDecodeError) as error:
    sys.stderr.write(f"gate-tick: coherence-apply {job_dir.name}: {error}\n")
    return None

  # guard: a refused result hangs nothing, and the refusal goes where any landing failure goes
  if proc.returncode != 0 or not isinstance(answer, dict) or not isinstance(answer.get(_CONFLICTS_KEY), int):
    sys.stderr.write(f"gate-tick: coherence-apply {job_dir.name}: {proc.stdout.strip()} {proc.stderr.strip()}\n")
    return None
  return answer[_CONFLICTS_KEY]


def _poll_coherence_jobs(asset_note: Path, repo_root: Path, today_str: str) -> list[dict]:
  """
  Land every finished coherence check tracked on a folder-note and take it off the note's list.

  Notes:
    - The note's launch-checkbox and coordinator jobs and its pending wake are left as they are.
    - A check whose apply succeeded owes no further line, because the apply records the check's own History line in
      its commit, and a cancelled check owes none either; both leave the list at once.
    - A failed or dead check stays on the note's list, carrying its failure line, until that line stands in the
      note's history; a later tick finishes an entry left in that state without applying its result again, even
      when its bundle is gone.
    - A failure line already in the note's history, in whatever language it was written, is not written again; when
      every owed line is already there the note is neither written nor committed and only the list is brought up
      to date.
    - When the commit fails, the error propagates with the owed lines still on the list, and the note is put back
      to its text when that succeeds, otherwise it keeps the uncommitted lines.
    - A finished check's result is applied first, then its entry is taken off the list, then its bundle is retired;
      when the write that updates the list raises right after the apply, the next tick finds the check's line in
      the note's history, applies nothing and only takes the entry off the list.

  Args:
    asset_note: The folder-note tracking the checks.
    repo_root: The repository root holding the job queue and the job-marker sidecar.
    today_str: ISO date string pinned into the History lines.

  Returns:
    One `{"doc", "job_id", "outcome"}` record per check that finished on this tick, `outcome` being `done`,
    `cancelled`, `dead` or `failed`; a `done` record also carries `conflicts`, the number of conflicts hung, and a
    `failed` one stands for a finished check whose apply was refused or failed, with no `conflicts`. A check found
    already landed, its own line standing in the note's history, is reported as `done` with the count read off
    that line and is not applied again. A check whose failure line an earlier tick left owed is not reported
    again. Empty when none finished on this tick.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot be resolved while
      recording a failure line.
    OSError: If the note or the job-marker sidecar cannot be written, or the commit of the failure lines raises
      it; after a commit that landed, a failed sidecar write leaves the owed lines committed and still on the list,
      and the next tick finds them in the history, writes nothing again and only takes the checks off the list.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the failure lines exits
      non-zero.
  """

  # Domain(spec.coherence):
  # # A finished coherence check lands as conflict callouts
  # A coherence check of a document returns no document to place; it returns the conflicts it found against the
  # approved documents around it. Each checked document has its own entry in a list kept for its asset outside the
  # note's text, and the entries are polled independently of the asset's other jobs, so checks of several documents
  # run side by side and none waits for or blocks the rest. When a check finishes, its conflicts are hung as callouts
  # on the folder-notes of the documents involved, with no coordinator step in between, and the asset's history
  # records how many were found and, when any neighbours were left out over the size budget, how many. The callouts
  # are the operator's signal, so a finished check wakes nobody. A check that died, or finished with a result that
  # could not be used, hangs nothing: the history records a warning line and the asset goes on, never halted. A
  # cancelled check owes nothing and leaves the list at once. A finished check is applied at most once: its
  # conflicts and its own line in the asset's history, naming the document, the check, how many conflicts were hung
  # and how many neighbours were left out when any were, are recorded together as one change, so there is never a
  # moment when the conflicts are hung and the line is missing. A later pass that meets a finished check first looks
  # in the asset's history for that check's own line, whatever language it was written in: only the history itself
  # counts, and another check's line never does. When the line is there, the conflicts are not hung again and the
  # check is simply taken off the list, so a pass that hung the conflicts and then failed to take the check off the
  # list causes no second hanging. A check that died, or whose result could not be used, hangs nothing and stays
  # on the list with the warning line it owes until that line is recorded in the asset's history; a later pass
  # records it without applying the result. The warning line of such a check is recorded at most once: before a
  # pass records the warning lines it owes, it looks in the asset's history for each check's own warning line, the
  # same document and the same check, whatever language it was written in, and only the history itself counts. A
  # line already there was recorded by an earlier pass that then failed to take the check off the list, so it is
  # not written again and the check is simply taken off the list. When every owed line is already in the history,
  # nothing is recorded at all. If recording fails, the note is put back as it was. Putting the note
  # back can fail too: then the note keeps the unrecorded lines, the failure is reported, and the next pass reads
  # that text as the note's own.

  jobs = spec_job_markers.coherence_jobs(repo_root, asset_note)
  landed: list[dict] = []
  retired: set[int] = set()
  for index, job in enumerate(jobs):
    # guard: a check that landed on an earlier tick only waits for its History line, whatever became of its bundle
    if JobMarker.HISTORY in job:
      continue
    marker = find_active_job_marker(repo_root, job[JobMarker.EXPERT], job[JobMarker.JOB_ID])

    # guard: a check still running stays on the list
    if marker is None:
      continue
    doc, job_id = job[JobMarker.DOC], job[JobMarker.JOB_ID]
    record: dict[str, str | int] = { JobMarker.DOC: doc, JobMarker.JOB_ID: job_id, _OUTCOME_KEY: marker.lower() }

    # a finished check's conflicts hang now; a cancelled one has nothing to say, a dead one only its failure
    line: str | None = None
    if marker == JOB_MARKER_DONE:
      dropped = job.get(JobMarker.DROPPED)

      # a check whose own line already stands in the note's history has landed: the apply commits that line
      # together with the conflicts, so a pass that failed to mark the check as landed left the proof behind,
      # and this pass hangs nothing again and only marks it
      count = recorded_coherence_count(spec_paths.read_text(asset_note), doc, job_id, dropped)
      if count is None:
        key, fields = _coherence_line_fields(doc, job_id, dropped)
        count = _apply_coherence_result(
            repo_root, repo_root / _JOBS_BASE / job[JobMarker.EXPERT] / job_id,
            note = asset_note, line = note_explainers.history_line(asset_note, key, **fields), today = today_str,
        )

      # a landed check owes no further line; one whose apply was refused or failed owes its failure line
      if count is None:
        record[_OUTCOME_KEY] = _OUTCOME_FAILED
        line = note_explainers.history_line(asset_note, HistoryEvent.COHERENCE_FAILED, doc = doc, job_id = job_id)
      else:
        record[_CONFLICTS_KEY] = count
    elif marker == JOB_MARKER_DEAD:
      line = note_explainers.history_line(asset_note, HistoryEvent.COHERENCE_FAILED, doc = doc, job_id = job_id)

    # the entry is marked as landed before anything else happens to the check: a check whose line is already in
    # the note, and a cancelled one, simply leave the list; a failed or dead one stays with the line it owes,
    # which survives until the commit below succeeds
    if line is None:
      retired.add(index)
    else:
      jobs[index] = { **job, JobMarker.HISTORY: line }
    spec_job_markers.update(repo_root, asset_note, {
        JobMarker.COHERENCE_JOBS: [ kept for at, kept in enumerate(jobs) if at not in retired ],
    })

    # a finished or cancelled bundle is spent; a dead one is kept for diagnostics
    if marker != JOB_MARKER_DEAD:
      gate_dispatch.consume_stale_job(repo_root, job[JobMarker.EXPERT], job_id)
    landed.append(record)

  # the checks that owe the note a line: this tick's, and those an earlier tick left on the list
  owing = [ job for job in jobs if JobMarker.HISTORY in job ]

  # guard: no line is owed, so the note is left as it is
  if not owing:
    return landed

  # a failure line the history already holds, in whatever language it was written, was committed by a tick that
  # then failed to take its check off the list; it is not written a second time
  text = spec_paths.read_text(asset_note)
  _, fm_end = flip_gate.parse_frontmatter(text)
  recorded = set(_history_rows(text[fm_end:]))
  owed = [
      job[JobMarker.HISTORY] for job in owing
      if not recorded.intersection(note_explainers.history_fragments(
          HistoryEvent.COHERENCE_FAILED, doc = job[JobMarker.DOC], job_id = job[JobMarker.JOB_ID],
      ))
  ]

  # one History line per check that still has something to say, in one write and one commit; when every owed line
  # is already in the history the note is left as it is and only the list is brought up to date below
  if owed:
    body = text[fm_end:]
    for line in owed:
      body = history_journal.append(body, line, today_str, repo = repo_root)
    write_and_commit_note(
        asset_note.parent, asset_note, note_explainers.heal_note_text(asset_note, text[:fm_end] + body),
        original_text = text,
        subject = f"{_PROMOTE_AUTHOR_NAME}: coherence checks landed on {asset_note.parent.name}",
    )

  # the lines are in the note's history for good, so the checks that owed them leave the list
  spec_job_markers.update(repo_root, asset_note, {
      JobMarker.COHERENCE_JOBS: [
          job for index, job in enumerate(jobs) if index not in retired and JobMarker.HISTORY not in job
      ],
  })
  return landed


def set_fm_json(fm_text: str, key: str, value: dict | list) -> str:
  """
  Set or insert `key: <compact-json>` in a frontmatter block.

  Mirrors `flip_gate.set_bool`'s shape for a JSON-valued (rather than boolean-valued) key —
  the hand-rolled frontmatter parser treats a value as an opaque string, so a one-line JSON
  value round-trips through it without any schema change. Reused by `coordinator_dispatch.py`
  for its own worker-internal dict-valued markers.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to set.
    value: The dict or list to serialize as the key's compact-JSON value.

  Returns:
    The updated frontmatter text.
  """
  literal = json.dumps(value)
  pat = _compile_key_pattern(key)
  if pat.search(fm_text):
    return pat.sub(lambda _m: f"{key}: {literal}", fm_text, count = 1)
  return spec_frontmatter.insert_before_close(fm_text, f"{key}: {literal}\n")


def del_fm_key(fm_text: str, key: str) -> str:
  """
  Remove a frontmatter key's line, if present.

  Mirrors `set_fm_json`'s regex approach for the opposite operation — deleting rather than
  writing a key. A no-op (returns `fm_text` unchanged) when the key is absent.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to remove.

  Returns:
    The updated frontmatter text.
  """
  pat = re.compile(_FM_KEY_RE_TEMPLATE.format(key = re.escape(key)) + _TRAILING_NEWLINE_RE)
  return pat.sub("", fm_text, count = 1)


def read_fm_list(fm_text: str, key: str) -> list[str]:
  """
  Read a YAML list-typed frontmatter value.

  Recognizes both the block form — indented or not, never reading the closing fence as an
  item — and the inline form (`key: ["a", "b"]`), returning members unquoted.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences), or any
      larger text this block leads (the trailing body is never scanned).
    key: The list-typed frontmatter key (e.g. `spec_targets`).

  Returns:
    The list's string members, in file order; empty when the key is an inline `[]`, absent, or
    written with no members.
  """
  return spec_frontmatter.read_list(fm_text, key)


def write_fm_list(fm_text: str, key: str, values: list[str]) -> str:
  """
  Set or insert a `key:` YAML list value in a frontmatter block.

  Reused by `note_ops.note_set_key` (its `_Kind.LIST` writer). Members are written as YAML
  scalars, quoted only when YAML would otherwise read them differently. An existing inline
  (empty or populated) or block list — indented or not — is replaced in place, a missing key is
  inserted before the closing fence, and an empty list is written as `key: []`.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The list-typed frontmatter key.
    values: Replacement member list.

  Returns:
    The updated frontmatter text.
  """
  return spec_frontmatter.write_list(fm_text, key, values)


def _compile_key_pattern(key: str) -> re.Pattern[str]:
  """
  Compile `_FM_KEY_RE_TEMPLATE` for one frontmatter key.

  Args:
    key: The frontmatter key to match a same-line value for.

  Returns:
    The compiled single-line `^key\\s*:.*$` pattern.
  """
  return re.compile(_FM_KEY_RE_TEMPLATE.format(key = re.escape(key)))


def _run_note_check(asset_note: Path) -> list[dict]:
  """
  Run `note-check` on `asset_note` via the sibling CLI, for folding into this tick's own result.

  Best-effort: a missing or broken CLI degrades to reporting no violations rather than failing
  the tick, since the structural check is advisory (the coordinator repairs what it finds, this
  worker never does).

  Args:
    asset_note: The status folder-note path to check.

  Returns:
    The `note-check` violations list; empty when the note is structurally clean, or the CLI
    itself could not be resolved, run, or parsed, or answered with something other than a JSON object.
  """

  # Decision: subprocess the sibling CLI, not an in-process import — `note_ops.py` already imports
  # this module (for `set_fm_json` / `write_fm_list`), so importing it here would be circular

  # the sibling CLI that hosts the `note-check` verb
  cli = _BIN / _SPEC_CLI_NAME

  # guard: sibling CLI missing from this checkout — degrade to a skip, never fail the tick
  if not cli.is_file():
    return []
  try:
    proc = subprocess.run(
        [sys.executable, str(cli), _NOTE_CHECK_SUBVERB, str(asset_note)],
        capture_output = True, text = True, check = False, encoding = "utf-8", errors = _DECODE_ERRORS,
    )
  # waiver: best-effort follow-up — a broken subprocess must degrade to "nothing to report",
  # never abort the tick that already handled the active-job polling pass above
  except OSError:
    return []
  try:
    result = json.loads(proc.stdout)
  except json.JSONDecodeError:
    return []

  # guard: an answer that is not a JSON object names no violations either
  if not isinstance(result, dict):
    return []
  return result.get(_VIOLATIONS_KEY, [])


def _read_response_outcome(repo_root: Path, expert: str, job_id: str) -> str | None:
  """
  Read the outcome a finished job's response reports.

  Args:
    repo_root: The repository root holding the job store.
    expert: The expert the job ran under.
    job_id: The job's id.

  Returns:
    The response's non-empty `outcome` string, or None when the bundle holds no readable response naming one.
  """

  # Decision: chose reading core's job bundle directly, not `collect-job` — `collect-job` withholds a DEAD or
  # CANCELLED job's response, which `last_job` records; revisit when core's `collect-job` returns the response for
  # every status.

  # the finished job's response; a missing or unreadable one names no outcome
  try:
    response = json.loads((repo_root / _JOBS_BASE / expert / job_id / _RESPONSE_FILE).read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    # `ValueError` covers both a JSON syntax error and bytes that are not UTF-8 text
    return None

  # only a JSON object naming a non-empty outcome reports one
  outcome = response.get(_RESPONSE_OUTCOME) if isinstance(response, dict) else None
  return outcome.strip() if isinstance(outcome, str) and outcome.strip() else None


def apply_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Apply an active expert job's terminal bundle marker to the asset.

  Every marker retires the tracked job and records it as the asset's last job, a `DONE` retired on a cancelled
  asset and a `DONE` whose delivery was refused recording it as unlanded; every marker except a
  `DONE` on a cancelled asset raises a `job-done` wake for the coordinator to act on. `DONE` lands the
  job's `result/` into the asset folder and leaves the folder-note untouched when the result was
  delivered or the job left nothing to land; a `DONE` cascade fold, whose `target_doc` lies inside the folder of
  one of the note's declared `spec_targets` assets, is neither landed nor halted: it is retired with `last_job`
  recorded without `unlanded`, the `job-done` wake is raised, and its bundle is left for the coordinator's
  `land-result --target` landing. On an asset whose note carries `spec_cancelled: true` a `DONE` is retired
  with no landing and no wake, and recorded as unlanded and retired by the cancel. `CANCELLED` leaves everything
  untouched but the job's own records. `DEAD`, and a `DONE` whose delivery was refused, instead
  halt the asset, appending a persistent `[!failure]` callout to `# Gates` that stays until an
  operator resolves it by hand, and leave the job bundle in place for diagnostics; a refused
  delivery is additionally reported as a `plugin_error` warning to the core error ledger,
  fire-and-forget. Deciding what happens next on the asset — dispatching a replacement job,
  reacting to the halt — is `spec.coordinator`'s call; this pass only records the terminal outcome. The tracked
  job is retired, the wake raised and `last_job` recorded only once the halt is committed, so a failed commit
  leaves the job tracked, with the folder-note put back to its text when putting it back succeeds.

  Guarantees:
    - On a `CANCELLED` marker, and on a `DONE` marker whose result was delivered or was
      legitimately empty, the job bundle is retired, freeing its dedup key for re-dispatch while
      its files stay on disk; a retirement that fails never raises and leaves the bundle unretired.
    - On a `DEAD` marker, on a `DONE` marker whose delivery was refused, and on a `DONE` marker that is a cascade
      fold, the job bundle is left unretired, kept on disk for diagnostics or for the coordinator's landing.
    - A `DONE` job whose `target_doc` lies outside the asset folder but inside the folder of one of the note's
      declared `spec_targets` assets is neither landed nor halted: its `job-done` wake is raised, and the pass
      reports `job-done`. Any other `target_doc` outside the asset folder is a refused delivery when the job's
      response declares files, and an empty ending when it declares none.
    - The asset is halted with a persistent failure callout in `# Gates` exactly when the job
      ended `DEAD` or ended `DONE` with its delivery refused; every other terminal marker leaves
      the folder-note untouched.
    - A `DONE` job on a note carrying `spec_cancelled: true` is retired without landing its result and
      without raising a wake, and the pass reports `job-cancelled`.
    - Every retirement of the tracked job records `last_job` with `checkbox`, `expert`, `job_id`, `outcome` and
      `marker`: `outcome` is the outcome the job's `response.json` reports, or the lowercased marker when the
      bundle holds no response naming one; `marker` is always the lowercased marker. A `DONE` whose landing was
      refused records `last_job` with `unlanded: true`; a `DONE` retired on a cancelled asset records it with
      `unlanded: true` and `retired_by_cancel: true`; a cascade fold records it with neither.
    - The tracked job is retired, its `job-done` wake raised and `last_job` recorded only after the halt of a `DEAD`
      or refused-landing job is committed; when that commit fails, the error propagates and the job stays tracked,
      so the next tick retries. The folder-note is back to the text it had when the commit fails with an `OSError`
      or a `subprocess.CalledProcessError` and putting the note back succeeds; otherwise the commit's own error
      still propagates and the note is left holding the uncommitted halt text.

  Args:
    asset_note: The status folder-note path.
    text: The folder-note's full text as last read from disk.
    fm_end: Index just past the frontmatter's closing `---` fence in `text`.
    body: The folder-note's body text (post-frontmatter).
    asset_dir: The asset folder the marker is being applied to.
    repo_root: The repository root holding the job-marker sidecar.
    marker: The terminal marker found in the job's bundle directory (`"DONE"` / `"DEAD"` /
      `"CANCELLED"`).
    job_info: The tracked active-job marker (`checkbox` / `expert` / `job_id`).
    today_str: ISO date string pinned into the halt callout.

  Returns:
    A result dict naming the applied `TickAction` plus the job's `checkbox` and `job_id`. The
    action is the asset-halted one whenever the asset was halted, the job-cancelled one for
    `CANCELLED` and for a `DONE` retired on a cancelled asset, and the job-done one otherwise.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved while journaling a halt.
    OSError: If the halted folder-note cannot be written or its commit raises it, in which case the job stays
      tracked and the folder-note is put back when that succeeds; or if the job-marker sidecar cannot be written,
      in which case the job stays tracked and a halt already committed stands.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when staging or committing the halted
      folder-note exits non-zero; the job stays tracked, and the folder-note is put back when that succeeds,
      otherwise it keeps the uncommitted halt text while this commit error still propagates.
  """

  # Contract:
  # The job bundle is retired, freeing its dedup key so the same checkbox can be re-dispatched,
  # on a `CANCELLED` marker and on a `DONE` marker whose result was delivered or was legitimately
  # empty; its files stay on disk for the coordinator's job-done wake to read. The retirement is best effort: a
  # failure to retire the bundle never raises and leaves the bundle unretired. On a `DEAD` marker,
  # on a `DONE` marker whose delivery was refused, and on a `DONE` marker that is a cascade fold,
  # the bundle is deliberately left unretired: kept for diagnostics, or for the coordinator's landing.

  # Contract:
  # A `DONE` job whose `target_doc` lies outside the asset folder but inside the folder of one of the note's
  # declared `spec_targets` assets is a cascade fold: it is neither landed nor halted. The tracked job is retired,
  # a `job-done` wake is raised for the coordinator, which lands the document into the target asset and retires
  # the bundle, and the pass reports `job-done`. Any other `target_doc` outside the asset folder is a refused
  # delivery when the job's response declares files, and an empty ending when it declares none.

  # Contract:
  # The asset is halted with a persistent failure callout in its `# Gates` section exactly when
  # the job ended `DEAD` or ended `DONE` with its delivery refused; every other terminal marker,
  # a cascade fold included, leaves the asset's folder-note untouched.

  # Contract:
  # A `DONE` job on a note carrying `spec_cancelled: true` is retired without landing its result and without
  # raising a wake, and the pass reports `job-cancelled`.

  # Contract:
  # Every retirement of the tracked job records `last_job` with `checkbox`, `expert`, `job_id`, `outcome` and
  # `marker`. `outcome` is the outcome the job's `response.json` reports, falling back to the lowercased marker when
  # the bundle holds no response naming one; `marker` is always the lowercased marker. A `DONE` whose landing was
  # refused records `last_job` with `unlanded: true`; a `DONE` retired on a cancelled asset records it with
  # `unlanded: true` and `retired_by_cancel: true`; a cascade fold records it with neither.

  # Contract:
  # The tracked job is retired, its `job-done` wake raised and `last_job` recorded only after the halt of a `DEAD`
  # or refused-landing job is committed. When that commit fails, the error propagates and the job stays tracked,
  # so the next tick retries. The folder-note is back to the text it had when the commit fails with an `OSError`
  # or a `subprocess.CalledProcessError` and putting the note back succeeds. Otherwise the commit's own error
  # still propagates and the note is left holding the uncommitted halt text.

  checkbox_label = job_info[JobMarker.CHECKBOX]
  job_id = job_info[JobMarker.JOB_ID]
  expert = job_info[JobMarker.EXPERT]

  # the retired job stays readable as the note's last job, so the coordinator's wake can find its response
  # its outcome is the one the job's response reports, the marker standing in when the job left none
  last_job = { JobMarker.CHECKBOX: checkbox_label, JobMarker.EXPERT: expert, JobMarker.JOB_ID: job_id,
               JobMarker.OUTCOME: _read_response_outcome(repo_root, expert, job_id) or marker.lower(),
               JobMarker.MARKER: marker.lower() }

  # Domain(spec.lifecycle):
  # # A cancelled asset takes no finished work
  # Work that finishes after its asset was cancelled belongs to nothing that is still going on. Its result is not
  # placed in the asset and nobody is woken to act on it; the job is only retired, so the cancelled asset stays
  # exactly as the cancellation left it. Such work is recorded as never landed, whatever outcome it reported, and as
  # withheld by the cancellation, so that taking the asset back can owe the work again. This holds for finished work
  # alone: a job that died is still reported.

  # a finished job on a cancelled asset is retired without its result and without a wake
  values, _end = flip_gate.parse_frontmatter(text)
  if marker == JOB_MARKER_DONE and flip_gate.is_true(values, Gate.SPEC_CANCELLED):
    spec_job_markers.update(
        repo_root, asset_note,
        {
            JobMarker.ACTIVE_JOB: None,
            JobMarker.LAST_JOB: spec_job_markers.mark_retired_by_cancel(spec_job_markers.mark_unlanded(last_job)),
        },
    )
    gate_dispatch.consume_stale_job(repo_root, expert, job_id)
    return {
        TickAction.ACTION: TickAction.JOB_CANCELLED, JobMarker.CHECKBOX: checkbox_label, JobMarker.JOB_ID: job_id,
    }

  # Domain(spec.lifecycle):
  # # A cascade fold is landed by the coordinator, not by the collector
  # A change folds its delta into documents that belong to other assets, its declared targets. The finished fold
  # is not placed by the collector of finished work, which only ever writes into the asset the job came from, and it
  # is not treated as a failure either: the job is recorded as finished, the coordinator is woken, and the
  # coordinator places the document in the target asset by naming that target itself, after which the landing
  # spends the job. A document meant for any other place outside the asset, inside the catalog or beyond it, is
  # still a failed delivery and halts the asset.

  # a cascade fold's document belongs to a target asset: the coordinator lands it and retires the bundle on the
  # wake raised here, so the tick neither lands it nor halts, and the record stays landed-pending, never unlanded
  if marker == JOB_MARKER_DONE and _is_cascade_fold(
      text, fm_end, asset_dir = asset_dir, repo_root = repo_root, expert = expert, job_id = job_id):
    spec_job_markers.update(
        repo_root, asset_note,
        { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE, JobMarker.LAST_JOB: last_job },
    )
    return { TickAction.ACTION: TickAction.JOB_DONE, JobMarker.CHECKBOX: checkbox_label, JobMarker.JOB_ID: job_id }

  # the clause a halt of this asset carries; stays None on every branch that leaves the note as it is
  halt_reason: str | None = None

  # a dead job, or a finished one whose result could not be placed, halts the asset; every other
  # ending leaves the note untouched
  if marker == JOB_MARKER_DONE:
    # the job's document and attachments arrive only through `result/`: put them in the asset
    # folder and commit them here, so the document the coordinator submits into review on the
    # `job-done` wake this same call raises is already tracked
    landing = _land_job_result(repo_root, asset_dir, expert, job_id)
    action = TickAction.JOB_DONE

    # a failed delivery leaves the work in the bundle, kept unretired for diagnostics, and halts
    # the asset on the collector's own reason; a delivered or empty one retires the bundle
    if landing.get(_LANDING_ACTION_KEY) == _LANDING_REFUSED:
      # the job's result never reached the asset, so its record says so whatever outcome the job reported
      last_job = spec_job_markers.mark_unlanded(last_job)
      action = TickAction.ASSET_HALTED
      halt_reason = HaltReason.LANDING_REFUSED.format(
          job_id = job_id, label = checkbox_label, reason = landing.get(_LANDING_REASON_KEY),
      )
      error_report.report_warning(
          repo_root, cause = PluginErrorCause.LANDING_REFUSED,
          incident = f"{_LANDING_INCIDENT_PREFIX}{expert}/{job_id}", detail = halt_reason,
      )
    else:
      # retire the bundle so its dedup key frees for a retry — same move the coordinator-job
      # branch already makes; the bundle's files stay on disk for the coordinator's wake to read
      gate_dispatch.consume_stale_job(repo_root, expert, job_id)
  elif marker == _JOB_MARKER_CANCELLED:
    # a cancelled bundle is equally spent — retire it so the checkbox can be re-dispatched
    action = TickAction.JOB_CANCELLED
    gate_dispatch.consume_stale_job(repo_root, expert, job_id)
  else:
    # marker == JOB_MARKER_DEAD — the bundle is left unretired beside the halt
    action = TickAction.ASSET_HALTED
    halt_reason = HaltReason.JOB_DIED.format(job_id = job_id, label = checkbox_label)

  # halt the asset via the shared text-core primitive, in this call's own single write+commit
  if halt_reason is not None:
    fm_text, body, _ = flip_gate.halt_asset_text(
        text[:fm_end], body, halt_reason, today = today_str, lang = note_explainers.lang_for_note(asset_note),
    )
    write_and_commit_note(
        asset_dir, asset_note, note_explainers.heal_note_text(asset_note, fm_text + body),
        original_text = text, subject = f"{_PROMOTE_AUTHOR_NAME}: halt {asset_dir.name} — {halt_reason}",
    )

  # the job is over on every branch: retire the marker and raise the wake the coordinator's
  # `job-done` trigger reads; the postman sweep delivers it, so no note write has to carry it.
  # The retirement comes last, after the halt is committed: a halt that could not be committed
  # leaves the job tracked, so the next tick finds its marker again and retries
  spec_job_markers.update(
      repo_root, asset_note,
      {
          JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE,
          JobMarker.LAST_JOB: last_job,
      },
  )

  # the applied marker's action plus the job identity it acted on, for every branch above
  return {
      TickAction.ACTION: action,
      JobMarker.CHECKBOX: checkbox_label,
      JobMarker.JOB_ID: job_id,
  }


def coordinator_job_dead_line(trigger: str, job_id: str, *, lang: str) -> str:
  """
  Build the `# History` WARNING text for a dead coordinator-job bundle.

  Single owner of this line's exact wording, so concurrent writers append identical text
  regardless of which one reaches the dead marker first. The day group and bullet are the
  shared history verb's, not this builder's.

  Args:
    trigger: The `CoordinatorJobKey.TRIGGER` value recorded on the dead job.
    job_id: The dead job's id.
    lang: The note's authoring language for the line's narrative tail.

  Returns:
    The `WARNING: ...` line text, without bullet or date.
  """
  # the localized narrative tail of the History line, in the note's authoring language
  return note_explainers.history_line_for_lang(lang, HistoryEvent.JOB_DEAD,
                                               job_id = job_id, trigger = trigger)


def is_dead_job_recorded(body: str, trigger: str, job_id: str) -> bool:
  """
  Tell whether a note's history already carries the dead-job warning line of one coordinator job.

  Guarantees:
    - Only a row of the note's `# History` section counts, the section ending at the next top-level heading and its
      day headings belonging to it; the same text outside that section never counts, and neither does the line of
      another job. The line is recognised in any language the plugin writes in.

  Args:
    body: The note's body text.
    trigger: The trigger recorded on the dead job.
    job_id: The dead job's id.

  Returns:
    True when some row of the note's `# History` section, its bullet and surrounding blanks set aside, equals that
    job's warning line in any language the plugin writes in; the line of another job never counts, and neither
    does the same text anywhere outside that section or a row inside a code fence.
  """

  # Contract:
  # Only a row of the note's `# History` section counts, the section ending at the next top-level heading and its
  # day headings belonging to it. The same text anywhere else in the note never counts, and neither does the line
  # of another job. The line is recognised in any language the plugin writes in, so a dead job's warning is
  # recorded once even when the note's language changed after it was written.

  # the line as every authoring language renders it, since the note's language may have changed since it was written
  variants = set(note_explainers.history_fragments(HistoryEvent.JOB_DEAD, job_id = job_id, trigger = trigger))
  return any(row in variants for row in _history_rows(body))


def _history_rows(body: str) -> list[str]:
  """
  List the rows of a note's `# History` section, each without its bullet and surrounding blanks.

  Args:
    body: The note's body text.

  Returns:
    The rows between the `# History` heading and the next top-level heading, in note order; the blank rows and the
    day headings inside the section are among them, a row inside a code fence is not. Empty when the note has no
    such section.
  """
  lines = body.splitlines()
  fenced = spec_frontmatter.fenced_lines(lines)
  rows: list[str] = []
  in_history = False

  # the section opens at its own heading and closes at the next top-level one, the day headings inside it being
  # part of it; a row inside a code fence is neither a heading nor a record
  for index, row in enumerate(lines):
    if fenced[index]:
      continue
    if row.startswith(_H1_PREFIX):
      in_history = row.rstrip() == Section.HISTORY
    elif in_history:
      rows.append(row.strip().lstrip("-*").strip())
  return rows


def _coherence_line_fields(doc: str, job_id: str, dropped: int | None) -> tuple[str, dict[str, str]]:
  """
  Name the History event of a coherence check that landed, and the fields of its line.

  Args:
    doc: The checked document.
    job_id: The check's job id.
    dropped: The number of neighbours left out over the size budget, or `None` when none was.

  Returns:
    The event key, the plain one or the one that also names the dropped neighbours, and the line's fields, the
    conflict count standing as `COHERENCE_COUNT_SLOT`.
  """
  # every line names the job, so it identifies one check; the count is filled in by whoever comes to know it
  fields = { _LINE_DOC: doc, _LINE_JOB: job_id, _LINE_COUNT: COHERENCE_COUNT_SLOT }

  # a check that left neighbours out names how many
  if dropped:
    return HistoryEvent.COHERENCE_CHECKED_TRIMMED, { **fields, _LINE_DROPPED: str(dropped) }
  return HistoryEvent.COHERENCE_CHECKED, fields


def recorded_coherence_count(body: str, doc: str, job_id: str, dropped: int | None) -> int | None:
  """
  Read the conflict count off a note whose history already carries the line of one landed coherence check.

  Guarantees:
    - Only a row of the note's `# History` section counts, and only as this check's own line: the document, the
      job and the number of dropped neighbours all match, with any count and in any language the plugin writes in.
    - The line of another job or another document never counts, and neither does the same text outside the
      `# History` section.

  Args:
    body: The note's body text.
    doc: The checked document.
    job_id: The check's job id.
    dropped: The number of neighbours the check left out over the size budget, or `None` when none was.

  Returns:
    The count the line states, or `None` when no row of the note's `# History` section is that check's line.
  """

  # Contract:
  # Only a row of the note's `# History` section counts, and only as this check's own line: the document, the job
  # and the number of dropped neighbours all match, with any count and in any language the plugin writes in.
  # The line of another job or another document never counts, and neither does the same text outside that section.

  # the line as every authoring language renders it, the count left open, since only the apply came to know it
  key, fields = _coherence_line_fields(doc, job_id, dropped)
  patterns = [
      re.compile(r"(\d+)".join(re.escape(part) for part in variant.split(COHERENCE_COUNT_SLOT)))
      for variant in note_explainers.history_fragments(key, **fields)
  ]

  # the first row that is this check's line gives its count
  for row in _history_rows(body):
    for pattern in patterns:
      if (match := pattern.fullmatch(row)) is not None:
        return int(match.group(1))
  return None


def is_tick_pending(asset_note: Path, repo_root: Path, trigger: str) -> bool:
  """
  Tell whether a retiring coordinator job leaves a ticked launch row standing that nothing will enact.

  Args:
    asset_note: The status folder-note path.
    repo_root: The repository root holding the job-marker sidecar.
    trigger: The wake-trigger token of the coordinator job being retired.

  Returns:
    True when the note's current `# Gates` section holds a ticked launch row, no wake other than a `declined` one
    is raised (the `tick-pending` wake replaces a raised `declined`), no launch job is in flight, the note is
    neither halted nor cancelled, and the job was not itself woken by such a row.

  Raises:
    OSError: If the job-marker sidecar or the folder-note cannot be read. Nothing is written.
  """

  # Domain(spec.lifecycle):
  # # A ticked launch row outlives no coordinator job
  # A ticked launch row is the operator's order to start a step, and only the coordinator carries it out. A
  # coordinator job woken for another reason can end without enacting the order, and then nothing would wake the
  # coordinator again. So when its job is let go, the note as that job left it is read: a launch row still ticked
  # there wakes the coordinator once more. A wake that was turned away while the job ran is replaced by this one:
  # both make the coordinator read the asset afresh and both end with whatever it does next, but only this one
  # reaches the coordinator without a further change to the note. No such wake is raised while the wake of a
  # finished launch step already waits, while a launch job is still running, or on a halted or cancelled asset,
  # and a job that was itself such a wake never orders another, so an order the coordinator cannot carry out does
  # not loop.

  # a wake raised by this very rule never orders another
  if trigger == CoordinatorTrigger.TICK_PENDING:
    return False

  # the job markers read fresh, since the stage-lag step may have just raised its own wake
  markers = spec_job_markers.read(repo_root, asset_note)

  # a raised job-done wake already brings the coordinator back, and a running launch job wakes it when it ends; a
  # declined wake is replaced, since nothing delivers it without a further commit
  if markers.get(JobMarker.PENDING_WAKE) not in _REPLACEABLE_WAKES or markers.get(JobMarker.ACTIVE_JOB) is not None:
    return False

  # the note as the retired job left it, re-read since the stage-lag step may have just rewritten it
  text = spec_paths.read_text(asset_note)
  frontmatter, fm_end = flip_gate.parse_frontmatter(text)

  # a halted or cancelled asset launches nothing
  if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED) or flip_gate.is_true(frontmatter, Gate.SPEC_CANCELLED):
    return False

  # the body's lines, where the `# Gates` section is looked for
  lines = text[fm_end:].split("\n")

  # guard: a note without a `# Gates` section holds no launch row
  if (span := review_rows.find_gates_span(lines)) is None:
    return False

  # any ticked launch row still standing is an order nobody enacted
  return any(row.ticked for row in review_rows.parse_gate_rows(lines[span[0]:span[1]]))


def _apply_coordinator_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Sweep a finished `coordinator_job` marker off the asset.

  Retires the coordinator's own tracked job — never a ladder expert job, so a `DEAD` bundle here
  never halts the asset. `DEAD` instead appends a `# History` WARNING line, unless the note's `# History`
  section already carries that line for that job in any language the plugin writes in, in which case nothing is
  written or committed;
  `DONE` / `CANCELLED` free the bundle's dedup key for the coordinator's next dispatch. A `DONE` job that left an
  approved document at `draft` additionally raises a stage-lag wake or warning for that document; the retry of the
  same job after a failed marker clear neither wakes that lag again nor warns.
  Any wake flag raised while the swept job ran survives for the next genuine wake to redeem, unless a fresh
  stage lag replaces it with the declined-wake flag. A job that leaves a ticked launch row standing raises the
  `tick-pending` wake flag in the same sidecar write that clears the marker, replacing a raised `declined` wake
  flag, unless a `job-done` wake is already raised, a launch job is in flight, the note is halted or cancelled, or
  the swept job was itself woken by `tick-pending`.
  The `coordinator_job` marker is cleared last, once the
  `DEAD` warning line and, for a `DONE` job, the stage-lag step are committed, so a failed commit of either
  leaves the job tracked, with the folder-note put back to its text when putting it back succeeds.

  Args:
    asset_note: The status folder-note path.
    text: The folder-note's full text as last read from disk.
    fm_end: Index just past the frontmatter's closing `---` fence in `text`.
    body: The folder-note's body text (post-frontmatter).
    asset_dir: The asset folder the commit's repo root is resolved from.
    repo_root: The repository root holding the job-marker sidecar and `.experts/.jobs/`.
    marker: The terminal marker found in the job's bundle directory (`"DONE"` / `"DEAD"` /
      `"CANCELLED"`).
    job_info: The tracked coordinator-job marker (`trigger` / `expert` / `job_id`).
    today_str: ISO date string pinned into the History line.

  Returns:
    A result dict naming the applied `TickAction` plus the job's `trigger` and `job_id`, and a
    `stage_lag` list of the document basenames the stage-lag step acted on when there were any.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot be resolved. It
      covers the history append of the `DEAD` warning line and the history append of a stage-lag warning in the
      stage-lag step of a `DONE` job. Nothing of that write has reached the note, no wake flag is raised and the
      stage-lag record is unchanged; the marker stays set, so the job stays tracked and the retry tries again.
    OSError: Covers the note write and the commit of the `DEAD` warning line, the note write, the commit, the
      wake-flag write and the stage-lag record write of the stage-lag step of a `DONE` job, the reads of the
      sidecar and the note that decide the `tick-pending` wake flag, and the final write that clears the
      `coordinator_job` marker and raises that flag. The marker stays set in every case, so the job stays tracked,
      and a failed final write raises no `tick-pending` flag either. A failed note
      write commits nothing. A failed commit puts the note back to its previous text when that succeeds, otherwise
      the note keeps the uncommitted text, and no wake flag is raised and the stage-lag record is unchanged. After
      a committed stage-lag note a failed wake-flag write leaves no flag raised and the record unchanged, and a
      failed record write leaves the flag raised and the record unchanged. A committed warning line, whether the
      `DEAD` one or a stage-lag one, stays committed when the stage-lag record write or the final clear fails, and
      the retry writes no second line for it.
    subprocess.CalledProcessError: Covers the commit of the `DEAD` warning line and the commit of the stage-lag
      note of a `DONE` job, when it exits non-zero. The marker stays set, so the job stays tracked; the note is put
      back to its previous text when that succeeds, otherwise it keeps the uncommitted text while this commit error
      still propagates. After a failed stage-lag commit no wake flag is raised and the stage-lag record is
      unchanged.
  """

  # Domain(spec.lifecycle):
  # # The coordinator's own wake job is retired, never escalated
  # The job the coordinator runs to wake over an asset is not a step of the asset's promotion
  # ladder, so its death never halts the asset: it is recorded as a warning line in the asset's
  # history and nothing more. A coordinator job that finished or was cancelled is simply retired,
  # which frees its deduplication key so the coordinator's next dispatch for the asset is not
  # mistaken for a repeat of the finished one. A job that finished is also the moment to look for
  # a stage lag: an approved document the job left still at the draft stage. The job is let go only
  # after everything its ending owes the asset is recorded: the warning about a job that died and,
  # for a job that finished, the stage-lag step. If recording fails, the job stays tracked and the
  # next pass tries again. The failed record is taken back by putting the note back as it was, but putting it
  # back can fail too: then the note keeps the unrecorded text, the failure is reported, and the next pass reads
  # that text as the note's own. A warning already in the asset's history for that very job, in any language the
  # plugin writes in, is not recorded a second time: the retry only lets the job go. Only the history itself is
  # looked at: another job's warning never counts, and neither do the same words standing anywhere else in the note.
  # However the job ended, a launch row its asset still holds ticked when it is let go wakes the coordinator once
  # more, raised together with letting the job go, so the job is never let go without the wake it owes. It takes
  # the place of a wake turned away while the job ran. No such wake is owed while the wake of a finished launch
  # step already waits, while a launch job is still running, on a halted or cancelled asset, or when the job was
  # itself such a wake.

  # the job's identity, read before the coordinator-job marker it came from is cleared
  trigger = job_info[JobMarker.TRIGGER]
  job_id = job_info[JobMarker.JOB_ID]

  # every marker clears the coordinator-job marker (below, once its own duty is done); only DEAD owes
  # the note a WARNING line, and only DONE / CANCELLED owe the bundle its dedup retirement
  if marker == JOB_MARKER_DEAD:
    # one language resolution serves the WARNING line and the explainer heal (the resolver
    # walks to the settings root and reads config)
    note_lang = note_explainers.lang_for_note(asset_note)
    line = coordinator_job_dead_line(trigger, job_id, lang = note_lang)

    # a note that already carries this job's line had it committed by a pass that then failed to clear
    # the marker; that pass's retry writes nothing more and only clears the marker below
    if not is_dead_job_recorded(body, trigger, job_id):
      write_and_commit_note(
          asset_dir, asset_note,
          text[:fm_end] + note_explainers.ensure_explainers(
              history_journal.append(body, line, today_str, repo = repo_root), note_lang,
          ),
          original_text = text,
          subject = f"{_PROMOTE_AUTHOR_NAME}: coordinator job {job_id} ({trigger}) died on {asset_dir.name}",
      )
    action = TickAction.COORDINATOR_JOB_DEAD
  else:
    # marker in (JOB_MARKER_DONE, _JOB_MARKER_CANCELLED) — retire the bundle so its dedup key
    # frees for the coordinator's next dispatch; nothing here reaches the note
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
    action = TickAction.COORDINATOR_JOB_CONSUMED

  # a finished job that left an approved document at `draft` wakes the coordinator once, then warns
  lagging = (
      update_stage_lag(asset_note, asset_dir, repo_root, today_str, job_id = job_id)
      if marker == JOB_MARKER_DONE else []
  )

  # the marker is cleared last, once every commit of the job's retirement is in: a WARNING line or a
  # stage-lag note that could not be committed leaves the job tracked, so the next tick finds its
  # finished bundle again and retries. A ticked launch row the job left standing raises its wake in the
  # same write, so the job is never let go without the wake it owes
  changes: dict[str, str | None] = { JobMarker.COORDINATOR_JOB: None }
  if is_tick_pending(asset_note, repo_root, trigger):
    changes[JobMarker.PENDING_WAKE] = JobMarker.TICK_PENDING
  spec_job_markers.update(repo_root, asset_note, changes)

  # the applied marker's action plus the job identity it acted on, for every branch above
  result = {
      TickAction.ACTION: action,
      JobMarker.TRIGGER: trigger,
      JobMarker.JOB_ID: job_id,
  }
  if lagging:
    result[_STAGE_LAG_RESULT] = lagging
  return result


def _find_all_lagging_docs(asset_note: Path, asset_dir: Path) -> dict[str, str]:
  """
  Find the documents of an asset whose approval never reached their stage.

  Args:
    asset_note: The asset's status folder-note.
    asset_dir: The asset folder holding its documents.

  Returns:
    A mapping of `<basename>:<review_result>` to the document basename, one entry per lagging document.
  """
  # the note's own ladder decides which documents count
  basenames = ( LevelDoc.BASENAMES
                if flip_gate.parse_frontmatter(spec_paths.read_text(asset_note))[0].get(SpecKey.ROLE) in LEVEL_ROLES
                else None )

  # each ladder document whose approval never reached its stage, keyed by its basename and verdict
  lagging: dict[str, str] = {}
  for name in sorted(os.listdir(asset_dir)):
    doc = asset_dir / name
    if spec_doc_types.is_ladder_document(doc, basenames) and set_stage.is_stage_lagging(doc):
      lagging[stage_lag_fingerprint(doc)] = name
  return lagging


def stage_lag_fingerprint(doc: Path) -> str:
  """
  Name the stage lag of one document by its basename and its current verdict.

  Args:
    doc: The document whose lag is named.

  Returns:
    The `<basename>:<review_result>` fingerprint the stage-lag record is keyed by.
  """
  verdict = spec_frontmatter.parse(spec_paths.read_text(doc))[0].get(SpecKey.REVIEW_RESULT, "")
  return f"{doc.name}:{verdict}"


def is_stage_lag_unraised(doc: Path, raised: Mapping[str, str]) -> bool:
  """
  Check whether a document lags its approval with no wake or warning on record for that lag yet.

  Args:
    doc: The document to check.
    raised: The asset's stage-lag record.

  Returns:
    True when the document lags and the record holds nothing for its current fingerprint.
  """
  return set_stage.is_stage_lagging(doc) and stage_lag_fingerprint(doc) not in raised


def record_stage_lag_wake(repo_root: Path, asset_note: Path, docs: Iterable[Path]) -> None:
  """
  Record the lags of the given documents as woken, each with where its episode begins in the note's history.

  Lags with a wake or warning already on record are left as they are.

  Args:
    repo_root: The repository root holding the stage-lag sidecar.
    asset_note: The asset's status folder-note the record belongs to.
    docs: The documents a wake has just been dispatched over.

  Raises:
    OSError: If the asset note cannot be read, or the stage-lag sidecar cannot be read or written.
  """
  # the lags not yet on record among these documents, each now spent on this wake
  raised = spec_job_markers.read_stage_lag(repo_root, asset_note)
  woken = {
      stage_lag_fingerprint(doc): _LAG_WOKEN for doc in docs if doc.is_file() and is_stage_lag_unraised(doc, raised)
  }

  # guard: every lag here is already on record, or none of these documents lags
  if not woken:
    return

  # each lag woken here opens an episode, marked by the warning lines the history carried before it
  body = spec_paths.read_text(asset_note)
  episodes = { f"{fingerprint}{_LAG_EPISODE_SUFFIX}": str(_count_lag_warnings(body, fingerprint))
               for fingerprint in woken }
  spec_job_markers.write_stage_lag(repo_root, asset_note, { **raised, **woken, **episodes })


def _count_lag_warnings(body: str, fingerprint: str) -> int:
  """
  Count the rows of a note's `# History` section that are the warning of one stage lag.

  Args:
    body: The folder-note's text.
    fingerprint: The `<basename>:<review_result>` fingerprint of the lag.

  Returns:
    The number of history rows warning of that lag, for the same document and verdict, in any language the plugin
    writes in.
  """
  # the warning of this lag as every language the plugin writes in words it
  name, _sep, verdict = fingerprint.partition(":")
  variants = set(note_explainers.history_fragments(HistoryEvent.STAGE_LAG, doc = name, review_result = verdict))
  return sum(1 for row in _history_rows(body) if row in variants)


def _read_lag_episode(raised: Mapping[str, str], fingerprint: str) -> int:
  """
  Read how many warning rows of a lag the history carried when the lag's episode began.

  Args:
    raised: The asset's stage-lag record.
    fingerprint: The `<basename>:<review_result>` fingerprint of the lag.

  Returns:
    The count the record holds for the lag; 0 when the record holds no mark for it or the mark is not a number.
  """
  # a record written before episodes were marked, or a mangled mark, reads as an episode that began with no line
  mark = raised.get(f"{fingerprint}{_LAG_EPISODE_SUFFIX}", "")
  return int(mark) if mark.isdigit() else 0


def update_stage_lag(asset_note: Path, asset_dir: Path, repo_root: Path, today_str: str, *,
                     job_id: str = "") -> list[str]:
  """
  Wake the coordinator once over documents left lagging by a finished job, then warn once.

  The first finish over a lagging document wakes the coordinator once, with the document's verdict re-read as a
  transition. A finish of another job over the same document and verdict, or a pass that names no job, records one
  `# History` warning and wakes nobody. A pass for the job whose finish already woke a lag does nothing for that
  lag. Later finishes do nothing.

  Guarantees:
    - When the call has new text for the note, nothing durable is recorded before that text is committed; when
      the commit fails the error propagates, no wake flag is raised and the stage-lag record is unchanged. The
      note is back to the text it had, so the retry acts on the same lags exactly once; when putting it back
      fails too, the commit's own error still propagates and the note keeps the uncommitted text, which the retry
      reads as the note's own.
    - A lag's episode begins when the lag is recorded as woken; the stage-lag record then also keeps how many
      warning lines of that lag, for the same document and verdict and written in any language the plugin writes
      in, the `# History` section already carried at that moment.
    - Within one episode the stage-lag warning line is written at most once: when the history has gained such a
      line since the episode began, because an earlier pass of this episode committed it and then failed to record
      the lag as warned, the pass writes no line and only records the lag as warned. When the pass then has
      nothing at all to change in the note, it makes no commit and only brings the stage-lag record up to date.
    - A warning line that was already there when the episode began belongs to an earlier episode and does not
      count, so a lag that ended and came back with the same document and verdict gets its own warning.
    - A record that carries no such mark for a woken lag, written before episodes were marked, reads as an episode
      that began with no line, so any such line in the history counts.
    - The count of finishes over a lag is idempotent per job: the stage-lag record keeps the id of the job whose
      pass woke the lag, and a later pass that names the same job id, met again because an earlier pass failed to
      let it go, is not a second finish. It neither wakes again nor writes the warning, and the lag stays recorded
      as woken with the marks of its episode. Only a finish of a different job, or a pass that names no job, over a
      woken lag counts as the second finish and writes the warning.

  Notes:
    - Commits the note when the pass changes its text, so the coordinator watch sees the change; a pass with
      nothing to change in the note makes no commit, as when every warning is already in the history since its
      episode began and nothing is freshly woken.
    - Updates the asset's stage-lag record on every call that completes, dropping lags that are no longer
      present; a call whose commit fails leaves the record unchanged.

  Args:
    asset_note: The asset's status folder-note.
    asset_dir: The asset folder holding its documents.
    repo_root: The repository root holding the stage-lag sidecar.
    today_str: ISO date string pinned into the History line.
    job_id: The id of the finished coordinator job this pass runs for; empty when the pass names no job.

  Returns:
    The basenames of the documents of every fresh lag and every repeated lag the call handled, fresh ones first,
    including a repeated lag whose warning line was already in the history since its episode began and was only
    recorded as warned; a lag that the finish of the named job already woke is not among them. Empty when no lag
    was fresh or repeated.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved while appending the warning line of a repeated lag whose line is not in the history since its
      episode began; nothing has been written, no wake flag is raised and the stage-lag record is unchanged.
    OSError: If the folder-note cannot be written or its commit raises it; the note is put back to its previous
      text when that succeeds, otherwise it keeps the uncommitted text, and no wake flag is raised and the
      stage-lag record is unchanged. Also if the stage-lag sidecar cannot be read, in which case nothing has been
      written, or if a sidecar write fails: with nothing owed, the record is unchanged;
      after the note's commit, or when the note needed none, the note stays as the pass left it, and when the wake
      flag cannot be written none is raised and the record is unchanged, and when the record cannot be written the
      flag is raised and the record is unchanged.
    subprocess.CalledProcessError: If committing the note exits non-zero; the note is put back when that
      succeeds, otherwise it keeps the uncommitted text, and no wake flag is raised and the stage-lag record is
      unchanged.
  """

  # Domain(spec.lifecycle):
  # # A stage lag wakes the coordinator once, then warns once
  # A stage lag is a document whose review verdict says approved while its stage is still draft: the
  # approval was recorded but the promotion never followed. A finished coordinator job that leaves
  # such a document behind has not completed its work, yet nothing else would wake the coordinator
  # again, so the lag itself must trigger the retry. A lag is identified by the document together
  # with its verdict, so a changed verdict is a new lag. The first finish over a lag wakes the
  # coordinator exactly once; the document's recorded verdict is reopened first, so the woken
  # coordinator reads the approval as a fresh transition and promotes the document. A second finish
  # over the same document and verdict means the wake did not cure the lag: one warning line goes
  # into the asset's history and nobody is woken, since a third attempt would loop without end.
  # A finish is counted once per coordinator job: the job whose finish woke a lag is remembered with it. The same
  # finished job can be met again, because a pass that woke the lag may fail before it lets the job go, and the next
  # pass then finds that job still tracked. That is the same finish, not a second one: it neither wakes the
  # coordinator again nor writes the warning, and the lag stays remembered as woken. Only the finish of a different
  # job over that lag shows that the wake did not cure it, and only that finish brings the warning.
  # Every later finish over that lag does nothing. A lag that is no longer present is forgotten,
  # so a document that lags again later with the same verdict starts over with a wake. The time from a lag's wake
  # until the lag is gone is one episode; a lag that returns is a new episode, woken again and, if the wake does
  # not cure it, warned about again.
  # Acting on a lag is remembered only once the change to the asset's note is safely recorded. The
  # reopened verdict, or the warning, is recorded first; only then is the wake raised and the lag
  # remembered as woken or warned. If recording fails, nothing is remembered and the note is put back as it was,
  # so the next pass meets the same lag in the same state and still wakes once, or warns once. Putting the note
  # back can fail too: then the note keeps the unrecorded text, the failure is reported, and the next pass reads
  # that text as the note's own.
  # The warning about a lag is written at most once per episode. When a lag is woken, the number of its warnings
  # already in the asset's history is remembered with it: the same document and the same verdict, whatever language
  # they were written in; nothing but the history itself counts. Before the warning is written, the history is
  # searched again. A warning that appeared since the wake was recorded by an earlier pass of this same episode,
  # which then failed to remember the lag as warned, so nothing is written again and the lag is only remembered
  # as warned. A warning that was already there at the wake belongs to an earlier episode and does not stop this
  # one's warning. A lag remembered as woken with no such number, remembered before episodes were told apart, is
  # treated as an episode that began with no warning in the history.

  # Contract:
  # When the call has new text for the note, nothing durable is recorded before that text is committed. When the
  # commit fails the error propagates, no wake flag is raised and the stage-lag record is unchanged. The note is
  # back to the text it had, so the retry acts on the same lags exactly once; when putting it back fails too, the
  # commit's own error still propagates and the note keeps the uncommitted text, which the retry reads as the
  # note's own.
  # A lag's episode begins when the lag is recorded as woken. The stage-lag record then also keeps how many warning
  # lines of that lag, for the same document and verdict and written in any language the plugin writes in, the
  # `# History` section already carried at that moment.
  # Within one episode the stage-lag warning line is written at most once: when the history has gained such a line
  # since the episode began, because an earlier pass of this episode committed it and then failed to record the lag
  # as warned, the pass writes no line and only records the lag as warned. When the pass then has nothing at all to
  # change in the note, it makes no commit and only brings the stage-lag record up to date.
  # A warning line that was already there when the episode began belongs to an earlier episode and does not count,
  # so a lag that ended and came back with the same document and verdict gets its own warning.
  # A record that carries no such mark for a woken lag, written before episodes were marked, reads as an episode that
  # began with no line, so any such line in the history counts.
  # The count of finishes over a lag is idempotent per job. When a finished job's pass wakes a lag, the stage-lag
  # record keeps that job's id with the lag. A later pass that names the same job id, the same job met again because
  # an earlier pass failed to let it go, is not a second finish: it neither wakes again nor writes the warning, and
  # the lag stays recorded as woken with the marks of its episode. Only a finish of a different job, or a pass that
  # names no job, over a woken lag counts as the second finish and writes the warning.

  # the lagging documents now, and the lags already acted on for this asset
  lagging = _find_all_lagging_docs(asset_note, asset_dir)
  raised = spec_job_markers.read_stage_lag(repo_root, asset_note)
  fresh = [ fingerprint for fingerprint in lagging if fingerprint not in raised ]

  # a lag this very job's finish already woke is met again only because an earlier pass over the job failed to let
  # it go: that is the same finish, not a second one, and it neither wakes again nor warns
  same_finish = [
      fingerprint for fingerprint in lagging
      if job_id and raised.get(fingerprint) == _LAG_WOKEN
      and raised.get(f"{fingerprint}{_LAG_JOB_SUFFIX}") == job_id
  ]
  repeated = [
      fingerprint for fingerprint in lagging
      if raised.get(fingerprint) == _LAG_WOKEN and fingerprint not in same_finish
  ]

  # a lag no longer present is forgotten, a fresh one is woken, a woken one is warned once; a lag met again by
  # the finish that woke it stays woken, with the marks of its episode
  record = {
      fingerprint: _LAG_WOKEN if fingerprint in fresh or fingerprint in same_finish else _LAG_WARNED
      for fingerprint in lagging
  }
  record.update({
      key: raised[key] for fingerprint in same_finish
      for key in ( f"{fingerprint}{_LAG_EPISODE_SUFFIX}", f"{fingerprint}{_LAG_JOB_SUFFIX}" ) if key in raised
  })

  # guard: nothing new to wake and nothing left to warn about — only the record is kept current
  if not fresh and not repeated:
    spec_job_markers.write_stage_lag(repo_root, asset_note, record)
    return []

  # the note's new text is built in memory from the text on disk, which a failed commit puts back
  original_text = spec_paths.read_text(asset_note)
  new_text = original_text

  # a fresh lag reopens the document's recorded verdict, so the redeemed wake reads it as a transition
  if fresh:
    values, fm_end = flip_gate.parse_frontmatter(new_text)

    # an unreadable recorded state is the dispatcher's own scratch; rebuilding it only re-fires transitions
    try:
      state = json.loads(values.get(SpecCoordinatorDocStateKey.STATE) or "{}")
    except json.JSONDecodeError:
      state = {}
    state = state if isinstance(state, dict) else {}

    # the reopened verdict of every freshly lagging document
    for fingerprint in fresh:
      state[lagging[fingerprint]] = SpecCoordinatorDocStateKey.REVIEW_REOPENED
    new_text = set_fm_json(new_text[:fm_end], SpecCoordinatorDocStateKey.STATE, state) + new_text[fm_end:]

    # each fresh lag opens an episode, marked by the warning lines the history carried before it
    record.update({ f"{fingerprint}{_LAG_EPISODE_SUFFIX}": str(_count_lag_warnings(original_text, fingerprint))
                    for fingerprint in fresh })

    # the finish that wakes a lag is remembered with it, so a second pass over the same job is told apart
    if job_id:
      record.update({ f"{fingerprint}{_LAG_JOB_SUFFIX}": job_id for fingerprint in fresh })

  # a repeated lag is reported once and wakes nobody again
  note_lang = note_explainers.lang_for_note(asset_note)
  for fingerprint in repeated:
    # guard: a warning the history gained since this episode began, in whatever language it was written, was
    # committed by a pass that then failed to record the lag as warned; it is not written a second time. A
    # warning that was there before the episode began belongs to an earlier one and does not count
    if _count_lag_warnings(original_text, fingerprint) > _read_lag_episode(raised, fingerprint):
      continue
    name, _sep, verdict = fingerprint.partition(":")
    line = note_explainers.history_line_for_lang(note_lang, HistoryEvent.STAGE_LAG, doc = name,
                                                 review_result = verdict)
    new_text = history_journal.append(new_text, line, today_str, repo = repo_root)

  # one commit carries the note so the coordinator watch sees it; a commit that fails leaves the note, the wake
  # flag and the record as they were, so the pass that retries acts on the same lags once. A pass whose every
  # warning is already in the history has nothing to write and only brings the record up to date below
  if new_text != original_text:
    names = ", ".join(sorted({ lagging[fingerprint] for fingerprint in [ *fresh, *repeated ] }))
    write_and_commit_note(
        asset_dir, asset_note, new_text, original_text = original_text,
        subject = f"{_PROMOTE_AUTHOR_NAME}: stage lag on {asset_dir.name} ({names})",
    )

  # the redeemable wake and the record follow the commit, never precede it
  if fresh:
    spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: JobMarker.DECLINED })
  spec_job_markers.write_stage_lag(repo_root, asset_note, record)
  return [ lagging[fingerprint] for fingerprint in [ *fresh, *repeated ] ]


def gate_tick(asset_note: Path, today: str | None = None) -> dict:
  """
  Poll one asset's coherence checks and jobs, then structurally check its folder-note.

  Finished coherence checks tracked on the note land first, independently of everything else. An
  asset tracking an active expert job then has that job's terminal marker checked; the
  coordinator's own tracked job is checked the same way next. When neither has finished, the
  folder-note is structurally checked and any violations are reported without being repaired.
  Stage promotion, gate advancement, and dispatching further work are not part of the tick.

  Guarantees:
    - A failure to land a finished job's result halts the asset with a persistent failure
      callout and leaves the job bundle unretired, and never raises out of or fails the tick.
      Recording that halt can still fail the tick, and the job then stays tracked for the next tick to retry. When
      the halt's history line is refused, or its note cannot be written or committed, no halt is committed and the
      note holds the text it had; only a failed commit whose put-back fails too leaves the uncommitted halt text,
      while the commit's own error still propagates. When only the job record that follows the committed halt
      cannot be written, the committed halt stands.
    - A failure to run the advisory `note-check` degrades to no violations and never raises out
      of or fails the tick.
    - A finished coherence check's result is applied at most once: the check's own History line is committed
      together with the conflicts, and a check whose line already stands in the note's history is never applied
      again, only marked as landed. The History line of a failed or dead check stays owed, its entry kept on the
      note's coherence list carrying the line, until the commit that records it has succeeded and the list has been
      updated after it, and a later tick finishes it.
    - The coordinator's own tracked job is retired only after every commit of its retirement (the dead-job
      warning line, the stage-lag note) has succeeded; a failed commit leaves it tracked for the next tick, with
      the note put back to the text it had or, when putting it back fails too, holding the uncommitted text while
      the commit's own error still propagates.
    - A dead coordinator job's WARNING line is recorded at most once: when the note's history already carries that
      job's line, written in any language the plugin writes in and never another job's, because an earlier tick
      wrote it and then failed to clear the marker, the retry writes and commits nothing more and only clears the
      marker.
    - A finished job's stage-lag warning line is recorded at most once as well: when the note's history already
      carries that lag's line, because an earlier tick wrote it and then failed to record the lag as warned, the
      retry writes no second line.

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    today: Optional ISO date forwarded into the applied job-marker's callout and history line.

  Returns:
    A result dict whose `action` is one of `job-done`, `job-cancelled`, `asset-halted`,
    `coordinator-job-consumed`, `coordinator-job-dead`, or `noop`; every non-`noop` action
    carries the identity it acted on (`checkbox` + `job_id` for the active-job branches,
    `trigger` + `job_id` for the coordinator-job branches); a `noop` carries an additional
    `violations` list when `note-check` found any. Whatever the action, a `coherence` list of the
    coherence checks that finished this tick is added when there were any.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved while recording a finished job.
    OSError: If a folder-note write fails or its commit raises it, or a job-marker or stage-lag sidecar write
      fails; the finished job or check stays tracked for the next tick, the note is put back when that
      succeeds, and a commit that landed before a failed sidecar write stands. A check whose apply committed stays
      applied when the write that takes it off the list fails; the next tick only takes the entry off the list.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the
      rewritten folder-note exits non-zero, or when committing the coordinator job's dead-job warning line or
      stage-lag note does; the finished job or check stays tracked for the next tick, and the note is put back
      to its text when that succeeds, otherwise it keeps the uncommitted text while this commit error still
      propagates.
  """

  # Contract:
  # A failure to land a finished job's result never raises out of the tick and never fails it.
  # The asset is halted with a persistent failure callout and the job bundle stays unretired.
  # Recording that halt can still fail the tick, and the job then stays tracked for the next tick to retry. When
  # the halt's history line is refused, or its note cannot be written or committed, no halt is committed and the
  # note holds the text it had; only a failed commit whose put-back fails too leaves the uncommitted halt text,
  # while the commit's own error still propagates. When only the job record that follows the committed halt
  # cannot be written, the committed halt stands.

  # Contract:
  # A failure to run the advisory note-check never raises out of the tick and never fails it.
  # The check degrades to reporting no violations.

  # Contract:
  # A finished coherence check's result is applied at most once: the check's own History line is committed
  # together with the conflicts, and a check whose line already stands in the note's history is never applied
  # again, only marked as landed.
  # The History line of a failed or dead check stays owed, its entry kept on the note's coherence list carrying
  # the line, until the commit that records it has succeeded and the list has been updated after it; a later tick
  # finishes it.

  # Contract:
  # The coordinator's own tracked job is retired only after every commit of its retirement has succeeded: the
  # dead-job warning line, the stage-lag note. A failed commit leaves the job tracked for the next tick, with the
  # note put back to the text it had or, when putting it back fails too, holding the uncommitted text while the
  # commit's own error still propagates.
  # A dead job's WARNING line is recorded at most once: when the note's history already carries that job's line,
  # written in any language the plugin writes in and never another job's, because an earlier tick wrote it and then
  # failed to clear the marker, the retry writes and commits nothing more and only clears the marker.
  # A finished job's stage-lag warning line is recorded at most once as well: when the note's history already carries
  # that lag's line, because an earlier tick wrote it and then failed to record the lag as warned, the retry writes
  # no second line.

  # the repository and the day every line of this tick is pinned to
  repo_root = flip_gate.repo_root(asset_note.parent)
  today_str = flip_gate.effective_today(today)

  # the coherence checks land first and on their own, so the note the job polling reads below already carries them
  landed = _poll_coherence_jobs(asset_note, repo_root, today_str)
  result = _poll_jobs(asset_note, repo_root, today_str)
  if landed:
    result[_COHERENCE_KEY] = landed
  return result


def _poll_jobs(asset_note: Path, repo_root: Path, today_str: str) -> dict:
  """
  Poll one asset's active expert job and coordinator job, then structurally check the folder-note.

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    repo_root: The repository root holding the job queue and the job-marker sidecar.
    today_str: ISO date string pinned into the applied job-marker's callout and history line.

  Returns:
    The tick result `gate_tick` describes, without the coherence checks.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved while recording a finished job.
    OSError: If a folder-note write fails or its commit raises it, for a halt, the coordinator job's warning line
      or stage-lag note, or a job-marker or stage-lag sidecar write fails, or the sidecar or note read that
      decides a retired coordinator job's `tick-pending` wake flag fails.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the
      rewritten folder-note exits non-zero, or when committing the coordinator job's warning line or
      stage-lag note does.
  """
  # the tick's one snapshot of the folder-note: its text, frontmatter split, body and job markers
  asset_dir = asset_note.parent
  text = spec_paths.read_text(asset_note)
  _, fm_end = flip_gate.parse_frontmatter(text)
  body = text[fm_end:]
  markers = spec_job_markers.read(repo_root, asset_note)

  # Domain(spec.lifecycle):
  # # Expert job terminal outcomes
  # A dispatched expert job finishes in one of three states. A completed or a cancelled job both
  # free the ladder's work slot for the same step to be dispatched again if it is still needed —
  # the attempt is done with, successfully or not, and nothing about it needs to be kept in the
  # way. A job that dies instead stops the whole asset from moving forward until an operator looks
  # at it: the failed attempt is left exactly as it was, on purpose, so there is something to
  # examine before deciding what happens next. That stop applies only to a step on the asset's own
  # promotion ladder — the automation's own background job watching over the asset is not part of
  # that ladder, so its own death is only ever recorded as a warning and never halts the asset it
  # was watching. A completed job whose result cannot be placed in the asset counts as a failed one: it stops
  # the asset the same way and its attempt is left as it was. A completed job that belongs to a declared
  # target of the asset is not placed by this pass either: the coordinator does it. A job's ending is
  # recorded before the job is let go. A step of the asset's own ladder that ends stops being tracked, and
  # the coordinator is woken about it, only after the halt of the asset, when one is owed, is safely
  # recorded; a finished step of a cancelled asset wakes nobody. The coordinator's own background job is let
  # go only after the warning about its death is recorded in the asset's history or, for one that finished,
  # after the stage-lag step its ending owes the asset is in; letting it go wakes nobody by itself, unless the
  # asset still holds a ticked launch row the coordinator has to carry out. If recording
  # fails, the job stays tracked and the next pass tries again, and the asset's note is put back as it was;
  # putting it back can fail too, and then the note keeps the unrecorded text, the failure is reported, and the
  # next pass reads that text as the note's own.

  # active-job polling: an asset tracking an `active_job` marker has its job bundle's
  # terminal marker checked before anything else this tick
  job_info = markers[JobMarker.ACTIVE_JOB]
  if isinstance(job_info, dict):
    marker = find_active_job_marker(repo_root, job_info[JobMarker.EXPERT], job_info[JobMarker.JOB_ID])
    if marker is not None:
      return apply_job_marker(
          asset_note, text, fm_end,
          body = body, asset_dir = asset_dir, repo_root = repo_root,
          marker = marker, job_info = job_info, today_str = today_str,
      )

  # coordinator-job polling: same terminal-marker check, applied to the
  # coordinator's own one-job-per-asset slot
  coord_job_info = markers[JobMarker.COORDINATOR_JOB]
  if isinstance(coord_job_info, dict):
    coord_marker = find_active_job_marker(
        repo_root, coord_job_info[JobMarker.EXPERT], coord_job_info[JobMarker.JOB_ID],
    )
    if coord_marker is not None:
      return _apply_coordinator_job_marker(
          asset_note, text, fm_end,
          body = body, asset_dir = asset_dir, repo_root = repo_root,
          marker = coord_marker, job_info = coord_job_info, today_str = today_str,
      )

  # structural check, folded into the tick result — repairing a violation is the coordinator's
  # own job (through its pen and `note-set-key`), never this worker's.
  violations = _run_note_check(asset_note)
  result: dict = { TickAction.ACTION: TickAction.NOOP }
  if violations:
    result[_VIOLATIONS_KEY] = violations
  return result


def main(argv: list[str]) -> int:
  """
  Poll one asset's active job and note-check it from the command line, printing the result as
  JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs gate-tick")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into emitted callouts")
  args = parser.parse_args(argv)
  asset_note: Path = args.asset_note.resolve()

  # guard: asset status folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2

  # run the tick and print its result as one JSON object on stdout, for the caller that ran this worker
  print(json.dumps(gate_tick(asset_note, today = args.today)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
