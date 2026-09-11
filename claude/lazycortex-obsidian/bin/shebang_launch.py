"""
Launch a file through the interpreter its own first line names.

The exec bit is not part of this contract: a git client that cannot store modes
(obsidian-git on Android, any Windows checkout) strips it silently, so nothing here
asks the OS to honour a shebang. The line is read, the interpreter is resolved, and
the caller gets an argv it can hand to `subprocess`. A Python file is always run by
the interpreter that is already running, `sys.executable`, so PATH is never consulted
for Python at all.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# a shebang interpreter is Python when its basename is python, python3 or python3.N
_PYTHON_NAME = re.compile(r"^python(3(\.\d+)?)?$")
# the env trampoline carries no meaning for us — the token after it is the interpreter
_ENV_BASENAME = "env"


class ShebangError(Exception):
  """
  Raised when a file cannot be launched from its first line.
  """


def read_shebang(path: Path) -> list[str]:
  """
  Read the interpreter tokens a file's first line declares.

  Args:
    path: File to inspect.

  Returns:
    Tokens after `#!`, with a leading `/usr/bin/env` dropped — e.g. `["python3"]`,
    `["/bin/sh", "-e"]`.

  Raises:
    ShebangError: File unreadable, first line empty, or not a `#!` line.
  """
  try:
    # waiver: stdlib encoding idiom, not a domain constant
    with path.open("r", encoding = "utf-8", errors = "replace") as fh:
      first = fh.readline()
  except OSError as e:
    raise ShebangError(f"{path}: cannot read: {e}") from e
  # guard: only a `#!` line declares an interpreter
  if not first.startswith("#!"):
    raise ShebangError(f"{path}: no shebang on line 1")
  tokens = first[2:].split()
  # guard: `#!` with nothing after it
  if not tokens:
    raise ShebangError(f"{path}: empty shebang")
  if Path(tokens[0]).name == _ENV_BASENAME:
    tokens = tokens[1:]
    # guard: `#!/usr/bin/env` naming no interpreter
    if not tokens:
      raise ShebangError(f"{path}: env shebang names no interpreter")
  return tokens


def argv_for(path: Path, *args: str) -> list[str]:
  """
  Build the argv that runs `path` through its declared interpreter.

  Guarantees:
    - A Python-named interpreter always runs under `sys.executable`, never one resolved
      from PATH.

  Args:
    path: File to run.
    *args: Arguments appended after the file.

  Returns:
    `[sys.executable, path, *args]` for a Python file; otherwise
    `[interpreter, flags..., path, *args]` with the interpreter absolute.

  Raises:
    ShebangError: No usable shebang, or the interpreter is not on PATH.
  """

  # Domain(plugin.boundaries):
  # # Cross-machine safe script launch
  # A script is launched through the interpreter named on its own first line, never through
  # the operating system honouring an executable permission bit: a client that cannot
  # preserve file modes when syncing a checkout across machines or platforms strips that bit
  # silently, and a launcher that trusted it would fail on exactly the installs that most
  # need it to work. A script that names itself as Python is always launched under the
  # interpreter already running rather than one resolved from the search path, so a consumer
  # with several Python versions installed never runs a sibling script under a version
  # different from the one hosting it.

  # Contract:
  # For a file whose shebang names Python, the returned argv MUST launch it under
  # `sys.executable`, the interpreter already running, and MUST NEVER use an interpreter
  # resolved from PATH.

  tokens = read_shebang(path)
  interp, flags = tokens[0], tokens[1:]
  if _PYTHON_NAME.match(Path(interp).name):
    return [ sys.executable, *flags, str(path), *args ]
  resolved = interp if Path(interp).is_absolute() else shutil.which(interp)
  # guard: the interpreter the file asks for is not installed
  if not resolved:
    raise ShebangError(f"{path}: interpreter {interp!r} not found on PATH")
  return [ resolved, *flags, str(path), *args ]
