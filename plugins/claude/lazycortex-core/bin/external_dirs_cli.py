"""
External-directory surface for the `lazycortex-core` CLI.

This module backs the `external-dirs` subcommand family — `check`, `apply`, `status`,
`fix-ignore`, and `set-root` — over the `external_dirs` module and the local-only settings
overlay. Every verb prints JSON to stdout except `status`, whose single token is meant to be
branched on directly. The repository root follows the convention every other subcommand
uses: the `LAZY_REPO_ROOT` env var, falling back to the process working directory,
overridable per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json
import os

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import ExternalDirsKey, SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from external_dirs import (  # pylint: disable=import-error
  append_ignore_lines,
  apply,
  check,
  declared_paths,
  ignore_fix_lines,
  source_root,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_local_only_section, save_local_section  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# waiver: closed-set status tokens printed by `external-dirs status`, consumed verbatim by the install skill
_NO_DECLARATION = "no-declaration"
_CONFIGURED = "configured"
_DECLINED = "declined"
_UNCONFIGURED = "unconfigured"
# waiver: argparse verb tokens of the `external-dirs` subcommand family, not domain keys
_VERB_CHECK = "check"
_VERB_APPLY = "apply"
_VERB_STATUS = "status"
_VERB_FIX_IGNORE = "fix-ignore"
_VERB_SET_ROOT = "set-root"
# waiver: JSON keys of the `fix-ignore` wire shape, not domain constants
_ROWS = "rows"
_PROPOSED = "proposed"
_APPENDED = "appended"


def compute_status(repo: Path) -> str:
  """
  Classify how far a checkout has gone in configuring its declared external directories.

  Args:
    repo: Repository root whose declaration and overlay are read.

  Returns:
    One of `no-declaration`, `configured`, `declined`, or `unconfigured`, checked in that order.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """

  # Domain(install.reconciliation):
  # # A checkout's external-directory state is one of four, checked in order
  # A checkout that declares no external directories is outside the feature entirely, whatever
  # its personal overlay records. Otherwise a recorded source root means the operator already
  # configured the directories; failing that, a recorded refusal means the operator declined;
  # and a checkout with a declaration but neither answer is still unconfigured. The order is fixed
  # so that a recorded root always outranks a stale refusal, and the install skill branches on the
  # single resulting word.

  # guard: nothing declared — the whole feature is inert for this repository
  if not declared_paths(repo):
    return _NO_DECLARATION

  # guard: a recorded source root means the operator already answered
  if source_root(repo) is not None:
    return _CONFIGURED

  # a recorded refusal in the personal overlay is the only other answer the operator can have given
  return _DECLINED if load_local_only_section(
    repo / SettingsFile.REL, SettingsKey.EXTERNAL_DIRS,
  ).get(ExternalDirsKey.DECLINED) else _UNCONFIGURED


def set_root(repo: Path, root: str) -> dict[str, object]:
  """
  Record the absolute source root for this checkout in the local-only overlay.

  Args:
    repo: Repository root whose overlay is written.
    root: Operator-supplied absolute or `~`-anchored path that holds the declared directories.

  Returns:
    A confirmation dict of the shape `{"status": "written", "root": <root>}`.

  Raises:
    ValueError: If `root` is neither an absolute nor a `~`-anchored path.
    json.JSONDecodeError: If the local settings overlay is not valid JSON.
  """
  # guard: a relative root would anchor to whatever the reader's repo is — the operator names an absolute source
  if not os.path.isabs(os.path.expanduser(root)):
    raise ValueError(f"root must be an absolute path, got {root!r}")

  # the root is personal to this machine, so it lands in the local overlay and never in the tracked file
  section = load_local_only_section(repo / SettingsFile.REL, SettingsKey.EXTERNAL_DIRS)
  section[ExternalDirsKey.ROOT] = root
  save_local_section(repo / SettingsFile.REL, SettingsKey.EXTERNAL_DIRS, section)
  # waiver: JSON keys of the confirmation wire shape, not domain constants
  return { "status": "written", "root": root }


def fix_ignore(repo: Path, *, write: bool) -> dict[str, object]:
  """
  Report the ignore coverage of every declared path and the `.gitignore` lines still missing.

  Notes:
    - Reads the tracked `lazy.settings.json`, its local overlay and the repository's ignore rules;
      with `write` set, appends the proposed lines to `.gitignore`.

  Args:
    repo: Repository root whose declaration and ignore rules are read.
    write: When true, append the proposed lines to `.gitignore` and report what was appended.

  Returns:
    `{"rows": <check rows>, "proposed": <lines>}`, plus `"appended": <lines>` when `write` is set.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  # the missing lines are computed once so the report and the append share the same list
  proposed = ignore_fix_lines(repo)
  out: dict[str, object] = { _ROWS: check(repo), _PROPOSED: proposed }

  # the lines reach .gitignore only under --apply, and the report then says what was appended
  if write:
    out[_APPENDED] = append_ignore_lines(repo, proposed)

  # the coverage report, with the appended lines when a write happened
  return out


def cmd_external_dirs(argv: list[str]) -> int:
  """
  Run the `external-dirs` subcommand family and print the verb's result to stdout.

  Args:
    argv: Argument vector after the subcommand name (verb, its arguments, optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 when `set-root` rejects its path or finds the local
    settings overlay malformed.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If `status`, `check`, `apply` or `fix-ignore` finds the tracked
      `lazy.settings.json` or its local overlay malformed; only `set-root` reports that as an
      error document.
  """
  # the family's command line: the repo-root override and one sub-verb with its own arguments
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core external-dirs")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature, not a domain key
  verbs = parser.add_subparsers(dest = "verb", required = True)
  verbs.add_parser(_VERB_CHECK)
  verbs.add_parser(_VERB_APPLY)
  verbs.add_parser(_VERB_STATUS)
  # waiver: argparse CLI signature, not a domain key
  verbs.add_parser(_VERB_FIX_IGNORE).add_argument("--apply", action = "store_true", dest = "write")
  # waiver: argparse CLI signature, not a domain key
  verbs.add_parser(_VERB_SET_ROOT).add_argument("root")
  args = parser.parse_args(argv)
  repo = resolve_repo_root(args.cwd)

  # `status` prints a bare token so a shell can branch on it; every other verb prints JSON
  if args.verb == _VERB_STATUS:
    print(compute_status(repo))
    return 0

  # `set-root` reports a rejected path as an error document, never as a traceback
  if args.verb == _VERB_SET_ROOT:
    try:
      print(json.dumps(set_root(repo, args.root)))
    except ValueError as error:
      # waiver: JSON key of the error wire shape, not a domain constant
      print(json.dumps({ "error": str(error) }))
      return 1
    return 0

  # `fix-ignore` reports the coverage rows and the proposed lines, appending them only under --apply
  if args.verb == _VERB_FIX_IGNORE:
    print(json.dumps(fix_ignore(repo, write = args.write), ensure_ascii = False))
    return 0

  # `apply` and `check` share one wire shape — the per-path rows
  print(json.dumps(apply(repo) if args.verb == _VERB_APPLY else check(repo), ensure_ascii = False))
  return 0
