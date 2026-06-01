"""
Scope resolution for lazycortex-wiki.

Reads `wiki.scopes` from `.claude/lazy.settings.json` in the target repo
and provides two public operations:

- `resolve_scope_by_path` — map a file path to the first matching scope.
- `iter_nodes` — enumerate all files that belong to a given scope config.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class GlobMatcher:
  """
  Shell-style glob matcher with path-aware separator semantics.

  `PurePath.match` in Python 3.12 has inconsistent `**` semantics across
  versions and does not reliably match zero path components.  `fnmatch.fnmatch`
  treats every `*` as crossing `/`, so `src/*.py` wrongly matches `src/sub/a.py`.
  This class compiles each pattern to a regex where a single `*` → `[^/]*`
  (does NOT cross `/`) and `**` → zero or more full path components.

  Every pattern (with or without `**`) is compiled to a regex once and cached.
  """

  def __init__(self) -> None:
    """
    Initialise the matcher with an empty compiled-pattern cache.
    """
    self._cache: dict[str, re.Pattern] = {}

  def match(self, rel_posix: str, pattern: str) -> bool:
    """
    Return True when `rel_posix` matches `pattern` under shell glob semantics.

    A single `*` matches within one path component (does not cross `/`); `**`
    matches zero or more whole components.  All patterns route through the same
    regex compiler so single-`*` patterns never leak across directory boundaries.

    Args:
      rel_posix: Repo-relative POSIX path string (no leading `/`).
      pattern: Shell glob pattern; `**` matches zero or more path components.

    Returns:
      True on a match, False otherwise.
    """
    # guard: compile and cache the regex on first use for this pattern
    if pattern not in self._cache:
      self._cache[pattern] = self._compile(pattern)
    return bool(self._cache[pattern].match(rel_posix))

  def _compile(self, pattern: str) -> re.Pattern:
    """
    Compile a shell glob pattern to a `re.Pattern` with path-aware separators.

    A single `*` → `[^/]*` (does not cross `/`); `?` → `[^/]`; `**` expands to
    "any sequence of characters including `/`" (i.e. `.*`).  Leading `**/` and
    trailing `/**` are special-cased to allow zero-component matches so that
    `**/*.md` matches both `readme.md` and `docs/readme.md`.

    Args:
      pattern: Shell glob pattern; may or may not contain `**`.

    Returns:
      Compiled regular expression that implements the glob semantics.
    """
    # Split on ** and escape/translate each non-** segment
    parts = pattern.split("**")
    segs: list[str] = []
    for part in parts:
      escaped = re.escape(part)
      # waiver: re.escape produces raw-string literals; replace back glob chars
      escaped = escaped.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
      segs.append(escaped)
    regex = ".*".join(segs)
    # Normalise /.*/ → zero or more path components (includes bare /)
    regex = regex.replace("/.*/" , "(?:/|/.*/)")
    # Normalise leading .*/ → optional (handles **/*.md matching top-level files)
    if regex.startswith(".*/"):
      regex = "(?:.*/)?" + regex[3:]
    # Normalise trailing /.* → optional trailing slash+anything
    if regex.endswith("/.*"):
      regex = regex[:-3] + "(?:/.*)?"
    return re.compile("^" + regex + "$")


# ----------------------------------------------------------------------------------------
class ScopeResolver:
  """
  Resolve file paths to wiki scopes and enumerate scope members.

  Scopes are read from `wiki.scopes` in the repo's `.claude/lazy.settings.json`.
  The `wiki` block may contain a version key; it is silently ignored.
  """

  _SETTINGS_PATH = ".claude/lazy.settings.json"
  _WIKI_KEY = "wiki"
  _SCOPES_KEY = "scopes"
  _VERSION_KEY = "_version"
  _PATHS_KEY = "paths"
  _EXCLUDE_PATHS_KEY = "exclude_paths"
  _GIT_DIR = ".git"

  def __init__(self, *, repo: Path | str) -> None:
    """
    Initialise the resolver for the given repository root.

    Args:
      repo: Absolute path to the repository root that owns `.claude/lazy.settings.json`.
    """
    self._repo = Path(repo).resolve()
    self._matcher = GlobMatcher()

  # ------------------------------------------------------------------
  def load_scopes(self) -> dict:
    """
    Load and return the `wiki.scopes` dict from the repo settings file.

    Returns:
      Dict of scope-id → scope-config entries.  Empty dict when the
      settings file is absent, unreadable, or carries no `wiki.scopes` key.
    """
    settings_file = self._repo / self._SETTINGS_PATH
    # guard: settings file does not exist — return empty scopes
    if not settings_file.is_file():
      return {}
    with settings_file.open(encoding = "utf-8") as fh:
      data = json.load(fh)
    wiki = data.get(self._WIKI_KEY, {})
    scopes_raw = wiki.get(self._SCOPES_KEY, {})
    # guard: scopes not a dict (config error) — treat as empty
    if not isinstance(scopes_raw, dict):
      return {}
    # Drop meta keys that are not scope definitions
    return {
      k: v
      for k, v in scopes_raw.items()
      if k != self._VERSION_KEY and isinstance(v, dict)
    }

  # ------------------------------------------------------------------
  def resolve_scope_by_path(
    self,
    path: Path | str,
  ) -> tuple[str, dict] | None:
    """
    Return the first scope whose `paths` globs match and no `exclude_paths` glob matches.

    Path normalisation: an absolute input is resolved first (so macOS symlink
    prefixes like `/var`→`/private/var` line up with the resolved repo root)
    then made repo-relative; a relative input is read as already repo-relative.
    The result is a POSIX string, so absolute and relative paths both work.
    If the path is not under the repo root at all, it cannot match any scope.

    When multiple scopes match the same file this method returns the first
    matching scope (dict iteration order = insertion order in Python 3.7+).
    Overlapping scopes are a configuration error that `/wiki.doctor` flags
    separately; this method does not resolve them.

    Args:
      path: Absolute or repo-relative path to the file being resolved.

    Returns:
      `(scope_id, cfg)` for the first matching scope, or `None` when no
      scope matches.
    """
    path = Path(path)
    # guard: make path repo-relative; skip if outside the repo
    try:
      if path.is_absolute():
        # Resolve absolute inputs so symlink prefixes match the resolved repo root.
        rel_posix = path.resolve().relative_to(self._repo).as_posix()
      else:
        rel_posix = PurePath(path).as_posix()
    except ValueError:
      return None

    scopes = self.load_scopes()
    for scope_id, cfg in scopes.items():
      if self._matches_scope(rel_posix, cfg):
        return scope_id, cfg
    return None

  # ------------------------------------------------------------------
  def iter_nodes(self, cfg: dict) -> list[Path]:
    """
    Enumerate all files in the repo that belong to the given scope config.

    Uses `os.walk` + `GlobMatcher` — stdlib `glob`/`rglob` are banned
    per the project tech conventions.  Results are deduped by resolved
    absolute path and returned sorted for determinism.

    Args:
      cfg: A single scope-config dict (the value side of a `wiki.scopes` entry).

    Returns:
      Sorted list of absolute `Path` objects for all matching, non-excluded files.
    """
    paths_globs: list[str] = cfg.get(self._PATHS_KEY) or []
    exclude_globs: list[str] = cfg.get(self._EXCLUDE_PATHS_KEY) or []

    seen_abs: set[Path] = set()
    candidates: list[Path] = []

    for base, dirs, files in os.walk(str(self._repo)):
      # guard: never descend into git internals
      dirs[ : ] = [ d for d in dirs if d != self._GIT_DIR ]
      for fname in files:
        full = Path(base) / fname
        rel = full.relative_to(self._repo).as_posix()
        for pat in paths_globs:
          # guard: pattern does not match this file
          if not self._matcher.match(rel, pat):
            continue
          ap = full.resolve()
          # guard: already collected under a different glob — skip duplicate
          if ap in seen_abs:
            break
          # guard: excluded by an exclude_paths pattern
          if any(self._matcher.match(rel, ep) for ep in exclude_globs):
            break
          seen_abs.add(ap)
          if ap.is_file():
            candidates.append(ap)
          break

    candidates.sort()
    return candidates

  # ------------------------------------------------------------------
  def _matches_scope(self, rel_posix: str, cfg: dict) -> bool:
    """
    Return True when `rel_posix` matches at least one `paths` glob and no `exclude_paths` glob.

    Args:
      rel_posix: Repo-relative POSIX path string.
      cfg: Scope-config dict.

    Returns:
      True on a match, False otherwise.
    """
    paths_globs: list[str] = cfg.get(self._PATHS_KEY) or []
    exclude_globs: list[str] = cfg.get(self._EXCLUDE_PATHS_KEY) or []
    # guard: no paths globs means the scope can never match
    if not paths_globs:
      return False
    matched = any(self._matcher.match(rel_posix, pat) for pat in paths_globs)
    # guard: file does not match any include glob
    if not matched:
      return False
    excluded = any(self._matcher.match(rel_posix, ep) for ep in exclude_globs)
    return not excluded
