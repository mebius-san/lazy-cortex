"""
Attach protocol references to a routine's `protocols` list in lazy.settings.json.

Backs the `add-protocols` subcommand of the `lazycortex-core` CLI — the deterministic
write half of the optional-routine-protocol flow. A configurator's offer skill
(`lazy-routine.offer-protocols`) does the discovery, relevance judgment, and operator
prompt, then calls this to union the chosen reference ids into the routine's existing
`protocols` list. The routine entry is otherwise untouched; the runtime keeps reading
the flat `protocols` list exactly as before.

Reads go through `lazy_settings.load_tracked_section` (tracked layer, no local overlay —
the correct layer for a read-modify-write round-trip); the write goes through
`lazy_settings.save_section` (atomic, version-stamped, never touches the local overlay).
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
from pathlib import Path

from constants import RoutineKey, SettingsKey
from lazy_settings import load_tracked_section, save_section

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def _resolve_settings_path(cwd: Path | str | None) -> Path:
  """
  Resolve the tracked settings-file path from an optional explicit working directory.

  Args:
    cwd: Explicit repository root, or `None` to fall back to the `LAZY_REPO_ROOT`
      environment variable and then the process working directory.

  Returns:
    Path to `<cwd>/.claude/lazy.settings.json` under the resolved working directory.
  """
  # guard: explicit --cwd wins; otherwise mirror the dispatcher's LAZY_REPO_ROOT-or-cwd convention
  if cwd is not None:
    root = Path(cwd)
  else:
    root = Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))
  # waiver: filesystem path idiom
  return root / ".claude" / "lazy.settings.json"


def add_protocols(routine_name: str, ids: list[str], *, cwd: Path | str | None = None) -> dict:
  """
  Union protocol reference ids into one routine's `protocols` list.

  Existing entries are preserved in order and de-duplicated, so re-running with the same
  ids is a no-op. The routine entry is otherwise left untouched. When the routine is not
  registered (e.g. the daemon gate unregistered it) nothing is created and the call is a
  no-op reporting `routine_absent`.

  Args:
    routine_name: Key under the `routines` section to attach protocols to.
    ids: Protocol reference ids (`<plugin>:<name>`) to union into the routine.
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.

  Returns:
    Dict with `routine`, `added` (ids appended this call), and `protocols` (the resulting
    list); `routine_absent` is True instead when the routine entry is missing.

  Raises:
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
    OSError: If the tracked settings file or its parent directory cannot be written.
  """
  path = _resolve_settings_path(cwd)
  routines = load_tracked_section(path, SettingsKey.ROUTINES)
  routine = routines.get(routine_name)
  # guard: routine not registered — nothing to attach to
  if not isinstance(routine, dict):
    return { "routine": routine_name, "routine_absent": True, "added": [], RoutineKey.PROTOCOLS: [] }
  current = routine.get(RoutineKey.PROTOCOLS)
  if not isinstance(current, list):
    current = []
  added: list[str] = []
  for pid in ids:
    # guard: already attached — preserve, never duplicate
    if pid in current:
      continue
    current.append(pid)
    added.append(pid)
  routine[RoutineKey.PROTOCOLS] = current
  # guard: nothing new — skip the write so the round-trip stays a true no-op
  if added:
    save_section(path, SettingsKey.ROUTINES, routines)
  return { "routine": routine_name, "added": added, RoutineKey.PROTOCOLS: current }


def cmd_add_protocols(argv: list[str]) -> int:
  """
  Run the `add-protocols` subcommand: union comma-separated ids into a routine's protocols.

  Args:
    argv: Argument vector after the subcommand name (`--routine`, `--ids`, optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 2 on argument error.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core add-protocols")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--routine", required = True)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--ids", default = "", help = "Comma-separated protocol reference ids")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  ids = [ s.strip() for s in args.ids.split(",") if s.strip() ]
  print(json.dumps(add_protocols(args.routine, ids, cwd = args.cwd)))
  return 0
