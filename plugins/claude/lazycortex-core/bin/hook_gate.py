#!/usr/bin/env python3

"""
Runtime enablement gate for lazycortex-core lifecycle hooks.

Each hook calls `is_enabled(<short-name>)` as its first action and returns without work when the
gate answers False. Two mutually-exclusive modes, keyed on the presence of the
`LAZYCORTEX_HOOKS_ALLOW_LIST` environment variable:

- variable present (allow-list mode) — only the named hooks run. The daemon sets it for every
  routine it dispatches, from that routine's `hooks_enabled` list, so nothing the daemon spawns
  runs a lazycortex hook unless it is explicitly opted in; a present-but-empty value disables
  every hook. The variable is named for the action it exerts, not for who set it — an operator
  can export it in a shell to get the same behaviour. Resolved by a pure in-memory check, so a
  spawn short-circuits here before touching stdin, git, or the network.
- variable absent (interactive default) — every hook runs unless its short name is listed in
  `lazy.settings.json[hooks][disabled]` (tracked value with the local overlay merged on top).

A hook that acts on a repository other than the session's (a commit made with `git -C <dir>`) passes
that repository's directory, so its `hooks.disabled` decides. Such a hook that must read stdin first
calls `is_admitted(<short-name>)` as its first action — the allow-list half alone, with no settings
read — and `is_enabled(<short-name>, cwd = <dir>)` once the payload names the directory.

The interactive block-list read fails open: any resolution error resolves to "not disabled", so
a hook still runs. Silencing a hook is always an explicit act, never an accident of a missing or
malformed settings file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN_DIR))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from constants import EnvVar, HooksKey, SettingsFile, SettingsKey  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import plugin_locator  # noqa: E402


def is_admitted(name: str) -> bool:
  """
  Report whether the allow-list regime lets the hook identified by `name` run in the current process.

  Guarantees:
    - Decides from the process environment alone: it never reads settings, stdin, or git, so a hook can call it
      before consuming stdin and exit early.

  Args:
    name: The hook's canonical short name (a `HookName` value, e.g. `git-guard`).

  Returns:
    False when the allow-list environment variable is set and does not contain `name`; True otherwise,
    including when the variable is absent.
  """

  # Contract:
  # The answer is decided from the process environment alone. It MUST NEVER read settings, stdin, or git,
  # so a hook can call it before consuming stdin and exit early.

  # the allow-list variable; whether it is set at all selects the regime
  allow = os.environ.get(EnvVar.HOOKS_ALLOW_LIST)

  # no allow-list: the regime has no say, the block-list in settings decides
  if allow is None:
    return True

  # the variable's presence is the signal; only the hooks it names run
  return name in { item.strip() for item in allow.split(",") if item.strip() }


def is_enabled(name: str, *, cwd: Path | None = None) -> bool:
  """
  Report whether the hook identified by `name` should run in the current process.

  Guarantees:
    - Any failure to resolve the disabled-hooks list — no repository, no settings file, or an unreadable or
      malformed value — leaves every hook enabled; only an explicit `hooks.disabled` entry can disable one.
    - When `cwd` is given, only the `hooks.disabled` of the repository holding `cwd` is judged; the process's own
      working directory is never consulted.

  Notes:
    - Under the allow-list environment variable the answer comes from the environment alone, with no I/O.
    - Otherwise it runs several `git` subprocesses and reads the repository's settings file on every call; nothing
      is cached.

  Args:
    name: The hook's canonical short name (a `HookName` value, e.g. `git-guard`).
    cwd: A directory inside the repository whose `hooks.disabled` is read; `None` reads the repository
      of the process's working directory.

  Returns:
    True when the hook should proceed; False when the current context disables it — either the
    allow-list environment variable is set and does not contain `name`, or an interactive session
    finds `name` under `hooks.disabled` of that repository.
  """

  # Contract:
  # Any failure to resolve the disabled-hooks list (no repository, no settings file, an unreadable or
  # malformed value) MUST leave every hook enabled; only an explicit `hooks.disabled` entry can disable one.

  # Contract:
  # When `cwd` is given, only the `hooks.disabled` of the repository holding `cwd` decides; the process's own
  # working directory MUST NEVER be consulted.

  # Domain(runtime.daemon-loop):
  # # Which hooks a spawn may run
  # A spawned process runs under one of two mutually exclusive regimes for deciding which hooks
  # fire. When it carries an explicit allow-list, only the hooks named in that list run at all, and
  # an allow-list that names nothing disables every hook for that spawn — a dispatcher sets this
  # regime for every unit of work it hands off, scoped to that unit's own declared hook set, so
  # nothing it triggers runs a hook it never opted into. When no allow-list is present, every hook
  # runs by default, and only an explicit operator block-list can silence one — an interactive
  # session is presumed to want the full hook set unless told otherwise.

  # allow-list mode: the variable's presence is the signal, regardless of who set it. Pure
  # in-memory check — the expert-spawn fast path exits here with no I/O.
  if os.environ.get(EnvVar.HOOKS_ALLOW_LIST) is not None:
    return is_admitted(name)

  # interactive default: run unless the operator silenced this hook in that repository's settings.
  return name not in _disabled_hooks(cwd)


def _disabled_hooks(cwd: Path | None) -> frozenset[str]:
  """
  Return the set of hook short names the operator has disabled for interactive sessions.

  Reads the `hooks` section of the nearest `lazy.settings.json` from `cwd` upward within the repository holding it,
  else the one at that repository's root (tracked value with the local overlay merged on top). Fails open — any
  resolution error (no repository, no settings file, or an unreadable or malformed value) yields an empty set, so
  only an explicit `hooks.disabled` entry silences a hook.

  Notes:
    - Runs several `git` subprocesses (repository root, settings root, nearest-directory bound) and reads the
      settings file from disk on every call.

  Args:
    cwd: A directory inside the repository to read; `None` means the process's working directory.

  Returns:
    The frozenset of disabled hook short names, or an empty frozenset when none are configured or
    the settings cannot be read.
  """

  # Domain(runtime.daemon-loop):
  # # Silencing a hook is always deliberate
  # A hook is treated as disabled only when the operator's own configuration names it explicitly.
  # Any failure to resolve that configuration — no repository, no settings file, an unreadable or
  # malformed value — resolves to nothing being disabled, never the other way around. A hook must
  # never fall silent because of a missing or broken settings file; it can only fall silent because
  # someone said so.

  # guard: not inside a git repository — nothing to disable against
  if _repo_root(cwd) is None:
    return frozenset()

  # the block-list lives in the settings nearest to the directory within that repository, never the session's
  settings_path = plugin_locator.query_settings_root(cwd if cwd is not None else Path.cwd()) / SettingsFile.REL

  # guard: no settings file for this repository
  if not settings_path.exists():
    return frozenset()

  # load the hooks section; any failure to load it leaves no hook disabled
  # noinspection PyBroadException
  try:
    # waiver: lazy_settings is imported inside this try so any failure to load it leaves no hook disabled;
    # a module-level import would make a broken settings loader take the hook down instead of failing open
    # waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
    import lazy_settings  # type: ignore  # noqa: E402  # pylint: disable=import-error
    section = lazy_settings.load_section(settings_path, SettingsKey.HOOKS)
  except Exception:
    return frozenset()

  # the operator's block-list, empty when the key is absent
  disabled = section.get(HooksKey.DISABLED) or []

  # guard: malformed `disabled` value — treat as no disables
  if not isinstance(disabled, list):
    return frozenset()

  # names compare as text, so a non-string entry still silences the hook it spells
  return frozenset(str(item) for item in disabled)


def _repo_root(cwd: Path | None) -> Path | None:
  """
  Return the absolute root of the git repository holding a directory, or None when unavailable.

  Notes:
    - Runs a `git` subprocess on every call; its error output is discarded.

  Args:
    cwd: The directory to resolve from; `None` means the process's working directory.

  Returns:
    The root of the checkout the directory sits in as a `Path`, a linked worktree's own root inside one; None when
    the directory is missing or not inside a git repository, or the `git` binary is missing.
  """
  return plugin_locator.find_checkout_toplevel(cwd if cwd is not None else Path.cwd())
