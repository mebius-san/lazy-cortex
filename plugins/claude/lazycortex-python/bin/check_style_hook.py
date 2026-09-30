#!/usr/bin/env python3
"""
PostToolUse body of the `lazy-python.check-style` hook.

`hooks/lazy-python.check-style.sh` is a thin bash shim that execs this script under
`"${LAZYCORTEX_PYTHON:-python3}"` with the hook payload on stdin. Narrows to an Edit or
Write of a `.py` file, skips a file that does not currently compile (an edit still in
progress), then runs `pcf.py --honor-excludes` so `pcf` owns the exclude decision. Prints
a PostToolUse `additionalContext` JSON payload carrying every `: note:` violation line,
and exits 0 on every path. Exists so the hook needs no `jq`, which is absent from Git Bash
on Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# the style checker this hook runs, shipped beside this script
_PCF = Path(__file__).with_name("pcf.py")

# the tools whose writes are checked, and the only file type the checker reads
_TOOLS = ("Edit", "Write")
_PY_SUFFIX = ".py"

# the marker pcf puts on every violation line
_NOTE_MARKER = ": note:"


# ----------------------------------------------------------------------------------------
def parse_edited_py_file(payload: str) -> str | None:
  """
  Extract the edited `.py` file path from a PostToolUse hook payload.

  Args:
    payload: Raw PostToolUse JSON payload read from the hook's stdin.

  Returns:
    The edited file's path as reported by the payload, or None when the payload is not
    JSON, does not name an Edit/Write call, or does not target a `.py` file.
  """
  # guard: a payload that is not JSON names no file — the hook must never crash its trigger
  try:
    data = json.loads(payload)
  except ValueError:
    return None

  # guard: only an Edit / Write call carries a file the checker can read
  if not isinstance(data, dict) or data.get("tool_name") not in _TOOLS:
    return None

  # guard: a payload without a tool_input object names no file
  if not isinstance(tool_input := data.get("tool_input"), dict):
    return None

  # the file lands under `file_path`, or `path` on an older payload shape
  path = tool_input.get("file_path") or tool_input.get("path")

  # guard: only a .py file is the checker's to read
  if not isinstance(path, str) or not path.endswith(_PY_SUFFIX):
    return None
  return path


# ----------------------------------------------------------------------------------------
def format_report_path(real_file: str, project_dir: str) -> str:
  """
  Render a file path for display, relative to the project directory when possible.

  Args:
    real_file: Resolved absolute path of the checked file.
    project_dir: Absolute path of the project root to relativize against.

  Returns:
    The path relative to `project_dir` when `real_file` lies inside it, otherwise
    `real_file` unchanged.
  """
  # a file inside the project is reported repo-relative, anything else as its absolute path
  try:
    return Path(real_file).relative_to(os.path.realpath(project_dir)).as_posix()
  except ValueError:
    return real_file


# ----------------------------------------------------------------------------------------
def collect_violations(real_file: str) -> list[str]:
  """
  Collect the style-checker violation lines for a Python file.

  Skips a file that does not currently compile, treating it as an edit still in progress
  rather than a style violation.

  Args:
    real_file: Absolute, resolved path of the Python file to check.

  Returns:
    Each `pcf` violation line for the file, or an empty list when the file is clean,
    excluded, or does not compile.
  """
  # guard: a file that does not parse is an edit in progress, not a style problem
  try:
    compile(Path(real_file).read_bytes(), real_file, "exec", dont_inherit = True)
  except (OSError, SyntaxError, ValueError):
    return []

  # pcf owns the exclude decision; --honor-excludes makes an excluded path a no-op
  result = subprocess.run(
    [ sys.executable, str(_PCF), "--honor-excludes", real_file ],
    capture_output = True, text = True, check = False, encoding = "utf-8",
  )
  return [ line for line in (result.stdout + result.stderr).splitlines() if _NOTE_MARKER in line ]


# ----------------------------------------------------------------------------------------
def main() -> int:
  """
  Check the edited Python file's style and report violations to the invoking session.

  Returns:
    Process exit code; always 0, since a style problem is reported through
    `additionalContext` rather than through hook failure.
  """
  path = parse_edited_py_file(sys.stdin.read())
  project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")

  # guard: no .py edit, or no project to report against — nothing to check
  if path is None or not os.path.isdir(project_dir):
    return 0

  # resolve symlinks, then collect the style violations of the edited file
  real_file = os.path.realpath(path)
  notes = collect_violations(real_file)

  # guard: a clean or excluded file stays silent
  if not notes:
    return 0

  # the violations reach the session as PostToolUse additionalContext
  context = f"Style violations in {format_report_path(real_file, project_dir)}:\n\n" + "\n".join(notes)
  print(json.dumps({ "hookSpecificOutput": { "hookEventName": "PostToolUse", "additionalContext": context } }))
  return 0


if __name__ == "__main__":
  sys.exit(main())
