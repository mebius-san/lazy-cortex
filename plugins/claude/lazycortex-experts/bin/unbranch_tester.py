#!/usr/bin/env python3

"""
Tester branch removal for the lazycortex-experts plugin.

Backs the `unbranch-tester` verb: the tester now checks the deployed product and commits nothing, so the
`workspace` and `can_commit_in_repo` keys an older install seeded into its entry no longer apply. The verb removes
those two keys from every expert whose `agent` is the tester agent, in the tracked settings and in the gitignored
local overlay at the toplevel of the checkout the run works in.
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
import experts_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The dispatch string of the tester agent, the keys removed from its entries and the section and field that name it.
TESTER_AGENT = "lazycortex-experts:lazy-experts.tester"
_REMOVED_KEYS = ( "workspace", "can_commit_in_repo" )
_EXPERTS_SECTION = "experts"
_AGENT_FIELD = "agent"

# The tracked settings file and its gitignored local overlay, relative to the repository root.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_LOCAL_REL = Path(".claude") / "lazy.settings.local.json"

# The core verb a value is removed through, and its arguments.
_CORE_SET = "settings-set"
_KEY_FLAG = "--key"
_DELETE_FLAG = "--delete"
_CWD_FLAG = "--cwd"
_SCOPE_FLAG = "--scope"
_KEY_SEP = "/"

# The settings layer each file is written through.
_TRACKED_SCOPE = "tracked"
_LOCAL_SCOPE = "local"

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120

# How undecodable subprocess output is read.
_DECODE_ERRORS = "replace"

# The answer's keys: the removed pairs of the tracked file and of the local overlay.
_TRACKED_KEY = "tester_unbranched"
_LOCAL_KEY = "local_tester_unbranched"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def compute_removals(settings: dict) -> list[str]:  # waiver: parsed settings JSON, shape is not ours
  """
  Report the `<expert key>/<removed key>` pairs a removal would delete from one parsed settings layer.

  Guarantees:
    - Only a key of `workspace` / `can_commit_in_repo` on an expert whose `agent` is the tester agent is reported.
    - Sections and entries of another shape than an object are skipped.

  Args:
    settings: One parsed settings layer.

  Returns:
    A plain list of `<expert key>/<removed key>` pairs; empty when no tester entry carries a removed key.
  """
  pairs: list[str] = []

  # guard: a missing or malformed `experts` section holds no tester entry
  experts = settings.get(_EXPERTS_SECTION)
  if not isinstance(experts, dict):
    return pairs

  # only an object entry naming the tester agent contributes the removed keys it carries
  for key, entry in experts.items():
    if isinstance(entry, dict) and entry.get(_AGENT_FIELD) == TESTER_AGENT:
      pairs.extend(f"{key}{_KEY_SEP}{field}" for field in _REMOVED_KEYS if field in entry)
  return pairs


def _core_delete(core_cli: Path, repo: Path, *, scope: str, path: list[str]) -> None:
  """
  Delete one value from the `experts` section of one settings layer.

  Args:
    core_cli: The core plugin's CLI file.
    repo: The repository root.
    scope: The settings layer written, `tracked` or `local`.
    path: The keys from the `experts` section down to the value.

  Raises:
    RuntimeError: When the core CLI cannot run, runs past its time limit, or exits non-zero.
  """
  # a spawn the system refuses, or a call past its time limit, is a failed core call like any other
  try:
    res = subprocess.run(
        [ sys.executable, str(core_cli), _CORE_SET, _EXPERTS_SECTION, _SCOPE_FLAG, scope, _KEY_FLAG,
          _KEY_SEP.join(path), _DELETE_FLAG, _CWD_FLAG, str(repo) ],
        cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
        errors = _DECODE_ERRORS, timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{_CORE_SET} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{_CORE_SET} could not run: {error}") from error

  # guard: a failed core call leaves the value as it was
  if res.returncode != 0:
    raise RuntimeError(f"{_CORE_SET} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]} "
                       f"stdout={res.stdout.strip()[:240]}")


def _read_layer(settings_path: Path) -> dict | None:  # waiver: parsed settings JSON, shape is not ours
  """
  Read one settings layer as a JSON object.

  Args:
    settings_path: The tracked settings file or the local overlay.

  Returns:
    The parsed settings object; None when the file is absent.

  Raises:
    ValueError: When the file cannot be read, does not parse as JSON, or is not a JSON object.
  """
  # guard: an absent file holds nothing to change and is never created
  if not settings_path.is_file():
    return None

  # an unreadable or unparseable file fails the run
  try:
    settings = json.loads(settings_path.read_text(encoding = "utf-8"))
  except (OSError, ValueError) as error:
    raise ValueError(f"{settings_path} does not parse as JSON: {error}") from error

  # guard: only an object can carry the sections
  if not isinstance(settings, dict):
    raise ValueError(f"{settings_path} is not a JSON object")
  return settings


def migrate(repo: Path, core_cli: Path | None, *, dry_run: bool = False) -> dict[str, list[str]]:
  """
  Remove the branch and commit keys from the tester entries of the repository's settings.

  Guarantees:
    - Only `workspace` and `can_commit_in_repo` of experts naming the tester agent are removed; every other key,
      the key order and every other entry stay as read.
    - The tracked file and the local overlay are each read and written alone; an absent overlay is never created.
    - A dry run writes nothing.
    - A second run finds nothing to do.

  Args:
    repo: The repository root.
    core_cli: The core plugin's CLI file; required unless the run is dry.
    dry_run: Report without writing.

  Returns:
    The removed `<expert key>/<key>` pairs of the tracked file under `tester_unbranched` and of the overlay under
    `local_tester_unbranched`; an absent layer reports an empty list.

  Raises:
    RuntimeError: When a write is due and no usable core CLI is given, or a core call fails.
    ValueError: When a settings file does not parse as a JSON object.
  """

  # Contract:
  # Only the `workspace` and `can_commit_in_repo` keys of experts naming the tester agent are ever removed;
  # every other key, the key order and every other entry stay exactly as read.

  # Contract:
  # The tracked settings file and the local overlay are each read and written alone, and an absent
  # overlay is never created.

  # Contract:
  # A dry run writes nothing.

  # Contract:
  # A second run right after a successful one finds nothing to do and reports no pairs.

  # each layer is read alone and reports its own removal pairs
  tracked = _read_layer(repo / _SETTINGS_REL)
  local = _read_layer(repo / _LOCAL_REL)
  tracked_pairs = compute_removals(tracked or {})
  local_pairs = compute_removals(local or {})
  result = { _TRACKED_KEY: tracked_pairs, _LOCAL_KEY: local_pairs }

  # a dry run, or a run with nothing to remove, returns the report as it stands
  if dry_run or not (tracked_pairs or local_pairs):
    return result

  # guard: a write needs the core CLI
  if core_cli is None or not core_cli.is_file():
    raise RuntimeError(f"core CLI not usable: {core_cli}")

  # each layer is written through its own scope
  for scope, pairs in ( (_TRACKED_SCOPE, tracked_pairs), (_LOCAL_SCOPE, local_pairs) ):
    for pair in pairs:
      expert, field = pair.rsplit(_KEY_SEP, 1)
      _core_delete(core_cli, repo, scope = scope, path = [ expert, field ])
  return result


def main(argv: list[str]) -> int:
  """
  Run the `unbranch-tester` command and print its result as one JSON line.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when a layer has work left, 1 when none does.
    - Any failure exits 2 under every flag, never an answer `--check` gives.

  Notes:
    - The tracked settings and the local overlay are those at the toplevel of the checkout that `--cwd`, else
      `$LAZY_REPO_ROOT`, else the working directory sits in, even inside a nested project with settings of its own:
      the sections migrated are read by the daemon, which keeps them at the checkout's toplevel.

  Args:
    argv: Command-line arguments, without the program name.

  Returns:
    With `--check`, 0 when work remains and 1 when none does; 0 otherwise; 2 when the run failed.
  """

  # Contract:
  # With `--check` the command writes nothing and exits 0 when work remains and 1 when none does;
  # the migration step's `applies_when` predicate builds on this answer.

  # Contract:
  # Any failure exits 2 under every flag, so a failure is never mistaken for the `--check` answer
  # "nothing to do".

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-experts unbranch-tester")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--core-cli", default = None)
  args = parser.parse_args(argv)

  # the core CLI to call, when the caller names one
  core_cli = Path(args.core_cli) if args.core_cli else None

  # a check runs dry against the checkout toplevel of `--cwd`, else of the daemon's env var, else of the process cwd,
  # where the daemon-read sections live; any failure exits 2
  try:
    result = migrate(experts_locator.query_repo_root(args.cwd), core_cli, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"unbranch-tester: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result, ensure_ascii = False))

  # only a check answers through its exit code
  if args.check:
    return 0 if any(result.values()) else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
