"""Resolve the decisions-registry context files for a body-writer dispatch.

Per `spec-decisions-design.md` § "How decisions are read", a document under review that lives
inside a spec asset folder gets its asset's and owning product's `decisions.md` registries
staged into the writer's `context/`, renamed at staging as `decisions-asset.md` /
`decisions-product.md` — the two files share a basename on disk, so a same-named guideline file
could otherwise collide with either of them.

Only a main or barrier (`validation` / `terminal`) writer dispatch calls this — never
`doc_doctor`'s repair dispatch, which repairs structure and has no use for content decisions.
The coordinator (`lazy-review.coordination-playbook.md` Chapter 4) reaches this module through
the `decisions-context` CLI verb, never by importing it directly — this plugin's own writer
dispatch is prose the coordinator persona carries out via `Bash`, not Python code.

Resolution is purely structural: an asset folder carries its own status folder-note
(`<dir>/<dir.name>.md` with `spec_role: status`), and its owning product's `decisions.md` sits
at the asset folder's grandparent — `<spec_path>/<category>/<slug>/`, the fixed nesting
`lazy-spec.layout-protocol` documents for every asset. A document that sits directly at a product's
own root (`design.md` / `tech.md` at `<spec_path>/`, no asset-level status note to key off) has
no such structural marker of its own, so that case reads `.claude/lazy.settings.json`'s
`spec.vault_root` and `products` map directly.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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
import frontmatter as _fm  # noqa: E402


_DECISIONS_FILENAME = "decisions.md"
_SPEC_ROLE_KEY = "spec_role"
_STATUS_ROLE = "status"

_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION_KEY = "spec"
_VAULT_ROOT_KEY = "vault_root"
_DEFAULT_VAULT_ROOT = "specs"
_PRODUCTS_KEY = "products"
_SPEC_PATH_KEY = "spec_path"

ASSET_CONTEXT_KEY = "decisions-asset.md"
PRODUCT_CONTEXT_KEY = "decisions-product.md"


def _resolve_asset_dir(doc_path: Path) -> Path | None:
  """
  Resolve `doc_path`'s owning spec-asset folder, when it has one.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    `doc_path`'s parent folder, when that folder carries its own status folder-note
    (`<dir>/<dir.name>.md` with `spec_role: status`); `None` when the sibling note is absent,
    unreadable, or carries a different role.
  """
  asset_dir = doc_path.parent
  status_note = asset_dir / f"{asset_dir.name}.md"
  # guard: no sibling status note at all — doc_path is not inside a spec asset folder
  if not status_note.is_file():
    return None
  try:
    meta, _body = _fm.parse(status_note.read_text())
  except OSError:
    return None
  return asset_dir if meta.get(_SPEC_ROLE_KEY) == _STATUS_ROLE else None


def _find_settings_root(start: Path) -> Path | None:
  """
  Walk up from `start` to the nearest dir holding `.claude/lazy.settings.json`.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The first ancestor (inclusive) carrying the settings file, or `None` when no ancestor does.
  """
  for candidate in (start, *start.parents):
    if (candidate / _SETTINGS_REL).is_file():
      return candidate
  return None


def _resolve_product_root(doc_path: Path) -> Path | None:
  """
  Resolve `doc_path`'s owning product's spec-content root, when `doc_path` sits directly there.

  Covers the product-level document case (`design.md` / `tech.md` at `<spec_path>/`), which
  carries no asset-level status note to key off — the settings' `products` map is the only
  record of which directory is a genuine product root.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    `doc_path`'s own parent directory, when it equals a registered product's `spec_path`
    resolved under the settings' spec content root; `None` otherwise (including when no
    `.claude/lazy.settings.json`, `spec` section, or `products` map is found).
  """
  doc_dir = doc_path.parent
  settings_root = _find_settings_root(doc_dir)
  # guard: no settings file above doc_dir — nothing to resolve a product against
  if settings_root is None:
    return None

  # Decision: read the settings file directly rather than subprocessing the specs CLI — plain
  # data read, not a call into another plugin's code (dev.plugin-boundaries.md § 1 governs the latter)

  # parse the settings JSON; a missing or malformed file resolves to no product
  try:
    data = json.loads((settings_root / _SETTINGS_REL).read_text())
  except (OSError, json.JSONDecodeError):
    return None

  # the content root mirrors spec_paths.spec_content_root: settings_root / vault_root, default "specs"
  spec_cfg = data.get(_SPEC_SECTION_KEY)
  vault_root = spec_cfg.get(_VAULT_ROOT_KEY) if isinstance(spec_cfg, dict) else None
  content_root = settings_root / (vault_root if isinstance(vault_root, str) and vault_root else _DEFAULT_VAULT_ROOT)

  # doc_dir matches a genuine product root only when some registered spec_path resolves to it
  products = data.get(_PRODUCTS_KEY)
  # guard: no products map at all — nothing to match doc_dir against
  if not isinstance(products, dict):
    return None

  # scan every registered product for one whose spec_path resolves to doc_dir
  for record in products.values():
    # guard: a non-dict entry can carry no spec_path field to check below
    if not isinstance(record, dict):
      continue
    spec_path = record.get(_SPEC_PATH_KEY)
    if isinstance(spec_path, str) and spec_path and (content_root / spec_path) == doc_dir:
      return doc_dir
  return None


def collect(doc_path: Path) -> dict[str, str]:
  """
  Read the asset's and owning product's `decisions.md` registries for `doc_path`.

  Per `spec-decisions-design.md` § "Storage", `decisions.md` is created lazily by the first
  decision recorded into it — a missing file is normal, never a warning.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    A `{filename: text}` map carrying whichever of `decisions-asset.md` / `decisions-product.md`
    resolved to an existing file; `{}` when `doc_path` sits outside any spec asset folder AND
    outside any registered product's own root.
  """
  asset_dir = _resolve_asset_dir(doc_path)
  # an asset-level document: its own registry plus its owning product's, two levels up
  if asset_dir is not None:
    context: dict[str, str] = {}
    asset_decisions = asset_dir / _DECISIONS_FILENAME
    if asset_decisions.is_file():
      context[ASSET_CONTEXT_KEY] = asset_decisions.read_text()

    # the owning product's registry sits at the asset folder's grandparent — the fixed
    # `<spec_path>/<category>/<slug>/` nesting every spec asset uses
    product_decisions = asset_dir.parent.parent / _DECISIONS_FILENAME
    if product_decisions.is_file():
      context[PRODUCT_CONTEXT_KEY] = product_decisions.read_text()
    return context

  # no asset-level status note — doc_path may still be a product-level document sitting
  # directly at that product's own root, with no asset structure to key off at all
  product_dir = _resolve_product_root(doc_path)
  # guard: doc_path resolves to neither an asset nor a registered product's own root
  if product_dir is None:
    return {}

  # a product-root document has only the product half to resolve — no asset registry exists here
  product_decisions = product_dir / _DECISIONS_FILENAME
  return { PRODUCT_CONTEXT_KEY: product_decisions.read_text() } if product_decisions.is_file() else {}
