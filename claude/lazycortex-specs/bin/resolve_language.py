"""Spec-language resolver primitive — pick the effective doc language.

The language for a spec doc is resolved through a fallback chain; the
first non-empty value wins:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's `language` (resolved by attributing the doc
   path to a product via `resolve_product_by_path`);
3. the `spec` section's `language` in `lazy.settings.json`;
4. the top-level `language` key (repo-wide default);
5. the hardcoded floor `en`.

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
_SPEC_LANGUAGE_KEY = "language"
_ROOT_LANGUAGE_KEY = "language"
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


def _read_settings(vault: Path) -> dict:
  """
  Read the vault settings file as a dict, empty when absent or malformed.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    The parsed settings dict, or an empty dict when the file is missing or is
    not valid JSON.
  """
  settings_path = vault / _SETTINGS_REL
  # guard: missing settings file means no configured values at all
  if not settings_path.is_file():
    return {}
  try:
    data = json.loads(settings_path.read_text())
  except (OSError, json.JSONDecodeError):
    return {}
  return data if isinstance(data, dict) else {}


def _clean(value: object) -> str | None:
  """
  Narrow a raw settings value to a usable language tag.

  Args:
    value: Raw value read from the settings dict.

  Returns:
    The value when it is a non-empty string, else None.
  """
  return value if isinstance(value, str) and value else None


def _spec_section_language(settings: dict) -> str | None:
  """
  Read the spec section's own `language` key from a parsed settings dict.

  Args:
    settings: The parsed `lazy.settings.json` contents.

  Returns:
    The configured spec language, or None when the section or the key is
    absent or empty.
  """
  spec = settings.get(_SPEC_SECTION)
  # guard: missing or malformed spec section means no configured default
  if not isinstance(spec, dict):
    return None
  return _clean(spec.get(_SPEC_LANGUAGE_KEY))


def resolve_repo_language(vault: Path) -> str:
  """
  Resolve the repo-level spec language, ignoring any per-doc override.

  The chain returns the first non-empty value among: the `spec` section's
  `language`, the top-level `language` key, and the floor `en`.

  Args:
    vault: Vault root directory holding `.claude/lazy.settings.json`.

  Returns:
    The resolved language tag; never empty (falls back to `en`).
  """
  # one settings read serves both rungs of the chain
  settings = _read_settings(vault)
  return _spec_section_language(settings) or _clean(settings.get(_ROOT_LANGUAGE_KEY)) or _LANGUAGE_FLOOR


def resolve_spec_language(vault: Path, doc_path: str) -> str:
  """
  Resolve the effective language for a spec doc via the fallback chain.

  The chain returns the first non-empty value among: the doc's frontmatter
  `spec_language`, the owning product's `language`, the `spec` section's
  `language`, the top-level `language` key, and the floor `en`.

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

  # 3-5. Spec-section language, repo-wide language, hardcoded floor.
  return resolve_repo_language(vault)


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
