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
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re
from dataclasses import dataclass, field

import frontmatter as _fm
from keys import Tag

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ---------------------------------------------------------- name flattening


_TAG_PREFIX = Tag.EXPERT_PREFIX
_TAG_LINE = re.compile(rf"^{re.escape(_TAG_PREFIX)}([A-Za-z0-9._-]+)\s*$")

# The historian's owned section is identified by THIS tag on its first
# non-empty content line — never by its H1 title. `HISTORIAN_FLAT` is the
# flat (dot→dash) form of the `lazy-review.historian` dispatch name.
HISTORIAN_FLAT = "lazy-review-historian"
_HISTORIAN_TAG = f"{_TAG_PREFIX}{HISTORIAN_FLAT}"


# ----------------------------------------------------- code-fence stripping


_FENCE_RE = re.compile(r"^```")


def strip_code_fences(body: str) -> str:
  """
  Return `body` with every line inside a triple-backtick code fence replaced by an empty line.

  Fence delimiters themselves become empty lines too. Line positions are preserved so byte
  offsets stay aligned (callers that use the result for regex search get the same line numbers).

  The protocol uses code fences for two things callers MUST treat as inert body content:

  - `diff`-style edit markers (a `[!question]` callout removed by a main writer in
    `edit_marker_style: diff` lives inside a ` ```diff ``` ` fence as `- > [!question] ...`
    lines).
  - Plain fence-wrapped examples of callout syntax in body prose.

  Neither case is a real callout. Predicates that decide "is there an open #review/question?"
  must ignore them — otherwise documents deadlock forever on stale or example markup.

  Args:
    body: Raw document body text, possibly containing triple-backtick code fences.

  Returns:
    Body text with all fenced content replaced by blank lines, fences included.
  """
  out: list[str] = []
  in_fence = False
  for line in body.split("\n"):
    if _FENCE_RE.match(line):
      in_fence = not in_fence
      out.append("")
      continue
    out.append("" if in_fence else line)
  return "\n".join(out)


def flatten_expert_name(dispatch_name: str) -> str:
  """
  Render an expert dispatch name as the Obsidian-tag-safe flat form.

  Obsidian tag syntax forbids dots, so the forward mapping replaces every `.` with `-`.
  The inverse mapping is ambiguous and is never attempted: callers flatten their dispatch
  name forward and compare strings.

  Args:
    dispatch_name: Expert dispatch name in dot-namespace form, e.g. `lazy-review.historian`.

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

  Attributes:
    meta: Frontmatter key-value pairs parsed from the YAML block.
    frontmatter_text: Raw frontmatter block including its opening and closing fences.
    body: Document body after the frontmatter block.
    sections: H1 sections enumerated from the body, in document order.
    top_heading: First H1 section, or `None` when the body has no H1 headings.
    history_section: Historian-owned H1 section identified by its ownership tag, or `None`.
  """

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
  Return `True` when the first non-empty line of `section_content` is the historian tag.

  The historian tag is `#expert/lazy-review-historian`, with or without a trailing
  `/<section-id>`. The historian section is recognised by this tag, never by its H1
  title: a document whose own prose carries an H1 titled `History` must not be mistaken
  for the historian's owned section.

  Args:
    section_content: Section body text following the H1 heading line.

  Returns:
    `True` when the first non-empty line matches the historian ownership tag, `False`
    otherwise.
  """
  for raw in section_content.splitlines():
    stripped = raw.strip()
    # guard: skip leading blank lines so the historian tag is matched on the first line with content
    if not stripped:
      continue
    if stripped == _HISTORIAN_TAG:
      return True
    return stripped.startswith(f"{_HISTORIAN_TAG}/")
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
  matches = list(_H1_LINE.finditer(body))
  if not matches:
    return []
  sections: list[Section] = []
  for i, m in enumerate(matches):
    title = m.group(1).strip()
    # Heading line includes its trailing newline if present.
    line_end = body.find("\n", m.end())
    if line_end == -1:
      heading_line_end = len(body)
    else:
      heading_line_end = line_end + 1
    heading_line = body[m.start():heading_line_end]
    next_start = matches[i + 1].start() if i + 1 < len(matches) else len(body)
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
  Return the historian-owned H1 section of `body`, identified by its ownership tag.

  Detection is tag-based, not title-based; see `is_historian_section` for the matching
  rule.

  Args:
    body: Document body text to search.

  Returns:
    The historian-owned `Section`, or `None` when no section carries the tag.
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
