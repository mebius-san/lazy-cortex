"""
Tool declarations for the spec catalog — what an asset is realised and checked with.

An asset's tools are the `spec_tools` frontmatter key on its status folder-note, and the set of
legal values is open: this plugin ships four declarations in
`references/lazy-spec.tool-types.json`, and a product declares its own under
`products[<key>].tool_types.<name>` in `.claude/lazy.settings.json`.

A declaration carries the playbook the coordinator loads for the tool, the document type the
tool's own report is written as, and optionally the document type its plan is written as — a
tool whose work needs no plan simply declares none.

The key is read three ways and the difference matters: an absent `spec_tools` means nobody has
judged the asset yet, an empty list means judged to need no tool at all, and a populated list is
the determined set.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import json
import sys
from functools import lru_cache
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_keys  # noqa: E402


# ----------------------------------------------------------------------------------------
class ToolTypeField:
  """
  Field names a tool declaration carries.

  Attributes:
    PLAYBOOK: Reference of the playbook the coordinator loads for the tool.
    REPORT_DOC: Document type the tool's own report is written as.
    PLAN_DOC: Document type the tool's plan is written as, absent for a tool needing none.
  """

  PLAYBOOK = "playbook"
  REPORT_DOC = "report_doc"
  PLAN_DOC = "plan_doc"


# ----------------------------------------------------------------------------------------
class _K:
  """
  Path and settings-key constants used by the declaration resolver.

  Attributes:
    TOOL_TYPES: Settings key holding a product's own tool declarations.
    REFERENCES_DIR: The plugin subdirectory holding the shipped declaration file.
    DEFAULTS_FILE: Filename of the shipped declaration file.
    ENCODING: File encoding used throughout this module.
  """

  TOOL_TYPES = "tool_types"
  REFERENCES_DIR = "references"
  DEFAULTS_FILE = "lazy-spec.tool-types.json"
  ENCODING = "utf-8"


# The one home of this key is `spec_keys.AssetTypeKey`, which `note_ops` reads from too.
_TOOLS_KEY = spec_keys.AssetTypeKey.TOOLS


def _plugin_root() -> Path:
  """
  Return the lazycortex-specs plugin root (parent of this script's `bin/`).

  Returns:
    Absolute path of the plugin root directory.
  """
  return Path(__file__).resolve().parent.parent


@lru_cache(maxsize = 1)
def builtin_defaults() -> dict[str, dict]:
  """
  Read the plugin's own tool declarations.

  Returns:
    Mapping of tool name to its declaration dict, exactly as shipped.
  """
  path = _plugin_root() / _K.REFERENCES_DIR / _K.DEFAULTS_FILE
  return json.loads(path.read_text(encoding = _K.ENCODING)).get(_K.TOOL_TYPES) or {}


def _declared(record: dict) -> dict[str, dict]:
  """
  Return every tool visible in one product's scope.

  The product's own declarations merge key-by-key over the shipped ones, so a product may
  replace a single field of a shipped tool without restating the rest.

  Args:
    record: The product's settings record, or `{}` when the caller has no product in scope.

  Returns:
    Mapping of tool name to its merged declaration dict.
  """
  merged = dict(builtin_defaults())
  for name, decl in ((record or {}).get(_K.TOOL_TYPES) or {}).items():
    merged[name] = { **merged.get(name, {}), **decl }
  return merged


def resolve(tool: str, record: dict) -> dict | None:
  """
  Resolve one tool's declaration in a product's scope.

  Args:
    tool: The tool name to look up.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The merged declaration dict, or None when neither the plugin nor the product declares it.
  """
  return _declared(record).get(tool)


def playbook_ref(tool: str, record: dict) -> str:
  """
  Resolve the playbook reference the coordinator loads for one tool.

  Args:
    tool: The tool being coordinated.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The playbook reference, or the empty string when the tool is undeclared or names none.
  """
  return (resolve(tool, record) or {}).get(ToolTypeField.PLAYBOOK, "")


def report_doc(tool: str, record: dict) -> str:
  """
  Resolve the document type one tool's report is written as.

  Args:
    tool: The tool doing the work.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The report document type, or the empty string when the tool is undeclared.
  """
  return (resolve(tool, record) or {}).get(ToolTypeField.REPORT_DOC, "")


def plan_doc(tool: str, record: dict) -> str:
  """
  Resolve the document type one tool's plan is written as.

  Args:
    tool: The tool doing the work.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The plan document type, or the empty string for a tool whose work needs no plan.
  """
  return (resolve(tool, record) or {}).get(ToolTypeField.PLAN_DOC, "")


def tools_of(note: Path) -> list[str] | None:
  """
  Read one status folder-note's `spec_tools` frontmatter value.

  Args:
    note: The status folder-note to read.

  Returns:
    None when the key is absent (nobody has judged the asset yet), an empty list when it is
    declared empty (judged to need no tool), or the declared tool names.
  """
  text = note.read_text(encoding = _K.ENCODING)
  # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
  fm_values, fm_end = flip_gate._parse_frontmatter(text)
  # guard: an absent key is "not determined yet", which no list value can express
  if _TOOLS_KEY not in fm_values:
    return None
  # waiver: sibling-module list reader -- handles both the block and the inline list forms
  return gate_tick._read_fm_list(text[:fm_end], _TOOLS_KEY)
