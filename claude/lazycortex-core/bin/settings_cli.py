"""
Generic settings-section read/write surface for the `lazycortex-core` CLI.

This module backs the `settings-get` / `settings-set` subcommands — the blessed
cross-plugin contract that lets a sibling plugin
read and write a top-level section of the consumer's `lazy.settings.json` without
importing any `lazycortex-core` Python. The wire shape is JSON in via stdin, JSON
out via stdout.

Reads go through `lazy_settings.load_tracked_section` (tracked layer only, no local
overlay — the correct layer for a read-modify-write round-trip). Writes go through
`lazy_settings.save_section` (atomic, version-stamped, never touches the local overlay).
The settings file is resolved as `<cwd>/.claude/lazy.settings.json`, where `<cwd>`
follows the same convention every other subcommand uses: the `LAZY_REPO_ROOT` env var,
falling back to the process working directory, overridable per-call with `--cwd`.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
import sys
from pathlib import Path

from lazy_settings import load_tracked_section, save_section


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
  return root / ".claude" / "lazy.settings.json"


def settings_get(section: str, *, cwd: Path | str | None = None) -> dict:
  """
  Load one tracked section of the consumer's `lazy.settings.json`.

  The tracked layer is read without the local overlay, so the returned value is the
  exact on-disk section a subsequent write would round-trip. A section absent from the
  file (or a missing file) yields the `_version`-stamped empty stub that
  `load_tracked_section` produces.

  Args:
    section: Name of the top-level section to read.
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.

  Returns:
    The tracked section dict, or a fresh current-version stub when the section is absent.

  Raises:
    json.JSONDecodeError: If the tracked settings file is not valid JSON.
  """
  return load_tracked_section(_resolve_settings_path(cwd), section)


def settings_set(section: str, value: object, *, cwd: Path | str | None = None) -> dict:
  """
  Persist one section of the consumer's `lazy.settings.json` atomically.

  The section is written through the version-stamping atomic writer; surrounding sections
  are preserved untouched and the local overlay is never written. A non-object section
  value is rejected before any write happens.

  Args:
    section: Name of the top-level section to store under.
    value: Section content to persist; must be a JSON object (dict).
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.

  Returns:
    A confirmation dict of the shape `{"status": "written", "section": <name>}`.

  Raises:
    ValueError: If `value` is not a JSON object (dict).
    OSError: If the tracked settings file or its parent directory cannot be written.
  """
  # guard: a section is always a JSON object — reject scalars / arrays before touching disk
  if not isinstance(value, dict):
    raise ValueError(f"section value must be a JSON object, got {type(value).__name__}")
  save_section(_resolve_settings_path(cwd), section, value)
  return { "status": "written", "section": section }


def cmd_settings_get(argv: list[str]) -> int:
  """
  Run the `settings-get` subcommand: print one tracked section as JSON to stdout.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 2 on argument error.
  """
  parser = argparse.ArgumentParser(prog = "lazycortex-core settings-get")
  parser.add_argument("section")
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  print(json.dumps(settings_get(args.section, cwd = args.cwd)))
  return 0


def cmd_settings_set(argv: list[str]) -> int:
  """
  Run the `settings-set` subcommand: read a JSON object from stdin and persist it.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 on malformed / non-object stdin, 2 on argument error.
  """
  parser = argparse.ArgumentParser(prog = "lazycortex-core settings-set")
  parser.add_argument("section")
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  try:
    value = json.loads(sys.stdin.read() or "null")
  except json.JSONDecodeError as e:
    print(json.dumps({ "error": f"stdin parse: {e}" }))
    return 1
  try:
    confirmation = settings_set(args.section, value, cwd = args.cwd)
  except ValueError as e:
    print(json.dumps({ "error": str(e) }))
    return 1
  print(json.dumps(confirmation))
  return 0
