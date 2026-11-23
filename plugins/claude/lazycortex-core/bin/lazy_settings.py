"""
lazy.settings.json read/write helper with per-section _version migration ladder.

Two-file model (mirrors Claude Code's settings.json / settings.local.json):

- `lazy.settings.json` — tracked, committed; shared team config.
- `lazy.settings.local.json` — gitignored; per-machine / personal overrides.
  Sits as a sibling of the tracked file (same directory, `.local` suffix
  inserted before `.json`). Discovered automatically by load_section.

Merge semantics on read mirror Claude Code's stack:

- scalars: local replaces tracked;
- arrays: union + dedupe (tracked order first, novel local entries appended);
- objects: recursive deep merge.

The `_version` key is owned by tracked and never adopted from local — `migrate_all` walks every
overlay section through its ladder: a stamped section from its own stamp, an unstamped one from the
version the tracked file's same section sat on before the run, and it leaves unstamped sections unstamped.
An unstamped overlay section whose section the tracked file does not carry, or carries as nothing but its
version stamp, is walked from the first rung of its ladder when the section is replayable (every rung leaves
current-shape data unchanged). For any other section the version is read from its own data on every run,
through the retired-shape and ambiguous-value tables of the section's ladder module: with no retired shape it
is current, and when an ambiguous value lies below the start the version is unknown, so the section stays as
stored and `read_undetermined_sections` names it. A tracked section with real content gives its version
to the overlay section.

Writes go to tracked. `save_section` never touches local and stamps a section only with a version the
file's own section already stands on (the current one for a section the file does not carry yet). Callers that
need a load → modify → save round-trip on a single layer should use
`load_tracked_section` to avoid local-overlay leaks into the tracked file.

Migration model. All read entry points (`load_section` / `load_tracked_section` /
`load_verbatim_tracked_section` / `load_local_only_section`) are PURE reads — they never run the migration ladder
and never write to disk. Migration is an install / doctor responsibility, invoked
explicitly via `migrate_all` (called from `/lazy-core.install` / `/lazy-core.doctor`).
The daemon never migrates anything from a read path; if the on-disk schema is behind
`CURRENT_VERSIONS` the caller sees the file as-is and must surface the mismatch.
This separation prevents the daemon-self-block failure mode where an upgrade-driven
write back dirties the tracked tree and trips the daemon's own dirty-tree halt.
"""
from __future__ import annotations

import copy
import json
import sys
from importlib import import_module
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from types import ModuleType

  from collections.abc import Callable


CURRENT_VERSIONS = {
  "agent_models": 2,
  "daemon": 4,
  "external_dirs": 1,
  "routines": 8,
  "experts": 4,
  "git": 1,
  "products": 3,
  "review": 13,
  "spec": 2,
  "structure": 1,
  "terms": 2,
  "wiki": 3,
}
# Sections no plugin reads any more; the migration ladder deletes them from the file
RETIRED_SECTIONS = ( "repos", )

# Decision: an explicit list, not every section — the daemon, wiki, routines, review and experts rungs seed keys
# or rewrite values a current section may hold, so replaying them would change an overlay that is already current

# Sections whose every rung leaves data already in the current shape unchanged, so an overlay section of unknown
# version may walk the whole ladder
_REPLAYABLE_SECTIONS = frozenset({ "agent_models", "products", "spec", "terms" })


def resolve_agent_model_tier(value: object) -> str | None:
  """
  Unwrap one `agent_models` entry value to its effective tier string.

  An entry is either a bare string (the operator's pin) or a seed object
  `{"tier": ..., "seeded_from": ...}` recording where the value came from —
  `seeded_from` is install-step bookkeeping and never itself a tier. Both
  shapes resolve to the same effective tier; a malformed object (no `tier`
  key, or a non-string `tier`) resolves to no tier at all.

  Args:
    value: One `agent_models[<group>][<key>]` entry as read from settings.

  Returns:
    The tier string, or `None` when `value` is neither a string nor a
    seed object with a string `tier`.
  """

  # Domain(settings.versioning):
  # # An agent's model tier can be a personal choice or a recorded default
  # A model tier assigned to one agent is recorded one of two ways: either as the tier name
  # itself, meaning an operator picked it deliberately, or as a small record that also notes
  # where the value was seeded from. The provenance note is bookkeeping about how the value got
  # there, never a tier in its own right, so resolving an agent's effective tier always looks
  # only at the tier itself and ignores where it came from.

  # guard: bare-string pin — the value is already the tier
  if isinstance(value, str):
    return value

  # guard: not a seed object — nothing to unwrap
  if not isinstance(value, dict):
    return None
  # waiver: 'tier' names the seed-object field per the documented agent_models entry shape;
  # a one-member constants container for a single call site is not worth the indirection
  tier = value.get("tier")
  return tier if isinstance(tier, str) else None


def _migrations(section_key: str) -> dict[int, Callable[[dict], dict]]:
  """
  Return the migration ladder for a given section key.

  Args:
    section_key: Name of the section in lazy.settings.json whose ladder is requested.

  Returns:
    Mapping from source version to migration callable, or an empty dict when no ladder module
    exists for the section.
  """
  module = _find_ladder_module(section_key)
  return module.MIGRATIONS if module is not None else {}


def _find_ladder_module(section_key: str) -> ModuleType | None:
  """
  Import the ladder module of a given section key.

  Args:
    section_key: Name of the section in lazy.settings.json whose ladder module is requested.

  Returns:
    The section's module under `lazy_settings_migrations`, or `None` when no ladder module exists for it.
  """
  mod_name = section_key.replace(".", "_").replace("-", "_")
  try:
    return import_module(f"lazy_settings_migrations.{mod_name}")
  except ModuleNotFoundError:
    return None


def _find_unstamped_version(
    section_key: str,
    section: dict,
    tracked_versions: dict[str, int | None],
) -> int | None:
  """
  Tell the version an unstamped overlay section sits on.

  Args:
    section_key: Name of the overlay section.
    section: The overlay section, without a version stamp.
    tracked_versions: Mapping from section key to the version the tracked file's section sat on before this run,
      `None` for a section whose version the tracked file cannot give.

  Returns:
    The tracked file's version when it gives one. Otherwise the highest version of the oldest retired shape the
    section holds, or the current version when it holds none; `None` when a step below that version would
    rewrite a value the section holds that a current section may hold too.
  """

  # Domain(settings.versioning):
  # # An overlay section's age is read from its own data
  # A personal overlay section with no version stamp, whose section the shared file does not carry or carries
  # as a bare version stub, has no version to inherit, so its age is read from what it holds, on every run.
  # Each retired shape proves the section was written no later than the last version that still had it,
  # and the oldest such proof sets where the upgrade starts;
  # a section holding none is current. A value an upgrade rewrites but an operator may still choose today
  # proves nothing, so when a step that would rewrite it lies below the start, the age stays unknown:
  # the section is left as stored until the operator states the version it was written for.

  # the tracked file gives the version when it can — the overlay section then sits on it
  if (tracked := tracked_versions[section_key]) is not None:
    return tracked

  # otherwise the oldest retired shape the section holds sets the start; none means current
  module = _find_ladder_module(section_key)
  start = min(( version for version, holds in getattr(module, "LEGACY_SHAPES", {}).items() if holds(section) ),
              default = CURRENT_VERSIONS[section_key])

  # a step below the start that would rewrite a value a current section may hold too leaves the age unknown
  if any(version < start and holds(section) for version, holds in getattr(module, "AMBIGUOUS_VALUES", {}).items()):
    return None
  return start


def migrate_root_version_to_section_version(raw: dict) -> dict:
  """
  Move a legacy root-level `version` field down to each section's per-section version key.

  Args:
    raw: Parsed lazy.settings.json content; mutated in place when a legacy root version is found.

  Returns:
    The same dict with the root `version` removed and its value propagated into each section
    that did not already declare its own per-section version.
  """
  # a legacy root version is present — lift it into every section that lacks its own
  if SettingsKey.LEGACY_VERSION in raw:
    legacy = raw.pop(SettingsKey.LEGACY_VERSION)

    # propagate legacy version into every section that has no per-section version yet
    for section in raw.values():
      if isinstance(section, dict) and SettingsKey.VERSION not in section:
        section[SettingsKey.VERSION] = legacy
  return raw


def _local_overlay_path(tracked_path: Path) -> Path:
  """
  Return the sibling `.local.json` overlay path for the given tracked settings file.

  Example: `/repo/.claude/lazy.settings.json` →
  `/repo/.claude/lazy.settings.local.json`.

  Args:
    tracked_path: Path to the tracked settings file. The file does not need to exist.

  Returns:
    Path with `.local` inserted before the final suffix, in the same directory.
  """
  return tracked_path.with_name(f"{tracked_path.stem}.local{tracked_path.suffix}")


def _deep_merge_claude(base: object, overlay: object) -> object:
  """
  Deep-merge `overlay` onto `base` using Claude Code's settings semantics.

  - dict + dict: recursive merge; overlay keys win on scalar conflicts.
    The `_version` key is sticky: base wins (tracked owns versioning).
  - list + list: tracked entries preserved in order, then novel overlay
    entries appended (dedupe by equality).
  - mismatched types or scalars: overlay wins.

  Args:
    base: Tracked layer value.
    overlay: Local-overlay value to merge on top of `base`.

  Returns:
    The merged value following the semantics described above.
  """

  # Domain(settings.versioning):
  # # Two-layer settings merge
  # A project's settings are read from two layers: a shared, committed file and a personal,
  # per-machine overlay sitting beside it. The overlay never rewrites a plain value outright —
  # a scalar in the overlay replaces the shared one, a list keeps every shared entry in its
  # original order and only appends overlay entries not already present, and a nested structure
  # merges recursively so an overlay only has to state what it changes. Across every layer the
  # section's own version marker always comes from the shared file; the personal overlay can
  # never advance or shadow it.

  if isinstance(base, dict) and isinstance(overlay, dict):
    result = { **base }
    for key, value in overlay.items():
      # guard: tracked owns versioning — never adopt _version from local
      if key == SettingsKey.VERSION:
        continue
      if key in result:
        result[key] = _deep_merge_claude(result[key], value)
      else:
        result[key] = value
    return result
  if isinstance(base, list) and isinstance(overlay, list):
    merged = list(base)

    # append only entries that are not already present in the tracked list
    for item in overlay:
      if item not in merged:
        merged.append(item)
    return merged
  return overlay


def _parse_layer(path: Path) -> dict:
  """
  Parse one settings layer from disk as a JSON object.

  An empty file reads as an empty object.

  Args:
    path: Path to the settings layer, tracked file or local overlay, known to exist.

  Returns:
    The layer's top-level object.

  Raises:
    ValueError: If the layer is not valid JSON (a `json.JSONDecodeError`) or its top level is not a JSON object;
      the message of the latter names the file.
  """
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}")

  # guard: a layer whose top level is not an object is unreadable, like one that does not parse
  if not isinstance(raw, dict):
    raise ValueError(f"{path}: settings layer is not a JSON object")
  return raw


def load_tracked_section(path: Path | str, section_key: str) -> dict:
  """
  Load one section from the tracked settings file only, without applying the local overlay.

  PURE read. No migration ladder, no write-back. When the on-disk schema is behind
  `CURRENT_VERSIONS`, the caller sees the file as-is — schema mismatch is the explicit
  install / doctor's problem to detect and fix (`migrate_all`). Daemon read paths never
  mutate the tracked file: any write here would dirty the working tree and trip the
  daemon's own dirty-tree halt.

  Callers that perform a load → modify → save round-trip MUST use this entry point to
  avoid leaking local-overlay state into the tracked file on save.

  Guarantees:
    - Never writes to disk and never runs a migration ladder; this is a pure read of
      whatever is already on disk.
    - A tracked file that is not valid JSON, or whose top level is not a JSON object, raises `ValueError`;
      it is never read as an empty or section-less file.

  Args:
    path: Path to the tracked settings file. May be a string or `Path`.
    section_key: Name of the section to load.

  Returns:
    The section dict, freshly initialised to the current version when missing from the file.

  Raises:
    ValueError: If the tracked file is not valid JSON (a `json.JSONDecodeError`) or its top level is not a JSON
      object; the message of the latter names the file.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  # Contract:
  # A tracked file that is not valid JSON, or whose top level is not a JSON object, MUST raise `ValueError`.
  # It is never read as an empty or section-less file: callers, such as the memory writer, treat the raise as
  # "unreadable" and must not mistake it for a file that declares nothing.

  path = Path(path)

  # guard: no tracked file yet — return a fresh section pinned to the current version
  if not path.exists():
    return { SettingsKey.VERSION: CURRENT_VERSIONS.get(section_key, 1) }

  # the section as the tracked file stores it
  section = _parse_layer(path).get(section_key, {})

  # guard: section missing from on-disk file — caller sees a fresh current-version stub
  if not section:
    return { SettingsKey.VERSION: CURRENT_VERSIONS.get(section_key, 1) }
  return section


def load_verbatim_tracked_section(path: Path | str, section_key: str) -> dict | None:
  """
  Load one section from the tracked settings file exactly as it is stored.

  Unlike `load_tracked_section`, an absent section is reported as absent rather than replaced by a
  version-stamped stub, and the local overlay is not applied.

  Guarantees:
    - Never writes to disk and never runs a migration ladder; this is a pure read of
      whatever is already on disk.
    - A tracked file that is not valid JSON, or whose top level is not a JSON object, raises `ValueError`;
      it is never read as an empty or section-less file.

  Args:
    path: Path to the tracked settings file. May be a string or `Path`.
    section_key: Name of the section to load.

  Returns:
    The section dict as stored, or `None` when the file does not exist or does not carry the key.

  Raises:
    ValueError: If the tracked file is not valid JSON (a `json.JSONDecodeError`) or its top level is not a JSON
      object; the message of the latter names the file.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  # Contract:
  # A tracked file that is not valid JSON, or whose top level is not a JSON object, MUST raise `ValueError`.
  # It is never reported as an absent section: callers, such as the memory writer, treat the raise as
  # "unreadable" and must not mistake it for a file that does not carry the section.

  path = Path(path)

  # guard: no tracked file — the section is absent
  if not path.exists():
    return None

  # the section exactly as stored, `None` when the file does not carry it
  return _parse_layer(path).get(section_key)


def load_local_only_section(path: Path | str, section_key: str) -> dict:
  """
  Return the local-overlay's view of one section, or an empty dict when absent.

  No merge, no migration, no write-back. Intended for skills that want to inspect what is
  present in the personal overlay for a given section — typically audits, diagnostics, or
  wizards that surface effective configuration.

  Guarantees:
    - Never writes to disk and never runs a migration ladder; this is a pure read of
      whatever is already on disk.
    - An overlay file that is not valid JSON, or whose top level is not a JSON object, raises `ValueError`;
      it is never read as an empty overlay.

  Args:
    path: Path to the tracked settings file; the sibling `.local.json` is consulted.
    section_key: Name of the section to read from the overlay.

  Returns:
    The section dict from the overlay, or an empty dict when the overlay file does not exist
    or does not declare that section.

  Raises:
    ValueError: If the local overlay file is not valid JSON (a `json.JSONDecodeError`) or its top level is not a JSON
      object; the message of the latter names the file.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  # Contract:
  # An overlay file that is not valid JSON, or whose top level is not a JSON object, MUST raise `ValueError`.
  # It is never read as an empty overlay: callers, such as the memory writer, treat the raise as "unreadable"
  # and must not mistake it for an overlay that declares nothing.

  local_path = _local_overlay_path(Path(path))

  # guard: no overlay file present — caller sees an empty view
  if not local_path.exists():
    return {}

  # the overlay's own view of the section, empty when it does not carry it
  return _parse_layer(local_path).get(section_key, {}) or {}


def load_section(path: Path | str, section_key: str) -> dict:
  """
  Load one section with the local overlay deep-merged onto the tracked layer.

  This is the reading entry point for nearly every caller. The returned value is the effective
  view per Claude Code semantics (scalar replace, array union+dedupe, object deep merge), with
  the section version sticky to the tracked layer. PURE read — no migration, no write-back.

  Callers that intend to write back the loaded section (load → modify → save) MUST use
  `load_tracked_section` instead — saving a merged view would leak local-overlay entries
  into the tracked, shared file.

  Guarantees:
    - Never writes to disk and never runs a migration ladder; this is a pure read of
      whatever is already on disk.
    - A tracked or overlay file that is not valid JSON, or whose top level is not a JSON object, raises
      `ValueError`; neither layer is ever read as empty.

  Args:
    path: Path to the tracked settings file.
    section_key: Name of the section to load.

  Returns:
    The effective section dict (tracked content with local overlay applied when present).

  Raises:
    ValueError: If the tracked or the overlay file is not valid JSON (a `json.JSONDecodeError`) or its top level is
      not a JSON object; the message of the latter names the file.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  # Contract:
  # A tracked or overlay file that is not valid JSON, or whose top level is not a JSON object, MUST raise
  # `ValueError`. Neither layer is ever read as empty: callers, such as the memory writer, treat the raise as
  # "unreadable" and must not mistake it for a layer that declares nothing.

  path = Path(path)
  tracked = load_tracked_section(path, section_key)
  local_section = load_local_only_section(path, section_key)

  # guard: no local-overlay content — tracked view is already the effective view
  if not local_section:
    return tracked
  merged = _deep_merge_claude(tracked, local_section)

  # a merge of two dict layers is always a dict; the fallback keeps the declared return type honest
  return merged if isinstance(merged, dict) else {}


def migrate_all(path: Path | str) -> dict[str, tuple[int, int]]:
  """
  Bring every declared settings section to its current version and drop the retired sections.

  Install / doctor-side entry point — invoked ONLY by `/lazy-core.install`,
  `/lazy-core.doctor`, or the CLI `lazy_settings.py migrate` subcommand. The daemon
  never calls this from a read path: migration is an explicit, operator-triggered action,
  never a side effect of reading settings (Bug 104).

  Walks the tracked file, applies every section's ladder, writes the migrated content back to
  disk atomically when any upgrade ran. The sibling gitignored overlay `lazy.settings.local.json`
  is migrated too: retired sections are deleted from it, and every overlay section below the current
  version is walked through its ladder. A stamped overlay section walks from its own stamp, with the
  stamp advanced. An unstamped one is taken to sit on the version the tracked file's same section had
  before this run migrated it (`1` when that section carries no stamp), and stays unstamped. When the
  tracked file does not carry the section (the section is absent, empty or holds nothing but its version
  stamp, or the file is missing), a replayable section walks from the first rung of its ladder, and any other
  section takes its version from its own data on every run: current when it holds no retired shape, and left
  as stored when the version cannot be told. An overlay section whose walk changes nothing is not rewritten.

  Guarantees:
    - The sibling local overlay is never created by this call.
    - The overlay never gains a section or a version stamp it did not already carry.
    - The overlay is rewritten only when something in it changed.
    - An unstamped overlay section whose version cannot be told is left exactly as stored, neither migrated nor
      stamped, and `read_undetermined_sections` names it.
    - That holds on every run, not only the first: what an earlier run wrote into the tracked file never settles the
      version of such a section, so it stays left as stored until the overlay stamps it or the tracked file carries
      real content for the section.

  Args:
    path: Path to the tracked settings file. The file may be missing; in that case the overlay is
      still migrated, its unstamped replayable sections are walked from the first rung of their
      ladders, its other unstamped sections take their version from their own data, and the result map
      holds only the overlay's rewrites.

  Returns:
    Mapping from section key to `(before, after)` version tuples for every section that was upgraded
    in the tracked file or rewritten in the overlay. A section walked in both layers appears once, with
    the tracked pair. Sections already at the target version are omitted.

  Raises:
    OSError: If the migrated tracked file or overlay cannot be written back to disk.
    json.JSONDecodeError: If the tracked file or the overlay is not valid JSON.
    KeyError: If a section's ladder has no step for a version the tracked file or an overlay section
      is sitting on, so the walk to the current version cannot complete.
  """

  # Contract:
  # The sibling local overlay is never created by this call; a missing overlay stays missing.

  # Contract:
  # The overlay never gains a section or a version stamp it did not already carry.

  # Contract:
  # The overlay is rewritten only when something in it changed;
  # an overlay that needs no change is left untouched on disk.

  # Contract:
  # An unstamped overlay section whose version cannot be told is left exactly as stored:
  # it is neither migrated nor stamped, and `read_undetermined_sections` names it.

  # Contract:
  # That holds on every run, not only the first: what an earlier run wrote into the tracked file never
  # settles the version of such a section, so it stays left as stored until the overlay stamps it
  # or the tracked file carries real content for the section.

  # Domain(settings.versioning):
  # # Settings evolve one section at a time, only when explicitly asked
  # Each top-level settings section carries its own version number rather than the file having
  # one overall version, so an old section can be brought forward independently of its
  # neighbours. A file written before per-section versioning existed carries one legacy version
  # at the top instead; that value is pushed down into every section that has not yet recorded
  # its own, and the legacy marker is then discarded. Bringing a section's version forward is
  # never a side effect of simply reading the settings — it only happens when explicitly asked,
  # so an ordinary run never rewrites a file the operator has not touched. A section with no
  # documented path from its current version to the version the project expects is treated as
  # broken rather than silently left behind. A section no plugin reads any more is retired: it is
  # deleted from the file on the same explicit run, and never stamped back.

  path = Path(path)
  result: dict[str, tuple[int, int]] = {}

  # read the tracked file once, with any legacy root version already lifted into its sections
  raw: dict | None = None
  if path.exists():
    # waiver: stdlib encoding idiom
    raw = migrate_root_version_to_section_version(json.loads(path.read_text(encoding = "utf-8") or "{}"))

  # the overlay merges back over the tracked layer on read, so it is migrated alongside it, against
  # the tracked versions as they stand before this run moves them
  overlay = _migrate_local_overlay(_local_overlay_path(path), _tracked_versions(raw))

  # guard: no file on disk → nothing to migrate in it; only the overlay's walks are reported
  if raw is None:
    return overlay

  # drop every retired section the file still carries, whatever its version or content
  changed = False
  for key in RETIRED_SECTIONS:
    if key in raw:
      del raw[key]
      changed = True

  # walk every live section from its own version up to the current one
  for key, target in CURRENT_VERSIONS.items():
    section = raw.get(key, {})

    # guard: section missing from on-disk file — stamp a current-version stub and continue
    if not section:
      raw[key] = { SettingsKey.VERSION: target }
      changed = True
      continue

    # the version the section sits on, 1 when it carries no stamp
    cur = section.get(SettingsKey.VERSION, 1)

    # guard: section already at or beyond the current version — nothing to walk
    if cur >= target:
      continue

    # a section below the current version walks its ladder up to it
    raw[key] = _walk_ladder(key, section, cur, target)
    result[key] = (cur, target)
    changed = True

  # the file is rewritten only when a section was dropped, stamped or walked
  if changed:
    _atomic_write(path, raw)

  # a section walked in either layer is reported once; where both layers walked it, the tracked walk wins
  return { **overlay, **result }


def read_undetermined_sections(path: Path | str) -> list[str]:
  """
  Name the local overlay sections whose version `migrate_all` cannot tell and so leaves unmigrated.

  Such a section carries no version stamp of its own, the tracked file holds no real content for its section to take
  one from, and its own data does not settle it: it holds a value an upgrade step would rewrite although a current
  section may hold the same value. Called before `migrate_all`, the answer is exactly the set that run leaves as
  stored; the remedy for each is a version stamp in the overlay naming the version the section is written for.

  Guarantees:
    - Never creates, changes or deletes either settings file.
    - Called before `migrate_all` on the same files, names exactly the overlay sections that run leaves as stored
      for want of a version.
    - Running `migrate_all` never silences the answer: a section stays named on every later call until the overlay
      stamps it or the tracked file carries real content for the section.

  Args:
    path: Path to the tracked settings file; the sibling `.local.json` overlay is read. Either file may be missing.

  Returns:
    The undetermined section keys, in the order of `CURRENT_VERSIONS`; empty when the overlay is missing.

  Raises:
    ValueError: If the tracked file or the overlay is not valid JSON (a `json.JSONDecodeError`) or its top level is
      not a JSON object; the message of the latter names the file.
  """

  # Contract:
  # This is a pure read: it never creates, changes or deletes either settings file.

  # Contract:
  # Called before `migrate_all` on the same files, the keys it names are exactly the overlay sections
  # that run leaves as stored for want of a version.

  # Contract:
  # Running `migrate_all` never silences the answer: a section stays named on every later call
  # until the overlay stamps it or the tracked file carries real content for the section.

  path = Path(path)
  local_path = _local_overlay_path(path)

  # guard: no overlay on disk — nothing in it can stay unmigrated
  if not local_path.exists():
    return []

  # the versions the overlay inherits, read from the tracked file as `migrate_all` reads it before moving it
  tracked = migrate_root_version_to_section_version(_parse_layer(path)) if path.exists() else None
  tracked_versions = _tracked_versions(tracked)
  overlay = _parse_layer(local_path)

  # an unstamped overlay section whose version neither the tracked file nor its own data gives is undetermined
  return [
    key for key in CURRENT_VERSIONS
    if isinstance(section := overlay.get(key), dict) and SettingsKey.VERSION not in section
    and _find_unstamped_version(key, section, tracked_versions) is None
  ]


def _walk_ladder(section_key: str, section: dict, cur: int, target: int) -> dict:
  """
  Walk one section through its migration ladder from `cur` up to `target`.

  Args:
    section_key: Name of the section whose ladder is walked.
    section: Section content sitting on version `cur`.
    cur: Version the section currently sits on.
    target: Version the walk ends on.

  Returns:
    The migrated section, stamped with `target`.

  Raises:
    KeyError: If the ladder has no step for a version the walk passes through.
  """
  ladder = _migrations(section_key)

  # walk the ladder one step at a time, stamping the new version after each migration
  while cur < target:
    # guard: a gap in the ladder cannot be walked — name the section and version rather
    # than letting a bare KeyError reach the daemon
    if cur not in ladder:
      raise KeyError(f"section {section_key!r}: no migration step from version {cur} (target {target})")
    section = ladder[cur](section)
    cur += 1
    section[SettingsKey.VERSION] = cur
  return section


def _tracked_versions(raw: dict | None) -> dict[str, int | None]:
  """
  Read the version every declared section of the tracked file sits on.

  Args:
    raw: Parsed tracked settings content with any legacy root version already lifted, or `None`
      when the tracked file is missing.

  Returns:
    Mapping from every declared section key to its version: the section's own stamp, `1` for a
    section without one. For a section the file does not carry, the first rung of its ladder when
    the section is replayable, and `None` otherwise. A section holding nothing but its version stamp
    counts as not carried, replayable or not, and maps the same way.
  """

  # Domain(settings.versioning):
  # # A local overlay section without a stamp sits on the tracked section's version
  # The local overlay holds per-machine overrides of settings sections and usually carries no version
  # stamp of its own, so a section there is taken to sit on the version of the same section in the
  # tracked file. When the tracked file does not carry that section at all, or there is no tracked
  # file, the overlay section's version is unknown, and the answer depends on what its upgrade steps
  # do. A section whose every step leaves data already in the current shape unchanged is walked
  # through the whole ladder from its first step: old content is upgraded, current content stays as
  # it is. A section whose steps seed defaults or rewrite values a current section may legitimately
  # hold is never replayed from the start, because that would alter an overlay that is already up to
  # date; its version is read from the section's own content instead, and when that cannot be told it
  # is left as stored and reported for the operator to settle. For every section, replayable or not, a
  # tracked section holding nothing but its version stamp counts as absent: the explicit migration run
  # itself writes that bare stub for every section the shared file lacked, so the stamp says nothing
  # about the overlay. A replayable overlay section under such a stub replays its whole ladder from the
  # first step; any other has its version read from its own content on every run, and one that still
  # cannot be told is reported on every run, not once. Only a tracked section with real content gives
  # its version to the overlay. A walk that changes nothing leaves the overlay file untouched, and an
  # overlay section never gains a stamp.

  versions: dict[str, int | None] = {}

  # a section with content sits on its own stamp, or on 1 when it has none, as the tracked walk assumes; one the
  # file does not carry, or carries as a bare version stub, tells nothing about the overlay, which then starts from
  # the first rung when its whole ladder is safe to replay, and otherwise has its version read from its own data
  for key, current in CURRENT_VERSIONS.items():
    section = raw.get(key) if raw is not None else None
    if isinstance(section, dict) and section.keys() - { SettingsKey.VERSION }:
      versions[key] = section.get(SettingsKey.VERSION, 1)
    elif key in _REPLAYABLE_SECTIONS:
      versions[key] = min(_migrations(key), default = current)
    else:
      versions[key] = None
  return versions


def _migrate_local_overlay(
    local_path: Path,
    tracked_versions: dict[str, int | None],
) -> dict[str, tuple[int, int]]:
  """
  Drop the retired sections from the local overlay and walk its sections forward through their ladders.

  A stamped section walks from its own stamp, with the stamp advanced. An unstamped section stays unstamped
  and walks from the tracked file's version of the same section; when the tracked file gives none, the start
  comes from the overlay section's own data. A section whose version cannot be told stays as stored. The
  overlay is rewritten only when a section's content changed.

  Args:
    local_path: Path to the local overlay file. The file may be missing.
    tracked_versions: Mapping from section key to the version the tracked file's section sat on before
      this run migrated it, or `None` when the tracked file cannot give one, as for a section it does not carry
      or carries as nothing but its version stamp; an unstamped overlay section starts from the version given
      here, or from the version its own data shows when this gives `None`.

  Returns:
    Mapping from section key to `(before, after)` version tuples for every overlay section that was
    rewritten, empty when the overlay is missing or nothing changed.

  Raises:
    OSError: If the migrated overlay cannot be written back to disk.
    json.JSONDecodeError: If the overlay is not valid JSON.
    KeyError: If an overlay section's ladder has no step for a version the walk passes through.
  """
  # guard: no overlay on disk — nothing to migrate, and the overlay is never created
  if not local_path.exists():
    return {}

  # the overlay as stored, with no change recorded yet
  # waiver: stdlib encoding idiom
  raw = json.loads(local_path.read_text(encoding = "utf-8") or "{}")
  changed = False
  walked_sections: dict[str, tuple[int, int]] = {}

  # drop every retired section the overlay still carries
  for key in RETIRED_SECTIONS:
    if key in raw:
      del raw[key]
      changed = True

  # walk every section the overlay carries; an unstamped one sits on the tracked section's version
  for key, target in CURRENT_VERSIONS.items():
    section = raw.get(key)

    # guard: section absent or not an object — the overlay gains no section
    if not isinstance(section, dict):
      continue
    stamped = SettingsKey.VERSION in section
    cur = section[SettingsKey.VERSION] if stamped else _find_unstamped_version(key, section, tracked_versions)

    # guard: version unknown, or already at or beyond the current one — the section stays as stored
    if cur is None or cur >= target:
      continue
    walked = _walk_ladder(key, copy.deepcopy(section), cur, target)

    # an unstamped overlay section stays unstamped: the tracked layer owns its version
    if not stamped:
      walked.pop(SettingsKey.VERSION, None)

    # a walk that changed nothing leaves the section, and the file, as stored
    if walked == section:
      continue
    raw[key] = walked
    walked_sections[key] = ( cur, target )
    changed = True

  # the overlay is rewritten only when a section changed
  if changed:
    _atomic_write(local_path, raw)

  # the sections the walk rewrote, for the caller's report
  return walked_sections


def save_section(path: Path | str, section_key: str, section: dict, *, stamp: bool = True) -> None:
  """
  Persist one section to the tracked settings file.

  The file is rewritten atomically and the sibling local-overlay file is never touched. No
  migration is performed on the surrounding sections — schema-bridge work belongs in
  `migrate_all` (install / doctor-side), never as a side effect of save.

  Guarantees:
    - The sibling local-overlay file is never touched by this call.

  Notes:
    - A stamp claims that the migration ladder walked the content, so a section without its own
      `_version` takes the version the file's existing section sits on: the on-disk stamp when it
      has one, no stamp when the on-disk section is unstamped, and the current version only when
      the file does not carry the section yet (absent or empty).
    - A section that carries its own `_version` keeps it.
    - With stamping switched off the section is written exactly as given.

  Args:
    path: Path to the tracked settings file.
    section_key: Name of the section to store under.
    section: Section dict to persist; a version key may be added to it in place.
    stamp: Whether a section without its own `_version` receives the version described in Notes.

  Raises:
    OSError: If the tracked file or its parent directory cannot be written.
    json.JSONDecodeError: If the existing tracked file is not valid JSON.
  """

  # Contract:
  # The sibling local-overlay file is never touched by this call; only the tracked
  # file is written.

  # Domain(settings.versioning):
  # # A version stamp claims the migrations have been applied
  # A section's version stamp is a statement that the migration ladder has already carried its
  # content up to that version. Storing a section therefore never invents that claim: content
  # saved without a stamp of its own inherits the version of the section it replaces, and stays
  # unstamped when the replaced section was unstamped, so the next explicit migration still walks
  # it. Only a section the file does not hold yet, whether absent or empty, has nothing for the
  # ladder to carry forward and is stamped with the current version. A section that arrives with
  # its own stamp keeps it, and when stamping is switched off the content is stored exactly as
  # given.

  path = Path(path)
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}") if path.exists() else {}

  # an unstamped section takes the version the file's own section sits on: a stamp is a claim that the
  # ladder walked the content, so only a section the file does not carry yet is stamped current
  if stamp and SettingsKey.VERSION not in section:
    on_disk = raw.get(section_key)
    if not isinstance(on_disk, dict) or not on_disk:
      section[SettingsKey.VERSION] = CURRENT_VERSIONS.get(section_key, 1)
    elif SettingsKey.VERSION in on_disk:
      section[SettingsKey.VERSION] = on_disk[SettingsKey.VERSION]

  # the section replaces its predecessor in place, every other section stays as it was
  raw[section_key] = section
  _atomic_write(path, raw)


def save_local_section(path: Path | str, section_key: str, section: dict) -> None:
  """
  Persist one section to the gitignored local-overlay file beside the tracked settings file.

  The overlay section is written verbatim with no schema-version stamp: the section version is
  sticky to the tracked layer, so a version key in the overlay would shadow it on merge. The
  tracked file is never touched. Intended for per-machine, personal gates that must survive
  across runs without entering the shared, committed settings file.

  Guarantees:
    - The tracked settings file is never touched by this call.

  Args:
    path: Path to the tracked settings file; the sibling `.local.json` overlay is written.
    section_key: Name of the section to store under in the overlay.
    section: Section dict to persist into the overlay.

  Raises:
    OSError: If the overlay file or its parent directory cannot be written.
    json.JSONDecodeError: If the existing overlay file is not valid JSON.
  """

  # Contract:
  # The tracked settings file is never touched by this call; only the sibling
  # local-overlay file is written.

  local_path = _local_overlay_path(Path(path))
  # waiver: stdlib encoding idiom
  raw = json.loads(local_path.read_text(encoding = "utf-8") or "{}") if local_path.exists() else {}
  raw[section_key] = section
  _atomic_write(local_path, raw)


def _atomic_write(path: Path, data: dict) -> None:
  """
  Write `data` as pretty-printed JSON to `path` atomically.

  Args:
    path: Destination file path. Parent directories are created when missing.
    data: JSON-serialisable dict to write.

  Raises:
    OSError: If the destination file or its parent directory cannot be written.
    TypeError: If `data` is not JSON-serialisable.
  """
  # the shared writer keeps the file's mode and writes through a symlink to its real target
  runtime_state.atomic_write_text(path, json.dumps(data, indent = 2, sort_keys = False) + "\n")


def _cli() -> None:
  """
  Run the `migrate [path]` command of the settings migrator.

  Brings the settings file, which defaults to `.claude/lazy.settings.json`, and its local overlay to the current
  section versions. Prints a one-line summary on stdout, followed by one line per section that moved when anything
  moved; overlay-only rewrites count as moved. After the summary, prints one line per overlay section left
  unmigrated for want of a version, naming the section and the version stamp to add; those sections are found
  before the run moves anything and are not counted as up to date.

  Raises:
    SystemExit: With code 2 after a usage line on stderr when the subcommand is missing or is not `migrate`, or
      after a one-line stderr message when the path is a directory.
  """
  # guard: only the "migrate" subcommand is supported
  # waiver: argparse CLI signature, not a domain key
  if len(sys.argv) < 2 or sys.argv[1] != "migrate":
    # waiver: one-off human-facing usage message
    print("usage: lazy_settings.py migrate [path]", file = sys.stderr)
    sys.exit(2)

  # the requested file, defaulting to the repo-local settings path
  target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".claude/lazy.settings.json")

  # guard: a directory where the settings file is expected is a usage error, not a file to migrate
  if target.is_dir():
    print(f"lazy_settings.py: {target} is a directory, not a settings file", file = sys.stderr)
    sys.exit(2)

  # the overlay sections this run cannot place are named before it moves the tracked versions they inherit
  undetermined = read_undetermined_sections(target)

  # every ladder runs against the file, and the sections it moved are counted
  upgraded = migrate_all(target)

  # a section left unmigrated in the overlay is not up to date, even when its tracked side moved
  up_to_date = len(CURRENT_VERSIONS) - len(upgraded.keys() | set(undetermined))

  # one-line summary for the operator, with a per-section breakdown only when something moved
  if not upgraded:
    print(f"migrated: 0 sections ({up_to_date} up-to-date)")
  else:
    print(f"migrated: {len(upgraded)} sections ({up_to_date} up-to-date)")
    for key, (old, new) in upgraded.items():
      print(f"  {key}: v{old} -> v{new}")

  # each section left unmigrated for want of a version gets its own line naming the fix
  for key in undetermined:
    print(
        f"  unmigrated: {key} in {_local_overlay_path(target)} — it has no _version, the tracked file gives none "
        f"(its {key} section is absent or holds only a _version), and its data does not tell the version; add "
        f"\"_version\": <the version it is written for, {CURRENT_VERSIONS[key]} if current> to it and run migrate "
        f"again",
    )


if __name__ == "__main__":
  _cli()
