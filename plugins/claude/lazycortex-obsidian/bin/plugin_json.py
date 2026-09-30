#!/usr/bin/env python3
"""
JSON primitives behind the `lazy-obsidian.update-plugin` skill, needing no `jq` — absent from Git Bash on
Windows.

Exposes two verbs: `version`, printing a manifest's `version` field, and `merge-overrides`, deep-merging
one plugin's override block onto its vault `data.json`.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Sequence


# the path argument that means "read the document from stdin"
_STDIN = "-"

# the manifest field carrying a plugin's version
_VERSION_KEY = "version"

# the two verbs this script serves
_VERB_VERSION, _VERB_MERGE = "version", "merge-overrides"

# every JSON document here is UTF-8; the suffix of the sibling a write goes through before its rename
_ENCODING, _TMP_SUFFIX = "utf-8", ".tmp"

# the `merge-overrides` outcomes the skill reports verbatim
_NO_OVERRIDES, _APPLIED, _CURRENT = "no-overrides", "overrides-applied", "overrides-current"

# exit code for a file that cannot be read or written, does not parse, or has the wrong shape
_EXIT_INVALID = 1


# ----------------------------------------------------------------------------------------
def read_version(source: str) -> str:
  """
  Read a manifest's string `version` field.

  Args:
    source: Manifest path, or `-` to read the document from stdin.

  Returns:
    The manifest's `version` value, or an empty string when the field is absent or not a string.

  Raises:
    OSError: If `source` names a file that cannot be read.
    ValueError: If the document is not valid JSON.
  """
  data = json.loads(sys.stdin.read() if source == _STDIN else Path(source).read_text(encoding = _ENCODING))

  # a manifest without a string version reads as an absent plugin
  version = data.get(_VERSION_KEY) if isinstance(data, dict) else None
  return version if isinstance(version, str) else ""


# ----------------------------------------------------------------------------------------
def deep_merge(base: dict, override: dict) -> dict:
  """
  Merge one mapping's keys onto another, recursively for nested objects.

  Guarantees:
    - A key whose value is an object in both mappings merges recursively; any other value, including
      an array, is replaced outright by the override's value.
    - `base` is never mutated; every returned mapping, at every nesting level, is a new object that
      shares nothing with `base` or `override`.

  Args:
    base: Mapping providing the values a key keeps when the override does not touch it.
    override: Mapping whose keys take precedence over `base`.

  Returns:
    A new mapping combining both inputs per the merge guarantee above.
  """

  # Contract:
  # A key whose value is an object on both sides merges recursively; any other override
  # value, arrays included, replaces the base value outright.

  # Contract:
  # `base` is never mutated. Every mapping this returns, at every nesting level, is a new
  # object; nothing in the result is shared with either `base` or `override`.

  # a key the override leaves alone keeps a deep copy of its base value, so nothing is shared with `base`
  merged = { key: copy.deepcopy(value) for key, value in base.items() if key not in override }

  # an override key wins; two objects under one key merge recursively, anything else is replaced
  for key, value in override.items():
    merged[key] = deep_merge(base[key], value) if isinstance(base.get(key), dict) and isinstance(value, dict) \
        else copy.deepcopy(value)
  return merged


# ----------------------------------------------------------------------------------------
def merge_overrides(settings: Path, plugin_id: str, data_file: Path, *, dry_run: bool) -> str:
  """
  Apply one plugin's override block onto its vault data file.

  Guarantees:
    - Writes the merged data atomically, so an interrupted run never leaves a partially written file,
      and a completed call leaves no leftover temporary file.
    - Creates the data file when it does not yet exist.
    - Writes nothing when the result is `no-overrides`, `overrides-current`, or a dry run.

  Args:
    settings: Path to the plugin-settings document holding every plugin's override block.
    plugin_id: The plugin whose override block is applied.
    data_file: Path to the vault plugin's data file the override is merged onto.
    dry_run: Reports the outcome without writing when true.

  Returns:
    `no-overrides` when the plugin has no override block, `overrides-current` when the data file
    already carries every override value, or `overrides-applied` when the merge was written (or
    would be, under a dry run).

  Raises:
    ValueError: If the settings file or the data file is not valid JSON, if the settings file's top
      level is not a JSON object, or if an existing data file is not a JSON object.
    OSError: If a file cannot be read or written.
  """

  # Contract:
  # The write is atomic: a caller never observes a partially written data file, and a
  # completed call leaves no leftover temporary file behind.

  # Contract:
  # A missing data file is created rather than treated as an error.

  # Contract:
  # Nothing is written when the outcome is `no-overrides`, `overrides-current`, or a dry
  # run; the data file changes only when an override actually alters it.

  # guard: a settings file that is not an object holds no override blocks to read
  if not isinstance(blocks := json.loads(settings.read_text(encoding = _ENCODING)), dict):
    raise ValueError(f"{settings} is not a JSON object")

  # guard: no override block for this plugin — the vault's data.json is left alone
  if not isinstance(override := blocks.get(plugin_id) or {}, dict) or not override:
    return _NO_OVERRIDES

  # the vault's current data; a missing data.json merges as an empty object
  before = json.loads(data_file.read_text(encoding = _ENCODING)) if data_file.is_file() else {}

  # guard: an existing data.json that is not an object cannot take a merge
  if not isinstance(before, dict):
    raise ValueError(f"{data_file} is not a JSON object")

  # the override applied on top of what the vault already carries
  after = deep_merge(before, override)

  # guard: the vault already carries every override value — nothing to write
  if after == before:
    return _CURRENT

  # guard: a dry run reports the merge it would write and writes nothing
  if dry_run:
    return _APPLIED

  # write-then-rename, so an interrupted run never leaves a half-written data.json
  tmp = data_file.with_name(data_file.name + _TMP_SUFFIX)
  tmp.write_text(json.dumps(after, indent = 2, ensure_ascii = False) + "\n", encoding = _ENCODING)
  os.replace(tmp, data_file)
  return _APPLIED


# ----------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
  """
  Parse CLI arguments and dispatch to the requested verb.

  Args:
    argv: Optional argument list; when None, falls back to the process argv.

  Returns:
    Process exit code: 0 on success, or the invalid-document exit code when a file cannot be read or
    written, does not parse, or has the wrong shape.
  """
  # one subcommand per verb, each taking the paths its skill step names
  # waiver: argparse CLI signature
  parser = argparse.ArgumentParser(prog = "plugin_json")
  # waiver: argparse CLI signature
  sub = parser.add_subparsers(dest = "command", required = True)
  # waiver: argparse CLI signature
  sub.add_parser(_VERB_VERSION, help = "print a manifest's version, empty when absent") \
    .add_argument("manifest", help = "manifest.json path, or - for stdin")
  # waiver: argparse CLI signature
  merge = sub.add_parser(_VERB_MERGE, help = "deep-merge one plugin's override block onto its data.json")
  # waiver: argparse CLI signature
  merge.add_argument("settings", type = Path, help = "plugin-settings.json holding the override blocks")
  # waiver: argparse CLI signature
  merge.add_argument("plugin_id", help = "the plugin whose block is merged")
  # waiver: argparse CLI signature
  merge.add_argument("data", type = Path, help = "the vault plugin's data.json, created when absent")
  # waiver: argparse CLI signature
  merge.add_argument("--dry-run", action = "store_true", help = "report the outcome without writing")

  # a usage error exits through argparse before any file is touched
  args = parser.parse_args(argv)

  # every verb prints one line; a document that does not parse is a one-line error, not a traceback
  try:
    if args.command == _VERB_VERSION:
      print(read_version(args.manifest))
    else:
      print(merge_overrides(args.settings, args.plugin_id, args.data, dry_run = args.dry_run))
  except (OSError, ValueError) as error:
    print(f"plugin_json: {error}", file = sys.stderr)
    return _EXIT_INVALID
  return 0


if __name__ == "__main__":
  sys.exit(main())
