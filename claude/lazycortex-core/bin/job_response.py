"""
Classification of the response envelope every expert job writes.

`outcome` / `error` / `result` belong to the expert-runtime contract, and the tokens in
`outcome` are the only proof a job finished. This module owns reading that payload and
deciding what it says, so the pump, the queue metrics, and the routines that reconcile
against an external input store all reach the same verdict from the same bytes.
"""
from __future__ import annotations

import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import JobFile, JobMarker, JobOutcome, JobResponseKey, JobStatus  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


def outcome_tokens(response: dict) -> list[str]:
  """
  Split a response payload's `outcome` field into its individual tokens.

  A protocol may declare a composite outcome as a comma-separated list, so the
  discriminator is a token set rather than a single string. A response whose
  `outcome` is absent, empty, or not a string yields an empty list — the shape
  that marks a violated response envelope.

  Args:
    response: Parsed `response.json` payload, or an empty dict when the file
      was absent or unreadable.

  Returns:
    The non-empty outcome tokens in declaration order.
  """
  raw = response.get(JobResponseKey.OUTCOME)
  # guard: a missing or non-string outcome carries no tokens
  if not isinstance(raw, str):
    return []
  return [ token.strip() for token in raw.split(",") if token.strip() ]


def is_deferred(response: dict) -> bool:
  """
  Decide whether a response postpones the work rather than finishing or failing it.

  `deferred` is reserved across all protocols and means the expert deliberately
  left the work undone and its input untouched — the consumer must neither drain
  the input nor treat the job as failed. An `error` token alongside it wins:
  a failure is a failure regardless of what else the payload claims.

  Args:
    response: Parsed `response.json` payload, or an empty dict when the file
      was absent or unreadable.

  Returns:
    `True` when the payload reports the reserved deferred outcome.
  """
  tokens = outcome_tokens(response)
  return JobOutcome.DEFERRED in tokens and JobOutcome.ERROR not in tokens


def is_success(response: dict) -> bool:
  """
  Decide whether a finished job's response payload reports completed work.

  Success is asserted, never assumed: the payload must carry at least one
  outcome token and none of them may be the reserved `error` or `deferred`
  tokens. A payload that omits `outcome`, carries it empty, or could not be
  parsed at all violates the response envelope every expert is bound by, and
  counts as a failure — the caller must not treat it as completed work.

  Args:
    response: Parsed `response.json` payload, or an empty dict when the file
      was absent or unreadable.

  Returns:
    `True` when the payload explicitly reports a finished, non-error outcome.
  """
  tokens = outcome_tokens(response)
  return bool(tokens) and not { JobOutcome.ERROR, JobOutcome.DEFERRED }.intersection(tokens)


def classify_response(response: dict) -> str:
  """
  Classify a finished bundle's response into its terminal status token.

  Args:
    response: Parsed `response.json` payload, or an empty dict when the file
      was absent or unreadable.

  Returns:
    `JobStatus.DONE` for completed work, `JobStatus.DEFERRED` for postponed
    work, `JobStatus.FAILED` for everything else — an error outcome and a
    violated envelope alike.
  """
  # guard: postponed work is neither finished nor failed, and must not be counted as either
  if is_deferred(response):
    return JobStatus.DEFERRED
  return JobStatus.DONE if is_success(response) else JobStatus.FAILED


def read_response(jdir: Path) -> dict:
  """
  Read a job bundle's response payload.

  Args:
    jdir: Path to the job-bundle directory holding the response file.

  Returns:
    The parsed payload, or an empty dict when the file is absent, unreadable,
    malformed, or holds a non-object JSON value.
  """
  resp_path = jdir / JobFile.RESPONSE
  # guard: the expert may have exited without writing a response at all
  if not resp_path.exists():
    return {}
  try:
    parsed = json.loads(resp_path.read_text())
  except (OSError, json.JSONDecodeError):
    return {}
  return parsed if isinstance(parsed, dict) else {}


def is_job_bundle(path: Path) -> bool:
  """
  Report whether a path under an expert's queue is one of its job bundles.

  A bundle is recognised by anything a dispatch leaves in it: either payload file, or any
  of the markers a job acquires as it runs. A directory carrying none of them was never a
  job and is not one now.

  Args:
    path: Path to the directory being judged, as found under `.experts/.jobs/<expert>/`.

  Returns:
    `True` when the path is a directory holding a job payload or a job marker.
  """

  # Decision: the test is "did a dispatch leave anything here", not one signature file —
  # payloads alone would reject a bundle reduced to its markers, and markers alone would reject
  # one whose dispatch died before touching the first marker. Both shapes are real, and both
  # must count. Every scanner of the queue asks this question, and each one answering it
  # privately is how an empty `.claude` sidecar the harness drops beside a bundle came to be
  # counted as a queued job that never drains.

  # guard: a stray file beside the bundles is not a queue entry
  if not path.is_dir():
    return False

  # any trace a dispatch leaves is proof enough; the directory needs to carry only one of them
  return any(
    (path / name).exists()
    for name in (
      JobFile.REQUEST, JobFile.CONFIG, JobFile.RESPONSE,
      JobMarker.READY, JobMarker.PID, JobMarker.DONE, JobMarker.DEAD, JobMarker.CANCELLED,
    )
  )
