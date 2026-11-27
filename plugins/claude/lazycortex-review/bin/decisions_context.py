"""Resolve the decisions registries of a review document for a body-writer dispatch.

Per `spec-decisions-design.md` § "How decisions are read", a document under review that lives
inside a spec asset folder gets its asset's and owning product's `decisions.md` registries
named in the writer job's request, as repo-relative paths, the asset's first. The registries are
not copied into the job: the expert reads them from the working tree when it runs. The two
files share a basename on disk, so the order of the paths is what tells them apart.

Only a main or barrier (`validation` / `terminal`) writer dispatch uses this — never
`doc_doctor`'s repair dispatch, which repairs structure and has no use for content decisions.
The `dispatch-writer` verb (module `writer_dispatch`) calls `collect_paths` and names the
registries by path. The `decisions-context` verb prints the `{filename: text}` map of `collect`,
the registries' text under the disambiguated names `decisions-asset.md` / `decisions-product.md`,
and prints the warnings of `collect` on stderr.

The asset half is structural: an asset folder carries its own status folder-note
(`<dir>/<dir.name>.md` with `spec_role: status`). The product half reads
the settings' `spec.vault_root` and `products` map, local overlay merged on, through core's
`settings-get` verb: the owning
product is the one whose `spec_path` is the longest covering the folder, so an asset nested
inside another asset, or sitting straight at the product root, still finds its product, and a
product nested inside another resolves to the inner one. Without a registered product the legacy
`<spec_path>/<folder>/<slug>/` nesting, kept only when no product is registered, is assumed and
the product registry is read from the asset folder's grandparent.
"""
from __future__ import annotations

import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_DECISIONS_FILENAME = "decisions.md"
_SPEC_ROLE_KEY = "spec_role"
_STATUS_ROLE = "status"

_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION_KEY = "spec"
_PRODUCTS_KEY = "products"
_SPEC_PATH_KEY = "spec_path"

# The warning a refused spec content root leaves when the product registry is located without the product root,
# filled with the refusal.
_ROOT_REFUSED_TEMPLATE = "product decisions located without the product root: {error}"

ASSET_CONTEXT_KEY = "decisions-asset.md"
PRODUCT_CONTEXT_KEY = "decisions-product.md"


def resolve_asset_dir(doc_path: Path) -> Path | None:
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
    meta, _body = _fm.parse(status_note.read_text(encoding = "utf-8"))
  except OSError:
    return None
  return asset_dir if meta.get(_SPEC_ROLE_KEY) == _STATUS_ROLE else None


def find_settings_root(start: Path) -> Path | None:
  """
  Find the nearest directory from `start` upward that holds `.claude/lazy.settings.json`.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The nearest such directory, `start` included and never above the root of the checkout `start` sits in, or
    `None` when none holds the file.
  """
  # the nearest settings root within the checkout
  return _review_locator.find_nearest_dir(start, _SETTINGS_REL)


def _owning_product_root(start_dir: Path) -> Path | None:
  """
  Resolve the root of the registered product owning `start_dir`.

  The settings' `products` map is the only record of which directories are product roots; the
  owner is the product whose `spec_path` resolves to `start_dir` itself or to an ancestor of it,
  the longest such when products nest.

  Args:
    start_dir: Absolute directory to attribute — an asset folder, or a document's own folder.

  Returns:
    The owning product's root directory (`<content-root>/<spec_path>`); `None` when no
    registered product covers `start_dir` (including when no `.claude/lazy.settings.json`,
    `spec` section, or `products` map is found, or the settings cannot be read).

  Raises:
    SettingsReadError: When the merged `spec.vault_root` is refused, so no product root can be known.
  """
  settings_root = find_settings_root(start_dir)

  # guard: no settings file above start_dir — nothing to resolve a product against
  if settings_root is None:
    return None

  # guard: the merged `spec` and `products` sections; an unreadable settings layer resolves to no product
  try:
    data = _core_settings.read_merged_sections(settings_root, _SPEC_SECTION_KEY, _PRODUCTS_KEY)
  except SettingsReadError:
    return None

  # the spec content root the product paths resolve under; a refused root reaches the caller, which reports it
  content_root = _core_settings.spec_content_root(settings_root, data.get(_SPEC_SECTION_KEY))

  # a directory is owned only by a product whose registered spec_path resolves onto or above it
  products = data.get(_PRODUCTS_KEY)

  # guard: no products map at all — nothing to match start_dir against
  if not isinstance(products, dict):
    return None

  # scan every registered product; the deepest covering root wins when products nest
  best: Path | None = None
  for record in products.values():
    # guard: a non-dict entry can carry no spec_path field to check below
    if not isinstance(record, dict):
      continue

    # guard: only a non-empty spec_path names a product root
    if not isinstance(spec_path := record.get(_SPEC_PATH_KEY), str) or not spec_path:
      continue
    candidate = content_root / spec_path

    # guard: this product's root neither is start_dir nor sits above it
    if candidate != start_dir and candidate not in start_dir.parents:
      continue
    if best is None or len(candidate.parts) > len(best.parts):
      best = candidate
  return best


def collect(doc_path: Path) -> tuple[dict[str, str], list[str]]:
  """
  Read the asset's and owning product's `decisions.md` registries for `doc_path`.

  Per `spec-decisions-design.md` § "Storage", `decisions.md` is created lazily by the first
  decision recorded into it — a missing file is normal, never a warning.

  Guarantees:
    - A refused spec content root always yields exactly one warning in the returned warnings.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    A `{filename: text}` map carrying whichever of `decisions-asset.md` / `decisions-product.md`
    resolved to an existing file; `{}` when `doc_path` sits outside any spec asset folder AND
    outside any registered product's own root. Paired with the warnings to report, one when a refused
    spec content root left the product root unknown.
  """

  # Contract:
  # A refused spec content root MUST always yield exactly one warning in the returned warnings and is never
  # silently dropped: the caller reports it, since the product registry could not be located without it.

  # Domain(review.dispatch):
  # # Decisions context for a review writer
  # A document under review that lives inside a spec asset folder receives its own asset's
  # decision registry and its owning product's decision registry together as writer context,
  # so a writer proposing a change can see both what was already decided for this asset and
  # what its product has already settled. A document that sits directly at a product's own
  # root, with no enclosing asset, receives only the product's registry. A registry that has
  # not yet had a decision recorded into it is absent by design, never an error condition.

  # each resolved registry is read whole, under the name that tells the two apart, beside the warnings to report
  registries, warnings = _resolve_registries(doc_path)
  return { key: path.read_text(encoding = "utf-8") for key, path in registries }, warnings


def collect_paths(repo: Path, doc_path: Path) -> tuple[list[str], list[str]]:
  """
  Name the asset's and owning product's `decisions.md` registries for `doc_path` by repository path.

  Per `spec-decisions-design.md` § "Storage", `decisions.md` is created lazily by the first
  decision recorded into it — a missing file is normal, never a warning.

  Guarantees:
    - The asset's own registry comes before the owning product's.
    - A refused spec content root always yields exactly one warning in the returned warnings.

  Args:
    repo: The repository root the returned paths are relative to.
    doc_path: Absolute path to the document under review.

  Returns:
    The repo-relative POSIX paths of whichever registries exist, `[]` when `doc_path` sits outside any spec
    asset folder AND outside any registered product's own root; and the warnings to report with the dispatch,
    one when a refused spec content root left the product root unknown.
  """

  # Contract:
  # The asset's own registry MUST come before the owning product's: the two share a file name,
  # so the order is the only thing a reader has to tell them apart.

  # Contract:
  # A refused spec content root MUST always yield exactly one warning in the returned warnings and is never
  # silently dropped: the caller reports it, since the product registry could not be located without it.

  # the same registries `collect` reads, named by where they sit in the repository
  registries, warnings = _resolve_registries(doc_path)
  return [ path.relative_to(repo).as_posix() for _key, path in registries ], warnings


def _resolve_registries(doc_path: Path) -> tuple[list[tuple[str, Path]], list[str]]:
  """
  Resolve the decisions registries that exist for `doc_path`.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    `(name, path)` pairs for the registries that exist, the name being `decisions-asset.md` or
    `decisions-product.md`, the asset's registry first, `[]` when `doc_path` sits outside any spec asset
    folder AND outside any registered product's own root; and one warning when a refused spec content root left
    the owning product's root unknown, none otherwise.
  """
  asset_dir = resolve_asset_dir(doc_path)

  # the owning product's root, attributed from the asset folder, else the document's own folder; a refused content
  # root leaves it unknown and is reported, never silently dropped
  warnings: list[str] = []
  try:
    owner_root = _owning_product_root(asset_dir if asset_dir is not None else doc_path.parent)
  except SettingsReadError as error:
    owner_root = None
    warnings.append(_ROOT_REFUSED_TEMPLATE.format(error = error))

  # an asset-level document: its own registry plus its owning product's
  if asset_dir is not None:
    # the owning product's registry sits at the product root the settings register, however
    # deep the asset is nested below it; without a registered product the legacy
    # `<spec_path>/<folder>/<slug>/` nesting, kept only when no product is registered, puts it
    # at the asset folder's grandparent
    product_root = owner_root or asset_dir.parent.parent
    candidates = [
        ( ASSET_CONTEXT_KEY, asset_dir / _DECISIONS_FILENAME ),
        ( PRODUCT_CONTEXT_KEY, product_root / _DECISIONS_FILENAME ),
    ]
    return [ ( key, path ) for key, path in candidates if path.is_file() ], warnings

  # guard: no asset-level status note, and doc_path is not a product-level document sitting directly at a
  # registered product's own root either
  if owner_root is None or owner_root != doc_path.parent:
    return [], warnings

  # a product-root document has only the product half to resolve — no asset registry exists here
  product_decisions = owner_root / _DECISIONS_FILENAME
  return ( [ ( PRODUCT_CONTEXT_KEY, product_decisions ) ] if product_decisions.is_file() else [] ), warnings
