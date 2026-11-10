from __future__ import annotations

import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Encoding the response file is written with.
_ENCODING = "utf-8"

# File name the expert runtime reads a job's answer from, at the root of the job dir.
_RESPONSE_FILE = "response.json"

# Envelope keys of the runtime's response contract.
_KEY_OUTCOME = "outcome"
_KEY_RESULT = "result"
# Key of one result entry naming the returned file, relative to the job dir.
_KEY_PATH = "path"
_KEY_ERROR = "error"
_KEY_CATEGORY = "category"
_KEY_MESSAGE = "message"

# Outcome value that carries an error object instead of a result list.
OUTCOME_ERROR = "error"

# Failure categories of the runtime's response contract.
CATEGORY_LOGICAL = "logical"
CATEGORY_TRANSIENT = "transient"
CATEGORY_TECHNICAL = "technical"


# ----------------------------------------------------------------------------------------
class JobRefusedError(Exception):
  """
  Refusal of an expert job, carrying the category it is reported under.

  Attributes:
    category: Failure category of the runtime's response contract: logical, technical or transient.
    reason: One-line explanation reported as the refusal message.
  """

  def __init__(self, *, category: str, reason: str) -> None:
    """
    Create a refusal.

    Args:
      category: Failure category the refusal is reported under.
      reason: One-line explanation of the refusal.
    """
    # the exception's own message is the refusal reason
    super().__init__(reason)

    # the response-contract category the refusal is reported under
    self.category: str = category
    # the one-line reason the response's error message carries
    self.reason: str = reason


# ----------------------------------------------------------------------------------------
def write_response(job_dir: Path,
                   *,
                   outcome: str,
                   result: list[str] | None = None,
                   category: str | None = None,
                   message: str | None = None) -> Path:
  """
  Write a job's answer where the expert runtime collects it.

  Guarantees:
    - The response file is `response.json` at the root of the job directory, never inside a subfolder like `result/`.
    - Each result entry is written as a `{"path": <entry>}` object, the shape the runtime's collector reads.

  Notes:
    - An existing response of the job is replaced.

  Args:
    job_dir: Job directory the response belongs to.
    outcome: Outcome value; `error` makes the response carry an error object instead of a result list.
    result: Job-dir-relative paths of the files a non-error outcome returns, each written as a `{"path": …}`
      entry; `None` omits the result key from the response.
    category: Failure category of an error outcome.
    message: Failure message of an error outcome.

  Returns:
    Path of the written response file.
  """

  # Contract:
  # The response MUST be written to `response.json` at the root of the job directory,
  # never into a subfolder such as `result/`, because the expert runtime's collector
  # reads the job's answer from that exact location.

  # Contract:
  # Each result entry MUST be written as a `{"path": <entry>}` object,
  # because the expert runtime's collector reads the job's result files from that shape.

  # an error outcome carries the error object; every other outcome carries its result list
  if outcome == OUTCOME_ERROR:
    envelope: dict[str, object] = {
      _KEY_OUTCOME: outcome,
      _KEY_ERROR:   { _KEY_CATEGORY: category, _KEY_MESSAGE: message },
    }
  else:
    envelope = { _KEY_OUTCOME: outcome }
    # an outcome with nothing to list (a noop) carries no result key at all
    if result is not None:
      envelope[_KEY_RESULT] = [ { _KEY_PATH: entry } for entry in result ]

  # the file lands where the runtime collects it
  path = Path(job_dir) / _RESPONSE_FILE
  path.write_text(json.dumps(envelope, indent = 2) + "\n", encoding = _ENCODING)
  return path
