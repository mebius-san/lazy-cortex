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

The `_version` key is owned by tracked and never adopted from local —
migration ladders run against tracked only.

Writes go to tracked. `save_section` never touches local. Callers that
need a load → modify → save round-trip on a single layer should use
`load_tracked_section` to avoid local-overlay leaks into the tracked file.

Migration model. All read entry points (`load_section` / `load_tracked_section` /
`load_local_only_section`) are PURE reads — they never run the migration ladder
and never write to disk. Migration is an install / doctor responsibility, invoked
explicitly via `migrate_all` (called from `/lazy-core.install` / `/lazy-core.doctor`).
The daemon never migrates anything from a read path; if the on-disk schema is behind
`CURRENT_VERSIONS` the caller sees the file as-is and must surface the mismatch.
This separation prevents the daemon-self-block failure mode where an upgrade-driven
write back dirties the tracked tree and trips the daemon's own dirty-tree halt.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import tempfile
from pathlib import Path

from constants import SettingsKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


CURRENT_VERSIONS = {
  "agent_models": 1,
  "daemon": 2,
  "routines": 2,
  "experts": 1,
  "git": 1,
  "products": 1,
  "repos": 1,
  "review": 1,
  "spec": 1,
  "wiki": 1,
}

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
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from importlib import import_module
    ladder = import_module(f"lazy_settings_migrations.{mod_name}")
    return ladder.MIGRATIONS
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
  # guard: nothing to migrate when no legacy root version is present
  if SettingsKey.LEGACY_VERSION in raw:
    legacy = raw.pop(SettingsKey.LEGACY_VERSION)
    # propagate legacy version into every section that has no per-section version yet
    for v in raw.values():
      if isinstance(v, dict) and SettingsKey.VERSION not in v:
        v[SettingsKey.VERSION] = legacy
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
  stem = tracked_path.stem
  suffix = tracked_path.suffix
  return tracked_path.with_name(f"{stem}.local{suffix}")


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
  if isinstance(base, dict) and isinstance(overlay, dict):
    result = { **base }
    for k, v in overlay.items():
      # guard: tracked owns versioning — never adopt _version from local
      if k == SettingsKey.VERSION:
        continue
      if k in result:
        result[k] = _deep_merge_claude(result[k], v)
      else:
        result[k] = v
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

  Args:
    path: Path to the tracked settings file. May be a string or `Path`.
    section_key: Name of the section to load.

  Returns:
    The section dict, freshly initialised to the current version when missing from the file.

  Raises:
    json.JSONDecodeError: If the tracked file is not valid JSON.
  """
  path = Path(path)
  # guard: no tracked file yet — return a fresh section pinned to the current version
  if not path.exists():
    return { SettingsKey.VERSION: CURRENT_VERSIONS.get(section_key, 1) }
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}")
  section = raw.get(section_key, {})
  # guard: section missing from on-disk file — caller sees a fresh current-version stub
  if not section:
    return { SettingsKey.VERSION: CURRENT_VERSIONS.get(section_key, 1) }
  return section


def load_local_only_section(path: Path | str, section_key: str) -> dict:
  """
  Return the local-overlay's view of one section, or an empty dict when absent.

  No merge, no migration, no write-back. Intended for skills that want to inspect what is
  present in the personal overlay for a given section — typically audits, diagnostics, or
  wizards that surface effective configuration.

  Args:
    path: Path to the tracked settings file; the sibling `.local.json` is consulted.
    section_key: Name of the section to read from the overlay.

  Returns:
    The section dict from the overlay, or an empty dict when the overlay file does not exist
    or does not declare that section.

  Raises:
    json.JSONDecodeError: If the local overlay file is not valid JSON.
  """
  local_path = _local_overlay_path(Path(path))
  # guard: no overlay file present — caller sees an empty view
  if not local_path.exists():
    return {}
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

  Args:
    path: Path to the tracked settings file.
    section_key: Name of the section to load.

  Returns:
    The effective section dict (tracked content with local overlay applied when present).

  Raises:
    json.JSONDecodeError: If either the tracked or overlay file is not valid JSON.
  """
  path = Path(path)
  tracked = load_tracked_section(path, section_key)
  local_section = load_local_only_section(path, section_key)
  # guard: no local-overlay content — tracked view is already the effective view
  if not local_section:
    return tracked
  merged = _deep_merge_claude(tracked, local_section)
  # guard: top-level merge of two dict layers always yields a dict
  return merged if isinstance(merged, dict) else {}


def migrate_all(path: Path | str) -> dict[str, tuple[int, int]]:
  """
  Run the migration ladder for every section declared in `CURRENT_VERSIONS`.

  Install / doctor-side entry point — invoked ONLY by `/lazy-core.install`,
  `/lazy-core.doctor`, or the CLI `lazy_settings.py migrate` subcommand. The daemon
  never calls this from a read path: migration is an explicit, operator-triggered action,
  never a side effect of reading settings (Bug 104).

  Walks the file, applies every section's ladder, writes the migrated content back to
  disk atomically when any upgrade ran.

  Args:
    path: Path to the tracked settings file. The file may be missing; in that case every
      section is treated as already at the current version (the result map is empty).

  Returns:
    Mapping from section key to `(before, after)` version tuples for sections that were
    upgraded. Sections already at the target version are omitted from the result.

  Raises:
    OSError: If the migrated tracked file cannot be written back to disk.
    json.JSONDecodeError: If the tracked file is not valid JSON.
  """
  path = Path(path)
  result: dict[str, tuple[int, int]] = {}
  # guard: no file on disk → nothing to migrate; every section is implicitly at current
  if not path.exists():
    return result
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}")
  raw = migrate_root_version_to_section_version(raw)
  changed = False
  for k, target in CURRENT_VERSIONS.items():
    section = raw.get(k, {})
    # guard: section missing from on-disk file — stamp a current-version stub and continue
    if not section:
      raw[k] = { SettingsKey.VERSION: target }
      changed = True
      continue
    cur = section.get(SettingsKey.VERSION, 1)
    # guard: section already at or beyond the current version — nothing to walk
    if cur >= target:
      continue
    pre = cur
    ladder = _migrations(k)
    # walk the ladder one step at a time, stamping the new version after each migration
    while cur < target:
      section = ladder[cur](section)
      cur += 1
      section[SettingsKey.VERSION] = cur
    raw[k] = section
    result[k] = (pre, cur)
    changed = True
  if changed:
    _atomic_write(path, raw)
  return result


def save_section(path: Path | str, section_key: str, section: dict) -> None:
  """
  Persist one section to the tracked settings file.

  The section is stamped with the current schema version when no section version is present,
  and the file is rewritten atomically. The sibling local-overlay file is never touched. No
  migration is performed on the surrounding sections — schema-bridge work belongs in
  `migrate_all` (install / doctor-side), never as a side effect of save.

  Args:
    path: Path to the tracked settings file.
    section_key: Name of the section to store under.
    section: Section dict to persist.

  Raises:
    OSError: If the tracked file or its parent directory cannot be written.
    json.JSONDecodeError: If the existing tracked file is not valid JSON.
  """
  path = Path(path)
  # waiver: stdlib encoding idiom
  raw = json.loads(path.read_text(encoding = "utf-8") or "{}") if path.exists() else {}
  section.setdefault(SettingsKey.VERSION, CURRENT_VERSIONS.get(section_key, 1))
  raw[section_key] = section
  _atomic_write(path, raw)

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
  path.parent.mkdir(parents = True, exist_ok = True)
  # waiver: temp-file naming idiom, not a domain constant
  fd, tmp = tempfile.mkstemp(dir = path.parent, prefix = ".lazy_settings_", suffix = ".json")
  # noinspection PyBroadException
  try:
    # waiver: stdlib file-mode idiom
    with os.fdopen(fd, "w") as f:
      json.dump(data, f, indent = 2, sort_keys = False)
      f.write("\n")
    os.replace(tmp, path)
  except Exception:
    # best-effort cleanup of the temp file before re-raising the original failure
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise


def _cli() -> None:
  """
  Run the settings-migration command-line entry point.

  Reads the optional `migrate [path]` arguments, runs every section's
  migration ladder, and prints a one-line summary of upgraded sections.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import sys
  # guard: only the "migrate" subcommand is supported
  # waiver: argparse CLI signature, not a domain key
  if len(sys.argv) < 2 or sys.argv[1] != "migrate":
    # waiver: one-off human-facing usage message
    print("usage: lazy_settings.py migrate [path]", file = sys.stderr)
    sys.exit(2)
  target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".claude/lazy.settings.json")
  upgraded = migrate_all(target)
  total = len(CURRENT_VERSIONS)
  up_to_date = total - len(upgraded)
  if not upgraded:
    print(f"migrated: 0 sections ({up_to_date} up-to-date)")
  else:
    print(f"migrated: {len(upgraded)} sections ({up_to_date} up-to-date)")
    for k, (a, b) in upgraded.items():
      print(f"  {k}: v{a} -> v{b}")


if __name__ == "__main__":
  _cli()
