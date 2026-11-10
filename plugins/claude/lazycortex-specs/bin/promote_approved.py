from __future__ import annotations

import argparse
import dataclasses
import json
import os
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
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES, AttachmentKey, LevelDoc, ReviewResultValue, SpecKey, Stage, StageKey,
)


# The reasons a document with an accepted verdict is passed over.
SKIP_DEFERRED = "deferred"
SKIP_IN_REVIEW = "in-review"

# The keys of a skipped or refused entry; only a refused entry carries the stage the document holds on disk.
_DOC = "doc"
_REASON = "reason"
_STAGE = "stage"

# The frontmatter spelling of a true flag.
_TRUE = "true"

# The verb's exit codes: nothing refused, and at least one document refused.
_EXIT_OK = 0
_EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
@dataclass
class PromoteResult:
  """
  Outcome of promoting the accepted documents of one status folder-note's ladder.

  Attributes:
    promoted: Paths of the documents moved from `draft` to `approved`.
    restamped: Paths of the already approved documents that received a fresh approval stamp.
    attachments: Paths of the attachments whose stage was brought to their owner's stage.
    skipped: Entries naming a document with an accepted verdict that was passed over, each with its reason.
    refused: Entries naming a document whose stage change was refused, each with the refusal reason and the stage
      the document holds on disk.
    touched_paths: Paths of every file written, for the caller's commit.
  """

  promoted: list[str] = field(default_factory = list)
  restamped: list[str] = field(default_factory = list)
  attachments: list[str] = field(default_factory = list)
  skipped: list[dict[str, str]] = field(default_factory = list)
  refused: list[dict[str, str]] = field(default_factory = list)
  touched_paths: list[str] = field(default_factory = list)

  def add_touched(self, paths: list[str]) -> None:
    """
    Record written paths for the caller's commit, listing each path once in the order it was first written.

    Args:
      paths: The paths that were written.
    """
    # each written path is listed once, in the order it was first written
    for path in paths:
      if path not in self.touched_paths:
        self.touched_paths.append(path)

  def add_attachments(self, paths: list[str]) -> None:
    """
    Record attachments whose stage was mirrored from their owner, listing each once and also as written.

    Args:
      paths: The attachment paths that were mirrored.
    """
    # each mirrored attachment is listed once, and its write rides in the commit too
    for path in paths:
      if path not in self.attachments:
        self.attachments.append(path)
    self.add_touched(paths)


def _ladder_documents(note: Path) -> list[Path]:
  """
  List the documents of a status folder-note's ladder.

  Args:
    note: The status folder-note whose folder holds the ladder.

  Returns:
    The ladder documents in name order: the level system documents for a level note, every typed markdown file of
    the folder for an asset note.
  """
  basenames = ( LevelDoc.BASENAMES
                if spec_frontmatter.parse(spec_paths.read_text(note))[0].get(SpecKey.ROLE) in LEVEL_ROLES else None )

  # the note's own ladder decides membership, in a stable name order
  return [ note.parent / name for name in sorted(os.listdir(note.parent))
           if spec_doc_types.is_ladder_document(note.parent / name, basenames) ]


def _move(doc: Path, result: PromoteResult, bucket: list[str], *, restamp: bool, now: str | None) -> None:
  """
  Apply the approval to one document and file it into a result bucket.

  Notes:
    - A refused document is never written: it is recorded in the result's `refused` list with the stage it keeps
      on disk and contributes nothing to `touched_paths`.

  Args:
    doc: The document to approve.
    result: The result to record into.
    bucket: The result list that receives the document when something was written.
    restamp: Whether to restamp the approval time of an already approved document.
    now: The approval time to stamp, as an ISO 8601 string; the current UTC time when omitted.

  Raises:
    RuntimeError: If a written document does not carry the stage on disk after the write.
  """
  outcome = set_stage.apply_stage(doc, Stage.APPROVED, restamp = restamp, now = now)

  # a refused document is left unwritten, and its entry records the stage it keeps on disk; written paths and
  # mirrored attachments of an accepted change go to the caller's commit
  result.add_touched(outcome.touched_paths)
  result.add_attachments(outcome.attachments)
  if outcome.status == set_stage.StageStatus.REFUSED:
    on_disk = spec_frontmatter.parse(spec_paths.read_text(doc))[0].get(StageKey.STAGE) or ""
    result.refused.append({ _DOC: str(doc), _REASON: outcome.reason or "", _STAGE: on_disk })
  elif outcome.status == set_stage.StageStatus.SET:
    bucket.append(str(doc))


def promote_approved(note: Path, *,
                     transitioned: frozenset[str] = frozenset(),
                     now: str | None = None) -> PromoteResult:
  """
  Promote every accepted document of a status folder-note's ladder in one pass.

  An accepted draft becomes `approved`; an already approved document named in `transitioned` is restamped with a
  fresh approval time. A document in its own review or parked as deferred is passed over with a reason, and
  attachments follow their owner's stage. A refusal on one document never stops the others.

  Guarantees:
    - Never commits; every written path is listed once in `touched_paths`, in first-write order.
    - A repeat on an already reconciled folder, with no document named in `transitioned`, writes nothing and
      reports empty lists.

  Args:
    note: The status folder-note whose ladder is walked.
    transitioned: Basenames of the approved documents whose approval is renewed.
    now: The approval time to stamp, as an ISO 8601 string; the current UTC time when omitted.

  Returns:
    The promoted, restamped, mirrored, skipped, and refused documents together with every written path.

  Raises:
    RuntimeError: If a written document does not carry the stage on disk after the write.
  """

  # Contract:
  # This call NEVER commits; the commit belongs to the caller.

  # Contract:
  # Every path this call writes is listed exactly once in `touched_paths`, in the order it was first written.

  # Contract:
  # A repeat on an already reconciled folder, with no document named in `transitioned`, writes nothing.

  # Domain(spec.lifecycle):
  # # Which documents of a ladder are promoted
  # Only an authored document that carries an accepted review verdict is a candidate for promotion; a document
  # without one has nothing to promote. An attachment is never promoted on its own: it follows the stage of the
  # document that owns it. A document that is in its own review is skipped until that review ends, and a deferred
  # document is passed over even when its verdict is accepted. An accepted draft becomes approved. An approved
  # document that the wake names as transitioned is a renewed approval and is restamped with a fresh approval time.
  # After the documents are settled, every attachment catches up with the stage its owner now holds.

  result = PromoteResult()
  documents = _ladder_documents(note)

  # every accepted document is promoted, restamped on a named re-approval, or passed over with a reason
  for doc in documents:
    values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))

    # guard: an attachment follows its owner and a document without an accepted verdict has nothing to promote
    if values.get(AttachmentKey.OWNER_DOC) or values.get(SpecKey.REVIEW_RESULT) not in ReviewResultValue.ACCEPTED:
      continue

    # a document in its own review is the review loop's business until the review ends: reported as skipped
    if values.get(SpecKey.REVIEW_ACTIVE) == _TRUE:
      result.skipped.append({ _DOC: str(doc), _REASON: SKIP_IN_REVIEW })
      continue

    # a parked document is passed over even with an approved verdict: reported as skipped
    if values.get(StageKey.STAGE) == Stage.DEFERRED:
      result.skipped.append({ _DOC: str(doc), _REASON: SKIP_DEFERRED })
      continue

    # an accepted draft is promoted; an approved document the wake names is a re-approval
    if set_stage.is_stage_lagging(doc):
      _move(doc, result, result.promoted, restamp = False, now = now)
    elif values.get(StageKey.STAGE) == Stage.APPROVED and doc.name in transitioned:
      _move(doc, result, result.restamped, restamp = True, now = now)

  # every owner's attachments catch up with the owner's stage as it now stands
  for doc in documents:
    values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))
    stage = values.get(StageKey.STAGE)
    if stage and not values.get(AttachmentKey.OWNER_DOC):
      result.add_attachments(set_stage.cascade_attachments(doc, stage))
  return result


def main(argv: list[str]) -> int:
  """
  Run the `promote-approved` verb.

  Promote the accepted drafts of the note's ladder, restamp the named re-approvals, and catch attachments up, without
  committing. Print the result as one JSON line.

  Notes:
    - Every change to the other documents is already written when the verb exits with 1; a refused document is left
      untouched, and its entry's `stage` names the stage it keeps on disk.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    1 when at least one document was refused, 0 otherwise.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs promote-approved")
  # waiver: argparse CLI signature -- positional argument names
  parser.add_argument("note", type = Path)
  # waiver: argparse CLI signature -- repeatable option flag
  parser.add_argument("--transitioned", action = "append", default = [])
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--now", default = None)
  args = parser.parse_args(argv)

  # one JSON line carries the whole result; a refusal on any document is the exit code's business
  result = promote_approved(args.note, transitioned = frozenset(args.transitioned), now = args.now)
  print(json.dumps(dataclasses.asdict(result), ensure_ascii = False))
  return _EXIT_REFUSED if result.refused else _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
