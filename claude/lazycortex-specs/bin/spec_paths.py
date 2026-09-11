"""Spec layout roots — settings-root vs content-root resolution.

The settings-root holds `.claude/lazy.settings.json`; the content-root holds the
subsystem folders and the `requests/` inbox, and is `settings-root/<vault_root>`
(default `specs`). Bin code reads config from the settings-root but joins spec
content under the content-root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


DEFAULT_VAULT_ROOT = "specs"
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION = "spec"
_VAULT_ROOT_KEY = "vault_root"
# waiver: sibling-plugin CLI env contract per dev.plugin-boundaries § 1c
_ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
_BIN_DIR = "bin"


def find_settings_root(start: Path) -> Path:
  """
  Walk up from `start` to the nearest dir holding `.claude/lazy.settings.json`.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The first ancestor (inclusive) containing the settings file; `start`
    resolved when none is found.
  """
  cur = start.resolve()
  for cand in [ cur, *cur.parents ]:
    # guard: first dir carrying the settings file is the settings-root
    if (cand / _SETTINGS_REL).is_file():
      return cand
  return cur


def _vault_root_value(settings_root: Path) -> str:
  """
  Read `spec.vault_root` from settings, defaulting to `specs`.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    The configured vault-root segment, or `specs` when unset/malformed.
  """
  path = settings_root / _SETTINGS_REL
  # guard: no settings file — use the default root
  if not path.is_file():
    return DEFAULT_VAULT_ROOT
  data = json.loads(path.read_text())
  spec = data.get(_SPEC_SECTION)
  # guard: missing/malformed spec section — default
  if not isinstance(spec, dict):
    return DEFAULT_VAULT_ROOT
  value = spec.get(_VAULT_ROOT_KEY)
  # guard: only a non-empty string overrides the default
  if isinstance(value, str) and value:
    return value
  return DEFAULT_VAULT_ROOT


def spec_content_root(settings_root: Path) -> Path:
  """
  Resolve the spec content-root under a settings-root.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    `settings_root / <spec.vault_root>` (default `specs`).
  """

  # Domain(spec.config):
  # # Settings and content live at two different roots
  # A checkout keeps its configuration and its actual spec content at two different roots on
  # purpose: the settings-root is wherever the project's own configuration already lives, while
  # the content-root is a separate, configurable location underneath it that holds nothing but
  # the spec catalog itself. Keeping them apart lets the spec catalog occupy its own named
  # location in a project that organizes its other content differently, without the project's
  # own configuration having to move to make room for it.

  return settings_root / _vault_root_value(settings_root)


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _cached_sibling_root(name: str) -> Path | None:
  """
  Locate a sibling plugin's newest cached install next to this plugin's own cached install.

  A cached install lives at `<cache>/<registry>/<plugin>/<version>/`, so when this file runs from
  one, the cache root is four levels above `bin/` and every sibling's versions sit under it. A dev
  source tree has no version level above `bin/`, so the walk finds nothing there — the dev layout
  is served by the daemon's env export and each caller's own dev fallback.

  Args:
    name: Sibling plugin name, which is also its cache directory and CLI name.

  Returns:
    The sibling's highest cached version directory, or None outside a cached install or when no
    version of the sibling is cached.
  """
  own = Path(__file__).resolve()
  # guard: not a cached install — a dev checkout has no version directory above bin/
  if not own.parents[1].name.replace(".", "").isdigit():
    return None
  # the cache root sits four levels above bin/: cache/<registry>/<plugin>/<version>/bin
  try:
    cache = own.parents[4]
  except IndexError:
    return None
  versions = [
    version
    for registry in cache.iterdir() if (registry / name).is_dir()
    for version in (registry / name).iterdir()
    if version.is_dir() and version.name.replace(".", "").isdigit()
  ]
  return max(versions, key = lambda v: _version_sort_key(v.name)) if versions else None


def resolve_plugin_cli(name: str) -> Path | None:
  """
  Locate a sibling plugin's CLI binary by name.

  Lets a plugin's bin script reach another plugin's published CLI without assuming a fixed
  install layout; each caller applies its own error handling to a missing result. The plugin-dirs
  environment (exported by the daemon) is walked first; outside the daemon, a cached install falls
  back to the sibling's newest version in the same plugin cache.

  Guarantees:
    - When both the plugin-dirs environment and the plugin cache carry a matching CLI, the
      plugin-dirs environment's copy is returned.

  Args:
    name: Name of the CLI binary to look for under each plugin directory's `bin/` folder.

  Returns:
    The resolved binary path, or None when neither the plugin-dirs environment nor the plugin
    cache carries the named CLI.
  """

  # Contract:
  # When both the plugin-dirs environment and the plugin cache carry a matching CLI,
  # the plugin-dirs environment's copy is returned.

  raw = os.environ.get(_ENV_PLUGIN_DIRS, "")
  for entry in raw.split(os.pathsep):
    # guard: empty path segment (trailing/double pathsep) — skip it
    if not entry:
      continue
    cli = Path(entry) / _BIN_DIR / name
    if cli.is_file():
      return cli
  # plugin-cache fallback — a session (hook, skill) has no daemon export to walk
  root = _cached_sibling_root(name)
  # guard: no cached sibling — nothing further to try
  if root is None:
    return None
  cli = root / _BIN_DIR / name
  return cli if cli.is_file() else None


def spec_roots(start: Path) -> tuple[Path, Path]:
  """
  Resolve both spec layout roots from a starting directory.

  Args:
    start: Directory to resolve roots from (cwd or a content path).

  Returns:
    `(settings_root, content_root)`.
  """
  settings_root = find_settings_root(start)
  return settings_root, spec_content_root(settings_root)
