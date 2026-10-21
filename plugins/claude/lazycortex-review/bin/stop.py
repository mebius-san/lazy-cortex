"""`/lazy-review.stop <file>` — bail out of the review loop without
finalizing. Sets `review_active: false` and commits. Body and
`approved` are left untouched so a subsequent `start` can resume
from the operator's last state.
"""
from __future__ import annotations

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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import ReviewKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The per-cycle autorun choices stopping a review removes from the frontmatter.
_AUTORUN_KEYS = ( ReviewKey.SKIP_VALIDATION, ReviewKey.AUTORUN, ReviewKey.AUTORUN_CYCLES )


def _atomic_commit(file_path: Path) -> None:
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )

  # the pathspec keeps a concurrently staged foreign file out of the stop commit
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: stop {file_path.name}", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )


def stop_review(file_path: Path) -> bool:
  """
  Set `review_active` to `false` and drop the cycle's autorun choices from the frontmatter.

  Guarantees:
    - Leaves the round counter, phase, done-lists, approval state, and the document body
      unchanged; only `review_active` is modified and `review_skip_validation`, `review_autorun`,
      and `review_autorun_cycles` are removed.

  Args:
    file_path: Absolute path to the markdown file to update.

  Returns:
    `True` if the file was modified, `False` if it was already inactive.
  """

  # Domain(review.lifecycle):
  # # Stopping pauses the round machine, it does not reset it
  # Leaving review turns the loop off and drops the cycle's autorun choices; the round
  # counter, phase, done-lists, and approval state are left exactly as they stood, and the
  # document body is untouched. A later re-entry into review resumes the round machine from
  # wherever it was paused, rather than starting the cycle over.

  # Contract:
  # Stopping review changes only `review_active` and removes `review_skip_validation`,
  # `review_autorun`, and `review_autorun_cycles`; the round counter, phase,
  # done-lists, approval state, and the document body are left unchanged.

  # flip the active flag
  text = _atomic_io.read_text(file_path)
  lf_text, ending = _atomic_io.to_lf(text)
  lf_text = _fm.set_field(lf_text, ReviewKey.ACTIVE, False)

  # drop the cycle's autorun choices; every other lifecycle key is left untouched
  for key in _AUTORUN_KEYS:
    lf_text = _fm.unset_field(lf_text, key)

  # write only when something changed
  new_text = _atomic_io.restore_ending(lf_text, ending)
  # guard: an unchanged document is not rewritten
  if new_text == text:
    return False
  _atomic_io.write_text_atomic(file_path, new_text)
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
