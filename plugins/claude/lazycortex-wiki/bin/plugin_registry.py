"""
Installed-plugin lookup through Claude Code's plugin registry, for lazycortex-wiki.

Every resolver in this plugin that needs a sibling plugin's root — `axes.py`, `mirror.py`
and `dispatch.py` each locate `lazycortex-core`'s CLI — ends its ladder here, after the
daemon's `$LAZYCORTEX_PLUGIN_DIRS` export and the dev-vault sibling layout both miss. The
plugin cache is never walked: it keeps every version ever installed, so the highest cached
directory is not necessarily the version this machine has enabled. The registry
(`~/.claude/plugins/installed_plugins.json`) names the `installPath` the install actually
recorded, and the highest recorded version wins.

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract), so this
module is this plugin's own copy of the lookup, not shared with any neighbour.
"""
from __future__ import annotations

import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: external Claude Code registry path, not an internal key
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"

# Separator between a plugin's name and its marketplace in a registry key (`<plugin>@<marketplace>`).
_MARKETPLACE_SEP = "@"

# Registry key that nests the plugin map in newer registry files.
_KEY_PLUGINS = "plugins"

# Per-record keys this module reads.
_KEY_VERSION = "version"
_KEY_INSTALL_PATH = "installPath"


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin version string.

  Args:
    name: Version string as the registry records it.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def installed_plugin_root(name: str, home: Path | None = None) -> Path | None:
  """
  Resolve a plugin's installed source root from Claude Code's plugin registry.

  The registry (`~/.claude/plugins/installed_plugins.json`) records one entry per project and
  version that installed the plugin, each naming its `installPath`; the highest recorded version
  wins. The plugin cache itself is never searched: it keeps every version ever installed, so a walk
  across it returns copies the registry no longer names.

  Args:
    name: Plugin name without its `@<marketplace>` suffix.
    home: Home directory holding the registry; the current user's when omitted.

  Returns:
    The recorded install root when it exists on disk, else None.
  """
  registry = (home or Path.home()) / _INSTALLED_PLUGINS_REL
  try:
    data = json.loads(registry.read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return None
  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  plugins = data.get(_KEY_PLUGINS, data) if isinstance(data, dict) else {}
  records = [
    rec
    for key, entries in plugins.items() if key.split(_MARKETPLACE_SEP, 1)[0] == name
    for rec in (entries or []) if isinstance(rec, dict) and rec.get(_KEY_INSTALL_PATH)
  ]
  # guard: the plugin was never installed on this machine
  if not records:
    return None
  best = max(records, key = lambda rec: _version_sort_key(str(rec.get(_KEY_VERSION, ""))))
  root = Path(str(best[_KEY_INSTALL_PATH]))
  return root if root.is_dir() else None
