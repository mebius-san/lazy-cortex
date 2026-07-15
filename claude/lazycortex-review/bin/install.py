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
from keys import Paths, ReviewKey  # noqa: E402  # pylint: disable=wrong-import-position


_REQUIRED_DIRS = (
    ".experts/.jobs",
    ".logs/lazy-review/runs",
)

_DEFAULT_SETTINGS = {
    "review": {
        "_version": 1,
        "classes": [],
        "edit_marker_style": "simple",
        # Repairer name the dispatcher resolves for parse-broken files. Pinned to
        # the registered expert key so the marketplace `<domain>.<role>` convention
        # holds (the dispatcher's bare `Role.DOC_DOCTOR` default is a last resort).
        "doc_doctor": "review.doc_doctor",
    },
    "experts": {
        "_version": 1,
        # Plugin-shipped system experts, registered unconditionally so a review
        # class (or the spec.product-config wizard) can reference them without a
        # separate wiring step. Keys follow the marketplace `<domain>.<role>`
        # convention. Absent-only merge — never overwrites local edits.
        "review.historian": {
            "agent": "lazycortex-review:lazy-review.historian",
            "git_author": {
                "name": "Doc Review Historian",
                "email": "review.historian@lazycortex.local",
            },
            # historian commits the Doc-Review trailer locally → needs commit rights
            "can_commit_in_repo": True,
        },
        "review.doc_doctor": {
            "agent": "lazycortex-review:lazy-review.doc_doctor",
            "git_author": {
                "name": "Doc Doctor",
                "email": "review.doc_doctor@lazycortex.local",
            },
        },
    },
    "routines": {
        "_version": 1,
        "lazy-review.scan": {
            "type": "md-scan",
            # Minute cadence — the whole-vault sieve reads every .md's
            # frontmatter per tick; 5s belongs to narrow request routines.
            # Matches spec.gate-tick's precedent for `**/*.md` scans.
            "interval_sec": 60,
            "timeout_sec": 60,
            "priority": 10,
            # Coarse scope-root masks, one per product / scope, written by
            # the generators (`lazy-review.configure`, `spec.product-config`,
            # `spec.install`): `<root>/**/*.md` — `**` is recursive in the
            # core md-scan matcher. Filename/depth precision lives in
            # review.classes[].paths (dispatch-time routing) and the
            # frontmatter filter below, never here.
            "paths": [],
            # Only opted-in files: start/submit stamp `review_active: true`
            # atomically, and the state machine skips non-active files — so
            # an absent-key file could only ever produce a no-op subprocess
            # spawn, which the whole-vault sieve would multiply per tick.
            # `review_result: { in: [None] }` excludes post-finalize files
            # (finalize strips `review_active` AND stamps `review_result`).
            "filter": {
                "frontmatter": {
                    ReviewKey.ACTIVE: {"in": [True], "not_in": []},
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
