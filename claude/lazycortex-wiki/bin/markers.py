"""
HTML-comment marker utilities for lazycortex-wiki managed regions.

Wiki owns bounded regions in markdown bodies that are delimited by
`<!-- auto:<marker_id>:start -->` / `<!-- auto:<marker_id>:end -->` pairs.
`Markers` exposes two operations: rewriting the inner content between an
existing pair, and ensuring the canonical See-also section exists before
rewriting it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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
  """

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

    Args:
      text: Full document text (or body text) containing the markers.
      marker_id: Logical identifier of the managed region to rewrite.
      inner: New content to place between the markers. Leading/trailing
        newlines are normalized so the markers sit on their own lines.

    Returns:
      Document text with the inner region replaced.  Unchanged when the
      marker pair is not present.
    """
    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)

    # guard: marker pair absent — caller must insert via ensure_see_also
    if start not in text or end not in text:
      return text

    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)

    # Advance past the start marker and its trailing newline
    after_start = start_idx + len(start)
    # guard: if there's a newline immediately after the start marker, consume it
    if after_start < len(text) and text[after_start] == "\n":
      after_start += 1

    # Normalise inner: strip surrounding newlines, then re-add exactly one trailing
    inner_stripped = inner.strip("\n")
    if inner_stripped:
      inner_block = inner_stripped + "\n"
    else:
      inner_block = ""

    return text[:after_start] + inner_block + text[end_idx:]

  # ──────────────────────────────────────────────────────────────────────────
  def read_inner(self, text: str, marker_id: str = SEE_ALSO_MARKER_ID) -> str | None:
    """
    Return the content between the start/end markers, or `None` when absent.

    The returned content has surrounding newlines stripped, mirroring the
    normalization `rewrite_between` applies on write.

    Args:
      text: Full document text (or body text) that may contain the markers.
      marker_id: Logical identifier of the managed region to read; defaults
        to the canonical See-also region.

    Returns:
      The inner content with surrounding newlines stripped, or `None` when
      the marker pair is not present.
    """
    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)

    # guard: marker pair absent
    if start not in text or end not in text:
      return None

    start_idx = text.index(start)
    after_start = start_idx + len(start)
    # guard: consume the newline immediately after the start marker
    if after_start < len(text) and text[after_start] == "\n":
      after_start += 1

    end_idx = text.index(end, start_idx)
    return text[after_start:end_idx].strip("\n")

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

    Args:
      body: Markdown body text (the part after the frontmatter fences, or the
        entire document when there is no frontmatter).
      inner: Lines to place between the markers — typically the
        `see_also` entries from the curator result, joined by newlines.

    Returns:
      Body text with the See-also section present and up-to-date.
    """
    mid = self.SEE_ALSO_MARKER_ID
    start = self._start_marker(mid)
    end = self._end_marker(mid)

    # guard: section already present — just rewrite the inner
    if start in body and end in body:
      return self.rewrite_between(body, mid, inner)

    # Build the normalised inner block
    inner_stripped = inner.strip("\n")
    if inner_stripped:
      inner_block = inner_stripped + "\n"
    else:
      inner_block = ""

    section = (
      f"\n{self.SEE_ALSO_HEADING}\n"
      f"{self.SEE_ALSO_PROTECTED_TAG}\n"
      f"{start}\n"
      f"{inner_block}"
      f"{end}\n"
    )

    # Append after a trailing newline (ensure exactly one blank separator)
    if body.endswith("\n"):
      return body + section
    return body + "\n" + section
