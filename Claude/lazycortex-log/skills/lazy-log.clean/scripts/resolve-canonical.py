#!/usr/bin/env python3
"""Emit JSON of every canonical skill / agent / command name visible to this session.

Sources (any can be missing — we just skip what's not there):
  1. In-repo plugin sources under <repo>/claude/<plugin>/{skills,agents,commands}/
  2. In-repo project-local sources under <repo>/.claude/{skills,agents,commands}/
  3. Every install path listed in ~/.claude/plugins/installed_plugins.json
  4. Global ~/.claude/{skills,agents,commands}/

For each artifact we prefer the frontmatter `name:` field over the directory/file
basename — that is what consumers see in the slash-command/skill picker, and what
`.logs/claude/<name>/` folders end up named.

Output (stdout):
  {
    "canonical":   [...sorted unique names across all kinds...],
    "by_kind":     {"skill": [...], "agent": [...], "command": [...]},
    "sources":     {"in_repo": N, "installed_plugins": N, "global": N}
  }
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
INSTALLED = HOME / ".claude" / "plugins" / "installed_plugins.json"

NAME_RE = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
WAIVER_RE = re.compile(r"^logging-waiver:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)


def _extract_frontmatter_block(path: Path) -> str | None:
    """Return the raw YAML frontmatter block (between the --- delimiters), or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    return text[3:end]


def read_frontmatter_name(path: Path) -> str | None:
    """Return the YAML `name:` field from a file's frontmatter, or None."""
    block = _extract_frontmatter_block(path)
    if block is None:
        return None
    m = NAME_RE.search(block)
    return m.group(1).strip() if m else None


def read_frontmatter_waiver(path: Path) -> str | None:
    """Return the `logging-waiver:` reason string from frontmatter, or None."""
    block = _extract_frontmatter_block(path)
    if block is None:
        return None
    m = WAIVER_RE.search(block)
    return m.group(1).strip() if m else None


def harvest_root(
    root: Path, counters: dict[str, int], waivered: dict[str, str]
) -> dict[str, set[str]]:
    """Walk one root for skills/agents/commands. Returns {kind: {names}}.

    Also populates *waivered* in-place: maps artifact name → logging-waiver reason
    for every file that carries a ``logging-waiver:`` frontmatter key.
    """
    found: dict[str, set[str]] = {"skill": set(), "agent": set(), "command": set()}
    if not root.is_dir():
        return found

    # Skills: <root>/skills/<dir>/SKILL.md
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for entry in os.listdir(skills_dir):
            skill_md = skills_dir / entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            name = read_frontmatter_name(skill_md) or entry
            found["skill"].add(name)
            counters["files"] += 1
            reason = read_frontmatter_waiver(skill_md)
            if reason is not None:
                waivered[name] = reason

    # Agents: <root>/agents/<file>.md
    agents_dir = root / "agents"
    if agents_dir.is_dir():
        for entry in os.listdir(agents_dir):
            if not entry.endswith(".md"):
                continue
            agent_md = agents_dir / entry
            if not agent_md.is_file():
                continue
            name = read_frontmatter_name(agent_md) or agent_md.stem
            found["agent"].add(name)
            counters["files"] += 1
            reason = read_frontmatter_waiver(agent_md)
            if reason is not None:
                waivered[name] = reason

    # Commands: <root>/commands/<file>.md
    commands_dir = root / "commands"
    if commands_dir.is_dir():
        for entry in os.listdir(commands_dir):
            if not entry.endswith(".md"):
                continue
            cmd_md = commands_dir / entry
            if not cmd_md.is_file():
                continue
            name = read_frontmatter_name(cmd_md) or cmd_md.stem
            found["command"].add(name)
            counters["files"] += 1
            reason = read_frontmatter_waiver(cmd_md)
            if reason is not None:
                waivered[name] = reason

    return found


def merge(into: dict[str, set[str]], more: dict[str, set[str]]) -> None:
    for k, v in more.items():
        into[k] |= v


def repo_root() -> Path | None:
    """Return the nearest ancestor that contains a .git directory."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def in_repo_plugin_roots(repo: Path | None) -> list[Path]:
    """Find <repo>/claude/<plugin>/ roots when authoring plugins."""
    if repo is None:
        return []
    candidate = repo / "claude"
    if not candidate.is_dir():
        return []
    return [p for p in candidate.iterdir() if p.is_dir()]


def project_local_root(repo: Path | None) -> Path | None:
    """Return <repo>/.claude/ if it exists, else fall back to cwd/.claude/.

    The fallback handles the case where cwd is not inside a git repo (e.g. in
    tests) but the caller has already arranged a .claude/ tree under cwd.
    """
    if repo is not None:
        candidate = repo / ".claude"
        return candidate if candidate.is_dir() else None
    # No git repo found — use cwd as the project root.
    candidate = Path.cwd() / ".claude"
    return candidate if candidate.is_dir() else None


def installed_plugin_roots() -> list[Path]:
    if not INSTALLED.is_file():
        return []
    try:
        data = json.loads(INSTALLED.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    roots: list[Path] = []
    for entries in data.get("plugins", {}).values():
        for entry in entries:
            install_path = entry.get("installPath")
            if install_path:
                roots.append(Path(install_path))
    # Dedupe while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def global_root() -> Path:
    return HOME / ".claude"


def main() -> int:
    counters = {
        "in_repo_plugin_roots": 0,
        "project_local_root": 0,
        "installed_roots": 0,
        "global_root": 0,
        "files": 0,
    }
    aggregate: dict[str, set[str]] = {"skill": set(), "agent": set(), "command": set()}
    waivered: dict[str, str] = {}

    repo = repo_root()

    for root in in_repo_plugin_roots(repo):
        merge(aggregate, harvest_root(root, counters, waivered))
        counters["in_repo_plugin_roots"] += 1

    proj = project_local_root(repo)
    if proj is not None:
        merge(aggregate, harvest_root(proj, counters, waivered))
        counters["project_local_root"] = 1

    for root in installed_plugin_roots():
        merge(aggregate, harvest_root(root, counters, waivered))
        counters["installed_roots"] += 1

    g = global_root()
    if g.is_dir():
        merge(aggregate, harvest_root(g, counters, waivered))
        counters["global_root"] = 1

    by_kind = {k: sorted(v) for k, v in aggregate.items()}
    canonical = sorted(set().union(*aggregate.values()))

    output = {
        "canonical": canonical,
        "by_kind": by_kind,
        "waivered": waivered,
        "sources": {
            "in_repo_plugin_roots": counters["in_repo_plugin_roots"],
            "project_local_root": counters["project_local_root"],
            "installed_plugin_roots": counters["installed_roots"],
            "global_root": counters["global_root"],
            "files_scanned": counters["files"],
        },
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
