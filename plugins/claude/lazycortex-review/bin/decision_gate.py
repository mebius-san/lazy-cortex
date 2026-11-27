from __future__ import annotations

import argparse
import json
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
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import doc_history as _doc_history  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import ParseError  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The verb's program name and argument spellings.
_PROG = "decision-clean"
_ARG_FILE = "file"
_ARG_REPO = "--repo"

# The JSON key of the verb's answer and of its refusal.
_CLEAN_KEY = "clean"
_ERROR_KEY = "error"

# The suffix a reviewable document carries.
_MARKDOWN_SUFFIX = ".md"


# ----------------------------------------------------------------------------------------
def _only_boxes_changed(before: str | None, after: str | None) -> bool:
  """
  Report whether one commit changed nothing in the document's body but the ticks of its ready banner's boxes.

  Args:
    before: The document's text in the commit's parent revision, `None` when there is none.
    after: The document's text in the commit's own revision, `None` when the commit deleted it.

  Returns:
    True when both revisions exist and their frontmatter parses, their bodies are equal outside the banner whatever
    the frontmatter holds, the commit's banner is the ready one, and every banner line that differs is a checkbox
    line with the same label on both sides.
  """
  # guard: a commit that created or deleted the document changed more than a box
  if before is None or after is None:
    return False

  # guard: a revision whose frontmatter does not parse is a broken document, an edit and never a decision
  try:
    before_body, after_body = _fm.parse(before)[1], _fm.parse(after)[1]
  except ParseError:
    return False

  # any change of the body outside the banner is a text edit; the frontmatter is machine state, never text
  if _banner.strip_banner(before_body) != _banner.strip_banner(after_body):
    return False

  # decision boxes live only on the ready banner, so any other banner state is no tick
  if _banner.extract(after_body) is not _banner.State.READY:
    return False

  # a banner line added or removed is not a tick
  old_lines = _banner.extract_block(before_body).split("\n")
  new_lines = _banner.extract_block(after_body).split("\n")
  if len(old_lines) != len(new_lines):
    return False

  # every differing line is a checkbox whose label stayed, so only its tick moved
  return all(
      old == new or ((label := _banner.box_label(old)) is not None and label == _banner.box_label(new))
      for old, new in zip(old_lines, new_lines, strict = True)
  )


def is_decision_clean(repo: Path, file_path: Path, *, bot_emails: set[str], boundary_emails: set[str]) -> bool:
  """
  Report whether a decision box ticked on a review document's ready banner counts.

  Guarantees:
    - Whose commit it is follows its author address alone; the commit message never decides it.
    - Every operator commit since the review's newest own commit is judged, so a text edit is never hidden by a
      later commit that only ticks a box, nor by a commit of another system identity.
    - Only the document's body counts as its text; a frontmatter change is never an edit, while a commit that
      leaves the frontmatter unparseable always is, and never makes the call fail.
    - A commit of another system identity and a bookkeeping commit are passed over, neither judged nor ending the
      span.
    - Uncommitted edits in the working tree are never read.

  Notes:
    - Reads the document's history through git; nothing is written.

  Args:
    repo: Repository root.
    file_path: The review document, inside `repo`.
    bot_emails: Every system identity, whose commits are never the operator's.
    boundary_emails: The identities that answer for the review, whose newest commit ends the operator's span.

  Returns:
    True when no operator commit since the review's newest own commit changed anything in the body but the ready
    banner's box ticks, including when there is no such commit.

  Raises:
    RuntimeError: If the document's revisions cannot be read through git.
  """

  # Contract:
  # A decision box counts only when every operator commit since the review's newest own commit (one under a
  # boundary identity) changed nothing in the body but the ticks of the ready banner's boxes. Several such commits
  # are judged together: a text edit followed by a commit that only ticks a box NEVER counts as clean, and a
  # commit of another system identity in between NEVER ends the span. With no operator commit since the review's
  # newest own commit, the answer is clean.

  # Contract:
  # Only the body is the document's text: a change of the frontmatter beside a tick NEVER makes the answer dirty.
  # An operator commit that leaves the frontmatter unparseable is an edit: the answer is dirty, NEVER a failure.

  # Contract:
  # Whose commit it is follows the author address alone, exactly as the operator-edit wake decides it; a phase
  # trailer in the message NEVER makes a commit the system's. A commit of a system identity outside the boundary
  # set, and a bookkeeping commit (`Lazy-Watch: skip`) under any address, is passed over: it neither ends the span
  # nor makes the answer dirty.

  # Domain(review.lifecycle):
  # # A decision counts only on unchanged text
  # A decision box on the ready banner counts only when, since the review last answered the document, the
  # operator changed nothing in the document's text but the ticks of the banner's boxes. A tick that comes with an
  # edit of the text, in the same change or in an earlier change since the review's turn, does not fire the
  # decision: the edit is answered first. A changed box label or a changed banner line that is not a box is an
  # edit too. The frontmatter is machine state the writer never sees, so a change to it, such as an editor
  # stamping it on save, is never an edit; a change that leaves the frontmatter broken is one. Only the review's
  # own answer ends the span: a change by another part of the system, such as a curator linking terms, answers
  # nothing and is passed over, and so are bookkeeping changes.

  # newest first, every commit up to the review's newest own commit is the operator's span
  rel = str(file_path.resolve().relative_to(repo.resolve()))
  for record in _doc_history.read_revisions(repo, rel):
    # the review's newest own commit closes the span: everything older the review has already answered
    # waiver: `plugins/claude/lazycortex-specs/bin/coordinator_dispatch.py` shares this basename; a whole-project mypy
    # run resolves the bare import to that unrelated module and checks the attribute against the wrong file
    if _coordinator_dispatch.is_bot_email(record.author_email, boundary_emails):  # type: ignore[attr-defined]
      return True

    # guard: another system identity's commit and a bookkeeping commit are nobody's decision
    # waiver: same basename shadowing as the call above
    if (_coordinator_dispatch.is_bot_email(record.author_email, bot_emails)  # type: ignore[attr-defined]
        or _doc_history.is_watch_skip(record)):
      continue

    # one operator commit that changed more than a tick makes the decision dirty
    if not _only_boxes_changed(record.parent_text, record.text):
      return False

  # the span reached the document's first commit without finding a text edit
  return True


def main(argv: list[str]) -> int:
  """
  Run the `decision-clean` review verb for one document.

  Print `{"clean": true | false}` on stdout as one JSON line. A document that is missing or is not markdown is
  refused with a stderr line, as is a file outside the repository; an unreadable settings file or git history is
  reported as a JSON object with an `error` key on stdout.

  Notes:
    - Reads the repository's settings and the document's git history; nothing is written.

  Args:
    argv: The document path relative to the repository root, optionally followed by `--repo <dir>`, a directory
      inside the repository (default: `$LAZY_REPO_ROOT`, then the working directory).

  Returns:
    `0` on an answer, `1` when the settings or git history cannot be read, `2` when the file is not an existing
    markdown file inside the repository.
  """
  # the document path and the repository root are the verb's whole argument list
  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(_ARG_FILE)
  parser.add_argument(_ARG_REPO, default = None)
  args = parser.parse_args(argv)

  # the document is named relative to the repository root
  repo = _review_locator.query_repo_root(args.repo)
  file_path = (repo / args.file).resolve()

  # guard: only an existing markdown file carries a banner to judge
  if not file_path.is_file() or file_path.suffix.lower() != _MARKDOWN_SUFFIX:
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # guard: a file outside the repository has no history in it
  if not file_path.is_relative_to(repo):
    sys.stderr.write(f"not inside the repository {repo}: {file_path}\n")
    return 2

  # the system identities and the history are read together; either failing leaves the answer unknown
  try:
    # waiver: `plugins/claude/lazycortex-specs/bin/coordinator_dispatch.py` shares this basename; a whole-project mypy
    # run resolves the bare import to that unrelated module and checks the attributes against the wrong file
    settings = _coordinator_dispatch.load_settings(  # type: ignore[attr-defined]
        _review_locator.query_settings_root(file_path.parent))
    clean = is_decision_clean(
        repo, file_path,
        # waiver: same basename shadowing as the call above
        bot_emails = _coordinator_dispatch.collect_bot_emails(settings),  # type: ignore[attr-defined]
        # waiver: same basename shadowing as the call above
        boundary_emails = _coordinator_dispatch.collect_boundary_emails(settings),  # type: ignore[attr-defined]
    )
  except RuntimeError as error:
    sys.stdout.write(json.dumps({ _ERROR_KEY: str(error) }) + "\n")
    return 1

  # one JSON answer
  sys.stdout.write(json.dumps({ _CLEAN_KEY: clean }) + "\n")
  return 0
