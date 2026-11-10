from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
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
# pylint: disable-next=import-error,wrong-import-position
from constants import (  # noqa: E402
  MigrationFile, MigrationKey, MigrationTerritory, SettingsFile, SettingsKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from frontmatter_parser import parse_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from guard_checks import compile_scope_glob  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from lazy_settings import load_section  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The step-file name grammar: a three-digit number and a kebab-case slug.
_NAME_RE = re.compile(r"^(\d{3})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md\Z")
# The three body sections of a step, in their fixed order.
_SECTIONS = ( "## Why", "## Steps", "## Done when" )
# The closed frontmatter vocabulary of a step file.
_KEYS = ( MigrationKey.SINCE, MigrationKey.SUPERSEDES, MigrationKey.APPLIES_WHEN, MigrationKey.WRITES )
# The settings section owned by lazycortex-specs that names the catalog root.
_SPEC_SECTION = "spec"
# The key of the spec section that holds the catalog root.
_VAULT_ROOT = "vault_root"
# The catalog root when the settings name none.
_DEFAULT_SPEC_ROOT = "specs"
# The setting a refused catalog root is reported under.
_VAULT_ROOT_SETTING = "spec.vault_root"
# Path segments that make a catalog root reach outside a plain repo-relative directory.
_UNSAFE_SEGMENTS = ( "", ".", ".." )
# The placeholder a step glob carries for the spec catalog root.
_SPEC_ROOT_TOKEN = "{spec_root}"
# The CLI-name prefix every lazycortex plugin's bin script carries.
_PLUGIN_PREFIX = "lazycortex-"
# The directory no repo walk enters.
_GIT_DIR = ".git"
# Glob metacharacters that end the literal leading part of a pattern.
_WILDCARDS = "*?["
# The suffix of a step-file candidate.
_MD_SUFFIX = ".md"
# The suffix of the temp file a stamp is written through.
_TMP_SUFFIX = ".tmp"
# The directory of a plugin root that holds its CLI.
_BIN_DIR = "bin"
# The codec error handler that keeps undecodable consumer bytes readable.
_DECODE_ERRORS = "replace"
# The exit code of a verb that could not judge the condition at all.
_VERB_ERROR_EXIT = 2
# The seconds a plugin verb may run before it counts as broken.
_VERB_TIMEOUT_S = 120


# ----------------------------------------------------------------------------------------
class _PredicateKind(StrEnum):
  """
  Names and argument keys of the `applies_when` predicate vocabulary, as a step file writes them.
  """

  # A glob matches at least one path, optionally minus an `except` list.
  PATH_EXISTS = "path_exists"
  # A glob matches no path.
  PATH_MISSING = "path_missing"
  # A dotted key is present in the merged settings.
  SETTINGS_KEY_PRESENT = "settings_key_present"
  # A dotted key is absent from the merged settings.
  SETTINGS_KEY_ABSENT = "settings_key_absent"
  # At least one document under a glob carries a frontmatter key.
  FRONTMATTER_KEY = "frontmatter_key"
  # At least one file under a glob matches a regular expression.
  FILE_CONTAINS = "file_contains"
  # A plugin verb exits 0.
  VERB = "verb"
  # The globs a `path_exists` match must avoid.
  EXCEPT = "except"
  # The glob argument of a mapping-valued predicate.
  GLOB = "glob"
  # The frontmatter-key argument of `frontmatter_key`.
  KEY = "key"
  # The regular-expression argument of `file_contains`.
  PATTERN = "pattern"


# ----------------------------------------------------------------------------------------
class _ReasonKind(StrEnum):
  """
  Why a predicate held or failed, and why the plan skipped a step.
  """

  # Every condition held.
  OK = "ok"
  # A condition did not hold.
  NO_MATCH = "no-match"
  # A `verb` predicate's plugin or its CLI is not on this machine.
  PLUGIN_MISSING = "plugin-missing"
  # The plugin's stamp already reaches the step's release.
  STAMPED = "stamped"
  # A sibling step supersedes the step.
  SUPERSEDED = "superseded"
  # A condition of the step did not hold.
  NOT_APPLICABLE = "not-applicable"
  # The step works on the spec catalog, and the repository grants the catalog no territory.
  NO_SPEC_TERRITORY = "no-spec-territory"


# ----------------------------------------------------------------------------------------
class _ReportProp(StrEnum):
  """
  Keys of the plan report and of the stamp payload.
  """

  # The per-plugin reports of a plan.
  PLUGINS = "plugins"
  # The steps still to apply, in number order.
  APPLICABLE = "applicable"
  # The steps left out, with their reason.
  SKIPPED = "skipped"
  # The files that could not be planned, with their reason.
  INVALID = "invalid"
  # The plugin's stamped version.
  STAMP = "stamp"
  # A step or stamp file path.
  PATH = "path"
  # Why an entry was skipped or is invalid.
  REASON = "reason"
  # The failing predicate's reason under a not-applicable skip.
  DETAIL = "detail"
  # A step's number.
  NUMBER = "number"
  # A step's slug.
  SLUG = "slug"
  # A step's release version.
  SINCE = "since"
  # A step's write globs, spec root expanded.
  WRITES = "writes"
  # The stamped version in a stamp payload.
  VERSION = "version"
  # The UTC time a stamp was written.
  STAMPED_AT = "stamped_at"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class Step:
  """
  One parsed migration step file of a plugin.

  Attributes:
    plugin: The plugin the step belongs to.
    number: The step's ordinal within the plugin, from its file name.
    slug: The step's kebab-case name, from its file name.
    path: The step file.
    since: The plugin version the step was released in, or None while unreleased.
    supersedes: Numbers of the earlier steps this step cancels.
    applies_when: The predicate mappings that must all hold for the step to apply.
    writes: The repo-relative globs the step may write, as written in the file.
  """

  # The plugin the step belongs to.
  plugin: str
  # The step's ordinal within the plugin, from its file name; it orders the plugin's steps.
  number: int
  # The step's kebab-case name, from its file name.
  slug: str
  # The step file.
  path: Path
  # The plugin version the step was released in, or None while unreleased.
  since: str | None
  # Numbers of the earlier steps this step cancels.
  supersedes: tuple[int, ...]
  # The predicate mappings that must all hold for the step to apply.
  applies_when: tuple[dict, ...]
  # The repo-relative globs the step may write, as written in the file.
  writes: tuple[str, ...]


# waiver: public name fixed by the migration interface the CLI verbs consume; the docstring states it builds a key
def version_key(version: str) -> tuple[int, ...]:
  """
  Build the sort key of a dotted plugin version, so versions compare numerically.

  Guarantees:
    - Versions that differ only by trailing zero segments (`10.0` and `10.0.0`) get equal keys, and the
      key order is the order of the versions with the shorter one padded by zeros.

  Args:
    version: A dotted version such as `10.0.0`; a segment's leading digits count, any suffix is ignored.

  Returns:
    One integer per dotted segment, trailing zero segments dropped.

  Raises:
    ValueError: When a segment carries no leading digits.
  """

  # Contract:
  # Two versions that differ only by trailing zero segments MUST get equal keys, and comparing keys MUST
  # match comparing the versions with the shorter one padded by zeros; the stamp check relies on it.

  # each segment contributes its leading digits
  key = []
  for segment in str(version).split("."):
    digits = re.match(r"\d+", segment)

    # guard: a segment without digits is not a version
    if digits is None:
      raise ValueError(f"not a version: {version!r}")
    key.append(int(digits.group()))

  # trailing zeros are dropped, which is what zero-padding the shorter version amounts to
  while key and key[-1] == 0:
    key.pop()
  return tuple(key)


def parse_step(path: Path, plugin: str) -> Step:
  """
  Read one migration step file and check it against the step format.

  Guarantees:
    - A file outside the step format — its name, an unknown, missing or empty frontmatter key, an unknown
      or malformed predicate, or the body sections — raises instead of yielding a partial step.

  Args:
    path: The step file, named `<NNN>-<slug>.md`.
    plugin: The plugin the step belongs to.

  Returns:
    The parsed step.

  Raises:
    ValueError: When the file breaks the step format; the message names the reason.
    OSError: When the file cannot be read.
  """

  # Contract:
  # A step file that breaks the format in any way MUST raise; a partially parsed step never reaches a
  # caller, because the plan and the stamp both trust every field of a returned step.

  # the file name carries the ordinal and the slug
  name = _NAME_RE.match(path.name)

  # guard: the file name is not `<NNN>-<slug>.md`
  if name is None:
    raise ValueError(f"file name {path.name!r} is not <NNN>-<slug>.md")

  # the frontmatter is read as a flat mapping, the body checked for its sections
  text = path.read_text(encoding = "utf-8")
  meta = parse_frontmatter(text)
  _validate_sections(text)
  unknown = sorted(set(meta) - set(_KEYS))

  # guard: a key outside the vocabulary
  if unknown:
    raise ValueError(f"unknown key: {', '.join(unknown)}")

  # every required key must carry a value
  for required in ( MigrationKey.APPLIES_WHEN, MigrationKey.WRITES ):
    # guard: a required key is missing
    if meta.get(required) in ( None, "" ):
      raise ValueError(f"missing {required}")
  predicates = tuple(_parse_predicate(item) for item in _parse_sequence(meta[MigrationKey.APPLIES_WHEN],
                                                                          MigrationKey.APPLIES_WHEN))

  # guard: a step with no condition would apply forever
  if not predicates:
    raise ValueError(f"{MigrationKey.APPLIES_WHEN} must name at least one condition")

  # every field normalised to its declared shape
  return Step(
    plugin = plugin, number = int(name.group(1)), slug = name.group(2), path = path,
    since = _normalize_since(meta.get(MigrationKey.SINCE)),
    supersedes = _normalize_supersedes(meta.get(MigrationKey.SUPERSEDES)),
    applies_when = predicates,
    writes = tuple(_require_text(item, MigrationKey.WRITES)
                   for item in _parse_sequence(meta[MigrationKey.WRITES], MigrationKey.WRITES)),
  )


# waiver: public name fixed by the migration interface the CLI verbs consume; the docstring states it lists globs
def check_writes(step: Step, repo: Path) -> list[str]:
  """
  Find every write glob of the step that reaches outside the plugins' territory in a consumer repository.

  Args:
    step: A parsed step.
    repo: The consumer repository root, whose spec settings name the catalog root.

  Returns:
    The offending globs as the step file writes them; empty when every glob stays inside. A glob naming
    `{spec_root}` is offending while the catalog root grants no territory.
  """
  spec_root = _read_spec_root(repo)
  return [ glob for glob in step.writes
           if (spec_root is None and _SPEC_ROOT_TOKEN in glob)
           or not _is_in_territory(_expand(glob, spec_root), spec_root) ]


def evaluate(predicate: dict, repo: Path, home: Path) -> tuple[bool, str]:
  """
  Judge one applicability predicate against a consumer repository.

  Args:
    predicate: One predicate mapping from a step's `applies_when`.
    repo: The consumer repository root.
    home: The home directory whose plugin registry resolves a `verb` predicate's plugin.

  Returns:
    Whether the predicate holds, and why: `ok`, `no-match`, or `plugin-missing` when a `verb`
    predicate's plugin or its CLI cannot be found.

  Raises:
    ValueError: When the predicate cannot be judged — it is malformed, the settings file is not valid
      JSON, a file under its glob cannot be read, or a `verb` predicate's CLI cannot be started or exits 2.
  """
  _validate_predicate(predicate)

  # the verb predicate is the one that can miss its plugin altogether
  if _PredicateKind.VERB in predicate:
    return _run_verb(predicate[_PredicateKind.VERB], repo, home)

  # every other predicate is a plain yes or no
  return ( True, _ReasonKind.OK ) if _is_held(predicate, repo, _read_spec_root(repo)) else (
    False, _ReasonKind.NO_MATCH)


def plan(repo: Path, home: Path, plugins: dict[str, Path], *, only: set[str] | None = None) -> dict:
  """
  Build the migration plan of a consumer repository: per plugin, the steps still to apply.

  Guarantees:
    - A step file or stamp that cannot be read, and a step whose predicate cannot be judged, never
      raise; each is reported under `invalid` and the rest of the plugin's steps are still planned.
    - A step file a valid step supersedes is skipped as `superseded`, never `invalid`, even when it cannot
      be parsed.
    - A step that names `{spec_root}` while the catalog root grants no territory is skipped as
      `not-applicable` with detail `no-spec-territory`, never `invalid`.
    - `applicable` is ordered by step number.

  Args:
    repo: The consumer repository root.
    home: The home directory whose plugin registry resolves `verb` predicates.
    plugins: Plugin name to plugin root, the roots whose `migrations/` are read.
    only: When given, the plugin names to plan; every other plugin is left out.

  Returns:
    `{"plugins": {name: {"applicable", "skipped", "invalid", "stamp"}}}` — applicable step mappings
    (`path`, `number`, `slug`, `since`, `writes` with the spec root expanded), skipped `{path, reason}`
    entries (a `not-applicable` one also carries `detail`), invalid `{path, reason}` entries, and the plugin's
    stamped version or None.

  Raises:
    ValueError: When the consumer's settings file is not valid JSON.
  """

  # Contract:
  # A broken step file, a broken stamp, or a predicate that cannot be judged MUST NOT raise; each is
  # reported under `invalid` and planning continues, so one bad file never hides another plugin's steps.

  # Contract:
  # A superseded step file, parseable or not, and a `{spec_root}` step in a repository whose catalog grants no
  # territory MUST land under `skipped`, never `invalid`; the migrate skill never stamps a plugin with an
  # `invalid` entry, so either would keep the plugin unstamped forever.

  # Contract:
  # `applicable` MUST be ordered by step number; the migrate skill applies the steps in exactly that order.

  # one report per plugin in scope
  report = {}
  for name in sorted(plugins):

    # guard: the caller narrowed the plan to other plugins
    if only is not None and name not in only:
      continue
    report[name] = _plan_plugin(repo, home, name, root = plugins[name])

  # the plan wraps the per-plugin reports
  return { _ReportProp.PLUGINS: report }


def read_stamp(repo: Path, plugin: str) -> str | None:
  """
  Read the plugin's migrated-version stamp from the consumer repository.

  Args:
    repo: The consumer repository root.
    plugin: The plugin name.

  Returns:
    The stamped version, or None when the plugin has no stamp yet.

  Raises:
    ValueError: When the stamp file exists but carries no readable dotted version.
  """
  path = _locate_stamp(repo, plugin)

  # guard: no stamp yet
  if not path.is_file():
    return None

  # the payload must be an object carrying a string version
  try:
    payload = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, ValueError) as exc:
    raise ValueError(f"unreadable stamp {path.name}: {exc}") from exc
  if not isinstance(payload, dict) or not isinstance(payload.get(_ReportProp.VERSION), str):
    raise ValueError(f"stamp {path.name} carries no version")

  # a stamp that is not a dotted version could not be compared with a step's release
  version_key(payload[_ReportProp.VERSION])
  return payload[_ReportProp.VERSION]


def write_stamp(repo: Path, plugin: str, version: str) -> Path:
  """
  Record the version a plugin's migrations are complete for, replacing any earlier stamp.

  Args:
    repo: The consumer repository root.
    plugin: The plugin name.
    version: The plugin version to record.

  Returns:
    The stamp file written.

  Raises:
    ValueError: When the version is not a dotted version.
  """
  version_key(version)
  path = _locate_stamp(repo, plugin)
  path.parent.mkdir(parents = True, exist_ok = True)

  # a whole-file rewrite through a sibling temp file, so a reader never sees half a stamp
  payload = {
    _ReportProp.VERSION: version,
    _ReportProp.STAMPED_AT: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
  }
  tmp = path.with_name(path.name + _TMP_SUFFIX)
  tmp.write_text(json.dumps(payload, indent = 2) + "\n", encoding = "utf-8")
  os.replace(tmp, path)
  return path


def _plan_plugin(repo: Path, home: Path, plugin: str, *, root: Path) -> dict:
  """
  Plan one plugin's steps.

  Args:
    repo: The consumer repository root.
    home: The home directory for `verb` predicates.
    plugin: The plugin name.
    root: The plugin root.

  Returns:
    The plugin's `applicable` / `skipped` / `invalid` / `stamp` report.
  """
  applicable: list[dict] = []
  skipped: list[dict] = []
  invalid: list[dict] = []
  spec_root = _read_spec_root(repo)

  # a broken stamp is reported and treated as no stamp, so every released step is judged again
  try:
    stamp = read_stamp(repo, plugin)
  except ValueError as exc:
    stamp = None
    invalid.append({ _ReportProp.PATH: str(repo / MigrationFile.STAMP.format(plugin = plugin)),
                     _ReportProp.REASON: str(exc) })

  # the valid steps, and every number any of them supersedes
  steps, rejected = _load_steps(root / MigrationFile.DIR, plugin, repo = repo, spec_root = spec_root)
  superseded = { number for step in steps for number in step.supersedes }

  # a step file that cannot be planned is moot once a valid step supersedes its number
  for number, rejection in rejected:
    if number is not None and number in superseded:
      skipped.append({ _ReportProp.PATH: rejection[_ReportProp.PATH], _ReportProp.REASON: _ReasonKind.SUPERSEDED })
    else:
      invalid.append(rejection)

  # Domain(install.reconciliation):
  # # A migration step is judged only while the consumer may still need it
  # A released step the consumer's recorded migrated version already reaches is not considered again;
  # an unreleased step is always considered. A step a sibling step names as superseded is dropped, since
  # the superseding step covers the state both before and after it, and so is a superseded step file that
  # cannot even be read. A step that works on the spec catalog has nothing to do in a repository whose
  # catalog grants no territory. Of the rest, a step applies only when every one of its conditions holds
  # against the consumer's repository; steps are taken in their number order.

  # each step lands in exactly one bucket
  for step in steps:
    entry = str(step.path)

    # a release the stamp reaches, then a superseded step, are left out before any condition runs
    if step.since is not None and stamp is not None and version_key(step.since) <= version_key(stamp):
      skipped.append({ _ReportProp.PATH: entry, _ReportProp.REASON: _ReasonKind.STAMPED })
      continue
    if step.number in superseded:
      skipped.append({ _ReportProp.PATH: entry, _ReportProp.REASON: _ReasonKind.SUPERSEDED })
      continue

    # guard: a step on the spec catalog has nothing to do while the catalog grants no territory
    if spec_root is None and _names_spec_root(step):
      skipped.append({ _ReportProp.PATH: entry, _ReportProp.REASON: _ReasonKind.NOT_APPLICABLE,
                       _ReportProp.DETAIL: _ReasonKind.NO_SPEC_TERRITORY })
      continue

    # a predicate that cannot be judged makes the step invalid rather than silently inapplicable
    try:
      verdict = _evaluate_all(step, repo, home)
    except ValueError as exc:
      invalid.append({ _ReportProp.PATH: entry, _ReportProp.REASON: str(exc) })
      continue
    if verdict != _ReasonKind.OK:
      skipped.append({ _ReportProp.PATH: entry, _ReportProp.REASON: _ReasonKind.NOT_APPLICABLE,
                       _ReportProp.DETAIL: verdict })
      continue

    # an applicable step carries what the migrate skill needs to run and commit it
    applicable.append({
      _ReportProp.PATH: entry, _ReportProp.NUMBER: step.number, _ReportProp.SLUG: step.slug,
      _ReportProp.SINCE: step.since, _ReportProp.WRITES: [ _expand(glob, spec_root) for glob in step.writes ],
    })

  # the plugin's report, applicable steps already in number order
  return {
    _ReportProp.APPLICABLE: applicable, _ReportProp.SKIPPED: skipped, _ReportProp.INVALID: invalid,
    _ReportProp.STAMP: stamp,
  }


def _load_steps(directory: Path,
                plugin: str,
                *,
                repo: Path,
                spec_root: str | None) -> tuple[list[Step], list[tuple[int | None, dict]]]:
  """
  Parse every step file of a plugin, setting aside each that cannot be planned.

  Args:
    directory: The plugin's migrations directory.
    plugin: The plugin name.
    repo: The consumer repository root, for the territory check.
    spec_root: The repo-relative spec catalog root, or None when it grants no territory.

  Returns:
    The valid steps in number order, and the rejected step files: each with the step number its file name
    carries (None when the name is not `<NNN>-<slug>.md`) and its `{path, reason}` entry. A file that does not
    parse, a step whose number another file shares, and a step whose writes leave the territory are rejected;
    a `{spec_root}` glob counts against no step while the catalog grants no territory, since such a step is
    skipped rather than rejected.
  """

  # guard: the plugin ships no migrations
  if not directory.is_dir():
    return [], []

  # every markdown file is a step candidate
  parsed: list[Step] = []
  rejected: list[tuple[int | None, dict]] = []
  for name in sorted(os.listdir(directory)):

    # guard: only markdown files are step candidates
    if not name.endswith(_MD_SUFFIX):
      continue
    try:
      step = parse_step(directory / name, plugin)
    except (OSError, ValueError) as exc:
      number = _NAME_RE.match(name)
      rejected.append(( int(number.group(1)) if number else None,
                        { _ReportProp.PATH: str(directory / name), _ReportProp.REASON: str(exc) } ))
      continue
    outside = [ glob for glob in check_writes(step, repo) if spec_root is not None or _SPEC_ROOT_TOKEN not in glob ]

    # guard: a step may never write the consumer's own code
    if outside:
      rejected.append(( step.number, { _ReportProp.PATH: str(step.path),
                                       _ReportProp.REASON: f"writes outside territory: {', '.join(outside)}" } ))
      continue
    parsed.append(step)

  # two files on one number leave the order undefined, so neither is planned
  numbers = [ step.number for step in parsed ]
  valid = []
  for step in sorted(parsed, key = lambda item: item.number):
    if numbers.count(step.number) > 1:
      rejected.append(( step.number, { _ReportProp.PATH: str(step.path),
                                       _ReportProp.REASON: f"duplicate step number {step.number:03d}" } ))
    else:
      valid.append(step)
  return valid, rejected


def _evaluate_all(step: Step, repo: Path, home: Path) -> str:
  """
  Judge every predicate of a step, stopping at the first that fails.

  Args:
    step: The step.
    repo: The consumer repository root.
    home: The home directory for `verb` predicates.

  Returns:
    `ok` when all predicates hold, else the failing predicate's reason.
  """
  for predicate in step.applies_when:
    held, reason = evaluate(predicate, repo, home)

    # the first failing predicate decides the step
    if not held:
      return reason

  # no predicate failed
  return _ReasonKind.OK


def _is_held(predicate: dict, repo: Path, spec_root: str | None) -> bool:
  """
  Tell whether a predicate that resolves to a plain yes or no holds.

  Args:
    predicate: A validated predicate mapping other than `verb`.
    repo: The consumer repository root.
    spec_root: The repo-relative spec catalog root, or None when it grants no territory.

  Returns:
    Whether the predicate holds.

  Raises:
    ValueError: When a file under the predicate's glob cannot be read, or a glob names `{spec_root}` while
      the catalog root grants no territory.
  """
  # path predicates match files and directories
  if _PredicateKind.PATH_EXISTS in predicate:
    excluded = [ compile_scope_glob(_expand(glob, spec_root)) for glob in predicate.get(_PredicateKind.EXCEPT, []) ]
    hits = _find_all_matches(repo, _expand(predicate[_PredicateKind.PATH_EXISTS], spec_root))
    return any(not any(rx.match(hit) for rx in excluded) for hit in hits)
  if _PredicateKind.PATH_MISSING in predicate:
    return not _find_all_matches(repo, _expand(predicate[_PredicateKind.PATH_MISSING], spec_root))

  # settings predicates read the merged settings
  if _PredicateKind.SETTINGS_KEY_PRESENT in predicate:
    return _has_settings_key(repo, predicate[_PredicateKind.SETTINGS_KEY_PRESENT])
  if _PredicateKind.SETTINGS_KEY_ABSENT in predicate:
    return not _has_settings_key(repo, predicate[_PredicateKind.SETTINGS_KEY_ABSENT])

  # content predicates read every file under a glob
  spec = next(iter(predicate.values()))
  texts = [ _read_text(repo / rel) for rel in _find_all_matches(repo, _expand(spec[_PredicateKind.GLOB], spec_root))
            if (repo / rel).is_file() ]
  if _PredicateKind.FRONTMATTER_KEY in predicate:
    return any(spec[_PredicateKind.KEY] in parse_frontmatter(text) for text in texts)

  # the pattern predicate searches each file's whole text, line anchors per line
  pattern = re.compile(spec[_PredicateKind.PATTERN], re.MULTILINE)
  return any(pattern.search(text) for text in texts)


def _run_verb(argv: list[str], repo: Path, home: Path) -> tuple[bool, str]:
  """
  Run a plugin verb in the consumer repository and judge its exit code.

  Args:
    argv: The plugin name, the verb, and its arguments.
    repo: The consumer repository root, the verb's working directory.
    home: The home directory whose plugin registry resolves the plugin.

  Returns:
    `(True, "ok")` on exit 0, `(False, "no-match")` on exit 1, on exit 3 (nothing the verb can do in this
    repository), or on any other code than 2, `(False, "plugin-missing")` when the plugin or its CLI cannot be
    found.

  Raises:
    ValueError: When the CLI cannot be started, runs past its time limit, or exits 2, the verb's own report that
      it could not judge.
  """
  plugin, verb, *args = argv
  resolved = lazy_setup.plugin_root(plugin, repo, home)

  # guard: the plugin is not on this machine
  if resolved is None:
    return False, _ReasonKind.PLUGIN_MISSING
  short = plugin.split("@", 1)[0].removeprefix(_PLUGIN_PREFIX)
  cli = Path(resolved["root"]) / _BIN_DIR / f"{_PLUGIN_PREFIX}{short}"

  # guard: the plugin ships no CLI
  if not cli.is_file():
    return False, _ReasonKind.PLUGIN_MISSING

  # the CLI runs under this interpreter, never through its exec bit, and a hung verb is a broken one
  try:
    proc = subprocess.run(
      [ sys.executable, str(cli), verb, *args ], cwd = str(repo), stdin = subprocess.DEVNULL,
      capture_output = True, text = True, check = False, timeout = _VERB_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as exc:
    raise ValueError(f"{plugin} {verb} timed out after {_VERB_TIMEOUT_S}s") from exc
  except OSError as exc:
    raise ValueError(f"cannot run {plugin} {verb}: {exc}") from exc

  # exit 2 is the verb's own failure, never an answer about the condition
  if proc.returncode == _VERB_ERROR_EXIT:
    raise ValueError(f"{plugin} {verb} failed with exit {_VERB_ERROR_EXIT}: {proc.stderr.strip()}")

  # only exit 0 holds; exit 1, exit 3 (the verb's precondition is absent here) and
  # any other code leave the condition unmet
  return ( True, _ReasonKind.OK ) if proc.returncode == 0 else ( False, _ReasonKind.NO_MATCH )


def _has_settings_key(repo: Path, dotted: str) -> bool:
  """
  Tell whether a dotted key is present in the consumer's merged settings.

  Args:
    repo: The consumer repository root.
    dotted: `<section>.<key>...`; a bare section name asks whether the section carries any key.

  Returns:
    Whether the key is present.
  """
  section, *rest = dotted.split(".")
  node = load_section(repo / SettingsFile.REL, section)

  # a bare section counts when it carries more than its version stamp
  if not rest:
    return any(key != SettingsKey.VERSION for key in node)

  # each further segment descends one mapping
  current: object = node
  for segment in rest:
    if not isinstance(current, dict) or segment not in current:
      return False
    current = current[segment]
  return True


def _find_all_matches(repo: Path, glob: str) -> list[str]:
  """
  Find every repo-relative file and directory a glob matches.

  Args:
    repo: The repository root.
    glob: A repo-relative glob; `**` spans any depth, including none.

  Returns:
    The matching POSIX paths, sorted; `.git` is never entered.
  """
  # a literal path is answered without a walk
  if not any(char in glob for char in _WILDCARDS):
    return [ glob ] if (repo / glob).exists() else []

  # the walk starts at the literal leading directories of the pattern
  head = []
  for segment in glob.split("/")[:-1]:
    if any(char in segment for char in _WILDCARDS):
      break
    head.append(segment)
  regex = compile_scope_glob(glob)

  # every file and directory under the walk root is tested against the whole pattern
  hits = []
  for current, dirs, files in os.walk(repo.joinpath(*head)):
    dirs[:] = [ name for name in dirs if name != _GIT_DIR ]
    rel_dir = Path(current).relative_to(repo).as_posix()
    for name in dirs + files:
      rel = name if rel_dir == "." else f"{rel_dir}/{name}"
      if regex.match(rel):
        hits.append(rel)

  # a stable order, whatever the filesystem's listing order
  return sorted(hits)


def _read_spec_root(repo: Path) -> str | None:
  """
  Read the consumer's repo-relative spec catalog root from its settings.

  Args:
    repo: The consumer repository root.

  Returns:
    The `spec.vault_root` setting without its trailing slash, `specs` when unset or empty, or None when the
    setting is not a plain repo-relative directory — the repo root, absolute, climbing through `..`, or
    carrying a glob metacharacter or whitespace.
  """
  section = load_section(repo / SettingsFile.REL, _SPEC_SECTION)

  # guard: an unset or empty root takes the default, as the specs plugin reads it
  if section.get(_VAULT_ROOT) in ( None, "" ):
    return _DEFAULT_SPEC_ROOT
  value = section[_VAULT_ROOT]

  # Domain(install.reconciliation):
  # # A catalog root that is not a plain subdirectory grants no territory
  # The spec catalog belongs to the plugins' territory only when its configured root is a plain directory
  # inside the repository; an unset or empty root means the default catalog directory. A root that is the
  # repository itself, absolute, that climbs out through a parent reference, or whose name carries a wildcard,
  # a character class, or whitespace would hand the consumer's own code to migration steps, so it contributes
  # no territory at all, and a step that works on the catalog has nothing to do there. A trailing slash is
  # ignored.

  # guard: anything but a plain relative directory fails closed
  if not isinstance(value, str) or value.startswith("/") or any(
      _is_unsafe_segment(segment) for segment in value.rstrip("/").split("/")):
    return None
  return value.rstrip("/")


def _is_unsafe_segment(segment: str) -> bool:
  """
  Tell whether one path segment of a catalog root keeps it from being a plain directory name.

  Args:
    segment: One `/`-separated segment of the configured root.

  Returns:
    Whether the segment is empty, `.` or `..`, or carries a glob metacharacter or whitespace.
  """
  return (segment in _UNSAFE_SEGMENTS or any(char in _WILDCARDS for char in segment)
          or any(char.isspace() for char in segment))


def _expand(glob: str, spec_root: str | None) -> str:
  """
  Substitute the spec catalog root into a step glob.

  Args:
    glob: A glob that may carry the `{spec_root}` placeholder.
    spec_root: The repo-relative catalog root, or None when it grants no territory.

  Returns:
    The glob with every placeholder replaced.

  Raises:
    ValueError: When the glob names the placeholder and the catalog root grants no territory.
  """
  # guard: nothing to substitute
  if _SPEC_ROOT_TOKEN not in glob:
    return glob

  # guard: a refused catalog root never stands in for the placeholder
  if spec_root is None:
    raise ValueError(f"{glob!r} uses {_SPEC_ROOT_TOKEN} while {_VAULT_ROOT_SETTING} is not a plain "
                     f"repo-relative directory")
  return glob.replace(_SPEC_ROOT_TOKEN, spec_root)


def _names_spec_root(step: Step) -> bool:
  """
  Tell whether any glob of a step, written or matched, names the `{spec_root}` placeholder.

  Args:
    step: A parsed step.

  Returns:
    Whether the placeholder appears in its write globs or in a glob its predicates match.
  """
  # the glob-valued arguments of every predicate, alongside the write globs
  globs = list(step.writes)
  for predicate in step.applies_when:
    globs += [ value for key, value in predicate.items()
               if key in ( _PredicateKind.PATH_EXISTS, _PredicateKind.PATH_MISSING ) ]
    globs += predicate.get(_PredicateKind.EXCEPT, [])
    globs += [ value[_PredicateKind.GLOB] for value in predicate.values() if isinstance(value, dict) ]
  return any(_SPEC_ROOT_TOKEN in glob for glob in globs)


def _is_in_territory(glob: str, spec_root: str | None) -> bool:
  """
  Tell whether an expanded write glob stays inside the plugins' territory.

  Args:
    glob: An expanded repo-relative glob.
    spec_root: The repo-relative catalog root, a territory directory of its own, or None when it grants
      no territory.

  Returns:
    Whether the glob stays inside.
  """

  # Domain(install.reconciliation):
  # # A migration step writes only what the plugins own in a consumer repository
  # A step may touch the Claude configuration tree, the generated domain-document tree, the tracked state
  # corner, the project's Python tool configuration file, and the spec catalog. Anything else, the
  # consumer's own code above all, is outside; so is any path that is absolute or climbs out through a
  # parent reference.

  # guard: an absolute path or a parent reference escapes every prefix
  if glob.startswith("/") or ".." in glob.split("/"):
    return False

  # an entry ending in `/` is a directory prefix, any other entry an exact file
  catalog = () if spec_root is None else ( f"{spec_root}/", )
  return any(glob.startswith(entry) if entry.endswith("/") else glob == entry
             for entry in ( *MigrationTerritory.PREFIXES, *catalog ))


def _locate_stamp(repo: Path, plugin: str) -> Path:
  """
  Build the path of a plugin's stamp file in the consumer repository.

  Args:
    repo: The consumer repository root.
    plugin: The plugin name.

  Returns:
    The stamp path.

  Raises:
    ValueError: When the plugin name is empty or carries a path separator.
  """
  # guard: the name becomes a file name
  if not plugin or "/" in plugin or "\\" in plugin:
    raise ValueError(f"bad plugin name: {plugin!r}")
  return repo / MigrationFile.STAMP.format(plugin = plugin)


def _read_text(path: Path) -> str:
  """
  Read a consumer file as text, tolerating bytes that are not UTF-8.

  Args:
    path: The file.

  Returns:
    Its text, undecodable bytes replaced.

  Raises:
    ValueError: When the file cannot be read, so the predicate reading it cannot be judged.
  """
  # an unreadable file is never treated as empty: a condition would then be judged on a file nobody read
  try:
    return path.read_text(encoding = "utf-8", errors = _DECODE_ERRORS)
  except OSError as exc:
    raise ValueError(f"cannot read {path}: {exc}") from exc


def _validate_sections(text: str) -> None:
  """
  Validate that the body carries exactly the three step sections in their order.

  Args:
    text: The whole step file.

  Raises:
    ValueError: When the `##` headings outside code fences differ from the required three.
  """
  lines = text.splitlines()
  start = 0

  # the body starts after the closing frontmatter fence
  if lines and lines[0].strip() == "---":
    start = next((idx + 1 for idx in range(1, len(lines)) if lines[idx].strip() == "---"), len(lines))

  # level-two headings count only outside fenced code blocks
  headings = []
  fenced = False
  for line in lines[start:]:
    if line.lstrip().startswith("```"):
      fenced = not fenced
    elif not fenced and line.startswith("## "):
      headings.append(line.rstrip())

  # guard: the sections differ from the fixed three
  if tuple(headings) != _SECTIONS:
    raise ValueError(f"body sections must be {', '.join(_SECTIONS)} in order, found {headings or 'none'}")


def _normalize_since(value: object) -> str | None:
  """
  Normalise the `since` value to a version string.

  Args:
    value: The raw frontmatter value.

  Returns:
    The version string, or None for an empty value.

  Raises:
    ValueError: When the value is not a dotted version.
  """
  # guard: an unreleased step
  if value in ( None, "" ):
    return None

  # a bare number such as `10.1` arrives coerced and is read back as text
  text = str(value)
  version_key(text)
  return text


def _normalize_supersedes(value: object) -> tuple[int, ...]:
  """
  Normalise the `supersedes` value to step numbers.

  Args:
    value: The raw frontmatter value: absent, one number, a list, or a flow sequence.

  Returns:
    The superseded step numbers.

  Raises:
    ValueError: When an entry is not a whole number.
  """
  # guard: nothing superseded
  if value in ( None, "" ):
    return ()

  # one number or a list of them
  items = [ value ] if isinstance(value, int) else _parse_sequence(value, MigrationKey.SUPERSEDES)
  try:
    return tuple(int(str(item)) for item in items)
  except ValueError as exc:
    raise ValueError(f"supersedes entries must be step numbers: {value!r}") from exc


def _parse_sequence(value: object, key: str) -> list:
  """
  Parse a frontmatter list given either as `- item` lines or as a flow sequence.

  Args:
    value: The raw frontmatter value.
    key: The key, for the error message.

  Returns:
    The list items.

  Raises:
    ValueError: When the value is neither shape.
  """
  # block lists arrive parsed, flow sequences arrive as text
  if isinstance(value, list):
    return value
  if isinstance(value, str) and value.startswith("["):
    parsed = _Flow(value).parse_document()
    if isinstance(parsed, list):
      return parsed
  raise ValueError(f"{key} must be a list")


def _require_text(value: object, key: str) -> str:
  """
  Require a non-empty string.

  Args:
    value: The value.
    key: Where it came from, for the error message.

  Returns:
    The string.

  Raises:
    ValueError: When the value is not a non-empty string.
  """
  # guard: only a non-empty string is a glob or a name
  if not isinstance(value, str) or not value:
    raise ValueError(f"{key} entries must be non-empty strings: {value!r}")
  return value


def _parse_predicate(item: object) -> dict:
  """
  Parse one `applies_when` list item into a validated predicate mapping.

  Args:
    item: A `name: value` item, a flow mapping, or an already-parsed mapping.

  Returns:
    The predicate mapping.

  Raises:
    ValueError: When the item is not a well-formed predicate.
  """
  # a block item arrives as `name: value` text, a flow item as `{...}`
  parsed: object = item
  if isinstance(item, str):
    parsed = _Flow(item if item.startswith("{") else "{" + item + "}").parse_document()

  # guard: a predicate is always a mapping
  if not isinstance(parsed, dict):
    raise ValueError(f"predicate must be a mapping: {item!r}")
  _validate_predicate(parsed)
  return parsed


def _validate_predicate(predicate: dict) -> None:
  """
  Validate a predicate mapping against the predicate vocabulary.

  Args:
    predicate: The mapping.

  Raises:
    ValueError: When the predicate names no known predicate, several, or carries a malformed argument.
  """
  names = [ key for key in predicate if key != _PredicateKind.EXCEPT ]

  # guard: exactly one predicate per mapping
  if len(names) != 1:
    raise ValueError(f"predicate must name exactly one condition: {predicate!r}")
  name, value = names[0], predicate[names[0]]
  excluded = predicate.get(_PredicateKind.EXCEPT)

  # guard: `except` qualifies only path_exists, and lists globs
  if _PredicateKind.EXCEPT in predicate and (
      name != _PredicateKind.PATH_EXISTS or not isinstance(excluded, list)
      or not all(isinstance(glob, str) and glob for glob in excluded)):
    raise ValueError(f"except must be a list of globs under {_PredicateKind.PATH_EXISTS}: {predicate!r}")

  # string-valued predicates
  if name in ( _PredicateKind.PATH_EXISTS, _PredicateKind.PATH_MISSING, _PredicateKind.SETTINGS_KEY_PRESENT,
               _PredicateKind.SETTINGS_KEY_ABSENT ):
    _require_text(value, name)
    return

  # mapping-valued predicates
  if name in ( _PredicateKind.FRONTMATTER_KEY, _PredicateKind.FILE_CONTAINS ):
    _validate_mapping_argument(name, value)
    return

  # the verb predicate: plugin, verb, then its arguments
  if name == _PredicateKind.VERB:
    # guard: a plugin, a verb, and string arguments
    if not isinstance(value, list) or len(value) < 2 or not all(isinstance(arg, str) and arg for arg in value):
      raise ValueError(f"{_PredicateKind.VERB} takes [plugin, verb, args...]: {value!r}")
    return

  # anything else is outside the vocabulary
  raise ValueError(f"unknown predicate: {name}")


def _validate_mapping_argument(name: str, value: object) -> None:
  """
  Validate the `{glob, key}` or `{glob, pattern}` argument of a mapping-valued predicate.

  Args:
    name: The predicate name.
    value: Its argument.

  Raises:
    ValueError: When the argument has other keys, empty values, or a pattern that does not compile.
  """
  second = _PredicateKind.KEY if name == _PredicateKind.FRONTMATTER_KEY else _PredicateKind.PATTERN

  # guard: the mapping must carry exactly the glob and its second argument
  if not isinstance(value, dict) or set(value) != { _PredicateKind.GLOB, second }:
    raise ValueError(f"{name} takes {{{_PredicateKind.GLOB}, {second}}}: {value!r}")
  _require_text(value[_PredicateKind.GLOB], name)
  _require_text(value[second], name)

  # guard: only a pattern argument needs to compile
  if second != _PredicateKind.PATTERN:
    return

  # a pattern that does not compile is a format error, caught before any file is read
  try:
    re.compile(value[_PredicateKind.PATTERN])
  except re.error as exc:
    raise ValueError(f"{name} pattern does not compile: {exc}") from exc


# ----------------------------------------------------------------------------------------
class _Flow:
  """
  Reader of the YAML flow subset a step's frontmatter uses: mappings, sequences, quoted and plain scalars.

  A plain scalar runs to the next `,`, `]`, or `}` and stays a string; a value carrying one of those, or a
  `: `, is written quoted.
  """

  def __init__(self, text: str) -> None:
    """
    Bind the reader to one flow value.

    Args:
      text: The flow text.
    """
    # The flow text being read.
    self._text = text
    # The read position within the text.
    self._pos = 0

  def _skip(self) -> None:
    """
    Step over whitespace.
    """
    while self._pos < len(self._text) and self._text[self._pos].isspace():
      self._pos += 1

  def _peek(self) -> str:
    """
    Look at the next significant character.

    Returns:
      The character, or an empty string at the end.
    """
    self._skip()
    return self._text[self._pos] if self._pos < len(self._text) else ""

  def _expect(self, char: str) -> None:
    """
    Consume one required character.

    Args:
      char: The character.

    Raises:
      ValueError: When the next significant character differs.
    """
    # guard: the structure is broken
    if self._peek() != char:
      raise ValueError(f"expected {char!r} at {self._pos} in {self._text!r}")
    self._pos += 1

  def _parse_value(self) -> str | list | dict:
    """
    Parse one value at the current position.

    Returns:
      The value.
    """
    char = self._peek()
    if char == "{":
      return self._parse_mapping()
    if char == "[":
      return self._parse_sequence()
    if char in ( '"', "'" ):
      return self._parse_quoted()
    return self._parse_plain(",]}")

  def _parse_mapping(self) -> dict:
    """
    Parse a `{key: value, ...}` mapping.

    Returns:
      The mapping.

    Raises:
      ValueError: When an entry is not followed by `,` or `}`.
    """
    self._expect("{")
    result: dict = {}
    while self._peek() != "}":
      key = self._parse_quoted() if self._peek() in ( '"', "'" ) else self._parse_plain(":,}")
      self._expect(":")
      result[key] = "" if self._peek() in ( ",", "}" ) else self._parse_value()

      # entries are separated by commas
      if self._peek() == ",":
        self._pos += 1
      elif self._peek() != "}":
        raise ValueError(f"expected ',' or '}}' at {self._pos} in {self._text!r}")

    # step past the closing brace
    self._pos += 1
    return result

  def _parse_sequence(self) -> list:
    """
    Parse a `[item, ...]` sequence.

    Returns:
      The items.

    Raises:
      ValueError: When an item is not followed by `,` or `]`.
    """
    self._expect("[")
    result: list = []
    while self._peek() != "]":
      result.append(self._parse_value())

      # items are separated by commas
      if self._peek() == ",":
        self._pos += 1
      elif self._peek() != "]":
        raise ValueError(f"expected ',' or ']' at {self._pos} in {self._text!r}")

    # step past the closing bracket
    self._pos += 1
    return result

  def _parse_quoted(self) -> str:
    """
    Parse a single- or double-quoted scalar.

    Returns:
      The unquoted string.

    Raises:
      ValueError: When the quote is never closed.
    """
    quote = self._peek()
    start = self._pos
    self._pos += 1
    while self._pos < len(self._text):
      char = self._text[self._pos]

      # a backslash escapes the next character only inside double quotes
      if char == "\\" and quote == '"':
        self._pos += 2
        continue
      if char == quote:

        # a doubled single quote is one literal quote
        if quote == "'" and self._text[self._pos + 1:self._pos + 2] == "'":
          self._pos += 2
          continue
        self._pos += 1
        raw = self._text[start:self._pos]
        return raw[1:-1].replace("''", "'") if quote == "'" else json.loads(raw)
      self._pos += 1

    # the text ended inside the quote
    raise ValueError(f"unclosed quote in {self._text!r}")

  def _parse_plain(self, stops: str) -> str:
    """
    Parse a plain scalar up to the first stop character.

    Args:
      stops: The characters that end the scalar.

    Returns:
      The stripped scalar.

    Raises:
      ValueError: When the scalar is empty.
    """
    self._skip()
    start = self._pos
    while self._pos < len(self._text) and self._text[self._pos] not in stops:
      self._pos += 1
    value = self._text[start:self._pos].strip()

    # guard: a missing scalar
    if not value:
      raise ValueError(f"missing value at {start} in {self._text!r}")
    return value

  def parse_document(self) -> str | list | dict:
    """
    Parse the whole text as one value.

    Returns:
      The value.

    Raises:
      ValueError: When the text is not one well-formed flow value.
    """
    value = self._parse_value()
    self._skip()

    # guard: trailing text after the value
    if self._pos != len(self._text):
      raise ValueError(f"unexpected text at {self._pos} in {self._text!r}")
    return value
