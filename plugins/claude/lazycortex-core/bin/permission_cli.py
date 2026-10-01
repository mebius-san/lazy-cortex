"""
Helper backing the `lazycortex-core permission-allow` CLI subcommand.

The subcommand registers one Bash allow-pattern in a Claude Code settings
file's `permissions.allow` list. Per `lazy-core.hygiene` § Settings split,
per-tool permissions belong in `settings.local.json` (gitignored), never
tracked `settings.json`; this helper does not enforce the file name, just
applies the pattern wherever the caller points it.

Idempotent: the pattern is appended only when absent; existing patterns
are preserved untouched. The settings file is created (with any missing
parent dirs) when it doesn't yet exist. The wire shape is plain stdout:
`added` on insertion, `already-present` on a no-op.

This module exists so each plugin's install skill can register its CLI
allow-pattern in one Bash line — no per-skill duplicated inline Python.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _Outcome:
  """
  Stdout wire-shape outcomes returned by `ensure_permission_allow`.
  """

  ADDED = "added"
  ALREADY_PRESENT = "already-present"
  PRESENT = "present"
  ABSENT = "absent"


class _SettingsKey:
  """
  Top-level keys this helper reads/writes in the target settings JSON.
  """

  PERMISSIONS = "permissions"
  ALLOW = "allow"


class _CliMeta:
  """
  Argparse metadata for the `permission-allow` subcommand.
  """

  PROG = "lazycortex-core permission-allow"
  ARG_PATH = "settings_path"
  ARG_PATTERN = "pattern"
  HELP_PATH = "Target settings file (e.g. .claude/settings.local.json)"
  HELP_PATTERN = "Bash allow-pattern, e.g. Bash(lazycortex-specs *)"
  ARG_CHECK = "--check"
  HELP_CHECK = "Only report whether the pattern is present (present / absent); never write"


def ensure_permission_allow(settings_path: Path, pattern: str) -> str:
  """
  Ensure a Bash allow-pattern is present in a settings file's permissions.allow list.

  The settings file is loaded as JSON (creating an empty object when absent), the
  `permissions.allow` list is materialised on demand, and the pattern is appended only
  when not already present. The file is rewritten atomically with two-space indentation
  and a trailing newline. Parent directories are created when missing.

  Guarantees:
    - An entry already present in `permissions.allow` is never removed, duplicated, or
      reordered; `pattern` is appended at most once, only when not already a member.

  Args:
    settings_path: Path to the settings file (typically `<root>/.claude/settings.local.json`).
    pattern: Allow-pattern string, e.g. `Bash(lazycortex-specs *)`.

  Returns:
    `_Outcome.ADDED` when the pattern was newly inserted, `_Outcome.ALREADY_PRESENT`
    when the call was a no-op.

  Raises:
    json.JSONDecodeError: If the settings file exists but is not valid JSON.
    OSError: If the file or its parent directory cannot be written.
  """

  # Contract:
  # An entry already present in `permissions.allow` is never removed, duplicated, or
  # reordered; `pattern` is appended at most once, only when not already a member.

  # load the settings file, defaulting to an empty object when it doesn't yet exist
  data: dict = json.loads(settings_path.read_text(encoding = "utf-8")) if settings_path.exists() else {}
  perms = data.setdefault(_SettingsKey.PERMISSIONS, {})
  allow = perms.setdefault(_SettingsKey.ALLOW, [])
  if pattern in allow:
    return _Outcome.ALREADY_PRESENT
  allow.append(pattern)
  runtime_state.atomic_write_text(settings_path, json.dumps(data, indent = 2) + "\n")
  return _Outcome.ADDED


def has_permission_allow(settings_path: Path, pattern: str) -> bool:
  """
  Report whether a Bash allow-pattern is already in a settings file's permissions.allow list.

  A missing file, or one without a `permissions.allow` list, holds no pattern. Nothing is
  written or created.

  Args:
    settings_path: Path to the settings file.
    pattern: Allow-pattern string to look for.

  Returns:
    True when `pattern` is a member of `permissions.allow`, False otherwise.

  Raises:
    json.JSONDecodeError: If the settings file exists but is not valid JSON.
  """
  # guard: an absent file carries no permissions at all
  if not settings_path.exists():
    return False
  data = json.loads(settings_path.read_text(encoding = "utf-8"))
  return pattern in data.get(_SettingsKey.PERMISSIONS, {}).get(_SettingsKey.ALLOW, [])


def cmd_permission_allow(argv: list[str]) -> int:
  """
  Run the `permission-allow` subcommand: register one Bash allow-pattern in a settings file.

  Parses `<settings-path>` and `<pattern>` positional args, applies the idempotent ensure,
  prints the outcome word (`added` / `already-present`) to stdout, exits 0 on success. With
  `--check` it only probes: prints `present` / `absent` and touches nothing, so an install
  skill can skip the writing call when the pattern is already registered.

  Args:
    argv: Subcommand argv tail (positional `<settings-path>` then `<pattern>`).

  Returns:
    Process exit code: `0` on success, `2` on argument-parse failure.
  """
  parser = argparse.ArgumentParser(prog=_CliMeta.PROG)
  parser.add_argument(_CliMeta.ARG_PATH, help=_CliMeta.HELP_PATH)
  parser.add_argument(_CliMeta.ARG_PATTERN, help=_CliMeta.HELP_PATTERN)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument(_CliMeta.ARG_CHECK, action="store_true", help=_CliMeta.HELP_CHECK)
  args = parser.parse_args(argv)
  settings_path = Path(getattr(args, _CliMeta.ARG_PATH))
  pattern = getattr(args, _CliMeta.ARG_PATTERN)

  # guard: the probe answers without writing and leaves the file untouched
  if args.check:
    print(_Outcome.PRESENT if has_permission_allow(settings_path, pattern) else _Outcome.ABSENT)
    return 0
  print(ensure_permission_allow(settings_path, pattern))
  return 0
