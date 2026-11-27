"""
Migration behind the `lazycortex-specs migrate-playbook-names` verb, which rewrites the old keys of the renamed
shipped playbooks in a consumer's settings to their new keys.

Every string value of the tracked settings and of the gitignored local overlay beside them that is exactly one of the
old shipped playbook keys becomes its new key; every other value, every key and the order of keys and lists stay as
read. The migration never commits.
"""
from __future__ import annotations

import argparse
import json
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
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The plugin prefix every renamed key carries.
_PREFIX = "lazycortex-specs:lazy-spec."

# Every old shipped playbook key and the key that replaced it: the asset-type playbooks now end in `-type`, the job
# playbooks in `-job`.
_RENAMES = {
    f"{_PREFIX}feature-playbook": f"{_PREFIX}feature-type",
    f"{_PREFIX}change-playbook": f"{_PREFIX}change-type",
    f"{_PREFIX}bug-playbook": f"{_PREFIX}bug-type",
    f"{_PREFIX}content-playbook": f"{_PREFIX}content-type",
    f"{_PREFIX}research-playbook": f"{_PREFIX}research-type",
    f"{_PREFIX}release-playbook": f"{_PREFIX}release-type",
    f"{_PREFIX}tool-code-playbook": f"{_PREFIX}build-job",
    f"{_PREFIX}tool-test-playbook": f"{_PREFIX}test-job",
    f"{_PREFIX}tool-research-playbook": f"{_PREFIX}research-job",
}

# The tracked settings file and its gitignored local overlay, each read here alone and written through the core verb
# that owns it: the tracked layer verbatim, the overlay through its own scope, which core never stamps.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_LOCAL_REL = Path(".claude") / "lazy.settings.local.json"
_CORE_SET = "settings-set"
_VERBATIM_FLAG = "--verbatim"
_SCOPE_FLAG = "--scope"
_LOCAL_SCOPE = "local"
_CWD_FLAG = "--cwd"

# The separator of a reported dotted settings path.
_PATH_SEP = "."

# The result's wire-shape keys and the action values, read by the migration step and the tests.
_ACTION_KEY = "action"
_RENAMED_KEY = "renamed"
_LOCAL_ACTION_KEY = "local_action"
_LOCAL_RENAMED_KEY = "local_renamed"
_PATH_KEY = "path"
_FROM_KEY = "from"
_TO_KEY = "to"
_RENAMED = "renamed"
_NONE = "none"

_ENCODING = "utf-8"

# How a subprocess's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Rename the old shipped playbook keys in the tracked settings and in the local overlay to their new keys.

  Guarantees:
    - In each settings layer, the tracked file and the local overlay, only a string value equal to an old playbook
      key changes, by becoming its new key. Every other value, every key and the order of keys and lists stay as
      read.
    - The tracked settings file and the local overlay are each read and written alone; a rename found in one layer is
      never written to the other.
    - An absent local overlay is never created.
    - A dry run and a run with nothing to rename write nothing.
    - Each layer's renames are reported in that layer's document order: sections as the file lists them, then object
      values in key order and list items in index order. The two layers are reported in separate lists.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    A mapping with `action` and `renamed` for the tracked settings and `local_action` and `local_renamed` for the
    local overlay: an action is `renamed` when at least one value of that layer is renamed and `none` otherwise; the
    renamed list holds one `path`, `from`, `to` entry per renamed value and is empty for `none`.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, a core call runs past its time limit or exits
      non-zero.
    FileNotFoundError: When no tracked settings file exists at or above `repo`.
    ValueError: When the tracked settings file or the local overlay is malformed.
  """

  # Contract:
  # In each settings layer, the tracked file and the local overlay, only a string value exactly equal to an old
  # playbook key changes, by becoming its new key. Dict keys, every other value and the order of keys and lists stay
  # as read.

  # Contract:
  # The tracked settings file and the local overlay are each read and written alone. A rename found in one layer is
  # written to that layer only, and a write to one layer never touches the other.

  # Contract:
  # An absent local overlay MUST never be created.

  # Contract:
  # A dry run and a run with nothing to rename MUST write nothing; a migration step's `applies_when` predicate and
  # its rerun rely on that.

  # Contract:
  # Each reported list, `renamed` for the tracked settings and `local_renamed` for the local overlay, holds its
  # entries in document order of its own layer: sections in the order the file lists them, and inside a section
  # object values in key order and list items in index order, nested values before the next sibling. The entries of
  # the two layers are never merged into one list.

  settings_root = spec_paths.require_settings_root(repo)

  # each layer is read and rewritten alone; an absent overlay carries nothing and is never created
  local_path = settings_root / _LOCAL_REL
  renamed, changed = _rename_layer(spec_paths.read_settings(settings_root / _SETTINGS_REL))
  local_renamed, local_changed = _rename_layer(spec_paths.read_settings(local_path)) if local_path.is_file() \
      else ([], [])

  # unless the run is dry, each changed section goes back whole to the layer it came from
  if not dry_run:
    for section, rewritten in changed:
      _write_settings(settings_root, section, json.dumps(rewritten), _VERBATIM_FLAG)
    for section, rewritten in local_changed:
      _write_settings(settings_root, section, json.dumps(rewritten), _SCOPE_FLAG, _LOCAL_SCOPE)
  return {
      _ACTION_KEY: _RENAMED if renamed else _NONE, _RENAMED_KEY: renamed,
      _LOCAL_ACTION_KEY: _RENAMED if local_renamed else _NONE, _LOCAL_RENAMED_KEY: local_renamed,
  }


def _rename_layer(settings: dict) -> tuple[list[dict], list[tuple[str, object]]]:
  """
  Work out the playbook renames of one settings layer.

  Args:
    settings: One parsed settings layer, the tracked file or the local overlay.

  Returns:
    The `path`, `from`, `to` entries of every renamed value in document order, and each section that changed paired
    with its rewritten value.
  """
  renamed: list[dict] = []
  changed: list[tuple[str, object]] = []

  # every object-valued section rewritten in document order; only a section that changed is kept for the write
  for section, value in settings.items():
    # guard: a section that is not an object is no settings section the core verb could write back
    if not isinstance(value, dict):
      continue

    # the section rewritten with every rename it carries collected; a section without one is not written back
    found: list[dict] = []
    rewritten = _rewrite(value, section, found)
    if found:
      renamed.extend(found)
      changed.append(( section, rewritten ))
  return renamed, changed


# waiver: `value` is any node of operator-edited JSON; the body narrows it and hands anything else back as read
def _rewrite(value: object, path: str, found: list[dict]) -> object:
  """
  Return a settings node with every old playbook key in it replaced by its new key.

  Args:
    value: One node of the parsed settings: an object, a list, or a scalar.
    path: The dotted settings path of the node, used to report each rename.
    found: The list that gains one `path`, `from`, `to` entry per renamed value, in document order.

  Returns:
    The rewritten node, with keys and the order of keys and lists as read.
  """
  # an object keeps its keys and their order, each value rewritten in turn
  if isinstance(value, dict):
    return { key: _rewrite(item, f"{path}{_PATH_SEP}{key}", found) for key, item in value.items() }

  # a list keeps its order, each item rewritten under its index
  if isinstance(value, list):
    return [ _rewrite(item, f"{path}{_PATH_SEP}{index}", found) for index, item in enumerate(value) ]

  # only a string equal to an old key changes; every other value goes back as read
  if isinstance(value, str) and value in _RENAMES:
    found.append({ _PATH_KEY: path, _FROM_KEY: value, _TO_KEY: _RENAMES[value] })
    return _RENAMES[value]
  return value


def _write_settings(settings_root: Path, section: str, payload: str, *layer_args: str) -> None:
  """
  Write one settings section back whole through the core `settings-set` verb.

  Args:
    settings_root: The repository root holding the tracked settings.
    section: The name of the settings section to write.
    payload: The JSON text of the whole section.
    *layer_args: The core verb's arguments naming the layer written: `--verbatim` for the tracked file,
      `--scope local` for the overlay.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, runs past its time limit, or exits non-zero.
  """
  # a spawn the system refuses, or a call that runs past its time limit, is a failed core call like any other;
  # undecodable output bytes are replaced, never raised on
  try:
    res = subprocess.run(
        [ sys.executable, str(spec_paths.resolve_core_cli(settings_root)), _CORE_SET, section, *layer_args,
          _CWD_FLAG, str(settings_root) ],
        input = payload, cwd = str(settings_root), capture_output = True, text = True, check = False,
        encoding = _ENCODING, errors = _DECODE_ERRORS, timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{_CORE_SET} {section} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{_CORE_SET} {section} could not run: {error}") from error

  # guard: a failed core call leaves the section unwritten, so the run stops
  if res.returncode != 0:
    raise RuntimeError(
        f"{_CORE_SET} {section} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]} "
        f"stdout={res.stdout.strip()[:240]}")


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when a value in either settings layer would be renamed, 1 when none
      would.
    - Any failure of the migration, a failed core call or malformed settings included, exits 2 under every flag,
      never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names a
      directory inside the repository (falling back to the `LAZY_REPO_ROOT` environment variable, then the process
      working directory); the run works in the nearest directory at or above it, within its checkout, that holds
      `.claude/lazy.settings.json`, else the checkout's root.

  Returns:
    Exit code: with `--check`, 0 when a value would be renamed and 1 when none would; 0 otherwise; 2 when the
    migration failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when a value in either settings layer, the tracked file or
  # the local overlay, would be renamed, 1 when none would.

  # Contract:
  # Any failure of the migration, a failed core call or malformed settings included, MUST exit 2 under every flag, so
  # a migration step's `applies_when` predicate never reads a failure as an answer.

  # the verb's flags: two ways to run without writing, and the repository root
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-playbook-names")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # a check runs dry; any failure, a core call's or any other, exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(spec_locator.query_settings_root(args.cwd), dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    # a failed core call, malformed settings, or any other fault is not an answer and must never look like one
    sys.stderr.write(f"migrate-playbook-names: {error}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 1 if result[_ACTION_KEY] == _NONE and result[_LOCAL_ACTION_KEY] == _NONE else 0
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
