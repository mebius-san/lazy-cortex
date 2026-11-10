"""
Logic behind the `lazycortex-specs migrate-review-class` verb — retires the `architecture` review class in a
consumer's settings.

An earlier release seeded the product-root `architecture.md` under a review class named `architecture`; the class
is now `system-architecture`. This verb renames the retired entry when the current one is absent and removes it when
the current one is already there, leaving every other class as it was. Settings are read and written only through
the core CLI. It never commits.
"""
from __future__ import annotations

import argparse
import json
import os
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
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The retired class token and the token that replaces it.
_RETIRED_CLASS = "architecture"
_CURRENT_CLASS = "system-architecture"

# The identity key of a review class entry.
_CLASS_KEY = "class"

# The settings section and the key inside it the verb reads and writes, through the core verbs that own them.
_SECTION = "review"
_CLASSES_KEY = "classes"
_CORE_GET = "settings-get"
_CORE_SET = "settings-set"
_KEY_FLAG = "--key"
_VALUE_FLAG = "--value"
_CWD_FLAG = "--cwd"

_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's wire-shape key and its values, read by the migration step and the tests.
_ACTION_KEY = "action"
_RENAMED = "renamed"
_REMOVED = "removed"
_NONE = "none"

# The exit code of a run the core call failed, told apart from both `--check` answers.
_EXIT_FAILED = 2

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Retire the `architecture` review class in the repository's settings.

  Guarantees:
    - With no `system-architecture` class, the first `architecture` entry becomes `system-architecture` in place,
      every other key it carries kept; with one, every `architecture` entry is removed and the existing class is
      left untouched.
    - Every other class keeps its content and the list keeps its order; nothing is written when no `architecture`
      entry exists, and a dry run writes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"action"}` — `renamed`, `removed`, or `none` when no `architecture` entry exists.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, a core call's output cannot be decoded, a core
      call exits non-zero, or `settings-get` prints anything but JSON.
  """

  # Contract:
  # Only `architecture` entries change: the first is renamed to `system-architecture` when that class is absent,
  # every other one is removed, and the existing `system-architecture` entry and every other class keep their content
  # and order. A dry run and a run with nothing to retire MUST call no `settings-set`; a migration step's
  # `applies_when` predicate and its rerun rely on that.

  settings_root = spec_paths.find_settings_root(repo)
  classes = _read_classes(settings_root)

  # guard: settings without a classes list carry nothing to retire
  if not isinstance(classes, list) or not any(_is_class(entry, _RETIRED_CLASS) for entry in classes):
    return { _ACTION_KEY: _NONE }

  # a rename happens only when the current class is absent; once it exists, every retired entry left goes
  is_renamed = not any(_is_class(entry, _CURRENT_CLASS) for entry in classes)
  has_current = not is_renamed
  migrated: list = []

  # one pass in list order, so every kept entry stays where it was
  for entry in classes:
    # any other class goes back as read
    if not _is_class(entry, _RETIRED_CLASS):
      migrated.append(entry)

    # the first retired entry takes the current identity and keeps its other keys; any later one is dropped
    elif not has_current:
      migrated.append({ **entry, _CLASS_KEY: _CURRENT_CLASS })
      has_current = True

  # the whole list goes back through the core verb, unless the run is dry
  if not dry_run:
    _call_core(settings_root, _CORE_SET, _SECTION, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG, json.dumps(migrated))
  return { _ACTION_KEY: _RENAMED if is_renamed else _REMOVED }


def _is_class(entry: object, token: str) -> bool:
  """
  Report whether a review class entry carries the given class token.

  Args:
    entry: One item of the classes list.
    token: The class token to match.

  Returns:
    True when the entry is an object whose `class` value equals the token.
  """
  return isinstance(entry, dict) and entry.get(_CLASS_KEY) == token


def _read_classes(repo: Path) -> object:
  """
  Read the repository's review classes through the core `settings-get` verb.

  Args:
    repo: The repository root.

  Returns:
    The parsed `review.classes` value; None when the settings carry none.

  Raises:
    RuntimeError: When the core call fails or prints anything but JSON.
  """
  try:
    return json.loads(_call_core(repo, _CORE_GET, _SECTION, _KEY_FLAG, _CLASSES_KEY) or "null")
  except json.JSONDecodeError as error:
    raise RuntimeError(f"{_CORE_GET} {_SECTION} returned malformed JSON: {error}") from error


def _call_core(repo: Path, *args: str) -> str:
  """
  Run one core CLI verb against the repository and return what it printed.

  Args:
    repo: The repository root passed to the verb.
    *args: The verb and its arguments.

  Returns:
    The verb's stdout.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, runs past its time limit, its output cannot be
      decoded, or the verb exits non-zero.
  """
  # a spawn the system refuses, a call that runs past its time limit, or output that is not UTF-8 is a failed core
  # call like any other
  try:
    res = subprocess.run(
        [ sys.executable, str(spec_paths.resolve_core_cli(repo)), *args, _CWD_FLAG, str(repo) ],
        cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
        timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{args[0]} {_SECTION} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{args[0]} {_SECTION} could not run: {error}") from error

  # guard: a failed core call leaves the settings unknown, so the run stops
  if res.returncode != 0:
    raise RuntimeError(f"{args[0]} {_SECTION} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]}")

  # the verb's output as printed
  return res.stdout


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when an `architecture` entry would change, 1 when none would.
    - Any failure of the migration, a failed core call included, exits 2 under every flag, never an answer `--check`
      gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when the class would change and 1 when it would not; 0 otherwise; 2 when the
    migration failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when an `architecture` entry would change, 1 when none
  # would; any failure of the migration, a failed core call included, MUST exit 2, so a migration step's
  # `applies_when` predicate never reads a failure as an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-review-class")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure, a core call's or any other, exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    # a failed core call, malformed settings, or any other fault is not an answer and must never look like one
    sys.stderr.write(f"migrate-review-class: {error}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 1 if result[_ACTION_KEY] == _NONE else 0
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
