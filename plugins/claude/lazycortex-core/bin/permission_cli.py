"""
Helper backing the `lazycortex-core permission-allow` and `permission-edit` CLI subcommands.

`permission-allow` registers one Bash allow-pattern in a Claude Code settings
file's `permissions.allow` list; `permission-edit` adds, moves or removes MCP tool
names across its `permissions.allow` and `permissions.ask` lists. Per `lazy-core.hygiene` § Settings split,
per-tool permissions belong in `settings.local.json` (gitignored), never
tracked `settings.json`; this helper does not enforce the file name, just
applies the pattern wherever the caller points it.

`permission-allow` is idempotent: the pattern is appended only when absent; existing patterns
are preserved untouched. The settings file is created (with any missing
parent dirs) when it doesn't yet exist. Its wire shape is plain stdout:
`added` on insertion, `already-present` on a no-op, and `present` / `absent` with `--check`.

`permission-edit` prints its report as one JSON line carrying a `status` word (`written`, `unchanged`,
`dry-run` or `error`) and the names each kind of change touched. It exits 1 when it refuses names that are not
MCP tool names, or when its write leaves an MCP tool in both lists; `--dry-run` writes nothing.

This module exists so each plugin's install skill can register its permissions
in one Bash line — no per-skill duplicated inline Python.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Sequence


# An MCP tool name, the only shape the permission-edit verb writes.
_MCP_NAME = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+")
# The first indented line of a JSON document, whose leading whitespace is the file's indent unit.
_INDENTED_LINE = re.compile(r"\n([ \t]+)\S")
# A `\uXXXX` escape, the mark of a file that spells non-ASCII text as escapes.
_UNICODE_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")
# The indent a settings file the permission edit creates is written with.
_NEW_FILE_INDENT = 2


class _Outcome:
  """
  Stdout wire-shape outcomes returned by `ensure_permission_allow`.
  """

  # The pattern was missing and has been written into the allow list.
  ADDED = "added"
  # The pattern was already in the allow list; nothing was written.
  ALREADY_PRESENT = "already-present"
  # Check mode: the pattern is in the allow list.
  PRESENT = "present"
  # Check mode: the pattern is not in the allow list.
  ABSENT = "absent"


class _SettingsKey:
  """
  Top-level keys this helper reads/writes in the target settings JSON.
  """

  # The top-level permissions block of a Claude Code settings file.
  PERMISSIONS = "permissions"
  # The allow-pattern list inside the permissions block.
  ALLOW = "allow"
  # The ask-pattern list inside the permissions block.
  ASK = "ask"



# ----------------------------------------------------------------------------------------
class _ReportKey:
  """
  Field names of the report a permission edit prints.
  """

  # The edit's outcome word.
  STATUS = "status"
  # Names newly added to the allow list.
  ALLOW_ADDED = "allow_added"
  # Names newly added to the ask list.
  ASK_ADDED = "ask_added"
  # Names moved from the allow list to the ask list.
  MOVED_TO_ASK = "moved_to_ask"
  # Names removed from either list.
  REMOVED = "removed"
  # The settings file the edit concerns.
  PATH = "path"
  # Names the verb refused.
  INVALID = "invalid"
  # A one-line explanation of a refusal.
  MESSAGE = "message"



# ----------------------------------------------------------------------------------------
class _EditStatus:
  """
  Outcome words of a permission edit.
  """

  # The file was rewritten.
  WRITTEN = "written"
  # The call would change nothing; nothing was written.
  UNCHANGED = "unchanged"
  # The call would change the file; nothing was written.
  DRY_RUN = "dry-run"
  # The call was refused before any write, or its write left an MCP tool in both lists.
  ERROR = "error"


class _CliMeta:
  """
  Argparse metadata for the `permission-allow` subcommand.
  """

  # The program name shown in `--help` output.
  PROG = "lazycortex-core permission-allow"
  # The positional argument naming the settings file.
  ARG_PATH = "settings_path"
  # The positional argument naming the allow pattern.
  ARG_PATTERN = "pattern"
  # The help text of the settings-file argument.
  HELP_PATH = "Target settings file (e.g. .claude/settings.local.json)"
  # The help text of the allow-pattern argument.
  HELP_PATTERN = "Bash allow-pattern, e.g. Bash(lazycortex-specs *)"
  # The flag selecting check mode.
  ARG_CHECK = "--check"
  # The help text of the check-mode flag.
  HELP_CHECK = "Only report whether the pattern is present (present / absent); never write"


def ensure_permission_allow(settings_path: Path, pattern: str) -> str:
  """
  Ensure a Bash allow-pattern is present in a settings file's permissions.allow list.

  Registering a pattern is idempotent: calling again with the same pattern changes nothing. The settings
  file and its parent directories are created when missing.

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

  # Decision: own read-append-write, not a call into `apply_permission_edit` — that writer skips a
  # name the ask list already holds, which would break the contract above for a pattern pinned to ask.

  # load the settings file, defaulting to an empty object when it doesn't yet exist
  data: dict = json.loads(settings_path.read_text(encoding = "utf-8")) if settings_path.exists() else {}
  perms = data.setdefault(_SettingsKey.PERMISSIONS, {})
  allow = perms.setdefault(_SettingsKey.ALLOW, [])

  # a pattern already in the allow list leaves the file as it is
  if pattern in allow:
    return _Outcome.ALREADY_PRESENT

  # the pattern joins the end of the allow list and the file is rewritten
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
  # the settings path and the pattern are positional; `--check` turns the call into a probe
  parser = argparse.ArgumentParser(prog=_CliMeta.PROG)
  parser.add_argument(_CliMeta.ARG_PATH, help=_CliMeta.HELP_PATH)
  parser.add_argument(_CliMeta.ARG_PATTERN, help=_CliMeta.HELP_PATTERN)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument(_CliMeta.ARG_CHECK, action="store_true", help=_CliMeta.HELP_CHECK)
  args = parser.parse_args(argv)

  # the parsed path and pattern every mode works on
  settings_path = Path(getattr(args, _CliMeta.ARG_PATH))
  pattern = getattr(args, _CliMeta.ARG_PATTERN)

  # the probe answers without writing and leaves the file untouched
  if args.check:
    print(_Outcome.PRESENT if has_permission_allow(settings_path, pattern) else _Outcome.ABSENT)
    return 0
  print(ensure_permission_allow(settings_path, pattern))
  return 0


def _render_like(data: dict, original: str | None) -> str:
  """
  Render a settings object in the layout of the text it was read from.

  Args:
    data: Settings object to render.
    original: Text of the file as it was read, or `None` for a file that does not exist yet.

  Returns:
    The JSON text, with the original's indent unit, its spelling of non-ASCII text and its trailing newline;
    a new file gets a two-space indent and a trailing newline.
  """
  # a file the edit creates has no layout of its own to keep, so it takes the default one
  if original is None:
    return json.dumps(data, indent = _NEW_FILE_INDENT) + "\n"

  # the indent unit is the leading whitespace of the first indented line; a one-line file stays on one line,
  # compact when it carries no space after its separators
  indent_match = _INDENTED_LINE.search(original)
  indent = indent_match.group(1) if indent_match else None
  compact = indent is None and ": " not in original and ", " not in original
  separators = ( ",", ":" ) if compact else None

  # non-ASCII text stays as the file spells it: escaped only when the file escapes it and holds none raw
  escaped = bool(_UNICODE_ESCAPE.search(original)) and original.isascii()
  newline = "\n" if original.endswith("\n") else ""
  return json.dumps(data, indent = indent, ensure_ascii = escaped, separators = separators) + newline


def _edit_lists(allow: list[str], ask: list[str], *, add_allow: list[str], add_ask: list[str], remove: list[str],
                move_to_ask: list[str]) -> dict[str, list[str]]:
  """
  Apply an edit to the allow and ask lists in place.

  Args:
    allow: Allow list, edited in place.
    ask: Ask list, edited in place.
    add_allow: Names to add to the allow list.
    add_ask: Names to add to the ask list.
    remove: Names to remove from both lists.
    move_to_ask: Names to move from the allow list to the ask list.

  Returns:
    The names each kind of change touched, keyed by report field.
  """
  report: dict[str, list[str]] = {
    _ReportKey.ALLOW_ADDED: [], _ReportKey.ASK_ADDED: [], _ReportKey.MOVED_TO_ASK: [], _ReportKey.REMOVED: [],
  }

  # a name moved to ask leaves allow first, so no later step can keep it in both lists
  for name in move_to_ask:
    if name in allow:
      allow.remove(name)
      if name not in ask:
        ask.append(name)
      report[_ReportKey.MOVED_TO_ASK].append(name)

  # a new name lands in its list only when neither list holds it yet
  for names, target, key in ( ( add_allow, allow, _ReportKey.ALLOW_ADDED ), ( add_ask, ask, _ReportKey.ASK_ADDED ) ):
    for name in names:
      if name not in allow and name not in ask:
        target.append(name)
        report[key].append(name)

  # a removed name leaves both lists
  for name in remove:
    if name in allow or name in ask:
      allow[:] = [ entry for entry in allow if entry != name ]
      ask[:] = [ entry for entry in ask if entry != name ]
      report[_ReportKey.REMOVED].append(name)
  return report


def apply_permission_edit(path: Path, *, allow: Sequence[str] = (), ask: Sequence[str] = (),
                          remove: Sequence[str] = (), move_to_ask: Sequence[str] = (),
                          dry_run: bool = False) -> dict:
  """
  Edit the allow and ask lists of a settings file's permissions block.

  Guarantees:
    - A name already in a list is never duplicated, and entries the edit does not name keep their order.
    - A name the edit adds or moves never ends up in both lists.
    - An `mcp__<server>__<tool>` name left in both lists after a write fails the edit with the error status.
    - Entries that are not `mcp__<server>__<tool>` names never fail the edit and are never touched.
    - A call that changes nothing, or a dry run, writes nothing.
    - A rewritten existing file keeps its own layout: indent unit (a one-line file stays on one line, compact if it
      was), key order, spelling of non-ASCII text (raw unless the file only uses unicode escapes) and trailing
      newline. A file the edit creates gets a two-space indent and a trailing newline.

  Args:
    path: Settings file to edit; a missing one is created by a real change.
    allow: Names to add to the allow list.
    ask: Names to add to the ask list.
    remove: Names to remove from both lists.
    move_to_ask: Names to move from the allow list to the ask list.
    dry_run: Report what would change without writing.

  Returns:
    Report with the status word, the names each kind of change touched and the settings file path.

  Raises:
    json.JSONDecodeError: If the settings file exists but is not valid JSON.
    OSError: If the file or its parent directory cannot be written.
  """

  # Contract:
  # A name already in a list is never duplicated by an edit,
  # and entries the edit does not name keep their order.

  # Contract:
  # A name the edit adds or moves never ends up in both lists.

  # Contract:
  # An MCP tool name of the form `mcp__<server>__<tool>` left in both lists after a write fails the edit
  # with the error status; the write is not hidden and both entries stay.

  # Contract:
  # Entries that are not of the form `mcp__<server>__<tool>` never make the edit an error
  # and are never touched, even when held by both lists.

  # Contract:
  # A call that changes nothing, and a dry run, write nothing.

  # Contract:
  # An edit that rewrites an existing settings file keeps that file's own layout: its indent unit (spaces or tabs;
  # a one-line file stays on one line, compact when it had no spaces after separators), the order of its keys,
  # its spelling of non-ASCII text (raw, unless the file only uses unicode escapes) and whether it ends with
  # a newline. A file the edit creates is written with a two-space indent and a trailing newline.

  # the file is read as it stands; a missing one starts empty and is only created by a real change
  original = path.read_text(encoding = "utf-8") if path.exists() else None
  data: dict = json.loads(original) if original is not None else {}
  perms = data.get(_SettingsKey.PERMISSIONS)
  perms = perms if isinstance(perms, dict) else {}
  new_allow = list(perms.get(_SettingsKey.ALLOW) or [])
  new_ask = list(perms.get(_SettingsKey.ASK) or [])

  # the edit runs on copies of both lists, and its report says what it would change
  report = _edit_lists(new_allow, new_ask, add_allow = list(allow), add_ask = list(ask), remove = list(remove),
                       move_to_ask = list(move_to_ask))
  changed = any(report.values())
  result = { _ReportKey.STATUS: _EditStatus.UNCHANGED, **report, _ReportKey.PATH: str(path) }

  # a call that changes nothing, or only asks what it would change, writes nothing
  if not changed or dry_run:
    result[_ReportKey.STATUS] = _EditStatus.DRY_RUN if changed else _EditStatus.UNCHANGED
    return result

  # a list key already present stays even when emptied; an absent one appears only to hold a name
  for key, values in ( ( _SettingsKey.ALLOW, new_allow ), ( _SettingsKey.ASK, new_ask ) ):
    if key in perms or values:
      perms[key] = values
  data[_SettingsKey.PERMISSIONS] = perms
  runtime_state.atomic_write_text(path, _render_like(data, original))

  # the file is read back, and an MCP tool left in both lists fails the edit; the operator's
  # other entries are not this writer's to judge
  written = json.loads(path.read_text(encoding = "utf-8")).get(_SettingsKey.PERMISSIONS, {})
  overlap = set(written.get(_SettingsKey.ALLOW) or []) & set(written.get(_SettingsKey.ASK) or [])
  if any(_MCP_NAME.fullmatch(name) for name in overlap):
    result[_ReportKey.STATUS] = _EditStatus.ERROR
    return result
  result[_ReportKey.STATUS] = _EditStatus.WRITTEN
  return result


def cmd_permission_edit(argv: list[str]) -> int:
  """
  Run the `permission-edit` subcommand: add, move or remove MCP tool names in a settings file's permissions.

  Prints the edit's report as JSON. Names that are not MCP tool names are refused before anything is written.

  Args:
    argv: Argument vector after the subcommand name (settings path, repeatable `--allow`, `--ask`, `--remove`,
      `--move-to-ask`, and `--dry-run`).

  Returns:
    Process exit code: `0` on success, `1` when the edit is refused or fails.
  """
  # every list flag repeats; dry-run reports without writing
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core permission-edit")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("settings_path")
  for flag in ( "--allow", "--ask", "--remove", "--move-to-ask" ):
    # waiver: argparse CLI signature, not a domain key
    parser.add_argument(flag, action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  args = parser.parse_args(argv)

  # guard: only MCP tool names are this verb's to edit; anything else is refused before any write
  if invalid := [
    name for name in [ *args.allow, *args.ask, *args.remove, *args.move_to_ask ] if not _MCP_NAME.fullmatch(name)
  ]:
    print(json.dumps({
      _ReportKey.STATUS: _EditStatus.ERROR, _ReportKey.INVALID: invalid, _ReportKey.PATH: args.settings_path,
      _ReportKey.MESSAGE: "permission-edit edits mcp__<server>__<tool> names only",
    }))
    return 1

  # the edit's report is the verb's whole output; a broken invariant is a failed edit
  result = apply_permission_edit(
    Path(args.settings_path), allow = args.allow, ask = args.ask, remove = args.remove,
    move_to_ask = args.move_to_ask, dry_run = args.dry_run,
  )
  print(json.dumps(result))
  return 1 if result[_ReportKey.STATUS] == _EditStatus.ERROR else 0
