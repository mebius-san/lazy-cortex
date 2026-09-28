"""
HTML-comment marker utilities for lazycortex-wiki managed regions.

Wiki owns bounded regions in markdown bodies that are delimited by
`<!-- auto:<marker_id>:start -->` / `<!-- auto:<marker_id>:end -->` pairs.
`Markers` exposes two operations: rewriting the inner content between an
existing pair, and ensuring the canonical See-also section exists before
rewriting it.
"""
from __future__ import annotations

import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Opening or closing line of a fenced code block: up to three spaces of indent, then a run of at
# least three backticks or tildes (CommonMark).
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

# Character that opens a backtick fence; its info string may not carry another one.
_BACKTICK = "`"


# Line endings the marker code recognises: a CRLF pair counts as one line break, like a bare LF.
_CRLF = "\r\n"
_LF = "\n"


def _inner_block(inner: str, eol: str) -> str:
  """
  Render region content as whole lines ending in `eol`, or an empty string when there is none.

  Args:
    inner: Region content, its lines separated by LF or CRLF.
    eol: Line ending every rendered line carries.

  Returns:
    The content with surrounding blank lines stripped and each line ending in `eol`.
  """
  stripped = inner.replace(_CRLF, _LF).strip(_LF)

  # guard: an empty region renders as nothing between the markers
  if not stripped:
    return ""
  return stripped.replace(_LF, eol) + eol


# ────────────────────────────────────────────────────────────────────────────
class CodeFence:
  """
  Line-by-line tracker of whether a markdown line sits inside a fenced code block.

  Guarantees:
    - A fence closes only on a line of the same character it opened with, at least as long as the
      opening run, with nothing but whitespace after it; a shorter run or the other fence
      character is reported as ordinary content, never a closing delimiter.
  """

  def __init__(self) -> None:
    """
    Start outside any fenced block.
    """
    # the fence character of the open block, empty while outside one
    self._char = ""

    # the length of the run that opened the current block
    self._length = 0

  @property
  def inside(self) -> bool:
    """
    True while a fenced block is open.
    """
    return bool(self._char)

  @property
  def closer(self) -> str:
    """
    Delimiter line that closes the open fenced block, or an empty string while outside one.
    """
    return self._char * self._length

  def step(self, line: str) -> bool:
    """
    Feed the next line and report whether it opens or closes a fenced block.

    Guarantees:
      - A fence closes only on a line made of the same character it opened with, at least as long as
        the opening run, with nothing after it but whitespace; a shorter run or the other fence
        character is reported as ordinary content, never a closing delimiter.

    Args:
      line: One markdown line, without its line ending.

    Returns:
      True when the line is a fence delimiter; False for any other line, fenced content included.
    """

    # Domain(wiki.terms):
    # # Where a fenced code block ends
    # A fenced block closes only on a line made of the same fence character it opened with, at least as
    # long as the opening run, with nothing after it but whitespace. A shorter run or the other fence
    # character inside the block is quoted content, so an example of one fence style inside another never
    # ends the block early.

    # Contract:
    # A fence closes only on a line made of the same character it opened with, at least as long as the
    # opening run, with nothing after it but whitespace; any other line — a shorter run or the other
    # fence character — is reported as ordinary content, NEVER as a closing delimiter.

    match = _FENCE_RE.match(line)

    # guard: not a fence-shaped line at all
    if match is None:
      return False
    run = match.group(1)
    rest = line[match.end():]

    # outside a block: any fence-shaped line opens one, unless a backtick info string carries a backtick
    if not self._char:
      # guard: an inline code span, not a fence
      if run[0] == _BACKTICK and _BACKTICK in rest:
        return False
      self._char, self._length = run[0], len(run)
      return True

    # guard: inside a block only a matching, long-enough, bare run closes it
    if run[0] != self._char or len(run) < self._length or rest.strip():
      return False
    self._char, self._length = "", 0
    return True


# ────────────────────────────────────────────────────────────────────────────
class Markers:
  """
  Read/write the HTML-comment-delimited managed regions in a markdown body.

  Each managed region is bounded by::

      <!-- auto:<marker_id>:start -->
      <inner content>
      <!-- auto:<marker_id>:end -->

  Wiki owns the inner content; everything outside the markers is operator
  territory and is preserved byte-for-byte.

  Guarantees:
    - Every byte outside a managed region, the marker lines themselves included, survives any
      operation on this class unchanged.

  Attributes:
    SEE_ALSO_MARKER_ID: Marker identifier for the canonical See-also managed region.
    SEE_ALSO_HEADING: Heading text for the canonical See-also section.
    SEE_ALSO_PROTECTED_TAG: Owner tag marking the See-also section as a protected cross-plugin region.
  """

  # Contract:
  # Every byte outside a managed region, including the two marker lines that delimit it,
  # MUST survive unchanged; only the span between the delimiters is ever rewritten.

  # Marker-id for the canonical See-also section.
  SEE_ALSO_MARKER_ID = "see-also"

  # Heading text for the canonical See-also section — an H1 protected-owner section.
  SEE_ALSO_HEADING = "# See also"

  # Owner tag on the first content line of the See-also section. Marks the H1 as a protected
  # cross-plugin region (`#protected/<owner>/<region>`) so any other file-mutating plugin
  # (e.g. review) preserves it verbatim; the wiki manages the bytes inside via the markers.
  SEE_ALSO_PROTECTED_TAG = "#protected/wiki/see-also"

  def _start_marker(self, marker_id: str) -> str:
    """
    Return the opening HTML comment for the given marker_id.

    Args:
      marker_id: Logical identifier for the managed region, e.g. `see-also`.

    Returns:
      Opening marker string, e.g. `<!-- auto:see-also:start -->`.
    """
    return f"<!-- auto:{marker_id}:start -->"

  def _end_marker(self, marker_id: str) -> str:
    """
    Return the closing HTML comment for the given marker_id.

    Args:
      marker_id: Logical identifier for the managed region.

    Returns:
      Closing marker string, e.g. `<!-- auto:see-also:end -->`.
    """
    return f"<!-- auto:{marker_id}:end -->"

  def find_region(self, text: str, marker_id: str) -> tuple[int, int] | None:
    """
    Locate the managed region a marker pair actually delimits.

    Guarantees:
      - A marker is recognised only on a line of its own, outside fenced code blocks; a marker
        mentioned inline in prose or quoted inside a fenced example never anchors a region.
      - For the `see-also` marker id, a pair whose start marker lies inside the `# See also` section
        is returned over any other pair present in the document.

    Args:
      text: Full document text (or body text) that may contain the markers.
      marker_id: Logical identifier of the managed region.

    Returns:
      `(start_idx, end_idx)` — offsets of the start marker and of the end marker that closes it — or
      `None` when no real marker pair is present.
    """

    # Contract:
    # A marker is recognised only on a line of its own outside fenced code blocks; a marker mentioned
    # inline in prose or quoted inside a fenced example NEVER anchors a region.

    # Contract:
    # For the `see-also` marker id, a pair whose start marker lies inside the `# See also` section
    # MUST win over any other pair present in the document; a pair outside that section is used only
    # when no pair inside it exists.

    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)
    fence = CodeFence()
    section = ""
    open_at: int | None = None
    open_in_see_also = False
    fallback: tuple[int, int] | None = None
    offset = 0

    # walk the lines once, pairing each own-line start marker with the next own-line end marker
    for line in text.splitlines(keepends = True):
      bare = line.rstrip("\r\n")
      stripped = bare.strip()
      line_start = offset
      offset += len(line)

      # guard: fence delimiters and fenced content are never markers
      if fence.step(bare) or fence.inside:
        continue

      # an H1 names the section the following lines belong to
      if bare.startswith("# "):
        section = stripped
      elif stripped == start:
        open_at = line_start + bare.index(start)
        open_in_see_also = section == self.SEE_ALSO_HEADING
      elif stripped == end and open_at is not None:
        pair = ( open_at, line_start + bare.index(end) )

        # guard: a pair inside the See-also section is the canonical one
        if open_in_see_also or marker_id != self.SEE_ALSO_MARKER_ID:
          return pair
        fallback = fallback or pair
        open_at = None

    # no canonical pair — fall back to the first own-line pair outside the section
    return fallback

  # ──────────────────────────────────────────────────────────────────────────
  def rewrite_between(self, text: str, marker_id: str, inner: str) -> str:
    """
    Replace the content between the start/end markers with `inner`.

    The operation is idempotent: calling this method twice with the same
    `inner` produces byte-identical output on the second call.  If the
    marker pair is absent from `text`, the text is returned unchanged —
    use `ensure_see_also` to insert the section when it may be missing.

    The rendered shape after replacement::

        <!-- auto:<marker_id>:start -->
        <inner lines>
        <!-- auto:<marker_id>:end -->

    Guarantees:
      - Rewriting a region with the same `inner` twice produces byte-identical output.
      - Text carrying no marker pair is returned unchanged, and no region is inserted.
      - A marker mentioned only in prose or inside a fenced code example is never mistaken for a region
        boundary, so an example of the marker syntax elsewhere in the text is left untouched.
      - A CRLF right after the start marker counts as its own line break, and the content placed
        between the markers takes that same line ending — CRLF after a CRLF marker line, LF
        otherwise — so a region in a mixed-ending document rewrites idempotently and is never
        glued onto the marker line.

    Args:
      text: Full document text (or body text) containing the markers.
      marker_id: Logical identifier of the managed region to rewrite.
      inner: New content to place between the markers, its lines separated by LF or CRLF.
        Leading/trailing newlines are normalized, and every line is re-emitted with the
        start-marker line's own ending, so the markers sit on their own lines.

    Returns:
      Document text with the inner region replaced.  Unchanged when the
      marker pair is not present.
    """

    # Domain(wiki.graph):
    # # Managed region ownership inside a node
    # A node is split between two owners: the bounded regions the wiki maintains and everything else,
    # which belongs to the operator. Each managed region carries a name of its own and is delimited by a
    # hidden start and an end marker, so the boundary survives arbitrary hand edits made around it.
    # Only the span between the two delimiters is the wiki's to replace; the delimiters themselves and
    # every byte outside them are preserved exactly. Refreshing a region is idempotent — the same
    # content yields the same node — so a region may be regenerated on every pass without churning the
    # document. A node carrying no delimiters has no managed region at all, and a refresh leaves it
    # untouched rather than guessing where the region would have belonged.

    # Contract:
    # Rewriting a region with the same content twice MUST produce byte-identical output,
    # so a refresh may run on every pass without churning the document.

    start = self._start_marker(marker_id)

    # Contract:
    # A document carrying no marker pair MUST be returned unchanged;
    # the managed region is never inserted here and never guessed at.

    # bound the managed region so everything outside it survives the rewrite
    region = self.find_region(text, marker_id)

    # guard: marker pair absent — caller must insert via ensure_see_also
    if region is None:
      return text
    start_idx, end_idx = region

    # Contract:
    # A CRLF pair right after the start marker counts as its line break, exactly like a bare LF;
    # the content spliced between the markers MUST use that same line ending — CRLF when the
    # start-marker line ends in CRLF, LF otherwise — so a region in a mixed-ending document
    # rewrites idempotently and its content is never glued onto the marker line.

    # Advance past the start marker; inserted lines take the start-marker line's own ending
    after_start = start_idx + len(start)
    eol = _CRLF if text.startswith(_CRLF, after_start) else _LF

    # consume the line ending after the start marker so the marker keeps its own line
    if text.startswith(eol, after_start):
      after_start += len(eol)

    # Normalise inner: strip surrounding newlines, then re-add exactly one trailing
    inner_block = _inner_block(inner, eol)

    # splice the new content in, leaving both markers and the surrounding document intact
    return text[:after_start] + inner_block + text[end_idx:]

  # ──────────────────────────────────────────────────────────────────────────
  def read_inner(self, text: str, marker_id: str = SEE_ALSO_MARKER_ID) -> str | None:
    """
    Return the content between the start/end markers, or `None` when absent.

    The returned content has surrounding newlines stripped, mirroring the
    normalization `rewrite_between` applies on write.

    Guarantees:
      - Reading a region back returns exactly the content a rewrite placed in it.
      - A marker mentioned only in prose or inside a fenced code example is never mistaken for a region
        boundary, so it is never read back as if it delimited a region.
      - A CRLF or LF right after the start marker is consumed as the marker's own line ending, and
        every CRLF inside the returned span is turned into LF, so an LF region and a CRLF region
        holding the same logical lines are read back identically.

    Args:
      text: Full document text (or body text) that may contain the markers.
      marker_id: Logical identifier of the managed region to read; defaults
        to the canonical See-also region.

    Returns:
      The inner content as LF-joined lines with surrounding newlines stripped, or `None` when
      the marker pair is not present.
    """

    # Contract:
    # Reading a region MUST return exactly the content a rewrite placed in it,
    # normalised identically on both sides.

    region = self.find_region(text, marker_id)

    # guard: marker pair absent
    if region is None:
      return None

    # Contract:
    # A CRLF or LF right after the start marker MUST be consumed as the marker's own line ending,
    # never returned as content, and the returned span MUST have every CRLF turned into LF — the
    # exact content a rewrite with that content would have placed, for LF and CRLF regions alike.

    # walk past the start marker to the first byte the caller actually owns
    start_idx, end_idx = region
    after_start = start_idx + len(self._start_marker(marker_id))

    # consume the line ending after the start marker so it is not read as content
    for eol in (_CRLF, _LF):
      if text.startswith(eol, after_start):
        after_start += len(eol)
        break

    # hand back the span between the markers as LF lines, normalised the way a write leaves it
    return text[after_start:end_idx].replace(_CRLF, _LF).strip(_LF)

  # ──────────────────────────────────────────────────────────────────────────
  def ensure_see_also(self, body: str, inner: str) -> str:
    """
    Ensure the `# See also` section with markers exists and contains `inner`.

    If the heading + marker pair is already present, only the inner content
    is rewritten (idempotent).  If absent, the section is appended to the end
    of `body`::

        # See also
        #protected/wiki/see-also
        <!-- auto:see-also:start -->
        <inner lines>
        <!-- auto:see-also:end -->

    Guarantees:
      - A body never ends up with more than one canonical See-also section.
      - A newly created section is placed at the end of the body.
      - A marker mentioned only in prose or inside a fenced code example is never mistaken for the
        existing section, so it never causes a second See-also section to be created.
      - A body ending inside a fenced code block left open has that block closed with a matching
        delimiter before the new section is appended, so the section is recognised on the next call
        and repeated calls never add a second one.
      - A newly appended section, including a closing fence line added for an unclosed fence, uses
        the body's majority line ending — CRLF when CRLF line breaks outnumber bare LF ones, LF
        otherwise.

    Args:
      body: Markdown body text (the part after the frontmatter fences, or the
        entire document when there is no frontmatter).
      inner: Lines to place between the markers — typically the
        `see_also` entries from the curator result, joined by newlines.

    Returns:
      Body text with the See-also section present and up-to-date.
    """

    # Domain(wiki.graph):
    # # Canonical See-also section of a node
    # Every node carries exactly one canonical See-also section, holding its outbound links to
    # neighbouring nodes. The section is created the first time a node has links to show and is
    # refreshed in place from then on, so a node never accumulates a second copy of it.
    # Its first content line is an ownership tag naming the wiki as the section's owner: any other tool
    # that rewrites the same documents reads that tag as a claim and preserves the whole section, while
    # the wiki itself manages only the delimited span inside it.
    # The section belongs at the end of the body — links are a trailing appendix of a node, never an
    # interruption of the prose above them.

    # Contract:
    # A body MUST never carry more than one canonical See-also section; an existing
    # section is refreshed in place and NEVER duplicated by a second copy.

    mid = self.SEE_ALSO_MARKER_ID
    start = self._start_marker(mid)
    end = self._end_marker(mid)

    # guard: section already present — just rewrite the inner
    if self.find_region(body, mid) is not None:
      return self.rewrite_between(body, mid, inner)

    # Contract:
    # A newly appended section, and a closing fence line added for a fence left open, MUST use
    # the body's majority line ending — CRLF when CRLF line breaks outnumber bare LF ones,
    # LF otherwise — so a CRLF body is never given LF-terminated lines.

    # a new section takes the body's majority line ending, so a CRLF body is not given LF lines
    crlf = body.count(_CRLF)
    eol = _CRLF if crlf > body.count(_LF) - crlf else _LF

    # Build the normalised inner block
    inner_block = _inner_block(inner, eol)

    # Contract:
    # A fenced code block left open to the end of the body is closed with a matching delimiter line
    # before the new section is appended, keeping the appended section outside any fence so it is
    # recognised as the canonical section on the next call and a second section is NEVER created.

    # a fenced block left open to the end of the body would swallow the section, so it is closed first
    fence = CodeFence()
    for line in body.splitlines():
      fence.step(line)
    if fence.inside:
      body = (body if body.endswith(_LF) else body + eol) + fence.closer + eol

    # assemble the whole section so later runs find the heading, tag and markers
    section = (
      f"{eol}{self.SEE_ALSO_HEADING}{eol}"
      f"{self.SEE_ALSO_PROTECTED_TAG}{eol}"
      f"{start}{eol}"
      f"{inner_block}"
      f"{end}{eol}"
    )

    # Contract:
    # A newly created See-also section MUST be placed at the end of the body,
    # never inserted between existing prose.

    # Append after a trailing newline (ensure exactly one blank separator)
    if body.endswith(_LF):
      return body + section
    return body + eol + section
