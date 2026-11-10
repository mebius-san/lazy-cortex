from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import lazy_setup  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import migration_steps  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from constants import MigrationFile, MigrationKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from frontmatter_parser import parse_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from repo_root import resolve_repo_root  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from runtime_state import atomic_write_text  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The manifest under a plugin root that records the plugin's version.
_MANIFEST = ".claude-plugin/plugin.json"
# The manifest field holding the plugin version.
_MANIFEST_VERSION = "version"
# The `root` field of a plugin-root resolution.
_ROOT = "root"
# The frontmatter fence line of a step file.
_FENCE = "---"
# The line endings a step file line may carry, stripped to compare its content.
_EOL = "\r\n"
# The suffix of a step file.
_MD_SUFFIX = ".md"
# Text encoding of step files.
_ENCODING = "utf-8"
# Program name every verb's argparse `prog` starts with.
_PROG = "lazycortex-core"
# The commit whose copy of a step file tells whether a release already landed.
_HEAD = "HEAD"
# The directory under a plugin root holding one settings-ladder file per section.
_LADDER_DIR = "bin/lazy_settings_migrations"
# The suffix of a settings-ladder section file.
_PY_SUFFIX = ".py"
# The package marker of the ladder directory, which is no section.
_PACKAGE_INIT = "__init__.py"
# The module-level name of a section file's ladder dict.
_LADDER_NAME = "MIGRATIONS"
# Exit code of `settings-rungs` when the window adds no rung.
_EXIT_NO_RUNGS = 1
# Exit code of `settings-rungs` when the rungs cannot be read.
_EXIT_FAILED = 2


# ----------------------------------------------------------------------------------------
class _ReportProp(StrEnum):
  """
  Keys of the JSON documents the migration verbs print.

  Attributes:
    STATUS: The outcome word of a check, a stamp, or a refusal.
    REASON: Why a call was refused.
    STEP: The checked step's parsed fields.
    PATH: A file path.
    PLUGINS: The plan's per-plugin reports.
    INSTALLED_VERSION: The version a planned plugin's root records.
    STAMPED: The step files a release set `since` on, or would set it on.
    UNSTAMPED_BEFORE: How many step files carried an empty `since` before the release.
    PLUGIN: The plugin a checked step belongs to.
    NUMBER: A checked step's number.
    SLUG: A checked step's slug.
    RUNGS: The settings-ladder rungs added in a window.
    SECTION: The settings section a rung belongs to.
    VERSION: The ladder key of a rung.
  """

  # The outcome word of a check, a stamp, or a refusal.
  STATUS = "status"
  # Why a call was refused.
  REASON = "reason"
  # The checked step's parsed fields.
  STEP = "step"
  # A file path.
  PATH = "path"
  # The plan's per-plugin reports.
  PLUGINS = "plugins"
  # The version a planned plugin's root records.
  INSTALLED_VERSION = "installed_version"
  # The step files a release set `since` on, or would set it on.
  STAMPED = "stamped"
  # How many step files carried an empty `since` before the release.
  UNSTAMPED_BEFORE = "unstamped_before"
  # The plugin a checked step belongs to.
  PLUGIN = "plugin"
  # A checked step's number.
  NUMBER = "number"
  # A checked step's slug.
  SLUG = "slug"
  # The settings-ladder rungs added in a window.
  RUNGS = "rungs"
  # The settings section a rung belongs to.
  SECTION = "section"
  # The ladder key of a rung.
  VERSION = "version"


# ----------------------------------------------------------------------------------------
class _StatusKind(StrEnum):
  """
  Outcome words under the `status` key, which callers branch on.

  Attributes:
    OK: The call succeeded.
    ERROR: The call was refused; `reason` says why.
  """

  # The call succeeded.
  OK = "ok"
  # The call was refused; `reason` says why.
  ERROR = "error"


def cmd_migrate_plan(argv: list[str]) -> int:
  """
  Run the `migrate-plan` subcommand: print the migration plan of a repository, or check one step file.

  The plan covers the plugins the repository enables and this machine can resolve to a source root; each
  plugin's report also carries the version its root's manifest records, or null when the manifest names
  none. Asked to check a single step file instead, it judges that file against the step format and the
  plugins' write territory.

  Args:
    argv: Argument vector after the subcommand name (`--repo`, `--home`, repeatable `--plugin`, `--check`).

  Returns:
    Process exit code: 0 on a printed plan or an accepted step, 1 on a refusal (an `error` JSON is printed).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser; this includes
      `--check` given without exactly one `--plugin`.
  """
  # the verb's command line
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = f"{_PROG} migrate-plan")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--repo", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--home", default = None, help = "Home directory holding the plugin registry")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--plugin", action = "append", default = None, help = "Plugin to plan (repeatable)")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--check", default = None, help = "Check one step file instead of planning")
  args = parser.parse_args(argv)
  repo = resolve_repo_root(args.repo)

  # a check judges one file on its own
  if args.check is not None:
    # guard: a step belongs to exactly one plugin
    if not args.plugin or len(args.plugin) != 1:
      # waiver: one-off argparse usage message
      parser.error("--check needs exactly one --plugin")
    return _run_step_check(Path(args.check), args.plugin[0], repo = repo)

  # the enabled plugins, each resolved to the root its migrations are read from
  home = Path(args.home) if args.home is not None else Path.home()
  roots = {}
  for name in lazy_setup.discover(repo, home)[_ReportProp.PLUGINS]:
    resolved = lazy_setup.plugin_root(name, repo, home)

    # guard: a plugin this machine cannot resolve has no migrations to read
    if resolved is None:
      continue
    roots[name] = Path(resolved[_ROOT])

  # the plan, narrowed to the named plugins when any are named, each plugin's report extended with the
  # version its root records
  only = set(args.plugin) if args.plugin else None
  try:
    report = migration_steps.plan(repo, home, roots, only = only)
  except ValueError as error:
    return _refuse(str(error))
  for name, entry in report[_ReportProp.PLUGINS].items():
    entry[_ReportProp.INSTALLED_VERSION] = _read_manifest_version(roots[name])

  # the plan on stdout is what the migrate skill reads
  print(json.dumps(report))
  return 0


def cmd_migrate_stamp(argv: list[str]) -> int:
  """
  Run the `migrate-stamp` subcommand: record the version a plugin's migrations are complete for.

  Args:
    argv: Argument vector after the subcommand name (`--repo`, `--plugin`, `--version`).

  Returns:
    Process exit code: 0 with `{"status": "ok", "path": ...}` printed, 1 when the plugin name or the
    version is refused or the stamp cannot be written (an `error` JSON is printed).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = f"{_PROG} migrate-stamp")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--repo", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--plugin", required = True, help = "Plugin whose migrations are complete")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--version", required = True, help = "Plugin version the migrations are complete for")
  args = parser.parse_args(argv)

  # the stamp is written whole; a refused name or version writes nothing
  try:
    path = migration_steps.write_stamp(resolve_repo_root(args.repo), args.plugin, args.version)
  except (OSError, ValueError) as error:
    return _refuse(str(error))

  # the stamp path is what the caller folds into its commit
  print(json.dumps({ _ReportProp.STATUS: _StatusKind.OK, _ReportProp.PATH: str(path) }))
  return 0


def cmd_migrate_release(argv: list[str]) -> int:
  """
  Run the `migrate-release` subcommand: set the release version on every unreleased step of a plugin.

  Guarantees:
    - Only the `since` line of an unreleased step's frontmatter changes; every other byte of the file,
      line endings included, stays as it was. A released step is never written.
    - A step whose `since` already equals the version being released while the HEAD commit's copy has an empty
      `since`, or HEAD has no copy, is still being released: it is listed under `stamped` and left as it is, so
      a release that stopped after stamping lists the same steps when it runs again.
    - Every step file is parsed and validated before the first write, so an invalid step refuses the
      release with no file written.
    - A file that cannot be written mid-release refuses the release with a reason listing the step files
      already stamped.

  Args:
    argv: Argument vector after the subcommand name (`--plugin-dir`, `--version`, `--dry-run`).

  Returns:
    Process exit code: 0 with `{"stamped": [paths], "unstamped_before": n}` printed (`n` counting the listed steps,
    every one of them unreleased at HEAD), 1 when the version or a
    step file is refused or a file cannot be written (an `error` JSON is printed).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """

  # Contract:
  # Only the `since` line of an unreleased step changes, every other byte stays, and a released step is
  # never written; a released step is immutable, and its consumers' stamps are compared against it.

  # Contract:
  # A step stamped with this very version in the worktree but unreleased at HEAD MUST be listed under `stamped`,
  # dry run or not, and never rewritten; the publish that stamped it and then stopped relies on the rerun
  # listing it again for its major-bump gate and its changelog.

  # Contract:
  # Every step file MUST be parsed and validated before the first write, so an invalid step refuses the
  # release with no file written; a write that fails mid-release refuses with a reason listing the step
  # files already stamped, so the caller knows which files changed.

  # the verb's command line
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = f"{_PROG} migrate-release")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--plugin-dir", required = True, help = "Plugin root whose migrations/ is released")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--version", required = True, help = "Plugin version being released")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--dry-run", action = "store_true", help = "List the steps without writing them")
  args = parser.parse_args(argv)

  # Domain(install.reconciliation):
  # # A step takes its release version once, at publication
  # A migration step written since the last publication carries no release version; publishing the plugin
  # gives every such step the version being published. A step that already carries one was released
  # earlier and stays exactly as it is, so a consumer's recorded migrated version keeps meaning the same
  # steps. A step that carries the version being published only in the working copy, while the last commit
  # still holds it unreleased, belongs to a publication that stopped halfway, and it is part of this one.

  # every step is parsed before any is written, so one broken file refuses the whole release
  try:
    migration_steps.version_key(args.version)
    steps = _load_release_steps(Path(args.plugin_dir))
    unreleased = [ step.path for step in steps if step.since is None ]
    resumed = [ step.path for step in steps if step.since == args.version and _read_unreleased_at_head(step.path) ]
  except (OSError, ValueError) as error:
    return _refuse(str(error))

  # the unreleased steps take the version one file at a time, unless this is a dry run; a failed write
  # names what is already stamped
  stamped: list[Path] = []
  if not args.dry_run:
    for path in unreleased:
      try:
        atomic_write_text(path, _with_since(path.read_bytes().decode(_ENCODING), args.version))
      except (OSError, ValueError) as error:
        return _refuse(f"{path.name}: {error}; already stamped: {', '.join(map(str, stamped)) or 'none'}")
      stamped.append(path)

  # the release report lists the stamped steps, those an earlier stopped run already stamped included
  pending = sorted(unreleased + resumed)
  document = { _ReportProp.STAMPED: [ str(path) for path in pending ], _ReportProp.UNSTAMPED_BEFORE: len(pending) }
  print(json.dumps(document))
  return 0


def cmd_settings_rungs(argv: list[str]) -> int:
  """
  Run the `settings-rungs` subcommand: list the settings-ladder rungs a plugin gained since a git revision.

  Guarantees:
    - A rung is a section and a ladder key present in the working tree and absent at the revision; a section
      file the revision does not hold contributes every key it has now, and a key removed since contributes
      nothing.
    - Exit 0 means at least one rung was added and exit 1 means none; every failure exits 2.

  Args:
    argv: Argument vector after the subcommand name (`--plugin-dir`, `--since`).

  Returns:
    Process exit code: 0 with `{"rungs": [{"section": ..., "version": ...}, ...]}` printed when at least one rung
    was added, 1 with the same document and an empty list when none was, 2 when the revision or a section
    file's ladder cannot be read (the reason goes to stderr).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """

  # Contract:
  # A rung MUST be a section and a ladder key present in the working tree and absent at the revision: a section
  # file the revision does not hold contributes every key it has now, and a key removed since contributes
  # nothing; the major-bump gates count exactly these as the settings migrations a release ships.

  # Contract:
  # Exit 0 means at least one rung was added and exit 1 means none; every failure MUST exit 2, so the publish
  # and pre-commit gates never read an unreadable ladder as "no rung".

  # the verb's command line
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = f"{_PROG} settings-rungs")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--plugin-dir", required = True, help = "Plugin root whose settings ladder is read")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--since", required = True, help = "Git revision the ladder is compared against")
  args = parser.parse_args(argv)

  # Domain(settings.versioning):
  # # A new rung of the settings ladder is a new step number, not a new file
  # Each settings section keeps its whole upgrade ladder in one place, numbered by the version each step
  # upgrades from. A plugin that moves a section to a new version adds one numbered step to that section's
  # ladder; a section seen for the first time brings every step it holds. A step removed since the revision
  # adds nothing.

  # the rungs are collected whole; whatever stops the reading is named on stderr and exits 2
  try:
    rungs = _find_all_new_rungs(Path(args.plugin_dir), args.since)
  # waiver: broad catch is the boundary of the gates that read exit 1 as "no new rung"; an uncaught error would
  # exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    # an unknown revision, an unreadable ladder, or any other fault is not an answer and must never look like one
    sys.stderr.write(f"settings-rungs: {error!r}\n")
    return _EXIT_FAILED

  # the rungs on stdout, the exit code saying whether there are any
  print(json.dumps({ _ReportProp.RUNGS: rungs }))
  return 0 if rungs else _EXIT_NO_RUNGS


def _find_all_new_rungs(root: Path, since: str) -> list[dict[str, str | int]]:
  """
  List the settings-ladder keys present in a plugin root's working tree and absent at a git revision.

  Args:
    root: The plugin root.
    since: The git revision to compare against.

  Returns:
    One `{"section": ..., "version": ...}` entry per new key, ordered by section then key; empty when the
    plugin ships no ladder.

  Raises:
    ValueError: When the revision names no commit, or a section file's ladder cannot be read.
    OSError: When git cannot be started or a section file cannot be read.
  """
  directory = root / _LADDER_DIR

  # guard: the plugin ships no settings ladder
  if not directory.is_dir():
    return []

  # the revision must name a commit, else every file would look absent there
  probe = subprocess.run(
    [ "git", "-C", str(directory), "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}" ],
    stdin = subprocess.DEVNULL, capture_output = True, text = True, encoding = _ENCODING, check = False,
  )
  # guard: an unknown revision is a failure, never an empty window
  if probe.returncode != 0:
    raise ValueError(f"unknown revision: {since}")

  # each section file's keys now, minus its keys at the revision
  rungs: list[dict[str, str | int]] = []
  for name in sorted(os.listdir(directory)):
    # guard: only section files carry a ladder
    if not name.endswith(_PY_SUFFIX) or name == _PACKAGE_INIT:
      continue
    path = directory / name
    current = _parse_ladder_keys(path.read_bytes().decode(_ENCODING), name)
    previous = _read_ladder_keys_at(path, since)
    rungs += [ { _ReportProp.SECTION: path.stem, _ReportProp.VERSION: key } for key in sorted(current - previous) ]
  return rungs


def _read_ladder_keys_at(path: Path, revision: str) -> set[int]:
  """
  Read the ladder keys of a section file as a git revision holds it.

  Args:
    path: The section file in the working tree.
    revision: The git revision, already verified to name a commit.

  Returns:
    The ladder keys; empty when the revision holds no copy of the file.

  Raises:
    ValueError: When the revision's copy holds no readable ladder.
    OSError: When git cannot be started.
  """
  # the committed copy, read relative to the file's own directory
  proc = subprocess.run(
    [ "git", "-C", str(path.parent), "show", f"{revision}:./{path.name}" ],
    stdin = subprocess.DEVNULL, capture_output = True, text = True, encoding = _ENCODING, check = False,
  )

  # guard: no committed copy, so the section had no rung then
  if proc.returncode != 0:
    return set()
  return _parse_ladder_keys(proc.stdout, f"{path.name}@{revision}")


def _parse_ladder_keys(source: str, label: str) -> set[int]:
  """
  Read the integer keys of a section file's module-level `MIGRATIONS` dict from its source text.

  Args:
    source: The section file's source text.
    label: The name the error messages give the file.

  Returns:
    The ladder keys.

  Raises:
    ValueError: When the source does not parse, assigns no `MIGRATIONS` dict literal at module level, or the
      dict holds a key that is not an integer literal.
  """
  # the source is parsed, never run
  try:
    tree = ast.parse(source)
  except SyntaxError as error:
    raise ValueError(f"{label}: does not parse: {error}") from error

  # the last module-level assignment of the ladder name wins, as it would at import
  ladder: ast.expr | None = None
  for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == _LADDER_NAME for t in node.targets):
      ladder = node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == _LADDER_NAME:
      ladder = node.value

  # guard: the ladder must be a dict literal
  if not isinstance(ladder, ast.Dict):
    raise ValueError(f"{label}: no {_LADDER_NAME} dict literal")

  # every key is an integer literal; a bool is not a version
  keys: set[int] = set()
  for key in ladder.keys:
    # guard: a `**` unpacking or a non-integer key leaves the ladder unreadable
    if not isinstance(key, ast.Constant) or not isinstance(key.value, int) or isinstance(key.value, bool):
      raise ValueError(f"{label}: {_LADDER_NAME} key is not an integer literal")
    keys.add(key.value)
  return keys


def _read_unreleased_at_head(path: Path) -> bool:
  """
  Read the HEAD commit's copy of a step file through git and tell whether it holds the step unreleased.

  Args:
    path: The step file in the working tree.

  Returns:
    True when HEAD's copy of the file has an empty `since`, or HEAD holds no copy of it.

  Raises:
    OSError: When git cannot be started.
  """
  # the committed copy, read relative to the file's own directory
  proc = subprocess.run(
    [ "git", "-C", str(path.parent), "show", f"{_HEAD}:./{path.name}" ],
    stdin = subprocess.DEVNULL, capture_output = True, text = True, encoding = _ENCODING, check = False,
  )

  # guard: no committed copy, so the step was never released
  if proc.returncode != 0:
    return True
  return parse_frontmatter(proc.stdout).get(MigrationKey.SINCE) in ( None, "" )


def _run_step_check(path: Path, plugin: str, *, repo: Path) -> int:
  """
  Check one step file and print the verdict.

  Args:
    path: The step file.
    plugin: The plugin the step belongs to.
    repo: The repository whose spec settings name the catalog root.

  Returns:
    0 with the parsed step printed, 1 with the refusal printed.
  """
  # the format first, then the write territory
  try:
    step = migration_steps.parse_step(path, plugin)
    outside = migration_steps.check_writes(step, repo)
  except (OSError, ValueError) as error:
    return _refuse(f"{path.name}: {error}")

  # guard: a step may never write the consumer's own code
  if outside:
    return _refuse(f"{path.name}: writes outside territory: {', '.join(outside)}")

  # the accepted step's fields as the file states them
  fields = {
    _ReportProp.PLUGIN: step.plugin, _ReportProp.PATH: str(step.path), _ReportProp.NUMBER: step.number,
    _ReportProp.SLUG: step.slug, MigrationKey.SINCE: step.since, MigrationKey.SUPERSEDES: list(step.supersedes),
    MigrationKey.APPLIES_WHEN: list(step.applies_when), MigrationKey.WRITES: list(step.writes),
  }
  print(json.dumps({ _ReportProp.STATUS: _StatusKind.OK, _ReportProp.STEP: fields }))
  return 0


def _load_release_steps(root: Path) -> list[migration_steps.Step]:
  """
  Parse every step file of a plugin root for a release.

  Args:
    root: The plugin root.

  Returns:
    The parsed steps in file-name order; empty when the plugin ships no migrations.

  Raises:
    ValueError: When a step file breaks the step format; the message names the file.
    OSError: When a step file cannot be read.
  """
  directory = root / MigrationFile.DIR

  # guard: the plugin ships no migrations
  if not directory.is_dir():
    return []

  # every markdown file is a step and must parse
  steps = []
  for name in sorted(os.listdir(directory)):
    # guard: only markdown files are steps
    if not name.endswith(_MD_SUFFIX):
      continue
    try:
      steps.append(migration_steps.parse_step(directory / name, root.name))
    except ValueError as error:
      raise ValueError(f"{name}: {error}") from error

  # the steps in file-name order
  return steps


def _with_since(text: str, version: str) -> str:
  """
  Set the `since` line of a step file's frontmatter, leaving every other byte as it is.

  Args:
    text: The step file's text, line endings untranslated.
    version: The release version.

  Returns:
    The text with its `since` line set; a frontmatter without one gains it right after the opening fence.

  Raises:
    ValueError: When the text opens with no closed frontmatter.
  """
  lines = text.splitlines(keepends = True)

  # guard: a step file opens with its frontmatter fence
  if not lines or lines[0].rstrip(_EOL) != _FENCE:
    raise ValueError("no frontmatter")

  # the frontmatter runs to the next fence; its `since` line is rewritten keeping its own line ending
  for index, line in enumerate(lines[1:], start = 1):
    content = line.rstrip(_EOL)
    if content == _FENCE:
      break
    if content.startswith(f"{MigrationKey.SINCE}:"):
      lines[index] = f"{MigrationKey.SINCE}: {version}{line[len(content):]}"
      return "".join(lines)
  else:
    raise ValueError("unclosed frontmatter")

  # no `since` line: one is added after the opening fence, with the fence's line ending
  lines.insert(1, f"{MigrationKey.SINCE}: {version}{lines[0][len(_FENCE):]}")
  return "".join(lines)


def _read_manifest_version(root: Path) -> str | None:
  """
  Read the version a plugin root's manifest records.

  Args:
    root: The plugin root.

  Returns:
    The version string, or None when the manifest is missing, unreadable, or names no string version.
  """
  # an unreadable manifest is no version, never a failed plan
  try:
    data = json.loads((root / _MANIFEST).read_text(encoding = _ENCODING))
  except (OSError, ValueError):
    return None

  # only a string version counts
  version = data.get(_MANIFEST_VERSION) if isinstance(data, dict) else None
  return version if isinstance(version, str) else None


def _refuse(reason: str) -> int:
  """
  Print a refusal document.

  Args:
    reason: Why the call was refused.

  Returns:
    The refusal exit code, 1.
  """
  # the refusal is one JSON line, never a traceback
  print(json.dumps({ _ReportProp.STATUS: _StatusKind.ERROR, _ReportProp.REASON: reason }))
  return 1
