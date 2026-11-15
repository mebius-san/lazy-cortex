from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
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
import cancel_sweep  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import catalog_note  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coherence  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_check  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_pins  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import upstream_tick  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import FLIP_GATE_NAME, AttachmentKey, Stage, StageKey  # noqa: E402


# A backfill primitive's call shape: the repository root, then the dry-run and path-listing switches
Backfill = Callable[..., dict]

_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The repo-relative directory the upstream units live under, as the upstream tick lays it out
_UPSTREAM_ROOT = "upstream"

# The exit code of a run with a failed repair or a failure of the run as a whole
_EXIT_FAILED = 2

# The commit identity and subject of the one batch commit, the identity `cancel-sweep` commits under
_AUTHOR_NAME = FLIP_GATE_NAME
_AUTHOR_EMAIL = f"{FLIP_GATE_NAME}@bot.invalid"
_SUBJECT = f"{FLIP_GATE_NAME}: doctor repairs"


# ----------------------------------------------------------------------------------------
class Check:
  """
  Finding classes the doctor reports, one per repair.

  Attributes:
    CANCEL_SWEEP: Class of a cancelled asset whose documents are not all cancelled.
    STAGE_TAG_MIRROR: Class of a document whose stage tag does not track its stage.
    DOC_TYPE: Class of a document missing its `spec_doc_type`.
    ASSET_TYPE: Class of a status note missing its `spec_asset_type`.
    PINNED_TOPICS: Class of a document whose `wiki_pinned_topics` is missing or names the wrong product.
    LEVEL_NOTE: Class of a level note that is missing or lacks part of the level schema.
    CONFLICTED_FLAG: Class of a folder-note whose `spec_conflicted` flag disagrees with its conflict callouts.
    DANGLING_REQUEST_LINK: Class of an upstream unit frozen on a request link that no longer resolves.
  """

  # Class of a cancelled asset whose documents are not all cancelled.
  CANCEL_SWEEP = "cancel-sweep"
  # Class of a document whose stage tag does not track its stage.
  STAGE_TAG_MIRROR = "stage-tag-mirror"
  # Class of a document missing its `spec_doc_type`.
  DOC_TYPE = "doc-type"
  # Class of a status note missing its `spec_asset_type`.
  ASSET_TYPE = "asset-type"
  # Class of a document whose `wiki_pinned_topics` is missing or names the wrong product.
  PINNED_TOPICS = "pinned-topics"
  # Class of a level note that is missing or lacks part of the level schema.
  LEVEL_NOTE = "level-note"
  # Class of a folder-note whose `spec_conflicted` flag disagrees with its conflict callouts.
  CONFLICTED_FLAG = "conflicted-flag"
  # Class of an upstream unit frozen on a request link that no longer resolves.
  DANGLING_REQUEST_LINK = "dangling-request-link"


# ----------------------------------------------------------------------------------------
class _Out:
  """
  Wire-shape keys of the printed result and of each finding.
  """

  # The list of findings in the printed result.
  FINDINGS = "findings"
  # The count of repaired findings in the result, and the repaired flag of one finding.
  APPLIED = "applied"
  # The count of findings left unrepaired in the result.
  PENDING = "pending"
  # The finding class of one finding.
  CHECK = "check"
  # The settings-root-relative path of one finding.
  PATH = "path"
  # The message describing one finding.
  MESSAGE = "message"
  # The failure of the run as a whole, printed in place of the report.
  ERROR = "error"


# ----------------------------------------------------------------------------------------
class _Message:
  """
  Finding messages the operator reads, one per class, and the suffixes a repair outcome appends.
  """

  # Message of a cancelled asset whose documents are not all cancelled.
  CANCEL_SWEEP = "the asset is cancelled but some of its documents are not"
  # Message of a document whose stage tag does not track its stage.
  STAGE_TAG_MIRROR = "the stage tag does not match the stage"
  # Message of a document missing its type, or carrying one on a level note.
  DOC_TYPE = "the document's `spec_doc_type` is missing, or sits on a level note"
  # Message of a status note missing its asset type.
  ASSET_TYPE = "the status note carries no `spec_asset_type`"
  # Message of a document whose topic pin is missing or names the wrong product.
  PINNED_TOPICS = "`wiki_pinned_topics` is missing or names the wrong product"
  # Message of a level note that does not exist.
  LEVEL_NOTE_MISSING = "the level note is missing"
  # Lead-in of the message of a level note missing parts of the schema; the missing parts follow it.
  LEVEL_NOTE_LACKS = "the level note lacks"
  # Message of a folder-note whose conflict flag disagrees with its callouts.
  CONFLICTED_FLAG = "`spec_conflicted` does not match the conflict callouts on the note"
  # Suffix lead-in of a class whose check failed before it found anything.
  CHECK_FAILED = "the check could not run"
  # Suffix lead-in of a finding whose class failed during repair.
  REPAIR_FAILED = "the repair failed"
  # Suffix lead-in of an asset the cancel sweep refused.
  SWEEP_REFUSED = "the sweep was refused"
  # Suffix lead-in of an asset the cancel sweep failed on.
  SWEEP_FAILED = "the sweep failed"
  # Suffix lead-in of a document the stage change refused.
  STAGE_REFUSED = "the stage change was refused"
  # Suffix lead-in of an upstream unit the release skipped.
  RELEASE_SKIPPED = "the release was skipped"
  # Suffix lead-in of a finding whose repair is written but whose batch commit failed.
  COMMIT_FAILED = "the repair is written but its commit failed"


# ----------------------------------------------------------------------------------------
class _Wire:
  """
  Result keys of the sibling primitives the doctor reads.
  """

  # The cancel sweep's list of assets still to sweep.
  PENDING = "pending"
  # The cancel sweep's list of assets it swept.
  SWEPT = "swept"
  # The cancel sweep's list of assets it refused.
  REFUSED = "refused"
  # The cancel sweep's list of assets it failed on.
  FAILED = "failed"
  # The asset an entry of the cancel sweep names.
  ASSET = "asset"
  # The reason an entry of a refused, failed or skipped list carries.
  REASON = "reason"
  # A backfill's list of files it wrote, or would write.
  PATHS = "paths"
  # The path of one entry of the spec-tree scan.
  PATH = "path"
  # The kind of one scan or upstream finding.
  KIND = "kind"
  # The detail of one scan or upstream finding.
  DETAIL = "detail"
  # What the level-note backfill did with a note.
  OUTCOME = "outcome"
  # The path of the level note the backfill dealt with.
  NOTE = "note"
  # The schema parts the level-note backfill adds to a note.
  ADDED = "added"
  # The level-note outcome of a note that already carries the whole schema.
  UNCHANGED = "unchanged"
  # The level-note outcome of a note that does not exist yet.
  CREATED = "created"
  # The upstream scan's list of findings.
  FINDINGS = "findings"
  # The upstream source an upstream finding or entry belongs to.
  REPO_KEY = "repo_key"
  # The mount of an upstream unit.
  MOUNT = "mount"
  # The path of an upstream unit inside its source.
  UNIT_PATH = "unit_path"
  # The upstream release's list of units it released.
  RESET = "reset"
  # The upstream release's list of units it skipped.
  SKIPPED = "skipped"
  # The tags of a document.
  TAGS = "tags"


# ----------------------------------------------------------------------------------------
class SpecDoctor:
  """
  Doctor reporting, and on request repairing, the spec catalog's mechanical drift.

  Each drift is a finding naming its class, the path it sits at and a message; a run answers with the findings and
  how many of them were repaired. The drift is what a deterministic repair can fix, never a judgement call.

  Responsibilities:
    - List every finding without writing anything, unless repair is requested.
    - When repair is requested, repair each class; the cancel sweep and the upstream release commit on their own,
      the other repairs land in one commit under the flip-gate bot identity carrying only the files they wrote.
    - Report one class's failure in that class's findings and carry on with the others.

  Guarantees:
    - A run without repair writes nothing.
    - A run that wrote nothing in the batch classes makes no batch commit.
    - One class's failure never stops the classes after it.

  Attributes:
    repo: The settings root every finding path is relative to.
    apply: Whether the run repairs what it finds.
  """

  def __init__(self, repo: Path, *, apply: bool) -> None:
    """
    Bind the doctor to a catalog and a repair mode.

    Args:
      repo: A directory inside the catalog's repository; the settings root above it is the one used.
      apply: Whether to repair what is found, or only list it.

    Raises:
      FileNotFoundError: If no `.claude/lazy.settings.json` sits at or above `repo`.
    """
    # the settings root every finding path is relative to
    self.repo: Path = spec_paths.require_settings_root(repo)

    # whether the run repairs what it finds
    self.apply: bool = apply

    # every finding in report order
    self._findings: list[dict] = []

    # whether a repair or a check failed
    self._failed: bool = False

    # the files the non-committing repairs wrote, and the findings that ride the batch commit
    self._batch_paths: list[str] = []
    self._batch_findings: list[dict] = []

  @property
  def failed(self) -> bool:
    """
    Whether a check or a repair failed during the run.

    Notes:
      - Meaningful once `run` has returned.
    """
    return self._failed

  def run(self) -> dict:
    """
    List the catalog's mechanical drift and, when repair is requested, repair it.

    Guarantees:
      - Without repair, nothing is written or committed.
      - With repair, the repairs that do not commit on their own land in exactly one commit under the flip-gate bot
        identity, carrying only the files those repairs wrote.
      - When those repairs wrote nothing, no commit is made.
      - One class's failure never stops the classes after it, and marks the run as failed.

    Notes:
      - With repair, the cancel sweep and the upstream release commit per asset and per unit as they go, and the
        remaining repairs are committed once at the end.

    Returns:
      `{"findings": [...], "applied": N, "pending": M}`; each finding is `{"check", "path", "message", "applied"}`.
    """

    # Contract:
    # Without repair the run MUST write and commit nothing.

    # Contract:
    # With repair, every repair that does not commit on its own MUST land in exactly one commit, made under the
    # flip-gate bot identity and carrying only the files those repairs wrote.

    # Contract:
    # When the repairs that do not commit on their own wrote nothing, the run MUST make no commit.

    # Contract:
    # One class's failure MUST NOT stop the other classes from being checked and repaired, and it MUST mark the run
    # as failed.

    # Domain(spec.repair):
    # # A repair heals the drift an older version left behind
    # A catalog written by an older plugin version can hold data that a rule added later would have prevented: assets
    # cancelled while their documents never followed, stage tags that do not track the stages, documents and status
    # notes missing their type keys or topic pins, level notes missing part of the level schema, a conflict flag that
    # disagrees with the callouts on its note, and upstream units frozen on a request link that no longer resolves.
    # Each such class has exactly one deterministic repair, applied on request. Legacy data that became inconsistent
    # only because an older version lacked a rule is always healed; a guard that protects a new action never blocks
    # the repair of that data, because the repair is not the action the guard was written for.

    # Domain(spec.repair):
    # # A gate orphaned by gate precedence is not repaired automatically
    # A gate that stands orphaned by the precedence between gates has two valid repairs: turn the later gate off, or
    # halt the asset. Choosing between them is a decision about the asset, not a mechanical correction of drifted
    # data, so no repair is applied and the operator picks the way out.

    # the classes that commit on their own run first and last, the batch classes between them
    self._run_class(Check.CANCEL_SWEEP, self._run_cancel_sweep)
    self._run_class(Check.STAGE_TAG_MIRROR, self._run_stage_tags)
    self._run_class(Check.DOC_TYPE, lambda: self._run_backfill(
        Check.DOC_TYPE, spec_doc_types.backfill, _Message.DOC_TYPE))
    self._run_class(Check.ASSET_TYPE, lambda: self._run_backfill(
        Check.ASSET_TYPE, asset_types.backfill, _Message.ASSET_TYPE))
    self._run_class(Check.PINNED_TOPICS, lambda: self._run_backfill(
        Check.PINNED_TOPICS, spec_pins.backfill, _Message.PINNED_TOPICS))
    self._run_class(Check.LEVEL_NOTE, self._run_level_notes)
    self._run_class(Check.CONFLICTED_FLAG, self._run_conflicted)
    self._run_class(Check.DANGLING_REQUEST_LINK, self._run_upstream)

    # the batch repairs land together in one commit
    if self.apply:
      self._commit_batch()

    # the report counts what was repaired and what is left
    applied = sum(1 for finding in self._findings if finding[_Out.APPLIED])
    return { _Out.FINDINGS: self._findings, _Out.APPLIED: applied, _Out.PENDING: len(self._findings) - applied }

  def _add(self, check: str, path: str, message: str) -> dict:
    """
    Record a finding as not yet repaired.

    Args:
      check: The finding class.
      path: The settings-root-relative path the finding sits at.
      message: What is wrong.

    Returns:
      The recorded finding, which later repair steps update in place.
    """
    finding = { _Out.CHECK: check, _Out.PATH: path, _Out.MESSAGE: message, _Out.APPLIED: False }
    self._findings.append(finding)
    return finding

  def _to_root_rel(self, path: Path | str) -> str:
    """
    Express a path inside the catalog's repository relative to the settings root.

    Args:
      path: An absolute path, or one relative to the working directory.

    Returns:
      The posix path relative to the settings root.
    """
    return Path(path).resolve().relative_to(self.repo.resolve()).as_posix()

  def _run_class(self, check: str, body: Callable[[], None]) -> None:
    """
    Run one class's check and repair, containing any failure to that class.

    Args:
      check: The finding class, named in the report when the check failed before finding anything.
      body: The callable that lists the class's findings and, when repairing, repairs them.
    """
    mark = len(self._findings)
    try:
      body()
    # waiver: one class's failure must not stop the classes after it; it is named in its findings and the run exits
    # as failed
    except Exception as error:  # pylint: disable=broad-exception-caught
      self._failed = True
      reason = f"{type(error).__name__}: {error}"
      own = self._findings[mark:]

      # a check that failed before it found anything is reported on its own line
      if not own:
        self._add(check, "", f"{_Message.CHECK_FAILED}: {reason}")

      # every finding the class recorded is left unrepaired and names the failure
      for finding in own:
        finding[_Out.APPLIED] = False
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.REPAIR_FAILED}: {reason}"

  def _settle(self, finding: dict, paths: list[str]) -> None:
    """
    Mark a finding repaired and queue the files its repair wrote for the batch commit.

    Args:
      finding: The finding the repair resolved.
      paths: The settings-root-relative paths the repair wrote.
    """
    finding[_Out.APPLIED] = True
    self._batch_findings.append(finding)
    self._batch_paths.extend(path for path in paths if path not in self._batch_paths)

  def _run_cancel_sweep(self) -> None:
    """
    Report cancelled assets that still have documents not at `cancelled` and, when repairing, sweep them.

    Notes:
      - The sweep commits each asset on its own; an asset it refuses or fails on stays pending with the reason.
    """
    # every cancelled asset whose documents were left behind
    found = { rel: self._add(Check.CANCEL_SWEEP, rel, _Message.CANCEL_SWEEP)
              for rel in cancel_sweep.sweep(self.repo, dry_run = True)[_Wire.PENDING] }

    # guard: nothing left behind, nothing to sweep
    if not found:
      return

    # a dry run ends at the listing
    if not self.apply:
      return

    # the sweep commits each asset on its own, and every swept asset is repaired
    swept = cancel_sweep.sweep(self.repo)
    for entry in swept[_Wire.SWEPT]:
      if (finding := found.get(entry[_Wire.ASSET])) is not None:
        finding[_Out.APPLIED] = True

    # a refused asset stays pending with the refusal reason
    for entry in swept[_Wire.REFUSED]:
      if (finding := found.get(entry[_Wire.ASSET])) is not None:
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.SWEEP_REFUSED}: {entry[_Wire.REASON]}"

    # a failed asset stays pending with the failure and marks the run failed
    for entry in swept[_Wire.FAILED]:
      self._failed = True
      if (finding := found.get(entry[_Wire.ASSET])) is not None:
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.SWEEP_FAILED}: {entry[_Wire.REASON]}"

  def _find_all_tag_drift(self) -> dict[str, str]:
    """
    List the documents whose stage tag does not track their stage.

    Returns:
      The drift detail of each such document, keyed by its settings-root-relative path.
    """
    content_root = spec_paths.spec_content_root(self.repo)
    return { self._to_root_rel(content_root / entry[_Wire.PATH]): entry[_Wire.DETAIL]
             for entry in spec_check.scan_spec_tree(content_root)
             if entry[_Wire.KIND] == spec_check.STAGE_TAG_MIRROR }

  def _run_stage_tags(self) -> None:
    """
    Report documents whose stage tag does not track their stage and, when repairing, restamp them.

    Notes:
      - A document the stage change refuses stays pending with the refusal reason.
      - The files written ride the batch commit.
    """
    # every staged document whose stage tag does not track its stage
    found = { rel: self._add(Check.STAGE_TAG_MIRROR, rel, f"{_Message.STAGE_TAG_MIRROR}: {detail}")
              for rel, detail in self._find_all_tag_drift().items() }

    # guard: no drift, nothing to restamp
    if not found:
      return

    # a dry run ends at the listing
    if not self.apply:
      return

    # the refusal reasons and the written files, collected over the restamps
    reasons: dict[str, str] = {}
    written: list[str] = []

    # each document is restamped at the stage it already has; an attachment through its owner
    for rel in found:
      result = self._restamp(self.repo / rel)
      written.extend(self._to_root_rel(path) for path in result.touched_paths)
      if result.reason:
        reasons[rel] = result.reason

    # a document no longer drifting is repaired; the rest keep their refusal reason
    remaining = self._find_all_tag_drift()
    for rel, finding in found.items():
      if rel not in remaining:
        self._settle(finding, written)
      elif rel in reasons:
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.STAGE_REFUSED}: {reasons[rel]}"

  @staticmethod
  def _restamp(doc: Path) -> set_stage.StageResult:
    """
    Rewrite a document's stage marks at the stage it already carries.

    Notes:
      - An attachment is restamped through its owner document, whose stage it mirrors.
      - Writes the document's files without committing.

    Args:
      doc: The document whose stage tag has drifted.

    Returns:
      The stage change's outcome: the paths it touched and the reason it was refused, if it was.
    """

    # Domain(spec.repair):
    # # A drifted stage tag is restamped at the stage the document already has
    # A document's stage tag mirrors its stage, and when the two disagree the stage is the truth: the document is
    # stamped again at the stage it already carries, so the tag follows and the stage never changes. An attachment has
    # no stage of its own, it mirrors its owner document, so it is restamped through the owner. A cancelled document is
    # restamped as cancelled together with its asset, never alone, because a document type whose category is mandatory
    # refuses a lone cancellation; the document is already cancelled, so its recorded mark is kept.

    # an attachment's stage mirrors its owner's, so the owner is the one restamped
    owner = spec_frontmatter.parse(spec_paths.read_text(doc))[0].get(AttachmentKey.OWNER_DOC, "")
    target = doc.parent / owner if owner else doc

    # the stage the target already carries is the one it is restamped at
    stage = spec_frontmatter.parse(spec_paths.read_text(target))[0].get(StageKey.STAGE, "")
    return set_stage.apply_stage(target, stage, with_asset = stage == Stage.CANCELLED)

  def _run_backfill(self, check: str, backfill: Backfill, message: str) -> None:
    """
    Report the files a backfill primitive would write and, when repairing, run it.

    Notes:
      - A file the backfill still lists after the run stays pending.
      - The files written ride the batch commit.

    Args:
      check: The finding class of the backfill's drift.
      backfill: The backfill primitive, called with the repository root and the dry-run and path-listing switches.
      message: The message every finding of this class carries.
    """
    # every file the backfill would write
    found = { rel: self._add(check, rel, message)
              for rel in backfill(self.repo, dry_run = True, with_paths = True)[_Wire.PATHS] }

    # guard: nothing to write, nothing to backfill
    if not found:
      return

    # a dry run ends at the listing
    if not self.apply:
      return

    # the backfill writes, then a second listing tells what it left behind
    backfill(self.repo)
    remaining = set(backfill(self.repo, dry_run = True, with_paths = True)[_Wire.PATHS])
    for rel, finding in found.items():
      if rel not in remaining:
        self._settle(finding, [ rel ])

  def _run_level_notes(self) -> None:
    """
    Report level notes that are missing or lack part of the level schema and, when repairing, bring them up to it.

    Notes:
      - Covers the catalog root's note and every registered product's own.
      - A note the schema still finds short after the repair stays pending.
      - The files written ride the batch commit.
    """
    # the catalog root's note, then every registered product's own
    targets = [ ( None, True ), *( ( key, False ) for key in sorted(resolve_product.load_products(self.repo)) ) ]
    for product, root in targets:
      planned = catalog_note.backfill(self.repo, product = product, root = root, dry_run = True)

      # guard: a note that already carries the whole level schema owes nothing
      if planned[_Wire.OUTCOME] == _Wire.UNCHANGED:
        continue

      # the note is reported as missing, or with the schema parts it lacks
      rel = Path(planned[_Wire.NOTE]).as_posix()
      message = _Message.LEVEL_NOTE_MISSING if planned[_Wire.OUTCOME] == _Wire.CREATED \
          else f"{_Message.LEVEL_NOTE_LACKS} {', '.join(planned[_Wire.ADDED])}"
      finding = self._add(Check.LEVEL_NOTE, rel, message)

      # a dry run ends at the listing
      if not self.apply:
        continue

      # the note is brought up to the schema and checked once more
      catalog_note.backfill(self.repo, product = product, root = root)
      if catalog_note.backfill(self.repo, product = product, root = root, dry_run = True)[_Wire.OUTCOME] \
          == _Wire.UNCHANGED:
        self._settle(finding, [ rel ])

  def _find_all_flag_drift(self) -> list[Path]:
    """
    List the folder-notes whose conflict flag disagrees with the conflict callouts on them.

    Returns:
      The drifted folder-notes, sorted, each listed once.
    """
    return sorted({ *coherence.find_all_conflicted_drift(self.repo), *coherence.find_all_gateless_flags(self.repo) })

  def _run_conflicted(self) -> None:
    """
    Report folder-notes whose `spec_conflicted` flag disagrees with their conflict callouts and, when repairing,
    bring the flag in line.

    Notes:
      - A note still drifting after the repair stays pending.
      - The files written ride the batch commit.
    """
    # every folder-note whose conflict flag disagrees with its callouts
    found = { self._to_root_rel(note): ( note, self._add(
        Check.CONFLICTED_FLAG, self._to_root_rel(note), _Message.CONFLICTED_FLAG) )
              for note in self._find_all_flag_drift() }

    # guard: no drift, no flag to bring in line
    if not found:
      return

    # a dry run ends at the listing
    if not self.apply:
      return

    # each note's flag is brought in line through the coherence writer
    for note, _finding in found.values():
      coherence.update_conflicted_flag(self.repo, note)

    # a note no longer drifting on a second look is repaired
    remaining = { self._to_root_rel(note) for note in self._find_all_flag_drift() }
    for rel, ( _note, finding ) in found.items():
      if rel not in remaining:
        self._settle(finding, [ rel ])

  def _find_unit_rel(self, repo_key: str, unit_path: str) -> str:
    """
    Locate an upstream unit's folder inside the repository.

    Args:
      repo_key: The upstream source the unit belongs to.
      unit_path: The unit's path inside its source.

    Returns:
      The settings-root-relative posix path of the unit's folder.
    """
    # the unit sits under one of its source's mounts; the first mount holding it names it
    base = self.repo / _UPSTREAM_ROOT / repo_key
    mounts = sorted(entry for entry in os.listdir(base) if (base / entry / unit_path).is_dir()) \
        if base.is_dir() else []
    return ( base / mounts[0] / unit_path if mounts else base / unit_path ).relative_to(self.repo).as_posix()

  def _run_upstream(self) -> None:
    """
    Report upstream units frozen on a request that no longer resolves and, when repairing, release them.

    Notes:
      - The release commits each unit itself; a unit it skips stays pending with the reason.
    """
    # every unit frozen on a request that no longer resolves
    found = { ( entry[_Wire.REPO_KEY], entry[_Wire.UNIT_PATH] ): self._add(
        Check.DANGLING_REQUEST_LINK, self._find_unit_rel(entry[_Wire.REPO_KEY], entry[_Wire.UNIT_PATH]),
        entry[_Wire.DETAIL] )
              for entry in upstream_tick.doctor_scan(self.repo)[_Wire.FINDINGS]
              if entry[_Wire.KIND] == upstream_tick.DoctorFinding.DANGLING_REQUEST_LINK }

    # guard: nothing dangling, nothing to release
    if not found:
      return

    # a dry run ends at the listing
    if not self.apply:
      return

    # the release commits each unit itself, and every released unit is repaired
    done = upstream_tick.doctor_apply(self.repo)
    for entry in done[_Wire.RESET]:
      if (finding := found.get(( entry[_Wire.REPO_KEY], entry[_Wire.UNIT_PATH] ))) is not None:
        finding[_Out.APPLIED] = True

    # a skipped unit stays pending with its reason
    for entry in done[_Wire.SKIPPED]:
      if (finding := found.get(( entry[_Wire.REPO_KEY], entry[_Wire.UNIT_PATH] ))) is not None:
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.RELEASE_SKIPPED}: {entry[_Wire.REASON]}"

  def _commit_batch(self) -> None:
    """
    Commit every file the batch repairs wrote in one commit under the flip-gate bot identity.

    Notes:
      - A failed commit leaves the repairs written and uncommitted; each finding it carried is reported as not
        applied and the run is marked failed.
    """
    # guard: nothing written, nothing to commit
    if not self._batch_paths:
      return

    # every file the batch repairs wrote lands in one commit under the bot identity
    try:
      flip_gate.commit_paths(self.repo, self._batch_paths, subject = _SUBJECT, author_name = _AUTHOR_NAME,
                             author_email = _AUTHOR_EMAIL)
    # waiver: a failed commit leaves the repairs written but uncommitted; every finding it carried is reported as
    # not applied and the run exits as failed
    except Exception as error:  # pylint: disable=broad-exception-caught
      self._failed = True
      for finding in self._batch_findings:
        finding[_Out.APPLIED] = False
        finding[_Out.MESSAGE] = f"{finding[_Out.MESSAGE]}; {_Message.COMMIT_FAILED}: {type(error).__name__}: {error}"


def _fail(error: BaseException) -> int:
  """
  Report a failure of the run as a whole.

  Notes:
    - Prints a JSON object with an `error` key to stdout and the failure to stderr.

  Args:
    error: The failure that ended the run.

  Returns:
    The failing exit code.
  """
  # a caller reading stdout gets the failure as JSON, an operator reading stderr gets it too
  sys.stderr.write(f"doctor: {error!r}\n")
  print(json.dumps({ _Out.ERROR: f"{type(error).__name__}: {error}" }))
  return _EXIT_FAILED


def main(argv: list[str]) -> int:
  """
  Run the `doctor` verb: list the spec catalog's mechanical drift and, with `--apply`, repair it.

  Guarantees:
    - Without `--apply`, nothing is written.
    - Exits 0 on success, and 2 when a repair failed or the run as a whole failed.
    - A failure of the run as a whole prints a JSON object with an `error` key instead of the report.

  Notes:
    - Prints the report `{"findings": [...], "applied": N, "pending": M}` as JSON to stdout.
    - The repository root is `--cwd`, else the daemon-exported `LAZY_REPO_ROOT`, else the process working directory.

  Args:
    argv: The verb's argv tail: the optional `--apply` flag, which repairs what is found, and `--cwd`, the
      repository root.

  Returns:
    The process exit code.
  """

  # Contract:
  # The verb MUST exit 2 when a repair or a check failed, and 0 otherwise, so a caller never reads a failed run as a
  # clean one.

  # Contract:
  # A failure of the run as a whole MUST print a JSON object with an `error` key in place of the report and exit 2;
  # callers read that key to tell a failed run from a report.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs doctor")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--apply", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # any failure of the run as a whole exits 2 with a JSON error object
  try:
    doctor = SpecDoctor(repo, apply = args.apply)
    result = doctor.run()
  # waiver: the run's boundary — every failure leaves as exit 2 with an `error` object, never as a partial report
  except Exception as error:  # pylint: disable=broad-exception-caught
    return _fail(error)
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    return _fail(error)

  # the report goes to stdout; a failed repair exits 2
  print(json.dumps(result))
  return _EXIT_FAILED if doctor.failed else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
