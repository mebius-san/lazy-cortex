#!/usr/bin/env python3

"""
scaffold_registry — dependency-free owner of the lazy-core.scaffold `## Registry` block.

Parses / renders / surgical splices the rigid 3-level YAML mapping
(plugin -> template-path -> [globs]) without a YAML library, and exposes
upsert / remove / list / validate / sync-rule / sync-plugin / set-entry / drop-entry
as the `lazycortex-core scaffold` subcommand.
"""

from __future__ import annotations

from typing import NamedTuple

import argparse
import json
import os
import sys
from enum import StrEnum
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import file_sync  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_git_toplevel  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


REGISTRY_HEADING = "## Registry"
LOCAL_KEY = "_local"
# The consumer-side record of which plugins are installed; relative to the operator's home.
_INSTALLED_PLUGINS = "~/.claude/plugins/installed_plugins.json"
# A plugin's per-group scaffold manifest, one directory below its templates tree.
MANIFEST_NAME = "scaffold.entries.json"
# The plugin-root directory that holds the template groups.
_TEMPLATES_DIR = "templates"
# The scaffold rule file, relative to the scope root (the repo root or the operator's home).
_REGISTRY_REL = os.path.join(".claude", "rules", "lazy-core.scaffold.md")
# The consumer's template groups, relative to the scope root.
_CONSUMER_TEMPLATES_REL = os.path.join(".claude", "templates")
# The two install scopes a registry can live in.
_SCOPE_PROJECT = "project"
_SCOPE_USER = "user"
# A registry key naming a path under the operator's home.
_HOME_PREFIX = "~/"
# Exit code of a sync whose template write did not verify, the copy primitive's own.
_EXIT_SYNC_FAILED = 3
_FENCE_OPEN = "```yaml"
_FENCE_CLOSE = "```"
# YAML-reserved leading characters: a plain scalar starting with one of these must be quoted.
_RESERVED_LEAD = set("*&!|>%@`[]{},?\"'#:")
# Minimal scaffold rule template used when creating a registry file from scratch.
MINIMAL_REGISTRY = (
  "---\n"
  "description: Scaffold registry — authoring templates a plugin registers.\n"
  "always_loaded: fires at create-time; path-scoped contracts don't trigger on Write\n"
  "---\n"
  "# Scaffold\n\n"
  "Before composing any **new** file whose path matches a glob below, `Read` the matching "
  "template first. Contract: `plugins/claude/lazycortex-core/references/lazy-core.scaffold-registry-contract.md`.\n\n"
  "When several globs match the same path, the most specific wins — within a key and across "
  "keys. Specificity is a total order of three steps: (1) the number of path segments that "
  "carry no wildcard character; (2) on a tie, the number of literal characters outside the "
  "wildcards; (3) on a tie, the `_local` key over a plugin key.\n\n"
  "## Registry\n\n```yaml\n{}\n```\n"
)



# ----------------------------------------------------------------------------------------
class _FindingFieldId(StrEnum):
  """
  Keys of one finding that `validate` returns.

  Attributes:
    CODE: The finding's closed-set code.
    SEVERITY: The finding's severity level.
    MSG: The one-line human-readable description of the finding.
  """

  # The finding's closed-set code.
  CODE     = "code"
  # The finding's severity level.
  SEVERITY = "severity"
  # The one-line human-readable description of the finding.
  MSG      = "msg"



# ----------------------------------------------------------------------------------------
class _FindingKind(StrEnum):
  """
  Closed-set codes of the findings that `validate` returns.

  Attributes:
    PARSE_ERROR: The Registry block does not parse.
    ORPHAN_KEY: A registry key names a plugin that is not installed.
    BAD_SHAPE: A key's value or a template's glob list has the wrong shape.
    PLUGIN_ROOT_VAR: A template path spells the plugin-root variable instead of a plain path.
    MISSING_TEMPLATE: A template path names no readable file.
    GLOB_OVERLAP: Two keys claim the very same glob.
  """

  # The Registry block does not parse.
  PARSE_ERROR      = "parse_error"
  # A registry key names a plugin that is not installed.
  ORPHAN_KEY       = "orphan_key"
  # A key's value or a template's glob list has the wrong shape.
  BAD_SHAPE        = "bad_shape"
  # A template path spells the plugin-root variable instead of a plain path.
  PLUGIN_ROOT_VAR  = "plugin_root_var"
  # A template path names no readable file.
  MISSING_TEMPLATE = "missing_template"
  # Two keys claim the very same glob.
  GLOB_OVERLAP     = "glob_overlap"



# ----------------------------------------------------------------------------------------
class _FindingLevel(StrEnum):
  """
  Severity levels of the findings that `validate` returns.

  Attributes:
    FAIL: A structural defect that refuses the registry.
    WARN: A defect surfaced for a human to judge.
  """

  # A structural defect that refuses the registry.
  FAIL = "FAIL"
  # A defect surfaced for a human to judge.
  WARN = "WARN"



# ----------------------------------------------------------------------------------------
class _FieldId(StrEnum):
  """
  Field names of the JSON reports that the scaffold verbs print.

  Attributes:
    STATUS: The run's outcome word.
    REGISTRY: The registry file the run read or wrote.
    GROUPS: The template groups a plugin ships.
    TEMPLATES: One receipt line per template copied.
    COUNTS: Receipt lines counted per copy state.
    FAILED: Templates whose write did not verify.
    MESSAGE: A one-line explanation of a refusal.
    PLUGIN: The registry key a verb acted on.
    TEMPLATE: The template path a verb acted on.
    FINDINGS: The `validate` findings behind a refusal.
    GROUP: A receipt line's template group.
    FILE: A receipt line's file name.
    STATE: A receipt line's copy state.
  """

  # The run's outcome word.
  STATUS    = "status"
  # The registry file the run read or wrote.
  REGISTRY  = "registry"
  # The template groups a plugin ships.
  GROUPS    = "groups"
  # One receipt line per template copied.
  TEMPLATES = "templates"
  # Receipt lines counted per copy state.
  COUNTS    = "counts"
  # Templates whose write did not verify.
  FAILED    = "failed"
  # A one-line explanation of a refusal.
  MESSAGE   = "message"
  # The registry key a verb acted on.
  PLUGIN    = "plugin"
  # The template path a verb acted on.
  TEMPLATE  = "template"
  # The `validate` findings behind a refusal.
  FINDINGS  = "findings"
  # A receipt line's template group.
  GROUP     = "group"
  # A receipt line's file name.
  FILE      = "file"
  # A receipt line's copy state.
  STATE     = "state"



# ----------------------------------------------------------------------------------------
class _RunState(StrEnum):
  """
  Outcome words that the scaffold verbs report as a run's status.

  Attributes:
    CREATED: The registry file did not exist and was created with the key.
    REGISTERED: The key was written into an existing registry.
    UNCHANGED: The registry already held exactly this content.
    ERROR: The registry does not parse and was not written.
    NONE: The plugin ships no scaffold manifest.
    COLLISION: Two manifests declare one template path with different globs.
    REMOVED_ENTRY: One template was dropped and the key still lists others.
    REMOVED_PLUGIN: The last template was dropped, so the key left the block.
    NOT_FOUND: The key does not list the template.
  """

  # The registry file did not exist and was created with the key.
  CREATED        = "created-and-registered"
  # The key was written into an existing registry.
  REGISTERED     = "registered"
  # The registry already held exactly this content.
  UNCHANGED      = "unchanged"
  # The registry does not parse and was not written.
  ERROR          = "error"
  # The plugin ships no scaffold manifest.
  NONE           = "none"
  # Two manifests declare one template path with different globs.
  COLLISION      = "collision"
  # One template was dropped and the key still lists others.
  REMOVED_ENTRY  = "removed-entry"
  # The last template was dropped, so the key left the block.
  REMOVED_PLUGIN = "removed-plugin"
  # The key does not list the template.
  NOT_FOUND      = "not-found"



# ----------------------------------------------------------------------------------------
class _SubcommandKind(StrEnum):
  """
  Subcommands of the scaffold CLI that act on a plugin's manifests or on one registry entry.

  Attributes:
    SYNC_PLUGIN: Copy a plugin's templates and register its manifest entries.
    SET_ENTRY: Write one template's globs under one registry key.
    DROP_ENTRY: Drop one template from one registry key.
  """

  # Copy a plugin's templates and register its manifest entries.
  SYNC_PLUGIN = "sync-plugin"
  # Write one template's globs under one registry key.
  SET_ENTRY   = "set-entry"
  # Drop one template from one registry key.
  DROP_ENTRY  = "drop-entry"



# ----------------------------------------------------------------------------------------
class ManifestCollisionError(ValueError):
  """
  Error raised when two scaffold manifests declare one template path with different globs.

  Attributes:
    key: The contested template path.
    group_a: The group that declared the template path first.
    group_b: The group whose declaration conflicts with the first.
  """

  def __init__(self, key: str, group_a: str, group_b: str) -> None:
    """
    Build the collision error naming the contested template path and both groups.

    Args:
      key: The contested template path.
      group_a: The group that declared the template path first.
      group_b: The group whose declaration conflicts with the first.
    """
    super().__init__(
      f'scaffold-sync: collision — template path "{key}" declared by both group "{group_a}" '
      f'and group "{group_b}" with conflicting globs; resolve before continuing'
    )

    # the parties of the collision, for a caller that reports them on its own terms
    self.key = key
    self.group_a = group_a
    self.group_b = group_b



# ----------------------------------------------------------------------------------------
class MergedManifests(NamedTuple):
  """
  Union of the scaffold manifests that one plugin ships.

  Attributes:
    groups: The template groups that ship a manifest, in alphabetical order.
    entries: The merged map of template paths to glob lists, with template paths kept verbatim.
  """

  # Decision: a NamedTuple, not a frozen dataclass — the module is loaded by file path without a
  # `sys.modules` entry in places, and the dataclass decorator needs that entry to resolve the class.

  # Groups that ship a manifest, alphabetical.
  groups: list[str]
  # Union of every group's template map, keys verbatim.
  entries: dict[str, list[str]]


def _locate_block(md: str) -> tuple[list[str], int, int]:
  """
  Return the line list, open-fence index, and close-fence index for the Registry block.

  Locate the single `## Registry` heading, then find the ```yaml fence that follows
  it and its matching closing fence.

  Args:
    md: Full markdown source to search.

  Returns:
    A tuple of (lines, open_idx, close_idx).

  Raises:
    ValueError: If the heading is missing or appears more than once, if no ```yaml
      fence is found under the heading, or if the fence is unterminated.
  """
  lines = md.splitlines()
  headings = [ idx for idx, line in enumerate(lines) if line.strip() == REGISTRY_HEADING ]

  # guard: exactly one Registry heading required
  if len(headings) != 1:
    raise ValueError(
      f"expected exactly one '{REGISTRY_HEADING}' heading, found {len(headings)}"
    )
  head_idx = headings[0]
  open_idx = None
  for pos in range(head_idx + 1, len(lines)):
    if lines[pos].strip() == _FENCE_OPEN:
      open_idx = pos
      break
    if lines[pos].strip() and not lines[pos].startswith("#"):
      break

  # guard: a ```yaml fence must follow the heading
  if open_idx is None:
    raise ValueError("no ```yaml fence found under ## Registry")
  close_idx = None
  for pos in range(open_idx + 1, len(lines)):
    if lines[pos].strip() == _FENCE_CLOSE:
      close_idx = pos
      break

  # guard: the fence must be closed
  if close_idx is None:
    raise ValueError("unterminated ```yaml fence under ## Registry")
  return lines, open_idx, close_idx


def _unquote(val: str) -> str:
  """
  Strip a single layer of surrounding double- or single-quotes from a YAML scalar.

  Args:
    val: Raw scalar string, possibly quoted.

  Returns:
    The unquoted value, or the trimmed input unchanged if it is not quoted.
  """
  val = val.strip()
  if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
    return val[1:-1]
  return val


def parse_registry_block(md: str) -> dict:
  """
  Parse the `## Registry` ```yaml block into {plugin: {path: [globs]}}.

  The shape is rigid: top-level keys at column 0 (`key:`), template paths at
  2-space indent (`path:`), globs at 4-space indent (`- glob`). `{}` means empty.
  Anything outside this shape raises ValueError.

  Args:
    md: Full markdown source containing exactly one `## Registry` ```yaml block.

  Returns:
    Nested dict mapping plugin key → template path → list of glob strings.

  Raises:
    ValueError: If the heading, fence, or block structure is invalid, or if a
      duplicate top-level key is encountered.
  """
  lines, open_idx, close_idx = _locate_block(md)
  body = lines[open_idx + 1 : close_idx]
  nonblank = [ line for line in body if line.strip() ]
  if nonblank == ["{}"]:
    return {}
  data: dict = {}
  cur_plugin: str | None = None
  cur_path: str | None = None
  for raw in body:
    # guard: skip blank lines
    if not raw.strip():
      continue
    if raw == raw.lstrip():  # column 0 -> top-level key
      # guard: top-level line must end with ':' to be a valid key mapping
      if not raw.rstrip().endswith(":"):
        raise ValueError(f"top-level line is not a 'key:' mapping: {raw!r}")
      cur_plugin = raw.rstrip()[:-1].strip()

      # guard: reject duplicate top-level keys
      if cur_plugin in data:
        raise ValueError(f"duplicate top-level key: {cur_plugin}")
      data[cur_plugin] = {}
      cur_path = None
    elif raw.startswith("    - "):  # 4-space glob item
      # guard: a glob item requires an enclosing template path to be active
      if cur_path is None:
        raise ValueError(f"glob item before any template path: {raw!r}")
      data[cur_plugin][cur_path].append(_unquote(raw[len("    - "):]))
    elif raw.startswith("  ") and not raw.startswith("   "):  # exactly 2-space -> template path
      # guard: a template path requires an enclosing plugin key to be active
      if cur_plugin is None:
        raise ValueError(f"template path before any plugin key: {raw!r}")

      # guard: template path line must end with ':' to be a valid mapping
      if not raw.rstrip().endswith(":"):
        raise ValueError(f"template line is not a 'path:' mapping: {raw!r}")
      cur_path = raw.strip()[:-1].strip()
      data[cur_plugin][cur_path] = []
    else:
      raise ValueError(f"unexpected indentation in registry block: {raw!r}")
  return data


def _scalar(val: str) -> str:
  """
  Render a glob/path as a YAML plain scalar, quoting only when necessary.

  Quote only when `val` starts with a YAML-reserved character (e.g. a leading `*`).
  Mid-string reserved characters stay plain.

  Args:
    val: Glob or path string to render.

  Returns:
    The input wrapped in double-quotes if the leading character is reserved, otherwise the input unchanged.
  """
  if val and val[0] in _RESERVED_LEAD:
    return f'"{val}"'
  return val


def render_key(plugin: str, entries: dict) -> str:
  """
  Serialize one top-level key's sub-block into YAML text.

  Emit `<plugin>:` then 2-space-indented `path:` lines each followed by 4-space
  `- glob` lines, in insertion order. The result ends with a newline.

  Args:
    plugin: Top-level plugin key (e.g. `lazycortex-core` or `_local`).
    entries: Mapping of template paths to lists of glob strings.

  Returns:
    The serialized sub-block as a string with a trailing newline.
  """
  out = [ f"{plugin}:" ]
  for path, globs in entries.items():
    out.append(f"  {path}:")
    for glob in globs:
      out.append(f"    - {_scalar(glob)}")
  return "\n".join(out) + "\n"


def _key_line_span(body_lines: list[str], plugin: str) -> tuple[int, int] | None:
  """
  Locate the contiguous line range for a top-level plugin key in the block body.

  Scans for a column-0 `<plugin>:` heading line, then extends the span downward
  to include all blank lines and indented child lines that follow it.

  Args:
    body_lines: Lines between the opening and closing fence markers (exclusive).
    plugin: Top-level key name to search for (e.g. `lazycortex-core`).

  Returns:
    A `(start, end)` pair where `start` is the index of the `<plugin>:` line and
    `end` (exclusive) is the first line that belongs to the next sibling key or
    to trailing blank space after the last key. Returns `None` when the key is
    absent.
  """
  start = None
  for idx, line in enumerate(body_lines):
    stripped = line.rstrip()

    # the key line sits at column 0, ends with ':', and names the target plugin
    if line == line.lstrip() and stripped.endswith(":") and stripped[:-1].strip() == plugin:
      start = idx
      break

  # guard: key not present
  if start is None:
    return None
  end = start + 1
  while end < len(body_lines) and (not body_lines[end].strip() or body_lines[end].startswith(" ")):
    end += 1
  return start, end


def _body_lines(md: str) -> list[str]:
  """
  Extract the lines that live between the fence markers of the Registry block.

  An empty block (`{}` or genuinely blank) returns an empty list so callers can
  treat it uniformly as "no keys present yet".

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.

  Returns:
    The list of raw lines between the opening and closing fence (exclusive).
    Returns an empty list when the block contains only `{}` or only blank lines.
  """
  lines, open_idx, close_idx = _locate_block(md)
  body = lines[open_idx + 1 : close_idx]
  non_blank = [ line for line in body if line.strip() ]

  # guard: treat an empty-dict sentinel as an empty body
  if non_blank == ["{}"] or not non_blank:
    return []
  return body


def _rewrite_block(md: str, body_lines: list[str]) -> str:
  """
  Reconstruct the markdown source with a replacement Registry block body.

  Replaces the lines between the opening and closing fence markers with
  `body_lines`, preserving every other byte in the source including the final
  newline when originally present. The source's own line ending is kept: a CRLF source is
  rewritten CRLF throughout, including the fence markers and `body_lines`; an LF source stays LF.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    body_lines: Replacement lines to place between the fence markers.

  Returns:
    The full markdown source with the block body replaced by `body_lines`.
  """
  lines, open_idx, close_idx = _locate_block(md)
  new_lines = lines[: open_idx + 1] + body_lines + lines[close_idx:]

  # the source's own line ending is kept, so a CRLF file stays CRLF
  newline = _newline_of(md)
  text = newline.join(new_lines)
  if md.endswith("\n"):
    text += newline
  return text


def _newline_of(md: str) -> str:
  """
  Return the line ending a markdown source uses.

  Args:
    md: Full markdown source.

  Returns:
    `\\r\\n` when the source carries any CRLF line ending, otherwise `\\n`.
  """
  return "\r\n" if "\r\n" in md else "\n"


def _read(path: str) -> str:
  """
  Read a rule file as stored, with no newline translation.

  Args:
    path: File to read.

  Returns:
    The file's text with its line endings untouched.
  """
  # waiver: stdlib file-mode idiom
  with open(path, encoding = "utf-8", newline = "") as fle:
    return fle.read()


def splice_upsert(md: str, plugin: str, entries: dict) -> str:
  """
  Replace or insert a plugin key-region inside the Registry block.

  When the key already exists, its entire line span is replaced with a freshly
  rendered block. When the key is absent, the rendered block is appended after
  the last existing key.

  Guarantees:
    - Every other plugin's key-region and every byte outside the fence markers are
      preserved verbatim.
    - The input's own line ending is kept: a CRLF source stays CRLF throughout, an LF source stays LF.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Top-level key name to upsert (e.g. `lazycortex-core` or `_local`).
    entries: Mapping of template paths to lists of glob strings for this key.

  Returns:
    The updated markdown source with the plugin key-region replaced or appended.
  """

  # Contract:
  # Every other plugin's key-region and every byte outside the fence markers are
  # preserved verbatim; only the named plugin's own line span is replaced or appended.

  # Contract:
  # The returned source MUST keep the input's own line ending: a CRLF source stays CRLF throughout,
  # an LF source stays LF.

  # Domain(install.reconciliation):
  # # Splicing a registry key touches only that key's own lines
  # A plugin registering, updating, or dropping its own entries in a shared registry never
  # rewrites the file as a whole; it replaces only the contiguous span of lines that belong to
  # its own top-level key, leaving every other plugin's key and every byte outside the
  # registry's own block untouched. Ordering follows arrival — a key that does not exist yet
  # is appended after whatever is already there, never inserted or reordered — so an
  # independent writer touching a different key at another time can never see its own
  # untouched region moved.

  body = _body_lines(md)
  rendered = render_key(plugin, entries).splitlines()
  span = _key_line_span(body, plugin)
  if span is None:
    new_body = body + rendered
  else:
    span_start, span_end = span
    new_body = body[:span_start] + rendered + body[span_end:]
  return _rewrite_block(md, new_body)


def graft_registry(shipped_md: str, target_md: str) -> str:
  """
  Return the shipped rule text carrying the target's current Registry block body.

  Everything outside the `## Registry` fence comes from the shipped source, so a
  stale consumer copy is refreshed wholesale.

  Guarantees:
    - The target's Registry block body — the customer-authored key plus every
      installed plugin's key — is carried over verbatim.
    - The shipped source's own line ending is kept, carried-over body lines included: a CRLF shipped source
      stays CRLF throughout, an LF one stays LF.

  Args:
    shipped_md: Full markdown source of the rule as the plugin ships it.
    target_md: Full markdown source of the consumer's current copy.

  Returns:
    The shipped source with its Registry block body replaced by the target's.

  Raises:
    ValueError: If either source lacks a well-formed `## Registry` ```yaml block.
  """

  # Contract:
  # The target's Registry block body — the customer-authored key plus every
  # installed plugin's key — is carried over verbatim; no key is dropped or reordered.

  # Contract:
  # The returned source MUST keep the shipped source's own line ending, carried-over body lines
  # included: a CRLF shipped source stays CRLF throughout, an LF one stays LF.

  # Domain(install.reconciliation):
  # # A scaffold registry refresh keeps the consumer's block, replaces everything around it
  # Refreshing a consumer's scaffold registry file takes the whole document from the shipped
  # source except for one region: the body of the registry block, which is the consumer's own
  # accumulated state — every installed plugin's own entries plus whatever the consumer
  # authored under its own key. That body survives a refresh unchanged while every other byte
  # in the file, instructions and heading text alike, is replaced with whatever the shipping
  # plugin ships today, so a stale consumer copy of the surrounding rule text is corrected on
  # every sync without losing a single registered key.

  body = _body_lines(target_md)

  # an empty consumer block carries no keys, so the shipped empty-dict sentinel stands in
  return _rewrite_block(shipped_md, body or ["{}"])


def scope_root(registry: str) -> str:
  """
  Return the consumer-scope root that a registry file's relative template paths are written against.

  Args:
    registry: Path of the registry markdown file, `<root>/.claude/rules/<name>.md`.

  Returns:
    The absolute path of the directory three levels above the registry file.
  """
  return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(registry))))


def read_installed_plugins() -> frozenset[str] | None:
  """
  Return the names of the plugins installed for the operator, or None when that record is unreadable.

  Returns:
    The plugin names, each taken from the part of a record key before `@`; None when
    the record is absent, unreadable, or not shaped as expected.
  """
  try:
    with open(os.path.expanduser(_INSTALLED_PLUGINS), encoding = "utf-8") as fle:
      data = json.load(fle)
  except (OSError, ValueError):
    return None
  # waiver: external-result schema field name, not an internal key
  plugins = data.get("plugins")

  # guard: an unexpected shape says nothing about what is installed
  if not isinstance(plugins, dict):
    return None
  return frozenset(key.split("@")[0] for key in plugins)


def _is_template_readable(path: str, base_dir: str) -> bool:
  """
  Report whether a registered template path resolves to a readable file in the consumer's tree.

  Args:
    path: Template path exactly as the registry records it.
    base_dir: Consumer-scope root that a relative path is resolved against.

  Returns:
    True when the resolved path names an existing, readable file.
  """
  resolved = os.path.expanduser(path) if path.startswith("~") else os.path.join(base_dir, path)
  return os.path.isfile(resolved) and os.access(resolved, os.R_OK)


def validate(md: str, *, base_dir: str | None = None, installed: frozenset[str] | None = None) -> list[dict]:
  """
  Return a list of findings for the Registry block; an empty list means the block is clean.

  Reports every problem found in the block as a coded finding; the finding codes name the problem kinds.

  Guarantees:
    - Every finding this function adds for a template that is missing on disk or for a
      key that matches no installed plugin carries severity `WARN`, never `FAIL`.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    base_dir: Consumer-scope root for resolving template paths; None skips the
      on-disk existence check entirely.
    installed: Names of the installed plugins; None skips the orphan-key check entirely.

  Returns:
    A list of finding dicts, each with keys `code`, `severity` (`"FAIL"` or `"WARN"`),
    and `msg`. Returns an empty list when the block is structurally valid and no
    overlaps, missing templates, or orphan keys are detected.
  """

  # Contract:
  # A missing-template finding and an orphan-key finding MUST both carry severity `WARN`:
  # neither is a precondition for authoring a file, so neither may block a caller that
  # refuses only on `FAIL`.

  # Domain(install.reconciliation):
  # # A scaffold template path always lives in the consumer's own tree
  # A registered template path names where a scaffolded file will be authored inside the
  # consumer's own tree — a project's own template directory or the operator's global one —
  # never inside the shipping plugin's installed directory. A path built from a variable that
  # only resolves inside a plugin's own tree therefore names nothing a consumer could ever
  # reach, and is rejected outright rather than merely warned about. Two different registered
  # keys claiming the very same glob is a softer problem: both stay valid on their own, only
  # the choice between them for one shared path becomes ambiguous, so it is surfaced for a
  # human to judge instead of treated as a structural defect.

  # Domain(install.reconciliation):
  # # A registry defect is reported, never a precondition
  # A registry may name a template that is missing or unreadable on disk, and it may carry a key
  # for a plugin that is no longer installed. Neither stops an author from writing the file whose
  # path the entry matches, and neither licenses substituting a neighbouring template in the
  # missing one's place — the registry exists to point at a starting draft, not to gate authoring.
  # Both conditions are therefore surfaced to the operator as warnings through the same reporting
  # channel that carries glob shadowing, and a caller that refuses only on structural defects goes
  # on working unimpeded.

  # a block that does not parse has no entries to judge, so that one defect is the whole report
  findings: list[dict] = []
  try:
    data = parse_registry_block(md)
  except ValueError as error:
    return [ {
      _FindingFieldId.CODE: _FindingKind.PARSE_ERROR,
      _FindingFieldId.SEVERITY: _FindingLevel.FAIL,
      _FindingFieldId.MSG: str(error),
    } ]

  # every key is scanned on its own, and the globs it claims are kept for the cross-key pass below
  globs_by_key: dict[str, set] = {}
  for plugin, entries in data.items():
    # a key naming a plugin nobody installed is leftover registration, not a structural defect
    if installed is not None and plugin != LOCAL_KEY and plugin not in installed:
      findings.append({
        _FindingFieldId.CODE: _FindingKind.ORPHAN_KEY,
        _FindingFieldId.SEVERITY: _FindingLevel.WARN,
        _FindingFieldId.MSG: f"{plugin}: registry key matches no installed plugin",
      })

    # guard: top-level value must be a dict (mapping of template paths)
    if not isinstance(entries, dict):
      findings.append({
        _FindingFieldId.CODE: _FindingKind.BAD_SHAPE,
        _FindingFieldId.SEVERITY: _FindingLevel.FAIL,
        _FindingFieldId.MSG: f"{plugin} not a mapping",
      })
      continue
    gset: set = set()
    for path, globs in entries.items():
      if "${CLAUDE_PLUGIN_ROOT}" in path:
        findings.append({
          _FindingFieldId.CODE: _FindingKind.PLUGIN_ROOT_VAR,
          _FindingFieldId.SEVERITY: _FindingLevel.FAIL,
          _FindingFieldId.MSG: f"{plugin}: template path uses ${{CLAUDE_PLUGIN_ROOT}}: {path}",
        })
      # a plugin-root path resolves nowhere by design, so only a plain path is looked for on disk
      elif base_dir is not None and not _is_template_readable(path, base_dir):
        findings.append({
          _FindingFieldId.CODE: _FindingKind.MISSING_TEMPLATE,
          _FindingFieldId.SEVERITY: _FindingLevel.WARN,
          _FindingFieldId.MSG: f"{plugin}: template missing or unreadable: {path}",
        })

      # guard: glob list must be a list
      if not isinstance(globs, list):
        findings.append({
          _FindingFieldId.CODE: _FindingKind.BAD_SHAPE,
          _FindingFieldId.SEVERITY: _FindingLevel.FAIL,
          _FindingFieldId.MSG: f"{plugin}/{path}: globs not a list",
        })
        continue
      gset.update(globs)
    globs_by_key[plugin] = gset

  # two keys claiming the very same glob are surfaced for a human to judge
  # limit: identical spellings only, compare glob coverage if differently spelled clashes start to matter
  keys = list(globs_by_key)
  for idx_a, key_a in enumerate(keys):
    for idx_b in range(idx_a + 1, len(keys)):
      common = globs_by_key[key_a] & globs_by_key[keys[idx_b]]
      if common:
        findings.append({
          _FindingFieldId.CODE: _FindingKind.GLOB_OVERLAP,
          _FindingFieldId.SEVERITY: _FindingLevel.WARN,
          _FindingFieldId.MSG: f"{key_a} and {keys[idx_b]} share globs: {sorted(common)}",
        })
  return findings


def splice_remove(md: str, plugin: str) -> str:
  """
  Delete a plugin key-region from the Registry block.

  Removes the `<plugin>:` heading line and all of its indented child lines.
  Has no effect when the key is absent.

  Guarantees:
    - Every other plugin's key-region and every byte outside the fence markers are
      preserved verbatim.
    - The input's own line ending is kept: a CRLF source stays CRLF throughout, an LF source stays LF.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Top-level key name to remove (e.g. `lazycortex-core` or `_local`).

  Returns:
    The updated markdown source with the plugin key-region removed, or the
    original source unchanged when the key was not present.
  """

  # Contract:
  # Every other plugin's key-region and every byte outside the fence markers are
  # preserved verbatim; only the named plugin's own line span is removed.

  # Contract:
  # The returned source MUST keep the input's own line ending: a CRLF source stays CRLF throughout,
  # an LF source stays LF.

  body = _body_lines(md)
  span = _key_line_span(body, plugin)

  # guard: key absent — nothing to remove
  if span is None:
    return md
  span_start, span_end = span
  new_body = body[:span_start] + body[span_end:]
  return _rewrite_block(md, new_body)


def merge_manifests(install_path: str) -> MergedManifests:
  """
  Merge every scaffold manifest that a plugin ships into one template map.

  A plugin without a templates tree yields no groups and no entries. A template path that two groups declare with
  identical globs counts as one entry.

  Args:
    install_path: Root directory of the installed plugin.

  Returns:
    The groups that contributed a manifest and the merged map of template paths to glob lists.

  Raises:
    ManifestCollisionError: If two groups declare one template path with different globs.
  """
  templates_dir = os.path.join(install_path, _TEMPLATES_DIR)

  # guard: a plugin without a templates tree ships no scaffold entries at all
  if not os.path.isdir(templates_dir):
    return MergedManifests(groups = [], entries = {})

  # a manifest sits exactly one directory below templates/, so a flat listing finds every one
  groups = sorted(
    name for name in os.listdir(templates_dir)
    if os.path.isfile(os.path.join(templates_dir, name, MANIFEST_NAME))
  )

  # every group's map joins the union; a key two groups declare differently stops the merge
  entries: dict[str, list[str]] = {}
  owner: dict[str, str] = {}
  for group in groups:
    with open(os.path.join(templates_dir, group, MANIFEST_NAME), encoding = "utf-8") as fle:
      # waiver: external manifest schema field name, not an internal key
      templates = json.load(fle).get("templates", {})
    for key, globs in templates.items():
      # guard: a key another group already declared with different globs is a collision
      if key in entries and entries[key] != globs:
        raise ManifestCollisionError(key, owner[key], group)
      entries[key] = globs
      owner.setdefault(key, group)

  # the groups that contributed and their merged map
  return MergedManifests(groups = groups, entries = entries)


def _fail_findings(md: str) -> list[dict]:
  """
  Return the structural defects of a registry source.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.

  Returns:
    The findings of severity `FAIL`; an empty list when the registry is fit to be written.
  """
  # only a structural defect refuses a write; warnings are the operator's to judge
  return [ fnd for fnd in validate(md) if fnd[_FindingFieldId.SEVERITY] == _FindingLevel.FAIL ]


def upsert(registry: str, plugin: str, entries: dict) -> dict:
  """
  Register one plugin's template map in a registry file, creating the file when it is absent.

  An existing registry that does not parse is reported and left as it is. A registry that already holds exactly
  the resulting content is not rewritten.

  Guarantees:
    - An existing registry that does not parse cleanly (has `FAIL` findings) is reported with status `error` and is
      never rewritten.
    - A result identical to the file's current content leaves the file untouched and is reported with status
      `unchanged`.

  Args:
    registry: Path of the registry markdown file.
    plugin: Registry key to write.
    entries: Mapping of template paths to lists of glob strings for the key.

  Returns:
    A report holding the outcome word under `status` and the registry key under `plugin`; a registry that does not
    parse adds the defects under `findings`.
  """

  # Contract:
  # An existing registry that does not parse cleanly, meaning it has FAIL findings,
  # is reported with status `error` and NEVER rewritten.

  # Contract:
  # A result identical to the file's current content leaves the file untouched
  # and is reported with status `unchanged`.

  # an absent registry starts from the minimal rule file
  if not os.path.exists(registry):
    _atomic_write(registry, splice_upsert(MINIMAL_REGISTRY, plugin, entries))
    return { _FieldId.STATUS: _RunState.CREATED, _FieldId.PLUGIN: plugin }

  # the registry as it stands on disk
  md = _read(registry)

  # guard: an existing file that does not parse cleanly is never rewritten
  if errs := _fail_findings(md):
    return { _FieldId.STATUS: _RunState.ERROR, _FieldId.PLUGIN: plugin, _FieldId.FINDINGS: errs }

  # the key is replaced in place; an identical result leaves the file alone
  new_md = splice_upsert(md, plugin, entries)
  if new_md == md:
    return { _FieldId.STATUS: _RunState.UNCHANGED, _FieldId.PLUGIN: plugin }
  _atomic_write(registry, new_md)
  return { _FieldId.STATUS: _RunState.REGISTERED, _FieldId.PLUGIN: plugin }


def set_entry(md: str, plugin: str, template: str, globs: list[str]) -> str:
  """
  Return the registry source with one template's globs set under one key.

  The key's other templates stay as they are; the named template takes the new globs whole, and a key that does
  not exist yet is created.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Registry key to write under.
    template: Template path to set.
    globs: Glob strings the template takes.

  Returns:
    The updated markdown source.

  Raises:
    ValueError: If the source lacks a well-formed `## Registry` ```yaml block.
  """
  # the key's other templates stay; this one takes the new globs whole
  entries = dict(parse_registry_block(md).get(plugin) or {})
  entries[template] = list(globs)
  return splice_upsert(md, plugin, entries)


def drop_entry(md: str, plugin: str, template: str) -> tuple[str, bool]:
  """
  Return the registry source without one template under one key.

  A key left with no template leaves the block instead of staying empty. A template that the key does not list
  leaves the source as it is.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Registry key to drop from.
    template: Template path to drop.

  Returns:
    The updated markdown source and whether the key listed the template.

  Raises:
    ValueError: If the source lacks a well-formed `## Registry` ```yaml block.
  """
  entries = dict(parse_registry_block(md).get(plugin) or {})

  # guard: a template the key does not list leaves the registry as it is
  if template not in entries:
    return md, False
  del entries[template]

  # a key left with no template disappears from the block instead of staying empty
  return (splice_upsert(md, plugin, entries) if entries else splice_remove(md, plugin)), True


def _resolve_local_key(key: str, *, scope_base: str, home: str) -> str:
  """
  Resolve a template path that the registry records into an absolute path.

  Args:
    key: Template path exactly as the registry records it.
    scope_base: Scope root that a relative template path is resolved against.
    home: The operator's home directory, which a `~/` template path is resolved against.

  Returns:
    The path of the template in the consumer's tree.
  """
  # a home-relative key names the operator's home whatever the scope; any other key is scope-relative
  if key.startswith(_HOME_PREFIX):
    return os.path.join(home, key[len(_HOME_PREFIX):])
  return os.path.join(scope_base, key)


def _join_findings(findings: list[dict]) -> str:
  """
  Join the messages of findings into one line.

  Args:
    findings: Findings as `validate` returns them.

  Returns:
    The finding messages separated by semicolons.
  """
  # one line naming every finding, for the run's message field
  return "; ".join(fnd[_FindingFieldId.MSG] for fnd in findings)


def _sync_groups(install_path: str, scope_base: str, merged: MergedManifests, protected: frozenset[str],
                 result: dict) -> None:
  """
  Copy a plugin's template groups into the consumer's tree and record the receipts in the run's report.

  Notes:
    - Adds one line per copied template to the report's template list and counts the lines per copy state.
    - Names every template whose write did not verify in the report's failed list.

  Args:
    install_path: Root directory of the installed plugin.
    scope_base: Scope root that holds the consumer's template groups.
    merged: The plugin's merged manifests.
    protected: Normalized paths of the operator's own templates, which a copy never overwrites.
    result: Run report to extend.
  """
  # each group's shipped templates are copied over stale ones, the manifest itself excluded
  for group in merged.groups:
    receipt = file_sync.sync_dir(
      os.path.join(install_path, _TEMPLATES_DIR, group),
      os.path.join(scope_base, _CONSUMER_TEMPLATES_REL, group),
      excludes = frozenset({ MANIFEST_NAME }), copy_diverged = True, protected = protected,
    )

    # every receipt line is reported, counted by state, and a write that did not verify is named
    for entry in receipt:
      state = entry[file_sync.KEY_STATE]
      name = entry[file_sync.KEY_FILE]
      result[_FieldId.TEMPLATES].append({ _FieldId.GROUP: group, _FieldId.FILE: name, _FieldId.STATE: state })
      result[_FieldId.COUNTS][state] = result[_FieldId.COUNTS].get(state, 0) + 1
      if state == file_sync.STATE_FAILED:
        result[_FieldId.FAILED].append(f"{group}/{name}")


def sync_plugin(plugin: str, install_path: str, *, scope: str, repo_root: str, home: str) -> dict:
  """
  Copy a plugin's scaffold templates into a consumer scope and register their globs.

  Guarantees:
    - A registry that does not parse, a collision between the plugin's manifests, or a plugin that ships no manifest
      ends the run before any template or the registry file is written.
    - A template the operator registered as their own is never overwritten by a namesake the plugin ships.

  Notes:
    - Copies the template groups into the scope's templates tree and writes the registry file.

  Args:
    plugin: Registry key to register the plugin's templates under.
    install_path: Root directory of the installed plugin.
    scope: Install scope, `project` or `user`.
    repo_root: Root of the repository that a `project` scope writes into.
    home: The operator's home directory, which a `user` scope writes into.

  Returns:
    A report holding the outcome word under `status`, the registry path, the groups copied, one line per template,
    the line counts per copy state, the templates whose write did not verify, and a one-line message that explains
    a refusal.
  """

  # Contract:
  # A registry that does not parse, a collision between the plugin's manifests, or a plugin that ships no manifest
  # MUST end the run before anything is written: neither a template nor the registry file is touched.

  # Contract:
  # A template the operator registered under the `_local` key MUST NEVER be overwritten by a namesake
  # the plugin ships.

  # scope root and registry path the run works against
  scope_base = home if scope == _SCOPE_USER else repo_root
  registry = os.path.join(scope_base, _REGISTRY_REL)
  result: dict = {
    _FieldId.STATUS: "", _FieldId.REGISTRY: registry, _FieldId.GROUPS: [], _FieldId.TEMPLATES: [],
    _FieldId.COUNTS: {}, _FieldId.FAILED: [], _FieldId.MESSAGE: "",
  }

  # the registry as it stands, or the minimal rule file when it is absent
  current = _read(registry) if os.path.exists(registry) else MINIMAL_REGISTRY

  # guard: a registry that does not parse is never written, so nothing else is written either
  if errs := _fail_findings(current):
    result.update({ _FieldId.STATUS: _RunState.ERROR, _FieldId.MESSAGE: _join_findings(errs) })
    return result

  # the operator's own `_local` templates are never overwritten by a namesake the plugin ships
  local = parse_registry_block(current).get(LOCAL_KEY) or {}
  protected = frozenset(
    file_sync.norm_path(_resolve_local_key(key, scope_base = scope_base, home = home)) for key in local
  )

  # every manifest is merged before anything is written, so a collision leaves the consumer untouched
  try:
    merged = merge_manifests(install_path)
  except ManifestCollisionError as error:
    result.update({ _FieldId.STATUS: _RunState.COLLISION, _FieldId.MESSAGE: str(error) })
    return result

  # guard: a plugin shipping no manifest has nothing to copy and nothing to register
  if not merged.groups:
    message = f"no {MANIFEST_NAME} manifests found under `{install_path}/{_TEMPLATES_DIR}/`"
    result.update({ _FieldId.STATUS: _RunState.NONE, _FieldId.MESSAGE: message })
    return result

  # the templates land first, then the merged map lands under the plugin's own key
  result[_FieldId.GROUPS] = merged.groups
  _sync_groups(install_path, scope_base, merged, protected, result)
  outcome = upsert(registry, plugin, merged.entries)

  # the registry outcome is the run's status
  result[_FieldId.STATUS] = outcome[_FieldId.STATUS]
  if outcome.get(_FieldId.FINDINGS):
    result[_FieldId.MESSAGE] = _join_findings(outcome[_FieldId.FINDINGS])
  return result


def _add_entry_parsers(sub: argparse._SubParsersAction) -> None:
  """
  Declare the argument parsers of the plugin-sync and entry-level subcommands.

  Args:
    sub: Subparser collection to extend.
  """
  # sync-plugin names the plugin, its install tree and the scope the registry lives in
  sync = sub.add_parser(_SubcommandKind.SYNC_PLUGIN)
  # waiver: argparse CLI signature, not a domain key
  sync.add_argument("--plugin", required = True)
  # waiver: argparse CLI signature, not a domain key
  sync.add_argument("--install-path", required = True)
  # waiver: argparse CLI signature, not a domain key
  sync.add_argument("--scope", required = True, choices = ( _SCOPE_PROJECT, _SCOPE_USER ))
  # waiver: argparse CLI signature, not a domain key
  sync.add_argument("--cwd", default = None)

  # set-entry and drop-entry name one template under one key of one registry
  for name in ( _SubcommandKind.SET_ENTRY, _SubcommandKind.DROP_ENTRY ):
    sparser = sub.add_parser(name)
    # waiver: argparse CLI signature, not a domain key
    sparser.add_argument("--registry", required = True)
    # waiver: argparse CLI signature, not a domain key
    sparser.add_argument("--plugin", required = True)
    # waiver: argparse CLI signature, not a domain key
    sparser.add_argument("--template", required = True)
    if name == _SubcommandKind.SET_ENTRY:
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--glob", action = "append", required = True)


def _cmd_sync_plugin(args: argparse.Namespace) -> int:
  """
  Run the `sync-plugin` subcommand and print its report as JSON.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code: 3 when a template write did not verify, 1 on a manifest collision or a registry that does not
    parse, otherwise 0.
  """
  result = sync_plugin(
    args.plugin, args.install_path, scope = args.scope,
    repo_root = str(resolve_git_toplevel(args.cwd)), home = str(Path.home()),
  )
  print(json.dumps(result))

  # a write that did not verify outranks the registry outcome, as it does for the copy primitive
  if result[_FieldId.FAILED]:
    return _EXIT_SYNC_FAILED
  return 1 if result[_FieldId.STATUS] in ( _RunState.COLLISION, _RunState.ERROR ) else 0


def _refuse_entry(args: argparse.Namespace, error: Exception) -> int:
  """
  Report on stderr that an entry verb could not read or parse its registry.

  The report is one JSON line naming the plugin, the template and the reason; the registry file is not touched.

  Args:
    args: Parsed command-line arguments of the `set-entry` or `drop-entry` subcommand.
    error: The failure that stopped the verb.

  Returns:
    Shell exit code 1.
  """
  # the refusal is one JSON line naming the entry and the reason, as the upsert verb's refusal is
  refusal = {
    _FieldId.STATUS: _RunState.ERROR, _FieldId.PLUGIN: args.plugin, _FieldId.TEMPLATE: args.template,
    _FieldId.MESSAGE: f"registry `{args.registry}` cannot be used: {error}",
  }
  print(json.dumps(refusal), file = sys.stderr)
  return 1


def _cmd_set_entry(args: argparse.Namespace) -> int:
  """
  Run the `set-entry` subcommand and print its report as JSON.

  The registry file is created when it is absent.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code: 0 on success, 1 when the registry cannot be read or lacks a well-formed `## Registry` block;
    that refusal is one JSON line on stderr and the registry file stays as it is.
  """
  # the new map is the file's current one with the template set; an unreadable or unparseable registry is refused
  try:
    current = _read(args.registry) if os.path.exists(args.registry) else MINIMAL_REGISTRY
    entries = parse_registry_block(set_entry(current, args.plugin, args.template, args.glob))[args.plugin]
  except (OSError, ValueError) as error:
    return _refuse_entry(args, error)

  # the map is written through the one upsert path
  outcome = upsert(args.registry, args.plugin, entries)
  return _emit({ **outcome, _FieldId.TEMPLATE: args.template })


def _cmd_drop_entry(args: argparse.Namespace) -> int:
  """
  Run the `drop-entry` subcommand and print its report as JSON.

  A key left with no template leaves the registry block. A missing registry or a template that the key does not
  list is reported as not found and the file stays as it is.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code: 0 when the template was dropped, 1 when it was not found or the registry cannot be read or
    lacks a well-formed `## Registry` block; an unusable registry is reported as one JSON line on stderr and the
    registry file stays as it is.
  """
  report = { _FieldId.STATUS: _RunState.NOT_FOUND, _FieldId.PLUGIN: args.plugin, _FieldId.TEMPLATE: args.template }

  # guard: a registry that does not exist lists no template at all
  if not os.path.exists(args.registry):
    print(json.dumps(report))
    return 1

  # the registry without the template; an unreadable or unparseable registry is refused untouched
  try:
    new_md, found = drop_entry(_read(args.registry), args.plugin, args.template)
  except (OSError, ValueError) as error:
    return _refuse_entry(args, error)

  # guard: a template the key does not list is refused and the file stays as it is
  if not found:
    print(json.dumps(report))
    return 1

  # a key with templates left is rewritten by upsert; a key left empty is removed from the block
  if entries := parse_registry_block(new_md).get(args.plugin):
    outcome = upsert(args.registry, args.plugin, entries)
    # a registry that does not parse is reported, never rewritten
    if outcome[_FieldId.STATUS] == _RunState.ERROR:
      return _emit({ **outcome, _FieldId.TEMPLATE: args.template })
    return _emit({ **report, _FieldId.STATUS: _RunState.REMOVED_ENTRY })
  _atomic_write(args.registry, new_md)
  return _emit({ **report, _FieldId.STATUS: _RunState.REMOVED_PLUGIN })


def _atomic_write(path: str, text: str) -> None:
  """
  Write `text` to `path` atomically via a same-directory temp file.

  Creates the parent directory if absent. The write is completed by an
  atomic rename so a concurrent reader never observes a partial file.

  Args:
    path: Destination file path (created or overwritten).
    text: Full text content to write.
  """
  # the shared writer keeps the file's mode and writes through a symlink to its real target
  runtime_state.atomic_write_text(Path(path), text)


def _emit(obj: dict) -> int:
  """
  Serialise `obj` as JSON to stdout and return a shell exit code.

  Returns 0 for all statuses except `"error"`, which returns 1.

  Args:
    obj: Result dict to emit; must contain a `"status"` key.

  Returns:
    0 on success, 1 when `obj["status"] == "error"`.
  """
  print(json.dumps(obj))
  # waiver: external-result schema field name, not an internal key
  if obj.get("status") == "error":
    return 1
  return 0


def _load_entries(arg: str) -> dict:
  """
  Deserialise a plugin entries mapping from a CLI argument string.

  Accepts two forms: a bare JSON object string, or `@<path>` where `<path>`
  is a file containing the JSON object.

  Args:
    arg: JSON string or `@<filepath>` reference.

  Returns:
    The deserialised mapping of template paths to glob lists.
  """
  if arg.startswith("@"):
    with open(arg[1:], encoding = "utf-8") as fle:
      return json.load(fle)
  return json.loads(arg)


def _sync_rule(src: str, registry: str, *, exists: bool) -> int:
  """
  Refresh a consumer's scaffold rule file from the shipped source and report the outcome.

  The whole file is taken from the shipped source; only the Registry block body
  is carried over from the consumer's current copy. The written file is re-read
  and compared before the outcome is reported.

  Guarantees:
    - Refreshing an existing consumer file preserves that file's own line ending in the
      merged result, regardless of the shipped source's line ending.

  Args:
    src: Path of the shipped rule file.
    registry: Path of the consumer's rule file.
    exists: Whether the consumer's file is already present.

  Returns:
    Shell exit code: 0 on success, 1 on error or a failed post-write comparison.
  """
  # guard: without the shipped source there is nothing to refresh from
  if not os.path.exists(src):
    return _emit({ "status": "error", "msg": f"shipped source not found: {src}" })
  shipped = _read(src)

  # an absent target takes the shipped file whole, empty registry block included
  if not exists:
    _atomic_write(registry, shipped)
    new_md = shipped
    status = "installed"
  else:
    current = _read(registry)
    try:
      new_md = graft_registry(shipped, current)
    except ValueError as error:
      return _emit({ "status": "error", "msg": str(error) })

    # Contract:
    # Refreshing an existing consumer file preserves that file's own line ending in the
    # merged result, regardless of the shipped source's line ending.

    # the consumer's line ending survives a refresh from the shipped source
    new_md = new_md.replace("\r\n", "\n").replace("\n", _newline_of(current))
    if new_md == current:
      return _emit({ "status": "unchanged", "registry": registry })
    _atomic_write(registry, new_md)
    status = "refreshed"

  # a write that did not land, leaving the target without the intended bytes, is reported as a failure
  if _read(registry) != new_md:
    _emit({ "status": "failed", "registry": registry })
    return 1
  return _emit({ "status": status, "registry": registry })


def _cmd_upsert(args: argparse.Namespace) -> int:
  """
  Run the `upsert` subcommand: register one plugin's template map and print the report as JSON.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code: 0 on success, 1 when the registry does not parse; that refusal is one JSON line on stderr.
  """
  outcome = upsert(args.registry, args.plugin, _load_entries(args.entries))

  # a registry that does not parse is reported on stderr, as the verb always has
  if outcome[_FieldId.STATUS] == _RunState.ERROR:
    refusal = { _FieldId.STATUS: _RunState.ERROR, _FieldId.FINDINGS: outcome[_FieldId.FINDINGS] }
    print(json.dumps(refusal), file = sys.stderr)
    return 1
  return _emit(outcome)


def _cmd_sync_rule(args: argparse.Namespace) -> int:
  """
  Run the `sync-rule` subcommand: refresh the whole rule file from the shipped source, keeping the consumer's block.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code: 0 on success, 1 on error or a failed post-write comparison.
  """
  return _sync_rule(args.src, args.registry, exists = os.path.exists(args.registry))


def _cmd_remove(args: argparse.Namespace) -> int:
  """
  Run the `remove` subcommand: drop one plugin's block from the registry and print the report as JSON.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code 0, whether the block was removed or was absent.
  """
  # guard: a missing registry holds no block to remove
  if not os.path.exists(args.registry):
    return _emit({"status": "absent", "plugin": args.plugin})

  # a registry without the plugin's block is left untouched
  md = _read(args.registry)
  new_md = splice_remove(md, args.plugin)
  if new_md == md:
    return _emit({"status": "absent", "plugin": args.plugin})
  _atomic_write(args.registry, new_md)
  return _emit({"status": "removed", "plugin": args.plugin})


def _read_or_minimal(registry: str) -> str:
  """
  Read a registry file, or the minimal registry when the file does not exist.

  Args:
    registry: Path of the registry file.

  Returns:
    The registry's markdown text.
  """
  return _read(registry) if os.path.exists(registry) else MINIMAL_REGISTRY


def _cmd_list(args: argparse.Namespace) -> int:
  """
  Run the `list` subcommand: print the parsed registry as JSON.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code 0.
  """
  return _emit({"status": "ok", "registry": parse_registry_block(_read_or_minimal(args.registry))})


def _cmd_validate(args: argparse.Namespace) -> int:
  """
  Run the `validate` subcommand: print the registry's own findings as JSON without touching it.

  Args:
    args: Parsed command-line arguments.

  Returns:
    Shell exit code 0.
  """
  # the registry's own location names the consumer scope its relative template paths live in
  found = validate(
    _read_or_minimal(args.registry), base_dir = scope_root(args.registry), installed = read_installed_plugins(),
  )
  return _emit({"status": "ok", "findings": found})


# The handler each subcommand of the scaffold CLI routes to.
_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
  _SubcommandKind.SYNC_PLUGIN: _cmd_sync_plugin,
  _SubcommandKind.SET_ENTRY: _cmd_set_entry,
  _SubcommandKind.DROP_ENTRY: _cmd_drop_entry,
  # waiver: argparse CLI signature, not a domain key
  "upsert": _cmd_upsert,
  # waiver: argparse CLI signature, not a domain key
  "remove": _cmd_remove,
  # waiver: argparse CLI signature, not a domain key
  "list": _cmd_list,
  # waiver: argparse CLI signature, not a domain key
  "validate": _cmd_validate,
  # waiver: argparse CLI signature, not a domain key
  "sync-rule": _cmd_sync_rule,
}


def main(argv: list[str]) -> int:
  """
  Entry point for the `lazycortex-core scaffold` CLI.

  Maintains and inspects scaffold registry markdown files from the command line. Each
  invocation reports its result as a single JSON object on stdout.

  Args:
    argv: Argument list (typically `sys.argv[1:]`).

  Returns:
    Shell exit code: 0 on success, 1 on an error, a manifest collision, or a template that is not found, and 3 when
    a template write did not verify.
  """
  # one subparser per registry operation, each naming its registry file
  arg_parser = argparse.ArgumentParser(prog = "lazycortex-core scaffold")
  # waiver: argparse CLI signature, not a domain key
  sub = arg_parser.add_subparsers(dest = "cmd", required = True)
  for name in ("upsert", "remove", "list", "validate", "sync-rule"):
    sparser = sub.add_parser(name)
    # waiver: argparse CLI signature, not a domain key
    sparser.add_argument("--registry", required = True)
    if name in ("upsert", "remove"):
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--plugin", required = True)
    # waiver: argparse CLI signature, not a domain key
    if name == "upsert":
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--entries", required = True)
    # waiver: argparse CLI signature, not a domain key
    if name == "sync-rule":
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--src", required = True)
  _add_entry_parsers(sub)
  args = arg_parser.parse_args(argv)

  # guard: argparse rejects unknown subcommands, so a name the table lacks is a programming error
  handler = _HANDLERS.get(args.cmd)
  if handler is None:
    return 1

  # hand the parsed namespace to the subcommand's handler
  return handler(args)


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
