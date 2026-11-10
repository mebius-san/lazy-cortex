#!/usr/bin/env python3

"""
Snippet enabler for the lazycortex-obsidian plugin.

The one editor of the enabled CSS snippet list in a vault's appearance settings. Backs the `snippet-enable`
verb, which prints one JSON line with status `applied`, `no-vault`, or `refused`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import vault_manifest  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from iconize_sync import IconizeError, find_vault  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from vault_keys import Encoding, VaultPath  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The appearance key listing every enabled snippet by name
ENABLED_KEY = "enabledCssSnippets"

# The suffix a snippet file carries on disk
SNIPPET_SUFFIX = ".css"

# Per-snippet outcomes
ENABLED, ALREADY_ENABLED, DEFERRED = "enabled", "already-enabled", "deferred"

# Run statuses the CLI prints
STATUS_APPLIED, STATUS_NO_VAULT, STATUS_REFUSED = "applied", "no-vault", "refused"

# Refusal reasons
UNPARSEABLE_REASON = "{path} does not parse as JSON; left untouched"
NOT_OBJECT_REASON = "{path} is not a JSON object; left untouched"
NOT_ARRAY_REASON = "{path}: `enabledCssSnippets` is not a JSON array; left untouched"

# Exit code of a refused run
EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class SnippetEnableRefusedError(Exception):
  """
  Refusal to edit the appearance settings, raised before anything is written.

  Attributes:
    reason: One-line explanation of the refusal.
  """

  def __init__(self, reason: str) -> None:
    """
    Create a refusal carrying a reportable reason.

    Args:
      reason: One-line explanation of the refusal.
    """
    super().__init__(reason)

    # The one-line reason the caller reports
    self.reason: str = reason


@dataclass
class EnableResult:
  """
  Outcome of one enable run.

  Attributes:
    snippets: Outcome per requested snippet name: enabled, already-enabled, or deferred when its file is missing.
    touched_paths: Vault-relative paths written by the run.
  """

  # The outcome per requested snippet name
  snippets: dict[str, str] = field(default_factory = dict)
  # Vault-relative paths the run wrote
  touched_paths: list[str] = field(default_factory = list)


# ----------------------------------------------------------------------------------------
def _read_config(config: Path) -> dict:  # waiver: Obsidian config JSON, shape is not ours
  """
  Read the appearance settings file.

  Args:
    config: Appearance settings file inside the vault.

  Returns:
    The settings object, empty when the file does not exist.

  Raises:
    SnippetEnableRefusedError: If the file does not parse, is not an object, or its snippet list is not an array.
  """
  # guard: an absent file starts from an empty config
  if not config.exists():
    return {}

  # an unreadable or unparseable file is refused
  try:
    data = json.loads(config.read_text(encoding = Encoding.UTF8))
  except (OSError, ValueError) as error:
    raise SnippetEnableRefusedError(UNPARSEABLE_REASON.format(path = config)) from error

  # guard: only an object can carry the snippet list
  if not isinstance(data, dict):
    raise SnippetEnableRefusedError(NOT_OBJECT_REASON.format(path = config))

  # guard: a snippet list of another shape cannot be appended to safely
  if not isinstance(data.get(ENABLED_KEY, []), list):
    raise SnippetEnableRefusedError(NOT_ARRAY_REASON.format(path = config))
  return data


def enable(vault: Path, names: list[str]) -> EnableResult:
  """
  Enable each named snippet whose stylesheet exists and is not listed yet.

  Guarantees:
    - Existing entries are never removed.
    - The settings file is written once, and only when the list grew; a run that enables nothing leaves it untouched.

  Args:
    vault: Obsidian config directory.
    names: Snippet names, without the stylesheet suffix.

  Returns:
    The per-snippet outcomes and the vault-relative paths written.

  Raises:
    SnippetEnableRefusedError: If the settings file cannot be edited safely; nothing is written.
  """

  # Contract:
  # Entries already present in the enabled snippet list are never removed;
  # a run only ever adds names.

  # Contract:
  # The settings file is written only when at least one snippet was newly enabled,
  # and then exactly once; a run that enables nothing leaves the file untouched.

  # read the current list the run appends to
  config = vault / VaultPath.APPEARANCE
  data = _read_config(config)
  enabled: list = list(data.get(ENABLED_KEY, []))  # waiver: Obsidian config JSON, entries are not ours
  result = EnableResult()

  # each name is appended only when its file is on disk and it is not listed yet
  for name in names:
    if name in enabled:
      result.snippets[name] = ALREADY_ENABLED
    elif not (vault / VaultPath.SNIPPETS / f"{name}{SNIPPET_SUFFIX}").is_file():
      result.snippets[name] = DEFERRED
    else:
      enabled.append(name)
      result.snippets[name] = ENABLED

  # the file is written once, and only when the list grew
  if ENABLED in result.snippets.values():
    data[ENABLED_KEY] = enabled
    vault_manifest.dump_json(config, data)
    result.touched_paths.append("/".join(config.relative_to(vault.parent).parts))
  return result


# ----------------------------------------------------------------------------------------
def _emit(status: str, result: EnableResult, reason: str | None) -> None:
  """
  Print the run outcome as one JSON line.

  Args:
    status: Run status.
    result: Per-snippet outcomes and written paths.
    reason: Refusal reason, or None when the run was not refused.
  """
  print(json.dumps({ "status": status, "snippets": result.snippets, "touched_paths": result.touched_paths,
                     "reason": reason }, ensure_ascii = False))


def main(argv: list[str]) -> int:
  """
  Run the `snippet-enable` command.

  Notes:
    - Prints one JSON line with status `applied`, `no-vault`, or `refused`.

  Args:
    argv: Command-line arguments, without the program name.

  Returns:
    Zero on success or when the checkout has no config directory, one when the run was refused.
  """
  # waiver: argparse CLI signature
  parser = argparse.ArgumentParser(prog = "lazycortex-obsidian snippet-enable")
  # waiver: argparse CLI signature
  parser.add_argument("--name", action = "append", required = True, help = "snippet name, without .css")
  # waiver: argparse CLI signature
  parser.add_argument("--vault", help = "Obsidian config directory (default: <git toplevel>/.obsidian)")
  args = parser.parse_args(argv)

  # resolve the config directory; a checkout that cannot name one is refused
  try:
    vault = Path(args.vault) if args.vault else find_vault(None) / VaultPath.OBSIDIAN
  except IconizeError as error:
    _emit(STATUS_REFUSED, EnableResult(), str(error))
    return EXIT_REFUSED

  # guard: a checkout without a config directory has nothing to enable
  if not vault.is_dir():
    _emit(STATUS_NO_VAULT, EnableResult(), None)
    return 0

  # a refusal names its reason and leaves the file as it was
  try:
    result = enable(vault, args.name)
  except SnippetEnableRefusedError as error:
    _emit(STATUS_REFUSED, EnableResult(), error.reason)
    return EXIT_REFUSED
  _emit(STATUS_APPLIED, result, None)
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
