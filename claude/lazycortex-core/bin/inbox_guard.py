"""
Ownership guard for an inbox shared by more than one checkout.

An inbox reached through a symlink is one physical directory, so a repository cloned twice —
an interactive copy and a runtime copy — can end up with two daemons scanning it. Each daemon
keeps its own dedup keys and its own error ledger, so both dispatch a job for the same file
and the document is processed twice. This module detects the two ways that happens: two
supervisor units on this host resolving to one inbox, and a checkout that gates the daemon on
a bare boolean while declaring externally-sourced directories, which cannot distinguish the
machines a synced overlay reaches.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from pathlib import Path

from constants import (
  DaemonKey,
  InboxGuardKey,
  InboxGuardKind,
  RoutineKey,
  RoutineType,
  SettingsFile,
  SettingsKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def _inbox_routines(repo: Path) -> dict[str, Path]:
  """
  Map each inbox routine of a repository to the real directory it scans.

  Notes:
    - The read is best-effort. This runs against every checkout registered on the host, so a
      neighbour with an unreadable or half-written settings file reads as registering no inbox
      routine instead of failing the whole guard for the checkout that asked.

  Args:
    repo: Repository root whose routine registry is read.

  Returns:
    Routine name to canonical absolute inbox path with symlinks resolved; empty when the
    repository registers no inbox routine or its settings cannot be read.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from lazy_settings import load_section
  try:
    registry = load_section(repo / SettingsFile.REL, SettingsKey.ROUTINES)
  except (OSError, ValueError):
    return {}
  out: dict[str, Path] = {}
  for name, cfg in registry.items():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue
    # guard: only an inbox routine scans a directory
    if cfg.get(RoutineKey.TYPE) != RoutineType.INBOX:
      continue
    rel = cfg.get(RoutineKey.INBOX_DIR)
    # guard: a routine without a string inbox path cannot be canonicalised
    if not isinstance(rel, str) or not rel:
      continue
    out[str(name)] = (repo / rel).resolve()
  return out


def check_inbox_collision(repo: Path | str, platform: str | None = None) -> list[dict]:
  """
  Report every other checkout on this host that drives the same physical inbox.

  Notes:
    - Only daemons installed on this host are visible. A checkout synced to a second machine
      is the other case, covered by `check_run_here_specificity`.

  Args:
    repo: Repository root whose inbox routines are being defended.
    platform: Optional `sys.platform` override, forwarded to the daemon registry.

  Returns:
    One finding dict per contested inbox carrying `InboxGuardKey` fields; empty when this
    checkout registers no inbox routine or no other daemon shares one.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from daemon_registry import RegistryRow, enumerate_local_daemons
  repo = Path(repo).resolve()
  mine = _inbox_routines(repo)
  # guard: nothing to contest without a local inbox routine
  if not mine:
    return []
  findings: list[dict] = []
  for row in enumerate_local_daemons(platform):
    other = Path(str(row[RegistryRow.REPO_ROOT])).resolve()
    # guard: this checkout's own supervisor unit is not a second daemon
    if other == repo:
      continue
    for other_name, other_inbox in _inbox_routines(other).items():
      for name, inbox in mine.items():
        # guard: different physical directories are independent
        if other_inbox != inbox:
          continue
        findings.append({
          InboxGuardKey.KIND: InboxGuardKind.COLLISION,
          InboxGuardKey.ROUTINE: name,
          InboxGuardKey.INBOX: str(inbox),
          InboxGuardKey.OTHER_REPO: str(other),
          InboxGuardKey.OTHER_ROUTINE: other_name,
          InboxGuardKey.DETAIL: (
            f"routine '{name}' scans {inbox}, also driven by '{other_name}' in {other}"
          ),
        })
  return findings


def check_run_here_specificity(repo: Path | str) -> list[dict]:
  """
  Report a daemon gate that cannot distinguish the machines a synced overlay reaches.

  A checkout that declares externally-sourced directories is, by construction, reachable from
  a file-synced path, so the gitignored overlay carrying the gate travels to every machine
  holding that path and a bare boolean reads as answered on all of them.

  Args:
    repo: Repository root whose gate and declaration are read.

  Returns:
    One finding dict when the gate is a bare true while external dirs are declared; empty
    otherwise.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from external_dirs import declared_paths
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from lazy_settings import load_local_only_section
  repo = Path(repo)
  # guard: no external declaration — the gate's shape is not this guard's business
  if not declared_paths(repo):
    return []
  gate = load_local_only_section(repo / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.RUN_HERE)
  # guard: only a bare true is under-specified; a host list, false, and absence are all definite
  if gate is not True:
    return []
  return [{
    InboxGuardKey.KIND: InboxGuardKind.RUN_HERE_AMBIGUOUS,
    InboxGuardKey.DETAIL: (
      "daemon.run_here is a bare true while external dirs are declared — pin it to a host "
      "list so a synced overlay cannot start a second daemon on another machine"
    ),
  }]
