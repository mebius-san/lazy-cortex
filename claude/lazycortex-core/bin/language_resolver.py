"""
Core language resolver primitive — the repo-wide storage language.

The core chain has one rung and a floor: the top-level `language` key of
`<repo>/.claude/lazy.settings.json`, else the hardcoded `en`. Plugins with
their own overriding key (specs, wiki) resolve through their own CLI; this
verb is what every core-side writer — the history agents, the runtime
doctor, memory notes — reads instead of guessing from surrounding text.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_ROOT_LANGUAGE_KEY = "language"
_LANGUAGE_FLOOR = "en"


def resolve_language(repo: Path) -> str:
  """
  Resolve the repo-wide storage language from the settings document.

  Guarantees:
    - Always returns a language tag; a missing, unreadable, or malformed
      settings document resolves to `en` instead of raising.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.

  Returns:
    The top-level `language` value when it is a non-empty string, else `en`.
  """

  # Contract:
  # Resolution MUST always yield a language tag: a missing, unreadable, or
  # malformed settings document falls back to `en` rather than raising.

  # the one settings document the whole chain reads
  settings_path = repo / _SETTINGS_REL

  # guard: no settings file — `en` is the shipped floor
  if not settings_path.is_file():
    return _LANGUAGE_FLOOR
  try:
    settings = json.loads(settings_path.read_text())
  except (OSError, json.JSONDecodeError):
    return _LANGUAGE_FLOOR
  # guard: a malformed settings document falls back the same way a missing one does
  if not isinstance(settings, dict):
    return _LANGUAGE_FLOOR

  # the configured code, when the document carries one at all
  value = settings.get(_ROOT_LANGUAGE_KEY)
  # guard: an absent or empty key leaves the floor in place
  if not isinstance(value, str) or not value:
    return _LANGUAGE_FLOOR
  return value


def main(argv: list[str]) -> int:
  """
  Resolve the repo-wide language from the command line and print it.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code 0 on success.
  """
  # the CLI front door for the resolver — one optional repo root, the resolved tag on stdout
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-core resolve-language")
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + repo-root default
      "--cwd", type = Path, default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "repo root holding .claude/lazy.settings.json (default: $LAZY_REPO_ROOT or cwd)",
  )
  args = parser.parse_args(argv)
  repo: Path = (args.cwd or Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))).resolve()
  print(resolve_language(repo))
  return 0
