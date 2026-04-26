#!/usr/bin/env python3
"""Stop hook — trigger distill when a fresh commit landed this turn.

Single-gate model: `.logs/commits.jsonl` mtime > stored mtime in
`.logs/.distill-trigger-last-mtime` (i.e. a commit was recorded during
the just-finished turn). When the gate passes, exit 2 (asking Claude
to run the `lazycortex-log:lazy-log.distill` agent before ending the
turn). Otherwise: silent no-op (exit 0). The mtime marker is updated
in a `finally` block whenever the gate passes, so a missed write
doesn't permanently re-arm the hook.

Silent no-op when:
  - `stop_hook_active` is true (prevent re-entry loop)
  - `.logs/commits.jsonl` is missing
  - first run in this repo (no baseline marker yet — record and exit)
  - gate fails (no fresh commit this turn)
  - any exception (pass-through, never block stop)

Protocol reference: https://code.claude.com/docs/en/hooks.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

TIER = {"haiku": 1, "sonnet": 2, "opus": 3}
SENTINELS = {"inherit", None, ""}
COMMITS_REL = ".logs/commits.jsonl"
MTIME_MARKER_REL = ".logs/.distill-trigger-last-mtime"


def read_last_mtime(path: str) -> float:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def write_last_mtime(path: str, mtime: float) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"{mtime}\n")
        os.replace(tmp, path)
    except Exception:
        pass


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


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        sys.exit(0)

    cwd = payload.get("cwd")
    root = git_toplevel(cwd) or cwd or os.getcwd()

    commits_path = os.path.join(root, COMMITS_REL)
    marker_path = os.path.join(root, MTIME_MARKER_REL)

    if not os.path.isfile(commits_path):
        sys.exit(0)

    current_mtime = os.path.getmtime(commits_path)

    # Bootstrap: no baseline yet. Record current mtime and stay silent —
    # only future mtime advances (real commits) should fire the hook.
    if not os.path.isfile(marker_path):
        write_last_mtime(marker_path, current_mtime)
        sys.exit(0)

    last_mtime = read_last_mtime(marker_path)

    # Gate: did a commit land during the just-finished turn?
    if current_mtime <= last_mtime:
        sys.exit(0)

    try:
        cfg = load_config(root)
        flat = build_flat_map(cfg)
        model = flat.get("lazycortex-log:lazy-log.distill")
        if model in SENTINELS or model not in TIER:
            model = "haiku"

        print(
            "A commit landed this turn. "
            f'Run: Agent(subagent_type="lazycortex-log:lazy-log.distill", '
            f'model="{model}", prompt="distill commits from this turn"). '
            "Skip ONLY if the user said 'don't distill' this turn.",
            file=sys.stderr,
        )
        sys.exit(2)
    finally:
        # Always advance the marker once the gate passed, so a missed
        # write doesn't permanently re-arm the hook.
        write_last_mtime(marker_path, current_mtime)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
