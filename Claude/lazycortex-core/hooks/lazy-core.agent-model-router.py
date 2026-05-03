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
from pathlib import Path

# Hooks run as standalone scripts (no package context). Add the plugin's
# bin/ to sys.path so `lazy_settings` is importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))
from lazy_settings import load_section  # noqa: E402

TIER = {"haiku": 1, "sonnet": 2, "opus": 3}
SENTINELS = {"default", None, ""}


def _safe_load(path: Path) -> dict:
    """Load agent_models section, falling back to {} on any IO or parse error."""
    if not path.exists():
        return {}
    try:
        return load_section(path, "agent_models")
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"[lazy-core.agent-model-router] failed to load {path}: {e}",
            file=sys.stderr,
        )
        return {}


def load_config(cwd: str | None) -> dict:
    """Merge user-scope config under project-scope (project wins per-group).

    Each scope is loaded via lazy_settings.load_section so that on-disk
    migration runs transparently. The merge logic matches the original:
    user groups are applied first, project groups win on collision.
    """
    user_path = Path.home() / ".claude" / "lazy.settings.json"
    proj_path = Path(cwd or ".") / ".claude" / "lazy.settings.json"

    user_section = _safe_load(user_path)
    proj_section = _safe_load(proj_path)

    merged: dict = {}
    for section in (user_section, proj_section):  # project wins on key collisions within a group
        for g, entries in section.items():
            if not isinstance(entries, dict):
                continue  # skip metadata (`_version: int`, future timestamp fields, etc.).
                          # Filtering by shape, not name, because `_user`/`_project`/`_builtin`
                          # are legitimate group keys that share the underscore prefix.
            merged.setdefault(g, {}).update(entries)
    return {"agent_models": merged}


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
            f"for {subagent!r}, treating as default",
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
