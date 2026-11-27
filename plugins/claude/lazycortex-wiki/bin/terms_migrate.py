from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final

  from collections.abc import Callable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import axes as _axes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import dispatch as _dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import markers as _markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import term_dictionary as _term_dictionary  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import term_links as _term_links  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import terms as _terms  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Combined size of the documents one sweep job names; a directory heavier than this is split into several jobs.
_SWEEP_JOB_MAX_BYTES: Final = 150_000

# Settings section, layers and scope keys the verbs read and write.
_SECTION_TERMS: Final = "terms"
_KEY_SCOPES: Final = "scopes"
_KEY_PATHS: Final = "paths"
_KEY_DIR: Final = "dir"
_KEY_LEGACY_FILE: Final = "legacy_file"
_KEY_SOURCE_EXCLUDE: Final = "source_exclude"
_KEY_LINK_EXCLUDE: Final = "link_exclude"
_LAYER_TRACKED: Final = "tracked"
_LAYER_LOCAL: Final = "local"
_LAYER_MERGED: Final = "merged"
# The separator of a keyed settings path
_KEY_SEP: Final = "/"

# A heading of the old dictionary file, which opens one term.
_LEGACY_HEADING_RE: Final = re.compile(r"^##\s+(?P<term>.+?)\s*$")
_GROUP_TERM: Final = "term"
# A first-level heading of the old dictionary file, which closes the term above it.
_LEGACY_H1_RE: Final = re.compile(r"^# ")
# The most characters of a dropped chunk's first line the report carries.
_DROPPED_LINE_MAX: Final = 80
_NL: Final = "\n"
# The blank line between two definitions of one joined term
_DEFINITION_GAP: Final = "\n\n"

# Keys of one migrated scope's report, and of one joined term in it.
KEY_SCOPE: Final = "scope"
KEY_TERMS: Final = "terms"
KEY_MERGED: Final = "merged"
KEY_SKIPPED: Final = "skipped"
KEY_DOCUMENTS: Final = "documents"
KEY_UNDECODABLE: Final = "undecodable"
KEY_FILE: Final = "file"
KEY_DROPPED: Final = "dropped"
KEY_WHERE: Final = "where"
KEY_LINE: Final = "line"
# Keys of the documents a pass left alone because they changed on disk meanwhile, and of the links to headings of the
# old dictionary file it could not move, one `{file, links}` record per document.
KEY_CHANGED_ON_DISK: Final = "changed_on_disk"
KEY_UNMOVED: Final = "unmoved"
KEY_LINKS: Final = "links"

# Where a dropped chunk of the old dictionary stood.
DROPPED_PREAMBLE: Final = "preamble"
DROPPED_AFTER_H1: Final = "after-h1"

# Keys of one recased scope's report and of one rename in it.
KEY_RENAMED: Final = "renamed"
KEY_KEPT: Final = "kept"
KEY_FROM: Final = "from"
KEY_TO: Final = "to"

# The title line's heading prefix of a term file, and the carriage return a CRLF line ends in before its line feed.
_TITLE: Final = "# "
_CR: Final = "\r"
# The suffix of the temporary name a recased file passes through between its two names.
_RECASE_SUFFIX: Final = ".recase"

# The git setting that makes paths case-blind, its true value, and the `ls-files` switches for deleted and untracked
# paths.
_GIT_IGNORECASE: Final = "core.ignorecase"
_GIT_TRUE: Final = "true"
_GIT_DELETED: Final = "--deleted"
_GIT_OTHERS: Final = "--others"

# Keys of the sweep's dispatch report.
KEY_DIRECTORIES: Final = "directories"
KEY_QUEUED: Final = "queued"
KEY_ALREADY_QUEUED: Final = "already_queued"
KEY_DEFERRED_TO: Final = "deferred_to"
KEY_UNMIGRATED: Final = "unmigrated"
KEY_ERROR: Final = "error"
KEY_HOST: Final = "host"
KEY_PATH: Final = "path"

# Verdict keys and states of core's daemon gate check.
_RUN_HERE_STATE: Final = "state"
_STATES_QUEUE: Final = frozenset({ "run-here", "unset" })
_STATES_DEFER: Final = frozenset({ "not-this-checkout", "not-this-host" })

# The status `dispatch-job` answers when a job under the same key is still active.
_STATUS_ALREADY_QUEUED: Final = "already-queued"
_KEY_STATUS: Final = "status"

# The sweep's dedup-key prefix, the separator after the scope id, and the separator before a part number.
_SWEEP_KEY_PREFIX: Final = "terms-sweep:"
_SCOPE_SEP: Final = ":"
_PART_SEP: Final = "#"
# The escapes a scope id and a directory take inside a key, the escape character's own first, so that the two
# separators never stand in a name.
_KEY_ESCAPES: Final = ( ( "%", "%25" ), ( ":", "%3A" ), ( "#", "%23" ) )

# The tracked state directory, the sweep marker's name pattern and its one key.
_STATE_DIR: Final = ".state"
_MARK_NAME: Final = "lazy-wiki.terms-sweep.{scope}.json"
_MARK_SWEPT_AT: Final = "swept_at"
_UTC_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

# Outcomes of seeding a scope's link exclusion.
SEED_SEEDED: Final = "seeded"
SEED_KEPT: Final = "kept"
SEED_NO_SCOPE: Final = "no-scope"

# The leading character of a hidden entry, which a dictionary directory may carry without holding a term.
_HIDDEN: Final = "."

# The separator of `git ls-files -z` output, and the encoding of every file read.
_NUL: Final = "\0"
_ENCODING: Final = "utf-8"


# ----------------------------------------------------------------------------------------
class TermsVerbError(Exception):
  """
  Failure that stops a terms migration verb before it finishes.

  Attributes:
    report: What the verb had done before it stopped, for its outcome line.
  """

  def __init__(self, reason: str, *, report: dict | None = None) -> None:
    """
    Create the failure with its reason and what the verb had done so far.

    Args:
      reason: Why the verb stopped, as the exception's message.
      report: Outcome of the work finished before the failure.
    """
    # the reason as the exception's message
    super().__init__(reason)

    # what the verb had done before it stopped, for its outcome line
    self.report: dict | None = report


# ----------------------------------------------------------------------------------------
class UnclosedFenceError(ValueError):
  """
  Failure of cutting an old dictionary text whose code fence is still open at its end.

  Attributes:
    line: Number of the line that opened the fence left open, counted from 1.
  """

  def __init__(self, line: int) -> None:
    """
    Create the failure with the line that opened the unclosed fence.

    Args:
      line: Number of the line that opened the fence left open, counted from 1.
    """
    # the reason as the exception's message
    super().__init__(f"a code fence opened on line {line} is never closed")

    # the 1-based number of the line that opened the fence left open
    self.line = line


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class TermsSettings:
  """
  Settings a terms migration verb reads once per run.

  Attributes:
    scopes: Every terms scope of the merged settings, by id, in configuration order.
    mirrors: Mirror directories of every wiki scope.
    managed: Dictionary directories of every terms scope, then the generated domain tree when configured.
  """

  # Every terms scope of the merged settings, by id, in configuration order
  scopes: dict[str, dict]
  # The mirror directories of every wiki scope
  mirrors: list[str]
  # The dictionary directories of every terms scope, then the generated domain tree
  managed: list[str]

  @classmethod
  def read(cls, repo: Path) -> TermsSettings | None:
    """
    Read the terms settings of a repository.

    Args:
      repo: Absolute repository root.

    Returns:
      The settings of the merged view, or `None` when it carries no terms scopes.
    """
    terms = _axes.read_settings(repo, _SECTION_TERMS, layer = _LAYER_MERGED)
    scopes = terms.get(_KEY_SCOPES) if isinstance(terms, dict) else None

    # guard: the merged settings carry no terms scopes at all
    if not isinstance(scopes, dict):
      return None

    # the dictionary directories come from the scopes held here, never from a memo of an older read
    return cls(
      scopes = { scope_id: cfg for scope_id, cfg in scopes.items() if isinstance(cfg, dict) },
      mirrors = _terms.read_all_mirror_paths(repo),
      managed = _axes.read_managed_dirs(repo, dictionaries = _axes.scope_dictionary_dirs(scopes)),
    )

  def find_all_served(self) -> list[tuple[str, dict, str]]:
    """
    List the scopes that name a dictionary directory.

    Guarantees:
      - Only a scope that names a dictionary directory is returned, in configuration order, and its directory
        comes back without a trailing separator.

    Returns:
      One tuple of scope id, scope settings and dictionary directory per served scope.
    """

    # Contract:
    # Only a scope that names a dictionary directory is returned, in configuration order, and its directory
    # comes back without a trailing separator.

    # only a scope naming its dictionary directory is served
    return [
      ( scope_id, cfg, cfg[_KEY_DIR].rstrip(_KEY_SEP) ) for scope_id, cfg in self.scopes.items()
      if isinstance(cfg.get(_KEY_DIR), str) and cfg[_KEY_DIR].strip(_KEY_SEP)
    ]

  def build_context(self, cfg: dict) -> _term_links.SyncContext:
    """
    Build the facts a document pass over one scope consults.

    Args:
      cfg: Settings of the scope the pass runs over.

    Returns:
      The mirror directories, managed directories and link exclusions of the pass.
    """
    # the facts every document pass of the run consults
    return _term_links.SyncContext(
      mirror_paths = list(self.mirrors), managed_dirs = list(self.managed),
      link_exclude = _filter_strings(cfg, _KEY_LINK_EXCLUDE),
    )


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class LegacyCut:
  """
  Term files cut out of an old single-file dictionary.

  Attributes:
    files: Text of every term file, by file name stem.
    merged: One `{file, terms}` record per file that joins several headings.
    skipped: Headings whose term names no usable file.
    dropped: One `{where, line}` record per dropped chunk that holds text, in file order.
  """

  # The text of every term file, by file name stem
  files: dict[str, str]
  # One `{file, terms}` record per file that joins several headings
  merged: list[dict]
  # The headings whose term names no usable file
  skipped: list[str]
  # One `{where, line}` record per dropped chunk that holds text
  dropped: list[dict]

  @classmethod
  def from_text(cls, text: str) -> LegacyCut:
    """
    Cut the text of an old single-file dictionary into term files.

    Guarantees:
      - A heading that names no usable file never makes the cut fail; it is reported in `skipped`.
      - No definition is lost: headings whose file names coincide, ignoring letter case, end up in one file that
        keeps every definition in the order the headings appeared.
      - No text is dropped silently: every chunk of the old dictionary that belongs to no definition and holds a
        non-blank line that is not an H1 heading is reported in `dropped`, in file order.
      - An H1 heading line is neither content nor a dropped line; it never appears in `dropped`, while text under it
        still does.
      - A fenced code block still open at the end of the text makes the cut fail with an `UnclosedFenceError` that
        carries the 1-based line which opened it; a cut in which an open fence swallowed the later headings is never
        returned.

    Args:
      text: Text of the old dictionary file.

    Returns:
      The term files, the joined terms, the skipped headings and the dropped chunks.

    Raises:
      UnclosedFenceError: If a fenced code block is still open at the end of the text.
    """

    # Domain(wiki.terms):
    # # How the old single-file dictionary becomes term files
    # Every second-level heading of the old dictionary opens one term, and a first-level heading closes it: nothing
    # from a first-level heading onward belongs to a definition. A tag line such as `#protected/...` is not a
    # heading. A fenced code block closes only on a line of the same fence character, at least as long as the opening
    # run, with nothing after it but whitespace. A line inside a fence, and the fence lines themselves, are never a
    # heading: a second-level line there opens no term and a first-level line there closes nothing. Such lines belong
    # to whatever stands around the fence: the definition of the term above, the preamble, or the stretch dropped
    # after a closing first-level heading. A fence still open at the end of the file makes the whole file refused,
    # because the open fence would swallow every later term into one definition: the migration stops before anything
    # is written or deleted, keeps the old file and its setting, and the refusal names the file and the line where
    # the unclosed fence opened and says that the fence must be closed by hand. A heading's exact spelling is the
    # term's title, and the section under it is the definition. Text before the first term heading (the preamble) and
    # everything from a closing first-level heading to the next term heading or the end of the file stay out of the
    # term files, but nothing is dropped silently: each such stretch that holds text is reported with where it stood
    # and its first line that is not a first-level heading. A first-level heading line is a title: it is neither
    # content nor dropped text, so it never counts as text and is never reported itself, and a preamble made only of
    # a title reports nothing. An old file that holds a non-blank line other than a first-level heading but yields no
    # term at all is refused: the migration stops before writing anything and keeps the old file. An empty or blank
    # old file, and one made only of title lines and blank lines, becomes an empty dictionary.
    # Headings whose file names coincide, ignoring letter case, are one term. Its file is named after the first of
    # those headings, its title is that file name in its normalised form, and every definition is kept, in order,
    # separated by a blank line. That blank line inside a definition is how a later audit recognises a joined term
    # that the curator must rewrite into one. A heading made only of characters a file name cannot carry names no
    # file: it is skipped and reported. A skipped heading never fails the run while at least one other heading makes
    # a term. When every heading names no file, the old file yields no term at all and is refused like any other such
    # file: the migration stops before writing anything, keeps the old file, and names those headings in the refusal.

    # Contract:
    # A heading that names no usable file NEVER makes the cut fail; it is reported in `skipped`.

    # Contract:
    # No definition is lost: headings whose file names coincide, ignoring letter case, end up in one file that
    # keeps every definition in the order the headings appeared.

    # Contract:
    # No text is dropped silently: every chunk of the old dictionary that belongs to no definition and holds a
    # non-blank line that is not an H1 heading is reported in `dropped`, in file order. An H1 heading line is neither
    # content nor a dropped line, so it never appears in `dropped`; text under it still does.

    # Contract:
    # A fenced code block still open at the end of the text makes the cut fail with an `UnclosedFenceError` that
    # carries the 1-based line which opened it; the caller NEVER receives a cut in which an open fence swallowed
    # the headings after it.

    sections: list[tuple[str, list[str]]] = []
    dropped: list[dict] = []
    outside: tuple[str, list[str]] | None = ( DROPPED_PREAMBLE, [] )
    fence = _markers.CodeFence()
    fence_opened = 0

    # every `## ` heading opens a term and an H1 closes it; the preamble and each closing H1's tail are dropped
    for number, line in enumerate(text.split(_NL), start = 1):
      # a fence line and every line inside a fence belong to the chunk they stand in, never a heading; the line that
      # opens a fence is remembered for the refusal of a fence left open
      if fence.step(line) or fence.inside:
        fence_opened = ( fence_opened or number ) if fence.inside else 0
        ( outside[1] if outside is not None else sections[-1][1] ).append(line)
        continue
      match = _LEGACY_HEADING_RE.match(line)
      if match is not None:
        cls._report_dropped(outside, dropped)
        outside = None
        sections.append(( match.group(_GROUP_TERM), [] ))
      elif _LEGACY_H1_RE.match(line):
        # an H1 line is a title, never content nor a dropped line; after a term it opens a dropped chunk
        if outside is None:
          outside = ( DROPPED_AFTER_H1, [] )
      elif outside is not None:
        outside[1].append(line)
      else:
        sections[-1][1].append(line)

    # guard: a fence still open at the end of the file would swallow every heading after it into one definition
    if fence.inside:
      raise UnclosedFenceError(fence_opened)

    # the chunk still open at the end of the file is dropped like any other
    cls._report_dropped(outside, dropped)

    # headings that name one file, ignoring letter case, form one group in the order they appear
    groups: dict[str, list[tuple[str, str, str]]] = {}
    skipped: list[str] = []
    for term, body in sections:
      stem = _term_dictionary.term_file_stem(term)
      # guard: a term made only of forbidden characters names no file
      if not stem:
        skipped.append(term)
        continue
      groups.setdefault(stem.casefold(), []).append(( stem, term, _NL.join(body).strip() ))

    # a lone heading keeps its spelling; joined headings take the file name and keep every definition in order
    files: dict[str, str] = {}
    merged: list[dict] = []
    for members in groups.values():
      stem = members[0][0]
      if len(members) == 1:
        files[stem] = _term_dictionary.render_term_file(members[0][1], members[0][2])
        continue
      definitions = _DEFINITION_GAP.join(definition for _, _, definition in members if definition)
      files[stem] = _term_dictionary.render_term_file(stem, definitions)
      merged.append({ KEY_FILE: stem, KEY_TERMS: [ term for _, term, _ in members ] })
    return cls(files = files, merged = merged, skipped = skipped, dropped = dropped)

  @staticmethod
  def _report_dropped(chunk: tuple[str, list[str]] | None, dropped: list[dict]) -> None:
    """
    Record a dropped chunk of the old dictionary when it holds any text.

    Args:
      chunk: Where the chunk stood and its lines, or `None` when no chunk is open.
      dropped: The records of the dropped chunks so far; extended in place.
    """
    lines = [ line.strip() for line in chunk[1] if line.strip() ] if chunk is not None else []

    # guard: no open chunk, or one made only of blank lines, drops nothing worth naming
    if chunk is None or not lines:
      return

    # the chunk is named by where it stood and its first line
    dropped.append({ KEY_WHERE: chunk[0], KEY_LINE: lines[0][ : _DROPPED_LINE_MAX ] })


# ----------------------------------------------------------------------------------------
class TermsMigration:
  """
  Migration of terms scopes from an old single dictionary file to a directory of term files.
  """

  def __init__(self, *, repo: Path, settings: TermsSettings, core: _dispatch.CoreDispatch | None = None) -> None:
    """
    Prepare the migration of one repository.

    Args:
      repo: Absolute repository root.
      settings: Terms settings read once for the run.
      core: Bridge to core's settings writes; required by `run`, unused by `check`.
    """
    # the repository, its settings as read once for the run, and the door to core's settings writes
    self._repo = repo
    self._settings = settings
    self._core = core

    # opt: the cut of each old dictionary file computed once per run — valid while the old file is not changed
    # between the check and the cut within one run
    self._cuts: dict[str, LegacyCut] = {}

  def check(self) -> bool:
    """
    Tell whether the migration still has work.

    Guarantees:
      - The check never writes.
      - A document that is not valid UTF-8 is never counted as work.
      - The answer is true while a document the document pass would edit still holds an old terms line of a term the
        dictionary holds, or a link the pass would move onto a term file. It is also true while such a document that
        the scope excludes as a term source still carries an old terms section, whatever the section holds, in an
        already migrated scope and with an empty dictionary too.

    Returns:
      `True` when a scope still names its old dictionary file, or an editable document still carries an old terms
      line of a term the dictionary holds, a link to a heading of the old file that moves onto a term file, or, when
      the scope excludes it as a term source, an old terms section.
    """

    # Domain(wiki.terms):
    # # When the migration still has work
    # The migration has work left while a scope still names its old dictionary file. It also has work left while a
    # document that the document pass would edit still carries an old terms line of a term the dictionary now holds,
    # or a link to a heading of the old file that the pass would move onto a term file.
    # A document that the scope excludes as a term source, which no curator ever reads, has work left as soon as it
    # still carries an old terms section at all, whatever the section holds, in an already migrated scope too and
    # when the dictionary is empty. The documents the pass leaves alone, such as mirrors, folder notes, managed
    # directories and documents the scope excludes from link editing, never count as work. A document that is not
    # valid UTF-8 is never work either, because the pass skips it.

    # Contract:
    # The check NEVER writes; it only answers whether any work is left. A document that is not valid UTF-8 is never
    # counted as work.

    # Contract:
    # The check answers true while a document the document pass would edit still holds an old terms line of a term
    # the dictionary holds, or a link the pass would move onto a term file. It also answers true while such a
    # document that the scope excludes as a term source still carries an old terms section, whatever the section
    # holds, in an already migrated scope and with an empty dictionary too.

    served = self._settings.find_all_served()

    # a scope still naming its old dictionary file has work left
    if any(_KEY_LEGACY_FILE in cfg for _, cfg, _ in served):
      return True

    # a document of a scope still carrying an old terms line of a term its dictionary holds, or a link to a heading of
    # the old file that the pass would move onto a term file, has work left
    for _, cfg, directory in served:
      plan = self._build_plan(cfg, directory)
      known = { stem.casefold() for stem in plan.terms }
      context = self._settings.build_context(cfg)
      for rel in list_documents(self._repo, _filter_strings(cfg, _KEY_PATHS)):
        # guard: a document the pass may not edit is no work of the migration
        if _term_links.find_refusal_reason(self._repo, rel, context) is not None:
          continue
        # guard: a document that is not valid UTF-8 is skipped by the pass, so it is no work either
        try:
          text = TextFile(path = self._repo / rel).read()
        except UnicodeDecodeError:
          continue
        # a document no curator reads as a term source has work left while it carries an old terms section at all
        if self._is_source_excluded(cfg, rel) and _term_links.has_legacy_section(text):
          return True
        # guard: an empty dictionary settles no old terms line and takes no old heading link
        if not known:
          continue
        words = _term_links.find_all_legacy_terms(text)
        if any(_term_dictionary.term_file_stem(word).casefold() in known for word in words):
          return True
        if _term_links.has_legacy_anchor_links(text, plan):
          return True
    return False

  def run(self) -> list[dict]:
    """
    Migrate every served scope to its dictionary directory and bring its documents in line.

    Guarantees:
      - A scope whose dictionary directory holds a file that the cut of its live old dictionary file would not write
        with identical bytes stops the whole run, and then nothing is written for any scope.
      - A directory holding only some of exactly the files the cut writes is an interrupted earlier run, and the
        run resumes it.
      - A live old dictionary file that holds a non-blank line that is not an H1 heading but cuts into no term file
        stops the whole run, and then nothing is written for any scope and that file is not deleted; an empty or
        whitespace-only old file, and one made only of H1 title lines and blanks, still migrates to an empty
        dictionary.
      - A live old dictionary file in which a fenced code block is still open at the end of the file stops the whole
        run, and then nothing is written for any scope, that file is not deleted and its setting stays.
      - A document that is not valid UTF-8 never fails the run; it is skipped and listed in the report of its
        scope under `undecodable`.
      - No new term link is placed in a document; only links already standing are normalised, links to headings of
        the old dictionary file are moved onto the term files, and old terms lines of terms the dictionary holds are
        removed. In a document that the scope excludes as a term source the old terms section is removed whole,
        heading, comment and every line up to the next heading of level one or two, whatever the section holds. A
        document the pass refuses stays untouched.
      - Nothing is staged or committed; whatever changed is left in the working tree for the caller to commit.
      - Repeating the run on a repository it has already migrated changes nothing.

    Returns:
      One report per served scope, in configuration order. Besides the documents rewritten and the undecodable ones,
      a report lists under `changed_on_disk` the documents that changed on disk during the run and were left as they
      were, and under `unmoved` the links to headings of the old dictionary file that no link edit reaches, per
      document.

    Raises:
      TermsVerbError: If a dictionary directory holds a file the live old file's cut would not write with identical
        bytes, a live old dictionary file holds a non-blank line other than an H1 heading but cuts into no term file,
        an old dictionary file is not valid UTF-8 or has a code fence still open at its end, or core cannot drop the
        old file's setting.
    """

    # Domain(wiki.terms):
    # # Migrating the terms scopes to dictionary directories
    # Nothing is written until every scope has passed the check. A dictionary directory beside a still-existing old
    # file stops the whole run only when it holds a file that the cut of that old file would not write with identical
    # content: a foreign file, or a term file whose content differs. Two dictionaries are never merged silently.
    # A directory holding only part of exactly what the cut writes is an interrupted earlier run: the run resumes,
    # writes the missing term files, deletes the old file and drops the setting.
    # A scope is then migrated in order: the old file is cut into term files, the file is deleted, and the setting
    # that names it is dropped from every settings layer that carries it. The setting goes last, so a run
    # interrupted earlier finds the cut done and only drops the setting.
    # After that every document of the scope is passed, documents under an open review included. Links already
    # standing get their targets normalised, links to headings of the old file are moved onto the term files the cut
    # made of them, and the old terms-section lines of terms the dictionary now holds are removed; lines of terms it
    # does not hold wait for the curator. A document the scope excludes as a term source is the exception: no curator
    # ever comes to it, so its old terms section is removed whole, heading, comment and every line up to the next
    # heading of level one or two, whatever terms it names, known to the dictionary or not, and also when it holds
    # prose or a table instead of term lines; one blank line stays between its neighbours. Everything else about such
    # a document is as in any other. No new link is placed, since every link is placed by the curator. Mirror
    # documents, folder notes, documents inside dictionary directories or the generated domain tree, and documents
    # the scope excludes from link editing are left as they are, a terms section in them included. A document that is
    # not valid UTF-8 never stops the migration: it is skipped, named, and listed in the report of its scope.
    # Each document is read once, and its new text is made from exactly what was read. A document that changed on disk
    # between that reading and the write is someone's edit: it is left as it stands and named in the report, never
    # overwritten.
    # A link to a heading of the old file may stand where no link edit reaches: on a heading line, on a checkbox line,
    # in a comment, in code. It stays as written, as before, but it is no longer silent: the run names each such link,
    # per document, so the operator can move it by hand. The check of whether the migration still has work never
    # counts such a link, because the run can never close it.

    # Contract:
    # A scope whose dictionary directory holds a file that the cut of its live old dictionary file would not write
    # with identical bytes stops the whole run with a `TermsVerbError`, and then nothing is written for any scope.
    # A directory holding only some of exactly the files the cut writes is an interrupted earlier run, and the run
    # resumes it.

    # Contract:
    # A live old dictionary file that holds a non-blank line that is not an H1 heading but cuts into no term file
    # stops the whole run with a `TermsVerbError`, and then nothing is written for any scope and that file is not
    # deleted. An empty or whitespace-only old file, and one made only of H1 title lines and blanks, still migrates
    # to an empty dictionary.

    # Contract:
    # A live old dictionary file in which a fenced code block is still open at the end of the file stops the whole
    # run with a `TermsVerbError`, and then nothing is written for any scope, that file is not deleted and its
    # setting stays.

    # Contract:
    # A document of a scope that is not valid UTF-8 NEVER fails the run; it is skipped and listed in the report of
    # its scope under `undecodable`.

    # Contract:
    # The run NEVER places a new term link in a document; it only normalises links already standing, moves links to
    # headings of the old dictionary file onto the term files, and removes old terms lines of terms the dictionary
    # holds. In a document that the scope excludes as a term source it removes the old terms section whole, heading,
    # comment and every line up to the next heading of level one or two, whatever the section holds. A document the
    # pass refuses stays untouched.

    # Contract:
    # The run NEVER stages or commits; whatever it changed is left in the working tree for the caller to commit.

    # Contract:
    # The run is idempotent: repeating it on a repository it has already migrated changes nothing.

    served = self._settings.find_all_served()

    # every scope is checked before anything is written, so a refused run leaves the repository as it was
    for scope_id, cfg, directory in served:
      self._check_cut(scope_id, cfg, directory)

    # the old files are cut first, so every document pass sees its scope's whole dictionary
    reports = [ self._cut(scope_id, cfg, directory) for scope_id, cfg, directory in served ]

    # then every document of each scope has its links and its old terms section brought in line
    for report, ( _, cfg, directory ) in zip(reports, served, strict = True):
      report.update(self._pass_documents(cfg, directory))
    return reports

  def _check_cut(self, scope_id: str, cfg: dict, directory: str) -> None:
    """
    Refuse a scope whose old file cannot be migrated cleanly into its dictionary directory.

    Args:
      scope_id: Id of the scope.
      cfg: Settings of the scope.
      directory: Repo-relative dictionary directory of the scope.

    Raises:
      TermsVerbError: If the old file cuts into no term file while it holds a `## ` heading that names no file (the
        refusal names those headings) or a non-blank line other than an H1 heading, the directory holds a file that
        the cut of the still existing old file would not write with identical bytes, or the old file is not valid
        UTF-8 or has a code fence still open at its end.
    """
    legacy = cfg.get(_KEY_LEGACY_FILE)

    # guard: a scope without an old file, or one whose old file is already gone, has nothing to merge into
    if not isinstance(legacy, str) or not (self._repo / legacy).is_file():
      return

    # the cut of the old file, which every check below judges
    cut = self._read_cut(legacy)

    # guard: headings that all name no file would leave an empty dictionary and delete the old file for nothing
    if not cut.files and cut.skipped:
      raise TermsVerbError(
        f"scope {scope_id}: the old dictionary file {legacy} holds `## ` term headings but none of them yields "
        f"a file name ({', '.join(cut.skipped)}); nothing was migrated",
      )

    # guard: an old file holding text beyond its H1 title lines but no term would be deleted for an empty dictionary
    if not cut.files and any(
      line.strip() and not _LEGACY_H1_RE.match(line)
      for line in TextFile(path = self._repo / legacy).read().split(_NL)
    ):
      raise TermsVerbError(
        f"scope {scope_id}: the old dictionary file {legacy} holds text but no `## ` term heading was found; "
        f"nothing was migrated",
      )

    # guard: no directory yet, so nothing can clash with the cut
    target = self._repo / directory
    if not target.is_dir():
      return

    # a file the cut would write with the same bytes is a run interrupted part-way; anything else is a second
    # dictionary beside the old file
    expected = {
      f"{stem}{_term_dictionary.TERM_FILE_SUFFIX}": text.encode(_ENCODING) for stem, text in cut.files.items()
    }
    foreign = [
      name for name in sorted(os.listdir(target))
      if not name.startswith(_HIDDEN)
      and not ( name in expected and (target / name).is_file() and (target / name).read_bytes() == expected[name] )
    ]

    # guard: a dictionary directory holding a file the cut would not write beside a live old file is refused
    if foreign:
      raise TermsVerbError(
        f"scope {scope_id}: dictionary directory {directory} holds files the old file {legacy} would not produce "
        f"({', '.join(foreign)}) while that file still exists",
      )

  def _read_cut(self, legacy: str) -> LegacyCut:
    """
    Return the cut of one old dictionary file into term files.

    Args:
      legacy: Repo-relative path of the old dictionary file.

    Returns:
      The term files, merged terms, skipped headings and dropped chunks the old file cuts into.

    Raises:
      TermsVerbError: If the old file is not valid UTF-8 or has a code fence still open at its end.
    """
    # the cut of one old file, computed once per run
    if legacy not in self._cuts:
      try:
        self._cuts[legacy] = LegacyCut.from_text(TextFile(path = self._repo / legacy).read())
      except UnicodeDecodeError as error:
        raise TermsVerbError(f"the old dictionary file {legacy} is not valid UTF-8: {error}") from error
      except UnclosedFenceError as error:
        raise TermsVerbError(
          f"the old dictionary file {legacy} has a code fence opened on line {error.line} that is never "
          f"closed; close that fence by hand and run the migration again; nothing was migrated",
        ) from error
    return self._cuts[legacy]

  def _cut(self, scope_id: str, cfg: dict, directory: str) -> dict:
    """
    Turn one scope's old dictionary file into term files and drop the setting that names it.

    Args:
      scope_id: Id of the scope.
      cfg: Settings of the scope.
      directory: Repo-relative dictionary directory of the scope.

    Returns:
      The scope's report, with the count of cut terms, the joined terms, the skipped headings and the dropped
      chunks.

    Raises:
      TermsVerbError: If the old file has a code fence still open at its end, or the setting that names it cannot be
        dropped.
    """
    report: dict = {
      KEY_SCOPE: scope_id, KEY_TERMS: 0, KEY_MERGED: [], KEY_SKIPPED: [], KEY_DROPPED: [], KEY_DOCUMENTS: [],
      KEY_UNDECODABLE: [], KEY_CHANGED_ON_DISK: [], KEY_UNMOVED: [],
    }
    legacy = cfg.get(_KEY_LEGACY_FILE)

    # guard: a scope already on its directory has nothing to cut
    if not isinstance(legacy, str):
      return report

    # the old file, when it is still there, becomes one file per term and then goes; the directory appears only
    # with its first term file, since a missing directory is an empty dictionary
    source = self._repo / legacy
    if source.is_file():
      cut = self._read_cut(legacy)
      if cut.files:
        (self._repo / directory).mkdir(parents = True, exist_ok = True)
      for stem, text in cut.files.items():
        _term_links.write_document(self._repo, f"{directory}/{stem}{_term_dictionary.TERM_FILE_SUFFIX}", text)
      source.unlink()
      report.update({
        KEY_TERMS: len(cut.files), KEY_MERGED: cut.merged, KEY_SKIPPED: cut.skipped, KEY_DROPPED: cut.dropped,
      })

    # the key goes last, so a run stopped before it finds the cut done and only drops the key again
    self._drop_legacy_key(scope_id)
    return report

  def _drop_legacy_key(self, scope_id: str) -> None:
    """
    Remove the old-file setting of one scope from every settings layer that carries it.

    Args:
      scope_id: Id of the scope.

    Raises:
      TermsVerbError: If core is unreachable or a settings write fails.
    """
    # guard: dropping a settings key needs core
    if self._core is None:
      raise TermsVerbError("core CLI is unreachable; the old dictionary key cannot be dropped")

    # the key leaves every layer that carries it, the rest of the scope stays
    key = _KEY_SEP.join(( _KEY_SCOPES, scope_id, _KEY_LEGACY_FILE ))
    try:
      for layer in ( _LAYER_TRACKED, _LAYER_LOCAL ):
        terms = _axes.read_settings(self._repo, _SECTION_TERMS, layer = layer)
        scopes = terms.get(_KEY_SCOPES) if isinstance(terms, dict) else None
        cfg = scopes.get(scope_id) if isinstance(scopes, dict) else None
        if isinstance(cfg, dict) and _KEY_LEGACY_FILE in cfg:
          self._core.delete_setting(repo = self._repo, section = _SECTION_TERMS, key = key, layer = layer)
    except ( RuntimeError, ValueError, OSError ) as error:
      raise TermsVerbError(f"scope {scope_id}: dropping {_KEY_LEGACY_FILE} failed: {error}") from error

  def _build_plan(self, cfg: dict, directory: str, *, drop_legacy: bool = False) -> _term_links.LinkPlan:
    """
    Build the link plan that brings the documents of one scope in line with its dictionary directory.

    Args:
      cfg: Settings of the scope.
      directory: Repo-relative dictionary directory of the scope.
      drop_legacy: Whether the plan removes an old terms section whole.

    Returns:
      The plan that names no word, so it places no new link, names the old dictionary file's path, and removes an
      old terms section whole only when `drop_legacy` is set.
    """
    # the old file's path without its extension, and the dictionary directory, which is where the old file stood
    # when the directory took its name
    legacy = cfg.get(_KEY_LEGACY_FILE)
    paths = [ directory ]
    if isinstance(legacy, str):
      paths.append(PurePosixPath(legacy).with_suffix("").as_posix())

    # a plan that only normalises the links already standing, moves links to headings of the old file onto the term
    # files and settles the old terms lines the dictionary holds; it names no word, so no new link is placed
    return _term_links.LinkPlan(
      dictionary_dir = directory,
      terms = _term_dictionary.TermDictionary(path = self._repo / directory).read_terms(),
      link_retargets = {}, retargets = {}, word_links = {}, rejected = set(),
      legacy_paths = tuple(dict.fromkeys(paths)), drop_legacy = drop_legacy,
    )

  @staticmethod
  def _is_source_excluded(cfg: dict, rel: str) -> bool:
    """
    Tell whether a scope excludes a document as a term source.

    Args:
      cfg: Settings of the scope.
      rel: Repo-relative path of the document.

    Returns:
      `True` when the document matches one of the scope's term-source exclusions.
    """
    matcher = _scope.GlobMatcher()
    return any(matcher.match(rel, glob) for glob in _filter_strings(cfg, _KEY_SOURCE_EXCLUDE))

  def _pass_documents(self, cfg: dict, directory: str) -> dict[str, list]:
    """
    Bring the links and the old terms text of every document of one scope in line with its dictionary.

    A document that the scope excludes as a term source loses its old terms section whole.

    Notes:
      - A document changed on disk between its reading and its write is not written.
      - A document that cannot be read at all is set aside and named like one that is not valid UTF-8, and the pass
        goes on with the next document.

    Args:
      cfg: Settings of the scope.
      directory: Repo-relative dictionary directory of the scope.

    Returns:
      The report keys of the scope. `documents` lists the repo-relative documents that were rewritten, `undecodable`
      the ones set aside because they are not valid UTF-8, `changed_on_disk` the ones that changed on disk between
      being read and being written and so were not written, and `unmoved` one `{file, links}` entry per document
      holding links to headings of the old dictionary file that no link edit reaches.
    """
    plan = self._build_plan(cfg, directory)
    dropping = self._build_plan(cfg, directory, drop_legacy = True)

    # every document of the scope, documents under review included; a document no curator reads loses its old terms
    # section whole
    return pass_all_documents(
      self._repo, list_documents(self._repo, _filter_strings(cfg, _KEY_PATHS)), self._settings.build_context(cfg),
      plan_of = lambda rel: dropping if self._is_source_excluded(cfg, rel) else plan,
    )


# ----------------------------------------------------------------------------------------
class GitPathProbe:
  """
  What git sees of a repository's paths, read without staging or writing anything.
  """

  def __init__(self, *, repo: Path) -> None:
    """
    Bind the probe to a repository.

    Args:
      repo: Absolute repository root.
    """
    # the repository every git call runs in
    self._repo = repo

  def is_tracked(self, rel: str) -> bool:
    """
    Tell whether git tracks exactly a path.

    Notes:
      - Runs git.

    Args:
      rel: Repo-relative posix path.

    Returns:
      `True` when the index lists the path as written.

    Raises:
      CalledProcessError: If git cannot list the files.
    """
    return bool(self._list_files(rel))

  def is_case_blind(self) -> bool:
    """
    Tell whether git on this checkout ignores letter case in paths.

    Notes:
      - Runs git.

    Returns:
      `True` when the repository's `core.ignorecase` is true.
    """
    result = subprocess.run(
      [ "git", "config", "--bool", _GIT_IGNORECASE ], cwd = str(self._repo), capture_output = True, text = True,
      check = False,
    )
    return result.stdout.strip() == _GIT_TRUE

  def is_rename_seen(self, old_rel: str, new_rel: str) -> bool:
    """
    Tell whether git sees a file moved from one path to another on disk.

    Notes:
      - Runs git; called once the file stands at its new path.

    Args:
      old_rel: Repo-relative posix path the file stood at.
      new_rel: Repo-relative posix path the file stands at now.

    Returns:
      `True` when git does not track the old path, or lists the old path as deleted and the new one as untracked.

    Raises:
      CalledProcessError: If git cannot list the files.
    """
    # a path git never tracked loses nothing to a rename; a tracked one needs git to see it gone and the new path new
    return not self.is_tracked(old_rel) or (
      bool(self._list_files(old_rel, _GIT_DELETED)) and bool(self._list_files(new_rel, _GIT_OTHERS))
    )

  def _list_files(self, rel: str, *flags: str) -> str:
    """
    List one path as `git ls-files` sees it.

    Args:
      rel: Repo-relative posix path, matched literally.
      flags: Extra `ls-files` switches choosing which paths are listed.

    Returns:
      The listing, empty when git lists nothing.

    Raises:
      CalledProcessError: If git cannot list the files.
    """
    return os.fsdecode(subprocess.check_output(
      [ "git", "ls-files", "-z", *flags, "--", f":(literal){rel}" ], cwd = str(self._repo),
    ))


def _move_twice(source: Path, target: Path) -> None:
  """
  Move a file to a new path through a temporary name beside it.

  Args:
    source: The file.
    target: The path it moves to.

  Raises:
    OSError: If a move fails.
  """
  # a hidden temporary name, which no term listing reads, carries the file between the two names
  temporary = target.with_name(f"{_HIDDEN}{target.name}{_RECASE_SUFFIX}")
  source.rename(temporary)
  temporary.rename(target)


# ----------------------------------------------------------------------------------------
class TermsRecase:
  """
  Migration of terms dictionaries to the letter case of each term's language.

  A term file's title, and the file name derived from it, takes the case its language asks for; the links to a
  renamed term file follow it, keeping the words they show. A file whose rename git does not see keeps its name,
  and its links stay.
  """

  def __init__(self, *, repo: Path, settings: TermsSettings) -> None:
    """
    Prepare the recase of one repository.

    Args:
      repo: Absolute repository root.
      settings: Terms settings read once for the run.
    """
    # the repository, its settings as read once for the run, and git's view of its paths
    self._repo = repo
    self._settings = settings
    self._probe = GitPathProbe(repo = repo)

  def check(self) -> bool:
    """
    Tell whether a dictionary still holds a term file whose title or file name breaks the letter-case canon.

    Guarantees:
      - The check never writes.
      - A scope that still names its old dictionary file is never counted as work.

    Notes:
      - Runs git.
      - A name-only change of a tracked file is not counted while git on this checkout is case-blind, because the
        rename could not be taken.

    Returns:
      `True` while a served scope's term file has a title line the canon would change, or a file name the canon
      would change that a run can take.
    """

    # Contract:
    # The check NEVER writes.

    # Contract:
    # A scope that still names its old dictionary file is never counted as work.

    # a term file the canon retitles is work left, and so is one it renames, unless git on this checkout can never
    # take that case-only rename of a tracked file
    blind = self._probe.is_case_blind()
    return any(
      entry.retitled or not ( blind and self._probe.is_tracked(self._rel(entry.path)) )
      for _, _, directory in self._find_all_scopes() for entry in self._find_all_recased(directory)
    )

  def run(self) -> list[dict]:
    """
    Bring every served scope's term files to the letter-case canon and move the links to the renamed ones.

    Guarantees:
      - Only the title line of a term file changes; every other byte of the file stays.
      - A term file is renamed only when its name is its title's file name, letter case ignored; any other term file
        keeps its name.
      - A link to a renamed term file is moved onto the new name and keeps showing the words it showed.
      - A scope that still names its old dictionary file is left untouched and gets no report.
      - Nothing is staged or committed.
      - Repeating the run changes nothing.

    Notes:
      - Runs git to see whether each rename registers.
      - A file whose rename git does not see is moved back to its name; its title stays cased and its links stand.

    Returns:
      One report per served scope, in configuration order: the scope, the renames as `{from, to}` stems under
      `renamed`, the files that kept their name for want of a rename git sees as `{from, to}` stems, the new stem
      being the one the file would have taken, under `kept`, the documents rewritten, the documents set aside as not
      valid UTF-8, and the documents left alone because they changed on disk during the run.

    Raises:
      CalledProcessError: If git cannot list the files.
      OSError: If a term file cannot be written or moved.
    """

    # Domain(wiki.terms):
    # # Bringing a dictionary to the letter-case canon
    # A dictionary written before the letter-case canon is brought to it once. Each term file's title line takes the
    # case of the term's language, and nothing else in the file changes. A file whose name is its title's file name,
    # letter case aside, is renamed to the cased title's file name, unless another file already holds that name, and
    # then both files stay as they are; a file named otherwise keeps its name, and a file with no title line, or one
    # that cannot be read as text, is left alone. A file the canon renames is moved through a temporary name, so the
    # file system records a change of path. Git is then asked, without staging anything, whether it sees the old path
    # deleted and the new one untracked; a path git never tracked always counts as seen. Where git does not see it,
    # which is a case-only rename of a tracked file on a checkout where git ignores letter case, the file is moved
    # back: it keeps its name, its title stays cased, and links keep pointing at its name. Such a file is reported
    # as kept, not renamed. Work is not left over a name-only change of a tracked file while git ignores letter
    # case, because git on that checkout can never take it. Every link to a renamed file in the scope's documents,
    # documents under review included, is moved onto the new name, and a link without display text keeps showing the
    # words it showed, so a reader sees the same sentence. A scope that still holds its old single-file dictionary
    # waits for its own migration first.

    # Contract:
    # Only the title line of a term file changes; every other byte of the file stays.

    # Contract:
    # A term file is renamed only when its name is its title's file name with letter case ignored; any other term
    # file keeps its name.

    # Contract:
    # A link to a renamed term file is moved onto the new name and keeps showing the words it showed.

    # Contract:
    # A scope that still names its old dictionary file is left untouched and gets no report.

    # Contract:
    # The run NEVER stages or commits anything.

    # Contract:
    # Repeating the run changes nothing.

    reports: list[dict] = []

    # each served scope's term files are recased first, then its documents follow the renamed ones
    for scope_id, cfg, directory in self._find_all_scopes():
      renamed, kept = self._apply_all(directory, self._find_all_recased(directory))
      passed = self._pass_documents(cfg, directory, renamed) if renamed else {}
      reports.append({
        KEY_SCOPE: scope_id,
        KEY_RENAMED: [ { KEY_FROM: old, KEY_TO: new } for old, new in renamed.items() ],
        KEY_KEPT: [ { KEY_FROM: old, KEY_TO: new } for old, new in kept.items() ],
        KEY_DOCUMENTS: passed.get(KEY_DOCUMENTS, []),
        KEY_UNDECODABLE: passed.get(KEY_UNDECODABLE, []),
        KEY_CHANGED_ON_DISK: passed.get(KEY_CHANGED_ON_DISK, []),
      })
    return reports

  def _find_all_scopes(self) -> list[tuple[str, dict, str]]:
    """
    List the served scopes whose dictionary is already a directory of term files.

    Returns:
      One tuple of scope id, scope settings and dictionary directory per scope, in configuration order.
    """
    return [ served for served in self._settings.find_all_served() if _KEY_LEGACY_FILE not in served[1] ]

  def _find_all_recased(self, directory: str) -> list[_Recased]:
    """
    Find the term files of a dictionary directory that the letter-case canon changes.

    Args:
      directory: Repo-relative dictionary directory.

    Returns:
      One entry per term file whose title or file name the canon changes, in file-name order.
    """
    root = self._repo / directory

    # guard: a missing directory holds no term file
    if not root.is_dir():
      return []

    # every markdown file directly in the directory with a decodable title line is judged on its own
    found: list[_Recased] = []
    for name in sorted(os.listdir(root)):
      # guard: only a visible term file directly in the directory counts
      if ( name.startswith(_HIDDEN) or not name.endswith(_term_dictionary.TERM_FILE_SUFFIX)
           or not (root / name).is_file() ):
        continue
      if ( recased := _Recased.read(root / name) ) is not None:
        found.append(recased)
    return found

  def _apply_all(self, directory: str, recased: list[_Recased]) -> tuple[dict[str, str], dict[str, str]]:
    """
    Write the cased title lines and rename the files the canon renames, where git sees the rename.

    Notes:
      - Runs git, and prints a note to stderr for each file left as it is or kept under its name.

    Args:
      directory: Repo-relative dictionary directory, for the stderr notes.
      recased: The term files to change.

    Returns:
      A pair of maps, each keyed by old stem. The first holds the new stem of each renamed term file. The second
      holds the stem each file would have taken, for the files whose rename git does not see and that kept their
      name.

    Raises:
      CalledProcessError: If git cannot list the files.
      OSError: If a term file cannot be written or moved.
    """
    renamed: dict[str, str] = {}
    kept: dict[str, str] = {}

    # each file takes its cased title, then moves to its cased name unless another file already holds that name
    for entry in recased:
      target = entry.path.with_name(entry.new_stem + _term_dictionary.TERM_FILE_SUFFIX)
      # guard: a different file already carrying the new name keeps both files as they are
      if entry.new_stem != entry.stem and target.exists() and not os.path.samefile(entry.path, target):
        print(f"terms: {directory}/{target.name} already exists, {entry.path.name} left as it is", file = sys.stderr)
        continue
      entry.path.write_bytes(entry.data)

      # a file the canon only retitles keeps its name
      if entry.new_stem == entry.stem:
        continue

      # the move goes through a temporary name, so a case-only rename reaches the file system as a change of path;
      # a rename git does not see is moved back, and the file keeps its name and its links
      _move_twice(entry.path, target)
      if self._probe.is_rename_seen(self._rel(entry.path), self._rel(target)):
        renamed[entry.stem] = entry.new_stem
        continue
      _move_twice(target, entry.path)
      kept[entry.stem] = entry.new_stem
      print(
        f"terms: git does not see {directory}/{entry.path.name} renamed to {target.name}; the name stays",
        file = sys.stderr,
      )
    return renamed, kept

  def _rel(self, path: Path) -> str:
    """
    Return a path of the repository as a repo-relative posix path.

    Args:
      path: A path inside the repository.

    Returns:
      The path relative to the repository root, with forward slashes.
    """
    return path.relative_to(self._repo).as_posix()

  def _pass_documents(self, cfg: dict, directory: str, renamed: dict[str, str]) -> dict[str, list]:
    """
    Move every link of a scope's documents to a renamed term file onto its new name.

    Args:
      cfg: Settings of the scope.
      directory: Repo-relative dictionary directory of the scope.
      renamed: The new stem of each renamed term file, by its old stem.

    Returns:
      The pass's report keys, as `pass_all_documents` returns them.
    """
    # a plan that only follows the renames: it names no word, rejects nothing and touches no old terms section
    plan = _term_links.LinkPlan(
      dictionary_dir = directory,
      terms = _term_dictionary.TermDictionary(path = self._repo / directory).read_terms(),
      link_retargets = {}, retargets = dict(renamed), word_links = {}, rejected = set(),
    )
    return pass_all_documents(
      self._repo, list_documents(self._repo, _filter_strings(cfg, _KEY_PATHS)), self._settings.build_context(cfg),
      plan_of = lambda _rel: plan,
    )


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _Recased:
  """
  One term file as the letter-case canon rewrites it.

  Attributes:
    path: The term file.
    stem: File name stem the file carries now.
    new_stem: File name stem the file carries once recased.
    data: The file's bytes with the cased title line.
    retitled: Whether the canon changes the title line.
  """

  # The term file
  path: Path
  # The file name stem the file carries now
  stem: str
  # The file name stem the file carries once recased
  new_stem: str
  # The file's bytes with the cased title line
  data: bytes
  # Whether the canon changes the title line
  retitled: bool

  @classmethod
  def read(cls, path: Path) -> _Recased | None:
    """
    Read a term file and work out what the letter-case canon makes of it.

    Notes:
      - A file that is not valid UTF-8 is treated as one without a title line.

    Args:
      path: The term file.

    Returns:
      The recased file, or `None` when it has no title line or the canon changes neither its title nor its name.

    Raises:
      OSError: If the file cannot be read.
    """
    raw = path.read_bytes()
    stem = path.name[:-len(_term_dictionary.TERM_FILE_SUFFIX)]

    # guard: a file that is not valid UTF-8 has no title line to case
    try:
      text = raw.decode(_ENCODING)
    except UnicodeDecodeError:
      return None

    # the title line ends at the first line break, a carriage return before it included
    first, newline, rest = text.partition(_NL)
    line = first.removesuffix(_CR)

    # guard: a file without a title line is left alone
    if not line.startswith(_TITLE):
      return None

    # the title is cased in place, and the name follows only when it is the title's own file name
    title = line[len(_TITLE):].strip()
    cased = _term_dictionary.compute_term_title(title)
    derived = _term_dictionary.term_file_stem(title).casefold() == stem.casefold()
    new_stem = _term_dictionary.term_file_stem(cased) if derived else stem
    new_first = first.replace(title, cased, 1)

    # guard: a file the canon changes in neither title nor name is no work
    if new_first == first and new_stem == stem:
      return None
    data = ( new_first + newline + rest ).encode(_ENCODING)
    return cls(path = path, stem = stem, new_stem = new_stem, data = data, retitled = new_first != first)



# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class SweepUnit:
  """
  One terms-curator job of a sweep.

  Attributes:
    directory: Repo-relative directory the job's documents lie in.
    files: Repo-relative documents the job names.
    dedup_key: Key the job is queued under.
  """

  # The repo-relative directory the job's documents lie in
  directory: str
  # The repo-relative documents the job names
  files: list[str]
  # The key the job is queued under
  dedup_key: str


# ----------------------------------------------------------------------------------------
class TermsSweep:
  """
  Pass of the terms curator over every document of the terms scopes.

  Attributes:
    undecodable: Repo-relative documents a listing set aside because they are not valid UTF-8.
  """

  def __init__(self,
               *,
               repo: Path,
               settings: TermsSettings | None,
               core: _dispatch.CoreDispatch | None = None) -> None:
    """
    Prepare the sweep of one repository.

    Args:
      repo: Absolute repository root.
      settings: Terms settings read once for the run, or `None` when the repository has no terms scopes.
      core: Bridge to core's job queue; required by `dispatch`, unused by the listing and `check`.
    """
    # the repository, its settings as read once for the run, and the door to core's job queue
    self._repo = repo
    self._settings = settings
    self._core = core

    # the documents a listing set aside because they are not valid UTF-8
    self.undecodable: list[str] = []

  def read_documents(self, paths: list[str], *, scope: str | None = None) -> dict[str, list[str]]:
    """
    List the documents the sweep covers, by scope.

    Guarantees:
      - A document that several scopes cover is listed once, under the first migrated scope (one without
        `legacy_file`) in configuration order that covers it; only when no migrated scope covers it does it go to the
        first unmigrated scope that does. No document is swept twice.
      - A document that is not valid UTF-8 is never listed; it is recorded in `undecodable` instead.
      - With a scope id, only that scope is listed; a document that another scope owns under that rule stays with
        that scope and is not listed under the named one.
      - A scope id that names no scope with a dictionary directory raises a `TermsVerbError`.

    Args:
      paths: Repo-relative files or directories to limit the sweep to; empty for every document.
      scope: Id of the one scope to list; `None` for every scope.

    Returns:
      Repo-relative documents by scope id, in configuration order; empty without terms scopes.

    Raises:
      TermsVerbError: If `scope` names no scope that names a dictionary directory.
    """

    # Domain(wiki.terms):
    # # Which documents the terms sweep covers
    # Every document a scope covers gets one curator pass, except those where the curator would do nothing: mirror
    # documents, folder notes, documents in managed directories, and documents excluded as term sources. A document
    # excluded only from link editing is still listed, because the curator takes terms from it. A scope that still
    # carries its old dictionary file owns no document that a migrated scope also covers: such a document belongs to
    # the migrated scope, whatever the configuration order. Among migrated scopes, and among unmigrated ones, the
    # first in configuration order takes a shared document. A document that only an unmigrated scope covers stays
    # with it. A scope that still carries its old dictionary file is listed too, but a sweep that queues jobs
    # leaves it out, because the curator has no dictionary directory to work against.
    # A document that is not valid UTF-8 is not listed and is named instead, since no curator job could read it.
    # A sweep may be limited to one named scope. It keeps the ownership above: a document that another scope owns
    # under that rule is not taken by the named one. A name that is no scope with a dictionary directory stops the
    # sweep.

    # Contract:
    # A document that several scopes cover is listed once, under the first migrated scope (one without `legacy_file`)
    # in configuration order that covers it; only when no migrated scope covers it does it go to the first unmigrated
    # scope that does. No document is swept twice.

    # Contract:
    # A document that is not valid UTF-8 is NEVER listed; it is recorded in the `undecodable` attribute instead.

    # Contract:
    # With a scope id, only that scope is listed; a document that another scope owns under that rule stays with that
    # scope and is not listed under the named one.

    # Contract:
    # A scope id that names no scope with a dictionary directory raises a `TermsVerbError`.

    served = self._settings.find_all_served() if self._settings is not None else []

    # guard: a named scope must be one that names its dictionary directory
    if scope is not None and scope not in { scope_id for scope_id, _, _ in served }:
      raise TermsVerbError(f"no terms scope with a dictionary directory is named {scope!r}")

    # each served scope claims its documents; a document a scope claimed earlier stays with that scope, also when
    # only a later scope is asked for; a migrated scope claims before one that still carries its old dictionary file,
    # which owns only what no migrated scope covers, and within each group the configuration order decides
    matcher = _scope.GlobMatcher()
    wanted = [ path.strip(_KEY_SEP) for path in paths ]
    seen: set[str] = set()
    claimed: dict[str, list[str]] = {}
    for scope_id, cfg, _ in sorted(served, key = lambda entry: _KEY_LEGACY_FILE in entry[1]):
      excluded = _filter_strings(cfg, _KEY_SOURCE_EXCLUDE)
      claimed[scope_id] = [
        rel for rel in list_documents(self._repo, _filter_strings(cfg, _KEY_PATHS))
        if rel not in seen and self._is_swept(rel, wanted) and not self._is_owned_elsewhere(rel)
        and not any(matcher.match(rel, glob) for glob in excluded)
      ]
      seen.update(claimed[scope_id])

    # the scopes are listed in configuration order, only the one asked for when a scope is named; a document that is
    # not valid UTF-8 is set aside and named, since no curator job could read it
    listed: dict[str, list[str]] = {}
    for scope_id, _, _ in served:
      if scope is None or scope_id == scope:
        listed[scope_id] = [ rel for rel in claimed[scope_id] if self._is_decodable(rel) ]
        self.undecodable.extend(rel for rel in claimed[scope_id] if rel not in listed[scope_id])
    return listed

  def _is_decodable(self, rel: str) -> bool:
    """
    Tell whether a document is valid UTF-8.

    Args:
      rel: Repo-relative path of the document.

    Returns:
      `True` when the document can be read as text; `False` when it is not valid UTF-8 or cannot be read at all.
    """
    # a document the curator could read is valid UTF-8, and one that cannot be read at all is no more use to it
    try:
      TextFile(path = self._repo / rel).read()
    except (OSError, UnicodeDecodeError):
      return False
    return True

  def build_units(self, scope_id: str, documents: list[str]) -> list[SweepUnit]:
    """
    Group documents into the jobs a sweep queues.

    Guarantees:
      - The dedup key of an unsplit directory is `terms-sweep:<scope id>:<directory>` and of a split one
        `terms-sweep:<scope id>:<directory>#<n>`, with `n` counted from 1. Inside the scope id and the directory,
        `%` is written `%25`, `:` `%3A` and `#` `%23` (the escape character first) before the key is built, so the
        key is identical for ordinary names and two different scope, directory and part combinations never share a
        key.
      - The key of an unsplit directory stays the same from run to run, so a repeated sweep collapses into jobs
        still queued; the parts of a split directory are cut again from the current document sizes, so a growing
        document can move between parts and be queued a second time.

    Args:
      scope_id: Id of the scope whose documents are grouped.
      documents: Repo-relative documents to group.

    Returns:
      One unit per directory, or several when the directory's documents are too heavy for one job.
    """

    # Domain(wiki.terms):
    # # The unit of work of the terms sweep
    # The unit of work is one directory without its subdirectories. A directory whose documents together exceed
    # 150 000 bytes is split into several jobs, the documents filling each part in order, and each part's number
    # joins the key the job is queued under. The key names the scope as well as the directory, so two scopes whose
    # documents share a directory get two jobs and neither swallows the other. The scope's name and the directory
    # are written into the key with the characters that separate the key's parts (the colon and the hash mark)
    # and the escape mark itself (the percent sign) escaped, so a scope or directory whose name holds them can
    # never share a key with another scope, directory or part; an ordinary name appears in the key as it is.
    # Parts are cut again from the documents' current sizes on every run, so a document that grows while earlier
    # parts are still queued can land in another part and be queued a second time; this is an accepted limitation.

    # Contract:
    # The dedup key of an unsplit directory is `terms-sweep:<scope id>:<directory>` and of a split one
    # `terms-sweep:<scope id>:<directory>#<n>`, with `n` counted from 1. Inside the scope id and the directory,
    # `%` is written `%25`, `:` `%3A` and `#` `%23` (the escape character first) before the key is built, so the
    # key is identical for ordinary names and two different scope, directory and part combinations never share a key.
    # The key of an unsplit directory stays the same from run to run, so a repeated sweep collapses into jobs still
    # queued; the parts of a split directory are cut again from the current document sizes, so a growing document
    # can move between parts and be queued a second time.

    by_directory: dict[str, list[str]] = {}

    # one directory, without its subdirectories, is the unit of work
    for rel in sorted(documents):
      by_directory.setdefault(PurePosixPath(rel).parent.as_posix(), []).append(rel)

    # a directory heavier than one job carries is split, in order, and each part's number joins its key; the scope
    # joins it too, so two scopes sharing a directory never collapse into one job
    units: list[SweepUnit] = []
    for directory, files in by_directory.items():
      parts = self._split(files)
      for number, part in enumerate(parts, start = 1):
        suffix = f"{_PART_SEP}{number}" if len(parts) > 1 else ""
        units.append(SweepUnit(
          directory = directory, files = part,
          dedup_key = f"{_SWEEP_KEY_PREFIX}{_escape_key_part(scope_id)}{_SCOPE_SEP}{_escape_key_part(directory)}"
                      f"{suffix}",
        ))
    return units

  def check(self, *, migrated: bool = False) -> bool:
    """
    Tell whether the sweep still has work.

    Guarantees:
      - The check never writes.
      - With `migrated` true, the scopes that still carry their old dictionary file are left out of the answer;
        without it they count like any other scope.

    Args:
      migrated: Whether to leave out the scopes that still carry their old dictionary file.

    Returns:
      `True` when a scope has documents to sweep and no marker of a finished sweep step.
    """

    # Contract:
    # The check NEVER writes; it only answers whether a scope has documents and no marker.

    # Contract:
    # With `migrated` true, the scopes that still carry their old dictionary file are left out of the answer;
    # without it they count like any other scope.

    # a scope with documents to sweep and no marker of a finished sweep step has work left; an unmigrated one only
    # when it is asked for
    skipped = set(self.find_all_unmigrated()) if migrated else set()
    return any(
      files and scope_id not in skipped and not self._mark_path(scope_id).is_file()
      for scope_id, files in self.read_documents([]).items()
    )

  def find_all_unmigrated(self) -> list[str]:
    """
    List the scopes that still carry their old dictionary file.

    Returns:
      Ids of the served scopes whose settings still name their old dictionary file, in configuration order.
    """
    # a served scope still naming its old file has no dictionary directory content yet
    return [
      scope_id for scope_id, cfg, _ in ( self._settings.find_all_served() if self._settings is not None else [] )
      if _KEY_LEGACY_FILE in cfg
    ]

  def dispatch(self,
               paths: list[str],
               *,
               mark: bool,
               scope: str | None = None,
               include_review: bool = False) -> dict:
    """
    Queue the sweep jobs in the checkout the daemon gate names for this machine.

    Guarantees:
      - A non-null `deferred_to` in the report always means nothing was queued by this call.
      - A marker is written only after every job was queued or already active, or after the queueing was
        deferred; a failure never writes one.
      - A marker that already exists is never rewritten.
      - A marking sweep without a scope leaves out every scope whose marker already exists: such a scope is neither
        listed, queued nor counted, and its marker is untouched.
      - A sweep that names a scope, or that does not mark, queues every migrated scope it covers whether or not a
        marker exists.
      - A scope that still carries its old dictionary file is never queued and never marked, with or without `mark`
        and with or without paths; its id is listed in the report under `unmigrated`, in configuration order, and
        the list is empty when there is none. With a named scope only that scope is considered.
      - Naming a scope that still carries its old dictionary file raises a `TermsVerbError` before anything is
        queued or marked.
      - A failed daemon gate check, an unreadable daemon gate and a failed queueing each raise a `TermsVerbError`
        that carries the report counted so far.
      - Every queued job opens documents under review to the curator only when `include_review` is true; by default
        no queued job edits a document under review.

    Args:
      paths: Repo-relative files or directories to limit the sweep to; empty for every document.
      mark: Whether to write the sweep marker of each scope once the queueing is settled.
      scope: Id of the one scope to sweep; `None` for every scope.
      include_review: Whether the queued jobs may edit documents under an open review round; false by default.

    Returns:
      The report with the counts of directories, queued jobs and jobs already active, the daemon's checkout when
      the queueing was deferred to it, and the scopes left out because they still carry their old dictionary file.

    Raises:
      TermsVerbError: If core is unreachable, `scope` names no scope that names a dictionary directory, `scope`
        names a scope that still carries its old dictionary file, the daemon gate cannot be read, or a job cannot
        be queued; the error carries the report counted so far for an unreadable gate or a failed queueing, and a
        zero-count report listing the scope for an unmigrated one.
    """

    # Domain(wiki.terms):
    # # Where the sweep jobs are queued
    # Jobs are queued only in the checkout that the daemon gate names for this machine, or anywhere when the gate
    # is unset, in which case the only executor is a manual drain in this checkout. In any other checkout nothing is
    # queued and the answer names the daemon's checkout, by machine and path. A gate that cannot be read is a
    # failure, not a reason to queue anyway. A job still active under the same key is not queued again. Finished
    # jobs under the key are released first, because nobody collects the result of a sweep job.
    # A sweep that marks and names no scope takes only the scopes that have no marker yet: a scope whose sweep step
    # is already settled is not swept again. A sweep that names a scope takes it whether or not its marker exists,
    # and a sweep that does not mark takes every scope, or the named one, markers or not.
    # A scope whose settings still name its old single dictionary file, not migrated yet, is never queued by any of
    # these sweeps: the curator would only answer that there is nothing to do. The answer names such a scope instead,
    # so the operator sees what was left out. Naming such a scope explicitly stops the sweep, pointing at the
    # migration. Once the operator has migrated the scope by hand, the sweep is run by hand as well.

    # Contract:
    # A non-null `deferred_to` always means nothing was queued by this call.

    # Contract:
    # A marker is written only after every job was queued or already active, or after the queueing was deferred;
    # a failure NEVER writes one.

    # Contract:
    # A marker that already exists is never rewritten.

    # Contract:
    # A marking sweep without a scope leaves out every scope whose marker already exists: such a scope is neither
    # listed, queued nor counted, and its marker is untouched.

    # Contract:
    # A sweep that names a scope, or that does not mark, queues every migrated scope it covers whether or not a
    # marker exists.

    # Contract:
    # A scope that still carries its old dictionary file is NEVER queued and NEVER marked, with or without `mark`
    # and with or without paths; its id is listed in the report under `unmigrated`, in configuration order, and the
    # list is empty when there is none. With a named scope only that scope is considered.

    # Contract:
    # Naming a scope that still carries its old dictionary file raises a `TermsVerbError` before anything is queued
    # or marked.

    # Contract:
    # A failed daemon gate check, an unreadable daemon gate and a failed queueing each raise a `TermsVerbError`
    # that carries the report counted so far.

    # Contract:
    # Every queued job opens documents under review to the curator only when `include_review` is true; by default
    # no queued job edits a document under review.

    # guard: queueing needs core
    if self._core is None:
      raise TermsVerbError("core CLI is unreachable")

    # the scopes in reach of this sweep that still carry their old dictionary file
    unmigrated = [ scope_id for scope_id in self.find_all_unmigrated() if scope is None or scope_id == scope ]

    # guard: a named scope still on its old dictionary file has no dictionary for the curator to work against
    if scope is not None and unmigrated:
      raise TermsVerbError(
        f"terms scope {scope!r} is not migrated yet: its dictionary is still its old file; run terms-migrate first",
        report = {
          KEY_DIRECTORIES: 0, KEY_QUEUED: 0, KEY_ALREADY_QUEUED: 0, KEY_DEFERRED_TO: None,
          KEY_UNMIGRATED: unmigrated,
        },
      )

    # an unmigrated scope is never swept, and a marking sweep over every scope takes only the scopes whose sweep has
    # not been settled yet
    listed = {
      scope_id: files for scope_id, files in self.read_documents(paths, scope = scope).items()
      if scope_id not in unmigrated and not ( mark and scope is None and self._mark_path(scope_id).is_file() )
    }

    # the jobs the listing makes, and the report counting them as the queueing goes
    units = [ unit for scope_id, files in listed.items() for unit in self.build_units(scope_id, files) ]
    report: dict = {
      KEY_DIRECTORIES: len({ unit.directory for unit in units }), KEY_QUEUED: 0, KEY_ALREADY_QUEUED: 0,
      KEY_DEFERRED_TO: None, KEY_UNMIGRATED: unmigrated,
    }

    # the daemon gate decides whether this checkout's queue reaches the daemon at all
    try:
      verdict = self._core.query_daemon_run_here(self._repo)
    except ( RuntimeError, ValueError, OSError ) as error:
      raise TermsVerbError(f"daemon gate check failed: {error}", report = report) from error

    # the daemon runs in another checkout: its queue is the one the jobs must reach, so the sweep defers to it
    if verdict.get(_RUN_HERE_STATE) in _STATES_DEFER:
      report[KEY_DEFERRED_TO] = { KEY_HOST: verdict.get(KEY_HOST), KEY_PATH: verdict.get(KEY_PATH) }
      self._mark_all(listed, mark = mark)
      return report

    # guard: a gate that cannot be read leaves no checkout to queue in
    if verdict.get(_RUN_HERE_STATE) not in _STATES_QUEUE:
      raise TermsVerbError(f"daemon gate check answered {verdict.get(_RUN_HERE_STATE)!r}", report = report)

    # one job per unit; a job already active under the key is counted, never queued twice
    for unit in units:
      try:
        answer = self._core.dispatch_terms_curator(
          repo = self._repo, files = unit.files, dedup_key = unit.dedup_key, include_review = include_review,
        )
      except ( RuntimeError, ValueError, OSError ) as error:
        raise TermsVerbError(f"queueing {unit.dedup_key} failed: {error}", report = report) from error
      counter = KEY_ALREADY_QUEUED if answer.get(_KEY_STATUS) == _STATUS_ALREADY_QUEUED else KEY_QUEUED
      report[counter] += 1

    # the marker is written only once every job is queued
    self._mark_all(listed, mark = mark)
    return report

  def _is_owned_elsewhere(self, rel: str) -> bool:
    """
    Tell whether a document belongs to another owner than the curator.

    Args:
      rel: Repo-relative document.

    Returns:
      `True` for a mirror document, a document inside a managed directory and a folder note.
    """
    # guard: without settings nothing is listed, so nothing is owned elsewhere either
    if self._settings is None:
      return False

    # a mirror document, a document inside a managed directory, and a folder note are never the curator's
    pure = PurePosixPath(rel)
    return (
      _terms.is_under_mirror(rel, self._settings.mirrors)
      or any(rel.startswith(f"{base}/") for base in self._settings.managed if base)
      or pure.stem == pure.parent.name
    )

  def _is_swept(self, rel: str, wanted: list[str]) -> bool:
    """
    Tell whether a document falls under the paths a sweep was limited to.

    Args:
      rel: Repo-relative document.
      wanted: Repo-relative files or directories; empty for every document.

    Returns:
      `True` when no path limits the sweep, or the document equals or lies below one.
    """
    # without paths every document is swept; with them, a document equal to one or below one
    return not wanted or any(rel == path or rel.startswith(f"{path}/") for path in wanted)

  def _split(self, files: list[str]) -> list[list[str]]:
    """
    Split the documents of one directory into parts a single job can carry.

    Args:
      files: Repo-relative documents of one directory, in order.

    Returns:
      The parts, each in the order of `files`; empty for no documents.
    """
    parts: list[list[str]] = []
    weight = 0

    # documents fill a part in order until the next one would carry it over the limit
    # limit: parts are re-cut from current sizes on every run, so a document that grows while earlier parts are still
    # queued can move to another part number and be queued twice; key parts by their documents if repeats matter
    for rel in files:
      size = self._read_size(rel)
      if not parts or ( parts[-1] and weight + size > _SWEEP_JOB_MAX_BYTES ):
        parts.append([])
        weight = 0
      parts[-1].append(rel)
      weight += size
    return parts

  def _read_size(self, rel: str) -> int:
    """
    Measure a document for the job size limit.

    Args:
      rel: Repo-relative document.

    Returns:
      Size in bytes; zero when the document cannot be measured.
    """
    # a document that cannot be measured weighs nothing rather than failing the sweep
    try:
      return (self._repo / rel).stat().st_size
    except OSError:
      return 0

  def _mark_path(self, scope_id: str) -> Path:
    """
    Locate the sweep marker of one scope.

    Args:
      scope_id: Id of the scope.

    Returns:
      Absolute path of the marker file.
    """
    # the tracked marker of one scope's finished sweep step
    return self._repo / _STATE_DIR / _MARK_NAME.format(scope = scope_id)

  def _mark_all(self, listed: dict[str, list[str]], *, mark: bool) -> None:
    """
    Write the sweep marker of every listed scope that has none, when asked.

    Args:
      listed: Documents by scope id, as the listing answers.
      mark: Whether markers are written at all.
    """

    # Domain(wiki.terms):
    # # The sweep marker
    # A scope's sweep marker records that its sweep step is finished. It is written only when asked, and only once
    # every job was queued, or the queueing was deferred to the daemon's checkout, or the scope has no documents.
    # A failed queueing never writes it. A marker once present is never rewritten, not even by a sweep that names
    # that scope. A marker is never written for a scope that is not migrated yet: it would stop the real sweep once
    # the operator migrates the scope by hand. The sweep counts as pending while a scope has documents and no marker,
    # and the pending-check can be asked to leave out the scopes not migrated yet, so the migration step does not stay
    # pending on them. A sweep over every scope that marks leaves out the scopes whose marker is already there.

    # only a sweep asked to mark writes the marker
    if not mark:
      return

    # each scope's marker is written once and never rewritten
    for scope_id in listed:
      path = self._mark_path(scope_id)
      if path.is_file():
        continue
      path.parent.mkdir(parents = True, exist_ok = True)
      path.write_text(
        json.dumps({ _MARK_SWEPT_AT: datetime.now(UTC).strftime(_UTC_FORMAT) }) + _NL, encoding = _ENCODING,
      )


# ----------------------------------------------------------------------------------------
def pass_all_documents(repo: Path,
                       documents: list[str],
                       context: _term_links.SyncContext,
                       *,
                       plan_of: Callable[[str], _term_links.LinkPlan]) -> dict[str, list]:
  """
  Bring the term links and the old terms text of documents in line with the link plan each one receives.

  Notes:
    - Reads each document once and rewrites in place the ones whose text changes.
    - A document changed on disk between its reading and its write is not written.
    - A document that cannot be read at all is set aside and named like one that is not valid UTF-8, and the pass
      goes on with the next document.

  Args:
    repo: Absolute repository root.
    documents: Repo-relative documents to pass, documents under review included.
    context: Settings-derived facts the pass consults.
    plan_of: The link plan a document receives, by its repo-relative path.

  Returns:
    The report keys of the pass. `documents` lists the repo-relative documents that were rewritten, `undecodable` the
    ones set aside because they are not valid UTF-8, `changed_on_disk` the ones that changed on disk between being
    read and being written and so were not written, and `unmoved` one `{file, links}` entry per document holding
    links to headings of an old dictionary file that no link edit reaches.
  """
  # every document, documents under review included; refused ones stay as they are, and one that is not valid UTF-8
  # is set aside and named instead of stopping the run
  written: list[str] = []
  undecodable: list[str] = []
  changed: list[str] = []
  unmoved: list[dict] = []
  for rel in documents:
    # the document is read once; those bytes are rendered, searched for links it cannot move and compared before
    # the write
    # a document that cannot be read is set aside and named like one that is not valid UTF-8, and the pass
    # goes on to the next
    try:
      data = (repo / rel).read_bytes()
    except OSError as error:
      print(f"terms: {rel} could not be read, set aside: {error}", file = sys.stderr)
      undecodable.append(rel)
      continue
    document_plan = plan_of(rel)
    try:
      result = _term_links.render_document(
        repo, rel, document_plan, context, allow_review = True, data = data,
      )
      links = (
        _term_links.find_all_unmoved_anchor_links(TextFile(path = repo / rel).decode(data), document_plan)
        if result[_term_links.KEY_STATUS] != _term_links.STATUS_REFUSED else []
      )
    except UnicodeDecodeError:
      undecodable.append(rel)
      continue

    # a link to a heading of the old file where no edit reaches stays as written, and is named
    if links:
      unmoved.append({ KEY_FILE: rel, KEY_LINKS: links })

    # guard: nothing to write
    if result[_term_links.KEY_STATUS] != _term_links.STATUS_APPLIED:
      continue

    # limit: an edit landing between this check and the write is lost, compare and write through one handle then
    # guard: a document that changed on disk since it was read is someone's edit, left alone and named
    if (repo / rel).read_bytes() != data:
      changed.append(rel)
      continue

    # the document takes its new text and is counted as rewritten
    _term_links.write_document(repo, rel, result[_term_links.KEY_TEXT])
    written.append(rel)

  # what the pass wrote, set aside, left alone and could not move
  return {
    KEY_DOCUMENTS: written, KEY_UNDECODABLE: undecodable, KEY_CHANGED_ON_DISK: changed, KEY_UNMOVED: unmoved,
  }


def list_documents(repo: Path, globs: list[str]) -> list[str]:
  """
  List the tracked documents that match globs and exist in the working tree.

  Guarantees:
    - Each tracked document is listed once, in git's order, and a path missing from the working tree is never
      listed.

  Notes:
    - A path whose name is not valid UTF-8 never fails the listing; it is reported on stderr and left out of the
      result, so it never reaches a write or a print, and every other path is returned as usual.

  Args:
    repo: Absolute repository root.
    globs: Repo-relative glob patterns.

  Returns:
    Repo-relative documents.

  Raises:
    CalledProcessError: If git cannot list the files.
  """

  # Contract:
  # Each tracked document is listed once, in git's order, and a path missing from the working tree is never listed.

  found: list[str] = []

  # each glob is listed by git; -z keeps non-ASCII paths unquoted, and the listing is taken as bytes and decoded
  # without loss, so a name that is not UTF-8 cannot fail it
  for glob in globs:
    raw = os.fsdecode(subprocess.check_output(
      [ "git", "ls-files", "-z", "--", f":(glob){glob}" ], cwd = str(repo),
    ))
    for rel in raw.split(_NUL):
      # guard: the trailing separator leaves an empty name
      if not rel:
        continue

      # a name that is not UTF-8 cannot be written or printed; it is reported and left out
      try:
        rel.encode(_ENCODING)
      except UnicodeEncodeError:
        print(f"terms: skipped a document whose name is not UTF-8: {rel!r}", file = sys.stderr)
        continue
      found.append(rel)

  # each document once, in git's order; a tracked path deleted from the working tree is no document
  return [ rel for rel in dict.fromkeys(found) if (repo / rel).is_file() ]


def seed_link_exclude(repo: Path, path: str, glob: str, core: _dispatch.CoreDispatch) -> str:
  """
  Seed an exclusion from link editing on the scope that covers a document.

  Guarantees:
    - An existing `link_exclude` of a scope is never changed; the seed is written only when the scope has none.

  Args:
    repo: Absolute repository root.
    path: Document the exclusion is for, repo-relative or absolute inside the repository.
    glob: Glob to exclude from link editing.
    core: Bridge to core's settings writes.

  Returns:
    `seeded` when the exclusion was written, `kept` when the scope already has one, `no-scope` when no scope
    covers the document.
  """

  # Domain(wiki.terms):
  # # Seeding an exclusion from link editing
  # A neighbouring plugin may seed an exclusion from link editing for a document it owns. The exclusion lands on
  # the scope whose paths cover the document, found by paths alone, whatever else the scope carries and also when
  # the scope has not been migrated yet. The operator's existing exclusions are never changed. The seed lands in
  # the settings layer that defines the scope.

  # Contract:
  # An existing `link_exclude` of a scope is NEVER changed; the seed is written only when the scope has none.

  terms = _axes.read_settings(repo, _SECTION_TERMS, layer = _LAYER_MERGED)
  scopes = terms.get(_KEY_SCOPES) if isinstance(terms, dict) else None
  rel = _to_repo_relative(repo, path)

  # the first scope whose paths cover the document, whatever its other keys say
  matcher = _scope.GlobMatcher()
  found = next(
    (
      ( scope_id, cfg ) for scope_id, cfg in ( scopes.items() if isinstance(scopes, dict) else [] )
      if isinstance(cfg, dict) and any(matcher.match(rel, glob_) for glob_ in _filter_strings(cfg, _KEY_PATHS))
    ),
    None,
  )

  # guard: no scope covers the document
  if found is None:
    return SEED_NO_SCOPE
  scope_id, cfg = found

  # guard: the operator's own exclusions stand as they are
  if _KEY_LINK_EXCLUDE in cfg:
    return SEED_KEPT

  # the exclusion lands in the layer that defines the scope: the tracked file, or the overlay when only it does
  tracked = _axes.read_settings(repo, _SECTION_TERMS, layer = _LAYER_TRACKED)
  tracked_scopes = tracked.get(_KEY_SCOPES) if isinstance(tracked, dict) else None
  layer = _LAYER_TRACKED if isinstance(tracked_scopes, dict) and scope_id in tracked_scopes else _LAYER_LOCAL
  core.save_setting(
    repo = repo, section = _SECTION_TERMS, key = _KEY_SEP.join(( _KEY_SCOPES, scope_id, _KEY_LINK_EXCLUDE )),
    value = [ glob ], layer = layer,
  )
  return SEED_SEEDED


def _escape_key_part(part: str) -> str:
  """
  Escape a scope id or a directory for a sweep job key.

  Args:
    part: The scope id or the repo-relative directory.

  Returns:
    The text with the escape character and the key's separators escaped; unchanged when it holds none of them.
  """
  # the escape character first, so an escape written by an earlier replacement is never escaped again
  for char, escape in _KEY_ESCAPES:
    part = part.replace(char, escape)
  return part


def _to_repo_relative(repo: Path, path: str) -> str:
  """
  Express a path relative to the repository where it lies inside it.

  Args:
    repo: Absolute repository root.
    path: Path as the caller wrote it.

  Returns:
    The repo-relative path in POSIX form, or the path as written when it lies outside the repository.
  """
  # an absolute path inside the repository becomes repo-relative; anything else is taken as written
  candidate = Path(path)
  if not candidate.is_absolute():
    return PurePosixPath(path).as_posix()
  try:
    return candidate.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return candidate.as_posix()


def _filter_strings(cfg: dict, key: str) -> list[str]:
  """
  Filter the string items out of a list in scope settings.

  Args:
    cfg: Settings of one scope.
    key: Name of the setting.

  Returns:
    The string items of the setting; empty when it is missing or not a list.
  """
  value = cfg.get(key)

  # guard: a missing or malformed list holds nothing
  if not isinstance(value, list):
    return []
  return [ item for item in value if isinstance(item, str) ]
