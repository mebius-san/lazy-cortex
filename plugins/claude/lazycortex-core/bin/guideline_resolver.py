"""
Guideline-resolution surface for the `lazycortex-core` CLI.

This module backs the `guidelines-resolve` subcommand: it turns a job role plus the guideline entries a caller
declares into the files a job reads, and reports them as JSON, never raising. The enabled plugins' own
`provides_guidelines` canon for the role comes first, then the declared entries. A plugin key of the form
`<plugin>:<name>` resolves to that plugin's reference file, a plain entry is a repository path, and anything
that does not resolve is reported as a warning instead of stopping the job. In declared-only mode no plugin's canon
is read and the answer holds the declared entries alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import lazy_setup  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from plugin_locator import PluginNotFoundError, plugin_root, query_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Where a plugin keeps its manifest and the reference files a key names
_MANIFEST = ".claude-plugin/plugin.json"
_REFERENCES = "references"
# The manifest field mapping a role to the guideline entries the plugin provides for it
_PROVIDES = "provides_guidelines"
# The separator between a key's plugin and its reference name, and the character only a path holds
_KEY_SEP = ":"
_PATH_SEP = "/"
# The JSON keys of the verb's request and answer
_DECLARED, _PATHS, _WARNINGS, _ERROR = "declared", "paths", "warnings", "error"
# The warnings an entry, a plugin or a manifest that does not resolve produces
_NOT_FOUND = "guideline not found: {}"
_PLUGIN_NOT_FOUND = "guideline plugin not found: {}"
_MANIFEST_UNREADABLE = "guideline manifest unreadable: {}"
# The reasons a malformed request is refused with
_NO_ROLE = "--role is required"
_BAD_STDIN = 'stdin must be a JSON object {"declared": [<entry>, ...]} with string entries'


def _split_key(entry: str) -> tuple[str, str] | None:
  """
  Split a guideline entry into its plugin and reference name when it is a plugin key.

  Args:
    entry: Guideline entry, either a `<plugin>:<name>` key or a repository path.

  Returns:
    The plugin name and the reference name, or `None` when the entry is a repository path.
  """

  # Domain(plugin.boundaries):
  # # A guideline entry is a reference key or a repository path
  # An entry naming exactly one plugin and one reference name, separated by a single colon and with no path
  # separator anywhere, is a reference key into that plugin's references. Anything else is a path inside the
  # repository. A path never needs a colon, and a key never holds a directory, so the two forms cannot be confused.

  # an entry with anything but one colon, no path separator and two non-empty halves is a repository path
  plugin, sep, name = entry.partition(_KEY_SEP)
  if entry.count(_KEY_SEP) != 1 or _PATH_SEP in entry or not plugin or not name or not sep:
    return None

  # the plugin and the reference it names
  return plugin, name


def _find_plugin_root(plugin: str, repo: Path, roots: dict[str, Path | None]) -> Path | None:
  """
  Find the root directory of an installed plugin for the repository.

  Args:
    plugin: Plugin name.
    repo: Repository root the lookup starts from.
    roots: Answers already found during this call, by plugin name; updated with this plugin's answer.

  Returns:
    The plugin's root directory, or `None` when no lookup stage locates the plugin.
  """

  # opt: one call's lookups share `roots`, which lives only for that call, so no answer outlives the plugin trees
  if plugin not in roots:
    try:
      roots[plugin] = plugin_root(plugin, start = repo)[0]
    except PluginNotFoundError:
      roots[plugin] = None

  # the remembered root, or None when no stage located the plugin
  return roots[plugin]


def _read_provided(root: Path, role: str) -> list[str] | None:
  """
  Read the guideline entries a plugin provides for a role.

  Args:
    root: Root directory of the plugin.
    role: Job role whose entries are wanted.

  Returns:
    The entries the plugin provides for the role, empty when it provides none, or `None` when its manifest
    cannot be read or does not have the expected shape.
  """

  # guard: a manifest that cannot be read or parsed contributes nothing
  try:
    # waiver: stdlib encoding idiom
    manifest = json.loads((root / _MANIFEST).read_text(encoding = "utf-8"))
  except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    return None

  # guard: the manifest and its field must be objects; an absent field provides nothing
  provided = manifest.get(_PROVIDES, {}) if isinstance(manifest, dict) else None
  if not isinstance(provided, dict):
    return None

  # guard: the role's entries, when declared, must be a list of strings
  entries = provided.get(role, [])
  if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
    return None

  # the entries the plugin provides for the role
  return entries


def resolve_guidelines(repo: Path, role: str, declared: list[str], *,
                       base: Path | None = None, canon: bool = True) -> tuple[list[str], list[str]]:
  """
  Resolve the guideline files a job of one role reads, without raising.

  Enabled plugins' canon for the role comes first, followed by the caller's declared entries; the canon can be
  switched off to resolve the declared entries alone.

  Guarantees:
    - Each entry appears at most once in the paths, at its first position.
    - Enabled plugins' entries come first, in plugin name order, then the declared entries.
    - Without the canon, the paths hold the declared entries alone, the role is ignored, and no plugin or manifest
      warning is produced.
    - A plugin key becomes an absolute path, a repository path stays as written, and only existing files are
      listed.
    - A path a plugin provides is checked against `repo`; a path the caller declares is checked against `base`,
      or against `repo` when no `base` is given.
    - Every entry, plugin or manifest that does not resolve produces one warning, and nothing here raises.

  Args:
    repo: Repository root; the enabled plugins and the paths they provide are read against it.
    role: Job role whose canon the enabled plugins provide; ignored without the canon.
    declared: Guideline entries the caller declares, each a `<plugin>:<name>` key or a repository path.
    base: Directory the caller's declared paths are relative to; `None` means `repo`.
    canon: Whether the enabled plugins' canon for the role is included; `False` resolves the declared entries alone.

  Returns:
    The resolved guideline paths and the warnings for everything that did not resolve.
  """

  # Domain(plugin.boundaries):
  # # The guidelines a job of one role reads
  # A language plugin enabled in a repository brings the canon each role needs, so the canon reaches every job
  # without any per-repository setting. The plugins' entries form the outermost layer, plugins taken by name, and
  # the entries the repository's own settings declare follow them. An entry listed twice is read once, where it
  # first appears. Only files that exist are read; every entry, plugin or plugin manifest that cannot be resolved
  # is reported as a warning and never stops the job from going out.

  # Contract:
  # `paths` holds each entry at most once, at its first position, enabled plugins' entries first in plugin name
  # order, then `declared`; a key becomes an absolute path, a path stays as written, and only existing files are
  # listed. A plugin-provided path is checked against `repo`, a declared path against `base` (default `repo`).
  # Every entry, plugin or manifest that does not resolve is one warning; nothing here raises. With `canon` off no
  # enabled plugin's manifest is read: `paths` holds `declared` alone, `role` is ignored and no plugin or manifest
  # warning is produced.

  # the enabled plugins' entries for the role, in plugin name order, ahead of the caller's; each entry keeps the
  # directory its path form is relative to
  roots: dict[str, Path | None] = {}
  warnings: list[str] = []
  entries: dict[str, Path] = {}
  for plugin in sorted(lazy_setup.read_enabled_plugins(repo)) if canon else []:
    # guard: a plugin no stage locates provides nothing and is reported
    if (root := _find_plugin_root(plugin, repo, roots)) is None:
      warnings.append(_PLUGIN_NOT_FOUND.format(plugin))
      continue

    # guard: a manifest that cannot be used provides nothing and is reported
    if (provided := _read_provided(root, role)) is None:
      warnings.append(_MANIFEST_UNREADABLE.format(plugin))
      continue

    # the plugin's entries, each path form relative to the repository
    for entry in provided:
      entries.setdefault(entry, repo)

  # the caller's entries after every plugin's, each path form relative to `base`, the repository by default
  for entry in declared:
    entries.setdefault(entry, base or repo)

  # each distinct entry resolved in first-seen order, the unresolved ones reported
  paths: list[str] = []
  for entry, anchor in entries.items():
    key = _split_key(entry)
    if key is None:
      found = entry if (anchor / entry).is_file() else None
    else:
      key_root = _find_plugin_root(key[0], repo, roots)
      target = key_root / _REFERENCES / f"{key[1]}.md" if key_root is not None else None
      found = str(target) if target is not None and target.is_file() else None

    # a resolved entry joins the paths, an unresolved one becomes a warning
    if found is None:
      warnings.append(_NOT_FOUND.format(entry))
    else:
      paths.append(found)

  # the readable guidelines and everything that did not resolve
  return paths, warnings


def _parse_declared(text: str) -> list[str] | None:
  """
  Parse the declared guideline entries out of the request text.

  Args:
    text: Request body, expected to be a JSON object with a list of string entries under `declared`.

  Returns:
    The declared entries in the caller's order, or `None` when the request is malformed.
  """

  # guard: stdin that is not JSON is malformed
  try:
    request = json.loads(text)
  except json.JSONDecodeError:
    return None

  # guard: the request must be an object whose `declared` is a list of strings
  declared = request.get(_DECLARED) if isinstance(request, dict) else None
  if not isinstance(declared, list) or not all(isinstance(entry, str) for entry in declared):
    return None

  # the caller's entries, in its order
  return declared


def cmd_guidelines_resolve(argv: list[str]) -> int:
  """
  Run the `guidelines-resolve` subcommand: print the resolved guidelines as one JSON line to stdout.

  The request is read from stdin as a JSON object with the declared entries. A refused request prints
  `{"paths": null, "warnings": [], "error": ...}`.

  Args:
    argv: Argument vector after the subcommand name (`--role`, optional `--cwd`, `--base`); `--declared-only`
      resolves the declared entries alone and makes `--role` optional.

  Returns:
    Process exit code: 0 on success, 1 when stdin is malformed or, without `--declared-only`, the role is missing.

  Raises:
    SystemExit: With code 2 when `argv` holds an unknown argument.
  """

  # the verb's command line: the job's role and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core guidelines-resolve")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--role", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--base", default = None, help = "Directory declared paths are relative to (default: root)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--declared-only", action = "store_true", help = "Resolve the declared entries alone")
  args = parser.parse_args(argv)

  # read the declared guideline entries from stdin; a missing role outranks a malformed request
  declared = _parse_declared(sys.stdin.read())
  role_missing = not args.role and not args.declared_only

  # guard: a missing role or a malformed request is refused with the error answer
  if role_missing or declared is None:
    print(json.dumps({ _PATHS: None, _WARNINGS: [], _ERROR: _NO_ROLE if role_missing else _BAD_STDIN }))
    return 1

  # resolve against the checkout the command works in and print the one-line answer
  paths, warnings = resolve_guidelines(query_repo_root(args.cwd), args.role or "", declared,
                                       base = Path(args.base).resolve() if args.base else None,
                                       canon = not args.declared_only)
  print(json.dumps({ _PATHS: paths, _WARNINGS: warnings }))
  return 0
