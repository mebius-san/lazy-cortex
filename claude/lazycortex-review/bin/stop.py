"""`/lazy-review.stop <file>` — bail out of the review loop without
finalizing. Sets `review_active: false` and commits. Body and
`approved` are left untouched so a subsequent `start` can resume
from the operator's last state.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import argparse
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import ReviewKey  # noqa: E402


def _atomic_commit(file_path: Path) -> None:
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: stop {file_path.name}"],
      cwd=cwd, check=True, capture_output=True,
  )


def stop_review(file_path: Path) -> bool:
  """
  Set `review_active` to `false` in the document's frontmatter.

  Args:
    file_path: Absolute path to the markdown file to update.

  Returns:
    `True` if the file was modified, `False` if it was already inactive.
  """
  text = file_path.read_text()
  new_text = _fm.set_field(text, ReviewKey.ACTIVE, False)
  if new_text == text:
    return False
  file_path.write_text(new_text)
  return True


def main(argv: list[str]) -> int:
  """
  Stop an active review from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file is not found.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.stop")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()
  if not file_path.exists():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2
  changed = stop_review(file_path)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"stopped: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
