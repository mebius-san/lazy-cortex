"""
Generic settings-section read/write surface for the `lazycortex-core` CLI.

This module backs the `settings-get` / `settings-set` subcommands — the blessed
cross-plugin contract that lets a sibling plugin
read and write a top-level section of the consumer's `lazy.settings.json` without
importing any `lazycortex-core` Python. The wire shape is JSON in via stdin, JSON
out via stdout.

Reads default to `lazy_settings.load_tracked_section` (tracked layer only, no local
overlay — the correct layer for a read-modify-write round-trip); `--scope local` reads
the overlay alone and `--scope merged` the effective view. Writes go through
`lazy_settings.save_section` (atomic, version-stamped, never touches the local overlay)
or, with `--scope local`, `lazy_settings.save_local_section`. A slash-separated `--key` narrows
either verb to one nested value inside the section.
The settings file is resolved as `<cwd>/.claude/lazy.settings.json`, where `<cwd>`
follows the same convention every other subcommand uses: the `LAZY_REPO_ROOT` env var,
falling back to the process working directory, overridable per-call with `--cwd`;
`--home` swaps the repo file for the user-scope `~/.claude/lazy.settings.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import SettingsFile  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import (  # pylint: disable=import-error
  load_local_only_section, load_section, load_tracked_section, save_local_section, save_section,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# waiver: CLI --scope vocabulary, fixed by the settings-get / settings-set contract
_READERS: dict[str, Callable[[Path, str], dict[str, object]]] = {
  "tracked": load_tracked_section,
  "local": load_local_only_section,
  "merged": load_section,
}
# waiver: CLI --scope vocabulary, fixed by the settings-get / settings-set contract
_WRITERS: dict[str, Callable[[Path, str, dict[str, object]], None]] = {
  "tracked": save_section,
  "local": save_local_section,
}



# ----------------------------------------------------------------------------------------
class ConfirmKey:
  """
  Field names of the JSON confirmation and error documents the verbs print.

  Attributes:
    STATUS: The outcome word of a successful write.
    SECTION: The section the write landed in.
    KEY: The nested key path a keyed write touched.
    ERROR: The failure text of a rejected call.
  """

  STATUS = "status"
  SECTION = "section"
  KEY = "key"
  ERROR = "error"



# ----------------------------------------------------------------------------------------
class Outcome:
  """
  Outcome tokens under the status field of a confirmation document, which callers branch on.

  Attributes:
    WRITTEN: The section or nested value was stored.
    DELETED: The nested key was removed, or was already absent.
  """

  WRITTEN = "written"
  DELETED = "deleted"



# ----------------------------------------------------------------------------------------
def _resolve_settings_path(cwd: Path | str | None, *, home: bool = False) -> Path:
  """
  Resolve the tracked settings-file path from an optional explicit working directory.

  Args:
    cwd: Explicit repository root, or `None` to fall back to the `LAZY_REPO_ROOT`
      environment variable and then the process working directory.
    home: When true, target the user-scope file under `~/.claude/` and ignore `cwd`.

  Returns:
    Path to `<cwd>/.claude/lazy.settings.json` under the resolved working directory, or
    `~/.claude/lazy.settings.json` when `home` is set.
  """
  # the file sits at its canonical place under the root: --home wins, then the dispatcher's --cwd /
  # LAZY_REPO_ROOT / cwd convention
  return (Path.home() if home else resolve_repo_root(cwd)) / SettingsFile.REL


def _find_nested_value(section: dict[str, object], key: str) -> object:
  """
  Read one nested value out of a section by its slash-separated key path.

  Args:
    section: Section dict to read from.
    key: Slash-separated key path such as `a/b/c`; segments may themselves contain dots.

  Returns:
    The value at the path, or `None` when any segment is absent or a non-dict is hit early.
  """
  node: object = section

  # descend one segment at a time; a missing or non-dict step means the path is absent
  for part in key.split("/"):
    # guard: cannot descend into a scalar / list — the path is absent
    if not isinstance(node, dict) or part not in node:
      return None

    # step into the segment
    node = node[part]

  # the value at the end of the path
  return node


def _resolve_parent(section: dict[str, object], key: str, *, create: bool) -> tuple[dict[str, object] | None, str]:
  """
  Walk a slash-separated key path down to the dict that holds its last segment.

  Args:
    section: Section dict to walk.
    key: Slash-separated key path such as `a/b/c`; segments may themselves contain dots.
    create: When true, missing intermediate dicts are created along the way; when false a
      missing step yields no parent.

  Returns:
    A `(parent, leaf)` pair — the dict holding the final segment (or `None` when the path
    does not reach that far and `create` is false) and the final segment name.

  Raises:
    ValueError: If an intermediate segment exists but is not a JSON object, so the path
      cannot be created through it.
  """
  *parents, leaf = key.split("/")
  node = section

  # descend through every intermediate segment, creating dicts on demand when asked to
  for part in parents:
    # a missing step is created on demand, or ends the walk with no parent
    if part not in node:
      # guard: without create, a missing step means the path is absent
      if not create:
        return None, leaf
      node[part] = {}

    # guard: an existing non-object step cannot be descended into
    if not isinstance(step := node[part], dict):
      # waiver: naming the offending path segment in a CLI error message
      raise ValueError(f"key path {key!r}: segment {part!r} is not a JSON object")

    # step into the segment
    node = step

  # the dict that holds the leaf, and the leaf's name
  return node, leaf


def settings_get(section: str, *,
                 cwd: Path | str | None = None,
                 home: bool = False,
                 scope: str = "tracked") -> dict[str, object]:
  """
  Load one section of the consumer's `lazy.settings.json` from the requested layer.

  A section absent from the file, or a missing file, yields the layer's empty shape: a
  version-stamped empty stub for the tracked and merged layers, an empty dict for the local one.

  Guarantees:
    - With the default `tracked` scope the returned value is read from the tracked
      layer only, without the local overlay, so it is the exact on-disk section a
      subsequent `settings_set` call would round-trip.

  Args:
    section: Name of the top-level section to read.
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.
    home: Read the user-scope `~/.claude/lazy.settings.json` instead of the repo file.
    scope: Layer to read — `tracked` (default), `local` (overlay only), or `merged`.

  Returns:
    The section dict from the requested layer, or the layer's empty shape when absent.

  Raises:
    KeyError: If `scope` is not one of `tracked`, `local`, `merged`.
    json.JSONDecodeError: If the settings file read is not valid JSON.
  """

  # Contract:
  # With the default tracked scope the returned value is read from the tracked layer only,
  # without the local overlay, so it is the exact on-disk section a subsequent
  # settings_set call would round-trip.

  # Domain(plugin.boundaries):
  # # Settings exchange stays on the tracked layer unless the caller names the personal one
  # When one plugin reads or writes a section of the shared settings file on another plugin's
  # behalf, the exchange happens by default on the tracked layer that ships with the
  # repository. The local overlay a single machine keeps for its own personal choices is read
  # or written only when the caller asks for that layer by name, and a merged reading of both
  # layers is offered only for reads. Reading only the tracked value is what lets whatever
  # comes back be written back unchanged as a full round trip, and a default write into the
  # tracked layer keeps the local overlay untouched, so a personal preference recorded on one
  # machine is never silently overridden by a section another plugin wrote.

  # the requested layer's reader answers straight from the resolved file
  return _READERS[scope](_resolve_settings_path(cwd, home = home), section)


def settings_set(section: str,
                 value: object,
                 *,
                 cwd: Path | str | None = None,
                 home: bool = False,
                 scope: str = "tracked",
                 key: str | None = None,
                 delete: bool = False) -> dict[str, object]:
  """
  Persist one section — or one nested value inside it — of the consumer's `lazy.settings.json`.

  A whole-section write replaces the section and rejects anything that is not a JSON object
  before touching disk. A keyed write changes one nested value in place, creating the objects
  on the way to it, or removes it, and leaves the rest of the section as it was.

  Guarantees:
    - Only the named section is written on the chosen layer; every other section there
      is preserved untouched and the other layer's file is never written.

  Args:
    section: Name of the top-level section to store under.
    value: Section content (must be a JSON object) or, with `key`, the nested value to
      store; ignored when `delete` is set.
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.
    home: Write the user-scope `~/.claude/lazy.settings.json` instead of the repo file.
    scope: Layer to write — `tracked` (default) or `local` (the gitignored overlay).
    key: Slash-separated key path inside the section; `None` replaces the whole section.
    delete: With `key`, remove that key instead of setting it.

  Returns:
    A confirmation dict of the shape `{"status": "written", "section": <name>}`, with a
    `key` field added and `status` set to `deleted` for a `delete` call.

  Raises:
    ValueError: If `value` is not a JSON object (dict) for a whole-section write, or a
      `key` path runs through a non-object segment.
    KeyError: If `scope` is not `tracked` or `local`.
    json.JSONDecodeError: If the existing settings file on the target layer is not valid JSON.
    OSError: If the target settings file or its parent directory cannot be written.
  """

  # Contract:
  # Only the named section is written on the chosen layer; every other section there
  # is preserved untouched and the other layer's file is never written.

  # the file and the writer are fixed by the target scope before either branch touches them
  path = _resolve_settings_path(cwd, home = home)
  writer = _WRITERS[scope]

  # whole-section replace: the legacy contract, value must be a JSON object
  if key is None:
    # guard: a section is always a JSON object — reject scalars / arrays before touching disk
    if not isinstance(value, dict):
      # waiver: naming the rejected JSON type in a CLI error message; no class registry exists here
      raise ValueError(f"section value must be a JSON object, got {type(value).__name__}")

    # the whole section is replaced on the chosen layer and the write confirmed
    writer(path, section, value)
    return { ConfirmKey.STATUS: Outcome.WRITTEN, ConfirmKey.SECTION: section }

  # nested read-modify-write on the same layer the write lands on
  current = _READERS[scope](path, section)
  parent, leaf = _resolve_parent(current, key, create = not delete)

  # guard: deleting a key whose path is absent — nothing to remove, nothing to write
  if parent is None:
    return { ConfirmKey.STATUS: Outcome.DELETED, ConfirmKey.SECTION: section, ConfirmKey.KEY: key }

  # apply the one-leaf change in place
  if delete:
    parent.pop(leaf, None)
  else:
    parent[leaf] = value

  # write the section back on the same layer it was read from
  writer(path, section, current)

  # the confirmation names the outcome, the section, and the key
  return {
    ConfirmKey.STATUS: Outcome.DELETED if delete else Outcome.WRITTEN,
    ConfirmKey.SECTION: section,
    ConfirmKey.KEY: key,
  }


def _add_common_args(parser: argparse.ArgumentParser, scopes: tuple[str, ...]) -> None:
  """
  Attach the `section`, `--key`, `--scope`, `--home`, and `--cwd` arguments shared by both verbs.

  Args:
    parser: Parser to extend.
    scopes: Accepted `--scope` values for this verb.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("section")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--key", default = None, help = "Slash-separated path to one nested value inside the section")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--scope", choices = scopes, default = "tracked", help = "Settings layer (default: tracked)")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--home", action = "store_true", help = "Target ~/.claude/lazy.settings.json instead")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")


def cmd_settings_get(argv: list[str]) -> int:
  """
  Run the `settings-get` subcommand: print one section, or one nested value, as JSON to stdout.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--key`,
      `--scope`, `--home`, `--cwd`).

  Returns:
    Process exit code: 0 on success.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    json.JSONDecodeError: If the settings file read is not valid JSON.
  """
  # the verb's command line: the shared section / key / scope / root arguments with every read scope
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core settings-get")
  # waiver: CLI --scope vocabulary, fixed by the settings-get contract
  _add_common_args(parser, ("tracked", "local", "merged"))
  args = parser.parse_args(argv)

  # the section is printed whole, or narrowed to the one nested value --key names
  # waiver: read in both arms of the ternary below; inlining would repeat the settings read
  section = settings_get(args.section, cwd = args.cwd, home = args.home, scope = args.scope)
  print(json.dumps(section if args.key is None else _find_nested_value(section, args.key)))
  return 0


def cmd_settings_set(argv: list[str]) -> int:
  """
  Run the `settings-set` subcommand: persist a whole section from stdin, or one nested value.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--key`,
      `--value`, `--delete`, `--scope`, `--home`, `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 on malformed / non-object input or when the existing
    settings file on the target layer is not valid JSON.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
    OSError: If the target settings file or its parent directory cannot be written.
  """
  # the verb's command line: the shared arguments with the write scopes, plus the keyed-write switches
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core settings-set")
  # waiver: CLI --scope vocabulary, fixed by the settings-set contract
  _add_common_args(parser, ("tracked", "local"))
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--value", default = None, help = "JSON value to store under --key")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--delete", action = "store_true", help = "Remove --key instead of setting it")
  args = parser.parse_args(argv)

  # guard: --value or --delete given without --key
  if args.key is None and (args.value is not None or args.delete):
    # waiver: one-off argparse usage message
    parser.error("--value and --delete require --key")

  # guard: a keyed write needs exactly one of --value / --delete
  if args.key is not None and (args.value is None) == (not args.delete):
    # waiver: one-off argparse usage message
    parser.error("--key needs exactly one of --value or --delete")

  # the value comes from stdin for a whole-section write and from --value for a keyed one
  # waiver: parsed under its own except so a parse error names its source; the write below catches a
  # different exception, so the local cannot be inlined into it
  try:
    value = json.loads((sys.stdin.read() if args.key is None else args.value) or "null")
  except json.JSONDecodeError as error:
    print(json.dumps({ ConfirmKey.ERROR: f"{'stdin' if args.key is None else '--value'} parse: {error}" }))
    return 1

  # the write's confirmation is printed as is; a rejected value, or a settings file on the target
  # layer that is not valid JSON, is reported as an error JSON instead
  try:
    print(json.dumps(settings_set(
      args.section, value,
      cwd = args.cwd, home = args.home, scope = args.scope, key = args.key, delete = args.delete,
    )))
  except ValueError as error:
    print(json.dumps({ ConfirmKey.ERROR: str(error) }))
    return 1

  # the confirmation on stdout is the success signal the caller reads
  return 0
