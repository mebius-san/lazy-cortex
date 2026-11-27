from __future__ import annotations

from typing import NamedTuple

import argparse
import json
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
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
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import ParseError, SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import JobKey, JobMarker, ReportVerdictKind, ResultValue, ReviewKey, Tag  # noqa: E402


# A task line of the body: optional indentation, a `-` / `*` / `+` bullet, a checkbox, then the line's text.
_TASK_LINE_RE = re.compile(r"^[ \t]*[-*+][ \t]+\[([ xX])\][ \t]+(.*)$")

# The send-back tag as a whole tag: no tag character may follow it, and it starts a token.
_SEND_BACK_TAG_RE = re.compile(rf"(?<![\w/#-]){re.escape(Tag.SEND_BACK)}(?![\w/-])")

# The checkbox characters that read as ticked.
_TICKED_CHARS = frozenset({ "x", "X" })

# The exit code of a refused send-back: the document is left byte-identical.
EXIT_REFUSED = 2

# The exit code of a send-back whose document does not exist.
EXIT_MISSING_FILE = 1

# The bare YAML boolean literal a set frontmatter flag carries.
_YAML_TRUE = "true"

# The verb name the parser reports in its usage line.
_VERB = "send-back"

# The stdout key naming how many ticked items the send-back handed back.
SENT_BACK_KEY = "sent_back"

# The stdout key naming the `review_result` a send-back stamped.
RESULT_KEY = "result"

# The result each writer verdict closes a report's review with.
_VERDICT_RESULTS: dict[str | None, str] = {
    ReportVerdictKind.SUFFICIENT: ResultValue.SENT_BACK,
    ReportVerdictKind.NEW_PLAN: ResultValue.SENT_TO_PLAN,
}


# ----------------------------------------------------------------------------------------
class SendBackItem(NamedTuple):
  """
  Problem a document's producer listed for the operator to hand back for fixing.

  A send-back item is a task line of a document body that carries the whole `#review/send-back` tag. The operator
  ticks its checkbox to send the problem back.

  Attributes:
    line: Position of the item within the body it was found in, counted from 1.
    text: The item's line without its bullet, checkbox and tag.
    ticked: Whether the operator ticked the item's checkbox.
  """

  line: int
  text: str
  ticked: bool


def find_all_send_back_items(body: str) -> list[SendBackItem]:
  """
  Find the send-back items of a document body.

  Guarantees:
    - A line inside a fenced code block is never an item, whatever it contains.
    - Items come back in document order.

  Args:
    body: Document body to scan, without its frontmatter.

  Returns:
    The send-back items, each with its 1-based line within `body`; empty when the body holds none.
  """

  # Domain(review.markup):
  # # Send-back item
  # A send-back item is a problem that a document's producer lists as its own task line and tags as
  # sendable. A line inside literal code is never an item. The operator ticks the items that must be
  # fixed; an item left unticked stays open and is not handed back.

  # Contract:
  # A line inside a fenced code block is never an item, whatever it contains.

  # Contract:
  # Items come back in document order.

  # walk the body chunk by chunk, so a fenced code block's literal lines are never read as items
  items: list[SendBackItem] = []
  line_no = 0
  for chunk in _parser.split_fenced(body):
    for raw_line in chunk.text.splitlines():
      line_no += 1

      # a fenced line is literal code, and a line that is no task line carrying the whole tag is ordinary text
      if (chunk.fenced
          or (task := _TASK_LINE_RE.match(raw_line)) is None
          or not _SEND_BACK_TAG_RE.search(task.group(2))):
        continue

      # the item keeps the problem's own words, the tag dropped, and whether the operator ticked it
      items.append(SendBackItem(
          line_no, _SEND_BACK_TAG_RE.sub("", task.group(2)).strip(), task.group(1) in _TICKED_CHARS,
      ))
  return items


def send_back_text(text: str, *, result: str = ResultValue.SENT_BACK) -> str:
  """
  End a document's review cycle without approval by marking it as sent back.

  The review banner and every `review_*` frontmatter key are removed, and `review_result` is set to `result`.

  Guarantees:
    - Every byte outside the banner and the `review_*` frontmatter keys is kept unchanged, including the producer's
      task lines with their ticks, the `# History` section and every other frontmatter key.
    - Applying it to its own result returns that result unchanged.

  Args:
    text: Full document text, in LF line endings.
    result: The `review_result` value to stamp: `sent-back`, or `sent-to-plan` for a report sent to a new plan.

  Returns:
    The document text with the cycle ended.

  Raises:
    ParseError: If the frontmatter has an opening fence with no matching closing fence.
  """

  # Contract:
  # Every byte outside the banner and the `review_*` frontmatter keys is kept unchanged: the producer's task lines
  # with their ticks, the `# History` section and every other frontmatter key. The producer later reads exactly the
  # ticked lines as its work order.

  # Contract:
  # Applying it to its own result returns that result unchanged.

  # split the document once; the frontmatter half and the body half are rewritten independently
  meta, body = _fm.parse(text)
  fm_text = text[: len(text) - len(body)]

  # the banner offers gestures of a cycle that is ending, so it goes; the rest of the body stays as written
  body = _banner.strip_banner(body)

  # every review key belongs to the ending cycle, then the verdict that hands the document back is stamped
  for key in [ key for key in meta if key.startswith(ReviewKey.PREFIX) ]:
    fm_text = _fm.unset_field(fm_text, key)
  return _fm.set_field(fm_text, ReviewKey.RESULT, result) + body


def _refuse(reason: str) -> int:
  """
  Report a refused send-back on stderr and return its exit code.

  Args:
    reason: The refusal's cause, written after the `refused:` prefix.

  Returns:
    The exit code of a refused send-back.
  """
  # one stderr line names the refusal; the document stays untouched
  sys.stderr.write(f"refused: {reason}\n")
  return EXIT_REFUSED


def _decision_result(repo: Path, file_path: Path) -> tuple[str | None, str]:
  """
  Resolve the `review_result` a report's fix-by-remarks closes its review with.

  Args:
    repo: Repository root holding the marker sidecar; the settings are the document's nearest ones.
    file_path: The report document.

  Returns:
    A pair: the result named by the writer's recorded verdict, or `None` with the refusal's cause as the second
    item when the document is no report, the verdict is missing or unknown, or settings or sidecar cannot be read.
  """

  # unreadable settings say nothing about the class, so they refuse instead of reading as a plain class
  try:
    settings_root = _core_settings.query_settings_root_for(file_path)
    settings = _core_settings.read_merged_sections(settings_root, JobKey.REVIEW)
  except (RuntimeError, SettingsReadError) as error:
    return None, f"the review settings cannot be read, so the document's class is unknown: {error}"

  # guard: only a report class carries a writer's verdict
  if not _doc_class.is_report_class(settings, settings_root, file_path):
    return None, f"{file_path} is not of a report class"

  # an unreadable sidecar refuses too, never reads as "no verdict"
  try:
    verdict = _job_markers.read_checked(repo, file_path)[JobMarker.VERDICT]
  except OSError as error:
    return None, f"the marker sidecar cannot be read: {error}"

  # guard: no verdict, or one the closed set does not know, names no result
  if (result := _VERDICT_RESULTS.get(verdict)) is None:
    return None, f"no writer verdict is recorded for {file_path}"
  return result, ""


def main(argv: list[str]) -> int:
  """
  Run the `send-back <file> [--repo] [--decision]` verb, handing a document back for fixing.

  The document is rewritten in place with its review cycle ended, and its line endings are kept. The verb makes
  no commit. With `--decision` no ticked item is needed: the result comes from the writer's verdict recorded for
  the report, `sufficient` closing the review as `sent-back` and `new-plan` as `sent-to-plan`.

  Guarantees:
    - A refused send-back, exit code 2, and a missing file, exit code 1, leave the document byte-identical.
    - A successful send-back replaces the document atomically, so a reader never sees a partial write.
    - A successful send-back keeps the line endings the document had before it.
    - A successful send-back, with or without `--decision`, clears the writer's verdict recorded for the document
      in the marker sidecar, so it never carries into the next cycle.
    - The verb never commits.

  Notes:
    - Writes one JSON line `{"sent_back": <number of ticked items>}` to stdout on success; with `--decision` the
      line also carries `"result"`, the `review_result` value stamped, and the count is 0 when no item is ticked.
    - Writes one line naming the cause to stderr on a refusal or a missing file.
    - A relative `file` is resolved against the root of the checkout `--repo` names; an absolute `file` wins over it.

  Args:
    argv: Command-line arguments after the verb name: the document path, an optional `--repo` directory inside the
      repository (default: `$LAZY_REPO_ROOT`, then the working directory) and the optional `--decision` flag.

  Returns:
    0 on success; 1 when the file does not exist; 2 when the frontmatter does not parse, the document is not
    under review, no send-back item is ticked and `--decision` is absent, or, with `--decision`, the review
    settings cannot be read, the document is not of a report class, no known writer verdict is recorded, or the
    marker sidecar cannot be read.

  Raises:
    SystemExit: If the arguments are invalid.
    UnicodeDecodeError: If the document is not valid UTF-8.
    OSError: If the document cannot be read or written, or the marker sidecar cannot be rewritten.
  """

  # Domain(review.lifecycle):
  # # Ending a review cycle by sending back
  # When the operator ticks at least one send-back item, the review cycle ends without approval: its
  # gestures and control state go, and the document gets the sent-back outcome that tells its producer
  # to fix the ticked problems. Everything the producer wrote, ticks included, stays. An approval
  # ticked at the same time is not taken: the operator approves again once the fixes are back under
  # review. A document not under review, or with nothing ticked and no decision asked for, is refused and left
  # untouched.

  # Contract:
  # A refused call, exit code 2, and a call for a missing file, exit code 1, leave the document byte-identical.

  # Contract:
  # A successful call replaces the document atomically: a reader sees either the old text or the new text,
  # never a partial write.

  # Contract:
  # A successful call keeps the line endings the document had before it.

  # Contract:
  # A successful call, with or without `--decision`, clears the writer's verdict recorded for the document in the
  # marker sidecar, so that verdict never carries into the next review cycle.

  # Contract:
  # The verb never commits; the caller owns the commit that carries the change.

  # parse the verb's arguments
  ap = argparse.ArgumentParser(prog = _VERB)
  # waiver: argparse CLI signature, not a domain key
  ap.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  ap.add_argument("--repo", default = None)
  # waiver: argparse CLI signature, not a domain key
  ap.add_argument("--decision", action = "store_true")
  args = ap.parse_args(argv)

  # resolve the file against the root of the checkout `--repo`, `$LAZY_REPO_ROOT` or the cwd sits in; an absolute
  # file argument wins over that root
  file_path = (_review_locator.query_repo_root(args.repo) / args.file).resolve()

  # guard: only an existing file can be handed back
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return EXIT_MISSING_FILE

  # read the document once, in LF form, so its own line endings come back on write
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))

  # guard: a document whose frontmatter does not parse has no review state to end
  try:
    meta, body = _fm.parse(lf_text)
  except ParseError as error:
    return _refuse(f"frontmatter does not parse in {file_path}: {error}")

  # guard: only a document under review has a cycle to end
  if meta.get(ReviewKey.ACTIVE, "").strip().lower() != _YAML_TRUE:
    return _refuse(f"{file_path} is not under review")

  # the decision flag takes the result from the writer's verdict and needs no ticked item
  result: str = ResultValue.SENT_BACK
  if args.decision:
    decided, cause = _decision_result(_finalize.query_repo_root_for(file_path), file_path)
    # guard: a document with no usable verdict is left untouched
    if decided is None:
      return _refuse(cause)
    result = decided

  # count the operator's ticked send-back items; the count is reported on success
  ticked = sum(1 for item in find_all_send_back_items(body) if item.ticked)
  # guard: without a ticked item and without `--decision` the operator handed nothing back
  if not ticked and not args.decision:
    return _refuse(f"no send-back item is ticked in {file_path}")

  # end the cycle in the working tree; the coordinator's own commit carries it
  closed = send_back_text(lf_text, result = result)
  _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(closed, ending))

  # the cycle just closed, so the verdict it recorded belongs to no later cycle
  _job_markers.clear_verdict(_finalize.query_repo_root_for(file_path), file_path)
  print(json.dumps({ SENT_BACK_KEY: ticked, RESULT_KEY: result } if args.decision else { SENT_BACK_KEY: ticked }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
