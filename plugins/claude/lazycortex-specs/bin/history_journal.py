"""
`# History` journaling for a catalog note — one caller-side seam over the core verb.

Every history line a `lazycortex-specs` verb or worker writes goes through here, and here
only ever calls `lazycortex-core history-append` (dev.plugin-boundaries § 1c): the shape of
the section — day groups under `#### YYYY-MM-DD`, bullet lines, no time, no author — is the
core plugin's to define, and this module knows nothing about it beyond the wire contract.
The in-memory mode is what a writer that assembles a whole note before its single write needs:
text in, text out, nothing on disk. The file mode serves the coordinator persona, whose one
`note-history` call lands a line it composed itself.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class _Wire:
  """
  The core verb's CLI vocabulary and JSON wire keys, as `lazycortex-core history-append` prints them.

  Attributes:
    VERB: The core CLI subcommand.
    STDIN_FLAG: The flag selecting the in-memory mode (JSON in, JSON out, no disk write).
    LINE_FLAG: The file-mode flag carrying the line text.
    DATE_FLAG: The flag pinning the day group's date.
    TEXT: JSON key of the whole note text, both directions.
    LINE: JSON key of the line to append.
    DATE: JSON key of the pinned date.
  """

  VERB = "history-append"
  STDIN_FLAG = "--stdin"
  LINE_FLAG = "--line"
  DATE_FLAG = "--date"
  TEXT = "text"
  LINE = "line"
  DATE = "date"


def _core_argv(repo: Path | None, *tail: str) -> list[str]:
  """
  Build the interpreter-launched argv for one `history-append` call.

  Args:
    repo: The repository root the core-CLI resolver's dev fallback is tried against; `None`
      means the current working directory.
    tail: The verb's own arguments.

  Returns:
    The full argv list, interpreter first.
  """
  cli = gate_dispatch.resolve_core_cli(repo or Path.cwd())
  return [sys.executable, str(cli), _Wire.VERB, *tail]


def append(text: str, line: str, today: str | None = None, *, repo: Path | None = None) -> str:
  """
  Append one history line to a note's text without touching disk.

  Args:
    text: The whole note text, frontmatter included, or a bare body.
    line: The line to record, without a leading bullet.
    today: Optional ISO date pinned as the day group; the verb's own UTC today otherwise.
    repo: Optional repository root for the core-CLI resolver's dev fallback.

  Returns:
    The note text with the line placed under the right day group of `# History`.

  Raises:
    RuntimeError: When the core verb refuses or cannot be resolved.
  """
  payload: dict[str, str] = {_Wire.TEXT: text, _Wire.LINE: line}
  if today:
    payload[_Wire.DATE] = today
  proc = subprocess.run(
      _core_argv(repo, _Wire.STDIN_FLAG),
      input = json.dumps(payload), capture_output = True, text = True, check = False,
  )

  # guard: the verb refused (empty line, bad date, malformed request) — surface its own message
  if proc.returncode != 0:
    raise RuntimeError(f"history-append refused: {proc.stderr.strip() or proc.stdout.strip()}")
  return json.loads(proc.stdout)[_Wire.TEXT]


def append_to_file(note: Path, line: str, today: str | None = None, *, repo: Path | None = None) -> dict:
  """
  Append one history line to a note on disk, rewriting the file in place.

  Args:
    note: The note path.
    line: The line to record, without a leading bullet.
    today: Optional ISO date pinned as the day group.
    repo: Optional repository root for the core-CLI resolver's dev fallback.

  Returns:
    The verb's own result record (`file`, `date`, `new_day`).

  Raises:
    RuntimeError: When the core verb refuses or cannot be resolved.
  """
  tail = [str(note), _Wire.LINE_FLAG, line]
  if today:
    tail += [_Wire.DATE_FLAG, today]
  proc = subprocess.run(_core_argv(repo, *tail), capture_output = True, text = True, check = False)

  # guard: the verb refused — surface its own message rather than a bare exit code
  if proc.returncode != 0:
    raise RuntimeError(f"history-append refused: {proc.stderr.strip() or proc.stdout.strip()}")
  return json.loads(proc.stdout)
