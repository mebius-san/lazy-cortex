"""
HTML-comment marker utilities for lazycortex-specs managed regions.

Built for the heterogeneous `# Sources` container in spec entity docs. The
`# Sources` section is a container that hosts multiple H2 sub-sections, each
owned by a different writer (or by the operator). The marker pairs are
therefore scoped to ONE sub-section at a time, not to the whole H1 inner.

Three nested ownership levels (full contract in
`references/lazy-spec.sources-protocol.md`):

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

This module ships the generic marker read/rewrite primitives, the idempotent creation of the `# Sources`
container, and the projection of the `## Requests` and `## Docs` sub-sections from frontmatter targets.
"""
from __future__ import annotations

import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping


# Decision: keep this class a near-clone of lazycortex-wiki's marker helper, not a shared utility —
# cross-plugin Python imports are banned by `dev.plugin-boundaries.md § 2a`, and a CLI-subprocess boundary
# is overkill for an in-memory string-rewrite helper.

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

  Attributes:
    SOURCES_HEADING: Heading text for the `# Sources` container section.
    SOURCES_PROTECTED_TAG: Owner tag marking the `# Sources` section as a protected cross-plugin region.
    REQUESTS_HEADING: Heading text for the `## Requests` sub-section.
    REQUESTS_MARKER_ID: Marker identifier for the requests sub-section's managed region.
    DOCS_HEADING: Heading text for the `## Docs` sub-section.
    DOCS_MARKER_ID: Marker identifier for the docs sub-section's managed region.
  """

  # Domain(spec.notes):
  # # A shared container narrows ownership to one sub-kind at a time
  # A source-references section can hold several kinds of reference side by side, each
  # contributed by a different party, without any one contributor owning the whole section. The
  # section itself is claimed once, as a whole, so that nothing outside the spec system ever
  # rewrites it wholesale; inside it, a heading marks out each kind's own share of the space, and
  # only the narrow span belonging to one automated kind is ever rewritten on its own. A kind an
  # operator wrote by hand, with no such span of its own, is never touched by any rewrite.

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

  # Domain(spec.notes):
  # # A frontmatter list projects into a matching body list, never the reverse
  # Which requests contributed to a document is recorded once, in the document's own
  # frontmatter, and everything visible in the body is only ever a rendering of that record —
  # one bullet per contributing request, refreshed to match whenever the frontmatter list
  # changes. Editing the visible list directly is never how a contribution is added or removed;
  # the frontmatter stays the one place that decides what the projection shows next.

  # ──────────────────────────────────────────────────────────────────────────
  # `## Requests` sub-section — auto-projected from `spec_source_requests`
  # frontmatter by `lazy-spec.request-apply`. Each automated sub-kind ships its
  # own constants block alongside this one.
  # ──────────────────────────────────────────────────────────────────────────

  # H2 heading text for the requests sub-section.
  REQUESTS_HEADING = "## Requests"

  # Marker-id for the requests sub-section; expands to `<!-- auto:spec-requests:start --> / :end -->`.
  REQUESTS_MARKER_ID = "spec-requests"

  # ──────────────────────────────────────────────────────────────────────────
  # `## Docs` sub-section — auto-projected from `spec_source_docs` frontmatter.
  # ──────────────────────────────────────────────────────────────────────────

  # H2 heading text for the docs sub-section.
  DOCS_HEADING = "## Docs"

  # Marker-id for the docs sub-section; expands to `<!-- auto:spec-docs:start --> / :end -->`.
  DOCS_MARKER_ID = "spec-docs"

  # The wikilink target of a projected bullet: the bytes left of the `|` inside the first `[[…]]`.
  _BULLET_TARGET_RE = re.compile(r"^- \[\[([^\]|]+)")

  # The path separator inside a wikilink target.
  _SEP = "/"

  # The start of an H1 line, the only boundary of a protected section.
  _H1_RE = re.compile(r"(?m)^# \S")

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

    Guarantees:
      - Calling this method twice with the same `inner` and `marker_id` produces
        byte-identical output on the second call.

    Args:
      text: Full document text (or body text) containing the markers.
      marker_id: Logical identifier of the managed region to rewrite.
      inner: New content to place between the markers. Leading/trailing
        newlines are normalized so the markers sit on their own lines.

    Returns:
      Document text with the inner region replaced.  Unchanged when the
      marker pair is not present.
    """

    # Contract:
    # Calling this method twice with the same `inner` and `marker_id` produces
    # byte-identical output on the second call.

    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)

    # guard: marker pair absent — caller must insert via an ensure_* method
    if start not in text or end not in text:
      return text

    # locate the managed region's boundaries before splicing new content into it
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)

    # Advance past the start marker and its trailing newline
    after_start = start_idx + len(start)

    # consume the newline right after the start marker so the marker keeps its own line
    if after_start < len(text) and text[after_start] == "\n":
      after_start += 1

    # Normalise inner: strip surrounding newlines, then re-add exactly one trailing
    inner_stripped = inner.strip("\n")
    if inner_stripped:
      inner_block = inner_stripped + "\n"
    else:
      inner_block = ""

    # splice the new inner block in, keeping both marker lines intact
    return text[:after_start] + inner_block + text[end_idx:]

  # ──────────────────────────────────────────────────────────────────────────
  def read_inner(self, text: str, marker_id: str = REQUESTS_MARKER_ID) -> str | None:
    """
    Return the content between the start/end markers, or `None` when absent.

    The returned content has surrounding newlines stripped, mirroring the
    normalization `rewrite_between` applies on write.

    Guarantees:
      - Reading text that `rewrite_between` just wrote for the same `marker_id` returns
        exactly the normalized `inner` value that was written.

    Args:
      text: Full document text (or body text) that may contain the markers.
      marker_id: Logical identifier of the managed region to read; defaults
        to the requests sub-section.

    Returns:
      The inner content with surrounding newlines stripped, or `None` when
      the marker pair is not present.
    """

    # Contract:
    # Reading text that `rewrite_between` just wrote for the same `marker_id` returns
    # exactly the normalized `inner` value that was written.

    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)

    # guard: marker pair absent
    if start not in text or end not in text:
      return None

    # step past the start marker to where the inner content actually begins
    start_idx = text.index(start)
    after_start = start_idx + len(start)

    # consume the newline right after the start marker so it stays out of the inner content
    if after_start < len(text) and text[after_start] == "\n":
      after_start += 1

    # the inner content runs up to the end marker, normalised the same way writes are
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

    Guarantees:
      - Never duplicates or modifies an already-present container; repeated calls are
        idempotent.

    Args:
      body: Markdown body text (the part after the frontmatter fences, or the
        entire document when there is no frontmatter).

    Returns:
      Body text with the container present at the end (newly inserted or
      already there, unchanged).
    """

    # Contract:
    # Never duplicates or modifies an already-present `# Sources` container; repeated
    # calls with the same `body` converge to the same idempotent result.

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

    Guarantees:
      - Never creates a second `## Requests` sub-section; repeated calls converge to one
        sub-section whose managed region always reflects the latest `bullets`.

    Args:
      body: Markdown body text.
      bullets: Lines to place between the request-markers — typically the
        bullet list projected from `spec_source_requests` frontmatter,
        joined by newlines.

    Returns:
      Body text with the requests sub-section present and up-to-date.
    """

    # Contract:
    # Never creates a second `## Requests` sub-section; repeated calls converge to one
    # sub-section whose managed region always reflects the latest `bullets`.

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

    # assemble the H2 sub-section with the marker pair wrapping the bullets
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
  def format_doc_display(self, target: str, products: Mapping[str, str]) -> str:
    """
    Return the default display text for a `## Docs` bullet pointing at `target`.

    The display follows the target's place in the catalog: a document directly under a product reads
    `<product> — product <role>`, a deeper one reads `<slug> — <role>`, and a target outside every product
    reads as its last path segment.

    Args:
      target: Wikilink target path of the document.
      products: Map from a product's catalog path (short and vault form) to the product key.

    Returns:
      The display text; the longest product path the target lies under decides its shape.
    """

    # Domain(spec.notes):
    # # Default display of a document link
    # A link in the documents list reads by the document's place in the catalog. A product's own document reads as
    # the product name, a dash, the word product and the document's role. A document of an asset reads as the asset's
    # folder name, a dash and the document's role. A target outside every product reads as its last path segment.
    # When products nest, the product with the longest path that contains the target is its owner.

    # the longest product path the target lies under decides its shape
    segments = target.split(self._SEP)
    owner = max(( path for path in products
                  if segments[:len(path.split(self._SEP))] == path.split(self._SEP) ), key = len, default = None)

    # a target under no product falls back to its last segment
    if owner is None:
      return segments[-1]

    # the target's path below the owning product
    rest = segments[len(owner.split(self._SEP)):]

    # a product's own document names the product, an asset's names its folder
    if len(rest) == 1:
      return f"{products[owner]} — product {rest[0]}"
    if len(rest) > 1:
      return f"{rest[-2]} — {rest[-1]}"
    return segments[-1]

  # ──────────────────────────────────────────────────────────────────────────
  def project_docs(self, body: str, targets: list[str], *, products: Mapping[str, str] | None = None,
                   displays: Mapping[str, str] | None = None) -> str:
    """
    Project the `## Docs` sub-section of `body` from the frontmatter `targets`.

    Guarantees:
      - Produces one bullet per distinct target, in listed order.
      - An existing bullet for a target is kept verbatim, so an operator's display survives.
      - Bullets of targets no longer listed are dropped.
      - Repeating the call on a reconciled body returns it unchanged.

    Args:
      body: Markdown body text.
      targets: Wikilink targets in frontmatter order; duplicates collapse.
      products: Map from a product's catalog path to its key, used for the default display of a new bullet.
      displays: Display text per target, taking precedence over the default for a new bullet.

    Returns:
      Body text with the docs sub-section present and up to date; text outside the managed region is untouched.
    """

    # Contract:
    # An existing bullet for a target is kept verbatim,
    # so the operator's display text survives every projection.

    # Contract:
    # The projection holds one bullet per distinct target, in the listed order.

    # Contract:
    # A target no longer listed leaves no bullet in the projection.

    # Contract:
    # Projecting an already reconciled body returns it unchanged.

    # an existing bullet keeps its display; a new one takes the given or the shape-aware default
    kept = self._bullets_by_target(self.read_inner(body, self.DOCS_MARKER_ID) or "")
    lines = [ kept.get(target) or
              f"- [[{target}|{(displays or {}).get(target) or self.format_doc_display(target, products or {})}]]"
              for target in dict.fromkeys(targets) ]
    return self._project(body, self.DOCS_HEADING, self.DOCS_MARKER_ID, "\n".join(lines))

  # ──────────────────────────────────────────────────────────────────────────
  def project_requests(self, body: str, targets: list[str], *, today: str,
                       displays: Mapping[str, str] | None = None) -> str:
    """
    Project the `## Requests` sub-section of `body` from the frontmatter `targets`.

    Guarantees:
      - Produces one bullet per distinct target, in listed order, each ending in a `YYYY-MM-DD` date.
      - An existing bullet for a target is kept verbatim, so its display and first date survive.
      - Bullets of targets no longer listed are dropped.
      - Repeating the call on a reconciled body returns it unchanged.

    Args:
      body: Markdown body text.
      targets: Wikilink targets in frontmatter order; duplicates collapse.
      today: Date, as `YYYY-MM-DD`, stamped on each new bullet.
      displays: Display text per target for a new bullet; the last path segment when absent.

    Returns:
      Body text with the requests sub-section present and up to date; text outside the managed region is untouched.
    """

    # Contract:
    # An existing bullet for a target is kept verbatim,
    # so the operator's display text and the date the target was first listed survive every projection.

    # Contract:
    # The projection holds one bullet per distinct target, in the listed order.

    # Contract:
    # Every bullet of the projection ends in a `YYYY-MM-DD` date.

    # Contract:
    # A target no longer listed leaves no bullet in the projection.

    # Contract:
    # Projecting an already reconciled body returns it unchanged.

    # an existing bullet keeps its display and its first date; a new one is dated today
    kept = self._bullets_by_target(self.read_inner(body, self.REQUESTS_MARKER_ID) or "")
    lines = [ kept.get(target) or
              f"- [[{target}|{(displays or {}).get(target) or target.split(self._SEP)[-1]}]] — {today}"
              for target in dict.fromkeys(targets) ]
    return self._project(body, self.REQUESTS_HEADING, self.REQUESTS_MARKER_ID, "\n".join(lines))

  # ──────────────────────────────────────────────────────────────────────────
  def _bullets_by_target(self, inner: str) -> dict[str, str]:
    """
    Index the bullet lines of a managed region by their wikilink target.

    Args:
      inner: Content between a marker pair.

    Returns:
      Map from target to the first bullet line naming it.
    """
    # the first bullet naming a target is the one kept
    bullets: dict[str, str] = {}
    for line in inner.splitlines():
      match = self._BULLET_TARGET_RE.match(line)
      if match and match.group(1) not in bullets:
        bullets[match.group(1)] = line
    return bullets

  # ──────────────────────────────────────────────────────────────────────────
  def _project(self, body: str, heading: str, marker_id: str, inner: str) -> str:
    """
    Place `inner` in the sub-section `heading` of the `# Sources` container, creating what is missing.

    When the marker pair exists, only the bytes between the markers change. Otherwise the container is created at
    the end of the body if missing and the sub-section is added at the end of the container, before the next H1.
    Repeating the call on a reconciled body returns it unchanged.

    Args:
      body: Markdown body text.
      heading: H2 heading line of the sub-section.
      marker_id: Identifier of the sub-section's marker pair.
      inner: Content to place between the markers.

    Returns:
      Body text with the sub-section holding `inner`.
    """
    start = self._start_marker(marker_id)
    end = self._end_marker(marker_id)

    # a sub-section already in place keeps its markers, and only the bytes between them change
    if start in body and end in body:
      return self.rewrite_between(body, marker_id, inner)

    # a missing container is created at the end of the body, after one blank line
    if not self._container_present(body):
      body = self.ensure_sources_container(body.rstrip() + "\n")

    # the sub-section closes the container, before the H1 that follows it
    stripped = inner.strip("\n")
    inner_block = f"{stripped}\n" if stripped else ""
    block = f"{heading}\n{start}\n{inner_block}{end}\n"
    cut = self._container_end(body)
    tail = body[cut:]
    return body[:cut].rstrip("\n") + "\n\n" + block + ("\n" + tail if tail else "")

  # ──────────────────────────────────────────────────────────────────────────
  def _container_end(self, body: str) -> int:
    """
    Locate the end of the `# Sources` container in `body`.

    Args:
      body: Markdown body text.

    Returns:
      Index of the first H1 after the container, or the length of `body` when none follows or the container
      is absent.
    """
    # waiver: regex glue between two interpolated constants, not a domain literal worth promoting
    pattern = re.escape(self.SOURCES_HEADING) + r"\s*\n\s*" + re.escape(self.SOURCES_PROTECTED_TAG) + r"\s*\n"
    container = re.search(pattern, body)

    # guard: no container means the body's end
    if container is None:
      return len(body)

    # the next H1 after the container ends it
    following = self._H1_RE.search(body, container.end())
    return following.start() if following else len(body)

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
