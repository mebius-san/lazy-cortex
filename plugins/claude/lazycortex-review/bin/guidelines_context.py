"""
Resolve the product guideline paths a review writer dispatch carries.

Per `lazy-spec.config-protocol.md` § `products[<key>].guidelines`, a product's guidelines are
keyed by the dispatched role token plus the wildcard `"*"`, and an asset type's own
`guidelines` reach every job on an asset of that type whatever the role. The effective list is
the ordered union catalog-wide `spec.guidelines` first, then the enclosing products outermost
first, then the owning product's own — role paths, then the asset type's, then the wildcard
set, a path already listed never repeated.

The coordinator (`lazy-review.coordination-playbook.md` Chapter 4) reaches this module through
the `guidelines-context` CLI verb before every main or barrier (`validation` / `terminal`)
writer dispatch — never before `doc_doctor`'s repair dispatch — and folds the returned paths
into that dispatch's `context`. The expert reads the real files in the working tree; nothing is
copied here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import decisions_context  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION_KEY = "spec"
_VAULT_ROOT_KEY = "vault_root"
_DEFAULT_VAULT_ROOT = "specs"
_PRODUCTS_KEY = "products"
_SPEC_PATH_KEY = "spec_path"
_GUIDELINES_KEY = "guidelines"
_WILDCARD_ROLE = "*"
_ASSET_TYPES_KEY = "asset_types"
_ASSET_TYPE_KEY = "spec_asset_type"
_EXPERT_KEY_SEP = "."

PATHS_KEY = "paths"
WARNINGS_KEY = "warnings"


def role_of(expert: str) -> str:
  """
  Derive the guideline role token from a composed expert key.

  Args:
    expert: The dispatched expert's key, `<domain>.<role>` (`game.data-writer`).

  Returns:
    The part after the first dot; the whole key when it carries none.
  """
  return expert.partition(_EXPERT_KEY_SEP)[2] or expert


def _build_product_chain(data: dict, content_root: Path, start_dir: Path) -> list[dict]:
  """
  List the registered product records covering `start_dir`, outermost first.

  Args:
    data: The parsed settings file.
    content_root: The spec content root the products' `spec_path` values hang under.
    start_dir: Absolute directory to attribute — a document's own folder.

  Returns:
    Every product record whose `spec_path` resolves onto or above `start_dir`, ordered from
    the shallowest root to the deepest; empty when no product covers it.
  """
  products = data.get(_PRODUCTS_KEY)

  # guard: no products map at all — nothing to match start_dir against
  if not isinstance(products, dict):
    return []

  # scan every registered product; each covering root is one layer, keyed by its depth for the sort
  covering: list[tuple[int, dict]] = []
  for record in products.values():
    # guard: a non-dict entry can carry no spec_path field to check below
    if not isinstance(record, dict):
      continue

    # guard: only a non-empty spec_path names a product root
    if not isinstance(spec_path := record.get(_SPEC_PATH_KEY), str) or not spec_path:
      continue

    # a root that is start_dir itself or sits above it covers the document
    candidate = content_root / spec_path
    if candidate == start_dir or candidate in start_dir.parents:
      covering.append((len(candidate.parts), record))
  return [ record for _depth, record in sorted(covering, key = lambda pair: pair[0]) ]


def _read_asset_type(doc_path: Path) -> str:
  """
  Read the `spec_asset_type` of the asset folder holding `doc_path`, when it is one.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    The declared type name; the empty string outside an asset folder or when the key is absent.
  """
  asset_dir = decisions_context.resolve_asset_dir(doc_path)

  # guard: not inside a spec asset folder — no type to read
  if asset_dir is None:
    return ""

  # the status folder-note is the one place the asset's type is declared
  meta, _body = _fm.parse((asset_dir / f"{asset_dir.name}.md").read_text(encoding = "utf-8"))
  value = meta.get(_ASSET_TYPE_KEY)
  return value if isinstance(value, str) else ""


def _collect_role_paths(layers: list[dict], role: str) -> list[str]:
  """
  Union one role's guideline paths across the config layers, outermost first.

  Args:
    layers: The `guidelines` dicts, catalog first, then products outermost first.
    role: The role key to read from each layer.

  Returns:
    The declared paths in layer order; empty when no layer declares the role.
  """
  paths: list[str] = []
  for layer in layers:
    declared = layer.get(role)
    if isinstance(declared, list):
      paths.extend(path for path in declared if isinstance(path, str))
  return paths


def _collect_type_paths(chain: list[dict], asset_type: str) -> list[str]:
  """
  Resolve the asset type's own guideline paths — the innermost product declaring them wins.

  Args:
    chain: The covering product records, outermost first.
    asset_type: The dispatched asset's `spec_asset_type`; empty when there is none.

  Returns:
    The declared paths, empty when no product declares the field for the type.
  """

  # guard: no asset type — a product-level document carries no type guidelines
  if not asset_type:
    return []

  # asset_types merge key-by-key down the chain, so the deepest declaration of the field wins
  for record in reversed(chain):
    types = record.get(_ASSET_TYPES_KEY)
    decl = types.get(asset_type) if isinstance(types, dict) else None
    declared = decl.get(_GUIDELINES_KEY) if isinstance(decl, dict) else None
    if isinstance(declared, list):
      return [ path for path in declared if isinstance(path, str) ]
  return []


def collect(doc_path: Path, expert: str) -> dict[str, list[str]]:
  """
  Resolve the guideline paths a writer of `expert` carries while working on `doc_path`.

  Guarantees:
    - A declared guideline path that does not resolve to a file is always reported in
      `warnings`, never silently dropped.
    - Paths come back role-specific first, then the asset type's, then the wildcard set, with
      a path already listed never repeated.

  Args:
    doc_path: Absolute path to the document under review.
    expert: The dispatched expert's composed key; its role part selects the role guidelines.

  Returns:
    A map with `paths` — repo-relative paths of every declared guideline that resolves to a
    file, in the order the guarantee states — and `warnings` naming every declared path that
    does not. Both empty outside a registered product.
  """

  # Contract:
  # A declared guideline path that does not resolve to a file is never silently dropped; it is
  # always reported back in `warnings` for the coordinator to log.

  # Contract:
  # Paths MUST come back role-specific first, then the asset type's own, then the wildcard set,
  # with a path already listed never repeated.

  # Domain(review.dispatch):
  # # Guidelines context for a review writer
  # A writer dispatched on a document inside a registered product follows the guidelines the
  # product declares for the role it is playing, then the guidelines that belong to the kind
  # of asset the document describes whatever the role — a content record's schema reaches
  # its designer and its data writer alike — and finally the guidelines that apply to every
  # role. Enclosing products contribute theirs before the owning product's own, and the
  # catalog-wide set comes before all of them.

  # the settings file above the document is the only record of products and their guidelines
  settings_root = decisions_context.find_settings_root(doc_path.parent)

  # guard: no settings file above the document — nothing declares a guideline for it
  if settings_root is None:
    return { PATHS_KEY: [], WARNINGS_KEY: [] }

  # Decision: read the settings file directly rather than subprocessing the specs CLI — plain
  # data read, not a call into another plugin's code (dev.plugin-boundaries.md § 1 governs the latter)

  # parse the settings JSON; a missing or malformed file declares nothing
  try:
    data = json.loads((settings_root / _SETTINGS_REL).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return { PATHS_KEY: [], WARNINGS_KEY: [] }

  # the content root mirrors spec_paths.spec_content_root: settings_root / vault_root, default "specs"
  spec_cfg = data.get(_SPEC_SECTION_KEY)
  spec_cfg = spec_cfg if isinstance(spec_cfg, dict) else {}
  vault_root = spec_cfg.get(_VAULT_ROOT_KEY)
  content_root = settings_root / (vault_root if isinstance(vault_root, str) and vault_root else _DEFAULT_VAULT_ROOT)

  # every product whose root covers the document, outermost first, is a layer of guidelines
  chain = _build_product_chain(data, content_root, doc_path.parent)

  # guard: no registered product covers the document — no guidelines reach it
  if not chain:
    return { PATHS_KEY: [], WARNINGS_KEY: [] }

  # the catalog-wide layer stands before every product's own, outermost first after it
  raw_layers = [ spec_cfg.get(_GUIDELINES_KEY), *(record.get(_GUIDELINES_KEY) for record in chain) ]
  layers: list[dict] = [ layer for layer in raw_layers if isinstance(layer, dict) ]
  declared = (
      _collect_role_paths(layers, role_of(expert))
      + _collect_type_paths(chain, _read_asset_type(doc_path))
      + _collect_role_paths(layers, _WILDCARD_ROLE)
  )

  # a path that doesn't resolve is a warning, never a silent drop
  paths: list[str] = []
  warnings: list[str] = []
  for rel in dict.fromkeys(declared):
    if (settings_root / rel).is_file():
      paths.append(rel)
    else:
      warnings.append(f"guideline not found: {rel}")
  return { PATHS_KEY: paths, WARNINGS_KEY: warnings }
