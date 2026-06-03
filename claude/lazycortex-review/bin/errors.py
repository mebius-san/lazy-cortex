"""Exception hierarchy for lazy-review.

All custom exceptions inherit from :class:`LazyReviewError`. Callers
that catch the base class get a single recovery point; callers that
care about a specific failure class catch a subclass.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class LazyReviewError(Exception):
  """
  Root of every exception raised by lazy-review.
  """


class ParseError(LazyReviewError):
  """Frontmatter / document parsing failed.

    `text_excerpt` carries up to 200 characters of the offending
    region so doc_doctor can be dispatched with concrete context.
    """

  def __init__(self, message: str, *, text_excerpt: str | None = None) -> None:
    super().__init__(message)
    self.text_excerpt = text_excerpt


class PayloadError(LazyReviewError):
  """Agent request / response payload violated the protocol.

    Used for malformed JSON, missing required fields, invalid outcome
    enums, or response result/ paths pointing outside the job dir.
    """


class OwnershipViolation(LazyReviewError):
  """An expert tried to mutate content it does not own.

    Section writer changed body prose, main writer touched a `#expert/<name>`
    owned section, final writer added body edits — every cross-ownership
    write surfaces here. The dispatcher refuses to apply such a response.
    """


class ProtectedFieldError(LazyReviewError):
  """Agent response tried to overwrite a reserved frontmatter key.

    `review_active` and `review_round` are dispatcher-owned. Attempts
    by experts to overwrite them are silently dropped at reapply time,
    but the dispatcher logs the violation through this exception type.
    """


class GitOpsError(LazyReviewError):
  """A local git operation failed.

    Lazy-review owns no remote operations; this surfaces only on local
    `add` / `commit` / `log` / `show` failures.
    """


class RepairExhausted(LazyReviewError):
  """
  `doc_doctor` failed to repair a broken document after N attempts.
  """

  def __init__(self, file_path: str, attempts: int) -> None:
    super().__init__(
        f"doc_doctor failed to repair {file_path} after {attempts} attempts"
    )
    self.file_path = file_path
    self.attempts = attempts
