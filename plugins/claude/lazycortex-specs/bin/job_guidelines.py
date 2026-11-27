"""
Logic behind the `lazycortex-specs job-guidelines <note> --role <role>` verb.

The verb answers which guideline files a job of one role, dispatched on one spec note, reads: the enabled plugins'
canon for the role, then the guidelines the note's owning product declares for the role, the note's asset type and
every role. The coordinator agent copies the answer into the payload of a launch-checkbox job it dispatches itself.
"""
from __future__ import annotations

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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The JSON keys of the verb's answer
_PATHS, _WARNINGS, _ERROR = "paths", "warnings", "error"


def _fail(error: str) -> int:
  """
  Print the verb's error answer.

  Args:
    error: Why no answer can be given.

  Returns:
    The refused exit code, 1.
  """
  # the error answer carries no paths at all, never a partial list
  print(json.dumps({ _PATHS: None, _WARNINGS: [], _ERROR: error }))
  return 1


def main(argv: list[str]) -> int:
  """
  Print the guideline files a job of one role reads on one note, as one JSON line.

  Answers for the product that owns the note and for the note's asset type, working in the settings root of the
  checkout the command runs in. The note path may be repo-relative or absolute.

  Guarantees:
    - For a command line that parses, standard output holds exactly one JSON line.
    - A successful answer carries the guideline paths and the warnings and exits 0.
    - An error answer, exiting 1, carries no paths at all, never a partial list; it names the cause.
    - An error answer is given when the note is no file, lies outside the repository, or the settings cannot be read.

  Args:
    argv: Command-line arguments, excluding the program name: the note path and `--role`.

  Returns:
    Exit code: 0 for a successful answer, 1 for an error answer.

  Raises:
    SystemExit: With code 2 when `--role` is missing or `argv` holds an unknown argument; nothing is printed to
      standard output.
  """

  # Contract:
  # For a command line that parses, stdout carries exactly one JSON line. Exit 0 answers `{"paths", "warnings"}`;
  # exit 1 answers `{"paths": null, "warnings": [], "error"}` when the note is no file, lies outside the repository
  # or the settings cannot be read, never a partial list. A command line that does not parse, a missing `--role` or
  # an unknown argument, is a usage error: it exits 2 through argparse with nothing on stdout. The coordinator agent
  # copies `paths` into a job payload and journals each warning.

  # the note and the role from the command line
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs job-guidelines")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--role", required = True)
  args = parser.parse_args(argv)

  # the directory whose settings the answer reads, and the note named relative to it
  repo = spec_locator.query_settings_root()
  note = repo / args.note

  # guard: a note that is no file has no product or asset type to answer for
  if not note.is_file():
    return _fail(f"note not found: {note}")

  # guard: a note outside the repository belongs to no product of it
  try:
    rel = note.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return _fail(f"note outside the repository: {note}")

  # guard: settings that cannot be read leave no product record to answer from; an error, never an empty list
  try:
    _key, record = resolve_product.effective_record_by_path(repo, rel)
  except ValueError as error:
    return _fail(str(error))

  # the role's guidelines for the note's product and asset type
  paths, warnings = gate_dispatch.collect_guideline_paths(repo, record or {}, args.role,
                                                          asset_type = asset_types.type_of(note))
  print(json.dumps({ _PATHS: paths, _WARNINGS: warnings }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
