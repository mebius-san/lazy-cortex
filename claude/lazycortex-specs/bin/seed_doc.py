"""
Deterministic single-document seeder — the Python primitive backing the
`lazycortex-specs seed-doc` CLI subcommand.

Seeds ONE authored doc beside an existing asset's status folder-note, from
the same per-type template chain `scaffold-asset` uses. The coordinator's
launch checkboxes are the intended caller: a spawn scaffolds the folder and
its folder-note alone, and every document is seeded later, one checkbox
tick at a time, through this primitive.

CLI: `seed-doc <product> <folder-note-path> --doc <name>:<spec_doc_type>
[--cwd <repo>]`. The folder-note path is repo-relative and must exist; the
target doc must not. The seeded doc starts at stage `empty` and inherits
the folder-note's `spec_source_requests` list, so the review dispatcher's
`context_from_frontmatter` can resolve the originating request(s) when the
doc's writer is dispatched.

Level mode: `seed-doc --root <folder-note-path> --doc <name>:<spec_doc_type>
[--cwd <repo>]` seeds a system document beside a level folder-note — the
catalog root's or a product's own. A product's level note is resolved to
the registered product whose `spec_path` is its folder, so the product
tokens, the per-product template layer and the paint declarations are the
product's own; at the catalog root the product tokens carry the content
root's directory name and only the project-wide override layer applies.
Naming a product alongside `--root` is refused; the two spellings never
combine.

Stdout: a JSON object with `outcome` and the created doc's repo-relative
path under `doc`. On error: a JSON object with `error` field and non-zero
exit.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import datetime as _dt
import json
import re
from pathlib import Path

import apply_request
import scaffold_asset
import spec_doc_types
import spec_paths
from spec_keys import SpecKey, SpecValue

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_PROG = "lazycortex-specs seed-doc"
_ARG_NOTE = "note"
_ARG_ROOT = "--root"
_HELP_DOC = "Produced document as <name>:<spec_doc_type>; exactly one, required"
_HELP_NOTE = "Repo-relative path of the asset's status folder-note"
_HELP_ROOT = "Repo-relative path of a level folder-note — the catalog root's or a product's own"
_STAGE_KEY = "spec_stage"
_SOURCE_REQUESTS_KEY = "spec_source_requests"
# waiver: one-off human-facing messages -- the two mode-selection refusal lines
_ERR_ROOT_WITH_PRODUCT = "--root takes no product and no positional folder-note"
_ERR_MODE_INCOMPLETE = "seed-doc needs <product> <folder-note-path>, or --root <folder-note-path>"

# The template family a level document is seeded from: `_resolve_template` prefixes the value
# with `spec.`, so `docs` names the shipped per-type directory every document type lives in, and
# the empty product below collapses the per-product layer, leaving project override then plugin.
_ROOT_TEMPLATE_FAMILY = "docs"
_NO_PRODUCT = ""


def _note_source_requests(note_text: str) -> list[str]:
  """
  Read the folder-note's `spec_source_requests` wikilink values.

  Args:
    note_text: Full folder-note text (frontmatter + body).

  Returns:
    The list values in declaration order, unquoted; empty when the key is absent or empty.
  """
  _fm, fm_end = apply_request._parse_frontmatter(note_text)
  match = re.search(
      rf"(?m)^{_SOURCE_REQUESTS_KEY}:\n((?:^  - .*\n)*)", note_text[:fm_end])
  # guard: key absent or carrying no block items — nothing to inherit
  if not match:
    return []
  return [ line.strip()[2:].strip().strip('"') for line in match.group(1).splitlines() ]


def _set_stage_empty(fm_text: str) -> str:
  """
  Force the frontmatter's `spec_stage` to `empty`.

  Args:
    fm_text: The doc's frontmatter slice, including both `---` fences.

  Returns:
    The frontmatter with `spec_stage: empty` — replacing a template-supplied value, or inserted
    before the closing fence when the template carried none.
  """
  if re.search(rf"(?m)^{_STAGE_KEY}:", fm_text):
    return re.sub(rf"(?m)^{_STAGE_KEY}:.*$", f"{_STAGE_KEY}: {scaffold_asset._K.STAGE_EMPTY}",
                  fm_text, count = 1)
  return fm_text.rstrip("\n").removesuffix("---") + f"{_STAGE_KEY}: {scaffold_asset._K.STAGE_EMPTY}\n---\n"


def _product_for_note(repo: Path, note_path: Path) -> tuple[str, dict]:
  """
  Find the registered product whose `spec_path` is the folder the level note sits in.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    note_path: Absolute path of the level folder-note.

  Returns:
    The `(product_key, record)` pair, or `("", {})` when no registered product owns the folder.
  """
  settings_path = repo / scaffold_asset._K.CLAUDE_DIR / scaffold_asset._K.SETTINGS_FILE
  try:
    products = json.loads(settings_path.read_text()).get(scaffold_asset._K.PRODUCTS) or {}
  except (OSError, json.JSONDecodeError):
    return "", {}
  content_root = spec_paths.spec_content_root(repo)
  folder = note_path.parent.resolve()
  for key, record in products.items():
    if isinstance(record, dict) and scaffold_asset._K.SPEC_PATH in record \
        and (content_root / record[scaffold_asset._K.SPEC_PATH]).resolve() == folder:
      return key, record
  return "", {}


def _root_seed_inputs(repo: Path, note_path: Path, note_fm: dict, slug: str,
                      doc_type: str) -> tuple[str, dict, Path]:
  """
  Resolve the product in scope, the template tokens and the template file a level document is seeded from.

  Args:
    repo: Repository root the templates and declarations are resolved against.
    note_path: Absolute path of the level folder-note.
    note_fm: The level folder-note's parsed frontmatter.
    slug: The level folder-note's own filename stem.
    doc_type: The document's declared type.

  Returns:
    A `(product, tokens, template_path)` triple — the product key owning the level (empty at the
    catalog root), the substitution mapping and the chosen template file.
  """

  # Domain(spec.declarations):
  # # A level document is named by the level that owns it
  # The catalog root and each product carry their own top-level documents the same way an
  # asset does. A product's own level note sits in the product's declared folder, so the
  # product that owns it names the document, styles it through its own template layer and
  # paints it with its own declarations — exactly as the product's assets are. The catalog root
  # belongs to no product: its document takes its name from the document tree's own top-level
  # directory, and its template comes from the shared per-type set with only the project-wide
  # override layer in front of it.

  # only a product's own level note has a product to resolve; the catalog root never does
  product: str = ""
  record: dict = {}
  if note_fm.get(SpecKey.ROLE) == SpecValue.ROLE_PRODUCT:
    product, record = _product_for_note(repo, note_path)
  if product:
    label, tag = product, scaffold_asset._product_tag(record)
  else:
    # the catalog root has no product record, so the content root's own directory names it
    label = tag = spec_paths.spec_content_root(repo).name
  tokens = { "product": label, "product_tag": tag, "slug": slug,
             "category": note_fm.get(SpecKey.ROLE, "") }
  return product, tokens, scaffold_asset._resolve_template(
      repo, _ROOT_TEMPLATE_FAMILY, product or _NO_PRODUCT,
      scaffold_asset._template_name(repo, doc_type, product or None))


def main(argv: list[str]) -> int:
  """
  Run the `seed-doc` subcommand: seed one authored doc beside an existing folder-note.

  Guarantees:
    - An existing target document is never overwritten: the request is refused with a JSON
      error object and a non-zero exit status, and the existing file is never opened for
      writing.
    - A refusal at any guard — a missing folder-note, a malformed `--doc` token, an existing
      target document, or a product named alongside `--root` — writes nothing to disk.

  Args:
    argv: CLI arguments after the subcommand token — `<product> <folder-note-path> --doc
      <name>:<type> [--cwd <repo>]`, or `--root <folder-note-path> --doc <name>:<type>
      [--cwd <repo>]`.

  Returns:
    Process exit code — `0` on success.

  Raises:
    SystemExit: On any refusal — a missing folder-note, a malformed `--doc` token, an existing
      target document, or a product named alongside `--root` — carrying a JSON error object on
      stdout and a non-zero status.
  """

  # Contract:
  # A refusal at any guard — a missing folder-note, a malformed `--doc` token, an existing
  # target document, or a product named alongside `--root` — writes nothing to disk: no document
  # file, template substitution, or folder-note history entry is created before the guard that
  # refuses the request runs.

  # the CLI surface: both target spellings are optional positionals so `--root` can replace them
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature -- the positionals are optional so `--root` can replace them
  parser.add_argument(scaffold_asset._K.ARG_PRODUCT, nargs = "?", default = None,
                      help = scaffold_asset._K.HELP_PRODUCT)
  parser.add_argument(_ARG_NOTE, nargs = "?", default = None, help = _HELP_NOTE)
  parser.add_argument(_ARG_ROOT, default = None, help = _HELP_ROOT)
  parser.add_argument(scaffold_asset._K.ARG_DOC, required = True, help = _HELP_DOC)
  parser.add_argument(scaffold_asset._K.ARG_CWD, default = None, help = scaffold_asset._K.HELP_CWD)
  args = parser.parse_args(argv)

  # the two spellings name the same seed at different levels and never combine
  if args.root:
    # guard: a product alongside --root would silently pick one of two conflicting scopes
    if args.product or args.note:
      scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL, _ERR_ROOT_WITH_PRODUCT)
    product, note_rel = None, args.root
  else:
    # guard: product mode needs both positionals — argparse cannot express the pairing
    if not args.product or not args.note:
      scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL, _ERR_MODE_INCOMPLETE)
    product, note_rel = args.product, args.note

  # resolve the repo, the product record, and the note before any write
  repo = Path(args.cwd).resolve() if args.cwd else scaffold_asset._repo_root(Path.cwd())
  record = scaffold_asset._resolve_product(repo, product) if product else {}
  note_path = repo / note_rel
  # guard: the note must already exist — seeding never scaffolds a folder
  if not note_path.is_file():
    scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL,
                         f"folder-note does not exist: {note_rel}")
  name, doc_type = scaffold_asset._parse_doc_token(args.doc)
  doc_path = note_path.parent / name

  # Contract:
  # An existing target document is never overwritten: when `doc_path` already exists, `main`
  # refuses the request with a JSON error object on stdout and a non-zero exit status, and the
  # existing file on disk is never opened for writing.

  # guard: an authored doc on disk is never overwritten
  if doc_path.exists():
    scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL,
                         f"target doc already exists: {name}")

  # the note's own declarations drive the template chain, exactly as a scaffold's would
  note_text = note_path.read_text()
  note_fm, _fm_end = apply_request._parse_frontmatter(note_text)
  slug = note_path.stem
  if product:
    asset_type = note_fm.get(scaffold_asset._K.ASSET_TYPE, "") or scaffold_asset._K.DESIGN_STEM
    alias_base = scaffold_asset._alias_base(asset_type, record)
    tokens = { "product": product, "product_tag": scaffold_asset._product_tag(record),
               "slug": slug, "category": asset_type }
    tmpl_path = scaffold_asset._resolve_template(
        repo, asset_type, product,
        scaffold_asset._template_name(repo, doc_type, product), alias_base = alias_base)
  else:
    product, tokens, tmpl_path = _root_seed_inputs(repo, note_path, note_fm, slug, doc_type)
  doc_text = scaffold_asset._substitute(tmpl_path.read_text(), tokens)
  doc_text = scaffold_asset._ensure_doc_type(doc_text, doc_type)
  # the type's own paint: the icon names the kind of document, matchers own the colour later
  if (doc_paint := spec_doc_types.icon_color(repo, doc_type, product or None)):
    doc_text = scaffold_asset._inject_iconize(doc_text, doc_paint[0], doc_paint[1] or "")

  # Domain(spec.notes):
  # # A freshly seeded document inherits its asset's own request lineage
  # A document seeded beside an asset's status note did not exist when the requests that led
  # to the asset were opened, yet it still needs the same attribution those requests carry, so
  # a reviewer later dispatched against the document can resolve exactly which request or
  # requests motivated it. The seed copies the note's own recorded request lineage onto the
  # new document rather than leaving it to be rediscovered, so that attribution survives even
  # once the asset's status note itself has moved on to citing something else.

  # the seeded doc is an unwritten skeleton inheriting the note's request attribution
  _doc_fm, doc_fm_end = apply_request._parse_frontmatter(doc_text)
  fm_text = _set_stage_empty(doc_text[:doc_fm_end])
  # quoted like every other writer of the key — bare `[[...]]` parses as a nested YAML list
  fm_text = apply_request._set_fm_list(fm_text, _SOURCE_REQUESTS_KEY,
                                       [ f"\"{link}\"" for link in _note_source_requests(note_text) ])
  doc_path.write_text(fm_text + doc_text[doc_fm_end:])

  # the folder-note history records the seed, mirroring the scaffold's own journal lines
  today = _dt.datetime.now(_dt.UTC).date().isoformat()
  scaffold_asset._append_history(
      note_path, [ f"{today} — lazy-spec.seed-doc · {name} seeded ({_STAGE_KEY} empty)" ])

  # the caller folds the reported path into its commit and review dispatch
  print(json.dumps({
      "outcome": scaffold_asset._K.OUTCOME_SUCCESS,
      "doc": str(doc_path.relative_to(repo)),
  }))
  return 0
