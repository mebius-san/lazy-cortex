from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Final, Literal


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The environment variables the runtime pins an expert job's commit identity with.
_ENV_AUTHOR_NAME = "GIT_AUTHOR_NAME"
_ENV_AUTHOR_EMAIL = "GIT_AUTHOR_EMAIL"

# The marker every bot identity's email carries.
_BOT_MARKER = "@bot."

# The outcome words of a note commit.
COMMITTED: Final = "committed"
NOTHING_TO_COMMIT: Final = "nothing-to-commit"
_REFUSED = "refused"

# The verb's exit codes: a commit or nothing to commit, and a refusal.
_EXIT_OK = 0
_EXIT_REFUSED = 1

# The text encoding git output is decoded with, and the porcelain status code of a renamed or copied entry.
_ENCODING = "utf-8"
_RENAME_CODES = frozenset({ "R", "C" })

# The width of a porcelain v1 entry's status field plus its separating space.
_STATUS_WIDTH = 3


# ----------------------------------------------------------------------------------------
class CommitRefusedError(Exception):
  """
  Refusal of a note commit before anything was committed.

  Attributes:
    reason: The human-readable refusal reason.
  """

  def __init__(self, reason: str) -> None:
    # the exception's own message is the reason itself
    super().__init__(reason)

    # the reason, kept for callers that report it without parsing the message
    self.reason: str = reason


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class CommitResult:
  """
  What a note commit did.

  Attributes:
    status: Whether a commit was made.
    sha: The new commit's hash, or None when nothing was committed.
    paths: The repo-relative paths the commit carried.
    repainted: The repainted paths among them.
    dirty: The repo-relative paths the working tree still reports changed after the commit.
  """

  status: Literal["committed", "nothing-to-commit"]
  sha: str | None
  paths: list[str] = field(default_factory = list)
  repainted: list[str] = field(default_factory = list)
  dirty: list[str] = field(default_factory = list)


def resolve_identity(*, require_bot: bool) -> tuple[str, str] | None:
  """
  Resolve the commit identity the runtime pinned for this process.

  A bot identity is required when the commit must not read as an operator edit, which would wake the coordinator.

  Args:
    require_bot: Whether a missing or non-bot author email refuses the commit.

  Returns:
    The pinned `(name, email)` pair when both halves are pinned, otherwise None for the ambient git identity.

  Raises:
    CommitRefusedError: If a bot identity is required and the author email is missing or not a bot's.
  """
  name = os.environ.get(_ENV_AUTHOR_NAME)
  email = os.environ.get(_ENV_AUTHOR_EMAIL)

  # guard: a bot-only commit under an operator's identity would read as the operator's own edit
  if require_bot and (email is None or _BOT_MARKER not in email):
    raise CommitRefusedError(f"commit identity is not a bot: {email or 'none'}")

  # a pair is pinned only when both halves are; otherwise git's own identity stays in force
  if name is None or email is None:
    return None
  return name, email


def _query_dirty_paths(repo: Path) -> list[str]:
  """
  List the paths the working tree reports changed.

  Args:
    repo: The repository root.

  Returns:
    The repo-relative paths of every changed, staged, or untracked entry, in git's order.
  """
  status = subprocess.run(
      [ "git", "status", "--porcelain=v1", "-z" ], cwd = str(repo), check = True, capture_output = True,
      text = True, encoding = _ENCODING,
  )

  # each entry is `XY path`; a rename or copy carries its origin path as the next field, which is skipped
  entries = iter(status.stdout.split("\0"))
  dirty: list[str] = []
  for entry in entries:
    # guard: the trailing separator leaves one empty field
    if not entry:
      continue
    dirty.append(entry[_STATUS_WIDTH:])
    if entry[0] in _RENAME_CODES:
      next(entries, None)
  return dirty


def commit_paths(repo: Path, paths: list[str], *,
                 subject: str,
                 require_bot: bool = False,
                 repaint: bool = False) -> CommitResult:
  """
  Commit exactly `paths` under the runtime's identity and report the tree left behind.

  Guarantees:
    - A refusal is raised before anything is committed.
    - Nothing is committed when the paths hold no change; the result then says so.

  Args:
    repo: The repository root.
    paths: The paths to commit, absolute or repo-relative.
    subject: The commit subject.
    require_bot: Whether the commit is refused unless the runtime pinned a bot identity.
    repaint: Whether the icon repaint of the markdown paths joins the commit.

  Returns:
    The commit's outcome, the new HEAD's hash, the paths it carried, the repainted paths among them, and the paths
    still dirty in the tree afterwards.

  Raises:
    CommitRefusedError: If a bot identity is required and none is pinned.
    subprocess.CalledProcessError: If the commit fails.
  """

  # Contract:
  # A refusal is raised before anything is committed;
  # a refused call leaves the repository history untouched.

  # Contract:
  # When the paths hold no change, NOTHING is committed
  # and the result reports that status instead of a commit.

  # the runtime's identity, resolved first so a refusal precedes any commit
  identity = resolve_identity(require_bot = require_bot)
  name, email = identity if identity is not None else ( None, None )

  # the one shared commit primitive does the repaint, the change check and the pathspec commit
  committed, carried, repainted = flip_gate.commit_paths_detail(
      repo, paths, subject = subject, author_name = name, author_email = email, repaint = repaint,
  )

  # the new commit's hash, read back only when there is one
  sha = flip_gate.git_field(repo, [ "rev-parse", "HEAD" ], "") if committed else None
  return CommitResult(
      status = COMMITTED if committed else NOTHING_TO_COMMIT, sha = sha, paths = carried,
      repainted = repainted, dirty = _query_dirty_paths(repo),
  )


def _refusal(reason: str) -> dict[str, object]:
  """
  Build the verb's output for a refused commit.

  Args:
    reason: The refusal reason.

  Returns:
    The JSON-ready result with no commit and the reason.
  """
  return { "status": _REFUSED, "sha": None, "paths": [], "repainted": [], "dirty": [], "clean": None,
           "reason": reason }


def main(argv: list[str]) -> int:
  """
  Run the `commit-note` verb and print its outcome as one JSON line.

  The note always leads the commit's pathspec, and a path outside the spec content root refuses the commit.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    0 on a commit or nothing to commit, 1 on a refusal.

  Raises:
    SystemExit: With code 2 if the arguments are invalid.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs commit-note")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note", type = Path)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--subject", required = True)
  # waiver: argparse CLI signature -- repeatable option flag
  parser.add_argument("--path", action = "append", default = [], type = Path)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--require-bot", action = "store_true")
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--repaint", action = "store_true")
  args = parser.parse_args(argv)

  # the note leads the pathspec, every named path resolved against the current directory
  note = args.note.resolve()
  paths = list(dict.fromkeys([ note, *( path.resolve() for path in args.path ) ]))
  content_root = spec_paths.spec_content_root(spec_paths.find_settings_root(note.parent)).resolve()
  outside = [ str(path) for path in paths if not path.is_relative_to(content_root) ]

  # guard: the verb commits spec-catalog files only, never a path outside the catalog
  if outside:
    print(json.dumps(_refusal(f"path outside the spec catalog {content_root}: {', '.join(outside)}"),
                     ensure_ascii = False))
    return _EXIT_REFUSED

  # the commit itself; a refused identity is reported, never raised to the caller
  try:
    done = commit_paths(flip_gate.repo_root(note.parent), [ str(path) for path in paths ], subject = args.subject,
                        require_bot = args.require_bot, repaint = args.repaint)
  except CommitRefusedError as refused:
    print(json.dumps(_refusal(refused.reason), ensure_ascii = False))
    return _EXIT_REFUSED

  # one JSON line carries the whole result
  print(json.dumps({
      "status": done.status, "sha": done.sha, "paths": done.paths, "repainted": done.repainted,
      "dirty": done.dirty, "clean": not done.dirty, "reason": None,
  }, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
