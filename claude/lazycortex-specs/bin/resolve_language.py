"""Spec-language resolver primitive — pick the effective doc language.

The language for a spec doc is resolved through a four-step fallback
chain; the first non-empty value wins:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's `language` (resolved by attributing the doc
   path to a product via `resolve_product_by_path`);
3. the `spec` section's `default_language` in `lazy.settings.json`;
4. the hardcoded floor `en`.

Settings live at `<vault>/.claude/lazy.settings.json`. Frontmatter is
read with a minimal flat-scalar parser — no yaml dependency.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — bare-name sibling import resolved at runtime via sys.path
import resolve_product  # noqa: E402


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION = "spec"
_DOC_LANGUAGE_KEY = "spec_language"
_PRODUCT_LANGUAGE_KEY = "language"
_DEFAULT_LANGUAGE_KEY = "default_language"
_LANGUAGE_FLOOR = "en"


def _parse_frontmatter(text: str) -> dict:
  """
  Parse the flat top-level scalar keys of a file's YAML frontmatter block.

  Mirrors the minimal reader used by the request opt-in handler: only
  unindented `key: value` lines are captured; nested blocks, comments, and
  bullet members are skipped. No yaml dependency.

  Args:
    text: Full file text, frontmatter expected at the very start.

  Returns:
    A flat dict of top-level scalar keys, or an empty dict when there is no
    parseable frontmatter.
  """
  # guard: frontmatter must open with the fence on the first line
  if not text.startswith("---\n"):
    return {}
  rest = text[4:]
  end_idx = rest.find("\n---\n")
  # guard: no closing fence means no parseable frontmatter
  if end_idx < 0:
    return {}
  block = rest[:end_idx]
  values: dict = {}
  for line in block.splitlines():
    stripped = line.lstrip()
    # guard: skip blank lines and comment / bullet markers
    if not stripped or stripped.startswith(("#", "-")):
      continue
    # guard: skip indented (nested) lines — only top-level scalars are captured
    if line != stripped:
      continue
    # guard: skip lines without a key:value separator
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    # guard: skip entries with an empty key
    if not k:
      continue
    values[k] = v.strip()
  return values


def _spec_default_language(vault: Path) -> str | None:
  """
  Read `default_language` from the `spec` section of the vault settings.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    The configured default language, or None when the section or key is absent
    or empty.
  """
  settings_path = vault / _SETTINGS_REL
  # guard: missing settings file means no configured default
  if not settings_path.is_file():
    return None
  data = json.loads(settings_path.read_text())
  spec = data.get(_SPEC_SECTION)
  # guard: missing or malformed spec section means no configured default
  if not isinstance(spec, dict):
    return None
  value = spec.get(_DEFAULT_LANGUAGE_KEY)
  # guard: only a non-empty string counts as a configured default
  if isinstance(value, str) and value:
    return value
  return None


def resolve_spec_language(vault: Path, doc_path: str) -> str:
  """
  Resolve the effective language for a spec doc via the fallback chain.

  The chain returns the first non-empty value among: the doc's frontmatter
  `spec_language`, the owning product's `language`, the `spec` section's
  `default_language`, and the floor `en`.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.
    doc_path: Doc path relative to `vault`.

  Returns:
    The resolved language tag; never empty (falls back to `en`).
  """
  # 1. Doc frontmatter wins.
  doc_file = vault / doc_path
  if doc_file.is_file():
    fm = _parse_frontmatter(doc_file.read_text())
    doc_lang = fm.get(_DOC_LANGUAGE_KEY)
    # guard: a non-empty frontmatter language is authoritative
    if doc_lang:
      return doc_lang

  # 2. Owning product's language.
  _, record = resolve_product.resolve_product_by_path(vault, doc_path)
  if isinstance(record, dict):
    product_lang = record.get(_PRODUCT_LANGUAGE_KEY)
    # guard: a non-empty product language is the next fallback
    if isinstance(product_lang, str) and product_lang:
      return product_lang

  # 3. Spec-section default.
  default_lang = _spec_default_language(vault)
  # guard: a configured default is the last non-floor fallback
  if default_lang:
    return default_lang

  # 4. Hardcoded floor.
  return _LANGUAGE_FLOOR


def main(argv: list[str]) -> int:
  """
  Resolve a doc's effective language from the command line and print it.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code 0 on success.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs resolve-language")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("relpath")
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + vault-root default
      "--cwd", type = Path, default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "vault root holding .claude/lazy.settings.json (default: cwd)",
  )
  args = parser.parse_args(argv)
  vault: Path = (args.cwd or Path.cwd()).resolve()
  print(resolve_spec_language(vault, args.relpath))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
