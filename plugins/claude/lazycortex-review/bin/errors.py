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


class DispatchRefusalError(LazyReviewError):
  """
  Refusal of a `dispatch-writer` request.

  Raised when the request is invalid or cannot be served, so no job has been queued.

  Attributes:
    marker_restored: Whether the document's job marker was put back after a refusal that came after it was written.
  """

  def __init__(self, message: str, *, marker_restored: bool | None = None) -> None:
    """
    Create the refusal with a message and what became of the document's job marker.

    Args:
      message: Human-readable description of the refusal.
      marker_restored: Whether the job marker was put back, or `None` when it was never written.
    """
    # the base exception carries the message
    super().__init__(message)

    # what became of the job marker, for a caller that must know whether the document still names a job
    self.marker_restored = marker_restored


class DispatchQueueError(LazyReviewError):
  """
  Failure of the queue call of a `dispatch-writer` request.

  Raised when the job marker was written and the queue call then failed, so no job has been queued, or when core
  reported the queue call as successful but its answer cannot be used, so the job may have been queued.

  Attributes:
    marker_restored: Whether the document's job marker was put back after the failure; `False` also when the marker
      was kept because the job may have been queued.
  """

  def __init__(self, message: str, *, marker_restored: bool) -> None:
    """
    Create the error with a message and what became of the document's job marker.

    Args:
      message: Human-readable description of the queue failure.
      marker_restored: Whether the job marker was put back.
    """
    # the base exception carries the message
    super().__init__(message)

    # what became of the job marker, for a caller that must know whether the document still names a job
    self.marker_restored = marker_restored


class QueueAnswerError(LazyReviewError):
  """
  Unusable answer to a queue call that core reported as successful.

  Raised when the answer is not JSON or is JSON that is not an object, so whether the job was queued is not known.
  """


class JobConsumeError(LazyReviewError):
  """
  Failure to mark a finished job consumed.

  Raised when the core CLI could not be reached, could not be launched, or refused the consume.

  Attributes:
    summary: What a landing did land and consume before the refusal, in the landing's summary shape, or `None`
      when the error does not come out of a landing.
  """

  def __init__(self, message: str, *, summary: dict | None = None) -> None:
    """
    Create the error with a message and, when it comes out of a landing, what that landing did land.

    Args:
      message: Human-readable description of the consume failure.
      summary: What the landing did land and consume before the refusal, in the landing's summary shape.
    """
    # the base exception carries the message
    super().__init__(message)

    # what a landing did land and consume before the refusal, when the error comes out of one
    self.summary = summary


class GitOpsError(LazyReviewError):
  """
  Failure of a local git operation.

  Lazy-review owns no remote operations; this surfaces only on local
  `add` / `commit` / `log` / `show` failures.
  """


class MarkerStoreCorruptError(LazyReviewError, OSError):
  """
  Failure of a job-marker sidecar that reads but is no marker store.

  Raised when the sidecar's content is not UTF-8 text, not JSON, or not a JSON object. It is an `OSError`, so every
  caller that refuses a decision on an unreadable store refuses on this one too.
  """


class SettingsReadError(LazyReviewError):
  """
  Failure of the core CLI to read a section of the consumer's settings.

  Raised when `lazycortex-core settings-get` exits non-zero or prints something that is not a JSON object —
  typically a tracked settings file or local overlay that is not valid JSON.
  """
