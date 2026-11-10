from __future__ import annotations

import json
import posixpath
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# the map's own path, fixed by convention and never configurable
MAP_PATH = "docs/structure.md"

# the depth of a path whose directory no depth profile claims
UNCLASSIFIED = "unclassified"

# Resolution field names: the resolved entries, each entry's path and depth, and whether the map exists.
RESOLVE_PATHS       = "paths"
RESOLVE_PATH        = "path"
RESOLVE_DEPTH       = "depth"
RESOLVE_MAP_PRESENT = "map_present"


# ----------------------------------------------------------------------------------------
class StructureResolveError(Exception):
  """
  Error raised when a resolution cannot read the repository's tracked files.
  """


# ----------------------------------------------------------------------------------------
class StructureWatch:
  """
  Derives the path filter the structure-scan routines must carry.

  The three structure-scan routines dispatch one expert job per tick carrying every changed
  path, and the job is paid for before the expert can judge a path irrelevant. What the
  routines watch is therefore a cost decision, not a preference, and it is derived from the
  structure section rather than authored: the map's exclusions become a pathspec the watch
  never enumerates. The unit of work is not derived at all — the routines run in the
  runtime's default whole-list mode, so a registration that still carries a grouping key is
  reported as drift.

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
  # question of how much work one observation is. Everything one tick observed is answered
  # together as a single unit of work: a directory moved whole is one change to the map, not
  # one per file inside it, and a wave of unrelated changes is still one reading of the tree.

  # repo-relative path of the settings file the structure section is read from
  _SETTINGS_PATH = ".claude/lazy.settings.json"
  # encoding the settings file is read with
  _ENCODING = "utf-8"
  # settings key of the structure section
  _STRUCTURE_KEY = "structure"
  # structure-section key listing the operator's exclusion globs
  _EXCLUDE_KEY = "exclude"
  # routine-registration key carrying the watched pathspec
  _PATH_FILTER_KEY = "path_filter"
  # git pathspec magic that turns a glob into an exclusion
  _EXCLUDE_MAGIC = ":(exclude)"
  # keys a registration must not carry: the retired one and the one whose default is wanted
  _STALE_KEYS = ( "group_globs", "group" )

  def __init__(self, *, repo: Path | str) -> None:
    """
    Bind the deriver to one repository root.

    Args:
      repo: Absolute path to the repository root that owns `.claude/lazy.settings.json`.
    """
    # the root every relative path below resolves against
    self.repo: Path = Path(repo)

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

  def excluded_globs(self) -> list[str]:
    """
    Return the globs of the paths the structure map does not describe.

    Guarantees:
      - The map's own path is always first, whatever the settings say.
      - The list has no duplicates and holds only non-blank strings.

    Returns:
      The map's own path followed by the operator's configured exclusions.
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
    return globs

  def is_excluded(self, rel: str) -> bool:
    """
    Tell whether a path is one the structure map does not describe.

    Args:
      rel: Repo-relative path.

    Returns:
      True when the path matches any excluded glob, the map's own path included.
    """
    matcher = _scope.GlobMatcher()
    return any(matcher.match(rel, glob) for glob in self.excluded_globs())

  def path_filter(self) -> list[str]:
    """
    Return the git pathspec the structure-scan routines must watch through.

    Returns:
      One `:(exclude)<glob>` entry per excluded path, the map's own path first, in a stable
      order with no duplicates.
    """
    return [ f"{self._EXCLUDE_MAGIC}{glob}" for glob in self.excluded_globs() ]

  def expected(self) -> dict:
    """
    Return the derived routine keys as one mapping.

    Returns:
      A dict carrying `path_filter` and nothing else — the unit of work is the runtime's
      default and is never registered.
    """
    # the shape a caller splices straight into a routine registration
    return { self._PATH_FILTER_KEY: self.path_filter() }

  def drift(self, registered: dict) -> dict:
    """
    Compare one registered routine config against the derivation and report the difference.

    Args:
      registered: The routine's config dict as it stands in the settings file.

    Returns:
      A dict naming each derived key whose registered value differs, and each grouping key
      the registration still carries, each carrying the expected and the actual value; empty
      when the routine carries exactly what is derived.
    """
    expected = self.expected()

    # a registered value counts as matching only when it equals the derivation exactly —
    # a superset is drift too, because it watches trees the operator has excluded
    findings = {}
    for key, want in expected.items():
      got = registered.get(key)
      if got != want:
        findings[key] = { "expected": want, "actual": got }

    # a routine carrying a grouping key is drift in the other direction: the routines want
    # the default whole-list unit, so any registered unit — the retired key or the live one,
    # whatever its value — is stale rather than chosen
    for key in self._STALE_KEYS:
      if key in registered:
        findings[key] = { "expected": None, "actual": registered[key] }
    return findings


# ----------------------------------------------------------------------------------------
class StructureProfiles:
  """
  Resolver of the depth at which the structure map describes a path.

  Callers hand it paths, or ask for the whole tree, and get each described path back with the depth
  of its directory's class. Paths the map does not describe never appear in a resolution.

  Guarantees:
    - Every depth in a resolution is one of the configured profile depths or `unclassified`.
    - A directory takes the depth of the first configured profile, in the settings' key order, any of whose
      globs matches a tracked, non-excluded file anywhere under the directory; no match gives `unclassified`.
  """

  # Contract:
  # Every depth in a resolution is one of the depths of the configured depth profiles or `unclassified`.

  # Contract:
  # A directory's depth is that of the first configured depth profile, in the settings' key order, any of
  # whose globs matches a tracked, non-excluded file anywhere under the directory; a directory that no
  # profile matches is `unclassified`.

  # structure-section key of the depth profiles, and the keys of one profile
  _PROFILES_KEY = "depth_profiles"
  _PROFILE_PATHS_KEY = "paths"
  _PROFILE_DEPTH_KEY = "depth"

  def __init__(self, *, watch: StructureWatch) -> None:
    """
    Bind the resolver to the repository a watch reads its structure section from.

    Args:
      watch: The structure watch of the repository, the source of its settings and exclusions.
    """
    # the source of the settings, the exclusions and the repository root
    self._watch = watch

    # each well-formed profile as its depth and globs, in the settings' key order
    configured = watch.section().get(self._PROFILES_KEY)
    self._profiles: list[tuple[str, list[str]]] = [
      (
        str(profile[self._PROFILE_DEPTH_KEY]),
        [ glob for glob in profile.get(self._PROFILE_PATHS_KEY) or [] if isinstance(glob, str) ],
      )
      for profile in ( configured.values() if isinstance(configured, dict) else [] )
      if isinstance(profile, dict) and isinstance(profile.get(self._PROFILE_DEPTH_KEY), str)
    ]

  def resolve(self, paths: list[str]) -> list[dict]:
    """
    Resolve the depth of each path the map describes.

    Guarantees:
      - A path the map does not describe, the map's own path and any `structure.exclude` match, is never returned.
      - A path takes the depth of its directory: itself when it is a directory on disk, otherwise its parent.
      - When the tracked files cannot be listed, `StructureResolveError` is raised and nothing is guessed.

    Args:
      paths: Repo-relative paths, in the order they are reported.

    Returns:
      One `{path, depth}` entry per path the map describes, in the given order.

    Raises:
      StructureResolveError: When the repository's tracked files cannot be listed.
    """

    # Contract:
    # A path the map does not describe, meaning the map's own path or one matching a `structure.exclude` glob,
    # is never returned.

    # Contract:
    # A path takes the depth of its directory: the path itself when it is a directory on disk, otherwise its
    # parent directory.

    # Contract:
    # When the tracked files cannot be listed, `StructureResolveError` is raised and nothing is guessed.

    # classify every directory before looking at any path
    classes, _dirs = self._classify()

    # a path that is a directory is its own directory; any other path takes its parent's
    resolved: list[dict] = []
    for path in paths:
      # guard: a path the map does not describe is never resolved
      if self._watch.is_excluded(path):
        continue
      directory = path.rstrip("/") if (self._watch.repo / path).is_dir() else posixpath.dirname(path)
      resolved.append({ RESOLVE_PATH: path, RESOLVE_DEPTH: classes.get(directory, UNCLASSIFIED) })
    return resolved

  def resolve_all(self) -> list[dict]:
    """
    Resolve the depth of every directory the map describes.

    Guarantees:
      - A directory holding no file the map describes is never returned.
      - When the tracked files cannot be listed, `StructureResolveError` is raised and nothing is guessed.

    Returns:
      One `{path, depth}` entry per directory holding a described file, sorted by path; the repository
      root is not listed.

    Raises:
      StructureResolveError: When the repository's tracked files cannot be listed.
    """

    # Contract:
    # A directory holding no file the map describes is never returned.

    # Contract:
    # When the tracked files cannot be listed, `StructureResolveError` is raised and nothing is guessed.

    # classify every directory, then list those holding a described file
    classes, dirs = self._classify()
    return [ { RESOLVE_PATH: directory, RESOLVE_DEPTH: classes.get(directory, UNCLASSIFIED) }
             for directory in sorted(dirs) if directory ]

  def _classify(self) -> tuple[dict[str, str], set[str]]:
    """
    Classify every directory that holds a described file.

    Returns:
      The depth of every classed directory, by repo-relative directory path (the root as an empty
      string), and the set of every directory holding a described file at any depth below it.

    Raises:
      StructureResolveError: When the repository's tracked files cannot be listed.
    """

    # Domain(wiki.structure):
    # # Which depth a part of the tree is described at
    # The structure map describes each part of the tree at the depth of a class the operator
    # configured, and a class belongs to a directory, not to a single file. A directory takes the
    # first configured class, in the order the classes are listed, that names any described file
    # anywhere below it. A file, and the line of the directory that holds it, are described at
    # that directory's depth; a path that is itself a directory uses its own class. A directory
    # no class names is unclassified: its line reads like a directory-only class, yet its files
    # may still earn lines of their own. Files the map does not describe neither earn a class nor
    # give one to the directories above them. This rule lives in one place only, and every
    # describer of the map (the incremental curator, the full rebuild and the audit) takes its
    # depths from it, so they cannot disagree about how deep any part of the tree is described.

    # every directory holding a described file, and the earliest class any described file under it names
    best: dict[str, int] = {}
    dirs: set[str] = set()
    matcher = _scope.GlobMatcher()
    for rel in self._tracked_files():
      # guard: a file the map does not describe classes nothing
      if self._watch.is_excluded(rel):
        continue
      rank = next(
        (
          index for index, (_depth, globs) in enumerate(self._profiles)
          if any(matcher.match(rel, glob) for glob in globs)
        ),
        None,
      )

      # the file counts for every directory above it, up to the root
      directory = posixpath.dirname(rel)
      while True:
        dirs.add(directory)
        if rank is not None and rank < best.get(directory, len(self._profiles)):
          best[directory] = rank
        if not directory:
          break
        directory = posixpath.dirname(directory)
    return { directory: self._profiles[rank][0] for directory, rank in best.items() }, dirs

  def _tracked_files(self) -> list[str]:
    """
    List the repository's tracked files.

    Returns:
      Repo-relative POSIX paths of every tracked file.

    Raises:
      StructureResolveError: When git cannot list them.
    """

    # the index is the tree the map describes; a failure to read it is reported, never guessed at
    try:
      listed = subprocess.run(
        [ "git", "ls-files", "-z" ], cwd = str(self._watch.repo), capture_output = True, check = False,
      )
    except OSError as error:
      raise StructureResolveError(f"git ls-files failed: {error}") from error

    # guard: git answered with an error — the tracked tree is unknown
    if listed.returncode != 0:
      raise StructureResolveError(f"git ls-files failed: {listed.stderr.decode(errors = 'replace').strip()}")
    return [ rel for rel in listed.stdout.decode().split("\0") if rel ]
