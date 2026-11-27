from __future__ import annotations

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
import build_registry  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_halt  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import BuildOutcomeKind, LangId, ReviewResultValue, SiblingDoc, SpecKey  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_lockit import Lockit  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The heading that opens one build's entry in the report, and the shape of the heading lines that close it: the
# next build's entry or any heading above it, never a sub-heading of the entry's own.
_ENTRY_HEADING = "#### build {build}"
_ENTRY_END_RE = re.compile(r"^#{1,4}(\s|$)")

# The lockit keys of the verdict line: the plain rejection, and the rejection whose remarks went into the plan.
_LINE_REJECTED = "report-verdict.rejected"
_LINE_TO_PLAN = "report-verdict.rejected-to-plan"

# The review verdicts this rejection consumes: the report's send-back, which would otherwise fire on the next build.
_CONSUMED_VERDICTS = frozenset({ ReviewResultValue.SENT_BACK, ReviewResultValue.SENT_TO_PLAN })

# The review plugin verb that removes a report's discussion block, the prefix of the reason a failed removal is
# reported with, and the key of its JSON answer.
_STRIP_ARGS = ( "strip-discussion", )
_STRIP_FAILED = "review discussion removal failed"
_STRIPPED = "stripped"

# The verb's output keys.
_BUILD = "build"
_LINE = "line"
_DISCUSSION_STRIPPED = "discussion_stripped"
_ERROR = "error"

# The verb's exit codes.
_EXIT_OK = 0
_EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class ReportRejectRefusedError(Exception):
  """
  Refusal of a report rejection.

  The message is the refusal text the verb reports to its caller.
  """

  def __init__(self, message: str) -> None:
    """
    Create the refusal with the text the verb reports.

    Args:
      message: The refusal text.
    """
    # the refusal text is the exception's own message
    super().__init__(message)


def reject(repo: Path, path: str, build: int, *, to_plan: bool) -> dict:
  """
  Close a build that is not accepted: in its release's report and in the release's build registry.

  Guarantees:
    - A refusal raised before the discussion block is removed leaves the report and the registry untouched; a
      release without a registry record of the build, a report whose `review_result` is an accepted verdict
      (`approved` or `approved-with-concerns`), and a report whose `review_result` is a consumed verdict
      (`sent-to-plan` or `sent-back`) that removing the key would not take away, such as one on an indented line,
      are refused that early.
    - The entry carries one verdict line: a repeated call with the same verdict leaves the report as the first call
      left it, and a call with the other verdict replaces the line the entry ends with.
    - A `review_result` of `sent-to-plan` or `sent-back` is removed from the report's frontmatter in the same write
      as the verdict line, every other byte kept, so it cannot fire again on the next build; a repeated call finds
      nothing to consume and leaves the report as it is.

  Notes:
    - Rewrites the release's `code-report.md` and the release's build registry file; never commits.
    - The writes come in a fixed order: the discussion block is removed, the verdict line is written, then the
      registry records the outcome. A refusal after the first write leaves the earlier writes in place.
    - The entry runs from its heading to the next heading of level 1 to 4 outside a code fence; a deeper
      sub-heading inside it stays part of it.

  Args:
    repo: The repository root.
    path: The release note, or another document of the release, absolute or relative to the current directory.
    build: The number of the build that is not accepted.
    to_plan: Whether the operator's remarks on the build went into the release's plan.

  Returns:
    The build number, the verdict line as written, and whether a discussion block was removed.

  Raises:
    ReportRejectRefusedError: If the report is missing or cannot be read, holds no entry for the build, reads an
      accepted `review_result` verdict (`approved` or `approved-with-concerns`), reads a consumed `review_result`
      verdict (`sent-to-plan` or `sent-back`) that removing the key would not take away, such as one on an
      indented line, its language cannot be resolved, the discussion block cannot be removed or takes the build's
      entry with it, or the report cannot be written.
    build_registry.BuildRegistryRefusedError: If the path is no release of a product, or the registry has no
      record of the build or cannot be read or written.
  """

  # Contract:
  # A refusal raised before the discussion block is removed MUST leave the report and the registry untouched; a
  # release whose registry holds no record of the build, a report whose review result is an accepted verdict, and
  # a report whose review result is a sent-to-plan or sent-back verdict that removing the key would not take away
  # (on an indented line, say) MUST be refused that early, because an accepted build is never rejected and a
  # verdict left live would fire again on the next build. The entry MUST carry one verdict
  # line: the same verdict again leaves the report as it was, the other verdict replaces the line. A review result
  # of sent-to-plan or sent-back MUST be removed from the report's frontmatter in the same write as the verdict
  # line, every other byte kept, so a repeated call finds nothing to consume and leaves the report as it is.

  # Domain(spec.lifecycle):
  # # A build that is not accepted is closed in its report and its registry
  # When the operator does not accept a build, its report loses the discussion of that build and the build's own
  # entry ends with a line saying it was not accepted, and that the remarks went into the plan when they did. The
  # build is then recorded as rejected, so the next build starts on top of its branch while the work it holds is
  # still unmerged. A build carries one verdict: deciding again replaces the line rather than adding a second one.
  # The send-back verdict a review left on the report is consumed by the rejection, so it cannot fire again on the
  # next build, and a build the review accepted is never rejected. A report that has no entry for the build, or a
  # build the registry never recorded, is refused before anything changes.

  # the release and its registry; the report sits beside the release note
  registry = build_registry.BuildRegistry.for_path(repo, path)
  report = registry.note.parent / SiblingDoc.CODE_REPORT
  heading = _ENTRY_HEADING.format(build = build)

  # guard: only a report that holds the build's entry can be closed
  text = _read(report)
  if heading not in _headings(text):
    raise ReportRejectRefusedError(f"{report} holds no entry {heading!r}")

  # guard: a build whose report review accepted is never rejected
  verdict = spec_frontmatter.parse(text)[0].get(SpecKey.REVIEW_RESULT)
  if verdict in ReviewResultValue.ACCEPTED:
    raise ReportRejectRefusedError(f"{report} reads {SpecKey.REVIEW_RESULT}: {verdict}; "
                                   "an accepted build is not rejected")

  # guard: a consumed verdict the key removal cannot reach would stay live after the write and fire again
  dropped = spec_frontmatter.drop_key(text, SpecKey.REVIEW_RESULT)
  remains = spec_frontmatter.parse(dropped)[0].get(SpecKey.REVIEW_RESULT)
  if remains in _CONSUMED_VERDICTS:
    raise ReportRejectRefusedError(f"{report} reads {SpecKey.REVIEW_RESULT}: {remains} in a line the key removal "
                                   "cannot reach; fix the frontmatter")

  # the build's registry record is read before the first write, so a missing one refuses with nothing written
  registry.read_record(build)

  # the line comes in the report's own language, resolved before anything is written
  try:
    line = Lockit.text(_LINE_TO_PLAN if to_plan else _LINE_REJECTED, note_explainers.lang_for_note(report))
  except (RuntimeError, ValueError) as error:
    raise ReportRejectRefusedError(f"the language of {report} cannot be resolved: {error}") from error

  # the review plugin owns the discussion block, so its own verb removes it
  stripped = _strip_discussion(report)

  # the entry ends with one verdict; a report that already ends it with this one is left as it is
  text = _read(report)

  # guard: an entry that left the report with the discussion block has no line to close it
  if heading not in _headings(text):
    raise ReportRejectRefusedError(f"{report} lost its entry {heading!r} with the discussion block")
  values, fm_end = spec_frontmatter.parse(text)
  head = text[:fm_end]

  # the send-back verdict is consumed by this rejection, in the same write, so it cannot fire on the next build
  if values.get(SpecKey.REVIEW_RESULT) in _CONSUMED_VERDICTS:
    head = spec_frontmatter.drop_key(head, SpecKey.REVIEW_RESULT)
  new_text = head + _close_entry(text[fm_end:], heading, line)
  if new_text != text:
    try:
      spec_paths.write_text_atomic(report, new_text)
    except OSError as error:
      raise ReportRejectRefusedError(f"{report} cannot be written: {error}") from error

  # the registry records the build as rejected, last
  registry.close(build, BuildOutcomeKind.REJECTED)
  return { _BUILD: build, _LINE: line, _DISCUSSION_STRIPPED: stripped }


def _read(report: Path) -> str:
  # a report that cannot be read is a refusal naming it, never a traceback
  try:
    return spec_paths.read_text(report)
  except (OSError, ValueError) as error:
    raise ReportRejectRefusedError(f"report {report} cannot be read: {error}") from error


def _headings(text: str) -> set[str]:
  # the heading lines of the text outside code fences, a heading quoted in a fence being code
  lines = spec_frontmatter.split_lines(text)
  fenced = spec_frontmatter.fenced_lines(lines)
  return { row.strip() for idx, row in enumerate(lines) if not fenced[idx] and row.startswith("#") }


def _close_entry(body: str, heading: str, line: str) -> str:
  # the entry runs from its heading to the next heading of its level or above outside a code fence
  lines = spec_frontmatter.split_lines(body)
  fenced = spec_frontmatter.fenced_lines(lines)
  start = next(idx for idx, row in enumerate(lines) if not fenced[idx] and row.strip() == heading)
  end = next(( idx for idx in range(start + 1, len(lines)) if not fenced[idx] and _ENTRY_END_RE.match(lines[idx]) ),
             len(lines))
  last = next(( idx for idx in range(end - 1, start, -1) if lines[idx].strip() ), start)

  # a line inside a code fence is code, never the entry's verdict
  verdict = last > start and not fenced[last]

  # guard: an entry that already ends with this verdict stays as it is
  if verdict and lines[last].strip() == line:
    return body

  # a verdict of another kind or language is replaced; otherwise the line follows the entry's last text, after the
  # closing fence a fence left open at the end of the body needs
  if verdict and lines[last].strip() in _verdicts():
    lines[last] = line
  else:
    closer = spec_frontmatter.open_fence(lines) if end == len(lines) and fenced[last] else ""
    lines[last + 1:last + 1] = [ closer, line ] if closer else [ line ]
  return "\n".join(lines) + ( "\n" if body.endswith("\n") else "" )


def _verdicts() -> set[str]:
  # every verdict line the plugin writes, in every language it carries
  return { Lockit.text(key, lang) for key in ( _LINE_REJECTED, _LINE_TO_PLAN ) for lang in LangId }


def _strip_discussion(report: Path) -> bool:
  # the removal is the first write; a failure ends the call before the line or the registry is touched
  run = review_halt.run_review_verb(report, _STRIP_ARGS, _STRIP_FAILED)
  if run.failure is not None:
    raise ReportRejectRefusedError(run.failure)

  # the verb answers whether a block came off
  try:
    answer = json.loads(run.stdout)
  except ValueError as error:
    raise ReportRejectRefusedError(f"{_STRIP_FAILED}: unreadable answer {run.stdout!r}") from error

  # guard: an answer without the flag is not one the verb gives
  if not isinstance(answer, dict) or not isinstance(answer.get(_STRIPPED), bool):
    raise ReportRejectRefusedError(f"{_STRIP_FAILED}: unreadable answer {run.stdout!r}")
  return answer[_STRIPPED]


def main(argv: list[str]) -> int:
  """
  Run the `report-reject` verb: close a build that is not accepted and print one JSON line.

  Notes:
    - `report-reject <release-note> --build <k> [--to-plan]` prints `build`, `line` and `discussion_stripped`.
    - A refusal prints `error` with the reason; the repository is the root of the checkout `$LAZY_REPO_ROOT`, else
      the current directory, sits in.
    - Failure modes, in the order the writes come: a path that is no release, an unreadable report, a report without
      the build's entry, a report whose review accepted the build, a report whose consumed review verdict sits where
      removing the key would not take it away, a registry without a record of the build or an unresolvable language
      is refused with nothing written; a failed removal of the discussion block is refused before the line and the
      registry are touched; a failed write of the line leaves the block removed and the registry untouched; a
      registry that cannot be rewritten with the outcome leaves the report written. Every refusal exits 1.
    - Never commits.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    Exit code 0 on success, 1 when the call was refused; an argument error exits with code 2.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs report-reject")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("path")
  # waiver: argparse CLI signature -- option flag + type
  parser.add_argument("--build", type = int, required = True)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--to-plan", action = "store_true")
  args = parser.parse_args(argv)

  # one JSON line per call; a refusal is printed under `error` and carried by the exit code
  try:
    out = reject(spec_locator.query_repo_root(), args.path, args.build, to_plan = args.to_plan)
  except (ReportRejectRefusedError, build_registry.BuildRegistryRefusedError) as refused:
    print(json.dumps({ _ERROR: str(refused) }, ensure_ascii = False))
    return _EXIT_REFUSED
  print(json.dumps(out, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
