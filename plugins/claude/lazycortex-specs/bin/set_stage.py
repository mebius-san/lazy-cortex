from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_decisions  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import summary_render  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES, AttachmentKey, ReviewResultValue, SpecKey, Stage, StageKey,
)


# The closed stage set, in the order the refusal lists it.
STAGES = ( Stage.EMPTY, Stage.DRAFT, Stage.APPROVED, Stage.REJECTED, Stage.CANCELLED, Stage.DEFERRED )

# The two stages a deferred document may leave for.
_DEFERRED_EXITS = frozenset({ Stage.DRAFT, Stage.CANCELLED })

# The document types mandatory for their asset's category, which no caller may cancel.
_UNCANCELLABLE_TYPES = frozenset({ "design", "system-design", "bug", "system-architecture" })

# The replacement each removed stage value points its caller at.
_REMOVED_STAGE_HINTS = {
    "review": "use `draft` + `review_active: true`",
    "done": "use `approved`",
    "wtr": "use `draft` or `approved` per intent",
}

# The mirror tag's prefix, the approval stamp key, and the stamp's UTC format.
_STAGE_TAG_PREFIX = "spec/"
_APPROVED_AT = "spec_approved_at"
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# The markdown suffix an attachment carries, and the frontmatter spelling of a true flag.
_MD = ".md"
_TRUE = "true"

# The living-doc roles whose approval transfers `[!decision]` blocks into the registry.
_LIVING_ROLES = frozenset({ "vision", "design", "bug", "tech", "architecture" })

# The `decide promote` result keys this module reads.
_PROMOTE_STATUS = "status"
_PROMOTE_REFUSED = "refused"
_PROMOTE_REASON = "reason"
_PROMOTE_TOUCHED = "touched_paths"

# A `[!decision-candidate]` callout opener, at any blockquote depth.
_CANDIDATE_RE = re.compile(r"^\s*(?:>\s*)+\[!decision-candidate\]", re.IGNORECASE)


# ----------------------------------------------------------------------------------------
class StageStatus:
  """
  Outcome words of a stage change.

  Attributes:
    SET: The change wrote at least one file.
    NOOP: The change found every file already in the requested state and wrote nothing.
    REFUSED: The change was refused, either by the document validation or by the decision registry.
  """

  SET = "set"
  NOOP = "noop"
  REFUSED = "refused"


# ----------------------------------------------------------------------------------------
class SetStageRefusedError(Exception):
  """
  Refusal of a stage change by the document validation.

  Attributes:
    reason: The human-readable refusal reason.
  """

  def __init__(self, reason: str) -> None:
    # the exception's own message is the reason itself
    super().__init__(reason)

    # the reason, kept for callers that report it without parsing the message
    self.reason: str = reason


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class ValidatedDoc:
  """
  Facts about a document that passed the stage-change validation.

  Attributes:
    doc_type: The document's declared `spec_doc_type`.
    product: The owning product's key, empty when the document belongs to no product.
    current_stage: The document's `spec_stage` before the change, empty when it carries none.
    role: The document's `spec_role`, empty when it carries none.
  """

  doc_type: str
  product: str
  current_stage: str
  role: str


def _find_candidate_line(text: str) -> int | None:
  """
  Find the first open decision-candidate callout in a document body.

  Args:
    text: The document's full text.

  Returns:
    The one-based line number of the first callout outside a code fence, or None when there is none.
  """
  # the body starts on the line after the frontmatter's closing fence
  _fm_body, end = spec_frontmatter.block(text)
  first_body = text[:end].count("\n")
  body = spec_frontmatter.split_lines(text)[first_body:]

  # the first callout outside a code fence, numbered as a line of the whole file
  for offset, ( line, in_fence ) in enumerate(zip(body, spec_frontmatter.fenced_lines(body), strict = True)):
    if not in_fence and _CANDIDATE_RE.match(line):
      return first_body + offset + 1
  return None


def _to_repo_relative(path: Path, repo: Path) -> str:
  """
  Express a path relative to the repository root.

  Args:
    path: The path to express.
    repo: The repository root.

  Returns:
    The POSIX-style repo-relative path, or the absolute POSIX path when `path` lies outside the repository.
  """
  resolved = path.resolve()
  return resolved.relative_to(repo).as_posix() if resolved.is_relative_to(repo) else resolved.as_posix()


def validate(doc: Path, stage: str, *, restamp: bool) -> ValidatedDoc:
  """
  Check that a document may move to the requested stage.

  Guarantees:
    - A document at `cancelled` is moved to no stage but `draft`; every other move out of `cancelled` is refused.

  Args:
    doc: The document to validate.
    stage: The requested stage.
    restamp: Whether the caller asks to restamp the approval time.

  Returns:
    The validated facts about the document.

  Raises:
    SetStageRefusedError: If the document carries no declared staged type, is an attachment, the stage is outside the
      closed set, an approval would leave a decision-candidate open, a deferred document is moved anywhere but
      `draft` or `cancelled`, a cancelled document is moved to any stage but `draft`, a category-mandatory type is
      cancelled, or `restamp` is asked for a stage other than `approved`.
  """

  # Contract:
  # A document at `cancelled` is moved to no stage but `draft`; every other move out of
  # `cancelled` is refused with `SetStageRefusedError`.

  text = spec_paths.read_text(doc)
  values, _end = spec_frontmatter.parse(text)

  # 1. the document declares a type
  doc_type = spec_doc_types.doc_type_of(doc)

  # guard: an untyped document has no stage ladder to move on
  if not doc_type:
    raise SetStageRefusedError("document carries no spec_doc_type")

  # 2. the type is declared in the owning product's scope, and it carries stages
  repo = spec_paths.find_settings_root(doc.parent)
  product, _record = resolve_product.resolve_product_by_path(repo, _to_repo_relative(doc, repo))
  declaration = spec_doc_types.resolve(repo, doc_type, product)

  # guard: a type the product never declared has no stage rules to check against
  if declaration is None:
    raise SetStageRefusedError(f"type `{doc_type}` is not declared in this product's scope")

  # guard: a type declared without stages carries no spec_stage to set
  if not declaration.get(spec_doc_types.DocTypeFlag.STAGES):
    raise SetStageRefusedError(f"type `{doc_type}` carries no spec_stage")

  # 2a. the document is not an attachment
  owner = values.get(AttachmentKey.OWNER_DOC, "")

  # guard: an attachment's stage mirrors its owner's and is never set on its own
  if owner:
    raise SetStageRefusedError(
        f"document is an attachment of `{owner}` — its stage mirrors the owner's; set the owner's stage instead")

  # Domain(spec.lifecycle):
  # # Stage ladder of an authored document
  # An authored document sits at exactly one of six stages: none yet, draft, approved, rejected, cancelled or deferred.
  # The set is closed. Three older stage words (review, done and wtr) were retired: a document under review is a
  # draft with its review switched on, a finished one is approved, and a waiting one is a draft or approved by intent.
  # A request for a retired word is refused with its replacement named. The stage is always mirrored by a matching
  # stage tag on the same document, so the two never disagree.

  # guard: 3. a stage outside the closed set is refused, with the replacement named for a removed one
  if stage not in STAGES:
    hint = _REMOVED_STAGE_HINTS.get(stage)
    suffix = f"; {hint}" if hint else ""
    raise SetStageRefusedError(f"stage `{stage}` is not in the closed set {' | '.join(STAGES)}{suffix}")

  # Domain(spec.lifecycle):
  # # No approval while a decision-candidate is open
  # A decision-candidate is a question the document still asks of its reviewers. A document that still carries one
  # outside a code example is not settled, so it cannot be approved: the candidate is folded through the document's
  # review first. An approval therefore never ships an open questionnaire.

  # guard: 4. an approval ships no questionnaire
  if stage == Stage.APPROVED and (line := _find_candidate_line(text)) is not None:
    raise SetStageRefusedError(
        f"document carries a decision-candidate at line {line} — fold it through the document's review "
        f"before approving")

  # the stage the document carries now, which the parked-document check and the write both read
  current = values.get(StageKey.STAGE, "")

  # Domain(spec.lifecycle):
  # # Exits of a deferred document
  # A deferred document is parked, not decided. It leaves that stage only by returning to draft, to be worked again,
  # or by being cancelled, to be abandoned. It cannot jump straight to approved, rejected or any other stage.

  # guard: a parked document has exactly two exits
  if current == Stage.DEFERRED and stage not in _DEFERRED_EXITS:
    raise SetStageRefusedError("document is deferred — set it to `draft` or `cancelled` first")

  # Domain(spec.lifecycle):
  # # A cancelled document has one way back
  # Cancelling abandons a document together with its asset. Its one way back is draft, taken when its asset is
  # un-cancelled. From cancelled it cannot be approved, rejected, parked or emptied.

  # guard: a cancelled document's one exit is draft, taken when its asset is un-cancelled
  if current == Stage.CANCELLED and stage not in ( Stage.CANCELLED, Stage.DRAFT ):
    raise SetStageRefusedError("document is cancelled — its only exit is `draft`")

  # Domain(spec.lifecycle):
  # # Mandatory documents are never cancelled
  # Some document types are mandatory for their asset's category: design, system design, bug and system architecture.
  # An asset of that category cannot exist without them, so such a document may be rejected or deferred but never
  # cancelled. Cancelling is available for every other staged type.

  # guard: a category-mandatory type is never cancelled
  if stage == Stage.CANCELLED and doc_type in _UNCANCELLABLE_TYPES:
    raise SetStageRefusedError(f"cancelled not allowed on `{doc}`")

  # guard: the restamp rides only on an approval
  if restamp and stage != Stage.APPROVED:
    raise SetStageRefusedError("--restamp is valid only with `approved`")

  # what the write needs to know about the document that passed
  return ValidatedDoc(doc_type = doc_type, product = product or "", current_stage = current,
                      role = values.get(SpecKey.ROLE, ""))


# ----------------------------------------------------------------------------------------
@dataclass
class StageResult:
  """
  Outcome of a stage change.

  Attributes:
    status: The outcome word, one of the `StageStatus` values.
    stage: The stage that was requested.
    reason: The refusal reason, present only on a refusal.
    approved_at: The approval time stamped by this change, present only when it stamped one.
    attachments: Paths of the attachments whose stage the change mirrored.
    touched_paths: Paths of every file the change wrote, for the caller's commit.
  """

  status: str
  stage: str
  reason: str | None = None
  approved_at: str | None = None
  attachments: list[str] = field(default_factory = list)
  touched_paths: list[str] = field(default_factory = list)


def _utc_now() -> str:
  """
  Return the current UTC time in the approval-stamp format.

  Returns:
    The timestamp as an ISO 8601 string ending in `Z`.
  """
  return datetime.now(UTC).strftime(_STAMP_FORMAT)


def _stamp_stage(text: str, stage: str) -> str:
  """
  Set a document's stage scalar and its mirror tag to the same stage.

  Args:
    text: The document's full text.
    stage: The stage to record.

  Returns:
    The document text carrying the new stage and its `spec/<stage>` tag.
  """
  # the stage scalar and its mirror tag always move together
  text = spec_frontmatter.set_scalar(text, StageKey.STAGE, stage)
  return spec_frontmatter.sweep_tag(text, _STAGE_TAG_PREFIX, f"{_STAGE_TAG_PREFIX}{stage}")


def _write_verified(path: Path, text: str, stage: str) -> None:
  """
  Write a document and confirm the stage landed on disk.

  Args:
    path: The document to write.
    text: The full text to write.
    stage: The stage the written document must carry.

  Raises:
    RuntimeError: If the document does not carry `stage` after the write.
  """
  spec_paths.write_text_atomic(path, text)

  # the stage the document carries once the write landed
  values, _end = spec_frontmatter.parse(spec_paths.read_text(path))

  # guard: a write that did not land the stage would report a promotion that never happened
  if values.get(StageKey.STAGE) != stage:
    raise RuntimeError(f"spec_stage on {path} is not `{stage}` after the write")


def cascade_attachments(owner: Path, stage: str) -> list[str]:
  """
  Mirror an owner document's stage onto its attachments.

  Attachments sitting in their own review (`review_active: true`) are skipped.

  Args:
    owner: The owner document whose folder is scanned for attachments.
    stage: The stage to mirror.

  Returns:
    Paths of the attachments that were rewritten.

  Raises:
    RuntimeError: If a rewritten attachment does not carry `stage` on disk after the write.
  """

  # Domain(spec.lifecycle):
  # # An attachment's stage mirrors its owner's
  # An attachment is a document that belongs to another document, its owner. It has no stage of its own: setting it
  # directly is refused, and whenever the owner changes stage every attachment follows to the same stage. An
  # attachment that is itself under review is left alone, because its reviewers own its state until that review ends.

  restamped: list[str] = []
  for name in sorted(os.listdir(owner.parent)):
    path = owner.parent / name

    # guard: only another markdown file can be one of the owner's attachments
    if path == owner or not name.endswith(_MD) or not path.is_file():
      continue

    # the candidate's own frontmatter says whose attachment it is
    text = spec_paths.read_text(path)
    values, _end = spec_frontmatter.parse(text)

    # guard: a file owned by another document, or one sitting in its own review, is not this cascade's
    if values.get(AttachmentKey.OWNER_DOC) != owner.name or values.get(SpecKey.REVIEW_ACTIVE) == _TRUE:
      continue

    # an attachment already at the owner's stage is left byte for byte
    new = _stamp_stage(text, stage)
    if new != text:
      _write_verified(path, new, stage)
      restamped.append(str(path))
  return restamped


def _refresh_containers(doc: Path) -> list[str]:
  """
  Re-tally the stats of the container notes that count a document's asset.

  A document sitting beside a level note refreshes nothing.

  Args:
    doc: The document whose stage just changed.

  Returns:
    Paths of the container notes whose stats changed.
  """
  folder_note = doc.parent / f"{doc.parent.name}{_MD}"

  # guard: a level document sits beside its level note, whose counts no stage move below it changes
  if folder_note.is_file():
    values, _end = spec_frontmatter.parse(spec_paths.read_text(folder_note))
    if values.get(SpecKey.ROLE) in LEVEL_ROLES:
      return []

  # every container above the asset re-tallies, and only a note whose stats moved is reported
  return [ str(note) for note in flip_gate.containers_above(doc.parent)
           if summary_render.apply_container_stats(note) ]


def _drop_key(text: str, key: str) -> str:
  """
  Remove one key's line from a document's frontmatter block, if present.

  Args:
    text: The full document text.
    key: The frontmatter key to remove.

  Returns:
    The text without the frontmatter's line for `key`; the body is never touched, and the text is unchanged
    when the key is absent.
  """
  _lines, end = spec_frontmatter.block(text)
  head = re.sub(rf"(?m)^{re.escape(key)}[ \t]*:.*\r?\n", "", text[:end], count = 1)
  return head + text[end:]


def apply_stage(doc: Path, stage: str, *,
                restamp: bool = False,
                now: str | None = None) -> StageResult:
  """
  Move one authored document to a stage.

  The document, its `spec/<stage>` mirror tag, its attachments, and the container notes counting it all end up
  consistent with the new stage; a real approval carries a `spec_approved_at` stamp, and an approved living
  document's decisions reach the registry.

  Guarantees:
    - Never commits; every written path is listed in the result's `touched_paths` for the caller's commit.
    - Moving an `approved` document to `draft` also removes its `review_result` from the frontmatter, so no
      later promotion pass can return the document to `approved`.
    - Moving a `cancelled` document to `draft` also removes its `review_result` from the frontmatter, so a
      document that returns from cancellation is reviewed again before it can be approved.
    - Moving a document out of `approved` to any other stage removes its `spec_approved_at` stamp, so the stamp
      exists only while the document is `approved`.

  Notes:
    - Approving a living document is first put to the decision registry; on its refusal nothing is written, the
      document keeps its previous stage, and `touched_paths` is empty.

  Args:
    doc: The document to move.
    stage: The requested stage.
    restamp: Whether to restamp the approval time on an already approved document.
    now: The approval time to stamp, as an ISO 8601 string; the current UTC time when omitted.

  Returns:
    The outcome, carrying the refusal reason on a refusal and the written paths otherwise.

  Raises:
    RuntimeError: If a written document does not carry `stage` on disk after the write.
  """

  # Contract:
  # This call NEVER commits; the commit belongs to the caller.

  # Contract:
  # Every path this call writes is listed in the result's `touched_paths`,
  # so the caller's commit carries the whole change.

  # Contract:
  # Moving an `approved` document to `draft` also removes its `review_result` from the
  # frontmatter, so no later promotion pass can return the document to `approved`.

  # Contract:
  # Moving a `cancelled` document to `draft` also removes its `review_result` from the
  # frontmatter, so a document that returns from cancellation walks review again before approval.

  # Contract:
  # The `spec_approved_at` stamp exists only while the document is `approved`:
  # every move out of `approved` to any other stage removes it, so a reader never
  # takes a stale stamp for a current approval.

  try:
    validated = validate(doc, stage, restamp = restamp)
  except SetStageRefusedError as refused:
    return StageResult(status = StageStatus.REFUSED, stage = stage, reason = refused.reason)

  # Domain(spec.decisions):
  # # Approval of a living document hands its decisions to the registry
  # Vision, design, bug, tech and architecture documents live on after approval, so the decisions written inside them
  # are kept in the decision registry rather than in the text. Approving one of them moves its decisions there. Before
  # anything is written, the registry is asked whether it will accept the transfer. It may refuse, for example because
  # the owning asset is cancelled, halted or already released. A refusal means the approval does not happen at all: no
  # file is written, the document keeps its previous stage, and the outcome is reported as a refusal with the
  # registry's reason. When the registry accepts, the stage is written and the decisions are moved into the registry.

  # an approved living doc hands its decisions to the registry, so the registry is asked before any write
  promotes = stage == Stage.APPROVED and validated.role in _LIVING_ROLES

  # guard: a registry refusal leaves every file as it was
  if promotes and (reason := spec_decisions.promote_refusal(doc)) is not None:
    return StageResult(status = StageStatus.REFUSED, stage = stage, reason = reason)

  # Domain(spec.lifecycle):
  # # Approval stamp
  # An approved document records the moment of its approval, and that moment exists only while the document is
  # approved. It is written when the document enters approved from any other stage, and again only when the caller
  # explicitly asks to restamp. It is removed on every move out of approved, whether to draft, rejected, cancelled,
  # deferred or empty, so nobody reads a past approval as a current one. Approving a document that is already
  # approved leaves the original moment untouched, so a repeated call never rewrites history. The stamp belongs to
  # approval alone: asking to restamp while moving to any other stage is refused. The moment is the current UTC time
  # unless the caller supplies one.

  # the stage, its mirror tag and, on a real approval or a restamp, the approval stamp land in one edit
  text = spec_paths.read_text(doc)
  new = _stamp_stage(text, stage)

  # Domain(spec.lifecycle):
  # # Rolling an approved document back retracts its verdict
  # Moving an approved document back to draft is the one downward stage move, made when what the document was built
  # from has changed. The review verdict that approved it no longer describes it, so the move retracts that verdict
  # too; otherwise the document would read as accepted-but-not-yet-promoted and be promoted straight back.

  # Domain(spec.lifecycle):
  # # A document returning from cancellation is reviewed again
  # A cancelled document comes back only to draft, and it comes back to be reviewed and then approved. A verdict it
  # carried from before the cancellation describes the document as it stood then, not a review it has passed since,
  # so the return to draft retracts that verdict as well; otherwise a document cancelled after approval would read
  # as accepted-but-not-yet-promoted and be approved again without any review.

  # a roll-back from approved, or a return from cancellation, drops the old verdict, so the next promote walk
  # cannot approve the document on it
  if stage == Stage.DRAFT and validated.current_stage in ( Stage.APPROVED, Stage.CANCELLED ):
    new = _drop_key(new, SpecKey.REVIEW_RESULT)

  # a move out of approved retracts the approval moment, so no reader takes a stale stamp for a current approval
  if stage != Stage.APPROVED and validated.current_stage == Stage.APPROVED:
    new = _drop_key(new, _APPROVED_AT)

  # a real approval or an explicit restamp records the approval moment
  approved_at = None
  if stage == Stage.APPROVED and (validated.current_stage != Stage.APPROVED or restamp):
    approved_at = now or _utc_now()
    new = spec_frontmatter.set_scalar(new, _APPROVED_AT, approved_at)
  touched: list[str] = []
  if new != text:
    _write_verified(doc, new, stage)
    touched.append(str(doc))

  # every attachment outside its own review mirrors the owner's new stage
  attachments = cascade_attachments(doc, stage)
  touched.extend(attachments)

  # every container note counting the asset re-tallies its stats
  touched.extend(_refresh_containers(doc))

  # the outcome of the stage write, before any decision registry hand-off
  result = StageResult(status = StageStatus.SET if touched else StageStatus.NOOP, stage = stage,
                       approved_at = approved_at, attachments = attachments, touched_paths = touched)

  # the registry already accepted the transfer above; a refusal here could only come from a race
  if promotes:
    promoted = spec_decisions.promote(doc)
    if promoted.get(_PROMOTE_STATUS) == _PROMOTE_REFUSED:
      result.status = StageStatus.REFUSED
      result.reason = promoted.get(_PROMOTE_REASON)
      return result
    for path in promoted.get(_PROMOTE_TOUCHED, []):
      if path not in result.touched_paths:
        result.touched_paths.append(path)
    if result.touched_paths:
      result.status = StageStatus.SET
  return result


def is_stage_lagging(doc: Path) -> bool:
  """
  Check whether a document was accepted in review yet still sits at `draft`.

  Args:
    doc: The document to check.

  Returns:
    True when the document carries an accepted `review_result`, `spec_stage: draft`, no active review, and is
    not an attachment.
  """
  values, _end = spec_frontmatter.parse(spec_paths.read_text(doc))
  return (
      values.get(SpecKey.REVIEW_RESULT) in ReviewResultValue.ACCEPTED
      and values.get(StageKey.STAGE) == Stage.DRAFT
      and values.get(SpecKey.REVIEW_ACTIVE) != _TRUE
      and not values.get(AttachmentKey.OWNER_DOC)
  )


def main(argv: list[str]) -> int:
  """
  Run the `set-stage` verb.

  Print the outcome as one JSON line.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    1 when the change was refused, 0 otherwise.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs set-stage")
  # waiver: argparse CLI signature -- positional argument names
  parser.add_argument("file", type = Path)
  # waiver: argparse CLI signature -- positional argument names
  parser.add_argument("stage")
  # waiver: argparse CLI signature -- the legacy author argument, accepted and ignored
  parser.add_argument("author", nargs = "?", default = None)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--restamp", action = "store_true")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--now", default = None)
  args = parser.parse_args(argv)

  # one JSON line carries the whole result; the exit code tells success from refusal
  result = apply_stage(args.file, args.stage, restamp = args.restamp, now = args.now)
  print(json.dumps({
      "status": result.status, "stage": result.stage, "approved_at": result.approved_at,
      "attachments": result.attachments, "touched_paths": result.touched_paths, "reason": result.reason,
  }, ensure_ascii = False))
  return 1 if result.status == StageStatus.REFUSED else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
