#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: Claude Code's config-dir override, an external environment name
_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
# waiver: the runtime daemon's plugin-dir export (dev.plugin-boundaries § 1c), an environment name
_PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
# waiver: the runtime dispatcher's repo-root export, an environment name
_REPO_ROOT_ENV = "LAZY_REPO_ROOT"
# waiver: Claude Code's config directory under a home directory, an external filesystem location
_CONFIG_DIR_NAME = ".claude"
# waiver: a project's tracked plugin settings file under its root, an external filesystem location
_SETTINGS_REL = Path(_CONFIG_DIR_NAME) / "lazy.settings.json"
# waiver: the install registry under Claude Code's config directory, an external filesystem location
_REGISTRY_REL = Path("plugins") / "installed_plugins.json"
# waiver: the repo layout of a plugin-authoring checkout and a plugin's manifest, not reusable domain keys
_DEV_ROOT, _MANIFEST = Path("plugins") / "claude", Path(".claude-plugin") / "plugin.json"
# waiver: external Claude Code registry field names, not internal keys
_K_PLUGINS, _K_INSTALL, _K_VERSION = "plugins", "installPath", "version"
# waiver: external Claude Code registry field names, not internal keys
_K_SCOPE, _K_PROJECT = "scope", "projectPath"
# The registry scopes that reach every repo of the user, and the ones bound to one project's checkout
_SCOPES_USER = frozenset({ "user", "managed" })
_SCOPES_PROJECT = frozenset({ "project", "local" })
# The separator between a plugin name and its marketplace in a registry key
_MARKETPLACE_SEP = "@"
# waiver: stage names of a resolved plugin root, read by the callers' reports
STAGE_ENV, STAGE_SIBLING, STAGE_REPO, STAGE_CACHE = "env", "sibling", "repo", "cache"
# The line prefix `git worktree list --porcelain` puts before each worktree path
_WORKTREE_PREFIX = "worktree "
# waiver: argparse sub-command names, surface strings rather than domain keys
_VERB_ROOT, _VERB_INSTALLED, _VERB_CHECKOUT, _VERB_TOPLEVEL = "root", "installed", "checkout", "toplevel"
# waiver: argparse sub-command name, a surface string rather than a domain key
_VERB_SETTINGS = "settings-root"
_ENCODING = "utf-8"
# waiver: stdlib decode-error mode that keeps every byte of a path name, not a domain constant
_DECODE_ERRORS = "surrogateescape"


# ----------------------------------------------------------------------------------------
class PluginNotFoundError(LookupError):
  """
  Failure of a plugin lookup in which no stage finds the requested plugin.

  The message names the plugin and every stage searched together with the location each one looked at.

  Attributes:
    name: Plugin name exactly as the caller asked for it, a `@<marketplace>` suffix included.
    searched: One `(stage, location)` pair per stage, in search order.
  """

  def __init__(self, name: str, searched: list[tuple[str, str]]) -> None:
    """
    Record the missing plugin and the stages searched for it.

    Args:
      name: Plugin name exactly as the caller asked for it, a `@<marketplace>` suffix included.
      searched: One `(stage, location)` pair per stage, in search order.
    """
    # the message is the whole report a caller prints
    super().__init__(
        f"plugin {name} not found: searched " + "; ".join(f"{stage} {where}" for stage, where in searched))

    # the parts, for a caller that formats its own report
    self.name: str = name
    self.searched: list[tuple[str, str]] = searched


def _run_git(start: Path, *args: str, errors: str) -> str | None:
  """
  Run one git command in a directory and return its first output line.

  Args:
    start: Directory the command runs in.
    *args: The git arguments.
    errors: Decode-error mode applied to the captured bytes.

  Returns:
    The first line of standard output, or None when git is missing, fails, or prints nothing.
  """
  # guard: a missing git binary means "not in git"
  try:
    done = subprocess.run([ "git", "-C", str(start), *args ], capture_output = True, check = False)
  except OSError:
    return None

  # guard: a failed command says nothing about the checkout
  if done.returncode != 0:
    return None

  # the first output line, decoded so no byte of a path name is lost; only a line feed ends a line, since a path
  # name may hold a carriage return
  lines = done.stdout.decode(_ENCODING, errors = errors).split("\n")
  return lines[0] if lines and lines[0] else None


def query_main_checkout(start: Path) -> Path:
  """
  Return the main checkout of the repository a directory belongs to.

  Args:
    start: Any directory inside the repository: its root, a subdirectory, or a linked worktree.

  Returns:
    The main checkout's root; the resolved `start` itself when it is not inside a git repository.
  """

  # Domain(plugin.boundaries):
  # # One repository, wherever the command runs from
  # A repository is one project whether a command runs at its root, in a subdirectory, or in a linked git worktree
  # a background job works in, and whatever branch is checked out there. Every such place answers to the main
  # checkout, the directory the repository was first cloned or created in; that is the path an install made for the
  # project records. Outside any repository the directory stands for itself.

  # the porcelain listing names the main checkout first, whichever worktree asks
  # waiver: git command-line arguments, not reusable domain keys
  first = _run_git(start, "worktree", "list", "--porcelain", errors = _DECODE_ERRORS)
  if first is not None and first.startswith(_WORKTREE_PREFIX):
    return Path(first[len(_WORKTREE_PREFIX):]).resolve()

  # outside git the directory stands for itself
  return start.resolve()


def query_checkout_toplevel(start: Path) -> Path:
  """
  Return the root of the checkout a directory sits in, which is a linked worktree's own root inside one.

  Args:
    start: Any directory inside the checkout.

  Returns:
    The checkout's root; the resolved `start` itself when it is not inside a git repository.
  """
  # the checkout's own root, or the directory itself where git names none
  return find_checkout_toplevel(start) or start.resolve()


def find_checkout_toplevel(start: Path) -> Path | None:
  """
  Return the root of the checkout a directory sits in, which is a linked worktree's own root inside one.

  Guarantees:
    - The answer is the resolved root of the checkout `start` sits in; inside a linked worktree it is that worktree's
      own root, never the main checkout.
    - When git names no checkout the answer is None, never a fallback directory.

  Args:
    start: Any directory inside the checkout.

  Returns:
    The checkout's root, resolved; None when git names none — outside a repository, for a missing directory, or
    without a git binary.
  """

  # Contract:
  # The answer is the resolved root of the checkout the directory sits in; inside a linked worktree it is that
  # worktree's own root, never the main checkout. When git names no checkout the answer is None and NEVER a fallback
  # directory, because callers tell "not in git" from "in git" by that None.

  # git names the toplevel of the current checkout, a worktree's own root included
  # waiver: git command-line arguments, not reusable domain keys
  top = _run_git(start, "rev-parse", "--show-toplevel", errors = _DECODE_ERRORS)
  return Path(top).resolve() if top is not None else None


def find_git_dir(start: Path) -> Path | None:
  """
  Return the git directory of the checkout a directory sits in, which is a linked worktree's own one inside it.

  Guarantees:
    - The answer is the absolute, resolved git directory of the checkout `start` sits in; inside a linked worktree
      it is that worktree's own git directory, never the main checkout's.
    - Outside git the answer is None.

  Args:
    start: Any directory inside the checkout.

  Returns:
    The absolute git directory, resolved; None when git names none — outside a repository, for a missing directory,
    or without a git binary.
  """

  # Contract:
  # The answer is the git directory of the checkout the directory sits in, absolute and resolved; inside a linked
  # worktree it is that worktree's own git directory, never the main checkout's. Outside git the answer is None.

  # git prints the directory relative to the start when it lies below it, so it is anchored there
  # waiver: git command-line arguments, not reusable domain keys
  found = _run_git(start, "rev-parse", "--git-dir", errors = _DECODE_ERRORS)
  return (start / found).resolve() if found is not None else None


def find_git_common_dir(start: Path) -> Path | None:
  """
  Return the git directory every worktree of the repository a directory belongs to shares.

  Guarantees:
    - The answer is the absolute, resolved git directory that every worktree of the repository shares; from a linked
      worktree it is the main checkout's `.git`, never that worktree's own git directory.
    - When git names no such directory the answer is None, never a fallback directory.

  Args:
    start: Any directory inside the repository: its main checkout, a subdirectory, or a linked worktree.

  Returns:
    The repository's shared git directory, absolute and resolved — the main checkout's `.git` from a linked
    worktree too; None when git names none — outside a repository, for a missing directory, or without a git binary.
  """

  # Contract:
  # The answer is the git directory every worktree of the repository shares, absolute and resolved; from a linked
  # worktree it is the main checkout's git directory, never that worktree's own. When git names none the answer is
  # None and NEVER a fallback directory, because callers tell "not in git" from "in git" by that None, key the
  # repository's one staging lock to this directory, and tell a linked worktree by comparing it with the checkout's
  # own git directory.

  # git prints the directory relative to the start when it lies below it, so it is anchored there
  # waiver: git command-line arguments, not reusable domain keys
  found = _run_git(start, "rev-parse", "--git-common-dir", errors = _DECODE_ERRORS)
  return (start / found).resolve() if found is not None else None


def find_nearest_dir(start: Path, rel: str | Path) -> Path | None:
  """
  Return the nearest directory from a start upward that holds a given path, never above the start's checkout root.

  Guarantees:
    - The search starts at `start` itself, or at its directory when `start` is a file, and returns the nearest
      directory that holds `rel`, so a nested subproject's own file wins over one further up.
    - The search never climbs above the root of the checkout `start` sits in, a linked worktree's own root included;
      a file `start` is bounded by the checkout its directory sits in, exactly as a directory is. Outside git it is
      unbounded and climbs to the filesystem root.

  Args:
    start: Directory the search begins at, checked first; a file begins it at the file's directory.
    rel: Path, relative to each candidate directory, whose presence marks the directory searched for.

  Returns:
    The nearest such directory, resolved; None when none holds it. Inside a checkout the search stops at the
    checkout's root, a linked worktree's own root included; outside git it climbs to the filesystem root.
  """

  # Domain(repo.checkout-resolution):
  # # The nearest configuration above a place, within its checkout
  # A file that configures part of a project is looked for at the place a command starts from and then in each
  # directory above it, and the nearest one wins, so a nested subproject keeps its own configuration. The search
  # never leaves the checkout the place belongs to: a configuration above a repository, or above a linked worktree's
  # own root, belongs to something else. Outside any repository nothing bounds the search.

  # Contract:
  # The search starts at the given directory itself, or at the file's own directory when the start is a file, and
  # answers the nearest directory that holds the given path, so a nested subproject's own file always wins over one
  # further up.

  # Contract:
  # The search MUST never climb above the root of the checkout the start sits in, a linked worktree's own root
  # included; a file start is bounded by the checkout its directory sits in, exactly as a directory start is. Outside
  # git it is unbounded and climbs to the filesystem root.

  # a file starts the search at its own directory, which is also where git is asked for the checkout
  here = start.resolve()
  here = here.parent if here.is_file() else here
  top = find_checkout_toplevel(here)

  # the candidates, nearest first, ending at the checkout root when there is one
  for candidate in [ here, *here.parents ]:
    if (candidate / rel).exists():
      return candidate

    # the checkout root is the last candidate; nothing above it belongs to this checkout
    if candidate == top:
      return None
  return None


def query_repo_root(start: Path | str | None = None) -> Path:
  """
  Return the root of the repository checkout a command works in.

  Guarantees:
    - The directory the command works in is `start` when given, else `$LAZY_REPO_ROOT`, else the process working
      directory; an empty value counts as not given.
    - The answer is the root of the checkout that directory sits in, whatever branch is checked out: a linked
      worktree's own root inside one, never the main checkout; outside git, the directory itself, resolved.

  Args:
    start: Directory the command was pointed at, or None to take the dispatcher's environment, then the working
      directory.

  Returns:
    The checkout's root.
  """

  # Domain(repo.checkout-resolution):
  # # The repository a command works in
  # A command belongs to exactly one repository checkout, however it was started: at the root, in a subdirectory,
  # in a linked worktree, or on any branch. Where it works is decided in a fixed order of precedence: the place it
  # was explicitly pointed at, else the repository the runtime assigned to its processes, else the place it runs in.
  # An empty answer at one step counts as no answer and passes the decision to the next. Whichever place wins, the
  # command works in the root of the checkout that place sits in. A linked worktree is a checkout of its own, so a
  # background job reads and writes its own worktree and never the main checkout, which every other worktree of the
  # repository shares. Outside any repository there is no checkout, and the place itself is the root.

  # Contract:
  # The directory a command works in is the explicit argument when given, else `LAZY_REPO_ROOT`, else the process
  # working directory; an empty value counts as not given.

  # Contract:
  # The answer MUST be the root of the checkout that directory sits in, whatever branch is checked out: inside a
  # linked worktree it is that worktree's own root, never the main checkout; outside git it is the directory itself,
  # resolved.

  # the start directory: the explicit one, then the dispatcher's environment, then the working directory
  chosen = str(start) if start is not None else ""
  return query_checkout_toplevel(Path(chosen or os.environ.get(_REPO_ROOT_ENV) or os.getcwd()))


def query_settings_root(start: Path | str | None = None) -> Path:
  """
  Return the directory whose `.claude/lazy.settings.json` configures the place a command works in.

  Guarantees:
    - The place the command works in is `start` when given, else `$LAZY_REPO_ROOT`, else the process working
      directory; an empty value counts as not given.
    - The answer is the nearest directory, from that place upward, holding `.claude/lazy.settings.json`, and the
      search never goes above the root of the checkout the place sits in, a linked worktree's own root included,
      so a nested project with its own settings keeps them. Outside git nothing is searched: the answer is the
      place itself, resolved, even when a directory above it holds a settings file.
    - When no directory holds the settings file, the answer is the root of the checkout the place sits in: a linked
      worktree's own root, never the main checkout; outside git, the place itself, resolved. It equals what
      `query_repo_root` answers for the same start.

  Args:
    start: Directory the command was pointed at, or None to take the dispatcher's environment, then the working
      directory.

  Returns:
    The nearest directory holding the settings file, from the start upward within its checkout; the checkout's
    root when none holds it.
  """

  # Domain(repo.checkout-resolution):
  # # The settings a command reads
  # A project's plugin settings come from the nearest settings file, looked for from the place a command starts and
  # then in each directory above it. That place is chosen in the same order of precedence as the repository the command
  # works in: the place it was explicitly pointed at, else the repository the runtime assigned to its processes, else
  # the place it runs in. The search never goes above the checkout that place sits in, a linked worktree's own root
  # included, so a settings file above the repository, or above a worktree's root, is never read. When no settings
  # file is found on the way, the settings belong to the root of the checkout. A plain subdirectory therefore reads
  # the settings of its checkout's root, while a nested project that keeps a settings file of its own keeps its own
  # settings. Outside any repository no search is made: the place a command starts from is its own settings root,
  # even when a directory above it holds a settings file, because such a directory may be the user's home, whose
  # settings file is the user's own and not a project's.

  # Contract:
  # The directory the search starts from is the explicit argument when given, else `LAZY_REPO_ROOT`, else the process
  # working directory; an empty value counts as not given.

  # Contract:
  # The answer MUST be the nearest directory, from that start upward, that holds `.claude/lazy.settings.json`, and the
  # search MUST never go above the root of the checkout the start sits in, a linked worktree's own root included, so
  # a nested project with its own settings keeps them. Outside git there is no checkout to bound the search, so
  # nothing is searched and the answer MUST be the start itself, resolved, even when a directory above it holds
  # `.claude/lazy.settings.json`: that directory may be the home directory, whose settings file is the user-scope
  # one, and project keys MUST never land there.

  # Contract:
  # When no directory holds the settings file, the answer is the root of the checkout the start sits in: a linked
  # worktree's own root, never the main checkout; outside git, the start itself, resolved. It is exactly what
  # `query_repo_root` answers for the same start.

  # the start directory: the explicit one, then the dispatcher's environment, then the working directory
  chosen = str(start) if start is not None else ""
  here = Path(chosen or os.environ.get(_REPO_ROOT_ENV) or os.getcwd())

  # guard: outside git no checkout bounds the walk, so the place itself holds the settings, never a directory above
  # it such as the home directory, whose settings file is the user's own
  if find_checkout_toplevel(here) is None:
    return here.resolve()

  # the nearest settings file within the checkout wins; without one the checkout's root holds the settings
  return find_nearest_dir(here, _SETTINGS_REL) or query_checkout_toplevel(here)


def registry_path(home: Path | None = None) -> Path:
  """
  Return the location of Claude Code's plugin install registry.

  Args:
    home: Home directory whose `.claude/` holds the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current
      user's `~/.claude/`.

  Returns:
    The registry file path, whether or not the file exists.
  """
  # an explicit home wins, then Claude Code's own config-dir override, then the user's home
  if home is not None:
    return home / _CONFIG_DIR_NAME / _REGISTRY_REL
  override = os.environ.get(_CONFIG_DIR_ENV)
  return (Path(override) if override else Path.home() / _CONFIG_DIR_NAME) / _REGISTRY_REL


def _version_key(record: dict) -> tuple[int, ...]:
  """
  Order a registry record by its recorded version.

  Args:
    record: One registry record.

  Returns:
    The dotted version as integers, component by component; a non-numeric component counts as 0.
  """
  return tuple(int(part) if part.isdigit() else 0 for part in str(record.get(_K_VERSION, "")).split("."))


def read_registry(home: Path | None = None) -> dict | None:
  """
  Read the install registry as the JSON object it holds.

  Args:
    home: Home directory holding the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current user's.

  Returns:
    The registry object, or None when the file is absent, unreadable, not UTF-8 text, not JSON, or not an object.
  """
  # an absent or unreadable registry holds nothing
  try:
    data = json.loads(registry_path(home).read_text(encoding = _ENCODING))
  except (OSError, UnicodeDecodeError, ValueError):
    return None

  # only an object is a registry
  return data if isinstance(data, dict) else None


def _read_records(home: Path | None) -> dict[str, list[dict]]:
  """
  Read the install registry into its records, pooled by bare plugin name.

  Args:
    home: Home directory passed through to `registry_path`.

  Returns:
    Bare plugin name to every record of it; empty when the registry is absent or unreadable.
  """
  # guard: a registry that cannot be read as an object records nothing
  if (data := read_registry(home)) is None:
    return {}

  # newer registries nest the map under `plugins`, older ones are the map itself
  plugins = data.get(_K_PLUGINS, data)

  # one plugin installed from two marketplaces has two keys, so records are pooled by bare name
  pooled: dict[str, list[dict]] = {}
  for key, records in (plugins.items() if isinstance(plugins, dict) else []):
    pooled.setdefault(str(key).split(_MARKETPLACE_SEP, 1)[0], []).extend(
        record for record in (records if isinstance(records, list) else []) if isinstance(record, dict))
  return pooled


def _is_eligible(record: dict, checkout: Path) -> bool:
  """
  Tell whether one registry record is an install this repository may use.

  Args:
    record: One registry record.
    checkout: The resolved main checkout of the asking repository.

  Returns:
    True when the record names an existing absolute install and is made for the user or for this checkout.
  """

  # Domain(plugin.boundaries):
  # # Which installed copy of a plugin a repository uses
  # The install registry is shared by every project on the machine and may list one plugin many times, once per
  # scope, project and version. A repository uses only the installs made for the whole user, or made for this very
  # project, matched against its main checkout, so a subdirectory or a worktree of it counts as the project. An
  # install made for another project is never used, even when it is newer. Among the usable installs the highest
  # version wins, compared number by number. An install whose path is not absolute, or no longer exists, is skipped.
  # Only the registry names an install. The plugin cache, where every version ever installed stays, is never walked
  # for one: its newest directory need not be the version this machine has enabled.

  # the install itself must be a real directory, named absolutely
  install = str(record.get(_K_INSTALL) or "")
  if not install or not Path(install).is_absolute() or not Path(install).is_dir():
    return False

  # a user-wide install reaches every repo, a project one only its own main checkout
  scope = record.get(_K_SCOPE)
  if scope in _SCOPES_USER:
    return True
  project = record.get(_K_PROJECT)
  return scope in _SCOPES_PROJECT and isinstance(project, str) and bool(project) \
      and Path(project).resolve() == checkout


def read_eligible_records(start: Path, home: Path | None = None) -> dict[str, list[dict]]:
  """
  Read the install records the repository a directory belongs to may use, pooled by bare plugin name.

  Guarantees:
    - Only records of the user or managed scope, or of the project or local scope whose project path is the asking
      repository's main checkout, are returned; another project's record is never returned.

  Args:
    start: Any directory inside the asking repository, or a plain directory outside git.
    home: Home directory holding the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current user's.

  Returns:
    Bare plugin name to its eligible records, in registry order; a plugin with no eligible record is absent.
  """

  # Contract:
  # Only records of the user (or managed) scope, or of the project / local scope whose project path is the asking
  # repository's main checkout, are ever returned. Another project's record MUST never be returned.

  # every plugin's records, filtered against the asking repo's main checkout
  checkout = query_main_checkout(start).resolve()
  eligible = {
      name: [ record for record in records if _is_eligible(record, checkout) ]
      for name, records in _read_records(home).items()
  }
  return { name: records for name, records in eligible.items() if records }


def installed_plugin_roots(start: Path, home: Path | None = None) -> dict[str, Path]:
  """
  Resolve the installed root of every plugin the registry records for the repository a directory belongs to.

  Guarantees:
    - Each plugin's root is the install of its highest eligible version, versions compared number by number
      (`1.10.0` above `1.9.0`); another project's record is never used, whatever its version.

  Args:
    start: Any directory inside the asking repository, or a plain directory outside git.
    home: Home directory holding the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current user's.

  Returns:
    Bare plugin name to the install root of its highest eligible version; a plugin with no eligible record is
    absent.
  """

  # Contract:
  # Each plugin's root MUST be the install of its highest eligible version, compared number by number, never as
  # strings; another project's record is never used, whatever its version. The routine resolver and the daemon's
  # self-update check build on this choice.

  # the highest version among each plugin's eligible records wins
  return {
      name: Path(str(max(records, key = _version_key)[_K_INSTALL]))
      for name, records in read_eligible_records(start, home).items()
  }


def installed_plugin_root(name: str, start: Path, home: Path | None = None) -> Path | None:
  """
  Resolve one plugin's installed root for the repository a directory belongs to.

  Args:
    name: Bare plugin name, matched against every `<name>@<marketplace>` key of the registry.
    start: Any directory inside the asking repository, or a plain directory outside git.
    home: Home directory holding the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current user's.

  Returns:
    The install root of the plugin's highest eligible version, or None when no record is eligible.
  """
  return installed_plugin_roots(start, home).get(name)


def plugin_root(name: str, start: Path, *, sibling_base: Path | None = None,
                home: Path | None = None) -> tuple[Path, str]:
  """
  Resolve the directory a plugin's sources are read from.

  Guarantees:
    - Stages run in a fixed order and the first hit wins: the exported plugin directories, the sibling source
      tree, the current checkout's own plugin tree, the install registry. No stage is reordered or skipped,
      except the sibling stage when no sibling base is given.
    - A miss raises, naming every stage searched.

  Args:
    name: Plugin name, with or without its `@<marketplace>` suffix.
    start: Any directory inside the asking repository, or a plain directory outside git.
    sibling_base: Directory holding the caller's own plugin tree; None skips the sibling stage.
    home: Home directory holding the registry; when omitted, `$CLAUDE_CONFIG_DIR` or the current user's.

  Returns:
    The plugin root and the stage that found it: `env`, `sibling`, `repo`, or `cache`.

  Raises:
    PluginNotFoundError: No stage finds the plugin.
  """
  bare = name.split(_MARKETPLACE_SEP, 1)[0]

  # Domain(plugin.boundaries):
  # # Order of locating a plugin
  # A plugin's sources are looked for in four places and the first hit wins. First the plugin directories the
  # runtime hands its processes for development source trees. Then the source tree sitting beside the asking plugin
  # in a development checkout. Then the plugin tree of the checkout the command runs in, a worktree's own tree
  # included. Last the install the registry records for this repository or for the whole user. Sources at hand are
  # never shadowed by an installed copy: a development checkout and a background job must run the sources being
  # edited, or a stale installed copy would silently answer in place of the code under development. The install
  # stays the last place so that a consumer, who has no exported directories and no development tree, still
  # reaches the plugin. When no place has the plugin, the lookup fails and names every place it searched; it never
  # carries on without the plugin.

  # Contract:
  # The stages run env, sibling, repo tree, registry, and the first hit wins; no stage is reordered or skipped
  # except the sibling stage when no sibling base is given. A miss MUST raise, naming every stage searched.

  # stage one: the exported plugin directories, matched on the directory name
  exported = os.environ.get(_PLUGIN_DIRS_ENV, "")
  for entry in filter(None, exported.split(os.pathsep)):
    if Path(entry).name == bare and (Path(entry) / _MANIFEST).is_file():
      return Path(entry).resolve(), STAGE_ENV

  # stage two: the sibling source tree beside the caller's own plugin
  sibling = sibling_base / bare if sibling_base is not None else None
  if sibling is not None and (sibling / _MANIFEST).is_file():
    return sibling.resolve(), STAGE_SIBLING

  # stage three: the plugin tree of the checkout the command runs in
  tree = query_checkout_toplevel(start) / _DEV_ROOT / bare
  if (tree / _MANIFEST).is_file():
    return tree.resolve(), STAGE_REPO

  # stage four: the install the registry records for this repository or the user
  installed = installed_plugin_root(bare, start, home)
  if installed is not None:
    return installed.resolve(), STAGE_CACHE

  # every stage missed: name each one and where it looked
  raise PluginNotFoundError(name, [
      (f"${_PLUGIN_DIRS_ENV}", exported or "(unset)"),
      ("sibling", str(sibling) if sibling is not None else "(none)"),
      ("repo tree", str(tree)),
      ("install registry", f"{registry_path(home)} (records for {query_main_checkout(start)} or the user)"),
  ])


def main(argv: list[str] | None = None) -> int:
  """
  Print the plugin or repository location that the chosen lookup verb resolves to.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 1 when the plugin is not found.

  Raises:
    SystemExit: With exit status 2 on a usage error.
  """
  # the five verbs, each taking the directory the lookup starts from; the program name is the invoked file's own
  parser = argparse.ArgumentParser()
  # waiver: argparse surface strings, not reusable domain keys
  sub = parser.add_subparsers(dest = "verb", required = True)
  # waiver: argparse surface strings, not reusable domain keys
  root = sub.add_parser(_VERB_ROOT, help = "print the directory a plugin's sources are read from")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("name", help = "plugin name, with or without its @<marketplace> suffix")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("--sibling-base", default = None, help = "directory holding the caller's own plugin tree")
  # waiver: argparse surface strings, not reusable domain keys
  installed = sub.add_parser(_VERB_INSTALLED, help = "print the install the registry records for the repository")
  # waiver: argparse surface strings, not reusable domain keys
  installed.add_argument("name", help = "plugin name, with or without its @<marketplace> suffix")
  # waiver: argparse surface strings, not reusable domain keys
  checkout = sub.add_parser(_VERB_CHECKOUT, help = "print the main checkout of the repository")
  for verb in (root, installed, checkout):
    # waiver: argparse surface strings, not reusable domain keys
    verb.add_argument("--start", default = None, help = "directory inside the repository (default: the cwd)")
  # waiver: argparse surface strings, not reusable domain keys
  toplevel = sub.add_parser(_VERB_TOPLEVEL, help = "print the root of the checkout a command works in")
  # waiver: argparse surface strings, not reusable domain keys
  toplevel.add_argument("--start", default = None,
                        help = "directory inside the checkout (default: $LAZY_REPO_ROOT, then the cwd)")
  # waiver: argparse surface strings, not reusable domain keys
  settings = sub.add_parser(_VERB_SETTINGS, help = "print the directory whose .claude/lazy.settings.json applies")
  # waiver: argparse surface strings, not reusable domain keys
  settings.add_argument("--start", default = None,
                        help = "directory inside the checkout (default: $LAZY_REPO_ROOT, then the cwd)")

  # the parsed verb and the start directory, the cwd unless one is named
  args = parser.parse_args(argv)
  start = Path(args.start) if args.start else Path.cwd()

  # the settings root is a walk up the checkout, not a plugin lookup; its start falls back to the dispatcher's
  # environment first
  if args.verb == _VERB_SETTINGS:
    print(query_settings_root(args.start))
    return 0

  # the checkout's own root needs no lookup either; its start falls back to the dispatcher's environment first
  if args.verb == _VERB_TOPLEVEL:
    print(query_repo_root(args.start))
    return 0

  # the main checkout needs no lookup
  if args.verb == _VERB_CHECKOUT:
    print(query_main_checkout(start))
    return 0

  # the install alone, or an error naming the registry and the checkout it was read for
  if args.verb == _VERB_INSTALLED:
    found_install = installed_plugin_root(args.name.split(_MARKETPLACE_SEP, 1)[0], start)
    if found_install is None:
      print(f"error: plugin {args.name} not installed for {query_main_checkout(start)} or the user in "
            f"{registry_path()}", file = sys.stderr)
      return 1
    print(found_install.resolve())
    return 0

  # a plugin root, or the error naming every stage searched
  try:
    found, _stage = plugin_root(args.name, start,
                                sibling_base = Path(args.sibling_base) if args.sibling_base else None)
  except PluginNotFoundError as error:
    print(f"error: {error}", file = sys.stderr)
    return 1
  print(found)
  return 0


if __name__ == "__main__":
  sys.exit(main())
