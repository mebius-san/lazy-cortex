"""Bootstrap lazy-review into a consumer repo.

Writes (or leaves alone if present) the following pieces of state:

- `<repo>/.claude/lazy.settings.json` — adds `review.classes`,
  `experts`, and `routines["lazy-review.scan"]` sections if absent.
  Existing values are never overwritten.
- `<repo>/.experts/.jobs/` and `<repo>/.logs/lazy-review/runs/`
  directories.

The CLI prints a summary of what changed.

This script does NOT touch `.gitignore`; the consumer is told what
entries to add (see the install SKILL.md).
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

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
from keys import Paths, ReviewKey  # noqa: E402


_REQUIRED_DIRS = (
    ".experts/.jobs",
    ".logs/lazy-review/runs",
)

_DEFAULT_SETTINGS = {
    "review": {
        "_version": 1,
        "classes": [],
        "edit_marker_style": "simple",
    },
    "experts": {
        "_version": 1,
    },
    "routines": {
        "_version": 1,
        "lazy-review.scan": {
            "type": "md-scan",
            "interval_sec": 5,
            "timeout_sec": 60,
            "priority": 10,
            "paths": [],
            # `review_active: { in: [None, True] }` covers the in-cycle
            # states (bootstrap-pending + active). `review_result:
            # { in: [None] }` excludes post-finalize files (finalize
            # strips `review_active` AND stamps `review_result`, so the
            # file matches `review_active: [None]` alone but belongs to
            # the consumer apply-gate, not the scan loop).
            "filter": {
                "frontmatter": {
                    ReviewKey.ACTIVE: {"in": [None, True], "not_in": []},
                    ReviewKey.RESULT: {"in": [None], "not_in": []},
                },
            },
            "command": ["lazycortex-review", "process-file"],
            "protocols": [
                "lazycortex-review:lazy-review.doc-review-protocol",
                "lazycortex-core:lazy-core.markdown-style",
            ],
        },
    },
}


def _ensure_dirs(repo: Path) -> list[str]:
  created: list[str] = []
  for rel in _REQUIRED_DIRS:
    d = repo / rel
    if not d.exists():
      d.mkdir(parents=True, exist_ok=True)
      created.append(rel)
  return created


def _ensure_settings(repo: Path) -> dict:
  settings_dir = repo / Paths.CLAUDE_DIR
  settings_dir.mkdir(parents=True, exist_ok=True)
  settings_path = settings_dir / Paths.SETTINGS_FILE
  if settings_path.exists():
    existing = json.loads(settings_path.read_text())
  else:
    existing = {}
  added: list[str] = []
  for top_key, top_value in _DEFAULT_SETTINGS.items():
    if top_key not in existing:
      existing[top_key] = top_value
      added.append(top_key)
      continue
  # Merge nested defaults conservatively.
    if isinstance(top_value, dict) and isinstance(existing[top_key], dict):
      for k, v in top_value.items():
        if k not in existing[top_key]:
          existing[top_key][k] = v
          added.append(f"{top_key}.{k}")
  settings_path.write_text(json.dumps(existing, indent=2) + "\n")
  return {"settings_path": str(settings_path), "added_keys": added}


def install(repo: Path) -> dict:
  """
  Bootstrap the lazy-review directory structure and default settings for a repository.

  Args:
    repo: Path to the repository root to install into.

  Returns:
    Dict with keys `repo`, `created_dirs`, `settings_path`, and `added_keys`.
  """
  repo = repo.resolve()
  dirs = _ensure_dirs(repo)
  settings_info = _ensure_settings(repo)
  return {
      "repo": str(repo),
      "created_dirs": dirs,
      **settings_info,
  }


def main(argv: list[str]) -> int:
  """
  Run the install bootstrap and print the JSON report to stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: always 0.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.install")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", type=Path, default=Path.cwd())
  args = parser.parse_args(argv)
  report = install(args.cwd)
  print(json.dumps(report, indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
