"""`/lazy-review.status <file>` — read-only state introspection.

Emits a single-line JSON record summarising:

- `review_active` (bool)
- `review_round` (int)
- `approved` (bool)
- `banner` (current banner state or `null`)
- `owners` (list of `{section, owner}` pairs for the doc's H1
  sections that carry an `#expert/<flat-name>` tag)
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,wrong-import-position,deprecated-module

import argparse
import json
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
import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import JobKey, ReviewKey  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import parser as _parser  # noqa: E402


def status_record(file_path: Path) -> dict:
  """
  Build a state summary dict for a single review document.

  Args:
    file_path: Absolute path to the markdown file to inspect.

  Returns:
    Dict with keys `file`, `review_active`, `review_round`, `review_approved`, `banner`,
    and `owners`.
  """
  text = file_path.read_text()
  meta, body = _fm.parse(text)
  doc = _parser.parse(text)
  current = _banner.extract(body)
  return {
      JobKey.FILE: str(file_path),
      # waiver: external-format field name, not an internal key
      ReviewKey.ACTIVE: meta.get(ReviewKey.ACTIVE, "false").lower() == "true",
      # waiver: external-format field name, not an internal key
      ReviewKey.ROUND: int(meta.get(ReviewKey.ROUND, "0") or 0),
      # waiver: external-format field name, not an internal key
      ReviewKey.APPROVED: meta.get(ReviewKey.APPROVED, "false").lower() == "true",
      JobKey.BANNER: current.value if current is not None else None,
      JobKey.OWNERS: [
          {JobKey.SECTION: s.title, JobKey.OWNER: s.owner_expert}
          for s in doc.sections if s.owner_expert is not None
      ],
  }


def main(argv: list[str]) -> int:
  """
  Print the status record for a review document as JSON to stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file is not found.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.status")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()
  if not file_path.exists():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2
  print(json.dumps(status_record(file_path), indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
