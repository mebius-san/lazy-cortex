"""
Resolve one document template by context and filename — the `template resolve` verb.

    lazycortex-specs template resolve --context <ctx> [--product <key>] [--type <expected>] [--cwd DIR] <file>

Prints `{"path", "doc_type", "layer"}` for the first layer of the template chain that carries the
file. A skill that needs a template asks here instead of composing a path by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import scaffold_asset

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: CLI verb and flag tokens -- this module's own argparse surface
_VERB_RESOLVE = "resolve"
_ARG_VERB = "verb"
_ARG_FILE = "file"
_ARG_CONTEXT = "--context"
_ARG_PRODUCT = "--product"
_ARG_TYPE = "--type"
_ARG_CWD = "--cwd"
# waiver: the env var the daemon exports for every subprocess it spawns
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
_PROG = "lazycortex-specs template"
# waiver: the two level contexts and the fall-through between them
_CONTEXT_VAULT = "vault"
_CONTEXT_PRODUCT = "product"
# waiver: JSON report keys the calling skill reads
_OUT_PATH = "path"
_OUT_DOC_TYPE = "doc_type"
_OUT_LAYER = "layer"


def _alias_for(repo: Path, context: str, product: str) -> str:
  """
  Pick the base context a lookup falls through to.

  Args:
    repo: Repository root.
    context: The requested template context.
    product: The product compound-key, or empty.

  Returns:
    `product` for the vault context, the declared alias base for a product-scoped asset type,
    otherwise an empty string.
  """
  # guard: the catalog root shares the level note with the product context
  if context == _CONTEXT_VAULT:
    return _CONTEXT_PRODUCT
  # guard: only a product-scoped asset type can declare an alias base
  if not product or context == _CONTEXT_PRODUCT:
    return ""
  return scaffold_asset._alias_base(context, scaffold_asset._resolve_product(repo, product))


def main(argv: list[str]) -> int:
  """
  Run the `template` subcommand from the command line, printing the resolution as JSON.

  Args:
    argv: Subcommand argv tail — `resolve --context <ctx> [--product <key>] [--type <t>] [--cwd DIR] <file>`.

  Returns:
    Exit code: 0 on success.

  Raises:
    SystemExit: When no layer carries the file, or the file declares a type other than `--type`.
  """
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature -- positional and flag names shown in --help / usage
  parser.add_argument(_ARG_VERB, choices = [ _VERB_RESOLVE ])
  parser.add_argument(_ARG_FILE)
  parser.add_argument(_ARG_CONTEXT, required = True)
  parser.add_argument(_ARG_PRODUCT, default = "")
  parser.add_argument(_ARG_TYPE, default = "")
  parser.add_argument(_ARG_CWD, default = None)
  args = parser.parse_args(argv)

  # the flag, then the daemon-exported env var, then the process cwd — like every sibling verb
  repo = scaffold_asset._repo_root(Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))
  alias_base = _alias_for(repo, args.context, args.product)
  layers = scaffold_asset._template_layers(repo, args.context, args.product, args.file, alias_base = alias_base)
  chosen = scaffold_asset._resolve_template(repo, args.context, args.product, args.file,
                                            alias_base = alias_base, expect_type = args.type)
  # with no product the per-product layer collapses onto the consumer layer under the same path, so
  # it names nothing; a by-type fallback lands on a sibling of a layer's path, so the folder decides
  named = [ (label, path) for label, path in layers
            if args.product or not label.endswith(scaffold_asset._K.LAYER_PRODUCT_OVERRIDE) ]
  layer = next(label for label, path in named if path.parent == chosen.parent)
  print(json.dumps({ _OUT_PATH: str(chosen), _OUT_DOC_TYPE: scaffold_asset._template_doc_type(chosen),
                     _OUT_LAYER: layer }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
