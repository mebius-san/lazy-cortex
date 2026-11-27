"""
Migration behind the `lazycortex-specs migrate-report-class` verb, which moves a consumer onto the build report review.

The shared `code-report` review class and every product-scoped `code-report@<key>` class gain the three keys the
install seeds, in the tracked settings and in the gitignored local overlay beside them; every other class, every
other key and the key order stay as read. A `build-branch.json` context entry that still carries the plain
registry read gains the backfill flag in place. The verb creates no build registry. Every retired per-test branch
`spec/<product>/releases/<release>/test-<k>` is force-deleted, merged or not, and no other branch is touched; a
checked-out one refuses the run before anything is written. The migration never commits.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
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


# How a subprocess's output is decoded, and how its undecodable bytes are read: replaced, so odd output never raises.
_ENCODING = "utf-8"
_DECODE_ERRORS = "replace"

# The class kind that gains the keys, and the separator of a product-scoped `<kind>@<key>` token.
_REPORT_KIND = "code-report"
_SCOPE_SEP = "@"

# The identity key of a review class entry and the three keys this verb adds.
_CLASS_KEY = "class"
_REPORT_FIELD = "report"
_PROTOCOLS_FIELD = "protocols"
_CONTEXT_FIELD = "context_from_verbs"
_CONTEXT_NAME = "name"

# Decision: the values are written as the install seed writes them, not computed per product — the verb the context
# entry names answers per document, so one entry serves every product.

# The values of the three keys, as the install seeds them on a new `code-report` class.
_SEEDED_REPORT = True
_SEEDED_PROTOCOL = "lazycortex-specs:lazy-spec.build-job"
_SEEDED_PROTOCOLS = ( "lazycortex-specs:lazy-spec.expert-signals-protocol", _SEEDED_PROTOCOL )
_SEEDED_CONTEXT = {
    "name": "build-branch.json",
    "command": [ "lazycortex-specs", "build-registry", "get", "{doc}", "--backfill" ],
}

# The command an earlier run of this migration wrote into the context entry, before the read could backfill.
_OLD_CONTEXT_COMMAND = [ "lazycortex-specs", "build-registry", "get", "{doc}" ]

# The key of a context entry that holds the verb it runs.
_CONTEXT_COMMAND = "command"

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

# The retired per-test branch name `spec/<product>/releases/<release>/test-<k>`, read segment by segment so a
# product or release never spans a `/`, and the git ref namespace the branches are read from.
_BRANCH_SEP = "/"
_TEST_BRANCH_SEGMENTS = 5
_SPEC_SEGMENT = "spec"
_RELEASES_SEGMENT = "releases"
_TEST_PREFIX = "test-"
_SPEC_HEADS = "refs/heads/spec/"
_GIT = "git"

# The git subcommands the branches are read and force-deleted with, and the worktree listing that names the branch
# each worktree has checked out.
_FOR_EACH_REF = "for-each-ref"
_REF_FORMAT = "--format=%(refname:short)"
_BRANCH = "branch"
_FORCE_DELETE = "-D"
_WORKTREE = "worktree"
_WORKTREE_LIST = "list"
_PORCELAIN = "--porcelain"

# The line prefixes of the porcelain worktree listing: a worktree's path, and the full ref of the branch it holds.
_WORKTREE_LINE = "worktree "
_BRANCH_LINE = "branch "
_HEADS_PREFIX = "refs/heads/"

# The entry a checkout carries at its root, and the variable naming an explicit git directory
_DOT_GIT = ".git"
_ENV_GIT_DIR = "GIT_DIR"

# The result's wire-shape keys, read by the migration step and the tests.
_CLASSES_UPDATED = "classes_updated"
_DELETED_TEST_BRANCHES = "deleted_test_branches"

# The exit codes of `--check`, and of a run that failed, told apart from both `--check` answers.
_EXIT_OK = 0
_EXIT_PENDING = 0
_EXIT_NOTHING = 1
_EXIT_FAILED = 2

# The seconds a core or git call may run before it counts as failed.
_CALL_TIMEOUT_S = 120


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Give the `code-report` review classes their build report keys and delete the retired per-test branches.

  Guarantees:
    - In each settings layer, the tracked file and the local overlay, only a `code-report` or `code-report@<key>`
      entry changes, and only by gaining what it lacks: `report: true` when the key is absent, the full seeded
      `protocols` list (`lazycortex-specs:lazy-spec.expert-signals-protocol`, then
      `lazycortex-specs:lazy-spec.build-job`) when the key is absent or the build-job id appended to a present
      `protocols` list that lacks it, and the `build-branch.json` context entry appended to a `context_from_verbs`
      list with no entry of that name (the key added as a one-entry list when absent).
    - A `build-branch.json` context entry whose command is exactly the plain read
      `["lazycortex-specs", "build-registry", "get", "{doc}"]` has that command replaced, in place, by the seeded
      command ending in `--backfill`; an entry with any other command stays as read.
    - A value of `protocols` or `context_from_verbs` that is not a list, a present `report` value, every other key,
      the key order and every other class stay as read; a class the operator renamed is left alone.
    - The two settings layers are each read and written alone, and an absent local overlay is never created.
    - No build registry is created.
    - Every local branch named `spec/<product>/releases/<release>/test-<k>`, each part one path segment, is deleted,
      merged or not, and no other branch is deleted; build branches `build-<k>` stay. One checked out in any worktree
      of the checkout makes the migration raise, naming the branch and that worktree's path, before anything is
      written. Outside every git checkout nothing is deleted.
    - Unless the run is dry, the branches are deleted before any settings layer is written, so a failed deletion
      leaves every settings file unwritten.
    - A dry run writes and deletes nothing.
    - `deleted_test_branches` holds the sorted names of the branches deleted, or in a dry run the branches that would
      be deleted.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    A mapping with `classes_updated`, the tokens of the classes that gained a key, the tracked layer first and the
    local overlay after it; and `deleted_test_branches`, the sorted names of the per-test branches deleted, or in a
    dry run the branches that would be deleted.

  Raises:
    RuntimeError: When a core call cannot run, runs past its time limit or exits non-zero, `settings-get` prints
      anything but JSON, a per-test branch is checked out in any worktree, or, inside a git checkout, git is missing
      or a git call fails or runs past its time limit.
  """

  # Contract:
  # In each settings layer, the tracked file and the local overlay, only a `code-report` or `code-report@<key>` entry
  # changes, and only by gaining what it lacks: `report` when absent, the build-job protocol in `protocols`, the
  # `build-branch.json` entry in `context_from_verbs`, and the backfill flag on a `build-branch.json` entry that
  # still carries the plain registry read. A non-list value of either list key, a present `report` value, a
  # `build-branch.json` entry with any other command, every other key and the key order stay as read, and a class
  # the operator renamed is left alone.

  # Contract:
  # The tracked settings file and the local overlay are each read and written alone, and an absent local overlay
  # MUST never be created.

  # Contract:
  # No build registry is created: a release that built before the registry existed gets its registry from the spec
  # coordinator in the daemon's checkout, where its build branches live.

  # Contract:
  # Every local branch named `spec/<product>/releases/<release>/test-<k>`, each part one path segment, is deleted,
  # merged or not, and no other branch is ever deleted; build branches `build-<k>` stay, they belong to
  # `build-registry prune`. When such a branch is checked out in any worktree of the checkout, this one or another,
  # the migration MUST refuse by raising an error that names the branch and that worktree's path, before writing
  # anything. Outside every git checkout there is nothing to delete.

  # Contract:
  # Unless the run is dry, the branches are deleted before any settings layer is written, so a deletion that fails
  # MUST leave every settings file unwritten.

  # Contract:
  # A dry run MUST write and delete nothing; a migration step's `applies_when` predicate relies on that.

  # Contract:
  # The result key `deleted_test_branches` holds the sorted names of the branches deleted, or in a dry run the
  # branches that would be deleted.

  settings_root = spec_paths.find_settings_root(repo)

  # both layers are read and migrated before anything is written, so a layer that fails to read leaves every file
  # unwritten
  tracked_classes, tracked_updated = _migrate_layer(settings_root, _TRACKED_SCOPE)
  local_classes, local_updated = _migrate_layer(settings_root, _LOCAL_SCOPE)

  # the per-test branches are found before anything is written too, so one checked out in any worktree refuses the
  # whole run
  test_branches = _test_branches(settings_root)

  # unless the run is dry, the branches go first, so a deletion that fails leaves every settings file unwritten;
  # then each layer that changed goes back whole to itself, and an overlay without a change is never written, so an
  # absent one is never created
  if not dry_run:
    if test_branches:
      _run_git(settings_root, _BRANCH, _FORCE_DELETE, *test_branches)
    for scope, classes, updated in ( ( _TRACKED_SCOPE, tracked_classes, tracked_updated ),
                                     ( _LOCAL_SCOPE, local_classes, local_updated ) ):
      if updated:
        _call_core(settings_root, _CORE_SET, _SECTION, _SCOPE_FLAG, scope, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG,
                   json.dumps(classes))

  # the result lists what changed, or in a dry run would change
  return {
      _CLASSES_UPDATED: [ *tracked_updated, *local_updated ],
      _DELETED_TEST_BRANCHES: test_branches,
  }


def _migrate_layer(settings_root: Path, scope: str) -> tuple[list, list[str]]:
  """
  Read one settings layer's review classes and return them with the `code-report` classes extended.

  Args:
    settings_root: The settings root.
    scope: The settings layer read, `tracked` or `local`.

  Returns:
    A pair: the layer's classes in list order with each `code-report` class extended, and the tokens of the classes
    that changed, in list order. Both are empty when the layer carries no classes list.

  Raises:
    RuntimeError: When a core call fails or prints anything but JSON.
  """
  # guard: a layer without a classes list carries no class to extend
  if not isinstance(classes := _read_classes(settings_root, scope), list):
    return [], []

  # one pass in list order, so every entry stays where it was
  migrated: list = []
  updated: list[str] = []
  for entry in classes:
    # a migrated entry is a new object; one left as read is the same object, so identity tells the change
    new_entry = _migrate_entry(entry)
    migrated.append(new_entry)
    if new_entry is not entry:
      updated.append(entry[_CLASS_KEY])
  return migrated, updated


# waiver: `entry` is one item of operator-edited JSON and may be any JSON value; the body narrows it
def _migrate_entry(entry: object) -> object:
  """
  Give one review class entry the build report keys it lacks.

  Args:
    entry: One item of the classes list.

  Returns:
    The entry itself when it is no `code-report` class, scoped or not, or lacks nothing; otherwise a new entry with
    the missing keys added, a plain-read `build-branch.json` command replaced by the seeded one, and the rest as
    read.
  """

  # Domain(spec.lifecycle):
  # # A build report review class gains only what it lacks
  # A review class for build reports, either the shared `code-report` class or a product-scoped
  # `code-report@<key>` class, becomes a report review by gaining only what it lacks: the report flag, the build's
  # protocol and the build-branch context file, which reads the build's record and creates the release's record
  # first when the release built before records existed. A build-branch context file an earlier migration wrote
  # with the plain read gains that creation. Whatever the operator already set stays as it is, and a class the
  # operator renamed is no build report class any more and is left alone.

  # guard: only an object naming a `code-report` class, scoped or not, gains the keys; a renamed class is the
  # operator's and stays as read
  if not isinstance(entry, dict):
    return entry
  token = entry.get(_CLASS_KEY)
  if not isinstance(token, str) or token.split(_SCOPE_SEP, 1)[0] != _REPORT_KIND:
    return entry

  # a copy, so the entry as read is kept for the comparison below; present keys keep their places, absent ones are
  # appended in the order the install seeds them
  new_entry = copy.deepcopy(entry)

  # the report flag is added only when absent; an operator's own value, false included, is theirs
  if _REPORT_FIELD not in new_entry:
    new_entry[_REPORT_FIELD] = _SEEDED_REPORT

  # an absent protocols key gets the whole seeded list; the build's protocol joins a protocols list that lacks it,
  # and a value that is not a list is the operator's
  protocols = new_entry.get(_PROTOCOLS_FIELD)
  if _PROTOCOLS_FIELD not in new_entry:
    new_entry[_PROTOCOLS_FIELD] = list(_SEEDED_PROTOCOLS)
  elif isinstance(protocols, list) and _SEEDED_PROTOCOL not in protocols:
    protocols.append(_SEEDED_PROTOCOL)

  # the build-branch context file joins a context list that has no file of that name; a value that is not a list
  # is the operator's
  contexts = new_entry.get(_CONTEXT_FIELD)
  if _CONTEXT_FIELD not in new_entry:
    new_entry[_CONTEXT_FIELD] = [ copy.deepcopy(_SEEDED_CONTEXT) ]
  elif isinstance(contexts, list) and not any(isinstance(item, dict)
                                              and item.get(_CONTEXT_NAME) == _SEEDED_CONTEXT[_CONTEXT_NAME]
                                              for item in contexts):
    contexts.append(copy.deepcopy(_SEEDED_CONTEXT))

  # the build-branch entry an earlier run wrote with the plain read gains the backfill flag in place; an entry with
  # any other command is the operator's
  if isinstance(contexts, list):
    for item in contexts:
      if (isinstance(item, dict) and item.get(_CONTEXT_NAME) == _SEEDED_CONTEXT[_CONTEXT_NAME]
          and item.get(_CONTEXT_COMMAND) == _OLD_CONTEXT_COMMAND):
        item[_CONTEXT_COMMAND] = list(_SEEDED_CONTEXT[_CONTEXT_COMMAND])

  # an entry that needed nothing goes back as the very object read, which tells the caller it did not change
  return entry if new_entry == entry else new_entry


def _test_branches(settings_root: Path) -> list[str]:
  """
  List the retired per-test branches of the spec releases, refusing when one is checked out.

  Args:
    settings_root: The settings root, where git runs.

  Returns:
    The sorted names of the local branches named `spec/<product>/releases/<release>/test-<k>`; empty when the
    settings root lies outside every git checkout.

  Raises:
    RuntimeError: When such a branch is checked out in any worktree, or the settings root lies inside a git checkout
      and git is missing, cannot run, runs past its time limit or exits non-zero.
  """

  # Domain(spec.lifecycle):
  # # Retired per-test branches are deleted
  # Earlier releases created a branch per test, named `spec/<product>/releases/<release>/test-<k>`. Releases no
  # longer use these branches, and the tester never creates or commits anything, so none of them holds work
  # anyone needs. The migration therefore deletes every one of them, merged or not. Every other branch stays,
  # the build branches included, since removing those is the build registry's own pruning. A per-test branch that
  # is checked out, in this checkout or in another worktree, is never deleted: the migration refuses and names it
  # with the worktree, so the operator switches that worktree away or removes it first.

  # guard: a directory outside every git checkout holds no branch to delete; a broken checkout still reaches git
  # and fails below, since git's own error text does not tell the two apart
  if not _inside_git_checkout(settings_root):
    return []

  # only the retired per-test branches among the local branches under the spec namespace, by name, sorted
  tests = sorted(branch for branch in _run_git(settings_root, _FOR_EACH_REF, _REF_FORMAT, _SPEC_HEADS).split()
                 if _is_test_branch(branch))

  # guard: a branch checked out in any worktree is never deleted, so a per-test one stops the run before anything
  # is written
  checked_out = _checked_out_branches(settings_root) if tests else {}
  if busy := [ branch for branch in tests if branch in checked_out ]:
    raise RuntimeError(f"the per-test branch {busy[0]} is checked out in the worktree {checked_out[busy[0]]}; "
                       "switch it to another branch or remove the worktree first")
  return tests


def _checked_out_branches(settings_root: Path) -> dict[str, str]:
  """
  Map every branch checked out in a worktree of the checkout to that worktree's path.

  Args:
    settings_root: The settings root, where git runs.

  Returns:
    The short branch names mapped to the paths of the worktrees holding them, the checkout itself included; a
    worktree on a detached HEAD holds no branch.

  Raises:
    RuntimeError: When git is missing, cannot run, runs past its time limit or exits non-zero.
  """

  # one pass over the porcelain listing: each worktree's path line comes before the line naming its branch
  checked_out: dict[str, str] = {}
  path = ""
  for line in _run_git(settings_root, _WORKTREE, _WORKTREE_LIST, _PORCELAIN).splitlines():
    if line.startswith(_WORKTREE_LINE):
      path = line[len(_WORKTREE_LINE):]
    elif line.startswith(_BRANCH_LINE):
      checked_out[line[len(_BRANCH_LINE):].removeprefix(_HEADS_PREFIX)] = path
  return checked_out


def _is_test_branch(branch: str) -> bool:
  """
  Report whether a branch name is a retired per-test branch.

  Args:
    branch: The short branch name.

  Returns:
    True when the name is `spec/<product>/releases/<release>/test-<k>`, each part one non-empty path segment;
    False otherwise.
  """
  parts = branch.split(_BRANCH_SEP)
  return (len(parts) == _TEST_BRANCH_SEGMENTS and all(parts) and parts[0] == _SPEC_SEGMENT
          and parts[2] == _RELEASES_SEGMENT and parts[4].startswith(_TEST_PREFIX) and parts[4] != _TEST_PREFIX)


def _run_git(settings_root: Path, *args: str) -> str:
  """
  Run one git command in the settings root and return what it printed.

  Args:
    settings_root: The settings root, where git runs.
    *args: The git arguments.

  Returns:
    The command's stdout.

  Raises:
    RuntimeError: When git is missing, cannot run, runs past its time limit or exits non-zero.
  """
  # guard: without git no branch can be read or deleted, and the migration must not pass for done
  if shutil.which(_GIT) is None:
    raise RuntimeError("git ≥ 2.10 required")

  # a git that cannot run, runs too long or fails stops the run
  try:
    res = subprocess.run(
        [ _GIT, *args ],
        cwd = str(settings_root), capture_output = True, text = True, check = False, encoding = _ENCODING,
        errors = _DECODE_ERRORS, timeout = _CALL_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"git {args[0]} timed out after {_CALL_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"git {args[0]} could not run: {error}") from error
  if res.returncode != 0:
    raise RuntimeError(f"git {args[0]} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]}")
  return res.stdout


def _inside_git_checkout(path: Path) -> bool:
  """
  Report whether a directory lies inside a git checkout.

  Args:
    path: The directory looked at.

  Returns:
    True when the environment names a git directory, or the directory or one of its parents holds a `.git` entry,
    a folder or a worktree's file; False otherwise.
  """
  # an explicit git directory in the environment is what git itself would use
  if os.environ.get(_ENV_GIT_DIR):
    return True

  # a `.git` entry at or above the directory marks a checkout, even one whose repository git cannot read
  return spec_locator.find_nearest_dir(path, _DOT_GIT) is not None


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
        cwd = str(repo), capture_output = True, text = True, check = False, encoding = _ENCODING,
        errors = _DECODE_ERRORS, timeout = _CALL_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{args[0]} {_SECTION} timed out after {_CALL_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{args[0]} {_SECTION} could not run: {error}") from error

  # guard: a failed core call leaves the settings unknown, so the run stops
  if res.returncode != 0:
    raise RuntimeError(f"{args[0]} {_SECTION} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]}")
  return res.stdout


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes and deletes nothing and exits 0 when a class would change or a per-test branch exists,
      1 otherwise.
    - Any failure of the migration exits 2 under every flag, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names a
      directory inside the repository (falling back to the `LAZY_REPO_ROOT` environment variable, then the process
      working directory); the run works in the nearest directory at or above it, within its checkout, that holds
      `.claude/lazy.settings.json`, else the checkout's root.

  Returns:
    Exit code: with `--check`, 0 when a class would change or a per-test branch exists, and 1 otherwise; 0 without
    it; 2 when the migration failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed.
  """

  # Contract:
  # With `--check` the verb MUST write and delete nothing and exit 0 when a class in either settings layer would
  # change or a per-test branch exists, 1 otherwise. An existing per-test branch counts as pending, like a class
  # that would change.

  # Contract:
  # Any failure of the migration MUST exit 2 under every flag, so a migration step's `applies_when` predicate never
  # reads a failure as an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-report-class")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(spec_locator.query_settings_root(args.cwd), dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-report-class: {error}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result, ensure_ascii = False))

  # only a check answers through its exit code; a per-test branch left to delete is pending like a class
  if args.check:
    return _EXIT_PENDING if result[_CLASSES_UPDATED] or result[_DELETED_TEST_BRANCHES] else _EXIT_NOTHING
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
