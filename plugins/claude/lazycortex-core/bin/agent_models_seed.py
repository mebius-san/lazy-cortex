"""
Seed a plugin's shipped agent tiers from the core tier table into a scope's `lazy.settings.json`.

Backs the `agent-models-seed` verb of the `lazycortex-core` CLI.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import lazy_setup  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import settings_cli  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import resolve_agent_model_tier  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_git_toplevel  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The settings section the seed lives in, and the domain group inside it the seed owns.
_SECTION = "agent_models"
_GROUP = "lazycortex"
# The shipped tier table, relative to the core plugin's root.
_SOT_REL = Path("skills") / "lazy-core.agent-models" / "default-tiers.json"
_CORE_PLUGIN = "lazycortex-core"
# The SOT's map of dispatch strings to tiers.
_SOT_DEFAULTS = "defaults"
# The two fields of a seed object.
_TIER = "tier"
_SEEDED_FROM = "seeded_from"
# The two install scopes.
_SCOPE_PROJECT = "project"
_SCOPE_USER = "user"



# ----------------------------------------------------------------------------------------
class SeedState(StrEnum):
  """
  Per-key verdict of an agent-model seed run.

  Describes what a seed run decided for one dispatch string and is reported per entry in the result.

  Attributes:
    ADDED: The key was absent and a seed object was written.
    UNCHANGED: The seed object already matched the shipped tier.
    REFRESHED: An untouched seed object followed the shipped tier to its new value.
    KEPT_LOCAL: The operator's own value was left as it is.
  """

  # The key was absent and a seed object was written.
  ADDED = "added"
  # The seed object already matched the shipped tier.
  UNCHANGED = "unchanged"
  # An untouched seed object followed the shipped tier to its new value.
  REFRESHED = "refreshed"
  # The operator's own value was left as it is.
  KEPT_LOCAL = "kept-local"



# ----------------------------------------------------------------------------------------
class SeedOutcomeKind(StrEnum):
  """
  Run-level outcome words of an agent-model seed run.

  Attributes:
    UNCHANGED: Nothing was written.
    NO_ENTRIES: The shipped tier table lists no dispatch string under the prefix.
    SEEDED_PREFIX: Prefix of the outcome word that names how many entries were written.
  """

  # Nothing was written.
  UNCHANGED = "unchanged"
  # The SOT lists no dispatch string under the prefix.
  NO_ENTRIES = "no-entries"
  # Prefix of the outcome naming how many entries were written.
  SEEDED_PREFIX = "seeded-"



# ----------------------------------------------------------------------------------------
class SeedReasonKind(StrEnum):
  """
  Closed set of refusal words a seed run reports.

  Attributes:
    SOT_MISSING: The shipped tier table could not be found.
    MISSING_PREFIX: No dispatch-string prefix was given.
    MISSING_SCOPE: The scope is neither `project` nor `user`.
    SETTINGS_UNPARSEABLE: The settings file exists but does not parse as a JSON object.
  """

  # The shipped tier table could not be found.
  SOT_MISSING = "sot-missing"
  # No dispatch-string prefix was given.
  MISSING_PREFIX = "missing-prefix"
  # The scope is neither `project` nor `user`.
  MISSING_SCOPE = "missing-scope"
  # The settings file exists but does not parse as a JSON object.
  SETTINGS_UNPARSEABLE = "settings-unparseable"



# ----------------------------------------------------------------------------------------
class SeedError(ValueError):
  """
  Refusal of an agent-model seed run.

  Raised when the run cannot proceed and the caller is told why.

  Attributes:
    reason: The closed-set refusal word the caller branches on.
    message: The sentence shown to the operator, empty when the reason says it all.
  """

  def __init__(self, reason: str, message: str = "") -> None:
    """
    Build a refusal carrying its closed-set reason and an optional sentence.

    Args:
      reason: Closed-set refusal word.
      message: Sentence explaining the refusal.
    """
    super().__init__(f"{reason}: {message}" if message else reason)

    # the closed-set refusal word the caller branches on, and the sentence it shows
    self.reason = reason
    self.message = message



# ----------------------------------------------------------------------------------------
@dataclass
class SeedResult:
  """
  Report of one agent-model seed run.

  Attributes:
    outcome: The run's outcome word.
    sot: The tier table the run read.
    entries: One record per dispatch string in scope, naming its tier, verdict and previous value.
  """

  # The run's outcome word.
  outcome: str
  # The tier table the run read.
  sot: str
  # One line per dispatch string in scope.
  entries: list[dict] = field(default_factory = list)


def _sot_missing_message(prefix: str) -> str:
  """
  Compose the sentence shown when the shipped tier table cannot be read.

  Args:
    prefix: Plugin prefix the run was seeding.

  Returns:
    The operator-facing sentence, the same whether the core plugin or its tier table is missing.
  """
  return f"{_CORE_PLUGIN} not installed; install it before seeding {prefix} tiers"


def _resolve_sot_path(root: Path, prefix: str) -> Path:
  """
  Resolve the shipped tier table of the core plugin.

  Args:
    root: Git toplevel of the repository the run works in.
    prefix: Plugin prefix the run is seeding, named in the refusal.

  Returns:
    Path of the tier table.

  Raises:
    SeedError: If the core plugin is not installed.
  """
  # the tier table ships with the core plugin, found the same way the `plugin-root` verb finds it
  report = lazy_setup.plugin_root(_CORE_PLUGIN, root, Path.home())

  # guard: an unresolved core plugin has no tier table to read
  if report is None:
    raise SeedError(SeedReasonKind.SOT_MISSING, _sot_missing_message(prefix))
  return Path(report["root"]) / _SOT_REL


def _read_sot(path: Path, prefix: str) -> dict[str, str]:
  """
  Read the dispatch strings the shipped tier table lists under a prefix.

  Args:
    path: Tier table to read.
    prefix: Plugin prefix a dispatch string must open with.

  Returns:
    Mapping of each matching dispatch string to its shipped tier.

  Raises:
    SeedError: If the tier table is not on disk.
  """
  # guard: a tier table that is not on disk is never replaced by a hardcoded fallback
  if not path.is_file():
    raise SeedError(SeedReasonKind.SOT_MISSING, _sot_missing_message(prefix))

  # the shipped map of dispatch strings to tiers
  defaults = json.loads(path.read_text(encoding = "utf-8")).get(_SOT_DEFAULTS, {})

  # the seed set is every dispatch string the plugin's prefix opens, verbatim
  return { key: tier for key, tier in defaults.items() if key.startswith(f"{prefix}:") }


def _read_group(settings: Path) -> dict:
  """
  Read the seed-owned group of the agent-model section from a settings file.

  Args:
    settings: Settings file to read.

  Returns:
    Mapping of dispatch strings to their recorded values, empty when the file or the group is absent.

  Raises:
    SeedError: If the file exists but does not parse as a JSON object.
  """
  # guard: an absent file is an empty one, and the write creates it
  if not settings.is_file():
    return {}

  # a file that does not parse is never treated as empty — that would erase its other sections
  try:
    data = json.loads(settings.read_text(encoding = "utf-8"))
  except json.JSONDecodeError as error:
    raise SeedError(SeedReasonKind.SETTINGS_UNPARSEABLE, f"{settings}: {error}") from error

  # guard: a file that parses but is not an object holds no sections and is refused, never treated as empty
  if not isinstance(data, dict):
    raise SeedError(SeedReasonKind.SETTINGS_UNPARSEABLE, f"{settings}: not a JSON object")

  # the domain group the seed owns, empty when not yet created
  return (data.get(_SECTION) or {}).get(_GROUP) or {}


def _judge(recorded: object, tier: str) -> tuple[SeedState, object]:
  """
  Decide what a seed run does with one recorded value.

  Args:
    recorded: The value recorded for the dispatch string, or `None` when absent.
    tier: The shipped tier for the dispatch string.

  Returns:
    The verdict and the tier it replaces or preserves, `None` when there is none.
  """

  # Domain(install.reconciliation):
  # # A seed stays refreshable until the operator touches it
  # Every value the installer writes records the shipped default it came from, so a later run can
  # tell an untouched seed from the operator's decision. An absent value gets the shipped default.
  # An untouched seed follows the shipped default when it moves, because a stale shipped value is
  # nobody's choice. A seed whose value no longer matches the default it recorded, and a value
  # written without any record of its origin, are the operator's pins and are never rewritten.

  # an absent key takes the shipped tier
  if recorded is None:
    return SeedState.ADDED, None

  # a bare string, or anything that is not a seed object, is the operator's pin
  if not isinstance(recorded, dict) or recorded.get(_TIER) != recorded.get(_SEEDED_FROM):
    return SeedState.KEPT_LOCAL, resolve_agent_model_tier(recorded)

  # an untouched seed is current or follows the shipped tier
  if recorded.get(_TIER) == tier:
    return SeedState.UNCHANGED, None
  return SeedState.REFRESHED, recorded.get(_TIER)


def seed(prefix: str, *, scope: str, cwd: Path | None = None) -> SeedResult:
  """
  Seed the shipped tiers of a plugin's agents into the settings file of a scope.

  An absent key gets the shipped tier, an untouched seed follows the shipped tier when it moves, and a value the
  operator set is never rewritten.

  Guarantees:
    - A value the operator pinned is never rewritten; it is pinned when it is not a seed object or no longer matches
      the tier it recorded.
    - Keys outside the given prefix are never touched.

  Args:
    prefix: Plugin prefix the dispatch strings must open with.
    scope: Install scope, `project` or `user`.
    cwd: Conventional repository root, or `None` for `LAZY_REPO_ROOT` and then the process working directory; the
      run widens it to its git toplevel, so a run from a subdirectory writes the checkout's settings file.

  Returns:
    The run's outcome word, the tier table read and one record per dispatch string in scope.

  Raises:
    SeedError: If the prefix or scope is invalid, the tier table is missing, or the settings file is unparseable.
  """

  # Contract:
  # A value the operator pinned is NEVER rewritten, whatever the shipped tier now says.
  # A value counts as pinned when it is not a seed object or no longer matches the tier it recorded.

  # Contract:
  # Keys outside the given prefix are NEVER touched.

  # guard: an empty prefix is refused before anything is read
  if not prefix:
    raise SeedError(SeedReasonKind.MISSING_PREFIX, "a dispatch-string prefix is required")

  # guard: a scope other than project or user is refused before anything is read
  if scope not in ( _SCOPE_PROJECT, _SCOPE_USER ):
    raise SeedError(SeedReasonKind.MISSING_SCOPE, f"scope must be {_SCOPE_PROJECT} or {_SCOPE_USER}, got {scope!r}")

  # the tier table and the target file are fixed before any value is compared; a run from a subdirectory
  # works on the checkout's own root
  root = resolve_git_toplevel(cwd)
  sot = _resolve_sot_path(root, prefix)
  seed_set = _read_sot(sot, prefix)
  home = scope == _SCOPE_USER
  settings = settings_cli.resolve_settings_path(root, home = home)

  # guard: a prefix the table does not list is reported, and the file is not touched
  if not seed_set:
    return SeedResult(outcome = SeedOutcomeKind.NO_ENTRIES, sot = str(sot))

  # each dispatch string is judged on its own against the recorded group, and only a changed key is written
  group = _read_group(settings)
  entries = []
  written = 0
  for dispatch, tier in seed_set.items():
    state, previous = _judge(group.get(dispatch), tier)
    if state in ( SeedState.ADDED, SeedState.REFRESHED ):
      settings_cli.settings_set(
        _SECTION, { _TIER: tier, _SEEDED_FROM: tier }, cwd = root, home = home, key = f"{_GROUP}/{dispatch}",
      )
      written += 1
    entries.append({ "dispatch": dispatch, "tier": tier, "state": str(state), "previous": previous })

  # the outcome counts what was written, or says nothing was
  outcome = f"{SeedOutcomeKind.SEEDED_PREFIX}{written}" if written else SeedOutcomeKind.UNCHANGED
  return SeedResult(outcome = str(outcome), sot = str(sot), entries = entries)


def cmd_agent_models_seed(argv: list[str]) -> int:
  """
  Run the `agent-models-seed` subcommand: seed the shipped agent tiers and print the result as JSON.

  Args:
    argv: Argument vector after the subcommand name (`--prefix`, `--scope`, optional `--cwd`).

  Returns:
    Process exit code: `0` on success, `1` when the run is refused.
  """
  # the prefix and scope are required, an absent one refused like an empty one; the repo root follows the
  # dispatcher convention
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core agent-models-seed")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--prefix", default = "")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--scope", default = "")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # a refusal is one JSON line naming its reason, never a traceback
  try:
    result = seed(args.prefix, scope = args.scope, cwd = Path(args.cwd) if args.cwd else None)
  except SeedError as error:
    print(json.dumps({ "outcome": error.reason, "message": error.message }))
    return 1

  # the result is printed whole for the caller's report
  print(json.dumps(asdict(result)))
  return 0
