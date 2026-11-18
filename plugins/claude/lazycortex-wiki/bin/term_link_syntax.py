from __future__ import annotations

import re
from dataclasses import dataclass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final, Self

  from collections.abc import Iterable


# A wikilink, with its inner text.
WIKILINK_RE: Final = re.compile(r"\[\[([^\[\]\n]+?)\]\]")

# Separators between a link's target and its text: plain, and escaped inside a table row.
PIPE: Final = "|"
ESCAPED_PIPE: Final = "\\|"
# The mark opening a heading anchor in a link's target.
_ANCHOR = "#"
# The separator between the segments of a link's target.
SLASH: Final = "/"

# Word boundary a named word must meet: no letter, digit, underscore, slash or hyphen beside it — the hyphen-minus,
# the hyphen U+2010, the non-breaking hyphen U+2011, the soft hyphen U+00AD, the small hyphen-minus U+FE63 and the
# fullwidth hyphen-minus U+FF0D, never a dash — and no dot leading into or out of a word. The pattern stays raw: the
# regex engine itself reads each `\uXXXX` escape.
_BEFORE = r"(?<![\w/\-\u2010\u2011\u00ad\ufe63\uff0d])(?<!\.)"
_AFTER = r"(?![\w/\-\u2010\u2011\u00ad\ufe63\uff0d])(?!\.\w)"
# The whitespace between two words of a named word: a run of spaces and tabs, never a line break.
_WORD_GAP = r"[ \t]+"
# A pipe as `re.escape` writes it in a pattern, and the pattern that also takes its escaped form.
_PIPE_PATTERN = re.escape(PIPE)
_ANY_PIPE_PATTERN = r"\\?\|"


def compile_word_pattern(word: str) -> re.Pattern[str] | None:
  """
  Compile the pattern that finds the occurrences of a named word in text.

  Args:
    word: The word as it stands in the text.

  Returns:
    The pattern, matching without letter case; `None` for a blank word, which names nothing.
  """
  tokens = word.split()

  # guard: a blank word names nothing
  if not tokens:
    return None

  # a pipe of the word also matches its escaped form, which a table row writes inside one cell
  body = _WORD_GAP.join(re.escape(token) for token in tokens).replace(_PIPE_PATTERN, _ANY_PIPE_PATTERN)
  return re.compile(_BEFORE + body + _AFTER, re.IGNORECASE)


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class TermLink:
  """
  One wikilink into a dictionary directory, split into its parts.

  Attributes:
    prefix: The dictionary directory and its slash, as written.
    rest: The part of the target after the prefix, anchor excluded.
    anchor: The heading anchor of the target, with its `#`, or empty.
    separator: The pipe before the link text, plain or escaped, or empty when the link has no text.
    text: The link text, or `None` when the link has none.
  """

  # The dictionary directory and its slash, as written
  prefix: str
  # The part of the target after the prefix, anchor excluded
  rest: str
  # The heading anchor of the target, with its `#`, or empty
  anchor: str
  # The pipe before the link text, plain or escaped, or empty when the link has no text
  separator: str
  # The link text, or None when the link has none
  text: str | None

  @property
  def path(self) -> str:
    """
    Target of the link as written, anchor excluded.
    """
    return self.prefix + self.rest

  @classmethod
  def parse(cls, inner: str, dictionary_dir: str) -> Self | None:
    """
    Split a wikilink's inner text, when it points into the dictionary directory.

    Args:
      inner: Text between the link's brackets.
      dictionary_dir: Repo-relative dictionary directory.

    Returns:
      The link's parts, or `None` for a link pointing elsewhere.
    """
    path, anchor, separator, text = cls.split(inner)
    prefix = f"{dictionary_dir}{SLASH}"

    # guard: a link outside the dictionary directory is someone else's
    if not path.casefold().startswith(prefix.casefold()) or len(path) == len(prefix):
      return None
    return cls(
      prefix = path[:len(prefix)], rest = path[len(prefix):], anchor = anchor, separator = separator, text = text,
    )

  @staticmethod
  def split(inner: str) -> tuple[str, str, str, str | None]:
    """
    Split a wikilink's inner text into its target path, anchor, separator and text.

    Guarantees:
      - The four parts lose nothing: path, anchor, separator and text, joined in that order with an absent text taken
        as empty, give back the inner text byte for byte.

    Args:
      inner: Text between the link's brackets.

    Returns:
      The target path without its anchor; the anchor with its `#`, or empty; the pipe before the link text, plain or
      escaped, or empty when the link has no text; and the link text, or `None` when the link has none.
    """

    # Contract:
    # The four parts lose nothing: path, anchor, separator and text, joined in that order with an absent text taken
    # as empty, give back the inner text byte for byte.

    # Domain(wiki.terms):
    # # Wikilink target, anchor and text
    # A wikilink is read from left to right. The first pipe ends the link's target, and everything after it is the
    # link text. Inside a table row a pipe has to be escaped with a backslash to survive the row, so an escaped pipe
    # ends the target exactly as a plain one does, and the backslash belongs to the separator, never to the target.
    # The first hash mark of the target opens its anchor, and everything after it up to the pipe is the anchor. A hash
    # mark that appears only in the link text is just text and opens nothing.

    # the first pipe, plain or escaped, ends the target; the first `#` of the target opens its anchor
    pipe = inner.find(PIPE)
    separator = "" if pipe < 0 else ESCAPED_PIPE if inner[pipe - 1:pipe] == "\\" else PIPE
    target = inner if pipe < 0 else inner[:pipe - len(separator) + 1]
    path, hash_mark, anchor = target.partition(_ANCHOR)
    return path, hash_mark + anchor, separator, None if pipe < 0 else inner[pipe + 1:]

  def render(self, stem: str) -> str:
    """
    Render the link pointing at a stem, its text kept.

    Args:
      stem: The stem the link points at.

    Returns:
      The full wikilink.
    """
    return f"[[{self.prefix}{stem}{self.anchor}{self.separator}{self.text or ''}]]"

  def unwrapped(self) -> str:
    """
    Return the text that stands in place of the link once it is removed.

    Returns:
      The link text; when it has none, the last segment of its target, or, for a link to a heading, the last
      non-empty segment of its target followed by the heading anchor with its `#`.
    """

    # Domain(wiki.terms):
    # # Words left by a removed term link
    # A link that is removed leaves the words a reader saw in its place. A link with display text leaves that text.
    # A link without display text leaves the last segment of its target. When such a bare link points at a heading,
    # it leaves the last segment that names something followed by the heading anchor, so two links to different
    # headings never leave the same words. This is the same reading the spec catalog's decision comparison gives
    # such a link, so a decision whose term link was removed in one copy still matches the other copy.

    # a link with text leaves that text; a bare link without a heading leaves the last segment of its target
    if self.text is not None:
      return self.text
    if not self.anchor:
      return self.rest.rsplit(SLASH, 1)[-1]

    # a bare link to a heading leaves the last segment that names something, followed by its anchor
    return next(( segment for segment in reversed(self.path.split(SLASH)) if segment ), "") + self.anchor

  @classmethod
  def unlink_all(cls, text: str, dictionary_dirs: Iterable[str]) -> str:
    """
    Replace every wikilink into a dictionary directory by the text that stands in its place.

    Guarantees:
      - Every byte outside the replaced term links is preserved, and a wikilink pointing outside the given
        directories is never touched; with no directories the text comes back unchanged.

    Args:
      text: Any text.
      dictionary_dirs: Repo-relative dictionary directories.

    Returns:
      The text with each such link unwrapped; every other link and every other byte unchanged.
    """

    # Contract:
    # Every byte outside the replaced term links is preserved exactly, and a wikilink that points
    # outside the given directories is never touched. With no directories the text is returned
    # unchanged.

    dirs = tuple(dictionary_dirs)

    # guard: no dictionary directory, so no link is a term link
    if not dirs:
      return text

    # the first directory a link parses against decides its replacement; a link into no directory stays
    def unlink(match: re.Match[str]) -> str:
      for directory in dirs:
        link = cls.parse(match.group(1), directory)
        if link is not None:
          return link.unwrapped()
      return match.group(0)

    # every wikilink in the text is offered to the replacement
    return WIKILINK_RE.sub(unlink, text)
