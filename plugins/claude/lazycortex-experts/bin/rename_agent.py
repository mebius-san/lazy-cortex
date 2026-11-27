#!/usr/bin/env python3

"""
Agent rename for the lazycortex-experts plugin.

Backs the `rename-implementer-agent` verb: the agent `lazy-experts.implementer` is now `lazy-experts.developer`, and
a consumer's settings still name the old one. The verb rewrites the `agent` of every expert that names the old agent
and moves the `agent_models` tiers keyed by the old dispatch string, in three settings layers: the tracked settings
and the gitignored local overlay beside them, at the toplevel of the checkout the run works in, and the user-scope
settings file in the home directory. Settings are written only through the core CLI. It never commits.
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


# The dispatch string of the agent before the rename and after it.
OLD_AGENT = "lazycortex-experts:lazy-experts.implementer"
NEW_AGENT = "lazycortex-experts:lazy-experts.developer"

# The tracked settings file and its gitignored local overlay, relative to the repository root, and the sections the
# verb touches.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_LOCAL_REL = Path(".claude") / "lazy.settings.local.json"
_EXPERTS_SECTION = "experts"
_MODELS_SECTION = "agent_models"
_AGENT_FIELD = "agent"

# The core verb a value is written through, and its arguments.
_CORE_SET = "settings-set"
_KEY_FLAG = "--key"
_VALUE_FLAG = "--value"
_DELETE_FLAG = "--delete"
_CWD_FLAG = "--cwd"
_SCOPE_FLAG = "--scope"
_HOME_FLAG = "--home"
_KEY_SEP = "/"

# The settings layer each file is written through.
_TRACKED_SCOPE = "tracked"
_LOCAL_SCOPE = "local"

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120

# How undecodable subprocess output is read.
_DECODE_ERRORS = "replace"

# The result's wire-shape keys.
_EXPERTS_RENAMED_KEY = "experts_renamed"
_TIERS_RENAMED_KEY = "tiers_renamed"
_TIERS_DROPPED_KEY = "tiers_dropped"

# The prefixes that name a result key of the local overlay and of the user-scope file after its tracked twin.
_LOCAL_PREFIX = "local_"
_HOME_PREFIX = "home_"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def plan(settings: dict) -> dict[str, list[str]]:  # waiver: parsed settings JSON, shape is not ours
  """
  Work out what the rename changes in a parsed settings file.

  Guarantees:
    - Only an `agent` value equal to the old agent and a key equal to the old dispatch string are reported.
    - Sections of another shape than an object, and entries of another shape than an object, are skipped.

  Args:
    settings: One parsed settings layer: the tracked file, the local overlay or the user-scope file.

  Returns:
    The lists `experts_renamed` (expert keys), `tiers_renamed` and `tiers_dropped` (`<group>/<old dispatch string>`).
  """

  # Contract:
  # Only an expert whose `agent` is exactly the old agent, and only a tier keyed exactly by the old dispatch string,
  # is reported.

  # Contract:
  # A section or an entry that is not an object is skipped and never makes the call fail.

  experts_renamed: list[str] = []
  tiers_renamed: list[str] = []
  tiers_dropped: list[str] = []

  # an expert is renamed only when its agent is exactly the old one
  experts = settings.get(_EXPERTS_SECTION)
  if isinstance(experts, dict):
    for key, entry in experts.items():
      if isinstance(entry, dict) and entry.get(_AGENT_FIELD) == OLD_AGENT:
        experts_renamed.append(key)

  # a tier moves to the new key, or is dropped when the new key already holds the group's answer
  models = settings.get(_MODELS_SECTION)
  if isinstance(models, dict):
    for group, tiers in models.items():
      if isinstance(tiers, dict) and OLD_AGENT in tiers:
        (tiers_dropped if NEW_AGENT in tiers else tiers_renamed).append(f"{group}{_KEY_SEP}{OLD_AGENT}")
  return { _EXPERTS_RENAMED_KEY: experts_renamed, _TIERS_RENAMED_KEY: tiers_renamed,
           _TIERS_DROPPED_KEY: tiers_dropped }


# waiver: `value` is a JSON value copied from operator-edited settings (a string or a tier object) and goes back
# through `json.dumps` as read
def _core_set(core_cli: Path, repo: Path, *, scope: str, section: str, path: list[str], value: object = None,
              delete: bool = False, home: bool = False) -> None:
  """
  Write or remove one nested value through the core `settings-set` verb.

  Args:
    core_cli: The core plugin's CLI file.
    repo: The repository root.
    scope: The settings layer written, `tracked` or `local`.
    section: The settings section.
    path: The keys from the section down to the value.
    value: The value to store; unused when deleting.
    delete: Whether to remove the value instead.
    home: Whether to write the user-scope settings file instead of the repository's.

  Raises:
    RuntimeError: When the core CLI cannot run, runs past its time limit, or exits non-zero.
  """
  tail = [ _DELETE_FLAG ] if delete else [ _VALUE_FLAG, json.dumps(value) ]
  if home:
    tail.append(_HOME_FLAG)
  # a spawn the system refuses, or a call past its time limit, is a failed core call like any other
  try:
    res = subprocess.run(
        [ sys.executable, str(core_cli), _CORE_SET, section, _SCOPE_FLAG, scope, _KEY_FLAG, _KEY_SEP.join(path),
          *tail, _CWD_FLAG, str(repo) ],
        cwd = str(repo), capture_output = True, text = True, check = False, encoding = "utf-8",
        errors = _DECODE_ERRORS, timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{_CORE_SET} {section} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{_CORE_SET} {section} could not run: {error}") from error

  # guard: a failed core call leaves the value as it was
  if res.returncode != 0:
    raise RuntimeError(f"{_CORE_SET} {section} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]} "
                       f"stdout={res.stdout.strip()[:240]}")


def _read_layer(settings_path: Path) -> dict | None:  # waiver: parsed settings JSON, shape is not ours
  """
  Read one settings layer as a JSON object.

  Args:
    settings_path: The tracked settings file, the local overlay or the user-scope settings file.

  Returns:
    The parsed settings object; None when the file is absent.

  Raises:
    ValueError: When the file cannot be read, does not parse as JSON, or is not a JSON object.
  """
  # guard: an absent file holds nothing to rename and is never created
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


# waiver: parsed settings JSON, shape is not ours
def _apply(core_cli: Path, repo: Path, *, scope: str, settings: dict, changes: dict[str, list[str]],
           home: bool = False) -> None:
  """
  Write the planned renames of one settings layer back to that layer.

  Args:
    core_cli: The core plugin's CLI file.
    repo: The repository root.
    scope: The settings layer written, `tracked` or `local`.
    settings: The layer as read, source of the tier values that move.
    changes: The result of `plan` for that layer.
    home: Whether the layer is the user-scope settings file.

  Raises:
    RuntimeError: When a core call fails.
  """
  # each matching expert gets its agent value replaced
  for key in changes[_EXPERTS_RENAMED_KEY]:
    _core_set(core_cli, repo, scope = scope, section = _EXPERTS_SECTION, path = [ key, _AGENT_FIELD ],
              value = NEW_AGENT, home = home)

  # each tier moves to the new key with its value as it is, then the old key goes
  for item in changes[_TIERS_RENAMED_KEY]:
    group = item.split(_KEY_SEP, 1)[0]
    _core_set(core_cli, repo, scope = scope, section = _MODELS_SECTION, path = [ group, NEW_AGENT ],
              value = settings[_MODELS_SECTION][group][OLD_AGENT], home = home)
    _core_set(core_cli, repo, scope = scope, section = _MODELS_SECTION, path = [ group, OLD_AGENT ], delete = True,
              home = home)

  # a tier whose new key already exists only loses the old key
  for item in changes[_TIERS_DROPPED_KEY]:
    _core_set(core_cli, repo, scope = scope, section = _MODELS_SECTION,
              path = [ item.split(_KEY_SEP, 1)[0], OLD_AGENT ], delete = True, home = home)


def migrate(repo: Path, core_cli: Path | None, *, dry_run: bool = False) -> dict[str, list[str]]:
  """
  Rename the agent in the repository's settings and in the user-scope settings.

  Guarantees:
    - Only the `agent` of the experts naming the old agent and the tiers keyed by the old dispatch string change;
      everything else stays as read.
    - The tracked settings file, the local overlay and the user-scope settings file are each read and written alone;
      what is found in one layer is never written to another.
    - An absent local overlay and an absent user-scope settings file are never created.
    - When the repository root is the home directory, the tracked file and the user-scope file are one file, handled
      once as the tracked layer and never again as the user-scope layer.
    - A dry run writes nothing.
    - A second run finds nothing to do.

  Args:
    repo: The repository root.
    core_cli: The core plugin's CLI file; required unless the run is dry.
    dry_run: Report without writing.

  Returns:
    The result of `plan` for the tracked settings as they were, plus the same three lists for the local overlay under
    `local_experts_renamed`, `local_tiers_renamed` and `local_tiers_dropped`, and for the user-scope settings under
    `home_experts_renamed`, `home_tiers_renamed` and `home_tiers_dropped`; an absent layer reports empty lists.

  Raises:
    RuntimeError: When a write is due and no usable core CLI is given, or a core call fails.
    ValueError: When the tracked settings file, the local overlay or the user-scope settings file does not parse as a
      JSON object.
  """

  # Contract:
  # Only the `agent` of an expert naming the old agent and a tier keyed by the old dispatch string change, in any of
  # the three settings layers; every other key, value and entry stays as read.

  # Contract:
  # The tracked settings file, the local overlay and the user-scope settings file are each read and written alone.
  # What is found in one layer is written to that layer only, and a write to one layer never touches another.

  # Contract:
  # An absent local overlay and an absent user-scope settings file MUST never be created.

  # Contract:
  # When the repository root is the home directory, the tracked file and the user-scope file are one file. It is
  # handled once, as the tracked layer, and never reported or written a second time as the user-scope layer.

  # Contract:
  # A dry run MUST write nothing.

  # Contract:
  # A second run over the output of a first run MUST find nothing to rename in any layer.

  # each layer is read alone, so the overlay is never folded into the tracked file or the other way round
  tracked = _read_layer(repo / _SETTINGS_REL)
  local = _read_layer(repo / _LOCAL_REL)

  # the user-scope file is a layer of its own, unless the repository root is the home directory and the tracked
  # file already is that file
  home_path = Path.home() / _SETTINGS_REL
  home = None if home_path.resolve() == (repo / _SETTINGS_REL).resolve() else _read_layer(home_path)

  # what the rename changes in each layer; the overlay's and the user-scope file's lists carry their prefixes
  tracked_changes = plan(tracked or {})
  local_changes = plan(local or {})
  home_changes = plan(home or {})
  result = { **tracked_changes, **{ _LOCAL_PREFIX + key: items for key, items in local_changes.items() },
             **{ _HOME_PREFIX + key: items for key, items in home_changes.items() } }

  # a dry run, or a run with nothing to rename in any of the three layers, returns the report as it stands
  if dry_run or not any(result.values()):
    return result

  # guard: a write needs the core CLI
  if core_cli is None or not core_cli.is_file():
    raise RuntimeError(f"core CLI not usable: {core_cli}")

  # each layer with work is written through its own scope; an absent layer has none and is never created
  if tracked is not None and any(tracked_changes.values()):
    _apply(core_cli, repo, scope = _TRACKED_SCOPE, settings = tracked, changes = tracked_changes)
  if local is not None and any(local_changes.values()):
    _apply(core_cli, repo, scope = _LOCAL_SCOPE, settings = local, changes = local_changes)
  if home is not None and any(home_changes.values()):
    _apply(core_cli, repo, scope = _TRACKED_SCOPE, settings = home, changes = home_changes, home = True)
  return result


def main(argv: list[str]) -> int:
  """
  Run the `rename-implementer-agent` command and print its result as one JSON line.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when any of the three settings layers has work left, 1 when none
      does.
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
  # With `--check` the verb MUST write nothing and exit 0 when any of the three settings layers, the tracked file,
  # the local overlay or the user-scope file, still has an agent or a tier to rename, 1 when none does.

  # Contract:
  # Any failure MUST exit 2 under every flag, so a migration step's `applies_when` predicate never reads a failure as
  # an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-experts rename-implementer-agent")
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
    sys.stderr.write(f"rename-implementer-agent: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result, ensure_ascii = False))

  # only a check answers through its exit code
  if args.check:
    return 0 if any(result.values()) else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
