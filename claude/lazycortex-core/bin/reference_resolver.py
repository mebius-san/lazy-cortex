"""
Resolve agent / protocol / aspect references to on-disk paths.

Supports three reference forms — plugin-scoped (`<plugin>:<name>`), user-scoped
(`user:<name>`), and bare (`<name>`) — and three categories (`agents`,
`protocols`, `aspects`). Plugin-scoped references prefer dev-plugin directories
listed in `LAZYCORTEX_PLUGIN_DIRS` before falling back to the Claude Code plugin
cache.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
from pathlib import Path

from constants import PluginFile

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: domain exception name imported across modules; shadowing builtin ReferenceError is intentional, not restructured for a checker
class ReferenceError(Exception):  # pylint: disable=redefined-builtin
  """
  Raised when a reference cannot be resolved to an existing file on disk.
  """


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


def _dev_plugin_dirs() -> list[Path]:
  """
  Return the dev-plugin directories declared by the runtime daemon.

  Each entry is a plugin source directory whose `.claude-plugin/plugin.json` name
  is matched against the requested plugin scope before the resolver consults the
  plugin cache. Subprocess routines inherit this env, so daemon-spawned
  subcommands see the same dev plugins the daemon does.

  Returns:
    The dev-plugin directories listed in `LAZYCORTEX_PLUGIN_DIRS`, or an empty
    list when the env var is unset or empty.
  """
  raw = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "")
  # guard: env var unset or empty — no dev plugin directories to consult
  if not raw:
    return []
  return [ Path(p) for p in raw.split(os.pathsep) if p ]


def _resolve_in_dev_dir(plugin_dir: Path, plugin_name: str, dir_name: str, name: str) -> Path | None:
  """
  Return the on-disk path for a reference inside one dev-plugin directory.

  The file's existence is not verified here — match-but-missing is a plugin
  authoring bug and must surface as a hard error at the call site rather than be
  silently shadowed by a cache fall-through.

  Args:
    plugin_dir: Dev-plugin source directory to inspect.
    plugin_name: Plugin scope requested by the reference.
    dir_name: Category subdirectory under the plugin root.
    name: Reference name without extension.

  Returns:
    The path `<plugin_dir>/<dir_name>/<name>.md` when the plugin's manifest name
    matches `plugin_name`; None when the manifest is missing, unreadable, or
    names a different plugin.
  """
  manifest = plugin_dir / PluginFile.MANIFEST_DIR / PluginFile.MANIFEST
  try:
    data = json.loads(manifest.read_text())
  except (FileNotFoundError, json.JSONDecodeError):
    return None
  # guard: manifest name does not match the requested plugin scope
  if data.get(PluginFile.NAME) != plugin_name:
    return None
  return plugin_dir / dir_name / f"{name}.md"


def resolve(ref: str, *, category: str, repo: Path) -> Path:
  """
  Resolve a reference string to a filesystem path.

  Reference forms:
    `<plugin>:<name>` — plugin cache at
    `~/.claude/plugins/cache/<registry>/<plugin>/<version>/<category>/<name>.md`,
    picking the version directory that sorts last (lexicographic order, so
    "2.0.0" > "10.0.0"; this mirrors `resolve_routine_command` in
    `runtime_daemon.py`).
    `user:<name>` — global `~/.claude/<category>/<name>.md`.
    `<name>` — repo-local `.claude/<category>/<name>.md`.

  Guarantees:
    - For a plugin-scoped reference, a matching dev-plugin directory takes precedence over
      the installed plugin cache.
    - A dev-plugin match whose file is missing raises rather than silently falling back to
      the cache.

  Args:
    ref: Reference string in one of the three forms above.
    category: One of `agents`, `protocols`, or `aspects`.
    repo: Repository root used for bare references.

  Returns:
    Absolute path to the resolved reference file.

  Raises:
    ReferenceError: When the resolved path does not exist, when a dev-plugin
      scope match points at a missing file, when no cache registry contains the
      plugin scope, or when the plugin has no cached versions.
  """

  # Contract:
  # For a plugin-scoped reference, a matching dev-plugin directory MUST be preferred over the
  # installed plugin cache; only when no dev-plugin directory declares the requested plugin
  # name does resolution fall back to the cache.

  # Contract:
  # Once a dev-plugin directory's manifest matches the requested plugin name, resolution MUST
  # NOT fall through to the plugin cache even when the declared file is missing on disk — that
  # mismatch is raised as an error instead of being silently masked by a cache hit.

  # Domain(plugin.boundaries):
  # # Reference scoping across plugin, user, and repo layers
  # A shared reference names where one document lives: inside a single named plugin, in the
  # operator's own global configuration, or in the consuming repository's local configuration.
  # A plugin-scoped reference always tries that plugin's active development sources first, so
  # work in progress on a plugin is read from its live source rather than a stale installed
  # copy; only once no matching development source exists does resolution fall back to the
  # installed copies of that plugin, and it always prefers the newest one found.

  # Plugin-shipped protocols live under <plugin-root>/references/ — the
  # repo-wide convention used by every plugin's own protocol/contract docs
  # (lazy-obsidian.iconize-protocol.md, lazy-core.expert-protocols-contract.md,
  # lazy-review.doc-review-protocol.md).
  # Agents stay under <plugin-root>/agents/. Consumer-local resolution
  # (no plugin prefix) keeps the canonical Claude Code shape
  # <repo>/.claude/<category>/<name>.md.
  # All branches map category to the on-disk directory the same way:
  # protocols live in `references/`, agents live in `agents/`. The mapping
  # applies uniformly to plugin-prefixed, user-scope, and bare references.
  plugin_dir_for_category = { "protocols": "references", "agents": "agents", "aspects": "references" }
  dir_name = plugin_dir_for_category.get(category, category)
  if ":" in ref:
    scope, name = ref.split(":", 1)
    # waiver: one-off reference-scope token, not a domain constant
    if scope == "user":
      # user-scope reference resolves under the global ~/.claude tree
      # waiver: filesystem path idiom
      p = Path.home() / ".claude" / dir_name / f"{name}.md"
    else:
      # Dev-plugin paths take precedence over the plugin cache.
      for plugin_dir in _dev_plugin_dirs():
        hit = _resolve_in_dev_dir(plugin_dir, scope, dir_name, name)
        if hit is not None:
          # guard: dev-plugin scope match but file missing on disk — plugin authoring bug
          if not hit.exists():
            raise ReferenceError(f"{category} not found in dev plugin: {ref} → {hit}")
          return hit
      # waiver: filesystem path idiom
      cache = Path.home() / ".claude/plugins/cache"
      # Real layout: cache/<registry>/<plugin>/<version>/<dir>/<name>.md.
      # Walk all <registry>/<plugin> dirs under any registry prefix.
      plugin_dirs: list[Path] = []
      if cache.is_dir():
        for registry in cache.iterdir():
          # guard: skip non-directory entries inside the cache root
          if not registry.is_dir():
            continue
          candidate = registry / scope
          if candidate.is_dir():
            plugin_dirs.append(candidate)
      # guard: no registry contains the requested plugin scope
      if not plugin_dirs:
        raise ReferenceError(f"plugin not in cache: {scope}")
      # Collect all version subdirectories across matching registry/plugin dirs.
      all_versions: list[Path] = []
      for pd in plugin_dirs:
        all_versions.extend(v for v in pd.iterdir() if v.is_dir())
      # guard: plugin dir exists but contains no cached versions
      if not all_versions:
        raise ReferenceError(f"no versions cached for plugin: {scope}")
      # highest version by numeric order (consistent with runtime_daemon)
      latest = max(all_versions, key = lambda v: _version_sort_key(v.name))
      p = latest / dir_name / f"{name}.md"
  else:
    # bare reference resolves under the repo-local .claude tree
    # waiver: filesystem path idiom
    p = Path(repo) / ".claude" / dir_name / f"{ref}.md"
  # guard: resolved path does not exist on disk
  if not p.exists():
    raise ReferenceError(f"{category} not found: {ref} → {p}")
  return p
