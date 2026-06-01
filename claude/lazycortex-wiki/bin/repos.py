"""
Cross-repo resolver for lazycortex-wiki.

Reads the `repos` block from `.claude/lazy.settings.json` (map
`<key> → {path}`) and resolves `@<repo-key>/relative/path` links
to absolute filesystem paths.  Plain relative paths (no `@` prefix)
resolve relative to the local repo root.

Cross-plugin Python import is forbidden
(per the inter-plugin boundary contract), so the minimal
`repos`-block loading is re-implemented here rather than importing
`lazycortex-core/bin/repo_resolver.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ────────────────────────────────────────────────────────────────────────────
# RepoRegistry
# ────────────────────────────────────────────────────────────────────────────

class RepoRegistry:
  """
  Registry of cross-repo paths read from `.claude/lazy.settings.json[repos]`.

  Each entry in `repos` maps a key string to an object with a `path` field.
  The special key `"."` always resolves to the local repo itself without
  consulting the settings file.

  Unregistered keys resolve to `None` so callers can treat them as doctor
  findings without raising exceptions.  Missing or malformed settings files
  produce an empty registry — same graceful result.
  """

  _SETTINGS_REL = ".claude/lazy.settings.json"
  _REPOS_KEY    = "repos"
  _VERSION_KEY  = "_version"
  _PATH_FIELD   = "path"
  _ENCODING     = "utf-8"

  def __init__(self, *, local_repo: Path | str) -> None:
    """
    Initialise the registry for the given local repository root.

    Args:
      local_repo: Absolute path to the repository whose
        `.claude/lazy.settings.json` is consulted.
    """
    self._local_repo: Path = Path(local_repo).resolve()
    self._repos: dict[str, str] = self._load()

  # ------------------------------------------------------------------
  def resolve_repo(self, key: str) -> Path | None:
    """
    Return the absolute path registered under `key`, or `None` when unregistered.

    The special key `"."` always returns the local repo root without
    consulting the settings file.  All other keys are looked up in the
    `repos` block; unregistered keys return `None` so the caller can
    surface them as doctor findings.

    Args:
      key: Registry key, or `"."` for the local repo.

    Returns:
      Absolute `Path` of the target repo, or `None` when the key is not
      in the registry.
    """
    # guard: dot shortcut resolves to local repo unconditionally
    if key == ".":
      return self._local_repo
    raw = self._repos.get(key)
    # guard: key not declared in settings
    if raw is None:
      return None
    return Path(raw).expanduser().resolve()

  # ------------------------------------------------------------------
  def resolve_link(self, link: str) -> Path | None:
    """
    Resolve a wiki See-also link string to an absolute path.

    Two syntaxes are accepted:

    - `@<repo-key>/relative/path` — repo-key-qualified cross-repo link.
      Resolved by looking up `<repo-key>` in the registry and joining
      `relative/path` under it.  Returns `None` when the key is unregistered.
    - Plain `relative/path` (no `@` prefix) — local link, resolved relative
      to the local repo root.

    Args:
      link: Raw link string from a See-also entry, with or without `@key/`
        prefix.

    Returns:
      Absolute `Path` of the link target, or `None` when the repo key is
      unregistered.
    """
    # guard: cross-repo link with @key/ prefix
    if link.startswith("@"):
      slash = link.find("/", 1)
      # guard: no slash after the key — treat entire remainder as key, path empty
      if slash == -1:
        key = link[1:]
        rel  = ""
      else:
        key = link[1:slash]
        rel  = link[slash + 1:]
      repo_root = self.resolve_repo(key)
      # guard: key is unregistered — propagate None to caller
      if repo_root is None:
        return None
      # guard: empty relative path — return repo root itself
      if not rel:
        return repo_root
      return repo_root / rel
    # plain relative path — join under local repo
    return self._local_repo / link

  # ------------------------------------------------------------------
  def _load(self) -> dict[str, str]:
    """
    Load the `repos` block from `.claude/lazy.settings.json`.

    Returns:
      Dict mapping repo key to its declared `path` string.  Empty dict
      when the settings file is absent, unreadable, not valid JSON, or
      carries a non-dict `repos` value.  The internal `_version` key is
      silently dropped.
    """
    settings_path = self._local_repo / self._SETTINGS_REL
    # guard: settings file absent — no repos declared
    if not settings_path.is_file():
      return {}
    try:
      text = settings_path.read_text(encoding = self._ENCODING)
      data = json.loads(text or "{}")
    except (OSError, json.JSONDecodeError):
      # guard: unreadable or malformed JSON — treat as empty registry
      return {}
    block = data.get(self._REPOS_KEY) or {}
    # guard: repos field present but not a dict
    if not isinstance(block, dict):
      return {}
    result: dict[str, str] = {}
    for k, v in block.items():
      # guard: skip the version bookkeeping key
      if k == self._VERSION_KEY:
        continue
      raw = (v or {}).get(self._PATH_FIELD) if isinstance(v, dict) else None
      # guard: entry missing or has no path field — skip
      if not raw:
        continue
      result[k] = raw
    return result
