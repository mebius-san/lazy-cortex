from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
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
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import doc_history as _doc_history  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import edit_markup as _edit_markup  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import note_ops as _note_ops  # noqa: E402
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import parser as _parser  # noqa: E402  # pylint: disable=wrong-import-position,deprecated-module,import-error
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from errors import ParseError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import BotIdentity, PassageKind, ReviewKey  # noqa: E402


# The head line of any review callout (banner, question, command), whatever its marker.
_REVIEW_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!\w+\][^#\n]*#review/[a-z-]+\s*$")

# A callout continuation line: the quote prefix that keeps a line inside the callout block.
_QUOTE_PREFIX = ">"

# An HTML comment — template guidance for the writer, never the document's prose — on one line or across several.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# A line carrying at least one letter or digit; a line without one is markup, never prose.
_PROSE_RE = re.compile(r"\w", re.UNICODE)

# The verb's program name and argument spellings.
_PROG = "operator-text"
_ARG_FILE = "file"
_ARG_REPO = "--repo"

# The frontmatter value that marks a document as under review.
_TRUE = "true"

# The JSON key of the verb's answer and of its refusal.
_PASSAGES_KEY = "passages"
_ERROR_KEY = "error"

# The suffix a reviewable document carries.
_MARKDOWN_SUFFIX = ".md"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class PassageRecord:
  """
  One run of a review document's prose that the operator wrote, or that was written because the operator ordered it.

  Attributes:
    source:
      `edit` when an operator commit wrote the text or a submit — the review bot opening the review — carried it
      in from the operator's draft, `command` when a review commit landed it while an operator command stood open
      in the document.
    commit: Full SHA of the commit the text is attributed to.
    command: The text of the operator command that stood open, for a `command` passage.
    text: The passage's lines, each whitespace-normalised, joined by newlines.
  """

  source: PassageKind
  commit: str
  command: str | None
  text: str


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _OriginRecord:
  """
  The commit a line of prose is attributed to, with the kind of operator act behind it.

  Attributes:
    source: `edit` or `command`, as on `PassageRecord`.
    commit: Full SHA of the commit.
    command: The text of the open command, for a `command` origin.
  """

  source: PassageKind
  commit: str
  command: str | None


# ----------------------------------------------------------------------------------------
def _normalise(line: str) -> str:
  """
  Reduce a line to the form two revisions of the same prose share.

  Args:
    line: One line of document text.

  Returns:
    The line stripped, with every inner whitespace run collapsed to one space.
  """
  return " ".join(line.split())


def _drop_review_callouts(text: str) -> str:
  """
  Remove every review callout block — the banner, questions, the command channel — from document text.

  Args:
    text: Document body text.

  Returns:
    The text without any review callout's head line or its quoted continuation lines.
  """
  kept: list[str] = []
  inside = False
  for line in text.split("\n"):
    # a review callout head opens a block that runs over every following quoted line
    if _REVIEW_CALLOUT_HEAD_RE.match(line):
      inside = True
      continue
    if inside and line.startswith(_QUOTE_PREFIX):
      continue
    inside = False
    kept.append(line)
  return "\n".join(kept)


def _drop_owned_sections(document: _parser.Document) -> str:
  """
  Remove every H1 section an expert or another plugin owns, heading included.

  Args:
    document: The parsed revision, its frontmatter already split off.

  Returns:
    The body holding only the text before the first H1 and the sections no ownership tag claims.
  """
  # the text before the first heading is the document's own; every section is kept only when no tag claims it; the
  # sections come from the one parse that split the frontmatter off, so a body opening with a horizontal rule is
  # never mistaken for a second frontmatter block
  headings = _parser.find_all_h1_headings(document.body)
  kept = [ document.body[: headings[0][0]] if headings else document.body ]
  for section in document.sections:
    if _body.owner_of_section(section.content) is None and _body.protected_section_owner(section.content) is None:
      kept.append(section.heading_line + section.content)
  return "".join(kept)


def _extract_content_lines(text: str, *, fallback_style: str) -> list[str]:
  """
  Return the lines of a revision of a review document that count as the document's own prose.

  Frontmatter, review callouts, HTML comments, owned and protected sections are left out; edit markers are folded
  into final text in the style the revision's own frontmatter pins. A revision whose frontmatter cannot be parsed,
  such as one with an unclosed fence, is read whole as plain prose: its sections are not split and no frontmatter is
  left out.

  Args:
    text: One revision of the document, frontmatter included.
    fallback_style: The repository's edit-marker style, used when the revision pins none or an unsupported style.

  Returns:
    The prose lines in document order, each whitespace-normalised, lines without a letter or digit left out.

  Raises:
    RuntimeError: If the repository's edit-marker style is unsupported and the revision does not pin a supported one.
  """
  # a revision whose frontmatter fence is broken still has prose; it is read whole as plain text, its sections not
  # split, so a later commit that repairs it is credited only with the lines it really added
  try:
    document = _parser.parse(text)
    meta, owned_dropped = document.meta, _drop_owned_sections(document)
  except ParseError:
    meta, owned_dropped = {}, text

  # each revision is folded in the style it pinned itself; one that pins none takes the repository's style
  pinned = meta.get(ReviewKey.MARKER_STYLE)
  style = pinned if isinstance(pinned, str) and pinned in _edit_markup.SUPPORTED_STYLES else fallback_style

  # the owned regions go first, then the review callouts and the HTML comments, then the edit markers fold into
  # final text
  prose = _HTML_COMMENT_RE.sub("", _drop_review_callouts(owned_dropped))

  # an unknown style would leave the markers unfolded and break the attribution across a fold, so it is refused
  try:
    prose = _edit_markup.strip_markers(prose, style = style)
  except ValueError as error:
    raise RuntimeError(f"edit markers cannot be folded: {error}") from error

  # only lines that carry prose take part in the comparison
  return [ norm for line in prose.split("\n") if _PROSE_RE.search(norm := _normalise(line)) ]


def _find_open_command(text: str) -> str | None:
  """
  Return the text of the operator command standing open in one revision of the document.

  Args:
    text: One revision of the document, frontmatter included.

  Returns:
    The body of the open command the coordinator would act on, never one inside a code fence or a foreign protected
    section, or `None` when the revision has none.
  """
  # the coordinator's own reading of an open command: never one inside a code fence or a foreign protected section;
  # a revision read from git keeps its CRLF endings, and the reading takes LF text
  # waiver: `plugins/claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
  # import resolves to that unrelated module, so mypy checks the attribute against the wrong file's shape
  return _note_ops.find_open_command_body(text.replace("\r\n", "\n"))  # type: ignore[attr-defined]


def _is_under_review(text: str) -> bool:
  """
  Report whether a revision's frontmatter marks the document as under review.

  Args:
    text: One revision of the document, frontmatter included.

  Returns:
    True when the frontmatter holds `review_active: true`; False otherwise, including when the frontmatter is
    unreadable.
  """
  # a revision without readable frontmatter is not under review
  try:
    meta, _body_text = _fm.parse(text)
  except ParseError:
    return False
  return str(meta.get(ReviewKey.ACTIVE, "")).strip().lower() == _TRUE


def _classify(
    record: _doc_history.RevisionRecord, parent: str, child: str, *, bot_emails: set[str],
) -> _OriginRecord | None:
  """
  Decide what, if anything, one commit of the document made the operator's.

  A commit under a system address makes `command` text when an operator command stood open in its parent revision.
  Failing that, it makes `edit` text only when it is made under the review bot identity and opens the review — the
  parent is not under review and its own revision is — because that submit carries the operator's draft into
  history. Any other system commit, an opening by any other system address such as a seeded template included,
  makes nothing. A commit under any other address makes nothing when it carries `Lazy-Watch: skip`, and is an
  operator `edit` otherwise.

  Args:
    record: The commit.
    parent: The document's text in the commit's parent revision, empty when there is none.
    child: The document's text in the commit's own revision.
    bot_emails: System addresses, from `collect_bot_emails`.

  Returns:
    The origin the commit's new prose is attributed to, or `None` when the commit made nothing the operator's.
  """
  # a system commit makes the operator's text only by landing it under an open command, or by a submit — the review
  # bot opening the review — which carries the operator's draft into history; any other system opening is a seed
  # waiver: `plugins/claude/lazycortex-specs/bin/coordinator_dispatch.py` shares this basename; a whole-project mypy
  # run resolves the bare import to that unrelated module and checks the attribute against the wrong file
  if _coordinator_dispatch.is_bot_email(record.author_email, bot_emails):  # type: ignore[attr-defined]
    if (command := _find_open_command(parent) if parent else None) is not None:
      return _OriginRecord(source = PassageKind.COMMAND, commit = record.sha, command = command)
    # waiver: same basename shadowing as the call above
    is_submit = _coordinator_dispatch.is_bot_email(  # type: ignore[attr-defined]
        record.author_email, { BotIdentity.EMAIL },
    )
    if is_submit and _is_under_review(child) and not _is_under_review(parent):
      return _OriginRecord(source = PassageKind.EDIT, commit = record.sha, command = None)
    return None

  # a bookkeeping commit makes nothing the operator's, whoever authored it
  if _doc_history.is_watch_skip(record):
    return None

  # every other commit is the operator's own edit
  return _OriginRecord(source = PassageKind.EDIT, commit = record.sha, command = None)


def _read_origins(repo: Path, rel: str, *, fallback_style: str, bot_emails: set[str]) -> dict[str, _OriginRecord]:
  """
  Attribute every prose line the operator's acts made in the document's history to the newest act that made it.

  The history is read across renames of the document, and a pure rename moves no authorship.

  Args:
    repo: Repository root.
    rel: The document's current path relative to `repo`.
    fallback_style: The repository's edit-marker style, used for a revision that pins none or an unsupported style.
    bot_emails: The review system's registered identities.

  Returns:
    Each normalised prose line an operator edit or a command landing made, mapped to its newest origin.

  Raises:
    RuntimeError: If the file's revisions cannot be read, or the repository's edit-marker style is unsupported.
  """
  # every commit of the file across its renames, oldest first, so a newer origin overwrites an older one; each
  # commit is classified, then credited with the prose lines it made
  origins: dict[str, _OriginRecord] = {}
  for record in reversed(_doc_history.read_revisions(repo, rel)):
    parent = record.parent_text or ""
    child = record.text

    # guard: a commit that deleted the file made no line
    if child is None:
      continue

    # a commit that made nothing the operator's is passed over
    if (origin := _classify(record, parent, child, bot_emails = bot_emails)) is None:
      continue

    # the lines this commit made are the ones its revision holds and its parent did not
    before = set(_extract_content_lines(parent, fallback_style = fallback_style))
    for line in _extract_content_lines(child, fallback_style = fallback_style):
      if line not in before:
        origins[line] = origin
  return origins


def read_operator_passages(repo: Path, file_path: Path, *, bot_emails: set[str]) -> list[PassageRecord]:
  """
  Return the passages of a review document's current prose that the operator made.

  Answer which parts of the document's current prose came from the operator, each with the commit it is attributed
  to. The answer covers the document's whole history, renames included.

  Guarantees:
    - Each current line goes to the newest operator act that made an equal line, never to an earlier act that wrote
      the same line; lines no operator act made are not reported.
    - Whose act a commit is follows its author address alone; text a system-address commit made is reported only
      when it lands under an open operator command or is made by a submit opening the review, and is never
      reported otherwise.
    - Text written by a bookkeeping change is never reported.
    - Text an operator act made is still reported after the review's edit markers around it were folded, each
      revision being folded in the edit-marker style its own frontmatter pins. A revision that pins none, or pins
      an unsupported style, is folded in the repository's style, so an old revision can never break the call; only
      an unsupported repository style makes the call fail, with a `RuntimeError`.
    - Text keeps the origin it had before a rename of the document.
    - A past revision whose frontmatter cannot be parsed never makes the call fail; it is read whole as plain
      prose, so a later commit that repairs it is credited only with the lines it really added.
    - A passage never mixes origins: consecutive lines with one origin form one passage.

  Notes:
    - Reads the repository's history through git; nothing is written.

  Args:
    repo: Repository root.
    file_path: The review document, inside `repo`.
    bot_emails: The review system's registered identities, whose commits are never the operator's.

  Returns:
    The operator's passages in document order.

  Raises:
    RuntimeError: If the document's revisions cannot be read through git, or the repository's edit-marker style is
      unsupported.
  """

  # Contract:
  # A passage is reported only for text an operator act made, and whose act it is follows the commit's author
  # address alone. A commit under any other address makes operator text unless it is a bookkeeping change. A
  # commit under a system address makes operator text only when it lands under an operator command that stood
  # open in its parent revision, or when it is a submit: a commit under the review bot identity that opens the
  # review, its parent revision not under review and its own revision under review, carrying the operator's draft
  # into history. A review opened by any other system address, such as a seeded template, makes nothing the
  # operator's. Text from any other system-address commit, and from a bookkeeping change, is NEVER reported as
  # the operator's.

  # Contract:
  # Text keeps the origin it had before the document was renamed; a rename moves no authorship. Text a writer
  # made stays a writer's after a rename, and a rename NEVER turns the document's text into the operator's.

  # Contract:
  # Text an operator act made MUST still be reported after the review's edit markers around it were folded into
  # final text; folding the markers never changes whose text it is. Each revision is folded in the edit-marker
  # style its own frontmatter pins. A revision that pins none, or pins an unsupported style, is folded in the
  # repository's style, so an old revision can never break the call. Only an unsupported repository style makes
  # the call fail, with a RuntimeError.

  # Contract:
  # A past revision whose frontmatter cannot be parsed NEVER makes the call fail. It is read whole as plain prose,
  # so a later commit that repairs it is credited only with the lines it really added.

  # Contract:
  # Each line of the document's current prose is attributed to the newest operator act that made an equal line; a
  # passage names the latest act behind its text, never an earlier act that wrote the same line.

  # Contract:
  # A passage never mixes origins: consecutive lines of the current prose with one origin form one passage, and a
  # line with a different origin, or with none, ends it.

  # Domain(review.operator-text):
  # # Operator's own text
  # Text of a document under review counts as the operator's when the operator wrote it, when a writer wrote it
  # because the operator had ordered it, or when it is the draft the operator handed over to open the review. A
  # reviewer's finding against such text goes to the operator, not back to a writer.
  #
  # Text counts as the operator's in three cases. (a) A change by the operator wrote it, unless that change is
  # explicitly marked as bookkeeping. (b) A system change wrote it while an operator instruction to the review loop
  # stood open in the document. (c) A submit opened the review: the review bot itself opened it with the operator's
  # draft, so the document was not under review before it and is after it, and the draft enters history as the
  # operator's.
  #
  # Only a submit made by the review bot itself carries the draft over. When a system expert running a job submits
  # a draft, the change is authored by that expert and the draft stays the system's text: it is never credited to
  # the operator. A system change that opens the review with a seeded template makes nothing the operator's, and
  # neither does any other system change.
  #
  # Only the document's own prose is compared. The review machinery's banner and callouts, sections that other
  # writers or plugins own, the history section, the frontmatter and text inside HTML comments, which is writer
  # guidance in templates, are left out. The review's edit markers are folded into final text first, so folding
  # them at an approval does not erase whose text it is.
  #
  # Each earlier version is folded in the edit-marker style it pinned itself, and in the repository's style where it
  # pins none or an unknown one. A version whose frontmatter cannot be read is compared as plain prose.
  #
  # A line of current prose belongs to the most recent such act that introduced an equal line; prose that no such
  # act introduced is not the operator's. The record spans the document's whole history, so text from an earlier
  # approved review cycle keeps its standing. The loop keeps no separate record: it is recovered from the
  # document's own change history each time it is asked.
  #
  # History is followed across renames: each earlier version is read under the name the document had then. Renaming
  # a document therefore moves no authorship, and its text keeps the origin it had before.

  # Decision: whose commit it is follows the author address, not the commit message's phase trailer — the operator
  # decided that a message never decides authorship, so this verb agrees with the operator-edit wake

  # the operator's acts are read from the document's whole history; a revision pinning no edit-marker style is
  # folded in the repository's
  fallback_style = _finalize.read_settings_edit_marker_style(file_path)
  rel = str(file_path.resolve().relative_to(repo.resolve()))
  origins = _read_origins(repo, rel, fallback_style = fallback_style, bot_emails = bot_emails)

  # every current prose line is looked up among the operator's acts, and consecutive lines with one origin form one
  # passage; a line none of them made is skipped, and the trailing empty sentinel line flushes the last run
  passages: list[PassageRecord] = []
  run: list[str] = []
  run_origin: _OriginRecord | None = None
  current = _extract_content_lines(file_path.read_text(encoding = "utf-8"), fallback_style = fallback_style)
  for line in [ *current, "" ]:
    origin = origins.get(line)
    if origin == run_origin and origin is not None:
      run.append(line)
      continue
    if run_origin is not None:
      passages.append(PassageRecord(**asdict(run_origin), text = "\n".join(run)))
    run, run_origin = [ line ], origin
  return passages


def main(argv: list[str]) -> int:
  """
  Run the `operator-text` review verb for one document.

  Print the operator's passages of the document as a JSON object with a `passages` list on stdout. A document that
  is missing or is not markdown is refused with a stderr line; an unreadable settings file or git history, or an
  unsupported repository edit-marker style, is reported as a JSON object with an `error` key on stdout. A revision
  whose frontmatter cannot be parsed is not an error: it is read whole as prose.

  Notes:
    - Reads the repository's settings, including the review section's former bot addresses, and its git history;
      nothing is written.

  Args:
    argv: The document path relative to the repository root, optionally followed by `--repo <dir>`, a directory
      inside the repository (default: `$LAZY_REPO_ROOT`, then the working directory).

  Returns:
    `0` on success, `1` when the settings or git history cannot be read or the repository's edit-marker
    style is unsupported, `2` when the file is not an existing markdown file.
  """
  # the document path and the repository root are the verb's whole argument list
  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(_ARG_FILE)
  parser.add_argument(_ARG_REPO, default = None)
  args = parser.parse_args(argv)

  # the document is named relative to the repository root
  repo = _review_locator.query_repo_root(args.repo)
  file_path = (repo / args.file).resolve()

  # guard: only an existing markdown file has prose to attribute
  if not file_path.is_file() or file_path.suffix.lower() != _MARKDOWN_SUFFIX:
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # the system identities and the history are read together; either failing leaves the answer unknown
  try:
    # waiver: `plugins/claude/lazycortex-specs/bin/coordinator_dispatch.py` shares this basename; a whole-project mypy
    # run resolves the bare import to that unrelated module and checks the attributes against the wrong file
    bot_emails = _coordinator_dispatch.collect_bot_emails(  # type: ignore[attr-defined]
        _coordinator_dispatch.load_settings(  # type: ignore[attr-defined]
            _review_locator.query_settings_root(file_path.parent)),
    )
    passages = read_operator_passages(repo, file_path, bot_emails = bot_emails)
  except (RuntimeError, ParseError) as error:
    sys.stdout.write(json.dumps({ _ERROR_KEY: str(error) }) + "\n")
    return 1

  # one JSON answer, the passages in document order
  sys.stdout.write(
      json.dumps({ _PASSAGES_KEY: [ asdict(passage) for passage in passages ] }, ensure_ascii = False) + "\n",
  )
  return 0
