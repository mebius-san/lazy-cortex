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

v2 -> v3 (`MIGRATIONS[2]`) admits draft and deferred documents into a scope that still carries
the stage predicate the specs install used to seed, which let in only approved and stageless
documents: that exact predicate is widened to the new default, which adds the draft and deferred
stages, and the same scope gains an `index_badges` list naming the stage so the topic index shows
each document's stage beside its entry. A predicate the operator reshaped, a scope with no stage
predicate, and an `index_badges` value already present are left exactly as found; re-running the
step changes nothing.
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
_FILTER_KEY   = "filter"
_FRONTMATTER_KEY = "frontmatter"
_INDEX_BADGES_KEY = "index_badges"

# The frontmatter field a spec catalog records a document's stage in.
_STAGE_FIELD = "spec_stage"

# The stage predicate the specs install seeded before drafts entered the wiki, and its replacement.
_OLD_STAGE_PREDICATE = { "in": [ None, "approved" ] }
_NEW_STAGE_VALUES    = [ None, "draft", "approved", "deferred" ]

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
  # guard: no scopes, or a malformed section — nothing to read axes from
  if not isinstance(scopes := data.get(_SCOPES_KEY), dict):
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
  # guard: no scopes, or a malformed section — nothing to strip
  if not isinstance(scopes := data.get(_SCOPES_KEY), dict):
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


def _admit_draft_stages(cfg: dict) -> dict:
  """
  Widen one scope's old default stage predicate and seed its stage badge.

  Args:
    cfg: One scope config from `wiki.scopes`.

  Returns:
    The scope with its stage predicate widened to admit draft and deferred documents and a
    stage badge added when it carried none, or the input unchanged when its stage predicate is
    absent or differs from the old default in any way.
  """
  # reach the frontmatter predicates through the filter, tolerating a malformed shape at either level
  flt = cfg.get(_FILTER_KEY)
  frontmatter = flt.get(_FRONTMATTER_KEY) if isinstance(flt, dict) else None

  # ref: Domain(settings.versioning) in lazy_settings_migrations/daemon.py — rewrite only the old seed literal
  # guard: no frontmatter filter, or a stage predicate other than the exact old seed literal — the step rewrites
  # the value only while it still equals that literal, so an operator's reshaped value is never touched
  if not isinstance(flt, dict) or not isinstance(frontmatter, dict) \
      or frontmatter.get(_STAGE_FIELD) != _OLD_STAGE_PREDICATE:
    return cfg

  # replace only the stage predicate; every other filter key and predicate is carried as found
  widened = {
    **cfg,
    _FILTER_KEY: { **flt, _FRONTMATTER_KEY: { **frontmatter, _STAGE_FIELD: { "in": list(_NEW_STAGE_VALUES) } } },
  }

  # seed the stage badge only when the scope has no index badge list of its own
  if _INDEX_BADGES_KEY not in widened:
    widened[_INDEX_BADGES_KEY] = [ _STAGE_FIELD ]
  return widened


def _migrate_admit_draft_stages(data: dict) -> dict:
  """
  Apply the v2 -> v3 admission of draft and deferred documents.

  Args:
    data: The `wiki` section content at v2.

  Returns:
    The section with every scope still on the old default stage predicate widened and badged,
    and every other key — including the section's `_version` sentinel — preserved.
  """
  # guard: no scopes, or a malformed section — nothing to widen
  if not isinstance(scopes := data.get(_SCOPES_KEY), dict):
    return data

  # rebuild the scope map, passing the version sentinel and non-dict values through as found
  return { **data, _SCOPES_KEY: {
    key: _admit_draft_stages(cfg) if key != _VERSION_KEY and isinstance(cfg, dict) else cfg
    for key, cfg in scopes.items()
  } }


MIGRATIONS = {
  1: _migrate_hoist_axes,
  2: _migrate_admit_draft_stages,
}
