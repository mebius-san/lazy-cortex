#!/usr/bin/env python3

"""
Emit JSON of every canonical skill / agent / command name visible to this session.

Walks the configured artifact roots (in-repo plugin sources, project-local `.claude/` tree,
installed-plugin directories listed in `installed_plugins.json`, and the global `~/.claude/`
tree), prefers each artifact's frontmatter `name:` over its filesystem basename, and writes
the merged result to stdout as a single JSON object.

The output object carries:
  - `canonical`: sorted unique names across every kind.
  - `by_kind`: per-kind sorted name lists (`skill`, `agent`, `command`).
  - `waivered`: artifact-name → `logging-waiver:` reason for every file that declared one.
  - `sources`: per-root counters (number of roots visited per category plus total files scanned).

Missing sources are silently skipped — the script tolerates absent directories and unreadable
or malformed JSON without failing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


HOME = Path.home()
INSTALLED = HOME / ".claude" / "plugins" / "installed_plugins.json"

NAME_RE = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
WAIVER_RE = re.compile(r"^logging-waiver:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)


def _extract_frontmatter_block(path: Path) -> str | None:
  """
  Return the raw YAML frontmatter block from a markdown file.

  Args:
    path: Absolute path to the markdown file to inspect.

  Returns:
    The text between the leading `---` delimiter and the next `\\n---` delimiter, or `None`
    when the file cannot be read, does not start with `---`, or has no closing delimiter.
  """
  try:
    # waiver: stdlib idiom, not a domain constant
    text = path.read_text(encoding = "utf-8", errors = "replace")
  except OSError:
    return None
  # guard: file must open with a frontmatter delimiter
  if not text.startswith("---"):
    return None
  # waiver: inline numeric literal, not a domain constant
  end = text.find("\n---", 3)
  # guard: closing delimiter must exist for the block to be valid
  if end < 0:
    return None
  return text[3:end]


def read_frontmatter_name(path: Path) -> str | None:
  """
  Return the YAML `name:` field declared in a file's frontmatter.

  Args:
    path: Absolute path to the markdown file to inspect.

  Returns:
    The stripped value of the `name:` key, or `None` when the file has no frontmatter or no
    `name:` declaration inside it.
  """
  block = _extract_frontmatter_block(path)
  # guard: no frontmatter — nothing to extract
  if block is None:
    return None
  match = NAME_RE.search(block)
  return match.group(1).strip() if match else None


def read_frontmatter_waiver(path: Path) -> str | None:
  """
  Return the `logging-waiver:` reason declared in a file's frontmatter.

  Args:
    path: Absolute path to the markdown file to inspect.

  Returns:
    The stripped reason string, or `None` when the file has no frontmatter or no
    `logging-waiver:` declaration.
  """
  block = _extract_frontmatter_block(path)
  # guard: no frontmatter — nothing to extract
  if block is None:
    return None
  match = WAIVER_RE.search(block)
  return match.group(1).strip() if match else None


def harvest_root(
    root: Path, counters: dict[str, int], waivered: dict[str, str]
) -> dict[ str, set[str] ]:
  """
  Collect skill / agent / command names from one artifact root.

  Scans `<root>/skills/*/SKILL.md`, `<root>/agents/*.md`, and `<root>/commands/*.md`, preferring
  each file's frontmatter `name:` over its directory or file basename.

  Args:
    root: Absolute path to the artifact root to scan; missing directories yield empty sets.
    counters: Counter dict updated in place; the `files` entry is incremented per artifact found.
    waivered: Mapping updated in place; artifact name is added with its `logging-waiver:` reason
      for every file that declared one.

  Returns:
    A mapping with keys `skill`, `agent`, `command`, each pointing at the set of names found
    under the corresponding subdirectory.
  """
  found: dict[ str, set[str] ] = { "skill": set(), "agent": set(), "command": set() }
  # guard: root must exist before scanning
  if not root.is_dir():
    return found

  # skills live one directory deep at <root>/skills/<dir>/SKILL.md
  # waiver: Claude Code artifact-directory name, not a domain key
  skills_dir = root / "skills"
  if skills_dir.is_dir():
    for entry in os.listdir(skills_dir):
      # waiver: filesystem path/filename idiom, not a domain constant
      skill_md = skills_dir / entry / "SKILL.md"
      # guard: only count entries that actually own a SKILL.md
      if not skill_md.is_file():
        continue
      name = read_frontmatter_name(skill_md) or entry
      # waiver: internal counter/summary dict subkey, single-source set in this script
      found["skill"].add(name)
      # waiver: internal counter/summary dict subkey, single-source set in this script
      counters["files"] += 1
      reason = read_frontmatter_waiver(skill_md)
      if reason is not None:
        waivered[name] = reason

  # agents live flat at <root>/agents/<file>.md
  # waiver: Claude Code artifact-directory name, not a domain key
  agents_dir = root / "agents"
  if agents_dir.is_dir():
    for entry in os.listdir(agents_dir):
      # guard: only markdown agent files are eligible
      # waiver: filesystem path/filename idiom, not a domain constant
      if not entry.endswith(".md"):
        continue
      agent_md = agents_dir / entry
      # guard: skip stray directories or broken symlinks
      if not agent_md.is_file():
        continue
      name = read_frontmatter_name(agent_md) or agent_md.stem
      # waiver: internal counter/summary dict subkey, single-source set in this script
      found["agent"].add(name)
      # waiver: internal counter/summary dict subkey, single-source set in this script
      counters["files"] += 1
      reason = read_frontmatter_waiver(agent_md)
      if reason is not None:
        waivered[name] = reason

  # commands live flat at <root>/commands/<file>.md
  # waiver: Claude Code artifact-directory name, not a domain key
  commands_dir = root / "commands"
  if commands_dir.is_dir():
    for entry in os.listdir(commands_dir):
      # guard: only markdown command files are eligible
      # waiver: filesystem path/filename idiom, not a domain constant
      if not entry.endswith(".md"):
        continue
      cmd_md = commands_dir / entry
      # guard: skip stray directories or broken symlinks
      if not cmd_md.is_file():
        continue
      name = read_frontmatter_name(cmd_md) or cmd_md.stem
      # waiver: internal counter/summary dict subkey, single-source set in this script
      found["command"].add(name)
      # waiver: internal counter/summary dict subkey, single-source set in this script
      counters["files"] += 1
      reason = read_frontmatter_waiver(cmd_md)
      if reason is not None:
        waivered[name] = reason

  return found


def merge(into: dict[ str, set[str] ], more: dict[ str, set[str] ]) -> None:
  """
  Merge per-kind name sets from `more` into `into`.

  Args:
    into: Aggregate mapping updated in place; existing entries are kept and unioned with new ones.
    more: Per-kind mapping whose values are unioned into the matching `into` entries.
  """
  for kind, names in more.items():
    into[kind] |= names


def repo_root() -> Path | None:
  """
  Return the nearest ancestor of the current working directory that contains a `.git` entry.

  Returns:
    The absolute path of the enclosing git repository, or `None` when the current working
    directory is not inside any repository.
  """
  cwd = Path.cwd()
  for parent in [ cwd, *cwd.parents ]:
    # waiver: filesystem path/filename idiom, not a domain constant
    if (parent / ".git").exists():
      return parent
  return None


def in_repo_plugin_roots(repo: Path | None) -> list[Path]:
  """
  Return every immediate child of the repository's `claude/` directory.

  Args:
    repo: Absolute path to the repository root, or `None` when no repository was detected.

  Returns:
    The list of `<repo>/claude/<plugin>/` directories, in filesystem order. Empty when no
    repository was supplied or the `claude/` directory is absent.
  """
  # guard: no repository context — nothing to enumerate
  if repo is None:
    return []
  # waiver: filesystem path/filename idiom, not a domain constant
  candidate = repo / "claude"
  # guard: repository must own a `claude/` directory
  if not candidate.is_dir():
    return []
  return [ entry for entry in candidate.iterdir() if entry.is_dir() ]


def project_local_root(repo: Path | None) -> Path | None:
  """
  Return the project-local `.claude/` root for the current session.

  Prefers `<repo>/.claude/` when a repository is supplied; falls back to `<cwd>/.claude/` when
  the call sites runs outside a git repository (typical in test harnesses that arrange a local
  `.claude/` tree).

  Args:
    repo: Absolute path to the repository root, or `None` to force the cwd fallback.

  Returns:
    The absolute path to the resolved `.claude/` directory, or `None` when no candidate exists.
  """
  if repo is not None:
    # waiver: filesystem path/filename idiom, not a domain constant
    candidate = repo / ".claude"
    return candidate if candidate.is_dir() else None
  # fall back to the current working directory when no git repo is available
  # waiver: filesystem path/filename idiom, not a domain constant
  candidate = Path.cwd() / ".claude"
  return candidate if candidate.is_dir() else None


def installed_plugin_roots() -> list[Path]:
  """
  Return the install paths of every plugin recorded in `~/.claude/plugins/installed_plugins.json`.

  Returns:
    A deduplicated list of plugin install directories in first-seen order. Empty when the
    registry file is missing or contains invalid JSON.
  """
  # guard: registry file must exist before parsing
  if not INSTALLED.is_file():
    return []
  try:
    # waiver: stdlib idiom, not a domain constant
    data = json.loads(INSTALLED.read_text(encoding = "utf-8"))
  except json.JSONDecodeError:
    return []
  roots: list[Path] = []
  # waiver: external installed-plugins JSON field name, not an internal key
  for entries in data.get("plugins", {}).values():
    for entry in entries:
      # waiver: external installed-plugins JSON field name, not an internal key
      install_path = entry.get("installPath")
      if install_path:
        roots.append(Path(install_path))
  # deduplicate while preserving first-seen ordering
  seen: set[Path] = set()
  unique: list[Path] = []
  for root in roots:
    if root not in seen:
      seen.add(root)
      unique.append(root)
  return unique


def global_root() -> Path:
  """
  Return the user-level `~/.claude/` directory.

  Returns:
    The absolute path to the home-scoped Claude configuration root. The directory is not
    guaranteed to exist; callers must check before scanning.
  """
  # waiver: filesystem path/filename idiom, not a domain constant
  return HOME / ".claude"


def main() -> int:
  """
  Aggregate canonical artifact names across every configured root and write the merged JSON.

  Returns:
    Process exit code; always `0`. The aggregated result is written to stdout as a single
    JSON object followed by a trailing newline.
  """
  counters = {
    "in_repo_plugin_roots": 0,
    "project_local_root": 0,
    "installed_roots": 0,
    "global_root": 0,
    "files": 0,
  }
  aggregate: dict[ str, set[str] ] = { "skill": set(), "agent": set(), "command": set() }
  waivered: dict[str, str] = {}

  repo = repo_root()

  # scan in-repo plugin sources first so authoring overrides win on tie
  for root in in_repo_plugin_roots(repo):
    merge(aggregate, harvest_root(root, counters, waivered))
    # waiver: internal counter/summary dict subkey, single-source set in this script
    counters["in_repo_plugin_roots"] += 1

  # then the project-local `.claude/` tree (consumer-side artifacts)
  proj = project_local_root(repo)
  if proj is not None:
    merge(aggregate, harvest_root(proj, counters, waivered))
    # waiver: internal counter/summary dict subkey, single-source set in this script
    counters["project_local_root"] = 1

  # then every installed plugin recorded in the marketplace registry
  for root in installed_plugin_roots():
    merge(aggregate, harvest_root(root, counters, waivered))
    # waiver: internal counter/summary dict subkey, single-source set in this script
    counters["installed_roots"] += 1

  # finally the user-level `~/.claude/` root
  global_dir = global_root()
  if global_dir.is_dir():
    merge(aggregate, harvest_root(global_dir, counters, waivered))
    # waiver: internal counter/summary dict subkey, single-source set in this script
    counters["global_root"] = 1

  by_kind = { kind: sorted(names) for kind, names in aggregate.items() }
  canonical = sorted(set().union(*aggregate.values()))

  output = {
    "canonical": canonical,
    "by_kind": by_kind,
    "waivered": waivered,
    "sources": {
      # waiver: internal counter/summary dict subkey, single-source set in this script
      "in_repo_plugin_roots": counters["in_repo_plugin_roots"],
      # waiver: internal counter/summary dict subkey, single-source set in this script
      "project_local_root": counters["project_local_root"],
      # waiver: internal counter/summary dict subkey, single-source set in this script
      "installed_plugin_roots": counters["installed_roots"],
      # waiver: internal counter/summary dict subkey, single-source set in this script
      "global_root": counters["global_root"],
      # waiver: internal counter/summary dict subkey, single-source set in this script
      "files_scanned": counters["files"],
    },
  }
  json.dump(output, sys.stdout, indent = 2)
  sys.stdout.write("\n")
  return 0


if __name__ == "__main__":
  sys.exit(main())
