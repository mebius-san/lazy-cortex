"""
Guard config writer and public scan file lister for the `lazycortex-core` CLI.

This module backs two subcommands. `guard-public-write` records the public scopes, waivers and skipped paths of a
repository's guard config and leaves every other key of an existing file as it is; the recorded scopes change only
when the caller states the mode: `--scope` globs for subtree-public mode, `--whole-repo` for none.
`guard-public-files` prints, as one JSON object, the files the public check scans: the tracked files within the
public scopes, minus encrypted files and skipped paths. The repository root follows the dispatcher convention:
the `LAZY_REPO_ROOT` env var, falling back to the process working directory, overridable per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import guard_checks  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from guard_checks import CONFIG_FILENAME  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: external-format guard config field names, read by guard_checks under the same spelling
_VERSION, _SCOPES, _WAIVERS, _SKIP = "version", "public_scopes", "waivers", "global_skip_paths"
# waiver: external-format waiver field names and the defaults guard_checks reads them with
_WAIVER_KEY_FIELDS = (( "check", "*" ), ( "scope", "*" ), ( "pattern", "" ))
# The config schema version this writer produces.
_SCHEMA_VERSION = 1
# Outcome words and report fields of the verb.
_CREATED, _UPDATED, _UNCHANGED = "created", "updated", "unchanged"
_STATUS, _PATH, _ERROR = "status", "path", "error"
# Fields of the `guard-public-files` report the check-public skill reads.
_FILES, _OUTSIDE_SCOPE, _ENCRYPTED, _SKIPPED = "files", "outside_scope", "encrypted", "skipped"


def _waiver_key(waiver: dict) -> tuple[str, ...]:
  """
  Return the identity of a waiver, made of what it covers.

  Args:
    waiver: Waiver record.

  Returns:
    The check, scope and pattern of the waiver, each with the default the scanner applies.
  """
  # a waiver is identified by what it covers, each field read with the default the scanner applies
  return tuple(str(waiver.get(name, default)) for name, default in _WAIVER_KEY_FIELDS)


def _merge_waivers(current: list, new: list[dict]) -> list:
  """
  Merge new waivers into the recorded ones.

  Args:
    current: Waivers already recorded.
    new: Waivers to add.

  Returns:
    The recorded waivers in their order; a new waiver replaces a recorded one covering the same, others are appended.
  """

  # Domain(guard.public-scan):
  # # Waiver identity
  # A waiver is identified by what it covers: the check it silences, the scope it applies to and the pattern it
  # matches. A field a waiver leaves out counts with the default the scanner applies when it reads that waiver,
  # so a waiver that omits its check and one that names every check are the same waiver.
  # Recording a waiver that covers the same ground as a recorded one replaces the recorded waiver in place, keeping
  # its position and taking the new reason and expiry; waivers covering different ground sit side by side. The
  # reason and the expiry are not part of the identity, so renewing a waiver never leaves two entries for one exemption.

  # a new waiver covering what a recorded one covers takes its place; any other one is appended
  merged = list(current)
  index = { _waiver_key(recorded): idx for idx, recorded in enumerate(merged) if isinstance(recorded, dict) }
  for waiver in new:
    key = _waiver_key(waiver)
    if key in index:
      merged[index[key]] = waiver
    else:
      index[key] = len(merged)
      merged.append(waiver)
  return merged


def write_guard_public(root: Path, *, scopes: list[str] | None, waivers: list[dict], skip_paths: list[str]) -> dict:
  """
  Write the guard config of a repository, merging the given entries into an existing file.

  Guarantees:
    - Every key of an existing config other than the schema version, the public scopes, the waivers and the globally
      skipped paths is kept with its value.
    - A call whose resulting config equals the recorded one leaves the file byte for byte unchanged.
    - Leaving the scopes unstated keeps the recorded public scopes, so a write that only adds waivers or skipped
      paths never wipes the scopes of a subtree-public repository; a stated list replaces them, and an empty list
      records none (whole-repo mode).

  Args:
    root: Repository root.
    scopes: Public scopes to record, replacing the recorded ones; empty records no scopes (whole-repo mode), and
      `None` keeps the recorded ones.
    waivers: Waivers to merge in.
    skip_paths: Paths to append to the globally skipped ones.

  Returns:
    Report with the status word (`created`, `updated` or `unchanged`), the config path, the waiver count and scopes.

  Raises:
    json.JSONDecodeError: If the existing config file is not valid JSON; the file is left untouched.
    ValueError: If the existing config file is valid JSON but not an object; the file is left untouched.
  """

  # Contract:
  # Every key of an existing config other than the schema version, the public scopes, the waivers and the globally
  # skipped paths is kept with its value; operator data stored under other keys survives every call.

  # Contract:
  # A call whose resulting config equals the recorded one leaves the file byte for byte unchanged,
  # so it is never rewritten and never reformatted.

  # Contract:
  # Leaving the scopes unstated keeps the recorded public scopes as they are, so a write that only adds waivers or
  # skipped paths never wipes the scopes of a subtree-public repository; a stated list replaces the recorded scopes,
  # and an empty list records none, which is whole-repo mode.

  path = root / CONFIG_FILENAME
  exists = path.is_file()
  data = json.loads(path.read_text(encoding = "utf-8")) if exists else {}

  # guard: a config that parses but is not an object holds no keys to merge into and is refused untouched
  if not isinstance(data, dict):
    raise ValueError(f"{CONFIG_FILENAME} is not a JSON object")

  # the recorded file keeps every key it has; stated scopes replace the recorded ones, the other owned keys merge
  merged = dict(data)
  merged[_VERSION] = _SCHEMA_VERSION
  merged[_SCOPES] = list(scopes) if scopes is not None else list(data.get(_SCOPES) or [])
  merged[_WAIVERS] = _merge_waivers(data.get(_WAIVERS) or [], waivers)
  if skip_paths or _SKIP in data:
    recorded = list(data.get(_SKIP) or [])
    merged[_SKIP] = recorded + [ skip_path for skip_path in dict.fromkeys(skip_paths) if skip_path not in recorded ]

  # an unchanged config is left byte for byte as it is
  status = _CREATED if not exists else (_UNCHANGED if merged == data else _UPDATED)
  if status != _UNCHANGED:
    runtime_state.atomic_write_text(path, json.dumps(merged, indent = 2) + "\n")
  return { _STATUS: status, _PATH: str(path), _WAIVERS: len(merged[_WAIVERS]), _SCOPES: merged[_SCOPES] }


def cmd_guard_public_write(argv: list[str]) -> int:
  """
  Run the `guard-public-write` subcommand: merge scopes, waivers and skip paths into the guard config.

  Args:
    argv: Argument vector after the subcommand name (repeatable `--scope`, `--waiver`, `--skip-path`, the
      `--whole-repo` flag and `--cwd`).

  Returns:
    Process exit code: `0` on success, `1` when `--scope` and `--whole-repo` are both given, a waiver is not a JSON
    object, or the existing config file is not valid JSON or not a JSON object; every refusal prints one JSON
    line with `status` set to `error` and leaves the file untouched.
  """
  # every flag repeats; the repo root follows the dispatcher convention
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core guard-public-write")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--scope", action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--waiver", action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--skip-path", action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--whole-repo", action = "store_true")
  args = parser.parse_args(argv)

  # guard: the two modes exclude each other, and the call is refused before the file is touched
  if args.scope and args.whole_repo:
    print(json.dumps({ _STATUS: _ERROR, "message": "--scope and --whole-repo exclude each other" }))
    return 1

  # the scopes change only when the call states the mode; a waiver-only call keeps the recorded ones
  scopes = list(args.scope) if args.scope else ([] if args.whole_repo else None)

  # every waiver must parse as an object before the file is touched
  waivers = []
  for raw in args.waiver:
    try:
      waiver = json.loads(raw)
    except json.JSONDecodeError:
      waiver = None

    # guard: one malformed waiver refuses the whole call
    if not isinstance(waiver, dict):
      print(json.dumps({ _STATUS: _ERROR, "message": f"--waiver is not a JSON object: {raw!r}" }))
      return 1
    waivers.append(waiver)

  # the merged config's summary is the verb's whole output; a config that does not parse is refused untouched
  try:
    result = write_guard_public(
      resolve_repo_root(args.cwd), scopes = scopes, waivers = waivers, skip_paths = args.skip_path,
    )
  except json.JSONDecodeError as error:
    print(json.dumps({ _STATUS: _ERROR, "message": f"{CONFIG_FILENAME} is not valid JSON: {error}" }))
    return 1
  except ValueError as error:
    print(json.dumps({ _STATUS: _ERROR, "message": str(error) }))
    return 1
  print(json.dumps(result))
  return 0


def find_public_scan_files(root: Path) -> dict:
  """
  Return the tracked files the public check scans, with the count of files dropped from the scan.

  Applies the same guard config reading and path matching as the `lazy-guard.check-public` pre-commit hook, so the
  skill and the hook agree on what counts as public.

  Guarantees:
    - The scan set is the same as the one the `lazy-guard.check-public` pre-commit hook scans: the same guard config
      reading and the same public-scope, encrypted-file and skip-path exclusions.

  Args:
    root: Repository root.

  Returns:
    Report with the scanned files under `files` in tracked order, and the counts of files dropped as outside the
    public scopes, as encrypted, and as skipped, under `outside_scope`, `encrypted` and `skipped`.

  Raises:
    RuntimeError: If the tracked files of the repository cannot be listed.
  """

  # Contract:
  # The scanned files are exactly the set the `lazy-guard.check-public` pre-commit hook scans: the guard config is
  # read the same way, and the public-scope, encrypted-file and skip-path exclusions are the same, so the skill and
  # the hook never disagree on which files count as public.

  # the tracked files are the starting list; `-z` keeps unusual paths unquoted
  # waiver: git CLI argument vector, not a domain key
  proc = subprocess.run([ "git", "ls-files", "-z" ], cwd = root, capture_output = True, text = True, check = False)

  # guard: no tracked list to filter outside a readable repository
  if proc.returncode != 0:
    raise RuntimeError(f"git ls-files failed: {proc.stderr.strip()}")
  tracked = [ path for path in proc.stdout.split("\0") if path ]

  # the same config reader and path predicates the pre-commit hook applies
  _, scope_globs, skip_globs = guard_checks.load_config(str(root))

  # filter 1: only the public scopes, when any are declared
  in_scope = [ path for path in tracked if guard_checks.in_public_scope(path, scope_globs) ]

  # filter 2: encrypted files are unreadable by design
  # waiver: file-extension idiom of age-encrypted files, shared with the hooks' staged-diff reader
  readable = [ path for path in in_scope if not path.endswith(".age") ]

  # filter 3: vendored or third-party paths are never scanned
  files = [ path for path in readable if not guard_checks.is_skipped(path, skip_globs) ]

  # the list plus what each filter dropped, for the skill's report line
  return {
    _FILES: files, _OUTSIDE_SCOPE: len(tracked) - len(in_scope), _ENCRYPTED: len(in_scope) - len(readable),
    _SKIPPED: len(readable) - len(files),
  }


def cmd_guard_public_files(argv: list[str]) -> int:
  """
  Run the `guard-public-files` subcommand: print the files the public check scans.

  Args:
    argv: Argument vector after the subcommand name (the `--cwd` option).

  Returns:
    Process exit code: `0` after printing the scan report as one JSON line; `1` when the tracked files cannot be
    listed, after printing one JSON line with `status` set to `error`.
  """
  # the repo root follows the dispatcher convention
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core guard-public-files")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the filtered list is the verb's whole output; an unlistable repository is refused
  try:
    result = find_public_scan_files(resolve_repo_root(args.cwd))
  except RuntimeError as error:
    print(json.dumps({ _STATUS: _ERROR, "message": str(error) }))
    return 1
  print(json.dumps(result))
  return 0
