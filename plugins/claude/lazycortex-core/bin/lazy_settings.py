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
  "terms": 1,
  "wiki": 3,
}
# Sections no plugin reads any more; the migration ladder deletes them from the file
RETIRED_SECTIONS = ( "repos", )


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
  mod_name = section_key.replace(".", "_").replace("-", "_")
  try:
    return import_module(f"lazy_settings_migrations.{mod_name}").MIGRATIONS
  except ModuleNotFoundError:
    return {}


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

  Args:
    path: Path to the tracked settings file. May be a string or `Path`.
    section_key: Name of the section to load.

  Returns:
    The section dict, freshly initialised to the current version when missing from the file.

  Raises:
    json.JSONDecodeError: If the tracked file is not valid JSON.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  path = Path(path)

  # guard: no tracked file yet — return a fresh section pinned to the current version
  if not path.exists():
    return { SettingsKey.VERSION: CURRENT_VERSIONS.get(section_key, 1) }

  # the section as the tracked file stores it
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}")
  section = raw.get(section_key, {})

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

  Args:
    path: Path to the tracked settings file. May be a string or `Path`.
    section_key: Name of the section to load.

  Returns:
    The section dict as stored, or `None` when the file does not exist or does not carry the key.

  Raises:
    json.JSONDecodeError: If the tracked file is not valid JSON.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  path = Path(path)

  # guard: no tracked file — the section is absent
  if not path.exists():
    return None

  # the section exactly as stored, `None` when the file does not carry it
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}")
  return raw.get(section_key)


def load_local_only_section(path: Path | str, section_key: str) -> dict:
  """
  Return the local-overlay's view of one section, or an empty dict when absent.

  No merge, no migration, no write-back. Intended for skills that want to inspect what is
  present in the personal overlay for a given section — typically audits, diagnostics, or
  wizards that surface effective configuration.

  Guarantees:
    - Never writes to disk and never runs a migration ladder; this is a pure read of
      whatever is already on disk.

  Args:
    path: Path to the tracked settings file; the sibling `.local.json` is consulted.
    section_key: Name of the section to read from the overlay.

  Returns:
    The section dict from the overlay, or an empty dict when the overlay file does not exist
    or does not declare that section.

  Raises:
    json.JSONDecodeError: If the local overlay file is not valid JSON.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

  local_path = _local_overlay_path(Path(path))

  # guard: no overlay file present — caller sees an empty view
  if not local_path.exists():
    return {}

  # the overlay's own view of the section, empty when it does not carry it
  # waiver: stdlib encoding idiom
  raw = json.loads(local_path.read_text(encoding = "utf-8") or "{}")
  return raw.get(section_key, {}) or {}


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

  Args:
    path: Path to the tracked settings file.
    section_key: Name of the section to load.

  Returns:
    The effective section dict (tracked content with local overlay applied when present).

  Raises:
    json.JSONDecodeError: If either the tracked or overlay file is not valid JSON.
  """

  # Contract:
  # Never writes to disk and never runs a migration ladder; this function is a pure
  # read of whatever is already on disk.

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
  before this run migrated it (`1` when that section carries no stamp, the current version when it is
  absent or empty), and stays unstamped.

  Guarantees:
    - The sibling local overlay is never created by this call.
    - The overlay never gains a section or a version stamp it did not already carry.
    - The overlay is rewritten only when something in it changed.

  Args:
    path: Path to the tracked settings file. The file may be missing; in that case the tracked
      sections are treated as already at the current version, so no unstamped overlay section is
      walked, the overlay is still migrated, and the result map is empty.

  Returns:
    Mapping from section key to `(before, after)` version tuples for tracked sections that were
    upgraded. Sections already at the target version are omitted; overlay upgrades are not reported.

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
  _migrate_local_overlay(_local_overlay_path(path), _tracked_versions(raw))

  # guard: no file on disk → nothing to migrate; every section is implicitly at current
  if raw is None:
    return result

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
  return result


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


def _tracked_versions(raw: dict | None) -> dict[str, int]:
  """
  Read the version every declared section of the tracked file sits on.

  Args:
    raw: Parsed tracked settings content with any legacy root version already lifted, or `None`
      when the tracked file is missing.

  Returns:
    Mapping from every declared section key to its version: the section's own stamp, `1` for a
    section without one, and the current version for a section the file does not carry.
  """
  versions = dict(CURRENT_VERSIONS)

  # guard: no tracked file — every section is implicitly at current
  if raw is None:
    return versions

  # a section the file carries sits on its own stamp, or on 1 when it has none, as the tracked walk assumes
  for key in CURRENT_VERSIONS:
    section = raw.get(key)
    if isinstance(section, dict) and section:
      versions[key] = section.get(SettingsKey.VERSION, 1)
  return versions


def _migrate_local_overlay(local_path: Path, tracked_versions: dict[str, int]) -> None:
  """
  Drop the retired sections from the local overlay and walk its sections forward through their ladders.

  A stamped section walks from its own stamp, with the stamp advanced. An unstamped section walks from
  the tracked file's version of the same section and stays unstamped.

  Args:
    local_path: Path to the local overlay file. The file may be missing.
    tracked_versions: Mapping from section key to the version the tracked file's section sat on before
      this run migrated it; it gives the starting version of each unstamped overlay section.

  Raises:
    OSError: If the migrated overlay cannot be written back to disk.
    json.JSONDecodeError: If the overlay is not valid JSON.
    KeyError: If an overlay section's ladder has no step for a version the walk passes through.
  """
  # guard: no overlay on disk — nothing to migrate, and the overlay is never created
  if not local_path.exists():
    return

  # the overlay as stored, with no change recorded yet
  # waiver: stdlib encoding idiom
  raw = json.loads(local_path.read_text(encoding = "utf-8") or "{}")
  changed = False

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
    cur = section[SettingsKey.VERSION] if stamped else tracked_versions[key]

    # guard: section already at or beyond the current version — nothing to walk
    if cur >= target:
      continue
    walked = _walk_ladder(key, section, cur, target)

    # an unstamped overlay section stays unstamped: the tracked layer owns its version
    if not stamped:
      walked.pop(SettingsKey.VERSION, None)
    raw[key] = walked
    changed = True

  # the overlay is rewritten only when a section was walked
  if changed:
    _atomic_write(local_path, raw)


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
  Run the settings-migration command-line entry point.

  Reads the optional `migrate [path]` arguments, runs every section's
  migration ladder, and prints a one-line summary of upgraded sections.
  """
  # guard: only the "migrate" subcommand is supported
  # waiver: argparse CLI signature, not a domain key
  if len(sys.argv) < 2 or sys.argv[1] != "migrate":
    # waiver: one-off human-facing usage message
    print("usage: lazy_settings.py migrate [path]", file = sys.stderr)
    sys.exit(2)

  # run every ladder against the requested file, defaulting to the repo-local settings path
  target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".claude/lazy.settings.json")
  upgraded = migrate_all(target)
  up_to_date = len(CURRENT_VERSIONS) - len(upgraded)

  # one-line summary for the operator, with a per-section breakdown only when something moved
  if not upgraded:
    print(f"migrated: 0 sections ({up_to_date} up-to-date)")
  else:
    print(f"migrated: {len(upgraded)} sections ({up_to_date} up-to-date)")
    for key, (old, new) in upgraded.items():
      print(f"  {key}: v{old} -> v{new}")


if __name__ == "__main__":
  _cli()
