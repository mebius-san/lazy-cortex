"""Spec-language resolver primitive — pick the effective doc language.

The language for a spec doc is resolved through a fallback chain; the
first non-empty value wins:

1. the doc's own frontmatter `spec_language` key;
2. the owning product's `language` (resolved by attributing the doc
   path to a product's effective record via `effective_record_by_path`,
   inheriting from any enclosing product);
3. the `spec` section's `language`;
4. the top-level `language` key (repo-wide default);
5. the hardcoded floor `en`.

Rungs 3-5 come from the core plugin's language verb, asked for this
plugin's `spec` section; this module does not read the settings itself.
Frontmatter is read with a minimal flat-scalar parser — no yaml dependency.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — bare-name sibling import resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: intentional suppression — bare-name sibling import resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: intentional suppression — bare-name sibling import resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_SPEC_SECTION = "spec"
_DOC_LANGUAGE_KEY = "spec_language"
_PRODUCT_LANGUAGE_KEY = "language"
# The core plugin whose language verb owns the section → repo-wide → `en` rungs.
_CORE_CLI_NAME = "lazycortex-core"
# Core CLI verb, flags, and this plugin's own settings section passed to it.
_SUB_RESOLVE_LANGUAGE = "resolve-language"
_ARG_SECTION = "--section"
_ARG_CWD = "--cwd"


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
    values[k] = spec_frontmatter.strip_comment(v.strip())
  return values


def resolve_repo_language(vault: Path) -> str:
  """
  Resolve the repo-level spec language, ignoring any per-doc override.

  The chain returns the first non-empty value among: the `spec` section's
  `language`, the top-level `language` key, and the floor `en`.

  Guarantees:
    - Never returns an empty value; an unconfigured repo resolves to the floor `en`.

  Args:
    vault: Vault root directory whose language is resolved.

  Returns:
    The resolved language tag; never empty (falls back to `en`).

  Raises:
    RuntimeError: If the core plugin's CLI cannot be resolved, its language verb exits non-zero, or the verb
      exits zero but answers nothing.
  """

  # Contract:
  # The resolved language tag is never empty; an unconfigured repo resolves to the floor `en`
  # rather than an empty string or None.

  # core owns these rungs; the spec plugin only names its own section
  cli = spec_paths.resolve_core_cli(vault)

  # ask core for the section → repo-wide → floor answer
  proc = subprocess.run(
      [ sys.executable, str(cli), _SUB_RESOLVE_LANGUAGE, _ARG_SECTION, _SPEC_SECTION, _ARG_CWD, str(vault) ],
      capture_output = True, text = True, check = False, encoding = "utf-8",
  )

  # guard: a non-zero exit or an empty answer — surface stdout+stderr instead of inventing a language
  if proc.returncode != 0 or not proc.stdout.strip():
    raise RuntimeError(
        f"{_CORE_CLI_NAME} {_SUB_RESOLVE_LANGUAGE} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return proc.stdout.removesuffix("\n")


def resolve_spec_language(vault: Path, doc_path: str) -> str:
  """
  Resolve the effective language for a spec doc via the fallback chain.

  The chain returns the first non-empty value among: the doc's frontmatter
  `spec_language`, the owning product's `language`, the `spec` section's
  `language`, the top-level `language` key, and the floor `en`.

  Guarantees:
    - Never returns an empty value; an unconfigured repo resolves to the floor `en`.

  Args:
    vault: Vault root directory containing the doc.
    doc_path: Doc path relative to `vault`.

  Returns:
    The resolved language tag; never empty (falls back to `en`).

  Raises:
    RuntimeError: If the doc and product rungs yield nothing and the core plugin's CLI cannot be resolved, its
      language verb exits non-zero, or the verb exits zero but answers nothing.
  """

  # Contract:
  # The resolved language tag is never empty; an unconfigured repo resolves to the floor `en`
  # rather than an empty string or None.

  # Domain(spec.config):
  # # Document language falls back through five rungs
  # A spec document's language is never asked for directly; it is settled by the first rung
  # that actually answers, in order: the document's own recorded language, the language its
  # owning product declares or, failing that, the nearest product enclosing it that declares
  # one, the catalog's own configured default, the repository's overall
  # default, and a fixed floor when nothing above ever answered. The order lets one document
  # diverge from its product, and one product diverge from the catalog, without forcing every
  # other document or product to declare a language it is otherwise happy to inherit.

  # 1. Doc frontmatter wins.
  doc_file = vault / doc_path
  if doc_file.is_file():
    fm = _parse_frontmatter(doc_file.read_text(encoding = "utf-8"))
    doc_lang = fm.get(_DOC_LANGUAGE_KEY)

    # guard: a non-empty frontmatter language is authoritative
    if doc_lang:
      return doc_lang

  # 2. Owning product's language.
  _, record = resolve_product.effective_record_by_path(vault, doc_path)
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
