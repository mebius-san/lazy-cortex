#!/usr/bin/env python3

"""
Agent discovery behind the `lazy-core.agent-models` wizard.

Backs the `agent-discover` verb: it answers which agents a repo can dispatch, which of them no `agent_models`
section configures yet, and which configured plugin keys point at an agent or plugin that no longer exists.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from enum import StrEnum
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import lazy_setup  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import plugin_locator  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The subagents the harness always offers.
BUILTINS = ( "Explore", "Plan", "general-purpose", "statusline-setup" )

# The groups the built-ins, the user's own agents and the repo's own agents are configured under.
_GROUP_BUILTIN = "_builtin"
_GROUP_USER = "_user"
_GROUP_PROJECT = "_project"

# Where agents, settings and the marketplace catalogs live under a repo or a home directory.
_AGENTS_REL = Path(".claude") / "agents"
_PLUGIN_AGENTS_DIR = "agents"
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_MARKETPLACES_REL = Path(".claude") / "plugins" / "marketplaces"
_CATALOG_REL = Path(".claude-plugin") / "marketplace.json"

# The filename shape of an agent, and the separators of a dispatch string, a registry key and a plugin group.
_AGENT_PATTERN = "*.md"
_AGENT_SUFFIX = ".md"
_DISPATCH_SEP = ":"
_GROUP_SEP = "-"

# The settings section compared against, the two scopes a configured key is reported under, and the catalog fields.
_SECTION = "agent_models"
_SCOPE_USER = "user"
_SCOPE_PROJECT = "project"
_CATALOG_PLUGINS = "plugins"
_CATALOG_NAME = "name"
_ROOT_KEY = "root"
_ENCODING = "utf-8"

# The answer's wire-shape keys and the two staleness proofs.
_AGENTS_KEY = "agents"
_MISSING_KEY = "missing"
_STALE_KEY = "stale"
_DISPATCH_KEY = "dispatch"
_GROUP_KEY = "group"
_PLUGIN_KEY = "plugin"
_SOURCE_KEY = "source"
_SCOPE_KEY = "scope"
_PROOF_KEY = "proof"


# ----------------------------------------------------------------------------------------
class StaleProof(StrEnum):
  """
  The proof that retires a configured agent tier, as the answer prints it.

  Attributes:
    AGENT_DELETED: The plugin is still here and no longer ships the agent.
    PLUGIN_RETIRED: The plugin is installed neither for this repo nor for the user, and gone from every marketplace.
  """

  # The plugin is still here and no longer ships the agent.
  AGENT_DELETED = "agent-deleted"
  # The plugin is installed neither for this repo nor for the user, and gone from every marketplace.
  PLUGIN_RETIRED = "plugin-retired"


def _find_all_stems(directory: Path) -> list[str]:
  """
  List the agent stems of the markdown files directly in one directory.

  Args:
    directory: The agents directory; absent yields nothing.

  Returns:
    The stems, sorted.
  """
  # guard: an absent directory holds no agent
  if not directory.is_dir():
    return []
  return sorted(
      name[:-len(_AGENT_SUFFIX)] for name in os.listdir(directory)
      if fnmatch.fnmatch(name, _AGENT_PATTERN) and (directory / name).is_file()
  )


def _build_agent(dispatch: str, group: str, plugin: str | None, source: Path | None) -> dict:
  """
  Shape one discovered agent as the answer lists it.

  Args:
    dispatch: The dispatch string.
    group: The `agent_models` group it is configured under.
    plugin: The plugin shipping it, or None.
    source: Its agent file, or None for a built-in.

  Returns:
    The agent record.
  """
  return { _DISPATCH_KEY: dispatch, _GROUP_KEY: group, _PLUGIN_KEY: plugin,
           _SOURCE_KEY: str(source) if source is not None else None }


def plugin_group(name: str) -> str:
  """
  Name the `agent_models` group a plugin's agents are configured under.

  Args:
    name: Bare plugin name.

  Returns:
    The name up to its first hyphen, or the whole name when it has none.
  """

  # Domain(runtime.agent-models):
  # # How a plugin's agents are named and grouped for model tiers
  # A plugin's agent is dispatched by the plugin name, a colon and the agent name. Model tiers are configured per
  # plugin family, not per plugin: the family is the part of the plugin name before its first hyphen, so plugins
  # sharing that prefix share one configuration group, and a plugin whose name has no hyphen is its own family.

  # the group key the wizard files every agent of this plugin family under
  return name.split(_GROUP_SEP, 1)[0]


def read_catalog_names(home: Path) -> set[str] | None:
  """
  Read the plugin names every registered marketplace catalog lists.

  Args:
    home: Home directory holding the marketplaces.

  Returns:
    The listed plugin names, or None when a registered marketplace's catalog is missing or unreadable.
  """
  base = home / _MARKETPLACES_REL

  # guard: no marketplace registered
  if not base.is_dir():
    return set()

  # every marketplace keeps its catalog at the same place under its own directory
  names: set[str] = set()
  for marketplace in os.listdir(base):
    try:
      catalog = json.loads((base / marketplace / _CATALOG_REL).read_text(encoding = _ENCODING))
    except (OSError, ValueError):
      return None

    # guard: a catalog that is not an object lists nothing anyone can rely on
    if not isinstance(catalog, dict):
      return None
    entries = catalog.get(_CATALOG_PLUGINS)
    names.update(
        str(entry[_CATALOG_NAME]) for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, dict) and _CATALOG_NAME in entry
    )
  return names


def _plugin_root(name: str, repo: Path, home: Path) -> Path | None:
  """
  Resolve the source root of a plugin.

  An installed copy counts only when it was made for the repo's main checkout or for the whole user.

  Args:
    name: Bare plugin name.
    repo: The repo root.
    home: The home directory whose plugin registry resolves the installed copy.

  Returns:
    The plugin root, or None when no stage resolves it.
  """
  # a plugin no stage resolves has no sources to read agents from
  try:
    return Path(lazy_setup.plugin_root(name, repo, home)[_ROOT_KEY])
  except plugin_locator.PluginNotFoundError:
    return None


def find_all_agents(repo: Path, home: Path, *, settings_root: Path | None = None) -> list[dict]:
  """
  Enumerate every agent this repo can dispatch.

  Args:
    repo: The repo root.
    home: The home directory.
    settings_root: Directory whose `.claude/settings.json` and `.claude/settings.local.json` say which plugins are
      enabled; None for the repo root.

  Returns:
    One record per dispatch string, sorted by it.
  """

  # Domain(runtime.agent-models):
  # # Which agents a repo can assign a model tier
  # Agents come from four sources: the subagents the harness always offers, the user's own agents, the repo's own
  # agents, and the agents shipped by plugins. A plugin's agents are offered only when the plugin both reaches this
  # repo (installed for the user, installed into this project, or authored in it) and is enabled in this repo. A
  # plugin installed only into some other project is invisible to this repo, and one installed but switched off here
  # ships nothing to dispatch here, so no tier is asked for its agents. Where one dispatch name turns up twice, the
  # first discovery stands.

  # the harness's own subagents are always offered
  found = [ _build_agent(name, _GROUP_BUILTIN, None, None) for name in BUILTINS ]

  # the user's own agents, then the repo's
  for base, group in ( (home, _GROUP_USER), (repo, _GROUP_PROJECT) ):
    directory = base / _AGENTS_REL
    found.extend(
        _build_agent(stem, group, None, directory / f"{stem}{_AGENT_SUFFIX}") for stem in _find_all_stems(directory))

  # the agents of every plugin installed for this repo or the user, or authored by it, and enabled here
  installed = plugin_locator.installed_plugin_roots(repo, home)
  authored = lazy_setup.find_dev_plugins(repo)
  enabled = lazy_setup.read_enabled_plugins(settings_root or repo)
  for name in sorted(set(installed) | set(authored)):
    root = _plugin_root(name, repo, home)

    # guard: a plugin this repo does not enable, or whose sources resolve nowhere, ships nothing here
    if name not in enabled or root is None:
      continue
    directory = root / _PLUGIN_AGENTS_DIR
    found.extend(
        _build_agent(f"{name}{_DISPATCH_SEP}{stem}", plugin_group(name), name, directory / f"{stem}{_AGENT_SUFFIX}")
        for stem in _find_all_stems(directory)
    )

  # one record per dispatch string, the first discovery winning
  unique: dict[str, dict] = {}
  for agent in found:
    unique.setdefault(agent[_DISPATCH_KEY], agent)
  return [ unique[key] for key in sorted(unique) ]


def read_configured(base: Path) -> dict[str, str]:
  """
  Read the dispatch strings one `agent_models` section configures.

  Args:
    base: Repo root or home directory holding `.claude/lazy.settings.json`.

  Returns:
    Dispatch string to the group it is configured under.

  Raises:
    ValueError: If the settings file is not valid JSON or not a JSON object.
    OSError: If the settings file exists but cannot be opened.
  """
  path = base / _SETTINGS_REL

  # guard: no settings file configures nothing
  if not path.is_file():
    return {}
  section = load_section(path, _SECTION)

  # only an object-valued key is a group; the version stamp and any scalar are not
  return {
      dispatch: group
      for group, entries in section.items() if isinstance(entries, dict)
      for dispatch in entries
  }


def find_all_stale(repo: Path, home: Path) -> list[dict]:
  """
  List the configured plugin keys whose agent or plugin no longer exists.

  Args:
    repo: The repo root, whose `.claude/lazy.settings.json` holds the project-scope keys.
    home: The home directory.

  Returns:
    One record per stale key, sorted by scope and dispatch string.

  Raises:
    ValueError: If a settings file is not valid JSON or not a JSON object.
    OSError: If a settings file exists but cannot be opened.
  """

  # Domain(runtime.agent-models):
  # # When a configured agent tier is provably dead
  # A model tier configured for a plugin's agent is retired only on proof. Either the plugin is still installed for
  # this repo or the user, or authored here, and no longer ships an agent of that name, or the plugin is installed
  # neither for this repo nor for the user and is gone from every marketplace, so it can never be installed again.
  # A plugin that was merely uninstalled still stands in its marketplace, and its tiers are left alone; a key that
  # names no plugin can never be proven absent.
  # A marketplace whose list cannot be read could still be offering the plugin, so while any list is unreadable no
  # plugin counts as gone from every marketplace.

  # the installs this repo may use, the authored plugins and the marketplace catalogs are what the proofs rest on
  installed = plugin_locator.installed_plugin_roots(repo, home)
  authored = lazy_setup.find_dev_plugins(repo)
  catalog = read_catalog_names(home)

  # every configured plugin key of both scopes is checked against the two proofs
  stale: list[dict] = []
  for scope, base in ( (_SCOPE_PROJECT, repo), (_SCOPE_USER, home) ):
    for dispatch, group in read_configured(base).items():
      plugin, sep, stem = dispatch.partition(_DISPATCH_SEP)

      # guard: a key that is not plugin-namespaced can never be proven absent
      if not sep:
        continue

      # the two proofs, the deleted agent first
      proof: StaleProof | None = None
      if plugin in installed or plugin in authored:
        root = _plugin_root(plugin, repo, home)
        if root is not None and not (root / _PLUGIN_AGENTS_DIR / f"{stem}{_AGENT_SUFFIX}").is_file():
          proof = StaleProof.AGENT_DELETED
      elif catalog is not None and plugin not in catalog:
        proof = StaleProof.PLUGIN_RETIRED
      if proof is not None:
        stale.append({ _SCOPE_KEY: scope, _GROUP_KEY: group, _DISPATCH_KEY: dispatch, _PROOF_KEY: proof })
  return sorted(stale, key = lambda entry: ( entry[_SCOPE_KEY], entry[_DISPATCH_KEY] ))


def discover(repo: Path, home: Path, *, settings_root: Path | None = None) -> dict:
  """
  Build the whole answer of the `agent-discover` verb.

  Args:
    repo: The repo root.
    home: The home directory.
    settings_root: Directory whose `.claude/settings.json` and `.claude/settings.local.json` say which plugins are
      enabled; None for the repo root. The project-scope `agent_models` section is read at the repo root, where the
      daemon reads it.

  Returns:
    The discovered `agents`, the `missing` dispatch strings no section configures, and the `stale` keys.

  Raises:
    ValueError: If a settings file is not valid JSON or not a JSON object.
    OSError: If a settings file exists but cannot be opened.
  """
  agents = find_all_agents(repo, home, settings_root = settings_root)
  configured = { **read_configured(home), **read_configured(repo) }
  return {
      _AGENTS_KEY: agents,
      _MISSING_KEY: sorted(agent[_DISPATCH_KEY] for agent in agents if agent[_DISPATCH_KEY] not in configured),
      _STALE_KEY: find_all_stale(repo, home),
  }


def cmd_agent_discover(argv: list[str]) -> int:
  """
  Run the `agent-discover` verb and print its answer as JSON.

  Args:
    argv: Arguments after the subcommand: an optional `--cwd <repo>` and `--home <dir>`.

  Returns:
    0 with the answer on stdout, 2 when a settings file cannot be opened or is not a valid JSON object (the reason on
    stderr).
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-core agent-discover")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--cwd", default = None)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--home", default = None)
  args = parser.parse_args(argv)
  home = Path(args.home).resolve() if args.home else Path.home()

  # a settings file that cannot be read is refused, never read as configuring nothing
  try:
    answer = discover(plugin_locator.query_repo_root(args.cwd), home,
                      settings_root = plugin_locator.query_settings_root(args.cwd))
  except (ValueError, OSError) as error:
    sys.stderr.write(f"agent-discover: {error}\n")
    return 2
  print(json.dumps(answer))
  return 0


if __name__ == "__main__":
  sys.exit(cmd_agent_discover(sys.argv[1:]))
