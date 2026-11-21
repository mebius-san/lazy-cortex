"""
Product-config resolver primitives — read products from settings.

Product config lives in `lazy.settings.json[products]` at
`<vault>/.claude/lazy.settings.json`. The `_version` key carries the
section schema version and is not a product record. Each remaining key
is a product whose record holds at least `spec_path` (content-root-relative).

The lookups answer which product a key or a path belongs to, where that product and its assets sit on disk, and
which expert drives its release build. When products nest, the longest matching `spec_path` owns a path.

A nested product inherits its ancestors' record through
`effective_record`; `ancestor_chain` lists them outermost first. Every
nesting reader takes an optional already-loaded registry, so a caller
walking a whole chain reads the settings file once rather than per link.

The CLI exposes one verb per kind of answer and prints one JSON line. Record verbs answer with the raw registry
record or the inherited one, by key or by path; a reader that acts on a product's configuration wants the
inherited record, and only a caller that writes the record back wants the raw one.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Each role mapped to its ordered guideline paths, the shape of every `guidelines` layer.
type RoleGuidelines = dict[str, list[str]]


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_paths import (  # noqa: E402
    SettingsError, _vault_root_value, find_settings_root, read_merged_sections, read_settings, spec_content_root,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import ReleaseConfigKey  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import gate_dispatch  # noqa: E402


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_VERSION_KEY = "_version"
_PRODUCTS_SECTION = "products"
_SPEC_SECTION = "spec"
_SPEC_PATH_KEY = "spec_path"
_MODE_BY_KEY = "by-key"
_MODE_BY_PATH = "by-path"
_MODE_EFFECTIVE = "effective"
_MODE_EFFECTIVE_BY_PATH = "effective-by-path"
_MODE_ANCESTOR_CHAIN = "ancestor-chain"
_MODE_OWN_SOURCE_CONFLICTS = "own-source-conflicts"
_MODE_RELEASE_IMPLEMENTER = "release-implementer"
_MODE_SPECIALISTS = "specialists"
_MODE_SPECIALISTS_BY_PATH = "specialists-by-path"
_EXPERTS_SECTION = "experts"
_AGENT_KEY = "agent"
_EXPERT_KEY_SEP = "."
_ENCODING = "utf-8"

# The shipped role-to-material map and the fields of one specialist entry
_SPECIALIST_ROLES_PATH = _BIN.parent / "references" / "lazy-spec.specialist-roles.json"
_SPECIALIST_ROLES_KEY = "specialist_roles"
_FIELD_ROLE = "role"
_FIELD_EXPERT = "expert"
_FIELD_AGENT = "agent"
_FIELD_ASPECTS = "aspects"
_FIELD_MATERIAL = "material"
_FIELD_GUIDELINES = "guidelines"
_FIELD_ORIGIN = "origin"
_ORIGIN_DERIVED = "derived"
_ORIGIN_SPEC = "spec"
_ORIGIN_PRODUCT = "product"
_ANSWER_KEY = "key"
_ANSWER_SPECIALISTS = "specialists"
_ANSWER_IMPLEMENTER = "implementer"
_ANSWER_WARNINGS = "warnings"
_ANSWER_ERROR = "error"
_IMPLEMENTER_CHAIN_KEY = "implementer_chain"
_ASSET_TYPES_KEY = "asset_types"
_GUIDELINES_KEY = "guidelines"
# The settings sections a release build is ordered from, read as the runtime dispatches from them
_RUNTIME_SECTIONS = ( _PRODUCTS_SECTION, _EXPERTS_SECTION, _SPEC_SECTION )

# Keys a nested product never takes from an ancestor — a code binding, a dependency list and a
# paint belong to one product; spec_path names the product itself
_SOURCE_KEY = "source"
_PATHS_KEY = "paths"
_OWN_ONLY_KEYS = frozenset({ _SOURCE_KEY, "dependencies", "icon", "color", _SPEC_PATH_KEY })
# The normalised spellings of a source path naming the repository root, which contains every other path
_ROOT_SOURCE_PATHS = frozenset({ ".", "" })


def load_products(vault: Path) -> dict:
  """
  Read the `products` section from the vault's `lazy.settings.json`.

  Excludes the section's own schema-version entry, so the result maps product keys to
  records only.

  Guarantees:
    - A settings file that exists but is not valid JSON, not UTF-8 text or not a JSON object raises `ValueError`
      naming the file; it never reads as an empty registry.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    A dict of product key to record; empty when the settings file or the
    `products` section is absent.

  Raises:
    ValueError: If the settings file exists but cannot be read, is not valid JSON, not UTF-8 text or not a JSON
      object; a `spec_paths.SettingsError` naming the file.
  """

  # Contract:
  # A settings file that exists but is not valid JSON, not UTF-8 text or not a JSON object raises `ValueError`
  # naming the file, and never reads as an empty registry; callers rely on the raise to abort before recording state.

  # Decision: the record readers parse the tracked file in process, not the merged view through the core CLI — they
  # stay dependency-light, with no import of the `lazy_settings` loader and no yaml dependency

  settings_path = vault / _SETTINGS_REL

  # guard: missing settings file means no products configured
  if not settings_path.is_file():
    return {}
  products = read_settings(settings_path).get(_PRODUCTS_SECTION)

  # guard: missing or malformed products section means no products
  if not isinstance(products, dict):
    return {}
  return { k: v for k, v in products.items() if k != _VERSION_KEY }


def load_catalog_guidelines(vault: Path) -> RoleGuidelines:
  """
  Read the catalog-wide guidelines every product inherits, from `spec.guidelines`.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    A dict of role to its ordered guideline paths; empty when the settings file, the `spec`
    section or its `guidelines` key is absent. A role whose value is not a list is left out.

  Raises:
    ValueError: If the settings file exists but cannot be read, is not valid JSON, not UTF-8 text or not a JSON
      object; a `spec_paths.SettingsError` naming the file.
  """
  settings_path = vault / _SETTINGS_REL

  # guard: missing settings file means no catalog guidelines
  if not settings_path.is_file():
    return {}
  return build_catalog_guidelines(read_settings(settings_path))


def build_catalog_guidelines(settings: dict) -> RoleGuidelines:
  """
  Take the catalog-wide guidelines every product inherits from already-parsed settings.

  Args:
    settings: The parsed settings file.

  Returns:
    A dict of role to its ordered guideline paths; empty when the `spec` section or its `guidelines` key is
    absent. A role whose value is not a list is left out.
  """
  spec = settings.get(_SPEC_SECTION)
  declared = spec.get(_GUIDELINES_KEY) if isinstance(spec, dict) else None

  # guard: missing or malformed guidelines key means none are declared
  if not isinstance(declared, dict):
    return {}
  return { role: list(paths) for role, paths in declared.items() if isinstance(paths, list) }


def _registry(vault: Path, products: dict | None) -> dict:
  """
  Return the products registry a reader should work against.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    products: An already-loaded registry, or None to read one from the settings file.

  Returns:
    The caller's registry when it gave one, otherwise the vault's own.
  """
  # a caller walking a whole chain loads the registry once and hands it down
  if products is not None:
    return products
  return load_products(vault)


def _is_path_prefix(spec_segments: list[str], doc_segments: list[str]) -> bool:
  """
  Return True when `spec_segments` is a segment-wise prefix of `doc_segments`.

  Comparison is on whole path segments, so `A/B` matches `A/B/x` but not
  `A/Bx/...`.

  Args:
    spec_segments: Segments of a product's `spec_path`.
    doc_segments: Segments of the doc path under test.

  Returns:
    True when every spec segment matches the leading doc segments in order.
  """
  # guard: a longer spec path cannot prefix a shorter doc path
  if len(spec_segments) > len(doc_segments):
    return False
  return doc_segments[:len(spec_segments)] == spec_segments


def resolve_product_by_key(vault: Path, key: str) -> dict | None:
  """
  Fetch a single product record by its exact key.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: Product key to look up.

  Returns:
    The product record, or None when no product carries that key.
  """
  return load_products(vault).get(key)


def resolve_product_by_path(vault: Path, rel_path: str, *,
                            products: dict | None = None) -> tuple[str | None, dict | None]:
  """
  Find the product owning a content-root-relative or repo-relative doc path.

  A product owns the path when its `spec_path` equals the path or is a
  segment-wise prefix of it. When several products nest, the one with the
  longest matching `spec_path` wins.

  Guarantees:
    - When several configured products' `spec_path` values nest, the returned product is always
      the one with the longest matching `spec_path`, never a shorter enclosing ancestor.
    - With `products` given, the products registry is not re-read from the settings file; the answer is the
      one the same registry on disk would have produced, and the vault-root segment is still read from the
      settings file.
    - A path with a leading vault-root segment is accepted repo-relative or content-root-relative and
      attributed to the same product either way; the reading present on disk wins, else the one a
      product claims more deeply, and on a tie the leading segment is dropped.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    rel_path: Doc path to attribute to a product, relative to the content-root or to the
      settings root (leading vault-root segment); when the leading segment allows both readings,
      the one present on disk wins, else the one a product claims more deeply.
    products: An already-loaded products registry used instead of re-reading it from the settings file;
      None reads the registry from the settings file.

  Returns:
    A `(key, record)` pair for the longest-matching product, or `(None, None)`
    when no product's `spec_path` matches.
  """

  # Contract:
  # When several configured products' spec_path values nest, the returned product is always the
  # one with the longest matching spec_path, never a shorter enclosing ancestor.
  # With `products` given, the products registry is not re-read from the settings file and the
  # answer is the same one that registry would have produced from disk; the vault-root segment
  # is still read from the settings file.

  # Contract:
  # A path whose leading segment is the vault root's own name is accepted in either form,
  # repo-relative or content-root-relative, and attributed to the same product either way.
  # When the leading segment allows both readings, the one present on disk wins, else the one
  # a product claims more deeply, and on a tie the leading segment is dropped.

  # Domain(spec.config):
  # # Nested products resolve by longest owning path
  # A document belongs to whichever configured product's own tree contains it, matched on
  # whole path segments rather than raw text, so a product named one thing never accidentally
  # claims a document that merely starts with the same letters under a differently named
  # sibling. When one product's tree sits nested inside another's, the more specific,
  # longer-matching tree wins, so a sub-product's own documents are never mistakenly
  # attributed to the broader product that just happens to contain it.

  # Domain(spec.config):
  # # A leading vault-root segment reads two ways
  # A document path whose first segment equals the vault root's own name is ambiguous. It can be
  # relative to the repository, where that segment is the vault root and is dropped, or relative
  # to the content-root, where a product's own tree path itself begins with that name (a product
  # under the `specs/` root whose tree is `specs/assets`, for instance). The reading whose file
  # exists on disk wins. When neither or both exist, the reading that some product claims more
  # deeply wins, and on a tie the segment is dropped.

  registry = _registry(vault, products)
  vroot = _vault_root_value(vault)
  parts = list(Path(rel_path).parts)

  # no leading vault-root segment — one reading only
  if not parts or parts[0] != vroot:
    return _find_longest_match(registry, parts)[:2]

  # a leading vault-root segment reads two ways: repo-relative (drop it) or content-root-relative
  # (keep it, a product whose spec_path starts with the vault root's own name); the one on disk wins
  stripped = parts[1:]
  as_repo = (vault / rel_path).exists()
  if as_repo != (vault / vroot / rel_path).exists():
    return _find_longest_match(registry, stripped if as_repo else parts)[:2]

  # neither or both on disk: the reading a product claims more deeply wins, a tie drops the segment
  kept = _find_longest_match(registry, parts)
  dropped = _find_longest_match(registry, stripped)
  return kept[:2] if kept[2] > dropped[2] else dropped[:2]


def _find_longest_match(registry: dict, doc_segments: list[str]) -> tuple[str | None, dict | None, int]:
  """
  Find the registered product with the longest `spec_path` owning the given path segments.

  Args:
    registry: The products registry.
    doc_segments: Content-root-relative segments of the doc path.

  Returns:
    A `(key, record, spec_path_length)` triple; `(None, None, -1)` when no product owns the path.
  """
  best_key: str | None = None
  best_record: dict | None = None
  best_len = -1
  for key, record in registry.items():
    spec_path = record.get(_SPEC_PATH_KEY) if isinstance(record, dict) else None

    # guard: skip records without a usable spec_path
    if not isinstance(spec_path, str) or not spec_path:
      continue
    spec_segments = Path(spec_path).parts

    # only a product whose spec_path owns this doc path competes for the longest match
    if not _is_path_prefix(list(spec_segments), doc_segments):
      continue
    if len(spec_segments) > best_len:
      best_len = len(spec_segments)
      best_key = key
      best_record = record
  return best_key, best_record, best_len


def ancestor_chain(vault: Path, key: str, *, products: dict | None = None) -> list[str]:
  """
  List the registered products enclosing `key`'s own tree, outermost first.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    Ancestor keys from the outermost enclosing product down to the nearest one; empty for a
    top-level product, an unknown key, or a product whose only enclosing record shares its
    exact `spec_path`.
  """
  registry = _registry(vault, products)
  own = registry.get(key)

  # guard: an unknown key, or a record without a usable spec_path, has no tree to be enclosed
  if not isinstance(own, dict) or not isinstance(own.get(_SPEC_PATH_KEY), str) or not own[_SPEC_PATH_KEY]:
    return []
  own_segments = list(Path(own[_SPEC_PATH_KEY]).parts)

  # one ancestor key per distinct enclosing spec_path — a twin registration sharing an ancestor's
  # exact path is the same tree level, not a second entry, and the first-registered key stands
  # for it (the same tie-break `resolve_product_by_path` applies to equal-length matches)
  by_path: dict[tuple[str, ...], str] = {}
  for other_key, record in registry.items():
    # guard: the product itself, or a malformed record, never encloses anything
    if other_key == key or not isinstance(record, dict):
      continue
    spec_path = record.get(_SPEC_PATH_KEY)

    # guard: a record without a usable spec_path cannot enclose anything
    if not isinstance(spec_path, str) or not spec_path:
      continue
    segments = tuple(Path(spec_path).parts)

    # a proper prefix only — an equal path is a twin registration, not a parent
    if len(segments) < len(own_segments) and _is_path_prefix(list(segments), own_segments):
      by_path.setdefault(segments, other_key)
  return [ by_path[segments] for segments in sorted(by_path, key = len) ]


def child_keys(vault: Path, key: str, *, products: dict | None = None) -> list[str]:
  """
  List the registered products `key` directly encloses — the inverse of `ancestor_chain`.

  Membership is by nearest ancestor, never by mere containment: a twice-nested product belongs
  to the product immediately above it, so it never appears in its grandparent's list.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    The child keys, sorted; empty for a product nothing is nested inside, for an unknown key,
    and for a twin registration sharing another product's exact `spec_path`.
  """
  registry = _registry(vault, products)

  # guard: an unknown key, or a malformed record, encloses nothing
  if not isinstance(registry.get(key), dict):
    return []
  children = []
  for other_key, record in registry.items():
    # guard: a product is never its own child, and a malformed record names no tree
    if other_key == key or not isinstance(record, dict):
      continue

    # the registry is resolved once above and handed down, so a chain per product costs no read
    chain = ancestor_chain(vault, other_key, products = registry)

    # the chain's last link is the nearest enclosing product — an outer one makes this a
    # grandchild, which belongs to the product between them rather than to this one
    if chain and chain[-1] == key:
      children.append(other_key)
  return sorted(children)


def _has_own_source(record: object) -> bool:
  """
  Tell whether a product record declares a code source of its own.

  Args:
    record: The raw product record.

  Returns:
    True when the record carries a non-empty `source` object.
  """
  return isinstance(record, dict) and isinstance(record.get(_SOURCE_KEY), dict) and bool(record[_SOURCE_KEY])


def find_release_owner_key(vault: Path, key: str, *, products: dict | None = None) -> str | None:
  """
  Find the product that owns the releases an asset of `key` ships in.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    products: An already-read products registry; None reads the merged one the expert runtime dispatches from, the
      local overlay merged on.

  Returns:
    The outermost key in the chain from the outermost ancestor down to `key` whose record declares a `source` of
    its own, or None when no product in that chain does — a design-only umbrella and its nested design-only
    products own no releases.

  Raises:
    ValueError: If `products` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """

  # Domain(spec.lifecycle):
  # # Releases belong to the product that owns the code
  # A release is a version of one deployable, so it belongs to the outermost product whose record
  # names the code it is built from. A product nested inside such an owner is an area of the same
  # deployable whether or not it names code of its own: naming code inside the owner's code only
  # narrows the area it is checked against, its assets ship in the owner's releases and it keeps
  # no releases itself. A product that names no code and sits under no owner is a design-only
  # umbrella, and the products under it that do name code each own their own releases.

  # the registry passed in, else the one the runtime dispatches from, so the owner comes from the same view as the
  # release's specialists
  registry = products if products is not None else read_runtime_products(vault)

  # the chain from the outermost ancestor down to the product itself, outermost first
  for candidate in [ *ancestor_chain(vault, key, products = registry), key ]:
    if _has_own_source(registry.get(candidate)):
      return candidate
  return None


def find_release_implementer(vault: Path, key: str, *, settings: dict | None = None) -> str | None:
  """
  Find the expert that drives a release build of a product.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    settings: The parsed settings to resolve from; None reads the merged view the expert runtime dispatches from.

  Returns:
    The product's explicit `release.implementer`, else the first registered expert of the product's
    `release.implementer_chain` — or, when the product declares no chain, of the repository's
    `spec.release.implementer_chain`; None when no expert resolves, which includes a `settings` of None with no
    settings file and no overlay in the vault.

  Raises:
    ValueError: If `settings` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """

  # Domain(spec.lifecycle):
  # # Who drives a release build
  # One expert drives a release build. A product that names its implementer explicitly gets that expert, and
  # the operator's word is final: no fallback list is consulted. Otherwise the choice falls to an ordered
  # fallback list, and the first expert on it that is actually registered wins; an entry nobody has
  # registered is passed over, not treated as an error. A product that declares a fallback list of its own
  # replaces the repository-wide list entirely and never extends it, so a product can narrow the candidates
  # without inheriting the repository's, and an empty list of its own means no fallback at all. When nothing
  # on the applicable list is registered there is no implementer, and the release has no expert to build it.

  # guard: no settings passed in — read them as the runtime sees them: the product record, the repository chain and
  # the expert registry alike, the local overlay merged on
  if settings is None:
    settings = read_runtime_settings(vault)

  # the product's own release record, empty when it declares none
  release = ((settings.get(_PRODUCTS_SECTION) or {}).get(key) or {}).get(ReleaseConfigKey.SECTION) or {}

  # an explicit implementer is the operator's word and wins over any chain
  if explicit := release.get(ReleaseConfigKey.IMPLEMENTER):
    return str(explicit)

  # the repository chain applies unless the product declares its own, which replaces it whole
  chain = ((settings.get(_SPEC_SECTION) or {}).get(ReleaseConfigKey.SECTION) or {}).get(_IMPLEMENTER_CHAIN_KEY) or []
  if _IMPLEMENTER_CHAIN_KEY in release:
    chain = release[_IMPLEMENTER_CHAIN_KEY] or []

  # the first chain entry the expert registry knows is the implementer
  return next(( name for name in chain if name in (settings.get(_EXPERTS_SECTION) or {}) ), None)


class SpecialistsError(ValueError):
  """
  Failure to build a product's specialist list from the settings.

  Signals missing or malformed information, so a caller never mistakes it for an empty list.

  Attributes:
    key: The product key the failure concerns, or None when no product covers the asked path.
  """

  def __init__(self, message: str, *, key: str | None) -> None:
    """
    Record the failure message and the product it concerns.

    Args:
      message: What is missing or malformed, naming the role or expert at fault.
      key: The product key the failure concerns, or None when no product covers the asked path.
    """
    # the message is the exception's own text
    super().__init__(message)

    # the product the failure concerns, printed back by the CLI
    self.key = key


def load_specialist_roles() -> dict[str, dict]:
  """
  Read the plugin's shipped map of specialist roles to the material each makes.

  Guarantees:
    - The roles come back in the order the shipped map declares them.

  Returns:
    Role to `{ "material": <text> }`, in shipped order; empty when the shipped map declares no roles.

  Raises:
    OSError: If the shipped map cannot be read.
    ValueError: If the shipped map is not valid JSON.
  """

  # Contract:
  # The roles come back in the order the shipped map declares them; the specialist list orders its shipped
  # roles by it.

  return json.loads(_SPECIALIST_ROLES_PATH.read_text(encoding = _ENCODING)).get(_SPECIALIST_ROLES_KEY) or {}


def read_runtime_settings(vault: Path) -> dict:
  """
  Read the settings a release build is ordered from, as the runtime dispatches from them.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    The `products`, `experts` and `spec` sections, each with the local overlay merged on.

  Raises:
    ValueError: If the merged settings cannot be read; a `spec_paths.SettingsError` naming the settings file, also
      when no core CLI resolves.
  """
  # the expert runtime dispatches from the merged view, so an expert or product declared only in the overlay counts
  return read_merged_sections(vault, *_RUNTIME_SECTIONS)


def read_runtime_products(vault: Path) -> dict:
  """
  Read the products registry as the runtime dispatches from it.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    Product key to record, with the local overlay merged on and without the section's schema-version entry.

  Raises:
    ValueError: If the merged settings cannot be read; a `spec_paths.SettingsError` naming the settings file, also
      when no core CLI resolves.
  """
  # one release is looked up in the view its experts are dispatched from, so an overlay-only product counts
  return filter_products(read_merged_sections(vault, _PRODUCTS_SECTION))


def read_runtime_catalog(vault: Path) -> tuple[dict, RoleGuidelines]:
  """
  Read the products registry and the catalog-wide guidelines as the runtime dispatches from them.

  Guarantees:
    - The registry and the guidelines come from one merged view of the settings, the local overlay merged on.
    - Merged settings that cannot be read raise `ValueError`; they are never answered as an empty registry or
      empty guidelines.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    The products registry, product key to record without the section's schema-version entry, and the catalog-wide
    `spec.guidelines` by role; both with the local overlay merged on.

  Raises:
    ValueError: If the merged settings cannot be read; a `spec_paths.SettingsError` naming the settings file, also
      when no core CLI resolves.
  """

  # Contract:
  # The registry and the catalog-wide guidelines MUST come from one merged view of the settings, the local overlay
  # merged on, so a caller holding the registry never gets guidelines from another view.

  # Contract:
  # Merged settings that cannot be read MUST raise `ValueError` naming the settings file. They are never answered
  # as an empty registry or empty guidelines: callers that scaffold from the pair rely on the raise to abort.

  # one merged read of both sections, so a caller holding the registry never reads the guidelines from another view
  settings = read_merged_sections(vault, _PRODUCTS_SECTION, _SPEC_SECTION)
  return filter_products(settings), build_catalog_guidelines(settings)


def filter_products(settings: dict) -> dict:
  """
  Take the products registry out of already-read settings.

  Args:
    settings: Settings holding a `products` section.

  Returns:
    Product key to record, without the section's schema-version entry.
  """
  return { k: v for k, v in (settings.get(_PRODUCTS_SECTION) or {}).items() if k != _VERSION_KEY }


def _split_expert_key(expert: str) -> tuple[str, str]:
  """
  Split an expert key into its domain and its role.

  Args:
    expert: A registered expert key, `<domain>.<role>`.

  Returns:
    The part before the first dot and the part after it; the whole key as the role when it carries no dot.
  """
  domain, _sep, role = expert.partition(_EXPERT_KEY_SEP)
  return domain, role or expert


def _parse_overrides(release: object, key: str) -> dict:
  """
  Read the per-role specialist overrides of one settings level.

  Args:
    release: The level's `release` section, as found in the settings.
    key: The product key the list is built for, named in a failure.

  Returns:
    Role to its override entry; `{}` when the level declares none.

  Raises:
    SpecialistsError: If the level's `specialists` value is not an object.
  """
  declared = release.get(ReleaseConfigKey.SPECIALISTS) if isinstance(release, dict) else None

  # guard: a level that declares no overrides changes nothing
  if declared is None:
    return {}

  # guard: an override set that is not an object is missing information, never an empty set
  if not isinstance(declared, dict):
    raise SpecialistsError(f"release.specialists must be an object, got {declared!r}", key = key)
  return declared


def _build_override_entry(role: str,
                          entry: object,
                          origin: str,
                          *,
                          shipped: dict,
                          experts: dict,
                          key: str) -> dict | None:
  """
  Validate one override entry and turn it into a specialist entry.

  Args:
    role: The role the entry overrides or adds.
    entry: The declared value — an object with `expert` and `material`, or `false`.
    origin: The settings level that declared it.
    shipped: The shipped role-to-material map.
    experts: The registered experts.
    key: The product key the list is built for, named in a failure.

  Returns:
    The entry's expert, material and origin; None when the entry switches the role off.

  Raises:
    SpecialistsError: If the entry is malformed, names no registered expert, or adds a role with no material.
  """

  # `false` is the documented way to switch the role off
  if entry is False:
    return None

  # guard: anything but an object naming an expert is malformed
  if not isinstance(entry, dict) or not isinstance(entry.get(_FIELD_EXPERT), str):
    raise SpecialistsError(f"{origin} specialist '{role}' needs an object with a string 'expert' or false, "
                           f"got {entry!r}", key = key)

  # the expert the entry names
  expert = entry[_FIELD_EXPERT]

  # guard: an expert the registry does not know cannot be launched
  if expert not in experts:
    raise SpecialistsError(f"{origin} specialist '{role}' names expert '{expert}', which is not registered",
                           key = key)

  # a shipped role may leave the material to the shipped text; a new role must state it
  material = entry.get(_FIELD_MATERIAL, (shipped.get(role) or {}).get(_FIELD_MATERIAL))

  # guard: an entry with no material, its own or shipped, cannot be ordered
  if not isinstance(material, str) or not material:
    raise SpecialistsError(f"{origin} specialist '{role}' has no material", key = key)
  return { _FIELD_EXPERT: expert, _FIELD_MATERIAL: material, _FIELD_ORIGIN: origin }


def _pick_expert(role: str,
                 candidates: list[str],
                 *,
                 implementer_domain: str | None,
                 key: str) -> str:
  """
  Choose the one registered expert that fills a derived role.

  Args:
    role: The derived role.
    candidates: Every registered expert holding that role.
    implementer_domain: The domain of the product's release implementer, or None when it has none.
    key: The product key the list is built for, named in a failure.

  Returns:
    The single candidate, or the one candidate sharing the implementer's domain.

  Raises:
    SpecialistsError: If several candidates hold the role and not exactly one shares the implementer's domain.
  """

  # one holder of the role is the answer; several are told apart by the implementer's domain
  if len(candidates) == 1:
    return candidates[0]
  same_domain = [ expert for expert in candidates if _split_expert_key(expert)[0] == implementer_domain ]

  # guard: none or several in the implementer's domain is a conflict only the operator settles
  if len(same_domain) != 1:
    raise SpecialistsError(
        f"role '{role}' is held by experts {', '.join(candidates)} and the release implementer's domain "
        f"'{implementer_domain}' does not pick one; name the expert in release.specialists.{role}",
        key = key,
    )
  return same_domain[0]


def build_specialists(vault: Path, key: str, *, settings: dict | None = None) -> dict:
  """
  Build a product's list of specialists from its registered experts and the settings overrides.

  The list is built afresh on every call and stored nowhere.

  Guarantees:
    - Missing or malformed information raises `SpecialistsError`; it never yields an empty or partial list.
    - With `settings` given, the answer is computed from that object alone; no settings value is read from the
      settings file.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`; guideline paths resolve against it.
    key: The product's compound-key.
    settings: The parsed settings to build from; None reads the merged view the expert runtime dispatches from.

  Returns:
    `{"key", "specialists", "warnings"}` — one entry per role with its expert, agent, aspects, material,
    guideline paths and origin, in shipped-role order and then added roles alphabetically; aspects are the
    expert's registered reference keys copied verbatim into a fresh list, empty when it has none; warnings name
    declared guideline paths with no file, each once.

  Raises:
    SpecialistsError: If the key is unknown, an override is malformed, names an unregistered expert or adds a
      role without material, a derived role is held ambiguously, a listed expert has no agent, or a listed
      expert's aspects are not a list of strings.
    ValueError: If `settings` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """

  # Contract:
  # Missing or malformed information raises `SpecialistsError`; the call never returns an empty or partial
  # list, so a caller can tell a failed build from a product that has no specialists.

  # Contract:
  # With `settings` given, the answer is computed from that object alone; no settings value is read from the
  # settings file, so a caller holding unsaved or already-parsed settings gets an answer that matches them.

  # Domain(spec.lifecycle):
  # # Who a release build orders material from
  # A release build has one implementer; every other registered expert whose role the plugin knows
  # a material for is a specialist the implementer may order that material from. The list is
  # derived afresh on every request and stored nowhere, and a request by document path is answered
  # for the product that owns the releases that document ships in. The implementer's own role drops
  # out of it. When two experts hold one role, the one in the implementer's own domain is taken;
  # when none or several are, the list fails and names the conflict for the operator to settle.
  # The repository and then the product may override the list one role at a time: an entry
  # replaces that role's derived expert, `false` switches the role off, and a later level wins, so
  # a product can switch a role back on that the repository switched off. An entry may omit the
  # material only for a role the plugin knows; a new role must state it. Each specialist also
  # carries the agent that launches its expert, the domain craft of that expert (the aspects it
  # declares, as references) and the guidelines of its role: the role's own first, then those
  # that apply to every role. So the expert chosen by domain changes what the build hands the
  # specialist. Missing information fails the list instead of leaving a gap: an unknown product,
  # a path no product covers, a request by document path whose product owns no release (the
  # failure names that product), a malformed override, an expert nobody registered, a role with
  # no material, an expert with no agent, and domain craft declared in any shape other than a
  # list of references. Only an expert the list actually names is checked: one whose role is
  # switched off, or is the implementer's, is not.

  # guard: settings not handed in are read from the vault
  if settings is None:
    settings = read_runtime_settings(vault)

  # the settings carry the products, the experts and both override levels alike
  registry = filter_products(settings)
  record = registry.get(key)

  # guard: an unknown product has no list, and that is a failure, not an empty answer
  if not isinstance(record, dict):
    raise SpecialistsError(f"unknown product key '{key}'", key = key)

  # the registered experts and the shipped role-to-material map the list is built from
  experts = settings.get(_EXPERTS_SECTION) or {}
  shipped = load_specialist_roles()

  # the implementer's role leaves the derived list, its domain breaks a tie between two holders of one role
  implementer = find_release_implementer(vault, key, settings = settings)
  implementer_domain, implementer_role = _split_expert_key(implementer) if implementer else (None, None)
  candidates: dict[str, list[str]] = {}
  for expert in experts:
    role = _split_expert_key(expert)[1]
    if role in shipped and role != implementer_role:
      candidates.setdefault(role, []).append(expert)

  # the repository's overrides apply first, the product's over them
  chosen: dict[str, dict | None] = {}
  levels = ( (_ORIGIN_SPEC, (settings.get(_SPEC_SECTION) or {}).get(ReleaseConfigKey.SECTION)),
             (_ORIGIN_PRODUCT, record.get(ReleaseConfigKey.SECTION)) )
  for origin, release in levels:
    for role, declared in _parse_overrides(release, key).items():
      chosen[role] = _build_override_entry(role, declared, origin, shipped = shipped, experts = experts, key = key)

  # the derived roles not overridden fill in beside the overrides, shipped roles first
  entries: list[dict] = []
  for role in [ *shipped, *sorted(role for role in chosen if role not in shipped) ]:
    entry: dict | None = None
    if role in chosen:
      entry = chosen[role]
    elif role in candidates:
      entry = { _FIELD_EXPERT: _pick_expert(role, candidates[role], implementer_domain = implementer_domain,
                                            key = key),
                _FIELD_MATERIAL: shipped[role][_FIELD_MATERIAL], _FIELD_ORIGIN: _ORIGIN_DERIVED }
    if entry is not None:
      entries.append({ _FIELD_ROLE: role, **entry })

  # each entry gains the agent and aspects of its expert and the guideline paths of its role
  effective = effective_record(vault, key, products = registry,
                               catalog_guidelines = build_catalog_guidelines(settings))
  specialists: list[dict] = []
  warnings: list[str] = []
  for entry in entries:
    expert = entry[_FIELD_EXPERT]
    registration = experts.get(expert) or {}
    agent = registration.get(_AGENT_KEY)

    # guard: an expert with no agent cannot be launched, so the list cannot name it
    if not isinstance(agent, str) or not agent:
      raise SpecialistsError(f"expert '{expert}' for specialist '{entry[_FIELD_ROLE]}' has no agent", key = key)

    # the domain craft the expert declares, as reference keys
    aspects = registration.get(_FIELD_ASPECTS, [])

    # guard: aspects that are not a list of reference keys are malformed information, never an empty list
    if not isinstance(aspects, list) or not all(isinstance(aspect, str) for aspect in aspects):
      raise SpecialistsError(f"expert '{expert}' for specialist '{entry[_FIELD_ROLE]}' has aspects that are not a "
                             f"list of reference keys: {aspects!r}", key = key)

    # the role's guideline paths; a declared path with no file is warned, never listed
    paths, missing = gate_dispatch.collect_guideline_paths(vault, effective, entry[_FIELD_ROLE])
    warnings.extend(missing)
    specialists.append({ _FIELD_ROLE: entry[_FIELD_ROLE], _FIELD_EXPERT: expert, _FIELD_AGENT: agent,
                         _FIELD_ASPECTS: list(aspects), _FIELD_MATERIAL: entry[_FIELD_MATERIAL],
                         _FIELD_GUIDELINES: paths, _FIELD_ORIGIN: entry[_FIELD_ORIGIN] })

  # the list and the warnings, each warning once
  return { _ANSWER_KEY: key, _ANSWER_SPECIALISTS: specialists, _ANSWER_WARNINGS: list(dict.fromkeys(warnings)) }


def build_specialists_by_path(vault: Path, rel_path: str) -> dict:
  """
  Build the specialist list of the product that owns the releases a path ships in.

  Guarantees:
    - A path no product covers, or a product with no release owner, raises `SpecialistsError`; it never yields
      an empty or null answer.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`; the settings are read from it as the expert
      runtime dispatches from them, the local overlay merged on.
    rel_path: Doc path, content-root-relative or repo-relative as `resolve_product_by_path` reads it.

  Returns:
    The release owner's answer as `build_specialists` gives it, keyed by the owner.

  Raises:
    SpecialistsError: If no product covers the path, the product has no release owner, or the owner's list
      fails.
    ValueError: If the merged settings cannot be read; a `spec_paths.SettingsError` naming the settings file, also
      when no core CLI resolves.
  """

  # Contract:
  # A path no product covers, or a product with no release owner, raises `SpecialistsError`; the call never
  # returns an empty or null answer, so a caller can tell a failed lookup from a product with no specialists.

  settings = read_runtime_settings(vault)
  registry = filter_products(settings)
  key, _record = resolve_product_by_path(vault, rel_path, products = registry)

  # guard: a path no product covers has no list
  if key is None:
    raise SpecialistsError(f"no product covers '{rel_path}'", key = None)

  # the product that owns the releases the path ships in
  owner = find_release_owner_key(vault, key, products = registry)

  # guard: a design-only product owns no release, so no build orders material for it
  if owner is None:
    raise SpecialistsError(f"product '{key}' has no release owner", key = key)
  return build_specialists(vault, owner, settings = settings)


def _source_paths(record: object) -> list[str]:
  """
  Read a product record's source paths, each normalised.

  Args:
    record: The raw product record.

  Returns:
    The normalised paths of its `source`, empty when it declares none.
  """
  source = record.get(_SOURCE_KEY) if isinstance(record, dict) else None
  paths = source.get(_PATHS_KEY) if isinstance(source, dict) else None
  return [ _normalise_source_path(path) for path in paths or [] if isinstance(path, str) ]


def _normalise_source_path(path: str) -> str:
  """
  Normalise one source path to a comparable prefix.

  `.`, `./` and an empty name all name the repository root, which contains every path. A path such as `a/../b` is
  `b`, and a trailing slash does not matter.

  Args:
    path: The source path as written in the product record.

  Returns:
    The path with one trailing slash, or the empty string for the repository root.
  """
  # the repository root normalises to the empty prefix every path starts with; any other path ends in one slash
  normalised = posixpath.normpath(path.strip()).strip("/")
  return "" if normalised in _ROOT_SOURCE_PATHS else f"{normalised}/"


def _is_within(paths: list[str], outer: list[str]) -> bool:
  """
  Tell whether every path lies inside one of the outer paths, on a path-segment boundary.

  The empty outer path stands for the repository root and contains every path.

  Args:
    paths: Normalised source paths.
    outer: Normalised source paths of the enclosing product.

  Returns:
    True when each path equals or descends from some outer path.
  """
  return all(any(path.startswith(parent) for parent in outer) for path in paths)


def find_all_own_source_conflicts(vault: Path, *, products: dict | None = None) -> list[tuple[str, str]]:
  """
  List the nested products whose own `source` reaches outside the code of the product enclosing them.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    `(child, ancestor)` pairs, sorted by child key, where `ancestor` is the nearest ancestor of `child` with a
    `source` of its own and the child names a path outside that ancestor's paths; empty when every nested source
    only narrows the code above it.
  """
  registry = _registry(vault, products)
  conflicts: list[tuple[str, str]] = []
  for key in sorted(registry):
    # guard: a product without its own source conflicts with nobody
    if not _has_own_source(registry.get(key)):
      continue

    # the nearest ancestor that carries a source of its own
    owner = next(( ancestor for ancestor in reversed(ancestor_chain(vault, key, products = registry))
                   if _has_own_source(registry.get(ancestor)) ), None)

    # a nested source is legal while it only narrows the enclosing code
    if owner is not None and not _is_within(_source_paths(registry.get(key)), _source_paths(registry.get(owner))):
      conflicts.append(( key, owner ))
  return conflicts


def effective_record(vault: Path, key: str, *, products: dict | None = None,
                     catalog_guidelines: RoleGuidelines | None = None) -> dict:
  """
  Resolve a product's record with every undeclared inheritable key taken from its ancestors.

  Guarantees:
    - With `catalog_guidelines` given, the settings file's `spec.guidelines` are not read, and the mapping the
      caller passed is never modified.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    products: An already-loaded products registry covering only the products; None reads one
      from the settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the settings file.

  Returns:
    The merged record — `asset_types` merged key-by-key outermost first, `guidelines` as the
    ordered per-role union starting from the catalog-wide `spec.guidelines` as the outermost
    layer, ahead of every enclosing product's own and this product's own, so a top-level product
    with no guidelines declared of its own still carries a `guidelines` key when the catalog
    declares any, every other inheritable scalar from the nearest declaring product, `source` /
    `dependencies` / `icon` / `color` / `spec_path` the product's own only. `{}` for an unknown key.

  Raises:
    ValueError: If the settings file is read for the registry or the catalog-wide guidelines and cannot be read, is
      not valid JSON, not UTF-8 text or not a JSON object; a `spec_paths.SettingsError` naming the file.
  """

  # Contract:
  # With `catalog_guidelines` given, the settings file's `spec.guidelines` are not read and the given mapping
  # is the catalog-wide layer; the caller's mapping and its lists are never modified.

  registry = _registry(vault, products)
  own = registry.get(key)

  # guard: nothing registered under this key
  if not isinstance(own, dict):
    return {}
  merged: dict = {}
  asset_types: dict = {}

  # Domain(spec.config):
  # # Catalog-wide guidelines
  # Guidelines the catalog declares for the whole vault are the outermost layer every product
  # inherits, ahead of its enclosing products and its own. Products standing side by side at the
  # top of the catalog share no ancestor, so this is the one place a guideline reaches them all.

  # the catalog's own guidelines seed the per-role union
  guidelines: RoleGuidelines = (
      load_catalog_guidelines(vault) if catalog_guidelines is None
      else { role: list(paths) for role, paths in catalog_guidelines.items() }
  )

  # the registry is resolved once above and handed down, so the whole chain costs no extra read
  for link in (*ancestor_chain(vault, key, products = registry), key):
    record = registry.get(link) or {}

    # both sections are operator-edited JSON: a malformed one, or a malformed member inside it,
    # is skipped rather than raised on, so one bad key never blanks the whole effective record
    declared_types = record.get(_ASSET_TYPES_KEY)
    for name, decl in (declared_types if isinstance(declared_types, dict) else {}).items():
      # guard: a non-dict declaration carries no keys to merge over the ancestors'
      if not isinstance(decl, dict):
        continue
      asset_types[name] = { **asset_types.get(name, {}), **decl }
    declared_guidelines = record.get(_GUIDELINES_KEY)
    for role, paths in (declared_guidelines if isinstance(declared_guidelines, dict) else {}).items():
      # guard: a non-list role value has no ordered entries to union — iterating a bare string
      # would fold it into the union one character at a time
      if not isinstance(paths, list):
        continue
      bucket = guidelines.setdefault(role, [])
      bucket.extend(path for path in paths if path not in bucket)

    # every other scalar field merges over the ancestors', the nearer level winning
    for field, value in record.items():
      # own-only keys are filled from the product itself below, never from an ancestor
      if field in _OWN_ONLY_KEYS or field in (_ASSET_TYPES_KEY, _GUIDELINES_KEY):
        continue
      merged[field] = value

  # the own-only keys come from the product itself, applied last so no ancestor value survives
  for field in _OWN_ONLY_KEYS:
    if field in own:
      merged[field] = own[field]

  # the merged asset-type and guideline maps are attached only when some level declared them
  if asset_types:
    merged[_ASSET_TYPES_KEY] = asset_types
  if guidelines:
    merged[_GUIDELINES_KEY] = guidelines
  return merged


def effective_record_by_path(vault: Path,
                             rel_path: str,
                             *,
                             products: dict | None = None,
                             catalog_guidelines: RoleGuidelines | None = None) -> tuple[str | None, dict | None]:
  """
  Attribute a path to its innermost product and return that product's effective record.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    rel_path: Doc path to attribute, content-root-relative or repo-relative as `resolve_product_by_path` reads it.
    products: An already-loaded products registry covering only the products; None reads one
      from the settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; with it given, the settings file's
      `spec.guidelines` are not read. None reads them from the settings file.

  Returns:
    A `(key, record)` pair as `resolve_product_by_path` returns it, the record replaced by
    `effective_record` for that key; `(None, None)` when no product covers the path.

  Raises:
    ValueError: If the settings file is read for the registry or the catalog-wide guidelines and cannot be read, is
      not valid JSON, not UTF-8 text or not a JSON object; a `spec_paths.SettingsError` naming the file.
  """
  registry = _registry(vault, products)
  key, _record = resolve_product_by_path(vault, rel_path, products = registry)

  # guard: no product covers the path — nothing to inherit into
  if key is None:
    return None, None

  # the products registry is resolved once above and handed down; the catalog-wide guidelines are read from the
  # settings file again unless the caller handed them in
  return key, effective_record(vault, key, products = registry, catalog_guidelines = catalog_guidelines)


def owning_product_root(path: Path) -> Path | None:
  """
  Resolve the root folder of the registered product owning `path`.

  The settings root is the nearest ancestor of `path` carrying `.claude/lazy.settings.json`;
  `path` is then attributed through `resolve_product_by_path`, so when products nest the
  innermost (longest `spec_path`) one wins.

  Args:
    path: Absolute path of a folder or file inside the spec content-root.

  Returns:
    `<content-root>/<spec_path>` of the owning product, resolved; None when `path` sits outside
    the content-root or no registered product's `spec_path` covers it.
  """
  settings_root = find_settings_root(path)
  content_root = spec_content_root(settings_root).resolve()
  try:
    rel = path.resolve().relative_to(content_root)
  except ValueError:
    return None
  _key, record = resolve_product_by_path(settings_root, rel.as_posix())

  # guard: no registered product owns the path
  if record is None:
    return None
  return content_root / record[_SPEC_PATH_KEY]


def resolve_asset_token(asset_dir: Path, token: str) -> Path | None:
  """
  Resolve a cross-asset token (`spec_targets`) to the asset folder it names.

  A token is a path relative to the owning product's root, any number of segments deep:
  `changes/foo` for a standard asset, `changes/foo/bugs/crash` for one nested inside another,
  a bare `foo` for one sitting at the product root. Without a registered product the fixed
  `<spec_path>/<category>/<slug>/` nesting is assumed and the product root is taken two levels
  above `asset_dir`.

  Args:
    asset_dir: The asset folder the token is declared on.
    token: The product-relative path token.

  Returns:
    The named asset folder, or None when the token is empty, climbs out of the product, or
    names no folder-note that exists on disk.
  """
  parts = [ part for part in token.split("/") if part ]

  # guard: an empty token, or one stepping out of the product tree, names nothing
  if not parts or any(part in (".", "..") for part in parts):
    return None
  product_root = owning_product_root(asset_dir) or asset_dir.resolve().parent.parent
  target_dir = product_root.joinpath(*parts)

  # guard: a token whose folder-note is not on disk names no asset
  if not (target_dir / f"{target_dir.name}.md").is_file():
    return None
  return target_dir


def main(argv: list[str]) -> int:
  """
  Answer one product-configuration query chosen by the command line and print the result as JSON.

  Guarantees:
    - A failure of `specialists`, `specialists-by-path` or `release-implementer` exits 1 and prints an object whose
      `specialists` (`implementer` for `release-implementer`) is null and whose `error` carries the reason, never
      an empty answer; the result is read only on exit 0.

  Notes:
    - The `specialists` and `specialists-by-path` verbs print each guideline warning to standard error, never
      inside the JSON answer.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the query is answered, including a null result for an unknown key, a path no product owns or
    a product with no release implementer; 1 when `specialists` or `specialists-by-path` finds missing or malformed
    information, or when one of those verbs or `release-implementer` meets an unreadable or malformed settings
    file, after printing `{"key", "specialists": null, "error"}`, or `{"key", "implementer": null, "error"}` for
    `release-implementer`; `key` is the asked key, except null for an unreadable settings file under
    `specialists-by-path`.

  Raises:
    SystemExit: When the command line is not a valid verb with its positional argument.
  """

  # Contract:
  # A failure of the `specialists`, `specialists-by-path` or `release-implementer` verbs is never an empty answer:
  # the verb exits 1 and prints an object whose `specialists` (or, for `release-implementer`, `implementer`) is
  # null and whose `error` carries the reason, so a caller tells a failure from an empty list or a product with
  # no implementer by the exit code and the null value, and reads the result only on exit 0.

  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs resolve-product")
  # waiver: argparse namespace attribute name for the chosen verb, read back only by this function
  sub = parser.add_subparsers(dest = "mode", required = True)

  # every verb takes one positional — a registry key or a content-root- or repo-relative path —
  # plus the vault root
  for verb, positional in (
      (_MODE_BY_KEY, "key"), (_MODE_BY_PATH, "relpath"),
      (_MODE_EFFECTIVE, "key"), (_MODE_EFFECTIVE_BY_PATH, "relpath"),
      (_MODE_ANCESTOR_CHAIN, "key"), (_MODE_OWN_SOURCE_CONFLICTS, ""), (_MODE_RELEASE_IMPLEMENTER, "key"),
      (_MODE_SPECIALISTS, "key"), (_MODE_SPECIALISTS_BY_PATH, "relpath"),
  ):
    # waiver: argparse CLI signature -- subcommand and its positional argument name
    parsed = sub.add_parser(verb)
    if positional:
      parsed.add_argument(positional)
    parsed.add_argument(
        # waiver: argparse CLI signature -- option flag + vault-root default
        "--cwd", type = Path, default = None,
        # waiver: one-off human-facing message -- argparse help text
        help = "vault root holding .claude/lazy.settings.json (default: cwd)",
    )

  # the vault root anchors every settings lookup below
  args = parser.parse_args(argv)
  vault: Path = (args.cwd or Path.cwd()).resolve()

  # the registry-wide verbs answer about the nesting of products rather than one record
  if args.mode == _MODE_OWN_SOURCE_CONFLICTS:
    print(json.dumps({ "conflicts": [ list(pair) for pair in find_all_own_source_conflicts(vault) ] }))
    return 0
  if args.mode == _MODE_ANCESTOR_CHAIN:
    print(json.dumps({ "key": args.key, "chain": ancestor_chain(vault, args.key) }))
    return 0

  # the release-implementer verb answers unreadable settings with an error, like the specialist verbs
  if args.mode == _MODE_RELEASE_IMPLEMENTER:
    try:
      implementer = find_release_implementer(vault, args.key)
    except SettingsError as error:
      print(json.dumps({ _ANSWER_KEY: args.key, _ANSWER_IMPLEMENTER: None, _ANSWER_ERROR: str(error) }))
      return 1
    print(json.dumps({ _ANSWER_KEY: args.key, _ANSWER_IMPLEMENTER: implementer }))
    return 0

  # the specialist verbs fail loudly: missing information is an error, never an empty answer
  if args.mode in (_MODE_SPECIALISTS, _MODE_SPECIALISTS_BY_PATH):
    try:
      if args.mode == _MODE_SPECIALISTS:
        answer = build_specialists(vault, args.key)
      else:
        answer = build_specialists_by_path(vault, args.relpath)
    except SpecialistsError as error:
      print(json.dumps({ _ANSWER_KEY: error.key, _ANSWER_SPECIALISTS: None, _ANSWER_ERROR: str(error) }))
      return 1
    # unreadable settings are missing information too; no product resolved by path, the key asked for by key
    except SettingsError as error:
      asked = args.key if args.mode == _MODE_SPECIALISTS else None
      print(json.dumps({ _ANSWER_KEY: asked, _ANSWER_SPECIALISTS: None, _ANSWER_ERROR: str(error) }))
      return 1

    # a declared guideline with no file is reported beside the answer, never inside it
    for warning in answer.pop(_ANSWER_WARNINGS):
      print(warning, file = sys.stderr)
    print(json.dumps(answer))
    return 0

  # the by-key verbs answer straight from the products registry
  if args.mode in (_MODE_BY_KEY, _MODE_EFFECTIVE):
    record = resolve_product_by_key(vault, args.key)

    # guard: unknown key resolves to null under either verb, still a clean exit
    if record is None:
      print(json.dumps({ "key": args.key, "record": None }))
      return 0
    if args.mode == _MODE_EFFECTIVE:
      record = effective_record(vault, args.key)
    print(json.dumps({ "key": args.key, "record": record }))
    return 0

  # the by-path verbs walk the products registry for the longest owning spec_path
  if args.mode == _MODE_EFFECTIVE_BY_PATH:
    key, record = effective_record_by_path(vault, args.relpath)
  else:
    key, record = resolve_product_by_path(vault, args.relpath)

  # print the owning product's key and record; a path no product owns prints both as null, a
  # non-error result
  print(json.dumps({ "key": key, "record": record }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
