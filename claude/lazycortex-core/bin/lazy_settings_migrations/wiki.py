"""
Migrations for the `wiki` section of `lazy.settings.json`.

v1 -> v2 (`MIGRATIONS[1]`) hoists the classification-axis vocabulary from the individual scopes
to the section: the union of every scope's `tag_axes`, in first-seen order, becomes the
repository-wide `wiki.tag_axes`, and each scope's own list is kept as the narrowing it now
means. Because every scope's list is a subset of the union it contributed to, the effective set
of axes per scope is unchanged by the move. The same step seeds the section-level `wiki.exclude`
list from the fixed project-structure map, which the configure wizard used to append to each
scope's `exclude_paths` one by one. Idempotent: a section already carrying `tag_axes` and
`exclude` is passed through unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SCOPES_KEY   = "scopes"
_TAG_AXES_KEY = "tag_axes"
_EXCLUDE_KEY  = "exclude"
_SCOPE_EXCLUDE_KEY = "exclude_paths"
_VERSION_KEY  = "_version"

# The project-structure map has one fixed address, so its exclusion is repository-wide by nature.
_STRUCTURE_MAP = "docs/structure.md"


def _scope_entries(data: dict) -> list[dict]:
  """
  List the scope-config dicts of a `wiki` section.

  Args:
    data: The `wiki` section content.

  Returns:
    Every value of `wiki.scopes` that is a dict, in declaration order; empty when the key is
    absent or malformed.
  """
  scopes = data.get(_SCOPES_KEY)
  # guard: no scopes, or a malformed section — nothing to read axes from
  if not isinstance(scopes, dict):
    return []
  return [ cfg for key, cfg in scopes.items() if key != _VERSION_KEY and isinstance(cfg, dict) ]


def _hoisted_axes(data: dict) -> list[str]:
  """
  Build the repository-wide axis vocabulary from the scopes that used to own it.

  Args:
    data: The `wiki` section content at v1.

  Returns:
    Every axis any scope declares, deduplicated, in the order first seen.
  """
  axes: list[str] = []
  for cfg in _scope_entries(data):
    declared = cfg.get(_TAG_AXES_KEY) or []
    for axis in declared:
      # guard: not an axis name, or already collected from an earlier scope
      if not isinstance(axis, str) or axis in axes:
        continue
      axes.append(axis)
  return axes


def _without_structure_map(data: dict) -> dict:
  """
  Drop the project-structure map from every scope's own exclude list.

  Args:
    data: The `wiki` section content, already carrying the hoisted keys.

  Returns:
    The section with each scope's `exclude_paths` stripped of the structure-map entry; a scope
    left with an empty list keeps the empty list rather than losing the key.
  """
  scopes = data.get(_SCOPES_KEY)
  # guard: no scopes, or a malformed section — nothing to strip
  if not isinstance(scopes, dict):
    return data
  rebuilt = {}
  for key, cfg in scopes.items():
    # guard: the section's own `_version` sentinel, not a scope
    if key == _VERSION_KEY or not isinstance(cfg, dict):
      rebuilt[key] = cfg
      continue
    own = cfg.get(_SCOPE_EXCLUDE_KEY)
    # guard: the scope declares no excludes of its own
    if not isinstance(own, list):
      rebuilt[key] = cfg
      continue
    rebuilt[key] = { **cfg, _SCOPE_EXCLUDE_KEY: [ glob for glob in own if glob != _STRUCTURE_MAP ] }
  return { **data, _SCOPES_KEY: rebuilt }


def _migrate_hoist_axes(data: dict) -> dict:
  """
  Apply the v1 -> v2 hoist of the axis vocabulary and the section-level exclude list.

  Args:
    data: The `wiki` section content at v1.

  Returns:
    The section carrying `tag_axes` and `exclude` at its own level, with every other key —
    including each scope's now-narrowing `tag_axes` and the section's `_version` sentinel —
    preserved.
  """

  # Domain(settings.versioning):
  # # A migration never rebuilds what the operator already edited
  # An upgrade step that seeds a new setting runs on every load of an old file, so the seed must recognise its own
  # earlier work: a value already present — whether the seed wrote it or the operator reshaped it since — is left
  # exactly as found, and only a section that has never carried the key gets the derived default. Re-running the
  # same step is therefore always free, and an operator's edit survives any number of upgrades.

  # Contract:
  # A `tag_axes` or `exclude` list already present on the section is NEVER rebuilt or
  # reordered by this step; only an absent key receives the derived value.

  # work on a copy — the ladder contract hands back a new section dict
  hoisted = dict(data)

  # build the vocabulary only when the section has none — a list already present is the
  # operator's and is never rebuilt
  if not isinstance(hoisted.get(_TAG_AXES_KEY), list):
    hoisted[_TAG_AXES_KEY] = _hoisted_axes(data)

  # seed the exclude list only when the section has none, for the same reason
  if not isinstance(hoisted.get(_EXCLUDE_KEY), list):
    hoisted[_EXCLUDE_KEY] = [ _STRUCTURE_MAP ]

  # the per-scope structure-map entries are redundant now that the section carries the exclusion
  return _without_structure_map(hoisted)


MIGRATIONS = {
  1: _migrate_hoist_axes,
}
