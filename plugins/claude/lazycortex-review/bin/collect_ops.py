"""Postman for finished expert jobs: wake the coordinator, land payloads on demand.

`collect-tick` (the routine sweep) walks `<repo>/.experts/.jobs/<expert>/<job_id>/` for
DONE-and-not-CONSUMED job bundles and, per target document, clears the runtime `active_job`
marker, raises the `job-done` pending wake, and dispatches the coordinator directly — the
sweep itself no longer lands payloads and no longer commits.
The landing happens inside the coordinator's own wake, via `collect-job`: payloads are
applied via `reapply.reapply`, the `active_job` marker is cleared, the document is written,
and only then is each applied job consumed — a failed write consumes nothing. The
coordinator's single `commit-doc` carries payload and settle together — `collect-job` itself
never commits and raises no wake. This module
carries no scheduling judgment:
a `DEAD` job, a job still pending, or a job already `CONSUMED` is left exactly as found for
whoever dispatched it to decide what happens next.

Request-payload fields this module reads (written by the job's dispatcher; `mode` is the
same structural field `payload.build_request` already writes — `"main"` for a full-document
payload, `"validation"` / `"terminal"` for a section-writer payload):

    {
      "_target_file": "<absolute path of the reviewed document>",
      "mode":       "main" | "validation" | "terminal",
      "expert":     "<dispatch name of the section-owning writer>",  # required when mode != "main"
      "section_id": "<section id>",                                  # required when mode != "main"
      "section":    "<H1 section title>",                            # optional; defaults from `section_id`
      "position":   "top" | "bottom"                                 # optional; defaults to bottom
    }

Response-payload fields this module reads (the agent's `response.json`):

    {
      "outcome": "edited" | "empty" | "error",
      "result": [{"path": "result/<document>"}, {"path": "result/<attachment>"}, ...],
                # required when outcome == "edited"
      "plan_verdict": "sufficient" | "new-plan"
                # required of a `main` job on a document of a report class; ignored elsewhere
    }

A report class's `main` job whose `plan_verdict` is absent or neither value is retired under `failed` with nothing
of it landed. The verdict of the last such job the landing applies is stored as the document's `verdict` job marker
under the document's repository root, in the same write that clears `active_job` when the collect's repository is
that root.

The first `result` entry is the job's own document. Every further entry is an attachment the
landing puts beside that document under the entry's own basename — accepted on `mode == "main"`
only; any other mode's extra entries are dropped with a line on stderr.

Only `outcome == "edited"` jobs carry content to apply. An `outcome == "empty"` job — a
writer that finished with nothing to change — is consumed without touching the document, so
the round still closes within one sweep. An `edited` job whose result cannot be applied — a
malformed request or response, or a result that cannot be parsed or landed — is retired
(consumed) and named under `failed` with its reason, so the caller decides the turn. A bundle
whose files cannot be read right now (`OSError`) is left uncollected and unconsumed for a later
pass, and so is any outcome other than `edited` / `empty`. In the sweep, a finished bundle whose
own request can never be used (not a request object, or naming a target that cannot be turned into a path)
is retired and named once in the sweep's `error`, while a finished bundle whose `response.json` can never be
read as a response object is named in the sweep's `error` and handed to the coordinator, whose landing retires
it under `failed`; and a job whose attachment cannot be put beside the document lands nothing and is retired
under `failed`, unless its attachments cannot all be put back to their earlier state: that job stays finished and
unconsumed and is named under `unfinished`. Before anything is written, git is asked once about every file an
attachment would replace, and each must be tracked and unmodified, or its name must be new; a job with an attachment
over any other file writes nothing and is retired under `failed`, its reason naming each such path, while the other
jobs still land. A job whose bundle files could not be read ahead of the landing adds no path to that question: it is
held back, unconsumed, for a later pass. Only git that cannot be asked, or a document whose folder is not inside the
repository, refuses the landing, and then nothing is written. Nothing is stored between landings.
A bundle already consumed, dead or cancelled is never read as work again, by the sweep or by the landing.

Jobs are consumed through the core CLI only, in the order they were applied. A consume that core refuses makes the
landing take the unconsumed jobs' results out of the document again and end with the reason, so a job's result is in
the document if and only if the job is consumed, and the next landing lands the rest. Attachments are written
whole or not at all.
"""
from __future__ import annotations

from typing import NamedTuple

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import doc_class as _doc_class  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import payload as _payload  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import reapply as _reapply  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    CoreCommand, EnvVar, JobFile, JobKey, JobMarker, JobStatus, Outcome, Phase, ReportVerdictKind, ReviewKey,
    ReviewProtocol, Tag,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from errors import GitOpsError, JobConsumeError, PayloadError, SettingsReadError  # noqa: E402


# A link target pointing into the job's own result dir — what a writer spells when it references
# an attachment it is returning alongside the document. Four shapes carry such a target: an inline
# link `(result/x)`, a titled inline link `(result/x "t")`, a reference definition `[a]: result/x`,
# and an HTML source attribute `src="result/x"`. Only the opening delimiter is captured and
# replayed, so whatever closes each shape is left exactly as the writer spelled it.
# ref: lazycortex-specs/bin/land_result.py
_RESULT_LINK_RE = re.compile(
    r"""(?P<open>\(|\]:[ \t]*|src[ \t]*=[ \t]*["'])result/(?P<name>[^)"'\s]+)""")

# `_RESULT_LINK_RE`'s capture groups: the delimiter that opened the shape, replayed verbatim,
# and the returned file's name behind the `result/` prefix.
_GROUP_OPEN = "open"
_GROUP_NAME = "name"

# The job bundle's own output directory, mirrored from the runtime layout.
_RESULT_DIR = "result"

# The `collect-job` result key naming the jobs whose result could not be applied, and the key of
# the reason inside each of its entries.
_FAILED = "failed"
_FAILED_REASON = "reason"

# The reason reported for a report's main-writer job whose response gives no plan verdict.
_MISSING_VERDICT_REASON = f"a report's main writer gave no `{JobKey.PLAN_VERDICT}`"
# The reason reported for a report's main-writer job whose plan verdict is neither known value; the value follows it.
_UNKNOWN_VERDICT_REASON = f"`{JobKey.PLAN_VERDICT}` is neither of {sorted(ReportVerdictKind)}"

# The reason reported for an `edited` job whose payload or request is malformed.
_UNAPPLIED_EDIT_REASON = "the edit's result or request is malformed and could not be applied"
# The reason a job is reported with when one of its attachments could not be written beside the document.
_UNLANDED_ATTACHMENT_REASON = "an attachment could not be put beside the document"
# The Unicode normalisation form file names are brought to before they are compared: the composed one.
_ONE_SPELLING: Final = "NFC"
# The reason a job is reported with when one of its attachments would replace a file that git does not hold
# unchanged; the paths follow it.
_DIRTY_ATTACHMENT_REASON = "an attachment would replace a file git cannot give back"
# The stderr line a job is held back with when git was never asked about one of its attachment paths before the
# landing; the paths follow it.
_UNASKED_ATTACHMENT_REASON = "held back, git was not asked about an attachment path"

# The protocols of this plugin one of which every review dispatch attaches to its job: the writer's wire contract
# and the coordinator's playbook.
_REVIEW_PROTOCOLS: Final = frozenset({ ReviewProtocol.DOC_REVIEW, ReviewProtocol.COORDINATION_PLAYBOOK })
# The stderr line a finished review job is named with when neither its request nor the job markers name its
# document.
_ORPHAN_REVIEW_REASON = "a review job whose document nothing names; kept for the operator"

# The `collect-job` result key naming, as `<expert>/<job id>`, the finished jobs this call left unconsumed because
# one of their attachments could not be put back to its earlier state; present only when there is such a job.
_UNFINISHED = "unfinished"

# The `collect-job` result key naming, as `<expert>/<job id>` in landing order, the jobs whose results are in the
# document while unconsumed; present only when the results could not be taken out again.
_UNCONSUMED = "unconsumed"

# Frontmatter key marking a spec catalog's own canonical or status note — a file a landing
# may never overwrite, whoever else's plugin owns it.
_SPEC_ROLE_KEY = "spec_role"

# Log line for attachment entries a non-main mode drops, filled with the job, the entry count and the mode.
DROPPED_ATTACHMENTS_TEMPLATE = (
    "collect-job: {job}: {count} attachment entry(ies) dropped — mode {mode!r} accepts none\n"
)
# Log line for a `result/` link naming a file the response never delivered, filled with the job and the name.
MISSING_NEIGHBOUR_TEMPLATE = "collect-job: {job}: link to missing neighbour {name!r}\n"
# Log line for a delivered attachment no link references, filled with the job and the name.
UNLINKED_ATTACHMENT_TEMPLATE = "collect-job: {job}: attachment {name!r} is not linked from the document\n"


# ----------------------------------------------------------------------------------------
class _Step(NamedTuple):
  """
  One applied job of a landing, with what is needed to take it out again.

  Attributes:
    jdir: The job-bundle directory.
    text_before: The document's LF text before this job was applied.
    written: The attachments the job wrote, mapping each file name to its bytes.
    landed: The repo-relative paths of the attachments the job put beside the document.
  """

  # The job-bundle directory.
  jdir: Path
  # The document's LF text before this job was applied.
  text_before: str
  # The attachments the job wrote, mapping each file name to its bytes.
  written: dict[str, bytes]
  # The repo-relative paths of the attachments the job put beside the document.
  landed: list[str]


# ------------------------------------------------------------- plan verdict


def _is_report_document(file_path: Path) -> bool:
  """
  Tell whether the document's review class is configured as a report class.

  Args:
    file_path: The document whose class is resolved, from the merged settings nearest to it.

  Returns:
    True only when the resolved class sets `report` to `true`; a document no class covers and a class without the
    flag read as False.

  Raises:
    RuntimeError: When no core CLI is resolvable.
    ValueError: When the review settings cannot be read, so whether the document is a report is unknown.
  """
  # the document's nearest settings name its class
  settings_root = _core_settings.query_settings_root_for(file_path)

  # guard: unreadable settings say nothing about the class; reading them as "not a report" would land a report's
  # main job with no verdict, so the landing is refused and the next pass retries
  try:
    settings = _core_settings.read_merged_sections(settings_root, JobKey.REVIEW)
  except SettingsReadError as error:
    raise ValueError(f"the review settings cannot be read, so the document's class is unknown: {error}") from error
  return bool(_doc_class.is_report_class(settings, settings_root, file_path))


def _verdict_failure(response: dict) -> str | None:
  """
  Judge the plan verdict a report's main writer gave in its response.

  Args:
    response: Parsed `response.json` contents of a main-writer job on a report-class document.

  Returns:
    The reason the job is retired under `failed`, or `None` when `plan_verdict` is one of the two known values.
  """
  verdict = response.get(JobKey.PLAN_VERDICT)

  # guard: a report's writer always states whether the plan suffices; silence is a malformed answer
  if verdict is None:
    return _MISSING_VERDICT_REASON

  # guard: a value outside the closed pair would paint a banner that promises no known path
  if verdict not in set(ReportVerdictKind):
    return f"{_UNKNOWN_VERDICT_REASON}: {verdict!r}"
  return None


# ------------------------------------------------------------- job discovery


def _job_target(repo: Path, jdir: Path, data: dict) -> Path | None:
  """
  Resolve the document a job bundle targets.

  Args:
    repo: Absolute path to the repository root.
    jdir: The job-bundle directory.
    data: The bundle's parsed `request.json` object; callers pass an object only.

  Returns:
    The target document's path — from the payload's `_target_file` when the dispatch
    carried it, else recovered through the job-markers sidecar (`mark-job` records the
    document→job link before every dispatch) — or `None` when neither names one.

  Raises:
    OSError: If the payload names no document and the job-marker sidecar exists but cannot be read, or reads but is
      no store.
  """
  target = data.get(JobKey.TARGET_FILE)
  if isinstance(target, str) and target.strip():
    return Path(target)

  # fallback: the mark-job marker written before dispatch still links doc to job; a sidecar that cannot be
  # read raises `OSError` to the caller's per-bundle boundary and is never read as "no document"
  key = _job_markers.find_doc_for_job_checked(repo, jdir.name)

  # guard: no payload field and no marker entry — the job is unaddressable
  if key is None:
    return None
  return repo / key


def _job_dirs_for_file(repo: Path, file_path: Path) -> list[Path]:
  """
  Return the finished, unconsumed job bundles under `.experts/.jobs/` that target `file_path`.

  Only `DONE` bundles are read: a bundle still in flight, consumed, dead or cancelled is not. A finished bundle
  whose own request can never be used (not a request object, or naming a target that cannot be turned into a
  path), a bundle whose files cannot be read right now, a bundle whose document cannot be looked up because the
  job-marker sidecar cannot be read or reads but is no store, and a queue folder that cannot be listed are
  stepped over with a line on stderr and left uncollected; the call never raises.

  Args:
    repo: Absolute path to the repository root.
    file_path: Absolute path to the review document.

  Returns:
    The matching job-bundle directories, with expert queues and bundles taken in sorted order.
  """
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR

  # guard: no job queue at all — nothing can target this file
  if not jobs_root.is_dir():
    return []
  target = str(file_path)
  out: list[Path] = []

  # every expert queue is walked; only a finished, unconsumed bundle is opened
  for expert_dir in _list_dir(jobs_root):
    # only expert subdirectories hold job bundles
    if not expert_dir.is_dir():
      continue
    for jdir in _list_dir(expert_dir):
      # the per-bundle boundary: one bundle that cannot be read is stepped over, never raised out
      try:
        # a bundle still in flight has no result yet, and a consumed, dead or cancelled one is never
        # read as work again, whatever its files hold
        if not jdir.is_dir() or read_job_status(jdir) != JobStatus.DONE:
          continue

        # a job dir without a request.json carries no target to match
        if not (jdir / JobFile.REQUEST).is_file():
          continue
        resolved = _read_bundle_target(repo, jdir)

        # a payload target is compared verbatim (dispatchers write the same absolute string),
        # while a sidecar-recovered `repo / key` needs symlink-safe resolution to match it
        if resolved is not None and (str(resolved) == target or resolved.resolve() == file_path.resolve()):
          out.append(jdir)
      except OSError as error:
        # the bundle's files cannot be read right now; a later pass may read them
        sys.stderr.write(f"collect-job: {jdir}: {type(error).__name__}: {error}\n")
      # waiver: a bundle's own files are untrusted data — whatever their content raises must stop at this
      # bundle; a narrower list is what let one malformed request stop every landing
      except Exception as error:  # pylint: disable=broad-exception-caught
        sys.stderr.write(f"collect-job: {jdir}: unusable request, skipped: {type(error).__name__}: {error}\n")
  return out


def _read_bundle_target(repo: Path, jdir: Path) -> Path | None:
  """
  Read a bundle's request and return the document it targets.

  Args:
    repo: Absolute path to the repository root.
    jdir: The job-bundle directory.

  Returns:
    The targeted document's path, or `None` when the bundle is addressed to no review document.

  Raises:
    OSError: When the request cannot be read right now, the target is a link loop that cannot be resolved right now,
      or the request names no document and the job-marker sidecar exists but cannot be read or reads but is no store.
    ValueError: When the request can never be used: it is not a request object, or it names a target that cannot
      be turned into a path.
  """
  data = _read_json_object(jdir / JobFile.REQUEST)

  # guard: a request that is no object names no document and never will
  if data is None:
    raise ValueError(f"{JobFile.REQUEST} is not a readable request object")
  target = _job_target(repo, jdir, data)

  # guard: no target and no marker link — the bundle is not addressed to any review document
  if target is None:
    return None

  # a target that cannot be turned into a path raises here, inside the caller's boundary, and not later
  # where the path is first used; a link loop (`RuntimeError` before Python 3.13) is a fault of the host the
  # operator can still fix, so it is told as one that cannot be read right now
  try:
    target.resolve()
  except RuntimeError as error:
    raise OSError(f"the target {target} cannot be resolved right now: {error}") from error
  return target


def _list_dir(folder: Path) -> list[Path]:
  """
  List the entries of a folder in sorted order.

  Notes:
    - Writes one line to stderr naming the failure when the folder cannot be listed.

  Args:
    folder: The folder to list.

  Returns:
    The folder's entries in sorted order, or an empty list when the folder cannot be listed.
  """
  # a folder that cannot be listed holds nothing this pass can use; it is named once and passed over
  try:
    return sorted(folder.iterdir())
  except OSError as error:
    sys.stderr.write(f"collect-job: {folder}: {type(error).__name__}: {error}\n")
    return []


def read_job_status(jdir: Path) -> str:
  """
  Classify a job bundle by its terminal marker files.

  Args:
    jdir: Job-bundle directory to classify.

  Returns:
    One of `Outcome.CONSUMED`, `JobStatus.DEAD`, `JobStatus.CANCELLED`, `JobStatus.DONE`, or
    `JobStatus.PENDING`, in precedence order when more than one marker is present: a consumed
    job always classifies as `CONSUMED` before `JobStatus.DEAD`, which takes precedence over
    `JobStatus.CANCELLED`, which in turn takes precedence over `JobStatus.DONE` (a cancelled
    job's payload must never be collected); a job carrying none of the markers classifies as
    `JobStatus.PENDING`.
  """

  # Domain(review.jobs):
  # # A job bundle's state is read from its own markers, most final first
  # A job bundle carries its lifecycle as file markers beside it rather than in one field, and
  # more than one marker can be present at once — a job can be judged dead after it has already
  # finished, or cancelled after it has already finished. The bundle is read most-final-marker-
  # first: once consumed, a job's state never regresses; a dead job's payload is never
  # collected even if it also finished; a cancelled job's payload is never collected even if it
  # also finished. Only a bundle carrying none of these markers is still in flight.

  if (jdir / Outcome.CONSUMED).exists():
    return Outcome.CONSUMED
  if (jdir / JobFile.DEAD).exists():
    return JobStatus.DEAD
  if (jdir / JobFile.CANCELLED).exists():
    return JobStatus.CANCELLED
  if (jdir / JobFile.DONE).exists():
    return JobStatus.DONE
  return JobStatus.PENDING


# --------------------------------------------------------------- payload apply


def _is_spec_document(path: Path) -> bool:
  """
  Report whether `path` is an existing markdown note carrying a spec catalog's role marker.

  Args:
    path: Absolute path of the destination an attachment would take.

  Returns:
    `True` when the file exists, is markdown, and its frontmatter carries `spec_role`;
    `False` for every other path, including one that cannot be read.
  """
  # guard: only an existing markdown file can carry the frontmatter that marks a spec note
  # waiver: `.md` is the fixed markdown file suffix, a file-format fact rather than tunable data
  if path.suffix.lower() != ".md" or not path.is_file():
    return False
  try:
    meta, _body = _fm.parse(path.read_text(encoding = "utf-8"))
  # waiver: an unreadable neighbour is simply not a spec note — the landing is not this
  # helper's to refuse over an IO error it cannot attribute
  except (OSError, UnicodeDecodeError):
    return False
  return _SPEC_ROLE_KEY in meta


def _is_case_clash(entry: str, name: str) -> bool:
  """
  Tell whether a folder entry and a file name are two names that differ only by letter case.

  Args:
    entry: The name of an entry already in the folder, in whatever spelling the folder listing gives it.
    name: The file name about to be written.

  Returns:
    True when the two differ by letter case alone; False when they are the same name, composed and decomposed
    spellings of a character counting as the same, and when they differ by more than letter case.
  """
  # both names are brought to one spelling first: a listing may give a decomposed name for the very file
  # the other name spells composed, and that is one name, not a clash
  known = unicodedata.normalize(_ONE_SPELLING, entry)
  wanted = unicodedata.normalize(_ONE_SPELLING, name)
  return known != wanted and known.casefold() == wanted.casefold()


def _require_entry_lands(source: Path, dest: Path | None, document: Path) -> None:
  """
  Refuse one `result` entry whose bundle file, or whose destination, makes it unsafe to copy.

  Args:
    source: The entry's file inside the job bundle's `result/` directory.
    dest: The path the entry would take beside the document, or `None` for the job's own
      result document, which is read rather than copied out.
    document: The review document this job targets.

  Raises:
    PayloadError: When the bundle file is a symlink or absent, or when the destination is a
      symlink, differs from an entry already in its folder only by letter case (composed and decomposed
      spellings of a character count as the same name), is the reviewed document itself, or is a spec
      catalog's own note.
    OSError: When the destination's folder cannot be listed.
  """

  # Domain(review.dispatch):
  # # A landing replaces a same-named attachment, never the document or a spec note
  # A response's entries are files the collector copies into a directory full of documents it
  # did not write. Re-landing an attachment under the same name is the ordinary regenerate case
  # and may replace the earlier file, provided the document's recorded history can give that
  # earlier file back; a file it cannot give back is not replaced, as the rule on what a landing
  # may replace sets out. Apart from that, only three destinations are refused by name: the
  # reviewed document itself is the round's own output and is never an attachment's destination;
  # a spec catalog's canonical or status note belongs to a pipeline this collector knows nothing
  # about; and a file already in the folder whose name differs from the attachment's only by
  # letter case. Wherever
  # letter case does not tell file names apart, such a name is that existing file, so landing the
  # attachment would replace a file the result never named and whose state nobody checked. The
  # rule is applied everywhere, whatever the local file system does with case, so a landing
  # behaves the same on every machine. Two spellings of one accented character, a single
  # precomposed character or a base letter followed by a combining mark, are one name, not two:
  # a folder may report a file's name in either spelling, so both names are brought to the same
  # spelling before they are compared. A name that then equals an existing file's name is that
  # file, and landing it is the ordinary replace-the-same-attachment case; only a name that then
  # differs from an existing one by letter case alone is refused.
  # A symlink is refused at both ends before anything is read or written, because what it names
  # is outside the checked location whatever it resolves to, and the containment the entry
  # passed was only ever about the name: a copy onto a symlinked destination writes through it.

  # guard: a symlink names a file outside the bundle whatever it resolves to
  if source.is_symlink():
    raise PayloadError(f"result entry is a symlink: {source.name!r}")

  # guard: the response declared a file the writer never wrote — a malformed response
  if not source.is_file():
    raise PayloadError(f"result entry declared but not delivered: {source.name!r}")

  # the job's own result document is read, never copied — it has no destination to check
  if dest is None:
    return

  # guard: a symlinked destination is written through, landing the file outside the folder
  if dest.is_symlink():
    raise PayloadError(f"attachment destination is a symlink: {source.name!r}")

  # guard: a name that differs from an entry of the folder only by letter case is that very file wherever
  # letter case does not tell names apart, and writing it would replace a file nothing was asked about
  if any(_is_case_clash(entry, dest.name) for entry in os.listdir(dest.parent)):
    raise PayloadError(f"attachment name differs from an existing file only by letter case: {source.name!r}")

  # guard: the document an attachment rides with is never the file it overwrites
  if dest == document:
    raise PayloadError(f"attachment would overwrite the reviewed document: {source.name!r}")

  # guard: a spec catalog's own note is nobody's attachment destination
  if _is_spec_document(dest):
    raise PayloadError(f"attachment would overwrite a spec document: {source.name!r}")


def _attachment_names(request: dict, response: dict, jdir: Path, document: Path) -> list[str]:
  """
  Resolve the response's attachment entries to the basenames they take beside the document.

  Args:
    request: Parsed `request.json` contents.
    response: Parsed `response.json` contents.
    jdir: Job-bundle directory, named in the dropped-entry log line.
    document: The review document this job targets, which the attachments land beside.

  Returns:
    The attachment basenames in declaration order; empty when the response carries none or
    the dispatch's mode does not accept them.

  Raises:
    PayloadError: When an entry resolves to anything but a plain filename under `result/`,
      carries a control character in its name, has a name not in composed (`NFC`) spelling,
      names a file the job bundle never wrote or
      symlinked, or would land on a symlink, on a name that differs from an existing file only
      by letter case (composed and decomposed spellings of a character count as the same name), on
      the reviewed document, or on a spec catalog's own note.
    OSError: When the document's folder cannot be listed.
  """
  entries = response[JobKey.RESULT][1:]

  # only a main-writer payload may carry attachments — every other mode drops the extras
  if request.get(JobKey.MODE) != Phase.MAIN:
    if entries:
      sys.stderr.write(DROPPED_ATTACHMENTS_TEMPLATE.format(
          job = jdir.name, count = len(entries), mode = request.get(JobKey.MODE),
      ))
    return []
  names = [_payload.attachment_basename(entry) for entry in entries]

  # every entry is a promise about a file and a destination; check the whole list before
  # anything is copied, so a response with one bad entry lands nothing at all rather than a part
  for name in names:
    _require_entry_lands(jdir / _RESULT_DIR / name, document.parent / name, document)
  return names


def _fix_attachment_links(body: str, names: list[str], jdir: Path) -> str:
  """
  Rewrite the body's `result/<file>` links to the neighbour names the attachments will take.

  Covers every shape a writer spells such a target in: an inline link, a titled inline link, a
  reference definition, and an HTML `src` attribute.

  Notes:
    - Never raises and never drops a link: a mismatch between the links and the delivered
      attachments is reported on stderr and the landing continues.

  Args:
    body: The writer's document body as returned.
    names: The attachment basenames this response delivered.
    jdir: Job-bundle directory, named in each log line.

  Returns:
    The body with every `result/<file>` link rewritten to `<file>`.
  """
  delivered = set(names)
  linked: set[str] = set()

  # replace one `result/<file>` link target with the bare neighbour name
  def _neighbour(match: re.Match) -> str:
    name = match.group(_GROUP_NAME)
    linked.add(name)

    # warn when the document points at a neighbour this response never delivered
    if name not in delivered:
      sys.stderr.write(MISSING_NEIGHBOUR_TEMPLATE.format(job = jdir.name, name = name))
    return f"{match.group(_GROUP_OPEN)}{name}"

  # rewrite every result/ link in one pass, then report the two mismatch directions
  out = _RESULT_LINK_RE.sub(_neighbour, body)

  # an attachment nobody references is still landed — the operator is told, the job is not failed
  for name in sorted(delivered - linked):
    sys.stderr.write(UNLINKED_ATTACHMENT_TEMPLATE.format(job = jdir.name, name = name))
  return out


def _build_agent_body(
    jdir: Path, request: dict, response: dict, document: Path,
) -> tuple[str, str, tuple[str, str] | None, list[str]]:
  """
  Build the `reapply.reapply` inputs for one job's response payload.

  Args:
    jdir: Job-bundle directory the response's `result` path resolves against.
    request: Parsed `request.json` contents.
    response: Parsed `response.json` contents.
    document: The review document this job targets.

  Returns:
    An `(agent_body, phase, owned_owner, attachments)` tuple — the first three ready to pass
    into `reapply.reapply`, the fourth the attachment basenames this response delivered,
    resolved once here so the caller never re-reads the array. `mode == "main"` yields a
    main-writer's full document body — every `result/<file>` link already rewritten to the
    neighbour name its attachment takes beside the document — with `owned_owner` `None`; any
    other mode (`"validation"` / `"terminal"`) yields the body wrapped in the owned section's
    heading and ownership tag, with `owned_owner` identifying that section and no
    attachments.

  Raises:
    PayloadError: When any `result` entry — the document's own included — resolves to anything
      but a plain deliverable file inside the bundle that is safe to land.
  """
  # the document entry is contained exactly like an attachment: one plain filename inside the
  # bundle's own result/ dir, read through the payload contract's single checker
  result_name = _payload.attachment_basename(response[JobKey.RESULT][0])
  result_source = jdir / _RESULT_DIR / result_name
  _require_entry_lands(result_source, None, document)
  attachments = _attachment_names(request, response, jdir, document)
  # the payload is processed as LF like the document; `collect_for_file` gives it the document's
  # own ending on write
  result_text = _atomic_io.read_text(result_source).replace("\r\n", "\n")
  _result_meta, result_body = _fm.parse(result_text)

  # a main-writer payload is the full document body, no owned section
  if request.get(JobKey.MODE) == Phase.MAIN:
    return _fix_attachment_links(result_body, attachments, jdir), Phase.MAIN, None, attachments

  # wrap the response body in the owned section's heading and ownership tag, per _reassemble_section
  section_id = request[JobKey.SECTION_ID]
  flat_expert = _parser.flatten_expert_name(request[JobKey.EXPERT])
  owner = (flat_expert, section_id)
  title = request.get(JobKey.SECTION) or section_id.replace("_", " ").capitalize()
  owner_tag = f"{Tag.EXPERT_PREFIX}{flat_expert}/{section_id}"
  stripped = result_body.strip("\n")
  agent_body = f"# {title}\n{owner_tag}\n\n{stripped}\n" if stripped else f"# {title}\n{owner_tag}\n"
  return agent_body, Phase.SECTION, owner, attachments


def _apply_one_job(
    text: str, jdir: Path, request: dict, response: dict, document: Path, ending: str,
) -> tuple[str, list[str]] | None:
  """
  Apply one DONE job's response to `text`.

  Args:
    text: Current document text (frontmatter + body), LF outside its fenced code blocks.
    jdir: Job-bundle directory the response's `result` path resolves against.
    request: Parsed `request.json` contents.
    response: Parsed `response.json` contents.
    document: The review document this job targets, which the attachments land beside.
    ending: The document's line ending, which the payload's fenced code blocks take.

  Returns:
    A `(document_text, attachments)` tuple — the updated document text and the attachment
    basenames the response delivered — or `None` when the response's outcome is not `edited`,
    carries no `result`, or the payload is otherwise malformed (an entry that is not a plain
    filename, one the bundle never wrote or symlinked, or one that would overwrite the
    document or a spec note). A job with a non-`edited` outcome is left uncollected for a
    future pass to interpret; the caller retires an `edited` job that yields `None` and reports
    it as failed.

  Raises:
    OSError: When a result file of the bundle cannot be read right now; it is not turned into `None`, so the
      caller can leave the job for a later pass.
  """
  # guard: only a completed edit carries content to land; empty/error responses are left uncollected
  if response.get(JobKey.OUTCOME) != Outcome.EDITED:
    return None

  # guard: outcome=edited without a result payload is a malformed response — nothing to apply; the
  # caller retires the job and reports it as failed
  if not isinstance(result := response.get(JobKey.RESULT), list) or not result:
    return None

  # a malformed request (e.g. `section_id` without a matching `expert`) or a malformed
  # attachment entry yields nothing to apply either, and the caller retires the job the same way;
  # a result file that cannot be read right now is no verdict on the job, so that error goes up
  try:
    agent_body, phase, owner, attachments = _build_agent_body(jdir, request, response, document)
  except (KeyError, PayloadError):
    return None

  # the payload's fenced blocks take the document's ending now, since the write-back conversion
  # never reaches inside a fence; every other line stays LF through the whole pipeline
  agent_body = _atomic_io.to_fence_ending(agent_body, ending)

  # a fence the agent left open would swallow every operator section grafted after the payload
  agent_body = _parser.close_open_fence(agent_body, ending)
  section_layout = (
      {owner: request[JobKey.POSITION]} if owner is not None and JobKey.POSITION in request else None
  )

  # graft the response onto the operator's current document via the existing reapply pipeline
  reapply_result = _reapply.reapply(
      operator_text = text,
      agent_body = agent_body,
      phase = phase,
      agent_frontmatter_overlay = {},
      owned_owner = owner,
      section_layout = section_layout,
  )

  # an answered question or decision-candidate is a settled decision the round just folded —
  # the callout must not survive it, or the next wake reads the same tick as fresh operator
  # input and reopens forever, and finalize refuses a document still carrying the candidate
  _landed_meta, landed_body = _fm.parse(reapply_result.text)
  stripped_body = _body.strip_answered_questions(landed_body)

  # nothing answered in this round — the landed text is already final
  if stripped_body == landed_body:
    return reapply_result.text, attachments
  return reapply_result.text[:len(reapply_result.text) - len(landed_body)] + stripped_body, attachments


# ------------------------------------------------------------- consume (§1c)


def _restore_attachments(
    repo: Path, folder: Path, names: list[str], earlier: list[dict[str, bytes]], tracked: set[str],
) -> bool:
  """
  Put attachments back to the state they had before the jobs being taken out of a landing wrote them.

  Each name returns to what the earlier jobs of the same call left under it, or, when none of them wrote it, to its
  committed version, or is removed when it was new.

  Notes:
    - An attachment that cannot be put back is named on stderr, and the others are still put back.
    - Never raises `OSError`.

  Args:
    repo: Absolute path to the repository root.
    folder: The folder the attachments lie in, beside the document.
    names: The attachment names to put back.
    earlier: What each earlier job of this call that stays landed wrote, in landing order: name to bytes.
    tracked: The attachment names that were tracked, unmodified files when the call began.

  Returns:
    `True` when every named attachment is back in its earlier state; `False` when at least one could not be put
    back.
  """
  # whether every attachment is back in its earlier state
  is_restored = True

  # each name goes back on its own
  for name in names:
    dest = folder / name

    # one attachment that cannot be put back must not stop the others; it is named, never passed over in silence
    try:
      held = next(( written[name] for written in reversed(earlier) if name in written ), None)

      # what an earlier job of this call wrote comes back from memory
      if held is not None:
        _atomic_io.write_bytes_atomic(dest, held)

      # a file the call found tracked and unmodified gets its committed version back
      elif name in tracked:
        _git_ops.restore_from_head(repo, dest)

      # a name that was new goes, unless its write never happened or something else now sits there
      elif dest.is_file():
        dest.unlink()
    except (OSError, GitOpsError) as error:
      sys.stderr.write(f"collect-job: attachment {dest} could not be put back ({type(error).__name__}: {error})\n")
      is_restored = False
  return is_restored


def _folder_in_repo(repo: Path, file_path: Path) -> Path:
  """
  Work out the repo-relative folder of a review document.

  Args:
    repo: Absolute path to the repository root.
    file_path: Absolute path to the review document.

  Returns:
    The document's folder relative to the repository root, taken from the path as given, normalised.

  Raises:
    ValueError: When the folder is not inside the repository, as given or once its links are followed, or
      cannot be resolved.
  """
  folder = Path(os.path.normpath(file_path.parent))

  # a folder that leaves the repository through a link is outside it too: git answers for nothing there
  try:
    is_inside = folder.is_relative_to(repo) and folder.resolve().is_relative_to(repo.resolve())
  except RuntimeError as error:
    raise ValueError(f"the document's folder {folder} cannot be resolved: {error}") from error

  # guard: nothing is landed for a document outside the repository
  if not is_inside:
    raise ValueError(f"the document's folder {folder} is not inside the repository {repo}")
  return folder.relative_to(repo)


def _read_attachment_states(
    repo: Path, rel_folder: Path, candidates: list[Path],
) -> tuple[set[str], set[str], set[str]]:
  """
  Ask git, before anything is written, about every file an attachment of the jobs may replace, and name the paths
  asked about.

  Args:
    repo: Absolute path to the repository root.
    rel_folder: The document's folder relative to the repository root; the attachments land in it.
    candidates: The job bundles about to be landed.

  Returns:
    Three sets: the repo-relative paths git cannot give back as they lie (untracked, ignored, modified, staged or
    deleted); the bare names of the attachments that are tracked, unmodified files right now; and every
    repo-relative attachment path git was asked about. An attachment whose path is in the first set or whose name is
    in the second is a file git knows; any other asked-about path is a new file. A bundle whose files cannot be
    read adds no path, so its job is held back by the landing.

  Raises:
    ValueError: When git cannot be launched or fails.
  """
  paths: set[str] = set()

  # the names are read ahead of the landing from every main writer's completed edit; a bundle that cannot be
  # read and an entry that names no plain file add nothing here, and each job is judged by the landing itself
  for jdir in candidates:
    try:
      request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
      response = json.loads((jdir / JobFile.RESPONSE).read_text(encoding = "utf-8"))
      is_writer_edit = response.get(JobKey.OUTCOME) == Outcome.EDITED and request.get(JobKey.MODE) == Phase.MAIN
      entries = response[JobKey.RESULT][1:] if is_writer_edit else []
    # waiver: a bundle's own files are untrusted data — whatever their content raises is the landing's to judge
    except Exception:  # pylint: disable=broad-exception-caught
      continue
    for entry in entries:
      try:
        paths.add((rel_folder / _payload.attachment_basename(entry)).as_posix())
      except (PayloadError, TypeError, ValueError):
        continue

  # guard: a batch that puts nothing beside the document asks git nothing
  if not paths:
    return set(), set(), set()

  # git is asked once for every path; a path it reports is one whose present content it could not give back.
  # A git that cannot be launched, or that fails, leaves the question open for every job, so the call stops
  try:
    dirty = set(_git_ops.read_status(repo, [ repo / path for path in sorted(paths) ]))
  except (GitOpsError, OSError) as error:
    raise ValueError(f"the attachment paths cannot be checked against git: {error}") from error
  return dirty, { Path(path).name for path in paths - dirty if (repo / path).is_file() }, paths


def _land_attachments(payloads: dict[str, bytes], dest_dir: Path) -> None:
  """
  Write each attachment into a directory under its own name.

  Notes:
    - Nothing is undone by this call: when a write fails, the error propagates and the undo is left to the caller.

  Args:
    payloads: The attachments, mapping each file name to its bytes.
    dest_dir: The directory the attachments land in.

  Raises:
    OSError: When a write fails; the names after it are not written.
  """
  # each name is written in declaration order
  for name, content in payloads.items():
    # limit: overwrites any same-named file, authorship unchecked — record the writer per attachment if strays appear
    # the bytes are swapped in whole: a write that fails part-way leaves no part of them under the name
    _atomic_io.write_bytes_atomic(dest_dir / name, content)


def consume_job(repo: Path, jdir: Path) -> None:
  """
  Mark one job bundle consumed.

  Guarantees:
    - A job is marked consumed by the core CLI and by nothing else. When core cannot be reached or refuses, the call
      raises `JobConsumeError` and the bundle is left exactly as it was; this module never writes the consumed
      marker itself.

  Args:
    repo: Absolute path to the repository root.
    jdir: Job-bundle directory to consume; its parent/own directory names are the expert
      and job id the `consume-job` CLI call needs.

  Raises:
    JobConsumeError: When the core CLI cannot be resolved, cannot be launched, or exits non-zero.
  """

  # Contract:
  # A job is marked consumed by the core CLI and by nothing else.
  # When core cannot be reached or refuses, the call raises `JobConsumeError` and the bundle is left exactly
  # as it was; this module NEVER writes the consumed marker itself.

  # Domain(review.jobs):
  # # Only the queue's owner retires a job
  # A finished job counts as retired only when the owner of the job queue says so. The owner records the
  # retirement in its own ledger first, so a retirement written past the owner would be one the owner knows
  # nothing about. When the owner cannot be reached or refuses, the job stays finished and is left for a later
  # pass.

  # guard: without the core CLI nothing may mark the job consumed
  try:
    cli = _git_ops.require_core_cli(repo)
  except RuntimeError as error:
    raise JobConsumeError(f"{CoreCommand.CONSUME_JOB} {_job_ref(jdir)}: {error}") from error

  # core owns the bundle's markers and the ledger entry it writes before the marker; its output is taken as
  # bytes, so the exit code alone says whether the job was consumed, whatever core printed
  env = os.environ.copy()
  env[EnvVar.LAZY_REPO_ROOT] = str(repo)
  try:
    proc = subprocess.run(
        [sys.executable, str(cli), CoreCommand.CONSUME_JOB],
        input = json.dumps({JobKey.EXPERT: jdir.parent.name, JobKey.JOB_ID: jdir.name}).encode("utf-8"),
        capture_output = True, env = env, check = False,
    )
  except OSError as error:
    raise JobConsumeError(
        f"{CoreCommand.CONSUME_JOB} {jdir.parent.name}/{jdir.name} could not be launched: {error}"
    ) from error

  # guard: core refused — the job stays as it is for a later pass
  if proc.returncode != 0:
    raise JobConsumeError(
        f"{CoreCommand.CONSUME_JOB} {jdir.parent.name}/{jdir.name} failed: "
        f"{(proc.stderr or proc.stdout).decode('utf-8', errors = 'replace').strip()}"
    )


# ------------------------------------------------------------------- collect


def collect_for_file(repo: Path, file_path: Path) -> dict:
  """
  Land every DONE-and-not-CONSUMED job targeting `file_path` into the working tree.

  Runs inside the coordinator's own wake. The document's finished jobs are applied in order, expert folders first and
  bundles within each in sorted order, the `active_job` marker is cleared, the document is written once, and only
  then are the jobs consumed in that same order: the applied jobs first, then the ones that could not be applied.
  A job whose attachments could not all be put back is not consumed in that call, and neither is a job held back
  because git was not asked about one of its attachment paths.
  Nothing is committed and no pending wake is raised — the wake being served is the one that asked for this landing,
  and the coordinator's own `commit-doc` carries the result. A failed write leaves every job unconsumed and undoes
  the attachments while the error propagates. An undo returns each attachment to what an earlier job of the same call
  that stays landed wrote under its name, else to its committed version, else removes it when it was new; one that
  cannot be put back is named on stderr, and its job is left finished and unconsumed and listed under `unfinished`.
  Nothing is stored between calls.

  A consume of an applied job that core refuses raises `JobConsumeError` out of the call. The jobs before it stay
  applied and consumed, the document is rewritten to the text holding exactly their results, and the attachments of
  the refused job and of every later job are undone. The error carries in its `summary` what did land, and the jobs
  taken out are still finished, so the next call lands them. When that rewrite itself fails, the results stay in the
  document and their attachments stay beside it.

  Guarantees:
    - An `empty` job is consumed and counted with the document left byte-identical.
    - Nothing is committed and no `pending_wake` is raised, whatever the batch holds.
    - One finished job whose result cannot be applied never stops the other finished jobs of the document from
      landing, and is never left behind: it is consumed and named under `failed` with its reason, and an edit that
      cannot be applied is traced on stderr and named the same way.
    - A document whose folder is not inside the repository, as given or once its links are followed, is refused
      before anything else happens: `ValueError` is raised, nothing is written, and no job is consumed. A folder
      that cannot be resolved at all is refused the same way. The folder is judged from the path as given,
      normalised.
    - Before anything is written, git is asked once about every path an attachment of a main writer's completed
      edit may take. Each path is asked about literally, never as a pattern; untracked and ignored files are found
      whatever the repository's own status settings say, and a file is named by its own path, not by an ignored
      folder above it. When git cannot be asked (it cannot be launched or it fails), the whole call is refused:
      `ValueError` is raised, nothing is written, the document is left unchanged, and no job is consumed. A job one
      of whose attachment paths git was not asked about, because its files could not be read ahead of the landing,
      is held back for that call: nothing of it is written, it is not consumed and not named under `failed`, one
      stderr line names it, and a later pass lands it. A job whose attachment name cannot be encoded as a file name
      is unappliable and retired under `failed`, and never stops the call.
    - A job that passes every other landing check (its result reads and applies, its entries are acceptable) but
      one of whose attachment paths is untracked, ignored, modified, staged or deleted is unappliable: nothing of
      it is written, neither document text nor attachment. It is consumed and named under `failed`, its reason
      names each such repo-relative path, and the other jobs of the batch still land. Such a job never stops the
      call and is not met again by a later call. A job that fails another landing check first is judged by that
      check alone, whatever lies under its attachment names. The earlier version of every file an attachment
      replaces must be one git can give back, since the undo relies on it.
    - A job bundle whose `request.json`, `response.json`, result document or result attachment cannot be read
      right now (reading raises `OSError`) is left uncollected and unconsumed, traced on stderr, and not named
      under `failed`; a later pass retries it.
    - A job's result lands whole or not at all: when one of its attachments cannot be put beside the document,
      its document text is not landed, every attachment of the job already written in this pass is undone as the
      undoing bullet below states, its attachment paths are not reported under `landed`, and the job is consumed
      and named under `failed`; the other jobs of the batch still land. One exception: when that undo itself cannot
      put every attachment back, the bullet on an attachment that cannot be put back states what holds, and the job
      is then not retired in that call.
    - Finding the finished jobs of the document never raises and is never stopped by what is not its finished work.
      A bundle that is not finished or is already consumed, dead or cancelled is not read at all. A finished bundle
      whose own request can never be used, because it is not a request object or it names a target that cannot be
      turned into a path, is stepped over with one stderr line, and the sweep retires it. A bundle whose files
      cannot be read right now is stepped over with one stderr line and left for a later pass. A job-marker sidecar
      that exists but cannot be read, or that reads but is no store, is never read as "no document": a bundle
      addressed only through it is stepped over the same way, with one stderr line, and left uncollected. A queue
      folder that cannot be listed is stepped over with one stderr line.
    - A batch in which at least one job applied lands whole or not at all. The `active_job` marker is cleared first
      and the document is written second, and only when its text changed. When either write raises, every
      attachment this call put beside the document is undone as the undoing bullet below states, no job of the
      batch is consumed, and the error propagates, so a later pass lands the whole batch again. A batch in which
      no job applied writes nothing and retires its failed jobs at once.
    - Taking jobs out of a landing (a refused consume of job k takes out k and every later job), undoing one job
      whose attachment write failed part-way, and undoing everything after a failed marker or document write put
      every attachment concerned back to the state it had before those jobs wrote it. A name goes back to the bytes
      an earlier job of the same call that stays landed wrote under it. For a name no such job wrote, it goes back
      to the committed version of a file that was tracked when the call began, restored into the working tree only,
      or is removed when the name was new. A failed put-back of one attachment raises nothing of its own: that
      attachment is named on stderr, the other attachments are still put back, and the error that caused the undo,
      if there is one, stays the one raised.
    - A job whose own attachment write failed, and whose attachments could then not all be put back, is not retired
      in that call: it stays finished and unconsumed, is named on stderr, and is listed in the summary under
      `unfinished` as `<expert>/<job id>`. It is not listed under `failed`. After a refused consume, when the
      document was rewritten but an attachment of the jobs taken out could not be put back, the jobs taken out are
      listed under `unfinished` in the `JobConsumeError` summary. The key is absent when there is no such job, and
      `collect-job` exits 1 when a returned summary carries it, so a landing whose summary carries it must not be
      committed. The working tree is then dirty. Under the daemon,
      its working-tree check stops on it and its discard restores it, after which a later pass lands the unconsumed
      jobs again.
    - A `main` job with outcome `edited` or `empty` on a report-class document whose response carries no
      `plan_verdict`, or one that is neither `sufficient` nor `new-plan`, is a job whose result cannot be applied:
      its reason names the field. The verdict of the last applied such job is stored as the document's `verdict` job
      marker under the document's repository root, in the write that clears `active_job` when the call's repository
      is that root; a batch without one leaves the stored verdict as it was. On any
      other class the field is ignored. When the document has finished jobs and its review settings cannot be read,
      the call is refused with `ValueError` before anything is written: no job is consumed and the next pass
      retries; such settings are never read as "not a report".
    - A job whose result cannot be applied is, when the call returns, consumed and named under `failed` with its
      reason, and nothing of its result is in the document. When the call raises instead, the jobs of this kind
      not yet consumed stay finished, are not listed under `failed`, and the next pass reports them.
    - A refused consume of a job whose result could not be applied leaves that job finished; it is not listed under
      `failed` in that call's summary, and the next pass reports it.
    - For a job whose result can be applied, after any call that returns, or raises without the double fault
      below, the result is in the document if and only if that job is consumed; the one other exception is a
      process killed between the writes and a job's consume. Such a kill leaves the document and the attachments
      written in the working tree with the jobs unconsumed: the tree is dirty, and under the daemon its working-tree
      check stops on it and its discard rolls it back, after which a later pass lands those jobs again. Jobs are
      consumed in the order they were applied, and only through core. When the consume of one job is refused, the
      jobs before it stay applied and consumed, and the document is rewritten to the text holding exactly their
      results (the text as it was read when the refused job is the first). The document is rewritten first, and
      only after that succeeded are the attachments of the refused job and of every later job undone, as the
      undoing bullet above states. `JobConsumeError` is raised carrying, in its `summary`, what did land. The jobs
      taken out are still finished, so the next pass lands them: a discarded tick whose consumes are rolled back
      therefore re-lands exactly those jobs, and no job whose result can be applied is retired while its result is
      missing from the document.
    - Double fault: when the corrective rewrite itself fails, the original `JobConsumeError` is still the one
      raised and its `summary` carries the key `unconsumed`, a list of `"<expert>/<job id>"` in landing order of
      the jobs whose results are in the document while unconsumed: the refused job and every later applied job.
      The key is absent from every summary without a double fault, so a document whose summary carries it must not
      be committed. The attachments of those jobs stay beside the document so its links to them hold, stderr names
      the jobs, and a later pass may apply them a second time.

  Args:
    repo: Absolute path to the repository root.
    file_path: Absolute path to the review document.

  Returns:
    `{"collected": N}` — the number of jobs landed by this call: `edited` payloads applied plus `empty` writers
    drained; jobs retired under `failed` are not counted. A batch that put
    attachments beside the document carries the additional `"landed"` key listing their repo-relative paths; a
    batch that landed none omits the key entirely, so a document-only landing reports the summary it always
    has. When some job's result could not be applied, the summary also carries a `"failed"` key listing one
    `{job_id, reason}` entry per such job, and omits it otherwise; the reason of a job whose attachment would
    replace a file git cannot give back names each such repo-relative path. This holds for the
    `{"collected": 0}` result too. When some finished job was left unconsumed because an attachment of it could
    not be put back, the summary also carries an `"unfinished"` key listing them as `<expert>/<job id>`, and omits
    it otherwise; a caller must not commit a landing whose summary carries it. The document is left untouched
    when `N` is `0`. A returned summary never carries `"unconsumed"`; that key rides only on
    `JobConsumeError.summary`, as stated under `Raises`.

  Raises:
    OSError: When the document cannot be read, or when the marker sidecar or the document cannot be written; the
      attachments this call put beside the document were undone and no job was consumed.
    JobConsumeError: When core refuses a consume or cannot be reached for it; its `summary` says what landed,
      carries `"unfinished"` when an attachment of the jobs taken out could not be put back (such a landing is
      not to be committed), and the results of the unconsumed jobs were taken out again. When
      that corrective rewrite itself fails (a double fault), the `summary` additionally carries `"unconsumed"`, a
      list of `"<expert>/<job id>"` in landing order naming the jobs whose results are in the document while
      unconsumed; the key is absent otherwise.
    RuntimeError: When the document has finished jobs and no core CLI is resolvable to read its review class;
      nothing is written and no job is consumed.
    ValueError: When the document has finished jobs and its review settings cannot be read, or when the document is
      not UTF-8 text (`UnicodeDecodeError`), or when its folder is not inside the repository, as given or once its
      links are followed, or cannot be resolved, or git cannot be launched or fails; nothing is written, nothing is
      applied and no job is consumed.
  """

  # Domain(review.jobs):
  # # An empty verdict still closes the round
  # A section writer that finds nothing to change is not a failure to land — its verdict is
  # consumed exactly like a writer that produced an edit, only without touching the document.
  # A batch made entirely of such empty verdicts leaves the document untouched: the round
  # still closes within the same wake, but nothing new enters the document's history.

  # Contract:
  # Finding the finished jobs of the document NEVER raises and is NEVER stopped by what is not the document's
  # finished work. A bundle that is not finished or is already consumed, dead or cancelled is not read at all.
  # A finished bundle whose own request can never be used, because it is not a request object or it names a
  # target that cannot be turned into a path, is stepped over with one stderr line, and the sweep retires it.
  # A bundle whose files cannot be read right now is stepped over with one stderr line and left for a later pass.
  # A job-marker sidecar that exists but cannot be read, or that reads but is no store, is NEVER read as "no
  # document": a bundle addressed only through it is stepped over the same way, with one stderr line, and left
  # uncollected.
  # A queue folder that cannot be listed is stepped over with one stderr line.

  # Contract:
  # A document whose folder is not inside the repository, as given or once its links are followed, is refused
  # before anything else happens: `ValueError` is raised, nothing is written, and no job is consumed.
  # A folder that cannot be resolved at all is refused the same way.
  # The folder is judged from the path as given, normalised.

  # a document outside the repository is refused here, before anything is written
  rel_folder = _folder_in_repo(repo, file_path)

  # every DONE bundle targeting the document is a landing candidate
  candidates =[jdir for jdir in _job_dirs_for_file(repo, file_path) if read_job_status(jdir) == JobStatus.DONE]

  # Contract:
  # Before anything is written, git is asked once about every path an attachment of a main writer's completed edit
  # may take. Each path is asked about literally, never as a pattern; untracked and ignored files are found whatever
  # the repository's own status settings say, and a file is named by its own path, not by an ignored folder above it.
  # When git cannot be asked (it cannot be launched or it fails), the whole call is refused: `ValueError` is raised,
  # nothing is written, the document is left unchanged, and no job is consumed.
  # A job one of whose attachment paths git was not asked about, because its files could not be read ahead of the
  # landing, is held back for that call: NOTHING of it is written, it is NOT consumed and NOT named under `failed`,
  # one stderr line names it, and a later pass lands it.
  # A job whose attachment name cannot be encoded as a file name is unappliable and retired under `failed`, and
  # NEVER stops the call.

  # git is asked once, before anything is written, which files an attachment may replace it can give back;
  # each job is then judged by the answer for its own attachments
  dirty, tracked, asked = _read_attachment_states(repo, rel_folder, candidates)

  # the document text accumulates payloads across the batch; `steps` keeps, per applied job in order, what
  # the text was before it and what it wrote beside the document
  # the ending is decided once from the file as read; every payload is applied to the LF text
  original = _atomic_io.read_text(file_path)
  text, ending = _atomic_io.to_lf(original)
  steps: list[_Step] = []

  # the jobs whose result could not be applied, each with the reason the caller is told
  failed: list[tuple[Path, str]] = []

  # the jobs left finished and unconsumed because an attachment could not be put back to its earlier state
  unfinished: list[str] = []

  # Contract:
  # When the document has finished jobs, its review class is read before anything is written. Settings that cannot
  # be read refuse the whole call with `ValueError`: nothing is written, no job is consumed, and every job stays
  # finished for the next pass. They are NEVER read as "not a report".

  # whether the document is a report is read once, before any job, so unreadable settings or an unreachable core
  # refuse the call instead of failing each job; the plan verdict of the last applied main job is what the marker
  # write stores
  is_report = bool(candidates) and _is_report_document(file_path)
  verdict: str | None = None

  # Contract:
  # A DONE job with `outcome == "empty"` is consumed and counted with the document left
  # byte-identical: no text change is applied for it, and a batch of only-empty jobs still
  # clears the `active_job` marker — the round closes instead of stranding the marker until
  # the daily sanitizer.

  # apply each parseable bundle: `edited` lands its payload, `empty` is drained content-free
  for jdir in candidates:

    # Contract:
    # One finished job whose result cannot be applied never stops the other finished jobs of the
    # same document from landing, and is never left behind: it is consumed and named under
    # `failed` with its reason, so the caller decides the turn instead of the sweep re-raising it.

    # the per-job boundary — a bundle of the wrong shape or with an unparsable result is this
    # job's own failure, and `text` is only replaced once a job has applied cleanly
    try:
      request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
      response = json.loads((jdir / JobFile.RESPONSE).read_text(encoding = "utf-8"))

      # Contract:
      # A `main` job that will be consumed (outcome `edited` or `empty`) on a report-class document MUST carry
      # `plan_verdict` set to `sufficient` or `new-plan`. A job without it, or with any other value, is retired
      # under `failed` with a reason naming the field, and nothing of it lands. On any other class, and on any
      # other mode, the field is ignored.

      # a report's main writer owes a plan verdict, and a job that withholds it lands nothing
      job_verdict: str | None = None
      is_consumable = response.get(JobKey.OUTCOME) in (Outcome.EDITED, Outcome.EMPTY)
      if is_report and is_consumable and request.get(JobKey.MODE) == Phase.MAIN:
        reason = _verdict_failure(response)
        # guard: a missing or unknown verdict retires the job as failed, and nothing of it lands
        if reason is not None:
          sys.stderr.write(f"collect-job: {jdir}: {reason}\n")
          failed.append(( jdir, reason ))
          continue
        job_verdict = response[JobKey.PLAN_VERDICT]

      # an `empty` writer finished with nothing to change — count it for consumption as-is
      if response.get(JobKey.OUTCOME) == Outcome.EMPTY:
        steps.append(_Step(jdir, text, {}, []))
        verdict = job_verdict or verdict
        continue
      outcome_applied = _apply_one_job(text, jdir, request, response, file_path, ending)

      # the attachments are read here, inside the boundary: one that cannot be read right now leaves the
      # job queued like any other unreadable bundle file
      payloads = {
          name: (jdir / _RESULT_DIR / name).read_bytes() for name in (outcome_applied[1] if outcome_applied else ())
      }
    except OSError as error:

      # Contract:
      # A job whose `request.json`, `response.json`, result document or result attachment cannot be read right
      # now (reading raises `OSError`) is left uncollected and unconsumed and is traced on stderr. It is NEVER
      # named under `failed`, so a later pass retries it.

      # the bundle's files cannot be read right now — that is not a verdict on the job's result,
      # so the job is left as it is for a later pass, traced but not retired
      sys.stderr.write(f"collect-job: {jdir}: {type(error).__name__}: {error}\n")
      continue
    # waiver: the per-job boundary catches every failure type on purpose — a narrower list is
    # what let one wrong-shaped bundle block the landing of its neighbours
    except Exception as error:  # pylint: disable=broad-exception-caught
      sys.stderr.write(f"collect-job: {jdir}: {type(error).__name__}: {error}\n")
      failed.append(( jdir, f"{type(error).__name__}: {error}" ))
      continue

    # an edit whose payload could not be applied is this job's failure too; any other outcome
    # with nothing to apply is not this verb's to judge and stays uncollected
    if outcome_applied is None:
      if response.get(JobKey.OUTCOME) == Outcome.EDITED:
        sys.stderr.write(f"collect-job: {jdir}: {_UNAPPLIED_EDIT_REASON}\n")
        failed.append(( jdir, _UNAPPLIED_EDIT_REASON ))
      continue

    # Contract:
    # A job that passes every other landing check (its result reads and applies, its entries are acceptable) but one
    # of whose attachment paths is untracked, ignored, modified, staged or deleted is unappliable: NOTHING of it is
    # written, neither document text nor attachment. It is consumed and named under `failed`, its reason names each
    # such repo-relative path, and the other jobs of the batch still land. Such a job NEVER stops the call and is not
    # met again by a later call.
    # A job that fails another landing check first is judged by that check alone, whatever lies under its attachment
    # names.
    # The earlier version of every file an attachment replaces must be one git can give back, since the undo relies
    # on it.

    # guard: an attachment path git was never asked about (the job's files could not be read ahead of the
    # landing) says nothing about what lies there now; the job is held back, unconsumed and unreported under
    # `failed`, for a later pass that can ask
    unasked = sorted(path for name in payloads if (path := (rel_folder / name).as_posix()) not in asked)
    if unasked:
      sys.stderr.write(f"collect-job: {jdir}: {_UNASKED_ATTACHMENT_REASON}: {', '.join(unasked)}\n")
      continue

    # a job that passed every other check is refused here when an attachment of it would replace a file git
    # cannot give back: nothing of it is written, and the job is retired with the paths as its reason
    lost = sorted(path for name in payloads if (path := (rel_folder / name).as_posix()) in dirty)
    if lost:
      sys.stderr.write(f"collect-job: {jdir}: {_DIRTY_ATTACHMENT_REASON}: {', '.join(lost)}\n")
      failed.append(( jdir, f"{_DIRTY_ATTACHMENT_REASON}: {', '.join(lost)}" ))
      continue

    # Contract:
    # A job's result lands whole or not at all. When one of its attachments cannot be put beside the document,
    # its document text is NOT landed and every attachment of the job already written in this pass is undone as the
    # rule on undoing attachments states. The job's attachment paths are NEVER reported under `landed`, the job is
    # consumed and named under `failed`, and the other jobs of the batch still land.
    # One exception: when that undo itself cannot put every attachment back, the rule on an attachment that cannot
    # be put back states what holds, and the job is then NOT retired in that call.

    # the attachments ride the document: each lands beside it under its declared basename, and a job
    # whose attachment cannot be written is this job's own failure, with nothing of it left behind
    try:
      _land_attachments(payloads, file_path.parent)
    except OSError as error:
      sys.stderr.write(f"collect-job: {jdir}: {type(error).__name__}: {error}\n")

      # the job's attachments go back to what the earlier jobs of this call left; a job whose attachment
      # cannot be put back is not retired, so the failure stays visible and a later pass meets the job again
      if _restore_attachments(
          repo, file_path.parent, list(payloads), [ done.written for done in steps ], tracked,
      ):
        failed.append(( jdir, f"{_UNLANDED_ATTACHMENT_REASON}: {type(error).__name__}: {error}" ))
      else:
        sys.stderr.write(f"collect-job: {jdir}: left finished, an attachment could not be put back\n")
        unfinished.append(_job_ref(jdir))
      continue

    # the whole result is on disk or in hand now, so the job's text joins the batch; what the document
    # held before this job, and what the job wrote beside it, is kept so the job can be taken out again
    landed = [ str(rel_folder / name) for name in payloads ]
    steps.append(_Step(jdir, text, payloads, landed))
    text = outcome_applied[0]
    verdict = job_verdict or verdict

  # nothing landed — the document stays exactly as found, and the unappliable jobs are retired:
  # left unconsumed they would be counted as finished work by every later sweep
  if not steps:
    return _retire_failed(repo, failed, consumed = 0, landed = [], unfinished = unfinished)

  # the LF result takes the document's own line ending once, just before it is written
  text = _atomic_io.restore_ending(text, ending)

  # Contract:
  # Landing never creates a commit and never raises a `pending_wake`, whatever the batch holds.
  # The caller runs inside the wake that asked for the landing and owns the single commit that
  # carries the result; a commit here would split that result, and a new wake would re-wake the
  # caller for a landing it is already serving.

  # Contract:
  # A batch in which at least one job applied lands whole or not at all.
  # The `active_job` marker is cleared first and the document is written second, and only when its text changed.
  # When either write raises, every attachment this call put beside the document is undone as the rule on
  # undoing attachments below states, NO job of the batch is consumed, and the error propagates, so a later
  # pass lands the whole batch again.
  # A batch in which no job applied writes nothing and retires its failed jobs at once.

  # Contract:
  # Taking jobs out of a landing (a refused consume of job k takes out k and every later job), undoing one job whose
  # attachment write failed part-way, and undoing everything after a failed marker or document write put every
  # attachment concerned back to the state it had before those jobs wrote it.
  # A name goes back to the bytes an earlier job of the same call that stays landed wrote under it. For a name no
  # such job wrote, it goes back to the committed version of a file that was tracked when the call began, restored
  # into the working tree only, or is removed when the name was new.
  # A failed put-back of one attachment raises nothing of its own: that attachment is named on stderr, the other
  # attachments are still put back, and the error that caused the undo, if there is one, stays the one raised.

  # Contract:
  # A job whose own attachment write failed, and whose attachments could then not all be put back, is NOT retired
  # in that call: it stays finished and unconsumed, is named on stderr, and is listed in the summary under
  # `unfinished` as `<expert>/<job id>`. It is NOT listed under `failed`.
  # After a refused consume, when the document was rewritten but an attachment of the jobs taken out could not be
  # put back, the jobs taken out are listed under `unfinished` in the `JobConsumeError` summary.
  # The key is ABSENT when there is no such job, and `collect-job` exits 1 when a returned summary carries it, so a
  # landing whose summary carries it MUST NOT be committed.
  # The working tree is then dirty. Under the daemon, its working-tree check stops on it and its discard restores
  # it, after which a later pass lands the unconsumed jobs again.

  # Domain(review.jobs):
  # # A landing only replaces what the history can give back
  # A file that a result puts beside the document may replace an earlier file of the same name. Nothing is set aside
  # for it: a landing replaces only a file whose earlier version the document's recorded history already holds
  # unchanged, or puts a file where none was. Where landings normally run, the working copy matches what the history
  # records, so this holds there by itself for every file the history tracks, and the check mainly guards a landing
  # run anywhere else. It is not vacuous even there: the check that the working copy matches the history does not
  # look at a file the history deliberately leaves out, so such a file can lie beside the document in any setting.
  # The history is asked once, before the landing writes anything, about every file a result may replace, and the
  # answer is applied per result. A result that would replace a file the history does not hold exactly as it lies
  # there, because the history does not know it, deliberately leaves it out, it has changed since it was recorded, or
  # it was removed, is not landed at all: nothing of it is written, its job is retired as failed with those files
  # named as the reason, and the other results of the same landing still land. Retiring the job, rather than
  # refusing the landing, is what keeps it from meeting the same file again on every later landing.
  # A result that is unusable for another reason is judged by that reason alone, whatever lies under its file names.
  # Only when the history cannot be asked at all is the whole landing refused, with nothing written.
  # Taking a result back out returns each file it put beside the document to what was there before that result: the
  # file an earlier result of the same landing, which stays put there, wrote under that name; else the version the
  # history records; else nothing, when the file was new.
  # When a file cannot be returned that way, the job is not retired on the strength of that landing: it stays
  # finished and is reported as left unfinished. The working copy then differs from the recorded history, which is
  # noticed where landings normally run, and discarding the unrecorded changes puts everything back, after which the
  # job lands again.
  # A landing cut off part-way leaves unrecorded changes in the working copy and its jobs unretired. Nothing needs
  # recovering beyond the recorded history: the unrecorded changes are discarded and the jobs land again.
  # A document that is itself outside the repository is not landed at all.

  # Contract:
  # The plan verdict of the last applied main-writer job of a report-class document is stored as the document's
  # `verdict` job marker under the document's repository root, whatever repository the collect was given; when the
  # collect's repository is that root, the verdict is stored in the same write that clears `active_job`. A batch
  # with no such job leaves the stored verdict as it was.

  # the coordinator collects inside its own wake: worktree write only, its `commit-doc`
  # carries the result and no new wake is raised for a landing already being served
  is_written = False
  try:
    # the marker write that closes the writer's turn also carries the report's plan verdict, when one landed; the
    # verdict is keyed by the document's repository root, so a document in another, nested checkout gets it its own
    # write
    markers: dict[str, str | None] = { JobMarker.ACTIVE_JOB: None }
    verdict_repo = _finalize.query_repo_root_for(file_path)
    if verdict is not None and verdict_repo.resolve() == repo.resolve():
      markers[JobMarker.VERDICT] = verdict
    elif verdict is not None:
      _job_markers.update(verdict_repo, file_path, { JobMarker.VERDICT: verdict })
    _job_markers.update(repo, file_path, markers)
    if text != original:
      _atomic_io.write_text_atomic(file_path, text)
    is_written = True
  finally:
    if not is_written:
      # nothing of this pass stays beside the document either
      _restore_attachments(
          repo, file_path.parent, list(dict.fromkeys(name for step in steps for name in step.written)), [], tracked,
      )

  # Contract:
  # A job whose result cannot be applied is, when the call returns, consumed and named under `failed` with its
  # reason, and nothing of its result is in the document.
  # When the call raises instead, the jobs of this kind not yet consumed stay finished, are NOT listed under
  # `failed`, and the next pass reports them.

  # Contract:
  # A refused consume of a job whose result could not be applied leaves that job finished. It is NOT listed under
  # `failed` in that call's summary, and the next pass reports it.

  # Contract:
  # For a job whose result can be applied, after any call that returns, or raises without the double fault named
  # below, the result is in the document if and only if that job is consumed. The one other exception is a
  # process killed between the writes and a job's consume. Such a kill leaves the document and the attachments
  # written in the working tree with the jobs unconsumed: the tree is dirty, and under the daemon its working-tree
  # check stops on it and its discard rolls it back, after which a later pass lands those jobs again.
  # Jobs are consumed in the order they were applied.
  # When the consume of one job is refused, the jobs before it stay applied and consumed, and the document is
  # rewritten to the text holding exactly their results; when the refused job is the first, that is the text as
  # it was read.
  # The document is rewritten first, and only after that succeeded are the attachments of the refused job and of
  # every later job undone, as the rule on undoing attachments states. `JobConsumeError` is raised carrying, in
  # its `summary`, what did land.
  # The jobs taken out are still finished, so the next pass lands them: a discarded tick whose consumes are
  # rolled back therefore re-lands exactly those jobs, and no job whose result can be applied is retired while
  # its result is missing from the document.
  # Double fault: when the corrective rewrite itself fails, the original `JobConsumeError` is still the one
  # raised and its `summary` carries the key `unconsumed`, a list of `"<expert>/<job id>"` in landing order of
  # the jobs whose results are in the document while unconsumed: the refused job and every later applied job.
  # The key is ABSENT from every summary without a double fault, so a document whose summary carries it MUST NOT
  # be committed. The attachments of those jobs STAY beside the document so its links to them hold, stderr names
  # the jobs, and a later pass MAY apply them a second time.

  # Domain(review.jobs):
  # # A landed result and its job's retirement agree
  # Two rules apply side by side, depending on whether a job's result can be put into the document at all.
  # A job whose result can be put into the document: its result is in the document if and only if the job has been
  # retired. A landing puts the results in, then asks the owner of the job queue to retire the jobs one by one, in
  # the order their results went in. When the owner refuses one, the landing takes that job's result and the result
  # of every job after it back out of the document, so the document holds exactly the results of the retired jobs.
  # The jobs taken out are still finished, so the next landing lands them. Because the two always agree, nothing
  # has to be remembered between landings: work thrown away together with its retirements is simply landed again.
  # A job whose result cannot be put into the document: it is retired on purpose and reported as failed, and
  # nothing of it is in the document.
  # Two cases fall outside the first rule. When a result cannot be taken back out, the document holds a result
  # whose job is not retired, and whatever that result wrote beside the document stays there too, so the
  # document's references to it hold. When the process dies between writing the document and retiring a job, the
  # same happens, and the unrecorded changes it leaves in the working copy are discarded where landings normally
  # run. In both, a later landing may put the same result in a second time.

  # limit: a process killed between the document write and a job's consume leaves that job applied and
  # unconsumed, and the next pass applies it again — closing it needs the document write and the consume
  # in one transaction owned by the job queue

  # drain the queue only now that the result is on disk, in the order the jobs were applied
  consumed = 0
  for index, step in enumerate(steps):
    try:
      consume_job(repo, step.jdir)
    except JobConsumeError as error:
      # the document must hold exactly what is consumed: this job and every later one are taken out again
      kept_text = original if index == 0 else _atomic_io.restore_ending(step.text_before, ending)
      error.summary = _summarize(
          consumed, [ path for done in steps[:index] for path in done.landed ], [], unfinished,
      )
      left = [ _job_ref(later.jdir) for later in steps[index:] ]

      # results that could not be taken out are named for the caller, which must not commit the document
      if not _take_out(file_path, steps[index:], kept_text):
        error.summary[_UNCONSUMED] = left

      # the text no longer points at them, so their attachments go back to what the consumed jobs left; jobs
      # whose attachment could not be put back are named as left unfinished
      elif not _restore_attachments(
          repo, file_path.parent, list(dict.fromkeys(name for later in steps[index:] for name in later.written)),
          [ done.written for done in steps[:index] ], tracked,
      ):
        error.summary[_UNFINISHED] = unfinished + left
      raise
    consumed += 1
  all_landed = [ path for step in steps for path in step.landed ]
  return _retire_failed(repo, failed, consumed = consumed, landed = all_landed, unfinished = unfinished)


def _summarize(consumed: int, landed: list[str], failures: list[dict], unfinished: list[str]) -> dict:
  """
  Build the summary of a landing.

  Args:
    consumed: The number of jobs consumed.
    landed: The repo-relative paths of the attachments put beside the document.
    failures: One `{job_id, reason}` entry per job whose result could not be applied.
    unfinished: The jobs left unconsumed because an attachment could not be put back, as `<expert>/<job id>`; a
      landing carrying them is not to be committed.

  Returns:
    A summary with `collected`, plus `landed`, `failed` and `unfinished` only when they are non-empty; a landing
    whose summary carries `unfinished` is not to be committed.
  """
  # the landed and failed keys are additive: a batch that put no attachment beside the document
  # and lost no job reports the single-key summary it always has, so a caller reading only
  # `collected` sees no change
  # waiver: 'collected'/'landed' are this verb's own wire-shape keys, read by its callers
  return {
      "collected": consumed,
      **({"landed": landed} if landed else {}),
      **({_FAILED: failures} if failures else {}),
      **({_UNFINISHED: unfinished} if unfinished else {}),
  }


def _retire_failed(
    repo: Path, failed: list[tuple[Path, str]], *, consumed: int, landed: list[str], unfinished: list[str],
) -> dict:
  """
  Consume each job whose result could not be applied and list them in the landing's summary.

  Args:
    repo: Absolute path to the repository root.
    failed: Each job-bundle directory whose result could not be applied, with its reason.
    consumed: The number of jobs the landing already consumed.
    landed: The repo-relative paths of the attachments the landing put beside the document.
    unfinished: The finished jobs left unconsumed because an attachment could not be put back, as
      `<expert>/<job id>`.

  Returns:
    The landing's summary, listing the retired jobs under `failed` and the unconsumed ones under `unfinished`.

  Raises:
    JobConsumeError: When core refuses to consume one of the jobs; its `summary` lists only the failed jobs
      consumed so far.
  """
  # a job whose result could not be applied is retired and reported with its reason; one that core refuses
  # to retire stays finished and is reported by the next pass, so it is not in this pass's summary
  failures: list[dict] = []
  for jdir, reason in failed:
    try:
      consume_job(repo, jdir)
    except JobConsumeError as error:
      error.summary = _summarize(consumed, landed, failures, unfinished)
      raise
    failures.append({ JobKey.JOB_ID: jdir.name, _FAILED_REASON: reason })
  return _summarize(consumed, landed, failures, unfinished)


def _take_out(file_path: Path, steps: list[_Step], text: str) -> bool:
  """
  Take the given jobs' results out of the document again.

  Only the document is rewritten; the attachments of the taken-out jobs are left to the caller.

  Notes:
    - Never raises `OSError`: when the rewrite fails, one stderr line names the jobs whose results stay in the
      document while unconsumed.

  Args:
    file_path: Absolute path to the review document.
    steps: The jobs whose results are taken out.
    text: The document text to rewrite the document to.

  Returns:
    `True` when the results were taken out; `False` when the rewrite failed, so the results stay in the document
    and their attachments stay beside it.
  """
  # the document text goes first: while it still holds the results, their attachments must stay beside it
  try:
    if _atomic_io.read_text(file_path) != text:
      _atomic_io.write_text_atomic(file_path, text)
  except OSError as error:
    # the double fault: the results stay in the document while their jobs are unconsumed, their attachments
    # stay with them so the document's links hold, and the refused consume stays the error the caller sees
    names = ", ".join(_job_ref(step.jdir) for step in steps)
    sys.stderr.write(
        f"collect-job: {file_path}: could not take results out again ({type(error).__name__}: {error}); "
        f"in the document while unconsumed: {names}\n"
    )
    return False
  return True


def _job_ref(jdir: Path) -> str:
  """
  Name a job by its expert and its id.

  Args:
    jdir: The job-bundle directory.

  Returns:
    The job's name as `<expert>/<job id>`.
  """
  # two experts may carry a job of the same id, so a job is named by its expert and its id together
  return f"{jdir.parent.name}/{jdir.name}"


# ---------------------------------------------------------------------- tick


def _is_review_active(doc: Path) -> bool:
  """
  Tell whether a document is in the review loop.

  Args:
    doc: The review document.

  Returns:
    True when its frontmatter reads `review_active: true`; False otherwise, including a document that is missing or
    cannot be read right now (reading raises `OSError`).

  Raises:
    UnicodeDecodeError: When the document is not UTF-8 text.
    ParseError: When the document's frontmatter does not parse.
  """
  # a document gone or unreadable is in no review
  try:
    meta, _body = _fm.parse(_atomic_io.read_text(doc))
  except OSError:
    return False
  return str(meta.get(ReviewKey.ACTIVE, "")).strip().lower() == "true"  # waiver: frontmatter literal


def _is_review_bundle(jdir: Path) -> bool:
  """
  Report whether a finished bundle is the review plugin's own, judged from its core job manifest.

  Args:
    jdir: The job-bundle directory.

  Returns:
    True when the manifest lists one of the review plugin's own protocols; False when the bundle has no manifest,
    the manifest is no JSON object, or it lists none of them.

  Raises:
    OSError: When the manifest exists but cannot be read right now.
  """
  manifest = jdir / JobFile.CONFIG

  # guard: a bundle without a manifest carries no mark of this plugin
  if not manifest.is_file():
    return False

  # a manifest that cannot be read right now raises to the caller's boundary: that says nothing about whose job
  # it is, so it is never read as "another plugin's"
  config = _read_json_object(manifest)
  protocols = config.get(JobKey.PROTOCOLS) if config is not None else None

  # every review dispatch attaches one of this plugin's own protocols to the job
  return isinstance(protocols, list) and any(ref in _REVIEW_PROTOCOLS for ref in protocols)


def _read_json_object(path: Path) -> dict | None:
  """
  Read one JSON file of a job bundle as an object.

  Args:
    path: The bundle's `request.json` or `response.json`.

  Returns:
    The parsed object, or `None` when the file's content can never be read as an object: its bytes are not UTF-8
    text, its text is not JSON, or its JSON value is not an object.

  Raises:
    OSError: When the file cannot be read right now.
  """
  # an unreadable file raises `OSError` to the caller: that says nothing about what the file holds
  raw = path.read_bytes()

  # bytes that are not UTF-8 text, or text that is not JSON, will never become an object
  try:
    data = json.loads(raw.decode("utf-8"))
  except ValueError:
    return None

  # a request or a response is an object; any other JSON value carries no field to read
  return data if isinstance(data, dict) else None


def _require_results_readable(jdir: Path, response: dict) -> None:
  """
  Open every result file a job's response names, to prove each one can be read right now.

  The named files are the document result and any attachment that exists in the bundle's `result/` folder. A response
  with no result list, an entry that names no plain file, a name that no path can carry, a file the bundle never
  wrote, and a symlinked entry are passed over; the landing judges the symlink.

  Args:
    jdir: The job bundle directory.
    response: The parsed response object of the job.

  Raises:
    OSError: When a named result file exists in the bundle but cannot be opened.
  """
  entries = response.get(JobKey.RESULT)

  # guard: a response that names no result list has nothing to open; the landing judges its shape
  if not isinstance(entries, list):
    return
  for entry in entries:
    # an entry that names no plain file, or a name no path can carry, is a malformed result, which the
    # landing retires — not this check's; only a file that is there and cannot be opened raises
    try:
      path = jdir / _RESULT_DIR / _payload.attachment_basename(entry)

      # a file the bundle never wrote, and a symlink, are the landing's to judge too: it refuses a symlink
      # whatever it points at, so only a plain file that is there is opened
      if not path.is_symlink() and path.is_file():
        # waiver: 'rb' is the builtin binary-read file mode, not a domain token
        with path.open("rb"):
          pass
    except (PayloadError, ValueError, TypeError):
      continue


def collect_tick(repo: Path) -> dict:
  """
  Raise a `job-done` wake and dispatch the coordinator for every document in the review loop with finished work.

  The postman sweep no longer lands payloads or commits anything. For each target file
  carrying at least one DONE-and-not-CONSUMED job it clears the `active_job` marker, raises
  the `job-done` pending wake, and dispatches the coordinator directly (no git item is
  needed — nothing was committed). The coordinator lands the payload itself with
  `collect-job` inside its wake and commits once, payload and settle together.

  A target whose coordinator is still busy is left with its wake raised and its jobs still
  DONE — the next sweep retries the dispatch, so a died coordinator job cannot strand the
  landing. A bundle file that cannot be read right now, a target document whose frontmatter cannot be parsed, or a
  target whose dispatch raises, is logged to stderr, named in `error`, and retried on a future sweep — it does not
  stop the rest of the batch. A target document that is missing, or whose reading raises `OSError`, counts as outside
  the review loop and is skipped like one. A target document that is not UTF-8 text is logged to stderr and its
  bundle is named in `error`; no wake is raised for it and it is not counted in `files`, and a future sweep tries
  it again. A `response.json` that can never be read as a response object is named in `error`, and
  its document is still handed to the coordinator as finished work in the same sweep; the coordinator's landing
  retires the bundle. A finished bundle whose own request can never be used (not a
  request object, or naming a target that cannot be turned into a path) is named once and retired; when core
  refuses that consume it is named and tried again next sweep. A finished bundle that cannot be resolved to a
  document, the job-marker sidecar having been read as a store, is skipped silently only when it is not the review's
  own (its manifest lists no review protocol); a review bundle whose document nothing names is named in `error` on
  every pass and kept. A finished bundle with no `response.json` is skipped silently; when the sidecar cannot be read
  or reads but is no store, a bundle addressed only through it is left untouched and named in `error`. A sidecar
  that reads but is no store is set aside at the end of every pass.
  A job queue root that cannot be listed ends the sweep with zero counts and an `error` naming
  it. An expert folder that cannot be listed is named in `error` while the others are swept.

  Guarantees:
    - One bundle or target document that cannot be read never stops the sweep: a bundle is named in the summary's
      `error` and every other deliverable document is still dispatched in the same sweep.
    - A finished bundle whose own request can never be used is retired by the sweep that finds it. That is a request
      that is not a request object (not UTF-8 text, not JSON, or not a JSON object) or one that names a target
      that cannot be turned into a path. Such a bundle is consumed, named once in the summary's `error`, and never
      named by a later sweep. When core refuses that consume, the bundle is not consumed, is named in `error`, and
      the next sweep tries again. A bundle whose files merely cannot be read right now is not consumed: it is
      named in `error` on every sweep and left in place. A bundle whose target is a link loop counts as one that
      cannot be read right now, not as unusable.
    - A finished bundle of a known document whose `response.json` can never be read as a response object (not UTF-8
      text, not JSON, or not a JSON object) is handed to the coordinator as finished work and named in the summary's
      `error`, and the sweep never consumes it: the document is counted, its wake is raised, and the landing that
      follows retires the bundle and reports it as failed, after which no sweep names it. A `response.json` that
      merely cannot be read right now (reading raises `OSError`) is not handed over and not consumed; such a bundle
      is named in `error` on every sweep.
    - A finished bundle is handed over only when the landing will be able to read it. When a result file that an
      `edited` response names exists but cannot be read right now (opening it raises `OSError`), the bundle is not
      counted, not handed over and not consumed: it is named in `error`, and a later sweep hands it over once the
      file reads. A result entry that is a symlink is passed over by this check: the landing judges it. Other
      finished bundles of the same document are still handed over.
    - A DONE job bundle that cannot be resolved to a target file, the job-marker sidecar having been read as a
      store, is judged by its own core manifest. A bundle whose manifest lists one of the review plugin's own
      protocols is the review's own: it is named in the summary's `error` and on stderr on every pass, and is
      never consumed, never counted, never woken for and never skipped silently, until the operator resolves it.
      A bundle without a manifest, or whose manifest lists no review protocol, belongs to another plugin's
      pipeline and is skipped silently: never counted, never written to stderr, and never surfaced as an `error`.
      A manifest that cannot be read right now is never read as another plugin's: the bundle is named in `error`
      and kept. Neither kind blocks the rest of the batch.
    - A job-marker sidecar that exists but cannot be read, or that reads but is no store, is never read as
      "no row": a bundle addressed only through it is never skipped silently as foreign. It is left untouched, not
      consumed, not counted, with no wake raised and not retired, and is named in the summary's `error`.
    - Every pass, also with no job queue and when the queue root cannot be listed, ends by setting aside a
      job-marker sidecar that reads but is no store, so such a sidecar blocks wakes and stops for at most one pass.
      The set-aside follows the sweep, so the pass that meets the corrupt sidecar still names a bundle addressed
      only through it. A sidecar that cannot be read, or cannot be moved aside, is told on stderr and in the
      summary's `error`.
    - A document whose frontmatter does not read `review_active: true` is skipped: no wake, no dispatch, not
      counted in `files`, and its finished job bundle is left unconsumed. A document that is missing, or whose
      reading raises `OSError`, counts as outside the review loop and is skipped silently like one. A document
      that is not UTF-8 text, or whose frontmatter does not parse, is not skipped silently: it is logged to
      stderr and its bundle is named in the summary's `error`, with no wake, no dispatch, not counted in
      `files`, the bundle left unconsumed and tried again by a later sweep.
    - A job queue root that exists but cannot be listed never makes the sweep raise: it returns `files` and
      `dispatched` as zero and an `error` naming the root.
    - An expert folder of the job queue that cannot be listed never stops the sweep and never hides the finished
      work of the other folders: it is named in the summary's `error`, and every other folder is still swept. A
      folder that merely vanished between the two listings holds nothing and is not named.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    `{"files": N, "dispatched": M}` — N is the number of distinct target files that carried
    at least one finished job, M is how many coordinator jobs this sweep queued. Carries an
    additional `"error"` field summarizing the failures when one or more targets could not
    be processed, when a review bundle's document is named by nothing, when the job queue root could not be listed,
    or when a job-marker sidecar could not be read or set aside (the error-ledger contract — a failed sweep must not
    report success via exit 0).
  """
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR

  # guard: no job queue at all — nothing to sweep, though a corrupt marker store is still set aside
  if not jobs_root.is_dir():
    return _set_aside_corrupt_markers(repo, {"files": 0, "dispatched": 0})

  # Domain(review.jobs):
  # # Only a landable verdict earns a wake
  # A sweep counts a document as having finished work only when at least one of its jobs
  # reached a verdict the postman can actually land — an edit or a deliberate no-change. A job
  # still being worked, one the runtime has already given up on, or one whose verdict the
  # postman cannot interpret must never count toward that decision: counting it would raise the
  # same wake every sweep forever, since nothing about the job's own state would ever change to
  # make it stop qualifying.

  # walk every DONE-and-not-CONSUMED job once, collecting its target file and job ids. Only an
  # outcome `collect-job` will consume counts: an `edited` payload is landed, an `empty` writer
  # is consumed without a document change. A coordinator's own DONE job (`handled`), an `error`
  # writer (the pump's retry ladder owns it), and a response-less bundle would never be
  # consumed — counting them would re-dispatch the coordinator every tick forever (found live:
  # 16 self-fed coordinator wakes).
  targets: dict[Path, list[str]] = {}
  broken: list[str] = []

  # guard: a queue root that cannot be listed leaves nothing to sweep; the sweep reports it and ends
  try:
    expert_dirs = sorted(jobs_root.iterdir())
  except OSError as error:

    # Contract:
    # A queue root that exists but cannot be listed NEVER makes the sweep raise: it returns zero `files`, zero
    # `dispatched` and an `error` naming the root, so the failure reaches the caller in the result.

    # trace the failure and end the sweep with it named in the result
    sys.stderr.write(f"collect-tick: {jobs_root}: {type(error).__name__}: {error}\n")
    return _set_aside_corrupt_markers(
        repo, {"files": 0, "dispatched": 0, JobKey.ERROR: f"job queue cannot be listed: {jobs_root}: {error}"},
    )
  for expert_dir in expert_dirs:
    # only expert subdirectories hold job bundles
    if not expert_dir.is_dir():
      continue
    # an expert folder that cannot be listed hides whatever finished work it holds: the sweep goes on with
    # the other folders and reports this one
    try:
      job_dirs = sorted(expert_dir.iterdir())
    # a folder removed between the listing above and this one holds nothing, and is no failure
    except FileNotFoundError:
      continue
    except OSError as error:

      # Contract:
      # An expert folder of the job queue that cannot be listed NEVER stops the sweep and never hides the
      # finished work of the other folders: it is named in the summary's `error`, and every other folder is
      # still swept. A folder that merely vanished between the two listings holds nothing and is not named.

      # trace the failure and keep the folder for the result, then go on with the other folders
      sys.stderr.write(f"collect-tick: {expert_dir}: {type(error).__name__}: {error}\n")
      broken.append(str(expert_dir))
      continue
    for jdir in job_dirs:

      # Contract:
      # One bundle, or one target document, that cannot be read never stops the sweep: the bundle
      # is named in the summary's `error` and every other deliverable document is still dispatched
      # in the same sweep.

      # this sweep's per-bundle error boundary — whatever one bundle or its document raises is
      # recorded against that bundle, and the walk goes on to the next one
      try:
        # only DONE-and-not-CONSUMED job dirs are due for this sweep
        if not jdir.is_dir() or read_job_status(jdir) != JobStatus.DONE:
          continue

        # the bundle's own request is untrusted data: it either names a target this sweep can use, or it
        # marks the bundle as one no later look will read differently; a file that cannot be read right
        # now is neither, and goes to the outer boundary
        resolved: Path | None = None
        unusable: Exception | None = None
        try:
          resolved = _read_bundle_target(repo, jdir)
        except OSError:
          raise
        # waiver: a bundle's own files are untrusted data — whatever their content raises must stop at
        # this bundle and retire it; a narrower list is what left one malformed request failing every sweep
        except Exception as error:  # pylint: disable=broad-exception-caught
          unusable = error

        # Contract:
        # A finished bundle whose own request can never be used MUST be retired by the sweep that finds it. That
        # is a request that is not a request object (its bytes are not UTF-8 text, the text is not JSON, or the
        # JSON value is not an object) or one that names a target that cannot be turned into a path. Such a
        # bundle is consumed, named once in the summary's `error`, and NEVER named by a later sweep.
        # When core refuses that consume, the bundle is NOT consumed, is named in `error`, and the next sweep
        # tries again.
        # A bundle whose files merely cannot be read right now (reading raises `OSError`) MUST NOT be consumed:
        # it is named in `error` on every sweep and left in place. A bundle whose target is a link loop counts as
        # one that cannot be read right now, NOT as unusable.

        # Domain(review.jobs):
        # # A request that can never be read is retired, not retried
        # A finished job is tied to its document only through its own request. When that request is not text,
        # not a structured record, a record of the wrong kind, or a record that names a document location nothing
        # can ever be found at, nothing can ever tie the job to a document, and no later look will read it
        # differently. Such a job is reported once and retired, so it stops
        # being reported as a fresh failure by every sweep. A job whose files simply cannot be read at this
        # moment is another matter: the next look may succeed, so it is kept and reported again.

        # guard: a request that will never parse cannot be matched to a document — retire it and report it once
        if unusable is not None:
          sys.stderr.write(f"collect-tick: {jdir}: unusable request, retired: {unusable!r}\n")
          consume_job(repo, jdir)
          broken.append(str(jdir))
          continue

        # Contract:
        # A DONE job bundle whose `request.json` carries no `_target_file` and whose job id has no row in the
        # review job-markers sidecar, the sidecar having been read as a store, is judged by its own core manifest.
        # A bundle whose manifest lists one of the review plugin's own protocols is the review's own: it is named
        # in the summary's `error` and by one stderr line on EVERY pass, and it is NEVER consumed, NEVER counted,
        # NEVER woken for and NEVER skipped silently, until the operator resolves it.
        # A bundle without a manifest, or whose manifest lists no review protocol, belongs to another plugin's
        # pipeline and is skipped silently: never counted, never written to stderr, never surfaced as an `error`.
        # A manifest that cannot be read right now is NEVER read as "another plugin's": the bundle is named in
        # `error` and kept.
        # Neither kind of bundle ever blocks collection of the rest of the batch.

        # Contract:
        # A job-marker sidecar that exists but cannot be read, or that reads but is no store, is NEVER read as "no
        # row": a bundle addressed only through it is NEVER skipped silently as foreign. It is left untouched, NOT
        # consumed, NOT counted, no wake is raised, it is NOT retired, and it is named in the summary's `error`.

        # no `_target_file` and no marker link: the bundle's own manifest decides whose job it is. One that
        # carries a review protocol is this plugin's and is named on every pass; any other is skipped silently
        if resolved is None:
          if _is_review_bundle(jdir):
            sys.stderr.write(f"collect-tick: {jdir}: {_ORPHAN_REVIEW_REASON}\n")
            broken.append(str(jdir))
          continue

        # Contract:
        # A document whose frontmatter does not read `review_active: true` is skipped: no wake is raised, no
        # coordinator is dispatched, it is not counted in `files`, and its finished job bundle is left unconsumed so
        # a resumed review still lands it.
        # A document that is missing, or whose reading raises `OSError`, counts as outside the review
        # loop and is skipped silently like one.
        # A document that is not UTF-8 text, or whose frontmatter does not parse, is NOT skipped silently: it is
        # logged to stderr and its bundle is named in the summary's `error`. No wake is raised, no coordinator is
        # dispatched, it is not counted in `files`, and its bundle is left unconsumed, so a later sweep tries it
        # again.

        # Domain(review.jobs):
        # # A document out of the review loop earns no wake
        # A document taken out of the review loop, for instance because its review was stopped, is not worked on:
        # finished work addressed to it raises no wake and is not landed. The finished work is kept, not discarded,
        # so that when the review is resumed the work still lands then.

        # guard: a document out of the review loop, e.g. stopped by its asset's cancel, takes no landing and no
        # wake; its bundle stays unconsumed so a resumed review still lands it
        if not _is_review_active(resolved):
          continue

        # the job's verdict is read from its response
        response_path = jdir / JobFile.RESPONSE

        # guard: a bundle that finished without a response is the sanitizer's to judge, not a failure of this sweep
        if not response_path.exists():
          continue
        response = _read_json_object(response_path)

        # Contract:
        # A finished bundle of a known document whose `response.json` can never be read as a response object
        # (its bytes are not UTF-8 text, the text is not JSON, or the JSON value is not an object) is handed to
        # the coordinator as finished work and named in the sweep's `error`, and the sweep NEVER consumes it:
        # the document is counted, its wake is raised, and the landing that follows retires the bundle and
        # reports it as failed, after which no sweep names it.
        # A `response.json` that merely cannot be read right now (reading raises `OSError`) MUST NOT be handed
        # over and MUST NOT be consumed: such a bundle is named in `error` on every sweep.

        # Domain(review.jobs):
        # # A writer's unreadable answer is still the coordinator's turn to decide
        # A writer that finished but left an answer nobody can read has failed its turn, and what to do
        # about a failed turn is the coordinator's decision: ask again, raise it with the operator, or drop
        # it. So the job counts as finished work for its document, and the coordinator is woken to land
        # it; the landing finds nothing it can apply, retires the job and tells the coordinator why.

        # only an outcome `collect-job` consumes is deliverable — everything else stays for the
        # pump's retry ladder or the daily sanitizer to judge, and a counted-but-never-consumed
        # bundle would re-raise this wake every sweep; a response that will never parse is consumed
        # by `collect-job` too, as a failed job, so it is deliverable
        if response is not None and response.get(JobKey.OUTCOME) not in (Outcome.EDITED, Outcome.EMPTY):
          continue

        # Contract:
        # A finished bundle is handed over only when the landing will be able to read it.
        # When a result file that an `edited` response names exists but cannot be read right now (opening it
        # raises `OSError`), the bundle MUST NOT be counted, handed over or consumed: it is named in the
        # sweep's `error`, and a later sweep hands it over once the file reads.
        # A result entry that is a symlink is passed over by this check: the landing judges it.
        # Other finished bundles of the same document are still handed over.

        # Domain(review.jobs):
        # # Finished work is held back until its result can be read
        # An edit is handed to the coordinator only when the landing that follows will be able to read what the
        # writer produced. If a result of the edit exists but cannot be read at this moment, waking the
        # coordinator would send it to a landing that has to leave the job alone again, and the same wake would
        # repeat on every sweep to no effect. Unreadable now is not unreadable for good, so the job is neither
        # retired nor handed over: it is held back and reported until its result reads. The hold concerns that
        # job alone, and other finished work of the same document still goes through.

        # an edit whose result cannot be read right now would wake the coordinator for a landing that
        # leaves it alone again, sweep after sweep — the raise goes to this bundle's boundary instead
        if response is not None and response.get(JobKey.OUTCOME) == Outcome.EDITED:
          _require_results_readable(jdir, response)

        # a response that will never parse is still a failure of this sweep's batch: it is reported here
        # as well, so the failed writer reaches the error ledger and not only the coordinator
        if response is None:
          sys.stderr.write(f"collect-tick: {jdir}: {JobFile.RESPONSE} is not a readable response object\n")
          broken.append(str(jdir))
        targets.setdefault(resolved, []).append(jdir.name)
      # waiver: the per-bundle boundary catches every failure type on purpose — a narrower list is
      # what let a wrong-shaped or non-UTF-8 file stop the whole sweep
      except Exception as error:  # pylint: disable=broad-exception-caught
        sys.stderr.write(f"collect-tick: {jdir}: {type(error).__name__}: {error}\n")
        broken.append(str(jdir))

  # raise the wake and dispatch the coordinator per target; one bad target logs and continues
  dispatched = 0
  failed: list[str] = []
  for doc, job_ids in sorted(targets.items()):
    try:
      _job_markers.update(
          repo, doc,
          { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE },
      )
      # waiver: type: ignore — coordinator_dispatch is a deferred/late-bound sibling import; mypy cannot resolve it
      result = _coordinator_dispatch.dispatch_job_done(  # type: ignore[attr-defined]
          repo, doc, "+".join(sorted(job_ids)),
      )
    # waiver: this sweep's per-target error boundary — one bad target must not stop the rest
    except Exception as error:
      sys.stderr.write(f"collect-tick: {doc}: {error}\n")
      failed.append(str(doc))
      continue
    # waiver: 'action' matches coordinator_dispatch's own wire-shape key, not a keys.py-promoted constant
    if result.get("action") == "dispatched":
      dispatched += 1

  # the "error" field is additive — a clean sweep's summary stays exactly the two keys above
  # waiver: 'files'/'dispatched' are this sweep's own wire-shape keys, not keys.py-promoted constants
  summary: dict[str, int | str] = {"files": len(targets), "dispatched": dispatched}
  errors = broken + failed

  # a sweep with failures must not report success via exit 0 (the error-ledger contract)
  if errors:
    summary[JobKey.ERROR] = f"{len(errors)} job(s) failed to collect: {', '.join(errors)}"

  # Contract:
  # Every pass, also with no job queue and when the queue root cannot be listed, ends by setting aside a job-marker
  # sidecar that reads but is no store, so such a sidecar blocks wakes and stops for at most one pass. The set-aside
  # follows the sweep, so the pass that meets the corrupt sidecar still names a bundle addressed only through it in
  # the summary's `error`. A sidecar that cannot be read, or cannot be moved aside, is told on stderr and in the
  # summary's `error`.

  # Domain(review.jobs):
  # # A garbled record of jobs in flight blocks for one pass at most
  # The record of which jobs are in flight on which documents is what a coordinator wake and a stop consult
  # before they act. When that record is garbled, it cannot be trusted either way, so every wake and every stop
  # is held until it is dealt with. The regular collect pass therefore sets such a record aside at its end: its
  # bytes are kept under another name and the pass says where, so nothing is lost and the block lasts at most
  # one pass. Within the pass that meets the garbled record, finished work addressed only through it is not
  # taken for another plugin's work: it is reported and kept untouched, and is collected once the record is
  # sound again.

  # the corrupt marker store is set aside only after the sweep, so a bundle addressed through it was named above
  return _set_aside_corrupt_markers(repo, summary)


def _set_aside_corrupt_markers(repo: Path, summary: dict[str, int | str]) -> dict[str, int | str]:
  """
  Set a corrupt job-marker store aside at the end of a collect pass.

  Args:
    repo: Absolute path to the repository root.
    summary: The pass's summary.

  Returns:
    The summary, with a failure to read or move the store appended to its `error`.
  """
  # a store that cannot be read or moved is a failure of this pass: it is told on stderr and in the summary
  try:
    _job_markers.set_aside_corrupt(repo)
  except OSError as error:
    reason = f"job markers cannot be set aside: {_job_markers.sidecar_path(repo)}: {type(error).__name__}: {error}"
    sys.stderr.write(f"collect-tick: {reason}\n")
    summary[JobKey.ERROR] = f"{summary[JobKey.ERROR]}; {reason}" if JobKey.ERROR in summary else reason
  return summary


def main_tick(argv: list[str]) -> int:
  """
  Run `collect_tick` and print its summary.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the working directory); the sweep covers the root of the checkout that
      directory sits in.

  Returns:
    Exit code: `0` when the sweep completed with nothing left uncollected, `1` when at least
    one target failed to collect.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazycortex-review collect-tick")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = None)
  args = parser.parse_args(argv)

  # sweep the checkout root of --repo, $LAZY_REPO_ROOT or the cwd; the CLI's whole contract is this one summary line
  summary = collect_tick(_review_locator.query_repo_root(args.repo))
  # waiver: 'files'/'dispatched' are collect_tick's own wire-shape keys, not keys.py-promoted constants
  print(json.dumps({"files": summary["files"], "dispatched": summary["dispatched"]}))
  return 1 if JobKey.ERROR in summary else 0


def main(argv: list[str]) -> int:
  """
  Land every DONE job targeting one review document and print the landing's summary.

  Prints one JSON object on stdout: the summary of the landing. Every failure exits `1` with a stderr line
  starting with `collect-job:` and one JSON summary on stdout. An `OSError`, `ValueError` or `RuntimeError` is
  told in one stderr line even when its own text runs over several lines; a refused consume is written with its
  own text as it is. No exception escapes.

  Args:
    argv: Command-line arguments, excluding the program name; `--repo` names a directory inside the repository
      (default: `$LAZY_REPO_ROOT`, then the working directory); a relative document path is read from the root of the
      checkout that directory sits in.

  Returns:
    Exit code: `0` on success, also when the summary lists jobs under `failed` (a job whose attachment would
    replace a file git cannot give back is retired there and does not fail the call). `1` on any failure: the
    partial summary of what did land when core refused a consume, or `{"collected": 0}` when the document or the
    job marker could not be read or written, the document's folder is not inside the repository or cannot be
    resolved, git cannot be launched or fails, the review settings cannot be read, no core CLI can be reached
    (`RuntimeError`), or the document is not UTF-8 text (that stderr line says a retry will not help); also `1`
    with the printed summary when it carries `unfinished`. `2` only when the target file does not exist.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazycortex-review collect-job")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = None)
  args = parser.parse_args(argv)

  # `file` resolves against the root of the checkout `--repo`, `$LAZY_REPO_ROOT` or the cwd sits in, unless it is
  # already absolute
  repo = _review_locator.query_repo_root(args.repo)
  file_path = (repo / args.file).resolve()

  # guard: the named document does not exist, nothing to collect for
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # every failure ends the verb with exit 1, one stderr line naming the reason, and a summary on stdout:
  # a caller reads what landed from the same place whether the landing finished or not
  try:
    summary = collect_for_file(repo, file_path)
  except JobConsumeError as error:
    sys.stderr.write(f"collect-job: {error}\n")

    # what did land before the refusal is still the caller's to commit; the jobs taken out again are
    # still finished, and the next call lands them
    print(json.dumps(error.summary if error.summary is not None else _summarize(0, [], [], [])))
    return 1
  except UnicodeDecodeError as error:
    # a document that is not UTF-8 text will not read on a retry either: nothing is applied and nothing is
    # consumed, and the sweep goes on naming the document's jobs in its own `error` until the document is fixed
    sys.stderr.write(
        f"collect-job: {file_path}: the document is not UTF-8 text and a retry will not help ({error}); "
        f"nothing landed\n"
    )
    print(json.dumps(_summarize(0, [], [], [])))
    return 1
  except (OSError, ValueError, RuntimeError) as error:
    # the document or the job marker could not be read or written, or no core CLI could be reached to read the
    # review class: nothing landed and nothing is consumed; a failure whose own text runs over several lines is
    # told in one, like every other
    detail = " ".join(str(error).split())
    sys.stderr.write(f"collect-job: {file_path}: {type(error).__name__}: {detail}; nothing landed\n")
    print(json.dumps(_summarize(0, [], [], [])))
    return 1

  # the CLI's whole contract is this one summary line
  print(json.dumps(summary))

  # a finished job left unconsumed over an attachment is a failure of this call too; its stderr line is written
  return 1 if _UNFINISHED in summary else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
