from __future__ import annotations

import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final

  from collections.abc import Callable, Set as AbstractSet


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import axes as _axes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import markers as _markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import term_dictionary as _term_dictionary  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import term_link_syntax as _term_link_syntax  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import terms as _terms  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Result `status` values and result keys of one document pass.
STATUS_APPLIED: Final = "applied"
STATUS_NOOP: Final = "noop"
STATUS_REFUSED: Final = "refused"
KEY_STATUS: Final = "status"
KEY_FILE: Final = "file"
KEY_REASON: Final = "reason"
KEY_LINKED: Final = "linked"
KEY_RETARGETED: Final = "retargeted"
KEY_SKIP_UNMATCHED: Final = "skip_unmatched"
KEY_SKIP_UNMATCHED_FRAGMENTS: Final = "skip_unmatched_fragments"
KEY_TEXT: Final = "text"
KEY_UNSETTLED: Final = "unsettled"

# Keys of one dangling-link record.
KEY_TARGET: Final = "target"
KEY_RENAMED_TO: Final = "renamed_to"

# Operation keys of the terms protocol's result format that act on documents.
_OP = "op"
_OP_RELINK = "relink"
_OP_RETARGET = "retarget"
_OP_REJECT = "reject"
_OP_TERM = "term"
_OP_FROM = "from"
_OP_TARGET = "target"
_OP_FILES = "files"
_OP_SKIP = "skip"

# Refusal reasons, one per document a pass may not edit.
_REASON_MISSING = "document does not exist"
_REASON_MIRROR = "document lies under a scope's mirror tree"
_REASON_MANAGED = "document lies inside a terms dictionary or the generated domain tree"
_REASON_LINK_EXCLUDED = "document is excluded from link editing by its terms scope"
_REASON_FOLDER_NOTE = "document is a folder note"
_REASON_REVIEW = "document carries `review_active: true` and belongs to its open review round"

# A markdown link whole; an inline code span.
_MD_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)")
_CODE_SPAN_RE = re.compile(r"(`+).+?\1")
# A bare URL, whose path and query are an address and never prose.
# limit: a word glued to a URL without whitespace stays unlinked, end the address at closing punctuation if it bites
_URL_RE = re.compile(r"https?://\S+")

# Comment delimiters of HTML.
_COMMENT_OPEN = "<!--"
_COMMENT_CLOSE = "-->"

# Lines carried byte-for-byte: a heading of any level, a callout title, a checkbox item, each also inside a callout.
_HEADING_RE = re.compile(r"^(?:\s*>)*\s{0,3}#{1,6}(?:\s|$)")
_CALLOUT_TITLE_RE = re.compile(r"^(?:\s*>)+\s*\[![^\]]*\]")
_CHECKBOX_RE = re.compile(r"^(?:\s*>)*\s*(?:[-*+]|\d+[.)])\s+\[[ xX]\]")

# An H1 line, and the tag that marks the H1 section it opens as owned by a plugin.
_H1_RE = re.compile(r"^# ")
_PROTECTED_TAG = "#protected/"

# The mark opening a heading anchor in a link's target.
_ANCHOR_MARK = "#"

# A markdown table row, where a link's pipe must be escaped.
_TABLE_ROW_RE = re.compile(r"^\s*\|")

# The old `## Terms` section, the heading that ends it, and its term lines: after an optional list marker (`-`, `*`,
# `+`, or a number with `.` or `)`), a bold word before a dash, or a plain word before a dash with spaces around
# it; a word followed by a colon names no term line
_LEGACY_HEADING_RE = re.compile(r"^##\s+Terms\s*$", re.IGNORECASE)
_SECTION_END_RE = re.compile(r"^#{1,2}\s")
_LEGACY_MARKER = r"^(?:(?:[-*+]|\d+[.)])\s+)?"
_LEGACY_BOLD_LINE_RE = re.compile(_LEGACY_MARKER + r"\*\*(?P<word>.+?)\*\*\s*[\u2014\u2013-]\s*.*$")
_LEGACY_PLAIN_LINE_RE = re.compile(_LEGACY_MARKER + r"(?P<word>[^\s*|:\[\]][^*|:\[\]]*?)\s+[\u2014\u2013-]\s.*$")
_GROUP_WORD = "word"

# A pipe that no backslash escapes.
_RAW_PIPE_RE = re.compile(r"(?<!\\)\|")
# The line break that joins a body's lines.
_NL = "\n"

_ENCODING = "utf-8"


# ----------------------------------------------------------------------------------------
class _Git:
  """
  Vocabulary of the read-only git invocations the rename-hint lookup is made of.
  """

  # The git executable, with paths printed unquoted so non-ASCII names come back as written
  EXE           = ( "git", "-c", "core.quotePath=false" )
  # Subcommands reading history and one commit
  LOG           = "log"
  SHOW          = "show"
  # Flags narrowing the log to the last commit that deleted a path, printed as its identifier only
  DELETED       = "--diff-filter=D"
  LAST          = "-1"
  HASH_ONLY     = "--format=%H"
  # Flags listing a merge commit's own changes: against each parent while searching history, and against the first
  # parent, the branch it was made on, when one commit's changes are read
  MERGES        = "-m"
  FIRST_PARENT  = "--first-parent"
  # Flags printing a commit's changed paths with their status, NUL-separated, no rename pairing and no header
  NO_RENAMES    = "--no-renames"
  NAME_STATUS   = "--name-status"
  # Flag printing changed paths relative to the directory git runs in, a nested project's root included
  RELATIVE      = "--relative"
  NUL_FIELDS    = "-z"
  NUL           = "\0"
  NO_HEADER     = "--format="
  # Flag printing a diff without context lines
  NO_CONTEXT    = "-U0"
  # Separator ending the options, the whole tree, and the prefix excluding a directory from it
  PATHS         = "--"
  TREE          = "."
  EXCLUDE       = ":(exclude)"
  # Pathspec magic that makes git read a path as written, never as a glob pattern
  LITERAL       = ":(literal)"
  # Status letters of an added and a changed path
  ADDED         = "A"
  MODIFIED      = "M"
  # Line openings of a diff: a hunk, a file header, a removed and an added line
  HUNK          = "@@"
  FILE_HEADER   = "diff "
  REMOVED       = "-"
  ADDED_LINE    = "+"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class LinkPlan:
  """
  Link edits one set of documents receives after a batch of term operations.

  Attributes:
    dictionary_dir: Repo-relative dictionary directory the links point into.
    terms: Term by stem, as the dictionary holds them after the batch.
    link_retargets: Per document, the stem an existing link's target as written now points at.
    retargets: The new stem of every renamed or joined term, by old stem.
    word_links: Per document, the stem every named word links to, by the word as it stands in the text.
    rejected: Stems whose links are removed.
    legacy_paths: Repo-relative paths, without file extension, of old single-file dictionaries whose heading links
      are moved onto the term files.
    drop_legacy: Whether an old terms section is removed whole, whatever its lines name.
    word_skips: Per document, the fragments whose places keep a named word plain, by the word as it stands in the
      text.
  """

  # The repo-relative dictionary directory the links point into
  dictionary_dir: str
  # The term by stem, as the dictionary holds them after the batch
  terms: dict[str, str]
  # Per document, the stem an existing link's target as written now points at
  link_retargets: dict[str, dict[str, str]]
  # The new stem of every renamed or joined term, by old stem
  retargets: dict[str, str]
  # Per document, the stem every named word links to, by the word as it stands in the text
  word_links: dict[str, dict[str, str]]
  # The stems whose links are removed
  rejected: set[str]
  # The paths, without file extension, of old single-file dictionaries whose heading links now point at term files
  legacy_paths: tuple[str, ...] = ()
  # Whether an old terms section goes whole, whatever its lines name
  drop_legacy: bool = False
  # Per document, the fragments whose places keep a named word plain, by the word as it stands in the text
  word_skips: dict[str, dict[str, tuple[str, ...]]] = field(default_factory = dict)


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class SyncContext:
  """
  Settings-derived facts every document pass of one verb run consults.

  Attributes:
    mirror_paths: Mirror directories of every wiki scope.
    managed_dirs: Dictionary directories and the generated domain tree.
    link_exclude: Globs of the documents the terms scope serves but whose text is never edited.
  """

  # The mirror directories of every wiki scope
  mirror_paths: list[str]
  # The dictionary directories and the generated domain tree
  managed_dirs: list[str]
  # The globs of the documents the terms scope serves but whose text is never edited
  link_exclude: list[str]


# ----------------------------------------------------------------------------------------
def build_link_plans(dictionary: _term_dictionary.TermDictionary,
                     change: _term_dictionary.DictionaryChange,
                     operations: list[dict],
                     sources: list[str],
                     *,
                     dictionary_dir: str) -> tuple[LinkPlan, LinkPlan]:
  """
  Build the link edits of the job's documents and of every other document of the scope.

  A `relink` operation's `skip` fragments reach the plan of the job's documents as the places that keep its word
  plain. A document an operation names is matched to a job source by its plain repo-relative form and planned under
  the source's own spelling.

  Args:
    dictionary: The dictionary before the batch is written; the plans take its terms as they will stand once
      `change` is written.
    change: The change the batch made to the dictionary.
    operations: The batch of term operations.
    sources: The job's source documents.
    dictionary_dir: Repo-relative dictionary directory.

  Returns:
    The plan of the job's source documents and the plan of every other scope document.
  """
  terms = dictionary.compute_terms_after(change)
  stems = { stem.casefold(): stem for stem in terms }
  allowed = { posixpath.normpath(rel): rel for rel in sources }
  word_links: dict[str, dict[str, str]] = {}
  word_skips: dict[str, dict[str, tuple[str, ...]]] = {}
  link_retargets: dict[str, dict[str, str]] = {}
  rejected: set[str] = set()

  # each document operation contributes to the plan of the job's own documents only
  for operation in operations:
    kind = operation.get(_OP)
    named = _term_dictionary.term_file_stem(str(operation.get(_OP_TERM, "")))
    stem = stems.get(named.casefold())

    # a rejected word's links are removed wherever the job's documents carry them
    if kind == _OP_REJECT:
      rejected.add(named)
      continue

    # guard: only a link or retarget operation on a present term edits documents
    if kind not in ( _OP_RELINK, _OP_RETARGET ) or stem is None:
      continue
    table, key = ( word_links, _OP_FROM ) if kind == _OP_RELINK else ( link_retargets, _OP_TARGET )
    for name in operation.get(_OP_FILES) or []:
      # guard: a document whose plain repo-relative form is no source of the job is never edited by a job operation
      if ( rel := allowed.get(posixpath.normpath(name)) ) is None:
        continue
      table.setdefault(rel, {})[str(operation.get(key, ""))] = stem
      if kind == _OP_RELINK:
        word_skips.setdefault(rel, {})[str(operation.get(_OP_FROM, ""))] = tuple(operation.get(_OP_SKIP) or ())

  # the job's documents take every edit; the rest of the scope follows renamed and joined terms only
  return (
    LinkPlan(
      dictionary_dir = dictionary_dir, terms = terms, link_retargets = link_retargets,
      retargets = dict(change.retargets), word_links = word_links, rejected = rejected, word_skips = word_skips,
    ),
    LinkPlan(
      dictionary_dir = dictionary_dir, terms = terms, link_retargets = {},
      retargets = dict(change.retargets), word_links = {}, rejected = set(),
    ),
  )


def build_sync_context(repo: Path, scope: _term_dictionary.TermsScope) -> SyncContext:
  """
  Read the settings every document pass of one verb run consults.

  Args:
    repo: Repository root.
    scope: The terms scope serving the documents.

  Returns:
    The mirror directories, managed directories and link exclusions.
  """
  return SyncContext(
    mirror_paths = _terms.read_all_mirror_paths(repo), managed_dirs = _axes.read_managed_dirs(repo),
    link_exclude = list(scope.link_exclude),
  )


def render_document(repo: Path,
                    path: str,
                    plan: LinkPlan,
                    context: SyncContext,
                    *,
                    allow_review: bool = False,
                    data: bytes | None = None) -> dict:
  """
  Compute one document's text with its term links and its old terms section in line with a link plan.

  Guarantees:
    - Never writes, creates or removes any file; the new text of an applied document travels only in the result.
    - Rendering the text an earlier call returned, with the same plan, reports `noop`.
    - A document under a mirror path, inside a managed directory, matching the scope's link exclusions, or a folder
      note is refused and yields no text, whatever `allow_review` says.
    - A document with `review_active: true` in its frontmatter is refused and yields no text unless `allow_review`
      is true.
    - Frontmatter, fenced blocks, foreign `#protected/...` H1 sections, heading lines, callout titles, checkbox
      lines, HTML comments, inline code and markdown links are carried through byte-for-byte into the returned text.
    - A wikilink outside the dictionary is carried through byte-for-byte, unless it points at a heading of an old
      dictionary file that the plan names and the dictionary holds that heading's term. Such a link is moved onto
      that term's file, keeping its text, or taking the heading as its text when it has none. A plan that names no
      old dictionary file moves no link.

  Args:
    repo: Repository root.
    path: Repo-relative path of the document.
    plan: The link edits the document receives.
    context: Settings-derived facts of the verb run.
    allow_review: Whether a document under an open review round may be edited.
    data: The document's bytes as the caller read them, rendered as given; read from disk when absent.

  Returns:
    `{status, file, linked, retargeted, skip_unmatched, skip_unmatched_fragments, unsettled}` on `applied` / `noop`,
    with the document's new text under `text` on `applied` only, or `{status, file, reason}` on `refused`.
    `skip_unmatched` lists the named words kept off the document because a fragment of theirs matched no place
    holding an occurrence to link; `skip_unmatched_fragments` holds, by each such named word, those fragments in the
    order sent; `unsettled` holds the term lines of the old terms section left standing, as written, in document
    order.

  Raises:
    UnicodeDecodeError: If the document is not valid UTF-8.
  """

  # Contract:
  # The call NEVER writes, creates or removes any file; the new text of an applied document
  # travels only in the result.

  # Contract:
  # Rendering the text an earlier call returned, with the same plan, reports `noop`.

  # Contract:
  # A document under a mirror path, inside a managed directory, matching the scope's link exclusions,
  # or a folder note is refused and yields no text, whatever `allow_review` says.

  # Contract:
  # A document with `review_active: true` in its frontmatter is refused and yields no text
  # unless `allow_review` is true.

  # Contract:
  # Frontmatter, fenced blocks, foreign `#protected/...` H1 sections, heading lines, callout titles,
  # checkbox lines, HTML comments, inline code and markdown links
  # are carried through byte-for-byte into the returned text.

  # Contract:
  # A wikilink outside the dictionary is carried through byte-for-byte, unless it points at a heading of an old
  # dictionary file that the plan names and the dictionary holds that heading's term. Such a link is moved onto
  # that term's file, keeping its text, or taking the heading as its text when it has none. A plan that names no
  # old dictionary file moves no link.

  # guard: the reasons that bar every pass come first; a document the pass may not edit is refused before it is read
  if (refusal := find_refusal_reason(repo, path, context)) is not None:
    return { KEY_STATUS: STATUS_REFUSED, KEY_FILE: path, KEY_REASON: refusal }

  # the frontmatter is split off before anything reads it — it is both the review flag's home and a region no
  # edit may reach
  file = TextFile(path = repo / path)
  head, body = _terms.split_frontmatter(file.read() if data is None else file.decode(data))

  # guard: the review loop owns the document until its round closes, unless the caller lifts that
  if not allow_review and _terms.REVIEW_ACTIVE_RE.search(head):
    return { KEY_STATUS: STATUS_REFUSED, KEY_FILE: path, KEY_REASON: _REASON_REVIEW }

  # the edits themselves; the new text travels only when they changed something
  editor = _DocumentEditor(plan = plan, path = path)
  edited = editor.edit(body)
  result: dict = {
    KEY_STATUS: STATUS_NOOP if edited == body else STATUS_APPLIED, KEY_FILE: path,
    KEY_LINKED: sorted(editor.linked), KEY_RETARGETED: sorted(editor.retargeted),
    KEY_SKIP_UNMATCHED: sorted(editor.skip_unmatched),
    KEY_SKIP_UNMATCHED_FRAGMENTS: dict(editor.skip_unmatched),
    KEY_UNSETTLED: list(editor.unsettled),
  }
  if result[KEY_STATUS] == STATUS_APPLIED:
    result[KEY_TEXT] = head + edited
  return result


def write_document(repo: Path, path: str, text: str) -> None:
  """
  Write a document's new text, keeping its line endings and byte-order mark.

  Args:
    repo: Repository root.
    path: Repo-relative path of the document.
    text: The new text, with LF line endings.
  """
  file = TextFile(path = repo / path)

  # an existing file is read first so the write restores its line endings and byte-order mark
  if (repo / path).is_file():
    file.read()
  file.write(text)


def find_all_legacy_terms(text: str) -> list[str]:
  """
  Return the words of the term lines still standing in a document's old terms section.

  Args:
    text: Full document text.

  Returns:
    The words, in document order; empty when the document has no such section.
  """
  _, body = _terms.split_frontmatter(text)
  return [
    word for line in _map_body(body) if line.legacy
    for word in [ _find_legacy_word(line) ] if word is not None
  ]


def has_legacy_section(text: str) -> bool:
  """
  Tell whether a document still carries an old terms section.

  Args:
    text: Full document text.

  Returns:
    `True` when a link edit sees the heading of an old terms section in the body.
  """
  _, body = _terms.split_frontmatter(text)
  return any(line.legacy_heading for line in _map_body(body))


def has_legacy_anchor_links(text: str, plan: LinkPlan) -> bool:
  """
  Tell whether a document still carries a link to a heading of an old dictionary file that a pass would move.

  Guarantees:
    - The answer is true exactly when the link edit of a document with this text, under the same plan, would move at
      least one link onto a term file, so a predicate built on it never disagrees with the pass. A link inside a
      frozen line, a comment or code never counts.

  Args:
    text: Full document text.
    plan: The link edits the document would receive.

  Returns:
    `True` when at least one link would be moved onto a term file.
  """

  # Contract:
  # The answer is true exactly when the link edit of a document with this text, under the same plan, would move at
  # least one link onto a term file, so a predicate built on it never disagrees with the pass. A link inside a
  # frozen line, a comment or code never counts.

  _, body = _terms.split_frontmatter(text)
  editor = _DocumentEditor(plan = plan, path = "")

  # a link the edit would move to a term file, where the edit reaches: outside frozen lines, comments and code
  for line in _map_body(body):
    for match in _term_link_syntax.WIKILINK_RE.finditer(line.text):
      # guard: a link the edit does not reach is never edited
      if not line.can_reach(match.start()):
        continue
      if editor.find_legacy_target(match.group(1)) is not None:
        return True
  return False


def find_all_unmoved_anchor_links(text: str, plan: LinkPlan) -> list[str]:
  """
  List the links to headings of an old dictionary file that no link edit can move onto a term file.

  A link counts when the plan names its old file and the dictionary holds the heading's term, yet it stands where a
  link edit leaves alone: a frozen line (heading, callout title, checkbox line, foreign protected section) or an HTML
  comment. Text in a fenced block or an inline code span is a literal sample, not a link, and is never listed.

  Guarantees:
    - Only links on a frozen line or inside an HTML comment, whose old file the plan names and whose heading's term
      the dictionary holds, are listed; a link in a fenced block or an inline code span never is, because text there
      is a literal sample, not a link.

  Args:
    text: Full document text.
    plan: The link edits the document would receive.

  Returns:
    The links as written, `[[…]]` included, in document order.
  """

  # Contract:
  # Only links on a frozen line (heading, callout title, checkbox line, foreign protected section) or inside an HTML
  # comment, whose old file the plan names and whose heading's term the dictionary holds, are listed. A link in a
  # fenced block or an inline code span is NEVER listed: text there is a literal sample, not a link.

  _, body = _terms.split_frontmatter(text)
  editor = _DocumentEditor(plan = plan, path = "")

  # a link the edit would move to a term file, standing on prose the edit leaves alone: a frozen line or a comment;
  # text in a fenced block or an inline code span is a literal sample, never a link
  return [
    match.group(0)
    for line in _map_body(body) if not line.code
    for match in _term_link_syntax.WIKILINK_RE.finditer(line.text)
    if not line.can_reach(match.start()) and not _is_in_code(line.text, match.start())
    and editor.find_legacy_target(match.group(1)) is not None
  ]


def find_all_dangling(repo: Path, dictionary_dir: str, documents: list[str]) -> list[dict]:
  """
  List the links of documents that point at a term file the dictionary does not hold.

  Only links a link edit reaches are listed. A link on a frozen line, such as a heading, a callout title, a checkbox
  line or a line of a foreign protected section, or inside a fence, an HTML comment or an inline code span, is never
  reported.

  Args:
    repo: Repository root.
    dictionary_dir: Repo-relative dictionary directory.
    documents: Repo-relative documents to read.

  Returns:
    One `{file, target, renamed_to}` record per document and dangling link target; `renamed_to` is the stem the
    term's file now carries, or `None` when its history names none.
  """

  # Domain(wiki.terms):
  # # Which dangling links the curator is shown
  # A link into the dictionary whose term file does not exist is shown to the curator only where a link edit could
  # reach it, that is, in the same running prose the edit works on. A dangling link inside a region the edit never
  # touches, such as a foreign protected section, a heading line, a callout title, a checkbox line, a fenced block,
  # inline code or an HTML comment, is left out. The curator could never close it: the edit cannot change that link,
  # so the operation would come back unmatched and the same record would return on every later job.
  # A document and a missing target make one record however often the document links to it, and the record carries
  # the hint of where a renamed term went, when one is known.

  present = {
    stem.casefold() for stem in _term_dictionary.TermDictionary(path = repo / dictionary_dir).read_terms()
  }
  hints = _RenameHints(repo = repo, dictionary_dir = dictionary_dir)
  found: list[dict] = []
  seen: set[tuple[str, str]] = set()

  # every link into the dictionary whose file is absent and that a link edit reaches is one record, once per
  # document and target
  for rel in documents:
    file = repo / rel
    # guard: a document that is gone carries no link
    if not file.is_file():
      continue
    _, body = _terms.split_frontmatter(TextFile(path = file).read())
    for line in _map_body(body):
      for match in _term_link_syntax.WIKILINK_RE.finditer(line.text):
        link = _Link.parse(match.group(1), dictionary_dir)
        # guard: a link outside the dictionary, or one where no link edit reaches, is never the curator's to close
        if link is None or not line.can_reach(match.start()):
          continue
        stem = link.stem(present)
        # guard: a link whose file exists, or a target already reported for this document, adds nothing
        if stem.casefold() in present or (rel, link.path) in seen:
          continue
        seen.add((rel, link.path))
        found.append({ KEY_FILE: rel, KEY_TARGET: link.path, KEY_RENAMED_TO: hints.query_renamed_to(stem) })
  return found


def find_refusal_reason(repo: Path, path: str, context: SyncContext) -> str | None:
  """
  Name why a document may not be edited, if it may not.

  Args:
    repo: Repository root.
    path: Repo-relative path of the document.
    context: Settings-derived facts of the verb run.

  Returns:
    The refusal reason, or `None` when nothing but the review flag still has to be checked.
  """

  # Domain(wiki.terms):
  # # Documents a link edit refuses
  # A link edit refuses a document that is missing, one under a mirror, and one inside a dictionary directory or the
  # generated domain tree, since those are written by their own owners. It refuses a document its scope excludes
  # from link editing; an operator's request is such a document and stays verbatim. It refuses a folder note, which
  # stands for its folder. It also refuses a document under an open review round, unless the caller lifts that,
  # because the review loop owns the text until the round closes.

  matcher = _scope.GlobMatcher()
  pure = PurePosixPath(path)

  # each document kind the pass leaves alone, in a fixed order
  reasons = (
    ( not (repo / path).is_file(), _REASON_MISSING ),
    ( _terms.is_under_mirror(path, context.mirror_paths), _REASON_MIRROR ),
    ( any(path.startswith(f"{base}/") for base in context.managed_dirs if base), _REASON_MANAGED ),
    ( any(matcher.match(path, glob) for glob in context.link_exclude), _REASON_LINK_EXCLUDED ),
    ( pure.stem == pure.parent.name, _REASON_FOLDER_NOTE ),
  )
  return next(( reason for refused, reason in reasons if refused ), None)


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _Line:
  """
  One body line with what the link edits may and may not touch in it.

  Attributes:
    start: Offset of the line in the body.
    text: The line without its line break.
    frozen: Whether the whole line is carried byte-for-byte.
    code: Whether the line is a fence or lies inside a fenced block.
    legacy: Whether the line belongs to an old terms section, its heading excluded.
    legacy_heading: Whether the line is the heading of an old terms section.
    table: Whether the line is a table row.
    comment_only: Whether the line holds nothing but HTML comment text.
    spans: Line-relative ranges no edit may reach: comments, code spans, markdown links and wikilinks.
    comments: Line-relative ranges of HTML comment text.
  """

  # The offset of the line in the body
  start: int
  # The line without its line break
  text: str
  # Whether the whole line is carried byte-for-byte
  frozen: bool
  # Whether the line is a fence or lies inside a fenced block
  code: bool
  # Whether the line belongs to an old terms section, its heading excluded
  legacy: bool
  # Whether the line is the heading of an old terms section
  legacy_heading: bool
  # Whether the line is a table row
  table: bool
  # Whether the line holds nothing but HTML comment text
  comment_only: bool
  # The line-relative ranges no edit may reach
  spans: tuple[tuple[int, int], ...]
  # The line-relative ranges of HTML comment text
  comments: tuple[tuple[int, int], ...]

  def can_reach(self, position: int) -> bool:
    """
    Tell whether a link edit reaches a line-relative position.

    Args:
      position: Line-relative offset.

    Returns:
      `True` when the line is not frozen and the position lies in neither an HTML comment nor an inline code span.
    """
    return not self.frozen and not _is_inside(position, self.comments) and not _is_in_code(self.text, position)


def _map_body(body: str) -> list[_Line]:
  """
  Map every body line to the regions the link edits may not touch.

  Args:
    body: Document body, frontmatter removed.

  Returns:
    One entry per line, in order.
  """

  # Domain(wiki.terms):
  # # Regions of a document that a link edit never touches
  # A link edit reaches only running prose. It leaves alone the frontmatter, fenced blocks, and any top-level section
  # owned by a plugin tag. Heading lines and callout titles stay as written because their text is the anchor that
  # heading links point at. Checkbox lines stay as written because a changed ticked line would read as a fresh
  # gesture of the operator. HTML comments, inline code, markdown links and other wikilinks are left alone too, and
  # so is a bare web address, which runs from its `http://` or `https://` up to the next whitespace and is carried
  # through untouched.
  # Where a link lands in a table row, the separator between target and text is escaped, and so is every pipe the
  # text already carried in escaped form, so the link never splits a cell and the row keeps its cells.

  lines = body.split(_NL)
  fence = _markers.CodeFence()
  in_comment = False
  protected = False
  legacy = False
  offset = 0
  out: list[_Line] = []

  # walk the lines, tracking fences, comments and the sections that open and close on headings
  for index, text in enumerate(lines):
    start = offset
    offset += len(text) + 1

    # a fence line and everything inside a fence is code, never prose
    if fence.step(text) or fence.inside:
      out.append(_Line(
        start = start, text = text, frozen = True, code = True, legacy = False, legacy_heading = False,
        table = False, comment_only = False, spans = (), comments = (),
      ))
      continue

    # comment ranges of the line, and whether the line opened inside a comment
    opened_in_comment = in_comment
    comments, in_comment = _find_all_comment_spans(text, in_comment)

    # an H1 opens a new section, protected when its first content line is an owner's tag; a level-two heading
    # opens or closes the old terms section
    if not opened_in_comment and _H1_RE.match(text):
      protected = _is_protected_section(lines, index)
    is_legacy_heading = not opened_in_comment and not protected and bool(_LEGACY_HEADING_RE.match(text))
    if is_legacy_heading:
      legacy = True
    elif not opened_in_comment and _SECTION_END_RE.match(text):
      legacy = False

    # a whole line is frozen when a protected section, a heading, a callout title or a checkbox holds it
    frozen = protected or any(regex.match(text) for regex in ( _HEADING_RE, _CALLOUT_TITLE_RE, _CHECKBOX_RE ))
    out.append(_Line(
      start = start, text = text, frozen = frozen, code = False, legacy = legacy and not is_legacy_heading,
      legacy_heading = is_legacy_heading, table = bool(_TABLE_ROW_RE.match(text)),
      comment_only = _is_comment_only(text, comments),
      spans = ( *comments, *_find_all_inline_spans(text, comments) ), comments = comments,
    ))
  return out


def _is_protected_section(lines: list[str], index: int) -> bool:
  """
  Tell whether the H1 section opened at a line is owned by a plugin.

  Args:
    lines: Body lines.
    index: Index of the H1 line.

  Returns:
    `True` when the first non-empty line after the heading is an owner's tag.
  """
  return next(( line for line in lines[index + 1:] if line.strip() ), "").strip().startswith(_PROTECTED_TAG)


def _find_all_comment_spans(text: str, in_comment: bool) -> tuple[tuple[tuple[int, int], ...], bool]:
  """
  Find the HTML comment ranges of one line.

  Args:
    text: The line.
    in_comment: Whether the line starts inside a comment opened earlier.

  Returns:
    The line-relative comment ranges, and whether a comment is still open at the line's end.
  """
  spans: list[tuple[int, int]] = []
  position = 0

  # alternate between looking for a comment's close and the next comment's open
  while position <= len(text):
    if in_comment:
      close = text.find(_COMMENT_CLOSE, position)
      # the comment runs on past this line
      if close < 0:
        spans.append((position, len(text)))
        return tuple(spans), True
      spans.append((position, close + len(_COMMENT_CLOSE)))
      position = close + len(_COMMENT_CLOSE)
      in_comment = False
      continue
    opening = text.find(_COMMENT_OPEN, position)
    # no further comment opens on this line
    if opening < 0:
      break
    position = opening
    in_comment = True

  # the line ends outside any comment
  return tuple(spans), False


def _find_all_inline_spans(text: str, comments: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
  """
  Find the code spans, markdown links and wikilinks of one line that lie outside its comments.

  Args:
    text: The line.
    comments: The line's comment ranges.

  Returns:
    Their line-relative ranges.
  """
  return [
    match.span()
    for regex in ( _CODE_SPAN_RE, _MD_LINK_RE, _term_link_syntax.WIKILINK_RE, _URL_RE )
    for match in regex.finditer(text)
    if not _is_inside(match.start(), comments)
  ]


def _is_inside(position: int, spans: tuple[tuple[int, int], ...] | list[tuple[int, int]]) -> bool:
  """
  Tell whether a position falls inside any range.

  Args:
    position: Line-relative offset.
    spans: Ranges to test against.

  Returns:
    `True` when a range holds the position.
  """
  return any(start <= position < end for start, end in spans)


def _is_comment_only(text: str, comments: tuple[tuple[int, int], ...]) -> bool:
  """
  Tell whether a non-blank line holds nothing but comment text.

  Args:
    text: The line.
    comments: The line's comment ranges.

  Returns:
    `True` when every non-blank character lies inside a comment.
  """
  marks = [ index for index, char in enumerate(text) if not char.isspace() ]
  return bool(marks) and all(_is_inside(index, comments) for index in marks)


# ----------------------------------------------------------------------------------------
class _Link(_term_link_syntax.TermLink):
  """
  One wikilink into a dictionary directory, with the stem its target names.

  Attributes:
    prefix: The dictionary directory and its slash, as written.
    rest: The part of the target after the prefix, anchor excluded.
    anchor: The heading anchor of the target, with its `#`, or empty.
    separator: The pipe before the link text, plain or escaped, or empty when the link has no text.
    text: The link text, or `None` when the link has none.
  """

  def stem(self, known: AbstractSet[str] = frozenset()) -> str:
    """
    Return the stem the link's target names once normalised.

    Args:
      known: The casefolded stems of the term files the dictionary holds.

    Returns:
      The target's stem. For a target ending in `.md` in any letter case, the stem without that ending wins whenever
      a term file carries it; the whole target's stem wins only when a term file carries that and none carries the
      stem without the ending; a target naming neither is read without the ending.
    """
    # the target after the dictionary directory, read the one way every written target is read
    return _term_dictionary.parse_target_stem(self.rest, known)


def _find_all_links(body: str, dictionary_dir: str) -> list[_Link]:
  """
  Collect the links into the dictionary directory that a body's prose and markup carry.

  Args:
    body: Document body.
    dictionary_dir: Repo-relative dictionary directory.

  Returns:
    The links outside code and comments, in document order.
  """
  found: list[_Link] = []
  for line in _map_body(body):
    # guard: code carries no link
    if line.code:
      continue
    for match in _term_link_syntax.WIKILINK_RE.finditer(line.text):
      link = _Link.parse(match.group(1), dictionary_dir)
      if (link is not None and not _is_inside(match.start(), line.comments)
          and not _is_in_code(line.text, match.start())):
        found.append(link)
  return found


def _is_in_code(text: str, position: int) -> bool:
  """
  Tell whether a position of a line lies inside an inline code span.

  Args:
    text: The line.
    position: Line-relative offset.

  Returns:
    `True` when a code span holds the position.
  """
  return any(match.start() <= position < match.end() for match in _CODE_SPAN_RE.finditer(text))


def _find_legacy_word(line: _Line) -> str | None:
  """
  Return the word a line of the old terms section names when the line is a term line.

  A leading list marker is never part of the word, and a line holding nothing but an HTML comment is no term line.

  Args:
    line: The line of the old terms section.

  Returns:
    The word, bold marks and list marker removed; `None` when the line is no term line.
  """
  # guard: a line holding nothing but an HTML comment is an author's note, never a term line
  if line.comment_only:
    return None

  # one reading for both shapes of a term line; the plain shape admits no `*` in its word, so the two never match
  # the same line and their order is free
  match = _LEGACY_BOLD_LINE_RE.match(line.text) or _LEGACY_PLAIN_LINE_RE.match(line.text)
  return None if match is None else match.group(_GROUP_WORD)


# ----------------------------------------------------------------------------------------
class _DocumentEditor:
  """
  Editor that applies one link plan to one document body.

  Attributes:
    linked: The named words of which at least one occurrence was linked.
    retargeted: The link targets, as the plan names them, that were moved onto another term.
    skip_unmatched: For each named word kept off the whole document because a fragment of theirs matched no place
      holding an occurrence to link, the fragments that matched no such place, in the order sent.
    unsettled: The term lines of the old terms section left standing, as written, in document order.
  """

  def __init__(self, *, plan: LinkPlan, path: str) -> None:
    """
    Bind the editor to the plan and the document it edits.

    Args:
      plan: The link edits.
      path: Repo-relative path of the document.
    """
    # the plan and the document's own share of it
    self._plan = plan
    self._words = plan.word_links.get(path, {})
    self._skips = plan.word_skips.get(path, {})
    self._targets = plan.link_retargets.get(path, {})

    # name lookups that ignore letter case
    self._retargets = { old.casefold(): new for old, new in plan.retargets.items() }
    self._rejected = { stem.casefold() for stem in plan.rejected }
    self._known = { stem.casefold() for stem in plan.terms }

    # Domain(wiki.terms):
    # # Terms renamed away still count while a batch is applied
    # While a batch is applied, the terms it renames or joins away from still count as existing when a link is
    # read. A rename therefore finds the links that named its term before the batch, even when the term's name ends
    # in `.md` and another term carries that name without the ending.

    # a link is read against the terms as they stood before the batch too, so a rename finds the links of its term
    self._link_known = self._known | { old.casefold() for old in plan.retargets }

    # a rejected name ending in the term-file suffix also stands for the name without it, as a link target does
    self._rejected_links = self._rejected | {
      _term_dictionary.term_file_stem(stem[:-len(_term_dictionary.TERM_FILE_SUFFIX)]).casefold()
      for stem in self._rejected if stem.endswith(_term_dictionary.TERM_FILE_SUFFIX)
    }

    # the named words without letter case, against which a line of the old terms section is settled
    self._words_cf = { word.strip().casefold() for word in self._words }

    # the dictionary's stems as written, by their casefolded form, for links into an old dictionary file
    self._stems = { stem.casefold(): stem for stem in plan.terms }
    self._legacy = { path.casefold() for path in plan.legacy_paths }

    # whether the line being edited is a table row, where a link's separator is escaped
    self._table = False

    # what the edit reached, for the caller's report
    self.linked: set[str] = set()
    self.retargeted: set[str] = set()
    self.skip_unmatched: dict[str, list[str]] = {}
    self.unsettled: list[str] = []

  def edit(self, body: str) -> str:
    """
    Apply the plan to a body.

    What the pass reached is reported afterwards through the editor's public attributes.

    Args:
      body: Document body, frontmatter removed.

    Returns:
      The edited body.
    """
    # the places kept plain are found on the body as the pass received it, before any edit of the batch; a word whose
    # exclusion cannot be honoured there is recorded as kept off the document
    kept, kept_off = self._find_all_kept_places(body)
    self.skip_unmatched.update(kept_off)

    # links first, then the named words, then the old terms section, which learns what the words reached; every
    # edit carries the places kept plain along with the text it moves
    edited, replacements = self._edit_links(body, self._edit_link)
    kept = { word: _shift_places(places, replacements, body = body) for word, places in kept.items() }
    for word in sorted(self._words, key = len, reverse = True):
      # guard: a word whose exclusion cannot be honoured is kept off the whole document
      if word in self.skip_unmatched:
        continue
      linked, replacements = self._link_word(edited, word, self._words[word], kept.get(word, []))
      kept = { other: _shift_places(places, replacements, body = edited) for other, places in kept.items() }
      edited = linked
    return self._clean_legacy(edited)

  def _find_all_kept_places(self, body: str) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[str]]]:
    """
    Find, on a body no edit has touched yet, the places each named word is kept plain in.

    Fragments are located on the body as received, while whether a fragment's place holds an occurrence to link is
    judged on the body with the batch's rejected links unwrapped.

    Args:
      body: Document body, frontmatter removed, as the pass received it.

    Returns:
      Places in the received body by named word, for the words whose every fragment holds an occurrence to link; and
      by named word, the fragments that have no place holding an occurrence to link.
    """
    mapped = _map_body(body)
    kept: dict[str, list[tuple[int, int]]] = {}
    kept_off: dict[str, list[str]] = {}

    # the body with the batch's rejected links unwrapped, where the text an unwrap frees is prose like any other
    freed, unwraps = self._edit_links(body, self._unwrap_rejected)
    freed_mapped = _map_body(freed)
    freed_blocked = _find_all_blocked_ranges(freed_mapped)

    # each named word's fragments are located in the received body, and judged on the freed one
    for word, fragments in self._skips.items():
      pattern = _term_link_syntax.compile_word_pattern(word)
      # guard: a word not named here, or a blank one, has no place to keep
      if word not in self._words or pattern is None:
        continue
      uses = _find_all_uses(pattern, freed, freed_mapped, freed_blocked)
      places = [ _find_all_places(mapped, fragment) for fragment in fragments ]
      freed_places = [ _shift_places(group, unwraps, body = body) for group in places ]

      # guard: a fragment holding no use cannot be honoured, so the word is kept off the whole document
      if unhonoured := [
        fragment for fragment, group in zip(fragments, freed_places, strict = True)
        if not any(_is_within(match.span(), group) for match, _ in uses)
      ]:
        kept_off[word] = unhonoured
        continue

      # every place any fragment matches keeps the word plain
      kept[word] = [ place for group in places for place in group ]
    return kept, kept_off

  def find_legacy_target(self, inner: str) -> tuple[str, str, str, str | None] | None:
    """
    Resolve a wikilink to a heading of an old dictionary file to the term file that heading became.

    Args:
      inner: Text between the link's brackets.

    Returns:
      The term file's stem, the heading as written, the link's separator and its text; `None` when the link is not
      to a heading of an old dictionary file the plan names, or the dictionary holds no term for that heading.
    """
    # guard: no old dictionary file is known
    if not self._legacy:
      return None

    # the link's target without the term-file suffix, its heading, separator and text
    path, anchor, separator, text = _term_link_syntax.TermLink.split(inner)
    if path.casefold().endswith(_term_dictionary.TERM_FILE_SUFFIX):
      path = path[:-len(_term_dictionary.TERM_FILE_SUFFIX)]

    # guard: only a link to a heading of an old dictionary file is moved
    if not anchor or path.casefold() not in self._legacy:
      return None

    # the heading names the term file the cut made of it; a heading the dictionary does not hold stays
    heading = anchor[len(_ANCHOR_MARK):]
    stem = self._stems.get(_term_dictionary.term_file_stem(heading).casefold())
    return None if stem is None else ( stem, heading, separator, text )

  def _edit_links(self,
                  body: str,
                  edit: Callable[[re.Match[str]], str]) -> tuple[str, list[tuple[int, int, str]]]:
    """
    Edit the existing wikilinks of a body wherever a link edit reaches them.

    A link on a frozen line, or inside an HTML comment or an inline code span, stays as written.

    Args:
      body: Document body.
      edit: The edit applied to each wikilink match the pass may reach; it returns the text standing in its place.

    Returns:
      The body with its links edited, and each replaced range of the given body with the text that took its place,
      in body order.
    """
    replacements: list[tuple[int, int, str]] = []

    # every link of every line, edited where the edit reaches it; an unchanged link is no replacement
    for line in _map_body(body):
      self._table = line.table
      for match in _term_link_syntax.WIKILINK_RE.finditer(line.text):
        if ( edited := self._edit_reached(line, match, edit) ) != match.group(0):
          replacements.append(( line.start + match.start(), line.start + match.end(), edited ))
    return _compute_replaced_body(body, replacements), replacements

  @staticmethod
  def _edit_reached(line: _Line, match: re.Match[str], edit: Callable[[re.Match[str]], str]) -> str:
    """
    Edit one wikilink match of a line through the given edit, or keep it as written.

    Args:
      line: The line holding the link.
      match: The wikilink's match on that line.
      edit: The edit applied to the match when the pass may reach it.

    Returns:
      The edited link, or the link as written where the pass does not reach it.
    """
    # guard: a link on a frozen line, in a comment or in a code span stays as it is
    if not line.can_reach(match.start()):
      return match.group(0)
    return edit(match)

  def _edit_legacy(self, match: re.Match[str]) -> str:
    """
    Move a link to a heading of an old dictionary file onto the term file that heading became.

    Args:
      match: The wikilink's match.

    Returns:
      The link pointing at the term file, its text kept or the heading taken as its text; the link as written when
      it is not to such a heading.
    """

    # Domain(wiki.terms):
    # # A link to a heading of the old dictionary file
    # When the dictionary moves from one old file to a directory of term files, a link in a document that points at a
    # heading of the old file is moved onto the term file the cut made of that heading. The old file is named by its
    # path, with or without its extension, followed by the heading. The link keeps its text; a link without text gets
    # the heading as its text, so what the reader sees stays the same. A heading the dictionary does not hold, whether
    # an unknown anchor or a heading that named no file, leaves the link as it is, and so does a link to the old file
    # without a heading. The old file's path is recognised also after the migration, because the dictionary directory
    # carries that path without its extension. This moves a link already standing and places no new one, so it
    # follows the same untouched regions as every other link edit: frozen lines such as headings, callout titles and
    # checkboxes, code, and comments.

    # guard: not a link to a heading the dictionary holds
    if (found := self.find_legacy_target(match.group(1))) is None:
      return match.group(0)

    # the link now targets the term file; a link without text keeps showing the heading as its text
    stem, heading, separator, text = found
    if not separator:
      separator = _term_link_syntax.ESCAPED_PIPE if self._table else _term_link_syntax.PIPE
    return (
      f"[[{self._plan.dictionary_dir}{_term_link_syntax.SLASH}{_render_link_target(stem)}{separator}"
      f"{heading if text is None else text}]]"
    )

  def _edit_link(self, match: re.Match[str]) -> str:
    """
    Edit one existing wikilink.

    A link into the dictionary that a rejected name claims gives way to the words it showed; any other link is moved
    through renames and retargets and normalised, and a link without text keeps the words it showed as its text
    whenever it is rewritten.

    Args:
      match: The wikilink's match.

    Returns:
      The words the link showed when a rejected name claims it; otherwise the link as it now stands, as written when
      its target is already in normal form. A link outside the dictionary comes back moved onto a term file when it
      pointed at a heading of an old dictionary file, and as written otherwise.
    """
    link = _Link.parse(match.group(1), self._plan.dictionary_dir)

    # a link outside the dictionary is someone else's, unless it points at a heading of an old dictionary file
    if link is None:
      return self._edit_legacy(match)

    # a link a rejected name claims gives way to its text, never moved onto another target
    if self._is_rejected(link):
      return link.unwrapped()

    # the target as written, normalised, then followed through renames and the job's own retargets
    original = link.stem(self._link_known)
    stem = self._retargets.get(original.casefold(), original)
    for target, new in self._targets.items():
      if self._parse_target(target).casefold() == original.casefold():
        stem = new
        self.retargeted.add(target)

    # a target already written as the stem's link keeps the link's bytes
    if ( target_written := _render_link_target(stem) ) == link.rest:
      return match.group(0)

    # Domain(wiki.terms):
    # # Words a rewritten link keeps showing
    # Any rewrite of a link without display text keeps, as its display text, exactly the words a reader saw before:
    # a normalisation that keeps the same term (`[[dir/notes.md]]` becomes `[[dir/notes.md.md|notes.md]]`,
    # `[[dir/a:b]]` becomes `[[dir/a-b|a:b]]`), a rename, a join or a retarget. Those words are the last segment of
    # the target, followed by its heading anchor for a link to a heading; in a table row the separator is escaped.
    # A link whose target does not change keeps its bytes, and a link that already has display text never gains or
    # loses any. A term link is read as the words it shows when the wiki decides whether a document's authored text
    # changed, so a rewrite that changed the shown words would make the document look edited.

    # any rewrite of a link without text keeps showing the words the reader saw
    if link.text is None:
      link = replace(
        link, separator = _term_link_syntax.ESCAPED_PIPE if self._table else _term_link_syntax.PIPE,
        text = link.unwrapped(),
      )
    return link.render(target_written)

  def _unwrap_rejected(self, match: re.Match[str]) -> str:
    """
    Replace a wikilink a rejected name claims by the words it showed.

    Args:
      match: The wikilink's match.

    Returns:
      The words the link showed when a rejected name claims it; otherwise the link as written.
    """
    link = _Link.parse(match.group(1), self._plan.dictionary_dir)

    # only a link into the dictionary that a rejected name claims gives way to its text
    return link.unwrapped() if link is not None and self._is_rejected(link) else match.group(0)

  def _is_rejected(self, link: _Link) -> bool:
    """
    Tell whether a rejected name of the batch claims a link.

    A link naming a term the batch knows is never claimed, and neither is a link that one of the document's retargets
    names: the retarget moves it.

    Args:
      link: A link into the dictionary.

    Returns:
      `True` when a rejected name claims the link.
    """

    # Domain(wiki.terms):
    # # Which links a rejected word removes
    # A link is first read against the terms that exist; only when it names none of them is it read again with the
    # rejected names counted as existing, and it gives way to its words when that reading names a rejected name. A
    # rejected name ending in `.md` also stands for the name without that ending, as a link target written that way
    # does, so a rejection reaches a dangling link in either written form: `notes.md.md` or `notes.md` for the name
    # `notes.md`, and `notes.md` also for the name `notes`. A link that names an existing term is never removed by a
    # rejection, because an existing term always wins. A link that one of the document's retargets names is never
    # claimed by a rejected name either: the retarget moves it, and a rejection never takes it first. Only a link no
    # retarget names, and that a rejection claims, is removed, never moved onto another target.

    original = link.stem(self._link_known).casefold()

    # a link naming a term the batch knows is never claimed: a term that exists wins over a rejected name, and a link
    # one of the document's retargets names is that retarget's to move; any other link is read again with the
    # rejected names counted as existing
    return (
      original not in self._link_known
      and not any(self._parse_target(target).casefold() == original for target in self._targets)
      and link.stem(self._link_known | self._rejected_links).casefold() in self._rejected_links
    )

  def _parse_target(self, target: str) -> str:
    """
    Return the stem a retarget's link target names.

    Args:
      target: The link target as a retarget of the document names it.

    Returns:
      The stem, read the way the links of the document are read.
    """
    parsed = _Link.parse(target, self._plan.dictionary_dir)

    # a target into the dictionary is read as a link; any other target gives its file name as it stands
    return parsed.stem(self._link_known) if parsed is not None else _term_dictionary.term_file_stem(target)

  def _clean_legacy(self, body: str) -> str:
    """
    Remove the settled lines of the old terms section, or the whole section when the plan drops it.

    Notes:
      - Sets `unsettled` to the term lines left standing, empty when the plan drops the section.

    Args:
      body: Document body.

    Returns:
      The body with those lines removed, and with a section left empty, or one the plan drops, removed whole.
    """

    # Domain(wiki.terms):
    # # The old terms section
    # Documents written before the dictionary directory carry a `## Terms` section of their own. A line of that
    # section is classified by its shape alone. A term line reads `word — definition`: after an optional list marker
    # (a hyphen, an asterisk, a plus, or a number followed by a full stop or a closing parenthesis, then whitespace;
    # the marker is never part of the word) the word is bold or plain, and a dash (em dash, en dash or hyphen) joins
    # it to its definition, with whitespace on both sides when the word is plain. The section holds term lines by
    # definition, so any line of that shape counts, a line of prose with a spaced dash included. A line with a colon
    # before its definition, a table row and a line holding nothing but an HTML comment are not term lines: they
    # are neither removed nor reported. A term line is removed once the dictionary holds its word, once the word was rejected, once the batch
    # renames a term away from that word or joins it into another, or once the curator names that word for a link in
    # the document, whether or not any occurrence got a link: the dictionary now answers for it. A section left
    # empty goes with its heading and its comment, and one blank line stays between its neighbours, also when the
    # section follows the frontmatter. A section that keeps some lines closes the gaps the removed lines leave: no
    # blank line is doubled, and none stays at the section's end beyond the one that separates it from what follows,
    # the document ending in one line break. A term line that none of these settles stays untouched, and the pass
    # reports it back to the curator as unsettled: the curator decides it.
    # A pass may take the section whole, whatever its lines say: a document that no curator reads as a term source
    # loses its old terms section, heading, comment and every line under it up to the next heading of level one or
    # two. It goes whatever terms its lines name, known to the dictionary or not, and also when the section holds
    # prose or a table instead of term lines. One blank line stays between its neighbours.

    lines = body.split(_NL)
    mapped = _map_body(body)

    # the term lines no settlement reaches stay, and the caller learns of each; a section the plan drops keeps none
    self.unsettled = [
      line.text for line in mapped
      if not self._plan.drop_legacy and line.legacy and _find_legacy_word(line) is not None
      and not self._is_settled(line)
    ]

    # sections are cleaned from the last one up, so earlier indices stay valid
    for heading in reversed([ index for index, line in enumerate(mapped) if line.legacy_heading ]):
      end = heading + 1
      while end < len(mapped) and mapped[end].legacy:
        end += 1

      # a plan that drops old sections takes each one whole, with its heading
      if self._plan.drop_legacy:
        lines = _drop_section(lines, heading, end)
        continue

      # otherwise only the settled lines go
      kept = [ index for index in range(heading + 1, end) if not self._is_settled(mapped[index]) ]

      # guard: a section none of whose lines is settled stays as it is
      if len(kept) == end - heading - 1:
        continue

      # a section keeping a line with text is tidied in place; one keeping none goes with its heading
      if any(lines[index].strip() and not mapped[index].comment_only for index in kept):
        lines[heading + 1:end] = _tidy_section([ lines[index] for index in kept ])
        continue
      lines = _drop_section(lines, heading, end)
    return _NL.join(lines)

  def _is_settled(self, line: _Line) -> bool:
    """
    Tell whether a line of the old terms section names a word the dictionary or the job settles.

    Args:
      line: The line of the old terms section.

    Returns:
      `True` for a term line whose word the dictionary holds, whose word the job rejected, whose term a batch rename
      or join took away, or whose word the job names for a link in the document, whether or not an occurrence was
      linked. `False` for any other line, including one that is no term line.
    """
    # guard: only a term line can be settled
    if (word := _find_legacy_word(line)) is None:
      return False

    # the word settles when the dictionary holds it, the job rejected it, a batch's rename took a term away from it,
    # or the job names it for a link, whether or not an occurrence was linked
    stem = _term_dictionary.term_file_stem(word.strip()).casefold()
    return (
      stem in self._known or stem in self._rejected or stem in self._retargets
      or word.strip().casefold() in self._words_cf
    )

  def _link_word(self,
                 body: str,
                 word: str,
                 stem: str,
                 kept: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int, str]]]:
    """
    Link the unlinked occurrences of one named word, except those standing in places kept plain.

    Notes:
      - Records the word as linked when an occurrence was linked.

    Args:
      body: Document body.
      word: The word as it stands in the text.
      stem: The stem it links to.
      kept: Body-relative places where the word stays plain.

    Returns:
      The body with the occurrences linked, and each replaced range of the given body with the link that took its
      place, in body order.
    """

    # Domain(wiki.terms):
    # # What counts as a use of a term
    # A word is never linked because it happens to match the dictionary. Only a word the curator named for a
    # document, in the form it stands there, is linked in that document.
    # Every occurrence of a named word that is not linked yet becomes a link. Letter case is ignored, and the word
    # must stand whole: no letter, digit, underscore or slash beside it, and no dot leading into or out of a longer
    # word. A hyphen beside the word joins it into a compound, and a part of a compound is not a use of the term.
    # The joiners are the hyphen in any of its forms, the soft hyphen included: the hyphen-minus, the hyphen U+2010,
    # the non-breaking hyphen U+2011, the soft hyphen U+00AD, the small hyphen-minus U+FE63 and the fullwidth
    # hyphen-minus U+FF0D, on either side of the word. A dash is not a join: an en dash, an em dash or a minus sign
    # directly beside the word leaves it a use of the term, and so does a dash with spaces around it. A term whose
    # own name carries a hyphen is matched whole. A dot that ends a sentence is a boundary, so a word at the end of
    # a sentence is found.
    # The curator may also name places of the document where the word is meant otherwise: fragments of the text,
    # each on one line and holding the word. An occurrence of the word that lies inside a place where a fragment
    # matches stays plain, and every other occurrence is linked as before. A fragment is matched exactly, letter
    # case included, within one line, against the document as it stood before the batch, link markup included. The
    # other edits of the same batch, such as a link renamed or retargeted on the line or a longer or other named
    # word linked on the line first, never break a fragment copied from the file, and an occurrence protected at
    # the start stays plain however the line changes around it. A fragment found in several places keeps the word
    # plain in each of them. An exclusion that cannot be honoured is never guessed at: when a fragment has no place
    # holding an occurrence that would otherwise be linked, judged on the document after the batch's rejected term
    # links have been unwrapped into their words (it is misspelled, it is gone, or it stands only where no link is
    # placed, such as a heading or a code span), the word is kept off the whole document. Nothing of that word is
    # linked there, and the curator gets the word back as unmatched.
    # The words a rejected link leaves behind are ordinary prose: an occurrence of the named word in them is a use
    # like any other, linked when no fragment protects it and kept plain when a fragment's place holds it. So a
    # fragment copied with the rejected link still standing in it finds its place there.
    # A fragment that ends inside a rejected link keeps plain only the part of the freed text it holds: its place ends
    # where its last character lands once the link is unwrapped into its words, and the words beyond that point are
    # ordinary prose, linked like any other occurrence. Retargets of the same document are no reason for a rejected
    # name to take their links, so a link a retarget moves is not unwrapped before the fragments are judged.
    # Keeping a word off a document keeps only that word unlinked there; the batch's other operations still edit
    # the document. An empty list of fragments is no exclusion.
    # Linking never reflows lines. A named word is a use only where it stands on one line: between its words any run
    # of spaces or tabs counts, and the link text keeps the words exactly as they stand. An occurrence broken across
    # a line break is not linked, so linking never changes the document's line structure. A word the curator named
    # that stands in the document only across a line break is reported as found nowhere, like a word standing only
    # where edits may not reach. The reason is that a link is read as its own words when the wiki decides whether a
    # document's authored text changed: a link that joined two lines would change the text's lines and make every
    # hard-wrapped document look edited after each curator pass.
    # Longer named words are linked first, so a short word never takes a piece out of a longer one, and
    # text that already sits inside a link is never searched again.
    # A pipe in a word reads differently by place. In a table row a raw pipe is a cell boundary, so an occurrence
    # whose text holds one spans two cells and is not a use of the word. The same word written with an escaped pipe
    # stays in one cell: it is linked, and its escape is kept. Outside a table an escaped pipe is not the word's
    # pipe, so an occurrence written with one is not a use of the word.

    # guard: a blank word names nothing
    if (pattern := _term_link_syntax.compile_word_pattern(word)) is None:
      return body, []

    # each use outside every place kept plain becomes a link, its text exactly as it stands
    mapped = _map_body(body)
    replacements = [
      (
        *match.span(),
        f"[[{self._plan.dictionary_dir}{_term_link_syntax.SLASH}{_render_link_target(stem)}"
        f"{_term_link_syntax.ESCAPED_PIPE if line.table else _term_link_syntax.PIPE}{match.group(0)}]]",
      )
      for match, line in _find_all_uses(pattern, body, mapped, _find_all_blocked_ranges(mapped))
      if not _is_within(match.span(), kept)
    ]

    # the word counts as linked once one of its uses became a link
    if replacements:
      self.linked.add(word)
    return _compute_replaced_body(body, replacements), replacements


def _find_all_blocked_ranges(mapped: list[_Line]) -> list[tuple[int, int]]:
  """
  Collect the body ranges no word may be linked in.

  Args:
    mapped: The body's lines.

  Returns:
    Body-relative ranges: frozen lines, old terms sections and every protected span.
  """
  ranges: list[tuple[int, int]] = []
  for line in mapped:
    if line.frozen or line.legacy or line.legacy_heading:
      ranges.append((line.start, line.start + len(line.text)))
      continue
    ranges.extend((line.start + low, line.start + high) for low, high in line.spans)
  return ranges


def _find_all_places(mapped: list[_Line], fragment: str) -> list[tuple[int, int]]:
  """
  Find every place of a body where a fragment stands within one line.

  Args:
    mapped: The body's lines.
    fragment: The text to find, matched exactly against each line's source text.

  Returns:
    Body-relative ranges, one per place, overlapping places included.
  """
  places: list[tuple[int, int]] = []

  # each line on its own, since a fragment never spans a line break
  for line in mapped:
    # the search restarts one character past each place found, so overlapping places are found too
    position = line.text.find(fragment)
    while position >= 0:
      places.append(( line.start + position, line.start + position + len(fragment) ))
      position = line.text.find(fragment, position + 1)
  return places


def _find_all_uses(pattern: re.Pattern[str],
                   body: str,
                   mapped: list[_Line],
                   blocked: list[tuple[int, int]]) -> list[tuple[re.Match[str], _Line]]:
  """
  Find the occurrences of a named word that a link may replace.

  Args:
    pattern: The word's pattern.
    body: Document body.
    mapped: The body's lines.
    blocked: Body-relative ranges no word may be linked in.

  Returns:
    Each occurrence clear of every blocked range and of a pipe that is not the word's, with its line, in body order.
  """
  uses: list[tuple[re.Match[str], _Line]] = []

  # each occurrence clear of every blocked range, and of a pipe that is not the word's, is a use of the word
  for match in pattern.finditer(body):
    start, end = match.span()
    # guard: an occurrence touching a region the edit may not reach stays as it is
    if any(start < high and low < end for low, high in blocked):
      continue
    line = next(line for line in reversed(mapped) if line.start <= start)
    # guard: in a table row a raw pipe is a cell boundary, and elsewhere an escaped one is not the word
    if _RAW_PIPE_RE.search(match.group(0)) if line.table else _term_link_syntax.ESCAPED_PIPE in match.group(0):
      continue
    uses.append(( match, line ))
  return uses


def _compute_replaced_body(body: str, replacements: list[tuple[int, int, str]]) -> str:
  """
  Replace ranges of a body by new text.

  Args:
    body: Document body.
    replacements: Ranges of the body, in body order and not overlapping, each with the text that takes its place.

  Returns:
    The body with every range replaced.
  """
  pieces: list[str] = []
  last = 0

  # the text before each range, then its replacement
  for start, end, text in replacements:
    pieces.append(body[last:start])
    pieces.append(text)
    last = end

  # the text after the last range
  pieces.append(body[last:])
  return "".join(pieces)


def _shift_places(places: list[tuple[int, int]],
                  replacements: list[tuple[int, int, str]],
                  *,
                  body: str) -> list[tuple[int, int]]:
  """
  Carry body-relative places through the replacements an edit made.

  Args:
    places: Places in the body before the edit.
    replacements: Ranges of that body, in body order, each with the text that took its place.
    body: The body before the edit.

  Returns:
    The same places in the edited body; a place a replacement cuts into grows to hold the whole new text, except
    that a place ending inside a range whose new text stands within it ends just past the last character it held
    there.
  """
  return [
    (
      _shift(low, replacements, body = body, is_end = False),
      _shift(high, replacements, body = body, is_end = True),
    )
    for low, high in places
  ]


def _shift(position: int, replacements: list[tuple[int, int, str]], *, body: str, is_end: bool) -> int:
  """
  Carry one body offset through the replacements an edit made.

  Args:
    position: Offset in the body before the edit.
    replacements: Ranges of that body, in body order, each with the text that took its place.
    body: The body before the edit, where the new text of a replaced range is looked for within that range.
    is_end: Whether the offset ends a place, so that inside a replaced range it moves past the new text, or past
      only the part of it the place held when the new text stands within the range.

  Returns:
    The offset in the edited body.
  """
  offset = 0

  # every replaced range wholly before the offset moves it by the change in length
  for start, end, text in replacements:
    # the ranges from here on lie after the offset, so the walk ends
    if position <= start:
      break
    # an offset inside a replaced range lands at the new text's start; an end lands past the new text, or, when the
    # new text stands within the range as an unwrapped link's words do, just past the last character it held there
    if position < end:
      if not is_end:
        return start + offset
      if ( kept := body.rfind(text, start, end) ) < 0:
        return start + offset + len(text)
      return start + offset + min(max(position - kept, 0), len(text))
    offset += len(text) - ( end - start )
  return position + offset


def _render_link_target(stem: str) -> str:
  """
  Render the target part, after the dictionary directory, of a link to a term.

  Args:
    stem: The term's file name stem.

  Returns:
    The stem itself, or the stem with the term-file suffix spelled out when the stem already ends in that suffix.
  """

  # Domain(wiki.terms):
  # # How a link to a term is written
  # The writer agrees with the reader of links. Every link the edits write, whether a new link, a link moved by a
  # rename, a join or a retarget, a link to a heading of the old dictionary file moved onto a term file, or an
  # existing link brought to its normal form, names a term whose own file name ends in `.md` with that extension
  # spelled out (`[[dir/notes.md.md]]` for the term titled `notes.md`), so it never reads as the term `notes`.
  # A link to any other term is written as before, and a correct link with the extension spelled out is never
  # shortened.

  # a stem ending in the suffix names its file in full, so the link never reads as the stem without that ending
  return (
    stem + _term_dictionary.TERM_FILE_SUFFIX if stem.casefold().endswith(_term_dictionary.TERM_FILE_SUFFIX) else stem
  )


def _is_within(span: tuple[int, int], places: list[tuple[int, int]]) -> bool:
  """
  Tell whether a range lies wholly inside any of several places.

  Args:
    span: Body-relative range.
    places: Body-relative ranges to test against.

  Returns:
    `True` when a place holds the whole range.
  """
  return any(low <= span[0] and span[1] <= high for low, high in places)


def _drop_section(lines: list[str], heading: int, end: int) -> list[str]:
  """
  Remove a whole section and leave exactly one blank line between its neighbours.

  The blank line also stays after a frontmatter block or leading blank lines; only a section that opens the body
  leaves no blank line before the next content.

  Args:
    lines: Body lines.
    heading: Index of the section's heading.
    end: Index of the first line after the section.

  Returns:
    The lines without the section.
  """
  before = lines[:heading]
  after = lines[end:]

  # blank lines on both sides of the cut collapse into one
  while before and not before[-1].strip():
    before.pop()
  while after and not after[0].strip():
    after.pop(0)

  # a section at the end of the body leaves the body ending in one line break
  if not after:
    return [ *before, "" ]

  # one blank line stays between the neighbours, also after a frontmatter block; only a section opening the body
  # leaves none
  return [ *before, "", *after ] if before or heading else after


def _tidy_section(kept: list[str]) -> list[str]:
  """
  Close the gaps that removed lines leave in a section that keeps some content.

  Args:
    kept: The section's remaining lines below its heading.

  Returns:
    The lines with no doubled blank line and no trailing blank line, followed by the one blank line that separates
    the section from what comes next, or that ends the body.
  """
  tidy: list[str] = []
  previous = "#"

  # a blank line directly after another blank line is a gap a removed line left
  for line in kept:
    if line.strip() or previous.strip():
      tidy.append(line)
    previous = line

  # trailing blank lines go; one empty entry then separates the next section, or ends the body with its line break
  while tidy and not tidy[-1].strip():
    tidy.pop()
  return [ *tidy, "" ]


# ----------------------------------------------------------------------------------------
class _RenameHints:
  """
  Lookup of the file a deleted term file lives on as, read from the history of the dictionary directory.
  """

  def __init__(self, *, repo: Path, dictionary_dir: str) -> None:
    """
    Bind the lookup to a repository and its dictionary directory.

    Args:
      repo: Repository root.
      dictionary_dir: Repo-relative dictionary directory.
    """
    # the repository and the directory whose history is read
    self._repo = repo
    self._dir = dictionary_dir

  def query_renamed_to(self, stem: str) -> str | None:
    """
    Name the stem a deleted term file lives on as.

    Notes:
      - A file of the deleting commit whose name is not valid UTF-8 is never a candidate and is reported on stderr,
        but it still counts as a file the commit added or changed: when one was left out, neither the rule for
        exactly one added file nor the rule for none added and exactly one changed settles the hint, and only a
        document of the commit that moved its link can.
      - A link target read from a document line that is not valid UTF-8 text is never returned as a hint.

    Args:
      stem: The stem whose file is gone.

    Returns:
      The current stem as valid UTF-8 text, or `None` when the history names none.
    """

    # Domain(wiki.terms):
    # # Where a renamed term went
    # A link into the dictionary may point at a file that a rename deleted. The hint for it names the file the term
    # lives in now, found from the commit that deleted the old file. When that commit added exactly one file, that
    # is the new name. When it added none and changed exactly one, the term joined the one standing there. When
    # neither settles it, a document line of the same commit whose link moved from the old file to a new one names
    # the file. The commit that deleted the old file may be a merge: a deletion made by the merge itself is found
    # too, and the merge's changes are then read against the branch it was made on, its first parent. When document
    # lines are compared, every changed line of a document's text counts, whatever characters it opens with; only
    # the file headers of the diff are skipped. Commit messages are never read, since their wording is no record of
    # what moved. Otherwise there is no hint, and the dangling link is left for the curator.

    # a merge is listed once per parent it is compared with, so only the first line names the commit
    sha = next(iter(self._run_git(
      _Git.LOG, _Git.MERGES, _Git.DELETED, _Git.LAST, _Git.HASH_ONLY,
      _Git.PATHS, f"{_Git.LITERAL}{self._format_file_path(stem)}",
    ).split()), "")

    # guard: a file never deleted was never renamed
    if not sha:
      return None

    # the files the deleting commit added and changed in the dictionary
    added: list[str] = []
    modified: list[str] = []
    listing = self._run_git(
      _Git.SHOW, _Git.MERGES, _Git.FIRST_PARENT, _Git.NO_RENAMES, _Git.RELATIVE, _Git.NAME_STATUS, _Git.NUL_FIELDS,
      _Git.NO_HEADER,
      sha, _Git.PATHS, f"{_Git.LITERAL}{self._dir}",
    )
    fields = [ field for field in listing.split(_Git.NUL) if field ]
    unnamed = 0
    for status, rel in zip(fields[::2], fields[1::2], strict = False):
      stem_of = self._stem_of(rel)

      # a term file whose name is not UTF-8 cannot be named in a link: it is reported and is no candidate, yet
      # it still counts as a file the commit added or changed
      if stem_of is not None and not self._is_text(stem_of):
        print(f"terms: skipped a file of '{self._dir}' whose name is not UTF-8: {rel!r}", file = sys.stderr)
        unnamed += 1
        continue
      if stem_of is not None and status == _Git.ADDED:
        added.append(stem_of)
      elif stem_of is not None and status == _Git.MODIFIED:
        modified.append(stem_of)

    # one added file is the new name; no added and one changed file is the term it joined; a file left out for
    # its name makes either count uncertain, so neither rule settles it
    if not unnamed and len(added) == 1:
      return added[0]
    if not unnamed and not added and len(modified) == 1:
      return modified[0]

    # otherwise a document of the same commit that moved its link names the new file
    return self._query_from_documents(sha, stem)

  def _query_from_documents(self, sha: str, stem: str) -> str | None:
    """
    Name the new stem from the document lines whose link moved off the old stem in one commit.

    Args:
      sha: The commit that deleted the term file.
      stem: The deleted stem.

    Returns:
      The single stem those lines moved to, or `None`.
    """
    diff = self._run_git(
      _Git.SHOW, _Git.MERGES, _Git.FIRST_PARENT, _Git.NO_RENAMES, _Git.NO_HEADER, _Git.NO_CONTEXT, sha,
      _Git.PATHS, _Git.TREE, f"{_Git.EXCLUDE}{self._dir}",
    )
    found: set[str] = set()
    removed: list[str] = []
    added: list[str] = []
    in_header = False

    # lines are paired within each hunk, the n-th removed line with the n-th added one; a file's header runs from its
    # `diff ` line to its first hunk, so a content line that itself opens with `--` or `++` is never taken for one
    for row in [ *diff.splitlines(), _Git.HUNK ]:
      if row.startswith(( _Git.HUNK, _Git.FILE_HEADER )):
        found.update(self._find_all_moves(removed, added, stem))
        removed, added = [], []
        in_header = row.startswith(_Git.FILE_HEADER)
      elif in_header:
        continue
      elif row.startswith(_Git.REMOVED):
        removed.append(row[1:])
      elif row.startswith(_Git.ADDED_LINE):
        added.append(row[1:])

    # one destination is a hint; none or several are not
    return next(iter(found)) if len({ item.casefold() for item in found }) == 1 else None

  def _find_all_moves(self, removed: list[str], added: list[str], stem: str) -> list[str]:
    """
    Collect the stems a hunk's links moved to from the old stem.

    Args:
      removed: The hunk's removed lines.
      added: The hunk's added lines.
      stem: The deleted stem.

    Returns:
      The new stems, one per moved link; a stem that is not valid UTF-8 text is left out.
    """
    moves: list[str] = []
    for before, after in zip(removed, added, strict = False):
      old_links = [ link.stem() for link in _find_all_links(before, self._dir) ]
      new_links = [ link.stem() for link in _find_all_links(after, self._dir) ]
      # guard: a line whose links changed in number is no plain retarget
      if len(old_links) != len(new_links):
        continue
      moves.extend(
        new for old, new in zip(old_links, new_links, strict = True)
        if old.casefold() == stem.casefold() and new.casefold() != stem.casefold() and self._is_text(new)
      )
    return moves

  @staticmethod
  def _is_text(stem: str) -> bool:
    """
    Tell whether a stem is valid UTF-8 text.

    Args:
      stem: The stem to test.

    Returns:
      `True` when the stem is valid UTF-8 text, `False` otherwise.
    """
    # a stem taken from a line that is not valid text carries the odd byte as an unpaired mark
    try:
      stem.encode(_ENCODING)
    except UnicodeEncodeError:
      return False
    return True

  def _format_file_path(self, stem: str) -> str:
    """
    Return the repo-relative path of a term file.

    Args:
      stem: Its stem.

    Returns:
      The path.
    """
    return f"{self._dir}{_term_link_syntax.SLASH}{stem}{_term_dictionary.TERM_FILE_SUFFIX}"

  def _stem_of(self, rel: str) -> str | None:
    """
    Return the stem of a term file path directly in the dictionary directory.

    Args:
      rel: A repo-relative path.

    Returns:
      The stem, or `None` for any other path.
    """
    prefix = f"{self._dir}{_term_link_syntax.SLASH}"
    name = rel[len(prefix):]

    # guard: only a term file directly in the directory has a stem
    if (not rel.startswith(prefix) or _term_link_syntax.SLASH in name
        or not name.endswith(_term_dictionary.TERM_FILE_SUFFIX)):
      return None
    return name[:-len(_term_dictionary.TERM_FILE_SUFFIX)]

  def _run_git(self, *args: str) -> str:
    """
    Run one read-only git command in the repository.

    Args:
      args: The git subcommand and its arguments.

    Returns:
      Its output, or an empty string when git fails: the hint is advisory and a failure only drops it.
    """
    try:
      proc = subprocess.run(
        [ *_Git.EXE, *args ], cwd = str(self._repo), capture_output = True, check = False,
      )
    except OSError:
      return ""

    # the output is taken as bytes and decoded without loss, so a path name that is not UTF-8 cannot fail the hint
    return os.fsdecode(proc.stdout) if proc.returncode == 0 else ""
