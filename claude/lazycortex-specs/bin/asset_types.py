"""
Asset-type declarations for the spec catalog — the `asset-type` CLI's resolver half.

An asset's kind is the `spec_asset_type` frontmatter key on its status folder-note, and the set
of legal values is open: this plugin ships five declarations in
`references/lazy-spec.asset-types.json`, and a product declares its own under
`products[<key>].asset_types.<name>` in `.claude/lazy.settings.json`.

A declaration carries the icon (and optional colour) the folder is painted with, the playbook
the coordinator loads for the type, the folder name a new asset of the type lands in by
default, the document it starts from as a `<file>:<doc_type>` pair, and the tools the type
implies before anyone has judged the asset. A type may borrow another type's playbook with
`alias_of` while keeping its own identity; an alias of an alias is refused rather than followed.

Every consumer asks here instead of matching a folder name against a closed list.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import os
import re
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
import spec_keys  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402


# ----------------------------------------------------------------------------------------
class AssetTypeField:
  """
  Field names an asset-type declaration carries.

  Attributes:
    ICON: Iconize icon name the asset folder is painted with.
    COLOR: Optional iconize colour paired with the icon.
    PLAYBOOK: Reference of the playbook the coordinator loads for the type.
    ALIAS_OF: Name of the concrete type this one borrows its playbook from.
    DEFAULT_PATH: Folder name a new asset of the type lands in when the caller names none.
    START_DOC: The type's starting document as a `<file>:<doc_type>` token.
    DEFAULT_TOOLS: Tools the type implies before anyone has judged the asset.
  """

  ICON = "icon"
  COLOR = "color"
  PLAYBOOK = "playbook"
  ALIAS_OF = "alias_of"
  DEFAULT_PATH = "default_path"
  START_DOC = "start_doc"
  DEFAULT_TOOLS = "default_tools"


# ----------------------------------------------------------------------------------------
class _K:
  """
  Path, settings-key, and frontmatter constants used by the declaration resolver.

  Attributes:
    ASSET_TYPES: Settings key holding a product's own asset-type declarations.
    PRODUCTS: Settings key holding the product registry.
    REFERENCES_DIR: The plugin subdirectory holding the shipped declaration file.
    DEFAULTS_FILE: Filename of the shipped declaration file.
    SETTINGS_REL: Repo-relative path of the settings file.
    ENCODING: File encoding used throughout this module.
    START_DOC_SEP: Separator between the file and the document type in a `start_doc` token.
    MD_SUFFIX: Filename suffix every spec document carries.
    SPEC_ROLE: Frontmatter key naming a document's role.
    STATUS_ROLE: The `spec_role` value marking a status folder-note.
    TOUCHED: Result field counting notes the backfill wrote to.
    SKIPPED: Result field counting notes the backfill left alone.
  """

  ASSET_TYPES = "asset_types"
  PRODUCTS = "products"
  REFERENCES_DIR = "references"
  DEFAULTS_FILE = "lazy-spec.asset-types.json"
  SETTINGS_REL = Path(".claude") / "lazy.settings.json"
  ENCODING = "utf-8"
  START_DOC_SEP = ":"
  MD_SUFFIX = ".md"
  SPEC_ROLE = "spec_role"
  STATUS_ROLE = "status"
  TOUCHED = "touched"
  SKIPPED = "skipped"


# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
_TYPE_KEY = spec_keys.AssetTypeKey.TYPE
_UNKNOWN = spec_keys.AssetTypeKey.UNKNOWN

# The frontmatter line the new key is inserted after — every status folder-note the catalog
# scaffolds carries `spec_role: status` above its body.
_FM_ANCHOR_RE = re.compile(r"(?m)^spec_role\s*:.*$")


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
  Read the plugin's own asset-type declarations.

  Returns:
    Mapping of type name to its declaration dict, exactly as shipped.
  """
  path = _plugin_root() / _K.REFERENCES_DIR / _K.DEFAULTS_FILE
  return json.loads(path.read_text(encoding = _K.ENCODING)).get(_K.ASSET_TYPES) or {}


def _declared(record: dict) -> dict[str, dict]:
  """
  Return every asset type visible in one product's scope.

  The product's own declarations merge key-by-key over the shipped ones, so a product may
  replace a single field of a shipped type without restating the rest.

  Args:
    record: The product's settings record, or `{}` when the caller has no product in scope.

  Returns:
    Mapping of type name to its merged declaration dict.
  """
  merged = dict(builtin_defaults())
  for name, decl in ((record or {}).get(_K.ASSET_TYPES) or {}).items():
    merged[name] = { **merged.get(name, {}), **decl }
  return merged


def resolve(asset_type: str, record: dict) -> dict | None:
  """
  Resolve one asset type's declaration in a product's scope.

  Args:
    asset_type: The `spec_asset_type` value to look up.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The merged declaration dict, or None when neither the plugin nor the product declares it.
  """
  return _declared(record).get(asset_type)


def alias_base(asset_type: str, record: dict) -> str:
  """
  Resolve the concrete type an alias borrows its declaration from.

  Args:
    asset_type: The type whose alias target is wanted.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The base type's name, or the empty string when the type is concrete or undeclared.

  Raises:
    ValueError: When the alias names an unknown base, or a base that is itself an alias.
  """
  base = (resolve(asset_type, record) or {}).get(AssetTypeField.ALIAS_OF, "")
  # guard: a concrete type borrows nothing — nothing further to validate
  if not base:
    return ""
  target = resolve(base, record)
  # guard: an alias pointing at nothing has no declaration to borrow
  if target is None:
    raise ValueError(f"{AssetTypeField.ALIAS_OF} of {asset_type!r} names an undeclared base type {base!r}")
  # guard: an alias chain would make resolution order-dependent — one hop only
  if target.get(AssetTypeField.ALIAS_OF):
    raise ValueError(f"{AssetTypeField.ALIAS_OF} of {asset_type!r} names {base!r}, which is itself "
                     f"an {AssetTypeField.ALIAS_OF} type — alias chains are not allowed")
  return base


def _effective(asset_type: str, record: dict) -> dict:
  """
  Resolve the declaration a type reads its playbook from, following one alias hop.

  Only the playbook is borrowed. Identity — the folder an asset lands in, the icon its folder
  is painted with, the document it starts from, the tools it implies — stays the alias's own,
  so an alias is a kind of its own that happens to be coordinated like its base.

  Args:
    asset_type: The type being resolved.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The type's own declaration with the base type's fields underneath it, or `{}` when the
    type is undeclared.
  """
  own = resolve(asset_type, record)
  # guard: an undeclared type has nothing to fall back to
  if own is None:
    return {}
  base = alias_base(asset_type, record)
  return { **(resolve(base, record) or {}), **own } if base else own


def icon_color(asset_type: str, record: dict) -> tuple[str, str] | None:
  """
  Resolve the icon and colour an asset of this type is painted with.

  Args:
    asset_type: The type being painted.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    An `(icon, color)` pair with an empty colour when the declaration names none, or None
    when the type is undeclared.
  """
  decl = resolve(asset_type, record)
  # guard: an undeclared type has no paint to report
  if decl is None:
    return None
  return decl.get(AssetTypeField.ICON, ""), decl.get(AssetTypeField.COLOR, "")


def playbook_ref(asset_type: str, record: dict) -> str:
  """
  Resolve the playbook reference the coordinator loads for one asset type.

  Args:
    asset_type: The type being coordinated.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The playbook reference, or the empty string when the type is undeclared or names none.
  """
  return _effective(asset_type, record).get(AssetTypeField.PLAYBOOK, "")


def default_path(asset_type: str, record: dict) -> str:
  """
  Resolve the folder name a new asset of this type lands in when the caller names none.

  Args:
    asset_type: The type being created.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The declared folder name, falling back to the type's own name.
  """
  return (resolve(asset_type, record) or {}).get(AssetTypeField.DEFAULT_PATH, "") or asset_type


def start_doc(asset_type: str, record: dict) -> tuple[str, str]:
  """
  Resolve the document a new asset of this type starts from.

  Args:
    asset_type: The type being created.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    A `(filename, doc_type)` pair, both empty when the type declares no starting document.
  """
  token = (resolve(asset_type, record) or {}).get(AssetTypeField.START_DOC, "")
  # guard: a type declaring no starting document has no pair to split
  if _K.START_DOC_SEP not in token:
    return "", ""
  name, _sep, doc_type = token.partition(_K.START_DOC_SEP)
  return name, doc_type


def default_tools(asset_type: str, record: dict) -> list[str]:
  """
  Resolve the tools an asset of this type implies before anyone has judged it.

  Args:
    asset_type: The type being created.
    record: The product's settings record, or `{}` to consult only the shipped set.

  Returns:
    The declared tool names, empty when the type implies none.
  """
  return list((resolve(asset_type, record) or {}).get(AssetTypeField.DEFAULT_TOOLS) or [])


def type_of(note: Path) -> str:
  """
  Read one status folder-note's `spec_asset_type` frontmatter value.

  The folder name is never consulted — a note under `ideas/` carrying `spec_asset_type: bug`
  is a bug.

  Args:
    note: The status folder-note to read.

  Returns:
    The declared type name, or the empty string when the key is absent.
  """
  # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
  fm_values, _fm_end = flip_gate._parse_frontmatter(note.read_text(encoding = _K.ENCODING))
  return fm_values.get(_TYPE_KEY, "")


def _folder_map(repo: Path) -> dict[str, str]:
  """
  Build the folder-name to type-name map the backfill derives a legacy note's type from.

  Every declared type contributes both its `default_path` and its own name, so an operator's
  type whose folder is named after the type itself resolves the same way a shipped one does.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.

  Returns:
    Mapping of folder name to the type it implies.
  """
  records: list[dict] = [ {} ]
  path = repo / _K.SETTINGS_REL
  if path.is_file():
    try:
      data = json.loads(path.read_text(encoding = _K.ENCODING))
    except json.JSONDecodeError:
      data = {}
    records = [ rec for rec in (data.get(_K.PRODUCTS) or {}).values() if isinstance(rec, dict) ] or [ {} ]

  # a later product's declaration may name the same folder; first writer wins, which keeps the
  # shipped set authoritative for the folder names it already owns
  mapping: dict[str, str] = {}
  for record in records:
    for name in _declared(record):
      for folder in ( default_path(name, record), name ):
        mapping.setdefault(folder, name)
  return mapping


def _insert_type(fm_text: str, asset_type: str) -> tuple[str, int]:
  """
  Insert a `spec_asset_type` line into a frontmatter block, right below its `spec_role` line.

  Args:
    fm_text: The note's frontmatter block, fences included.
    asset_type: The type name to write.

  Returns:
    A two-tuple `(new_frontmatter, insertions)`; `insertions` is `0` when there is no anchor
    line to write under.
  """
  line = f"{_TYPE_KEY}: {asset_type}"
  return _FM_ANCHOR_RE.subn(lambda m: f"{m.group(0)}\n{line}", fm_text, count = 1)


def backfill(repo: Path) -> dict:
  """
  Walk the spec content-root and add `spec_asset_type` to every status folder-note missing it.

  The type is derived from the name of the folder holding the asset — `features/auth/auth.md`
  is a `feature`. A folder no declaration claims yields the `unknown` sentinel, which the
  coordinator resolves on its own wake. Idempotent: a note already carrying the key is left
  alone and counted `skipped`. Never commits — the caller owns that.

  Args:
    repo: Absolute repository root (holds `.claude/lazy.settings.json`).

  Returns:
    `{"touched": N, "skipped": M}` — `N` notes gained the key, `M` already carried it.
  """
  settings_root = spec_paths.find_settings_root(repo)
  content_root = spec_paths.spec_content_root(settings_root)
  mapping = _folder_map(settings_root)
  touched = 0
  skipped = 0
  for dirpath, _dirnames, filenames in os.walk(content_root):
    folder = Path(dirpath)
    name = f"{folder.name}{_K.MD_SUFFIX}"
    # guard: a status folder-note is always named after its own folder
    if name not in filenames:
      continue
    note = folder / name
    text = note.read_text(encoding = _K.ENCODING)
    # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
    fm_values, fm_end = flip_gate._parse_frontmatter(text)
    # guard: only a status folder-note carries the asset's own type
    if fm_values.get(_K.SPEC_ROLE) != _K.STATUS_ROLE:
      continue
    # guard: already typed — idempotent no-op
    if _TYPE_KEY in fm_values:
      skipped += 1
      continue
    new_fm, count = _insert_type(text[:fm_end], mapping.get(folder.parent.name, _UNKNOWN))
    # guard: no anchor line to insert after — leave the note for the doctor to report
    if count != 1:
      skipped += 1
      continue
    note.write_text(new_fm + text[fm_end:], encoding = _K.ENCODING)
    touched += 1
  return { _K.TOUCHED: touched, _K.SKIPPED: skipped }


# waiver: CLI verb tokens -- dispatch keys for this module's own argparse router
_VERB_OF = "of"
_VERB_BACKFILL = "backfill"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
_OUT_ASSET_TYPE = "asset_type"


def _repo_from_args(cwd: str | None) -> Path:
  """
  Resolve the repository root the same way every other lazycortex-specs subcommand does.

  Args:
    cwd: The explicit `--cwd` value, or None.

  Returns:
    Absolute repository root: the flag, then the daemon-exported env var, then the process cwd.
  """
  return Path(cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()


def main(argv: list[str]) -> int:
  """
  Run one `asset-type` subcommand from the command line, printing its result as JSON.

  Args:
    argv: Argument list, excluding the program name.

  Returns:
    Exit code: `0` on success, `2` on bad arguments.
  """
  # waiver: argparse CLI signature -- program name shown in usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs asset-type")
  # waiver: argparse CLI signature -- subparser slot each verb registers into
  verbs = parser.add_subparsers(dest = "verb", required = True)
  p_of = verbs.add_parser(_VERB_OF)
  # waiver: argparse CLI signature -- positional argument name
  p_of.add_argument("note", type = Path)
  p_backfill = verbs.add_parser(_VERB_BACKFILL)
  # waiver: argparse CLI signature -- option flag + default
  p_backfill.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # `of` needs no repo at all — the answer lives in the note's own frontmatter
  if args.verb == _VERB_OF:
    print(json.dumps({ _OUT_ASSET_TYPE: type_of(args.note) }))
    return 0
  # the only remaining verb — argparse rejected anything else before reaching here
  print(json.dumps(backfill(_repo_from_args(args.cwd))))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
