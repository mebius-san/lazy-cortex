"""
Idempotent seeding of frontmatter predicates into an existing routine's `filter` block.

Backs the `routine-ensure-filter` subcommand of the `lazycortex-core` CLI: the boundary-legal
way for a sibling plugin to keep a class of documents it understands away from another plugin's
routine — the specs plugin parking `deferred` documents out of the wiki scanners — without
hand-editing `lazy.settings.json` or importing `lazycortex-core` Python.

The contract mirrors the wiki scope seed: only keys the routine's `filter.frontmatter` does not
carry are planted, an operator's own predicate for the same key is never overwritten or merged
into, and a routine that is not registered is reported, never created.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
from pathlib import Path

from constants import SettingsKey
from lazy_settings import load_tracked_section, save_section
from settings_cli import _resolve_settings_path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class _K:
  """
  Wire keys of the routine filter block and of this verb's result.

  Attributes:
    FILTER: The routine's filter block.
    FRONTMATTER: The frontmatter-predicate sub-block of a filter.
    STATUS: Result status key.
    ADDED: Status value when at least one key was seeded.
    UNCHANGED: Status value when every requested key was already present.
    ERROR: Status value for an unregistered routine or malformed input.
    REASON: Result key carrying the error reason.
    ADDED_KEYS: Result key listing the seeded frontmatter keys.
    NO_SUCH_ROUTINE: The reason reported for an unregistered routine.
    NOT_AN_OBJECT: The reason reported when the predicates argument is not a JSON object.
  """

  FILTER = "filter"
  FRONTMATTER = "frontmatter"
  STATUS = "status"
  ADDED = "added"
  UNCHANGED = "unchanged"
  ERROR = "error"
  REASON = "reason"
  ADDED_KEYS = "added_filter_keys"
  NO_SUCH_ROUTINE = "no such routine"
  NOT_AN_OBJECT = "filter-json must be a JSON object"


# ----------------------------------------------------------------------------------------
def ensure_routine_filter(repo: Path, name: str, filter_frontmatter: dict) -> dict:
  """
  Seed absent frontmatter predicates into one registered routine's `filter` block.

  Reads the tracked `routines` section, plants each requested predicate whose key the routine's
  `filter.frontmatter` does not already carry, and writes the section back only when something
  changed. A routine without a `filter` block gains one holding just the seeded predicates.

  Guarantees:
    - An existing predicate for a requested key is never overwritten, merged into, or reordered.
    - A routine that is not registered is never created; the failure is the call's outcome.
    - The `routines` section is written at most once per call, and only when it changed.

  Args:
    repo: Absolute repository root; the settings file is `<repo>/.claude/lazy.settings.json`.
    name: Registered routine name.
    filter_frontmatter: Predicates to seed, keyed by frontmatter key.

  Returns:
    `{"status": "added", "added_filter_keys": [...]}` when anything was seeded,
    `{"status": "unchanged"}` when every key was already present, or
    `{"status": "error", "reason": "no such routine"}` for an unregistered name.
  """

  # Domain(plugin.boundaries):
  # # Non-destructive filter seeding across plugin boundaries
  # When one plugin needs to keep a class of content it understands away from a routine owned
  # by a different plugin, it seeds a matching predicate onto that routine instead of editing
  # the owning plugin's configuration directly. Seeding only plants a predicate for a key the
  # routine does not judge yet; an operator's own predicate for that key is never overwritten,
  # merged into, or reordered, and a routine that has not been registered yet is never created
  # as a side effect of seeding.

  path = _resolve_settings_path(repo)
  routines = load_tracked_section(path, SettingsKey.ROUTINES)
  entry = routines.get(name)

  # Contract:
  # A routine that is not registered is NEVER created as a side effect of seeding; the
  # caller receives the failure as this call's outcome instead.

  # guard: seeding must never register a routine — that is the registrar's job
  if not isinstance(entry, dict):
    return { _K.STATUS: _K.ERROR, _K.REASON: _K.NO_SUCH_ROUTINE }

  # Contract:
  # Only keys absent from `filter.frontmatter` are planted; an existing predicate for a
  # requested key is NEVER overwritten or merged into, and the section is written at most once.

  # the keys the routine does not judge yet, in request order; a filter block is created on demand
  frontmatter = entry.setdefault(_K.FILTER, {}).setdefault(_K.FRONTMATTER, {})
  added = [ key for key in filter_frontmatter if key not in frontmatter ]
  # guard: every requested key is already judged by the routine — no write at all
  if not added:
    return { _K.STATUS: _K.UNCHANGED }

  # plant only the absent keys and persist the section once
  for key in added:
    frontmatter[key] = filter_frontmatter[key]
  save_section(path, SettingsKey.ROUTINES, routines)
  return { _K.STATUS: _K.ADDED, _K.ADDED_KEYS: added }


# ----------------------------------------------------------------------------------------
def cmd_routine_ensure_filter(argv: list[str]) -> int:
  """
  Run the `routine-ensure-filter` subcommand and print the outcome as JSON.

  Args:
    argv: Argument vector after the subcommand name: the routine name, `--filter-json` with the
      predicates object, and an optional `--cwd` repository root.

  Returns:
    Process exit code: 0 when the seed landed or was already in place, 1 for an unregistered
    routine or malformed predicates JSON, 2 on argument error.
  """
  # the CLI surface: routine name, predicates object, optional repository root
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core routine-ensure-filter")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("name")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--filter-json", required = True, help = "JSON object: frontmatter key -> predicate")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # the predicates must parse as a JSON object keyed by frontmatter key
  try:
    predicates = json.loads(args.filter_json)
  except json.JSONDecodeError as error:
    print(json.dumps({ _K.STATUS: _K.ERROR, _K.REASON: f"filter-json parse: {error}" }))
    return 1
  # guard: a scalar or array cannot be seeded key by key
  if not isinstance(predicates, dict):
    print(json.dumps({ _K.STATUS: _K.ERROR, _K.REASON: _K.NOT_AN_OBJECT }))
    return 1

  # seed against the explicit root, or the same LAZY_REPO_ROOT-or-cwd convention every verb uses
  repo = Path(args.cwd) if args.cwd is not None else _resolve_settings_path(None).parent.parent
  result = ensure_routine_filter(repo, args.name, predicates)
  print(json.dumps(result))
  return 1 if result.get(_K.STATUS) == _K.ERROR else 0
