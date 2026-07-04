#!/usr/bin/env python3

"""
Runtime enablement gate for lazycortex-core lifecycle hooks.

Each hook calls `is_enabled(<short-name>)` as its first action and returns without work when the
gate answers False. Two mutually-exclusive modes, keyed on the presence of the
`LAZYCORTEX_HOOKS_ALLOW_LIST` environment variable:

- variable present (allow-list mode) — only the named hooks run. The pump sets it for every
  expert spawn from the expert's `hooks.enabled` list, so a spawn runs no lazycortex hook unless
  it is explicitly opted in; a present-but-empty value disables every hook. The variable is named
  for the action it exerts, not for who set it — an operator can export it in a shell to get the
  same behaviour. Resolved by a pure in-memory check, so an expert spawn short-circuits here
  before touching stdin, git, or the network.
- variable absent (interactive default) — every hook runs unless its short name is listed in
  `lazy.settings.json[hooks][disabled]` (tracked value with the local overlay merged on top).

The interactive block-list read fails open: any resolution error resolves to "not disabled", so
a hook still runs. Silencing a hook is always an explicit act, never an accident of a missing or
malformed settings file.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN_DIR))
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from constants import EnvVar, HooksKey, SettingsFile, SettingsKey  # noqa: E402


def is_enabled(name: str) -> bool:
  """
  Report whether the hook identified by `name` should run in the current process.

  Args:
    name: The hook's canonical short name (a `HookName` value, e.g. `git-guard`).

  Returns:
    True when the hook should proceed; False when the current context disables it — either the
    allow-list environment variable is set and does not contain `name`, or an interactive session
    lists `name` under `hooks.disabled`.
  """
  allow = os.environ.get(EnvVar.HOOKS_ALLOW_LIST)
  # Allow-list mode: the variable's presence is the signal, regardless of who set it. Pure
  # in-memory check — the expert-spawn fast path exits here with no I/O.
  if allow is not None:
    return name in { item.strip() for item in allow.split(",") if item.strip() }
  # Interactive default: run unless the operator silenced this hook in settings.
  return name not in _disabled_hooks()


def _disabled_hooks() -> frozenset[str]:
  """
  Return the set of hook short names the operator has disabled for interactive sessions.

  Reads the `hooks` section of the current repository's `lazy.settings.json` (tracked value with
  the local overlay merged on top). Fails open — any resolution error yields an empty set so no
  hook is silenced by accident.

  Returns:
    The frozenset of disabled hook short names, or an empty frozenset when none are configured or
    the settings cannot be read.
  """
  repo = _repo_root()
  # guard: not inside a git repository — nothing to disable against
  if repo is None:
    return frozenset()
  settings_path = repo / SettingsFile.REL
  # guard: no settings file for this repository
  if not settings_path.exists():
    return frozenset()
  # noinspection PyBroadException
  try:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    import lazy_settings  # type: ignore  # noqa: E402
    section = lazy_settings.load_section(settings_path, SettingsKey.HOOKS)
  except Exception:
    return frozenset()
  disabled = section.get(HooksKey.DISABLED) or []
  # guard: malformed `disabled` value — treat as no disables
  if not isinstance(disabled, list):
    return frozenset()
  return frozenset(str(item) for item in disabled)


def _repo_root() -> Path | None:
  """
  Return the absolute root of the current git repository, or None when unavailable.

  Returns:
    The repository root as a `Path`, or None when the current directory is not inside a git
    repository or the `git` binary is missing.
  """
  try:
    out = subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL, text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None
  return Path(out) if out else None
