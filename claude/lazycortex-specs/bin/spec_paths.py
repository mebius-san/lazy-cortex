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
  return settings_root / _vault_root_value(settings_root)


def resolve_plugin_cli(name: str) -> Path | None:
  """
  Locate a sibling plugin's CLI binary by name.

  Lets a plugin's bin script reach another plugin's published CLI without assuming a fixed
  install layout; each caller applies its own error handling to a missing result.

  Args:
    name: Name of the CLI binary to look for under each plugin directory's `bin/` folder.

  Returns:
    The resolved binary path, or None when the plugin-dirs environment variable is unset or
    no plugin directory carries the named CLI.
  """
  raw = os.environ.get(_ENV_PLUGIN_DIRS, "")
  for entry in raw.split(os.pathsep):
    # guard: empty path segment (trailing/double pathsep) — skip it
    if not entry:
      continue
    cli = Path(entry) / _BIN_DIR / name
    if cli.is_file():
      return cli
  return None


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
