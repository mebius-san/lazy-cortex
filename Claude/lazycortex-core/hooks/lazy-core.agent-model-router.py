#!/usr/bin/env python3
"""PreToolUse hook — route Agent dispatches to a configured model.

Reads `.claude/lazy.settings.json` (project) merged under
`~/.claude/lazy.settings.json` (user), looks up `tool_input.subagent_type`
against the flattened `agent_models` map, and injects `model` into
`tool_input` when the caller hasn't set one.

Precedence (first wins):
    1. `LAZY_AGENT_MODEL_FLOOR` env var (session cap — strict, overrides caller)
    2. Caller-supplied `tool_input.model`
    3. Config lookup (subagent_type → model)
    4. No mutation

Grouped `agent_models` schema: top-level keys are group names
(`_builtin`, `_user`, `_project`, or plugin-domain like `lazycortex`);
values are maps of dispatch-string → model tier. Grouping is
organizational — the router flattens at load time.

Never blocks. Any error → `sys.exit(0)` (pass-through).

Protocol reference: https://code.claude.com/docs/en/hooks.md
"""
from __future__ import annotations

import json
import os
import sys

TIER = {"haiku": 1, "sonnet": 2, "opus": 3}
SENTINELS = {"inherit", None, ""}


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
    for src in (user, proj):  # project wins on key collisions within a group
        groups = src.get("agent_models") if isinstance(src, dict) else None
        if not isinstance(groups, dict):
            continue
        for g, entries in groups.items():
            if not isinstance(entries, dict):
                continue
            merged["agent_models"].setdefault(g, {}).update(entries)
    return merged


def build_flat_map(cfg: dict) -> dict:
    """Flatten grouped agent_models to {dispatch_string: model}.

    Keys inside every group ARE already full dispatch strings — grouping
    is organizational only. Collisions across groups: last one wins, with
    a stderr warning. Malformed groups (non-dict) are silently skipped.
    """
    out: dict = {}
    groups = cfg.get("agent_models", {})
    if not isinstance(groups, dict):
        return out
    for _group_name, entries in groups.items():
        if not isinstance(entries, dict):
            continue
        for key, val in entries.items():
            if key in out and out[key] != val:
                print(
                    f"[lazy-core.agent-model-router] duplicate key {key!r} "
                    f"across groups; using {val!r}",
                    file=sys.stderr,
                )
            out[key] = val
    return out


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Agent":
        sys.exit(0)

    ti = dict(payload.get("tool_input", {}))
    subagent = ti.get("subagent_type")
    if not subagent:
        sys.exit(0)

    # 1. Config lookup
    caller_model = ti.get("model")
    cfg = load_config(payload.get("cwd"))
    flat = build_flat_map(cfg)
    configured = flat.get(subagent)
    if configured in SENTINELS:
        configured = None  # explicit no-route
    elif configured is not None and configured not in TIER:
        print(
            f"[lazy-core.agent-model-router] unknown model {configured!r} "
            f"for {subagent!r}, treating as inherit",
            file=sys.stderr,
        )
        configured = None

    proposed = caller_model or configured

    # 2. Apply LAZY_AGENT_MODEL_FLOOR cap (wins over caller + config)
    floor = os.environ.get("LAZY_AGENT_MODEL_FLOOR", "").strip() or None
    if floor and floor in TIER:
        if proposed is None:
            proposed = floor
        elif proposed in TIER and TIER[proposed] > TIER[floor]:
            proposed = floor
    elif floor:
        print(
            f"[lazy-core.agent-model-router] unknown "
            f"LAZY_AGENT_MODEL_FLOOR={floor!r}, ignoring",
            file=sys.stderr,
        )

    # 3. No-op when nothing changes
    if proposed is None or proposed == caller_model:
        sys.exit(0)

    ti["model"] = proposed
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": ti,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
