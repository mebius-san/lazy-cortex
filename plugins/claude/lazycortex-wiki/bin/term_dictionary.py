from __future__ import annotations

import os
import posixpath
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final

  from collections.abc import Set as AbstractSet


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import axes as _axes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import wiki_job_response as _job_response  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import term_link_syntax as _term_link_syntax  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Settings section and keys a terms scope is configured under.
_SECTION_TERMS = "terms"
_KEY_SCOPES = "scopes"
_KEY_PATHS = "paths"
_KEY_DIR = "dir"
_KEY_LEGACY_FILE = "legacy_file"
_KEY_SOURCE_EXCLUDE = "source_exclude"
_KEY_LINK_EXCLUDE = "link_exclude"

# Settings layer a scope is resolved from: the tracked file with the local overlay merged in.
_LAYER_MERGED: Final = "merged"

# Operation keys of the terms protocol's result format.
_OP = "op"
_OP_ADD = "add"
_OP_EXTEND = "extend"
_OP_RENAME = "rename"
_OP_SPLIT = "split"
_OP_RELINK = "relink"
_OP_RETARGET = "retarget"
_OP_REJECT = "reject"
_OP_TERM = "term"
_OP_FROM = "from"
_OP_TARGET = "target"
_OP_FILES = "files"
_OP_DEFINITION = "definition"
_OP_SIBLING = "sibling"
_OP_SIBLING_DEFINITION = "sibling_definition"
_OP_SKIP = "skip"

# Keys of one refused operation as the batch's change reports it: its position in the batch, the operation as sent,
# and why it was refused.
REFUSED_INDEX: Final = "index"
REFUSED_OPERATION: Final = "operation"
REFUSED_REASON: Final = "reason"

# Characters that break a line; a fragment of one line carries none of them.
_LINE_BREAKS = "\r\n"

# Required string keys and required list keys of every operation the batch accepts.
_REQUIRED_KEYS: Final = {
  _OP_ADD:      ( ( _OP_TERM, _OP_DEFINITION ), () ),
  _OP_EXTEND:   ( ( _OP_TERM, _OP_DEFINITION ), () ),
  _OP_RENAME:   ( ( _OP_TERM, _OP_FROM, _OP_DEFINITION ), () ),
  _OP_SPLIT:    ( ( _OP_TERM, _OP_DEFINITION, _OP_SIBLING, _OP_SIBLING_DEFINITION ), () ),
  _OP_RELINK:   ( ( _OP_TERM, _OP_FROM ), ( _OP_FILES, ) ),
  _OP_RETARGET: ( ( _OP_TERM, _OP_TARGET ), ( _OP_FILES, ) ),
  _OP_REJECT:   ( ( _OP_TERM, ), () ),
}

# Heading prefix of the line that carries a term in its file.
_TITLE = "# "

# The most physical lines a term definition may span in the file.
_DEFINITION_MAX_LINES = 3

# Line separator of a term file: the title line ends at the first one.
_NL = "\n"

# Extension of a term file in the dictionary directory.
TERM_FILE_SUFFIX: Final = ".md"

# A character no file name on Windows or Android, or no Obsidian wikilink target, may carry, together with the
# whitespace around it; non-whitespace control characters are forbidden in Windows file names too.
_FORBIDDEN_RUN = re.compile(r"\s*[/\\:*?\"<>|#^\[\]\x00-\x08\x0e-\x1b]\s*")
_WHITESPACE_RUN = re.compile(r"\s+")
# Characters cut from both edges of a stem: a leading dot hides the file from Obsidian, Windows drops trailing
# dots and spaces, and a hyphen at an edge is a leftover of a replaced character.
_EDGE_CHARS = ". -"
_HYPHEN = "-"
_SPACE = " "
# Windows device names, matched without letter case, and the suffix that moves a stem off them.
_WINDOWS_DEVICES = frozenset(
  { "con", "prn", "aux", "nul", *( f"com{n}" for n in range(1, 10) ), *( f"lpt{n}" for n in range(1, 10) ) },
)
_DEVICE_SUFFIX = "-term"
_DOT = "."
# Unicode normal form a term is brought to before its file name is derived: one spelling per letter.
_NORMAL_FORM: Final = "NFC"



# ----------------------------------------------------------------------------------------
def term_file_stem(term: str) -> str:
  """
  Derive the file name stem under which a term's file lives in the dictionary directory.

  The stem has no `TERM_FILE_SUFFIX`. It is valid as a file name on Windows, Android, macOS and Linux and as an
  Obsidian wikilink target, never starts with a dot, keeps an inner dot, and is never a Windows device name.

  Guarantees:
    - Applying the function to its own result returns that result unchanged.

  Notes:
    - A term made only of forbidden and edge characters yields an empty stem.

  Args:
    term: Term of a terms dictionary.

  Returns:
    The file name stem of the term, without the file suffix.
  """

  # Contract:
  # Applying the function to its own result returns that result unchanged, so a writer or a link target fed
  # a stem instead of a term still arrives at the same file name.

  # Domain(wiki.terms):
  # # How a term names its file
  # A terms dictionary is a directory with one file per term. The file name comes from the term by one rule, so
  # every writer and every link target arrive at the same name.
  # The term is first brought to its composed Unicode form, so a letter written decomposed names the same file as
  # the composed one.
  # A character that a file name cannot carry on Windows and Android (`/ \ : * ? " < > |` and the non-whitespace
  # control characters) or that breaks an Obsidian wikilink target (`# ^ [ ] |`) becomes a hyphen. Whitespace next
  # to such a character is dropped with it: `Lazy-Watch: skip` becomes `Lazy-Watch-skip`.
  # Whitespace runs shrink to one space. Dots, hyphens and spaces are cut from both edges of the name: Obsidian does
  # not index a file whose name starts with a dot, Windows drops trailing dots and spaces, and a hyphen at an edge is
  # only a leftover of a replaced character: `.logs/commits.jsonl` becomes `logs-commits.jsonl`.
  # A dot inside the name stays: Obsidian keeps it and does not take it for an extension.
  # Windows reads the part before the first dot as a device name (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to LPT9, in
  # any letter case). Such a part takes the suffix `-term`, so `CON` becomes `CON-term`.
  # The rule is stable: applying it to its own result changes nothing.

  # one spelling per letter, so a decomposed and a composed form name the same file
  stem = unicodedata.normalize(_NORMAL_FORM, term)

  # each forbidden character becomes a hyphen and takes the whitespace around it along
  stem = _FORBIDDEN_RUN.sub(_HYPHEN, stem)

  # whitespace runs shrink to one space, then dots, hyphens and spaces leave both edges
  stem = _WHITESPACE_RUN.sub(_SPACE, stem).strip(_EDGE_CHARS)

  # Windows reads the part before the first dot as the device name, so that part takes the suffix
  head, dot, tail = stem.partition(_DOT)

  # a stem whose leading part is no device name is final as it stands
  if head.rstrip(_SPACE).casefold() not in _WINDOWS_DEVICES:
    return stem

  # the device name moves off itself while the rest of the stem stays
  return f"{head}{_DEVICE_SUFFIX}{dot}{tail}"


def parse_target_stem(target: str, known: AbstractSet[str]) -> str:
  """
  Return the stem that a link target, as written after the dictionary directory, names.

  Args:
    target: The target after the dictionary directory and its slash, heading anchor excluded.
    known: The casefolded stems of the term files the dictionary holds.

  Returns:
    The target's stem. For a target ending in `TERM_FILE_SUFFIX` in any letter case, the stem without that ending
    wins whenever a term file carries it; the whole target's stem wins only when a term file carries that and none
    carries the stem without the ending; a target naming neither is read without the ending.
  """

  # Domain(wiki.terms):
  # # Which term a link names
  # A link's target names a term file by the file-name rule applied to the target as written; the heading anchor and
  # the link text take no part in it. A target ending in the term-file extension `.md`, letter case ignored, is
  # resolved the way Obsidian resolves it: the exact file first. `[[dir/notes.md]]` names the file `dir/notes.md`,
  # the term whose file name is `notes`, whenever that file exists. Only when it does not exist, and a term file
  # whose name is the whole target, ending included, does exist (`notes.md.md`, the term titled `notes.md`), does
  # the whole target name that term. A target naming neither is read without the ending. A history lookup has no
  # dictionary at hand, so it always drops the ending.

  exact = term_file_stem(target)

  # a target written without the suffix names its stem as it stands
  if not target.casefold().endswith(TERM_FILE_SUFFIX):
    return exact

  # the file the target names as written wins, as Obsidian resolves it; only when that file is missing does a term
  # file carrying the whole target take the link, and a target naming neither drops the suffix
  stripped = term_file_stem(target[:-len(TERM_FILE_SUFFIX)])
  return exact if exact.casefold() in known and stripped.casefold() not in known else stripped


def render_term_file(term: str, definition: str) -> str:
  """
  Render the text of a term file.

  Args:
    term: The term as the title line spells it.
    definition: The term's definition.

  Returns:
    The title line, a blank line and the stripped definition, ending in one line break.
  """
  return f"{_TITLE}{term}{_NL}{_NL}{definition.strip()}{_NL}"



# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class TermsScope:
  """
  Terms scope that a set of documents resolved to.

  Attributes:
    scope_id: Identifier of the scope the documents resolved to.
    dictionary: Repo-relative path of the scope's dictionary directory.
    sources: Requested documents that remain term sources once the scope's exclusions are applied.
    paths: Globs of the documents the scope serves.
    link_exclude: Globs of the served documents whose text is never edited.
  """

  # The scope id the documents resolved to
  scope_id: str
  # The repo-relative dictionary directory of the scope
  dictionary: str
  # The requested documents that remain term sources once the scope's exclusions are applied
  sources: list[str]
  # The globs of the documents the scope serves
  paths: list[str]
  # The globs of the served documents whose text is never edited
  link_exclude: list[str]


# ----------------------------------------------------------------------------------------
def resolve_terms_scope(repo: Path, files: list[str]) -> TermsScope | None:
  """
  Resolve the terms scope that serves the given documents.

  Guarantees:
    - The first configured scope, in configuration order, whose paths cover any requested document wins.
    - When the winning scope's source exclusions leave no document, the result is `None` and later scopes are never
      tried.
    - A path inside the dictionary directory of any scope is never a source.
    - A scope without a dictionary directory, or one still carrying its old single file, never wins.

  Args:
    repo: Repository root whose merged settings declare the terms scopes.
    files: Repo-relative paths of the documents to resolve.

  Returns:
    The winning scope with its term sources, or `None`.
  """
  terms = _axes.read_settings(repo, _SECTION_TERMS, layer = _LAYER_MERGED)
  scopes = terms.get(_KEY_SCOPES) if isinstance(terms, dict) else None

  # guard: no terms scopes configured, or no documents requested — nothing belongs to a dictionary
  if not isinstance(scopes, dict) or not files:
    return None

  # Contract:
  # The first configured scope, in configuration order, whose paths cover any requested document wins.
  # When the winning scope's source exclusions leave no document, the result is None
  # and later scopes are never tried.

  # Contract:
  # A path inside the dictionary directory of any scope is never a source.
  # A scope without a dictionary directory, or one still carrying its old single file, never wins.

  # Domain(wiki.terms):
  # # Which scope serves a document
  # A scope serves the documents its paths cover, and the first scope that covers any requested document is the one
  # that serves them. A term file is never a document of any scope: the dictionary directory is the curator's own
  # ground, so no scope's paths can make a term file a source of terms or a target of link edits.
  # A scope without a dictionary directory serves nothing. Neither does a scope that still names its old single
  # dictionary file: between the settings upgrade and the dictionary migration the scope rests, and the curator's job
  # answers that there is nothing to do.

  # a term file of any scope is never a document, whatever the globs say
  dirs = _axes.scope_dictionary_dirs(scopes)
  requested = [ rel for rel in files if not any(rel.startswith(f"{base}/") for base in dirs) ]

  # the first serviceable scope in key order whose globs match any requested document wins
  matcher = _scope.GlobMatcher()
  for scope_id, cfg in scopes.items():
    # guard: a malformed scope, a scope without a dictionary directory, or a scope still on its old single file
    # serves nothing
    if not isinstance(cfg, dict) or not _dir_of(cfg) or _KEY_LEGACY_FILE in cfg:
      continue

    # the requested documents this scope's globs serve
    matched = [ rel for rel in requested if _is_matched(matcher, rel, cfg.get(_KEY_PATHS)) ]

    # a scope that serves none of the documents cannot win; the search moves on to the next one
    if not matched:
      continue

    # documents the scope serves but does not take terminology from drop out
    sources = [ rel for rel in matched if not _is_matched(matcher, rel, cfg.get(_KEY_SOURCE_EXCLUDE)) ]

    # guard: nothing survives the exclusions
    if not sources:
      return None

    # the winning scope with the documents that source its terms
    return TermsScope(
      scope_id = scope_id, dictionary = _dir_of(cfg), sources = sources,
      paths = _filter_strings(cfg.get(_KEY_PATHS)), link_exclude = _filter_strings(cfg.get(_KEY_LINK_EXCLUDE)),
    )

  # no scope claims any of the documents
  return None


def _dir_of(cfg: dict) -> str:
  """
  Return the dictionary directory a scope configures.

  Args:
    cfg: One scope's configuration.

  Returns:
    The repo-relative directory without a trailing slash, or an empty string when the scope names none.
  """
  value = cfg.get(_KEY_DIR)
  return value.rstrip("/") if isinstance(value, str) else ""


def _filter_strings(value: object) -> list[str]:
  """
  Return the strings of a configured list.

  Args:
    value: The configured value.

  Returns:
    Its string items, or an empty list when the value is no list.
  """
  # guard: a missing or malformed list holds nothing
  if not isinstance(value, list):
    return []
  return [ item for item in value if isinstance(item, str) ]


def _is_matched(matcher: _scope.GlobMatcher, rel: str, globs: object) -> bool:
  """
  Check whether a document matches any glob of a list.

  Args:
    matcher: Glob matcher used for the comparison.
    rel: Repo-relative path of the document.
    globs: Glob patterns to match against; anything other than a list matches nothing.

  Returns:
    `True` if at least one string glob matches the document.
  """
  # guard: a missing or malformed glob list matches nothing
  if not isinstance(globs, list):
    return False
  return any(isinstance(glob, str) and matcher.match(rel, glob) for glob in globs)


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class DictionaryChange:
  """
  Change a batch of term operations makes to a dictionary directory.

  Attributes:
    writes: Full text of every created or changed term file, by stem.
    removals: Stems whose term files are deleted.
    retargets: New stem a link to an old stem must point at, by old stem.
    merged: Stems of the terms the batch joined with another term.
    accepted: Operations the batch applied, in order, each as sent.
    refused: One mapping per refused operation, holding its zero-based position in the batch, the operation as sent
      and the reason, under `REFUSED_INDEX`, `REFUSED_OPERATION` and `REFUSED_REASON`.
  """

  # The full text of every created or changed term file, by stem
  writes: dict[str, str]
  # The stems whose term files are deleted
  removals: list[str]
  # The new stem a link to an old stem must point at, by old stem
  retargets: dict[str, str]
  # The stems of the terms the batch joined with another term
  merged: list[str]
  # The operations the batch applied, in their order, each as sent
  accepted: list[dict]
  # The operations the batch refused, each with its position in the batch and the reason
  refused: list[dict]


# ----------------------------------------------------------------------------------------
@dataclass
class _Entry:
  """
  One term of a dictionary directory, as held while a batch is applied.

  Attributes:
    stem: File name stem the term's file carries.
    term: Term as its file's title line spells it.
    definition: Definition of the term.
  """

  # The file name stem the term's file carries
  stem: str
  # The term as its file's title line spells it
  term: str
  # The definition of the term
  definition: str

  def render(self) -> str:
    """
    Render the text of the term's file.

    Returns:
      The title line, a blank line and the definition.
    """
    return render_term_file(self.term, self.definition)


# ----------------------------------------------------------------------------------------
class TermDictionary:
  """
  Terms dictionary kept as a directory with one file per term.

  Answers which terms and definitions the directory holds and works out the change a batch of term operations
  would make to it. The caller writes that change.
  """

  def __init__(self, *, path: Path) -> None:
    """
    Bind the dictionary to its directory.

    Args:
      path: Dictionary directory the operations apply to.
    """
    # the dictionary directory the operations apply to
    self._path = Path(path)

  def read_terms(self) -> dict[str, str]:
    """
    Return the terms the dictionary holds.

    Returns:
      Each term as its file's title line spells it, by file name stem; empty when the directory is missing.
    """
    return { entry.stem: entry.term for entry in self._load().values() }

  def compute_terms_after(self, change: DictionaryChange) -> dict[str, str]:
    """
    Return the terms the dictionary will hold once a change is written.

    Args:
      change: A change `compute_change` returned for this dictionary.

    Returns:
      Each term as its file's title line will spell it, by file name stem.
    """
    removed = { stem.casefold() for stem in [ *change.removals, *change.writes ] }

    # the terms on disk that the change leaves alone, then every written file with its new title line
    terms = { stem: term for stem, term in self.read_terms().items() if stem.casefold() not in removed }
    for stem, text in change.writes.items():
      title = text.partition(_NL)[0]
      terms[stem] = title[len(_TITLE):].strip() if title.startswith(_TITLE) else stem
    return terms

  def compute_change(self, operations: list[dict], *, sources: list[str]) -> DictionaryChange:
    """
    Judge a batch of term operations one by one and return the change the accepted ones make to the dictionary.

    Guarantees:
      - Each operation is judged on its own, in order, against the dictionary as the operations accepted before it
        left it; an operation that breaks a rule is refused and the rest go on.
      - A refused operation leaves no trace in `writes`, `removals`, `retargets` or `merged`.
      - An operation is refused for an unknown kind or a missing or malformed key, a definition or a split's sibling
        definition over three lines once stripped, a split whose definitions do not each name the other term or that
        names itself, a term absent at that point, a rejection of a dictionary term or of a name that names one
        when read as a link target, a document whose plain repo-relative form is no entry of `sources`, a `files`
        that is present but not a list of document paths, a forbidden `skip`, a term that gives no
        file name, or a `relink` of a word that another `relink` of the same word in the batch also links in the
        same document.
      - A `skip` is forbidden on an operation other than `relink`, when it is not a list of non-empty strings, and
        for a fragment that spans a line break or does not hold the word.
      - Two or more `relink` operations whose `from` is the same word, letter case and runs of whitespace aside,
        that name the same document are all refused, whatever their order, and none of them is applied; each
        reason names the document. A member that another rule would also refuse is still counted as a member and
        gets the conflict reason. A document one operation names twice is one document, and documents are compared
        in their plain repo-relative form, so `specs/a.md` and `./specs/a.md` are one document.
      - Every operation is either in `accepted`, in the order applied and as sent, or in `refused` with its position
        in the batch and its reason.
      - Raises no `JobRefusedError`, and never writes, creates or removes a term file.
      - Two terms whose names give one file name never both survive: an `add` or a `rename` landing on a taken file
        name joins the existing term, which keeps its title and takes the new definition, and the joined stem is
        reported in `merged`; a rename's old stem is reported in `retargets`, pointing at the stem links must follow.

    Args:
      operations: Operations judged in order.
      sources: Job's source documents an operation may name.

    Returns:
      The change the accepted operations make, with the accepted and the refused operations.
    """

    # Contract:
    # Each operation is judged on its own, in order, against the dictionary as the operations accepted before it
    # left it. A refused operation leaves no trace: `writes`, `removals`, `retargets` and `merged` are exactly
    # what the batch without it would give.

    # Contract:
    # Every operation lands in exactly one of `accepted`, as sent and in order, or `refused`, as an entry holding
    # its zero-based position in the batch, the operation and the reason. An operation's error never raises
    # `JobRefusedError` out of this method.

    # Contract:
    # This method never writes, creates or removes a term file, whatever the batch holds;
    # the caller applies the returned change.

    # Contract:
    # An operation is refused, and only for one of these causes: an unknown kind or a missing or malformed
    # key; a definition, or a split's sibling definition, over the line limit; a split whose definitions
    # do not each name the other term, or that names itself as its sibling; a term absent from the
    # dictionary at that point of the batch; a rejection of a dictionary term, or of a name that names one
    # when read as a link target; a document whose plain repo-relative form is no entry of `sources`, or a
    # `files` that is present but not a list of document paths; a forbidden `skip`; a term that gives no
    # file name; a `relink` of a word that another `relink` of the same word in the batch also links in
    # the same document. Any other operation is accepted.

    # Contract:
    # An operation that breaks a form rule is refused alone. The form rules are: a definition, or a split's
    # sibling definition, runs at most three lines once stripped, and a split's two definitions each name
    # the other term.

    # Contract:
    # An operation that carries a `skip` its protocol forbids is refused alone. A `skip` is forbidden on any
    # operation other than `relink`, when it is not a list of non-empty strings, and when a fragment spans
    # a line break or does not hold the word the operation links.

    # Contract:
    # Two or more `relink` operations whose `from` is the same word, letter case and runs of whitespace aside,
    # that name the same document are all refused, whatever their order; none of them is applied, and each
    # reason names the document. A member that another rule would also refuse is still counted as a member
    # and gets the conflict reason. A document that one operation names twice is one document, and documents
    # are compared in their plain repo-relative form, so `specs/a.md` and `./specs/a.md` are one document.

    # Contract:
    # Two terms whose names give one file name never both survive a batch.
    # An `add` or a `rename` landing on a taken file name joins the term already there:
    # that term keeps its title and takes the new definition, and its stem is reported in `merged`.
    # The old stem of a rename is reported in `retargets`, pointing at the stem that links must follow.

    # Domain(wiki.terms):
    # # Where a term lives in the dictionary
    # The dictionary is a directory with one file per term. The file is named after the term by the file-name rule,
    # and it holds the term on its title line, then its definition. The title keeps the exact spelling the term was
    # given; the file name is what links point at. A directory that is missing is an empty dictionary: git keeps no
    # empty directory, so a scope with no terms yet has none in a fresh clone. The batch is worked out against no
    # terms, and the directory appears when the first term file is written.
    # Two terms whose names give one file name are one term. A new term, or a renamed one, that lands on a file name
    # already taken joins the term standing there: that term keeps its title, takes the definition just sent, and
    # the links that pointed at the renamed term follow it to the joined one. The join is reported, so the curator
    # sees that two names collapsed into one. Sending a term again with the same spelling and the same definition
    # changes nothing, so it is not reported as a join. A rename that keeps the file name changes nothing but the
    # spelling on the title line.
    # A file name that a rename freed can be taken again later in the same batch. The links to it then stay with
    # the term now standing there, and are no longer moved to the renamed term. When it is taken again for a term
    # whose name gives the same file name in another letter case, the file keeps the spelling it has on disk and is
    # rewritten in place with the new title, so the directory never holds the old file beside a new one that differs
    # only in letter case. Renaming `a` to `b` and then `b` to `A` in one batch leaves the file `a` titled `A`,
    # exactly as renaming `a` to `A` directly does.
    # Linking a word, retargeting a link and rejecting a word do not change the dictionary. Each must name an
    # existing term (a rejection must name a word that is not a term) and may name only documents of the curator's
    # own job.
    # A word links to one term per document in one batch. When a batch links the same word twice in one document,
    # letter case and runs of whitespace aside, every link of that word in that document is refused, whatever their
    # order: the two links would compete for the same occurrences, and the later would silently replace the earlier,
    # places kept plain included, so the batch never picks one sense of the word by order. The other operations of
    # the batch go on. A word that in one document stands for two different terms is therefore linked to neither by
    # that batch. The same word linked in two different documents is fine.

    # one word links to one term per document, so every link of a word that competes for one document is refused
    conflicts = self._find_all_relink_conflicts(operations)

    # the terms on disk, and a working copy the accepted operations edit in order
    initial = self._load()
    batch = _Batch(
      entries = { key: _Entry(entry.stem, entry.term, entry.definition) for key, entry in initial.items() },
      sources = sources,
    )

    # each operation is judged on its own; a refused one leaves the working copy as it was and the rest go on
    accepted: list[dict] = []
    refused: list[dict] = []
    for index, operation in enumerate(operations):
      try:
        self._validate_keys(operation)
        # guard: a link of a word that another link of it competes with is never applied, whatever else is wrong with it
        if ( conflict := conflicts.get(index) ) is not None:
          raise _job_response.JobRefusedError(category = _job_response.CATEGORY_TECHNICAL, reason = conflict)
        self._validate_form(operation)
        self._validate_skip(operation)
        batch.apply(operation)
      except _job_response.JobRefusedError as refusal:
        refused.append({ REFUSED_INDEX: index, REFUSED_OPERATION: operation, REFUSED_REASON: refusal.reason })
        continue
      accepted.append(operation)

    # the difference between the working copy and the disk is the change
    return batch.build_change(initial, accepted = accepted, refused = refused)

  def _load(self) -> dict[str, _Entry]:
    """
    Read every term file of the directory.

    Returns:
      Terms by casefolded stem; empty when the directory is missing.
    """
    # guard: a missing directory holds no term
    if not self._path.is_dir():
      return {}

    # every markdown file directly in the directory is one term; the first of two stems equal in casefold wins
    entries: dict[str, _Entry] = {}
    for name in sorted(os.listdir(self._path)):
      file = self._path / name
      # guard: only a term file directly in the directory counts
      if not name.endswith(TERM_FILE_SUFFIX) or not file.is_file():
        continue
      stem = name[:-len(TERM_FILE_SUFFIX)]
      term, definition = self._read(file, stem)
      entries.setdefault(stem.casefold(), _Entry(stem, term, definition))
    return entries

  @staticmethod
  def _read(file: Path, stem: str) -> tuple[str, str]:
    """
    Read one term file back into its term and definition.

    Args:
      file: The term file.
      stem: File name stem of the term file.

    Returns:
      The term of the title line, or the stem when the file has none, and the definition.
    """
    title, _, rest = TextFile(path = file).read().partition(_NL)

    # guard: a file without a title line is named by its stem and holds only its definition
    if not title.startswith(_TITLE):
      return stem, f"{title}{_NL}{rest}".strip()
    return title[len(_TITLE):].strip(), rest.strip()

  @staticmethod
  def _validate_keys(operation: dict) -> None:
    """
    Refuse an operation of an unknown kind, with a required list key that is not a list of strings, or missing a key
    its kind requires.

    Args:
      operation: One term operation, as carried in a batch.

    Raises:
      JobRefusedError: Technical category on an unknown kind, on a required list key present but not a list of
        strings ("must be a list of document paths"), or on a missing or empty required key ("lacks"); the malformed
        list key is refused first.
    """
    # guard: an operation of an unknown kind names nothing the dictionary can do
    if not isinstance(kind := operation.get(_OP), str) or kind not in _REQUIRED_KEYS:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL, reason = f"unknown dictionary operation: {kind!r}",
      )

    # every required text key is a string, every required list key a non-empty list of strings; a list key that is
    # present but not a list of strings is malformed rather than missing
    texts, lists = _REQUIRED_KEYS[kind]
    missing = [ key for key in texts if not isinstance(operation.get(key), str) ]
    missing += [ key for key in lists if not operation.get(key) ]
    malformed = [
      key for key in lists
      if key in operation and (
        not isinstance(operation[key], list) or not all(isinstance(item, str) for item in operation[key])
      )
    ]

    # guard: a list key present in the wrong shape refuses the operation as malformed
    if malformed:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"{kind} operation: {', '.join(malformed)} must be a list of document paths",
      )

    # guard: a missing key refuses the operation
    if missing:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"{kind} operation lacks {', '.join(missing)}",
      )

  @staticmethod
  def _validate_form(operation: dict) -> None:
    """
    Refuse an operation whose definitions break the dictionary's form rules.

    Args:
      operation: One term operation, as carried in a batch.

    Raises:
      JobRefusedError: Technical category when a form rule is broken.
    """

    # Domain(wiki.terms):
    # # Shape of a term definition
    # A definition is meant to be read at a glance, so it spans at most three lines of the dictionary file. The
    # lines are counted as written: a soft wrap in an editor does not add a line, a hard line break does. A
    # change that would leave a longer definition is refused: the dictionary stays as it was before that one change,
    # and the rest of the batch goes on.
    # A term is split when a second term is added beside an existing one whose name a neighbouring concept had
    # taken. Each of the two definitions then names the other term. That mutual naming is the mark that tells a
    # freshly split pair apart from a dead term when the audit later looks for terms no document uses: a term
    # whose definition points at its twin is a deliberate neighbour, not a leftover. A split whose definitions
    # do not both name the other term is refused in the same way: that one change is refused, leaving the dictionary
    # as it was before it, while the rest of the batch goes on.
    # A term cannot be split against itself. Two names that differ only in letter case or in surrounding spaces
    # are the same name, and a split of that kind would leave two sections under one heading. It is refused in
    # the same way, and the dictionary stays as it was before it.

    term = str(operation.get(_OP_TERM, ""))
    definition = str(operation.get(_OP_DEFINITION, ""))
    is_split = operation.get(_OP) == _OP_SPLIT
    sibling = str(operation.get(_OP_SIBLING, ""))
    sibling_definition = str(operation.get(_OP_SIBLING_DEFINITION, ""))

    # each definition the operation writes is held to the line limit, counted as it will be written
    for heading, text in ( (term, definition), *( [ (sibling, sibling_definition) ] if is_split else [] ) ):
      # guard: a definition longer than the limit is refused
      if len(text.strip().splitlines()) > _DEFINITION_MAX_LINES:
        raise _job_response.JobRefusedError(
          category = _job_response.CATEGORY_TECHNICAL,
          reason = f"definition of {heading!r} exceeds {_DEFINITION_MAX_LINES} lines",
        )

    # guard: each definition of a split names the other term, which marks the pair as a split; a blank sibling
    # names nothing, since an empty string is found in every definition
    if is_split and (
      not sibling.strip()
      or sibling.casefold() not in definition.casefold()
      or term.casefold() not in sibling_definition.casefold()
    ):
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"split definitions of {term!r} and {sibling!r} do not each name the other term",
      )

    # guard: a split of a term against itself would leave two terms under one name
    if is_split and term.strip().casefold() == sibling.strip().casefold():
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"split of {term!r} names itself as the sibling",
      )

  @staticmethod
  def _validate_skip(operation: dict) -> None:
    """
    Refuse an operation whose places kept plain are malformed or do not hold its word.

    Args:
      operation: One term operation, as carried in a batch, its keys already checked.

    Raises:
      JobRefusedError: Technical category when an operation other than `relink` carries `skip`, when `skip` is not
        a list of non-empty strings, or when a fragment spans a line break or does not hold the word.
    """

    # Domain(wiki.terms):
    # # Places kept plain
    # When the curator links a word in a document, it may name places where the word is meant otherwise and must
    # stay plain. Each place is a fragment of the document's text. Such exclusions belong to linking a word only:
    # on any other operation they mean nothing and the operation carrying them is refused. They must be a list of
    # fragments, none of them empty. A fragment must stand on one line and must hold the word it excludes, matched
    # as the link edit matches it: letter case ignored, the word standing whole. A fragment across a line break can
    # never be found, since linking never reaches across lines, and a fragment without the word can never exclude
    # an occurrence of it. An exclusion that can never be honoured refuses the operation carrying it, up front, so
    # the curator learns of the mistake at once and corrects it, instead of the word being kept off the document
    # later for a reason that was visible in the request itself.

    kind = operation.get(_OP)

    # guard: an operation keeping no place plain has nothing to check
    if _OP_SKIP not in operation:
      return

    # guard: only a link operation keeps places plain
    if kind != _OP_RELINK:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL, reason = f"{kind} operation carries {_OP_SKIP}",
      )

    # guard: the places come as a list of non-empty strings
    if not isinstance(fragments := operation[_OP_SKIP], list) or not all(
      isinstance(item, str) and item for item in fragments
    ):
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"{_OP_SKIP} of relink {operation[_OP_FROM]!r} must be a list of non-empty strings",
      )

    # every fragment stands on one line and holds the word the way the link edit finds it
    pattern = _term_link_syntax.compile_word_pattern(operation[_OP_FROM])
    for fragment in fragments:
      # guard: a fragment across a line break, or one without the word, can never be honoured
      if any(char in fragment for char in _LINE_BREAKS) or pattern is None or pattern.search(fragment) is None:
        raise _job_response.JobRefusedError(
          category = _job_response.CATEGORY_TECHNICAL,
          reason = f"{_OP_SKIP} fragment {fragment!r} of relink {operation[_OP_FROM]!r} is not one line holding the "
                   f"word",
        )

  @classmethod
  def _find_all_relink_conflicts(cls, operations: list[dict]) -> dict[int, str]:
    """
    Find the relink operations that compete for one document.

    Only relink operations with valid keys count, documents are compared in their plain repo-relative form, and a
    document one operation names twice counts once.

    Args:
      operations: The batch's operations, in order.

    Returns:
      The reason each conflicting relink is refused with, by its position in the batch.
    """
    # each link operation's word, read the way the link edit matches it, against every document it names in its plain
    # repo-relative form; a document the operation names twice is one document, never a second link of the word
    linking: dict[tuple[str, str], list[int]] = {}
    for index, operation in enumerate(operations):
      # guard: only a link operation whose word and documents can be read names a word for documents
      if operation.get(_OP) != _OP_RELINK or not cls._has_valid_keys(operation):
        continue
      spelled = " ".join(str(operation[_OP_FROM]).split())
      for rel in dict.fromkeys(posixpath.normpath(name) for name in operation[_OP_FILES]):
        linking.setdefault(( spelled.casefold(), rel ), []).append(index)

    # every link of a word that another link of it competes with in one document is refused, naming that document
    conflicts: dict[int, str] = {}
    for ( word, rel ), indices in linking.items():
      # a word linked once in a document competes with nothing
      if len(indices) < 2:
        continue
      for index in indices:
        conflicts.setdefault(
          index, f"{len(indices)} relink operations of {word!r} name {rel!r}; one relink per word per document",
        )
    return conflicts

  @classmethod
  def _has_valid_keys(cls, operation: dict) -> bool:
    """
    Check whether an operation passes its key rule.

    Args:
      operation: One term operation, as carried in a batch.

    Returns:
      `True` if the operation has a known kind and every key it requires, each well typed; `False` otherwise.
    """
    # an operation whose word or documents cannot be read is never counted against another
    try:
      cls._validate_keys(operation)
    except _job_response.JobRefusedError:
      return False
    return True


# ----------------------------------------------------------------------------------------
class _Batch:
  """
  Working copy of a dictionary that one batch of term operations edits in order.
  """

  def __init__(self, *, entries: dict[str, _Entry], sources: list[str]) -> None:
    """
    Start the batch from the dictionary's terms.

    Args:
      entries: Copies of the dictionary's terms by casefolded stem; edited in place.
      sources: Job's source documents an operation may name; each is held in its plain repo-relative form.
    """
    # the terms as the operations so far left them
    self._entries = entries

    # the file name each term file carries on disk, by casefolded stem
    self._disk_stems = { key: entry.stem for key, entry in entries.items() }

    # the documents an operation may name, in their plain repo-relative form
    self._sources = { posixpath.normpath(rel) for rel in sources }

    # the new stem of every term renamed or joined so far, by old stem
    self._retargets: dict[str, str] = {}

    # the stems of the terms joined so far, in the order they were joined
    self._merged: list[str] = []

  def apply(self, operation: dict) -> None:
    """
    Apply one operation to the working copy, or refuse it and leave the working copy untouched.

    Args:
      operation: One operation whose keys and form are already checked.

    Raises:
      JobRefusedError: Technical category when the operation names a term it may not.
    """
    kind = operation[_OP]
    term = operation[_OP_TERM]

    # the working copy as it stands, put back whole when the operation is refused part way
    entries = { key: _Entry(entry.stem, entry.term, entry.definition) for key, entry in self._entries.items() }
    retargets = dict(self._retargets)
    merged = list(self._merged)

    # each kind edits the working copy, or only checks what it names
    try:
      if kind == _OP_ADD:
        self._add(term, operation[_OP_DEFINITION])
      elif kind == _OP_EXTEND:
        self._require(term).definition = operation[_OP_DEFINITION]
      elif kind == _OP_RENAME:
        self._rename(term, operation[_OP_FROM], operation[_OP_DEFINITION])
      elif kind == _OP_SPLIT:
        self._split(term, operation[_OP_DEFINITION], operation[_OP_SIBLING], operation[_OP_SIBLING_DEFINITION])
      elif kind == _OP_REJECT:
        self._validate_rejection(term)
      else:
        self._require(term)
        self._validate_files(operation[_OP_FILES])
    except _job_response.JobRefusedError:
      # a refused operation leaves no trace in the working copy
      self._entries, self._retargets, self._merged = entries, retargets, merged
      raise

  def build_change(self,
                   initial: dict[str, _Entry],
                   *,
                   accepted: list[dict],
                   refused: list[dict]) -> DictionaryChange:
    """
    Compare the working copy with the dictionary on disk.

    Args:
      initial: The dictionary's terms by casefolded stem, as read before the batch.
      accepted: The operations the batch applied, in order, each as sent.
      refused: One mapping per refused operation: its position in the batch, the operation as sent and the reason.

    Returns:
      The change the batch makes, carrying the accepted and the refused operations.
    """
    # a term file is written when it is new or its title or definition changed
    writes = {
      entry.stem: entry.render()
      for key, entry in self._entries.items()
      if key not in initial or (initial[key].term, initial[key].definition) != (entry.term, entry.definition)
    }

    # a term file the working copy no longer holds is removed
    removals = [ entry.stem for key, entry in initial.items() if key not in self._entries ]

    # a joined term counts once, and only while it still exists
    merged = list(dict.fromkeys(
      stem for stem in self._merged if stem.casefold() in self._entries
    ))
    return DictionaryChange(
      writes = writes, removals = removals, retargets = dict(self._retargets), merged = merged,
      accepted = accepted, refused = refused,
    )

  def _add(self, term: str, definition: str) -> None:
    """
    Add a term, or join it with the term that already takes its file name.

    Re-adding a term with identical spelling and definition changes nothing and is not reported as a join. Links to a
    newly created term file keep pointing at it.

    Args:
      term: The term to add.
      definition: Its definition.

    Raises:
      JobRefusedError: Technical category when the term has no file name.
    """
    stem = _stem_of(term)
    taken = self._entries.get(stem.casefold())

    # a taken file name turns the addition into an extension of the term already there; only a different spelling
    # or a changed definition is a join worth reporting
    if taken is not None:
      if taken.term != term.strip() or taken.definition.strip() != definition.strip():
        self._merged.append(taken.stem)
      taken.definition = definition
      return

    # a new term keeps its exact spelling on the title line, and links to its file stay where they point; a file
    # name the batch freed keeps the spelling it has on disk, so its file is rewritten rather than doubled
    stem = self._disk_stems.get(stem.casefold(), stem)
    self._entries[stem.casefold()] = _Entry(stem, term.strip(), definition)
    self._forget_retarget(stem)

  def _rename(self, term: str, source: str, definition: str) -> None:
    """
    Rename a term, correct its spelling, or join it with the term that takes the new file name.

    Args:
      term: The new name.
      source: The term being renamed.
      definition: The definition the renamed term carries.

    Raises:
      JobRefusedError: Technical category when the renamed term is absent or a name has no file name.
    """
    old = self._require(source)
    key = _stem_of(term).casefold()

    # the same file name only corrects the spelling on the title line
    if key == old.stem.casefold():
      old.term = term.strip()
      old.definition = definition
      return

    # the old file goes either way; links to it follow the term to its new file
    del self._entries[old.stem.casefold()]

    # the term already standing on the new file name, if any
    taken = self._entries.get(key)

    # a taken file name joins the renamed term with the term already there
    if taken is not None:
      taken.definition = definition
      self._merged.append(taken.stem)
      self._retarget(old.stem, taken.stem)
      return

    # a free file name takes the renamed term with its exact spelling; a file name the batch freed keeps the spelling
    # it has on disk, so its file is rewritten rather than doubled
    stem = self._disk_stems.get(key, _stem_of(term))
    self._entries[key] = _Entry(stem, term.strip(), definition)
    self._forget_retarget(stem)
    self._retarget(old.stem, stem)

  def _split(self, term: str, definition: str, sibling: str, sibling_definition: str) -> None:
    """
    Narrow an existing term and add its new neighbour.

    Args:
      term: The new neighbour.
      definition: The neighbour's definition.
      sibling: The existing term being narrowed.
      sibling_definition: The narrowed definition.

    Raises:
      JobRefusedError: Technical category when the sibling is absent or both names give one file name.
    """
    narrowed = self._require(sibling)

    # guard: a neighbour whose file name is the sibling's would split a term against itself
    if _stem_of(term).casefold() == narrowed.stem.casefold():
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"split of {term!r} names itself as the sibling",
      )

    # the sibling takes its narrowed definition and the neighbour is added beside it
    narrowed.definition = sibling_definition
    self._add(term, definition)

  def _validate_rejection(self, term: str) -> None:
    """
    Check that a rejected word is no term of the dictionary.

    Args:
      term: The rejected word.

    Raises:
      JobRefusedError: Technical category when the dictionary holds the word as a term, or when the word, read as a
        link target, names a term.
    """

    # Domain(wiki.terms):
    # # A rejected word never names a term
    # A word is rejected when the curator judges it no term, so a rejection is refused when the dictionary holds the
    # word as a term. The word is judged twice: by the file name the term rule gives it, and as a link target written
    # in a document, the way a link to it would be read. A word whose link reading names an existing term, such as
    # `notes.md` while the term `notes` exists, is refused like a rejection of that term itself. The name the curator
    # wrote is, read as a link, the existing term's own name, so the rejection would leave that term's links standing,
    # an existing term always winning, and pass as if the word had been dealt with; it is refused so the curator
    # learns the word is a term.

    # guard: a word the dictionary holds, by its own file name or by the term it names read as a link target, cannot
    # be rejected
    if ( _stem_of(term).casefold() in self._entries
         or parse_target_stem(term, self._entries.keys()).casefold() in self._entries ):
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL, reason = f"rejected word is a dictionary term: {term!r}",
      )

  def _require(self, term: str) -> _Entry:
    """
    Return the term an operation names.

    Args:
      term: The term named.

    Returns:
      The term in the working copy.

    Raises:
      JobRefusedError: Technical category when the term is absent.
    """
    # guard: an operation on an absent term is refused
    if (entry := self._entries.get(_stem_of(term).casefold())) is None:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL, reason = f"term is absent: {term!r}",
      )
    return entry

  def _validate_files(self, files: list[str]) -> None:
    """
    Check that an operation names only documents of the job.

    Each document is compared in its plain repo-relative form, so `./specs/a.md` is `specs/a.md`.

    Args:
      files: The documents the operation names.

    Raises:
      JobRefusedError: Technical category when a document is not a source of the job.
    """
    # guard: a document whose plain form is not a source of the job is not the curator's to edit
    if foreign := [ rel for rel in files if posixpath.normpath(rel) not in self._sources ]:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"documents that are not sources of this job: {foreign}",
      )

  def _forget_retarget(self, stem: str) -> None:
    """
    Stop moving links away from a stem whose file exists again.

    Args:
      stem: The stem a term file now carries.
    """
    self._retargets = {
      source: target for source, target in self._retargets.items() if source.casefold() != stem.casefold()
    }

  def _retarget(self, old: str, new: str) -> None:
    """
    Record that links to one stem now point at another.

    Args:
      old: The stem whose file is gone.
      new: The stem the links now point at.
    """
    # earlier moves that ended at the old stem now end at the new one; a move back onto itself is dropped
    for source, target in list(self._retargets.items()):
      if target.casefold() == old.casefold():
        self._retargets[source] = new
    self._retargets[old] = new
    self._retargets = {
      source: target for source, target in self._retargets.items() if source.casefold() != target.casefold()
    }


def _stem_of(term: str) -> str:
  """
  Return the file name stem of a term an operation names.

  Args:
    term: The term.

  Returns:
    Its non-empty stem.

  Raises:
    JobRefusedError: Technical category when the term gives no file name.
  """
  # guard: a term without a name cannot have a file
  if not (stem := term_file_stem(term)):
    raise _job_response.JobRefusedError(
      category = _job_response.CATEGORY_TECHNICAL, reason = f"term has no file name: {term!r}",
    )
  return stem
