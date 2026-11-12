"""
Logic behind the `lazycortex-specs migrate-gate-rows` verb — moves the `# Gates` section of spec folder notes onto
the grouped shape.

In the grouped shape the launch rows sharing a verb sit in one gate callout titled by the verb, under one shared
explanation. The verb applies that layout to every status, product and catalog note, so it neither adds nor removes a
row, and every byte outside the section stays. It never commits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import review_rows  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    LEVEL_ROLES, SpecKey, SpecValue,
)


# The roles of the folder notes that carry a `# Gates` section
_MIGRATED_ROLES = LEVEL_ROLES | { SpecValue.ROLE_STATUS }

# Why a note was left as it is
_REASON_CURRENT = "already current"
_REASON_NO_SECTION = "no gates section"
_REASON_ROLE_UNREADABLE = "spec_role is not a string"

_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's own wire-shape keys, and the keys of one skipped entry, read by the migration step and the tests
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"
_PATH_KEY = "path"
_REASON_KEY = "reason"

# The exit code of a failed run, told apart from both `--check` answers
_EXIT_FAILED = 2


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Lay the `# Gates` section of every spec folder note out into the grouped shape.

  Guarantees:
    - Only the `# Gates` section of a status, product or catalog note changes; every other byte keeps its place.
    - No launch row is added or removed: every row keeps its label and its tick.
    - A note without the section, a note already laid out, and a role that is not a string are left byte-identical
      and reported skipped with a reason, and the run goes on.
    - A dry run writes nothing, and a second run over the result changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the notes rewritten, as paths relative to the settings root, and the folder notes
    left as they are, each a `{"path", "reason"}` record; both in walk order.

  Raises:
    OSError: When a note cannot be read or written, or no settings file lies at or above `repo`.
    VaultRootError: When `spec.vault_root` names no sub-directory of the settings root.
  """

  # Contract:
  # Only the `# Gates` section of a status, product or catalog note changes, through the same layout the
  # `review-rows` verb runs; every other byte MUST keep its place, and no launch row is added or removed. A note
  # without the section or a role that is not a string MUST be left as it is and reported skipped with a reason, and
  # the run MUST go on. A dry run MUST write no file, and running the verb again over its own output MUST change
  # nothing.

  settings_root = spec_paths.require_settings_root(repo)
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # every markdown file under the content root, in a stable order
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    for name in sorted(filenames):

      # guard: only markdown files carry frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue

      # the note's text and its role, read once for every check below
      note = Path(dirpath) / name
      text = spec_paths.read_text(note)
      role = spec_frontmatter.parse(text)[0].get(SpecKey.ROLE, "")
      rel = note.relative_to(settings_root).as_posix()

      # guard: a role that is not a string cannot be read, so the note is skipped and the run goes on
      if not isinstance(role, str):
        result[_SKIPPED_KEY].append({ _PATH_KEY: rel, _REASON_KEY: _REASON_ROLE_UNREADABLE })
        continue

      # guard: only an asset's status note and a level note carry launch rows
      if role.strip() not in _MIGRATED_ROLES:
        continue

      # the laid-out text, and the reason when the note is left as it is
      new_text, reason = _migrate_text(settings_root, note, text)

      # a note the migration leaves as it is goes unwritten, reported with the reason
      if new_text == text:
        result[_SKIPPED_KEY].append({ _PATH_KEY: rel, _REASON_KEY: reason })
        continue

      # a changed note is reported, and written unless the run is dry
      result[_CHANGED_KEY].append(rel)
      if not dry_run:
        spec_paths.write_text_atomic(note, new_text)

  # both lists in walk order
  return result


def _migrate_text(settings_root: Path, note: Path, text: str) -> tuple[str, str]:
  """
  Lay out one folder note's `# Gates` section.

  Args:
    settings_root: The settings root the note lies under.
    note: Path of the folder note.
    text: The note's full text.

  Returns:
    The note text with the section laid out, and the reason the note is left as it is; the text unchanged when it
    has no section or the section is already laid out.
  """
  _fm_values, fm_end = spec_frontmatter.parse(text)

  # the stages and the language the `review-rows` verb reads, outside the `try` so only a missing section is caught
  stages = review_rows.read_review_stages(settings_root, note)
  lang = note_explainers.lang_for_note(note)

  # the section is laid out exactly as the `review-rows` verb lays it out
  try:
    body = review_rows.layout_body(text[fm_end:], stages, lang)
  except ValueError:
    return text, _REASON_NO_SECTION

  # the frontmatter is carried over untouched ahead of the laid-out body
  return text[:fm_end] + body, _REASON_CURRENT


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one note would change, 1 when none would.
    - Any failure exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a note would change and 1 when none would; 0 otherwise; 2 on any failure.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one note would change, 1 when none would; any
  # failure MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-gate-rows")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-gate-rows: {error!r}\n")
    return _EXIT_FAILED
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    sys.stderr.write(f"migrate-gate-rows: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
