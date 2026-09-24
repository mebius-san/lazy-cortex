"""Product-config resolver primitives — read products from settings.

Product config lives in `lazy.settings.json[products]` at
`<vault>/.claude/lazy.settings.json`. The `_version` key carries the
section schema version and is not a product record. Each remaining key
is a product whose record holds at least `spec_path` (vault-relative).

Two lookups are exposed:

- `resolve_product_by_key` — direct record fetch by product key.
- `resolve_product_by_path` — owning-product lookup for a vault-relative
  doc path, matching on path segments (never raw string prefix) and
  returning the longest matching `spec_path` when several products
  nest.
- `owning_product_root` — the on-disk root folder of the product owning
  an absolute path, resolved through the same longest-`spec_path` rule.
- `resolve_asset_token` — a `spec_targets` / `spec_depends_on` token to
  the asset folder it names: a path relative to the owning product's
  root, any number of segments deep.

A nested product inherits its ancestors' record through
`effective_record`; `ancestor_chain` lists them outermost first. Every
nesting reader takes an optional already-loaded registry, so a caller
walking a whole chain reads the settings file once rather than per link.

The CLI exposes four verbs, all printing one `{"key", "record"}` JSON
line and exiting 0 even when nothing resolves: `by-key <key>` and
`by-path <relpath>` answer with the raw registry record, `effective
<key>` and `effective-by-path <relpath>` with the inherited one. A
reader that acts on a product's configuration wants the `effective`
pair; the raw pair is for a caller that writes the record back.

Both read the settings JSON directly to stay dependency-light; no
import of the `lazy_settings` loader, no yaml dependency.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from spec_paths import _vault_root_value, find_settings_root, spec_content_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_VERSION_KEY = "_version"
_PRODUCTS_SECTION = "products"
_SPEC_PATH_KEY = "spec_path"
_MODE_BY_KEY = "by-key"
_MODE_BY_PATH = "by-path"
_MODE_EFFECTIVE = "effective"
_MODE_EFFECTIVE_BY_PATH = "effective-by-path"


def load_products(vault: Path) -> dict:
  """
  Read the `products` section from the vault's `lazy.settings.json`.

  The `_version` schema marker is stripped so the result maps product keys to
  records only.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    A dict of product key to record; empty when the settings file or the
    `products` section is absent.
  """
  settings_path = vault / _SETTINGS_REL

  # guard: missing settings file means no products configured
  if not settings_path.is_file():
    return {}
  data = json.loads(settings_path.read_text())
  products = data.get(_PRODUCTS_SECTION)

  # guard: missing or malformed products section means no products
  if not isinstance(products, dict):
    return {}
  return { k: v for k, v in products.items() if k != _VERSION_KEY }


def _registry(vault: Path, products: dict | None) -> dict:
  """
  Return the products registry a reader should work against.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    products: An already-loaded registry, or None to read one from the settings file.

  Returns:
    The caller's registry when it gave one, otherwise the vault's own.
  """
  # guard: a caller walking a whole chain loads the registry once and hands it down
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
  Find the product owning a vault-relative doc path.

  A product owns the path when its `spec_path` equals the path or is a
  segment-wise prefix of it. When several products nest, the one with the
  longest matching `spec_path` wins.

  Guarantees:
    - When several configured products' `spec_path` values nest, the returned product is always
      the one with the longest matching `spec_path`, never a shorter enclosing ancestor.
    - With `products` given, the settings file is not read; the answer is the one the same
      registry on disk would have produced.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    rel_path: Vault-relative doc path to attribute to a product.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    A `(key, record)` pair for the longest-matching product, or `(None, None)`
    when no product's `spec_path` matches.
  """

  # Contract:
  # When several configured products' spec_path values nest, the returned product is always the
  # one with the longest matching spec_path, never a shorter enclosing ancestor.
  # With `products` given, the settings file is not read and the answer is the same one that
  # registry would have produced from disk.

  # Domain(spec.config):
  # # Nested products resolve by longest owning path
  # A document belongs to whichever configured product's own tree contains it, matched on
  # whole path segments rather than raw text, so a product named one thing never accidentally
  # claims a document that merely starts with the same letters under a differently named
  # sibling. When one product's tree sits nested inside another's, the more specific,
  # longer-matching tree wins, so a sub-product's own documents are never mistakenly
  # attributed to the broader product that just happens to contain it.

  vroot = _vault_root_value(vault)
  parts = list(Path(rel_path).parts)

  # strip the vault-root prefix when the caller passed a repo-root-relative path
  if vroot != "." and parts and parts[0] == vroot:
    parts = parts[1:]
  doc_segments = tuple(parts)
  best_key: str | None = None
  best_record: dict | None = None
  best_len = -1
  for key, record in _registry(vault, products).items():
    spec_path = record.get(_SPEC_PATH_KEY) if isinstance(record, dict) else None

    # guard: skip records without a usable spec_path
    if not isinstance(spec_path, str) or not spec_path:
      continue
    spec_segments = Path(spec_path).parts

    # guard: skip products whose spec_path does not own this doc path
    if not _is_path_prefix(list(spec_segments), list(doc_segments)):
      continue
    if len(spec_segments) > best_len:
      best_len = len(spec_segments)
      best_key = key
      best_record = record
  return best_key, best_record


# keys a nested product never takes from an ancestor — a code binding, a dependency list and a
# paint belong to one product; spec_path names the product itself
_OWN_ONLY_KEYS = frozenset({ "source", "dependencies", "icon", "color", _SPEC_PATH_KEY })
_ASSET_TYPES_KEY = "asset_types"
_GUIDELINES_KEY = "guidelines"


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


def effective_record(vault: Path, key: str, *, products: dict | None = None) -> dict:
  """
  Resolve a product's record with every undeclared inheritable key taken from its ancestors.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    key: The product's compound-key.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    The merged record — `asset_types` merged key-by-key outermost first, `guidelines` as the
    ordered per-role union outermost first, every other inheritable scalar from the nearest
    declaring product, `source` / `dependencies` / `icon` / `color` / `spec_path` the product's
    own only. `{}` for an unknown key.
  """
  registry = _registry(vault, products)
  own = registry.get(key)

  # guard: nothing registered under this key
  if not isinstance(own, dict):
    return {}
  merged: dict = {}
  asset_types: dict = {}
  guidelines: dict[str, list[str]] = {}
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
    for field, value in record.items():
      # guard: own-only keys are filled from the product itself below, never from an ancestor
      if field in _OWN_ONLY_KEYS or field in (_ASSET_TYPES_KEY, _GUIDELINES_KEY):
        continue
      merged[field] = value
  for field in _OWN_ONLY_KEYS:
    if field in own:
      merged[field] = own[field]
  if asset_types:
    merged[_ASSET_TYPES_KEY] = asset_types
  if guidelines:
    merged[_GUIDELINES_KEY] = guidelines
  return merged


def effective_record_by_path(vault: Path, rel_path: str, *,
                             products: dict | None = None) -> tuple[str | None, dict | None]:
  """
  Attribute a path to its innermost product and return that product's effective record.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    rel_path: Vault-relative doc path to attribute.
    products: An already-loaded products registry; None reads it from the settings file.

  Returns:
    A `(key, record)` pair as `resolve_product_by_path` returns it, the record replaced by
    `effective_record(vault, key)`; `(None, None)` when no product covers the path.
  """
  registry = _registry(vault, products)
  key, _record = resolve_product_by_path(vault, rel_path, products = registry)

  # guard: no product covers the path — nothing to inherit into
  if key is None:
    return None, None

  # the registry is resolved once above and handed down, so the inheritance costs no extra read
  return key, effective_record(vault, key, products = registry)


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
  Resolve a cross-asset token (`spec_targets` / `spec_depends_on`) to the asset folder it names.

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
  Resolve a product by key or by path, raw or inherited, and print the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 on a usage error or unresolved path.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs resolve-product")
  sub = parser.add_subparsers(dest = "mode", required = True)

  # every verb takes one positional — a registry key or a vault-relative path — plus the vault root
  for verb, positional in (
      (_MODE_BY_KEY, "key"), (_MODE_BY_PATH, "relpath"),
      (_MODE_EFFECTIVE, "key"), (_MODE_EFFECTIVE_BY_PATH, "relpath"),
  ):
    # waiver: argparse CLI signature -- subcommand and its positional argument name
    parsed = sub.add_parser(verb)
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

  # guard: no owning product is a non-error null result
  if key is None:
    print(json.dumps({ "key": None, "record": None }))
    return 0
  print(json.dumps({ "key": key, "record": record }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
