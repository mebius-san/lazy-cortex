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
# Frontmatter filter — re-implemented locally because cross-plugin Python import is forbidden
# (inter-plugin boundary contract, mirroring nodes.py). The schema matches the lazycortex-core
# routine filter (`routine_types`): {"frontmatter": {<key>: {"in": [...], "not_in": [...]}},
# "folder_note": <bool>}, so the whole project shares one frontmatter-filter notation.
# ----------------------------------------------------------------------------------------

def _unquote(s: str) -> str:
  """
  Return `s` with one matched layer of surrounding single or double quotes removed.

  Args:
    s: Candidate string that may be wrapped in matching `"` or `'`.

  Returns:
    The unquoted string when both ends carry the same quote character; the input unchanged otherwise.
  """
  if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
    return s[1:-1]
  return s


def _coerce_scalar(s: str) -> bool | int | float | str | None:
  """
  Convert a raw YAML scalar literal into the closest matching Python value.

  Recognises the YAML booleans `true`/`false`, the nulls `null`/`~`, integers and floats, and
  falls back to the original string otherwise. Mirrors the lazycortex-core frontmatter parser so
  filter predicates compare against the same coerced types (notably `review_active: true` → `True`).

  Args:
    s: Raw scalar text from the right-hand side of a `key: value` pair.

  Returns:
    A `bool`, `None`, `int`, `float`, or `str` value depending on the literal shape.
  """
  s = _unquote(s)
  low = s.lower()
  # waiver: YAML scalar keywords, external-format tokens, not internal keys
  if low in ("true", "false"):
    return low == "true"
  if low in ("null", "~"):
    return None
  try:
    return int(s)
  except ValueError:
    pass
  try:
    return float(s)
  except ValueError:
    pass
  return s


def _parse_frontmatter(text: str) -> dict:
  """
  Return the YAML frontmatter at the head of `text` as a flat dict.

  Permissive and minimal: flat `key: value` scalars (coerced via `_coerce_scalar`), blank values
  (mapped to None), and indented `- item` lists attached to the most recent key. Missing or
  malformed frontmatter yields `{}`. Only the flat key→scalar/list shape the filter needs is
  supported — nested mappings, anchors, and multi-line scalars are out of scope.

  Args:
    text: Full document text whose frontmatter block (if any) is delimited by lines that are
      exactly `---`.

  Returns:
    The parsed mapping, or `{}` when there is no parseable frontmatter.
  """
  # guard: empty input — nothing to parse
  if not text:
    return {}
  lines = text.splitlines()
  # guard: missing opening fence
  if not lines or lines[0].strip() != "---":
    return {}
  # locate the closing fence inside the block
  close_idx = None
  for i in range(1, len(lines)):
    if lines[i].strip() == "---":
      close_idx = i
      break
  # guard: no closing fence — frontmatter is malformed
  if close_idx is None:
    return {}

  result: dict = {}
  current_key: str | None = None
  for raw in lines[1:close_idx]:
    stripped = raw.lstrip()
    indent = len(raw) - len(stripped)
    # indented `- item` line under the most recent key — append to its list
    if indent > 0 and stripped.startswith("- ") and current_key is not None:
      if not isinstance(result.get(current_key), list):
        result[current_key] = []
      result[current_key].append(_unquote(stripped[2:].strip()))
      continue
    # guard: not a key:value line
    if ":" not in raw:
      continue
    key, _, value = raw.partition(":")
    key = key.strip()
    value = value.strip()
    # guard: empty key after stripping
    if not key:
      continue
    result[key] = None if value == "" else _coerce_scalar(value)
    current_key = key
  return result


def _match_frontmatter_filter(flt: dict, frontmatter: dict) -> bool:
  """
  Apply a per-key `{in, not_in}` frontmatter predicate.

  `in` (when non-empty) is an allow-list; `not_in` (when non-empty) is a deny-list. Both AND
  together, and all keys AND together. A missing key reads as `None` (so `not_in: [true]` accepts
  a file that has no such key).

  Args:
    flt: Per-key predicate dict — `{<key>: {"in": [...], "not_in": [...]}}`.
    frontmatter: Parsed frontmatter dict from the candidate node.

  Returns:
    True when every key's allow-list and deny-list both accept the value; False otherwise.
  """
  for key, pred in flt.items():
    # guard: malformed per-key predicate — accept (a typo must not silently exclude every node)
    if not isinstance(pred, dict):
      continue
    actual = frontmatter.get(key)
    # waiver: predicate-filter schema subkeys, not reusable domain keys
    include = pred.get("in") or []
    exclude = pred.get("not_in") or []
    # guard: allow-list declared and value outside it
    if include and actual not in include:
      return False
    # guard: deny-list declared and value inside it
    if exclude and actual in exclude:
      return False
  return True


def _match_filter(flt: dict, frontmatter: dict, path: object = None) -> bool:
  """
  Apply a composite scope filter against one node.

  Filter shape: `{"frontmatter": {<key>: {in, not_in}}, "folder_note": <bool>}`. Each declared
  sub-filter must pass (AND semantics). An empty or malformed filter accepts everything — a
  defensive stance so a config typo cannot silently exclude every node from the wiki.

  Args:
    flt: Composite filter block from the scope config.
    frontmatter: Parsed frontmatter dict from the node under evaluation.
    path: Optional file path used for folder-note detection; when None the node is treated as not
      a folder note.

  Returns:
    True when every declared sub-filter accepts the node; False otherwise.
  """
  # guard: filter not a dict — accept everything
  if not isinstance(flt, dict):
    return True
  # waiver: routine-config schema field name, single source in the filter schema
  fm = flt.get("frontmatter")
  # guard: a frontmatter sub-filter is declared — it must pass
  if isinstance(fm, dict) and not _match_frontmatter_filter(fm, frontmatter):
    return False
  # waiver: routine-config schema field name, single source in the filter schema
  want = flt.get("folder_note")
  if isinstance(want, bool):
    _p = Path(str(path)) if path is not None else None
    is_fn = _p is not None and _p.stem == _p.parent.name
    # guard: want only folder-notes but this isn't one
    if want and not is_fn:
      return False
    # guard: forbid folder-notes but this is one
    if (not want) and is_fn:
      return False
  return True


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
  _FILTER_KEY = "filter"
  _GIT_DIR = ".git"
  _ENCODING = "utf-8"

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
    with settings_file.open(encoding = self._ENCODING) as fh:
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

    When that home scope declares a `filter` and the node fails it (e.g. the node carries
    `review_active: true` and the filter denies it), this returns `None` — the node is treated
    as out of scope for now and re-enters once the frontmatter flag clears.

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

    abs_path = path if path.is_absolute() else self._repo / path
    scopes = self.load_scopes()
    for scope_id, cfg in scopes.items():
      # guard: path does not belong to this scope
      if not self._matches_scope(rel_posix, cfg):
        continue
      # guard: the home scope's frontmatter filter rejects this node (e.g. it carries
      # review_active: true) — treat it as out of scope so process-file skips it without
      # dispatching the curator. First path-match wins, mirroring the no-filter path.
      if not self._passes_filter(cfg, abs_path):
        return None
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
          # guard: must be a real file and pass the scope's optional frontmatter filter — a
          # filtered node (e.g. review_active: true) drops out of the index entirely, so other
          # nodes do not link to it while the flag is set.
          if ap.is_file() and self._passes_filter(cfg, full):
            candidates.append(ap)
          break

    candidates.sort()
    return candidates

  # ------------------------------------------------------------------
  def _passes_filter(self, cfg: dict, abs_path: Path) -> bool:
    """
    Return True when the node at `abs_path` passes the scope's optional `filter`.

    Reads and parses the node's frontmatter only when a non-empty `filter` is configured, so
    filter-free scopes incur no extra IO. A read failure (missing/unreadable file) or a code file
    with no frontmatter parses to `{}`, which passes any `not_in` deny-list on a missing key.

    Args:
      cfg: The scope-config dict whose optional `filter` block is applied.
      abs_path: Absolute path to the node file whose frontmatter is evaluated.

    Returns:
      True when the node passes the filter (or no filter is configured); False when the filter
      rejects it.
    """
    flt = cfg.get(self._FILTER_KEY)
    # guard: no usable filter — accept without touching the file
    if not isinstance(flt, dict) or not flt:
      return True
    try:
      text = abs_path.read_text(encoding = self._ENCODING)
    except OSError:
      text = ""
    return _match_filter(flt, _parse_frontmatter(text), abs_path)

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
