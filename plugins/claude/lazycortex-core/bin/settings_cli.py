"""
Generic settings-section read/write surface for the `lazycortex-core` CLI.

This module backs the `settings-get` / `settings-set` subcommands — the blessed
cross-plugin contract that lets a sibling plugin
read and write a top-level section of the consumer's `lazy.settings.json` without
importing any `lazycortex-core` Python. The wire shape is JSON in via stdin, JSON
out via stdout. It also backs `mcp-config-drop`, which removes one server from an MCP
config file.

Reads default to `lazy_settings.load_tracked_section` (tracked layer only, no local
overlay — the correct layer for a read-modify-write round-trip); `--scope local` reads
the overlay alone and `--scope merged` the effective view. Writes go through
`lazy_settings.save_section` (atomic, never touches the local overlay; a section is stamped only with
the version the file's own section stands on, or the current one when the file does not carry it)
or, with `--scope local`, `lazy_settings.save_local_section`. A slash-separated `--key` narrows
either verb to one nested value inside the section. `--verbatim` makes `settings-get` print the
tracked section exactly as stored (`null` when the file does not carry it, no stub, no overlay) and
`settings-set` write the whole tracked section without any version stamp; it takes neither `--key`
nor another `--scope`.
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
  load_local_only_section, load_section, load_tracked_section, load_verbatim_tracked_section, save_local_section,
  save_section,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from runtime_state import atomic_write_text  # pylint: disable=import-error

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
# The settings layer a verbatim read or write is confined to.
_TRACKED = "tracked"
# The MCP config file's map of server names to their launch specs.
_MCP_SERVERS = "mcpServers"



# ----------------------------------------------------------------------------------------
class ConfirmKey:
  """
  Field names of the JSON confirmation and error documents the verbs print.

  Attributes:
    STATUS: The outcome word of a successful write.
    SECTION: The section the write landed in.
    KEY: The nested key path a keyed write touched.
    ERROR: The failure text of a rejected call.
    PATH: The file an MCP-config verb acted on.
    MESSAGE: The failure sentence of a refused MCP-config call.
  """

  # The outcome word of a successful write.
  STATUS = "status"
  # The section the write landed in.
  SECTION = "section"
  # The nested key path a keyed write touched.
  KEY = "key"
  # The failure text of a rejected call.
  ERROR = "error"
  # The file an MCP-config verb acted on.
  PATH = "path"
  # The failure sentence of a refused MCP-config call.
  MESSAGE = "message"



# ----------------------------------------------------------------------------------------
class Outcome:
  """
  Outcome tokens under the status field of a confirmation document, which callers branch on.

  Attributes:
    WRITTEN: The section or nested value was stored.
    DELETED: The nested key was removed, or was already absent.
    DROPPED: The MCP server was removed from the config file.
    ABSENT: The config file names no such MCP server; nothing was written.
    FAILED: The config file could not be read as a JSON object.
  """

  # The section or nested value was stored.
  WRITTEN = "written"
  # The nested key was removed, or was already absent.
  DELETED = "deleted"
  # The MCP server was removed from the config file.
  DROPPED = "dropped"
  # The config file names no such MCP server; nothing was written.
  ABSENT = "absent"
  # The config file could not be read as a JSON object.
  FAILED = "error"



# ----------------------------------------------------------------------------------------
def resolve_settings_path(cwd: Path | str | None, *, home: bool = False) -> Path:
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


def load_settings_section(section: str, *,
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
  return _READERS[scope](resolve_settings_path(cwd, home = home), section)


def load_verbatim_section(section: str, *, cwd: Path | str | None = None, home: bool = False) -> dict | None:
  """
  Load one tracked section of the consumer's `lazy.settings.json` exactly as it is stored.

  Unlike `load_settings_section`, an absent section is reported as absent rather than as a
  version-stamped stub, and the local overlay is not applied.

  Args:
    section: Name of the top-level section to read.
    cwd: Repository root override; resolves the settings file under `<cwd>/.claude/`.
    home: Read the user-scope `~/.claude/lazy.settings.json` instead of the repo file.

  Returns:
    The section dict as stored, or `None` when the file is missing or does not carry the section.

  Raises:
    json.JSONDecodeError: If the settings file is not valid JSON.
  """
  # the tracked file answers as stored: no stub, no overlay
  return load_verbatim_tracked_section(resolve_settings_path(cwd, home = home), section)


def settings_set(section: str,
                 value: object,
                 *,
                 cwd: Path | str | None = None,
                 home: bool = False,
                 scope: str = "tracked",
                 key: str | None = None,
                 delete: bool = False,
                 verbatim: bool = False) -> dict[str, object]:
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
    verbatim: Write the whole tracked section without a version stamp.

  Returns:
    A confirmation dict of the shape `{"status": "written", "section": <name>}`, with a
    `key` field added and `status` set to `deleted` for a `delete` call.

  Raises:
    ValueError: If `value` is not a JSON object (dict) for a whole-section write, a
      `key` path runs through a non-object segment, or `verbatim` is combined with `key` or
      a scope other than `tracked`.
    KeyError: If `scope` is not `tracked` or `local`.
    json.JSONDecodeError: If the existing settings file on the target layer is not valid JSON.
    OSError: If the target settings file or its parent directory cannot be written.
  """

  # Contract:
  # Only the named section is written on the chosen layer; every other section there
  # is preserved untouched and the other layer's file is never written.

  # the file and the writer are fixed by the target scope before either branch touches them
  path = resolve_settings_path(cwd, home = home)
  writer = _WRITERS[scope]

  # guard: a verbatim write replaces a whole tracked section; a keyed or local one has no verbatim form
  if verbatim and (key is not None or scope != _TRACKED):
    raise ValueError("verbatim writes a whole tracked section; it takes neither a key nor another scope")

  # whole-section replace: the legacy contract, value must be a JSON object
  if key is None:
    # guard: a section is always a JSON object — reject scalars / arrays before touching disk
    if not isinstance(value, dict):
      # waiver: naming the rejected JSON type in a CLI error message; no class registry exists here
      raise ValueError(f"section value must be a JSON object, got {type(value).__name__}")

    # the whole section is replaced on the chosen layer and the write confirmed; a verbatim one is never stamped
    if verbatim:
      save_section(path, section, value, stamp = False)
    else:
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


def _add_verbatim_arg(parser: argparse.ArgumentParser) -> None:
  """
  Attach the `--verbatim` switch shared by both verbs.

  Args:
    parser: Parser to extend.
  """
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--verbatim", action = "store_true",
                      help = "Whole tracked section as stored: no version stub on read, no version stamp on write")


def cmd_settings_get(argv: list[str]) -> int:
  """
  Run the `settings-get` subcommand: print one section, or one nested value, as JSON to stdout.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--key`,
      `--scope`, `--verbatim`, `--home`, `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 when a `--verbatim` read meets a settings file that is not
    valid JSON (an `error` JSON is printed).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser; this
      includes `--verbatim` combined with `--key` or a scope other than `tracked`.
    json.JSONDecodeError: If the settings file read is not valid JSON on a non-verbatim read.
  """
  # the verb's command line: the shared section / key / scope / root arguments with every read scope
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core settings-get")
  # waiver: CLI --scope vocabulary, fixed by the settings-get contract
  _add_common_args(parser, ("tracked", "local", "merged"))
  _add_verbatim_arg(parser)
  args = parser.parse_args(argv)

  # a verbatim read prints the tracked section as stored, or null when the file does not carry it
  if args.verbatim:
    # guard: a verbatim read is one whole tracked section
    if args.key is not None or args.scope != _TRACKED:
      # waiver: one-off argparse usage message
      parser.error("--verbatim reads a whole tracked section; it takes neither --key nor another --scope")
    try:
      print(json.dumps(load_verbatim_section(args.section, cwd = args.cwd, home = args.home)))
    except json.JSONDecodeError as error:
      print(json.dumps({ ConfirmKey.ERROR: f"{resolve_settings_path(args.cwd, home = args.home)}: {error}" }))
      return 1
    return 0

  # the section is printed whole, or narrowed to the one nested value --key names
  # waiver: read in both arms of the ternary below; inlining would repeat the settings read
  section = load_settings_section(args.section, cwd = args.cwd, home = args.home, scope = args.scope)
  print(json.dumps(section if args.key is None else _find_nested_value(section, args.key)))
  return 0


def cmd_settings_set(argv: list[str]) -> int:
  """
  Run the `settings-set` subcommand: persist a whole section from stdin, or one nested value.

  Args:
    argv: Argument vector after the subcommand name (section plus optional `--key`,
      `--value`, `--delete`, `--scope`, `--verbatim`, `--home`, `--cwd`).

  Returns:
    Process exit code: 0 on success, 1 on malformed / non-object input or when the existing
    settings file on the target layer is not valid JSON.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser; this
      includes `--verbatim` combined with `--key` or a scope other than `tracked`.
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
  _add_verbatim_arg(parser)
  args = parser.parse_args(argv)

  # guard: a verbatim write is one whole tracked section
  if args.verbatim and (args.key is not None or args.scope != _TRACKED):
    # waiver: one-off argparse usage message
    parser.error("--verbatim writes a whole tracked section; it takes neither --key nor another --scope")

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
      verbatim = args.verbatim,
    )))
  except ValueError as error:
    print(json.dumps({ ConfirmKey.ERROR: str(error) }))
    return 1

  # the confirmation on stdout is the success signal the caller reads
  return 0


def delete_mcp_server(path: Path, server: str) -> str:
  """
  Remove one server from an MCP config file.

  Guarantees:
    - A server the file does not name leaves the file byte for byte as it is.
    - Only the named server is removed; every other key keeps its place.

  Args:
    path: MCP config file.
    server: Name of the server to remove.

  Returns:
    `Outcome.DROPPED` when the server was removed, `Outcome.ABSENT` when the file does not name it.

  Raises:
    ValueError: If the file is missing, not valid JSON, or not a JSON object.
  """

  # Contract:
  # A server the file does not name leaves the file byte for byte as it is.

  # Contract:
  # Only the named server is removed; every other key keeps its place.

  # a config file that is missing or does not parse is refused, never recreated
  try:
    data = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    raise ValueError(f"{path}: {error}") from error

  # guard: a config that parses but is not an object is refused, never recreated
  if not isinstance(data, dict):
    raise ValueError(f"{path}: not a JSON object")

  # a server the file does not name leaves the file byte for byte as it is
  servers = data.get(_MCP_SERVERS)
  if not isinstance(servers, dict) or server not in servers:
    return Outcome.ABSENT

  # only the one server leaves; every other key keeps its place
  del servers[server]
  atomic_write_text(path, json.dumps(data, indent = 2) + "\n")
  return Outcome.DROPPED


def cmd_mcp_config_drop(argv: list[str]) -> int:
  """
  Run the `mcp-config-drop` subcommand: remove one server from an MCP config file and print the outcome as JSON.

  Args:
    argv: Argument vector after the subcommand name (config file, then server name).

  Returns:
    Process exit code: `0` on success, `1` when the file cannot be read as a JSON object.
  """
  # the verb names one config file and one server in it
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core mcp-config-drop")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("server")
  args = parser.parse_args(argv)

  # a refusal is one JSON line naming the file, never a traceback
  try:
    status = delete_mcp_server(Path(args.file), args.server)
  except ValueError as error:
    print(json.dumps({
      ConfirmKey.STATUS: Outcome.FAILED, ConfirmKey.PATH: args.file, ConfirmKey.MESSAGE: str(error),
    }))
    return 1

  # the outcome word and the file it concerns
  print(json.dumps({ ConfirmKey.STATUS: status, ConfirmKey.PATH: args.file }))
  return 0
