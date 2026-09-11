#!/usr/bin/env python3
"""
Discovery primitive for the `lazy-core.setup` install chain and its headless twin `lazy-core.autosetup`.

    lazy_setup.py discover <repo-root> [--home <dir>]

Prints one JSON object describing the chain a repo needs, resolved against that repo alone:

- `dev_mode` — whether the repo authors plugins itself (`claude/*/.claude-plugin/plugin.json`);
  in dev-mode an enabled plugin's in-repo sources outrank its cached copy.
- `plugins` — every enabled plugin name mapped to the source root the chain reads it from.
- `skills` — the ordered chain: `dispatch` (`<plugin>:<ns>.<name>`), `phase`, `path`,
  `plugin`, and `live_session` (the skill declares `requires_live_session: true`, so a headless
  executor skips it). Order is pre-install, then per-plugin with `lazy-core.install` first,
  then post-install; alphabetical inside each band.
- `skipped` — enabled plugins the machine has no sources for, with the reason.

Enablement is the union of `enabledPlugins` in `.claude/settings.json` and
`.claude/settings.local.json` under the repo; `installed_plugins.json` under the home directory
resolves an install path only, never enablement.
"""

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
import sys
from pathlib import Path

from frontmatter_parser import parse_frontmatter

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Decision: the skill and the agent call this primitive instead of listing the plugin cache
# themselves — an interactive session may carry no enumeration tool at all, and a listing over
# the whole cache is exactly what a consumer's permission layer may refuse mid-run.

# waiver: external Claude Code filesystem locations, not reusable domain keys
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
# waiver: external Claude Code filesystem locations, not reusable domain keys
_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
# waiver: external Claude Code manifest field names, not internal keys
_ENABLED_PLUGINS = "enabledPlugins"
# waiver: external Claude Code manifest field names, not internal keys
_INSTALL_PATH = "installPath"
# waiver: repo layout of a plugin-authoring vault, not a reusable domain key
_DEV_ROOT, _DEV_MANIFEST = "claude", ".claude-plugin/plugin.json"
# waiver: plugin layout, not a reusable domain key
_SKILLS_DIR, _SKILL_FILE = "skills", "SKILL.md"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASES = ("pre-install", "per-plugin", "post-install")
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASE_KEY = "lazy_setup_phase"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_LIVE_KEY = "requires_live_session"
# waiver: install-skill naming convention, not a reusable domain key
_INSTALL_SUFFIX = ".install"
# waiver: the one installer every chain runs first — it seeds what the others read
_FIRST_INSTALL = "lazy-core.install"
# waiver: report vocabulary shared with the skill and the agent
_NOT_INSTALLED = "plugin not installed on this machine"
# waiver: JSON report keys read by the skill and the agent
_K_DISPATCH, _K_PHASE = "dispatch", "phase"


def _read_json(path: Path) -> dict:
  """
  Load a JSON object from disk, treating an absent or unparseable file as empty.

  Args:
    path: File to read.

  Returns:
    The parsed object, or an empty dict when the file is missing or not valid JSON.
  """
  try:
    # waiver: stdlib encoding idiom
    data = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return {}
  return data if isinstance(data, dict) else {}


def read_enabled_plugins(repo: Path) -> set[str]:
  """
  Read the plugin names a repo enables from its two settings files.

  Args:
    repo: Repo root holding `.claude/settings.json` and `.claude/settings.local.json`.

  Returns:
    Names (marketplace suffix stripped) whose merged `enabledPlugins` entry is true.
  """

  # Domain(install.reconciliation):
  # # Enablement is the repo's own word, never the machine's
  # A plugin applies to a repo only when that repo's tracked or local settings switch it on; the
  # later file overrides the earlier one key by key. The machine-wide install registry spans
  # every project on the host, so it can say where a plugin's sources live but never whether
  # this repo wants them. In a repo that authors plugins, its own sources outrank a cached copy.

  # merge the tracked and the local map, the local one overriding key by key
  merged: dict = {}
  for rel in _SETTINGS_FILES:
    merged.update(_read_json(repo / rel).get(_ENABLED_PLUGINS) or {})

  # keep the switched-on keys, stripped of their `@<marketplace>` suffix
  return { key.split("@", 1)[0] for key, enabled in merged.items() if enabled }


def read_install_paths(home: Path) -> dict[str, Path]:
  """
  Read the machine's plugin registry into a map of plugin name to cached source root.

  Args:
    home: Home directory holding `.claude/plugins/installed_plugins.json`.

  Returns:
    Plugin name to the last recorded `installPath`; plugins with no record are absent.
  """
  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  data = _read_json(home / _INSTALLED_PLUGINS_REL)
  # waiver: external Claude Code manifest field name, not an internal key
  plugins = data.get("plugins", data)

  # the last well-formed record wins — any entry resolves the same per-version cache path
  out: dict[str, Path] = {}
  for key, entries in plugins.items():
    paths = [
        str(rec[_INSTALL_PATH]) for rec in entries or [] if isinstance(rec, dict) and rec.get(_INSTALL_PATH)
    ]
    if paths:
      out[key.split("@", 1)[0]] = Path(paths[-1])
  return out


def find_dev_plugins(repo: Path) -> dict[str, Path]:
  """
  Find the plugins a repo authors itself and map them to their in-repo source root.

  Args:
    repo: Repo root.

  Returns:
    Plugin directory name to `<repo>/claude/<name>`; empty when the repo authors no plugin.
  """
  return { sub.name: sub for sub in _list_subdirs(repo / _DEV_ROOT) if (sub / _DEV_MANIFEST).is_file() }


def _list_subdirs(base: Path) -> list[Path]:
  """
  List a directory's immediate subdirectories in name order.

  Args:
    base: Directory to list.

  Returns:
    Its subdirectories sorted by name; empty when `base` is not a directory.
  """
  # guard: an absent base has no children to list
  if not base.is_dir():
    return []
  return sorted(child for child in (base / name for name in os.listdir(base)) if child.is_dir())


def _skill_entry(plugin: str, skill_md: Path) -> dict | None:
  """
  Describe one `SKILL.md` as a chain entry, or nothing when it does not participate.

  Args:
    plugin: Plugin the skill ships in.
    skill_md: Path to the skill's `SKILL.md`.

  Returns:
    The chain entry, or `None` when the skill neither declares a phase nor is an installer.
  """
  # a declared phase wins; otherwise the `*.install` naming convention makes it an installer
  name = skill_md.parent.name
  # waiver: stdlib encoding idiom
  fm = parse_frontmatter(skill_md.read_text(encoding = "utf-8"))
  phase = fm.get(_PHASE_KEY)
  if phase not in _PHASES:
    phase = _PHASES[1] if name.endswith(_INSTALL_SUFFIX) else None

  # guard: a skill with neither a phase nor the installer name is not part of the chain
  if phase is None:
    return None

  # the chain entry the skill and the agent read
  return {
      # waiver: JSON report keys read by the skill and the agent
      _K_DISPATCH: f"{plugin}:{name}", _K_PHASE: phase, "path": str(skill_md),
      "plugin": plugin, "live_session": fm.get(_LIVE_KEY) is True,
  }


def _order_key(entry: dict) -> tuple:
  """
  Sort key placing phases in contract order and `lazy-core.install` first among installers.

  Args:
    entry: A chain entry from `_skill_entry`.

  Returns:
    The sort tuple.
  """
  # Contract: the chain order is phase band, then `lazy-core.install` ahead of every other
  # installer, then dispatch string; callers and the setup skill rely on it verbatim.
  return (
      _PHASES.index(entry[_K_PHASE]),
      not (entry[_K_PHASE] == _PHASES[1] and entry[_K_DISPATCH].endswith(":" + _FIRST_INSTALL)),
      entry[_K_DISPATCH],
  )


def discover(repo: Path, home: Path) -> dict:
  """
  Build the install chain for a repo.

  Guarantees:
    - `skills` is ordered by phase band, with `lazy-core.install` first among installers and
      the dispatch string deciding the rest.
    - An enabled plugin's in-repo sources outrank its cached copy.

  Args:
    repo: Repo root the chain targets.
    home: Home directory whose plugin registry resolves cached sources.

  Returns:
    The report described in the module docstring.
  """
  # both source kinds, in-repo first
  dev = find_dev_plugins(repo)
  cached = read_install_paths(home)

  # resolve every enabled plugin to one source root, reporting the ones this machine lacks
  roots: dict[str, Path] = {}
  skipped: list[dict] = []
  for plugin in sorted(read_enabled_plugins(repo)):
    root = dev.get(plugin) or cached.get(plugin)
    if root is None:
      # waiver: JSON report keys read by the skill and the agent
      skipped.append({ "plugin": plugin, "reason": _NOT_INSTALLED })
      continue
    roots[plugin] = root

  # collect the participating skills of every resolved plugin, then order the chain
  skills = [
      entry for plugin, root in roots.items()
      for skill_dir in _list_subdirs(root / _SKILLS_DIR) if (skill_dir / _SKILL_FILE).is_file()
      if (entry := _skill_entry(plugin, skill_dir / _SKILL_FILE)) is not None
  ]
  skills.sort(key = _order_key)

  # the report the skill and the agent read
  return {
      # waiver: JSON report keys read by the skill and the agent
      "dev_mode": bool(dev), "plugins": { name: str(root) for name, root in roots.items() },
      "skills": skills, "skipped": skipped,
  }


def main(argv: list[str] | None = None) -> int:
  """
  Parse the arguments and print the chain for the named repo.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 2 on a usage error.
  """
  # waiver: argparse surface strings, not reusable domain keys
  parser = argparse.ArgumentParser(prog = "lazy_setup.py")
  # waiver: argparse surface strings, not reusable domain keys
  sub = parser.add_subparsers(dest = "verb", required = True)
  # waiver: argparse surface strings, not reusable domain keys
  disc = sub.add_parser("discover", help = "print the install chain for a repo as JSON")
  # waiver: argparse surface strings, not reusable domain keys
  disc.add_argument("repo", help = "repo root the chain targets")
  # waiver: argparse surface strings, not reusable domain keys
  disc.add_argument("--home", default = None, help = "home directory (default: the current user's)")
  args = parser.parse_args(argv)

  # guard: a repo path that is not a directory is a usage error, not an empty chain
  repo = Path(args.repo).resolve()
  if not repo.is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # emit the report against the named home, defaulting to the current user's
  print(json.dumps(discover(repo, Path(args.home).resolve() if args.home else Path.home()), indent = 2,
                   ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
