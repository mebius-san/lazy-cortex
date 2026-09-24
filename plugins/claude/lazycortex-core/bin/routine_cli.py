"""
Routine-registry verbs for the `lazycortex-core` CLI.

This module backs the `routine-validate` / `routine-register` / `routine-unregister` /
`routine-show` / `routine-migrate` subcommands the `lazy-routine.register`, `lazy-routine.unregister`, and
`lazy-core.doctor` skills call instead of embedding Python. Validation reads the merged
settings view (tracked plus local overlay) because a broken local entry breaks the daemon just
as a tracked one does; registration and removal go through `expert_runtime`, which writes the
tracked layer only. The repository root follows the dispatcher convention: the
`LAZY_REPO_ROOT` env var, falling back to the process working directory, overridable per-call
with `--cwd`.
"""
from __future__ import annotations

import argparse
import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_runtime import register_routine, unregister_routine  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section, load_tracked_section  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from routine_types import (  # pylint: disable=import-error
  GROUP_DIR, GROUP_FILE, GROUP_KEY, LEGACY_GROUP_GLOBS_KEY, RoutineConfigError, validate_routine_entry,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def _build_parser(verb: str, *, with_name: bool) -> argparse.ArgumentParser:
  """
  Build the shared argparse surface for one routine verb.

  Args:
    verb: Subcommand name, used in the `prog` string.
    with_name: Whether the verb takes a positional routine name.

  Returns:
    A parser carrying the optional `--cwd` flag and, when requested, the positional name.
  """
  # the shared command line: the routine name when the verb takes one, and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = f"lazycortex-core {verb}")
  if with_name:
    # waiver: argparse CLI signature, not a domain key
    parser.add_argument("name")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  return parser


def cmd_routine_validate(argv: list[str]) -> int:
  """
  Run the `routine-validate` subcommand: print one `name<TAB>error` line per invalid routine.

  Guarantees:
    - Every invalid routine is reported, one line each, not only the first one found.

  Args:
    argv: Argument vector after the subcommand name (optional `--cwd`).

  Returns:
    Process exit code: 0 when every routine validates, 1 when at least one does not.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file or its local overlay is not valid JSON.
  """
  # waiver: CLI verb name, not a domain key
  args = _build_parser("routine-validate", with_name = False).parse_args(argv)
  routines = load_section(resolve_repo_root(args.cwd) / SettingsFile.REL, SettingsKey.ROUTINES)
  # waiver: the section-version stamp is lazy_settings' own field, not a routine
  routines.pop("_version", None)

  # Contract:
  # Every invalid entry is reported, one line each, not just the first; the doctor lists them all
  # in one pass and relies on the listing being complete.

  # walk the whole registry, counting the entries that fail
  invalid = 0
  for name, cfg in routines.items():
    # guard: a non-object entry, reported whole with no field to validate
    if not isinstance(cfg, dict):
      # waiver: diagnostic wording read by the doctor skill, not a reusable domain key
      print(f"{name}\tnot an object")
      invalid += 1
      continue

    # the registry's own validator names the first broken field of an object entry
    try:
      validate_routine_entry(name, cfg)
    except RoutineConfigError as error:
      print(f"{name}\t{error}")
      invalid += 1

  # one invalid entry is enough to fail the verb
  return 1 if invalid else 0


def cmd_routine_register(argv: list[str]) -> int:
  """
  Run the `routine-register` subcommand: validate and persist one routine entry.

  Args:
    argv: Argument vector after the subcommand name (name plus `--cfg <json>`, optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 on malformed or invalid config.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
    OSError: If the tracked settings file or its parent directory cannot be written.
  """
  # waiver: CLI verb name, not a domain key
  parser = _build_parser("routine-register", with_name = True)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cfg", required = True, help = "Fully-formed routine config as a JSON object")
  args = parser.parse_args(argv)

  # a malformed config is reported as one line, never as a traceback
  try:
    cfg = json.loads(args.cfg)
  except json.JSONDecodeError as error:
    print(f"cfg parse: {error}")
    return 1

  # guard: a routine config is always a JSON object — reject scalars / arrays before touching disk
  if not isinstance(cfg, dict):
    # waiver: naming the rejected JSON type in a CLI error message; no class registry exists here
    print(f"cfg must be a JSON object, got {type(cfg).__name__}")
    return 1

  # the registry validates the entry itself and reports a rejection as one line
  try:
    register_routine(resolve_repo_root(args.cwd), args.name, cfg)
  except RoutineConfigError as error:
    print(str(error))
    return 1

  # the outcome word the calling skill reads
  # waiver: CLI outcome token read by the calling skill, not a reusable domain key
  print("registered")
  return 0


def cmd_routine_unregister(argv: list[str]) -> int:
  """
  Run the `routine-unregister` subcommand: remove one routine entry.

  Args:
    argv: Argument vector after the subcommand name (name plus optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 when the routine is a protected built-in or the tracked
    settings file is not valid JSON.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    OSError: If the tracked settings file or its parent directory cannot be written.
  """
  # waiver: CLI verb name, not a domain key
  args = _build_parser("routine-unregister", with_name = True).parse_args(argv)

  # a protected built-in refuses removal, and a settings file that is not JSON cannot be read;
  # either is reported as one line
  try:
    unregister_routine(resolve_repo_root(args.cwd), args.name)
  except ValueError as error:
    print(str(error))
    return 1

  # the outcome word the calling skill reads
  # waiver: CLI outcome token read by the calling skill, not a reusable domain key
  print("unregistered")
  return 0


def cmd_routine_show(argv: list[str]) -> int:
  """
  Run the `routine-show` subcommand: print `present` plus the entry JSON, or `absent`.

  Args:
    argv: Argument vector after the subcommand name (name plus optional `--cwd`).

  Returns:
    Process exit code: 0 whether or not the routine exists.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file or its local overlay is not valid JSON.
  """
  # waiver: CLI verb name, not a domain key
  args = _build_parser("routine-show", with_name = True).parse_args(argv)
  routines = load_section(resolve_repo_root(args.cwd) / SettingsFile.REL, SettingsKey.ROUTINES)

  # an absent routine prints the outcome word alone
  if args.name not in routines:
    # waiver: CLI outcome token read by the calling skill, not a reusable domain key
    print("absent")
    return 0

  # a present routine prints the outcome word and then its entry, one line each
  # waiver: CLI outcome token read by the calling skill, not a reusable domain key
  print("present")
  print(json.dumps(routines[args.name]))
  return 0


def migrate_group_entry(cfg: dict) -> tuple[dict, list[str]]:
  """
  Rewrite one git routine's retired grouping keys into the `group` mode vocabulary.

  Guarantees:
    - A config carrying neither retired shape is returned equal and with an empty change list.

  Args:
    cfg: The routine config as registered.

  Returns:
    The rewritten config (a copy) and one line per change made, empty when nothing was retired.
  """

  # Contract:
  # A config carrying neither retired shape is returned EQUAL to the input, with an empty
  # change list, so re-running the migration is a no-op.

  # Domain(runtime.routines):
  # # What the retired grouping keys turn into
  # The unit of work used to be spread over two keys: a boolean that turned directory grouping
  # off, and a glob list that widened it. The boolean's two values keep their meaning under the
  # new vocabulary — off is one unit per file, on is one unit per directory. The glob list does
  # not: every registration that carried one came from a plugin whose worker now takes the whole
  # tick as one unit and splits it itself, so the list is dropped and the default takes over. An
  # operator who really wants a unit per named directory declares the list again under the new
  # key by hand; the migration never guesses that on their behalf.

  # the rewritten copy and the audit trail of what changed in it
  migrated = dict(cfg)
  changes: list[str] = []

  # the boolean opt-out maps one-to-one onto the two named modes it used to switch between
  if isinstance(migrated.get(GROUP_KEY), bool):
    mode = GROUP_FILE if migrated[GROUP_KEY] is False else GROUP_DIR
    changes.append(f"{GROUP_KEY}: {json.dumps(migrated[GROUP_KEY])} -> {json.dumps(mode)}")
    migrated[GROUP_KEY] = mode

  # the glob list is dropped, never converted — the default whole-tick unit replaces it
  if LEGACY_GROUP_GLOBS_KEY in migrated:
    changes.append(f"{LEGACY_GROUP_GLOBS_KEY}: dropped ({len(migrated[LEGACY_GROUP_GLOBS_KEY])} glob(s))")
    del migrated[LEGACY_GROUP_GLOBS_KEY]
  return migrated, changes


def cmd_routine_migrate(argv: list[str]) -> int:
  """
  Run the `routine-migrate` subcommand: rewrite retired grouping keys on every git routine.

  Prints one `name<TAB>change` line per rewrite and a closing summary line; without `--apply`
  nothing is written and the lines describe what an apply would do.

  Args:
    argv: Argument vector after the subcommand name (optional `--apply`, optional `--cwd`).

  Returns:
    Process exit code: 0 when no rewritten entry fails validation (a dry run returns 0 with its
    rewrites still pending), 1 when a rewritten entry still fails validation.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
    OSError: If the tracked settings file cannot be written.
  """
  # waiver: CLI verb name, not a domain key
  parser = _build_parser("routine-migrate", with_name = False)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--apply", action = "store_true", help = "Write the rewritten entries; default is a dry run")
  args = parser.parse_args(argv)
  repo = resolve_repo_root(args.cwd)

  # only the tracked layer is rewritten — a local-overlay entry is the operator's own file
  rewritten = 0
  invalid = 0
  for name, cfg in sorted(load_tracked_section(repo / SettingsFile.REL, SettingsKey.ROUTINES).items()):
    # guard: only a git routine ever carried the grouping keys — the section's version marker,
    # a malformed entry and every other routine type are skipped
    # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
    if not isinstance(cfg, dict) or cfg.get("type") != "git":
      continue

    # the rewrite and its audit trail for this routine
    migrated, changes = migrate_group_entry(cfg)

    # guard: already on the current shape — nothing to report for this routine
    if not changes:
      continue

    # one line per change, whether or not it is written
    for change in changes:
      print(f"{name}\t{change}")

    # a rewritten entry must validate before it is worth writing; a failure is one line, not a trace
    try:
      validate_routine_entry(name, migrated)
    except RoutineConfigError as error:
      print(f"{name}\tstill invalid: {error}")
      invalid += 1
      continue

    # a valid rewrite counts, and lands on disk only under --apply
    rewritten += 1
    if args.apply:
      register_routine(repo, name, migrated)

  # the closing line the calling skill reads
  # waiver: CLI outcome tokens read by the calling skill, not reusable domain keys
  print(f"{'rewrote' if args.apply else 'would rewrite'} {rewritten} routine(s), {invalid} still invalid")
  return 1 if invalid else 0
