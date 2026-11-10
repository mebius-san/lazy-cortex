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
  """
  Failure to parse a document's frontmatter or body.

  Carries an excerpt of the offending region so doc_doctor can be dispatched with concrete context.

  Attributes:
    text_excerpt: Excerpt of the document region that failed to parse.
  """

  def __init__(self, message: str, *, text_excerpt: str | None = None) -> None:
    """
    Create the error with a message and an optional excerpt of the offending text.

    Args:
      message: Human-readable description of the parse failure.
      text_excerpt: Excerpt of the document region that failed to parse.
    """
    # the base exception carries the message
    super().__init__(message)

    # the excerpt is kept for callers that report where parsing failed
    self.text_excerpt = text_excerpt


class PayloadError(LazyReviewError):
  """
  Protocol violation in an agent request or response payload.

  Raised when a payload is malformed, incomplete, or carries values or file references the protocol does not allow.
  """


class GitOpsError(LazyReviewError):
  """
  Failure of a local git operation.

  Lazy-review owns no remote operations; this surfaces only on local
  `add` / `commit` / `log` / `show` failures.
  """


class SettingsReadError(LazyReviewError):
  """
  Failure of the core CLI to read a section of the consumer's settings.

  Raised when `lazycortex-core settings-get` exits non-zero or prints something that is not a JSON object —
  typically a tracked settings file or local overlay that is not valid JSON.
  """
