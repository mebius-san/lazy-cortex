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

Both read the settings JSON directly to stay dependency-light; no
import of the `lazy_settings` loader, no yaml dependency.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_VERSION_KEY = "_version"
_PRODUCTS_SECTION = "products"
_SPEC_PATH_KEY = "spec_path"
_MODE_BY_KEY = "by-key"
_MODE_BY_PATH = "by-path"


def _load_products(vault: Path) -> dict:
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
  return _load_products(vault).get(key)


def resolve_product_by_path(vault: Path, rel_path: str) -> tuple[str | None, dict | None]:
  """
  Find the product owning a vault-relative doc path.

  A product owns the path when its `spec_path` equals the path or is a
  segment-wise prefix of it. When several products nest, the one with the
  longest matching `spec_path` wins.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    rel_path: Vault-relative doc path to attribute to a product.

  Returns:
    A `(key, record)` pair for the longest-matching product, or `(None, None)`
    when no product's `spec_path` matches.
  """
  doc_segments = Path(rel_path).parts
  best_key: str | None = None
  best_record: dict | None = None
  best_len = -1
  for key, record in _load_products(vault).items():
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


def main(argv: list[str]) -> int:
  """
  Resolve a product by key or by path and print the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 on a usage error or unresolved path.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs resolve-product")
  sub = parser.add_subparsers(dest = "mode", required = True)

  # waiver: argparse CLI signature -- by-key subcommand
  p_key = sub.add_parser(_MODE_BY_KEY)
  # waiver: argparse CLI signature -- positional argument name
  p_key.add_argument("key")
  p_key.add_argument(
      # waiver: argparse CLI signature -- option flag + vault-root default
      "--cwd", type = Path, default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "vault root holding .claude/lazy.settings.json (default: cwd)",
  )

  # waiver: argparse CLI signature -- by-path subcommand
  p_path = sub.add_parser("by-path")
  # waiver: argparse CLI signature -- positional argument name
  p_path.add_argument("relpath")
  p_path.add_argument(
      # waiver: argparse CLI signature -- option flag + vault-root default
      "--cwd", type = Path, default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "vault root holding .claude/lazy.settings.json (default: cwd)",
  )

  args = parser.parse_args(argv)
  vault: Path = (args.cwd or Path.cwd()).resolve()

  if args.mode == _MODE_BY_KEY:
    record = resolve_product_by_key(vault, args.key)
    # guard: unknown key resolves to null, still a clean exit
    if record is None:
      print(json.dumps({ "key": args.key, "record": None }))
      return 0
    print(json.dumps({ "key": args.key, "record": record }))
    return 0

  key, record = resolve_product_by_path(vault, args.relpath)
  # guard: no owning product is a non-error null result
  if key is None:
    print(json.dumps({ "key": None, "record": None }))
    return 0
  print(json.dumps({ "key": key, "record": record }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
