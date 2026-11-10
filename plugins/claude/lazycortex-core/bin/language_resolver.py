"""
Core language resolver primitive — the repo-wide storage language.

The chain is: the `language` key inside the caller's own top-level section of
`<repo>/.claude/lazy.settings.json` when the caller passes a section, else the
top-level `language` key, else the hardcoded `en`. This verb is the single owner
of that chain: a plugin with its own overriding key passes its section instead of
reading `language` keys itself, and every core-side writer — the history agents,
the runtime doctor, memory notes — calls it without a section instead of guessing
from surrounding text.
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


def resolve_language(repo: Path, *, section: str | None = None) -> str:
  """
  Resolve the language tag of a named settings section, falling back to the repo-wide storage language.

  Guarantees:
    - Always returns a language tag; a missing, unreadable, or malformed
      settings document resolves to `en` instead of raising.
    - A non-empty `language` value of the named section wins over a non-empty top-level `language` value, which
      wins over the floor `en`.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    section: Caller's own top-level settings section whose `language` key overrides the top-level one.

  Returns:
    The `language` value of the named section when one is given and it is a non-empty string, else the top-level
    `language` value when it is a non-empty string, else `en`.
  """

  # Contract:
  # Resolution MUST always yield a language tag: a missing, unreadable, or
  # malformed settings document falls back to `en` rather than raising.

  # Contract:
  # Precedence MUST be: the named section's own non-empty `language` value first,
  # then the top-level non-empty `language` value, then the floor `en`.
  # The top-level value NEVER overrides a non-empty value of the named section.

  # the one settings document the whole chain reads
  settings_path = repo / _SETTINGS_REL

  # guard: no settings file — `en` is the shipped floor
  if not settings_path.is_file():
    return _LANGUAGE_FLOOR
  try:
    settings = json.loads(settings_path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return _LANGUAGE_FLOOR

  # guard: a malformed settings document falls back the same way a missing one does
  if not isinstance(settings, dict):
    return _LANGUAGE_FLOOR

  # the named section's own key first, when the caller names a section and it carries one
  if section is not None:
    section_value = settings.get(section)
    section_lang = section_value.get(_ROOT_LANGUAGE_KEY) if isinstance(section_value, dict) else None
    if isinstance(section_lang, str) and section_lang:
      return section_lang

  # the configured repo-wide code, when the document carries one at all
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
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag naming the caller's own settings section
      "--section", default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "settings section whose own `language` key overrides the top-level one",
  )
  args = parser.parse_args(argv)
  repo: Path = (args.cwd or Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))).resolve()
  print(resolve_language(repo, section = args.section))
  return 0
