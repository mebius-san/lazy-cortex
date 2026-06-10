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
from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _Outcome:
  """
  Stdout wire-shape outcomes returned by `ensure_permission_allow`.
  """

  ADDED = "added"
  ALREADY_PRESENT = "already-present"


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


def ensure_permission_allow(settings_path: Path, pattern: str) -> str:
  """
  Ensure a Bash allow-pattern is present in a settings file's permissions.allow list.

  The settings file is loaded as JSON (creating an empty object when absent), the
  `permissions.allow` list is materialised on demand, and the pattern is appended only
  when not already present. The file is rewritten atomically with two-space indentation
  and a trailing newline. Parent directories are created when missing.

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
  data: dict = json.loads(settings_path.read_text()) if settings_path.exists() else {}
  perms = data.setdefault(_SettingsKey.PERMISSIONS, {})
  allow = perms.setdefault(_SettingsKey.ALLOW, [])
  if pattern in allow:
    return _Outcome.ALREADY_PRESENT
  allow.append(pattern)
  settings_path.parent.mkdir(parents=True, exist_ok=True)
  settings_path.write_text(json.dumps(data, indent=2) + "\n")
  return _Outcome.ADDED


def cmd_permission_allow(argv: list[str]) -> int:
  """
  Run the `permission-allow` subcommand: register one Bash allow-pattern in a settings file.

  Parses `<settings-path>` and `<pattern>` positional args, applies the idempotent ensure,
  prints the outcome word (`added` / `already-present`) to stdout, exits 0 on success.

  Args:
    argv: Subcommand argv tail (positional `<settings-path>` then `<pattern>`).

  Returns:
    Process exit code: `0` on success, `2` on argument-parse failure.
  """
  parser = argparse.ArgumentParser(prog=_CliMeta.PROG)
  parser.add_argument(_CliMeta.ARG_PATH, help=_CliMeta.HELP_PATH)
  parser.add_argument(_CliMeta.ARG_PATTERN, help=_CliMeta.HELP_PATTERN)
  args = parser.parse_args(argv)
  outcome = ensure_permission_allow(Path(getattr(args, _CliMeta.ARG_PATH)), getattr(args, _CliMeta.ARG_PATTERN))
  print(outcome)
  return 0
