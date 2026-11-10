from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final


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
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Settings section and keys a terms scope is configured under.
_SECTION_TERMS = "terms"
_KEY_SCOPES = "scopes"
_KEY_PATHS = "paths"
_KEY_FILE = "file"
_KEY_SOURCE_EXCLUDE = "source_exclude"

# Settings layer a scope is resolved from: the tracked file with the local overlay merged in.
_LAYER_MERGED: Final = "merged"

# Operation keys of the terms protocol's result format.
_OP = "op"
_OP_ADD = "add"
_OP_EXTEND = "extend"
_OP_RENAME = "rename"
_OP_SPLIT = "split"
_OP_TERM = "term"
_OP_FROM = "from"
_OP_DEFINITION = "definition"
_OP_SIBLING = "sibling"
_OP_SIBLING_DEFINITION = "sibling_definition"

# Heading prefix that opens a term section, and the line break sections are assembled with.
_HEADING = "## "

# The most physical lines a term definition may span in the file.
_DEFINITION_MAX_LINES = 3
_NL = "\n"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class TermsScope:
  """
  Terms scope that a set of documents resolved to.

  Names the dictionary the documents' terminology belongs to and the documents terms are taken from.

  Attributes:
    scope_id: Identifier of the scope the documents resolved to.
    dictionary: Repo-relative path of the scope's dictionary file.
    sources: Requested documents that remain term sources once the scope's exclusions are applied.
  """

  # The scope id the documents resolved to
  scope_id: str
  # The repo-relative dictionary file of the scope
  dictionary: str
  # The requested documents that remain term sources once the scope's exclusions are applied
  sources: list[str]


# ----------------------------------------------------------------------------------------
def resolve_terms_scope(repo: Path, files: list[str]) -> TermsScope | None:
  """
  Resolve the terms scope that serves the given documents.

  The first configured scope, in configuration order, whose paths cover any of the documents wins. Documents the
  scope serves but excludes from term sourcing drop out of the result.

  Guarantees:
    - The first configured scope, in configuration order, whose paths cover any requested document wins.
    - When the winning scope's source exclusions leave no document, the result is `None` and later scopes are
      never tried.

  Args:
    repo: Repository root whose merged settings declare the terms scopes.
    files: Repo-relative paths of the documents to resolve.

  Returns:
    The winning scope with its term sources, or `None` when no scope claims the documents or the exclusions leave
    no source.
  """
  terms = _axes.settings_get(repo, _SECTION_TERMS, layer = _LAYER_MERGED)
  scopes = terms.get(_KEY_SCOPES) if isinstance(terms, dict) else None

  # guard: no terms scopes configured, or no documents requested — nothing belongs to a dictionary
  if not isinstance(scopes, dict) or not files:
    return None

  # Contract:
  # The first configured scope, in configuration order, whose paths cover any requested document wins.
  # When the winning scope's source exclusions leave no document, the result is None
  # and later scopes are never tried.

  # the first scope in key order whose globs match any requested document wins
  matcher = _scope.GlobMatcher()
  for scope_id, cfg in scopes.items():
    # guard: a malformed scope entry matches nothing
    if not isinstance(cfg, dict):
      continue
    matched = [ rel for rel in files if _matches(matcher, rel, cfg.get(_KEY_PATHS)) ]

    # guard: a scope that serves none of the documents cannot win; the search moves on to the next one
    if not matched:
      continue

    # documents the scope serves but does not take terminology from drop out
    sources = [ rel for rel in matched if not _matches(matcher, rel, cfg.get(_KEY_SOURCE_EXCLUDE)) ]

    # guard: nothing survives the exclusions
    if not sources:
      return None

    # the winning scope with the documents that source its terms
    return TermsScope(scope_id = scope_id, dictionary = str(cfg.get(_KEY_FILE, "")), sources = sources)

  # no scope claims any of the documents
  return None


def _matches(matcher: _scope.GlobMatcher, rel: str, globs: object) -> bool:
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
class TermDictionary:
  """
  Terms dictionary file that term changes are applied to.

  Turns a batch of term operations into the resulting dictionary text, refusing a batch whose definitions break
  the dictionary's form. The dictionary file itself is never written; the caller receives the new text and
  decides what to do with it.

  Guarantees:
    - A refused batch leaves the dictionary file unchanged and yields no text.
  """

  def __init__(self, *, path: Path) -> None:
    """
    Bind the dictionary to its file.

    Args:
      path: Dictionary file the operations apply to.
    """
    # the dictionary file the operations apply to
    self._path = Path(path)

  def apply(self, operations: list[dict]) -> str:
    """
    Apply a batch of term operations and return the resulting dictionary text.

    Apply term changes that introduce, reword or reorganize dictionary terms. The batch is all-or-nothing: one
    refusal refuses every operation in it.

    Guarantees:
      - A refused batch raises `JobRefusedError` and yields no text; no operation of a refused batch is ever
        reflected in a result.
      - The dictionary file is not modified, whether the batch succeeds or is refused.
      - A batch carrying an operation that breaks a form rule is refused whole with the technical category and
        yields no text. The form rules are: a definition, or a split's sibling definition, runs at most three
        lines once stripped, and a split's two definitions each name the other term.

    Args:
      operations: Operations applied in order; each carries an `op` of `add`, `extend`, `rename` or `split`, the
        `term` and its `definition`, plus `from` for a rename and `sibling` with `sibling_definition` for a split.

    Returns:
      The full dictionary text with every operation applied.

    Raises:
      JobRefusedError: Logical category when the dictionary file is missing. Technical category when an operation is
        unknown, when a definition runs past three lines, when the two definitions of a split do not each name the
        other term, when the heading a new section would be placed before appears more than once, or when the
        section to change is absent or appears more than once.
    """

    # Contract:
    # A refused batch raises `JobRefusedError` and yields no text;
    # no operation of a refused batch is ever reflected in a result.

    # Contract:
    # The dictionary file is never modified, whether the batch succeeds or is refused.

    # Contract:
    # A batch carrying an operation that breaks a form rule is refused whole with the technical category
    # of `JobRefusedError` and yields no text. The form rules are: a definition, or a split's sibling definition,
    # runs at most three lines once stripped, and a split's two definitions each name the other term.

    # Domain(wiki.terms):
    # # Where a term section goes
    # A terms dictionary lists its sections by heading, compared case-insensitively first and by code point
    # second, so latin headings come before cyrillic ones and no locale decides the order. A new or renamed
    # section takes the place that order gives it; every other section keeps its exact text. The dictionary
    # is never repaired by guesswork: when the heading a change would anchor to appears more than once, or the
    # section it would change does not exist, nothing is written and the duplicate is left for the audit to
    # report. A missing dictionary is not recreated, because a silent fresh file would hide the loss of every
    # term it held.

    # guard: a missing dictionary is never recreated
    if not self._path.is_file():
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_LOGICAL, reason = f"dictionary not found: {self._path}",
      )

    # every operation's definitions must keep the dictionary's form before any of them is applied
    for operation in operations:
      self._check_form(operation)

    # the dictionary's current sections are what every operation edits
    preamble, sections = self._parse(TextFile(path = self._path).read())

    # each operation edits the in-memory section list; a refusal anywhere refuses the whole batch
    for operation in operations:
      kind = operation.get(_OP)
      term = str(operation.get(_OP_TERM, ""))
      definition = str(operation.get(_OP_DEFINITION, ""))
      if kind == _OP_ADD:
        self._insert(sections, term, definition)
      elif kind == _OP_EXTEND:
        sections[self._index_of(sections, term)] = (term, self._section(term, definition))
      elif kind == _OP_RENAME:
        del sections[self._index_of(sections, str(operation.get(_OP_FROM, "")))]
        self._insert(sections, term, definition)
      elif kind == _OP_SPLIT:
        sibling = str(operation.get(_OP_SIBLING, ""))
        sections[self._index_of(sections, sibling)] = (
          sibling, self._section(sibling, str(operation.get(_OP_SIBLING_DEFINITION, ""))),
        )
        self._insert(sections, term, definition)
      else:
        raise _job_response.JobRefusedError(
          category = _job_response.CATEGORY_TECHNICAL, reason = f"unknown dictionary operation: {kind!r}",
        )

    # the preamble, then every section's text in order
    return preamble + "".join(text for _, text in sections)

  @staticmethod
  def _check_form(operation: dict) -> None:
    """
    Refuse an operation whose definitions break the dictionary's form rules.

    Accept the operation unchanged when every definition it writes keeps the form.

    Args:
      operation: One term operation, as carried in a batch.

    Raises:
      JobRefusedError: Technical category when a definition runs past three lines, when the two definitions
        of a split do not each name the other term, or when the term and the sibling of a split are the same
        name, ignoring letter case and surrounding whitespace.
    """

    # Domain(wiki.terms):
    # # Shape of a term definition
    # A definition is meant to be read at a glance, so it spans at most three lines of the dictionary file. The
    # lines are counted as written: a soft wrap in an editor does not add a line, a hard line break does. A
    # change that would leave a longer definition is refused and the dictionary stays as it was.
    # A term is split when a second term is added beside an existing one whose name a neighbouring concept had
    # taken. Each of the two definitions then names the other term. That mutual naming is the mark that tells a
    # freshly split pair apart from a dead term when the audit later looks for terms no document uses: a term
    # whose definition points at its twin is a deliberate neighbour, not a leftover. A split whose definitions
    # do not both name the other term is refused in the same way.
    # A term cannot be split against itself. Two names that differ only in letter case or in surrounding spaces
    # are the same name, and a split of that kind would leave two sections under one heading. It is refused in
    # the same way, and the dictionary stays as it was.

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

    # guard: a split of a term against itself would leave two sections under one heading
    if is_split and term.strip().casefold() == sibling.strip().casefold():
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"split of {term!r} names itself as the sibling",
      )

  @staticmethod
  def _parse(text: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Split dictionary text into its preamble and its term sections.

    Args:
      text: Full dictionary text.

    Returns:
      The text before the first term heading, and the sections in file order as pairs of heading and full section
      text.
    """
    preamble = ""
    sections: list[tuple[str, str]] = []

    # every line opening with the heading prefix starts a section; the lines after it belong to it
    for line in text.splitlines(keepends = True):
      if line.startswith(_HEADING):
        sections.append((line[len(_HEADING):].strip(), line))
      elif sections:
        heading, body = sections[-1]
        sections[-1] = (heading, body + line)
      else:
        preamble += line
    return preamble, sections

  @staticmethod
  def _section(heading: str, definition: str) -> str:
    """
    Render the text of one term section.

    Args:
      heading: Term heading.
      definition: Term definition; surrounding whitespace is dropped.

    Returns:
      The section text: heading line, blank line, definition, closing blank line.
    """
    return f"{_HEADING}{heading}{_NL}{_NL}{definition.strip()}{_NL}{_NL}"

  @staticmethod
  def _sort_key(heading: str) -> tuple[str, str]:
    """
    Return the key that orders term headings.

    Args:
      heading: Term heading.

    Returns:
      A key ordering headings case-insensitively first and by code point second.
    """
    return heading.lower(), heading

  def _insert(self, sections: list[tuple[str, str]], heading: str, definition: str) -> None:
    """
    Insert a new term section at the place the heading order gives it.

    Args:
      sections: Heading and section text pairs, edited in place.
      heading: Heading of the new section.
      definition: Definition of the new term.

    Raises:
      JobRefusedError: Technical category when the heading the new section would be placed before appears more
        than once.
    """
    key = self._sort_key(heading)
    position = next(
      (index for index, (other, _) in enumerate(sections) if self._sort_key(other) > key), len(sections),
    )

    # guard: the anchor heading appears more than once — the dictionary is the audit's to repair
    if position < len(sections) and self._count(sections, sections[position][0]) > 1:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"anchor heading occurs more than once: {sections[position][0]!r}",
      )

    # a section appended after the last one is separated from it by a blank line
    if position == len(sections) and sections:
      last_heading, last_text = sections[-1]
      sections[-1] = (last_heading, last_text.rstrip(_NL) + _NL + _NL)
    sections.insert(position, (heading, self._section(heading, definition)))

  def _index_of(self, sections: list[tuple[str, str]], heading: str) -> int:
    """
    Locate the single section carrying a heading.

    Args:
      sections: Heading and section text pairs.
      heading: Heading of the section to find.

    Returns:
      Position of the section in the list.

    Raises:
      JobRefusedError: Technical category when the heading is absent or appears more than once.
    """
    count = self._count(sections, heading)

    # guard: the section to change must exist exactly once
    if count != 1:
      raise _job_response.JobRefusedError(
        category = _job_response.CATEGORY_TECHNICAL,
        reason = f"heading {'is absent' if count == 0 else 'occurs more than once'}: {heading!r}",
      )
    return next(index for index, (other, _) in enumerate(sections) if other == heading)

  @staticmethod
  def _count(sections: list[tuple[str, str]], heading: str) -> int:
    """
    Count the sections carrying a heading.

    Args:
      sections: Heading and section text pairs.
      heading: Heading to count.

    Returns:
      Number of sections whose heading equals the given one exactly.
    """
    return sum(1 for other, _ in sections if other == heading)
