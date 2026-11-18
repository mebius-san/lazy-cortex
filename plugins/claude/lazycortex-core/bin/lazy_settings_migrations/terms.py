"""
Migrations for the `terms` section of `lazy.settings.json`.

v1 -> v2 (`MIGRATIONS[1]`) turns each scope's single dictionary file into a dictionary directory: the
directory takes the file's path without its markdown suffix, or the path with a `.terms` suffix when the file
has none, and the scope's `file` key is replaced by `dir`. The old file is kept as the scope's `legacy_file`,
and its entry is dropped from the scope's `source_exclude` list, since it no longer is the dictionary. A scope
that already names a directory, and a scope that names no file, are left exactly as found, as is a section with
no scope map; re-running the step changes nothing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SCOPES_KEY = "scopes"
_VERSION_KEY = "_version"
_FILE_KEY = "file"
_DIR_KEY = "dir"
_LEGACY_FILE_KEY = "legacy_file"
_SOURCE_EXCLUDE_KEY = "source_exclude"

# The suffix a dictionary file drops to name its directory.
_MD_SUFFIX = ".md"
# The suffix a dictionary file without the markdown suffix gains to name its directory.
_DIR_SUFFIX = ".terms"


def _scope_file_to_dir(cfg: dict) -> dict:
  """
  Move one scope from its dictionary file to a dictionary directory.

  Args:
    cfg: One scope config from `terms.scopes`.

  Returns:
    The scope with its dictionary directory, legacy file and source exclusions settled; the scope as found when
    it already names a directory or names no file.
  """
  legacy = cfg.get(_FILE_KEY)

  # guard: the operator already named a directory, or the scope names no file to move from
  if _DIR_KEY in cfg or not isinstance(legacy, str) or not legacy:
    return cfg

  # the directory sits where the file did, without its markdown suffix
  moved = { key: value for key, value in cfg.items() if key != _FILE_KEY }
  moved[_DIR_KEY] = legacy.removesuffix(_MD_SUFFIX) if legacy.endswith(_MD_SUFFIX) else legacy + _DIR_SUFFIX
  moved[_LEGACY_FILE_KEY] = legacy

  # the old file no longer needs excluding from the term sources once it stops being the dictionary
  if isinstance(excluded := cfg.get(_SOURCE_EXCLUDE_KEY), list):
    moved[_SOURCE_EXCLUDE_KEY] = [ glob for glob in excluded if glob != legacy ]
  return moved


def _migrate_file_to_dir(data: dict) -> dict:
  """
  Apply the v1 -> v2 move of every scope's dictionary file to a dictionary directory.

  Args:
    data: The `terms` section content at v1.

  Returns:
    The section at v2, every dict scope migrated; the section as found when it carries no scope map.
  """

  # Domain(settings.versioning):
  # # A terms dictionary file becomes a dictionary directory
  # A terms scope used to keep its whole dictionary in one file; it now keeps one file per term in a dictionary
  # directory. The upgrade derives that directory from the file the scope already names: the directory sits at
  # the file's path without its markdown suffix, and a file that has no such suffix gets a `.terms` suffix
  # appended instead, so the directory never collides with the file it replaces. The old file is not deleted
  # and not forgotten: it is kept as a legacy entry, so that a later migration step can retire it once its
  # terms have been carried over. It also stops being excluded from the scope's term sources, because it is no
  # longer the dictionary. A scope that already names a directory is left exactly as found, even when it still
  # names a file: the directory is the operator's choice and is never rebuilt from the file. A scope that names
  # no file has nothing to move. Re-running the step changes nothing.

  # guard: no scopes, or a malformed section — nothing to move
  if not isinstance(scopes := data.get(_SCOPES_KEY), dict):
    return data

  # rebuild the scope map, passing the version sentinel and non-dict values through as found
  return { **data, _SCOPES_KEY: {
    key: _scope_file_to_dir(cfg) if key != _VERSION_KEY and isinstance(cfg, dict) else cfg
    for key, cfg in scopes.items()
  } }


MIGRATIONS = {
  1: _migrate_file_to_dir,
}
