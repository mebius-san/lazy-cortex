"""
HTML-comment marker utilities for lazycortex-specs managed regions.

A specs-side counterpart to lazycortex-wiki's `Markers`, adapted for the
heterogeneous `# Sources` container in spec entity docs. Unlike the wiki's
homogeneous `# See also` section (one writer, one inner block), specs's
`# Sources` is a container that hosts multiple H2 sub-sections, each
owned by a different writer (or by the operator). The marker pairs are
therefore scoped to ONE sub-section at a time, not to the whole H1 inner.

Three nested ownership levels (full contract in
`references/spec.sources-protocol.md`):

1. H1 `# Sources` + `#protected/spec/sources` owner tag on its first
   content line — section-level identity owned by specs as a whole;
   preserved byte-for-byte by foreign plugins (per `dev.protected-
   sections.md`). This class creates the container exactly once via
   `ensure_sources_container`; nothing else inside the container is
   touched at this level.

2. H2 `## <Kind>` sub-section heading — operator-territory boundary
   between sub-kinds. The heading line itself is preserved across
   re-writes; only the bytes inside the matching marker pair are
   managed.

3. Per-kind HTML marker pair `<!-- auto:spec-<kind>:start --> / :end -->`
   — narrow rewrite scope. Each automated sub-kind ships its own pair
   and one writer method; operator-authored sub-kinds carry no markers
   and stay untouched.

This module ships:

- generic `rewrite_between` / `read_inner` primitives keyed on
  `marker_id` — usable for any future per-kind writer;
- `ensure_sources_container` — idempotent insert of the H1 + protected
  tag at the end of body;
- `ensure_requests_subsection` — idempotent insert / rewrite of the
  `## Requests` H2 between its `auto:spec-requests` marker pair, the
  body-projection of `spec_source_requests` frontmatter.

The class is intentionally a near-clone of `lazycortex-wiki/bin/
markers.py` rather than a shared utility: cross-plugin Python imports
are banned by `dev.plugin-boundaries.md § 2a`, and a CLI-subprocess
boundary is overkill for an in-memory string-rewrite helper.
"""
from __future__ import annotations

import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ────────────────────────────────────────────────────────────────────────────
class Markers:
  """
  Read/write the HTML-comment-delimited managed regions in a spec doc body.

  Each managed region is bounded by::

      <!-- auto:<marker_id>:start -->
      <inner content>
      <!-- auto:<marker_id>:end -->

  Specs writers own the bytes between the markers; everything outside
  (including the H1 container heading, the protected owner tag, and any
  H2 sub-section headings) is preserved byte-for-byte.
  """

  # ──────────────────────────────────────────────────────────────────────────
  # H1 container — owned at the section level, no managed inner bytes at
  # this layer (the inner is composed of per-kind H2 sub-sections, each
  # with its own marker pair).
  # ──────────────────────────────────────────────────────────────────────────

  # H1 heading text for the container section.
  SOURCES_HEADING = "# Sources"

  # Owner tag placed on the first content line under the H1, marking the section as a
  # protected cross-plugin region. Foreign plugins (e.g. lazy-review.finalize) preserve
  # the whole section byte-for-byte; specs writers manage the per-sub-section bytes.
  SOURCES_PROTECTED_TAG = "#protected/spec/sources"

  # ──────────────────────────────────────────────────────────────────────────
  # `## Requests` sub-section — auto-projected from `spec_source_requests`
  # frontmatter by `spec.request-attach`. Each automated sub-kind ships its
  # own constants block alongside this one.
  # ──────────────────────────────────────────────────────────────────────────

  # H2 heading text for the requests sub-section.
  REQUESTS_HEADING = "## Requests"

  # Marker-id for the requests sub-section; expands to `<!-- auto:spec-requests:start --> / :end -->`.
  REQUESTS_MARKER_ID = "spec-requests"

  def _start_marker(self, marker_id: str) -> str:
    """
    Return the opening HTML comment for the given marker_id.

    Args:
      marker_id: Logical identifier for the managed region, e.g. `spec-requests`.

    Returns:
      Opening marker string, e.g. `<!-- auto:spec-requests:start -->`.
    """
    return f"<!-- auto:{marker_id}:start -->"

  def _end_marker(self, marker_id: str) -> str:
    """
    Return the closing HTML comment for the given marker_id.

    Args:
      marker_id: Logical identifier for the managed region.

    Returns:
      Closing marker string, e.g. `<!-- auto:spec-requests:end -->`.
    """
    return f"<!-- auto:{marker_id}:end -->"

  # ──────────────────────────────────────────────────────────────────────────
  def rewrite_between(self, text: str, marker_id: str, inner: str) -> str:
    """
    Replace the content between the start/end markers with `inner`.

    The operation is idempotent: calling this method twice with the same
    `inner` produces byte-identical output on the second call.  If the
    marker pair is absent from `text`, the text is returned unchanged —
    use the appropriate `ensure_*` method to insert the region first.

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

    # guard: marker pair absent — caller must insert via an ensure_* method
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
  def read_inner(self, text: str, marker_id: str = REQUESTS_MARKER_ID) -> str | None:
    """
    Return the content between the start/end markers, or `None` when absent.

    The returned content has surrounding newlines stripped, mirroring the
    normalization `rewrite_between` applies on write.

    Args:
      text: Full document text (or body text) that may contain the markers.
      marker_id: Logical identifier of the managed region to read; defaults
        to the requests sub-section.

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
  def ensure_sources_container(self, body: str) -> str:
    """
    Ensure the `# Sources` H1 container with its owner tag exists at the end of `body`.

    Creates the heading + protected-tag pair when absent. When the container is already
    present (detected by the protected-tag line under a `# Sources` heading), the body
    is returned unchanged — this method only ever creates the container shell, never
    modifies an existing one. The container hosts per-kind H2 sub-sections; this
    method does NOT create or touch those.

    Rendered shape when newly inserted::

        # Sources
        #protected/spec/sources

    Args:
      body: Markdown body text (the part after the frontmatter fences, or the
        entire document when there is no frontmatter).

    Returns:
      Body text with the container present at the end (newly inserted or
      already there, unchanged).
    """
    # guard: container already present — leave the existing one alone, sub-section writers manage inside
    if self._container_present(body):
      return body

    # Build the container block — H1 + protected-tag + trailing blank line for sub-section insertion
    container = (
      f"\n{self.SOURCES_HEADING}\n"
      f"{self.SOURCES_PROTECTED_TAG}\n"
      f"\n"
    )

    # Append after a trailing newline (ensure exactly one blank separator)
    if body.endswith("\n"):
      return body + container
    return body + "\n" + container

  # ──────────────────────────────────────────────────────────────────────────
  def ensure_requests_subsection(self, body: str, bullets: str) -> str:
    """
    Ensure the `## Requests` H2 sub-section under `# Sources` exists and projects `bullets`.

    When the requests-marker pair is already in `body`, the bullet list between the
    markers is rewritten (idempotent re-projection). When the pair is absent, the
    container is created if missing, then the H2 sub-section is appended inside the
    container with the markers wrapping `bullets`.

    Rendered shape when newly inserted::

        # Sources
        #protected/spec/sources

        ## Requests
        <!-- auto:spec-requests:start -->
        <bullets>
        <!-- auto:spec-requests:end -->

    Args:
      body: Markdown body text.
      bullets: Lines to place between the request-markers — typically the
        bullet list projected from `spec_source_requests` frontmatter,
        joined by newlines.

    Returns:
      Body text with the requests sub-section present and up-to-date.
    """
    mid = self.REQUESTS_MARKER_ID
    start = self._start_marker(mid)
    end = self._end_marker(mid)

    # guard: sub-section already present — just rewrite the inner bullets
    if start in body and end in body:
      return self.rewrite_between(body, mid, bullets)

    # Sub-section absent: ensure container first, then append the H2 + marker pair inside
    body = self.ensure_sources_container(body)

    # Build the normalised inner block
    bullets_stripped = bullets.strip("\n")
    if bullets_stripped:
      inner_block = bullets_stripped + "\n"
    else:
      inner_block = ""

    subsection = (
      f"{self.REQUESTS_HEADING}\n"
      f"{start}\n"
      f"{inner_block}"
      f"{end}\n"
    )

    # Append after the container's trailing blank line (which ensure_sources_container guarantees)
    if body.endswith("\n"):
      return body + subsection
    return body + "\n" + subsection

  # ──────────────────────────────────────────────────────────────────────────
  def _container_present(self, body: str) -> bool:
    """
    Report whether the `# Sources` H1 container is already in `body`.

    Detection requires the `# Sources` heading line AND the protected-owner tag line
    on consecutive non-blank lines — a bare `# Sources` heading without the tag is
    not the managed container and is left alone (operator-territory).

    Args:
      body: Markdown body text to inspect.

    Returns:
      `True` when the heading + tag pair is present in the canonical order,
      `False` otherwise.
    """
    # The container is identified by the H1 line directly followed (possibly with whitespace)
    # by the protected-owner tag line. Use a regex to span optional whitespace between them.
    # waiver: regex glue between two interpolated constants, not a domain literal worth promoting
    pattern = re.escape(self.SOURCES_HEADING) + r"\s*\n\s*" + re.escape(self.SOURCES_PROTECTED_TAG) + r"\s*\n"
    return re.search(pattern, body) is not None
