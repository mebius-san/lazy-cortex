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

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from constants import RoutineKey, SettingsKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from lazy_settings import load_tracked_section, save_section  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from plugin_locator import query_repo_root  # noqa: E402  # pylint: disable=import-error,wrong-import-position


def _resolve_settings_path(cwd: Path | str | None) -> Path:
  """
  Resolve the tracked settings file that holds the routines of the repository checkout a call works in.

  Args:
    cwd: Directory inside the repository, or `None` for `LAZY_REPO_ROOT`, else the process working directory.

  Returns:
    Path to `.claude/lazy.settings.json` at the root of the checkout that directory sits in, where the daemon reads
    the routines.
  """
  # the routines live at the checkout root of the explicit --cwd, the dispatcher's LAZY_REPO_ROOT or the cwd
  # waiver: filesystem path idiom
  return query_repo_root(cwd) / ".claude" / "lazy.settings.json"


def add_protocols(routine_name: str, ids: list[str], *, cwd: Path | str | None = None) -> dict:
  """
  Union protocol reference ids into one routine's `protocols` list.

  Existing entries are preserved in order and de-duplicated, so re-running with the same
  ids is a no-op. The routine entry is otherwise left untouched. When the routine is not
  registered (e.g. the daemon gate unregistered it) nothing is created and the call is a
  no-op reporting `routine_absent`.

  Guarantees:
    - An id already present in the routine's `protocols` list is preserved in its existing
      order and never duplicated; only ids not yet present are appended.
    - When `routine_name` is not present in the tracked settings' `routines` section, no
      entry is created; the call returns `routine_absent: True` and touches nothing on disk.

  Args:
    routine_name: Key under the `routines` section to attach protocols to.
    ids: Protocol reference ids (`<plugin>:<name>`) to union into the routine.
    cwd: Directory inside the repository, or `None` for `LAZY_REPO_ROOT`, else the process working directory; the
      settings file is the `.claude/lazy.settings.json` at the root of the checkout that directory sits in, where
      the daemon reads the routines.

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

  # Contract:
  # When `routine_name` is not present in the tracked settings' `routines` section, no entry
  # is created; the call returns `routine_absent: True` and touches nothing on disk.

  # guard: routine not registered — nothing to attach to
  if not isinstance(routine, dict):
    return { "routine": routine_name, "routine_absent": True, "added": [], RoutineKey.PROTOCOLS: [] }
  current = routine.get(RoutineKey.PROTOCOLS)
  if not isinstance(current, list):
    current = []

  # Contract:
  # An id already present in the routine's `protocols` list is preserved in its existing
  # order and never duplicated; only ids not yet present are appended.

  # union the requested ids into the routine's existing protocols, in order
  added: list[str] = []
  for pid in ids:
    # guard: already attached — preserve, never duplicate
    if pid in current:
      continue
    current.append(pid)
    added.append(pid)
  routine[RoutineKey.PROTOCOLS] = current

  # write only when something was added, so a no-op round-trip leaves the file untouched
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
