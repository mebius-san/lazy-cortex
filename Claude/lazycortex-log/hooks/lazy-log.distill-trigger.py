#!/usr/bin/env python3
"""Stop hook — trigger distill when commits are pending.

Checks `.logs/commits.jsonl` against the `last-distilled-sha` marker in
`docs/changelog.md`. When commits are pending and the hook has not
already fired this turn (`stop_hook_active`), exits 2 with a stderr
message asking Claude to run the `lazycortex-log:lazy-log.distill`
agent before ending the turn.

Silent no-op when:
  - `stop_hook_active` is true (prevent re-entry loop)
  - `.logs/commits.jsonl` is missing or empty
  - `docs/changelog.md` is missing or has no marker
  - no pending commits
  - any exception (pass-through, never block stop)

Protocol reference: https://code.claude.com/docs/en/hooks.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

TIER = {"haiku": 1, "sonnet": 2, "opus": 3}
SENTINELS = {"inherit", None, ""}
MARKER_RE = re.compile(r"<!--\s*lazy-log:\s*last-distilled-sha\s*=\s*([0-9a-f]+)\s*-->")


def _try_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_config(cwd: str | None) -> dict:
    """Merge user-scope config under project-scope (project wins per-group)."""
    proj = _try_json(os.path.join(cwd or ".", ".claude", "lazy.settings.json")) or {}
    user = _try_json(os.path.expanduser("~/.claude/lazy.settings.json")) or {}
    merged: dict = {"agent_models": {}}
    for src in (user, proj):
        groups = src.get("agent_models") if isinstance(src, dict) else None
        if not isinstance(groups, dict):
            continue
        for g, entries in groups.items():
            if not isinstance(entries, dict):
                continue
            merged["agent_models"].setdefault(g, {}).update(entries)
    return merged


def build_flat_map(cfg: dict) -> dict:
    out: dict = {}
    groups = cfg.get("agent_models", {})
    if not isinstance(groups, dict):
        return out
    for _group_name, entries in groups.items():
        if not isinstance(entries, dict):
            continue
        for key, val in entries.items():
            out[key] = val
    return out


def git_toplevel(cwd: str | None) -> str | None:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            return res.stdout.strip() or None
    except Exception:
        return None
    return None


def read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def extract_marker(changelog_path: str) -> str | None:
    if not os.path.isfile(changelog_path):
        return None
    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            for line in f:
                m = MARKER_RE.search(line)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def commits_after(commits: list[dict], marker_sha: str) -> list[dict]:
    """Return commits newer than marker_sha.

    `commits.jsonl` is append-only chronological, so we take entries after
    the marker's line. If marker isn't found in the file, treat all
    commits as pending (conservative — at worst prompts a no-op distill).
    """
    marker_prefix = (marker_sha or "").strip()
    if not marker_prefix:
        return commits
    found = False
    tail: list[dict] = []
    for entry in commits:
        sha = (entry.get("sha") or "").strip()
        if not found:
            if sha.startswith(marker_prefix) or marker_prefix.startswith(sha):
                found = True
            continue
        tail.append(entry)
    if not found:
        return commits
    return tail


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        sys.exit(0)

    cwd = payload.get("cwd")
    root = git_toplevel(cwd) or cwd or os.getcwd()

    commits = read_jsonl(os.path.join(root, ".logs/commits.jsonl"))
    if not commits:
        sys.exit(0)

    marker = extract_marker(os.path.join(root, "docs/changelog.md"))
    if marker is None:
        sys.exit(0)

    pending = commits_after(commits, marker)
    if not pending:
        sys.exit(0)

    cfg = load_config(root)
    flat = build_flat_map(cfg)
    model = flat.get("lazycortex-log:lazy-log.distill")
    if model in SENTINELS or model not in TIER:
        model = "haiku"

    print(
        f"{len(pending)} commit(s) pending distill since {marker}. "
        f'Run: Agent(subagent_type="lazycortex-log:lazy-log.distill", '
        f'model="{model}", prompt="distill pending commits"). '
        f"Skip ONLY if the user said 'don't distill' this turn.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
