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
  the only channel a job's document and attachments take into the catalog — then clears the
  marker, logs a `# History` line, and retires the bundle (`gate_dispatch.consume_stale_job`,
  freeing its dedup key so the checkbox can be re-dispatched); `CANCELLED` does the same without
  the landing; `DEAD` additionally sets `spec_halted: true` and appends a persistent `[!failure]`
  callout to `# Gates` (un-halting is a manual operator act, out of scope here), leaving its
  bundle unretired for diagnostics. Every clear also raises `pending_wake: job-done` in the sidecar — that flag,
  not a diff of the clearing commit, is what makes the transition visible to
  `coordinator_dispatch.py`'s own `job-done` trigger. This worker opens no review itself; the
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
  verb, logs a `# History` line with the count, and is retired; `CANCELLED` is retired with no line; `DEAD`
  logs a WARNING line and never halts the asset. A finished check leaves the note's list and wakes no
  coordinator, and the tick result gains a `coherence` list of the checks that finished.
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
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable, Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES,
    HaltReason,
    HistoryEvent,
    JobMarker,
    LevelDoc,
    SpecCoordinatorDocStateKey,
    SpecKey,
    TickAction,
)


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

# The two states a raised stage lag moves through: woken once, then warned and left alone.
_LAG_WOKEN = "woken"
_LAG_WARNED = "warned"

# The result key naming the documents a finished coordinator job left with a lagging stage.
_STAGE_LAG_RESULT = "stage_lag"

# The env var naming the repository root a sibling verb resolves against.
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# `note_ops.note_check`'s result-dict key this worker folds into its own tick result.
_VIOLATIONS_KEY = "violations"

# `land_result.land_result`'s result-dict key listing the paths it wrote.
_LANDED_KEY = "landed"

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
    subprocess.CalledProcessError: If the commit fails.
  """
  # waiver: sibling-module git read -- the one git-field helper every specs worker shares
  top = flip_gate.git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")

  # guard: the vault lives outside a git checkout — nothing to commit into; the file write
  # above stays and is the whole mutation
  if not top:
    return

  # the enclosing repo root anchors both the repaint and the git commands below
  repo = Path(top)

  # commit the note by pathspec under the dedicated bot identity, its icon repaint folded in, so the tree is
  # clean for the next daemon iteration and the operator's authorship and staging stay untouched
  flip_gate.commit_paths(
      repo, [ asset_note ], subject = subject, author_name = _PROMOTE_AUTHOR_NAME,
      author_email = _PROMOTE_AUTHOR_EMAIL,
  )


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


def _land_job_result(repo_root: Path, asset_dir: Path, expert: str, job_id: str) -> list[str]:
  """
  Put one finished job's document in the asset folder through the `land-result` collector.

  Notes:
    - Nothing is raised: a landing failure leaves the job undelivered and the tree as it was found.

  Args:
    repo_root: The repository root holding the job queue.
    asset_dir: The asset folder the job's document belongs in.
    expert: The dispatched expert's name, the job queue's first path segment.
    job_id: The finished job's id.

  Returns:
    The repo-relative paths the landing wrote and committed; empty when nothing landed.
  """

  # the finished job's bundle directory in the expert job queue
  job_dir = repo_root / _JOBS_BASE / expert / job_id

  # guard: the bundle is gone — there is nothing to land
  if not job_dir.is_dir():
    return []
  try:
    # waiver: local import inside the try on purpose -- a broken or missing `land_result` module
    # degrades into an undelivered job like any other landing failure instead of crashing the tick
    import land_result  # pylint: disable=import-error
    target = land_result.document_target(job_dir, asset_dir)

    # guard: the job delivered no document — nothing to place
    if target is None:
      return []
    return land_result.land_result(job_dir, target)[_LANDED_KEY]
  # waiver: fire-and-forget collector — ANY landing failure, the collector's own refusal
  # included, must leave the job undelivered rather than stop the tick that also has a
  # History line and a wake to write
  except Exception as error:
    sys.stderr.write(f"gate-tick: land-result {expert}/{job_id}: {error}\n")
    return []


def _apply_coherence_result(repo_root: Path, job_dir: Path) -> int | None:
  """
  Hang a finished coherence check's conflicts on the folder-notes of the documents involved.

  Notes:
    - Nothing is raised: a result that is refused, unusable or fails to commit hangs nothing.

  Args:
    repo_root: The repository root holding the job queue.
    job_dir: The finished coherence job's bundle directory.

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
        [ sys.executable, str(cli), _COHERENCE_APPLY_SUBVERB, str(job_dir) ],
        capture_output = True, text = True, check = False, encoding = "utf-8", env = env,
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

  Args:
    asset_note: The folder-note tracking the checks.
    repo_root: The repository root holding the job queue and the job-marker sidecar.
    today_str: ISO date string pinned into the History lines.

  Returns:
    One `{"doc", "job_id", "outcome"}` record per check that finished, `outcome` being `done`, `cancelled`,
    `dead` or `failed`; a `done` record also carries `conflicts`, the number of conflicts hung, and a `failed` one
    stands for a finished check whose apply was refused or failed, with no `conflicts`. Empty when none finished.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot be resolved.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the note exits non-zero.
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
  # cancelled check is simply dropped from the list, with no history line. Whatever its outcome, a finished check
  # leaves the list and is never landed twice.

  jobs = spec_job_markers.coherence_jobs(repo_root, asset_note)
  landed: list[dict] = []
  lines: list[str] = []
  for job in jobs:
    marker = find_active_job_marker(repo_root, job[JobMarker.EXPERT], job[JobMarker.JOB_ID])

    # guard: a check still running stays on the list
    if marker is None:
      continue
    doc, job_id = job[JobMarker.DOC], job[JobMarker.JOB_ID]
    record: dict[str, str | int] = { JobMarker.DOC: doc, JobMarker.JOB_ID: job_id, _OUTCOME_KEY: marker.lower() }

    # a finished check's conflicts hang now; a cancelled one is just retired, a dead one kept for diagnostics
    if marker == JOB_MARKER_DONE:
      count = _apply_coherence_result(repo_root, repo_root / _JOBS_BASE / job[JobMarker.EXPERT] / job_id)
      if count is None:
        record[_OUTCOME_KEY] = _OUTCOME_FAILED
        lines.append(note_explainers.history_line(
            asset_note, HistoryEvent.COHERENCE_FAILED, doc = doc, job_id = job_id,
        ))
      else:
        record[_CONFLICTS_KEY] = count
        dropped = job.get(JobMarker.DROPPED)
        lines.append(note_explainers.history_line(
            asset_note, HistoryEvent.COHERENCE_CHECKED_TRIMMED,
            doc = doc, count = str(count), dropped = str(dropped),
        ) if dropped else note_explainers.history_line(
            asset_note, HistoryEvent.COHERENCE_CHECKED, doc = doc, count = str(count),
        ))
      gate_dispatch.consume_stale_job(repo_root, job[JobMarker.EXPERT], job_id)
    elif marker == _JOB_MARKER_CANCELLED:
      gate_dispatch.consume_stale_job(repo_root, job[JobMarker.EXPERT], job_id)
    else:
      lines.append(note_explainers.history_line(
          asset_note, HistoryEvent.COHERENCE_FAILED, doc = doc, job_id = job_id,
      ))
    landed.append(record)

  # guard: nothing finished, nothing to record
  if not landed:
    return []

  # the finished checks leave the list before the note is written, so a failed commit cannot land them twice
  finished = { record[JobMarker.JOB_ID] for record in landed }
  spec_job_markers.update(repo_root, asset_note, {
      JobMarker.COHERENCE_JOBS: [ job for job in jobs if job[JobMarker.JOB_ID] not in finished ],
  })

  # one History line per check that has something to say, in one write and one commit
  if lines:
    text = spec_paths.read_text(asset_note)
    _, fm_end = flip_gate.parse_frontmatter(text)
    body = text[fm_end:]
    for line in lines:
      body = history_journal.append(body, line, today_str, repo = repo_root)
    spec_paths.write_text_atomic(asset_note, note_explainers.heal_note_text(asset_note, text[:fm_end] + body))
    commit_note_change(asset_note.parent, asset_note, f"{_PROMOTE_AUTHOR_NAME}: coherence checks landed on "
                                                       f"{asset_note.parent.name}")
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
    itself could not be resolved, run, or parsed.
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
        capture_output = True, text = True, check = False, encoding = "utf-8",
    )
  # waiver: best-effort follow-up — a broken subprocess must degrade to "nothing to report",
  # never abort the tick that already handled the active-job polling pass above
  except OSError:
    return []
  try:
    result = json.loads(proc.stdout)
  except json.JSONDecodeError:
    return []
  return result.get(_VIOLATIONS_KEY, [])


def apply_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Apply an active expert job's terminal bundle marker to the asset.

  Every marker retires the tracked job and raises a `job-done` wake for the coordinator to act
  on. `DONE` lands the job's `result/` into the asset folder — undelivered when the job left
  nothing to land — and appends a `# History` line recording the outcome; `CANCELLED` appends the
  same kind of line with nothing to land. `DEAD` instead halts the asset, appending a persistent
  `[!failure]` callout to `# Gates` that stays until an operator resolves it by hand, and leaves
  the job bundle in place for diagnostics. Deciding what happens next on the asset — dispatching a
  replacement job, reacting to the halt — is `spec.coordinator`'s call; this pass only records the
  terminal outcome.

  Guarantees:
    - On a `DONE` or `CANCELLED` marker, the job bundle is retired, freeing its dedup key for
      re-dispatch while its files stay on disk.
    - On a `DEAD` marker, the job bundle is left unretired, kept on disk for diagnostics.

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
    today_str: ISO date string pinned into the callout and history line.

  Returns:
    A result dict naming the applied `TickAction` plus the job's `checkbox` and `job_id`.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved.
    subprocess.CalledProcessError: Propagated from `commit_note_change` when staging or
      committing the rewritten folder-note exits non-zero.
  """

  # Contract:
  # On a `DONE` or `CANCELLED` marker, the job bundle is retired via
  # `gate_dispatch.consume_stale_job`, freeing its dedup key so the same checkbox can be
  # re-dispatched, while the bundle's files stay on disk for the coordinator's job-done wake
  # to read. On a `DEAD` marker, the bundle is deliberately left unretired, kept for
  # diagnostics alongside the asset halt.

  checkbox_label = job_info[JobMarker.CHECKBOX]
  job_id = job_info[JobMarker.JOB_ID]

  # one language resolution serves every branch's narrative line (the resolver walks to the
  # settings root and reads config)
  note_lang = note_explainers.lang_for_note(asset_note)
  fm_text = text[:fm_end]

  # the job is over on every branch: retire the marker and raise the wake the coordinator's
  # `job-done` trigger reads, before the note write below that the wake will accompany
  spec_job_markers.update(
      repo_root, asset_note,
      { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE },
  )

  # only the body/action/subject differ per marker kind
  if marker == JOB_MARKER_DONE:
    # the job's document and attachments arrive only through `result/`: put them in the asset
    # folder and commit them here, so the document the coordinator submits into review on the
    # `job-done` wake this same call raises is already tracked
    _land_job_result(repo_root, asset_dir, job_info[JobMarker.EXPERT], job_id)

    # the landing writes into the asset folder this call is about to edit, so the note text read
    # before it is now stale — re-read it, or the write below would revert what just landed
    text = spec_paths.read_text(asset_note)
    _, fm_end = flip_gate.parse_frontmatter(text)
    fm_text, body = text[:fm_end], text[fm_end:]

    # the localized narrative tail of the History line, in the note's authoring language
    done_tail = note_explainers.history_line_for_lang(note_lang, HistoryEvent.JOB_DONE,
                                                      job_id = job_id, label = checkbox_label)
    body = history_journal.append(body, done_tail, today_str, repo = repo_root)
    action = TickAction.JOB_DONE
    subject = f"{_PROMOTE_AUTHOR_NAME}: job {job_id} ({checkbox_label}) done on {asset_dir.name}"

    # retire the bundle so its dedup key frees for a retry — same move the coordinator-job
    # branch already makes; the bundle's files stay on disk for the coordinator's wake to read
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
  elif marker == _JOB_MARKER_CANCELLED:
    # the localized narrative tail of the History line, in the note's authoring language
    cancelled_tail = note_explainers.history_line_for_lang(note_lang, HistoryEvent.JOB_CANCELLED,
                                                           job_id = job_id, label = checkbox_label)
    body = history_journal.append(body, cancelled_tail, today_str, repo = repo_root)
    action = TickAction.JOB_CANCELLED
    subject = f"{_PROMOTE_AUTHOR_NAME}: job {job_id} ({checkbox_label}) cancelled on {asset_dir.name}"

    # a cancelled bundle is equally spent — retire it so the checkbox can be re-dispatched
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
  else:
    # marker == JOB_MARKER_DEAD — halt the asset via the shared text-core primitive, in this
    # branch's own single write+commit (the marker clear above touched no note text)
    reason = HaltReason.JOB_DIED.format(job_id = job_id, label = checkbox_label)
    fm_text, body, _ = flip_gate.halt_asset_text(
        fm_text, body, reason, today = today_str, lang = note_lang,
    )
    action = TickAction.ASSET_HALTED
    subject = f"{_PROMOTE_AUTHOR_NAME}: halt {asset_dir.name} — {reason}"

  # one write, one commit, shared by every branch above
  spec_paths.write_text_atomic(asset_note, note_explainers.heal_note_text(asset_note, fm_text + body))
  commit_note_change(asset_dir, asset_note, subject)

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


def _apply_coordinator_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Sweep a finished `coordinator_job` marker off the asset.

  Retires the coordinator's own tracked job — never a ladder expert job, so a `DEAD` bundle here
  never halts the asset. `DEAD` instead appends a `# History` WARNING line; `DONE` / `CANCELLED`
  free the bundle's dedup key for the coordinator's next dispatch. A `DONE` job that left an
  approved document at `draft` additionally raises a stage-lag wake or warning for that document.
  Any wake flag raised while the swept job ran is left untouched — it survives for the next
  genuine wake to redeem.

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
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved.
  """

  # Domain(spec.lifecycle):
  # # The coordinator's own wake job is retired, never escalated
  # The job the coordinator runs to wake over an asset is not a step of the asset's promotion
  # ladder, so its death never halts the asset: it is recorded as a warning line in the asset's
  # history and nothing more. A coordinator job that finished or was cancelled is simply retired,
  # which frees its deduplication key so the coordinator's next dispatch for the asset is not
  # mistaken for a repeat of the finished one. A job that finished is also the moment to look for
  # a stage lag: an approved document the job left still at the draft stage.

  # the job's identity, read before the coordinator-job marker it came from is cleared
  trigger = job_info[JobMarker.TRIGGER]
  job_id = job_info[JobMarker.JOB_ID]
  spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # every marker clears the coordinator-job marker (already applied above); only DEAD owes the
  # note a WARNING line, and only DONE / CANCELLED owe the bundle its dedup retirement
  if marker == JOB_MARKER_DEAD:
    # one language resolution serves the WARNING line and the explainer heal (the resolver
    # walks to the settings root and reads config)
    note_lang = note_explainers.lang_for_note(asset_note)
    body = history_journal.append(
        body, coordinator_job_dead_line(trigger, job_id, lang = note_lang), today_str,
        repo = repo_root,
    )
    spec_paths.write_text_atomic(asset_note, text[:fm_end] + note_explainers.ensure_explainers(body, note_lang))
    commit_note_change(
        asset_dir, asset_note,
        f"{_PROMOTE_AUTHOR_NAME}: coordinator job {job_id} ({trigger}) died on {asset_dir.name}",
    )
    action = TickAction.COORDINATOR_JOB_DEAD
  else:
    # marker in (JOB_MARKER_DONE, _JOB_MARKER_CANCELLED) — retire the bundle so its dedup key
    # frees for the coordinator's next dispatch; nothing here reaches the note
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
    action = TickAction.COORDINATOR_JOB_CONSUMED

  # a finished job that left an approved document at `draft` wakes the coordinator once, then warns
  lagging = update_stage_lag(asset_note, asset_dir, repo_root, today_str) if marker == JOB_MARKER_DONE else []

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
  Record the lags of the given documents as woken, unless a wake or warning is already on record for them.

  Args:
    repo_root: The repository root holding the stage-lag sidecar.
    asset_note: The asset's status folder-note the record belongs to.
    docs: The documents a wake has just been dispatched over.
  """
  # the lags not yet on record among these documents, each now spent on this wake
  raised = spec_job_markers.read_stage_lag(repo_root, asset_note)
  woken = {
      stage_lag_fingerprint(doc): _LAG_WOKEN for doc in docs if doc.is_file() and is_stage_lag_unraised(doc, raised)
  }

  # guard: every lag here is already on record, or none of these documents lags
  if not woken:
    return
  spec_job_markers.write_stage_lag(repo_root, asset_note, { **raised, **woken })


def update_stage_lag(asset_note: Path, asset_dir: Path, repo_root: Path, today_str: str) -> list[str]:
  """
  Wake the coordinator once over documents left lagging by a finished job, then warn once.

  The first finish over a lagging document wakes the coordinator once, with the document's verdict re-read as a
  transition. A second finish over the same document and verdict records one `# History` warning and wakes
  nobody. Later finishes do nothing.

  Notes:
    - Commits the note whenever it wakes or warns, so the coordinator watch sees the change.
    - Updates the asset's stage-lag record on every call, dropping lags that are no longer present.

  Args:
    asset_note: The asset's status folder-note.
    asset_dir: The asset folder holding its documents.
    repo_root: The repository root holding the stage-lag sidecar.
    today_str: ISO date string pinned into the History line.

  Returns:
    The basenames of the lagging documents acted on; empty when nothing was woken or warned.
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
  # Every later finish over that lag does nothing. A lag that is no longer present is forgotten,
  # so a document that lags again later with the same verdict starts over with a wake.

  # the lagging documents now, and the lags already acted on for this asset
  lagging = _find_all_lagging_docs(asset_note, asset_dir)
  raised = spec_job_markers.read_stage_lag(repo_root, asset_note)
  fresh = [ fingerprint for fingerprint in lagging if fingerprint not in raised ]
  repeated = [ fingerprint for fingerprint in lagging if raised.get(fingerprint) == _LAG_WOKEN ]

  # a lag no longer present is forgotten, a fresh one is woken, a woken one is warned once
  record = { fingerprint: _LAG_WOKEN if fingerprint in fresh else _LAG_WARNED for fingerprint in lagging }

  # guard: nothing new to wake and nothing left to warn about — only the record is kept current
  if not fresh and not repeated:
    spec_job_markers.write_stage_lag(repo_root, asset_note, record)
    return []

  # a fresh lag reopens the document's recorded verdict, so the redeemed wake reads it as a transition
  if fresh:
    text = spec_paths.read_text(asset_note)
    values, fm_end = flip_gate.parse_frontmatter(text)

    # an unreadable recorded state is the dispatcher's own scratch; rebuilding it only re-fires transitions
    try:
      state = json.loads(values.get(SpecCoordinatorDocStateKey.STATE) or "{}")
    except json.JSONDecodeError:
      state = {}
    state = state if isinstance(state, dict) else {}

    # the reopened verdict, the note write and the redeemable wake
    for fingerprint in fresh:
      state[lagging[fingerprint]] = SpecCoordinatorDocStateKey.REVIEW_REOPENED
    fm_text = set_fm_json(text[:fm_end], SpecCoordinatorDocStateKey.STATE, state)
    spec_paths.write_text_atomic(asset_note, fm_text + text[fm_end:])
    spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: JobMarker.DECLINED })

  # a repeated lag is reported once and wakes nobody again
  note_lang = note_explainers.lang_for_note(asset_note)
  for fingerprint in repeated:
    name, _sep, verdict = fingerprint.partition(":")
    line = note_explainers.history_line_for_lang(note_lang, HistoryEvent.STAGE_LAG, doc = name,
                                                 review_result = verdict)
    history_journal.append_to_file(asset_note, line, today_str, repo = repo_root)

  # one commit carries the note so the coordinator watch sees it, then the record is kept
  names = ", ".join(sorted({ lagging[fingerprint] for fingerprint in [ *fresh, *repeated ] }))
  commit_note_change(asset_dir, asset_note, f"{_PROMOTE_AUTHOR_NAME}: stage lag on {asset_dir.name} ({names})")
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
    - A failure to land a finished job's result leaves the job undelivered for the coordinator
      to report and the asset folder as found, and never raises out of or fails the tick.
    - A failure to run the advisory `note-check` degrades to no violations and never raises out
      of or fails the tick.

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
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the
      rewritten folder-note exits non-zero.
  """

  # Contract:
  # A failure to land a finished job's result never raises out of the tick and never fails it.
  # The job stays undelivered for the coordinator to report, and the asset folder is left
  # as found.

  # Contract:
  # A failure to run the advisory note-check never raises out of the tick and never fails it.
  # The check degrades to reporting no violations.

  # the repository and the day every line of this tick is pinned to
  repo_root = flip_gate.repo_root(asset_note.parent)
  # waiver: sibling-module date resolution -- the one today-pinning helper every specs worker shares
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
    subprocess.CalledProcessError: Propagated from `commit_note_change` when committing the
      rewritten folder-note exits non-zero.
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
  # was watching.

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
