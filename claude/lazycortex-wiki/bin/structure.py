from __future__ import annotations

import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# the map's own path, fixed by convention and never configurable
MAP_PATH = "docs/structure.md"


# ----------------------------------------------------------------------------------------
class StructureWatch:
  """
  Derives the path filter and the grouping globs the structure-scan routines must carry.

  The three structure-scan routines dispatch one expert job per watched item, and the job
  is paid for before the expert can judge the path irrelevant. What the routines watch is
  therefore a cost decision, not a preference, and it is derived from the structure section
  rather than authored: the map's exclusions become a pathspec the watch never enumerates,
  and the depth classes become the directory globs that collapse a directory-wide change
  into one job.

  Guarantees:
    - The map's own path is excluded whatever the settings say.
    - The derivation is a pure function of the structure section — two calls over the same
      settings return equal results, and nothing is read from the environment.
  """

  # Contract:
  # The returned `path_filter` ALWAYS excludes the map's own path, whether or not the
  # settings list it. A caller may add exclusions through the settings; no caller can
  # remove this one.

  # Domain(wiki.structure):
  # # What the structure map's watch is allowed to see
  # The map is kept current by watching the repository for files appearing, disappearing and
  # moving. Two kinds of path must never reach that watch. The first is the map itself: the
  # curator commits the map, so a watch that sees it is woken by its own output and never
  # settles. The second is any tree the operator has declared the map does not describe —
  # watching it buys nothing, because the only possible answer is that there is nothing to do.
  # The first kind is a property of the system and is subtracted unconditionally; the second is
  # the operator's declaration and is read from it. Beyond what is watched, there is the
  # question of how much work one observation is. A directory moved whole is one change to the
  # map, not one per file inside it, so paths that belong to the same described directory are
  # answered together as a single unit of work.

  _SETTINGS_PATH = ".claude/lazy.settings.json"
  _ENCODING = "utf-8"
  _STRUCTURE_KEY = "structure"
  _EXCLUDE_KEY = "exclude"
  _PROFILES_KEY = "depth_profiles"
  _PATHS_KEY = "paths"
  _PATH_FILTER_KEY = "path_filter"
  _GROUP_GLOBS_KEY = "group_globs"
  _EXCLUDE_MAGIC = ":(exclude)"

  def __init__(self, *, repo: Path | str) -> None:
    """
    Bind the deriver to one repository root.

    Args:
      repo: Absolute path to the repository root that owns `.claude/lazy.settings.json`.
    """
    # the root every relative path below resolves against
    self.repo: Path = Path(repo)

  # ------------------------------------------------------------------
  def section(self) -> dict:
    """
    Return the repository's structure section.

    Returns:
      The section dict, or an empty dict when the settings file is absent, unreadable, or
      carries no structure section.
    """
    settings_file = self.repo / self._SETTINGS_PATH

    # guard: settings file does not exist — nothing is configured
    if not settings_file.is_file():
      return {}

    # an unreadable or malformed file is the same "unconfigured" case as an absent one; the
    # derivation still returns its mandatory floor, which is the point of the floor
    try:
      with settings_file.open(encoding = self._ENCODING) as fh:
        data = json.load(fh)
    except (OSError, json.JSONDecodeError):
      return {}
    section = data.get(self._STRUCTURE_KEY, {})

    # guard: section absent or malformed — treat as unconfigured
    if not isinstance(section, dict):
      return {}
    return section

  # ------------------------------------------------------------------
  def path_filter(self) -> list[str]:
    """
    Return the git pathspec the structure-scan routines must watch through.

    Returns:
      One `:(exclude)<glob>` entry per excluded path, the map's own path first, in a stable
      order with no duplicates.
    """
    # the map leads the list whether or not the settings mention it — a caller may add
    # exclusions, never drop this one
    globs = [ MAP_PATH ]
    configured = self.section().get(self._EXCLUDE_KEY)

    # collect the operator's own exclusions behind it, skipping anything malformed
    if isinstance(configured, list):
      for entry in configured:
        if isinstance(entry, str) and entry.strip() and entry not in globs:
          globs.append(entry)
    return [ f"{self._EXCLUDE_MAGIC}{glob}" for glob in globs ]

  # ------------------------------------------------------------------
  def group_globs(self) -> list[str]:
    """
    Return the directory globs a structure-scan routine groups its items by.

    Returns:
      Every glob declared by any depth class, sorted and deduplicated; empty when no class
      is configured.
    """
    profiles = self.section().get(self._PROFILES_KEY)

    # guard: no classes configured — nothing to group by, every item stays on its own
    if not isinstance(profiles, dict):
      return []

    # one class's globs describe one slice of the tree; the union is what the map covers
    globs: set[str] = set()
    for cfg in profiles.values():
      # guard: a malformed class entry declares no globs
      if not isinstance(cfg, dict):
        continue
      paths = cfg.get(self._PATHS_KEY)
      if isinstance(paths, list):
        globs.update(entry for entry in paths if isinstance(entry, str) and entry.strip())
    return sorted(globs)

  # ------------------------------------------------------------------
  def expected(self) -> dict:
    """
    Return the derived routine keys as one mapping.

    Returns:
      A dict carrying `path_filter`, and `group_globs` only when at least one depth class
      declares a glob — the routine config rejects an empty glob list, and a routine that
      declares none groups by each changed file's own directory anyway.
    """
    # the shape a caller splices straight into a routine registration
    derived = { self._PATH_FILTER_KEY: self.path_filter() }
    globs = self.group_globs()

    # an empty set is not a value the routine schema accepts, and omitting the key is what
    # asks for the default grouping rather than a wider one
    if globs:
      derived[self._GROUP_GLOBS_KEY] = globs
    return derived

  # ------------------------------------------------------------------
  def drift(self, registered: dict) -> dict:
    """
    Compare one registered routine config against the derivation and report the difference.

    Args:
      registered: The routine's config dict as it stands in the settings file.

    Returns:
      A dict naming each derived key whose registered value differs, carrying the expected
      and the actual value; empty when the routine carries exactly what is derived.
    """
    expected = self.expected()

    # a registered value counts as matching only when it equals the derivation exactly —
    # a superset is drift too, because it watches trees the operator has excluded
    findings = {}
    for key, want in expected.items():
      got = registered.get(key)
      if got != want:
        findings[key] = { "expected": want, "actual": got }

    # a routine carrying grouping globs the section no longer declares is drift in the other
    # direction: nothing derives them any more, so the wider unit is stale rather than chosen
    if self._GROUP_GLOBS_KEY not in expected and registered.get(self._GROUP_GLOBS_KEY):
      findings[self._GROUP_GLOBS_KEY] = {
        "expected": None, "actual": registered.get(self._GROUP_GLOBS_KEY),
      }
    return findings
