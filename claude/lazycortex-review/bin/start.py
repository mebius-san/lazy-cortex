"""`/lazy-review.start <file>` — open a document for review.

Single atomic commit that:

- Sets frontmatter `review_active: true`, `review_round: 1`,
  `review_approved: false` (only the keys that are missing or wrong;
  the surgical line-edit keeps everything else byte-for-byte).
- Clears `review_result` if a prior finalize left it on the file —
  re-opening for review must reset the terminal apply-gate
  discriminator.
- Inserts the initial Waiting banner above the first H1.

`# History` is NOT inserted here — it is created lazily by the
historian on the first entry (`history.append_entry` calls
`ensure_history_section` itself).

The commit is made under the OPERATOR's git identity (no Doc-Review
trailer) so the dispatcher's next tick sees a "human commit" and
runs its first historian noop / writer dispatch.

Returns 0 on success, 2 when the file doesn't exist or isn't a
markdown file.
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
import banner as _banner  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import body as _body  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import ReviewKey  # noqa: E402


def open_review(file_path: Path, *, expert: str | None = None) -> bool:
  """
  Apply the bootstrap mutations to `file_path`.

  Returns:
    `True` if anything changed; `False` if the file was already opted-in and fully bootstrapped
    (idempotent re-run).
  """
  text = file_path.read_text()
  new_text = text
  new_text = _fm.set_field(new_text, ReviewKey.ACTIVE, True)
  meta, _ = _fm.parse(new_text)
  if ReviewKey.ROUND not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.ROUND, 1)
  if ReviewKey.APPROVED not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.APPROVED, False)
# Clear the terminal apply-gate discriminator if a prior finalize
# left it on the file. Re-opening for review means the apply-gate
# has nothing to act on yet — its trigger is the *next* finalize.
  if ReviewKey.RESULT in meta:
    new_text = _fm.unset_field(new_text, ReviewKey.RESULT)
  if expert:
    new_text = _fm.set_field(new_text, ReviewKey.EXPERT, expert)
# Re-opening a finalized doc: strip the prior cycle's `#status/<state>` landing
# callout from body. Symmetric with the `review_result` frontmatter clear above —
# both are terminal markers from the previous finalize and no longer apply while
# the doc is back in active review (Bug 121).
  _, body = _fm.parse(new_text)
  fm_text = new_text[: len(new_text) - len(body)]
  body = _body.strip_status_callout(body)
  if _banner.extract(body) is None:
    body = _banner.replace_banner(body, _banner.State.IN_PROCESS)
  new_text = fm_text + body
  if new_text == text:
    return False
  file_path.write_text(new_text)
  return True


def _atomic_commit(file_path: Path) -> None:
  """Stage the file and commit under the caller's git identity with
    a human-shaped subject (no Doc-Review trailer)."""
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: opt-in {file_path.name}"],
      cwd=cwd, check=True, capture_output=True,
  )


def main(argv: list[str]) -> int:
  """
  Open a document for review from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file does not exist or is not a markdown file.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.start")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--expert", default=None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true",
                      # waiver: argparse CLI signature, not a domain key
                      help="apply bootstrap mutations but do not commit")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()
  # waiver: filesystem path idiom
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
  changed = open_review(file_path, expert=args.expert)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"opted in: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
