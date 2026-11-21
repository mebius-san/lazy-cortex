"""
Migration behind the `lazycortex-specs migrate-plan-context` verb, which gives the `code-plan` review classes in a
consumer's settings the `context_from_verbs` field.

The shared `code-plan` class and every product-scoped `code-plan@<key>` class that lacks the field gain the value the
install seeds, in the tracked settings and in the gitignored local overlay beside them; every other class, every
other key and the list order stay as read. The migration never commits.
"""
from __future__ import annotations

import argparse
import copy
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

# The class kind that gains the field, and the separator of a product-scoped `<kind>@<key>` token.
_PLAN_KIND = "code-plan"
_SCOPE_SEP = "@"

# The identity key of a review class entry, and the field this verb adds.
_CLASS_KEY = "class"
_FIELD = "context_from_verbs"

# Decision: the value is written as the install seed writes it, not computed from the product — the verb it names
# answers per document, so one entry serves every product.

# The value of the field: one context file computed by the specs CLI from the document's path.
_SEEDED_VALUE = [ {
    "name": "specialists.json",
    "command": [ "lazycortex-specs", "resolve-product", "specialists-by-path", "{doc}" ],
} ]

# The settings section and the key inside it the verb reads and writes, through the core verbs that own them.
_SECTION = "review"
_CLASSES_KEY = "classes"
_CORE_GET = "settings-get"
_CORE_SET = "settings-set"
_KEY_FLAG = "--key"
_VALUE_FLAG = "--value"
_CWD_FLAG = "--cwd"
_SCOPE_FLAG = "--scope"

# The settings layers, each read and written alone through its scope.
_TRACKED_SCOPE = "tracked"
_LOCAL_SCOPE = "local"

# The environment variable naming the repository root when `--cwd` is absent.
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's wire-shape keys and the action values, read by the migration step and the tests.
_ACTION_KEY = "action"
_CLASSES_RESULT_KEY = "classes"
_LOCAL_ACTION_KEY = "local_action"
_LOCAL_CLASSES_RESULT_KEY = "local_classes"
_ADDED = "added"
_NONE = "none"

# The exit code of a run the core call failed, told apart from both `--check` answers.
_EXIT_FAILED = 2

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Add the `context_from_verbs` field to the `code-plan` review classes that lack it.

  Guarantees:
    - In each settings layer, the tracked file and the local overlay, only a `code-plan` or `code-plan@<key>` entry
      without the field changes, by gaining the seeded field. A present field, an empty list included, every other
      class, every other key and the order of the list stay as read.
    - The tracked settings file and the local overlay are each read and written alone; the classes of one layer are
      never written to the other.
    - An absent local overlay is never created.
    - A dry run and a run with nothing to add write nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    A mapping with `action` and `classes` for the tracked settings and `local_action` and `local_classes` for the
    local overlay: an action is `added` when at least one class of that layer gains the field and `none` otherwise;
    the classes list the class tokens that gain it, in list order, and is empty for `none`.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, a core call runs past its time limit or exits
      non-zero, or `settings-get` prints anything but JSON.
  """

  # Contract:
  # In each settings layer, the tracked file and the local overlay, only a `code-plan` or `code-plan@<key>` entry
  # without the `context_from_verbs` key changes, by gaining the seeded field. A present field, an empty list
  # included, every other class, every other key and the order of the list stay as read.

  # Contract:
  # The tracked settings file and the local overlay are each read and written alone. The classes of one layer are
  # written to that layer only, and a write to one layer never touches the other.

  # Contract:
  # An absent local overlay MUST never be created.

  # Contract:
  # A dry run and a run with nothing to add MUST write nothing; a migration step's `applies_when` predicate and its
  # rerun rely on that.

  settings_root = spec_paths.find_settings_root(repo)

  # both layers are read and migrated alone before either is written, so a layer that fails to read leaves the other
  # unwritten too
  tracked_classes, tracked_added = _migrate_layer(settings_root, _TRACKED_SCOPE)
  local_classes, local_added = _migrate_layer(settings_root, _LOCAL_SCOPE)

  # unless the run is dry, each layer that gained a field goes back whole to itself; an overlay without one is never
  # written, so an absent one is never created
  if not dry_run:
    for scope, classes, added in ( ( _TRACKED_SCOPE, tracked_classes, tracked_added ),
                                   ( _LOCAL_SCOPE, local_classes, local_added ) ):
      if added:
        _call_core(settings_root, _CORE_SET, _SECTION, _SCOPE_FLAG, scope, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG,
                   json.dumps(classes))
  return {
      _ACTION_KEY: _ADDED if tracked_added else _NONE, _CLASSES_RESULT_KEY: tracked_added,
      _LOCAL_ACTION_KEY: _ADDED if local_added else _NONE, _LOCAL_CLASSES_RESULT_KEY: local_added,
  }


def _migrate_layer(settings_root: Path, scope: str) -> tuple[list, list[str]]:
  """
  Read one settings layer's review classes and return them with the `code-plan` classes given the field.

  Args:
    settings_root: The settings root.
    scope: The settings layer read, `tracked` or `local`.

  Returns:
    A pair: the layer's classes in list order with the field added where it was missing, and the class tokens that
    gained it, in list order. Both are empty when the layer carries no classes list; the second is empty when no
    class lacks the field.

  Raises:
    RuntimeError: When a core call fails or prints anything but JSON.
  """
  # guard: a layer without a classes list carries no class to extend
  if not isinstance(classes := _read_classes(settings_root, scope), list):
    return [], []

  # one pass in list order, so every entry stays where it was
  migrated: list = []
  added: list[str] = []
  for entry in classes:
    # a plan class without the field goes back with a deep copy of the seed, so no two classes share one list;
    # any other entry goes back as read
    if _is_missing_field(entry):
      migrated.append({ **entry, _FIELD: copy.deepcopy(_SEEDED_VALUE) })
      added.append(entry[_CLASS_KEY])
    else:
      migrated.append(entry)
  return migrated, added


# waiver: `entry` is one item of operator-edited JSON and may be any JSON value; the body narrows it
def _is_missing_field(entry: object) -> bool:
  """
  Report whether a review class entry is a `code-plan` class without the field.

  Args:
    entry: One item of the classes list.

  Returns:
    True when the entry is an object naming a `code-plan` class, scoped or not, and has no `context_from_verbs` key.
  """
  # guard: an item that is not an object names no class at all
  if not isinstance(entry, dict):
    return False

  # the kind is the token's part before a scope separator; a present field, whatever its value, is the operator's
  token = entry.get(_CLASS_KEY)
  return isinstance(token, str) and token.split(_SCOPE_SEP, 1)[0] == _PLAN_KIND and _FIELD not in entry


def _read_classes(repo: Path, scope: str) -> object:
  """
  Read one settings layer's review classes through the core `settings-get` verb.

  Args:
    repo: The repository root.
    scope: The settings layer read, `tracked` or `local`.

  Returns:
    The parsed `review.classes` value of that layer; None when the layer carries none.

  Raises:
    RuntimeError: When the core call fails or prints anything but JSON.
  """
  try:
    return json.loads(_call_core(repo, _CORE_GET, _SECTION, _SCOPE_FLAG, scope, _KEY_FLAG, _CLASSES_KEY) or "null")
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
    - With `--check`, writes nothing and exits 0 when a class in either settings layer would gain the field, 1 when
      none would.
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
    SystemExit: With code 2, when an argument is unknown or malformed.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when a class in either settings layer, the tracked file or
  # the local overlay, would gain the field, 1 when none would.

  # Contract:
  # Any failure of the migration, a failed core call included, MUST exit 2 under every flag, so a migration step's
  # `applies_when` predicate never reads a failure as an answer.

  # the verb's flags: two ways to run without writing, and the repository root
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-plan-context")
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
    sys.stderr.write(f"migrate-plan-context: {error}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 1 if result[_ACTION_KEY] == _NONE and result[_LOCAL_ACTION_KEY] == _NONE else 0
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
