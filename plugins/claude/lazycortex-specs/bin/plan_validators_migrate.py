"""
Logic behind the `lazycortex-specs migrate-plan-validators` verb — drops the validators of the plan review classes in
a consumer's settings.

The plan documents carry no validators any more. This verb removes the `experts.validation` block from the
`code-plan`, `test-plan` and `system-test-plan` entries of `review.classes`, leaving every other class, every other
key and the list order as read. Settings are read and written only through the core CLI. It never commits.
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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# How a subprocess's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# Decision: only the bare class tokens match, never a product-scoped `<kind>@<key>` class — a scoped class exists to
# hold the reviewer an operator wired for one product, and that choice is not a seeded default to retire.

# The review classes of the plan documents, which carry no validators.
_PLAN_CLASSES = frozenset({ "code-plan", "test-plan", "system-test-plan" })

# The identity key of a review class entry, and the keys leading to its validators.
_CLASS_KEY = "class"
_EXPERTS_KEY = "experts"
_VALIDATION_KEY = "validation"

# The settings section and the key inside it the verb reads and writes, through the core verbs that own them.
_SECTION = "review"
_CLASSES_KEY = "classes"
_CORE_GET = "settings-get"
_CORE_SET = "settings-set"
_KEY_FLAG = "--key"
_VALUE_FLAG = "--value"
_CWD_FLAG = "--cwd"

# The environment variable naming the repository root when `--cwd` is absent.
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's wire-shape keys and the action values, read by the migration step and the tests.
_ACTION_KEY = "action"
_CLASSES_RESULT_KEY = "classes"
_DROPPED = "dropped"
_NONE = "none"

# The exit code of a run the core call failed, told apart from both `--check` answers.
_EXIT_FAILED = 2

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Drop the validators of the plan review classes in the repository's settings.

  Guarantees:
    - Only the `experts.validation` key of a `code-plan`, `test-plan` or `system-test-plan` entry changes: it is
      removed. Every other key of that entry, every other class — a product-scoped `<kind>@<key>` class included —
      and the order of the list stay as read.
    - A dry run and a run with no validators to drop write nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"action", "classes"}` — `action` is `dropped` or `none` when no plan class carries validators; `classes` lists
    the class tokens that lost their validators, in list order.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, a core call runs past its time limit or exits
      non-zero, or `settings-get` prints anything but JSON.
  """

  # Contract:
  # Only the `experts.validation` key of a `code-plan`, `test-plan` or `system-test-plan` entry changes: it is
  # removed, and every other key of that entry, every other class — a product-scoped `<kind>@<key>` class included —
  # and the order of the list stay as read. A dry run and a run with no validators to drop MUST call no
  # `settings-set`; a migration step's `applies_when` predicate and its rerun rely on that.

  settings_root = spec_paths.find_settings_root(repo)
  classes = _read_classes(settings_root)

  # guard: settings without a classes list carry no validators to drop
  if not isinstance(classes, list):
    return { _ACTION_KEY: _NONE, _CLASSES_RESULT_KEY: [] }

  # one pass in list order, so every entry stays where it was
  migrated: list = []
  dropped: list[str] = []
  for entry in classes:
    # an entry with validators on a plan class goes back without them; any other goes back as read
    if _has_plan_validators(entry):
      experts = { key: value for key, value in entry[_EXPERTS_KEY].items() if key != _VALIDATION_KEY }
      migrated.append({ **entry, _EXPERTS_KEY: experts })
      dropped.append(entry[_CLASS_KEY])
    else:
      migrated.append(entry)

  # no plan class carries validators: the answer is `none`, and nothing is written
  if not dropped:
    return { _ACTION_KEY: _NONE, _CLASSES_RESULT_KEY: [] }

  # the whole list goes back through the core verb, unless the run is dry
  if not dry_run:
    _call_core(settings_root, _CORE_SET, _SECTION, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG, json.dumps(migrated))
  return { _ACTION_KEY: _DROPPED, _CLASSES_RESULT_KEY: dropped }


def _has_plan_validators(entry: object) -> bool:
  """
  Report whether a review class entry is a plan class that carries validators.

  Args:
    entry: One item of the classes list.

  Returns:
    True when the entry is an object naming a plan class whose `experts.validation` block is present and non-empty.
  """
  # guard: an item that is not an object names no class at all
  if not isinstance(entry, dict):
    return False

  # the validators sit under the experts of a plan class; any other class, and an absent or empty block, is nothing
  # to drop
  experts = entry.get(_EXPERTS_KEY)
  return entry.get(_CLASS_KEY) in _PLAN_CLASSES and isinstance(experts, dict) and bool(experts.get(_VALIDATION_KEY))


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
    RuntimeError: When the core CLI cannot be resolved or started, runs past its time limit, or the verb exits
      non-zero.
  """
  # a spawn the system refuses, or a call that runs past its time limit, is a failed core call like any other;
  # undecodable output bytes are replaced, never raised on
  try:
    res = subprocess.run(
        [ sys.executable, str(spec_paths.resolve_core_cli(repo)), *args, _CWD_FLAG, str(repo) ],
        cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
        errors = _DECODE_ERRORS,
        timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{args[0]} {_SECTION} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{args[0]} {_SECTION} could not run: {error}") from error

  # guard: a failed core call leaves the settings unknown, so the run stops
  if res.returncode != 0:
    raise RuntimeError(f"{args[0]} {_SECTION} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]}")

  # a successful call answers on stdout; stderr carried only the failure text read above
  return res.stdout


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when a plan class would lose its validators, 1 when none would.
    - Any failure of the migration, a failed core call included, exits 2 under every flag, never an answer `--check`
      gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a class would change and 1 when none would; 0 otherwise; 2 when the migration
    failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when a plan class would lose its validators, 1 when none
  # would; any failure of the migration, a failed core call included, MUST exit 2, so a migration step's
  # `applies_when` predicate never reads a failure as an answer.

  # the verb's flags: two ways to run without writing, and the repository root
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-plan-validators")
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
    sys.stderr.write(f"migrate-plan-validators: {error}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 1 if result[_ACTION_KEY] == _NONE else 0
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
