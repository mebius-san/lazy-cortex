"""Markdown structure recognition for lazy-review.

The parser splits a document into its frontmatter and body, then
enumerates H1 sections in the body. Each section is annotated with
the optional ownership tag (`#expert/<flat-name>`) that marks meta
sections owned by a specific expert.

Round-trip guarantee: `doc.frontmatter_text + doc.body` reproduces
the input byte-for-byte. Sections are pointers into the body; mutating
helpers live elsewhere (`body.py`).
"""
from __future__ import annotations

from typing import NamedTuple

import re
from dataclasses import dataclass, field

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import frontmatter as _fm  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from keys import Tag  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# ---------------------------------------------------------- name flattening


_TAG_PREFIX = Tag.EXPERT_PREFIX
_TAG_LINE = re.compile(rf"^{re.escape(_TAG_PREFIX)}([A-Za-z0-9._-]+)\s*$")

# The review-owned `# History` section is identified by THIS tag on its first
# non-empty content line — never by its H1 title. The `#protected/` form marks
# it persistent under the cross-plugin protected-section contract: it survives
# every pass, including finalize.
_HISTORY_TAG = Tag.HISTORY


# ----------------------------------------------------- code-fence stripping


# an opening code-fence line: up to three spaces of indent, then a run of three or more backticks
# or tildes, then the info string
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

# one physical line with its newline kept; the last line may lack one
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+$")

# a fence opened with backticks carries no backtick in its info string (CommonMark)
_BACKTICK = "`"

# a fence line may be indented by at most this many spaces (CommonMark)
_MAX_FENCE_INDENT = 3

# a comment block opens on a line starting (after up to three spaces) with `<!--` (CommonMark HTML
# block type 2) or `%%` (Obsidian block comment) and ends on the first line holding its closer; a
# mid-line opener, or one indented four or more spaces, is ordinary text
_COMMENT_START_RE = re.compile(r" {0,3}(<!--|%%)")
_COMMENT_CLOSERS = { "<!--": "-->", "%%": "%%" }

# a closer may overlap its opener by this many characters, so `<!-->` and `<!--->` close at once
_CLOSER_OVERLAP = 2


class Chunk(NamedTuple):
  """
  One run of a markdown text: either a whole fenced code block or the text between fences.

  Attributes:
    text: The chunk's raw text; the chunks of a text concatenate back to it byte-for-byte.
    fenced: `True` for a fenced code block, fence lines included.
    info: The fenced block's info string (`diff`, `python`, …), stripped; empty for plain text.
    closed: `True` when the fenced block has its closing fence line.
  """

  text: str
  fenced: bool
  info: str = ""
  closed: bool = False


def _closes_fence(line: str, fence: str) -> bool:
  """
  Report whether `line` closes a code block opened with `fence`.

  Args:
    line: One physical line, its line ending already removed.
    fence: The opening fence's run of backticks or tildes.

  Returns:
    `True` when the line is a run of the same character at least as long as `fence`, with up to
    three spaces before it and only horizontal whitespace after it.
  """
  stripped = line.strip(" \t")
  return (
      len(line) - len(line.lstrip(" ")) <= _MAX_FENCE_INDENT
      and len(stripped) >= len(fence)
      and stripped == fence[0] * len(stripped)
  )


def _comment_left_open(line: str, closer: str | None) -> str | None:
  """
  Track an HTML or Obsidian comment block across one plain line.

  Args:
    line: One physical line outside any code fence, its line ending already removed.
    closer: The closing token of the comment still open before `line`, or `None`.

  Returns:
    The closing token of the comment still open after `line`, or `None` when none is.
  """
  # guard: inside a comment, the first line holding its closer ends it
  if closer is not None:
    return None if closer in line else closer
  start = _COMMENT_START_RE.match(line)

  # guard: the line opens no comment
  if start is None:
    return None
  closer = _COMMENT_CLOSERS[start.group(1)]
  return None if line.find(closer, start.start(1) + _CLOSER_OVERLAP) >= 0 else closer


def split_fenced(text: str) -> list[Chunk]:
  """
  Split `text` into fenced code blocks and the plain runs between them.

  Guarantees:
    - Concatenating the returned chunks' `text` reproduces `text` byte-for-byte.
    - A fenced chunk spans whole lines, from its opening fence line through its closing fence
      line, or through the end of `text` when the fence is never closed.
    - Both backtick and tilde fences are recognised, and a fence closes only on a run of its own
      character at least as long as its opening run.

  Args:
    text: Markdown text, with LF or CRLF line endings.

  Returns:
    The chunks in document order; plain chunks are never adjacent to one another.
  """

  # Contract:
  # Concatenating the chunks' `text` MUST reproduce the input byte-for-byte; a fenced chunk MUST
  # span whole lines from its opening fence through its closing fence (or the end of the text
  # when unclosed); a fence MUST close only on a run of its own character at least as long.

  # Domain(review.markup):
  # # What counts as a code fence
  # A code fence opens on a line holding a run of at least three backticks or three tildes,
  # indented by at most three spaces, and closes on the next line holding only a run of the same
  # character at least as long. A fence never closed runs to the end of the document, which is
  # how a reader renders it. Everything between the two fence lines is literal content.

  lines = _LINE_RE.findall(text)
  chunks: list[Chunk] = []
  plain: list[str] = []
  comment: str | None = None
  i = 0
  while i < len(lines):
    line = lines[i].rstrip("\r\n")
    opening = None if comment else _FENCE_OPEN_RE.match(line)

    # guard: inside a comment, or not an opening fence line (or a backtick fence whose info
    # string holds a backtick)
    if opening is None or (opening.group(1)[0] == _BACKTICK and _BACKTICK in opening.group(2)):
      comment = _comment_left_open(line, comment)
      plain.append(lines[i])
      i += 1
      continue

    # the block runs to its closing fence line, or to the end of the text when unclosed
    fence = opening.group(1)
    j = i + 1
    while j < len(lines) and not _closes_fence(lines[j].rstrip("\r\n"), fence):
      j += 1
    if plain:
      chunks.append(Chunk("".join(plain), False))
      plain = []
    chunks.append(Chunk("".join(lines[i:j + 1]), True, opening.group(2).strip(), j < len(lines)))
    i = j + 1

  # the plain run after the last fence
  if plain:
    chunks.append(Chunk("".join(plain), False))
  return chunks


def sub_outside_fences(
    pattern: re.Pattern[str],
    repl: str | Callable[[re.Match[str]], str],
    text: str,
    *,
    count: int = 0,
) -> str:
  """
  Substitute `pattern` in `text` everywhere except inside fenced code blocks.

  Guarantees:
    - No match starts, ends, or runs inside a fenced code block; fenced blocks are returned
      byte-for-byte.

  Args:
    pattern: Compiled pattern to substitute.
    repl: Replacement string or function, as for `re.sub`.
    text: Markdown text to rewrite.
    count: Maximum number of substitutions across the whole text; `0` means no limit.

  Returns:
    `text` with the substitutions applied outside fenced code blocks.
  """
  out: list[str] = []
  remaining = count
  for chunk in split_fenced(text):
    # guard: fenced content is literal, and a spent budget leaves the rest untouched
    if chunk.fenced or (count and remaining == 0):
      out.append(chunk.text)
      continue
    new_text, done = pattern.subn(repl, chunk.text, count = remaining)
    out.append(new_text)

    # an unlimited run keeps `remaining` at 0: a negative count would make `subn` replace nothing
    if count:
      remaining -= done
  return "".join(out)


def close_open_fence(text: str, newline: str = "\n") -> str:
  """
  Append the closing fence line a fenced code block left open at the end of `text` needs.

  Text appended after an unclosed fence would otherwise land inside the code block.

  Args:
    text: Markdown text, possibly ending inside an unclosed fence.
    newline: The line ending to write.

  Returns:
    `text` unchanged when no fence is left open, else `text` with the matching closing fence line.
  """
  chunks = split_fenced(text)

  # guard: nothing is left open at the end of the text
  if not chunks or not chunks[-1].fenced or chunks[-1].closed:
    return text
  opening = _FENCE_OPEN_RE.match(chunks[-1].text.splitlines()[0])
  fence = opening.group(1) if opening else "```"
  return text + ("" if text.endswith("\n") else newline) + fence + newline


def line_ending(text: str) -> str:
  """
  Pick the line ending new lines written into `text` should carry.

  Args:
    text: Markdown text, with LF, CRLF, or mixed line endings.

  Returns:
    `"\\r\\n"` when every line break outside fenced code blocks is CRLF, else `"\\n"`.
  """
  plain = "".join(chunk.text for chunk in split_fenced(text) if not chunk.fenced)
  return "\r\n" if "\r\n" in plain and plain.count("\n") == plain.count("\r\n") else "\n"


def h1_headings(text: str) -> list[tuple[int, int, str]]:
  """
  Locate every H1 heading line of `text` that sits outside a fenced code block.

  Args:
    text: Markdown text to scan.

  Returns:
    One `(start, end, title)` tuple per heading in document order, where `start` and `end` are
    the offsets of the heading match in `text` and `title` is the heading text.
  """
  headings: list[tuple[int, int, str]] = []
  offset = 0
  for chunk in split_fenced(text):
    # a `# ` line inside a fence is literal content, never a heading
    if not chunk.fenced:
      headings.extend(
          (offset + m.start(), offset + m.end(), m.group(1).strip())
          for m in _H1_LINE.finditer(chunk.text)
      )
    offset += len(chunk.text)
  return headings


def strip_code_fences(body: str) -> str:
  """
  Return `body` with every line inside a code fence replaced by an empty line.

  Fence delimiters themselves become empty lines too. Line numbers are preserved, so a line
  number computed on the result names the same line in `body`; character offsets are not.

  The protocol uses code fences for two things callers MUST treat as inert body content:

  - `diff`-style edit markers (a `[!question]` callout removed by a main writer in
    `edit_marker_style: diff` lives inside a ` ```diff ``` ` fence as `- > [!question] ...`
    lines).
  - Plain fence-wrapped examples of callout syntax in body prose.

  Neither case is a real callout. Predicates that decide "is there an open #review/question?"
  must ignore them — otherwise documents deadlock forever on stale or example markup.

  Guarantees:
    - The result has the same number of lines as `body`, and each line keeps its line
      number, so a line number computed against the result names the same line in `body`.
      Character and byte offsets are NOT preserved.

  Args:
    body: Raw document body text, possibly containing code fences.

  Returns:
    Body text with all fenced content replaced by blank lines, fences included.
  """

  # Contract:
  # The result has the same number of lines as `body`, and each line keeps its line
  # number, so a line number computed against the result names the same line in `body`.
  # Character and byte offsets are NOT preserved.

  # Domain(review.markup):
  # # Fenced content is inert to markup detection
  # A code fence's content is never a live callout, tick, or candidate, no matter what it
  # visually resembles — a diff-style edit block quoting a removed callout, or a fence-wrapped
  # example of callout syntax in prose, are both body content the writer meant literally, never
  # a signal to act on. Every predicate that scans a document for its own markup treats fenced
  # content as blank; skipping this step lets a stale or illustrative marker deadlock the
  # review loop forever, since it never resolves the way a live one would.

  return "".join(
      "\n" * chunk.text.count("\n") if chunk.fenced else chunk.text for chunk in split_fenced(body)
  )


def flatten_expert_name(dispatch_name: str) -> str:
  """
  Render an expert dispatch name as the Obsidian-tag-safe flat form.

  Obsidian tag syntax forbids dots, so the forward mapping replaces every `.` with `-`.
  The inverse mapping is ambiguous and is never attempted: callers flatten their dispatch
  name forward and compare strings.

  Args:
    dispatch_name: Expert dispatch name in dot-namespace form, e.g. `lazy-review.doc_doctor`.

  Returns:
    Flat form with every `.` replaced by `-`.
  """
  return dispatch_name.replace(".", "-")


# ---------------------------------------------------------- data classes


@dataclass
class Section:
  """
  One H1 section of the body.

  `content` spans from immediately after the heading line through (but not including) the
  next H1 heading, including any H2+ subsections nested inside. `owner_expert` is the flat
  tag name (no dot restoration) when an ownership tag is present, else `None`.

  Attributes:
    title: Heading text without the leading `# ` marker.
    heading_line: Raw heading line including its trailing newline when present.
    content: Section body text following the heading line.
    owner_expert: Flat expert name from the ownership tag, or `None` when absent.
  """

  title: str
  heading_line: str
  content: str
  owner_expert: str | None = None

  @property
  def is_meta_section(self) -> bool:
    """
    True when this section is owned by a specific expert.
    """
    return self.owner_expert is not None


@dataclass
class Document:
  """
  Parsed representation of a review document.

  Callers read sections and metadata from this object without re-parsing the source text.
  Concatenating `frontmatter_text` and `body` reproduces the original input byte-for-byte.

  Guarantees:
    - Concatenating `frontmatter_text` and `body` always reproduces the original parsed text
      byte-for-byte.

  Attributes:
    meta: Frontmatter key-value pairs parsed from the YAML block.
    frontmatter_text: Raw frontmatter block including its opening and closing fences.
    body: Document body after the frontmatter block.
    sections: H1 sections enumerated from the body, in document order.
    top_heading: First H1 section, or `None` when the body has no H1 headings.
    history_section: Historian-owned H1 section identified by its ownership tag, or `None`.
  """

  # Contract:
  # `frontmatter_text + body` always reproduces the original parsed text byte-for-byte.

  meta: dict[str, str]
  frontmatter_text: str
  body: str
  sections: list[Section] = field(default_factory=list)
  top_heading: Section | None = None
  history_section: Section | None = None


# ------------------------------------------------------------------- parse


_H1_LINE = re.compile(r"^# (.+?)\s*$", re.MULTILINE)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
  """
  Split `text` into its frontmatter metadata, raw frontmatter block, and body.

  `frontmatter_text` includes the opening and closing fences; concatenating it with
  `body` reproduces the original input byte-for-byte.

  Args:
    text: Full document text including the YAML frontmatter block.

  Returns:
    A tuple of `(meta, frontmatter_text, body)`.
  """
  meta, body = _fm.parse(text)
  frontmatter_text = text[: len(text) - len(body)]
  return meta, frontmatter_text, body


def _detect_owner(section_body: str) -> str | None:
  """
  Return the flat expert name from the ownership tag on the first non-empty line.

  The tag MUST be on its own line; prose or callouts above the tag break detection
  (deliberate per § Section ownership tag).

  Args:
    section_body: Section content text following the H1 heading line.

  Returns:
    Flat expert name (e.g. `lazy-review-historian`) when the first non-empty line is an
    `#expert/<flat-name>` tag, or `None` otherwise.
  """
  for raw in section_body.splitlines():
    stripped = raw.strip()

    # guard: skip leading blank lines so the ownership tag is matched on the first line with content
    if not stripped:
      continue
    match = _TAG_LINE.match(stripped)
    if match:
      return match.group(1)
    return None  # first non-empty line was not a tag
  return None


def is_historian_section(section_content: str) -> bool:
  """
  Return `True` when the first non-empty line of `section_content` is the History tag.

  The History tag is `#protected/review/history`. The History section is recognised by
  this tag, never by its H1 title: a document whose own prose carries an H1 titled
  `History` must not be mistaken for the review-owned History section.

  Args:
    section_content: Section body text following the H1 heading line.

  Returns:
    `True` when the first non-empty line matches the History ownership tag, `False`
    otherwise.
  """
  for raw in section_content.splitlines():
    stripped = raw.strip()

    # guard: skip leading blank lines so the History tag is matched on the first line with content
    if not stripped:
      continue
    return stripped == _HISTORY_TAG
  return False


def _enumerate_sections(body: str) -> list[Section]:
  """
  Produce one `Section` per H1 heading found in `body`.

  Each section's `content` spans from immediately after the heading line through the byte
  just before the next H1 heading, or EOF for the last section.

  Args:
    body: Document body text to scan for H1 headings.

  Returns:
    Ordered list of `Section` objects, one per H1 heading, empty when none are present.
  """
  headings = h1_headings(body)
  if not headings:
    return []
  sections: list[Section] = []
  for i, (start, match_end, title) in enumerate(headings):
    # Heading line includes its trailing newline if present.
    line_end = body.find("\n", match_end)
    if line_end == -1:
      heading_line_end = len(body)
    else:
      heading_line_end = line_end + 1
    heading_line = body[start:heading_line_end]
    next_start = headings[i + 1][0] if i + 1 < len(headings) else len(body)
    content = body[heading_line_end:next_start]
    owner = _detect_owner(content)
    sections.append(
        Section(
            title=title,
            heading_line=heading_line,
            content=content,
            owner_expert=owner,
        )
    )
  return sections


def find_history(body: str) -> Section | None:
  """
  Return the review-owned `# History` H1 section of `body`, identified by its ownership tag.

  Detection is tag-based, not title-based; see `is_historian_section` for the matching
  rule.

  Args:
    body: Document body text to search.

  Returns:
    The review-owned History `Section`, or `None` when no section carries the tag.
  """
  return next(
      (s for s in _enumerate_sections(body) if is_historian_section(s.content)),
      None,
  )


def parse(text: str) -> Document:
  """
  Parse `text` into a `Document`.

  Args:
    text: Full document text including the YAML frontmatter block.

  Returns:
    Populated `Document` with frontmatter metadata, body, enumerated sections, and
    the resolved `top_heading` and `history_section` fields.
  """
  meta, fm_text, body = _split_frontmatter(text)
  sections = _enumerate_sections(body)
  top = sections[0] if sections else None
  history = next((s for s in sections if is_historian_section(s.content)), None)
  return Document(
      meta=meta,
      frontmatter_text=fm_text,
      body=body,
      sections=sections,
      top_heading=top,
      history_section=history,
  )
