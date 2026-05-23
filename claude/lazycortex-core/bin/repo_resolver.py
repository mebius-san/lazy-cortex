"""
Resolve `repos.<key>` from `lazy.settings.json` to an absolute target-repo
path. Validates existence, R/W, and presence of the target's own
`.claude/lazy.settings.json`.

For now the path lives directly in tracked `lazy.settings.json[repos].<key>.path`,
which means machine-specific paths leak into git — known limitation, to be
solved by a proper local-overlay mechanism (Claude Code `settings.local.json`
+ `additionalDirectories` integration) as a separate task.
"""
from __future__ import annotations
import json
import os
from pathlib import Path


class RepoResolverError(RuntimeError):
  """
  Raised when a repo-key cannot be resolved to a usable target path.
  """


def _load_repos_block(local_repo: Path) -> dict:
  """
  Return the declared `repos` mapping for the given local repository.

  Args:
    local_repo: Absolute path to the repository whose `.claude/lazy.settings.json` is consulted.

  Returns:
    A dict keyed by repo name with the bookkeeping `_version` key removed; empty when the settings
    file is missing, unreadable, not valid JSON, or carries a non-dict `repos` value.
  """
  settings_path = Path(local_repo) / ".claude" / "lazy.settings.json"
  # guard: settings file absent — no repos declared
  if not settings_path.exists():
    return {}
  try:
    data = json.loads(settings_path.read_text() or "{}")
  except json.JSONDecodeError:
    # corrupt or partial settings — fall back to empty repos block
    return {}
  block = data.get("repos") or {}
  # guard: `repos` field present but not a dict — treat as missing
  if not isinstance(block, dict):
    return {}
  return { k: v for k, v in block.items() if k != "_version" }


def resolve(local_repo: Path, repo_key: str) -> Path:
  """
  Return the absolute, validated target path registered under `repo_key`.

  The shortcut `"."` resolves to `local_repo` itself without consulting the registry.

  Args:
    local_repo: Absolute path to the repository whose registry is consulted.
    repo_key: Registry key naming the target repo, or `"."` for the local repo.

  Returns:
    Absolute path to the target repository, with all symlinks resolved.

  Raises:
    RepoResolverError: When the key is not declared, lacks a `path` field, points at a path that
      does not exist, lacks its own `.claude/lazy.settings.json`, is not readable, or whose
      writable surface (`.experts/` when present, otherwise the repo root) is not writable.
  """
  local_repo = Path(local_repo).resolve()
  # guard: dot shortcut — caller wants the local repo itself
  if repo_key == ".":
    return local_repo
  repos = _load_repos_block(local_repo)
  # guard: requested key not declared
  if repo_key not in repos:
    raise RepoResolverError(
      f"repos.{repo_key} not declared in .claude/lazy.settings.json"
    )
  raw_path = (repos[repo_key] or {}).get("path")
  # guard: declared entry has no `path` field
  if not raw_path:
    raise RepoResolverError(
      f"repos.{repo_key} missing `path` field in lazy.settings.json"
    )
  abs_path = Path(raw_path).expanduser()
  # guard: declared path doesn't exist on disk
  if not abs_path.is_dir():
    raise RepoResolverError(
      f"repos.{repo_key}.path does not exist: {abs_path}"
    )
  target_settings = abs_path / ".claude" / "lazy.settings.json"
  # guard: target repo isn't a lazy-managed repo
  if not target_settings.exists():
    raise RepoResolverError(
      f"repos.{repo_key}.path missing .claude/lazy.settings.json: {abs_path}"
    )
  # guard: target repo not readable by the current process
  if not os.access(abs_path, os.R_OK):
    raise RepoResolverError(
      f"repos.{repo_key}.path not readable: {abs_path}"
    )
  experts_dir = abs_path / ".experts"
  check_target = experts_dir if experts_dir.exists() else abs_path
  # guard: target repo (or its .experts/ dir) not writable
  if not os.access(check_target, os.W_OK):
    raise RepoResolverError(
      f"repos.{repo_key}.path/.experts not writable: {abs_path}"
    )
  return abs_path.resolve()


def reverse_lookup(local_repo: Path, target_path: Path) -> str | None:
  """
  Return the registry key whose declared path resolves to `target_path`.

  Args:
    local_repo: Absolute path to the repository whose registry is consulted.
    target_path: Absolute path of the candidate target repository.

  Returns:
    The matching `repos.<key>` name, or None when no registered entry resolves to `target_path`.
  """
  target = Path(target_path).resolve()
  for key, entry in _load_repos_block(Path(local_repo)).items():
    raw = (entry or {}).get("path")
    # guard: entry has no `path` field — skip
    if not raw:
      continue
    if Path(raw).expanduser().resolve() == target:
      return key
  return None
