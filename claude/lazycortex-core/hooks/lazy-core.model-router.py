#!/usr/bin/env python3

"""
PreToolUse hook — route Agent dispatches to a configured model.

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
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Hooks run as standalone scripts (no package context). Add the plugin's
# bin/ to sys.path so `lazy_settings` is importable.

sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from lazy_settings import load_section  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from constants import AgentToolInput, HookKey, SettingsFile, SettingsKey, ToolName  # noqa: E402


TIER = { "haiku": 1, "sonnet": 2, "opus": 3 }
SENTINELS = { "default", None, "" }


def _safe_load(path: Path) -> dict:
  """
  Return the `agent_models` section persisted at the given settings path.

  Args:
    path: Filesystem location of a `lazy.settings.json` candidate.

  Returns:
    The stored `agent_models` mapping, or an empty mapping when the file is absent, unreadable,
    or not valid JSON.
  """
  # guard: missing settings file — caller treats as empty section
  if not path.exists():
    return {}
  try:
    return load_section(path, SettingsKey.AGENT_MODELS)
  except (json.JSONDecodeError, OSError) as e:
    # surface the failure to stderr so operators can diagnose; never abort the hook
    print(
      f"[lazy-core.model-router] failed to load {path}: {e}",
      file = sys.stderr,
    )
    return {}


def load_config(cwd: str | None) -> dict:
  """
  Return the merged `agent_models` configuration for the current invocation.

  The user-scope settings file is layered first, then the project-scope file overrides on a
  per-group basis (project wins on collisions within a group).

  Args:
    cwd: Working directory reported by the hook payload, used to locate the project settings
      file. May be None when the payload omits it.

  Returns:
    A dict with one key `agent_models` whose value is the merged grouped configuration.
  """
  # resolve both candidate settings paths (user-scope + project-scope)
  user_path = Path.home() / SettingsFile.REL
  proj_path = Path(cwd or ".") / SettingsFile.REL

  user_section = _safe_load(user_path)
  proj_section = _safe_load(proj_path)

  # merge per-group: user first, project overrides within each group
  merged: dict = {}
  for section in (user_section, proj_section):  # project wins on key collisions within a group
    for g, entries in section.items():
      # guard: non-dict entry is metadata (`_version: int`, future timestamp fields, etc.)
      if not isinstance(entries, dict):
        continue  # skip metadata. Filtering by shape, not name, because `_user`/`_project`/`_builtin`
                  # are legitimate group keys that share the underscore prefix.
      merged.setdefault(g, {}).update(entries)
  return { SettingsKey.AGENT_MODELS: merged }


def build_flat_map(cfg: dict) -> dict:
  """
  Flatten the grouped `agent_models` configuration into a single dispatch-string lookup.

  Keys inside every group are already full dispatch strings — grouping is organizational only.
  On cross-group collisions the last entry wins and a warning is emitted to stderr. Malformed
  groups (non-dict values) are silently skipped.

  Args:
    cfg: Configuration dict as returned by `load_config`, expected to contain an `agent_models`
      mapping.

  Returns:
    A flat dict mapping each dispatch string to its configured model tier.
  """
  out: dict = {}
  groups = cfg.get(SettingsKey.AGENT_MODELS, {})
  # guard: malformed top-level — return empty flat map
  if not isinstance(groups, dict):
    return out
  # walk every group and merge its entries into the flat output
  for _group_name, entries in groups.items():
    # guard: malformed group — skip silently
    if not isinstance(entries, dict):
      continue
    for key, val in entries.items():
      # warn on cross-group collision before overwriting
      if key in out and out[key] != val:
        print(
          f"[lazy-core.model-router] duplicate key {key!r} "
          f"across groups; using {val!r}",
          file = sys.stderr,
        )
      out[key] = val
  return out


def main() -> None:
  """
  Run the PreToolUse hook entry point for one tool-dispatch event.

  Reads the hook payload from stdin, decides whether to inject a `model` field into the
  outgoing `tool_input`, and writes the updated-input envelope to stdout when a change is
  required. Exits silently with status zero in every non-mutating branch so the trigger is
  never blocked.
  """
  payload = json.load(sys.stdin)
  # guard: only Agent dispatches participate in routing
  if payload.get(HookKey.TOOL_NAME) != ToolName.AGENT:
    sys.exit(0)

  # snapshot caller-supplied tool input so any mutation stays local to this hook
  ti = dict(payload.get(HookKey.TOOL_INPUT, {}))
  subagent = ti.get(AgentToolInput.SUBAGENT_TYPE)
  # guard: dispatch missing subagent name — nothing to look up
  if not subagent:
    sys.exit(0)

  # 1. Config lookup
  caller_model = ti.get(AgentToolInput.MODEL)
  cfg = load_config(payload.get(HookKey.CWD))
  flat = build_flat_map(cfg)
  configured = flat.get(subagent)
  if configured in SENTINELS:
    configured = None  # explicit no-route
  elif configured is not None and configured not in TIER:
    print(
      f"[lazy-core.model-router] unknown model {configured!r} "
      f"for {subagent!r}, treating as default",
      file = sys.stderr,
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
      f"[lazy-core.model-router] unknown "
      f"LAZY_AGENT_MODEL_FLOOR={floor!r}, ignoring",
      file = sys.stderr,
    )

  # 3. No-op when nothing changes
  # guard: routed model identical to caller's choice — leave tool_input untouched
  if proposed is None or proposed == caller_model:
    sys.exit(0)

  # emit the updated-input envelope so Claude Code applies the routed model
  ti[AgentToolInput.MODEL] = proposed
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
  # waiver: re-raise SystemExit so a clean sys.exit() from main() propagates past the crash-guard below
  except SystemExit:  # pylint: disable=try-except-raise
    raise
  except Exception:
    # hooks must never crash the trigger — swallow any unexpected failure
    sys.exit(0)
